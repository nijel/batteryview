"""Validate release tags and distribution identities before publication."""

from __future__ import annotations

import argparse
import sys
import tarfile
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path

from packaging.utils import canonicalize_name, parse_sdist_filename, parse_wheel_filename
from packaging.version import Version


def check_tag(tag: str, project: dict) -> Version:
    """Require an exact v-prefixed project version that PyPI can accept."""
    version = Version(project["version"])
    if version.local is not None:
        raise ValueError("PyPI releases cannot use local version identifiers")
    if tag != f"v{project['version']}":
        raise ValueError("Release tag must be v followed by the exact pyproject.toml version")
    return version


def check_distributions(directory: Path, project: dict) -> None:
    """Require one wheel and sdist, with matching filename and metadata identities."""
    files = sorted(directory.iterdir())
    wheels = [p for p in files if p.name.endswith(".whl")]
    sdists = [p for p in files if p.name.endswith(".tar.gz")]
    if len(files) != 2 or len(wheels) != 1 or len(sdists) != 1:
        raise ValueError("Release directory must contain exactly one wheel and one .tar.gz sdist")
    expected_name = canonicalize_name(project["name"])
    expected_version = Version(project["version"])
    for path in files:
        if path in wheels:
            name, version, _, _ = parse_wheel_filename(path.name)
            with zipfile.ZipFile(path) as archive:
                entries = [n for n in archive.namelist() if n.endswith(".dist-info/METADATA")]
                if len(entries) != 1:
                    raise ValueError("Wheel must contain exactly one distribution metadata file")
                metadata = archive.read(entries[0])
        else:
            name, version = parse_sdist_filename(path.name)
            with tarfile.open(path, "r:gz") as archive:
                entries = [m for m in archive.getmembers() if m.name.split("/")[1:] == ["PKG-INFO"]]
                if len(entries) != 1 or not entries[0].isfile():
                    raise ValueError("Sdist must contain exactly one top-level PKG-INFO file")
                stream = archive.extractfile(entries[0])
                if stream is None:
                    raise ValueError("Sdist metadata could not be read")
                metadata = stream.read()
        headers = BytesParser().parsebytes(metadata, headersonly=True)
        if (
            name != expected_name
            or version != expected_version
            or headers.get_all("Name") != [project["name"]]
            or headers.get_all("Version") != [str(expected_version)]
        ):
            raise ValueError(f"Distribution identity does not match pyproject.toml: {path.name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag")
    parser.add_argument("--project", type=Path, default=Path("pyproject.toml"))
    parser.add_argument("--dist", type=Path)
    args = parser.parse_args(argv)
    try:
        project = tomllib.loads(args.project.read_text(encoding="utf-8"))["project"]
        version = check_tag(args.tag, project)
        if args.dist is not None:
            check_distributions(args.dist, project)
    except (OSError, ValueError, KeyError, tarfile.TarError, zipfile.BadZipFile) as exc:
        print(f"Release validation failed: {exc}", file=sys.stderr)
        return 1
    print(f"version={version}")
    print(f"prerelease={str(version.is_prerelease or version.is_devrelease).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
