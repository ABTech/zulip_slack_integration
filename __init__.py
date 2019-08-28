import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
import re
import requests
import ssl
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
                     REDIS_PREFIX, SLACK_ERR_CHANNEL, GROUPME_TWO_WAY,
                     GROUPME_ENABLE, SSL_CERT_CHAIN_PATH, SSL_CERT_KEY_PATH,
                     ZULIP_PRIVATE_STREAM)

REDIS_USERS = REDIS_PREFIX + ':users:'
REDIS_BOTS = REDIS_PREFIX + ':bots:'
REDIS_CHANNELS = REDIS_PREFIX + ':channels:'
REDIS_CHANNELS_BY_NAME = REDIS_PREFIX + ':channelsByName:'
REDIS_MSG_SLACK_TO_ZULIP = {
    ZULIP_STREAM: REDIS_PREFIX + ':msg.slack.to.zulip:',
    ZULIP_PUBLIC: REDIS_PREFIX + ':msg.slack.to.zulip.pub:'
}

GROUP_UPDATES = ['channel_archive', 'channel_join', 'channel_leave',
                 'channel_name', 'channel_purpose', 'channel_topic',
                 'channel_unarchive', 'file_comment', 'file_mention',
                 'group_archive', 'group_join', 'group_leave', 'group_name',
                 'group_purpose', 'group_topic', 'group_unarchive',
                 'pinned_item', 'unpinned_item']

LOGLEVEL = os.environ.get('LOGLEVEL', 'INFO').upper()
logging.basicConfig(level=LOGLEVEL)

_LOGGER = logging.getLogger(__name__)

context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain(SSL_CERT_CHAIN_PATH, SSL_CERT_KEY_PATH)

class SlackHandler(logging.StreamHandler):
    def __init__(self, web_client, event_loop, channel_id):
        super().__init__(self)
        self.web_client = web_client
        self.event_loop = event_loop
        self.channel_id = channel_id

    def emit(self, record):
        try:
            msg = self.format(record)
            asyncio.ensure_future(self.web_client.chat_postMessage(
                channel=self.channel_id,
                text="Oopsie! " + msg,
                mrkdwn=False
            ), loop=self.event_loop)
        except Exception as e:
            print('could not post err to slack %s', repr(e))

# https://stackoverflow.com/a/21631948
def make_groupme_handler(channel, conf, send):
    class CustomGroupMeHandler(BaseHTTPRequestHandler):
        def _set_headers(self):
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()

        def do_POST(self):
            try:
                content_length = int(self.headers['Content-Length'])
                post_data = json.loads(self.rfile.read(content_length))
                send(channel, conf, post_data)
                self._set_headers()
            except:
                e = sys.exc_info()
                exc_type, exc_value, exc_traceback = e
                _LOGGER.error('Error do post groupme message: %s',
                              repr(traceback.format_exception(exc_type,
                                                              exc_value,
                                                              exc_traceback)))
    return CustomGroupMeHandler

