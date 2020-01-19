# Module to consolidate logic around reformatting messages that originate on
# slack before they are forwarded.

import re

_SLACK_NOTIF_MATCH = re.compile("<![a-zA-Z0-9]+>")
_SLACK_CHANNEL_MATCH = re.compile("<#[a-zA-Z0-9]+\\|[a-zA-Z0-9]+>")
_SLACK_LINK_BARE_URL_MATCH = re.compile("<([a-zA-Z0-9]+:[^|]+)\\|\\1>")
_SLACK_LINK_MATCH = re.compile("<([a-zA-Z0-9]+:[^|]+)\\|([^>]+)>")

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
