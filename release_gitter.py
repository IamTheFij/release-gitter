#! /usr/bin/env python3
from __future__ import annotations

import argparse
import logging
import platform
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from io import BytesIO
from itertools import product
from mimetypes import guess_type
from pathlib import Path
from subprocess import check_call
from subprocess import check_output
from tarfile import TarFile
from tarfile import TarInfo
from typing import Any
from typing import NamedTuple
from urllib.parse import urlparse
from zipfile import ZipFile

import requests

__version__ = "3.0.4"


logging.basicConfig(level=logging.WARNING)


class UnsupportedContentTypeError(ValueError):
    pass


class InvalidRemoteError(ValueError):
    pass


def removeprefix(s: str, pre: str) -> str:
    # Duplicate str.removeprefix for py<3.9
    try:
        return s.removeprefix(pre)  # type: ignore
    except AttributeError:
        # Py < 3.9
        return s[len(pre) :] if s and s.startswith(pre) else s


def removesuffix(s: str, suf: str) -> str:
    # Duplicate str.removesuffix for py<3.9
    try:
        return s.removesuffix(suf)  # type: ignore
    except AttributeError:
        # Py < 3.9
        return s[: -len(suf)] if s and s.endswith(suf) else s


SYSTEM_SYNONYMS: list[list[str]] = [
    ["Darwin", "darwin", "MacOS", "macos", "macOS"],
    ["Windows", "windows", "win", "win32", "win64"],
    ["Linux", "linux"],
]

ARCH_SYNONYMS: list[list[str]] = [
    ["arm"],
    ["x86_64", "amd64", "AMD64"],
    ["arm64", "aarch64", "armv8b", "armv8l"],
    ["x86", "i386", "i686"],
]


def get_synonyms(value: str, thesaurus: list[list[str]]) -> list[str]:
    """Gets synonym list for a given value."""
    results = [value]

    for l in thesaurus:
        if value in l:
            results += l

    return results


class MatchedValues(NamedTuple):
    version: str
    system: str
    arch: str


@dataclass
class GitRemoteInfo:
    """Extracts information about a repository"""

    hostname: str
    owner: str
    repo: str

    def get_releases_url(self):
        """Gets API url for releases based on hostname and repo info

        Currently only supporting Github and Gitea APIs"""
        if self.hostname == "github.com":
            return (
                f"https://api.{self.hostname}/repos/{self.owner}/{self.repo}/releases"
            )

        # Try to detect an api
        swagger_uri = f"https://{self.hostname}/swagger.v1.json"
        result = requests.get(swagger_uri)
        result.raise_for_status()
        swag = result.json()

        # Look for releases API
        gitea_releases_template = "/repos/{owner}/{repo}/releases"
        if gitea_releases_template in swag["paths"]:
            # TODO: Might be helpful to validate fields that are referenced in responses too
            return "".join(
                (
                    "https://",
                    self.hostname,
                    swag["basePath"],
                    gitea_releases_template.format(owner=self.owner, repo=self.repo),
                )
            )

        raise InvalidRemoteError(
            f"Could not find a valid API on host {self.hostname}. Only Github and Gitea APIs are supported"
        )


def read_git_remote() -> str:
    """Reads the git remote url from the origin"""
    return check_output(["git", "remote", "get-url", "origin"]).decode("UTF-8").strip()


def parse_git_url(git_url: str) -> GitRemoteInfo:
    """Extract Github repo info from a git remote url"""
    # Normalize Github ssh url as a proper URL
    if git_url.startswith("git@github.com:"):
        git_ssh_parts = git_url.partition(":")
        if not all(git_ssh_parts):
            raise InvalidRemoteError(
                f"Could not parse URL {git_url}. Is this an ssh url?"
            )
        git_url = f"ssh://{git_ssh_parts[0]}/{git_ssh_parts[2]}"

    u = urlparse(git_url)
    if not u.hostname:
        raise ValueError("Not an https url on origin")

    path = u.path.split("/")
    if len(path) < 3 or not all(path[1:3]):
        raise InvalidRemoteError(
            f"{path[1:3]} Could not parse owner and repo from URL {git_url}"
        )

    return GitRemoteInfo(u.hostname, path[1], removesuffix(path[2], ".git"))


