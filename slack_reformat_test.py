import unittest

import slack_reformat

class TestSlackReformat(unittest.TestCase):
    def test_format_notifications(self):
        # No groups in text
        self.assertEqual(
            slack_reformat.format_notifications('Plain Text'),
            'Plain Text'
        )

        # One group in text
        self.assertEqual(
            slack_reformat.format_notifications('Text with notification <!here> for you'),
            'Text with notification **@here** for you'
        )

        # Multiple notifications
        self.assertEqual(
            slack_reformat.format_notifications('<!here> Ping <!everyone> Loud <!channel>!'),
            '**@here** Ping **@everyone** Loud **@channel**!'
        )

    def test_format_channels(self):
        # No channels in text
        self.assertEqual(
            slack_reformat.format_channels('Plain Text'),
            'Plain Text'
        )

        # One channel in text
        self.assertEqual(
            slack_reformat.format_channels('Text with <#C123G567|channel> inline'),
            'Text with **#channel** inline'
        )

        # Two channels in text
        self.assertEqual(
            slack_reformat.format_channels('<#C1234567|channel1> with another <#C123AD67|channel2> etc'),
            '**#channel1** with another **#channel2** etc'
        )

        # Three channels

        self.assertEqual(
            slack_reformat.format_channels('<#C1234567|channel1> <#C12BB567|channel2> <#C12AA567|channel3>!'),
            '**#channel1** **#channel2** **#channel3**!'
        )



    def test_markdown_links(self):
        # Demo only -- this is not implemented yet.
        self.assertEqual(
            slack_reformat.format_markdown_links('Plain Text'),
            'Plain Text'
        )

if __name__ == '__main__':
    unittest.main()
