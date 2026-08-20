# Free LLM API Field Notes

Rate limits for eight free LLM APIs, read from the providers' own response headers rather than
from blog roundups — plus the LiteLLM pattern for running all of them behind one call site with
automatic failover.

- **Probed:** 2026-08-20
- **Reference workload:** ~27 calls / ~190K tokens per run (a multi-phase generation pipeline)
- **Free tiers rot fast** — re-probe before trusting any number here

Rows marked **`probed`** were verified with a live request on a real key.
Rows marked **`docs`** come from provider documentation and were *not* independently verified.

---

## The short version

| Rank | Platform | Why |
|---|---|---|
| **Use this** | **Mistral** | ~1B tokens/month on the free Experiment tier. Per-model limits, best of them 50 req/min & 50K tok/min. No card — phone verification only. |
| **Best backup** | **Google Gemini** | 500–1,500 req/day and 250K tok/min on Flash Lite. Highest request ceiling here, no card. |
| **Breadth, not volume** | **OpenRouter** | 400+ models behind one key, but only 50 req/day on `:free` models. Good for A/B testing models, poor as a primary. |
| **Gone** | ~~Cerebras~~ | Free tier ended 2026-08-17. Keys now return `402 payment_required`. Replaced by $5 one-time credits behind a card. |

---

## Platform landscape

| Platform | Free tier | Card? | Source | Watch out for |
|---|---|---|---|---|
| **Mistral** | ~1B tok/mo | No | `probed` | Limits are **per model**, not per account. Roundups claiming "2 req/min" are wrong. |
| **Google Gemini** | 500–1,500 req/day | No | `probed` | Flash *Lite* gets ~25× the daily requests of full Flash on the same key. Pick Lite deliberately. |
| **OpenRouter** | 50 req/day | No | `probed` | Rises to 1,000/day after $10 lifetime credits. Only `:free` model ids work on a $0 balance. |
| **Groq** | 1,000 req/day · 8K tok/min | No | `probed` | Fast per token, but 8K tok/min throttles any prompt with a large context. Request count is not the binding limit. |
| **HuggingFace** | 100K credits/mo | No | `docs` | Router works, but the free grant is small. PRO ($9/mo) raises it to 2M. |
| **NVIDIA NIM** | 1,000 credits once | No | `docs` | One-time grant, not a recurring tier. +4,000 with a business email. 40 req/min. |
| **Cloudflare Workers AI** | 10K neurons/day | No | `docs` | Roughly 15–25 Llama 8B calls/day. Edge deployment is the real selling point. |
| **SambaNova** | $5, expires 90d | Yes | `docs` | A trial, not a free tier. |
| ~~**Cerebras**~~ | — | Yes | `probed` | Free tier ended **2026-08-17**. Live key returns `402 payment_required`. Articles still advertising "1M tokens/day" are stale. |

---

## Mistral limits are per model

The finding most worth carrying forward. Two models on the same key differ by **47×** in requests
per minute. Picking the biggest model quietly caps throughput at 4 req/min — fatal for any pipeline
that makes dozens of calls.

| Model | req/min | tok/min | Verdict |
|---|---:|---:|---|
| `ministral-8b-latest` | 188 | 625,000 | Highest throughput on the tier. |
| `open-mistral-nemo` | 188 | 625,000 | Same ceiling, older model. |
| `codestral-latest` | 125 | 625,000 | Huge headroom; code-tuned, so weaker on prose. |
| **`mistral-small-latest`** | **50** | **50,000** | **Best quality-per-limit balance. General purpose.** |
| `devstral-latest` | 50 | 1,000,000 | Largest token budget of any model here. |
| `mistral-medium-latest` | 50 | 25,000 | Token-starved relative to small. |
| `magistral-medium-latest` | 50 | 25,000 | Reasoning variant, same token cap. |
| `mistral-large-latest` | **4** | 250,000 | ⚠️ Unusable for multi-call pipelines. |
| ~~`zai-glm-5-2`~~ | — | — | ❌ `403` — listed by `/v1/models` but blocked: "not available in your subscription tier". |

All read from `x-ratelimit-*` response headers, one 1-token call per model.

---

## Reliability beats leaderboard rank

Seventeen OpenRouter `:free` models, one identical structured-JSON prompt.
**Only 7 returned parseable JSON.** The failures included the highest-ranked open-weights model
available — which is why a benchmark on your own prompt beats any published index.

| Outcome | Count | Notable cases |
|---|---:|---|
| ✅ valid JSON | 7 / 17 | Fastest `poolside/laguna-s-2.1:free` at 17.9s; slowest usable `cohere/north-mini-code:free` at 87.1s. |
| ❌ malformed JSON | 5 / 17 | Included a **550B** model. Parameter count did not predict format compliance. |
| ❌ provider error | 4 / 17 | Top-ranked open-weights model 429'd on both attempts, hours apart — its free tier has only one upstream host. |
| ⚠️ empty content | 1 / 17 | Reasoning model burned tokens on `reasoning_tokens` and returned an empty `content` field. |

For contrast, **all 8 Mistral models tested returned valid schema**, in 5.3–12.6s versus
OpenRouter's 17.9–87.1s.

---

## The LiteLLM pattern

One call site, any provider, automatic retry and cross-provider failover. LiteLLM reads
`<PROVIDER>_API_KEY` from the environment on its own — you never pass keys explicitly.
Swapping providers becomes a string change.

### Registry + call site

