from __future__ import annotations

import importlib.util
import socket
import sys
import threading
import unittest
from pathlib import Path
from typing import Any


def _load_bridge_module() -> Any:
    path = Path(__file__).parents[1] / "scripts" / "pixiv_proxy_bridge.py"
    spec = importlib.util.spec_from_file_location("pixiv_proxy_bridge", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bridge = _load_bridge_module()


class PixivProxyBridgeTests(unittest.TestCase):
    def test_allow_list_accepts_only_pixiv_domains(self) -> None:
        hosts = [
            "pixiv.net",
            "www.pixiv.net",
            "accounts.pixiv.net",
            "i.pximg.net",
            "d.pixiv.org",
            "www.recaptcha.net",
            "www.gstatic.com",
        ]
        for host in hosts:
            with self.subTest(host=host):
                self.assertTrue(bridge.is_allowed_host(host))

    def test_allow_list_rejects_suffix_confusion(self) -> None:
        hosts = [
            "evilpixiv.net",
            "pixiv.net.example.com",
            "pximg.net.evil.test",
            "example.org",
            "google.com",
            "recaptcha.net.evil.test",
        ]
        for host in hosts:
            with self.subTest(host=host):
                self.assertFalse(bridge.is_allowed_host(host))

    def test_connect_target_requires_https_and_allow_list(self) -> None:
        self.assertEqual(
            bridge.parse_connect_target("www.pixiv.net:443"), ("www.pixiv.net", 443)
        )
        with self.assertRaises(ValueError):
            bridge.parse_connect_target("www.pixiv.net:80")
        with self.assertRaises(PermissionError):
            bridge.parse_connect_target("example.com:443")

    def test_socks5_connect_uses_ipv4_address_not_hostname(self) -> None:
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        observed: dict[str, bytes] = {}

        def fake_proxy() -> None:
            connection, _ = listener.accept()
            with connection:
                observed["greeting"] = connection.recv(3)
                connection.sendall(b"\x05\x00")
                observed["request"] = connection.recv(10)
                connection.sendall(b"\x05\x00\x00\x01\x7f\x00\x00\x01\x12\x34")

        worker = threading.Thread(target=fake_proxy)
        worker.start()
        connection = bridge.open_socks5_ipv4(
            "127.0.0.1", listener.getsockname()[1], "104.18.42.239", 443
        )
        connection.close()
        worker.join(timeout=2)
        listener.close()

        self.assertEqual(observed["greeting"], b"\x05\x01\x00")
        self.assertEqual(observed["request"][3], 1)
        self.assertEqual(observed["request"][4:8], socket.inet_aton("104.18.42.239"))

    def test_dns_cache_avoids_repeated_queries(self) -> None:
        resolver = bridge.DnsOverHttpsResolver()
        calls: list[str] = []

        def fake_query(host: str) -> tuple[tuple[str, ...], int]:
            calls.append(host)
            return (("104.18.42.239",), 300)

        resolver._query = fake_query
        self.assertEqual(resolver.resolve_ipv4("www.pixiv.net"), ("104.18.42.239",))
        self.assertEqual(resolver.resolve_ipv4("www.pixiv.net"), ("104.18.42.239",))
        self.assertEqual(calls, ["www.pixiv.net"])


if __name__ == "__main__":
    unittest.main()
