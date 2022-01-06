# release-gitter

Easily download releases from sites like Github and Gitea

## Original repo

Originally hosted at https://git.iamthefij.com/iamthefij/release-gitter.git

## Installation

From pypi `pip install release-gitter`

Alternatively, you can download `release_gitter.py` and run that file as long as you have `requests` installed.

## Usage

At minimum, release-gitter can be used to download the latest release file for a given repo using something like the following:

    release-gitter --git-url https://github.com/coder/super-tool "super-tool-{version}-{system}-{arch}"

Originally created for downloading binary releases for [pre-commit](https://pre-commit.com) hooks, so it also has features
to detect the remote repo automatically using `git remote get-url origin`, as well as detecting the currently checked out version
by parsing metadata files (currently only `Cargo.toml`).

In practice, it means that for a project like [StyLua](https://github.com/JohnnyMorganz/StyLua), when run within the repo one would only need to provide:

    release-gitter --extract-files "stylua" --exec "chmod +x stylua" \
        --map-system Windows=win64 --map-system Darwin=macos --map-system=linux=Linux \
        "stylua-{version}-{system}.zip"

And `release-gitter` will get the release version from the `Cargo.toml`, get the URL from the `git remote`, call the Github API and look for a release matching the templated file name, extract the `stylua` file from the archive, and then make it executable.

This allows a single command to be run from a checked out repo from pre-commit on any system to fetch the appropriate binary.

Additionally, it can be used to simplify install instructions for users by providing the `--git-url` option so it can be run from outside the repo.

Full usage is as follows:

    usage: release-gitter [-h] [--hostname HOSTNAME] [--owner OWNER] [--repo REPO]
                          [--git-url GIT_URL] [--version VERSION]
                          [--map-system MAP_SYSTEM] [--map-arch MAP_ARCH]
                          [--exec EXEC] [--extract-files EXTRACT_FILES]
                          [--extract-all] [--url-only]
                          format

    positional arguments:
      format                Format template to match assets. Eg
                            `foo-{version}-{system}-{arch}.zip`

    optional arguments:
      -h, --help            show this help message and exit
      --hostname HOSTNAME   Git repository hostname
      --owner OWNER         Owner of the repo. If not provided, it will be
                            retrieved from the git url
      --repo REPO           Repo name. If not provided, it will be retrieved from
                            the git url
      --git-url GIT_URL     Git repository URL. Overrides `git remote` detection,
                            but not command line options for hostname, owner, and
                            repo
      --version VERSION     Release version to download. If not provied, it will
                            look for project metadata
      --map-system MAP_SYSTEM, -s MAP_SYSTEM
                            Map a platform.system() value to a custom value
      --map-arch MAP_ARCH, -a MAP_ARCH
                            Map a platform.machine() value to a custom value
      --exec EXEC, -c EXEC  Shell commands to execute after download or extraction
      --extract-files EXTRACT_FILES, -e EXTRACT_FILES
                            A list of file name to extract from downloaded archive
      --extract-all, -x     Shell commands to execute after download or extraction
      --url-only            Only print the URL and do not download
