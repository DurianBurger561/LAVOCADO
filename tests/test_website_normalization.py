"""Address values are reduced to safe, comparable hostnames."""

import unittest

from app.context.website.normalization import normalize_hostname


class WebsiteNormalizationTests(unittest.TestCase):
    def test_discards_path_query_fragment_and_port(self) -> None:
        self.assertEqual(
            normalize_hostname("https://WWW.Example.COM:443/private?q=secret#anchor"),
            "www.example.com",
        )
        self.assertEqual(normalize_hostname("example.co.uk/private"), "example.co.uk")
        self.assertEqual(normalize_hostname("https://example.com.au/path"), "example.com.au")

    def test_normalizes_idn_and_trailing_dot(self) -> None:
        self.assertEqual(normalize_hostname("https://bücher.example./secret"), "xn--bcher-kva.example")
        self.assertEqual(normalize_hostname("EXAMPLE.COM."), "example.com")

    def test_rejects_non_web_or_ambiguous_values(self) -> None:
        for value in (
            None,
            "",
            "about:blank",
            "chrome://settings",
            "javascript:alert(1)",
            "file:///private/file",
            "ftp://example.com/file",
            "https:///example.com",
            "https://user:secret@example.com/",
            "https://example.com:99999/",
            "https://fake example.com/",
            "https://example.com\n.evil.test/",
            "https://example.com\\@evil.test/",
            "example.com.evil.test@trusted.example",
            "localhost",
        ):
            with self.subTest(value=value):
                self.assertIsNone(normalize_hostname(value))

    def test_does_not_truncate_multi_label_public_suffixes(self) -> None:
        self.assertEqual(normalize_hostname("a.b.example.co.uk"), "a.b.example.co.uk")
        self.assertEqual(normalize_hostname("a.b.example.com.au"), "a.b.example.com.au")


if __name__ == "__main__":
    unittest.main()
