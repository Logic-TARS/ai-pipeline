# Web Access Boundary

## Decision

AI Popline's Web UI and REST API are a single-operator administration surface. Supported access is limited to:

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

The intended remote deployment binds to the host's ZeroTier interface address. Binding a host process to `0.0.0.0` or `::` is not acceptable. The container image uses an internal wildcard listener only inside its isolated network namespace; Docker Compose publishes that port on host loopback, requires application authentication, and does not provide the supported ZeroTier listener path.

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

## Non-goals

This boundary does not support anonymous access, public hosting, multi-tenant isolation, arbitrary filesystem browsing, remote shell execution, or exposing lower-tool browser sessions. Supporting any of those capabilities requires a separate threat model and security review.
