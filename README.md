# Zulip / Slack / Groupe Bridge Bot

## Features

- Relays two-way between Zulip, Groupme, and Slack.
- Logs all public relayed traffic to a single Zulip stream.
- Logs private relayed traffic to a dedicated Zulip stream.

## Installation

1. Install redis.  A simple way to do this if you have docker installed is:

```
docker run -d --rm -p 6379:6379 --name redis_master redis:5.0
```

2. Create a slack bot account with bot user, add that bot to the appropriate channel on a slack.
3. Create a zulip bot account on the zulip instance you intend to run.
4. If you are using groupme, get a groupe bot account.
5. Edit `secrets.py` to configure the auth credentials for the above.
6. Configure stream/channel/topic names into `PUBLIC_TWO_WAY`, `PUBLIC_TWO_WAY_STREAM`, `ZULIP_LOG_PUBLIC_STREAM`, `ZULIP_LOG_PRIVATE_STREAM`.
7. If using groupme, set `GROUPME_ENABLE` and the cert chain paths.
