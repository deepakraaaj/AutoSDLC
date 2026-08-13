import sqlite3
import json
import os
from datetime import datetime, timezone
from app.schemas.models import GenerationOutput, OverallMetrics

# Overridable so a deployment (e.g. Docker) can point this at a dedicated
# data volume without shadowing this module's own directory — the default
# keeps the original next-to-this-file location for native/local runs.
DB_PATH = os.getenv("AUTOSDLC_DB_PATH") or os.path.join(os.path.dirname(__file__), "autosdlc.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_column(conn, table_name: str, column_name: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def init_db():
    conn = get_connection()
    c = conn.cursor()

    # Existing table
    c.execute("""
        CREATE TABLE IF NOT EXISTS generations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            project_name TEXT,
            input_text TEXT NOT NULL,
            output_json TEXT NOT NULL,
            metrics_json TEXT
        )
    """)

    # Counter table for auto-ID generation
    c.execute("""
        CREATE TABLE IF NOT EXISTS counters (
            name TEXT PRIMARY KEY,
            value INTEGER NOT NULL DEFAULT 0
        )
    """)

    # Small key/value store for app-level settings that need to persist
    # across restarts but don't warrant their own table — e.g. which AI
    # provider is active, chosen at runtime from the UI rather than baked
    # into .env at container build time.
    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    c.execute("INSERT OR IGNORE INTO counters VALUES ('epic', 0)")
    c.execute("INSERT OR IGNORE INTO counters VALUES ('story', 0)")
    c.execute("INSERT OR IGNORE INTO counters VALUES ('task', 0)")

    # Epics table
    c.execute("""
        CREATE TABLE IF NOT EXISTS epics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_id TEXT NOT NULL UNIQUE,
            generation_id INTEGER NOT NULL REFERENCES generations(id) ON DELETE CASCADE,
            ai_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            feature_area TEXT,
            priority TEXT NOT NULL DEFAULT 'medium',
            status TEXT NOT NULL DEFAULT 'planned',
            created_at TEXT NOT NULL,
            redmine_id INTEGER,
            redmine_priority_name TEXT
        )
    """)

    # Stories table
    c.execute("""
        CREATE TABLE IF NOT EXISTS stories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_id TEXT NOT NULL UNIQUE,
            generation_id INTEGER NOT NULL REFERENCES generations(id) ON DELETE CASCADE,
            epic_id INTEGER REFERENCES epics(id) ON DELETE SET NULL,
            ai_id TEXT NOT NULL,
            ai_epic_id TEXT,
            title TEXT NOT NULL,
            as_a TEXT,
            i_want TEXT,
            so_that TEXT,
            acceptance_criteria TEXT,
            feature_area TEXT,
            size TEXT,
            priority TEXT NOT NULL DEFAULT 'medium',
            confidence TEXT,
            status TEXT NOT NULL DEFAULT 'planned',
            created_at TEXT NOT NULL,
            redmine_id INTEGER,
            redmine_priority_name TEXT
        )
    """)

    # Tasks table
    c.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_id TEXT NOT NULL UNIQUE,
            generation_id INTEGER NOT NULL REFERENCES generations(id) ON DELETE CASCADE,
            story_id INTEGER REFERENCES stories(id) ON DELETE SET NULL,
            ai_id TEXT NOT NULL,
            ai_story_id TEXT,
            title TEXT NOT NULL,
            description TEXT,
            definition_of_done TEXT,
            estimate_hours TEXT,
            dependencies TEXT,
            confidence TEXT,
            priority TEXT NOT NULL DEFAULT 'medium',
            status TEXT NOT NULL DEFAULT 'todo',
            assignee TEXT,
            created_at TEXT NOT NULL,
            redmine_id INTEGER,
            redmine_priority_name TEXT
        )
    """)

    _ensure_column(conn, "epics", "redmine_priority_name", "TEXT")
    _ensure_column(conn, "stories", "redmine_priority_name", "TEXT")
    _ensure_column(conn, "tasks", "redmine_priority_name", "TEXT")
    _ensure_column(conn, "tasks", "test_cases", "TEXT")

    conn.commit()
    conn.close()


def get_setting(key: str, default: str | None = None) -> str | None:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = c.fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()
    conn.close()


def next_id(conn, type_name: str, prefix: str) -> str:
    """Generate next auto-ID for epic/story/task."""
    c = conn.cursor()
    c.execute("UPDATE counters SET value = value + 1 WHERE name = ?", (type_name,))
    c.execute("SELECT value FROM counters WHERE name = ?", (type_name,))
    row = c.fetchone()
    return f"{prefix}-{row['value']:04d}"


def extract_project_name(input_text: str) -> str:
    """Extract project name from first line of input."""
    lines = input_text.strip().split('\n')
    first_line = lines[0].strip() if lines else "Untitled Project"
    if first_line.startswith('#'):
        return first_line.replace('#', '').strip()
    return first_line[:50] if len(first_line) > 50 else first_line


def save_generation(input_text: str, output: GenerationOutput) -> int:
    """Save a generation to database. Returns row id."""
    conn = get_connection()
    c = conn.cursor()
    project_name = extract_project_name(input_text)
    # Include the UTC offset. A timezone-less ISO string is parsed by browsers
    # as local time, which made history entries appear several hours off.
    created_at = datetime.now(timezone.utc).isoformat()
    output_json = json.dumps(output.model_dump())
    metrics_json = json.dumps(output.metrics.model_dump()) if output.metrics else None

    c.execute("""
        INSERT INTO generations (created_at, project_name, input_text, output_json, metrics_json)
        VALUES (?, ?, ?, ?, ?)
    """, (created_at, project_name, input_text, output_json, metrics_json))
    conn.commit()
    row_id = c.lastrowid
    conn.close()
    return row_id


def save_generation_normalized(generation_id: int, output: GenerationOutput) -> dict:
    """Save a freshly-generated GenerationOutput into normalized epic/story/task
    tables, auto-generating human-facing IDs. Used by the one-click pipeline,
    where epics/stories/tasks are all new. For a step-by-step generation that
    resumes an existing generation_id, use save_stories_only/save_tasks_only
    directly instead — calling this again for the same generation_id would
    re-insert (and double) every row."""
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()

    result = {"epics": [], "stories": []}

    # Pass 1: Insert epics, build ai_id → db_id mapping
    epic_id_map: dict[str, int] = {}
    for epic in output.epics:
        issue_id = next_id(conn, 'epic', 'EP')
        c.execute("""
            INSERT INTO epics (issue_id, generation_id, ai_id, title, description,
                              feature_area, priority, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (issue_id, generation_id, epic.id, epic.title, epic.description,
              epic.feature_area, epic.priority, epic.status, now))
        db_id = c.lastrowid
        epic_id_map[epic.id] = db_id
        result["epics"].append({
            "ai_id": epic.id,
            "issue_id": issue_id,
            "db_id": db_id,
            "title": epic.title
        })

    conn.commit()
    conn.close()

    story_id_map, story_rows = save_stories_only(generation_id, output.stories, epic_id_map)
    result["stories"] = story_rows

    task_rows = save_tasks_only(generation_id, output.tasks, story_id_map)
    result["tasks"] = task_rows

    return result


