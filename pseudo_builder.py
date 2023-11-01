"""
This builder functions as a pseudo builder that instead downloads and installs a binary file using
release-gitter based on a pyproject.toml file. It's a total hack...
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from shutil import copy
from shutil import copytree
from shutil import move

import toml
from wheel.wheelfile import WheelFile

import release_gitter as rg
from release_gitter import removeprefix


PACKAGE_NAME = "pseudo"


@dataclass
class Config:
    format: str
    git_url: str
    hostname: str
    owner: str
    repo: str
    version: str | None = None
    pre_release: bool = False
    version_git_tag: bool = False
    version_git_no_fetch: bool = False
    map_system: dict[str, str] | None = None
    map_arch: dict[str, str] | None = None
    exec: str | None = None
    extract_all: bool = False
    extract_files: list[str] | None = None
    include_extra_files: list[str] | None = None


def download(config: Config) -> list[Path]:
    release = rg.fetch_release(
        rg.GitRemoteInfo(config.hostname, config.owner, config.repo), config.version
    )
    asset = rg.match_asset(
        release,
        config.format,
        version=config.version,
        system_mapping=config.map_system,
        arch_mapping=config.map_arch,
    )

    files = rg.download_asset(asset, extract_files=config.extract_files)

    # Optionally execute post command
    if config.exec:
        rg.check_call(config.exec, shell=True)

    return files


def read_metadata() -> Config:
    config = toml.load("pyproject.toml").get("tool", {}).get("release-gitter")
    if not config:
        raise ValueError("Must have configuration in [tool.release-gitter]")

    git_url = config.pop("git-url", None)
    remote_info = rg.parse_git_remote(git_url)

    args = Config(
        format=config.pop("format"),
        git_url=git_url,
        hostname=config.pop("hostname", remote_info.hostname),
        owner=config.pop("owner", remote_info.owner),
        repo=config.pop("repo", remote_info.repo),
    )

    for key, value in config.items():
        setattr(args, str(key).replace("-", "_"), value)

    if args.version is None:
        args.version = rg.read_version(
            args.version_git_tag,
            not args.version_git_no_fetch,
        )

    if args.extract_all:
        args.extract_files = []

    return args


class _PseudoBuildBackend:
    # Should allow passing args as `--build-option`
    _gitter_args = None

    def prepare_metadata_for_build_wheel(
        self, metadata_directory, config_settings=None
    ):
        # Create a .dist-info directory containing wheel metadata inside metadata_directory. Eg {metadata_directory}/{package}-{version}.dist-info/
        print("Prepare meta", metadata_directory, config_settings)

        metadata = read_metadata()
        version = removeprefix(metadata.version, "v") if metadata.version else "0.0.0"

        # Returns distinfo dir?
        dist_info = Path(metadata_directory) / f"{PACKAGE_NAME}-{version}.dist-info"
        dist_info.mkdir()

        # Write metadata
        pkg_info = dist_info / "METADATA"
        pkg_info.write_text(
            "\n".join(
                [
                    "Metadata-Version: 2.1",
                    f"Name: {PACKAGE_NAME}",
                    f"Version: {version}",
                ]
            )
        )

        # Write wheel info
        wheel_info = dist_info / "WHEEL"
        wheel_info.write_text(
            "\n".join(
                [
                    "Wheel-Version: 1.0",
                    "Root-Is-Purelib: true",
                    "Tag: py2-none-any",
                    "Tag: py3-none-any",
                ]
            )
        )

        return str(dist_info)

    def build_sdist(self, sdist_directory, config_settings=None):
        # Builds a .tar.gz and places it in specified sdist_directory
        # That should contain a toplevel drectory of `name-version` containing source files and the pyproject.toml

        # HACK: This isn't needed or used
        p = Path(sdist_directory + ".dist-info")
        return p

    def build_wheel(
        self, wheel_directory, config_settings=None, metadata_directory=None
    ):
        metadata_directory = Path(metadata_directory)

        metadata = read_metadata()
        version = removeprefix(metadata.version, "v") if metadata.version else "0.0.0"

        wheel_directory = Path(wheel_directory)
        wheel_directory.mkdir(exist_ok=True)

        wheel_scripts = wheel_directory / f"{PACKAGE_NAME}-{version}.data/scripts"
        wheel_scripts.mkdir(parents=True, exist_ok=True)

        copytree(metadata_directory, wheel_directory / metadata_directory.name)

        metadata = read_metadata()
        files = download(metadata)
        for file in files:
            move(file, wheel_scripts / file.name)

        for file_name in metadata.include_extra_files or []:
            file = Path(file_name)
            if Path.cwd() in file.absolute().parents:
                copy(file_name, wheel_scripts / file)
            else:
                raise ValueError(
                    f"Cannot include any path that is not within the current directory: {file_name}"
                )

        print(f"ls {wheel_directory}: {list(wheel_directory.rglob('*'))}")

        wheel_filename = f"{PACKAGE_NAME}-{version}-py2.py3-none-any.whl"
        with WheelFile(wheel_directory / wheel_filename, "w") as wf:
            print("Repacking wheel as {}...".format(wheel_filename), end="")
            # sys.stdout.flush()
            wf.write_files(wheel_directory)

        return wheel_filename


_BACKEND = _PseudoBuildBackend()


prepare_metadata_for_build_wheel = _BACKEND.prepare_metadata_for_build_wheel
build_sdist = _BACKEND.build_sdist
build_wheel = _BACKEND.build_wheel
