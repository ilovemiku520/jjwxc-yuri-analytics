"""Restricted HTTP CONNECT bridge for Pixiv over Cloudflare WARP proxy mode.

The bridge exists because the local network returns incorrect DNS answers for Pixiv.
It resolves an allow-listed hostname with Cloudflare DNS-over-HTTPS, connects to the
resolved IPv4 address through WARP's local SOCKS5 listener, and then relays TLS bytes
without decrypting them.
"""

from __future__ import annotations

import argparse
import http.client
import ipaddress
import json
import logging
import select
import socket
import socketserver
import ssl
import struct
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

PIXIV_SUFFIXES = ("pixiv.net", "pximg.net", "pixiv.org")
VERIFICATION_HOSTS = frozenset({"www.recaptcha.net", "www.gstatic.com"})
DEFAULT_LISTEN_HOST = "127.0.0.1"
DEFAULT_LISTEN_PORT = 41080
DEFAULT_WARP_HOST = "127.0.0.1"
DEFAULT_WARP_PORT = 40000
DOH_IP = "1.1.1.1"
DOH_SERVER_NAME = "cloudflare-dns.com"
MAX_HEADER_BYTES = 16_384


def is_allowed_host(host: str) -> bool:
    normalized = host.lower().rstrip(".")
    return normalized in VERIFICATION_HOSTS or any(
        normalized == suffix or normalized.endswith(f".{suffix}") for suffix in PIXIV_SUFFIXES
    )


def parse_connect_target(target: str) -> tuple[str, int]:
    host, separator, port_text = target.rpartition(":")
    if not separator or not host or not port_text.isdigit():
        raise ValueError("CONNECT target must use host:port form")
    host = host.lower().rstrip(".")
    port = int(port_text)
    if port != 443:
        raise ValueError("only TLS port 443 is allowed")
    if not is_allowed_host(host):
        raise PermissionError("hostname is outside the Pixiv allow-list")
    return host, port