def save_stories_only(
    generation_id: int, stories: list, epic_id_map: dict[str, int]
) -> tuple[dict[str, int], list[dict]]:
    """Insert a batch of stories for an already-existing generation, resolving
    each story's epic FK from `epic_id_map` (ai_id → db_id — build one with
    get_epic_id_map(generation_id) when resuming a step-by-step generation
    rather than calling this right after save_generation_normalized's epic
    pass). Returns (ai_id → db_id map for the inserted stories, row summaries)."""
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()

    story_id_map: dict[str, int] = {}
    rows = []
    for story in stories:
        issue_id = next_id(conn, 'story', 'US')
        db_epic_id = epic_id_map.get(story.epic_id) if story.epic_id else None

        ac_json = json.dumps(story.acceptance_criteria)
        c.execute("""
            INSERT INTO stories (issue_id, generation_id, epic_id, ai_id, ai_epic_id,
                                title, as_a, i_want, so_that, acceptance_criteria,
                                feature_area, size, priority, confidence, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (issue_id, generation_id, db_epic_id, story.id, story.epic_id,
              story.title, story.as_a, story.i_want, story.so_that, ac_json,
              story.feature_area, story.size, story.priority, story.confidence,
              story.status, now))
        db_id = c.lastrowid
        story_id_map[story.id] = db_id
        rows.append({"ai_id": story.id, "issue_id": issue_id, "db_id": db_id, "title": story.title})

    conn.commit()
    conn.close()
    return story_id_map, rows


def save_tasks_only(
    generation_id: int, tasks: list, story_id_map: dict[str, int]
) -> list[dict]:
    """Insert a batch of tasks for an already-existing generation, resolving
    each task's story FK from `story_id_map` (ai_id → db_id — build one with
    get_story_id_map(generation_id) when resuming a step-by-step generation).
    Returns row summaries."""
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()

    rows = []
    for task in tasks:
        issue_id = next_id(conn, 'task', 'TSK')
        db_story_id = story_id_map.get(task.story_id) if task.story_id else None

        deps_json = json.dumps(task.dependencies)
        test_cases_json = json.dumps([tc.model_dump() for tc in task.test_cases])
        c.execute("""
            INSERT INTO tasks (issue_id, generation_id, story_id, ai_id, ai_story_id,
                              title, description, definition_of_done, estimate_hours,
                              dependencies, confidence, priority, status, assignee, created_at,
                              test_cases)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (issue_id, generation_id, db_story_id, task.id, task.story_id,
              task.title, task.description, task.definition_of_done, task.estimate_hours,
              deps_json, task.confidence, task.priority, task.status, task.assignee, now,
              test_cases_json))
        db_id = c.lastrowid
        rows.append({"ai_id": task.id, "issue_id": issue_id, "db_id": db_id, "title": task.title})

    conn.commit()
    conn.close()
    return rows


