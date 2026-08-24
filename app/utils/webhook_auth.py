"""HMAC verification for inbound webhooks. This is the first inbound-
authenticated surface in AutoSDLC — everything else in this app (Redmine,
Bitbucket read-only endpoints, provider settings) authenticates OUTBOUND
calls this backend makes with credentials the operator supplies; nothing
until now has had to verify that an INBOUND request is genuinely from
Bitbucket. Get this fail-closed, or the webhook is worthless: an attacker
who can reach this endpoint could otherwise trigger arbitrary code-review
jobs (and, once Phase 3's push_backlog_to_bitbucket lands, PR comments) with
a forged payload."""
from __future__ import annotations

import hmac
import hashlib


def verify_bitbucket_signature(payload_bytes: bytes, signature_header: str | None, secret: str | None) -> bool:
    """Verify Bitbucket's `X-Hub-Signature: sha256=<hex>` header against the
    raw request body. Fails closed: a missing secret, missing header, or
    malformed header are all rejections, never a silent pass-through."""
    if not secret:
        return False
    if not signature_header or "=" not in signature_header:
        return False
    algo, _, provided_hex = signature_header.partition("=")
    if algo.strip().lower() != "sha256":
        return False
    expected_hex = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected_hex, provided_hex.strip())
