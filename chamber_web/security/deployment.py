"""Fail-closed network deployment policy for one server and one chamber.

No network setting may enable the physical Vötsch backend. Supported modes are
loopback-only ``localhost`` and plain-HTTP ``lab`` on a private network. TLS,
public origins and internet exposure are deliberately out of scope.
"""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import os
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

    @property
    def is_lab(self) -> bool:
        return self.mode == "lab"

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
        if mode not in {"localhost", "lab"}:
            raise DeploymentError("CHAMBER_NETWORK_MODE must be localhost or lab")
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
                raise DeploymentError("Non-loopback binding requires explicit lab mode")
            if any(config.get(name) for name in (
                    "CHAMBER_ALLOWED_CLIENT_CIDRS", "CHAMBER_PUBLIC_ORIGIN")):
                raise DeploymentError("Lab-only configuration in localhost mode")
            origins = frozenset({
                f"http://127.0.0.1:{port}", f"http://localhost:{port}"
            })
            override = config.get("CHAMBER_ALLOWED_ORIGINS")
            if override:
                requested = frozenset(v.strip() for v in override.split(","))
                if not requested or not requested.issubset(origins):
                    raise DeploymentError("Localhost origins cannot admit lab clients")
                origins = requested
            networks = (ipaddress.ip_network("127.0.0.0/8"),
                        ipaddress.ip_network("::1/128"))
            return cls(mode, host, port, origins, networks)
        return cls._lab(config, host, bind, port)

    @classmethod
    def _lab(cls, config, host: str, bind, port: int) -> "DeploymentPolicy":
        """Plain HTTP for a closed lab network (server, laptop, chamber only).

        Host/Origin binding, the client allowlist (default: private and
        loopback networks) and G08 sign-in still apply. There is no TLS mode.
        Origins are ``CHAMBER_PUBLIC_ORIGIN`` (comma-separated) or, for a
        specific bind address, ``http://<bind>:<port>``; loopback origins are
        always added.
        """
        if bind.is_multicast or (not bind.is_private and not bind.is_unspecified):
            raise DeploymentError("Lab mode binds only private, loopback or 0.0.0.0")
        if config.get("CHAMBER_TLS_CERT") or config.get("CHAMBER_TLS_KEY"):
            raise DeploymentError("TLS is not supported; lab mode is plain HTTP")
        origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
        raw = [v.strip().rstrip("/") for v in
               config.get("CHAMBER_PUBLIC_ORIGIN", "").split(",") if v.strip()]
        for origin in raw:
            try:
                parts = urlsplit(origin)
                valid = (parts.scheme == "http" and bool(parts.hostname) and
                         not parts.username and not parts.password and not parts.path and
                         not parts.query and not parts.fragment and parts.port == port)
            except ValueError as exc:
                raise DeploymentError("Invalid lab origin") from exc
            if not valid:
                raise DeploymentError(
                    f"Lab origins must look like http://<server-ip>:{port}")
            origins.add(origin)
        if not raw:
            if bind.is_unspecified:
                raise DeploymentError(
                    "Lab mode on 0.0.0.0 needs CHAMBER_PUBLIC_ORIGIN="
                    f"http://<server-ip>:{port} (the address the laptop opens)")
            if not bind.is_loopback:
                origins.add(f"http://{host}:{port}")
        cidrs = config.get("CHAMBER_ALLOWED_CLIENT_CIDRS", "")
        try:
            networks = tuple(ipaddress.ip_network(s.strip(), strict=True)
                             for s in cidrs.split(",") if s.strip()) or tuple(
                ipaddress.ip_network(net) for net in (
                    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
                    "169.254.0.0/16", "127.0.0.0/8", "::1/128", "fc00::/7"))
        except ValueError as exc:
            raise DeploymentError("Invalid client CIDR allowlist") from exc
        if any(net.prefixlen == 0 or not (net.is_private or net.is_loopback)
               for net in networks):
            raise DeploymentError("Lab client networks must be private")
        return cls("lab", host, port, frozenset(origins), networks)
