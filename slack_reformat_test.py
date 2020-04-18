import asyncio
import unittest

import slack_reformat

# Shorthand for doing an await in a unittest.
do_await = asyncio.get_event_loop().run_until_complete

# Simple standin for the redis lookup.
async def _trivial_user_lookup(id):
    if id == '12345':
        return 'Alice'
    else:
        return False

_trivial_user_formatter = slack_reformat.SlackUserFormatter(
    _trivial_user_lookup, log_on_error=False)

class TestSlackReformat(unittest.TestCase):
    def test_reformat_slack_text(self):
        # Just check one of everything to make sure it all works.
        self.assertEqual(
            do_await(
                slack_reformat.reformat_slack_text(_trivial_user_formatter,
                    'User <@12345> Channel <#C123G567|channel> Notif <!here> Link <http://foo.com>')),
            'User **@Alice** Channel **#channel** Notif **@here** Link http://foo.com')


    def test_format_user(self):
        # Simple standin for the redis lookup.
        async def user_lookup(id):
            if id == '12345':
                return 'Alice'
            elif id == '54321':
                return 'Bob'
            elif id == 'ERROR':
                raise NameError
            else:
                return False

        user_formatter = slack_reformat.SlackUserFormatter(user_lookup, log_on_error=False)

        # Null Case
        self.assertEqual(
            do_await(user_formatter.format_user('Plain Text')),
            'Plain Text'
        )

        # Just Alice
        self.assertEqual(
            do_await(user_formatter.format_user('Hi <@12345>')),
            'Hi **@Alice**'
        )

        # Unknown user
        self.assertEqual(
            do_await(user_formatter.format_user('Hi <@Unknown>')),
            'Hi <@Unknown>'
        )

        # Multiple Names
        self.assertEqual(
            do_await(user_formatter.format_user('Hi <@12345> and <@54321> and <@12345>!')),
            'Hi **@Alice** and **@Bob** and **@Alice**!'
        )

        # Simple error case -- should just hand back the original
        self.assertEqual(
            do_await(user_formatter.format_user('Hi <@ERROR>')),
            'Hi <@ERROR>'
        )

        # Error on second name should still convert other non-error ones.
        self.assertEqual(
            do_await(user_formatter.format_user('Hi <@12345> and <@ERROR> and <@54321>!')),
            'Hi **@Alice** and <@ERROR> and **@Bob**!'
        )


    def test_format_notifications(self):
        # No groups in text
        self.assertEqual(
            do_await(slack_reformat.format_notifications('Plain Text')),
            'Plain Text'
        )

        # One group in text
        self.assertEqual(
            do_await(slack_reformat.format_notifications('Text with notification <!here> for you')),
            'Text with notification **@here** for you'
        )

        # Multiple notifications
        self.assertEqual(
            do_await(slack_reformat.format_notifications('<!here> Ping <!everyone> Loud <!channel>!')),
            '**@here** Ping **@everyone** Loud **@channel**!'
        )


    def test_format_channels(self):
        # No channels in text
        self.assertEqual(
            do_await(slack_reformat.format_channels('Plain Text')),
            'Plain Text'
        )

        # One channel in text
        self.assertEqual(
            do_await(slack_reformat.format_channels('Text with <#C123G567|channel> inline')),
            'Text with **#channel** inline'
        )

        # Two channels in text
        self.assertEqual(
            do_await(slack_reformat.format_channels(
                '<#C1234567|channel1> with another <#C123AD67|channel2> etc')),
            '**#channel1** with another **#channel2** etc'
        )

        # Three channels

        self.assertEqual(
            do_await(slack_reformat.format_channels(
                '<#C1234567|channel1> <#C12BB567|channel2> <#C12AA567|channel3>!')),
            '**#channel1** **#channel2** **#channel3**!'
        )


    def test_markdown_links(self):
        # Does nothing if it shouldn't
        self.assertEqual(
            do_await(slack_reformat.format_markdown_links('Plain Text')),
            'Plain Text'
        )

        # Does nothing if there is a bare URL there
        self.assertEqual(
            do_await(slack_reformat.format_markdown_links('http://foo.com')),
            'http://foo.com'
        )

        # Base case - just the URL without a piped display name just gets its brackets stripped.
        self.assertEqual(
            do_await(slack_reformat.format_markdown_links('<http://foo.com>')),
            'http://foo.com'
        )

        # Base case - just the URL with a duplicated display name
        self.assertEqual(
            do_await(slack_reformat.format_markdown_links('<http://foo.com|http://foo.com>')),
            'http://foo.com'
        )

        # Base case - URL with display text
        self.assertEqual(
            do_await(slack_reformat.format_markdown_links('<http://foo.com|Display Text>')),
            '[Display Text](http://foo.com)'
        )

        # One of each
        self.assertEqual(
            do_await(slack_reformat.format_markdown_links(
                'Text <http://foo.com|http://foo.com> And <http://foo.com|Display Text> Done')),
            'Text http://foo.com And [Display Text](http://foo.com) Done'
        )

        # Three replacements
        self.assertEqual(
            do_await(slack_reformat.format_markdown_links(
                'Text <http://foo.com|http://foo.com> And <http://foo.com|Display Text> <http://bar.com|http://bar.com> Done')),
            'Text http://foo.com And [Display Text](http://foo.com) http://bar.com Done'
        )

        # Two bare link replacements
        self.assertEqual(
            do_await(slack_reformat.format_markdown_links(
                'Test <http://foo.com> <http://google.com>')),
            'Test http://foo.com http://google.com'
        )

        # Multiple Links: Bare & Display Name & Display Name == Link
        self.assertEqual(
            do_await(slack_reformat.format_markdown_links(
                'Test <http://foo.com> <http://google.com|The Goog> <http://bar.com|http://bar.com>')),
            'Test http://foo.com [The Goog](http://google.com) http://bar.com'
        )


        # mailto: scheme works (i.e. leading // isn't required)
        self.assertEqual(
            do_await(slack_reformat.format_markdown_links('<mailto:x@x.com|mailto:x@x.com>')),
            'mailto:x@x.com'
        )

    def test_format_files_from_slack(self):
        # Note: This test is _not_ exhaustive!
        #
        # TODO: Figure out some way to mock out the pieces necessary to allow us to test the download/upload
        # path for files.

        # None case
        output = do_await(slack_reformat.format_files_from_slack(None, False))
        self.assertEqual(output['plaintext'], '')
        self.assertEqual(output['markdown'], '')

        # None case, leading newline
        output = do_await(slack_reformat.format_files_from_slack(None, True))
        self.assertEqual(output['plaintext'], '')
        self.assertEqual(output['markdown'], '')

        # Base case
        output = do_await(slack_reformat.format_files_from_slack([], False))
        self.assertEqual(output['plaintext'], '')
        self.assertEqual(output['markdown'], '')

        # Single file, no title
        test_filename = 'filename.jpg'
        test_file = {
            "id": "U0000000",
            "created": 1579621511,
            "timestamp": 1579621511,
            "name": test_filename,
            "mimetype": "image/jpeg",
            "filetype": "jpg",
            "pretty_type": "JPEG",
            "user": "U1111111",
            "editable": False,
            "size": 750000,
            "mode": "hosted",
            "is_external": False,
            "external_type": "",
            "is_public": False,
            "public_url_shared": False,
            "display_as_bot": False,
            "username": "",
            "url_private": "https://files.slack.com/files-pri/T0000000-F0000000/filename.jpg"
            # ... and many omitted fields
        }
        output = do_await(slack_reformat.format_files_from_slack([test_file], True))
        self.assertEqual(output['plaintext'], '\n(Bridged Message included file: filename.jpg)')
        self.assertEqual(output['markdown'], '\n*(Bridged Message included file: filename.jpg)*')

        # Same test, no leading newline.
        output = do_await(slack_reformat.format_files_from_slack([test_file], False))
        self.assertEqual(output['plaintext'], '(Bridged Message included file: filename.jpg)')
        self.assertEqual(output['markdown'], '*(Bridged Message included file: filename.jpg)*')

        # Multiple files.
        output = do_await(slack_reformat.format_files_from_slack([test_file, test_file], False))
        self.assertEqual(output['plaintext'],
            '(Bridged Message included file: filename.jpg)\n(Bridged Message included file: filename.jpg)')
        self.assertEqual(output['markdown'],
            '*(Bridged Message included file: filename.jpg)*\n*(Bridged Message included file: filename.jpg)*')

        # If we have a title that matches the filename, it should not be displayed.
        test_file['title'] = test_filename
        output = do_await(slack_reformat.format_files_from_slack([test_file], True))
        self.assertEqual(output['plaintext'], '\n(Bridged Message included file: filename.jpg)')
        self.assertEqual(output['markdown'], '\n*(Bridged Message included file: filename.jpg)*')

        # Add a distinct title to the above:
        test_file['title'] = 'File Title'
        output = do_await(slack_reformat.format_files_from_slack([test_file], True))
        self.assertEqual(output['plaintext'], '\n(Bridged Message included file: filename.jpg: \'File Title\')')
        self.assertEqual(output['markdown'], '\n*(Bridged Message included file: filename.jpg: \'File Title\')*')

        # Deleted file
        test_file = {
            "id": "U0000000",
            "mode": "tombstone",
        }
        output = do_await(slack_reformat.format_files_from_slack([test_file], False))
        self.assertEqual(output['plaintext'], '')
        self.assertEqual(output['markdown'], '')


    def test_format_attachments_from_slack(self):
        # Note: This test is _not_ exhaustive!

        # Base case -- no attachments
        output = do_await(slack_reformat.format_attachments_from_slack(
            'message', [], False, _trivial_user_formatter))
        self.assertEqual(output['plaintext'], '')
        self.assertEqual(output['markdown'], '')

        # Link preview attachment.  This is built so that the text section needs to be reformatted.
        google_link_preview = {
            'title': 'Google',
            'title_link': 'http://www.google.com/',
            'text': 'Search the world\'s information at <http://www.google.com>',
            'fallback': 'Google',
            'from_url': 'http://www.google.com/',
            'service_icon': 'http://www.google.com/favicon.ico',
            'service_name': 'google.com',
            'id': 1,
            'original_url': 'http://www.google.com'
        }
        output = do_await(slack_reformat.format_attachments_from_slack(
            'message', [google_link_preview], False, _trivial_user_formatter))
        self.assertEqual(
            output['markdown'],
            '\n\n```quote\n**[Google](http://www.google.com/)**\nSearch the world\'s information at http://www.google.com\n```'
        )
        self.assertEqual(
            output['plaintext'],
            '\n\nGoogle: http://www.google.com/\nSearch the world\'s information at http://www.google.com\n'
        )


        # Github app attachment
        #
        # Note: correct behavior here requres that footers _also_ get the basic slack formatting rewrite.
        github_app_attachment = {
            "fallback": "ABTech/zulip_slack_integration",
            "title": "ABTech/zulip_slack_integration",
            "footer": "<https://github.com/ABTech/zulip_slack_integration|ABTech/zulip_slack_integration>",
            "id": 1,
            "footer_icon": "https://github.githubassets.com/favicon.ico",
            "ts": 1558647312,
            "color": "24292f",
            "fields": [{
                    "title": "Stars",
                    "value": "1",
                    "short": True
                }, {
                    "title": "Language",
                    "value": "Python",
                    "short": True
                }],
            "mrkdwn_in": ["text", "fields"],
            "bot_id": "BSWPYJGUF",
            "app_unfurl_url": "https://github.com/ABTech/zulip_slack_integration",
            "is_app_unfurl": True
        }
        output = do_await(slack_reformat.format_attachments_from_slack(
            'message', [github_app_attachment], False, _trivial_user_formatter))

        # TODO This test (really, the formatting itself) is time zone sensitive to the TZ of the machine
        # you are on!  Currently assumes Eastern time.

        self.assertEqual(
            output['markdown'],
            '\n\n```quote\n**ABTech/zulip_slack_integration**\n**Stars**\n1\n**Language**\nPython\n*[ABTech/zulip_slack_integration](https://github.com/ABTech/zulip_slack_integration)* | *Thu May 23 17:35:12 2019*\n```'
        )
        self.assertEqual(
            output['plaintext'],
            '\n\nABTech/zulip_slack_integration\nStars\n1\nLanguage\nPython\n[ABTech/zulip_slack_integration](https://github.com/ABTech/zulip_slack_integration) | Thu May 23 17:35:12 2019\n'
        )

if __name__ == '__main__':
    unittest.main()
