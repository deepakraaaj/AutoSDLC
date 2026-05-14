import re
from schemas import GenerationOutput, OverallMetrics, StoryMetrics, TaskMetrics, ValidationResult, ValidationCheck


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

    # === SPECIFICITY: Actor + Intent + Rationale ===
    expanded_blocklist = {
        "user", "the user", "a user", "users", "customer", "a customer", "person",
        "end user", "admin user", "the customer", "our user", "someone", "anyone",
        "team member", "team lead", "manager", "admin", "viewer", "guest"
    }

    specificity_scores = []
    for s in stories:
        # Actor quality
        actor = s.as_a.strip().lower()
        actor_score = 90 if (actor not in expanded_blocklist and len(actor.split()) >= 2) else 30

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

        specificity_scores.append(int((actor_score + intent_score + rationale_score) / 3))

    specificity = int(sum(specificity_scores) / len(specificity_scores))

    # === TESTABILITY: AC Count + AC Content Quality ===
    # Accept criteria that are clearly binary/testable even if they do not use
    # a strict BDD template.
    testable_markers = {
        "should", "must", "when", "given", "then", "assert", "verify",
        "accept", "reject", "allow", "block", "show", "display", "return",
        "save", "load", "generate", "start", "stop", "create", "update",
        "delete", "render", "validate", "handle", "process", "submit",
        "retry", "filter", "sort", "calculate", "sync", "enable", "disable",
        "persist", "import", "export", "open", "close", "approve", "search",
        "select", "download", "upload", "visible", "working", "error",
        "invalid", "missing", "empty", "failed", "success",
    }
    testability_scores = []
    for s in stories:
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
                    for kw in testable_markers
                )
                if has_words and has_keyword:
                    substantive_count += 1

            content_score = int((substantive_count / ac_count) * 100)
        else:
            content_score = 0

        testability_scores.append(int((count_score + content_score) / 2))

    testability = int(sum(testability_scores) / len(testability_scores))

    # === SIZING: Cross-validate size label against AC count and body length ===
    sizing_scores = []
    for s in stories:
        ac_count = len(s.acceptance_criteria)
        body_words = len(s.i_want.strip().split()) + len(s.so_that.strip().split())
        size = s.size.strip().lower()

        if size == "small" and ac_count <= 4 and body_words <= 20:
            sizing_scores.append(95)
        elif size == "medium" and ac_count <= 7:
            sizing_scores.append(90)
        elif size == "large":
            # Large stories should be split - always penalized slightly
            sizing_scores.append(50)
        else:
            # Inconsistency: e.g., "small" with 8 ACs
            sizing_scores.append(40)

    sizing = int(sum(sizing_scores) / len(sizing_scores))

    # === EDGE CASE: Scan AC content for edge case language ===
    edge_case_keywords = {
        "invalid", "empty", "fail", "error", "when", "if", "boundary",
        "exceed", "missing", "null", "zero", "negative", "timeout",
        "retry", "duplicate", "conflict", "unauthorized", "forbidden", "not found"
    }

    edge_case_scores = []
    for s in stories:
        ac_list = s.acceptance_criteria
        if not ac_list:
            edge_case_scores.append(0)
            continue

        edge_count = 0
        for criterion in ac_list:
            criterion_lower = criterion.strip().lower()
            if any(kw in criterion_lower for kw in edge_case_keywords):
                edge_count += 1

        ratio = edge_count / len(ac_list)
        if ratio >= 0.33:
            edge_case_scores.append(90)
        elif ratio >= 0.15:
            edge_case_scores.append(65)
        elif ratio > 0:
            edge_case_scores.append(45)
        else:
            edge_case_scores.append(20)

    edge_case = int(sum(edge_case_scores) / len(edge_case_scores))

    overall = int((specificity + testability + sizing + edge_case) / 4)

    return StoryMetrics(
        specificity_score=specificity,
        testability_score=testability,
        sizing_score=sizing,
        edge_case_score=edge_case,
        overall=overall,
    )


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

    # === CLARITY: Length + Detect exact copy-paste (not just title extension) ===
    clarity_scores = []
    for t in tasks:
        desc = t.description.strip()
        title = t.title.strip()
        dod = t.definition_of_done.strip()

        desc_words = desc.split()
        title_words = title.split()

        # Length score
        word_count = len(desc_words)
        if word_count >= 15:
            length_score = 80
        elif word_count >= 8:
            length_score = 55
        else:
            length_score = 20

        # PHASE 3B: Context-aware clarity
        # Only penalize if description is MOSTLY just the title (>85% overlap)
        # Penalty: if description == definition_of_done (exact copy-paste)
        if desc.lower() == dod.lower():
            length_score = 10
        elif title_words and desc_words:
            # Only penalize extreme overlap (95%+ of words from title)
            overlap = len(set(desc_words) & set(title_words)) / max(len(desc_words), 1)
            if overlap > 0.95:  # Changed from 0.7 to 0.95
                length_score = 20

        clarity_scores.append(length_score)

    clarity = int(sum(clarity_scores) / len(clarity_scores))

    # === DEFINITION OF DONE: Keywords + Structure analysis ===
    dod_keywords = {
        "tested", "test", "passing", "reviewed", "deployed", "verified",
        "approved", "merged", "checked", "confirmed", "documented", "coverage"
    }

    # PHASE 3A: Structure patterns (BDD, checklist, etc.)
    structure_patterns = [
        r"given.*when.*then",  # BDD style
        r"\d+\s*[-•]",  # Numbered or bulleted list
        r"✓|✗|☑|☐",  # Checkbox markers
        r"must|should|will",  # Explicit requirements
    ]

    dod_scores = []
    for t in tasks:
        dod = t.definition_of_done.strip().lower()
        desc = t.description.strip()

        # Penalty: if DoD is exact copy of description
        if dod == desc.lower():
            dod_score = 10
        else:
            # Check for verifiable outcome keywords (85 pts)
            has_keywords = any(kw in dod for kw in dod_keywords)

            # Check for structure/formatting (70 pts if present)
            has_structure = any(re.search(pattern, dod, re.IGNORECASE) for pattern in structure_patterns)

            if has_keywords:
                dod_score = 85
            elif has_structure:
                dod_score = 70
            else:
                dod_score = 45

        dod_scores.append(dod_score)

    dod = int(sum(dod_scores) / len(dod_scores))

    # === ESTIMATE: Numeric range validation ===
    estimate_scores = []
    for t in tasks:
        est = t.estimate_hours.strip()

        # Try to parse as "X-Y" format
        m = re.match(r'(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)', est)
        if m:
            try:
                low, high = float(m.group(1)), float(m.group(2))
                # Validate: 0 <= low < high <= 80, range <= 40
                if low >= 0 and high > low and high <= 80 and (high - low) <= 40:
                    estimate_scores.append(95)
                elif high > 80 or (high - low) > 40:
                    # Implausibly wide or out of bounds
                    estimate_scores.append(50)
                elif low > high:
                    # Inverted
                    estimate_scores.append(30)
                else:
                    estimate_scores.append(70)
            except (ValueError, TypeError):
                estimate_scores.append(20)
        else:
            # No valid range found - check if single number
            try:
                float(est)
                estimate_scores.append(60)
            except (ValueError, TypeError):
                estimate_scores.append(20)

    estimate = int(sum(estimate_scores) / len(estimate_scores))

    # === DEPENDENCY: Referential integrity ===
    dependency_scores = []
    for t in tasks:
        deps = t.dependencies or []

        if not deps:
            # No dependencies is fine - leaf tasks are valid
            dependency_scores.append(80)
        else:
            # Check if all dependency IDs exist in the output
            valid_count = sum(1 for dep_id in deps if dep_id in all_task_ids)

            if valid_count == len(deps):
                # All dependencies valid
                dependency_scores.append(95)
            elif valid_count == 0:
                # All dependencies are orphaned
                dependency_scores.append(10)
            else:
                # Some valid, some orphaned
                dependency_scores.append(40)

    dependency = int(sum(dependency_scores) / len(dependency_scores))

    overall = int((clarity + dod + estimate + dependency) / 4)

    return TaskMetrics(
        clarity_score=clarity,
        definition_of_done_score=dod,
        estimate_score=estimate,
        dependency_score=dependency,
        overall=overall,
    )


