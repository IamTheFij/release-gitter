#! /usr/bin/env python3
import argparse
import platform
from collections.abc import Sequence
from dataclasses import dataclass
from io import BytesIO
from mimetypes import guess_type
from pathlib import Path
from subprocess import check_call
from subprocess import check_output
from tarfile import TarFile
from tarfile import TarInfo
from typing import Any
from typing import Optional
from typing import Union
from urllib.parse import urlparse
from zipfile import ZipFile

import requests


# Extract metadata from repo


class InvalidRemoteError(ValueError):
    pass


@dataclass
class GitRemoteInfo:
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


def get_git_remote(git_url: Optional[str] = None) -> GitRemoteInfo:
    """Extract Github repo info from git remote url"""
    if not git_url:
        git_url = (
            check_output(["git", "remote", "get-url", "origin"]).decode("UTF-8").strip()
        )

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

    return GitRemoteInfo(u.hostname, path[1], path[2].removesuffix(".git"))


def get_cargo_version(p: Path) -> str:
    """Extracts cargo version from a Cargo.toml file"""
    with p.open() as f:
        for line in f:
            if line.startswith("version"):
                return line.partition(" = ")[2].strip()[1:-1]

    raise ValueError(f"No version found in {p}")


def get_git_tag(fetch: bool = True) -> Optional[str]:
    if fetch:
        check_call(["git", "fetch", "--tags", "--depth", "1"])

    git_tag = check_output(["git", "describe", "--tags"]).decode("UTF-8").strip()
    return git_tag or None


def read_version(from_tags: bool = False, fetch: bool = False) -> Optional[str]:
    if from_tags:
        return get_git_tag(fetch)

    matchers = {
        "Cargo.toml": get_cargo_version,
    }

    for name, extractor in matchers.items():
        p = Path(name)
        if p.exists():
            return extractor(p)

    # TODO: Log this out to stderr
    # raise ValueError(f"Unknown project type. Didn't find any of {matchers.keys()}")
    return None


# Fetch release and assets from Github


def get_release(
    remote: GitRemoteInfo,
    version: Optional[str] = None
    # TODO: Accept an argument for pre-release
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
        return result.json()[0]

    # Return matching version
    for release in result.json():
        if release["tag_name"].endswith(version):
            return release

    raise ValueError(f"Could not find release version ending in {version}")


def match_asset(
    release: dict[Any, Any],
    format: str,
    version: Optional[str] = None,
    system_mapping: Optional[dict[str, str]] = None,
    arch_mapping: Optional[dict[str, str]] = None,
) -> dict[Any, Any]:
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
        if "{version}" in format:
            raise ValueError(
                "No version provided or found in release name but is in format"
            )
        else:
            # This should never happen, but since version isn't used anywhere, we can make it an empty string
            version = ""

    system = platform.system()
    if system_mapping:
        system = system_mapping.get(system, system)

    arch = platform.machine()
    if arch_mapping:
        arch = arch_mapping.get(arch, arch)

    expected_names = {
        format.format(
            version=normalized_version,
            system=system,
            arch=arch,
        )
        for normalized_version in (
            version.lstrip("v"),
            "v" + version if not version.startswith("v") else version,
        )
    }

    for asset in release["assets"]:
        if asset["name"] in expected_names:
            return asset

    raise ValueError(
        f"Could not find asset named {expected_names} on release {release['name']}"
    )


class PackageAdapter:
    """Adapts the names and extractall methods from ZipFile and TarFile classes"""

    def __init__(self, content_type: str, response: requests.Response):
        self._package: Union[TarFile, ZipFile]
        if content_type == "application/zip":
            self._package = ZipFile(BytesIO(response.content))
        elif content_type == "application/x-tar":
            self._package = TarFile(fileobj=response.raw)
        elif content_type in ("application/gzip", "application/x-tar+gzip"):
            self._package = TarFile.open(fileobj=BytesIO(response.content), mode="r:*")
        else:
            raise ValueError(f"Unknown or unsupported content type {content_type}")

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
        path: Optional[Path],
        members: Optional[list[str]],
    ) -> list[str]:
        """Extract all or a subset of files from the package

        If the `file_names` list is empty, all files will be extracted"""
        if path is None:
            path = Path.cwd()
        if not members:
            self._package.extractall(path=path)
            return self.get_names()

        if isinstance(self._package, ZipFile):
            self._package.extractall(path=path, members=members)
        if isinstance(self._package, TarFile):
            self._package.extractall(
                path=path, members=(TarInfo(name) for name in members)
            )

        return members


def download_asset(
    asset: dict[Any, Any],
    extract_files: Optional[list[str]] = None,
    destination: Optional[Path] = None,
) -> list[Path]:
    if destination is None:
        destination = Path.cwd()

    result = requests.get(asset["browser_download_url"])

    content_type = asset.get(
        "content_type",
        guess_type(asset["name"]),
    )
    if extract_files is not None:
        if isinstance(content_type, tuple):
            content_type = "+".join(t for t in content_type if t is not None)
        if not content_type:
            raise TypeError(
                "Cannot extract files from archive because we don't recognize the content type"
            )
        package = PackageAdapter(content_type, result)
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
        values: Union[str, Sequence[Any], None],
        option_string: Optional[str] = None,
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


def parse_args(args: Optional[list[str]] = None) -> argparse.Namespace:
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
        help="Release version to download. If not provied, it will look for project metadata",
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
        "--exec", "-c", help="Shell commands to execute after download or extraction"
    )
    parser.add_argument(
        "--extract-files",
        "-e",
        action="append",
        help="A list of file name to extract from downloaded archive",
    )
    parser.add_argument(
        "--extract-all",
        "-x",
        action="store_true",
        help="Shell commands to execute after download or extraction",
    )
    parser.add_argument(
        "--url-only",
        action="store_true",
        help="Only print the URL and do not download",
    )

    parsed_args = parser.parse_args(args)

    # Merge in fields from args and git remote
    if not all((parsed_args.owner, parsed_args.repo, parsed_args.hostname)):
        remote_info = get_git_remote(parsed_args.git_url)

        def merge_field(a, b, field):
            value = getattr(a, field)
            if value is None:
                setattr(a, field, getattr(b, field))

        for field in ("owner", "repo", "hostname"):
            merge_field(parsed_args, remote_info, field)

    if parsed_args.version is None:
        parsed_args.version = read_version(
            parsed_args.version_git_tag,
            not parsed_args.version_git_no_fetch,
        )

    if parsed_args.extract_all:
        parsed_args.extract_files = []

    return parsed_args


def main():
    args = parse_args()

    release = get_release(
        GitRemoteInfo(args.hostname, args.owner, args.repo), args.version
    )
    asset = match_asset(
        release,
        args.format,
        version=args.version,
        system_mapping=args.map_system,
        arch_mapping=args.map_arch,
    )

    if args.url_only:
        print(asset["browser_download_url"])
        return

    files = download_asset(
        asset,
        extract_files=args.extract_files,
        destination=args.destination,
    )

    print(f"Downloaded {', '.join(str(f) for f in files)}")

    # Optionally execute post command
    if args.exec:
        check_call(args.exec, shell=True)


if __name__ == "__main__":
    main()
