# Accuracy Improvements Roadmap

**Current Baseline: 67% accuracy** (Phase 1)  
**Target: 90%+ accuracy** (Phases 2-5)

---

## Current Baseline (Phase 1)

Test results:
- ✅ Excellent backlog → TRUSTED (correct)
- ⚠️ Medium backlog → LOW (expected REVIEW) ← borderline case
- ✅ Poor backlog → LOW (correct)

**Issue with Test 2:** Medium quality is being scored as LOW because:
- Story quality (56%) is below 80% due to weak ACs
- Task quality (49%) is below 80% due to poor DoD
- Coverage (0%) due to missing epic_id + insufficient tasks
- Input quality (medium) due to 2 important gaps

The metrics are technically correct but very strict. We can improve in several directions.

---

## Phase 2: Calibrate Thresholds (Quick Win) 

**Effort: 2 hours | Accuracy gain: +10% | Risk: Low**

Current thresholds are at the harsh end. We can make them more lenient while keeping rigor:

### Option A: Adjust validation thresholds
```python
# Current (harsh)
coverage >= 80
story_quality >= 80
task_quality >= 80

# Option A (lenient)
coverage >= 70
story_quality >= 70
task_quality >= 70
```

**Impact:** Borderline cases (70-79%) would pass instead of fail
**Trade-off:** Less strict validation; easier to fake
**Recommendation:** Only if user feedback shows false negatives

### Option B: Weight checks by importance
```python
# Current: All 5 checks equally weighted
trust = passed_count / 5

# Option B: Weighted scoring
trust_score = (
    0.25 * coverage_pass +      # Most important - indicates real task coverage
    0.20 * story_quality_pass +  # Important - story definition
    0.20 * task_quality_pass +   # Important - task clarity
    0.20 * gap_count_pass +      # Important - input completeness
    0.15 * input_quality_pass    # Less important - gaps can have minor issues
)
```

**Impact:** Stories could now pass even if input_quality=medium if other 4 checks pass
**Example:** 0.25(✓) + 0.20(✓) + 0.20(✓) + 0.20(✓) + 0.15(✗) = 0.80 → REVIEW instead of LOW

### Option C: Adjust story sizing penalty
```python
# Current: Large stories always score 50 (harsh)
# Option C: Only penalize if ALSO has many ACs
if size == "large":
    if ac_count > 8:
        sizing_score = 40  # Definitely too large
    elif ac_count > 5:
        sizing_score = 60  # Borderline
    else:
        sizing_score = 80  # Large but focused
```

**Impact:** Large stories with few ACs would score higher
**Trade-off:** Less enforcement to split large stories

---

## Phase 3: Improve Clarity & DoD Detection (Medium Effort)

**Effort: 3-4 hours | Accuracy gain: +15% | Risk: Medium**

Current clarity/DoD scoring is strict. We can improve by:

### Option A: Smarter DoD keyword detection
```python
# Current: Must have keyword to score 85
# Option A: Check for verifiable structure
dod_keywords = {"tested", "reviewed", "deployed", ...}
verification_patterns = [
    r"test.*pass",
    r"100.*coverage",
    r"code review",
    r"all.*criteria",
]

# If multiple verification indicators → 85
# If some structure (bullet points, sentences) → 70
# Otherwise → 45
```

**Impact:** Well-structured DoD without magic keywords could score 70-80

### Option B: Context-aware clarity scoring
```python
# Current: Penalizes if 70%+ overlap with title
# Option A: Only penalize if MOSTLY the same
if description.lower() == title.lower():
    clarity = 10  # Exact duplicate
elif overlap > 0.8:
    clarity = 30  # Too similar
elif overlap > 0.6:
    clarity = clarity * 0.8  # Slight penalty
else:
    clarity = clarity  # No penalty
```

**Impact:** Descriptions that extend the title would score higher

