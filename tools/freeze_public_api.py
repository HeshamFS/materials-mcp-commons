from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import tomllib
import types
from collections.abc import Mapping, Sequence
from dataclasses import MISSING, fields, is_dataclass
from pathlib import Path
from typing import Any, ForwardRef, cast, get_args, get_origin

from mcp.client import Client

import materials_mcp_commons as commons
from materials_mcp_commons import (
    DISCOVER_CAPABILITY_ID,
    INSPECT_CAPABILITY_ID,
    ContractRegistry,
    Dispatcher,
    EngineControlHandlers,
    EngineMCPHost,
    LifecycleRegistry,
    ManifestLoader,
    create_mcp_server,
)

PUBLIC_ROOT = Path(__file__).parents[1]
EXPECTED_TOOLS = (
    "materials_discover",
    "materials_inspect",
    "materials_activate",
    "materials_execute",
)


class PublicAPIError(RuntimeError):
    """Raised when the public surface cannot be represented deterministically."""


def _annotation(value: object) -> str | None:
    if value is inspect.Signature.empty:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, ForwardRef):
        return value.__forward_arg__
    return inspect.formatannotation(value).replace("typing.", "")


def _qualified_name(value: type[object]) -> str:
    return f"{value.__module__}.{value.__qualname__}"


def _literal(value: object) -> object:
    if value is None or type(value) in {bool, int, float, str}:
        return value
    if isinstance(value, tuple):
        return [_literal(item) for item in cast(tuple[object, ...], value)]
    if isinstance(value, frozenset):
        literals = [_literal(item) for item in cast(frozenset[object], value)]
        return sorted(literals, key=lambda item: json.dumps(item, sort_keys=True))
    if is_dataclass(value) and not isinstance(value, type):
        return {
            "type": _qualified_name(type(value)),
            "fields": {
                field.name: _literal(getattr(value, field.name))
                for field in fields(cast(Any, value))
            },
        }
    representation = repr(value)
    if representation == "<factory>":
        return {"factory": True}
    raise PublicAPIError(f"Unsupported public default value: {representation}")


def _signature(value: object) -> dict[str, object]:
    signature = inspect.signature(cast(Any, value))
    parameters: list[dict[str, object]] = []
    for parameter in signature.parameters.values():
        item: dict[str, object] = {
            "name": parameter.name,
            "kind": parameter.kind.name.lower(),
        }
        annotation = _annotation(parameter.annotation)
        if annotation is not None:
            item["annotation"] = annotation
        if parameter.default is inspect.Parameter.empty:
            item["required"] = True
        else:
            item["default"] = _literal(parameter.default)
        parameters.append(item)
    document: dict[str, object] = {"parameters": parameters}
    return_annotation = _annotation(signature.return_annotation)
    if return_annotation is not None:
        document["return"] = return_annotation
    return document


def _data_fields(value: type[object]) -> list[dict[str, object]]:
    if not is_dataclass(value):
        return []
    result: list[dict[str, object]] = []
    for field in fields(cast(Any, value)):
        item: dict[str, object] = {
            "name": field.name,
            "annotation": _annotation(field.type),
        }
        if field.default is not MISSING:
            item["default"] = _literal(field.default)
        elif field.default_factory is not MISSING:
            item["default_factory"] = True
        else:
            item["required"] = True
        result.append(item)
    return result


def _class_annotations(value: type[object], field_names: set[str]) -> list[dict[str, str]]:
    annotations = inspect.get_annotations(value, eval_str=False)
    return [
        {"name": name, "annotation": cast(str, _annotation(annotation))}
        for name, annotation in annotations.items()
        if not name.startswith("_") and name not in field_names
    ]


