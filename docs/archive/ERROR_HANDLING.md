# Error Handling System — Production-Grade

**Status:** ✅ Implemented  
**Date:** May 12, 2026  
**Coverage:** All API endpoints + Streaming generation

---

## Overview

The application now has **centralized, explicit error handling** with three layers:

1. **Backend Error System** (`error_handler.py`)
   - Structured error classes with user-friendly messages
   - Severity levels (INFO, WARNING, ERROR, CRITICAL)
   - Technical details for logs + user-actionable guidance

2. **HTTP Error Handling** (`main.py`)
   - All endpoints wrapped with try-catch blocks
   - Proper HTTP status codes (400, 404, 500, etc.)
   - JSON error responses with structured data

3. **UI Toast Notifications** (static/index.html)
   - Auto-dismissing toasts for INFO/WARNING/ERROR
   - Persistent toasts for CRITICAL errors
   - Real-time feedback without blocking user flow

---

## Error Types

### 1. ValidationError
**When:** User input is invalid (empty text, wrong file type, invalid status)  
**HTTP Status:** 400  
**UI:** ⚠️ Warning toast (auto-dismiss 6s)  
**Example:**
```
Input text is required.
Only .md files are accepted.
Invalid status 'invalid'. Choose from: planned, in-progress, done.
```

### 2. RateLimitError
**When:** API rate limits exceeded (Groq: 30 req/min, 100 req/day)  
**HTTP Status:** 429  
**UI:** ⚠️ Warning toast (auto-dismiss 6s)  
**Example:**
```
Rate limit approaching (29/30 req/min)
Waiting 1.2s to stay within free tier limits...
```

### 3. APIError
**When:** External API fails (Groq, Gemini, Redmine)  
**HTTP Status:** 500  
**UI:** ❌ Error toast (auto-dismiss 8s)  
**Example:**
```
Groq API error: Connection timeout
Redmine API error: Unauthorized (401)
```

### 4. DatabaseError
**When:** Database operations fail (save, delete, update)  
**HTTP Status:** 500  
**UI:** ❌ Error toast (auto-dismiss 8s)  
**Example:**
```
Failed to save generation
Failed to update task status
```

### 5. FileError
**When:** File operations fail (read, upload, export)  
**HTTP Status:** 404/500  
**UI:** ❌ Error toast (auto-dismiss 8s)  
**Example:**
```
Brief resource missing: PROJECT_BRIEF_TEMPLATE.md
Failed to export Excel for generation 42
```

### 6. GenerationError
**When:** Content generation fails (epics, stories, tasks)  
**HTTP Status:** 500 (SSE stream)  
**UI:** ❌ Error event + toast  
**Example:**
```
Epic generation failed: Invalid JSON in response
Story generation returned empty after retry, skipping...
```

### 7. AppError (Generic)
**When:** Unexpected/unhandled errors  
**HTTP Status:** 500  
**Severity:** CRITICAL  
**UI:** 🔴 Persistent critical toast  
**Example:**
```
Unexpected error during generation: [stack trace in logs]
```

---

## Error Flow

### Streaming Generation (SSE)

```
User uploads brief
    ↓
Phase 1: Epic Generation
    └─ Error? → SSE error event → UI toast
    ↓
Phase 2: Story Generation (per epic)
    └─ Error? → Log + continue to next epic
    ↓
Phase 3: Task Generation (per epic)
    └─ Error? → Log + continue to next epic
    ↓
Metrics Computation
    └─ Error? → SSE error event → UI toast
    ↓
Database Save
    └─ Error? → SSE error event → UI toast
    ↓
Done → Show output or error
```

### Regular API Calls (JSON response)

```
User action (status update, export, etc.)
    ↓
API endpoint receives request
    ↓
Try-catch block catches errors
    ↓
Return JSON error response with error.code, error.message, error.severity
    ↓
Frontend detects error (HTTP !ok or res.error)
    ↓
Show toast with error.code + error.message
```

---

## Logging

### Log Levels

| Level | When | Example | Log Output |
|-------|------|---------|------------|
| DEBUG | Routine operations | "Phase2: Generating stories for epic E1 (attempt 1)" | `[DEBUG Phase2] ...` |
| INFO | Successful milestones | "Successfully generated 3 epics" | `[INFO Phase1] ...` |
| WARNING | Recoverable issues | "Generation 42 not found for export" | `[WARN StatusUpdate] ...` |
| ERROR | Failures that stop work | "Epic generation failed: Connection timeout" | `[ERROR Phase1] ...` |

### Log Files

- **Location:** `/home/deepakrajb/Desktop/KLProjects/AI Projects/story-generator/story_generator.log`
- **Console:** All logs also print to stderr
- **Format:** `[timestamp] [level] component: message`

### Example Log Session

```
[2026-05-12 14:23:45,123] [INFO] API: Generation stream started
[2026-05-12 14:23:46,450] [DEBUG] Phase1: AI response received: 1245 chars
[2026-05-12 14:23:46,451] [INFO] Phase1: Successfully generated 3 epics
[2026-05-12 14:23:47,200] [DEBUG] Phase2: Generating stories for epic E1 (attempt 1)
[2026-05-12 14:23:49,800] [INFO] Phase2: Added 2 stories for epic E1
[2026-05-12 14:23:50,100] [DEBUG] Phase3: Generating tasks for epic E1 (attempt 1)
[2026-05-12 14:23:52,500] [INFO] Phase3: Added 4 tasks for epic E1
[2026-05-12 14:23:53,100] [INFO] Metrics: Validation: trusted
[2026-05-12 14:23:53,500] [INFO] Database: Generation saved with ID 42
```

