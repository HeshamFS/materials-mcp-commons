"""Rights-gated, bounded local export for exact OPTIMADE records."""

from __future__ import annotations

import errno
import hashlib
import json
import math
import os
import re
import stat
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal, cast

from .client import ExactRecordRequest, OptimadeClient
from .config import PROVIDERS, ProviderConfig
from .contracts import SCHEMA_BASE, is_supported_api_version
from .errors import ExportError, ProviderProtocolError
from .transport import HttpResponse

EXPORT_PROVENANCE_SCHEMA = f"{SCHEMA_BASE}export-provenance.extension.schema.json"
_DESTINATION_PATTERN = re.compile(
    r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))(?!.*\\)[A-Za-z0-9._-]+"
    r"(?:/[A-Za-z0-9._-]+)*$"
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_ABSOLUTE_REFERENCE_PATTERN = re.compile(
    r"^(?:https://[^\s]+|urn:[A-Za-z0-9][A-Za-z0-9()+,.:=@;$_!*'%/?#-]*)$"
)
_CHEMICAL_SYMBOL_PATTERN = re.compile(r"^(?:[A-Z][a-z]?|X)$")
_CIF_FIELDS = (
    "lattice_vectors",
    "cartesian_site_positions",
    "species_at_sites",
    "species",
    "dimension_types",
    "nperiodic_dimensions",
    "nsites",
)
_MAX_CIF_SITES = 100_000
_MAX_EXPORTED_BYTES = 8 * 1024 * 1024


def _wire_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _reference(kind: str, *values: str) -> str:
    digest = hashlib.sha256("\0".join(values).encode("utf-8")).hexdigest()
    return f"urn:materials-mcp:optimade:{kind}:{digest}"


