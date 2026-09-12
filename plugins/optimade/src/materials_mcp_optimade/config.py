"""Immutable reviewed provider, rights, and citation configuration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Final, Literal

REGISTRY_BASE_URL: Final = "https://providers.optimade.org"
REGISTRY_LINKS_URL: Final = f"{REGISTRY_BASE_URL}/v1/links"


def _wire_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class RightsRecord:
    """A dated rights review; absence of reviewed terms is explicit and fail-closed."""

    basis: Literal["license", "public-domain", "access-only"]
    identifier: str
    terms_uri: str
    terms_sha256: str | None
    review_status: Literal["reviewed", "unavailable"]
    redistribution: Literal["permitted", "not-permitted", "unknown"]
    attribution: str
    reviewed_at: datetime
    expires_at: datetime

    def is_current(self, at: datetime) -> bool:
        if at.utcoffset() is None:
            raise ValueError("Rights comparison time must include a UTC offset")
        return self.reviewed_at <= at.astimezone(UTC) < self.expires_at

    def permits_redistribution(self, at: datetime) -> bool:
        return (
            self.review_status == "reviewed"
            and self.terms_sha256 is not None
            and self.redistribution == "permitted"
            and self.is_current(at)
        )

    def to_document(self) -> dict[str, object]:
        return {
            "basis": self.basis,
            "identifier": self.identifier,
            "terms_uri": self.terms_uri,
            "terms_sha256": self.terms_sha256,
            "review_status": self.review_status,
            "redistribution": self.redistribution,
            "attribution": self.attribution,
            "reviewed_at": _wire_time(self.reviewed_at),
            "expires_at": _wire_time(self.expires_at),
        }


@dataclass(frozen=True)
class CitationRecord:
    citation_ref: str
    title: str
    authors: tuple[str, ...]
    year: int
    doi: str

    def to_document(self) -> dict[str, object]:
        return {
            "citation_ref": self.citation_ref,
            "title": self.title,
            "authors": list(self.authors),
            "year": self.year,
            "identifier": {"scheme": "doi", "value": self.doi},
            "uri": f"https://doi.org/{self.doi}",
        }


@dataclass(frozen=True)
class ProviderConfig:
    provider_id: Literal["mp", "nmd"]
    database_id: Literal["mp", "nmd"]
    name: str
    index_base_url: str
    api_base_url: str
    homepage: str
    rights: RightsRecord
    citation: CitationRecord


_REVIEWED_AT = datetime(2026, 9, 12, 9, 50, tzinfo=UTC)
_EXPIRES_AT = datetime(2026, 10, 12, tzinfo=UTC)

PROVIDERS = MappingProxyType(
    {
        "mp": ProviderConfig(
            provider_id="mp",
            database_id="mp",
            name="The Materials Project",
            index_base_url="https://providers.optimade.org/index-metadbs/mp",
            api_base_url="https://optimade.materialsproject.org",
            homepage="https://materialsproject.org/",
            rights=RightsRecord(
                basis="access-only",
                identifier="NOASSERTION",
                terms_uri="https://materialsproject.org/about/terms",
                terms_sha256=None,
                review_status="unavailable",
                redistribution="unknown",
                attribution=(
                    "Cite the Materials Project and every record-specific source required "
                    "by the provider; this record grants no redistribution permission."
                ),
                reviewed_at=_REVIEWED_AT,
                expires_at=_EXPIRES_AT,
            ),
            citation=CitationRecord(
                citation_ref="https://doi.org/10.1038/s41563-025-02272-0",
                title="Accelerated data-driven materials science with the Materials Project",
                authors=("Matthew K. Horton et al.",),
                year=2025,
                doi="10.1038/s41563-025-02272-0",
            ),
        ),
        "nmd": ProviderConfig(
            provider_id="nmd",
            database_id="nmd",
            name="novel materials discovery (NOMAD)",
            index_base_url="https://providers.optimade.org/index-metadbs/nmd",
            api_base_url="https://nomad-lab.eu/prod/v1/optimade",
            homepage="https://nomad-lab.eu/",
            rights=RightsRecord(
                basis="license",
                identifier="CC-BY-4.0",
                terms_uri="https://nomad-lab.eu/nomad-lab/terms.html",
                terms_sha256=("174713534aece4cfdba681cdd2cb8436969b446eb3a9bc6dc7b04551bb4094ed"),
                review_status="reviewed",
                redistribution="permitted",
                attribution=(
                    "Attribute NOMAD, the source record, and identified submitters or "
                    "right-holders; preserve applicable dataset and publication citations."
                ),
                reviewed_at=_REVIEWED_AT,
                expires_at=_EXPIRES_AT,
            ),
            citation=CitationRecord(
                citation_ref="https://doi.org/10.21105/joss.05388",
                title=(
                    "NOMAD: A distributed web-based platform for managing materials "
                    "science research data"
                ),
                authors=("Markus Scheidgen et al.",),
                year=2023,
                doi="10.21105/joss.05388",
            ),
        ),
    }
)


def provider_config(provider_id: str) -> ProviderConfig:
    """Resolve only the exact reviewed execution allowlist."""

    try:
        return PROVIDERS[provider_id]
    except KeyError as error:
        raise ValueError("Provider is outside the reviewed execution allowlist") from error
