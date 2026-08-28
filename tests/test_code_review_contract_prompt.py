from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.prompt import build_code_review_message
from app.services.prompt import CODE_REVIEW_SYSTEM, CODE_REVIEW_VERIFY_SYSTEM


def test_code_review_prompt_marks_changed_endpoint_matched_by_related_service():
    diff = (
        "diff --git a/src/config/apiConfig.js b/src/config/apiConfig.js\n"
        "@@ -1 +1 @@\n"
        "+export const URL = '/vts/vts/exception/type/list'\n"
    )
    related_context = "backend/routes.py\n@app.get('/vts/vts/exception/type/list')\ndef route(): pass"

    message = build_code_review_message(diff, related_context)

    assert "Deterministic contract evidence" in message
    assert "/vts/vts/exception/type/list: matched in related-service evidence" in message


def test_code_review_prompt_keeps_unmatched_endpoint_as_unverified_risk():
    diff = (
        "diff --git a/src/config/apiConfig.js b/src/config/apiConfig.js\n"
        "@@ -1 +1 @@\n"
        "+export const URL = '/vts/report/vts/transaction/mapping/list'\n"
    )
    related_context = "backend/routes.py\n@app.get('/elock/report/vts/transaction/mapping/list')\ndef route(): pass"

    message = build_code_review_message(diff, related_context)

    assert "/vts/report/vts/transaction/mapping/list: not found in supplied related-service evidence" in message
    assert "does not prove request-parameter or response-shape semantics" in message


def test_code_review_prompt_does_not_create_contract_evidence_without_related_repo():
    diff = (
        "diff --git a/src/config/apiConfig.js b/src/config/apiConfig.js\n"
        "@@ -1 +1 @@\n"
        "+export const URL = '/vts/report/vts/transaction/mapping/list'\n"
    )

    message = build_code_review_message(diff, "")

    assert "No related-service repository evidence was available" in message
    assert "Deterministic contract evidence" not in message
    assert "not found in supplied related-service evidence" not in message


def test_code_review_policy_rejects_unproved_dependency_and_visual_speculation():
    assert "Do not report speculative dependency issues from an import alone" in CODE_REVIEW_SYSTEM
    assert "package.json/lockfile" in CODE_REVIEW_SYSTEM
    assert "Do not report subjective or hypothetical visual polish concerns" in CODE_REVIEW_SYSTEM
    assert "claims an imported package may be missing unless the" in CODE_REVIEW_VERIFY_SYSTEM
    assert "visual polish/style-only" in CODE_REVIEW_VERIFY_SYSTEM


def test_code_review_policy_rejects_false_order_by_for_aggregate_claims():
    assert "Do not claim an aggregate subquery is nondeterministic merely because it lacks ORDER BY" in CODE_REVIEW_SYSTEM
    assert "GROUP BY with" in CODE_REVIEW_SYSTEM
    assert "MAX/MIN with GROUP BY needs ORDER BY" in CODE_REVIEW_VERIFY_SYSTEM


def test_code_review_policy_requires_related_service_evidence_for_backend_claims():
    assert "If related-service repository evidence is not supplied" in CODE_REVIEW_SYSTEM
    assert "do not report backend/API/contract" in CODE_REVIEW_SYSTEM