def _recv_exact(connection: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = connection.recv(remaining)
        if not chunk:
            raise ConnectionError("SOCKS5 peer closed the connection")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def open_socks5_ipv4(
    proxy_host: str,
    proxy_port: int,
    target_ip: str,
    target_port: int,
    *,
    timeout: float = 15.0,
) -> socket.socket:
    packed_ip = ipaddress.IPv4Address(target_ip).packed
    connection = socket.create_connection((proxy_host, proxy_port), timeout=timeout)
    try:
        connection.settimeout(timeout)
        connection.sendall(b"\x05\x01\x00")
        if _recv_exact(connection, 2) != b"\x05\x00":
            raise ConnectionError("SOCKS5 proxy rejected unauthenticated access")

        request = b"\x05\x01\x00\x01" + packed_ip + struct.pack("!H", target_port)
        connection.sendall(request)
        response = _recv_exact(connection, 4)
        if response[0] != 5 or response[1] != 0:
            raise ConnectionError(f"SOCKS5 connect failed with code {response[1]}")

        address_type = response[3]
        if address_type == 1:
            _recv_exact(connection, 4)
        elif address_type == 3:
            _recv_exact(connection, _recv_exact(connection, 1)[0])
        elif address_type == 4:
            _recv_exact(connection, 16)
        else:
            raise ConnectionError("SOCKS5 proxy returned an invalid address type")
        _recv_exact(connection, 2)
        return connection
    except Exception:
        connection.close()
        raise


@dataclass(frozen=True)
class CacheEntry:
    addresses: tuple[str, ...]
    expires_at: float


class DnsOverHttpsResolver:
    def __init__(
        self,
        proxy_host: str = DEFAULT_WARP_HOST,
        proxy_port: int = DEFAULT_WARP_PORT,
        *,
        timeout: float = 15.0,
    ) -> None:
        self.proxy_host = proxy_host
        self.proxy_port = proxy_port
        self.timeout = timeout
        self._cache: dict[str, CacheEntry] = {}
        self._lock = threading.Lock()

    def resolve_ipv4(self, host: str) -> tuple[str, ...]:
        normalized = host.lower().rstrip(".")
        if not is_allowed_host(normalized):
            raise PermissionError("hostname is outside the Pixiv allow-list")

        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(normalized)
            if cached and cached.expires_at > now:
                return cached.addresses

        addresses, ttl = self._query(normalized)
        bounded_ttl = max(30, min(ttl, 1800))
        entry = CacheEntry(addresses=addresses, expires_at=now + bounded_ttl)
        with self._lock:
            self._cache[normalized] = entry
        return addresses

    def _query(self, host: str) -> tuple[tuple[str, ...], int]:
        raw_socket = open_socks5_ipv4(
            self.proxy_host,
            self.proxy_port,
            DOH_IP,
            443,
            timeout=self.timeout,
        )
        tls_socket: ssl.SSLSocket | None = None
        try:
            context = ssl.create_default_context()
            tls_socket = context.wrap_socket(raw_socket, server_hostname=DOH_SERVER_NAME)
            path = "/dns-query?" + urlencode({"name": host, "type": "A"})
            request = (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {DOH_SERVER_NAME}\r\n"
                "Accept: application/dns-json\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii")
            tls_socket.sendall(request)
            response = http.client.HTTPResponse(tls_socket)
            response.begin()
            body = response.read()
            if response.status != 200:
                raise ConnectionError(f"DoH returned HTTP {response.status}")
            payload = json.loads(body.decode("utf-8"))
        finally:
            if tls_socket is not None:
                tls_socket.close()
            else:
                raw_socket.close()

        if payload.get("Status") != 0:
            raise LookupError(f"DoH returned DNS status {payload.get('Status')}")

        addresses: list[str] = []
        ttls: list[int] = []
        for answer in payload.get("Answer", []):
            if answer.get("type") != 1:
                continue
            try:
                address = ipaddress.IPv4Address(answer.get("data", ""))
            except ipaddress.AddressValueError:
                continue
            if not address.is_global:
                continue
            addresses.append(str(address))
            ttls.append(int(answer.get("TTL", 60)))
        if not addresses:
            raise LookupError(f"DoH returned no public IPv4 address for {host}")
        return tuple(dict.fromkeys(addresses)), min(ttls or [60])


def _read_http_header(connection: socket.socket) -> bytes:
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = connection.recv(4096)
        if not chunk:
            raise ConnectionError("client closed before sending a complete header")
        data.extend(chunk)
        if len(data) > MAX_HEADER_BYTES:
            raise ValueError("proxy request header is too large")
    return bytes(data)


def _relay(left: socket.socket, right: socket.socket, idle_timeout: float = 180.0) -> None:
    sockets = [left, right]
    for connection in sockets:
        connection.settimeout(None)
    while True:
        readable, _, _ = select.select(sockets, [], [], idle_timeout)
        if not readable:
            return
        for source in readable:
            destination = right if source is left else left
            chunk = source.recv(65_536)
            if not chunk:
                return
            destination.sendall(chunk)


class PixivConnectHandler(socketserver.BaseRequestHandler):
    server: "PixivProxyServer"

    def handle(self) -> None:
        upstream: socket.socket | None = None
        established = False
        host = "unknown"
        try:
            self.request.settimeout(self.server.connection_timeout)
            header = _read_http_header(self.request)
            request_line = header.split(b"\r\n", 1)[0].decode("ascii", errors="strict")
            method, target, _version = request_line.split(" ", 2)
            if method.upper() != "CONNECT":
                self.request.sendall(b"HTTP/1.1 405 Method Not Allowed\r\nConnection: close\r\n\r\n")
                return
            host, port = parse_connect_target(target)
            addresses = self.server.resolver.resolve_ipv4(host)
            last_error: Exception | None = None
            for address in addresses:
                try:
                    upstream = open_socks5_ipv4(
                        self.server.warp_host,
                        self.server.warp_port,
                        address,
                        port,
                        timeout=self.server.connection_timeout,
                    )
                    break
                except Exception as error:
                    last_error = error
            if upstream is None:
                raise ConnectionError(f"all resolved addresses failed: {last_error}")

            self.request.sendall(
                b"HTTP/1.1 200 Connection Established\r\n"
                b"Proxy-Agent: PixivYuriBridge/1\r\n\r\n"
            )
            established = True
            logging.info("connected host=%s", host)
            _relay(self.request, upstream, self.server.idle_timeout)
        except PermissionError as error:
            logging.warning("blocked host=%s reason=%s", host, error)
            self._send_error(403, "Forbidden", established)
        except (ValueError, UnicodeError) as error:
            logging.warning("bad-request host=%s reason=%s", host, error)
            self._send_error(400, "Bad Request", established)
        except Exception as error:
            logging.error("upstream-failure host=%s reason=%s", host, error)
            self._send_error(502, "Bad Gateway", established)
        finally:
            if upstream is not None:
                upstream.close()

    def _send_error(self, code: int, reason: str, established: bool) -> None:
        if established:
            return
        try:
            response = f"HTTP/1.1 {code} {reason}\r\nConnection: close\r\n\r\n"
            self.request.sendall(response.encode("ascii"))
        except OSError:
            pass


class PixivProxyServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        resolver: DnsOverHttpsResolver,
        *,
        warp_host: str = DEFAULT_WARP_HOST,
        warp_port: int = DEFAULT_WARP_PORT,
        connection_timeout: float = 15.0,
        idle_timeout: float = 180.0,
    ) -> None:
        self.resolver = resolver
        self.warp_host = warp_host
        self.warp_port = warp_port
        self.connection_timeout = connection_timeout
        self.idle_timeout = idle_timeout
        super().__init__(server_address, PixivConnectHandler)


def _configure_logging(log_file: Path | None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen-host", default=DEFAULT_LISTEN_HOST)
    parser.add_argument("--listen-port", type=int, default=DEFAULT_LISTEN_PORT)
    parser.add_argument("--warp-host", default=DEFAULT_WARP_HOST)
    parser.add_argument("--warp-port", type=int, default=DEFAULT_WARP_PORT)
    parser.add_argument("--log-file", type=Path)
    args = parser.parse_args()

    if args.listen_host not in {"127.0.0.1", "::1", "localhost"}:
        parser.error("the bridge may only listen on loopback")

    _configure_logging(args.log_file)
    resolver = DnsOverHttpsResolver(args.warp_host, args.warp_port)
    with PixivProxyServer(
        (args.listen_host, args.listen_port),
        resolver,
        warp_host=args.warp_host,
        warp_port=args.warp_port,
    ) as server:
        logging.info("ready listen=%s:%s", args.listen_host, args.listen_port)
        try:
            server.serve_forever(poll_interval=0.5)
        except KeyboardInterrupt:
            logging.info("stopping")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