def _object(value: object, name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise ProviderProtocolError("provider-shape", f"Provider {name} must be an object")
    return cast(dict[str, object], value)


def _array(value: object, name: str) -> list[object]:
    if type(value) is not list:
        raise ProviderProtocolError("provider-shape", f"Provider {name} must be an array")
    return cast(list[object], value)


def _finite_number(value: object, name: str) -> float:
    if type(value) not in {int, float}:
        raise ExportError("cif-source-invalid", f"{name} must be a finite number")
    result = float(cast(int | float, value))
    if not math.isfinite(result):
        raise ExportError("cif-source-invalid", f"{name} must be a finite number")
    return result


def _vector3(value: object, name: str) -> tuple[float, float, float]:
    items = _array(value, name)
    if len(items) != 3:
        raise ExportError("cif-source-invalid", f"{name} must have exactly three values")
    return (
        _finite_number(items[0], name),
        _finite_number(items[1], name),
        _finite_number(items[2], name),
    )


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(first * second for first, second in zip(left, right, strict=True))


def _length(vector: Sequence[float]) -> float:
    return math.sqrt(_dot(vector, vector))


def _angle(first: Sequence[float], second: Sequence[float]) -> float:
    denominator = _length(first) * _length(second)
    if denominator <= 1e-15:
        raise ExportError("cif-source-invalid", "Lattice vector length is zero")
    cosine = max(-1.0, min(1.0, _dot(first, second) / denominator))
    return math.degrees(math.acos(cosine))


def _inverse3(matrix: Sequence[Sequence[float]]) -> tuple[tuple[float, float, float], ...]:
    a, b, c = matrix[0]
    d, e, f = matrix[1]
    g, h, i = matrix[2]
    determinant = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if not math.isfinite(determinant) or abs(determinant) <= 1e-12:
        raise ExportError("cif-source-invalid", "Lattice matrix is singular")
    scale = 1.0 / determinant
    return (
        ((e * i - f * h) * scale, (c * h - b * i) * scale, (b * f - c * e) * scale),
        ((f * g - d * i) * scale, (a * i - c * g) * scale, (c * d - a * f) * scale),
        ((d * h - e * g) * scale, (b * g - a * h) * scale, (a * e - b * d) * scale),
    )


def _fractional(
    cartesian: Sequence[float], inverse: Sequence[Sequence[float]]
) -> tuple[float, float, float]:
    values = tuple(
        sum(cartesian[row] * inverse[row][column] for row in range(3)) for column in range(3)
    )
    wrapped = tuple(value % 1.0 for value in values)
    return cast(
        tuple[float, float, float],
        tuple(0.0 if abs(value - 1.0) < 1e-12 else value for value in wrapped),
    )


def _cif_number(value: float) -> str:
    normalized = 0.0 if abs(value) < 5e-16 else value
    return format(normalized, ".15g")


def _is_reparse_point(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise ExportError(
            "export-path-unavailable", "Export path metadata is unavailable"
        ) from error
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return path.is_symlink() or bool(attributes & reparse_flag)


@dataclass(frozen=True)
class _ExportRequest:
    provider_id: Literal["mp", "nmd"]
    database_id: Literal["mp", "nmd"]
    entry_type: Literal["structures", "references"]
    entry_id: str
    format: Literal["optimade-json", "cif"]
    destination: str
    expected_response_sha256: str | None

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> _ExportRequest:
        required = {
            "provider_id",
            "database_id",
            "entry_type",
            "entry_id",
            "format",
            "destination",
            "overwrite",
        }
        if not required.issubset(payload) or set(payload) - (
            required | {"expected_response_sha256"}
        ):
            raise ExportError("input-shape", "Export input fields do not match the contract")
        provider_id = payload.get("provider_id")
        if type(provider_id) is not str or provider_id not in PROVIDERS:
            raise ExportError("provider-not-allowed", "Export provider is not reviewed")
        config = PROVIDERS[provider_id]
        database_id = payload.get("database_id")
        if database_id != config.database_id:
            raise ExportError("database-mismatch", "Export database does not match its provider")
        entry_type = payload.get("entry_type")
        if entry_type not in {"structures", "references"}:
            raise ExportError("input-shape", "Export entry type is invalid")
        entry_id = payload.get("entry_id")
        if type(entry_id) is not str or not 1 <= len(entry_id) <= 512:
            raise ExportError("input-shape", "Export entry ID is invalid")
        export_format = payload.get("format")
        if export_format not in {"optimade-json", "cif"}:
            raise ExportError("input-shape", "Export format is invalid")
        if export_format == "cif" and entry_type != "structures":
            raise ExportError("input-shape", "CIF export requires a structure record")
        destination = payload.get("destination")
        if (
            type(destination) is not str
            or len(destination) > 512
            or _DESTINATION_PATTERN.fullmatch(destination) is None
        ):
            raise ExportError(
                "export-path-rejected", "Export destination is not a safe relative path"
            )
        if payload.get("overwrite") is not False:
            raise ExportError("overwrite-rejected", "Export never overwrites an existing path")
        expected = payload.get("expected_response_sha256")
        if expected is not None and (
            type(expected) is not str or _SHA256_PATTERN.fullmatch(expected) is None
        ):
            raise ExportError("input-shape", "Expected source response SHA-256 is invalid")
        return cls(
            provider_id=cast(Literal["mp", "nmd"], provider_id),
            database_id=cast(Literal["mp", "nmd"], database_id),
            entry_type=cast(Literal["structures", "references"], entry_type),
            entry_id=entry_id,
            format=cast(Literal["optimade-json", "cif"], export_format),
            destination=destination,
            expected_response_sha256=expected,
        )


class OptimadeExporter:
    """Persist one exact record beneath an explicit pre-existing export root."""

    def __init__(self, export_root: Path, client: OptimadeClient | None = None) -> None:
        if not export_root.is_absolute() or not export_root.exists() or not export_root.is_dir():
            raise ExportError(
                "export-root-invalid", "Export root must be an existing absolute directory"
            )
        if _is_reparse_point(export_root):
            raise ExportError(
                "export-root-invalid", "Export root cannot be a link or reparse point"
            )
        self._root = export_root.resolve(strict=True)
        self._client = client or OptimadeClient()

    def _destination(self, relative: str) -> Path:
        parts = PurePosixPath(relative).parts
        destination = self._root.joinpath(*parts)
        parent = destination.parent
        if not parent.exists() or not parent.is_dir():
            raise ExportError(
                "export-parent-missing", "Export destination parent must already exist"
            )
        current = self._root
        for part in parts[:-1]:
            current /= part
            if _is_reparse_point(current) or not current.is_dir():
                raise ExportError(
                    "export-path-rejected", "Export path traverses an unsafe directory"
                )
        resolved_parent = parent.resolve(strict=True)
        if resolved_parent != self._root and self._root not in resolved_parent.parents:
            raise ExportError("export-path-rejected", "Export path escapes its configured root")
        if destination.exists() or destination.is_symlink():
            raise ExportError("overwrite-rejected", "Export destination already exists")
        return destination

    @staticmethod
    def _api_version(document: Mapping[str, object]) -> str:
        meta = _object(document.get("meta"), "response metadata")
        version = meta.get("api_version")
        if not is_supported_api_version(version):
            raise ExportError(
                "api-version-unsupported",
                "Export requires a stable response in the verified OPTIMADE 1.2 patch line",
            )
        return version

    @staticmethod
    def _cif(
        document: Mapping[str, object],
        *,
        config: ProviderConfig,
        response: HttpResponse,
        entry_id: str,
    ) -> bytes:
        data = _object(document.get("data"), "structure data")
        attributes = _object(data.get("attributes"), "structure attributes")
        if attributes.get("dimension_types") != [1, 1, 1] or (
            attributes.get("nperiodic_dimensions") != 3
        ):
            raise ExportError(
                "cif-unsupported", "CIF export currently requires a 3D periodic structure"
            )
        lattice_items = _array(attributes.get("lattice_vectors"), "lattice vectors")
        if len(lattice_items) != 3:
            raise ExportError("cif-source-invalid", "Lattice must contain exactly three vectors")
        lattice = tuple(
            _vector3(value, f"lattice vector {index}") for index, value in enumerate(lattice_items)
        )
        inverse = _inverse3(lattice)
        position_items = _array(
            attributes.get("cartesian_site_positions"), "Cartesian site positions"
        )
        species_at_sites = _array(attributes.get("species_at_sites"), "species at sites")
        if not 1 <= len(position_items) <= _MAX_CIF_SITES or len(species_at_sites) != len(
            position_items
        ):
            raise ExportError(
                "cif-source-invalid", "Site arrays are empty, oversized, or inconsistent"
            )
        nsites = attributes.get("nsites")
        if type(nsites) is not int or nsites != len(position_items):
            raise ExportError(
                "cif-source-invalid", "Declared site count does not match site arrays"
            )
        species_records = _array(attributes.get("species"), "species")
        species_by_name: dict[str, tuple[tuple[str, float], ...]] = {}
        for raw_species in species_records:
            species = _object(raw_species, "species record")
            name = species.get("name")
            if type(name) is not str or not name or len(name) > 128 or name in species_by_name:
                raise ExportError("cif-source-invalid", "Species names must be bounded and unique")
            symbols = _array(species.get("chemical_symbols"), "species chemical symbols")
            concentrations = _array(species.get("concentration"), "species concentrations")
            if not 1 <= len(symbols) <= 16 or len(symbols) != len(concentrations):
                raise ExportError(
                    "cif-source-invalid", "Species composition arrays are inconsistent"
                )
            components: list[tuple[str, float]] = []
            for symbol_value, concentration_value in zip(symbols, concentrations, strict=True):
                if type(symbol_value) is not str:
                    raise ExportError("cif-source-invalid", "Chemical symbol is not a string")
                concentration = _finite_number(concentration_value, "species concentration")
                if not 0.0 <= concentration <= 1.0:
                    raise ExportError(
                        "cif-source-invalid", "Species concentration is outside 0 to 1"
                    )
                if symbol_value == "vacancy" or concentration == 0.0:
                    continue
                if _CHEMICAL_SYMBOL_PATTERN.fullmatch(symbol_value) is None:
                    raise ExportError("cif-source-invalid", "Chemical symbol is not CIF-compatible")
                components.append((symbol_value, concentration))
            if not components or abs(sum(item[1] for item in components) - 1.0) > 1e-8:
                raise ExportError(
                    "cif-unsupported",
                    "CIF export does not support vacancy-bearing or incomplete occupied sites",
                )
            species_by_name[name] = tuple(components)
        a_vector, b_vector, c_vector = lattice
        lines = [
            f"data_optimade_{hashlib.sha256(entry_id.encode('utf-8')).hexdigest()[:16]}",
            "#",
            f"# Source provider: {config.name}",
            f"# Source record: {response.request_uri}",
            f"# Source response SHA-256: {response.sha256}",
            f"# Rights: {config.rights.identifier}",
            f"# Attribution: {config.rights.attribution}",
            f"# Citation: {config.citation.citation_ref}",
            "_audit_creation_method 'materials-mcp-optimade 0.1.0a1'",
            f"_cell_length_a {_cif_number(_length(a_vector))}",
            f"_cell_length_b {_cif_number(_length(b_vector))}",
            f"_cell_length_c {_cif_number(_length(c_vector))}",
            f"_cell_angle_alpha {_cif_number(_angle(b_vector, c_vector))}",
            f"_cell_angle_beta {_cif_number(_angle(a_vector, c_vector))}",
            f"_cell_angle_gamma {_cif_number(_angle(a_vector, b_vector))}",
            "_space_group_name_H-M_alt 'P 1'",
            "_space_group_IT_number 1",
            "loop_",
            "_atom_site_label",
            "_atom_site_type_symbol",
            "_atom_site_fract_x",
            "_atom_site_fract_y",
            "_atom_site_fract_z",
            "_atom_site_occupancy",
        ]
        counters: dict[str, int] = {}
        for index, (position_raw, species_name_raw) in enumerate(
            zip(position_items, species_at_sites, strict=True)
        ):
            if type(species_name_raw) is not str or species_name_raw not in species_by_name:
                raise ExportError("cif-source-invalid", "Site refers to an unknown species")
            position = _vector3(position_raw, f"Cartesian site position {index}")
            x, y, z = _fractional(position, inverse)
            for symbol, occupancy in species_by_name[species_name_raw]:
                counters[symbol] = counters.get(symbol, 0) + 1
                lines.append(
                    " ".join(
                        (
                            f"{symbol}{counters[symbol]}",
                            symbol,
                            _cif_number(x),
                            _cif_number(y),
                            _cif_number(z),
                            _cif_number(occupancy),
                        )
                    )
                )
        rendered = ("\n".join(lines) + "\n").encode("utf-8")
        if len(rendered) > _MAX_EXPORTED_BYTES:
            raise ExportError("export-too-large", "Rendered CIF exceeds the export byte limit")
        return rendered

    def _write_posix(self, destination: Path, content: bytes) -> None:
        no_follow = getattr(os, "O_NOFOLLOW", None)
        directory_flag = getattr(os, "O_DIRECTORY", None)
        if (
            type(no_follow) is not int
            or type(directory_flag) is not int
            or os.open not in os.supports_dir_fd
            or os.unlink not in os.supports_dir_fd
        ):
            raise ExportError(
                "export-platform-unsupported",
                "This platform lacks handle-relative no-follow export primitives",
            )

        relative = destination.relative_to(self._root)
        directory_flags = os.O_RDONLY | directory_flag | no_follow
        file_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | no_follow
        directory_descriptors: list[int] = []
        descriptor: int | None = None
        created = False
        try:
            directory_descriptors.append(os.open(self._root, directory_flags))
            for part in relative.parts[:-1]:
                directory_descriptors.append(
                    os.open(part, directory_flags, dir_fd=directory_descriptors[-1])
                )
            descriptor = os.open(
                relative.name,
                file_flags,
                0o600,
                dir_fd=directory_descriptors[-1],
            )
            created = True
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                descriptor = None
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError as error:
            raise ExportError("overwrite-rejected", "Export destination already exists") from error
        except OSError as error:
            if descriptor is not None:
                os.close(descriptor)
            if created:
                with suppress(OSError):
                    os.unlink(relative.name, dir_fd=directory_descriptors[-1])
            if error.errno in {errno.ELOOP, errno.ENOTDIR}:
                raise ExportError(
                    "export-path-rejected", "Export path changed or traversed an unsafe object"
                ) from error
            raise ExportError(
                "export-write-failed", "Export artifact could not be written"
            ) from error
        finally:
            for directory_descriptor in reversed(directory_descriptors):
                with suppress(OSError):
                    os.close(directory_descriptor)

    def _write(self, destination: Path, content: bytes) -> None:
        if os.name != "nt":
            self._write_posix(destination, content)
            return

        from ._windows_export import UnsafeExportPathError, write_exclusive

        try:
            write_exclusive(self._root, destination, content)
        except FileExistsError as error:
            raise ExportError("overwrite-rejected", "Export destination already exists") from error
        except UnsafeExportPathError as error:
            raise ExportError(
                "export-path-rejected", "Export path changed or traversed an unsafe object"
            ) from error
        except OSError as error:
            raise ExportError(
                "export-write-failed", "Export artifact could not be written"
            ) from error

    def export(self, payload: Mapping[str, object], *, request_ref: str) -> dict[str, object]:
        request = _ExportRequest.from_payload(payload)
        if (
            type(request_ref) is not str
            or len(request_ref) > 2048
            or _ABSOLUTE_REFERENCE_PATTERN.fullmatch(request_ref) is None
        ):
            raise ExportError("input-shape", "Export request reference is invalid")
        config = PROVIDERS[request.provider_id]
        started_at = datetime.now(UTC)
        if not config.rights.permits_redistribution(started_at):
            raise ExportError(
                "rights-denied",
                "Current reviewed provider rights do not affirmatively permit export",
            )
        destination = self._destination(request.destination)
        fields = _CIF_FIELDS if request.format == "cif" else ("immutable_id",)
        get_request = ExactRecordRequest(
            provider_id=request.provider_id,
            database_id=request.database_id,
            entry_id=request.entry_id,
            response_fields=fields,
            include=(),
            expected_immutable_id=None,
        )
        config, response, document = self._client.fetch_exact_record(
            request.entry_type,
            get_request,
            complete=request.format == "optimade-json",
        )
        api_version = self._api_version(document)
        if (
            request.expected_response_sha256 is not None
            and response.sha256 != request.expected_response_sha256
        ):
            raise ExportError(
                "source-precondition-failed",
                "Fresh provider response does not match the expected SHA-256",
            )
        exported_at = datetime.now(UTC)
        if not config.rights.permits_redistribution(exported_at):
            raise ExportError("rights-expired", "Provider rights expired before persistence")
        if request.format == "optimade-json":
            content = response.body
            media_type = response.headers.get("content-type", "application/vnd.api+json").split(
                ";", maxsplit=1
            )[0]
            projection: str | list[str] = "complete"
            operation = "byte-copy"
            notes = [
                "Artifact bytes are identical to the validated provider response bytes.",
                "Rights and attribution metadata remain attached to the returned artifact record.",
            ]
        else:
            content = self._cif(
                document,
                config=config,
                response=response,
                entry_id=request.entry_id,
            )
            media_type = "chemical/x-cif"
            projection = [*_CIF_FIELDS, "immutable_id"]
            operation = "optimade-cartesian-to-cif"
            notes = [
                "The 3D lattice is represented as a P 1 cell without claiming source symmetry.",
                "Cartesian coordinates were transformed to wrapped fractional coordinates.",
                "Species concentrations were emitted as CIF site occupancies.",
            ]
        if not content or len(content) > _MAX_EXPORTED_BYTES:
            raise ExportError(
                "export-too-large", "Export content is empty or exceeds its byte limit"
            )
        self._write(destination, content)
        artifact_sha256 = hashlib.sha256(content).hexdigest()
        extension: dict[str, object] = {
            "request_ref": request_ref,
            "provider_id": request.provider_id,
            "database_id": request.database_id,
            "entry_type": request.entry_type,
            "entry_id": request.entry_id,
            "format": request.format,
            "destination": request.destination,
            "requested_at": _wire_time(response.requested_at),
            "retrieved_at": _wire_time(response.retrieved_at),
            "exported_at": _wire_time(exported_at),
            "source": {
                "uri": response.request_uri,
                "media_type": response.headers.get(
                    "content-type", "application/vnd.api+json"
                ).split(";", maxsplit=1)[0],
                "size_bytes": len(response.body),
                "sha256": response.sha256,
                "api_version": api_version,
                "projection": projection,
            },
            "rights": config.rights.to_document(),
            "transformation": {
                "operation": operation,
                "implementation": "materials-mcp-optimade",
                "version": "1",
                "notes": notes,
            },
            "citation_refs": [config.citation.citation_ref],
        }
        provenance_ref = _reference("export-provenance", _canonical(extension).decode("utf-8"))
        uri = _reference("workspace-export", request.destination, artifact_sha256)
        return {
            "artifact_ref": _reference("export-artifact", request_ref, uri, artifact_sha256),
            "uri": uri,
            "media_type": media_type,
            "size_bytes": len(content),
            "sha256": artifact_sha256,
            "role": "output",
            "access_scope": "workspace",
            "provenance_ref": provenance_ref,
            "extensions": {EXPORT_PROVENANCE_SCHEMA: extension},
        }


__all__ = ["EXPORT_PROVENANCE_SCHEMA", "OptimadeExporter"]
