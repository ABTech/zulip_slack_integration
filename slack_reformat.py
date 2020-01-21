# Module to consolidate logic around reformatting messages that originate on
# slack before they are forwarded.

import datetime
import logging
import re
import sys
import traceback

_LOGGER = logging.getLogger(__name__)

# These are module-private regular expressions used by the reformatter
_SLACK_USER_MATCH = re.compile("<@([A-Z0-9]+)>")
_SLACK_NOTIF_MATCH = re.compile("<!([a-zA-Z0-9]+)>")
_SLACK_CHANNEL_MATCH = re.compile("<#[a-zA-Z0-9]+\\|([a-zA-Z0-9]+)>")
_SLACK_LINK_BARE_URL_MATCH = re.compile("<([a-zA-Z0-9]+:[^|]+)(\\|\\1){0,1}>")
_SLACK_LINK_MATCH = re.compile("<([a-zA-Z0-9]+:[^|]+)(?:\\|([^>]+)){0,1}>")

async def reformat_slack_text(user_formatter, input_text):
    '''This helper method, given a SlackUserFormatter, will format the input_text
       for transmission from Slack to other services.  Using it ensures that any dependencies
       between the individual reformatters is obeyed. '''
    input_text = await user_formatter.format_user(input_text)
    input_text = await format_notifications(input_text)
    input_text = await format_channels(input_text)
    input_text = await format_markdown_links(input_text)

    return input_text


async def _do_transform(input_text,
                        match_pattern, replace_func):
    '''This method provides the basic work of finding parts of a slack message to replace with
       alternate markdown, and then getting them replaced.  Private to this module.

       Searches input_text for regex_search (compiled regex object)
       Strips < > and prefix if specified.
           Ex. "<@U###>" becomes U###, "<!here>" becomes "here"
       Passes the regex match object to (async) replace_func, which returns what to replace it with.
           Ex. for channels which match "<@C##|general>" replace_func would return '**#general**'

       Returns the result of the transform.'''
    transform_shift = 0
    for m in match_pattern.finditer(input_text):
        match = m.group()

        old_text = input_text
        start = m.start() + transform_shift

        input_text = old_text[:start]
        input_text += await replace_func(m)
        input_text += old_text[start + len(match):]

        transform_shift = len(input_text) - len(old_text) + transform_shift
    return input_text


class SlackUserFormatter:
    def __init__(self, user_lookup_function, log_on_error=True):
        '''Constructor.  user_lookup_function should return a couroutine that resolves to
            the display name of the passed in user identifier. It may throw an exception on failure.'''
        self._get_slack_user = user_lookup_function
        self._log_on_error = log_on_error

    async def format_user(self, input_text):
        '''Handles reformatting of slack markdown user references in a string of text. '''

        async def user_reformat(m):
            '''User reformat helper function for _do_transform. '''
            match = m.group()
            at_user_id = match[2:-1]

            try:
                at_user = await self._get_slack_user(at_user_id)

                if at_user:
                    return '**@%s**' % at_user
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

            # in failure cases, just return the original text
            return match

        return await _do_transform(input_text,
                                   _SLACK_USER_MATCH,
                                   user_reformat)


async def format_notifications(input_text):
    '''Handles reformatting of things like @here.  Note that this assumes that
       any groups have already been filtered out, as they use a similar format
       but would need the ID to be looked up.'''
    async def notification_reformat(m):
        return ('**@%s**' % m.group(1))

    return await _do_transform(input_text,
                               _SLACK_NOTIF_MATCH,
                               notification_reformat)


async def format_channels(input_text):
    '''Finds anything that looks like a slack channel in the text, and replaces
       it with a bolded version.  Returns the new text.'''
    async def channel_reformat(m):
        return ('**#%s**' % m.group(1))

    return await _do_transform(input_text,
                               _SLACK_CHANNEL_MATCH,
                               channel_reformat)


async def format_markdown_links(input_text):
    '''Finds anything that looks like a markdown link in the text.

       If the display text is identical to the URL, we just remove all the markdown
       and leave a bare URL.  If there is replacement text, we change it to zulip
       markdown.

       NOTE: This later case results in brokenness for groupme, but presumably
       the URL will still be at least visible.

       NOTE: We currently will leave the carets in place for a URL of the form
       <http://foo.com>

       Returns the new text.'''
    async def replace_markdown_link(m):
        match = m.group()
        bare_url_match = _SLACK_LINK_BARE_URL_MATCH.match(match)

        if bare_url_match:
            replacement = bare_url_match.group(1)
        else:
            replacement_url = m.group(1)
            replacement_displaytext = m.group(2)
            replacement = '[%s](%s)' % (replacement_displaytext, replacement_url)

        return replacement

    return await _do_transform(input_text,
                               _SLACK_LINK_MATCH,
                               replace_markdown_link)

async def format_attachments_for_zulip(message_text, attachments, edit_or_delete, user_formatter):
    '''Translate a slack-style attachments list into text to be appended to a zulip message &
       append it to message_text, returning the result.'''
    attach_txt = ''
    if len(attachments) > 0:
        if edit_or_delete or len(message_text) > 0:
            attach_txt += '\n\n'
        for attach_i in range(len(attachments)):
            if attach_i > 0:
                attach_txt += '\n\n'
            attachment = attachments[attach_i]
            if 'pretext' in attachment:
                attach_txt += attachment['pretext'] + '\n'
            if ('text' in attachment or 'title' in attachment or
                    'author_name' in attachment):
                if (not edit_or_delete and not len(message_text) > 0
                    and 'pretext' not in attachment):
                    attach_txt += '\n'
                attach_txt += '```quote\n'
                if 'author_link' in attachment:
                    attach_txt += f"[{attachment['author_name']}]({attachment['author_link']})\n"
                elif 'author_name' in attachment:
                    attach_txt += f"{attachment['author_name']}\n"
                if 'title_link' in attachment:
                    attach_txt += f"**[{attachment['title']}]({attachment['title_link']})**\n"
                elif 'title' in attachment:
                    attach_txt += f"**{attachment['title']}**\n"
                if 'text' in attachment:
                    attach_txt += attachment['text'] + '\n'
                if 'image_url' in attachment:
                    attach_txt += f"[Image]({attachment['image_url']})\n"
                if 'fields' in attachment:
                    for field in attachment['fields']:
                        if 'title' in field:
                            attach_txt += f"**{field['title']}**\n"
                        if 'value' in field:
                            attach_txt += f"{field['value']}\n"
                if 'footer' in attachment:
                    attach_txt += f"*{attachment['footer']}*"
                if 'footer' in attachment and 'ts' in attachment:
                    attach_txt += " | "
                if 'ts' in attachment:
                    out_time = datetime.datetime.fromtimestamp(attachment['ts']).strftime('%c')
                    attach_txt += f"*{out_time}*"
                if 'footer' in attachment or 'ts' in attachment:
                    attach_txt += "\n"
                attach_txt += '```'

    return message_text + attach_txt

async def format_attachments_for_groupme(message_text, attachments, edit_or_delete, user_formatter):
    '''Translate a slack-style attachments list into text to be appended to a groupme message &
       append it to message_text, returning the result.'''
    # Placeholder for now.

    # Copied from never-used code in send_to_groupme:
    #
    # Check for image
    #    for attachment in msg['attachments']:
    #        # Add link to image to message text
    #        if attachment['type'] == 'image':
    #            caption = message_text if message_text else 'image'
    #            message_text = '[%s](%s)\n' % (caption, attachment['url'])
    #            break

    return message_text