def save_test_cases(generation_id: int, tasks: list) -> None:
    """Attach generated test cases to already-persisted task rows, matched by
    (generation_id, ai_id) — used by the step-by-step test-case phase, which
    runs after save_tasks_only has already created the task rows."""
    conn = get_connection()
    c = conn.cursor()
    for task in tasks:
        if not task.test_cases:
            continue
        test_cases_json = json.dumps([tc.model_dump() for tc in task.test_cases])
        c.execute(
            "UPDATE tasks SET test_cases = ? WHERE generation_id = ? AND ai_id = ?",
            (test_cases_json, generation_id, task.id),
        )
    conn.commit()
    conn.close()


def get_epic_id_map(generation_id: int) -> dict[str, int]:
    """ai_id → db_id for every epic already saved under this generation —
    used to resume a step-by-step generation into the stories phase without
    the in-memory map save_generation_normalized builds for a fresh run."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT ai_id, id FROM epics WHERE generation_id = ?", (generation_id,))
    result = {row["ai_id"]: row["id"] for row in c.fetchall()}
    conn.close()
    return result


def get_story_id_map(generation_id: int) -> dict[str, int]:
    """ai_id → db_id for every story already saved under this generation —
    used to resume a step-by-step generation into the tasks phase."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT ai_id, id FROM stories WHERE generation_id = ?", (generation_id,))
    result = {row["ai_id"]: row["id"] for row in c.fetchall()}
    conn.close()
    return result


