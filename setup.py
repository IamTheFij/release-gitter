from codecs import open
from os import path

from setuptools import find_packages
from setuptools import setup

here = path.abspath(path.dirname(__file__))

# Get the long description from the README file
with open(path.join(here, "README.md"), encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="release-gitter",
    version="0.4.0",
    description="Easily download releases from sites like Github and Gitea",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://git.iamthefij.com/iamthefij/release-gitter.git",
    download_url=(
        "https://git.iamthefij.com/iamthefij/release-gitter.git/archive/master.tar.gz"
    ),
    author="iamthefij",
    author_email="",
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
    ],
    keywords="",
    py_modules=["release_gitter", "pseudo_builder"],
    install_requires=["requests"],
    extras_require={"builder": ["toml", "wheel"]},
    entry_points={
        "console_scripts": [
            "release-gitter=release_gitter:main",
        ],
    },
)
