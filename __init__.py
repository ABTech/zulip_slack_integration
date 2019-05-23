import os
import slack
import zulip
import threading
import .secrets

slack_users = dict()
slack_channels = dict()

def send_to_slack(msg):
    if msg['subject'] in secrets.PUBLIC_TWO_WAY and msg['sender_short_name'] != secrets.ZULIP_BOT_NAME:
        web_client.chat_postMessage(
            channel=msg['subject'],
            text='**' + msg['sender_full_name'] + "**: " + msg['content']
#            thread_ts=thread_ts
        )

def run_zulip_listener():
    client.call_on_each_message(send_to_slack)

client = zulip.Client(email=ZULIP_BOT_EMAIL, api_key=secrets.ZULIP_API_KEY, site=secrets.ZULIP_URL)
t = threading.Thread(target=run_zulip_listener)
t.setDaemon(True)
t.start()

def get_slack_users(web_client):
    res = web_client.users_list()
    if not res['ok']:
        print('could not get users')
    else:
        for user in res['members']:
            if user['profile']['display_name'] == '':
                slack_users[user['id']] = user['name']
            else:
                slack_users[user['id']] = user['profile']['display_name']

def get_slack_channels(web_client):
    res = web_client.conversations_list()
    if not res['ok']:
        print('could not get channels')
    else:
        for channel in res['channels']:
            slack_channels[channel['id']] = channel['name']

# originally from https://github.com/ABTech/zulip_groupme_integration/blob/7674a3595282ce154cd24b1903a44873d729e0cc/server.py
def send_to_zulip(subject, user, msg, send_public=False):
    # Check for image
#    for attachment in msg['attachments']:
#        # Add link to image to message text
#        if attachment['type'] == 'image':
#            caption = message_text if message_text else 'image'
#            message_text = '[%s](%s)\n' % (caption, attachment['url'])
#            break

    to = secrets.ZULIP_STREAM
    if send_public:
        to = secrets.ZULIP_PUBLIC
    client.send_message({
        "type": 'stream',
        "to": to,
        "subject": subject,
        "content": '**' + user + '**: ' + msg

    })
            
@slack.RTMClient.run_on(event='message')
def receive_slack_msg(**payload):
    data = payload['data']
    web_client = payload['web_client']
    rtm_client = payload['rtm_client']
#    print(data)
    user_id = data['user']
    channel_id = data['channel']
    thread_ts = data['ts']
    if user_id not in slack_users:
        get_slack_users(web_client)
    if channel_id not in slack_channels:
        get_slack_channels(web_client)
    channel = slack_channels[channel_id]
    user = slack_users[user_id]
    msg = data['text']
    if (user_id != secrets.SLACK_BOT_ID):
#        if 'files' in data:
#            for file in data['files']:
#                web_client.files_sharedPublicURL(id=file['id'])
#                if msg == '':
#                    msg = file['permalink_public']
#                else:
#                    msg += '\n' + file['permalink_public']
        if channel == secrets.ZULIP_PUBLIC:
            send_to_zulip(channel, user, msg, send_public=True)
        else:
            send_to_zulip(channel, user, msg)


#slack_token = os.environ["SLACK_API_TOKEN"]
rtm_client = slack.RTMClient(token=secrets.SLACK_TOKEN)
web_client = slack.WebClient(token=secrets.SLACK_TOKEN)
rtm_client.start()
