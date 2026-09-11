from __future__ import annotations

import hashlib
import subprocess
from typing import cast

import pytest

from tests.contracts.support import PUBLIC_ROOT, SchemaDocument, load_json, sha256

FROZEN_MANIFEST = PUBLIC_ROOT / "tests" / "contracts" / "frozen-profiles" / "0.1.0.json"


def _manifest() -> SchemaDocument:
    return load_json(FROZEN_MANIFEST)


def _expected_files(manifest: SchemaDocument) -> dict[str, str]:
    files = cast(list[dict[str, object]], manifest["files"])
    return {cast(str, item["path"]): cast(str, item["sha256"]) for item in files}


def test_frozen_profile_matches_embedded_publication_manifest() -> None:
    manifest = _manifest()
    tree_root = PUBLIC_ROOT / cast(str, manifest["tree_path"])
    expected = _expected_files(manifest)
    actual = {path.name for path in tree_root.iterdir() if path.is_file()}
    assert actual == set(expected)
    assert {name: sha256(tree_root / name) for name in sorted(actual)} == expected


def test_frozen_manifest_matches_publication_commit_when_git_object_is_available() -> None:
    manifest = _manifest()
    commit = cast(str, manifest["publication_commit"])
    tree_path = cast(str, manifest["tree_path"])
    object_check = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=PUBLIC_ROOT,
        check=False,
        capture_output=True,
    )
    if object_check.returncode != 0:
        pytest.skip("Publication commit is unavailable; embedded digest enforcement still ran")

    listing = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", commit, "--", tree_path],
        cwd=PUBLIC_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    committed_paths = [line for line in listing.stdout.splitlines() if line]
    expected = _expected_files(manifest)
    assert committed_paths == [f"{tree_path}/{name}" for name in sorted(expected)]

    committed_hashes: dict[str, str] = {}
    for name in sorted(expected):
        blob = subprocess.run(
            ["git", "show", f"{commit}:{tree_path}/{name}"],
            cwd=PUBLIC_ROOT,
            check=True,
            capture_output=True,
        ).stdout
        committed_hashes[name] = hashlib.sha256(blob).hexdigest()
    assert committed_hashes == expected
