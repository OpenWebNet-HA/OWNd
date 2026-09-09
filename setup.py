#!/usr/bin/env python3

""" PyPi setup file for OWNd. """

import re
from pathlib import Path

import setuptools


version_match = re.search(
    r'^__version__ = "(?P<version>[^"]+)"$',
    Path("OWNd/__init__.py").read_text(encoding="utf-8"),
    re.MULTILINE,
)
if version_match is None:
    raise RuntimeError("Unable to find OWNd package version")

with open("README.md", encoding="utf-8", mode="r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="OWNd",
    version=version_match.group("version"),
    author="anotherjulien",
    url="https://github.com/OpenWebNet-HA/OWNd",
    author_email="yetanotherjulien@gmail.com",
    description="Python interface for the OpenWebNet protocol",
    license="LGPL-3.0-only",
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3.8",
        "Operating System :: OS Independent",
    ],
    install_requires=["aiohttp", "pytz", "python-dateutil"],
    python_requires=">=3.8",
)
