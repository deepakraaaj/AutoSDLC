import re
from app.schemas.models import GenerationOutput, OverallMetrics, StoryMetrics, TaskMetrics, TestMetrics, ValidationResult, ValidationCheck

# The one pass bar every quality gate in this app measures against: run_validation
# below (coverage/story/task quality checks) AND app.core.backlog_quality.find_weak_items
# (which items count as "weak" enough to target for a fix). Defined once here so the two
# can't drift apart the way they did before — a dimension scoring 61% used to pass
# find_weak_items's separate, lower "weak" cutoff (60) while still failing this bar,
# so it could never be targeted and would sit there forever dragging the average down.
QUALITY_PASS_THRESHOLD = 80

# === SPECIFICITY: Actor + Intent + Rationale ===
_EXPANDED_BLOCKLIST = {
    "user", "the user", "a user", "users", "customer", "a customer", "person",
    "end user", "admin user", "the customer", "our user", "someone", "anyone",
    "team member", "team lead", "manager", "admin", "viewer", "guest"
}

# === TESTABILITY: AC Count + AC Content Quality ===
# Accept criteria that are clearly binary/testable even if they do not use
# a strict BDD template.
_TESTABLE_MARKERS = {
    "should", "must", "when", "given", "then", "assert", "verify",
    "accept", "reject", "allow", "block", "show", "display", "return",
    "save", "load", "generate", "start", "stop", "create", "update",
    "delete", "render", "validate", "handle", "process", "submit",
    "retry", "filter", "sort", "calculate", "sync", "enable", "disable",
    "persist", "import", "export", "open", "close", "approve", "search",
    "select", "download", "upload", "visible", "working", "error",
    "invalid", "missing", "empty", "failed", "success",
}

# === EDGE CASE: Scan AC content for edge case language ===
_EDGE_CASE_KEYWORDS = {
    "invalid", "empty", "fail", "error", "when", "if", "boundary",
    "exceed", "missing", "null", "zero", "negative", "timeout",
    "retry", "duplicate", "conflict", "unauthorized", "forbidden", "not found"
}


def score_single_story(s) -> dict[str, int]:
    """Score one story on all four story dimensions. Factored out of
    score_stories so a single item can be scored on its own — used both to
    build the aggregate below and (by app.core.backlog_quality.find_weak_items)
    to find which specific stories are dragging the aggregate down, using the
    exact same rubric the Scorecard shows."""
    # Actor quality
    actor = s.as_a.strip().lower()
    actor_score = 90 if (actor not in _EXPANDED_BLOCKLIST and len(actor.split()) >= 2) else 30

    # Intent substance (i_want should be 8+ words, not just "login" or "do X")
    intent_words = len(s.i_want.strip().split())
    if intent_words >= 8:
        intent_score = 90
    elif intent_words >= 5:
        intent_score = 65
    else:
        intent_score = 25

    # Rationale substance (so_that should explain business value, 6+ words)
    rationale_words = len(s.so_that.strip().split())
    if rationale_words >= 6:
        rationale_score = 90
    elif rationale_words >= 3:
        rationale_score = 60
    else:
        rationale_score = 20

    specificity = int((actor_score + intent_score + rationale_score) / 3)

    ac_list = s.acceptance_criteria
    ac_count = len(ac_list)

    # Count-based score
    if ac_count >= 3:
        count_score = 80
    elif ac_count == 2:
        count_score = 60
    elif ac_count == 1:
        count_score = 30
    else:
        count_score = 0

    # Content quality: each AC should be substantive (6+ words) and contain quality keywords
    substantive_count = 0
    if ac_count > 0:
        for criterion in ac_list:
            criterion_text = criterion.strip().lower()
            has_words = len(criterion_text.split()) >= 6
            has_keyword = any(
                re.search(rf"\b{re.escape(kw)}\w*\b", criterion_text)
                for kw in _TESTABLE_MARKERS
            )
            if has_words and has_keyword:
                substantive_count += 1

        content_score = int((substantive_count / ac_count) * 100)
    else:
        content_score = 0

    testability = int((count_score + content_score) / 2)

    # Sizing: cross-validate size label against AC count and body length
    body_words = len(s.i_want.strip().split()) + len(s.so_that.strip().split())
    size = s.size.strip().lower()

    if size == "small" and ac_count <= 4 and body_words <= 20:
        sizing = 95
    elif size == "medium" and ac_count <= 7:
        sizing = 90
    elif size == "large":
        # Large stories should be split - always penalized slightly
        sizing = 50
    else:
        # Inconsistency: e.g., "small" with 8 ACs
        sizing = 40

    # Edge case coverage
    if not ac_list:
        edge_case = 0
    else:
        edge_count = sum(1 for criterion in ac_list if any(kw in criterion.strip().lower() for kw in _EDGE_CASE_KEYWORDS))
        ratio = edge_count / len(ac_list)
        if ratio >= 0.33:
            edge_case = 90
        elif ratio >= 0.15:
            edge_case = 65
        elif ratio > 0:
            edge_case = 45
        else:
            edge_case = 20

    return {"specificity": specificity, "testability": testability, "sizing": sizing, "edge_case": edge_case}


