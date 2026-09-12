"""Build the exact checksum-bound OPTIMADE declarative package."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Final

from materials_mcp_commons import (
    CapabilitySpec,
    ContractRegistry,
    EffectSpec,
    ExtensionSpec,
    PluginPackageBuilder,
    PluginPackageSpec,
    SchemaSpec,
)

PLUGIN_ROOT: Final = Path(__file__).parents[1]
PUBLIC_ROOT: Final = PLUGIN_ROOT.parents[1]
PROFILE_VERSION: Final = "0.2.0"
PLUGIN_ID: Final = "https://schemas.autonomouslab.io/materials-mcp/plugins/optimade"
PLUGIN_VERSION: Final = "0.1.0-alpha.1"
SCHEMA_BASE: Final = f"{PLUGIN_ID}/0.1.0/"
PROFILE_BASE: Final = "https://schemas.autonomouslab.io/materials-mcp/0.2.0/"


def _r0(description: str) -> EffectSpec:
    return EffectSpec(
        tier="R0",
        category="read-only",
        description=description,
        plan_required=False,
        approval_required=False,
        strong_confirmation_required=False,
    )


def _r1(description: str) -> EffectSpec:
    return EffectSpec(
        tier="R1",
        category="bounded-local",
        description=description,
        plan_required=False,
        approval_required=False,
        strong_confirmation_required=False,
    )


def _schema_specs() -> tuple[SchemaSpec, ...]:
    resources = (
        ("provider-list-input.schema.json", "input"),
        ("provider-list-result.schema.json", "result"),
        ("provider-inspect-input.schema.json", "input"),
        ("provider-inspect-result.schema.json", "result"),
        ("search-input.schema.json", "input"),
        ("search-result.schema.json", "result"),
        ("get-input.schema.json", "input"),
        ("export-input.schema.json", "input"),
        ("record-identity.extension.schema.json", "extension"),
        ("export-provenance.extension.schema.json", "extension"),
    )
    return tuple(
        SchemaSpec(
            schema_id=f"{SCHEMA_BASE}{filename}",
            source_path=filename,
            package_path=f"schemas/{filename}",
            role=role,
        )
        for filename, role in resources
    )


def package_spec() -> PluginPackageSpec:
    """Return the explicitly authored immutable package specification."""

    structured_error = f"{PROFILE_BASE}structured-error.schema.json"
    result_bundle = f"{PROFILE_BASE}result-bundle.schema.json"
    artifact = f"{PROFILE_BASE}artifact.schema.json"
    provider_list_input = f"{SCHEMA_BASE}provider-list-input.schema.json"
    provider_list_result = f"{SCHEMA_BASE}provider-list-result.schema.json"
    provider_inspect_input = f"{SCHEMA_BASE}provider-inspect-input.schema.json"
    provider_inspect_result = f"{SCHEMA_BASE}provider-inspect-result.schema.json"
    search_input = f"{SCHEMA_BASE}search-input.schema.json"
    search_result = f"{SCHEMA_BASE}search-result.schema.json"
    get_input = f"{SCHEMA_BASE}get-input.schema.json"
    export_input = f"{SCHEMA_BASE}export-input.schema.json"
    identity_extension = f"{SCHEMA_BASE}record-identity.extension.schema.json"
    export_extension = f"{SCHEMA_BASE}export-provenance.extension.schema.json"
    capabilities = (
        CapabilitySpec(
            capability_id=f"{PLUGIN_ID}/providers/list",
            title="List OPTIMADE providers",
            description=(
                "Read the official registry and resolve only reviewed supported provider "
                "index entries without querying registry-only databases."
            ),
            effect=_r0(
                "Performs bounded HTTPS reads of the official registry and reviewed provider "
                "index endpoints without persistence."
            ),
            input_schema=provider_list_input,
            result_schema=provider_list_result,
            error_schema=structured_error,
            supports_async=False,
        ),
        CapabilitySpec(
            capability_id=f"{PLUGIN_ID}/providers/inspect",
            title="Inspect an OPTIMADE provider",
            description=(
                "Inspect versions, base info, structures/references entry info, implementation "
                "metadata, limits, and current rights state for one supported provider."
            ),
            effect=_r0(
                "Performs bounded HTTPS metadata reads from one fixed reviewed provider "
                "without persistence."
            ),
            input_schema=provider_inspect_input,
            result_schema=provider_inspect_result,
            error_schema=structured_error,
            supports_async=False,
        ),
        CapabilitySpec(
            capability_id=f"{PLUGIN_ID}/structures/search",
            title="Search OPTIMADE structures",
            description=(
                "Run one validated OPTIMADE 1.2 filter across an explicit supported-provider "
                "subset with bounded fields, pages, results, honest partial failure, exact "
                "context measurement, and continuation or exact retrieval for omitted hits."
            ),
            effect=_r0(
                "Performs bounded concurrent HTTPS reads from explicitly selected supported "
                "providers without persistence."
            ),
            input_schema=search_input,
            result_schema=search_result,
            error_schema=structured_error,
            supports_async=False,
        ),
        CapabilitySpec(
            capability_id=f"{PLUGIN_ID}/structures/get",
            title="Get one OPTIMADE structure",
            description=(
                "Retrieve exactly one structure by reviewed provider, database, and entry "
                "identity and map it to one provenance-complete core ResultBundle."
            ),
            effect=_r0(
                "Performs one bounded HTTPS record read from one fixed reviewed provider "
                "without persistence."
            ),
            input_schema=get_input,
            result_schema=result_bundle,
            error_schema=structured_error,
            supports_async=False,
        ),
        CapabilitySpec(
            capability_id=f"{PLUGIN_ID}/references/search",
            title="Search OPTIMADE references",
            description=(
                "Run one validated OPTIMADE 1.2 filter over references across an explicit "
                "supported-provider subset with bounded projection, partial-failure reporting, "
                "and context-safe continuation or exact retrieval for omitted hits."
            ),
            effect=_r0(
                "Performs bounded concurrent HTTPS reads from explicitly selected supported "
                "providers without persistence."
            ),
            input_schema=search_input,
            result_schema=search_result,
            error_schema=structured_error,
            supports_async=False,
        ),
        CapabilitySpec(
            capability_id=f"{PLUGIN_ID}/references/get",
            title="Get one OPTIMADE reference",
            description=(
                "Retrieve exactly one reference by reviewed provider, database, and entry "
                "identity and map it to one provenance-complete core ResultBundle."
            ),
            effect=_r0(
                "Performs one bounded HTTPS record read from one fixed reviewed provider "
                "without persistence."
            ),
            input_schema=get_input,
            result_schema=result_bundle,
            error_schema=structured_error,
            supports_async=False,
        ),
        CapabilitySpec(
            capability_id=f"{PLUGIN_ID}/records/export",
            title="Export one OPTIMADE record",
            description=(
                "Persist one freshly retrieved exact record as checksummed native JSON or a "
                "supported scientific export only when current provider rights allow it."
            ),
            effect=_r1(
                "Writes one bounded artifact beneath an engine-authorized local path after an "
                "independent current-rights check."
            ),
            input_schema=export_input,
            result_schema=artifact,
            error_schema=structured_error,
            supports_async=False,
        ),
    )
    return PluginPackageSpec(
        profile_version=PROFILE_VERSION,
        plugin_id=PLUGIN_ID,
        plugin_version=PLUGIN_VERSION,
        name="Materials MCP OPTIMADE",
        description=(
            "Bounded, rights-aware OPTIMADE 1.2 federation over reviewed live materials "
            "databases with explicit provenance, partial failure, and local export effects."
        ),
        publisher_name="Hesham Salama",
        publisher_uri="https://autonomouslab.io/",
        license_expression="Apache-2.0",
        rights_uri="https://www.apache.org/licenses/LICENSE-2.0",
        capabilities=capabilities,
        schemas=_schema_specs(),
        extension_declarations=(
            ExtensionSpec(
                schema_id=identity_extension,
                applies_to=(f"{PROFILE_BASE}entity.schema.json", search_result),
            ),
            ExtensionSpec(
                schema_id=export_extension,
                applies_to=(artifact,),
            ),
        ),
    )


def build(destination: Path) -> str:
    contracts = ContractRegistry.from_directory(
        PUBLIC_ROOT / "schemas" / PROFILE_VERSION,
        PROFILE_VERSION,
    )
    receipt = PluginPackageBuilder(contracts).build(
        package_spec(),
        schema_source_root=PLUGIN_ROOT / "schemas" / "0.1.0",
        destination=destination,
    )
    return receipt.manifest_sha256


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args(argv)
    digest = build(args.destination)
    print(f"Built OPTIMADE declarative package: {args.destination.resolve()}")
    print(f"Manifest SHA-256: {digest}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
