"""Tests for authenticated model-download request construction."""

import unittest
from contextlib import redirect_stderr
from io import StringIO
from unittest.mock import patch

from app.vision.model_manifest import NUDENET_640M_DOWNLOAD_URL, REQUIRED_MODEL_IDS
from scripts.download_models import build_download_request, build_parser, main


def request_headers(request) -> dict[str, str]:
    return {name.casefold(): value for name, value in request.header_items()}


class DownloadModelTests(unittest.TestCase):
    def test_default_download_set_is_all_four_required_models(self) -> None:
        self.assertEqual(build_parser().parse_args([]).model, "all")
        self.assertEqual(len(REQUIRED_MODEL_IDS), 4)

    def test_download_error_includes_type_and_message(self) -> None:
        stderr = StringIO()
        with patch("sys.argv", ["download_models.py", "--model", "viddexa_nano"]), patch(
            "scripts.download_models.download_catalog_model",
            side_effect=RuntimeError("context dependencies unavailable"),
        ), redirect_stderr(stderr):
            result = main()

        self.assertEqual(result, 1)
        self.assertIn(
            "Failed viddexa_nano: RuntimeError: context dependencies unavailable",
            stderr.getvalue(),
        )

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
