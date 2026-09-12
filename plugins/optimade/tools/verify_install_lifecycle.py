"""Build, inspect, install, execute entry-point discovery, and uninstall release artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import cast

PLUGIN_ROOT = Path(__file__).parents[1]
PUBLIC_ROOT = PLUGIN_ROOT.parents[1]
UV_VERSION = "0.9.18"


class InstallLifecycleError(RuntimeError):
    """A release artifact or clean-environment lifecycle check failed."""


def _run(arguments: list[str], *, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        arguments,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode:
        diagnostic = (completed.stderr or completed.stdout).strip()
        raise InstallLifecycleError(f"Command failed ({arguments[0]}): {diagnostic}")
    return completed.stdout.strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build(source: Path, destination: Path, uv: str) -> tuple[Path, Path]:
    destination.mkdir()
    _run([uv, "build", "--no-sources", "--out-dir", str(destination)], cwd=source)
    wheels = sorted(destination.glob("*.whl"))
    sdists = sorted(destination.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise InstallLifecycleError("Build did not produce exactly one wheel and one sdist")
    return wheels[0], sdists[0]


def _safe_member(name: str) -> None:
    path = PurePosixPath(name)
    lowered = {part.lower() for part in path.parts}
    if path.is_absolute() or ".." in path.parts:
        raise InstallLifecycleError("Artifact contains an unsafe path")
    if lowered & {"_internal", ".git", ".venv", "__pycache__"} or any(
        part.lower() == "agents.md" for part in path.parts
    ):
        raise InstallLifecycleError("Artifact contains internal or transient material")


def _inspect_artifacts(wheel: Path, sdist: Path) -> tuple[int, int]:
    with zipfile.ZipFile(wheel) as archive:
        wheel_names = archive.namelist()
        for name in wheel_names:
            _safe_member(name)
        required_wheel = {
            "materials_mcp_optimade/_windows_export.py",
            "materials_mcp_optimade/host.py",
            "materials_mcp_optimade/py.typed",
            "materials_mcp_optimade/declarative/manifest.json",
            "materials_mcp_optimade/declarative/schemas/export-provenance.extension.schema.json",
        }
        if not required_wheel.issubset(wheel_names):
            raise InstallLifecycleError("Wheel omits required runtime or declarative files")
    with tarfile.open(sdist) as archive:
        members = archive.getmembers()
        for member in members:
            _safe_member(member.name)
            if member.issym() or member.islnk():
                raise InstallLifecycleError("Source distribution contains a link")
        relative_names = {"/".join(PurePosixPath(member.name).parts[1:]) for member in members}
        required_sdist = {
            "README.md",
            "docs/runtime.md",
            "conformance/structural-report.json",
            "schemas/0.1.0/search-result.schema.json",
            "tests/test_live_engine_integration.py",
            "uv.lock",
        }
        if not required_sdist.issubset(relative_names):
            raise InstallLifecycleError("Source distribution omits required public evidence")
    return len(wheel_names), len(members)


def _environment_python(environment: Path) -> Path:
    return environment / "Scripts/python.exe" if os.name == "nt" else environment / "bin/python"


def _entry_point(environment: Path) -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    folder = "Scripts" if os.name == "nt" else "bin"
    return environment / folder / f"materials-mcp-optimade-host{suffix}"


def _installed_version(python: Path) -> str:
    return _run(
        [
            str(python),
            "-c",
            ("from importlib.metadata import version; print(version('materials-mcp-optimade'))"),
        ]
    )


def _module_state(python: Path, module: str) -> str:
    return _run(
        [
            str(python),
            "-c",
            f"import importlib.util; print(importlib.util.find_spec('{module}') is not None)",
        ]
    )


def verify_install_lifecycle(uv: str) -> dict[str, object]:
    actual_uv = _run([uv, "--version"]).split()[1]
    if actual_uv != UV_VERSION:
        raise InstallLifecycleError(f"Expected uv {UV_VERSION}, found {actual_uv}")
    with tempfile.TemporaryDirectory(prefix="materials-mcp-optimade-lifecycle-") as raw:
        work = Path(raw)
        engine_wheel, _ = _build(PUBLIC_ROOT, work / "engine-dist", uv)
        first_wheel, first_sdist = _build(PLUGIN_ROOT, work / "plugin-dist-first", uv)
        second_wheel, second_sdist = _build(PLUGIN_ROOT, work / "plugin-dist-second", uv)
        if (_sha256(first_wheel), _sha256(first_sdist)) != (
            _sha256(second_wheel),
            _sha256(second_sdist),
        ):
            raise InstallLifecycleError("Two clean plugin builds are not byte-identical")
        wheel_members, sdist_members = _inspect_artifacts(first_wheel, first_sdist)

        environment = work / "environment"
        _run([uv, "venv", str(environment), "--python", sys.executable])
        python = _environment_python(environment)
        _run(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(python),
                str(engine_wheel),
                str(first_wheel),
            ]
        )
        if _installed_version(python) != "0.1.0a1":
            raise InstallLifecycleError("Installed plugin version differs from the built wheel")
        _run(
            [
                str(python),
                "-c",
                "import materials_mcp_commons, materials_mcp_optimade",
            ]
        )
        if _module_state(python, "mcp") != "False":
            raise InstallLifecycleError("Default plugin install unexpectedly includes MCP")
        _run([uv, "pip", "check", "--python", str(python)])
        _run([uv, "pip", "uninstall", "--python", str(python), "materials-mcp-optimade"])
        if _module_state(python, "materials_mcp_optimade") != "False":
            raise InstallLifecycleError("Plugin import remained after uninstall")
        if _module_state(python, "materials_mcp_commons") != "True":
            raise InstallLifecycleError("Plugin uninstall removed the separate engine")

        _run(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(python),
                f"{first_wheel}[mcp-host]",
            ]
        )
        if _module_state(python, "mcp") != "True":
            raise InstallLifecycleError("Host extra did not install the official MCP SDK")
        entry_point = _entry_point(environment)
        if not entry_point.is_file():
            raise InstallLifecycleError("Host console entry point is absent")
        _run([str(entry_point), "--help"])
        _run([uv, "pip", "check", "--python", str(python)])
        _run([uv, "pip", "uninstall", "--python", str(python), "materials-mcp-optimade"])
        if _module_state(python, "materials_mcp_optimade") != "False":
            raise InstallLifecycleError("Host-extra plugin import remained after uninstall")

        return {
            "report_version": 1,
            "platform": sys.platform,
            "python": f"{sys.version_info.major}.{sys.version_info.minor}",
            "uv": UV_VERSION,
            "engine_wheel_sha256": _sha256(engine_wheel),
            "plugin": {
                "version": "0.1.0a1",
                "wheel_sha256": _sha256(first_wheel),
                "sdist_sha256": _sha256(first_sdist),
                "wheel_members": wheel_members,
                "sdist_members": sdist_members,
            },
            "steps": [
                "two-byte-identical-builds",
                "safe-wheel-and-sdist-members",
                "clean-default-install",
                "default-install-excludes-mcp",
                "dependency-check",
                "uninstall-preserves-engine",
                "clean-host-extra-install",
                "host-entry-point-help",
                "dependency-check",
                "uninstall-and-import-absence",
            ],
            "result": "pass",
        }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uv", default="uv")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    document = verify_install_lifecycle(cast(str, args.uv))
    rendered = json.dumps(document, indent=2, sort_keys=True) + "\n"
    output = cast(Path | None, args.output)
    if output is None:
        print(rendered, end="")
    else:
        output.write_text(rendered, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
