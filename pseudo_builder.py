"""
This builder functions as a pseudo builder that instead downloads and installs a binary file using
release-gitter based on a pyproject.toml file. It's a total hack...
"""
from pathlib import Path
from shutil import copytree

import toml
from wheel.wheelfile import WheelFile

import release_gitter as rg


PACKAGE_NAME = "pseudo"


def download(config) -> list[Path]:
    release = rg.get_release(
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


def read_metadata():
    config = toml.load("pyproject.toml").get("tool", {}).get("release-gitter")
    if not config:
        raise ValueError("Must have configuration in [tool.release-gitter]")

    args = []
    for key, value in config.items():
        key = "--" + key
        if key == "--format":
            args += [value]
        elif isinstance(value, dict):
            for sub_key, sub_value in value.items():
                args = [key, f"{sub_key}={sub_value}"] + args
        elif isinstance(value, list):
            for sub_value in value:
                args = [key, sub_value] + args
        else:
            args = [key, value] + args

    return rg.parse_args(args)


class _PseudoBuildBackend:
    # Should allow passing args as `--build-option`
    _gitter_args = None

    def prepare_metadata_for_build_wheel(
        self, metadata_directory, config_settings=None
    ):
        # Createa  .dist-info directory containing wheel metadata inside metadata_directory. Eg {metadata_directory}/{package}-{version}.dist-info/
        print("Prepare meta", metadata_directory, config_settings)

        metadata = read_metadata()
        version = metadata.version.removeprefix("v")

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
        version = metadata.version.removeprefix("v")

        wheel_directory = Path(wheel_directory)
        wheel_directory.mkdir(exist_ok=True)

        wheel_scripts = wheel_directory / f"{PACKAGE_NAME}-{version}.data/scripts"
        wheel_scripts.mkdir(parents=True, exist_ok=True)

        # copytree(metadata_directory, wheel_directory / metadata_directory.name)
        copytree(metadata_directory, wheel_directory / metadata_directory.name)

        metadata = read_metadata()
        files = download(metadata)
        for file in files:
            file.rename(wheel_scripts / file.name)

        print(f"ls {wheel_directory}: {list(wheel_directory.glob('*'))}")

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
