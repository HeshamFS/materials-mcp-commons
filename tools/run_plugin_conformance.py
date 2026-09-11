from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from materials_mcp_commons import (
    ContractRegistry,
    ManifestLoader,
    PackageCase,
    PluginConformanceRunner,
    ProfileCase,
    build_versioned_matrix,
    render_capability_reference,
)
from materials_mcp_commons.contracts import load_json_object

PUBLIC_ROOT = Path(__file__).parents[1]
ENGINE_PACKAGE = PUBLIC_ROOT / "tests/runtime/positive-project/engine-lifecycle"
ENGINE_PACKAGE_0_1 = PUBLIC_ROOT / "tests/runtime/positive-project/engine-lifecycle-profile-0.1.0"
COMPATIBILITY = PUBLIC_ROOT / "tests/contracts/profile-0.2.0/profile-compatibility.json"


def build_plugin_report(public_root: Path = PUBLIC_ROOT) -> str:
    registry = ContractRegistry.from_directory(public_root / "schemas/0.2.0", "0.2.0")
    package = public_root / "tests/runtime/positive-project/engine-lifecycle"
    return PluginConformanceRunner(registry).evaluate(package).to_json()


def build_matrix_report(public_root: Path = PUBLIC_ROOT) -> str:
    compatibility = load_json_object(
        public_root / "tests/contracts/profile-0.2.0/profile-compatibility.json"
    )
    matrix = build_versioned_matrix(
        (
            ProfileCase("0.1.0", public_root / "schemas/0.1.0"),
            ProfileCase("0.2.0", public_root / "schemas/0.2.0"),
        ),
        (
            PackageCase(
                "actual-engine-control-profile-0.1.0",
                public_root / "tests/runtime/positive-project/engine-lifecycle-profile-0.1.0",
            ),
            PackageCase(
                "actual-engine-control-profile-0.2.0",
                public_root / "tests/runtime/positive-project/engine-lifecycle",
            ),
        ),
        (compatibility,),
    )
    return matrix.to_json()


def build_capability_reference(public_root: Path = PUBLIC_ROOT) -> str:
    registry = ContractRegistry.from_directory(public_root / "schemas/0.2.0", "0.2.0")
    manifest = ManifestLoader(registry).load(
        public_root / "tests/runtime/positive-project/engine-lifecycle"
    )
    return render_capability_reference(manifest)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate deterministic structural authoring evidence."
    )
    parser.add_argument("kind", choices=("package", "matrix", "reference"))
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    kind = cast(str, args.kind)
    builders = {
        "package": build_plugin_report,
        "matrix": build_matrix_report,
        "reference": build_capability_reference,
    }
    rendered = builders[kind]()
    output = cast(Path | None, args.output)
    if output is None:
        sys.stdout.write(rendered)
    else:
        output.write_text(rendered, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
