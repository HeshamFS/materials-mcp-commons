from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import cast

PUBLIC_ROOT = Path(__file__).parents[1]
PREVIOUS_ENGINE_REF = "a431239fc196efe3bdfed15b6b146c8365ee7575"
UV_VERSION = "0.9.18"


class InstallLifecycleError(RuntimeError):
    """A release installation lifecycle step failed."""


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


def _extract_git_archive(reference: str, destination: Path) -> None:
    archive = destination.parent / "previous.tar"
    with archive.open("wb") as handle:
        completed = subprocess.run(
            ["git", "archive", "--format=tar", reference],
            cwd=PUBLIC_ROOT,
            check=False,
            stdout=handle,
            stderr=subprocess.PIPE,
        )
    if completed.returncode:
        raise InstallLifecycleError(completed.stderr.decode("utf-8", errors="replace").strip())
    destination.mkdir()
    resolved = destination.resolve()
    with tarfile.open(archive) as package:
        for member in package.getmembers():
            target = (destination / member.name).resolve()
            if resolved not in target.parents and target != resolved:
                raise InstallLifecycleError("Git archive contains an unsafe path")
            if member.issym() or member.islnk():
                raise InstallLifecycleError("Git archive contains an unsupported link")
        package.extractall(destination, filter="data")


def _build(source: Path, destination: Path, uv: str) -> tuple[Path, Path]:
    destination.mkdir()
    _run([uv, "build", "--no-sources", "--out-dir", str(destination)], cwd=source)
    wheels = sorted(destination.glob("*.whl"))
    sdists = sorted(destination.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise InstallLifecycleError("Build did not produce exactly one wheel and one sdist")
    return wheels[0], sdists[0]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _environment_python(environment: Path) -> Path:
    return environment / "Scripts/python.exe" if os.name == "nt" else environment / "bin/python"


def _installed_version(python: Path) -> str:
    return _run(
        [
            str(python),
            "-c",
            "from importlib.metadata import version; print(version('materials-mcp-commons'))",
        ]
    )


def _assert_absent(python: Path) -> None:
    marker = _run(
        [
            str(python),
            "-c",
            "import importlib.util; print(importlib.util.find_spec('materials_mcp_commons'))",
        ]
    )
    if marker != "None":
        raise InstallLifecycleError("Engine import remained after uninstall")


def _project_version(root: Path) -> str:
    with (root / "pyproject.toml").open("rb") as handle:
        project = cast(dict[str, object], tomllib.load(handle)["project"])
    return cast(str, project["version"])


def verify_install_lifecycle(uv: str) -> dict[str, object]:
    actual_uv = _run([uv, "--version"]).split()[1]
    if actual_uv != UV_VERSION:
        raise InstallLifecycleError(f"Expected uv {UV_VERSION}, found {actual_uv}")
    with tempfile.TemporaryDirectory(prefix="materials-mcp-install-lifecycle-") as raw:
        work = Path(raw)
        previous_source = work / "previous-source"
        current_source = work / "current-source"
        _extract_git_archive(PREVIOUS_ENGINE_REF, previous_source)
        _extract_git_archive("HEAD", current_source)
        previous_version = _project_version(previous_source)
        current_version = _project_version(current_source)
        previous_wheel, _ = _build(previous_source, work / "previous-dist", uv)
        current_wheel, current_sdist = _build(current_source, work / "current-dist", uv)
        environment = work / "environment"
        _run([uv, "venv", str(environment), "--python", sys.executable])
        python = _environment_python(environment)

        _run([uv, "pip", "install", "--python", str(python), str(previous_wheel)])
        if _installed_version(python) != previous_version:
            raise InstallLifecycleError("Previous wheel version mismatch")
        _run([uv, "pip", "install", "--python", str(python), "--upgrade", str(current_wheel)])
        if _installed_version(python) != current_version:
            raise InstallLifecycleError("Upgrade did not select the current wheel")
        _run([uv, "pip", "check", "--python", str(python)])
        _run([uv, "pip", "uninstall", "--python", str(python), "materials-mcp-commons"])
        _assert_absent(python)

        _run(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(python),
                f"{current_wheel}[mcp-host]",
            ]
        )
        _run([str(python), "-c", "import materials_mcp_commons, mcp"])
        _run([uv, "pip", "check", "--python", str(python)])
        _run([uv, "pip", "uninstall", "--python", str(python), "materials-mcp-commons"])
        _assert_absent(python)

        return {
            "report_version": 1,
            "platform": sys.platform,
            "python": f"{sys.version_info.major}.{sys.version_info.minor}",
            "uv": UV_VERSION,
            "previous": {"git_ref": PREVIOUS_ENGINE_REF, "version": previous_version},
            "current": {
                "version": current_version,
                "wheel_sha256": _sha256(current_wheel),
                "sdist_sha256": _sha256(current_sdist),
            },
            "steps": [
                "install-previous-wheel",
                "upgrade-to-current-wheel",
                "dependency-check",
                "uninstall-and-import-absence",
                "install-current-mcp-host-extra",
                "host-import-and-dependency-check",
                "uninstall-and-import-absence",
            ],
            "result": "pass",
        }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify clean install, upgrade, host-extra install, and removal."
    )
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
