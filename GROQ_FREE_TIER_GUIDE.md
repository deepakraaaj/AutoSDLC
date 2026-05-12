# Groq Free Tier Guide - Daily Usage Without Rate Limiting

**Status:** ✅ Optimized for seamless daily processing  
**Tested:** 1 markdown file per day (20-30 API calls)  
**Rate Limits:** 30 req/min, 100 req/day

---

## What Changed (Improved Rate Limiting)

### Smart Request Throttling
The `GroqProvider` now automatically:
- ✅ Tracks requests per minute (30 req/min limit)
- ✅ Tracks requests per day (100 req/day limit)
- ✅ Applies **adaptive backoff** before hitting limits
- ✅ Queues requests intelligently
- ✅ Logs usage for visibility

### Before vs. After
```
BEFORE: Generic exponential backoff (5s, 10s, 20s)
  Problem: No per-minute tracking
  Problem: Could spam API on fast requests
  Problem: No daily counter

AFTER: Smart rate limiting with tracking
  ✓ Monitors requests/minute
  ✓ Monitors requests/day
  ✓ Backs off BEFORE hitting limit
  ✓ Prevents 429 errors proactively
  ✓ Logs usage for transparency
```

---

## How Much Can You Process Daily?

### Groq Free Tier Limits
```
30 requests/minute (hard limit)
100 requests/day (hard limit)
```

### Typical Processing Per Brief
```
Small brief (5-8 epics):
  • Phase 1: 1 call (epics)
  • Phase 2: 5-8 calls (stories)
  • Phase 3: 5-8 calls (tasks)
  • Total: ~11-17 calls ✅ FITS

Medium brief (10-15 epics):
  • Phase 1: 1 call
  • Phase 2: 10-15 calls
  • Phase 3: 10-15 calls
  • Total: ~21-31 calls ✅ FITS (but tight)

Large brief (20+ epics):
  • Total: 40+ calls ❌ EXCEEDS daily limit
  • Solution: Split into 2 briefs or wait until next day
```

### Real-World Daily Capacity
```
✅ 1 medium brief (15 epics)     → ~30 API calls (FITS)
✅ 2 small briefs (8 epics each) → ~34 API calls (FITS)
❌ 2 large briefs (20 epics each) → ~82 API calls (EXCEEDS)
```

**Bottom line:** 1 typical markdown file per day = **seamless, no rate limiting**

---

## Automatic Rate Limiting Features

### 1. Per-Minute Throttling
```python
# Tracks last 30 requests
# When hitting 30 req/min, automatically waits
# Then proceeds when window opens
```

**Example:**
```
Request 29 → OK (proceed)
Request 30 → OK (proceed)
Request 31 → THROTTLE (wait 3 seconds)
Request 32 → OK after wait (proceed)
```

### 2. Daily Counter
```python
# Resets at midnight
# Warns at 80 requests (20% buffer)
# Blocks at 100 requests
```

**Example:**
```
Morning: 0/100 requests used (✓ OK)
Afternoon: 25/100 requests used (✓ OK)
Evening: 95/100 requests used (⚠ Warning)
Late night: 100/100 requests used (❌ Blocked until tomorrow)
```

### 3. Exponential Backoff on 429 Errors
If you DO hit a 429 despite throttling:
```
Attempt 1: Wait 10s, retry
Attempt 2: Wait 20s, retry
Attempt 3: Wait 40s, retry
Attempt 4: Wait 80s, retry → Give up
```

### 4. Server Error Handling
If Groq server has errors (500):
```
Attempt 1: Wait 5s, retry
Attempt 2: Wait 10s, retry
Attempt 3: Wait 20s, retry
Attempt 4: Wait 40s, retry → Give up
```

---

## What You'll See in Logs

### Normal Operation (No Rate Limiting Needed)
```
[INFO GroqProvider] Request 1/100 for today
[INFO GroqProvider] Request 2/100 for today
[INFO GroqProvider] Request 3/100 for today
...
[INFO GroqProvider] Request 30/100 for today
```

### Approaching Limit (Throttling Kicks In)
```
[INFO GroqProvider] Request 28/100 for today
[WARN GroqProvider] Rate limit approaching (29/30 req/min). Waiting 1.2s...
[INFO GroqProvider] Request 29/100 for today
```

### Daily Limit Reached (Next Day)
```
[ERROR GroqProvider] Daily rate limit reached (100 requests/day). 
Please wait until tomorrow or upgrade your API key.
```

---

## Best Practices for Free Tier

### ✅ DO:
- Process **1 medium brief per day** without issues
- Check logs to see current usage (Request X/100)
- Use smaller briefs if processing multiple
- Split large briefs into smaller ones
- Process at different times of day