def get_task_id_map(generation_id: int) -> dict[str, int]:
    """ai_id → db_id for every task already saved under this generation —
    used to resume a step-by-step generation into the test-cases phase."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT ai_id, id FROM tasks WHERE generation_id = ?", (generation_id,))
    result = {row["ai_id"]: row["id"] for row in c.fetchall()}
    conn.close()
    return result


def update_generation_output(generation_id: int, output: GenerationOutput) -> None:
    """Overwrite the generations row's output/metrics blob — called at the end
    of every step-by-step phase endpoint so GET /history/{id} and
    GET /hierarchy/{id} reflect partial progress even if the user stops
    part-way through, instead of only ever being written once at the end."""
    conn = get_connection()
    c = conn.cursor()
    output_json = json.dumps(output.model_dump())
    metrics_json = json.dumps(output.metrics.model_dump()) if output.metrics else None
    c.execute(
        "UPDATE generations SET output_json = ?, metrics_json = ? WHERE id = ?",
        (output_json, metrics_json, generation_id),
    )
    conn.commit()
    conn.close()


def list_generations() -> list[dict]:
    """List all generations with summary info."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT id, created_at, project_name, metrics_json
        FROM generations
        ORDER BY created_at DESC
    """)
    rows = c.fetchall()
    conn.close()

    result = []
    for row in rows:
        metrics = None
        if row['metrics_json']:
            metrics = json.loads(row['metrics_json'])
        result.append({
            'id': row['id'],
            'created_at': row['created_at'],
            'project_name': row['project_name'],
            'metrics': metrics
        })
    return result


def get_generation(gen_id: int) -> dict | None:
    """Get a specific generation by id."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT id, created_at, project_name, input_text, output_json, metrics_json
        FROM generations
        WHERE id = ?
    """, (gen_id,))
    row = c.fetchone()
    conn.close()

    if not row:
        return None

    output = json.loads(row['output_json'])
    return {
        'id': row['id'],
        'created_at': row['created_at'],
        'project_name': row['project_name'],
        'input_text': row['input_text'],
        'output': output
    }


def get_generation_hierarchy(gen_id: int) -> dict | None:
    """Get generation as nested epic→story→task hierarchy."""
    conn = get_connection()
    c = conn.cursor()

    # Get all epics for this generation
    c.execute("""
        SELECT id, issue_id, ai_id, title, description, feature_area, priority, status, redmine_id, redmine_priority_name
        FROM epics WHERE generation_id = ? ORDER BY id
    """, (gen_id,))
    epics_rows = c.fetchall()

    epics = []
    for epic_row in epics_rows:
        epic_id = epic_row['id']

        # Get stories for this epic
        c.execute("""
            SELECT id, issue_id, ai_id, title, as_a, i_want, so_that, acceptance_criteria,
                   feature_area, size, priority, confidence, status, redmine_id, redmine_priority_name
            FROM stories WHERE generation_id = ? AND epic_id = ? ORDER BY id
        """, (gen_id, epic_id))
        stories_rows = c.fetchall()

        stories = []
        for story_row in stories_rows:
            story_id = story_row['id']

            # Get tasks for this story
            c.execute("""
                SELECT id, issue_id, ai_id, title, description, definition_of_done,
                       estimate_hours, dependencies, confidence, priority, status, assignee, redmine_id, redmine_priority_name,
                       test_cases
                FROM tasks WHERE generation_id = ? AND story_id = ? ORDER BY id
            """, (gen_id, story_id))
            tasks_rows = c.fetchall()

            tasks = [{
                "db_id": t['id'],
                "issue_id": t['issue_id'],
                "ai_id": t['ai_id'],
                "title": t['title'],
                "description": t['description'],
                "definition_of_done": t['definition_of_done'],
                "estimate_hours": t['estimate_hours'],
                "dependencies": json.loads(t['dependencies']) if t['dependencies'] else [],
                "confidence": t['confidence'],
                "priority": t['priority'],
                "status": t['status'],
                "assignee": t['assignee'],
                "redmine_id": t['redmine_id'],
                "redmine_priority_name": t['redmine_priority_name'],
                "test_cases": json.loads(t['test_cases']) if t['test_cases'] else []
            } for t in tasks_rows]

            ac = json.loads(story_row['acceptance_criteria']) if story_row['acceptance_criteria'] else []
            stories.append({
                "db_id": story_row['id'],
                "issue_id": story_row['issue_id'],
                "ai_id": story_row['ai_id'],
                "title": story_row['title'],
                "as_a": story_row['as_a'],
                "i_want": story_row['i_want'],
                "so_that": story_row['so_that'],
                "acceptance_criteria": ac,
                "feature_area": story_row['feature_area'],
                "size": story_row['size'],
                "priority": story_row['priority'],
                "confidence": story_row['confidence'],
                "status": story_row['status'],
                "redmine_id": story_row['redmine_id'],
                "redmine_priority_name": story_row['redmine_priority_name'],
                "tasks": tasks
            })

        epics.append({
            "db_id": epic_row['id'],
            "issue_id": epic_row['issue_id'],
            "ai_id": epic_row['ai_id'],
            "title": epic_row['title'],
            "description": epic_row['description'],
            "feature_area": epic_row['feature_area'],
            "priority": epic_row['priority'],
            "status": epic_row['status'],
            "redmine_id": epic_row['redmine_id'],
            "redmine_priority_name": epic_row['redmine_priority_name'],
            "stories": stories
        })

    conn.close()

    if not epics:
        return None

    return {"generation_id": gen_id, "epics": epics}


def delete_generation(gen_id: int) -> bool:
    """Delete a generation. Cascades to all related rows."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM generations WHERE id = ?", (gen_id,))
    conn.commit()
    deleted = c.rowcount > 0
    conn.close()
    return deleted