def score_stories(output: GenerationOutput) -> StoryMetrics:
    stories = output.stories
    if not stories:
        return StoryMetrics(
            specificity_score=0,
            testability_score=0,
            sizing_score=0,
            edge_case_score=0,
            overall=0,
        )

    per_story = [score_single_story(s) for s in stories]
    specificity = int(sum(d["specificity"] for d in per_story) / len(per_story))
    testability = int(sum(d["testability"] for d in per_story) / len(per_story))
    sizing = int(sum(d["sizing"] for d in per_story) / len(per_story))
    edge_case = int(sum(d["edge_case"] for d in per_story) / len(per_story))

    overall = int((specificity + testability + sizing + edge_case) / 4)

    return StoryMetrics(
        specificity_score=specificity,
        testability_score=testability,
        sizing_score=sizing,
        edge_case_score=edge_case,
        overall=overall,
    )


# === DEFINITION OF DONE: Keywords + Structure analysis ===
_DOD_KEYWORDS = {
    "tested", "test", "passing", "reviewed", "deployed", "verified",
    "approved", "merged", "checked", "confirmed", "documented", "coverage"
}

# Structure patterns (BDD, checklist, etc.)
_STRUCTURE_PATTERNS = [
    r"given.*when.*then",  # BDD style
    r"\d+\s*[-•]",  # Numbered or bulleted list
    r"✓|✗|☑|☐",  # Checkbox markers
    r"must|should|will",  # Explicit requirements
]


def score_single_task(t, all_task_ids: set[str]) -> dict[str, int]:
    """Score one task on all four task dimensions. Factored out of
    score_tasks the same way score_single_story was — see that function's
    docstring."""
    desc = t.description.strip()
    title = t.title.strip()
    dod = t.definition_of_done.strip()

    desc_words = desc.split()
    title_words = title.split()

    # Length score
    word_count = len(desc_words)
    if word_count >= 15:
        clarity = 80
    elif word_count >= 8:
        clarity = 55
    else:
        clarity = 20

    # Context-aware clarity: only penalize if description is MOSTLY just the
    # title (>95% overlap), or an exact copy-paste of the definition of done.
    if desc.lower() == dod.lower():
        clarity = 10
    elif title_words and desc_words:
        overlap = len(set(desc_words) & set(title_words)) / max(len(desc_words), 1)
        if overlap > 0.95:
            clarity = 20

    dod_lower = dod.lower()
    desc_lower = desc.lower()
    if dod_lower == desc_lower:
        dod_score = 10
    else:
        has_keywords = any(kw in dod_lower for kw in _DOD_KEYWORDS)
        has_structure = any(re.search(pattern, dod_lower, re.IGNORECASE) for pattern in _STRUCTURE_PATTERNS)
        if has_keywords:
            dod_score = 85
        elif has_structure:
            dod_score = 70
        else:
            dod_score = 45

    # Estimate: numeric range validation
    est = t.estimate_hours.strip()
    m = re.match(r'(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)', est)
    if m:
        try:
            low, high = float(m.group(1)), float(m.group(2))
            # Validate: 0 <= low < high <= 80, range <= 40
            if low >= 0 and high > low and high <= 80 and (high - low) <= 40:
                estimate = 95
            elif high > 80 or (high - low) > 40:
                estimate = 50  # Implausibly wide or out of bounds
            elif low > high:
                estimate = 30  # Inverted
            else:
                estimate = 70
        except (ValueError, TypeError):
            estimate = 20
    else:
        try:
            float(est)
            estimate = 60  # No valid range found - single number
        except (ValueError, TypeError):
            estimate = 20

    # Dependency: referential integrity
    deps = t.dependencies or []
    if not deps:
        dependency = 80  # No dependencies is fine - leaf tasks are valid
    else:
        valid_count = sum(1 for dep_id in deps if dep_id in all_task_ids)
        if valid_count == len(deps):
            dependency = 95
        elif valid_count == 0:
            dependency = 10  # All dependencies are orphaned
        else:
            dependency = 40  # Some valid, some orphaned

    return {"clarity": clarity, "definition_of_done": dod_score, "estimate": estimate, "dependency": dependency}


