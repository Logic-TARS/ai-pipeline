# Web Access Boundary

## Decision

AI Pipeline's Web UI and REST API are a single-operator administration surface. Supported access is limited to:

1. the host itself through loopback (`127.0.0.1` or `::1`); and
2. authenticated devices connected to an explicitly configured ZeroTier network.

Ordinary physical-LAN clients, public-internet clients, and devices that merely share a router with the host are outside the supported boundary. ZeroTier network membership provides transport isolation, not application identity; remote clients must still authenticate before any non-public endpoint is available.

## Components inside and outside the boundary

| Component | Allowed exposure |
| --- | --- |
| Web UI and REST API | Loopback; optionally one explicitly configured ZeroTier network after the remote-access security gate passes |
| Minimal liveness endpoint | Same listeners as the Web UI; response must not include paths, versions, accounts, or tool state |
| MCP server | Local stdio only |
| Photo-Process browser worker | Loopback only |
| Desktop browser helper | Loopback only |
| MPT, SAU, Gemini adapters | Local subprocesses or their existing loopback interfaces only |
| Job store and arbitrary filesystem paths | Never exposed directly; only registered task artifacts may later be served through guarded endpoints |

Enabling ZeroTier access for the Web UI must not make downstream workers, browser-debug helpers, or tool ports remotely reachable.

## Source-address rules

Access decisions use the direct socket peer address. Forwarding headers such as `X-Forwarded-For`, `Forwarded`, and `X-Real-IP` are untrusted; the guarded CLI disables proxy-header processing.

The intended remote deployment binds to the host's ZeroTier interface address. Binding a host process to `0.0.0.0` or `::` is not acceptable. The container image uses an internal wildcard listener only inside its isolated network namespace through `ai-pipeline serve --allow-container-wildcard`; Docker Compose publishes that port on host loopback, requires application authentication, and does not provide the supported ZeroTier listener path.

## Security gate for remote access

A ZeroTier listener is rejected until all of the following controls are implemented and enabled:

- application authentication for the Web UI and REST API;
- secure session handling, CSRF protection, and trusted Host/Origin validation;
- re-confirmation for publishing and other high-risk operations;
- guarded artifact access and diagnostic redaction;
- transport policy and explicit network configuration;
- automated network-security tests; and
- an operator runbook with an emergency disable procedure.

Until that gate passes, start the service on `127.0.0.1` only.

## Production acceptance checklist

Before treating the Web surface as production-ready, keep the following evidence with the deployment record:

- [ ] `ai-pipeline serve` starts with the intended `WEB_BIND_HOST` and rejects wildcard host binds outside the container-only `--allow-container-wildcard` path.
- [ ] `WEB_AUTH_REQUIRED=true` is set for every non-loopback listener, with independent `WEB_ADMIN_TOKEN`, `WEB_API_TOKEN`, and `WEB_SESSION_SECRET` values.
- [ ] `WEB_ALLOWED_NETWORKS`, `WEB_ALLOWED_HOSTS`, and `WEB_ALLOWED_ORIGINS` contain only the explicit ZeroTier address, CIDR, and HTTPS origin used by this deployment.
- [ ] TLS is configured with `WEB_TLS_CERTFILE` and `WEB_TLS_KEYFILE`; if `WEB_ALLOW_ZEROTIER_HTTP=true` is used, the exception is documented as temporary restricted mode.
- [ ] Windows Firewall allows the chosen TCP port only on the ZeroTier local address and only from the managed peer CIDR.
- [ ] `/health` returns only minimal liveness, `/monitor/uptime-kuma` returns only the Uptime Kuma liveness payload, while `/ready`, `/jobs`, `/run`, artifact endpoints, and content APIs require a valid session or bearer token.
- [ ] Browser write requests enforce CSRF and Host/Origin checks; REST automation uses `Authorization: Bearer <WEB_API_TOKEN>` instead of browser cookies.
- [ ] Web/API publishing stays disabled with `WEB_PUBLISH_ENABLED=false` until artifact review is complete and an operator intentionally enables the publish confirmation flow.
- [ ] MCP, Photo-Process, desktop browser helper, MPT, SAU, Gemini, and arbitrary workstation paths remain loopback-only or local subprocesses.
- [ ] Emergency disable has been rehearsed: stop the service, disable the firewall rule, restore `WEB_BIND_HOST=127.0.0.1`, clear `WEB_ALLOWED_NETWORKS`, set `WEB_PUBLISH_ENABLED=false`, rotate secrets, and deauthorize affected ZeroTier clients.

## Runtime failure and recovery

If the Web surface behaves unexpectedly in production:

1. Prefer fail-closed recovery: stop `ai-pipeline serve` before changing listener, firewall, TLS, or token settings.
2. Use `ai-pipeline doctor`, `/health`, authenticated `/ready` redacted flags (`data_dir_available`, `profiles_available`, `pipeline_defaults_available`), `ai-pipeline jobs show <task_id>`, and `ai-pipeline jobs events <task_id>` for diagnosis; do not expose raw lower-tool ports to debug remotely.
3. For authentication, CSRF, Host/Origin, TLS, or peer-address failures, keep the listener private and correct `.env`, certificate trust, client URL, or firewall rules before restarting.
4. For suspected credential exposure, rotate all three Web secrets and invalidate affected client access before returning to the ZeroTier listener.
5. For publishing uncertainty, set `WEB_PUBLISH_ENABLED=false` and verify `status.json`, `events.jsonl`, `artifacts.validation`, and `artifacts.publish_results` before retrying any upload.

## Non-goals

This boundary does not support anonymous access, public hosting, multi-tenant isolation, arbitrary filesystem browsing, remote shell execution, or exposing lower-tool browser sessions. Supporting any of those capabilities requires a separate threat model and security review.
