"""Generate deterministic structural conformance evidence for this plugin."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from materials_mcp_commons import (
    ContractRegistry,
    PluginConformanceRunner,
    render_capability_reference,
)

from materials_mcp_optimade.contracts import (
    PROFILE_VERSION,
    declarative_package_root,
    load_declarative_manifest,
)

PLUGIN_ROOT = Path(__file__).parents[1]
PUBLIC_ROOT = PLUGIN_ROOT.parents[1]
PROFILE_ROOT = PUBLIC_ROOT / "schemas" / PROFILE_VERSION


def build_report() -> str:
    registry = ContractRegistry.from_directory(PROFILE_ROOT, PROFILE_VERSION)
    return PluginConformanceRunner(registry).evaluate(declarative_package_root()).to_json()


def build_reference() -> str:
    return render_capability_reference(load_declarative_manifest(PROFILE_ROOT))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("report", "reference"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    kind = cast(str, args.kind)
    rendered = build_report() if kind == "report" else build_reference()
    output = cast(Path | None, args.output)
    if output is None:
        sys.stdout.write(rendered)
    else:
        output.write_text(rendered, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
