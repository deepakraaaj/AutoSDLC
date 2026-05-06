# AutoSDLC Quick Start Guide

## 🎯 What This Does

AutoSDLC transforms a project description (or uploaded docs) into professional user stories and developer tasks — instantly. With the new features, you can also save your work, export to Excel, and push directly to Redmine.

---

## ⚡ 60 Second Setup

```bash
cd story-generator

# Install dependencies (first time only)
pip install -r requirements.txt

# Set your AI provider in .env
# AI_PROVIDER=groq
# GROQ_API_KEY=your_key_here

# Run the server
uvicorn main:app --reload

# Open in browser
# http://localhost:8000
```

---

## 📝 Basic Workflow

### Option A: Chat Input
1. Type project description in **"Describe a project"** tab
2. Click **"Generate Stories & Tasks"**
3. Get back:
   - User stories with acceptance criteria
   - Developer tasks with estimates & definitions of done
   - Quality metrics scorecard
   - Gaps flagged

### Option B: Upload Markdown File
1. Click **"Upload .md file"** tab
2. Drag/drop or click to upload your project description
3. Click **"Generate Stories & Tasks"**
4. Same output as above

### Option C: Extract from Documents (New)
1. Open `story-generator/prompts/EXTRACT_FROM_DOCS.md`
2. Copy the prompt
3. Open ChatGPT/Claude/Gemini
4. Paste prompt + your documents (PRD, spec, emails, etc.)
5. Get clean markdown output
6. Upload that .md to AutoSDLC → Generate stories

### Option D: Extract from Your Codebase (New)
1. Open `story-generator/prompts/EXTRACT_FROM_REPO.md`
2. Follow Step 1: Run the bash command in your repository
3. Copy the output
4. Open ChatGPT/Claude/Gemini
5. Paste prompt + repo output
6. Get project description in markdown
7. Upload to AutoSDLC → Generate stories

---

## 💾 New Features

### Save & History
- Every generation is automatically saved to SQLite
- Click **"History"** tab to see all past generations
- Click any past generation to reload it
- Works offline — no cloud needed

### Export to Excel
- After generation, click **"⬇ Export to Excel"**
- Download `stories_tasks_{id}.xlsx`
- Two sheets:
  - **User Stories** — with acceptance criteria
  - **Developer Tasks** — with estimates, DoD, dependencies
- Share with PMs, stakeholders, or teams
- Import into spreadsheet tools

### Push to Redmine
- After generation, click **"↗ Push to Redmine"**
- First time: Enter Redmine URL, API key, project ID
- System creates:
  - Each story → parent epic issue
  - Each task → child issue linked to parent
- See created issue links immediately
- Click link to jump to Redmine

### Sprint Summary
- After generation, see at-a-glance stats:
  - Total stories
  - Total tasks
  - Estimated hours (summed from task estimates)
  - Overall quality %

### Copy Individual Stories/Tasks
- Hover over any story or task card
- Click **"copy"** button
- Get text copied to clipboard
- Share in Slack, email, docs, etc.

### Expand/Collapse All
- Use **"Expand/Collapse"** button above each section
- Quickly toggle all cards open/closed
- Useful for scrolling or printing

---

## 🔧 Configuration

### For Story Generation
```
AI_PROVIDER=groq          # or gemini, ollama, lmstudio
GROQ_API_KEY=sk-...       # Your API key for provider
```

### For Redmine Integration (Optional)
```
REDMINE_URL=https://your-redmine.example.com
REDMINE_API_KEY=your_api_key_here
REDMINE_PROJECT_ID=project_identifier
REDMINE_EPIC_TRACKER_ID=Epic        # or your custom tracker name
REDMINE_TASK_TRACKER_ID=Task        # or your custom tracker name
```

Get Redmine API key: 
- Log into Redmine
- Account → Settings → API Access → Show
- Copy your API key

---

## 📊 Example Input → Output

### Input
```
Build a food delivery app for small restaurants. 
Customers browse menus from local restaurants, 
add items to cart, pay online, and track delivery. 
Restaurant owners manage their menu and see 
incoming orders in real time.
```

