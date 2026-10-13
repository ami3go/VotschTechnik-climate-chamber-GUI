"""Fail-closed network deployment policy for one server and one chamber.

No network setting may enable the physical Vötsch backend. Source CLI may use
LAN mode only after explicit IP/CIDR, HTTPS certificate and client ACL setup.
The W01 frozen simulator deliberately stays loopback-only.
"""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import os
from pathlib import Path
import ssl
import time
from urllib.parse import urlsplit


class DeploymentError(RuntimeError):
    """Unsafe or ambiguous network configuration: startup must fail."""


@dataclass(frozen=True)
class DeploymentPolicy:
    mode: str
    bind_host: str
    port: int
    allowed_origins: frozenset[str]
    client_networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]
    certfile: Path | None = None
    keyfile: Path | None = None

    @property
    def is_lan(self) -> bool:
        return self.mode == "lan"

    def allows_client(self, address: str | None) -> bool:
        if not address:
            return False
        try:
            peer = ipaddress.ip_address(address)
            return any(peer in network for network in self.client_networks)
        except ValueError:
            return False

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "DeploymentPolicy":
        config = os.environ if env is None else env
        mode = config.get("CHAMBER_NETWORK_MODE", "localhost").strip().lower()
        if mode not in {"localhost", "lan"}:
            raise DeploymentError("CHAMBER_NETWORK_MODE must be localhost or lan")
        try:
            port = int(config.get("CHAMBER_PORT", "8080"))
        except ValueError as exc:
            raise DeploymentError("Invalid CHAMBER_PORT") from exc
        if not 1024 <= port <= 65535:
            raise DeploymentError("CHAMBER_PORT outside 1024..65535")
        host = config.get("CHAMBER_BIND_HOST", "127.0.0.1")
        try:
            bind = ipaddress.ip_address(host)
        except ValueError as exc:
            raise DeploymentError("CHAMBER_BIND_HOST must be a literal IP") from exc
        if mode == "localhost":
            if not bind.is_loopback:
                raise DeploymentError("Non-loopback binding requires explicit LAN mode")
            if any(config.get(name) for name in (
                    "CHAMBER_TLS_CERT", "CHAMBER_TLS_KEY",
                    "CHAMBER_ALLOWED_CLIENT_CIDRS", "CHAMBER_PUBLIC_ORIGIN")):
                raise DeploymentError("LAN-only configuration in localhost mode")
            # Treat configured origins only as a loopback convenience, not a
            # way to expand the listen interface or allow foreign Hosts.
            origins = frozenset({
                f"http://127.0.0.1:{port}", f"http://localhost:{port}"
            })
            override = config.get("CHAMBER_ALLOWED_ORIGINS")
            if override:
                requested = frozenset(v.strip() for v in override.split(","))
                if not requested or not requested.issubset(origins):
                    raise DeploymentError("Localhost origins cannot admit LAN clients")
                origins = requested
            networks = (ipaddress.ip_network("127.0.0.0/8"),
                        ipaddress.ip_network("::1/128"))
            return cls(mode, host, port, origins, networks)

        if bind.is_loopback or bind.is_multicast or bind.is_unspecified and not (
                config.get("CHAMBER_ALLOWED_CLIENT_CIDRS")):
            raise DeploymentError("LAN bind requires a non-loopback IP or explicit client ACL")
        if not bind.is_private and not bind.is_unspecified:
            raise DeploymentError("Public internet address binding is prohibited")
        raw_origin = config.get("CHAMBER_PUBLIC_ORIGIN", "")
        parts = urlsplit(raw_origin)
        if (parts.scheme != "https" or not parts.hostname or parts.username
                or parts.password or parts.path or parts.query or parts.fragment
                or parts.port != port):
            raise DeploymentError("Explicit https CHAMBER_PUBLIC_ORIGIN with port required")
        cidrs = config.get("CHAMBER_ALLOWED_CLIENT_CIDRS", "")
        if not cidrs:
            raise DeploymentError("LAN requires an explicit client network allowlist")
        try:
            networks = tuple(ipaddress.ip_network(s.strip(), strict=True)
                             for s in cidrs.split(","))
        except ValueError as exc:
            raise DeploymentError("Invalid client CIDR allowlist") from exc
        if not networks or any(net.prefixlen == 0 for net in networks):
            raise DeploymentError("Allow-all client CIDR is prohibited")
        cert = config.get("CHAMBER_TLS_CERT")
        key = config.get("CHAMBER_TLS_KEY")
        if not cert or not key:
            raise DeploymentError("LAN requires both TLS certificate and key")
        certfile, keyfile = Path(cert).resolve(), Path(key).resolve()
        if not certfile.is_file() or not keyfile.is_file():
            raise DeploymentError("Missing TLS certificate or key")
        if os.name != "nt" and keyfile.stat().st_mode & 0o077:
            raise DeploymentError("TLS private key must be owner-readable only")
        try:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(str(certfile), str(keyfile))
            # Validate validity interval and hostname; load_cert_chain alone
            # only checks that a key matches a syntactically valid certificate.
            certificate = ssl._ssl._test_decode_cert(str(certfile))
            if not (ssl.cert_time_to_seconds(certificate["notBefore"]) <= time.time()
                    < ssl.cert_time_to_seconds(certificate["notAfter"])):
                raise DeploymentError("TLS certificate is not currently valid")
            ssl.match_hostname(certificate, parts.hostname)
        except (OSError, ssl.SSLError, ValueError, KeyError, AttributeError) as exc:
            raise DeploymentError("Invalid or untrusted LAN TLS configuration") from exc
        except ssl.CertificateError as exc:
            raise DeploymentError("TLS certificate does not match public origin") from exc
        return cls(mode, host, port, frozenset({raw_origin}), networks,
                   certfile, keyfile)
