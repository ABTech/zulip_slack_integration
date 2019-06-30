import logging
import os
import re
import sys
import threading
import traceback

import redis
import slack
import zulip

from secrets import (PUBLIC_TWO_WAY, ZULIP_BOT_NAME, ZULIP_BOT_EMAIL,
                      ZULIP_API_KEY, ZULIP_URL, ZULIP_STREAM, ZULIP_PUBLIC,
                      SLACK_BOT_ID, SLACK_TOKEN, REDIS_HOSTNAME, REDIS_PORT,
                      REDIS_PASSWORD, SLACK_EDIT_UPDATE_ZULIP_TTL,
                      REDIS_PREFIX)

REDIS_USERS = REDIS_PREFIX + ':users:'
REDIS_BOTS = REDIS_PREFIX + ':bots:'
REDIS_CHANNELS = REDIS_PREFIX + ':channels:'
REDIS_MSG_SLACK_TO_ZULIP = {
    ZULIP_STREAM: REDIS_PREFIX + ':msg.slack.to.zulip:',
    ZULIP_PUBLIC: REDIS_PREFIX + ':msg.slack.to.zulip.pub:'
}

LOGLEVEL = os.environ.get('LOGLEVEL', 'INFO').upper()
logging.basicConfig(level=LOGLEVEL)

_LOGGER = logging.getLogger(__name__)

class ZulipSlack():
    def __init__(self):
        _LOGGER.debug('new ZulipSlack instance')

        slack_user_match = re.compile("<@[A-Z0-9]+>")
        slack_notif_match = re.compile("<![a-zA-Z0-9]+>")
        slack_channel_match = re.compile("<#[a-zA-Z0-9]+\|[a-zA-Z0-9]+>")

        _LOGGER.debug('connecting to redis')
        self.redis = redis.Redis(
            host=REDIS_HOSTNAME,
            port=REDIS_PORT,
            password=REDIS_PASSWORD,
            charset="utf-8",
            decode_responses=True)

        _LOGGER.debug('connecting to zulip')
        self.zulip_client = zulip.Client(email=ZULIP_BOT_EMAIL,
                                         api_key=ZULIP_API_KEY,
                                         site=ZULIP_URL)
        self.zulip_thread = threading.Thread(target=self.run_zulip_listener)
        self.zulip_thread.setDaemon(True)
        self.zulip_thread.start()
