import unittest
from typing import Any
from typing import Callable
from typing import NamedTuple
from typing import Optional
from unittest.mock import MagicMock
from unittest.mock import patch

import requests

import release_gitter


class TestExpression(NamedTuple):
    t: unittest.TestCase
    args: list[Any]
    kwargs: dict[str, Any]
    expected: Any
    exception: Optional[type[Exception]]

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
            test_case.run(release_gitter.get_git_remote)

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


if __name__ == "__main__":
    unittest.main()
