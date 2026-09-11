from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from materials_mcp_commons import (
    CapabilitySpec,
    ContractRegistry,
    EffectSpec,
    ExtensionSpec,
    PluginPackageBuilder,
    PluginPackageSpec,
    SchemaSpec,
)

PUBLIC_ROOT = Path(__file__).parents[1]
SOURCE_PACKAGE = PUBLIC_ROOT / "tests/runtime/positive-project/engine-lifecycle"


def _document(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def engine_control_spec(source: Path = SOURCE_PACKAGE) -> PluginPackageSpec:
    """Reconstruct the repository's real engine-control package as a typed specification."""
    document = _document(source / "manifest.json")
    publisher = cast(dict[str, object], document["publisher"])
    license_record = cast(dict[str, object], document["license"])
    return PluginPackageSpec(
        profile_version=cast(str, document["profile_version"]),
        plugin_id=cast(str, document["plugin_id"]),
        plugin_version=cast(str, document["plugin_version"]),
        name=cast(str, document["name"]),
        description=cast(str, document["description"]),
        publisher_name=cast(str, publisher["name"]),
        publisher_uri=cast(str | None, publisher.get("uri")),
        license_expression=cast(str, license_record["expression"]),
        rights_uri=cast(str, license_record["rights_uri"]),
        capabilities=tuple(
            CapabilitySpec(
                capability_id=cast(str, item["capability_id"]),
                title=cast(str, item["title"]),
                description=cast(str, item["description"]),
                effect=EffectSpec(**cast(dict[str, Any], item["effect"])),
                input_schema=cast(str, item["input_schema"]),
                result_schema=cast(str, item["result_schema"]),
                error_schema=cast(str, item["error_schema"]),
                supports_async=cast(bool, item["supports_async"]),
            )
            for item in cast(list[dict[str, object]], document["capabilities"])
        ),
        schemas=tuple(
            SchemaSpec(
                schema_id=cast(str, item["schema_id"]),
                source_path=cast(str, item["path"]),
                package_path=cast(str, item["path"]),
                role=cast(str, item["role"]),
            )
            for item in cast(list[dict[str, object]], document["schema_resources"])
        ),
        extension_declarations=tuple(
            ExtensionSpec(
                schema_id=cast(str, item["schema_id"]),
                applies_to=tuple(cast(list[str], item["applies_to"])),
            )
            for item in cast(list[dict[str, object]], document["extension_declarations"])
        ),
        extensions=cast(dict[str, object], document.get("extensions", {})),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild the real engine-control declarative package with the authoring API."
    )
    parser.add_argument("destination", type=Path)
    args = parser.parse_args(argv)
    contracts = ContractRegistry.from_directory(PUBLIC_ROOT / "schemas/0.2.0", "0.2.0")
    receipt = PluginPackageBuilder(contracts).build(
        engine_control_spec(),
        schema_source_root=SOURCE_PACKAGE,
        destination=cast(Path, args.destination),
    )
    print(receipt.manifest_sha256)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