#        self.zulip_ev_thread = threading.Thread(target=self.run_zulip_ev)
#        self.zulip_ev_thread.setDaemon(True)
#        self.zulip_ev_thread.start()

        @slack.RTMClient.run_on(event='message')
        def receive_slack_msg(**payload):
            _LOGGER.debug('caught slack message')
            try:
                data = payload['data']
                web_client = payload['web_client']
                rtm_client = payload['rtm_client']
                bot = False
                edit = False
                delete = False
                hide_public = False
                if 'subtype' in data and data['subtype'] == 'bot_message':
                    bot_id = data['bot_id']
                    user_id = self.get_slack_bot(bot_id, web_client=web_client)
                    if not user_id:
                        return
                    if user_id == SLACK_BOT_ID:
                        _LOGGER.debug("oops that's my message!")
                        return
                    bot = True
                elif ('subtype' in data and
                      data['subtype'] == 'message_changed'):
                    data.update(data['message'])
                    edit = True
                elif ('subtype' in data and
                      data['subtype'] == 'message_deleted'):
                    data.update(data['previous_message'])
                    delete = True
                if ('subtype' in data and
                    data['subtype'] == 'message_replied'):
                    return
                if not bot:
                    user_id = data['user']
                channel_id = data['channel']
                thread_ts = data['ts']
                user = self.get_slack_user(user_id, web_client=web_client)
                if not user:
                    return
                channel = self.get_slack_channel(channel_id,
                                                 web_client=web_client)
                if not channel:
                    return
                at_shift = 0
                for m in slack_user_match.finditer(data['text']):
                    match = m.group()
                    at_user_id = match[2:-1]
                    try:
                        at_user = self.get_slack_user(at_user_id,
                                                      web_client=web_client)
                        if at_user:
                            old_text = data['text']
                            start = m.start() + at_shift
                            data['text'] = old_text[:start]
                            data['text'] += '**@' + at_user + '**'
                            data['text'] += old_text[start + len(match):]
                            at_shift = len(data['text']) - len(old_text)
                        else:
                            _LOGGER.info("couldn't find get @ user %s:",
                                        at_user_id)
                    except:
                        e = sys.exc_info()
                        exc_type, exc_value, exc_traceback = e
                        trace = repr(traceback.format_exception(exc_type,
                                                                exc_value,
                                                                exc_traceback))
                        _LOGGER.warning("couldn't find get @ user %s: %s",
                                        at_user_id, trace)
                notif_shift = 0
                for m in slack_notif_match.finditer(data['text']):
                    match = m.group()
                    notif = match[2:-1]
                    old_text = data['text']
                    start = m.start() + notif_shift
                    data['text'] = old_text[:start]
                    data['text'] += '**@' + notif + '**'
                    data['text'] += old_text[start + len(match):]
                    notif_shift = len(data['text']) - len(old_text)
                channel_shift = 0
                for m in slack_channel_match.finditer(data['text']):
                    match = m.group()
                    ref_channel = (match[2:-1].split('|'))[1]
                    old_text = data['text']
                    start = m.start() + channel_shift
                    data['text'] = old_text[:start]
                    data['text'] += '**#' + ref_channel + '**'
                    data['text'] += old_text[start + len(match):]
                    channel_shift = len(data['text']) - len(old_text)
                if channel['type'] == 'channel':
                    msg = data['text']
                    channel_name = channel['name']
                    msg_id = data['client_msg_id']
            #        if 'files' in data:
            #            for file in data['files']:
            #                web_client.files_sharedPublicURL(id=file['id'])
            #                if msg == '':
            #                    msg = file['permalink_public']
            #                else:
            #                    msg += '\n' + file['permalink_public']
                    if channel_name in PUBLIC_TWO_WAY and not hide_public:
                        self.send_to_zulip(channel_name, user, msg,
                                           send_public=True, slack_id=msg_id,
                                           edit=edit, delete=delete)
                    self.send_to_zulip(channel_name, user, msg,
                                       slack_id=msg_id, edit=edit,
                                       delete=delete)
                elif channel['type'] == 'im':
                    _LOGGER.debug('updating user display name')
                    user = self.get_slack_user(user_id, web_client=web_client,
                                               force_update=True)
                    self.slack_web_client.chat_postMessage(
                        channel=channel_id,
                        text="OK, I have updated your display name for Slack \
messgaes on Zulip. Your name is now seen as: *" + user + "*.",
                        mrkdwn=True
                    )
                elif channel['type'] == 'group':
                    self.slack_web_client.chat_postMessage(
                        channel=channel_id,
                        text="I'm not sure what I'm doing here, so I'll just \
be annoying.",
                        mrkdwn=True
                    )
            except:
                e = sys.exc_info()
                exc_type, exc_value, exc_traceback = e
                _LOGGER.error('Error receive slack message: %s',
                              repr(traceback.format_exception(exc_type,
                                                              exc_value,
                                                              exc_traceback)))

        _LOGGER.debug('connecting to slack')
        self.slack_rtm_client = slack.RTMClient(token=SLACK_TOKEN)
        self.slack_web_client = slack.WebClient(token=SLACK_TOKEN)
        self.slack_rtm_client.start()

    def send_to_slack(self, msg):
        _LOGGER.debug('caught zulip message')
        try:
            if (msg['subject'] in PUBLIC_TWO_WAY and
                msg['sender_short_name'] != ZULIP_BOT_NAME):
                _LOGGER.debug('good to send zulip message to slack')
                self.slack_web_client.chat_postMessage(
                    channel=msg['subject'],
                    text=('*' + msg['sender_full_name'] + "*: " +
                          msg['content']),
                    mrkdwn=True
        #            thread_ts=thread_ts
                )
        except:
                e = sys.exc_info()
                exc_type, exc_value, exc_traceback = e
                _LOGGER.error('Error send slack message: %s',
                              repr(traceback.format_exception(exc_type,
                                                              exc_value,
                                                              exc_traceback)))

    def run_zulip_listener(self):
        self.zulip_client.call_on_each_message(self.send_to_slack)

