from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.review_filters import filter_code_review_findings, load_review_filter_policy


def _filter(comment: str, review_input: str = ""):
    return filter_code_review_findings([{"comment": comment, "evidence": comment}], review_input)


def test_filters_missing_dependency_claim_without_manifest_evidence():
    kept, removed = _filter("Tooltip is imported from @mui/material but may not be installed or listed in package.json.")

    assert kept == []
    assert removed[0]["filtered_reason"] == "unsupported_missing_dependency_claim"


def test_keeps_missing_dependency_claim_when_manifest_is_in_review_input():
    review_input = "diff --git a/package.json b/package.json\n--- a/package.json\n+++ b/package.json\n"
    kept, removed = _filter("Tooltip is imported but @mui/material is missing from package.json dependencies.", review_input)

    assert len(kept) == 1
    assert removed == []


def test_filters_style_only_visual_speculation():
    kept, removed = _filter("The text-shadow may not align properly with truncated line-clamp text.")

    assert kept == []
    assert removed[0]["filtered_reason"] == "style_only_visual_speculation"


def test_keeps_visual_finding_with_accessibility_impact():
    kept, removed = _filter("The tooltip content is inaccessible to keyboard users because focus handling was removed.")

    assert len(kept) == 1
    assert removed == []


def test_filters_false_order_by_for_max_group_by_claim():
    kept, removed = _filter("The SELECT serial_number, company_id, MAX(id) GROUP BY serial_number lacks ORDER BY and is nondeterministic.")

    assert kept == []
    assert removed[0]["filtered_reason"] == "false_order_by_for_aggregate_determinism"


def test_keeps_real_sql_latest_assumption_risk():
    kept, removed = _filter("The query assumes MAX(id) means latest business time, but ordering should use updated_at.")

    assert len(kept) == 1
    assert removed == []


def test_filters_unsupported_id_recency_assumption_without_temporal_evidence():
    kept, removed = _filter("MAX(id) may not be monotonically increasing with time, so this may return stale location data.")

    assert kept == []
    assert removed[0]["filtered_reason"] == "unsupported_id_recency_assumption_claim"


def test_keeps_id_recency_claim_when_temporal_evidence_exists():
    review_input = "diff --git a/repo.java b/repo.java\n+ ORDER BY updated_at DESC\n"
    kept, removed = _filter("MAX(id) may not be monotonically increasing with time, so this may return stale location data.", review_input)

    assert len(kept) == 1
    assert removed == []


def test_filters_generic_timezone_claim_without_contract_evidence():
    review_input = (
        "diff --git a/src/components/DateRangeComponent.tsx b/src/components/DateRangeComponent.tsx\n"
        "+  const maxDateTime = getDayEnd(moment()).valueOf();\n"
    )
    kept, removed = _filter(
        "Using moment().valueOf() without timezone awareness may produce incorrect day-end timestamps.",
        review_input,
    )

    assert kept == []
    assert removed[0]["filtered_reason"] == "unsupported_timezone_claim_without_contract"


def test_filters_generic_timezone_claim_for_other_date_library_without_contract_evidence():
    review_input = (
        "diff --git a/src/components/DateRangeComponent.tsx b/src/components/DateRangeComponent.tsx\n"
        "+  const maxDateTime = endOfDay(dayjs()).valueOf();\n"
    )
    kept, removed = _filter(
        "This may allow invalid selections in a different timezone because the day-end timestamp can be wrong.",
        review_input,
    )

    assert kept == []
    assert removed[0]["filtered_reason"] == "unsupported_timezone_claim_without_contract"


def test_keeps_timezone_claim_when_contract_evidence_exists():
    review_input = (
        "diff --git a/src/components/DateRangeComponent.tsx b/src/components/DateRangeComponent.tsx\n"
        "+  const maxDateTime = getDayEnd(moment()).valueOf();\n"
        "+  // backend timezone offset is converted to UTC before submission\n"
    )
    kept, removed = _filter(
        "Using moment().valueOf() without timezone awareness may produce incorrect day-end timestamps.",
        review_input,
    )

    assert len(kept) == 1
    assert removed == []


def test_filters_endpoint_missing_claim_when_contract_evidence_matched():
    review_input = (
        "Deterministic contract evidence from changed API path literals:\n"
        "- /vts/vts/exception/type/list: matched in related-service evidence\n"
    )
    kept, removed = _filter("The backend may not support route /vts/vts/exception/type/list.", review_input)

    assert kept == []
    assert removed[0]["filtered_reason"] == "endpoint_missing_claim_contradicted_by_contract_evidence"


def test_filters_related_service_absence_only_route_claim():
    kept, removed = _filter("The related-service evidence does not contain this exact path, so verify backend support before merging.")

    assert kept == []
    assert removed[0]["filtered_reason"] == "backend_claim_without_related_service_evidence"


def test_filters_generic_backend_contract_confirmation():
    kept, removed = _filter("Confirm the backend response includes filterBy with these exact keys to avoid pagination issues.")

    assert kept == []
    assert removed[0]["filtered_reason"] == "backend_claim_without_related_service_evidence"


