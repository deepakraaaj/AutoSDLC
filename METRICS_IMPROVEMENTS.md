# Improved Metrics — Explicit Quality Scoring

The metrics have been redesigned to measure **real content quality** instead of surface features like word count or the presence of hyphens. All metrics are now **explicit, auditable, and hard to game**.

---

## Before vs. After

### Story Quality

| Metric | Before | After |
|--------|--------|-------|
| **Specificity** | 2-word actor check + tiny blocklist | Actor detail + 8+ word intent + 6+ word rationale |
| **Testability** | Count ACs only | Count ACs + check each AC has 6+ words + quality keywords |
| **Sizing** | Pure label check | Cross-validate size vs. AC count + body length |
| **Edge Cases** | Use confidence as proxy (indirect) | Scan AC content for edge case keywords (direct) |

### Task Quality

| Metric | Before | After |
|--------|--------|-------|
| **Clarity** | Word count only | Word count + detect copy-paste from title/DoD |
| **DoD** | Word count only | Check for verifiable outcome keywords (tested, deployed, etc.) |
| **Estimate** | Hyphen presence | Parse numeric range, validate bounds (0-80 hrs, sensible gap) |
| **Dependency** | Backwards (has deps scores higher) | Validate task IDs actually exist in output |

### Coverage & Input Quality

| Metric | Before | After |
|--------|--------|-------|
| **Coverage** | Any-1-task-linked + 2 ACs + not-low confidence | **2+ tasks + all ACs 5+ words + epic assigned + not low conf** |
| **Input Quality** | Doesn't distinguish blocking/important gaps | Blocking=low, 3+ important=medium, else high |

---

## Examples: What Now Scores Higher vs. Lower

### Story Specificity

❌ **Low Score (30):**
```
As a: "user"
I want: "login"
So that: "access"
```

✅ **High Score (90+):**
```
As a: "new customer with existing account"
I want: "securely authenticate with email and password to access my personalized dashboard"
So that: "I can manage my orders, preferences, and payment methods without sharing credentials with other users"
```

---

### Story Testability

❌ **Low Score (30):**
```
Acceptance Criteria:
  - "works"
  - "ok"
  - "done"
```

✅ **High Score (90+):**
```
Acceptance Criteria:
  - "should reject invalid email format with specific error message"
  - "should enforce minimum 8 character password with special characters"
  - "should invalidate user session when logout button is clicked"
  - "should lock account after 5 failed login attempts within 60 minutes"
  - "should display error if password hash does not match stored hash"
```

---

### Task Clarity

❌ **Low Score (10):**
```
Title: "Login"
Description: "Login"  ← Exact copy of title
```

❌ **Medium Score (20):**
```
Description: "Implement login."  ← Too short, vague
```

✅ **High Score (80+):**
```
Description: "Implement password hashing using bcrypt library with cost factor 12. Validate password strength 
before hashing: minimum 8 chars, at least one uppercase, one number, one special character. Return specific 
error message for each validation failure."
```

---

### Task Definition of Done

❌ **Low Score (45):**
```
"Done when code is written"
```

❌ **Medium Score (10):**
```
"Do the thing"  ← Copy of description, no keywords
```

✅ **High Score (85+):**
```
"Unit tests pass with 95%+ coverage, code reviewed by security team, all acceptance criteria verified 
in staging environment, documentation updated, monitoring alerts configured"
```

---

### Task Estimate

❌ **Low Score (20):**
```
"blah"  ← Non-numeric
"a few hours"  ← Not parseable
```

❌ **Medium Score (50):**
```
"1-100"  ← Unrealistic range (>40 hour gap)
"0-200"  ← Out of bounds (>80 total)
```

✅ **High Score (95):**
```
"6-8"     ← Valid, reasonable range
"10-12"   ← Valid, well-scoped
"4-6"     ← Valid, small task
```

---

### Task Dependencies

❌ **Low Score (10):**
```
dependencies: ["T999", "T888"]  ← All IDs don't exist
```

