"""Standalone stdio host composition for the OPTIMADE integration."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from materials_mcp_commons import (
    AuthorizationReceipt,
    CapabilityDetail,
    CommonsError,
    ContractRegistry,
    Dispatcher,
    DispatchRequest,
    EngineMCPHost,
    LifecycleRegistry,
    LoadedManifest,
    ManifestLoader,
    Permission,
    PolicyEngine,
    PolicyError,
    PolicySnapshot,
    QuotaCharge,
    QuotaLimit,
    create_mcp_server,
)

from .client import OptimadeClient
from .contracts import CAPABILITY_IDS, PROFILE_VERSION, declarative_package_root
from .export import OptimadeExporter
from .handlers import OptimadeHandlers, bind_handlers

_EXPORT_PERMISSION = Permission("write", "urn:materials-mcp:workspace-export-root")
_EXPORT_QUOTA_KIND = "export-artifacts"


def _plain_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            cast(str, key): _plain_json(item)
            for key, item in cast(Mapping[object, object], value).items()
        }
    if isinstance(value, (list, tuple)):
        return [_plain_json(item) for item in cast(list[object] | tuple[object, ...], value)]
    return value


@dataclass(frozen=True)
class OptimadeHostRuntime:
    """One exact plugin registration composed into the generic MCP host."""

    host: EngineMCPHost
    registration_ref: str


@dataclass(frozen=True)
class _ExportAuthorizationResolver:
    policy_engine: PolicyEngine
    manifest: LoadedManifest
    policy: PolicySnapshot

    def __call__(
        self,
        request: DispatchRequest,
        target: CapabilityDetail,
    ) -> tuple[PolicySnapshot, AuthorizationReceipt]:
        if target.capability.capability_id != CAPABILITY_IDS["records_export"]:
            raise PolicyError(
                "effect-not-authorized",
                "The standalone host authorizes only its bounded export effect",
            )
        try:
            # The resolver runs before dispatch input validation, so it repeats that
            # exact contract check before minting any authorization material.
            payload = cast(dict[str, object], _plain_json(request.payload))
            self.manifest.validate(target.capability.input_schema, payload)
        except (AttributeError, CommonsError) as error:
            raise PolicyError(
                "export-input-rejected",
                "Export input failed its exact contract before authorization",
            ) from error
        destination = payload.get("destination")
        export_format = payload.get("format")
        if type(destination) is not str or type(export_format) is not str:
            raise PolicyError(
                "export-input-rejected",
                "Export identity is unavailable after contract validation",
            )
        destination_ref = f"urn:materials-mcp:workspace-export:{destination}"
        media_type = "chemical/x-cif" if export_format == "cif" else "application/json"
        plan = self.policy_engine.create_plan(
            request,
            target,
            steps=(
                {
                    "step_id": "persist",
                    "action": "write",
                    "description": "Write one fresh rights-cleared record beneath the export root.",
                    "targets": [destination_ref],
                },
            ),
            permissions=(_EXPORT_PERMISSION,),
            expected_outputs=({"role": "output", "media_type": media_type},),
            estimates=(
                {
                    "kind": "storage",
                    "value": {
                        "value_type": "integer",
                        "value": 1,
                        "unit": {"system": "UCUM", "identifier": "1", "symbol": "1"},
                    },
                },
            ),
            risks=(
                "The source response and provider redistribution rights must remain current.",
                "A consumed authorization and quota charge are not refunded after handler failure.",
            ),
        )
        grant = self.policy_engine.issue_grant(
            request,
            target,
            self.policy,
            plan,
            issued_at=request.occurred_at,
            charges=(QuotaCharge(_EXPORT_QUOTA_KIND, 1),),
        )
        receipt = self.policy_engine.consume(
            grant,
            request,
            target,
            self.policy,
            consumed_at=request.occurred_at,
        )
        return self.policy, receipt


def build_mcp_runtime(
    contracts: ContractRegistry,
    export_root: Path,
    policy_engine: PolicyEngine,
    *,
    owner_ref: str,
    export_quota: int = 100,
) -> OptimadeHostRuntime:
    """Compose the exact declarative package, handlers, R1 policy, and MCP host."""

    if type(export_quota) is not int or not 1 <= export_quota <= 1_000_000:
        raise PolicyError("invalid-export-quota", "Export quota must be between 1 and 1000000")
    manifest = ManifestLoader(contracts).load(declarative_package_root())
    lifecycle = LifecycleRegistry()
    registration = lifecycle.register(manifest)
    dispatcher = Dispatcher(lifecycle, contracts, policy_engine)
    handlers = OptimadeHandlers(OptimadeClient(), OptimadeExporter(export_root))
    bindings = bind_handlers(dispatcher, registration.registration_ref, handlers)
    if len(bindings) != len(CAPABILITY_IDS):
        raise PolicyError("binding-incomplete", "The standalone host did not bind every capability")
    policy = PolicySnapshot(
        owner_ref,
        (_EXPORT_PERMISSION,),
        (QuotaLimit(_EXPORT_QUOTA_KIND, export_quota),),
    )
    resolver = _ExportAuthorizationResolver(policy_engine, manifest, policy)
    host = EngineMCPHost(
        lifecycle,
        dispatcher,
        owner_ref=owner_ref,
        authorization_resolver=resolver,
    )
    return OptimadeHostRuntime(host=host, registration_ref=registration.registration_ref)


def _directory(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or not path.exists() or not path.is_dir():
        raise argparse.ArgumentTypeError("expected an existing absolute directory")
    return path


def _positive_quota(value: str) -> int:
    try:
        quota = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("export quota must be an integer") from error
    if not 1 <= quota <= 1_000_000:
        raise argparse.ArgumentTypeError("export quota must be between 1 and 1000000")
    return quota


def main(argv: Sequence[str] | None = None) -> None:
    """Run the four-tool engine protocol over stdio with this plugin registered."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-root", required=True, type=_directory)
    parser.add_argument("--export-root", required=True, type=_directory)
    parser.add_argument("--policy-root", required=True, type=_directory)
    parser.add_argument(
        "--owner-ref",
        default="urn:materials-mcp:owner:optimade-local-host",
    )
    parser.add_argument("--export-quota", type=_positive_quota, default=100)
    args = parser.parse_args(argv)
    profile_root = cast(Path, args.profile_root)
    export_root = cast(Path, args.export_root)
    policy_root = cast(Path, args.policy_root)
    owner_ref = cast(str, args.owner_ref)
    export_quota = cast(int, args.export_quota)

    contracts = ContractRegistry.from_directory(profile_root, PROFILE_VERSION)
    with PolicyEngine(policy_root, contracts) as policy_engine:
        runtime = build_mcp_runtime(
            contracts,
            export_root,
            policy_engine,
            owner_ref=owner_ref,
            export_quota=export_quota,
        )
        create_mcp_server(runtime.host).run("stdio")


if __name__ == "__main__":
    main()


__all__ = ["OptimadeHostRuntime", "build_mcp_runtime", "main"]
