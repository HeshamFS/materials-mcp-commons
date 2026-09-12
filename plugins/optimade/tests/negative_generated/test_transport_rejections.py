"""Generated negative controls for the HTTPS trust boundary.

No response in this module is scientific data or positive integration evidence.
"""

from __future__ import annotations

import http.client
import socket
import time
from collections.abc import Mapping
from typing import Any, ClassVar, cast

import pytest

from materials_mcp_optimade import transport as transport_module
from materials_mcp_optimade.errors import TransportError
from materials_mcp_optimade.transport import BoundedHttpsTransport, TrustedEndpoint


class _NegativeResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        body: bytes = b"",
        headers: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self.status = status
        self.headers = http.client.HTTPMessage()
        for name, value in headers:
            self.headers.add_header(name, value)
        self._body = body

    def read(self, amount: int | None = None) -> bytes:
        if not self._body:
            return b""
        size = len(self._body) if amount is None else amount
        chunk, self._body = self._body[:size], self._body[size:]
        return chunk


class _NoSocketConnection:
    sock = None


def _read_negative_response(
    *,
    body: bytes,
    headers: tuple[tuple[str, str], ...],
    max_bytes: int = 8,
) -> bytes:
    response = _NegativeResponse(body=body, headers=headers)
    return transport_module._read_bounded(  # pyright: ignore[reportPrivateUsage]
        cast(Any, response),
        max_bytes=max_bytes,
        deadline=time.monotonic() + 1.0,
        read_timeout=0.5,
        connection=cast(Any, _NoSocketConnection()),
    )


@pytest.mark.parametrize(
    "headers, body, max_bytes, code",
    [
        (
            (("Content-Length", "1"), ("Content-Length", "1")),
            b"x",
            8,
            "response-rejected",
        ),
        (
            (("Content-Length", "1"), ("Transfer-Encoding", "chunked")),
            b"x",
            8,
            "response-rejected",
        ),
        ((("Transfer-Encoding", "gzip"),), b"x", 8, "response-rejected"),
        ((("Content-Encoding", "gzip"),), b"x", 8, "content-encoding-rejected"),
        (
            (("Content-Encoding", "identity"), ("Content-Encoding", "identity")),
            b"x",
            8,
            "response-rejected",
        ),
        ((("Content-Length", "2"),), b"x", 8, "response-rejected"),
        ((("Content-Length", "9"),), b"", 8, "response-too-large"),
    ],
)
def test_ambiguous_or_unbounded_response_framing_is_rejected(
    headers: tuple[tuple[str, str], ...],
    body: bytes,
    max_bytes: int,
    code: str,
) -> None:
    with pytest.raises(TransportError) as captured:
        _read_negative_response(body=body, headers=headers, max_bytes=max_bytes)
    assert captured.value.code == code


def test_dns_resolution_is_inside_the_total_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    def delayed_resolution(*args: object, **kwargs: object) -> list[object]:
        del args, kwargs
        time.sleep(0.1)
        return []

    monkeypatch.setattr(transport_module.socket, "getaddrinfo", delayed_resolution)
    transport = BoundedHttpsTransport(
        connect_timeout=0.01,
        read_timeout=0.01,
        total_timeout=0.02,
        max_attempts=1,
    )

    with pytest.raises(TransportError) as captured:
        transport.get(TrustedEndpoint.from_url("https://providers.optimade.org"), "/v1/links")
    assert captured.value.code == "dns-timeout"
    assert captured.value.retryable is True


def test_dns_resolution_requests_ipv4_only(monkeypatch: pytest.MonkeyPatch) -> None:
    observed_families: list[int] = []

    def ipv4_resolution(
        host: str,
        port: int,
        *,
        family: int,
        type: int,
        proto: int,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        del host, port, type, proto
        observed_families.append(family)
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("1.1.1.1", 443))]

    monkeypatch.setattr(transport_module.socket, "getaddrinfo", ipv4_resolution)
    endpoint = TrustedEndpoint.from_url("https://providers.optimade.org")
    assert transport_module._resolve(  # pyright: ignore[reportPrivateUsage]
        endpoint, timeout=0.5
    ) == ("1.1.1.1",)
    assert observed_families == [socket.AF_INET]


class _NegativeStatusConnection:
    statuses: ClassVar[list[int]] = []
    requests: ClassVar[list[tuple[str, str]]] = []
    request_delay: ClassVar[float] = 0.0

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        self.sock = None

    def request(self, method: str, target: str, *, headers: Mapping[str, str]) -> None:
        del headers
        self.requests.append((method, target))
        time.sleep(self.request_delay)

    def getresponse(self) -> http.client.HTTPResponse:
        status = self.statuses.pop(0)
        response = _NegativeResponse(
            status=status,
            headers=(("Content-Type", "application/json"), ("Content-Length", "0")),
        )
        return cast(Any, response)

    def close(self) -> None:
        return None


def _negative_status_transport(
    monkeypatch: pytest.MonkeyPatch,
    statuses: list[int],
    *,
    connect_timeout: float = 0.5,
    read_timeout: float = 0.5,
    total_timeout: float = 1.0,
) -> BoundedHttpsTransport:
    _NegativeStatusConnection.statuses = list(statuses)
    _NegativeStatusConnection.requests = []
    _NegativeStatusConnection.request_delay = 0.0

    def approved_dns(endpoint: TrustedEndpoint, *, timeout: float) -> tuple[str, ...]:
        del endpoint, timeout
        return ("1.1.1.1",)

    monkeypatch.setattr(transport_module, "_resolve", approved_dns)
    monkeypatch.setattr(transport_module, "_PinnedHTTPSConnection", _NegativeStatusConnection)
    return BoundedHttpsTransport(
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
        total_timeout=total_timeout,
        max_attempts=2,
    )


def test_redirect_is_rejected_without_following_or_retrying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _negative_status_transport(monkeypatch, [302])

    with pytest.raises(TransportError) as captured:
        transport.get(TrustedEndpoint.from_url("https://providers.optimade.org"), "/v1/links")
    assert captured.value.code == "redirect-rejected"
    assert _NegativeStatusConnection.requests == [("GET", "/v1/links")]


def test_retryable_status_uses_exactly_the_configured_attempt_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _negative_status_transport(monkeypatch, [503, 503])

    with pytest.raises(TransportError) as captured:
        transport.get(TrustedEndpoint.from_url("https://providers.optimade.org"), "/v1/links")
    assert captured.value.code == "http-status"
    assert captured.value.http_status == 503
    assert captured.value.retryable is True
    assert _NegativeStatusConnection.requests == [
        ("GET", "/v1/links"),
        ("GET", "/v1/links"),
    ]


def test_request_header_phase_cannot_escape_the_total_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _negative_status_transport(
        monkeypatch,
        [200],
        connect_timeout=0.01,
        read_timeout=0.01,
        total_timeout=0.02,
    )
    _NegativeStatusConnection.request_delay = 0.03

    with pytest.raises(TransportError) as captured:
        transport.get(TrustedEndpoint.from_url("https://providers.optimade.org"), "/v1/links")
    assert captured.value.code == "request-timeout"
    assert _NegativeStatusConnection.requests == [("GET", "/v1/links")]
