from __future__ import annotations

import shutil
import subprocess
import venv
from dataclasses import dataclass
from pathlib import Path
from unittest import TestCase

ITEST_VENV_PATH = Path("venv-itest")


@dataclass
class PackageTestCase:
    name: str
    git_url: str
    version_args: str | None = None
    version_output: str | None = None


PACKAGE_TEST_CASES = [
    PackageTestCase(
        "stylua",
        "git+https://github.com/JohnnyMorganz/StyLua@v2.3.0",
        "--version",
        "stylua 2.3.0",
    ),
    PackageTestCase(
        "hadolint",
        # Contrived test relying on git tags
        "git+https://github.com/IamTheFij/hadolint@v2.13.1",
        "--version",
        "Haskell Dockerfile Linter 2.13.1",
    ),
    PackageTestCase(
        "hadolint",
        # Contrived test for cabal version
        "git+https://github.com/IamTheFij/hadolint@v2.12.0",
        "--version",
        "Haskell Dockerfile Linter 2.12.0",
    ),
]


class TestPseudoBuilder(TestCase):
    def setUp(self):
        venv.create(
            ITEST_VENV_PATH,
            system_site_packages=False,
            clear=True,
            with_pip=True,
        )
        self.pip_install("-e", ".[builder]")

    def tearDown(self):
        shutil.rmtree(ITEST_VENV_PATH)

    def pip_install(self, *args: str):
        subprocess.run(
            [str(ITEST_VENV_PATH.joinpath("bin", "pip")), "install", *args],
            check=True,
        )

    def test_install_remote_package(self):
        self.assertTrue(ITEST_VENV_PATH.exists())
        self.assertTrue(ITEST_VENV_PATH.joinpath("bin", "python").exists())
        self.assertTrue(ITEST_VENV_PATH.joinpath("bin", "pip").exists())

        for package in PACKAGE_TEST_CASES:
            self.pip_install("--no-index", "--no-build-isolation", package.git_url)

            # Check if the package is installed
            assert ITEST_VENV_PATH.joinpath("bin", package.name).exists()
            # Check if the package has executable permissions
            assert ITEST_VENV_PATH.joinpath("bin", package.name).stat().st_mode & 0o111

            result = subprocess.run(
                [
                    str(ITEST_VENV_PATH.joinpath("bin", package.name)),
                    *(package.version_args.split() if package.version_args else []),
                ],
                capture_output=True,
                text=True,
                check=True,
            )

            if package.version_output:
                self.assertIn(package.version_output, result.stdout)