def score_tasks(output: GenerationOutput, all_task_ids: set[str]) -> TaskMetrics:
    tasks = output.tasks
    if not tasks:
        return TaskMetrics(
            clarity_score=0,
            definition_of_done_score=0,
            estimate_score=0,
            dependency_score=0,
            overall=0,
        )

    per_task = [score_single_task(t, all_task_ids) for t in tasks]
    clarity = int(sum(d["clarity"] for d in per_task) / len(per_task))
    dod = int(sum(d["definition_of_done"] for d in per_task) / len(per_task))
    estimate = int(sum(d["estimate"] for d in per_task) / len(per_task))
    dependency = int(sum(d["dependency"] for d in per_task) / len(per_task))

    overall = int((clarity + dod + estimate + dependency) / 4)

    return TaskMetrics(
        clarity_score=clarity,
        definition_of_done_score=dod,
        estimate_score=estimate,
        dependency_score=dependency,
        overall=overall,
    )


def score_test_cases(output: GenerationOutput) -> TestMetrics:
    """Scores the manual QA test cases Phase 4 generates (see TestCase in
    app/schemas/models.py) — was defined on OverallMetrics from the start but
    never actually computed, so every generation showed test_metrics: null
    regardless of whether Phase 4 succeeded."""
    tasks = output.tasks
    if not tasks:
        return TestMetrics(coverage_score=0, expected_result_quality_score=0, edge_case_coverage_score=0, overall=0)

    # === COVERAGE: how many tasks got the prompt's target of 2-3 test cases each ===
    coverage_scores = []
    for t in tasks:
        n = len(t.test_cases)
        if n == 0:
            coverage_scores.append(0)
        elif n == 1:
            coverage_scores.append(40)
        elif n == 2:
            coverage_scores.append(80)
        else:
            coverage_scores.append(95)
    coverage = int(sum(coverage_scores) / len(coverage_scores))

    all_test_cases = [tc for t in tasks for tc in t.test_cases]
    if not all_test_cases:
        # Phase 4 produced nothing at all — coverage is meaningfully 0 (already
        # reflected above), but there's no content left to score for the
        # other two dimensions rather than a misleading fixed 0.
        return TestMetrics(coverage_score=coverage, expected_result_quality_score=0, edge_case_coverage_score=0, overall=int(coverage / 3))

    # === EXPECTED RESULT QUALITY: substantive, observable outcomes — not
    # "it works" or "no errors", which aren't verifiable by a QA tester ===
    vague_phrases = {"works correctly", "works as expected", "no errors", "success", "it works", "passes", "works"}
    quality_scores = []
    for tc in all_test_cases:
        result = tc.expected_result.strip()
        word_count = len(result.split())
        has_steps = len(tc.steps) > 0
        if result.lower() in vague_phrases or word_count < 4:
            score = 20
        elif word_count >= 10 and has_steps:
            score = 90
        elif word_count >= 6:
            score = 70
        else:
            score = 45
        quality_scores.append(score)
    expected_result_quality = int(sum(quality_scores) / len(quality_scores))

    # === EDGE CASE COVERAGE: mix of test types beyond happy-path "functional"
    # — same ratio-based scale as score_stories' edge-case check ===
    non_functional = sum(1 for tc in all_test_cases if tc.test_type != "functional")
    ratio = non_functional / len(all_test_cases)
    if ratio >= 0.33:
        edge_case_coverage = 90
    elif ratio >= 0.15:
        edge_case_coverage = 65
    elif ratio > 0:
        edge_case_coverage = 45
    else:
        edge_case_coverage = 20

    overall = int((coverage + expected_result_quality + edge_case_coverage) / 3)

    return TestMetrics(
        coverage_score=coverage,
        expected_result_quality_score=expected_result_quality,
        edge_case_coverage_score=edge_case_coverage,
        overall=overall,
    )


