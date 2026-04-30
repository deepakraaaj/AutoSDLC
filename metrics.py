from schemas import GenerationOutput, OverallMetrics, StoryMetrics, TaskMetrics


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

    generic_actors = {"user", "the user", "a user", "users", "customer", "person"}

    specificity_scores = []
    for s in stories:
        actor = s.as_a.strip().lower()
        is_specific = actor not in generic_actors and len(actor.split()) >= 2
        specificity_scores.append(90 if is_specific else 40)
    specificity = int(sum(specificity_scores) / len(specificity_scores))

    testability_scores = []
    for s in stories:
        ac_count = len(s.acceptance_criteria)
        if ac_count >= 3:
            testability_scores.append(95)
        elif ac_count == 2:
            testability_scores.append(80)
        elif ac_count == 1:
            testability_scores.append(55)
        else:
            testability_scores.append(10)
    testability = int(sum(testability_scores) / len(testability_scores))

    sizing_scores = []
    for s in stories:
        if s.size in ("small", "medium"):
            sizing_scores.append(95)
        else:
            sizing_scores.append(60)
    sizing = int(sum(sizing_scores) / len(sizing_scores))

    # Edge case proxy: low-confidence stories suggest edge cases weren't fully thought through
    edge_case_scores = []
    for s in stories:
        if s.confidence == "high":
            edge_case_scores.append(85)
        elif s.confidence == "medium":
            edge_case_scores.append(65)
        else:
            edge_case_scores.append(40)
    edge_case = int(sum(edge_case_scores) / len(edge_case_scores))

    overall = int((specificity + testability + sizing + edge_case) / 4)

    return StoryMetrics(
        specificity_score=specificity,
        testability_score=testability,
        sizing_score=sizing,
        edge_case_score=edge_case,
        overall=overall,
    )


def score_tasks(output: GenerationOutput) -> TaskMetrics:
    tasks = output.tasks
    if not tasks:
        return TaskMetrics(
            clarity_score=0,
            definition_of_done_score=0,
            estimate_score=0,
            dependency_score=0,
            overall=0,
        )

    clarity_scores = []
    for t in tasks:
        word_count = len(t.description.split())
        if word_count >= 20:
            clarity_scores.append(90)
        elif word_count >= 10:
            clarity_scores.append(70)
        else:
            clarity_scores.append(40)
    clarity = int(sum(clarity_scores) / len(clarity_scores))

    dod_scores = []
    for t in tasks:
        word_count = len(t.definition_of_done.split())
        if word_count >= 10:
            dod_scores.append(90)
        elif word_count >= 5:
            dod_scores.append(65)
        else:
            dod_scores.append(30)
    dod = int(sum(dod_scores) / len(dod_scores))

    estimate_scores = []
    for t in tasks:
        est = t.estimate_hours.strip()
        has_range = "-" in est or "–" in est
        estimate_scores.append(95 if has_range else 70)
    estimate = int(sum(estimate_scores) / len(estimate_scores))

    dependency_scores = []
    for t in tasks:
        if t.dependencies:
            dependency_scores.append(90)
        else:
            dependency_scores.append(70)
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
    story_metrics = score_stories(output)
    task_metrics = score_tasks(output)

    # Coverage: % of stories that are fully formed (have AC, linked tasks, not low confidence)
    stories = output.stories
    tasks = output.tasks
    linked_story_ids = {t.story_id for t in tasks if t.story_id}
    well_covered = sum(
        1 for s in stories
        if len(s.acceptance_criteria) >= 2
        and s.confidence != "low"
        and s.id in linked_story_ids
    )
    coverage_score = int((well_covered / len(stories)) * 100) if stories else 0

    blocking_gaps = sum(1 for g in output.gaps if g.severity == "blocking")
    if blocking_gaps > 0:
        input_quality = "low"
    elif len(output.gaps) > 3:
        input_quality = "medium"
    else:
        input_quality = "high"

    avg = int((story_metrics.overall + task_metrics.overall) / 2)
    if avg >= 80:
        summary = f"High confidence — {len(stories)} stories and {len(tasks)} tasks generated. {coverage_score}% of stories are fully covered with tasks and acceptance criteria."
    elif avg >= 60:
        summary = f"Medium confidence — some assumptions were made. Review {len(output.gaps)} gap(s) before starting work."
    else:
        summary = f"Low confidence — input was thin. Recommend answering the gaps and regenerating. {len(output.gaps)} gap(s) flagged."

    return OverallMetrics(
        coverage_score=coverage_score,
        gap_count=len(output.gaps),
        input_quality=input_quality,
        story_metrics=story_metrics,
        task_metrics=task_metrics,
        confidence_summary=summary,
    )
