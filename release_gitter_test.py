from __future__ import annotations

import unittest
from itertools import chain
from itertools import product
from tarfile import TarFile
from typing import Any
from typing import Callable
from typing import NamedTuple
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
    exception: type[Exception] | None = None
    msg: str | None = None

    def run(self, f: Callable):
        with self.t.subTest(msg=self.msg, f=f, args=self.args, kwargs=self.kwargs):
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


def first_result(f):
    def wrapper(*args, **kwargs):
        return f(*args, **kwargs)[0]

    return wrapper


class TestMatchAsset(unittest.TestCase):
    def test_match_asset_versions(self, *_):
        # Input variations:
        # Case 1: Version provided with prefix
        # Case 2: Version provided without prefix
        # Case 3: No version provided, tag exists in release
        # These should be impossible
        # Case 4: No version provided, tag doesn't exist in release but not in template
        # Case 5: No version provided, tag doesn't exist in release and is in template

        # Release variations:
        # Case 1: tag_name with version prefix
        # Case 2: tag_name without version prefix

        # File variations:
        # Case 1: file name with version prefix
        # Case 2: file name without version prefix

        def new_expression(version: str | None, tag_name: str, file_name: str):
            release = {"tag_name": tag_name, "assets": [{"name": file_name}]}
            expected = {"name": file_name}
            return TestExpression(
                self, [release, "file-{version}.zip", version], {}, expected
            )

        happy_cases = [
            new_expression(version, tag_name, file_name)
            for version, tag_name, file_name in product(
                ("v1.0.0", "1.0.0", None),
                ("v1.0.0", "1.0.0"),
                ("file-v1.0.0.zip", "file-1.0.0.zip"),
            )
        ]
        for test_case in happy_cases:
            test_case.run(first_result(release_gitter.match_asset))

    def test_match_asset_systems(self, *_):
        # Input variations:
        # Case 1: System mapping provided
        # Case 2: No system mapping provided

        # Test: We want to show that default matching will work out of the box with some values for the current machine
        # Test: We want to show that non-standard mappings will always work if provided manually

        def run_with_context(actual_system: str, *args, **kwargs):
            with patch("platform.system", return_value=actual_system):
                return release_gitter.match_asset(*args, **kwargs)

        def new_expression(
            actual_system: str,
            system_mapping: dict[str, str] | None,
            file_name: str,
            expected: dict[str, str],
            exception: type[Exception] | None = None,
            msg: str | None = None,
        ):
            release = {
                "name": "v1.0.0",
                "tag_name": "v1.0.0",
                "assets": [{"name": file_name}],
            }
            return TestExpression(
                self,
                [actual_system, release, "file-{system}.zip"],
                {"system_mapping": system_mapping},
                expected,
                exception,
                msg,
            )

        test_cases = chain(
            [
                new_expression(
                    "Earth",
                    None,
                    "file-Earth.zip",
                    {"name": "file-Earth.zip"},
                    msg="Current system always included as an exact match synonym",
                ),
                new_expression(
                    "Linux",
                    {"Linux": "jumanji"},
                    "file-jumanji.zip",
                    {"name": "file-jumanji.zip"},
                    msg="Non-standard system mapping works",
                ),
                new_expression(
                    "Linux",
                    {},
                    "file-darwin.zip",
                    {},
                    ValueError,
                    msg="No matching system",
                ),
            ],
            # Test default mappings
            (
                new_expression(
                    actual_system,
                    None,
                    file_name,
                    {"name": file_name},
                    msg="Default Linux mappings",
                )
                for actual_system, file_name in product(
                    ("Linux", "linux"),
                    ("file-Linux.zip", "file-linux.zip"),
                )
            ),
            (
                new_expression(
                    actual_system,
                    None,
                    file_name,
                    {"name": file_name},
                    msg="Default macOS mappings",
                )
                for actual_system, file_name in product(
                    ("Darwin", "darwin", "MacOS", "macos", "macOS"),
                    (
                        "file-Darwin.zip",
                        "file-darwin.zip",
                        "file-MacOS.zip",
                        "file-macos.zip",
                    ),
                )
            ),
            (
                new_expression(
                    actual_system,
                    None,
                    file_name,
                    {"name": file_name},
                    msg="Default Windows mappings",
                )
                for actual_system, file_name in product(
                    ("Windows", "windows", "win", "win32", "win64"),
                    (
                        "file-Windows.zip",
                        "file-windows.zip",
                        "file-win.zip",
                        "file-win32.zip",
                        "file-win64.zip",
                    ),
                )
            ),
        )
        for test_case in test_cases:
            test_case.run(first_result(run_with_context))

    def test_match_asset_archs(self, *_):
        # Input variations:
        # Case 1: Arch mapping provided
        # Case 2: No arch mapping provided

        # Test: We want to show that default matching will work out of the box with some values for the current machine
        # Test: We want to show that non-standard mappings will always work if provided manually

        def run_with_context(actual_arch: str, *args, **kwargs):
            with patch("platform.machine", return_value=actual_arch):
                return release_gitter.match_asset(*args, **kwargs)

        def new_expression(
            actual_arch: str,
            arch_mapping: dict[str, str] | None,
            file_name: str,
            expected: dict[str, str],
            exception: type[Exception] | None = None,
            msg: str | None = None,
        ):
            release = {
                "name": "v1.0.0",
                "tag_name": "v1.0.0",
                "assets": [{"name": file_name}],
            }
            return TestExpression(
                self,
                [actual_arch, release, "file-{arch}.zip"],
                {"arch_mapping": arch_mapping},
                expected,
                exception,
                msg,
            )

        test_cases = chain(
            [
                new_expression(
                    "Earth",
                    None,
                    "file-Earth.zip",
                    {"name": "file-Earth.zip"},
                    msg="Current arch always included as an exact match synonym",
                ),
                new_expression(
                    "x86_64",
                    {"x86_64": "jumanji"},
                    "file-jumanji.zip",
                    {"name": "file-jumanji.zip"},
                    msg="Non-standard arch mapping works",
                ),
                new_expression(
                    "x86_64",
                    {},
                    "file-arm.zip",
                    {},
                    ValueError,
                    msg="No matching arch",
                ),
            ],
            # Test default mappings
            (
                new_expression(
                    actual_arch,
                    None,
                    file_name,
                    {"name": file_name},
                    msg="Default arm mappings",
                )
                for actual_arch, file_name in product(
                    ("arm",),
                    ("file-arm.zip",),
                )
            ),
            (
                new_expression(
                    actual_arch,
                    None,
                    file_name,
                    {"name": file_name},
                    msg="Default amd64 mappings",
                )
                for actual_arch, file_name in product(
                    ("amd64", "x86_64", "AMD64"),
                    ("file-amd64.zip", "file-x86_64.zip"),
                )
            ),
            (
                new_expression(
                    actual_arch,
                    None,
                    file_name,
                    {"name": file_name},
                    msg="Default arm64 mappings",
                )
                for actual_arch, file_name in product(
                    ("arm64", "aarch64", "armv8b", "armv8l"),
                    (
                        "file-arm64.zip",
                        "file-aarch64.zip",
                        "file-armv8b.zip",
                        "file-armv8l.zip",
                    ),
                )
            ),
            (
                new_expression(
                    actual_arch,
                    None,
                    file_name,
                    {"name": file_name},
                    msg="Default x86 mappings",
                )
                for actual_arch, file_name in product(
                    ("x86", "i386", "i686"),
                    ("file-x86.zip", "file-i386.zip", "file-i686.zip"),
                )
            ),
        )
        for test_case in test_cases:
            test_case.run(first_result(run_with_context))


if __name__ == "__main__":
    unittest.main()