def parse_cargo_version(p: Path) -> str:
    """Extracts cargo version from a Cargo.toml file"""
    with p.open() as f:
        for line in f:
            if line.startswith("version"):
                return line.partition(" = ")[2].strip()[1:-1]

    raise ValueError(f"No version found in {p}")


def read_git_tag(fetch: bool = True) -> str | None:
    """Get local git tag for current repo

    fetch: optionally fetch tags with depth of 1 from remote"""
    if fetch:
        check_call(["git", "fetch", "--tags", "--depth", "1"])

    git_tag = check_output(["git", "describe", "--tags"]).decode("UTF-8").strip()
    return git_tag or None


def read_version(from_tags: bool = False, fetch: bool = False) -> str | None:
    """Read version information from file or from git"""
    if from_tags:
        logging.debug("Reading version from git tag")
        return read_git_tag(fetch)

    matchers = {
        "Cargo.toml": parse_cargo_version,
    }

    for name, extractor in matchers.items():
        p = Path(name)
        if p.exists():
            logging.debug(f"Reading version from {p}")
            return extractor(p)

    logging.warning(
        "Unknown local project version. Didn't find any of %s", set(matchers.keys())
    )

    return None


def fetch_release(
    remote: GitRemoteInfo,
    version: str | None = None,
    pre_release=False,
) -> dict[Any, Any]:
    """Fetches a release object from a Github repo

    If a version number is provided, that version will be retrieved. Otherwise, the latest
    will be returned.
    """
    result = requests.get(
        remote.get_releases_url(),
        # headers={"Accept": "application/vnd.github.v3+json"},
        headers={"Accept": "application/json"},
    )
    result.raise_for_status()

    # Return the latest if requested
    if version is None or version == "latest":
        logging.debug("Looking for latest release")

        for release in result.json():
            if release["prerelease"] and not pre_release:
                continue

            return release

    # Return matching version
    for release in result.json():
        if release["tag_name"].endswith(version):
            logging.debug(f"Found release {release['name']} matching version {version}")

            return release

    raise ValueError(
        f"Could not find release version ending in {version}."
        f"{ ' Is it a pre-release?' if not pre_release else ''}"
    )


def match_asset(
    release: dict[Any, Any],
    format: str,
    version: str | None = None,
    system_mapping: dict[str, str] | None = None,
    arch_mapping: dict[str, str] | None = None,
) -> tuple[dict[Any, Any], MatchedValues]:
    """Accepts a release and searches for an appropriate asset attached using
    a provided template and some alternative mappings for version, system, and machine info

    Args
        `release`: A dict release value from the Github API
        `format`: is a python format string allowing for "{version}", "{system}", and "{arch}"
        `version`: the version to use when matching, default will be the name of the release
        `system_mapping`: alternative values for results returned from `platform.system()`
        `arch_mapping`: alternative values for results returned from `platform.machine()`

    Note: Some fuzziness is built into the {version} template variable. We will try to match against
    the version as is, prefixed with a 'v' and have 'v' stripped from the beginning.

    Eg. An example from an arm64 Mac:

        match_asset({"name": "v1.0.0", ...}, `foo-{version}-{system}-{arch}.zip`)

    Matches against:
        * "foo-v1.0.0-Darwin-arm64.zip"
        * "foo-1.0.0-Darwin-arm64.zip"

    Now, instead of Darwin, maybe you want to use `macOS`. For that you'd provide a
    `system_mapping`.

        match_asset({"name": "v1.0.0", ...}, `foo-{version}-{system}-{arch}.zip, system_mapping={"Darwin": "macOS"})

    Matches against:
        * "foo-v1.0.0-macOS-arm64.zip"
        * "foo-1.0.0-macOS-arm64.zip"
    """
    if version is None:
        version = release["tag_name"]

    # This should never really happen
    if version is None:
        raise ValueError("No version provided or found in release name.")

    system = platform.system()
    if system_mapping:
        systems = [system_mapping.get(system, system)]
    else:
        systems = get_synonyms(system, SYSTEM_SYNONYMS)

    arch = platform.machine()
    if arch_mapping:
        archs = [arch_mapping.get(arch, arch)]
    else:
        archs = get_synonyms(arch, ARCH_SYNONYMS)

    expected_names = {
        format.format(
            version=version_opt,
            system=system_opt,
            arch=arch_opt,
        ): MatchedValues(version=version_opt, system=system_opt, arch=arch_opt)
        for version_opt, system_opt, arch_opt in product(
            (
                version.lstrip("v"),
                "v" + version if not version.startswith("v") else version,
            ),
            systems,
            archs,
        )
    }

    for asset in release["assets"]:
        if asset["name"] in expected_names:
            return (asset, expected_names[asset["name"]])

    raise ValueError(
        f"Could not find asset named {expected_names} on release {release['name']}"
    )