def compute_metrics(output: GenerationOutput) -> OverallMetrics:
    # Build set of all task IDs for dependency validation
    all_task_ids = {t.id for t in output.tasks}

    story_metrics = score_stories(output)
    task_metrics = score_tasks(output, all_task_ids)

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
        confidence_summary=summary,
    )


def run_validation(metrics: OverallMetrics) -> ValidationResult:
    checks = []
    passed_count = 0

    # PHASE 2A: Adjusted thresholds for better balance
    # Coverage and story/task quality lowered from 80% to 70% for more realistic assessment
    coverage_threshold = 70
    quality_threshold = 70

    # Check 1: Coverage Score >= 70% (was 80%)
    coverage_pass = metrics.coverage_score >= coverage_threshold
    checks.append(ValidationCheck(
        label="Coverage Score",
        passed=coverage_pass,
        value=f"{metrics.coverage_score}%",
        threshold=f"≥ {coverage_threshold}%"
    ))
    if coverage_pass:
        passed_count += 1

    # Check 2: Story Quality >= 70% (was 80%)
    story_pass = metrics.story_metrics.overall >= quality_threshold
    checks.append(ValidationCheck(
        label="Story Quality",
        passed=story_pass,
        value=f"{metrics.story_metrics.overall}%",
        threshold=f"≥ {quality_threshold}%"
    ))
    if story_pass:
        passed_count += 1

    # Check 3: Task Quality >= 70% (was 80%)
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
        recommendation = "⚠ Some quality checks failed. Review flagged gaps before starting work."
    else:
        trust_level = "low"
        recommendation = "✗ Input brief was thin. Answer the gaps listed below and regenerate."

    return ValidationResult(
        trust_level=trust_level,
        checks=checks,
        recommendation=recommendation
    )
