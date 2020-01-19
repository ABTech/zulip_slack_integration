# Module to consolidate logic around reformatting messages that originate on
# slack before they are forwarded.

import logging
import re
import sys
import traceback

_LOGGER = logging.getLogger(__name__)

# These are module-private regular expressions used by the reformatter
_SLACK_USER_MATCH = re.compile("<@[A-Z0-9]+>")
_SLACK_NOTIF_MATCH = re.compile("<![a-zA-Z0-9]+>")
_SLACK_CHANNEL_MATCH = re.compile("<#[a-zA-Z0-9]+\\|[a-zA-Z0-9]+>")
_SLACK_LINK_BARE_URL_MATCH = re.compile("<([a-zA-Z0-9]+:[^|]+)\\|\\1>")
_SLACK_LINK_MATCH = re.compile("<([a-zA-Z0-9]+:[^|]+)\\|([^>]+)>")

class SlackUserFormatter:
    def __init__(self, user_lookup_function, log_on_error=True):
        ''' Constructor.  user_lookup_function should return a couroutine that resolves to
            the display name of the passed in user identifier. It may throw an exception on failure.'''
        self._get_slack_user = user_lookup_function
        self._log_on_error = log_on_error

    async def format_user(self, input_text):
        ''' Handles reformatting of slack markdown user references in a string of text. '''
        at_shift = 0
        for m in _SLACK_USER_MATCH.finditer(input_text):
            match = m.group()
            at_user_id = match[2:-1]
            try:
                at_user = await self._get_slack_user(at_user_id)

                if at_user:
                    old_text = input_text
                    start = m.start() + at_shift
                    input_text = old_text[:start]
                    input_text += '**@' + at_user + '**'
                    input_text += old_text[start + len(match):]
                    at_shift = len(input_text) - len(old_text) + at_shift
                else:
                    _LOGGER.info("couldn't find get @ user %s:",
                                 at_user_id)
            except:
                e = sys.exc_info()
                exc_type, exc_value, exc_traceback = e
                trace = repr(traceback.format_exception(exc_type,
                                                        exc_value,
                                                        exc_traceback))
                if (self._log_on_error):
                    _LOGGER.warning("couldn't find get @ user %s: %s",
                                    at_user_id, trace)

        return input_text



def format_notifications(input_text):
    '''Handles reformatting of things like @here.  Note that this assumes that
       any groups have already been filtered out, as they use a similar format
       but would need the ID to be looked up.'''
    notif_shift = 0
    for m in _SLACK_NOTIF_MATCH.finditer(input_text):
        match = m.group()
        notif = match[2:-1]
        old_text = input_text
        start = m.start() + notif_shift
        input_text = old_text[:start]
        input_text += '**@' + notif + '**'
        input_text += old_text[start + len(match):]
        notif_shift = len(input_text) - len(old_text) + notif_shift
    return input_text


def format_channels(input_text):
    '''Finds anything that looks like a slack channel in the text, and replaces
       it with a bolded version.  Returns the new text.'''
    channel_shift = 0
    for m in _SLACK_CHANNEL_MATCH.finditer(input_text):
        match = m.group()
        ref_channel = (match[2:-1].split('|'))[1]
        old_text = input_text
        start = m.start() + channel_shift
        input_text = old_text[:start]
        input_text += '**#' + ref_channel + '**'
        input_text += old_text[start + len(match):]
        channel_shift = len(input_text) - len(old_text) + channel_shift
    return input_text


def format_markdown_links(input_text):
    '''Finds anything that looks like a markdown link in the text.

       If the display text is identical to the URL, we just remove all the markdown
       and leave a bare URL.  If there is replacement text, we change it to zulip
       markdown.

       NOTE: This later case results in brokenness for groupme, but presumably
       the URL will still be at least visible.

       NOTE: We currently will leave the carets in place for a URL of the form
       <http://foo.com>

       Returns the new text.'''
    link_shift = 0
    for m in _SLACK_LINK_MATCH.finditer(input_text):
        match = m.group()

        bare_url_match = _SLACK_LINK_BARE_URL_MATCH.match(match)

        if bare_url_match:
            replacement = bare_url_match.group(1)
        else:
            replacement_url = m.group(1)
            replacement_displaytext = m.group(2)
            replacement = '[%s](%s)' % (replacement_displaytext, replacement_url)

        old_text = input_text
        start = m.start() + link_shift
        input_text = old_text[:start]
        input_text += replacement
        input_text += old_text[start + len(match):]
        link_shift = len(input_text) - len(old_text) + link_shift
    return input_text