class PackageAdapter:
    """Adapts the names and extractall methods from ZipFile and TarFile classes"""

    def __init__(self, content_type: str, response: requests.Response):
        self._package: TarFile | ZipFile
        if content_type in (
            "application/zip",
            "application/x-zip-compressed",
        ):
            logging.debug("Opening zip file from response content")

            self._package = ZipFile(BytesIO(response.content))
        elif content_type == "application/x-tar":
            logging.debug("Opening tar file from response content")

            self._package = TarFile(fileobj=response.raw)
        elif content_type in (
            "gzip",
            "application/gzip",
            "application/x-tar+gzip",
            "application/x-tar+xz",
            "application/x-compressed-tar",
        ):
            logging.debug("Opening compressed tar file from response content")

            self._package = TarFile.open(fileobj=BytesIO(response.content), mode="r:*")
        else:
            raise UnsupportedContentTypeError(
                f"Unknown or unsupported content type {content_type}"
            )

    def get_names(self) -> list[str]:
        """Get list of all file names in package"""
        if isinstance(self._package, ZipFile):
            return self._package.namelist()

        if isinstance(self._package, TarFile):
            return self._package.getnames()

        raise ValueError(
            f"Unknown package type, cannot extract from {type(self._package)}"
        )

    def extractall(
        self,
        path: Path | None,
        members: list[str] | None,
    ) -> list[str]:
        """Extract all or a subset of files from the package

        If the `file_names` list is empty, all files will be extracted"""
        if path is None:
            path = Path.cwd()

        if not members:
            logging.debug("Extracting all members to %s", path)

            self._package.extractall(path=path)

            return self.get_names()

        # TODO: Use walrus operator when dropping 3.7 support
        missing_members = set(members) - set(self.get_names())
        if missing_members:
            raise ValueError(f"Missing members: {missing_members}")

        logging.debug("Extracting members %s to %s", members, path)

        if isinstance(self._package, ZipFile):
            self._package.extractall(path=path, members=members)
        if isinstance(self._package, TarFile):
            self._package.extractall(
                path=path, members=(self._package.getmember(name) for name in members)
            )

        return members


def get_asset_package(
    asset: dict[str, Any], result: requests.Response
) -> PackageAdapter:
    possible_content_types = (
        asset.get("content_type"),
        "+".join(t for t in guess_type(asset["name"]) if t is not None),
    )
    for content_type in possible_content_types:
        if not content_type:
            continue

        try:
            return PackageAdapter(content_type, result)
        except UnsupportedContentTypeError:
            continue
    else:
        raise UnsupportedContentTypeError(
            f"Cannot extract files from archive because we don't recognize the content types {possible_content_types}"
        )


