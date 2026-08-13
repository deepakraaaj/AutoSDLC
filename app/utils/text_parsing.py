def clean_raw(raw: str) -> str:
    """Strip markdown code fences an LLM sometimes wraps JSON output in
    (e.g. "```json\\n[...]\\n```"). Shared by app/services/generators.py's
    phase generators and main.py's clarify-chat/assistant-router parsing —
    kept here so both can import it without one depending on the other."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        raw = raw.rsplit("```", 1)[0]
    return raw.strip()