### Option C: Task-size-aware estimates
```python
# Current: All estimates 0-80, gap ≤40
# Option C: Validate against parent story size
if parent_story.size == "small":
    max_estimate = 16  # Small story max 2 days
    max_range = 8
elif parent_story.size == "medium":
    max_estimate = 40
    max_range = 20
else:  # large
    max_estimate = 80
    max_range = 40

# Validate against these bounds
```

**Impact:** Tasks too large for their story would be flagged

---

## Phase 4: Add Content Analysis (Higher Effort)

**Effort: 6-8 hours | Accuracy gain: +10-15% | Risk: Medium-High**

Add NLP/regex analysis for deeper content understanding:

### Option A: AC Quality Scoring
```python
# Current: Just checks word count + keywords
# Option A: Analyze structure
def score_ac_quality(criterion):
    score = 0
    
    # Check for Given/When/Then structure (BDD)
    if criterion.lower().startswith(("given ", "when ", "then ")):
        score += 20
    
    # Check for action verbs (should, must, will)
    action_verbs = {"should", "must", "will", "can", "does"}
    if any(v in criterion.lower() for v in action_verbs):
        score += 15
    
    # Check for measurable outcomes
    measurables = {"number", "%", "seconds", "within", "error", "message"}
    if any(m in criterion.lower() for m in measurables):
        score += 15
    
    # Check for negation (edge cases)
    if any(neg in criterion.lower() for neg in ["not ", "invalid", "error", "fail"]):
        score += 15
    
    # Penalize vague language
    vague = {"works", "ok", "good", "fine", "etc", "and so on"}
    if any(v in criterion.lower() for v in vague):
        score -= 20
    
    return min(100, max(0, score))

# Testability = avg AC quality instead of just keyword presence
```

**Impact:** Better AC evaluation; "should" alone isn't enough

### Option B: Estimate Realism Scoring
```python
# Current: Just validates numeric format
# Option A: Check if estimate matches typical sprint velocity
def is_realistic_estimate(estimate_hours, story_size, task_complexity):
    low, high = parse_range(estimate_hours)
    
    typical_ranges = {
        ("small", "simple"): (2, 4),
        ("small", "complex"): (4, 8),
        ("medium", "simple"): (4, 8),
        ("medium", "complex"): (8, 16),
        ("large", "simple"): (8, 20),
        ("large", "complex"): (20, 40),
    }
    
    min_exp, max_exp = typical_ranges.get((story_size, task_complexity), (2, 40))
    
    if low >= min_exp and high <= max_exp:
        return 95
    elif (low + high) / 2 <= 60:  # Still reasonable
        return 70
    else:
        return 40
```

**Impact:** Estimates validated against story context

### Option C: Gap Severity Analysis
```python
# Current: Just checks severity label
# Option A: Analyze gap description content
def analyze_gap_severity(description):
    # If gap talks about core functionality → should be blocking
    core_keywords = {"payment", "auth", "security", "data loss", "legal"}
    if any(k in description.lower() for k in core_keywords):
        return "blocking"  # Upgrade severity
    
    # If gap is vague → downgrade
    if len(description.split()) < 5:
        return "minor"  # Too vague to be important
    
    # If gap has clear solution → downgrade
    if "?" not in description:
        return "minor"  # Probably not a gap
    
    return original_severity
```

**Impact:** Better gap assessment; reduce false "important" gaps

---

## Phase 5: Machine Learning Calibration (Advanced)

**Effort: 12+ hours | Accuracy gain: +10-20% | Risk: High**

Use historical data to train metric weights:

### Option A: Feedback Loop
```
1. Generate backlog with current metrics
2. Track which ones were actually successful (used in production)
3. Use successful vs. unsuccessful outputs to adjust thresholds
4. Re-calibrate weights: which metrics best predicted success?
```