---

## Toast Notifications

### Severity Styling

| Severity | Color | Icon | Auto-Dismiss | When |
|----------|-------|------|--------------|------|
| INFO | Blue (#79c0ff) | ℹ | 3s | Routine messages |
| WARNING | Gold (#e3b341) | ⚠ | 6s | Rate limiting, validation |
| ERROR | Red (#f85149) | ✕ | 8s | API failures, DB errors |
| CRITICAL | Dark red (#da3633) | ⚠ | Never | Unhandled exceptions |

### Toast Position

- **Location:** Bottom-right corner
- **Stack:** Up to 5 toasts can stack
- **Clickable:** Each toast has a close (×) button
- **Z-index:** 10000 (above all other UI)

### Example Toast Sequence

```
User uploads file
  ↓
File is empty
  ↓
Toast: "ValidationError" / "Uploaded file is empty." (auto-dismiss 6s)
  ↓
User tries again
  ↓
Generation succeeds
  ↓
Toast: "Success" / "Excel exported successfully" (auto-dismiss 3s)
```

---

## Error Response Format

### Success (HTTP 200)
```json
{
  "generation_id": 42,
  "epics": [...],
  "stories": [...],
  "tasks": [...]
}
```

### Validation Error (HTTP 400)
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Input text is required.",
    "severity": "error",
    "details": null,
    "userAction": "Check your input and try again",
    "timestamp": "2026-05-12T14:23:45.123456"
  }
}
```

### API Error (HTTP 500)
```json
{
  "error": {
    "code": "API_ERROR",
    "message": "Groq API error: Connection timeout",
    "severity": "error",
    "details": "Provider: groq | Status: None",
    "userAction": "Please try again in a moment",
    "timestamp": "2026-05-12T14:23:45.123456"
  }
}
```

### Database Error (HTTP 500)
```json
{
  "error": {
    "code": "DATABASE_ERROR",
    "message": "Failed to save generation",
    "severity": "critical",
    "details": "Operation: save_generation | Details: disk full",
    "userAction": "Please contact support if this persists",
    "timestamp": "2026-05-12T14:23:45.123456"
  }
}
```

---

## SSE Error Events

During streaming generation, errors are sent as SSE events:

```json
{
  "type": "error",
  "error": {
    "code": "GENERATION_ERROR",
    "message": "Epic generation failed: Invalid JSON in response",
    "severity": "error",
    "details": "Phase: Epic Generation | Details: JSONDecodeError...",
    "userAction": "Check your brief and try again",
    "timestamp": "2026-05-12T14:23:45.123456"
  }
}
```

---

## Best Practices

### For Users

✅ **DO:**
- Check toasts for operation results
- Read user actions in error messages
- Retry after following suggestions
- Review logs if you need technical details

❌ **DON'T:**
- Ignore error toasts
- Retry immediately on rate limit errors (wait for suggested time)
- Assume silent failures — if something takes >10s, check logs

### For Developers

✅ **DO:**
- Use specific error classes (not generic `Exception`)
- Provide user actions in error messages
- Log at appropriate levels (DEBUG for routine, ERROR for failures)
- Test error paths (network failures, invalid input, DB down)

❌ **DON'T:**
- Return generic "Error occurred" messages
- Lose exception details in logs
- Swallow exceptions without logging
- Mix HTTP statuses (use 400 for client errors, 500 for server errors)

---

## Testing Error Scenarios

### Test Case 1: Invalid Input
```bash
curl -X POST http://localhost:8000/generate-stream \
  -H "Content-Type: application/json" \
  -d '{"text": ""}'
# Expected: HTTP 400, ValidationError toast
```

### Test Case 2: Rate Limiting
```bash
# Generate 30+ requests in <1 minute with Groq
# Expected: WARN logs + adaptive throttling + no 429 errors
```

### Test Case 3: File Export on Nonexistent Generation
```bash
curl http://localhost:8000/export-excel/99999
# Expected: HTTP 404, AppError toast "Generation 99999 not found"
```

### Test Case 4: Database Failure
```bash
# Simulate DB corruption or disk full
# Expected: HTTP 500, DatabaseError toast, error logged
```

---

## Troubleshooting

### "Toast notifications not showing"
- Check browser console for JavaScript errors
- Verify toast-container div exists in HTML
- Check z-index CSS (should be 10000)

### "Errors in logs but no toast"
- Error might be in console-only log
- Check handleEvent() is being called for SSE events
- Verify error object has required fields

### "Application appears frozen after error"
- Check if error is CRITICAL (doesn't auto-dismiss)
- Close persistent toast with × button
- Refresh page if truly stuck

### "Rate limiting feels slow"
- Groq free tier has 30 req/min limit
- Adaptive throttling waits before hitting limit
- This is expected behavior for free tier
- See ../guides/GROQ_FREE_TIER_GUIDE.md for capacity planning

---

## Production Checklist

✅ Error handling integrated in main.py
✅ All endpoints wrapped with try-catch blocks
✅ Logging configured (file + console)
✅ Toast notifications in UI
✅ Structured error responses
✅ User-friendly error messages
✅ Detailed error logging for debugging
✅ HTTP status codes correct
✅ SSE error events formatted properly
✅ Rate limiting errors handled gracefully

**System is ready for production use!**
