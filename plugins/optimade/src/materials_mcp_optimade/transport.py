"""Direct, DNS-pinned, bounded HTTPS GET transport for reviewed endpoints."""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import math
import re
import socket
import ssl
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from queue import Empty, Queue
from threading import BoundedSemaphore, Thread
from types import MappingProxyType
from typing import Final, Literal, cast
from urllib.parse import quote, urlencode, urlsplit

from .errors import ProviderProtocolError, TransportError

DEFAULT_MAX_RESPONSE_BYTES: Final = 2 * 1024 * 1024
DEFAULT_CONNECT_TIMEOUT_SECONDS: Final = 8.0
DEFAULT_READ_TIMEOUT_SECONDS: Final = 12.0
DEFAULT_TOTAL_TIMEOUT_SECONDS: Final = 25.0
MAX_REQUEST_URI_BYTES: Final = 8192
MAX_DNS_ADDRESSES: Final = 8
MAX_JSON_DEPTH: Final = 32
MAX_JSON_NODES: Final = 50_000
_HOST_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$")
_RETRYABLE_STATUSES = frozenset({429, 502, 503, 504})
_DNS_SLOTS = BoundedSemaphore(4)


@dataclass(frozen=True)
class TrustedEndpoint:
    hostname: str
    base_path: str

    @classmethod
    def from_url(cls, value: str) -> TrustedEndpoint:
        if type(value) is not str or len(value) > 2048:
            raise TransportError("endpoint-rejected", "Endpoint is not a bounded HTTPS URL")
        parsed = urlsplit(value)
        try:
            port = parsed.port
        except ValueError as error:
            raise TransportError("endpoint-rejected", "Endpoint port is invalid") from error
        if (
            parsed.scheme != "https"
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or port not in {None, 443}
            or parsed.query
            or parsed.fragment
        ):
            raise TransportError(
                "endpoint-rejected",
                "Endpoint must use credential-free HTTPS on the default port",
            )
        try:
            hostname = parsed.hostname.encode("idna").decode("ascii").lower()
        except UnicodeError as error:
            raise TransportError("endpoint-rejected", "Endpoint hostname is invalid") from error
        if _HOST_PATTERN.fullmatch(hostname) is None or ".." in hostname:
            raise TransportError("endpoint-rejected", "Endpoint hostname is invalid")
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            pass
        else:
            raise TransportError("endpoint-rejected", "Endpoint must use a reviewed DNS name")
        base_path = parsed.path.rstrip("/")
        _validate_path(base_path or "/")
        return cls(hostname=hostname, base_path=base_path)

    @property
    def origin(self) -> str:
        return f"https://{self.hostname}"

    def request_target(
        self,
        relative_path: str,
        query: Sequence[tuple[str, str]] = (),
    ) -> tuple[str, str]:
        _validate_path(relative_path)
        path = f"{self.base_path}{relative_path}"
        encoded_query = urlencode(query, doseq=False, safe="", quote_via=quote)
        target = f"{path}?{encoded_query}" if encoded_query else path
        uri = f"{self.origin}{target}"
        if len(uri.encode("utf-8")) > MAX_REQUEST_URI_BYTES:
            raise TransportError("request-uri-too-large", "Request URI exceeds the local limit")
        return target, uri


@dataclass(frozen=True)
class HttpResponse:
    request_uri: str
    status: int
    headers: Mapping[str, str]
    body: bytes
    sha256: str
    requested_at: datetime
    retrieved_at: datetime


def _validate_path(path: str) -> None:
    if (
        type(path) is not str
        or not path.startswith("/")
        or path.startswith("//")
        or "\\" in path
        or "?" in path
        or "#" in path
        or any(ord(char) < 0x20 for char in path)
    ):
        raise TransportError("path-rejected", "Request path is not a relative HTTPS path")
    decoded_segments = [segment.lower() for segment in path.split("/")]
    if any(segment in {".", "..", "%2e", "%2e%2e"} for segment in decoded_segments):
        raise TransportError("path-rejected", "Request path traversal is forbidden")


def quote_path_segment(value: str) -> str:
    if type(value) is not str or not value or len(value) > 512:
        raise TransportError("path-segment-rejected", "Path segment is empty or too large")
    if any(ord(char) < 0x20 for char in value):
        raise TransportError("path-segment-rejected", "Path segment contains control data")
    return quote(value, safe="")


