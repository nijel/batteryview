"""Release validation uses invented metadata and archives, without publishing."""

import importlib
import io
import tarfile
import zipfile

import pytest


@pytest.fixture
def release(monkeypatch):
    from pathlib import Path

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("check_release")


@pytest.mark.parametrize("version", ["1.2.3", "1.2.3rc1", "1.2.3.dev1", "1.2.3.post1"])
def test_release_tag_must_match_declared_version(release, version):
    assert str(release.check_tag(f"v{version}", {"version": version})) == version
    with pytest.raises(ValueError, match="exact"):
        release.check_tag("v1.2.4", {"version": version})
    with pytest.raises(ValueError, match="exact"):
        release.check_tag(version, {"version": version})


def test_release_rejects_local_and_invalid_versions(release):
    with pytest.raises(ValueError, match="local"):
        release.check_tag("v1.2.3+local", {"version": "1.2.3+local"})
    with pytest.raises(ValueError):
        release.check_tag("vnot-a-version", {"version": "not-a-version"})


def distributions(path, *, name="sample-tools", version="1.2.3"):
    metadata = f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\n".encode()
    wheel = path / "sample_tools-1.2.3-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("sample_tools-1.2.3.dist-info/METADATA", metadata)
    with tarfile.open(path / "sample_tools-1.2.3.tar.gz", "w:gz") as archive:
        info = tarfile.TarInfo("sample_tools-1.2.3/PKG-INFO")
        info.size = len(metadata)
        archive.addfile(info, io.BytesIO(metadata))
    return wheel


def test_release_checks_both_filename_and_metadata_identities(release, tmp_path):
    project = {"name": "sample-tools", "version": "1.2.3"}
    wheel = distributions(tmp_path)
    release.check_distributions(tmp_path, project)
    with pytest.raises(ValueError, match="identity"):
        release.check_distributions(tmp_path, {**project, "version": "1.2.4"})
    distributions(tmp_path, version="1.2.4")
    with pytest.raises(ValueError, match="identity"):
        release.check_distributions(tmp_path, project)
    distributions(tmp_path, name="different-project")
    with pytest.raises(ValueError, match="identity"):
        release.check_distributions(tmp_path, project)
    distributions(tmp_path)
    wheel.rename(tmp_path / "sample_tools-1.2.4-py3-none-any.whl")
    with pytest.raises(ValueError, match="identity"):
        release.check_distributions(tmp_path, project)


def test_release_requires_exactly_two_distribution_files(release, tmp_path):
    project = {"name": "sample-tools", "version": "1.2.3"}
    with pytest.raises(ValueError, match="exactly one"):
        release.check_distributions(tmp_path, project)
    distributions(tmp_path)
    (tmp_path / "unexpected.txt").write_text("synthetic extra file")
    with pytest.raises(ValueError, match="exactly one"):
        release.check_distributions(tmp_path, project)


def test_release_rejects_missing_or_duplicate_metadata(release, tmp_path):
    wheel = distributions(tmp_path)
    with zipfile.ZipFile(wheel, "w"):
        pass
    with pytest.raises(ValueError, match="metadata file"):
        release.check_distributions(tmp_path, {"name": "sample-tools", "version": "1.2.3"})
    with zipfile.ZipFile(wheel, "w") as archive:
        for name in ("a", "b"):
            archive.writestr(f"{name}.dist-info/METADATA", "synthetic metadata")
    with pytest.raises(ValueError, match="metadata file"):
        release.check_distributions(tmp_path, {"name": "sample-tools", "version": "1.2.3"})


@pytest.mark.parametrize("kind", ["missing", "symlink", "wrong-version"])
def test_release_validates_sdist_metadata_independently(release, tmp_path, kind):
    distributions(tmp_path)
    with tarfile.open(tmp_path / "sample_tools-1.2.3.tar.gz", "w:gz") as archive:
        if kind != "missing":
            info = tarfile.TarInfo("sample_tools-1.2.3/PKG-INFO")
            if kind == "symlink":
                info.type = tarfile.SYMTYPE
                info.linkname = "other-file"
                archive.addfile(info)
            else:
                data = b"Name: sample-tools\nVersion: 9.9.9\n"
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
    with pytest.raises(ValueError, match="PKG-INFO|identity"):
        release.check_distributions(tmp_path, {"name": "sample-tools", "version": "1.2.3"})


@pytest.mark.parametrize(
    ("version", "prerelease"), [("1.2.3", "false"), ("1.2.3rc1", "true"), ("1.2.3.dev1", "true")]
)
def test_release_outputs_safe_workflow_metadata(release, tmp_path, capsys, version, prerelease):
    project = tmp_path / "pyproject.toml"
    project.write_text(f'[project]\nname = "sample-tools"\nversion = "{version}"\n')
    assert release.main([f"v{version}", "--project", str(project)]) == 0
    assert capsys.readouterr().out == f"version={version}\nprerelease={prerelease}\n"
    assert release.main(["v9.9.9", "--project", str(project)]) == 1
    captured = capsys.readouterr()
    assert not captured.out and "Release validation failed" in captured.err