❌ **Medium Score (40):**
```
dependencies: ["T1", "T999"]  ← Some IDs don't exist (orphaned)
```

✅ **High Score (95):**
```
dependencies: ["T1", "T2"]  ← All IDs exist in output
```

✅ **High Score (80):**
```
dependencies: []  ← No dependencies is fine (leaf task)
```

---

### Coverage

❌ **Low Score (0%):**
```
Story S1:
  - epic_id: null  ← Not assigned to epic
  - tasks: 1  ← Only 1 task (need ≥2)
```

❌ **Medium Score (50%):**
```
2 stories, only 1 is well-covered because other has:
  - epic_id: null, OR
  - only 1 task, OR
  - ACs with <5 words
```

✅ **High Score (100%):**
```
All stories:
  - assigned to an epic (epic_id set)
  - linked to ≥2 substantive tasks (each task not orphaned)
  - all ACs are 5+ words
  - confidence != "low"
```

---

## Edge Case Detection (New!)

The edge case score now **actually scans AC content** for risk language:

**Edge case keywords:** invalid, empty, fail, error, when, if, boundary, exceed, missing, null, zero, negative, timeout, retry, duplicate, conflict, unauthorized, forbidden, not found

✅ **High Score (90):**
```
"when user enters password >40 characters, should truncate to 40 characters"
"if payment gateway timeout exceeds 30 seconds, should retry with exponential backoff"
"when user is not authenticated, should redirect to login page"
```

❌ **Low Score (20):**
```
"user can login"  ← No edge case language
"submit form works"  ← No failure conditions
```

---

## Key Changes to `metrics.py`

### 1. Imports
Added `import re` for numeric parsing of estimates.

### 2. `score_stories()` rewritten
- **Specificity:** 3 sub-scores (actor blocklist, intent substance, rationale substance)
- **Testability:** Count + content quality (keywords, word length)
- **Sizing:** Cross-validate size label vs. AC count and story body length
- **Edge Cases:** Scan ACs for edge case keywords instead of using confidence proxy

### 3. `score_tasks()` signature changed
```python
def score_tasks(output: GenerationOutput, all_task_ids: set[str]) -> TaskMetrics:
```
Now receives `all_task_ids` for dependency validation.

- **Clarity:** Word count + detect copy-paste from title + detect copy-paste from DoD
- **DoD:** Check for verifiable outcome keywords (tested, reviewed, deployed, etc.)
- **Estimate:** Parse numbers, validate bounds, check range plausibility
- **Dependency:** Validate all dependency IDs exist in output

### 4. `compute_metrics()` rewritten
- Builds `all_task_ids` set and passes to `score_tasks()`
- **Coverage:** Stricter rules (≥2 tasks, 5+ word ACs, epic assigned, not low confidence)
- **Input Quality:** Distinguishes blocking (low) vs. important (medium) gaps

---

## Validation Thresholds (unchanged)

The 5 validation checks still use the same thresholds:

| Check | Threshold | Meaning |
|-------|-----------|---------|
| Coverage Score | ≥ 80% | 80% of stories fully covered with tasks & ACs |
| Story Quality | ≥ 80% | Stories are detailed, testable, well-sized, edge-case-aware |
| Task Quality | ≥ 80% | Tasks are clear, verifiable, realistically estimated, properly sequenced |
| Gap Count | ≤ 3 | Input brief was fairly complete |
| Input Quality | = high | No blocking gaps, max 2 important gaps |

**Trust Levels:**
- **5/5 checks** → **TRUSTED** (✓ ready to use)
- **3-4 checks** → **REVIEW** (⚠ needs attention)
- **<3 checks** → **LOW CONFIDENCE** (✗ regenerate)

---

## Why These Changes Matter

### 1. **Substance over surface**
- Old: 3 single-word ACs scored 95. New: 3 ACs must each be 6+ words + contain quality keywords.
- Old: "login" as i_want scored 90. New: Must be 8+ words with clear action.