def approved_ip_literals(values: Iterable[str]) -> tuple[str, ...]:
    approved: list[str] = []
    for raw in values:
        try:
            address = ipaddress.ip_address(raw)
        except ValueError as error:
            raise TransportError("dns-rejected", "DNS returned an invalid address") from error
        # The transport deliberately pins only public IPv4 literals. A syntactically
        # global IPv6 literal can still be a NAT64 translation address whose embedded
        # IPv4 destination is loopback, private, or link-local. Network-specific NAT64
        # prefixes cannot be identified reliably from the literal alone, so a partial
        # prefix denylist would leave the SSRF boundary dependent on the host network.
        # The reviewed providers publish A records; fail closed elsewhere.
        if address.version != 4 or not address.is_global:
            raise TransportError("dns-rejected", "DNS returned a non-public IPv4 address")
        normalized = address.compressed
        if normalized not in approved:
            approved.append(normalized)
        if len(approved) > MAX_DNS_ADDRESSES:
            raise TransportError("dns-rejected", "DNS returned too many addresses")
    if not approved:
        raise TransportError("dns-rejected", "DNS returned no usable global address")
    return tuple(approved)


def _resolve(endpoint: TrustedEndpoint, *, timeout: float) -> tuple[str, ...]:
    deadline = time.monotonic() + timeout
    if not _DNS_SLOTS.acquire(timeout=timeout):
        raise TransportError("dns-timeout", "DNS resolution capacity timed out", retryable=True)
    result: Queue[tuple[Literal["ok", "error"], object]] = Queue(maxsize=1)

    def resolve() -> None:
        try:
            records = socket.getaddrinfo(
                endpoint.hostname,
                443,
                family=socket.AF_INET,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
            )
            result.put(("ok", records))
        except BaseException as error:
            result.put(("error", error))
        finally:
            _DNS_SLOTS.release()

    Thread(target=resolve, name="optimade-dns", daemon=True).start()
    try:
        outcome, value = result.get(timeout=max(0.001, deadline - time.monotonic()))
    except Empty as error:
        raise TransportError(
            "dns-timeout", "Endpoint DNS resolution timed out", retryable=True
        ) from error
    if outcome == "error":
        raise TransportError("dns-failed", "Endpoint DNS resolution failed", retryable=True) from (
            value if isinstance(value, BaseException) else None
        )
    if type(value) is not list:
        raise TransportError("dns-failed", "Endpoint DNS resolution returned invalid data")
    literals: list[str] = []
    for raw_record in cast(list[object], value):
        if type(raw_record) is not tuple:
            raise TransportError("dns-failed", "Endpoint DNS resolution returned invalid data")
        record = cast(tuple[object, ...], raw_record)
        if len(record) < 5:
            raise TransportError("dns-failed", "Endpoint DNS resolution returned invalid data")
        socket_address = record[4]
        if type(socket_address) is not tuple or not socket_address:
            raise TransportError("dns-failed", "Endpoint DNS resolution returned invalid data")
        literal = cast(tuple[object, ...], socket_address)[0]
        if type(literal) is not str:
            raise TransportError("dns-failed", "Endpoint DNS resolution returned invalid data")
        literals.append(literal)
    return approved_ip_literals(literals)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        hostname: str,
        address: str,
        *,
        timeout: float,
        context: ssl.SSLContext,
    ) -> None:
        super().__init__(hostname, port=443, timeout=timeout, context=context)
        self._pinned_address = address
        self._ssl_context = context

    def connect(self) -> None:
        raw = socket.create_connection((self._pinned_address, 443), self.timeout)
        try:
            self.sock = self._ssl_context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def _content_type(headers: http.client.HTTPMessage) -> str:
    return headers.get_content_type().lower()