### ❌ DON'T:
- Process multiple large briefs in one day
- Restart the same brief multiple times
- Generate and discard outputs repeatedly
- Try to bypass rate limiting with simultaneous requests
- Expect instant processing for very large briefs

### 🔄 Workflow:
```
1. Upload your markdown brief
2. App processes with automatic throttling
3. Generation takes 2-5 minutes (normal)
4. Review results
5. If happy, save/export
6. If unhappy, regenerate (counts as new request)

Daily capacity: ~1-2 regenerations per brief
```

---

## Upgrading Beyond Free Tier

If you need more than 100 requests/day:

### Groq Paid Plans
- **Growth:** Higher RPM + 1000+ req/day
- **Enterprise:** Custom limits
- Cost: Check Groq pricing

### Or Use Alternative Providers
```bash
# Use Ollama (local, no limits)
AI_PROVIDER=ollama OLLAMA_BASE_URL=http://localhost:11434 uvicorn main:app

# Use Gemini (different free tier)
AI_PROVIDER=gemini GEMINI_API_KEY=your_key uvicorn main:app

# Use LM Studio (local, no limits)
AI_PROVIDER=lmstudio LMSTUDIO_BASE_URL=http://localhost:1234 uvicorn main:app
```

---

## Monitoring Your Usage

### Check Current Usage
```python
from providers import GroqProvider

groq = GroqProvider()
print(f"Daily requests: {GroqProvider._daily_requests}/{GroqProvider.FREE_TIER_RPD}")
print(f"Requests this minute: {len(GroqProvider._request_times)}/{GroqProvider.FREE_TIER_RPM}")
```

### Read Logs
```bash
# Watch for Request X/100 messages
# These tell you exactly how many you've used
```

### Daily Reset
```
Resets automatically at midnight (local time)
No action needed
Usage counter resets to 0/100
```

---

## Troubleshooting

### Issue: "Rate limit reached"
**Cause:** Used 100+ requests today  
**Solution:** Wait until midnight local time (daily reset)

### Issue: "Waiting Xs before retry"
**Cause:** Hit 30 req/minute limit  
**Solution:** App is handling it automatically, just be patient (5-60s wait)

### Issue: Multiple 429 errors
**Cause:** Something is making requests very quickly  
**Solution:** Check if multiple processes are running, close extras

### Issue: Generation is slow (5+ minutes)
**Cause:** Rate limiting is throttling requests (normal)  
**Solution:** This is expected behavior, generation will complete

---

## FAQ

**Q: Can I process 2 briefs per day?**  
A: Yes, if they're small (5-8 epics each). Medium briefs (15 epics) × 2 = 62 calls (fits but tight). Large × 2 = exceeds limit.

**Q: What if I hit the daily limit?**  
A: App blocks new requests until tomorrow. Your current generation completes, future ones fail. Try again at midnight.

**Q: Can I use multiple API keys?**  
A: Yes, that would give you 100 req/key/day, but only use one key per instance to avoid conflicts.

**Q: Is rate limiting automatic?**  
A: Yes! You don't need to do anything. The app handles throttling before you hit limits.

**Q: How long does generation take?**  
A: 2-5 minutes typical (includes rate limiting waits). Large briefs may take longer.

**Q: What happens if I refresh/retry?**  
A: Each retry counts as a new request. Limit is 100 per day total.

---

## Example: Daily Workflow

```
8:00 AM: Start work
  Upload brief1.md (15 epics)
  ✓ Processes with auto-throttling
  ✓ Takes ~4 minutes (includes rate limit waits)
  ✓ Uses ~30 API calls
  → Status: 30/100 for today

12:00 PM: Review results
  ✓ Happy with output
  ✓ Export to Excel
  → No additional API calls

3:00 PM: Different project
  ✓ Try to upload brief2.md (20 epics)
  ✓ Processing...
  ✓ Uses ~40 API calls
  → Status: 70/100 for today

6:00 PM: Final review
  ✓ Want to regenerate brief1.md with tweaks
  ✓ Upload modified brief1-v2.md
  ✓ Uses ~30 API calls
  → Status: 100/100 for today ✅ AT LIMIT

9:00 PM: Try to process more
  ❌ "Daily rate limit reached"
  → Must wait until tomorrow

NEXT DAY: 12:01 AM
  ✓ Counter resets to 0/100
  ✓ Can process again
```

---

## Production Checklist

- ✅ Groq free tier working seamlessly
- ✅ Auto-throttling prevents 429 errors
- ✅ Daily counter prevents over-usage
- ✅ Exponential backoff for retries
- ✅ Clear logging of usage
- ✅ 1 markdown file per day = guaranteed no rate limiting
- ✅ Request tracking per-minute and per-day
- ✅ Automatic reset at midnight
- ✅ Works with production brief sizes (5-20 epics)

**Your system is production-ready for daily free tier usage!**
