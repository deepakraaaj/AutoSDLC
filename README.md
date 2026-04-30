# Story Generator

Story Generator is the AutoSDLC web app for turning a project brief into a structured backlog of epics, stories, and tasks.
It includes a FastAPI backend, a browser UI, local SQLite persistence, Excel export, and Redmine project/issue integration.

## What it does

- Compiles structured briefs into epics, stories, and tasks
- Generates backlogs from free-form input or uploaded documents
- Lets you review and edit work in the browser
- Stores generations locally in SQLite
- Exports the backlog to Excel
- Lists Redmine projects and pushes generated issues into Redmine

## Project layout

- `main.py` - FastAPI app and HTTP endpoints
- `static/index.html` - Browser UI
- `rule_based_generator.py` - Deterministic backlog compiler
- `prompt.py` - Prompt assembly and brief preparation
- `export.py` - Excel export
- `redmine.py` - Redmine workspace and issue integration
- `database.py` - SQLite persistence
- `redmine-local/` - Local Redmine stack and project provisioning helpers

## Local setup

```bash
cd story-generator
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --reload
```

Open:

```text
http://127.0.0.1:8000
```

## Redmine setup

If you want to push work into Redmine, configure these values in `.env`:

```bash
REDMINE_URL=https://your-redmine.example.com
REDMINE_API_KEY=your_api_key_here
REDMINE_PROJECT_ID=your_project_identifier
REDMINE_EPIC_TRACKER_ID=Epic
REDMINE_STORY_TRACKER_ID=Story
REDMINE_TASK_TRACKER_ID=Task
```

For a local Redmine environment, see [`redmine-local/README.md`](redmine-local/README.md).

## Tests

```bash
pytest
```