def _class_values(value: type[object], field_names: set[str]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for name, item in value.__dict__.items():
        if name.startswith("_") or name in field_names or name in {"code"}:
            continue
        if type(item) in {bool, int, float, str} or isinstance(item, (tuple, frozenset)):
            result.append({"name": name, "value": _literal(cast(object, item))})
    return result


def _class_members(value: type[object]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for name, descriptor in value.__dict__.items():
        if name.startswith("_") and name != "__call__":
            continue
        if isinstance(descriptor, property):
            if descriptor.fget is None:
                raise PublicAPIError(f"Public property {value.__name__}.{name} has no getter")
            result.append(
                {"name": name, "kind": "property", "signature": _signature(descriptor.fget)}
            )
        elif isinstance(descriptor, classmethod):
            result.append(
                {"name": name, "kind": "classmethod", "signature": _signature(getattr(value, name))}
            )
        elif isinstance(descriptor, staticmethod):
            result.append(
                {"name": name, "kind": "staticmethod", "signature": _signature(descriptor.__func__)}
            )
        elif inspect.isfunction(descriptor):
            result.append({"name": name, "kind": "method", "signature": _signature(descriptor)})
    return result


def _alias_expression(value: object) -> dict[str, object]:
    origin = get_origin(value)
    arguments = get_args(value)
    if origin is types.UnionType:
        return {
            "origin": "union",
            "arguments": [cast(str, _annotation(argument)) for argument in arguments],
        }
    if origin is not None:
        return {
            "origin": cast(str, _annotation(origin)),
            "arguments": [cast(str, _annotation(argument)) for argument in arguments],
        }
    raise PublicAPIError(f"Unsupported exported value: {value!r}")


def _python_export(name: str) -> dict[str, object]:
    value = getattr(commons, name)
    if inspect.isclass(value):
        field_documents = _data_fields(value)
        field_names = {cast(str, item["name"]) for item in field_documents}
        document: dict[str, object] = {
            "name": name,
            "kind": "protocol" if getattr(value, "_is_protocol", False) else "class",
            "module": value.__module__,
            "bases": [_qualified_name(base) for base in value.__bases__],
            "signature": _signature(value),
        }
        if field_documents:
            document["fields"] = field_documents
        annotations = _class_annotations(value, field_names)
        if annotations:
            document["annotations"] = annotations
        class_values = _class_values(value, field_names)
        if class_values:
            document["values"] = class_values
        members = _class_members(value)
        if members:
            document["members"] = members
        return document
    if inspect.isfunction(value):
        return {
            "name": name,
            "kind": "function",
            "module": value.__module__,
            "signature": _signature(value),
        }
    if value is None or type(value) in {bool, int, float, str}:
        return {"name": name, "kind": "constant", "value": _literal(value)}
    return {"name": name, "kind": "type-alias", "expression": _alias_expression(value)}


def _build_server() -> object:
    contracts = ContractRegistry.from_directory(PUBLIC_ROOT / "schemas/0.2.0", "0.2.0")
    manifest = ManifestLoader(contracts).load(
        PUBLIC_ROOT / "tests/runtime/positive-project/engine-lifecycle"
    )
    lifecycle = LifecycleRegistry()
    registration = lifecycle.register(manifest)
    controls = EngineControlHandlers(lifecycle)
    dispatcher = Dispatcher(lifecycle, contracts)
    dispatcher.bind(registration.registration_ref, DISCOVER_CAPABILITY_ID, controls.discover)
    dispatcher.bind(registration.registration_ref, INSPECT_CAPABILITY_ID, controls.inspect)
    host = EngineMCPHost(
        lifecycle,
        dispatcher,
        owner_ref="urn:materials-mcp:owner:public-api-freeze",
    )
    return create_mcp_server(host)


async def _protocol_tools() -> list[dict[str, object]]:
    server = _build_server()
    documents: list[dict[str, object]] = []
    async with Client(cast(Any, server)) as client:
        listed = await client.list_tools()
        for tool in listed.tools:
            documents.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                    "output_schema": tool.output_schema,
                }
            )
    if tuple(cast(str, item["name"]) for item in documents) != EXPECTED_TOOLS:
        raise PublicAPIError("MCP tool inventory differs from the four-tool engine boundary")
    return documents


def build_public_api_contract() -> dict[str, object]:
    with (PUBLIC_ROOT / "pyproject.toml").open("rb") as handle:
        pyproject = tomllib.load(handle)
    project = cast(dict[str, Any], pyproject["project"])
    scripts = cast(dict[str, str], project["scripts"])
    profiles = sorted(path.name for path in (PUBLIC_ROOT / "schemas").iterdir() if path.is_dir())
    exports = [_python_export(name) for name in commons.__all__]
    return {
        "contract_version": 1,
        "distribution": cast(str, project["name"]),
        "distribution_version": commons.__version__,
        "stability": "production-alpha-plugin-proof",
        "python": {
            "requires": cast(str, project["requires-python"]),
            "exports": exports,
        },
        "console_scripts": scripts,
        "protocol": {
            "sdk_extra": "mcp-host",
            "transport": "MCP",
            "tools": asyncio.run(_protocol_tools()),
        },
        "profile_versions": profiles,
    }


def serialize_public_api(contract: Mapping[str, object]) -> str:
    return json.dumps(contract, indent=2, sort_keys=True) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate the frozen production-alpha API contract."
    )
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    rendered = serialize_public_api(build_public_api_contract())
    output = cast(Path | None, args.output)
    if output is None:
        print(rendered, end="")
    else:
        output.write_text(rendered, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
