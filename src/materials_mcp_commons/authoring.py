from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import NoReturn, cast

from .contracts import ContractRegistry, resolve_contained_file
from .errors import AuthoringError, ContractError
from .manifest import LoadedManifest, ManifestLoader

ENGINE_REQUIREMENT = "materials-mcp-commons==0.1.0a13"
DIST_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:[-.][a-z0-9]+)*$")
IMPORT_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
PACKAGE_PATH_PATTERN = re.compile(r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$")
SPDX_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+() -]{0,254}$")
RESOURCE_ROLES = frozenset({"input", "result", "error", "extension"})
REPARSE_POINT = 0x400


def _fail(code: str, message: str) -> NoReturn:
    raise AuthoringError(code, message)


def _required_text(value: object, field_name: str, *, maximum: int = 2048) -> str:
    if type(value) is not str or not value.strip() or len(value) > maximum:
        _fail("invalid-authoring-spec", f"{field_name} must be non-empty bounded text")
    return value


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True, allow_nan=False)


def _json_bytes(value: object) -> bytes:
    try:
        rendered = json.dumps(
            _plain(value),
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise AuthoringError(
            "invalid-json-value", "Authoring values must be strict JSON"
        ) from error
    return f"{rendered}\n".encode()


def _freeze_json(value: object) -> object:
    try:
        copied = json.loads(_json_bytes(value))
    except json.JSONDecodeError as error:  # pragma: no cover - serializer output is controlled
        raise AuthoringError("invalid-json-value", "Authoring value could not be copied") from error
    return _freeze(copied)


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        document = cast(dict[str, object], value)
        return MappingProxyType({key: _freeze(item) for key, item in document.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in cast(list[object], value))
    return value


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {str(key): _plain(item) for key, item in mapping.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in cast(tuple[object, ...], value)]
    return value


def _relative_path(value: object, field_name: str) -> str:
    if type(value) is not str or PACKAGE_PATH_PATTERN.fullmatch(value) is None:
        _fail("unsafe-authoring-path", f"{field_name} must be a strict relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        _fail("unsafe-authoring-path", f"{field_name} is not a contained file path")
    return value


def _is_link_like(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    attributes = getattr(metadata, "st_file_attributes", 0)
    return path.is_symlink() or bool(attributes & REPARSE_POINT)


def _validated_parent(destination: Path) -> tuple[Path, Path]:
    if not destination.is_absolute():
        _fail("unsafe-destination", "Destination must be an absolute path")
    if destination.exists() or destination.is_symlink():
        _fail("destination-exists", "Destination must not already exist")
    try:
        parent = destination.parent.resolve(strict=True)
    except OSError as error:
        raise AuthoringError(
            "unsafe-destination", "Destination parent must already exist"
        ) from error
    if not parent.is_dir():
        _fail("unsafe-destination", "Destination parent must be a directory")
    cursor = destination.parent
    while True:
        if _is_link_like(cursor):
            _fail("unsafe-destination", "Destination path cannot traverse a link or junction")
        if cursor.parent == cursor:
            break
        cursor = cursor.parent
    normalized = parent / destination.name
    return parent, normalized


def _publish_directory(
    destination: Path,
    files: Mapping[str, bytes],
    *,
    validate: Callable[[Path], None] | None = None,
) -> Path:
    parent, normalized_destination = _validated_parent(destination)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.staging-", dir=parent))
    try:
        for relative_path, content in files.items():
            safe_path = _relative_path(relative_path, "output path")
            target = staging.joinpath(*PurePosixPath(safe_path).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        if validate is not None:
            validate(staging)
        staging.replace(normalized_destination)
    except AuthoringError:
        shutil.rmtree(staging)
        raise
    except (ContractError, OSError) as error:
        shutil.rmtree(staging)
        raise AuthoringError(
            "authoring-write-failed", "Authoring output could not be validated or published"
        ) from error
    return normalized_destination


def _file_hashes(root: Path) -> tuple[tuple[str, str], ...]:
    return tuple(
        (
            path.relative_to(root).as_posix(),
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    )


@dataclass(frozen=True)
class WorkspaceSpec:
    distribution_name: str
    import_name: str
    display_name: str
    publisher_name: str
    license_expression: str

    def __post_init__(self) -> None:
        if (
            type(self.distribution_name) is not str
            or DIST_NAME_PATTERN.fullmatch(self.distribution_name) is None
        ):
            _fail("invalid-workspace-name", "distribution_name must be normalized")
        if (
            type(self.import_name) is not str
            or IMPORT_NAME_PATTERN.fullmatch(self.import_name) is None
        ):
            _fail("invalid-workspace-name", "import_name must be a safe Python package name")
        _required_text(self.display_name, "display_name", maximum=256)
        _required_text(self.publisher_name, "publisher_name", maximum=256)
        if (
            type(self.license_expression) is not str
            or SPDX_PATTERN.fullmatch(self.license_expression) is None
        ):
            _fail("invalid-license", "license_expression must use bounded SPDX expression text")


@dataclass(frozen=True)
class ScaffoldReceipt:
    destination: Path
    files: tuple[tuple[str, str], ...]
    engine_requirement: str


def _workspace_files(spec: WorkspaceSpec) -> dict[str, bytes]:
    project_description = f"Scientific plugin workspace for {spec.display_name}."
    pyproject = f'''[build-system]
requires = ["hatchling>=1.27,<2"]
build-backend = "hatchling.build"

[project]
name = {_toml_string(spec.distribution_name)}
version = "0.1.0a0"
description = {_toml_string(project_description)}
readme = "README.md"
requires-python = ">=3.11,<3.15"
license = {_toml_string(spec.license_expression)}
authors = [
  {{ name = {_toml_string(spec.publisher_name)} }},
]
dependencies = [
  "{ENGINE_REQUIREMENT}",
]

[dependency-groups]
dev = [
  "pytest>=8.4,<10",
]

[tool.hatch.build.targets.wheel]
packages = ["src/{spec.import_name}"]

[tool.pytest.ini_options]
testpaths = ["tests"]
'''
    readme = f"""# {spec.display_name}

This is an empty Materials MCP authoring workspace. It contains no plugin
manifest, capability, handler, backend, scientific value, result, or validation
claim.

Author the real input, result, and error schemas under `schemas/`; implement
explicitly bound handlers under `src/{spec.import_name}/`; and keep authentic
positive evidence separate from generated negative and security inputs. Use the
typed authoring API to build a checksum-bound declarative package only after the
capability semantics, effects, rights, and schemas are complete.

A successful package build establishes structural conformance to one exact
profile, including package declarations, schema integrity, and registration
identity.

Before distribution, add the license text corresponding to the selected SPDX
expression and verify rights for every bundled resource. Until the pinned engine
alpha is published, install a locally built engine wheel first and install this
workspace with --no-deps as documented in the engine authoring guide.
"""
    schema_readme = """# Schemas

Place only authored, exact-identity JSON Schema Draft 2020-12 resources here.
The authoring SDK does not invent capability schemas or scientific semantics.
"""
    tests_readme = """# Tests

Use authentic provenance-traceable records for positive scientific evidence.
Keep generated malformed, boundary, fuzz, and security inputs in explicitly
labeled negative-only locations.
"""
    module = f'"""Implementation package for {spec.display_name}; no handlers are generated."""\n'
    gitignore = """__pycache__/
*.py[cod]
.venv/
.pytest_cache/
build/
dist/
*.egg-info/
.env
.env.*
artifacts/
runs/
"""
    return {
        ".gitignore": gitignore.encode(),
        "README.md": readme.encode(),
        "pyproject.toml": pyproject.encode(),
        f"src/{spec.import_name}/__init__.py": module.encode(),
        "schemas/README.md": schema_readme.encode(),
        "tests/README.md": tests_readme.encode(),
    }


def scaffold_workspace(spec: WorkspaceSpec, destination: Path) -> ScaffoldReceipt:
    files = _workspace_files(spec)
    published = _publish_directory(destination, files)
    return ScaffoldReceipt(published, _file_hashes(published), ENGINE_REQUIREMENT)


@dataclass(frozen=True)
class EffectSpec:
    tier: str
    category: str
    description: str
    plan_required: bool
    approval_required: bool
    strong_confirmation_required: bool

    def to_document(self) -> dict[str, object]:
        return {
            "tier": self.tier,
            "category": self.category,
            "description": self.description,
            "plan_required": self.plan_required,
            "approval_required": self.approval_required,
            "strong_confirmation_required": self.strong_confirmation_required,
        }


@dataclass(frozen=True)
class CapabilitySpec:
    capability_id: str
    title: str
    description: str
    effect: EffectSpec
    input_schema: str
    result_schema: str
    error_schema: str
    supports_async: bool

    def to_document(self) -> dict[str, object]:
        return {
            "capability_id": self.capability_id,
            "title": self.title,
            "description": self.description,
            "effect": self.effect.to_document(),
            "input_schema": self.input_schema,
            "result_schema": self.result_schema,
            "error_schema": self.error_schema,
            "supports_async": self.supports_async,
        }


@dataclass(frozen=True)
class SchemaSpec:
    schema_id: str
    source_path: str
    package_path: str
    role: str

    def __post_init__(self) -> None:
        _required_text(self.schema_id, "schema_id")
        _relative_path(self.source_path, "source_path")
        _relative_path(self.package_path, "package_path")
        if self.package_path == "manifest.json":
            _fail("path-collision", "Schema package_path cannot replace manifest.json")
        if self.role not in RESOURCE_ROLES:
            _fail("invalid-schema-role", "Schema role is not recognized")


@dataclass(frozen=True)
class ExtensionSpec:
    schema_id: str
    applies_to: tuple[str, ...]

    def __post_init__(self) -> None:
        _required_text(self.schema_id, "extension schema_id")
        if type(self.applies_to) is not tuple or not self.applies_to:
            _fail("invalid-extension", "Extension applies_to must be a non-empty tuple")
        if any(type(value) is not str for value in self.applies_to):
            _fail("invalid-extension", "Extension targets must be strings")


@dataclass(frozen=True)
class PluginPackageSpec:
    profile_version: str
    plugin_id: str
    plugin_version: str
    name: str
    description: str
    publisher_name: str
    license_expression: str
    rights_uri: str
    capabilities: tuple[CapabilitySpec, ...]
    schemas: tuple[SchemaSpec, ...]
    publisher_uri: str | None = None
    extension_declarations: tuple[ExtensionSpec, ...] = ()
    extensions: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "profile_version",
            "plugin_id",
            "plugin_version",
            "name",
            "description",
            "publisher_name",
            "license_expression",
            "rights_uri",
        ):
            _required_text(getattr(self, field_name), field_name)
        if self.publisher_uri is not None:
            _required_text(self.publisher_uri, "publisher_uri")
        if type(self.capabilities) is not tuple or not self.capabilities:
            _fail("invalid-authoring-spec", "capabilities must be a non-empty tuple")
        if type(self.schemas) is not tuple or not self.schemas:
            _fail("invalid-authoring-spec", "schemas must be a non-empty tuple")
        if type(self.extension_declarations) is not tuple:
            _fail("invalid-authoring-spec", "extension_declarations must be a tuple")
        schema_ids = [item.schema_id for item in self.schemas]
        package_paths = [item.package_path for item in self.schemas]
        capability_ids = [item.capability_id for item in self.capabilities]
        if len(schema_ids) != len(set(schema_ids)):
            _fail("duplicate-schema-id", "Schema identifiers must be unique")
        if len(package_paths) != len(set(package_paths)):
            _fail("path-collision", "Schema package paths must be unique")
        if len(capability_ids) != len(set(capability_ids)):
            _fail("duplicate-capability-id", "Capability identifiers must be unique")
        extension_value = cast(object, {} if self.extensions is None else self.extensions)
        if not isinstance(extension_value, Mapping):
            _fail("invalid-extension", "extensions must be an object")
        extension_mapping = cast(Mapping[str, object], extension_value)
        object.__setattr__(
            self,
            "extensions",
            cast(Mapping[str, object], _freeze_json(extension_mapping)),
        )


@dataclass(frozen=True)
class PackageReceipt:
    destination: Path
    manifest_sha256: str
    registration_identity: tuple[str, str]
    files: tuple[tuple[str, str], ...]
    manifest: LoadedManifest


class PluginPackageBuilder:
    """Build one exact-profile declarative package without executing plugin code."""

    def __init__(self, contracts: ContractRegistry) -> None:
        self._contracts = contracts

    def _manifest(
        self,
        spec: PluginPackageSpec,
        resource_hashes: Mapping[str, str],
    ) -> dict[str, object]:
        publisher: dict[str, object] = {"name": spec.publisher_name}
        if spec.publisher_uri is not None:
            publisher["uri"] = spec.publisher_uri
        document: dict[str, object] = {
            "contract": f"{self._contracts.canonical_base}plugin-manifest.schema.json",
            "profile_version": spec.profile_version,
            "plugin_id": spec.plugin_id,
            "plugin_version": spec.plugin_version,
            "name": spec.name,
            "description": spec.description,
            "publisher": publisher,
            "license": {
                "expression": spec.license_expression,
                "rights_uri": spec.rights_uri,
            },
            "capabilities": [item.to_document() for item in spec.capabilities],
            "schema_resources": [
                {
                    "schema_id": item.schema_id,
                    "path": item.package_path,
                    "sha256": resource_hashes[item.package_path],
                    "media_type": "application/schema+json",
                    "role": item.role,
                }
                for item in spec.schemas
            ],
            "extension_declarations": [
                {
                    "schema_id": item.schema_id,
                    "applies_to": list(item.applies_to),
                }
                for item in spec.extension_declarations
            ],
        }
        extensions = cast(Mapping[str, object], spec.extensions)
        if extensions:
            document["extensions"] = _plain(extensions)
        return document

    def build(
        self,
        spec: PluginPackageSpec,
        *,
        schema_source_root: Path,
        destination: Path,
    ) -> PackageReceipt:
        if spec.profile_version != self._contracts.profile_version:
            _fail("profile-mismatch", "Package spec and contract registry profiles differ")
        try:
            source_root = schema_source_root.resolve(strict=True)
        except OSError as error:
            raise AuthoringError(
                "invalid-source-root", "Schema source root does not exist"
            ) from error
        if not source_root.is_dir() or _is_link_like(schema_source_root):
            _fail("invalid-source-root", "Schema source root must be a non-link directory")
        _, normalized_destination = _validated_parent(destination)
        try:
            normalized_destination.relative_to(source_root)
        except ValueError:
            pass
        else:
            _fail("overlapping-roots", "Destination cannot be inside the schema source root")

        files: dict[str, bytes] = {}
        resource_hashes: dict[str, str] = {}
        for schema in spec.schemas:
            try:
                source = resolve_contained_file(schema_source_root, schema.source_path)
                content = source.read_bytes()
            except (ContractError, OSError) as error:
                raise AuthoringError(
                    "invalid-schema-source", "A declared schema source is unavailable or unsafe"
                ) from error
            files[schema.package_path] = content
            resource_hashes[schema.package_path] = hashlib.sha256(content).hexdigest()
        files["manifest.json"] = _json_bytes(self._manifest(spec, resource_hashes))

        loaded: LoadedManifest | None = None

        def validate(staging: Path) -> None:
            nonlocal loaded
            try:
                loaded = ManifestLoader(self._contracts).load(staging)
            except ContractError as error:
                raise AuthoringError(
                    "package-validation-failed",
                    "Authored package failed exact profile validation",
                ) from error

        published = _publish_directory(normalized_destination, files, validate=validate)
        if loaded is None:  # pragma: no cover - validation callback is mandatory
            _fail("package-validation-failed", "Authored package was not validated")
        return PackageReceipt(
            destination=published,
            manifest_sha256=loaded.manifest_sha256,
            registration_identity=(loaded.plugin_id, loaded.plugin_version),
            files=_file_hashes(published),
            manifest=loaded,
        )


def _scaffold_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="materials-mcp-scaffold",
        description="Create an empty Materials MCP plugin authoring workspace.",
    )
    parser.add_argument("destination", type=Path)
    parser.add_argument("--distribution-name", required=True)
    parser.add_argument("--import-name", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--publisher-name", required=True)
    parser.add_argument("--license-expression", required=True)
    return parser


def scaffold_main(argv: Sequence[str] | None = None) -> int:
    parser = _scaffold_parser()
    args = parser.parse_args(argv)
    try:
        receipt = scaffold_workspace(
            WorkspaceSpec(
                distribution_name=cast(str, args.distribution_name),
                import_name=cast(str, args.import_name),
                display_name=cast(str, args.display_name),
                publisher_name=cast(str, args.publisher_name),
                license_expression=cast(str, args.license_expression),
            ),
            cast(Path, args.destination),
        )
    except AuthoringError as error:
        next_action = (
            "Choose a new absolute destination whose parent already exists."
            if error.code in {"destination-exists", "invalid-destination"}
            else "Correct the explicit workspace inputs and retry."
        )
        sys.stderr.write(
            f"scaffold failed [{error.code}]: {error}; retryable=true; next_action={next_action}\n"
        )
        return 2
    sys.stdout.write(f"Created empty authoring workspace: {receipt.destination}\n")
    return 0
