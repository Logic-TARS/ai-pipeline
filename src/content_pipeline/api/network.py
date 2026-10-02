from __future__ import annotations

import ipaddress
import secrets
import socket
from pathlib import Path
from urllib.parse import urlsplit

from content_pipeline.settings import Settings

__all__ = [
    "ensure_bind_address_is_local",
    "is_loopback_host",
    "origin_matches",
    "parse_ip_address",
    "parse_networks",
    "peer_is_allowed",
    "secrets_compare",
    "validate_bind_configuration",
]

WILDCARD_HOSTS = {"0.0.0.0", "::", "[::]", "*"}
LOOPBACK_NAMES = {"localhost", "ip6-localhost"}


def parse_ip_address(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """Parse a direct socket address, normalizing IPv4-mapped IPv6 peers."""
    address = ipaddress.ip_address(value.split("%", 1)[0])
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def parse_networks(values: tuple[str, ...]) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    networks = []
    for value in values:
        networks.append(ipaddress.ip_network(value, strict=False))
    return tuple(networks)


def origin_matches(origin: str, *, scheme: str, host: str) -> bool:
    try:
        parsed = urlsplit(origin)
        return parsed.scheme == scheme and (parsed.hostname or "").lower().strip("[]") == host
    except ValueError:
        return False


def is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower().strip("[]")
    if normalized in LOOPBACK_NAMES:
        return True
    try:
        return parse_ip_address(normalized).is_loopback
    except ValueError:
        return False


def peer_is_allowed(peer: str, allowed_networks: tuple[str, ...]) -> bool:
    """Allow loopback or a direct peer in an explicitly configured network."""
    try:
        address = parse_ip_address(peer)
        networks = parse_networks(allowed_networks)
    except ValueError:
        return False
    if address.is_loopback:
        return True
    return any(address.version == network.version and address in network for network in networks)


def validate_bind_configuration(
    settings: Settings,
    *,
    host: str,
    ssl_certfile: Path | None,
    ssl_keyfile: Path | None,
    allow_container_wildcard: bool = False,
) -> list[str]:
    """Return fail-closed errors for a requested HTTP listener."""
    errors: list[str] = []
    normalized = host.strip().lower()
    if normalized in WILDCARD_HOSTS:
        if not allow_container_wildcard:
            return ["wildcard listeners are not supported; bind loopback or the exact ZeroTier interface IP"]
        if not settings.web_auth_required:
            errors.append("container wildcard listener requires WEB_AUTH_REQUIRED=true")

    admin_token = settings.web_admin_token.get_secret_value()
    api_token = settings.web_api_token.get_secret_value()
    session_secret = settings.web_session_secret.get_secret_value()
    if bool(ssl_certfile) != bool(ssl_keyfile):
        errors.append("both TLS certificate and key must be configured together")
    if settings.env.strip().lower() == "production" and not settings.web_auth_required:
        errors.append("production environment requires WEB_AUTH_REQUIRED=true")
    if settings.web_auth_required:
        if len(admin_token) < 32:
            errors.append("WEB_ADMIN_TOKEN must contain at least 32 characters")
        if len(api_token) < 32:
            errors.append("WEB_API_TOKEN must contain at least 32 characters")
        if len(session_secret) < 32:
            errors.append("WEB_SESSION_SECRET must contain at least 32 characters")
        if admin_token and secrets_compare(admin_token, api_token):
            errors.append("WEB_ADMIN_TOKEN and WEB_API_TOKEN must be different")
        if admin_token and secrets_compare(admin_token, session_secret):
            errors.append("WEB_ADMIN_TOKEN and WEB_SESSION_SECRET must be different")
        if api_token and secrets_compare(api_token, session_secret):
            errors.append("WEB_API_TOKEN and WEB_SESSION_SECRET must be different")

    if normalized in WILDCARD_HOSTS and allow_container_wildcard:
        return errors
    if is_loopback_host(host):
        return errors

    try:
        address = parse_ip_address(host)
        networks = parse_networks(settings.allowed_networks)
    except ValueError as exc:
        return [f"invalid remote bind or allowed network: {exc}"]

    if not any(address.version == network.version and address in network for network in networks):
        errors.append("remote bind IP must belong to WEB_ALLOWED_NETWORKS")
    if not settings.web_auth_required:
        errors.append("remote access requires WEB_AUTH_REQUIRED=true")
    normalized_host = host.lower().strip("[]")
    if normalized_host not in {item.lower().strip("[]") for item in settings.allowed_hosts}:
        errors.append("remote bind IP must be present in WEB_ALLOWED_HOSTS")
    expected_scheme = "https" if ssl_certfile and ssl_keyfile else "http"
    if not any(
        origin_matches(origin, scheme=expected_scheme, host=normalized_host) for origin in settings.allowed_origins
    ):
        errors.append(f"WEB_ALLOWED_ORIGINS must include the {expected_scheme} origin for the remote bind IP")
    if not ssl_certfile and not ssl_keyfile and not settings.web_allow_zerotier_http:
        errors.append("remote access requires TLS or explicit WEB_ALLOW_ZEROTIER_HTTP=true")
    return errors


def secrets_compare(left: str, right: str) -> bool:
    """Compare configuration secrets without exposing their values."""
    return secrets.compare_digest(left, right)


def ensure_bind_address_is_local(host: str) -> None:
    """Fail before Uvicorn starts when an exact bind address is not local."""
    if is_loopback_host(host):
        return
    try:
        address = parse_ip_address(host)
    except ValueError as exc:
        raise ValueError("WEB_BIND_HOST must be an IP address or localhost") from exc

    family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((str(address), 0))
        except OSError as exc:
            raise ValueError(f"bind address is not assigned to a local interface: {host}") from exc
