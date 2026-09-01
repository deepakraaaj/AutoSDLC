---
id: TS-002
title: Bitbucket PR listing returns 401 for configured repository
date: 2026-09-01
status: resolved
area: Bitbucket integration
tags:
  - bitbucket
  - authentication
  - pull-requests
  - configuration
---

## TL;DR

Bitbucket PR listing can fail with `Token is invalid, expired, or not supported for this endpoint` when Bitbucket rejects the configured token. The client now accepts `BITBUCKET_API_TOKEN` as a legacy alias, supports `BITBUCKET_AUTH_METHOD=basic|bearer`, and appends endpoint-specific remediation guidance to PR-listing 401 errors. For `kritilabs/fits-service`, a status-only probe confirmed the configured token is rejected globally by Bitbucket, not only by the PR endpoint.

## Issue

The project Pull Requests view reported:

```text
Bitbucket PR listing failed (401): Token is invalid, expired, or not supported for this endpoint.
```

The affected repository was `kritilabs/fits-service`.

## Investigation

Observed code path:

```text
app/api/projects.py::_fetch_repo_pull_requests
bitbucket/client.py::list_pull_requests
```

`BitbucketConfig` loaded only `BITBUCKET_ACCESS_TOKEN`, while `run.md` documented `BITBUCKET_API_TOKEN`. Authentication was also inferred only from whether `BITBUCKET_USERNAME` or `BITBUCKET_EMAIL` was set: identity present meant Basic auth, identity absent meant Bearer auth.

After confirming `.env` already had `BITBUCKET_ACCESS_TOKEN`, `BITBUCKET_WORKSPACE=kritilabs`, and `BITBUCKET_USERNAME` set to an email address, status-only live probes were run without printing the token. Both Basic and Bearer auth returned 401 for:

```text
https://api.bitbucket.org/2.0/user
https://api.bitbucket.org/2.0/repositories/kritilabs/fits-service
https://api.bitbucket.org/2.0/repositories/kritilabs/fits-service/pullrequests
```

Current Bitbucket Cloud guidance and real endpoint behavior vary by token type. Atlassian API tokens generally need Basic auth with the account email and pull-request read scopes. Repository or workspace access tokens generally use Bearer auth and should not be forced into Basic by an unrelated username/email env var.

## Approaches Considered

- Require all deployments to rename `BITBUCKET_API_TOKEN` to `BITBUCKET_ACCESS_TOKEN`.
- Keep automatic Basic/Bearer detection only.
- Add an explicit auth-method override and preserve the legacy token alias.

## Chosen Approach

The client now:

- Reads `BITBUCKET_ACCESS_TOKEN`, falling back to `BITBUCKET_API_TOKEN`.
- Supports `BITBUCKET_AUTH_METHOD=basic` and `BITBUCKET_AUTH_METHOD=bearer`.
- Keeps previous auto-detection when no explicit auth method is configured.
- Adds a targeted PR-listing 401 message that explains the expected env vars and scopes.

This keeps existing installs working while giving operators a deterministic fix when Bitbucket rejects one auth mode for PR endpoints.

## Root Cause

Confirmed in code: environment variable documentation and runtime loading did not agree, and auth-mode selection was implicit. Confirmed for the reported repository: the configured token is rejected by Bitbucket with both Basic and Bearer auth even on `/2.0/user`, so the current credential is expired, revoked, malformed, or lacks Bitbucket API access.

## Fix & Verification

Files changed:

```text
bitbucket/client.py
tests/test_bitbucket_client.py
.env.example
run.md
```

Verification:

```text
pytest tests/test_bitbucket_client.py
```

Result:

```text
23 passed
```

Broader project pull-request endpoint tests could not be collected in this environment because `ast_grep_py` was not installed.

## Takeaway

For Bitbucket auth issues, first identify the token type and pin the auth mode:

- Atlassian API token: `BITBUCKET_USERNAME=<account email>` and `BITBUCKET_AUTH_METHOD=basic`.
- Repository/workspace access token: unset `BITBUCKET_USERNAME` or set `BITBUCKET_AUTH_METHOD=bearer`.
- Ensure the token includes repository read and pull-request read scopes.
