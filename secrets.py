# Slack / Zulip / Groupe Bridge Config
# Please fill in all constants before operating

# Authentication / Authorization configuration
SLACK_BOT_ID = 'U00000000'                       # User ID of Bot
ZULIP_BOT_NAME = 'some-bot'                      # Loclapart of bot email
ZULIP_BOT_EMAIL = 'some-bot@zulipchat.com'       # Bot Email for zulip config.
ZULIP_API_KEY = '000000000000000000'
ZULIP_URL = 'https://andrew.zulipchat.com'
SLACK_TOKEN = 'xoxb-000000000000000000000000000'

# Slack Destination ID for Slack for bot error logs
SLACK_ERR_CHANNEL = 'U00000000'

# List of topics / slack channels to relay publicly.  They must be identically named on slack and zulip.
# Bot must be added to these slack channels.
PUBLIC_TWO_WAY = ['social']
PUBLIC_TWO_WAY_STREAM = 'abtech'  # Zulip stream for public two-way communications

# Configuration for zulip-side logging streams
ZULIP_LOG_PUBLIC_STREAM = 'slack'           # Public logging zulip stream
ZULIP_LOG_PRIVATE_STREAM = 'slack-private'  # Private logging zulip stream

# Redis configuration
REDIS_HOSTNAME = '127.0.0.1'
REDIS_PORT = 6379
REDIS_PASSWORD = ''
SLACK_EDIT_UPDATE_ZULIP_TTL = 60*60
REDIS_PREFIX = 'zulip.slack'

# Groupme configuration.  If not using Groupme, just set GROUPME_ENABLE to False.
GROUPME_ENABLE = False
SSL_CERT_CHAIN_PATH = ''
SSL_CERT_KEY_PATH = ''
GROUPME_TWO_WAY = {
    'channel-name': {
        'BOT_ID': '123456789123456789',
        'BOT_PORT': 1234,
        'BOT_NAME': 'mybot'
    }
}
