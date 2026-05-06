# Project Goal: Story & Task Generator

## What this system does

You either:
- **Upload a markdown file** describing an existing project, OR
- **Chat to describe a new project**

And the system gives you back **the best possible** user stories and tasks — good enough that a developer can pick one up and start working immediately, with no back-and-forth.

---

## The most important thing: quality

This system lives or dies on the quality of its output. Generic, vague stories and tasks are useless. The bar is:

**A developer reads a task and knows exactly what to build, how much time it takes, and what done looks like. No guessing.**

### What makes a story great

- Names the **specific type of user** — not just "user" but "first-time buyer", "admin", "guest user who hasn't registered"
- States a **clear, real benefit** — not "so that I can use the feature" but "so that I don't lose my cart if I close the tab"
- Has **acceptance criteria that are testable** — you can look at the running software and say yes or no
- Is **the right size** — one story = one meaningful thing a user can do, not ten things bundled together
- Covers **edge cases** that matter — what happens if the input is wrong, the network drops, the user is on mobile

### What makes a task great

- **Specific enough to start without asking anyone** — no ambiguity about what to build
- Has a **clear definition of done** — "endpoint returns 200 with token" not "build the endpoint"
- Lists **dependencies** — what needs to exist before this task can start
- Has a **realistic time estimate** — not just "small/medium/large" but actual hours or days
- Is **one thing** — if a task has "and" in it, it probably needs splitting

### What separates this from a basic AI output

Most AI tools give you generic, safe, shallow stories. This system should do better by:

1. **Asking smart follow-up questions** before generating — if you say "build a login system", it asks: social login or email/password? What happens on failed attempts? Is there a "remember me"? Mobile or web?
2. **Thinking about who the real users are** — not just "the user" but the different types of people using the system with different needs
3. **Spotting gaps** — things you didn't mention but will definitely need (e.g. you described signup but forgot password reset)
4. **Breaking tasks to the right level** — not too big (a week of work), not too small (30 minutes of trivial work)
5. **Ordering tasks sensibly** — dependencies first, so the team can start immediately without blockers

---

## How it works (from the user's point of view)

### Option A — Existing project
1. You upload a `.md` file describing your project
2. System reads it and asks 2–3 clarifying questions if anything is unclear
3. You answer (or skip)
4. You get back stories and tasks

### Option B — New project
1. You open a chat and describe your project in plain language
2. System asks smart follow-up questions to fill in the gaps
3. Once it has enough, it generates stories and tasks
4. You can ask it to adjust, split, or add more

---

## What a great user story looks like

> **As a** first-time buyer who hasn't created an account,  
> **I want to** check out as a guest without registering,  
> **So that** I can complete my purchase quickly without committing to an account.
>
> **Acceptance criteria:**
> - Guest can complete the full checkout flow without entering a password
> - Guest receives an order confirmation email
> - At the end of checkout, guest is offered (not forced) to create an account
> - If guest enters an email that already has an account, they are prompted to log in instead
> - Guest order history is not visible after the session ends

---

## What a great task looks like

> **Task:** Guest checkout — order confirmation email  
> **What to build:** When a guest completes checkout, send a transactional email to their entered address containing order number, itemised list, total, and estimated delivery date. No account link in the email.  
> **Definition of done:** Guest receives email within 60 seconds of order confirmation. Email renders correctly on mobile and desktop. Order number in email matches order in database.  
> **Estimate:** 4–6 hours  
> **Dependencies:** Email service (SendGrid/SES) must be configured. Order creation endpoint must exist.  
> **Does not include:** Account creation prompt (separate task)

---

## Metrics — how you know the output is good

The system shows a quality scorecard alongside every output so you don't have to guess whether to trust it.

### Story quality metrics
| Metric | What it checks |
|---|---|
| Completeness | Did it cover all features mentioned in the input? |
| Specificity | Are user types named specifically, not just "user"? |
| Testability | Does every story have acceptance criteria you can verify? |
| Right-sized | No stories that are too large (epic) or too trivial |
| Edge cases | Did it think beyond the happy path? |