### Option B: Ensemble Scoring
```python
# Instead of equal weighting, ensemble multiple scorers
scores = {
    "rule_based": score_with_current_metrics(),
    "keyword_density": score_by_keyword_coverage(),
    "structure_based": score_by_document_structure(),
    "consistency_based": score_by_field_coherence(),
}

# Weight by past accuracy
final_score = (
    0.4 * scores["rule_based"] +
    0.2 * scores["keyword_density"] +
    0.2 * scores["structure_based"] +
    0.2 * scores["consistency_based"]
)
```

### Option C: User Feedback Training
```
When user marks an output as:
- "This looks good" → log metrics as positive example
- "This needs rework" → log metrics as negative example

Use these to adjust thresholds over time
```

---

## Recommended Path (Quick to Solid)

### Week 1: Phase 2A + 2B (Quick wins)
```python
# Adjust thresholds + weight checks
# Expected: 67% → 75% accuracy
# Effort: 2 hours
```

### Week 2: Phase 3A + 3B (Improve detection)
```python
# Smarter DoD + Context-aware clarity
# Expected: 75% → 82% accuracy  
# Effort: 3-4 hours
```

### Week 3: Phase 4A (Content analysis)
```python
# Better AC quality scoring
# Expected: 82% → 88% accuracy
# Effort: 4-5 hours
```

### Week 4: Phase 5A (Feedback loop)
```python
# Track actual usage, calibrate
# Expected: 88% → 92%+ accuracy
# Effort: Ongoing
```

---

## Quick Reference: What to Improve First

| Issue | Phase | Effort | Gain |
|-------|-------|--------|------|
| Borderline cases (70-79%) getting LOW | 2A | 30m | +10% |
| DoD scoring too strict | 3A | 1h | +8% |
| Unclear what makes good AC | 4A | 2h | +10% |
| Estimates disconnected from story size | 3C | 1.5h | +5% |
| Gap severity not analyzed | 4C | 1h | +5% |

---

## Testing Each Improvement

```python
# After each improvement, run:
test_excellent()     # Should stay TRUSTED
test_medium()        # Should move toward REVIEW
test_poor()          # Should stay LOW

# Track: accuracy_before vs accuracy_after
```

---

## Decision Tree: Which Phases to Implement

**If user wants 70-75% accuracy:**  
→ Just use Phase 1 (current)

**If user wants 80% accuracy:**  
→ Add Phase 2A (threshold adjustment)

**If user wants 85% accuracy:**  
→ Add Phase 2A + 3A + 3B

**If user wants 90%+ accuracy:**  
→ Add Phase 2A + 3A + 3B + 4A + 4C

**If user wants 95%+ accuracy:**  
→ Add Phase 2A + 3A + 3B + 4A + 4B + 4C + 5A

---

## Summary Table

| Phase | What | Effort | Accuracy Impact | Risk | Recommendation |
|-------|------|--------|-----------------|------|-----------------|
| 1 (Current) | Baseline metrics | Done | 67% | N/A | ✓ Use now |
| 2A | Adjust thresholds | 30m | +8% | Low | ✓ Do next |
| 2B | Weight checks | 30m | +2% | Low | ✓ With 2A |
| 3A | Better DoD | 1h | +8% | Medium | ✓ After 2A |
| 3B | Context-aware clarity | 1h | +5% | Low | ✓ With 3A |
| 3C | Story-aware estimates | 1.5h | +5% | Low | ✓ After 3A |
| 4A | AC quality analysis | 2h | +10% | Medium | ⚠️ If ambitious |
| 4B | Estimate realism | 2h | +8% | Medium | ⚠️ If ambitious |
| 4C | Gap analysis | 1h | +5% | Medium | ⚠️ If ambitious |
| 5A | Feedback loop | Ongoing | +5-10% | High | 📊 Long-term |

**Fast path to 82%:** Phase 1 + 2A + 2B + 3A (2.5 hours)  
**Fast path to 88%:** Phase 1-4A (5 hours)  
**Premium path to 92%:** Phase 1-5A (8+ hours)