def _read_bounded(
    response: http.client.HTTPResponse,
    *,
    max_bytes: int,
    deadline: float,
    read_timeout: float,
    connection: _PinnedHTTPSConnection,
) -> bytes:
    lengths = response.headers.get_all("Content-Length", failobj=[]) or []
    if len(lengths) > 1:
        raise TransportError("response-rejected", "Response has duplicate length headers")
    transfers = response.headers.get_all("Transfer-Encoding", failobj=[]) or []
    if len(transfers) > 1 or (lengths and transfers):
        raise TransportError("response-rejected", "Response framing headers are ambiguous")
    if transfers and transfers[0].strip().lower() != "chunked":
        raise TransportError("response-rejected", "Response transfer encoding is unsupported")
    declared: int | None = None
    if lengths:
        try:
            declared = int(lengths[0])
        except ValueError as error:
            raise TransportError(
                "response-rejected", "Response length header is invalid"
            ) from error
        if declared < 0 or declared > max_bytes:
            raise TransportError("response-too-large", "Response exceeds the local byte limit")
    encodings = response.headers.get_all("Content-Encoding", failobj=[]) or []
    if len(encodings) > 1:
        raise TransportError("response-rejected", "Response has duplicate content encodings")
    encoding = (encodings[0] if encodings else "identity").strip().lower()
    if encoding not in {"", "identity"}:
        raise TransportError(
            "content-encoding-rejected",
            "Compressed provider responses are not accepted at this boundary",
        )
    chunks: list[bytes] = []
    total = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TransportError("request-timeout", "HTTPS request exceeded its total timeout")
        if connection.sock is not None:
            connection.sock.settimeout(min(read_timeout, remaining))
        try:
            chunk = response.read(min(65_536, max_bytes + 1 - total))
        except TimeoutError as error:
            raise TransportError(
                "request-timeout", "Provider response exceeded the read timeout", retryable=True
            ) from error
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise TransportError("response-too-large", "Response exceeds the local byte limit")
        chunks.append(chunk)
    body = b"".join(chunks)
    if declared is not None and len(body) != declared:
        raise TransportError("response-rejected", "Response length does not match its declaration")
    return body


class BoundedHttpsTransport:
    """GET-only transport with direct sockets, checked DNS, TLS, and no redirects."""

    def __init__(
        self,
        *,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
        read_timeout: float = DEFAULT_READ_TIMEOUT_SECONDS,
        total_timeout: float = DEFAULT_TOTAL_TIMEOUT_SECONDS,
        max_attempts: int = 2,
    ) -> None:
        if not 0 < connect_timeout <= 30 or not 0 < read_timeout <= 60:
            raise ValueError("Transport timeouts are outside the reviewed bounds")
        if not max(connect_timeout, read_timeout) <= total_timeout <= 90:
            raise ValueError("Total timeout is outside the reviewed bounds")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 2:
            raise ValueError("Transport attempts must be one or two")
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._total_timeout = total_timeout
        self._max_attempts = max_attempts
        context = ssl.create_default_context()
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        self._context = context

    def get(
        self,
        endpoint: TrustedEndpoint,
        relative_path: str,
        *,
        query: Sequence[tuple[str, str]] = (),
        accepted_content_types: frozenset[str] = frozenset(
            {"application/vnd.api+json", "application/json"}
        ),
        expected_statuses: frozenset[int] = frozenset({200}),
        max_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> HttpResponse:
        if type(max_bytes) is not int or not 1 <= max_bytes <= 8 * 1024 * 1024:
            raise ValueError("Response byte limit is outside the reviewed bounds")
        target, request_uri = endpoint.request_target(relative_path, query)
        requested_at = datetime.now(UTC)
        deadline = time.monotonic() + self._total_timeout
        addresses = _resolve(
            endpoint,
            timeout=min(self._connect_timeout, max(0.001, deadline - time.monotonic())),
        )
        last_error: TransportError | None = None
        for attempt in range(self._max_attempts):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            address = addresses[attempt % len(addresses)]
            connection = _PinnedHTTPSConnection(
                endpoint.hostname,
                address,
                timeout=min(self._connect_timeout, remaining),
                context=self._context,
            )
            try:
                connection.request(
                    "GET",
                    target,
                    headers={
                        "Accept": ", ".join(sorted(accepted_content_types)),
                        "Accept-Encoding": "identity",
                        "Connection": "close",
                        "Host": endpoint.hostname,
                        "User-Agent": "materials-mcp-optimade/0.1.0a1",
                    },
                )
                header_remaining = deadline - time.monotonic()
                if header_remaining <= 0:
                    raise TransportError(
                        "request-timeout",
                        "HTTPS request exceeded its total timeout",
                        retryable=True,
                    )
                if connection.sock is not None:
                    connection.sock.settimeout(
                        min(self._read_timeout, max(0.001, header_remaining))
                    )
                response = connection.getresponse()
                content_type = _content_type(response.headers)
                body = _read_bounded(
                    response,
                    max_bytes=max_bytes,
                    deadline=deadline,
                    read_timeout=self._read_timeout,
                    connection=connection,
                )
                if 300 <= response.status < 400:
                    raise TransportError(
                        "redirect-rejected",
                        "Provider redirects are not execution authority",
                        http_status=response.status,
                    )
                if response.status not in expected_statuses:
                    retryable = response.status in _RETRYABLE_STATUSES
                    raise TransportError(
                        "http-status",
                        "Provider returned an unexpected HTTP status",
                        http_status=response.status,
                        retryable=retryable,
                    )
                if content_type in accepted_content_types:
                    headers = MappingProxyType(
                        {key.lower(): value for key, value in response.headers.items()}
                    )
                    return HttpResponse(
                        request_uri=request_uri,
                        status=response.status,
                        headers=headers,
                        body=body,
                        sha256=hashlib.sha256(body).hexdigest(),
                        requested_at=requested_at,
                        retrieved_at=datetime.now(UTC),
                    )
                raise TransportError(
                    "content-type-rejected",
                    "Provider response content type is outside the request contract",
                    http_status=response.status,
                )
            except TransportError as error:
                last_error = error
            except (OSError, ssl.SSLError, http.client.HTTPException) as error:
                last_error = TransportError(
                    "network-failed",
                    "Direct HTTPS request failed",
                    retryable=True,
                )
                last_error.__cause__ = error
            finally:
                connection.close()
            if not last_error.retryable or attempt + 1 >= self._max_attempts:
                break
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(0.25 * (attempt + 1), remaining))
        if last_error is not None:
            raise last_error
        raise TransportError("request-timeout", "HTTPS request exceeded its total timeout")