# Status/Priority update functions
def update_epic_status(epic_id: int, status: str) -> bool:
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE epics SET status = ? WHERE id = ?", (status, epic_id))
    conn.commit()
    updated = c.rowcount > 0
    conn.close()
    return updated


def update_story_status(story_id: int, status: str) -> bool:
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE stories SET status = ? WHERE id = ?", (status, story_id))
    conn.commit()
    updated = c.rowcount > 0
    conn.close()
    return updated


def update_task_status(task_id: int, status: str) -> bool:
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, task_id))
    conn.commit()
    updated = c.rowcount > 0
    conn.close()
    return updated


def update_task_assignee(task_id: int, assignee: str | None) -> bool:
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE tasks SET assignee = ? WHERE id = ?", (assignee, task_id))
    conn.commit()
    updated = c.rowcount > 0
    conn.close()
    return updated


def update_epic_priority(epic_id: int, priority: str) -> bool:
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE epics SET priority = ? WHERE id = ?", (priority, epic_id))
    conn.commit()
    updated = c.rowcount > 0
    conn.close()
    return updated


def update_story_priority(story_id: int, priority: str) -> bool:
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE stories SET priority = ? WHERE id = ?", (priority, story_id))
    conn.commit()
    updated = c.rowcount > 0
    conn.close()
    return updated


def update_task_priority(task_id: int, priority: str) -> bool:
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE tasks SET priority = ? WHERE id = ?", (priority, task_id))
    conn.commit()
    updated = c.rowcount > 0
    conn.close()
    return updated


def _update_content(table: str, row_id: int, fields: dict) -> bool:
    """Dynamic multi-column UPDATE for whichever fields were actually
    provided — the status/priority/assignee updaters above are all
    single-column, so this is the one genuinely new DB-layer pattern full
    content editing needs. An empty `fields` dict is treated as "just check
    the row exists" rather than a no-op success, so a PATCH with an empty
    body still 404s correctly on a bad id."""
    conn = get_connection()
    c = conn.cursor()
    if not fields:
        c.execute(f"SELECT 1 FROM {table} WHERE id = ?", (row_id,))
        exists = c.fetchone() is not None
        conn.close()
        return exists
    set_clause = ", ".join(f"{col} = ?" for col in fields)
    c.execute(f"UPDATE {table} SET {set_clause} WHERE id = ?", (*fields.values(), row_id))
    conn.commit()
    updated = c.rowcount > 0
    conn.close()
    return updated


def update_epic_content(epic_id: int, fields: dict) -> bool:
    """fields: any of title/description/feature_area."""
    return _update_content("epics", epic_id, fields)


def update_story_content(story_id: int, fields: dict) -> bool:
    """fields: any of title/as_a/i_want/so_that/acceptance_criteria
    (list[str], JSON-encoded here to match how it's stored)/feature_area."""
    fields = dict(fields)
    if "acceptance_criteria" in fields and fields["acceptance_criteria"] is not None:
        fields["acceptance_criteria"] = json.dumps(fields["acceptance_criteria"])
    return _update_content("stories", story_id, fields)