### Output
```
✓ 8 user stories:
  - S1: Guest browses restaurant menus
  - S2: Guest adds items to cart
  - S3: Guest checks out as guest
  - ... (etc)

✓ 16 developer tasks:
  - T1: API endpoint for restaurant list (4-6 hrs)
  - T2: Menu database schema (2-3 hrs)
  - T3: Shopping cart service (6-8 hrs)
  - ... (etc)

✓ Quality metrics:
  - Story quality: 85%
  - Task quality: 82%
  - Coverage: 94%
  - Gaps found: 2

✓ Gaps flagged:
  - How is delivery tracked in real-time?
  - Payment processor integration details?
```

---

## 🚀 Full Workflow Example

1. **Preparation:** Use EXTRACT_FROM_DOCS.md with your project docs in Claude
2. **Upload:** Get the markdown, upload to AutoSDLC
3. **Generate:** Click Generate → review stories & tasks
4. **Export:** Download .xlsx to share with PM
5. **Review:** Team reviews, provides feedback
6. **Iterate:** Go back to History, reload, regenerate with new details
7. **Deploy:** Once approved, click "Push to Redmine"
8. **Track:** Issues appear in Redmine immediately
9. **Execute:** Developers pick tasks and start building

---

## 🎓 Tips & Best Practices

### Input Quality
- More details = better output
- Mention user types: "first-time buyers", "admin", "guest users"
- List specific features: not "build a cart" but "cart persists for 24h, shows qty and price, allows edit/delete"
- Mention constraints: "must work on mobile", "payment via Stripe", "live updates"

### When to Use Each Input Method
- **Chat:** Quick iteration, brainstorming, one-off ideas
- **File upload:** Existing docs (PRD, spec, README)
- **Extract from docs:** 5+ documents, mixed sources (emails, meeting notes, slides)
- **Extract from repo:** You already have a codebase, just need to plan next features

### Getting Perfect Output
- If output is generic: regenerate with more specific user types and edge cases
- If output is too big: ask for specific feature area only
- If output is incomplete: check the "Gaps" section, add those answers, regenerate

### Before Pushing to Redmine
- Review stories in History
- Check acceptance criteria are clear
- Verify task estimates are realistic
- Make sure dependencies are listed
- Export to Excel for team review if needed

---

## ❓ FAQ

**Q: What if I don't have Redmine?**  
A: Export to Excel instead. You can import into Jira, Linear, GitHub Projects, or any other tool later.

**Q: Can I edit stories after generation?**  
A: Currently, copy the output and edit manually. Future version will have inline editing.

**Q: Does my data stay private?**  
A: Yes. Unless you configure Redmine, everything stays on your machine (SQLite database). Extraction prompts you use in Claude/ChatGPT follow their privacy policies.

**Q: Can I use multiple AI providers?**  
A: Yes, change `AI_PROVIDER` in .env to switch between Groq, Gemini, Ollama, or LMStudio instantly.

**Q: What happens if generation fails?**  
A: Check your API key and provider status. Error message will tell you what went wrong.

**Q: How long does generation take?**  
A: Usually 10-30 seconds depending on AI provider. You'll see real-time progress.

**Q: Can I export past generations?**  
A: Yes, click History → click past generation → click Export Excel.

---

## 🆘 Troubleshooting

| Issue | Solution |
|-------|----------|
| "AI provider error" | Check API key in .env, verify provider service is up |
| "Redmine not configured" | Fill in REDMINE_URL, REDMINE_API_KEY, REDMINE_PROJECT_ID in .env |
| "Output structure error" | AI returned malformed JSON. Try regenerating or simpler input |
| "Generation not saved" | Check SQLite file exists at `story-generator/autosdlc.db` |
| "Export Excel fails" | Check openpyxl is installed (`pip install openpyxl`) |

---

## 📚 Files to Know

- `story-generator/main.py` — API server
- `story-generator/database.py` — SQLite + history
- `story-generator/export.py` — Excel export
- `story-generator/redmine.py` — Redmine integration
- `story-generator/static/index.html` — Web UI
- `story-generator/prompts/EXTRACT_FROM_DOCS.md` — Doc extractor prompt
- `story-generator/prompts/EXTRACT_FROM_REPO.md` — Repo analyzer prompt
- `story-generator/autosdlc.db` — SQLite database (auto-created)

---

## 🎉 You're Ready!

Run the server, describe a project, and get professional stories & tasks instantly. Export, push to Redmine, or iterate — it's all there.

Have feedback? Found a bug? Want a feature? The system is built to be extended.

**Happy story writing!** 🚀