### 2. **Cross-field validation**
- Old: Size label checked alone. New: "medium" size must have ≤7 ACs (not 10+).
- Old: Estimate checked for hyphen. New: Must be numeric, 0-80 hrs, sensible gap.

### 3. **Referential integrity**
- Old: Task with dependency ["T999"] scored 90 (has deps). New: Scores 10 (ID doesn't exist).

### 4. **Anti-copy-paste**
- Old: Task with desc=title scored 90 (≥20 words). New: Scores 10 (copy-paste detected).
- Old: DoD=description scored 90 (≥10 words). New: Scores 10 (exact copy).

### 5. **Real edge case coverage**
- Old: Set confidence="high" → edge_case=85 (no actual edge cases checked). 
- New: Must have 1-in-3 ACs with edge case language (invalid, error, when X fails, etc.).

---

## Testing the Metrics

Run these tests to verify the improvements:

```bash
cd story-generator

# Test 1: Verify low scores for low-quality content
python3 << 'EOF'
from metrics import compute_metrics
from schemas import GenerationOutput, Story, Task, Gap

output = GenerationOutput(
    needs_clarification=False,
    clarifying_questions=[],
    epics=[],
    stories=[Story(id="S1", title="User", as_a="user", i_want="login",
                   so_that="access", acceptance_criteria=["ok"],
                   feature_area="Auth", size="small", confidence="high")],
    tasks=[],
    gaps=[Gap(description="Design?", severity="blocking")]
)
metrics = compute_metrics(output)
assert metrics.story_metrics.overall < 50, "Low-quality story should score <50"
assert metrics.input_quality == "low", "Blocking gap should make input low"
print("✓ Low-quality output correctly scored low")
EOF

# Test 2: Verify high scores for substantive content
python3 << 'EOF'
from metrics import compute_metrics
from schemas import GenerationOutput, Story, Task, Epic

output = GenerationOutput(
    needs_clarification=False,
    clarifying_questions=[],
    epics=[Epic(id="E1", title="Auth", description="Auth", feature_area="Auth", priority="high")],
    stories=[Story(
        id="S1", title="Login", as_a="registered customer",
        i_want="securely log in with email and encrypted password to my account",
        so_that="I can access my orders and payment methods without exposing credentials",
        acceptance_criteria=[
            "should validate email format and reject invalid emails with error message",
            "should enforce minimum 8 char password with uppercase, number, special char",
            "should lock account after 5 failed attempts within 1 hour",
            "should redirect to dashboard when authentication succeeds"
        ],
        feature_area="Auth", size="medium", confidence="high", epic_id="E1"
    )],
    tasks=[
        Task(id="T1", title="Validation", story_id="S1", description="Implement validation logic for email format, password strength, and account lockout with proper error messages and logging.",
             definition_of_done="unit tests pass, code reviewed, documented, deployed to staging",
             estimate_hours="6-8", dependencies=[], confidence="high"),
        Task(id="T2", title="Integration", story_id="S1", description="Integrate email service and database for account lockout tracking and notification.",
             definition_of_done="integration tests pass, security review completed, monitoring alerts configured",
             estimate_hours="4-6", dependencies=["T1"], confidence="high")
    ],
    gaps=[]
)
metrics = compute_metrics(output)
assert metrics.story_metrics.overall >= 80, f"High-quality story should score ≥80, got {metrics.story_metrics.overall}"
assert metrics.task_metrics.overall >= 80, f"High-quality tasks should score ≥80, got {metrics.task_metrics.overall}"
assert metrics.coverage_score == 100, f"Full coverage should be 100%, got {metrics.coverage_score}"
print("✓ High-quality output correctly scored high")
EOF
```

---

## Summary

The metrics have been fundamentally rewritten to measure **what matters**: substantive story requirements, realistic task estimates, and referential integrity. The scoring is now **explicit** (you can see exactly why something scored what it did) and **hard to game** (surface features like word count are just one small part of a multi-faceted scoring system).