class _JsonBudget:
    def __init__(self) -> None:
        self.nodes = 0

    def visit(self, value: object, depth: int = 0) -> None:
        if depth > MAX_JSON_DEPTH:
            raise ProviderProtocolError("json-too-deep", "Provider JSON exceeds the depth limit")
        self.nodes += 1
        if self.nodes > MAX_JSON_NODES:
            raise ProviderProtocolError("json-too-complex", "Provider JSON exceeds the node limit")
        if type(value) is dict:
            for key, item in cast(dict[str, object], value).items():
                if len(key.encode("utf-8")) > 1024:
                    raise ProviderProtocolError(
                        "json-key-too-large", "Provider JSON contains an oversized key"
                    )
                self.visit(item, depth + 1)
        elif type(value) is list:
            for item in cast(list[object], value):
                self.visit(item, depth + 1)
        elif type(value) is str and len(value.encode("utf-8")) > 1_048_576:
            raise ProviderProtocolError(
                "json-string-too-large", "Provider JSON contains an oversized string"
            )
        elif type(value) is float and not math.isfinite(value):
            raise ProviderProtocolError("json-number-invalid", "Provider JSON is non-finite")


def _object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ProviderProtocolError(
                "json-duplicate-member", "Provider JSON contains a duplicate member"
            )
        result[key] = value
    return result


def _reject_constant(_: str) -> object:
    raise ProviderProtocolError("json-number-invalid", "Provider JSON is non-finite")


def decode_json_object(response: HttpResponse) -> dict[str, object]:
    try:
        text = response.body.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ProviderProtocolError("json-encoding", "Provider JSON is not UTF-8") from error
    try:
        document = json.loads(
            text,
            object_pairs_hook=_object_pairs,
            parse_constant=_reject_constant,
        )
    except ProviderProtocolError:
        raise
    except (json.JSONDecodeError, ValueError) as error:
        raise ProviderProtocolError(
            "json-invalid", "Provider response is not valid JSON"
        ) from error
    if type(document) is not dict:
        raise ProviderProtocolError("json-root", "Provider JSON root must be an object")
    result = cast(dict[str, object], document)
    _JsonBudget().visit(result)
    return result
