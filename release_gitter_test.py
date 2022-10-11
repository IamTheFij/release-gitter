from __future__ import annotations

import unittest
from pathlib import Path
from tarfile import TarFile
from typing import Any
from typing import Callable
from typing import NamedTuple
from typing import Optional
from unittest.mock import MagicMock
from unittest.mock import mock_open
from unittest.mock import patch
from zipfile import ZipFile

import requests

import release_gitter


class TestExpression(NamedTuple):
    t: unittest.TestCase
    args: list[Any]
    kwargs: dict[str, Any]
    expected: Any
    exception: Optional[type[Exception]] = None

    def run(self, f: Callable):
        with self.t.subTest(f=f, args=self.args, kwargs=self.kwargs):
            try:
                result = f(*self.args, **self.kwargs)
                self.t.assertIsNone(
                    self.exception,
                    f"Expected an exception of type {self.exception}, but found none",
                )
                self.t.assertEqual(self.expected, result)
                return result
            except Exception as e:
                if self.exception and isinstance(e, self.exception):
                    return e
                raise


class TestGeneral(unittest.TestCase):
    def test_removesuffix(self):
        for test_case in (
            TestExpression(self, ["repo.git", ".git"], {}, "repo"),
            TestExpression(self, ["repo", ".git"], {}, "repo"),
        ):
            test_case.run(release_gitter.removesuffix)


class TestRemoteInfo(unittest.TestCase):
    def test_parse_remote_info(self):
        for test_case in (
            TestExpression(
                self,
                ["https://github.com/owner/repo"],
                {},
                release_gitter.GitRemoteInfo("github.com", "owner", "repo"),
                None,
            ),
            TestExpression(
                self,
                ["git@github.com:owner/repo"],
                {},
                release_gitter.GitRemoteInfo("github.com", "owner", "repo"),
                None,
            ),
            TestExpression(
                self,
                ["ssh://git@git.iamthefij.com/owner/repo"],
                {},
                release_gitter.GitRemoteInfo("git.iamthefij.com", "owner", "repo"),
                None,
            ),
            TestExpression(
                self,
                ["https://git@example.com/repo"],
                {},
                None,
                release_gitter.InvalidRemoteError,
            ),
        ):
            test_case.run(release_gitter.parse_git_remote)

    def test_generate_release_url(self):
        for subtest in (
            TestExpression(
                self,
                [release_gitter.GitRemoteInfo("github.com", "owner", "repo")],
                {},
                "https://api.github.com/repos/owner/repo/releases",
                None,
            ),
            TestExpression(
                self,
                [release_gitter.GitRemoteInfo("git.iamthefij.com", "owner", "repo")],
                {},
                "https://git.iamthefij.com/api/v1/repos/owner/repo/releases",
                None,
            ),
            TestExpression(
                self,
                [release_gitter.GitRemoteInfo("gitlab.com", "owner", "repo")],
                {},
                None,
                release_gitter.InvalidRemoteError,
            ),
        ):
            mock_response = MagicMock(spec=requests.Response)
            mock_response.json = MagicMock()
            if subtest.args[0].hostname == "git.iamthefij.com":
                mock_response.json.return_value = {
                    "paths": {"/repos/{owner}/{repo}/releases": {}},
                    "basePath": "/api/v1",
                }
            with patch("requests.get", return_value=mock_response):
                subtest.run(release_gitter.GitRemoteInfo.get_releases_url)


class TestVersionInfo(unittest.TestCase):
    def test_no_cargo_file(self):
        with patch("pathlib.Path.exists", return_value=False):
            version = release_gitter.read_version()
            self.assertIsNone(version)

    @patch("pathlib.Path.exists", return_value=True)
    @patch(
        "pathlib.Path.open",
        mock_open(read_data="\n".join(["[package]", 'version = "1.0.0"'])),
    )
    def test_cargo_file_has_version(self, *_):
        version = release_gitter.read_version()
        self.assertEqual(version, "1.0.0")

    @patch("pathlib.Path.exists", return_value=True)
    @patch(
        "pathlib.Path.open",
        mock_open(read_data="\n".join(["[package]"])),
    )
    def test_cargo_file_missing_version(self, *_):
        with self.assertRaises(ValueError):
            release_gitter.read_version()


@patch("release_gitter.ZipFile", autospec=True)
@patch("release_gitter.BytesIO", autospec=True)
class TestContentTypeDetection(unittest.TestCase):
    def test_asset_encoding_priority(self, *_):
        package = release_gitter.get_asset_package(
            {
                "content_type": "application/x-tar",
                "name": "test.zip",
            },
            MagicMock(spec=["raw", "content"]),
        )
        # Tar should take priority over the file name zip extension
        self.assertIsInstance(package._package, TarFile)

    def test_fallback_to_supported_encoding(self, *_):
        package = release_gitter.get_asset_package(
            {
                "content_type": "application/octetstream",
                "name": "test.zip",
            },
            MagicMock(spec=["raw", "content"]),
        )
        # Should fall back to zip extension
        self.assertIsInstance(package._package, ZipFile)

    def test_missing_only_name_content_type(self, *_):
        package = release_gitter.get_asset_package(
            {
                "name": "test.zip",
            },
            MagicMock(spec=["raw", "content"]),
        )
        # Should fall back to zip extension
        self.assertIsInstance(package._package, ZipFile)

    def test_no_content_types(self, *_):
        with self.assertRaises(release_gitter.UnsupportedContentTypeError):
            release_gitter.get_asset_package(
                {
                    "name": "test",
                },
                MagicMock(spec=["raw", "content"]),
            )

    def test_no_supported_content_types(self, *_):
        with self.assertRaises(release_gitter.UnsupportedContentTypeError):
            release_gitter.get_asset_package(
                {
                    "content_type": "application/octetstream",
                    "name": "test",
                },
                MagicMock(spec=["raw", "content"]),
            )


if __name__ == "__main__":
    unittest.main()
