"""Tests for authenticated model-download request construction."""

import unittest

from app.vision.model_assets import NUDENET_640M_DOWNLOAD_URL
from scripts.download_models import build_download_request


def request_headers(request) -> dict[str, str]:
    return {name.casefold(): value for name, value in request.header_items()}


class DownloadModelTests(unittest.TestCase):
    def test_actions_token_authenticates_github_asset_request(self) -> None:
        request = build_download_request(
            {"GITHUB_TOKEN": "  test-actions-token  "}
        )

        self.assertEqual(request.full_url, NUDENET_640M_DOWNLOAD_URL)
        self.assertEqual(
            request_headers(request)["authorization"],
            "Bearer test-actions-token",
        )

    def test_local_request_remains_anonymous_without_token(self) -> None:
        request = build_download_request({})
        headers = request_headers(request)

        self.assertNotIn("authorization", headers)
        self.assertEqual(headers["accept"], "application/octet-stream")
        self.assertEqual(headers["user-agent"], "LAVOCADO-model-downloader")
        self.assertEqual(headers["x-github-api-version"], "2022-11-28")


if __name__ == "__main__":
    unittest.main()
