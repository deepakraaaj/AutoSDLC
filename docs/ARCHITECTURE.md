# AutoSDLC Project Architecture

## Directory Structure

```
autosdlc/
├── app/                          # Main application package
│   ├── __init__.py
│   ├── core/                     # Core business logic
│   │   ├── rule_based_generator.py   # Backlog generation logic
│   │   └── backlog_quality.py        # Quality scoring and validation
│   ├── services/                 # External integrations & utilities
│   │   ├── database.py               # SQLite persistence
│   │   ├── export.py                 # Excel export functionality
│   │   ├── metrics.py                # Metrics computation
│   │   ├── prompt.py                 # LLM prompt assembly
│   │   ├── providers.py              # LLM provider abstraction
│   │   └── brief_upload.py           # File upload handling
│   ├── schemas/                  # Data models
│   │   └── models.py                 # Pydantic schemas (Epic, Story, Task, etc.)
│   └── utils/                    # Utilities
│       └── error_handler.py          # Error handling & logging
├── redmine/                      # Redmine integration
│   ├── client.py                     # Redmine API client
│   └── local/                        # Local Redmine setup
│       ├── compose.yaml              # Docker compose config
│       ├── provision_projects.py     # Project provisioning
│       └── README.md
├── main.py                       # FastAPI application entry point
├── static/                       # Frontend assets
│   └── index.html                    # Web UI
├── docs/                         # Documentation
│   ├── README.md
│   ├── guides/                       # Quick start, provider guides
│   └── archive/                      # Historical docs
├── prompts/                      # LLM prompt templates
│   ├── EXTRACT_FROM_DOCS.md
│   ├── EXTRACT_FROM_REPO.md
│   └── IDEA_TO_PROJECT_BRIEF.md
├── tests/                        # Test suite
│   ├── test_rule_based_generator.py
│   ├── test_brief_upload.py
│   └── test_redmine_*.py
├── requirements.txt              # Python dependencies
├── .env                          # Environment config
└── autosdlc.db                  # SQLite database
```

## Module Responsibilities

### app/core/
- **rule_based_generator.py**: 3-phase pipeline for deterministic backlog generation
  - Phase 1: Extract 10-20 epics from brief
  - Phase 2: Generate 5-8 stories per epic
  - Phase 3: Generate 4-6 tasks per story
- **backlog_quality.py**: Task dependency normalization and backlog validation

### app/services/
- **database.py**: SQLite ORM and persistence layer
- **export.py**: Excel workbook generation
- **metrics.py**: Backlog quality scoring and validation metrics
- **prompt.py**: LLM prompt templates (system, user, and role-based)
- **providers.py**: Abstraction layer for LLM providers (Cerebras, Groq, LMStudio, etc.)
- **brief_upload.py**: File upload parsing (Markdown, Word documents)

### app/schemas/
- **models.py**: Pydantic data models for type safety and validation
  - GenerateRequest, GenerationOutput
  - Epic, Story, Task, Gap
  - OverallMetrics, ValidationResult

### app/utils/
- **error_handler.py**: Centralized error handling with user-friendly messages and logging

### redmine/
- **client.py**: REST API integration with Redmine
  - Project creation, issue synchronization
  - Custom field mapping for epics/stories/tasks
- **local/**: Docker-based local Redmine environment for development

## Data Flow

```
User Brief Input
    ↓
[prompt.py] Format & prepare brief
    ↓
[providers.py] Call LLM API
    ↓
[rule_based_generator.py] 3-phase generation
    ↓
[backlog_quality.py] Validate & normalize
    ↓
[database.py] Store in SQLite
    ↓
[export.py] Export to Excel / [redmine/client.py] Sync to Redmine
```

## Key Design Decisions

1. **Modular Imports**: Clear separation between core logic, services, and utilities
2. **Root Entry Point**: `main.py` at project root for simpler deployment
3. **Provider Abstraction**: Support multiple LLM providers without code changes
4. **Error Handling**: Centralized, with user-friendly messages and technical logging
5. **Database First**: SQLite for local persistence, optional Redmine sync

## Development

Run the app:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Access at: http://127.0.0.1:8000

Run tests:
```bash
pytest
```
