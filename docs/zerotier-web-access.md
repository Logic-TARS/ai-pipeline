# ZeroTier Web Access Runbook

AI Popline supports a single operator on loopback and, after the security gate is configured, authenticated devices on one explicitly configured ZeroTier network. This does not expose MCP, Photo-Process, the desktop browser helper, MPT, SAU, or arbitrary workstation files.

## Prerequisites

- The server and each client are authorized members of the same private ZeroTier network.
- The server has a stable managed ZeroTier IP.
- The chosen TCP port is not exposed by router port forwarding, UPnP, a public reverse proxy, or a wildcard firewall rule.
- AI Popline is initially stopped or bound to `127.0.0.1` while configuration is prepared.

On the Windows server, inspect the ZeroTier interface:

```powershell
Get-NetIPAddress |
  Where-Object { $_.InterfaceAlias -like "*ZeroTier*" -and $_.AddressFamily -eq "IPv4" } |
  Select-Object InterfaceAlias, IPAddress, PrefixLength
```

Record the exact server address and managed network CIDR. Do not substitute the physical Wi-Fi/Ethernet address or subnet.

## Generate independent secrets

Generate three different values and store them only in `.env` and the approved client credential store:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Use them respectively for `WEB_ADMIN_TOKEN`, `WEB_API_TOKEN`, and `WEB_SESSION_SECRET`. Each must be at least 32 characters, and the admin and API tokens must not match.

## Configure HTTPS

Direct Uvicorn TLS is the supported initial deployment. Create a certificate whose Subject Alternative Name contains the server's ZeroTier IP; for example, with OpenSSL:

```powershell
$ztIp = "10.147.17.5"
New-Item -ItemType Directory -Force .\data\web-tls | Out-Null
openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 365 `
  -keyout .\data\web-tls\zerotier.key `
  -out .\data\web-tls\zerotier.crt `
  -subj "/CN=$ztIp" `
  -addext "subjectAltName=IP:$ztIp"
```

Protect the private key with Windows ACLs and never commit `data/` or the key. Import the certificate, or preferably the private CA that issued it, into the trusted root store on each authorized client; verify its fingerprint out of band before trusting it.

ZeroTier encrypts peer traffic, but `WEB_ALLOW_ZEROTIER_HTTP=true` is only an explicit restricted-mode exception when HTTPS cannot yet be deployed. HTTP mode does not set Secure cookies or HSTS and should not be treated as the completed configuration.

## Configure AI Popline

Example `.env` values for a server at `10.147.17.5/24`:

```env
WEB_BIND_HOST=10.147.17.5
WEB_PORT=8080
WEB_ALLOWED_NETWORKS=10.147.17.0/24
WEB_ALLOWED_HOSTS=10.147.17.5
WEB_ALLOWED_ORIGINS=https://10.147.17.5:8080
WEB_AUTH_REQUIRED=true
WEB_ADMIN_TOKEN=<independent-random-value>
WEB_API_TOKEN=<different-independent-random-value>
WEB_SESSION_SECRET=<third-independent-random-value>
WEB_SESSION_TTL_SECONDS=604800
WEB_PUBLISH_ENABLED=false
WEB_PUBLISH_REAUTH_SECONDS=300
WEB_TLS_CERTFILE=G:\Job\ai-popline\data\web-tls\zerotier.crt
WEB_TLS_KEYFILE=G:\Job\ai-popline\data\web-tls\zerotier.key
WEB_ALLOW_ZEROTIER_HTTP=false
```

Use the exact assigned address. Wildcard listeners (`0.0.0.0`, `::`) are rejected by `ai-popline serve`, and a remote bind is rejected unless its address belongs to `WEB_ALLOWED_NETWORKS`, authentication is configured, and TLS or the explicit HTTP exception is selected.

## Configure Windows Firewall

Allow only the ZeroTier local address, managed peer CIDR, and selected port:

```powershell
New-NetFirewallRule `
  -DisplayName "AI Popline ZeroTier 8080" `
  -Direction Inbound -Action Allow -Protocol TCP `
  -LocalAddress 10.147.17.5 -LocalPort 8080 `
  -RemoteAddress 10.147.17.0/24
```

Review existing broad allow rules for Python, Uvicorn, or port 8080 and remove or narrow them. The application checks direct peer addresses too, but the firewall remains a required independent layer.

## Validate and start

```powershell
ai-popline doctor
ai-popline serve
```

The CLI verifies that the bind address is assigned to a local interface, rejects wildcard binding, checks the remote security policy, disables proxy-header trust, and loads configured TLS files. Do not use a direct wildcard `uvicorn` command for ZeroTier access.

From an authorized ZeroTier client, open `https://10.147.17.5:8080/` to use the operator console, or verify the REST surface directly:

```powershell
Invoke-RestMethod https://10.147.17.5:8080/health
$headers = @{ Authorization = "Bearer <WEB_API_TOKEN>" }
Invoke-RestMethod https://10.147.17.5:8080/ready -Headers $headers
```

Expected behavior:

- `/health` returns only `{"status":"ok"}`.
- protected endpoints return `401` without a valid session or bearer token.
- peers outside loopback and `WEB_ALLOWED_NETWORKS` return `403`.
- wrong Host or Origin values are rejected.
- remote plain HTTP is rejected unless the restricted-mode exception is explicit.

## Browser console and session flow

The packaged main interface loads at `/`. When authentication is enabled, enter `WEB_ADMIN_TOKEN` on the login screen; the console retains the signed session cookie, reads the separate CSRF cookie, and adds `X-CSRF-Token` to every write automatically. Use the header action to log out and clear both cookies.

The console supports task creation and preflight, status polling, event timelines, validation details, and guarded artifact previews. Browser path fields always refer to the server workstation, and do not grant arbitrary filesystem browsing.

REST automation should normally use `Authorization: Bearer <WEB_API_TOKEN>` instead. Bearer tokens are not stored in browser cookies and therefore do not use the CSRF header.

## Publishing protection

`WEB_PUBLISH_ENABLED=false` independently blocks Web/API publishing even when task JSON contains `"publish": true`. Keep it false until generated artifacts have been reviewed and publishing through the remote API is intentionally required.

When enabled, a publish request without confirmation returns HTTP `409` with a task fingerprint and a required value such as `PUBLISH:<fingerprint>`. Resubmit the unchanged task with that exact value in `X-AI-Popline-Publish-Confirmation`; changing any task field changes the fingerprint, and session-authenticated publishing also requires a recent login.

These controls do not replace pipeline privacy enforcement, uploader deduplication, or artifact review.

## Emergency disable

1. Stop the `ai-popline serve` process.
2. Disable the firewall rule: `Disable-NetFirewallRule -DisplayName "AI Popline ZeroTier 8080"`.
3. Set `WEB_BIND_HOST=127.0.0.1`, clear `WEB_ALLOWED_NETWORKS`, and set `WEB_PUBLISH_ENABLED=false`.
4. Rotate the admin token, API token, and session secret if any credential may be exposed.
5. Deauthorize the affected client in ZeroTier Central before restarting on loopback.