def download_asset(
    asset: dict[Any, Any],
    extract_files: list[str] | None = None,
    destination: Path | None = None,
) -> list[Path]:
    """Download asset from entity passed in

    Extracts files from archives if provided. Any empty list will extract all files

    Args
        `asset`: asset dictionary as returned from API
        `extract_files`: optional list of file paths to extract. An empty list will extract all
        `destination`: destination directory to put the downloaded assset

    Returns
        list of Path objects containing all extracted files
    """
    if destination is None:
        destination = Path.cwd()

    result = requests.get(asset["browser_download_url"])

    if extract_files is not None:
        logging.info("Extracting package %s", asset["name"])
        package = get_asset_package(asset, result)
        extract_files = package.extractall(path=destination, members=extract_files)

        return [destination / name for name in extract_files]

    file_name = destination / asset["name"]
    with open(file_name, "wb") as f:
        f.write(result.content)

    return [file_name]


class MapAddAction(argparse.Action):
    def __call__(
        self,
        _: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[Any] | None,
        option_string: str | None = None,
    ):
        # Validate that required value has something
        if self.required and not values:
            raise argparse.ArgumentError(
                self, f"Did not provide required argument {option_string}"
            )

        # Get and initialize the destination
        dest = getattr(namespace, self.dest)
        if dest is None:
            dest = {}

        # Parse values
        if values is not None:
            if isinstance(values, str):
                values = (values,)
            for value in values:
                if "=" not in value:
                    raise argparse.ArgumentError(
                        self,
                        f"Value needs to be in the form `key=value` and received {value}",
                    )
                parts = value.partition("=")
                dest[parts[0]] = parts[2]

        # Set dest value
        setattr(namespace, self.dest, dest)


def _parse_args(args: list[str] | None = None) -> argparse.Namespace:
    logging.debug("Parsing arguments: %s", args)
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "format",
        help="Format template to match assets. Eg. `foo-{version}-{system}-{arch}.zip`",
    )
    parser.add_argument(
        "destination",
        metavar="DEST",
        nargs="?",
        type=Path,
        default=Path.cwd(),
        help="Destination directory. Defaults to current directory",
    )
    parser.add_argument(
        "-v", action="count", help="verbose or debug logging", default=0
    )
    parser.add_argument(
        "--hostname",
        help="Git repository hostname",
    )
    parser.add_argument(
        "--owner",
        help="Owner of the repo. If not provided, it will be retrieved from the git url",
    )
    parser.add_argument(
        "--repo",
        help="Repo name. If not provided, it will be retrieved from the git url",
    )
    parser.add_argument(
        "--git-url",
        help="Git repository URL. Overrides `git remote` detection, but not command line options for hostname, owner, and repo",
    )
    parser.add_argument(
        "--version",
        help="Release version to download. If not provided, it will look for project metadata",
    )
    parser.add_argument(
        "--prerelease",
        action="store_true",
        help="Include pre-release versions in search",
    )
    parser.add_argument(
        "--version-git-tag",
        "-t",
        action="store_true",
        help="Get the release version from a git tag",
    )
    parser.add_argument(
        "--version-git-no-fetch",
        action="store_true",
        help="Shallow fetch tags prior to checking versions",
    )
    parser.add_argument(
        "--map-system",
        "-s",
        action=MapAddAction,
        help="Map a platform.system() value to a custom value",
    )
    parser.add_argument(
        "--map-arch",
        "-a",
        action=MapAddAction,
        help="Map a platform.machine() value to a custom value",
    )
    parser.add_argument(
        "--exec",
        "-c",
        help="Shell commands to execute after download or extraction. {} will be expanded to the downloaded asset name.",
    )
    parser.add_argument(
        "--extract-files",
        "-e",
        action="append",
        help="A list of file names to extract from the downloaded archive",
    )
    parser.add_argument(
        "--extract-all",
        "-x",
        action="store_true",
        help="Extract all files from the downloaded archive",
    )
    parser.add_argument(
        "--url-only",
        action="store_true",
        help="Only print the URL and do not download",
    )
    parser.add_argument(
        "--use-temp-dir",
        action="store_true",
        help="Use a temporary directory as the destination",
    )

    parsed_args = parser.parse_args(args)

    # Merge in fields from args and git remote
    if not all((parsed_args.owner, parsed_args.repo, parsed_args.hostname)):
        # Check to see if a git url was provided. If not, we use local directory git remote
        if parsed_args.git_url is None:
            parsed_args.git_url = read_git_remote()

            # If using a local repo, try to determine version from project files
            if parsed_args.version is None:
                parsed_args.version = read_version(
                    parsed_args.version_git_tag,
                    not parsed_args.version_git_no_fetch,
                )

        # Get parts from git url
        remote_info = parse_git_url(parsed_args.git_url)

        def merge_field(a, b, field):
            value = getattr(a, field)
            if value is None:
                setattr(a, field, getattr(b, field))

        for field in ("owner", "repo", "hostname"):
            merge_field(parsed_args, remote_info, field)

    if parsed_args.extract_all:
        parsed_args.extract_files = []

    if parsed_args.use_temp_dir:
        parsed_args.destination = Path(tempfile.mkdtemp())

    return parsed_args


