import unittest

from research_platform.sanitization import sanitize_text_urls, sanitize_url


class UrlSanitizationTests(unittest.TestCase):
    def test_case_insensitive_credentials_and_aws_signature_fields_are_removed(self):
        url = (
            "https://user:password@example.com/report?safe=ok&monkey=banana"
            "&KEY=key-secret&Signature=signature-secret&SiG=sig-secret"
            "&credential=credential-secret&secret=secret-value&ToKeN=token-secret"
            "&AUTH=auth-secret&PASSWORD=password-secret&authCode=code-secret"
            "&pwd=pwd-secret&X-Amz-Signature=aws-signature-secret"
            "&X-Amz-Credential=aws-credential-secret"
            "&X-Amz-Security-Token=aws-token-secret&X-Amz-Date=20260801T000000Z"
        )

        sanitized = sanitize_url(url)

        self.assertEqual(
            sanitized,
            (
                "https://example.com/report?safe=ok&monkey=banana"
                "&X-Amz-Date=20260801T000000Z"
            ),
        )

    def test_embedded_and_nested_urls_are_sanitized(self):
        text = (
            "See https://example.com/report?topic=safe&key=outer-secret and "
            "https://redirect.example/?next=https%3A%2F%2Fnested.example%2F"
            "%3Ftoken%3Dnested-secret"
        )

        sanitized = sanitize_text_urls(text)

        self.assertNotIn("outer-secret", sanitized)
        self.assertNotIn("nested-secret", sanitized)
        self.assertIn("topic=safe", sanitized)
        self.assertIn("nested.example", sanitized)


if __name__ == "__main__":
    unittest.main()
