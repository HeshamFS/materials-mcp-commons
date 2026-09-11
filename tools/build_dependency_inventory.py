from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from collections import deque
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from typing import cast

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

PUBLIC_ROOT = Path(__file__).parents[1]
ROOT_DISTRIBUTION = "materials-mcp-commons"
_CLASSIFIER_LICENSES = {
    "License :: OSI Approved :: Apache Software License": "Apache-2.0",
    "License :: OSI Approved :: BSD License": "BSD",
    "License :: OSI Approved :: MIT License": "MIT",
    "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "License :: OSI Approved :: Python Software Foundation License": "PSF-2.0",
}


class DependencyInventoryError(RuntimeError):
    """The installed production graph cannot be inventoried exactly."""


def _license(name: str) -> str:
    metadata = distribution(name).metadata
    expressions = metadata.get_all("License-Expression", [])
    expression = expressions[0] if expressions else None
    if expression:
        return expression.strip()
    licenses = metadata.get_all("License", [])
    legacy = licenses[0] if licenses else None
    if legacy and "\n" not in legacy and len(legacy) <= 128:
        return legacy.strip()
    found = sorted(
        {
            mapped
            for classifier in metadata.get_all("Classifier", [])
            if (mapped := _CLASSIFIER_LICENSES.get(classifier)) is not None
        }
    )
    if found:
        return " OR ".join(found)
    raise DependencyInventoryError(f"No bounded license expression found for {name}")


def _requirements(name: str, extras: frozenset[str]) -> list[Requirement]:
    metadata = distribution(name).metadata
    environment = cast(dict[str, str], default_environment())
    selected = extras or frozenset({""})
    result: list[Requirement] = []
    for raw in metadata.get_all("Requires-Dist", []):
        requirement = Requirement(raw)
        if requirement.marker is None or any(
            requirement.marker.evaluate({**environment, "extra": extra}) for extra in selected
        ):
            result.append(requirement)
    return sorted(result, key=lambda item: canonicalize_name(item.name))


def _scope(extra: str | None) -> list[dict[str, object]]:
    root = canonicalize_name(ROOT_DISTRIBUTION)
    queue: deque[tuple[str, frozenset[str]]] = deque(
        [(root, frozenset({extra}) if extra else frozenset())]
    )
    requested_extras: dict[str, frozenset[str]] = {}
    direct: set[str] = set()
    while queue:
        name, extras = queue.popleft()
        combined = requested_extras.get(name, frozenset()) | extras
        if requested_extras.get(name) == combined:
            continue
        requested_extras[name] = combined
        try:
            requirements = _requirements(name, combined)
        except PackageNotFoundError as error:
            raise DependencyInventoryError(
                f"Required distribution is not installed: {name}"
            ) from error
        for requirement in requirements:
            child = canonicalize_name(requirement.name)
            if name == root:
                direct.add(child)
            queue.append((child, frozenset(requirement.extras)))

    packages: list[dict[str, object]] = []
    for name in sorted(requested_extras):
        installed = distribution(name)
        packages.append(
            {
                "name": canonicalize_name(installed.metadata["Name"]),
                "version": installed.version,
                "license": _license(name),
                "relationship": (
                    "root" if name == root else "direct" if name in direct else "transitive"
                ),
            }
        )
    return packages


def build_inventory() -> dict[str, object]:
    lock = PUBLIC_ROOT / "uv.lock"
    return {
        "inventory_version": 1,
        "source": "installed distribution metadata resolved by the checked-in uv lock",
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "platform": sys.platform,
        "machine": platform.machine().lower(),
        "uv_lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
        "scopes": {
            "base": _scope(None),
            "mcp-host": _scope("mcp-host"),
        },
    }


def serialize_inventory(document: dict[str, object]) -> str:
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the exact installed production dependency and license inventory."
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    rendered = serialize_inventory(build_inventory())
    output = cast(Path | None, args.output)
    if output is None:
        print(rendered, end="")
    else:
        output.write_text(rendered, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
