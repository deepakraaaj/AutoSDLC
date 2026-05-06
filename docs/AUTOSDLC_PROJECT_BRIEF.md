# AutoSDLC Project Brief

## Project Summary

AutoSDLC is a local web application that converts a project description or uploaded Markdown document into high-quality software delivery artifacts: epics, user stories, developer tasks, quality metrics, and delivery gaps. The system is designed for engineering leads, product managers, and delivery teams that need actionable sprint-ready work items without spending hours manually decomposing requirements.

The current implementation includes a FastAPI backend, a browser UI, SQLite persistence, Excel export, Redmine project and issue integration, and reusable extraction prompts for preparing project descriptions from documents or repositories.

## Primary Goal

The main goal is to produce stories and tasks that are specific enough for developers to start work with minimal clarification.

A successful output should:

- Identify clear epics, stories, and implementation tasks.
- Use specific user personas instead of generic "user" language.
- Include testable acceptance criteria for every story.
- Include clear definitions of done for every task.
- Include realistic time estimates and dependencies.
- Flag missing information and delivery risks.
- Provide quality metrics so teams can judge whether the output is ready.
- Allow the generated plan to be saved, reviewed, exported, and pushed into Redmine.

## Target Users

### Engineering Lead

The engineering lead uses AutoSDLC to quickly turn rough project ideas, feature briefs, or existing documentation into sprint-ready work. They care about technical clarity, task scope, estimates, dependencies, and whether the team can start without extra meetings.

### Product Manager

The product manager uses AutoSDLC to validate whether a product idea has been decomposed into clear user outcomes. They care about story quality, acceptance criteria, gaps, and coverage of the original requirement.

### Developer

The developer uses generated tasks to understand exactly what to build. They care about implementation scope, dependencies, definition of done, estimate, and links to the parent story.

### Delivery Manager

The delivery manager uses AutoSDLC outputs to populate planning tools such as Redmine and track progress across epics, stories, and tasks.

## Current Capabilities

### 1. Project Input

AutoSDLC supports two primary input modes:

- Chat-style text input for describing a new project or feature.
- Markdown upload for existing project descriptions, product briefs, specs, or extracted documentation.

The backend validates empty input and accepts only `.md` files for file upload.

### 2. AI-Based Generation

The backend sends the project input to a configured AI provider and expects structured JSON output matching the internal schema.

Supported provider configuration includes:

- Groq
- Gemini
- Ollama
- LM Studio

The generated output can include:

- Clarifying questions
- Epics
- User stories
- Developer tasks
- Gaps
- Quality metrics

If the input is too vague, the system can return clarifying questions before final generation.

### 3. Epics, Stories, and Tasks

Generated work is structured as a hierarchy:

- Epic: large feature area or delivery objective.
- Story: user-centered capability linked to an epic.
- Task: implementation activity linked to a story.

Each epic includes:

- ID
- Title
- Description
- Feature area
- Priority
- Status

Each story includes:

- ID
- Title
- Persona
- Desired capability
- Business value
- Acceptance criteria
- Feature area
- Size
- Priority
- Confidence
- Status
- Parent epic ID

Each task includes:

- ID
- Title
- Description
- Definition of done
- Estimate in hours
- Dependencies
- Parent story ID
- Confidence
- Priority
- Status
- Assignee

### 4. Quality Metrics

The system scores generated output so users can judge readiness.

Story metrics include:

- Specificity
- Testability
- Sizing
- Edge case coverage
- Overall story score

Task metrics include:

- Clarity
- Definition of done quality
- Estimate quality
- Dependency quality
- Overall task score

Overall metrics include:

- Coverage score
- Gap count
- Input quality
- Confidence summary

### 5. SQLite Persistence

Every completed generation is saved to a local SQLite database.

The database stores:

- Raw generation output
- Project name
- Original input text
- Metrics
- Normalized epics
- Normalized stories
- Normalized tasks
- Status updates
- Assignees
- Redmine issue IDs

The normalized tables allow the UI to manage statuses, assignments, and Redmine links after generation.

### 6. History

Users can open the History tab to view previous generations.

History entries show:

- Generation date
- Project name
- Quality score

Users can reload a previous generation and continue working with it.

### 7. Project Hierarchy UI

The UI renders a nested hierarchy:

- Epics contain stories.
- Stories contain tasks.

Users can:

- Expand and collapse hierarchy cards.
- Update epic, story, and task statuses.
- Assign tasks to people.
- View Redmine issue IDs after successful push.

Status and assignee changes are persisted through backend API calls.

### 8. Sprint Summary

After generation, the UI displays a sprint summary with:

- Total stories
- Total tasks
- Estimated hours
- Overall quality percentage

This gives users a quick delivery-level view of the generated plan.

### 9. Excel Export

Users can export a generation to an Excel workbook.

The workbook includes:

- Epics sheet
- User Stories sheet
- Developer Tasks sheet

The sheets include formatted headers, wrapped text, priorities, statuses, estimates, dependencies, and confidence values.

### 10. Redmine Integration

AutoSDLC can push generated work into Redmine.

The integration supports:

- Listing Redmine projects.
- Displaying nested project options.
- Creating a new Redmine project from the UI.
- Creating Epic, Story, and Task issues.
- Linking stories under epics.
- Linking tasks under stories.
- Mapping priorities.
- Sending custom fields when available.
- Persisting returned Redmine issue IDs locally.

Required Redmine configuration:

- Redmine URL
- Redmine API key
- Redmine project ID or identifier
- Epic tracker
- Story tracker
- Task tracker

The local Redmine setup includes a Docker Compose stack and a provisioning script for repeatable test projects.

### 11. Extraction Prompts

The project includes reusable prompts that help users prepare better input:

- `story-generator/prompts/EXTRACT_FROM_DOCS.md`
- `story-generator/prompts/EXTRACT_FROM_REPO.md`

These prompts can be used with an external AI tool to turn scattered documents or repository context into a clean Markdown project description for AutoSDLC.

## Key Backend API Endpoints

### Generation

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/generate-stream` | Generate from chat input using server-sent events |
| POST | `/generate-from-file-stream` | Generate from uploaded Markdown using server-sent events |

### History

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/history` | List previous generations |
| GET | `/history/{gen_id}` | Load one generation |
| DELETE | `/history/{gen_id}` | Delete one generation |

### Hierarchy and Tracking

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/hierarchy/{gen_id}` | Load normalized epic-story-task hierarchy |
| GET | `/dashboard` | Load aggregate counts |
| GET | `/projects` | Load all saved project generations |
| PATCH | `/epics/{epic_id}/status` | Update epic status |
| PATCH | `/stories/{story_id}/status` | Update story status |
| PATCH | `/tasks/{task_id}/status` | Update task status |
| PATCH | `/tasks/{task_id}/assignee` | Update task assignee |

### Export and Redmine

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/export-excel/{gen_id}` | Download Excel workbook |
| POST | `/redmine/projects/list` | List Redmine workspace projects and metadata |
| POST | `/redmine/projects/create` | Create a Redmine project |
| POST | `/push-to-redmine` | Push generated epics, stories, and tasks to Redmine |

## Data Model

### Generation

Represents a full AI output for one project input.

Important fields:

- ID
- Created date
- Project name
- Input text
- Output JSON
- Metrics JSON

### Epic

Represents a parent delivery objective.

Important fields:

- Local database ID
- AutoSDLC issue ID
- AI-generated ID
- Generation ID
- Title
- Description
- Feature area
- Priority
- Status
- Redmine issue ID

### Story

Represents user-facing capability.

Important fields:

- Local database ID
- AutoSDLC issue ID
- AI-generated ID
- Parent epic reference
- Generation ID
- Story statement fields
- Acceptance criteria
- Feature area
- Size
- Priority
- Confidence
- Status
- Redmine issue ID

### Task

Represents implementation work.

Important fields:

- Local database ID
- AutoSDLC issue ID
- AI-generated ID
- Parent story reference
- Generation ID
- Description
- Definition of done
- Estimate
- Dependencies
- Priority
- Confidence
- Status
- Assignee
- Redmine issue ID

## Functional Requirements

### Input and Generation

- The user can enter a project description in a text box.
- The user can upload a Markdown file.
- The system validates that input is not empty.
- The system rejects non-Markdown file uploads.
- The system streams generation progress to the UI.
- The system displays AI tokens as they arrive.
- The system parses the final AI response as JSON.
- The system validates the response against Pydantic schemas.
- The system displays clarifying questions when the input is insufficient.
- The system saves completed generations automatically.

### Output Review

- The user can view generated epics, stories, and tasks.
- The user can inspect quality metrics.
- The user can inspect delivery gaps.
- The user can expand and collapse hierarchy cards.
- The user can copy generated content.
- The user can start a new session.

### Tracking

- The user can reload a previous generation.
- The user can update epic status.
- The user can update story status.
- The user can update task status.
- The user can assign or clear a task assignee.
- The system persists tracking changes in SQLite.

### Export

- The user can export a saved generation to Excel.
- The Excel file includes epics, stories, and tasks.
- The exported file preserves key planning fields.

### Redmine

- The user can configure Redmine URL and API key.
- The system can list Redmine projects.
- The system can show Redmine metadata readiness, including missing trackers or custom fields.
- The user can create a new Redmine project.
- The user can push a generation to a selected Redmine project.
- The system creates epic, story, and task issues.
- The system links child issues to parent issues.
- The system stores returned Redmine issue IDs locally.

## Nonfunctional Requirements

- The app should run locally.
- The app should not require user accounts.
- The UI should remain responsive during generation.
- Backend errors should be surfaced clearly in the UI.
- Generated data should persist locally without cloud storage.
- Redmine integration should fail gracefully and show per-issue errors.
- AI provider configuration should be environment-driven.
- The app should be simple to start with `uvicorn main:app --reload`.

## Local Setup

```bash
cd story-generator
pip install -r requirements.txt
uvicorn main:app --reload
```

Open:

```text
http://localhost:8000
```

Example `.env`:

```text
AI_PROVIDER=groq
GROQ_API_KEY=your_key_here

REDMINE_URL=http://localhost:3001
REDMINE_API_KEY=your_redmine_key_here
REDMINE_PROJECT_ID=autosdlc-template
REDMINE_EPIC_TRACKER_ID=Epic
REDMINE_STORY_TRACKER_ID=Story
REDMINE_TASK_TRACKER_ID=Task
```

## Local Redmine Setup

```bash
cd story-generator/redmine-local
docker compose up -d
```

Open:

```text
http://localhost:3001
```

Default login:

- Username: `admin`
- Password: `admin`

After retrieving a Redmine API key, provision projects:

```bash
export REDMINE_URL=http://localhost:3001
export REDMINE_API_KEY=your_redmine_key_here
python3 provision_projects.py --template projects.template.json
```

## Current Implementation Files

### Backend

- `story-generator/main.py`
- `story-generator/schemas.py`
- `story-generator/providers.py`
- `story-generator/prompt.py`
- `story-generator/metrics.py`
- `story-generator/database.py`
- `story-generator/export.py`
- `story-generator/redmine.py`

### Frontend

- `story-generator/static/index.html`

### Redmine Local Environment

- `story-generator/redmine-local/compose.yaml`
- `story-generator/redmine-local/provision_projects.py`
- `story-generator/redmine-local/projects.template.json`

### Supporting Prompts

- `story-generator/prompts/EXTRACT_FROM_DOCS.md`
- `story-generator/prompts/EXTRACT_FROM_REPO.md`

## Acceptance Criteria

### Generation

- Given a detailed project description, when the user clicks Generate, then the UI streams progress and displays epics, stories, tasks, metrics, and gaps.
- Given a vague project description, when the AI determines more information is needed, then the UI displays clarifying questions before final generation.
- Given an invalid AI response, when parsing fails, then the UI displays a clear error.

### Persistence

- Given a completed generation, when generation finishes, then the result is saved to SQLite.
- Given a saved generation, when the user opens History, then the generation is listed.
- Given a saved generation, when the user clicks it, then the output and hierarchy reload.

### Hierarchy Tracking

- Given a saved generation, when the user changes an epic status, then the backend persists the new status.
- Given a saved generation, when the user changes a story status, then the backend persists the new status.
- Given a saved generation, when the user changes a task status, then the backend persists the new status.
- Given a saved generation, when the user enters a task assignee, then the backend persists the assignee.

### Export

- Given a saved generation, when the user clicks Export to Excel, then an `.xlsx` workbook downloads.
- The workbook includes epics, user stories, and developer tasks.

### Redmine

- Given valid Redmine credentials, when the user loads projects, then Redmine projects appear in the project dropdown.
- Given valid Redmine credentials and a project name, when the user creates a project, then the project is created in Redmine.
- Given a saved generation and selected Redmine project, when the user pushes to Redmine, then epic, story, and task issues are created.
- Given a successful Redmine push, when Redmine returns issue IDs, then local rows store those Redmine IDs.

## Known Gaps and Next Work

### Short-Term

- Add automated tests for `story-generator`.
- Add endpoint tests for Redmine project listing and issue push using mocked HTTP calls.
- Add frontend browser checks for hierarchy status and assignee persistence.
- Add a safer migration path for existing SQLite databases when schema changes.
- Add delete confirmation in the History UI.
- Improve duplicate prevention for repeated Redmine pushes.

### Medium-Term

- Add Jira, GitHub Issues, or Linear integrations.
- Add bulk export and bulk delete for history.
- Add editable stories and tasks before export or Redmine push.
- Add role-based assignment suggestions.
- Add saved Redmine profiles.
- Add import from existing Redmine projects.

### Long-Term

- Connect the story/task generator with the larger AutoSDLC architecture-doc and router-agent MVP.
- Use repository context to generate implementation-aware tasks.
- Add autonomous routing from generated tasks to agents or humans.
- Add code generation and review agents behind explicit human approval gates.

## Success Metrics

- Generated output reaches at least 80 percent overall quality for detailed inputs.
- A developer can start implementing most generated tasks without extra clarification.
- Redmine push succeeds for all valid generated epics, stories, and tasks.
- Exported Excel files are usable by product and delivery stakeholders.
- History reload preserves generated output and tracking metadata.
- Status and assignee changes survive page refresh.

## Out of Scope for Current Version

- User accounts.
- Multi-user collaboration.
- Production deployment.
- Full Redmine administration beyond project creation and issue creation.
- Automatic code generation.
- Automatic code review.
- Jira, Linear, or GitHub Issues integrations.
- Real-time team capacity planning.

## Recommended Demo Flow

1. Start the app with `uvicorn main:app --reload`.
2. Open `http://localhost:8000`.
3. Paste a project description or upload this Markdown file.
4. Generate epics, stories, and tasks.
5. Review sprint summary and quality metrics.
6. Update a few statuses and assignees in the hierarchy.
7. Export the result to Excel.
8. Open the Redmine modal.
9. Load or create a Redmine project.
10. Push the generation to Redmine.
11. Confirm created Redmine issue links and local Redmine IDs.
