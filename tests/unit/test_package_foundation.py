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
    assert project["version"] == "0.1.0a12"
    assert project["requires-python"] == ">=3.11,<3.15"
    assert project["license"] == "Apache-2.0"
    assert project["authors"] == [{"name": "Hesham Salama"}]
    assert project["scripts"] == {
        "materials-mcp-conformance": (
            "materials_mcp_commons.plugin_conformance:plugin_conformance_main"
        ),
        "materials-mcp-scaffold": "materials_mcp_commons.authoring:scaffold_main",
    }


def test_runtime_version_matches_distribution_metadata() -> None:
    assert materials_mcp_commons.__version__ == "0.1.0a12"
    assert materials_mcp_commons.__version__ == version("materials-mcp-commons")


def test_base_runtime_and_optional_host_dependencies_are_separated() -> None:
    pyproject = load_pyproject()
    project = cast(dict[str, Any], pyproject["project"])
    build_system = cast(dict[str, Any], pyproject["build-system"])

    assert project["dependencies"] == [
        "jsonschema>=4.26,<5",
        "referencing>=0.37,<0.38",
        "typing-extensions>=4.12,<5",
    ]
    assert project["optional-dependencies"] == {"mcp-host": ["mcp>=2.2,<2.3"]}
    assert build_system == {
        "requires": ["hatchling>=1.27,<2"],
        "build-backend": "hatchling.build",
    }


def test_source_package_contains_only_the_declared_engine_modules() -> None:
    package_root = PUBLIC_ROOT / "src" / "materials_mcp_commons"
    package_files = sorted(
        path.relative_to(package_root).as_posix()
        for path in package_root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )

    assert package_files == [
        "__init__.py",
        "authoring.py",
        "context.py",
        "contracts.py",
        "control.py",
        "dispatch.py",
        "errors.py",
        "lifecycle.py",
        "manifest.py",
        "mcp_host.py",
        "operations.py",
        "plugin_conformance.py",
        "policy.py",
        "py.typed",
        "runs.py",
        "state_recovery.py",
    ]


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