def compute_metrics(output: GenerationOutput) -> OverallMetrics:
    # Build set of all task IDs for dependency validation
    all_task_ids = {t.id for t in output.tasks}

    story_metrics = score_stories(output)
    task_metrics = score_tasks(output, all_task_ids)
    test_metrics = score_test_cases(output)

    # === COVERAGE: Stricter definition ===
    # A story is well-covered if ALL of:
    # 1. Has >= 2 tasks linked (not just any 1)
    # 2. All its ACs have content (each criterion >= 5 words)
    # 3. epic_id is set (story belongs to an epic)
    # 4. confidence != "low"

    stories = output.stories
    tasks = output.tasks

    # Build task count per story
    task_count_per_story = {}
    for t in tasks:
        if t.story_id:
            task_count_per_story[t.story_id] = task_count_per_story.get(t.story_id, 0) + 1

    well_covered = 0
    for s in stories:
        ac_list = s.acceptance_criteria
        # Check AC content: each AC should have 5+ words
        all_ac_substantive = all(len(ac.strip().split()) >= 5 for ac in ac_list) if ac_list else False

        is_covered = (
            task_count_per_story.get(s.id, 0) >= 2  # >= 2 tasks linked
            and all_ac_substantive  # All ACs have substance
            and s.epic_id is not None  # Belongs to an epic
            and s.confidence != "low"  # Not low confidence
        )
        if is_covered:
            well_covered += 1

    coverage_score = int((well_covered / len(stories)) * 100) if stories else 0

    # === INPUT QUALITY: Distinguish blocking vs important ===
    gaps = output.gaps
    blocking = sum(1 for g in gaps if g.severity == "blocking")
    important = sum(1 for g in gaps if g.severity == "important")
    total_gaps = len(gaps)

    if blocking > 0:
        input_quality = "low"
    elif important > 2:
        input_quality = "medium"
    elif important > 0 or total_gaps > 5:
        input_quality = "medium"
    else:
        input_quality = "high"

    # === Confidence Summary ===
    avg = int((story_metrics.overall + task_metrics.overall) / 2)
    if avg >= 80 and input_quality == "high":
        summary = f"High confidence — {len(stories)} stories and {len(tasks)} tasks generated. {coverage_score}% fully covered with substantive ACs and linked tasks."
    elif avg >= 60:
        summary = f"Medium confidence — some assumptions made. Review {len(gaps)} gap(s) and AC depth before starting work."
    else:
        summary = f"Low confidence — input was thin or ACs lack substance. Answer gaps and regenerate."

    return OverallMetrics(
        coverage_score=coverage_score,
        gap_count=len(gaps),
        input_quality=input_quality,
        story_metrics=story_metrics,
        task_metrics=task_metrics,
        test_metrics=test_metrics,
        confidence_summary=summary,
    )


def run_validation(metrics: OverallMetrics) -> ValidationResult:
    checks = []
    passed_count = 0

    # Coverage and story/task quality gate on the same shared bar (QUALITY_PASS_THRESHOLD)
    # find_weak_items targets fixes against — see that constant's definition for why.
    coverage_threshold = QUALITY_PASS_THRESHOLD
    quality_threshold = QUALITY_PASS_THRESHOLD

    # Check 1: Coverage Score clears the shared pass bar
    coverage_pass = metrics.coverage_score >= coverage_threshold
    checks.append(ValidationCheck(
        label="Coverage Score",
        passed=coverage_pass,
        value=f"{metrics.coverage_score}%",
        threshold=f"≥ {coverage_threshold}%"
    ))
    if coverage_pass:
        passed_count += 1

    # Check 2: Story Quality clears the shared pass bar
    story_pass = metrics.story_metrics.overall >= quality_threshold
    checks.append(ValidationCheck(
        label="Story Quality",
        passed=story_pass,
        value=f"{metrics.story_metrics.overall}%",
        threshold=f"≥ {quality_threshold}%"
    ))
    if story_pass:
        passed_count += 1

    # Check 3: Task Quality clears the shared pass bar
    task_pass = metrics.task_metrics.overall >= quality_threshold
    checks.append(ValidationCheck(
        label="Task Quality",
        passed=task_pass,
        value=f"{metrics.task_metrics.overall}%",
        threshold=f"≥ {quality_threshold}%"
    ))
    if task_pass:
        passed_count += 1

    # Check 4: Gap Count <= 3
    gaps_pass = metrics.gap_count <= 3
    checks.append(ValidationCheck(
        label="Gap Count",
        passed=gaps_pass,
        value=f"{metrics.gap_count}",
        threshold="≤ 3"
    ))
    if gaps_pass:
        passed_count += 1

    # Check 5: Input Quality == "high"
    quality_pass = metrics.input_quality == "high"
    checks.append(ValidationCheck(
        label="Input Quality",
        passed=quality_pass,
        value=metrics.input_quality.capitalize(),
        threshold="= High"
    ))
    if quality_pass:
        passed_count += 1

    # Determine trust level
    if passed_count == 5:
        trust_level = "trusted"
        recommendation = "✓ Output is ready to use. Review any gaps and push to Redmine."
    elif passed_count >= 3:
        trust_level = "review"
        if metrics.task_metrics.dependency_score < quality_threshold:
            recommendation = "⚠ Task dependency references need repair before planning work. Use the dependency repair action, then review the updated score."
        else:
            failed = ", ".join(check.label for check in checks if not check.passed)
            recommendation = f"⚠ {failed} needs review before starting work."
    else:
        trust_level = "low"
        recommendation = "✗ Input brief was thin. Answer the gaps listed below and regenerate."

    return ValidationResult(
        trust_level=trust_level,
        checks=checks,
        recommendation=recommendation
    )