#    def run_zulip_ev(self):
#        self.zulip_client.call_on_each_event(lambda event: sys.stdout.write(str(event) + "\n"))

    def get_slack_bot(self, bot_id, web_client=None, force_update=False):
        redis_key = REDIS_BOTS + bot_id
        ret_bot = self.redis.get(redis_key)
        if ret_bot is None or force_update:
            _LOGGER.debug('fetching slack bot')
            if web_client is None:
                web_client = self.slack_web_client
            res = web_client.bots_info(bot=bot_id)
            if not res['ok']:
                _LOGGER.error('could not fetch bot %s, %s', bot_id, repr(res))
                return False
            else:
                bot = res['bot']
                ret_bot = bot['user_id']
                self.redis.set(redis_key, ret_bot)
        return ret_bot

    def get_slack_user(self, user_id, web_client=None, force_update=False):
        redis_key = REDIS_USERS + user_id
        ret_user = self.redis.get(redis_key)
        if ret_user is None or force_update:
            _LOGGER.debug('fetching slack user')
            if web_client is None:
                web_client = self.slack_web_client
            res = web_client.users_info(user=user_id)
            if not res['ok']:
                _LOGGER.error('could not fetch user %s, %s', user_id,
                              repr(res))
                return False
            else:
                user = res['user']
                if user['profile']['display_name'] == '':
                    ret_user = user['name']
                else:
                    ret_user = user['profile']['display_name']
                self.redis.set(redis_key, ret_user)
        return ret_user

    def get_slack_channel(self, channel_id, web_client=None,
                          force_update=False):
        redis_key = REDIS_CHANNELS + channel_id
        ret_channel = self.redis.hgetall(redis_key)
        if ret_channel is None or not ret_channel or force_update:
            _LOGGER.debug('fetching slack channel')
            if web_client is None:
                web_client = self.slack_web_client
            res = web_client.conversations_info(channel=channel_id)
            if not res['ok']:
                _LOGGER.error('could not fetch channel %s, %s', channel_id,
                              repr(res))
                return False
            else:
                channel = res['channel']
                if 'is_channel' in channel and channel['is_channel']:
                    _LOGGER.debug('found channel %s', channel_id)
                    ret_channel = {
                        'type': 'channel',
                        'name': channel['name']
                    }
                elif 'is_im' in channel and channel['is_im']:
                    ret_channel = {
                        'type': 'im',
                        'user_id': channel['user']
                    }
                elif 'is_group' in channel and channel['is_group']:
                    ret_channel = {
                        'type': 'group',
                        'name': channel['name']
                    }
                else:
                    _LOGGER.warning('not a channel, im, or group for %s',
                                    channel_id)
                    return False
                self.redis.hmset(redis_key, ret_channel)
        return ret_channel

    # originally from https://github.com/ABTech/zulip_groupme_integration/blob/7674a3595282ce154cd24b1903a44873d729e0cc/server.py
    def send_to_zulip(self, subject, user, msg, slack_id=None,
                      send_public=False, edit=False, delete=False):
        _LOGGER.debug('sending to zulip, public: %s', str(send_public))
        try:
            # Check for image
        #    for attachment in msg['attachments']:
        #        # Add link to image to message text
        #        if attachment['type'] == 'image':
        #            caption = message_text if message_text else 'image'
        #            message_text = '[%s](%s)\n' % (caption, attachment['url'])
        #            break

            sent = dict()
            zulip_id = None
            to = ZULIP_STREAM
            if send_public:
                to = ZULIP_PUBLIC
            if edit and slack_id:
                redis_key = REDIS_MSG_SLACK_TO_ZULIP[to] + slack_id
                zulip_id = self.redis.get(redis_key)
                if zulip_id is not None:
                    sent = self.zulip_client.update_message({
                        'message_id': int(zulip_id),
                        "content": '**' + user + '**: ' + msg
                    })
                elif not send_public:
                    sent = self.zulip_client.send_message({
                        "type": 'stream',
                        "to": to,
                        "subject": subject,
                        "content": '**' + user + '**: ' + msg + ' *(edited)*'
                    })
            elif delete and slack_id:
                redis_key = REDIS_MSG_SLACK_TO_ZULIP[to] + slack_id
                zulip_id = self.redis.get(redis_key)
                if zulip_id is not None and send_public:
                    sent = self.zulip_client.delete_message(int(zulip_id))
                elif zulip_id is not None and not send_public:
                    sent = self.zulip_client.update_message({
                        'message_id': int(zulip_id),
                        "content": '**' + user + '**: ' + msg + ' *(deleted)*'
                    })
                elif not send_public:
                    sent = self.zulip_client.send_message({
                        "type": 'stream',
                        "to": to,
                        "subject": subject,
                        "content": '**' + user + '**: ' + msg + ' *(deleted)*'
                    })
            else:
                sent = self.zulip_client.send_message({
                    "type": 'stream',
                    "to": to,
                    "subject": subject,
                    "content": '**' + user + '**: ' + msg

                })
            if 'result' not in sent or sent['result'] != 'success':
                _LOGGER.error('Could not send zulip message %s', sent)
                return
            if slack_id is not None and not delete:
                if edit and zulip_id is not None:
                    sent['id'] = zulip_id
                elif edit:
                    return
                redis_key = REDIS_MSG_SLACK_TO_ZULIP[to] + slack_id
                self.redis.set(redis_key, sent['id'],
                               ex=SLACK_EDIT_UPDATE_ZULIP_TTL)
        except:
                e = sys.exc_info()
                exc_type, exc_value, exc_traceback = e
                _LOGGER.error('Error send zulip message: %s',
                              repr(traceback.format_exception(exc_type,
                                                              exc_value,
                                                              exc_traceback)))

zulip_slack = ZulipSlack()