def update_task_content(task_id: int, fields: dict) -> bool:
    """fields: any of title/description/definition_of_done/estimate_hours/
    dependencies (list[str], JSON-encoded here to match how it's stored)."""
    fields = dict(fields)
    if "dependencies" in fields and fields["dependencies"] is not None:
        fields["dependencies"] = json.dumps(fields["dependencies"])
    return _update_content("tasks", task_id, fields)


def get_dashboard_stats() -> dict:
    """Get overall project statistics."""
    conn = get_connection()
    c = conn.cursor()

    c.execute("SELECT COUNT(*) as count FROM epics")
    total_epics = c.fetchone()['count']

    c.execute("SELECT COUNT(*) as count FROM stories")
    total_stories = c.fetchone()['count']

    c.execute("SELECT COUNT(*) as count FROM tasks")
    total_tasks = c.fetchone()['count']

    c.execute("""
        SELECT status, COUNT(*) as count FROM epics GROUP BY status
    """)
    epic_status = {row['status']: row['count'] for row in c.fetchall()}

    c.execute("""
        SELECT status, COUNT(*) as count FROM stories GROUP BY status
    """)
    story_status = {row['status']: row['count'] for row in c.fetchall()}

    c.execute("""
        SELECT status, COUNT(*) as count FROM tasks GROUP BY status
    """)
    task_status = {row['status']: row['count'] for row in c.fetchall()}

    c.execute("SELECT COUNT(*) as count FROM tasks WHERE assignee IS NULL")
    unassigned_tasks = c.fetchone()['count']

    conn.close()

    return {
        "total_epics": total_epics,
        "total_stories": total_stories,
        "total_tasks": total_tasks,
        "epic_status": epic_status,
        "story_status": story_status,
        "task_status": task_status,
        "unassigned_tasks": unassigned_tasks
    }


def get_all_projects() -> list[dict]:
    """Get all generations with epic/story/task counts."""
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
        SELECT g.id, g.created_at, g.project_name, g.metrics_json,
               COUNT(DISTINCT e.id) as epic_count,
               COUNT(DISTINCT s.id) as story_count,
               COUNT(DISTINCT t.id) as task_count,
               SUM(CASE WHEN t.status = 'done' THEN 1 ELSE 0 END) as done_tasks
        FROM generations g
        LEFT JOIN epics e ON g.id = e.generation_id
        LEFT JOIN stories s ON g.id = s.generation_id
        LEFT JOIN tasks t ON g.id = t.generation_id
        GROUP BY g.id
        ORDER BY g.created_at DESC
    """)
    rows = c.fetchall()
    conn.close()

    result = []
    for row in rows:
        metrics = json.loads(row['metrics_json']) if row['metrics_json'] else None
        result.append({
            'id': row['id'],
            'project_name': row['project_name'],
            'created_at': row['created_at'],
            'epic_count': row['epic_count'] or 0,
            'story_count': row['story_count'] or 0,
            'task_count': row['task_count'] or 0,
            'done_tasks': row['done_tasks'] or 0,
            'metrics': metrics
        })
    return result


def update_epic_redmine_id(db_id: int, redmine_id: int, redmine_priority_name: str | None = None) -> None:
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "UPDATE epics SET redmine_id = ?, redmine_priority_name = COALESCE(?, redmine_priority_name) WHERE id = ?",
        (redmine_id, redmine_priority_name, db_id),
    )
    conn.commit()
    conn.close()


def update_story_redmine_id(db_id: int, redmine_id: int, redmine_priority_name: str | None = None) -> None:
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "UPDATE stories SET redmine_id = ?, redmine_priority_name = COALESCE(?, redmine_priority_name) WHERE id = ?",
        (redmine_id, redmine_priority_name, db_id),
    )
    conn.commit()
    conn.close()


def update_task_redmine_id(db_id: int, redmine_id: int, redmine_priority_name: str | None = None) -> None:
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "UPDATE tasks SET redmine_id = ?, redmine_priority_name = COALESCE(?, redmine_priority_name) WHERE id = ?",
        (redmine_id, redmine_priority_name, db_id),
    )
    conn.commit()
    conn.close()