class SlackBridge():
    def __init__(self):
        _LOGGER.debug('new SlackBridge instance')

        slack_user_match = re.compile("<@[A-Z0-9]+>")
        slack_notif_match = re.compile("<![a-zA-Z0-9]+>")
        slack_channel_match = re.compile("<#[a-zA-Z0-9]+\\|[a-zA-Z0-9]+>")

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

        if GROUPME_ENABLE:
            _LOGGER.debug('connecting to groupmes')
            self.groupme_threads = {}
            for channel, conf in GROUPME_TWO_WAY.items():
                self.groupme_threads[channel] = threading.Thread(
                    target=self.run_groupme_listener, args=(channel, conf))
                self.groupme_threads[channel].setDaemon(True)
                self.groupme_threads[channel].start()

        @slack.RTMClient.run_on(event='message')
        async def receive_slack_msg(**payload):
            _LOGGER.debug('caught slack message')
            try:
                data = payload['data']
                web_client = payload['web_client']
                rtm_client = payload['rtm_client']
                bot = False
                edit = False
                delete = False
                me = False
                if 'subtype' in data and data['subtype'] == 'bot_message':
                    bot_id = data['bot_id']
                    user_id = await self.get_slack_bot(bot_id,
                                                       web_client=web_client)
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
                user = await self.get_slack_user(user_id,
                                                 web_client=web_client)
                if not user:
                    return
                channel = await self.get_slack_channel(channel_id,
                                                       web_client=web_client)
                if not channel:
                    return
                at_shift = 0
                for m in slack_user_match.finditer(data['text']):
                    match = m.group()
                    at_user_id = match[2:-1]
                    try:
                        at_user = await self.get_slack_user(at_user_id,
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

                if (channel['type'] == 'channel' or
                        channel['type'] == 'private-channel'):
                    msg = data['text']
                    channel_name = channel['name']
                    private = (channel['type'] == 'private-channel')
                    if ('subtype' in data and
                            data['subtype'] in GROUP_UPDATES):
                        msg_id = None
                        user = None
                    elif ('subtype' in data and
                          data['subtype'] == 'me_message'):
                        msg_id = None
                        me = True
                        if 'edited' in data:
                            edit = True
                    elif 'client_msg_id' in data:
                        msg_id = data['client_msg_id']
                    elif 'bot_id' in data:
                        msg_id = None
                    else:
                        msg_id = None
                        _LOGGER.warning("no msg id for user %s: %s",
                                        user, trace)
            #        if 'files' in data:
            #            for file in data['files']:
            #                web_client.files_sharedPublicURL(id=file['id'])
            #                if msg == '':
            #                    msg = file['permalink_public']
            #                else:
            #                    msg += '\n' + file['permalink_public']
                    if channel_name in PUBLIC_TWO_WAY:
                        self.send_to_zulip(channel_name, msg, user=user,
                                           send_public=True, slack_id=msg_id,
                                           edit=edit, delete=delete, me=me)
                    self.send_to_zulip(channel_name, msg, user=user,
                                       slack_id=msg_id, edit=edit,
                                       delete=delete, me=me, private=private)
                    self.send_to_groupme(channel_name, msg, user=user,
                                         edit=edit, delete=delete, me=me)
                elif channel['type'] == 'im':
                    _LOGGER.debug('updating user display name')
                    user = await self.get_slack_user(user_id,
                                                     web_client=web_client,
                                                     force_update=True)
                    await self.slack_web_client.chat_postMessage(
                        channel=channel_id,
                        text="OK, I have updated your display name for Slack \
messgaes on Zulip. Your name is now seen as: *" + user + "*.",
                        mrkdwn=True
                    )
                elif channel['type'] == 'group':
                    await self.slack_web_client.chat_postMessage(
                        channel=channel_id,
                        text="I'm not sure what I'm doing here, so I'll just \
be annoying.",
                        mrkdwn=True
                    )
            except:
                e = sys.exc_info()
                exc_type, exc_value, exc_traceback = e
                _LOGGER.error('Error receive slack message: %s, %s',
                              repr(traceback.format_exception(exc_type,
                                                              exc_value,
                                                              exc_traceback)),
                              data)


        _LOGGER.debug('connecting to slack')
        self.slack_loop = asyncio.new_event_loop()
        self.slack_rtm_client = slack.RTMClient(token=SLACK_TOKEN,
                                                run_async=True,
                                                loop=self.slack_loop)
        self.slack_web_client = slack.WebClient(token=SLACK_TOKEN,
                                                run_async=True,
                                                loop=self.slack_loop)
        self.slack_log_format = '%(asctime)s %(name)-12s %(levelname)-8s %(message)s'
        self.slack_log_formatter = logging.Formatter(self.slack_log_format)
        self.slack_logger = SlackHandler(self.slack_web_client,
                                         self.slack_loop,
                                         SLACK_ERR_CHANNEL)
        self.slack_logger.setLevel(logging.INFO)
        self.slack_logger.setFormatter(self.slack_log_formatter)
        logging.getLogger('').addHandler(self.slack_logger)
        self.slack_loop.run_until_complete(self.slack_rtm_client.start())

    def send_from_zulip(self, msg):
        _LOGGER.debug('caught zulip message')
        try:
            if (msg['subject'] in PUBLIC_TWO_WAY and
                    msg['sender_short_name'] != ZULIP_BOT_NAME):
                _LOGGER.debug('good to send zulip message to slack')
                asyncio.ensure_future(
                    self.slack_web_client.chat_postMessage(
                        channel=msg['subject'],
                        text=('*' + msg['sender_full_name'] + "*: " +
                              msg['content']),
                        mrkdwn=True
                        # thread_ts=thread_ts
                    ), loop=self.slack_loop)
                self.send_to_groupme(msg['subject'], msg['content'],
                                     user=msg['sender_full_name'])
        except:
            e = sys.exc_info()
            exc_type, exc_value, exc_traceback = e
            _LOGGER.error('Error send slack message: %s',
                          repr(traceback.format_exception(exc_type,
                                                          exc_value,
                                                          exc_traceback)))

    def run_zulip_listener(self):
        self.zulip_client.call_on_each_message(self.send_from_zulip)

#    def run_zulip_ev(self):
#        self.zulip_client.call_on_each_event(lambda event: sys.stdout.write(str(event) + "\n"))

    def send_from_groupme(self, channel, conf, post_data):
        if post_data['name'] != conf['BOT_NAME']:
            _LOGGER.debug('good to send groupme message to slack')
            message_text = post_data['text']
            user = f"{post_data['name']} [GroupMe]"

            for attachment in post_data['attachments']:
                # Add link to image to message text
                if attachment['type'] == 'image':
                    caption = message_text if message_text else 'image'
                    message_text = '[%s](%s)\n' % (caption,
                                                   attachment['url'])
                    break

            slack_text = f"*{user}*: {message_text}"
            asyncio.ensure_future(
                self.slack_web_client.chat_postMessage(
                    channel=channel,
                    text=slack_text,
                    mrkdwn=True
                    # thread_ts=thread_ts
                ), loop=self.slack_loop)
            if channel in PUBLIC_TWO_WAY:
                self.send_to_zulip(channel, message_text, user=user,
                                   send_public=True)
            channel_id = self.get_slack_channel_by_name(channel)
            if channel_id is not None:
                channel_type = get_slack_channel(channel_id)['type']
                private = (channel_type == 'private-channel')
                self.send_to_zulip(channel, message_text, user=user,
                                   private=private)

    def run_groupme_listener(self, channel, conf):
        server_address = ('', conf['BOT_PORT'])
        HandlerClass = make_groupme_handler(channel, conf,
                                            self.send_from_groupme)
        httpd = ThreadingHTTPServer(server_address, HandlerClass)
        _LOGGER.debug('listening http for groupme bot: %s', channel)
        httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
        httpd.serve_forever()

    async def new_slack_user(self, user_id, user, web_client=None):
        if web_client is None:
            web_client = self.slack_web_client
        res = await web_client.im_open(user=user_id)
        if not res['ok']:
            _LOGGER.error('could not user im %s, %s', user_id, repr(res))
            return
        channel = res['channel']['id']
        await web_client.chat_postMessage(
            channel=channel,
            text="Hi " + user + ", welcome to the AB Tech Slack!",
            mrkdwn=True
        )
        await web_client.chat_postMessage(
            channel=channel,
            text="My job here is to forward messages to and from Zulip. Your \
name is now seen on Zulip as: *" + user + "*. If you update your name on \
Slack, respond here with _literally anything_ at any time and I'll update \
my records to use your new name when I forward messages to Zulip for you.",
            mrkdwn=True
        )

    async def get_slack_bot(self, bot_id, web_client=None, force_update=False):
        redis_key = REDIS_BOTS + bot_id
        ret_bot = self.redis.get(redis_key)
        if ret_bot is None or force_update:
            _LOGGER.debug('fetching slack bot')
            if web_client is None:
                web_client = self.slack_web_client
            res = await web_client.bots_info(bot=bot_id)
            if not res['ok']:
                _LOGGER.error('could not fetch bot %s, %s', bot_id, repr(res))
                return False
            bot = res['bot']
            ret_bot = bot['user_id']
            self.redis.set(redis_key, ret_bot)
        return ret_bot

    async def get_slack_user(self, user_id, web_client=None,
                             force_update=False):
        redis_key = REDIS_USERS + user_id
        ret_user = self.redis.get(redis_key)
        if ret_user is None or force_update:
            _LOGGER.debug('fetching slack user')
            if web_client is None:
                web_client = self.slack_web_client
            res = await web_client.users_info(user=user_id)
            if not res['ok']:
                _LOGGER.error('could not fetch user %s, %s', user_id,
                              repr(res))
                return False
            user = res['user']
            if user['profile']['display_name'] == '':
                ret_user = user['name']
            else:
                ret_user = user['profile']['display_name']
            self.redis.set(redis_key, ret_user)
            if not force_update:
                await self.new_slack_user(user_id, ret_user,
                                          web_client=web_client)
        return ret_user

    async def get_slack_channel(self, channel_id, web_client=None,
                                force_update=False):
        redis_key = REDIS_CHANNELS + channel_id
        ret_channel = self.redis.hgetall(redis_key)
        if ret_channel is None or not ret_channel or force_update:
            _LOGGER.debug('fetching slack channel')
            if web_client is None:
                web_client = self.slack_web_client
            res = await web_client.conversations_info(channel=channel_id)
            if not res['ok']:
                _LOGGER.error('could not fetch channel %s, %s', channel_id,
                              repr(res))
                return False
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
            elif ('is_group' in channel and channel['is_group'] and
                  'is_mpim' in channel and not channel['is_mpim']):
                ret_channel = {
                    'type': 'private-channel',
                    'name': channel['name']
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
            redis_key_by_name = REDIS_CHANNELS_BY_NAME + channel['name']
            self.redis.set(redis_key_by_name, channel_id)
        return ret_channel

    async def get_slack_channel_by_name(self, channel_name):
        redis_key = REDIS_CHANNELS_BY_NAME + channel_name
        ret_channel_id = self.redis.get(redis_key)
        if ret_channel_id is None:
            _LOGGER.warning('cannot get slack channel by name yet: %s',
                            channel_name)
        return ret_channel_id

    # originally from https://github.com/ABTech/zulip_groupme_integration/blob/7674a3595282ce154cd24b1903a44873d729e0cc/server.py
    def send_to_zulip(self, subject, msg, user=None, slack_id=None,
                      send_public=False, edit=False, delete=False, me=False,
                      private=False):
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
            user_prefix = ''
            if user is not None and not me:
                user_prefix = '**' + user + '**: '
            elif user is not None and me:
                user_prefix = '**' + user + '** '
            to = ZULIP_STREAM
            if send_public:
                to = ZULIP_PUBLIC
            elif private:
                to = ZULIP_PRIVATE_STREAM
            if edit and slack_id:
                redis_key = REDIS_MSG_SLACK_TO_ZULIP[to] + slack_id
                zulip_id = self.redis.get(redis_key)
                if zulip_id is not None:
                    sent = self.zulip_client.update_message({
                        'message_id': int(zulip_id),
                        "content": user_prefix + msg
                    })
                elif not send_public:
                    sent = self.zulip_client.send_message({
                        "type": 'stream',
                        "to": to,
                        "subject": subject,
                        "content": user_prefix + msg + ' *(edited)*'
                    })
            elif edit and not slack_id and send_public:
                # don't publish me_message edits publically
                pass
            elif edit and not slack_id and not send_public:
                sent = self.zulip_client.send_message({
                    "type": 'stream',
                    "to": to,
                    "subject": subject,
                    "content": user_prefix + msg + ' *(edited)*'
                })
            elif delete and slack_id:
                redis_key = REDIS_MSG_SLACK_TO_ZULIP[to] + slack_id
                zulip_id = self.redis.get(redis_key)
                if zulip_id is not None and send_public:
                    sent = self.zulip_client.delete_message(int(zulip_id))
                elif zulip_id is not None and not send_public:
                    sent = self.zulip_client.update_message({
                        'message_id': int(zulip_id),
                        "content": user_prefix + msg + ' *(deleted)*'
                    })
                elif not send_public:
                    sent = self.zulip_client.send_message({
                        "type": 'stream',
                        "to": to,
                        "subject": subject,
                        "content": user_prefix + msg + ' *(deleted)*'
                    })
            else:
                sent = self.zulip_client.send_message({
                    "type": 'stream',
                    "to": to,
                    "subject": subject,
                    "content": user_prefix + msg

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

    def send_to_groupme(self, subject, msg, user=None, edit=False,
                        delete=False, me=False):
        try:
            # Check for image
        #    for attachment in msg['attachments']:
        #        # Add link to image to message text
        #        if attachment['type'] == 'image':
        #            caption = message_text if message_text else 'image'
        #            message_text = '[%s](%s)\n' % (caption, attachment['url'])
        #            break

            if subject not in GROUPME_TWO_WAY:
                return
            elif edit or delete:
                return
            _LOGGER.debug('sending to groupme')

            sent = dict()
            user_prefix = ''
            if user is not None and not me:
                user_prefix = user + ': '
            elif user is not None and me:
                user_prefix = user + ' '

            to = GROUPME_TWO_WAY[subject]
            send_data = {
                'bot_id': to['BOT_ID'],
                'text': user_prefix + msg
            }

            requests.post("https://api.groupme.com/v3/bots/post",
                          data=send_data)

            # if 'result' not in sent or sent['result'] != 'success':
            #     _LOGGER.error('Could not send zulip message %s', sent)
            #     return
        except:
            e = sys.exc_info()
            exc_type, exc_value, exc_traceback = e
            _LOGGER.error('Error send groupme message: %s',
                          repr(traceback.format_exception(exc_type,
                                                          exc_value,
                                                          exc_traceback)))

slack_bridge = SlackBridge()
