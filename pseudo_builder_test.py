from __future__ import annotations

import shutil
import subprocess
import venv
from pathlib import Path
from unittest import TestCase

ITEST_VENV_PATH = Path("venv-itest")


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

        itest_packages = {
            "stylua": "git+https://github.com/JohnnyMorganz/StyLua",
            "selene": "git+https://github.com/amitds1997/selene",
        }

        for package, source in itest_packages.items():
            self.pip_install("--no-index", "--no-build-isolation", source)
            # Check if the package is installed
            assert ITEST_VENV_PATH.joinpath("bin", package).exists()
            # Check if the package has executable permissions
            assert ITEST_VENV_PATH.joinpath("bin", package).stat().st_mode & 0o111
