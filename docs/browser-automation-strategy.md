# Browser Automation Strategy Decision

**Status:** Accepted for the current Japanese visualisation workflow  
**Date:** 2026-07-27  
**Scope:** `content_pipeline` Japanese image workflow and its `Photo-Process` integration

## Decision

The Japanese workflow will use **Photo-Process browser automation as its current production execution backend**. It will be redesigned around one long-lived, single-owner browser worker per Google account/profile.

An official image-generation API is the preferred future backend **only after** its output has been shown to reproduce the required `日语视觉化` Gem behaviour and a supported credential/configuration is supplied. It is not the current implementation route.

## Why this decision

- The Japanese workflow explicitly targets the private/custom Gem named `日语视觉化`; its behaviour is not currently represented as an API prompt, model configuration, or API credential in this repository.
- `.env.example` exposes an optional `GEMINI_IMAGE_COMMAND`, but no configured official image API adapter, API key, model, or parity test for this Gem exists.
- The existing `gemini-skill` client is used for generic image-generation branches. It does not establish that it can reproduce this Gem's private configuration.
- Therefore replacing the current backend with an API now would change functionality without evidence of equivalence. Browser automation remains necessary for this workflow, but must be made safe and observable.

## Operating constraints

1. **Trusted local execution only.** Browser controls, the Photo-Process worker, and diagnostics remain bound to the local machine. They must not be exposed as a public network service.
2. **One owner per Chrome profile.** A production profile may be held by exactly one persistent browser worker. Batch jobs, direct CLI calls, and foreground debugging must not launch competing Chrome instances with that profile.
3. **Profile separation.** Production generation and human debugging use separate user-data directories. No cookies, profile contents, passwords, or authentication tokens are committed, copied into job artifacts, or emitted in normal logs.
4. **Human authentication bootstrap.** A user signs in interactively to the production profile and confirms access to the target Gem. Automation may reuse that session but must not attempt to bypass Google authentication or challenge flows.
5. **Stable target resolution.** A verified `/gem/<id>` URL is the normal path. Name-based discovery is recovery-only and must be validated before it updates configuration.
6. **Fail closed.** Missing login, redirected Gem URLs, inaccessible Gems, profile contention, or UI changes stop the image before upload/generation; they must not be retried as generation failures.
7. **Artifact-based success.** A visible browser, a loaded chat input, or a successful process launch is not success. The only success condition is a newly generated image that passes the existing decode/dimension/aspect validation and is copied into the parent job's output path.
8. **Bounded execution.** Each profile processes one image operation at a time. Retries are bounded and allowed only for transient stages; authentication, access, and lock failures require remediation.

## Target backend boundary

```text
AI Popline Japanese pipeline
  -> Photo-Process adapter (structured request/result)
  -> per-profile browser worker (only Chrome owner)
  -> Gemini / 日语视觉化 Gem
```

The adapter result must distinguish at least:

```text
OK
AUTH_REQUIRED
GEM_ACCESS_FAILED
BROWSER_BUSY
UI_CHANGED
TIMEOUT
NO_OUTPUT
VALIDATION_FAILED
EXTERNAL_TOOL_FAILED
```

## Explicit non-goals

- Automatically solve CAPTCHA, MFA, account challenges, or access restrictions.
- Treat a browser window, a chat textbox, or a generic `/app` page as proof that the target Gem is usable.
- Introduce an API backend without a configured provider and an output-parity acceptance test.

## Migration rule for a future API backend

A future API implementation may become the primary backend only when all are true:

1. The provider/model, authentication method, quota, and supported image-editing input are documented in configuration.
2. The `日语视觉化` system behaviour has a versioned prompt/configuration equivalent.
3. A representative, approved comparison set demonstrates acceptable output parity.
4. The API adapter returns the same structured result and artifact-validation evidence as the browser adapter.
5. A rollback to the browser backend is available until production validation is complete.
