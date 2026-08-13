import json


def sse(event_type: str, data: dict) -> str:
    """Frame one Server-Sent-Events chunk. Shared by main.py's endpoints and
    app/services/generators.py's phase generators — kept here instead of
    either module so importing it doesn't create a circular import between
    the two (generators.py needs it; main.py needs generators.py)."""
    return f"data: {json.dumps({'type': event_type, **data})}\n\n"
