from pathlib import Path

import pytest

from content_pipeline.api.network import (
    ensure_bind_address_is_local,
    is_loopback_host,
    peer_is_allowed,
    validate_bind_configuration,
)
from content_pipeline.settings import Settings

ADMIN_TOKEN = "a" * 32
API_TOKEN = "b" * 32
SESSION_SECRET = "c" * 32


def _remote_settings(**overrides) -> Settings:
    values = {
        "web_bind_host": "10.147.17.5",
        "web_allowed_networks": "10.147.17.0/24",
        "web_allowed_hosts": "10.147.17.5",
        "web_allowed_origins": "https://10.147.17.5:8080",
        "web_auth_required": True,
        "web_admin_token": ADMIN_TOKEN,
        "web_api_token": API_TOKEN,
        "web_session_secret": SESSION_SECRET,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_peer_boundary_allows_loopback_and_configured_zerotier_network() -> None:
    assert peer_is_allowed("127.0.0.1", ())
    assert peer_is_allowed("::1", ())
    assert peer_is_allowed("10.147.17.42", ("10.147.17.0/24",))
    assert not peer_is_allowed("192.168.1.42", ("10.147.17.0/24",))
    assert not peer_is_allowed("not-an-address", ("10.147.17.0/24",))


def test_bind_policy_rejects_wildcards() -> None:
    settings = Settings(_env_file=None)

    errors = validate_bind_configuration(settings, host="0.0.0.0", ssl_certfile=None, ssl_keyfile=None)

    assert errors == ["wildcard listeners are not supported; bind loopback or the exact ZeroTier interface IP"]


def test_container_wildcard_requires_application_authentication() -> None:
    settings = Settings(_env_file=None)

    errors = validate_bind_configuration(
        settings,
        host="0.0.0.0",
        ssl_certfile=None,
        ssl_keyfile=None,
        allow_container_wildcard=True,
    )

    assert errors == ["container wildcard listener requires WEB_AUTH_REQUIRED=true"]


def test_container_wildcard_allows_authenticated_internal_listener() -> None:
    settings = _remote_settings(
        web_bind_host="0.0.0.0",
        web_allowed_hosts="127.0.0.1,localhost,testserver",
        web_allowed_origins="http://127.0.0.1:8080,http://localhost:8080,http://testserver",
        web_allow_zerotier_http=True,
    )

    errors = validate_bind_configuration(
        settings,
        host="0.0.0.0",
        ssl_certfile=None,
        ssl_keyfile=None,
        allow_container_wildcard=True,
    )

    assert errors == []


def test_production_environment_requires_auth_even_on_loopback() -> None:
    settings = Settings(_env_file=None, env="production")

    errors = validate_bind_configuration(
        settings,
        host="127.0.0.1",
        ssl_certfile=None,
        ssl_keyfile=None,
    )

    assert errors == ["production environment requires WEB_AUTH_REQUIRED=true"]


def test_remote_bind_requires_network_auth_and_transport() -> None:
    settings = Settings(_env_file=None, web_bind_host="10.147.17.5")

    errors = validate_bind_configuration(
        settings,
        host=settings.web_bind_host,
        ssl_certfile=None,
        ssl_keyfile=None,
    )

    assert "remote bind IP must belong to WEB_ALLOWED_NETWORKS" in errors
    assert "remote access requires WEB_AUTH_REQUIRED=true" in errors
    assert "remote access requires TLS or explicit WEB_ALLOW_ZEROTIER_HTTP=true" in errors


def test_valid_zerotier_tls_bind_passes_policy(tmp_path: Path) -> None:
    cert = tmp_path / "server.crt"
    key = tmp_path / "server.key"
    cert.write_text("test", encoding="utf-8")
    key.write_text("test", encoding="utf-8")
    settings = _remote_settings(web_tls_certfile=cert, web_tls_keyfile=key)

    errors = validate_bind_configuration(settings, host=settings.web_bind_host, ssl_certfile=cert, ssl_keyfile=key)

    assert errors == []


def test_restricted_http_mode_requires_matching_origin() -> None:
    settings = _remote_settings(
        web_allow_zerotier_http=True,
        web_allowed_origins="https://10.147.17.5:8080",
    )

    errors = validate_bind_configuration(
        settings,
        host=settings.web_bind_host,
        ssl_certfile=None,
        ssl_keyfile=None,
    )

    assert "WEB_ALLOWED_ORIGINS must include the http origin for the remote bind IP" in errors


def test_auth_secrets_must_be_long_and_distinct() -> None:
    settings = _remote_settings(web_admin_token="short", web_api_token="short", web_session_secret="short")

    errors = validate_bind_configuration(
        settings,
        host=settings.web_bind_host,
        ssl_certfile=Path("cert.pem"),
        ssl_keyfile=Path("key.pem"),
    )

    assert "WEB_ADMIN_TOKEN must contain at least 32 characters" in errors
    assert "WEB_API_TOKEN must contain at least 32 characters" in errors
    assert "WEB_SESSION_SECRET must contain at least 32 characters" in errors
    assert "WEB_ADMIN_TOKEN and WEB_API_TOKEN must be different" in errors
    assert "WEB_ADMIN_TOKEN and WEB_SESSION_SECRET must be different" in errors
    assert "WEB_API_TOKEN and WEB_SESSION_SECRET must be different" in errors


def test_local_bind_probe_rejects_nonlocal_test_address() -> None:
    assert is_loopback_host("localhost")
    ensure_bind_address_is_local("127.0.0.1")
    with pytest.raises(ValueError, match="not assigned to a local interface"):
        ensure_bind_address_is_local("192.0.2.123")