### Task quality metrics
| Metric | What it checks |
|---|---|
| Clarity | Can a developer start without asking questions? |
| Definition of done | Is "done" clearly stated for every task? |
| Estimates | Does every task have a time estimate? |
| No bloat | Are tasks single-responsibility, not bundled? |
| Dependencies | Are blockers called out before they surprise someone? |

### Overall output metrics
| Metric | What it means |
|---|---|
| Coverage score | % of input requirements turned into stories |
| Gap count | How many missing requirements were caught |
| Confidence | How confident the system is in each story/task (high/medium/low) |
| Input quality | How clear the input was — low score means you should add more detail |

Each story and task gets a **confidence indicator** — if the system is guessing, it tells you. You only trust what's marked high confidence, and you review the rest.

---

## What success looks like

- A developer reads the output and can start working the same day
- A product manager reads the stories and says "yes, that's exactly what I meant"
- No obvious gaps — the system caught things you forgot to mention
- Stories and tasks are the right size — not too big, not too small
- Metrics scorecard shows 80%+ on all quality dimensions
- Output in under 60 seconds

---

## What this system does NOT do

- It does not write code
- It does not push to Redmine, Jira, or any other tool (yet)
- It does not manage who does what
- It does not track progress

For now, the only job is: **input → the best possible stories + tasks.**

---

## Inputs accepted

| Input type | Format | Example |
|---|---|---|
| Existing project description | Markdown file (.md) | Project README, feature brief, spec doc |
| New project description | Plain chat | "I want to build a food delivery app for small restaurants" |

---

## Output format

1. **Clarifying questions** (if needed, before generating) — 2–5 short questions, skippable
2. **User stories** — grouped by feature area, with acceptance criteria
3. **Tasks** — one task per developer action, with definition of done and estimates
4. **Gaps flagged** — things mentioned but not fully defined, or things missing entirely

---

## Scope for first version

- Web page: file upload box + chat text area + Generate button
- Smart clarifying questions before output
- Stories and tasks displayed on screen, copyable
- No login required
- Stateless — each session is fresh

---

## AI provider

The system is **not locked to one AI**. You can switch between:

| Provider | Good for |
|---|---|
| **Groq** | Fast and cheap — good for quick iterations during development |
| **Gemini Flash** (Google) | Fast, capable, good at structured output |
| **Self-hosted** (Ollama etc.) | Full privacy, no data leaves your machine |

Provider is set in a config file — one line change to switch. The prompt and output format stay the same regardless of which AI is running underneath.

---

## What to build

1. **Web page** — file upload, chat input, Generate button, output display with metrics scorecard
2. **Backend** — receives input, asks clarifying questions if needed, calls the configured AI with a high-quality prompt, returns structured output + quality scores
3. **Provider config** — simple config to switch between Groq, Gemini Flash, or self-hosted with no code changes
4. **The prompt** — this is the most important piece. It must produce expert-level stories and tasks, not generic ones. Will need iteration and testing against real project inputs.

---

## Timeline

- **Day 1:** Core backend — take input, call Claude, return stories and tasks
- **Day 2:** Clarifying questions flow — system asks before generating if input is thin
- **Day 3:** Web UI — upload, chat, output display
- **Day 4:** Prompt refinement — test against 5–10 real project descriptions, improve until output is genuinely great
- **Day 5:** Edge cases and polish

Total: ~1 week for a working first version.

---

## The prompt is the product

The AI prompt that generates stories and tasks is not a detail — it is the core of this system. A bad prompt gives you generic output that wastes everyone's time. A great prompt gives you output that a senior product manager would be proud of.

Prompt must:
- Understand software project context deeply
- Know what a well-formed story looks like vs a vague one
- Know what a well-scoped task looks like vs one that's too big or too small
- Spot missing requirements and flag them
- Ask the right clarifying questions when input is ambiguous
- Never produce filler — every story and task must earn its place