def test_filters_product_intent_confirmation_not_bug():
    kept, removed = _filter("Commented out navigation items, removing user access to these features. Confirm if this is intentional and aligns with product strategy.")

    assert kept == []
    assert removed[0]["filtered_reason"] == "product_intent_confirmation_not_bug"


def test_filters_unproved_cross_origin_route_claim():
    kept, removed = _filter("Changed SIM Details link from PMS_UI_URL + '/sim/list' to '/sim/list'. Verify if PMS_UI_URL is required for cross-origin routing.")

    assert kept == []
    assert removed[0]["filtered_reason"] == "unproved_cross_origin_route_claim"


def test_keeps_backend_contract_claim_with_runtime_failure_evidence():
    kept, removed = _filter("Backend response structure is not confirmed and this code can throw TypeError: cannot read filterBy of undefined.")

    assert len(kept) == 1
    assert removed == []


def test_filters_unproved_dynamic_label_requirement():
    kept, removed = _filter("Tooltip title content is hardcoded to 'Source ID' and zone.name, which may not reflect the intended dynamic label for the zone. If the label should vary, the title should be parameterized.")

    assert kept == []
    assert removed[0]["filtered_reason"] == "unproved_dynamic_label_requirement"


def test_keeps_dynamic_label_issue_with_accessibility_evidence():
    kept, removed = _filter("Tooltip title is hardcoded and conflicts with the aria-label requirement for translated platform names.")

    assert len(kept) == 1
    assert removed == []


def test_filters_unproved_pointer_events_speculation():
    kept, removed = _filter("The 'pointer-events-none' class is applied to the outer container but 'pointer-events-auto' is used on inner interactive elements. This can cause subtle interaction issues if the parent container captures pointer events unintentionally.")

    assert kept == []
    assert removed[0]["filtered_reason"] == "unproved_pointer_events_speculation"


def test_keeps_pointer_events_issue_with_click_failure_evidence():
    kept, removed = _filter("The pointer-events-none overlay covers the button, making it unclickable on hover.")

    assert len(kept) == 1
    assert removed == []


def test_filters_unproved_default_value_product_expectation():
    kept, removed = _filter("Default date range is initialized to today's start/end, which may not match user expectations if the intended default is a broader or historical range. Ensure this aligns with product requirements.")

    assert kept == []
    assert removed[0]["filtered_reason"] == "unproved_default_value_product_expectation"


def test_keeps_default_value_regression_with_previous_behavior_evidence():
    kept, removed = _filter("Default date range changed from the previous default of last 30 days to today, causing a regression for historical transaction review.")

    assert len(kept) == 1
    assert removed == []


def test_filters_unproved_tostring_type_guard_claim():
    kept, removed = _filter("Click handler calls props.onClickSwapUser with cellProps.cell.row.original.id.toString(), but the original.id type is not verified here. If id is not a number or string, this could cause runtime errors or incorrect behavior.")

    assert kept == []
    assert removed[0]["filtered_reason"] == "unproved_tostring_type_guard_claim"


def test_keeps_tostring_issue_with_nullable_type_evidence():
    kept, removed = _filter("The row id is optional in the interface, so id.toString() can throw TypeError when id is undefined.")

    assert len(kept) == 1
    assert removed == []


def test_filters_backend_claim_when_related_service_evidence_was_not_checked():
    review_input = (
        "Pull request diff:\n\n"
        "+const url = '/vts/report/list'\n\n"
        "No related-service repository evidence was available. Endpoint compatibility must remain an unverified risk, not a confirmed defect."
    )
    kept, removed = _filter("Confirm the backend response shape supports this API route before merging.", review_input)

    assert kept == []
    assert removed[0]["filtered_reason"] == "backend_claim_without_related_service_evidence"


def test_keeps_backend_claim_when_related_service_evidence_was_checked():
    review_input = (
        "Pull request diff:\n\n"
        "+const url = '/vts/report/list'\n\n"
        "Related service repository evidence (read-only cross-check):\n"
        "## Related repository: fits-service\n"
        "--- routes.py ---\n"
        "1: @app.get('/vts/report/list')"
    )
    kept, removed = _filter("The backend route contract may mismatch the changed API path.", review_input)

    assert len(kept) == 1
    assert removed == []


def test_filter_policy_can_be_loaded_from_json_file(tmp_path):
    policy = tmp_path / "rules.json"
    policy.write_text(
        '{"version": 1, "rules": [{"id": "custom_noise", "text_any": ["custom false positive"]}]}',
        encoding="utf-8",
    )
    load_review_filter_policy.cache_clear()

    loaded = load_review_filter_policy(str(policy))

    assert loaded["rules"][0]["id"] == "custom_noise"


def test_invalid_filter_policy_falls_back_to_builtin(tmp_path):
    policy = tmp_path / "bad.json"
    policy.write_text("not-json", encoding="utf-8")
    load_review_filter_policy.cache_clear()

    loaded = load_review_filter_policy(str(policy))

    assert any(rule["id"] == "unsupported_missing_dependency_claim" for rule in loaded["rules"])
