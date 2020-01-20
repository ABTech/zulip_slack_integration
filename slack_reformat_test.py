import asyncio
import unittest

import slack_reformat

# Shorthand for doing an await in a unittest.
do_await = asyncio.get_event_loop().run_until_complete

class TestSlackReformat(unittest.TestCase):
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

        # mailto: scheme works (i.e. leading // isn't required)
        self.assertEqual(
            do_await(slack_reformat.format_markdown_links('<mailto:x@x.com|mailto:x@x.com>')),
            'mailto:x@x.com'
        )


if __name__ == '__main__':
    unittest.main()
