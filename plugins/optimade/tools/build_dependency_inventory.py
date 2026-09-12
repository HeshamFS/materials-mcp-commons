"""Build the exact installed runtime dependency and license inventory."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import sysconfig
from collections import deque
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from typing import cast

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

PLUGIN_ROOT = Path(__file__).parents[1]
ROOT_DISTRIBUTION = "materials-mcp-optimade"
_CLASSIFIER_LICENSES = {
    "License :: OSI Approved :: Apache Software License": "Apache-2.0",
    "License :: OSI Approved :: BSD License": "BSD",
    "License :: OSI Approved :: MIT License": "MIT",
    "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "License :: OSI Approved :: Python Software Foundation License": "PSF-2.0",
}
_LICENSE_FILE_HASHES = {
    (
        "tiktoken",
        "258463fc3788f1f9b6a3f1820d8a87481ac24018d53167597e25d3e9031851ca",
    ): "MIT",
    (
        "tiktoken",
        "418cb499b436128d653d79941333a5437b7be2ea9213dcc2f04d15d5d2c51d86",
    ): "MIT",
}


class DependencyInventoryError(RuntimeError):
    """The installed production graph cannot be inventoried exactly."""


def _machine() -> str:
    observed = platform.machine().strip().lower()
    if observed:
        return observed
    platform_tag = sysconfig.get_platform().lower()
    for candidate in ("x86_64", "amd64", "aarch64", "arm64"):
        if candidate in platform_tag:
            return candidate
    raise DependencyInventoryError("Machine architecture is unavailable")


def _license(name: str) -> str:
    installed = distribution(name)
    metadata = installed.metadata
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
    for relative in installed.files or ():
        if "license" not in str(relative).lower():
            continue
        path = cast(Path, installed.locate_file(relative))
        if not path.is_file():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        mapped = _LICENSE_FILE_HASHES.get((canonicalize_name(name), digest))
        if mapped is not None:
            return mapped
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


def build_inventory() -> dict[str, object]:
    root = canonicalize_name(ROOT_DISTRIBUTION)
    queue: deque[tuple[str, frozenset[str]]] = deque([(root, frozenset())])
    visited: dict[str, frozenset[str]] = {}
    direct: set[str] = set()
    while queue:
        name, extras = queue.popleft()
        combined = visited.get(name, frozenset()) | extras
        if visited.get(name) == combined:
            continue
        visited[name] = combined
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
    for name in sorted(visited):
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
    lock = PLUGIN_ROOT / "uv.lock"
    return {
        "inventory_version": 1,
        "source": "installed distribution metadata resolved by the checked-in uv lock",
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "platform": sys.platform,
        "machine": _machine(),
        "uv_lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
        "packages": packages,
    }


def serialize_inventory(document: dict[str, object]) -> str:
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
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