def download_release(
    remote_info: GitRemoteInfo,
    destination: Path,
    format: str,
    version: str | None = None,
    system_mapping: dict[str, str] | None = None,
    arch_mapping: dict[str, str] | None = None,
    extract_files: list[str] | None = None,
    pre_release=False,
    exec: str | None = None,
) -> list[Path]:
    """Convenience method for fetching, downloading, and extracting a release

    This is slightly different than running off the commandline, it will execute the shell script
    from the destination directory, not the current working directory.
    """
    release = fetch_release(
        remote_info,
        version=version,
        pre_release=pre_release,
    )
    asset, matched_values = match_asset(
        release,
        format,
        version=version,
        system_mapping=system_mapping,
        arch_mapping=arch_mapping,
    )

    format_fields = dict(
        asset_name=asset["name"],
        **matched_values._asdict(),
    )

    formatted_files = (
        [file.format(**format_fields) for file in extract_files]
        if extract_files is not None
        else None
    )

    files = download_asset(
        asset,
        extract_files=formatted_files,
        destination=destination,
    )

    if exec:
        check_call(
            exec.format(asset["name"], **format_fields), shell=True, cwd=destination
        )

    return files


def main():
    args = _parse_args()

    logging.getLogger().setLevel(30 - 10 * args.v)

    # Fetch the release
    release = fetch_release(
        GitRemoteInfo(args.hostname, args.owner, args.repo),
        version=args.version,
        pre_release=args.prerelease,
    )

    logging.debug("Found release: %s", release["name"])

    version = args.version or release["tag_name"]

    logging.debug("Release version: %s", version)

    # Find the asset to download using mapping rules
    asset, matched_values = match_asset(
        release,
        args.format,
        version=version,
        system_mapping=args.map_system,
        arch_mapping=args.map_arch,
    )

    logging.info(f"Downloading {asset['name']} from release {release['name']}")

    if args.url_only:
        print(asset["browser_download_url"])
        return

    format_fields = dict(
        asset_name=asset["name"],
        **matched_values._asdict(),
    )

    # Format files to extract with version info, as this is sometimes included
    formatted_files = (
        [file.format(**format_fields) for file in args.extract_files]
        if args.extract_files is not None
        else None
    )

    files = download_asset(
        asset,
        extract_files=formatted_files,
        destination=args.destination,
    )

    print(f"Downloaded {', '.join(str(f) for f in files)}")

    # Optionally execute post command
    if args.exec:
        check_call(
            args.exec.format(asset["name"], **format_fields),
            shell=True,
            cwd=args.destination,
        )


if __name__ == "__main__":
    main()
