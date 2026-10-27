"""Validate release tags and distribution identities before publication."""

from __future__ import annotations

import argparse
import re
import sys
import tarfile
import tomllib
import zipfile
from datetime import date
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


def release_notes(changelog: str, version: Version) -> str:
    """Extract one dated Markdown version section without consuming adjacent releases."""
    lines = changelog.splitlines(keepends=True)
    headings = []
    fence = None
    for index, line in enumerate(lines):
        if fence is not None:
            if re.fullmatch(rf" {{0,3}}{re.escape(fence[0])}{{{fence[1]},}}\s*", line):
                fence = None
            continue
        opening = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if opening:
            fence = (opening[1][0], len(opening[1]))
        elif re.match(r"^##(?:[ \t]+|$)", line):
            headings.append((index, line.strip()))
    if fence is not None:
        raise ValueError("Unclosed code fence in changelog")
    matches = [
        position
        for position, (_, heading) in enumerate(headings)
        if re.match(rf"^##[ \t]+\[{re.escape(str(version))}\](?:[ \t]|$)", heading)
    ]
    if len(matches) != 1:
        raise ValueError(f"Changelog must contain exactly one section for {version}")
    position = matches[0]
    start, heading = headings[position]
    dated = re.fullmatch(r"##[ \t]+\[[^\]]+\][ \t]+-[ \t]+(\d{4}-\d{2}-\d{2})", heading)
    if dated is None:
        raise ValueError(f"Changelog section {version} requires a YYYY-MM-DD release date")
    date.fromisoformat(dated[1])
    end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
    body = "".join(lines[start + 1 : end]).strip("\r\n")
    visible = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL)
    substantive = any(
        line.strip(" \t-*+") and not re.match(r"^\s*(?:#{1,6}\s|`{3,}|~{3,}|\[[^\]]+\]:)", line)
        for line in visible.splitlines()
    )
    if not substantive:
        raise ValueError(f"Changelog section {version} has no substantive release notes")
    return body + "\n"


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
    parser.add_argument("--changelog", type=Path, default=Path("CHANGELOG.md"))
    parser.add_argument("--notes-output", type=Path)
    args = parser.parse_args(argv)
    try:
        project = tomllib.loads(args.project.read_text(encoding="utf-8"))["project"]
        version = check_tag(args.tag, project)
        notes = release_notes(args.changelog.read_text(encoding="utf-8"), version)
        if args.dist is not None:
            check_distributions(args.dist, project)
        if args.notes_output is not None:
            args.notes_output.write_text(notes, encoding="utf-8", newline="\n")
    except (OSError, ValueError, KeyError, tarfile.TarError, zipfile.BadZipFile) as exc:
        print(f"Release validation failed: {exc}", file=sys.stderr)
        return 1
    print(f"version={version}")
    print(f"prerelease={str(version.is_prerelease or version.is_devrelease).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
