from __future__ import annotations

import tomllib
from importlib.metadata import version
from pathlib import Path
from typing import Any, cast

import materials_mcp_commons

PUBLIC_ROOT = Path(__file__).parents[2]


def load_pyproject() -> dict[str, Any]:
    raw = tomllib.loads((PUBLIC_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return raw


def test_distribution_metadata() -> None:
    project = cast(dict[str, Any], load_pyproject()["project"])

    assert project["name"] == "materials-mcp-commons"
    assert project["version"] == "0.1.0a0"
    assert project["requires-python"] == ">=3.11,<3.15"
    assert project["license"] == "Apache-2.0"
    assert project["authors"] == [{"name": "Hesham Salama"}]


def test_runtime_version_matches_distribution_metadata() -> None:
    assert materials_mcp_commons.__version__ == "0.1.0a0"
    assert materials_mcp_commons.__version__ == version("materials-mcp-commons")


def test_initial_package_has_no_runtime_dependencies() -> None:
    pyproject = load_pyproject()
    project = cast(dict[str, Any], pyproject["project"])
    build_system = cast(dict[str, Any], pyproject["build-system"])

    assert project["dependencies"] == []
    assert build_system == {
        "requires": ["hatchling>=1.27,<2"],
        "build-backend": "hatchling.build",
    }


def test_initial_source_package_contains_only_the_version_surface() -> None:
    package_root = PUBLIC_ROOT / "src" / "materials_mcp_commons"
    package_files = sorted(
        path.relative_to(package_root).as_posix()
        for path in package_root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )

    assert package_files == ["__init__.py", "py.typed"]


def test_contract_layout_has_exact_versions_and_no_mutable_alias() -> None:
    schema_root = PUBLIC_ROOT / "schemas"
    contract_directories = sorted(path.name for path in schema_root.iterdir() if path.is_dir())

    assert contract_directories == ["0.1.0", "0.2.0"]
    assert not (schema_root / "latest").exists()
    assert (schema_root / "0.1.0" / "schema-index.json").is_file()
    assert (schema_root / "0.2.0" / "schema-index.json").is_file()


def test_contract_corpora_remain_physically_separated() -> None:
    corpus_root = PUBLIC_ROOT / "tests" / "contracts"
    assert (corpus_root / "positive-real").is_dir()
    assert (corpus_root / "negative-generated").is_dir()
    assert not any(
        path.name.startswith("NG-") for path in (corpus_root / "positive-real").rglob("*")
    )