```python
# pip install litellm tenacity
#   tenacity is NOT a declared litellm dependency, but its retry path
#   imports it lazily whenever num_retries= is passed. Without it every
#   call dies with "tenacity import failed".
import os, litellm

PROVIDERS = {
    "mistral":    {"prefix": "mistral",    "key": "MISTRAL_API_KEY",    "model": "mistral-small-latest"},
    "gemini":     {"prefix": "gemini",     "key": "GEMINI_API_KEY",     "model": "gemini-3.5-flash-lite"},
    "openrouter": {"prefix": "openrouter", "key": "OPENROUTER_API_KEY", "model": "nvidia/nemotron-3-super-120b-a12b:free"},
    "groq":       {"prefix": "groq",       "key": "GROQ_API_KEY",       "model": "openai/gpt-oss-120b"},
}
# Order by real free capacity, not by model quality.
FALLBACK_ORDER = ["mistral", "gemini", "openrouter", "groq"]


def configured(pid):
    return bool(os.getenv(PROVIDERS[pid]["key"], "").strip())


def model_string(pid):
    m = PROVIDERS[pid]
    # "mistral/mistral-small-latest" — prefix tells litellm which API to hit
    return f"{m['prefix']}/{os.getenv(m['key'].replace('API_KEY', 'MODEL'), m['model'])}"


def complete(system, user, active="mistral"):
    resp = litellm.completion(
        model=model_string(active),
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        temperature=0.3, max_tokens=8000, timeout=120,
        num_retries=3,                       # exponential backoff on 429/5xx
        fallbacks=[model_string(p) for p in FALLBACK_ORDER
                   if p != active and configured(p)] or None,
    )
    # resp.model reveals who ACTUALLY served it — may not be `active`
    # if litellm fell through to a fallback. Attribute usage accordingly.
    served = getattr(resp, "model", "")
    cost   = (getattr(resp, "_hidden_params", {}) or {}).get("response_cost") or 0.0
    return resp.choices[0].message.content, served, cost
```

### Always strip fences before parsing

```python
import json, re


def parse_json_array(raw):
    """Models wrap JSON in ```json fences even when told not to."""
    t = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    t = re.sub(r"\s*```$", "", t)
    i, j = t.find("["), t.rfind("]")          # salvage from surrounding prose
    if i != -1 and j > i:
        t = t[i:j + 1]
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        return []
```

### Re-probe the limits yourself

```bash
# Mistral — per-model limits live in the response headers
curl -sD- -o/dev/null https://api.mistral.ai/v1/chat/completions \
  -H "Authorization: Bearer $MISTRAL_API_KEY" -H 'Content-Type: application/json' \
  -d '{"model":"mistral-small-latest","messages":[{"role":"user","content":"hi"}],"max_tokens":1}' \
  | grep -i ratelimit

# Groq — same idea, x-ratelimit-* headers
curl -sD- -o/dev/null https://api.groq.com/openai/v1/chat/completions \
  -H "Authorization: Bearer $GROQ_API_KEY" -H 'Content-Type: application/json' \
  -d '{"model":"openai/gpt-oss-120b","messages":[{"role":"user","content":"hi"}],"max_tokens":1}' \
  | grep -i x-ratelimit

# OpenRouter — free metadata endpoint, costs no tokens and no quota
curl -s https://openrouter.ai/api/v1/key -H "Authorization: Bearer $OPENROUTER_API_KEY"

# OpenRouter — list every currently-free model id
curl -s https://openrouter.ai/api/v1/models \
  | jq -r '.data[] | select(.id | endswith(":free")) | .id'

# Mistral — list every model the key can reach
curl -s https://api.mistral.ai/v1/models \
  -H "Authorization: Bearer $MISTRAL_API_KEY" | jq -r '.data[].id'
```

---

## Gotchas worth remembering

1. **Rate limits can be per model, not per account.**
   Mistral's spread runs from 4 to 188 req/min on one key. Probe every model you intend to use —
   never assume the account-level number applies.

2. **Listed does not mean available.**
   `/v1/models` advertised a model that returned `403 tier_not_allowed` on the free plan. Send one
   real request before designing around a model.

3. **Reasoning models can return empty content.**
   Tokens go to `reasoning_tokens` while `message.content` comes back empty. Treat
   empty-but-successful as a failure case explicitly.

4. **Probe with metadata endpoints where they exist.**
   OpenRouter's `/api/v1/key` is free and uncounted. On a 50-req/day budget, a health check that
   costs a request is a real tax.

5. **Persist daily counters across restarts.**
   Per-minute windows self-heal in 60s, so memory is fine. Daily caps do not — a restart otherwise
   forgets that a key is already exhausted.

6. **Escape braces in prompts built with `str.format()`.**
   A JSON example inside a template makes `format()` read `{"title"` as a placeholder and raise
   `KeyError`. Double them: `{{` and `}}`.

7. **Attribute usage to whoever actually served the call.**
   With `fallbacks=`, the responding provider may not be the one you asked for. Read `resp.model`
   before crediting a usage counter.

8. **Distrust listicles about free tiers.**
   Published figures were wrong in both directions here: Mistral's real limit was 25× more generous
   than reported, and Cerebras had been dead for three days. Headers are the only source of truth.

---

*All figures probed on 2026-08-20 against live keys, except rows marked `docs`. Free tiers change
without notice — Cerebras went from best-in-class to unavailable in under a week. Re-run the probe
commands above before relying on any number here.*
