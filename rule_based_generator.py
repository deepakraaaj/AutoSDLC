from __future__ import annotations

import re
from dataclasses import dataclass

from backlog_quality import normalize_task_dependencies
from schemas import Epic, GenerationOutput, Gap, Story, Task


# Validation thresholds for backlog depth
MIN_EPICS = 10
MIN_STORIES_PER_EPIC = 5
MIN_TASKS_PER_STORY = 4


@dataclass(frozen=True)
class TaskSpec:
    title: str
    description: str
    definition_of_done: str
    estimate_hours: str
    dependencies: list[str]
    priority: str | None = None
    confidence: str = "high"


@dataclass(frozen=True)
class StorySpec:
    title: str
    as_a: str
    i_want: str
    so_that: str
    acceptance_criteria: list[str]
    feature_area: str
    size: str
    priority: str
    tasks: list[TaskSpec]
    confidence: str = "high"


@dataclass(frozen=True)
class EpicSpec:
    title: str
    description: str
    feature_area: str
    priority: str
    stories: list[StorySpec]


def _task(
    title: str,
    description: str,
    definition_of_done: str,
    estimate_hours: str,
    dependencies: list[str],
    *,
    priority: str | None = None,
    confidence: str = "high",
) -> TaskSpec:
    return TaskSpec(
        title=title,
        description=description,
        definition_of_done=definition_of_done,
        estimate_hours=estimate_hours,
        dependencies=dependencies,
        priority=priority,
        confidence=confidence,
    )


def _story(
    title: str,
    as_a: str,
    i_want: str,
    so_that: str,
    acceptance_criteria: list[str],
    feature_area: str,
    size: str,
    priority: str,
    tasks: list[TaskSpec],
    *,
    confidence: str = "high",
) -> StorySpec:
    return StorySpec(
        title=title,
        as_a=as_a,
        i_want=i_want,
        so_that=so_that,
        acceptance_criteria=acceptance_criteria,
        feature_area=feature_area,
        size=size,
        priority=priority,
        tasks=tasks,
        confidence=confidence,
    )


STRUCTURE_MARKERS = (
    "## current capabilities",
    "## functional requirements",
    "## acceptance criteria",
    "## local setup",
    "## local redmine setup",
    "## known gaps and next work",
)


def looks_like_structured_brief(text: str) -> bool:
    normalized = text.lower()
    return sum(marker in normalized for marker in STRUCTURE_MARKERS) >= 4


BLUEPRINTS: list[EpicSpec] = [
    EpicSpec(
        title="Project Intake and Generation",
        description="Turn a project brief or chat prompt into a structured backlog.",
        feature_area="Generation",
        priority="critical",
        stories=[
            _story(
                "Enter project description",
                "project contributor",
                "to enter a project description in the chat tab",
                "I can start a generation from a plain prompt",
                [
                    "The chat tab accepts a free-form project description.",
                    "Submitting non-empty text starts the generation flow.",
                    "Empty text is rejected with a visible error.",
                ],
                "Generation",
                "small",
                "critical",
                [
                    _task(
                        "Build the chat input form and submit flow",
                        "Wire the text area, Generate button, and request submission for chat input.",
                        "A user can submit text from the chat tab and reach the generation pipeline.",
                        "4-6",
                        ["The generation endpoint is available."],
                    ),
                    _task(
                        "Validate non-empty text before dispatching generation",
                        "Reject blank input before the request is sent and show a visible validation message.",
                        "Empty submissions are blocked before generation starts.",
                        "2-4",
                        ["The chat input form exists."],
                    ),
                    _task(
                        "Add error handling for generation request failures",
                        "Catch and display readable error messages if the generation endpoint returns an error.",
                        "Generation failures show a user-friendly error message and allow retry.",
                        "2-3",
                        ["The submit flow is wired."],
                    ),
                    _task(
                        "Add loading state and disable button during generation",
                        "Show visual feedback while the request is in flight so users know not to resubmit.",
                        "The submit button is disabled and shows loading state during generation.",
                        "1-2",
                        ["The chat input form exists."],
                    ),
                ],
            ),
            _story(
                "Upload Markdown brief",
                "project contributor",
                "to upload a Markdown brief",
                "I can reuse existing documentation instead of rewriting it",
                [
                    "The upload surface accepts `.md` files.",
                    "Non-Markdown uploads are rejected with a visible error.",
                    "Empty files are rejected before generation starts.",
                ],
                "Generation",
                "small",
                "critical",
                [
                    _task(
                        "Add markdown file upload and file picker handling",
                        "Wire the upload tab so it can read a Markdown file and pass the contents forward.",
                        "A `.md` file can be selected and read from the upload tab.",
                        "4-6",
                        ["The upload tab is available."],
                    ),
                    _task(
                        "Reject invalid uploads before generation starts",
                        "Block non-Markdown and empty uploads with a readable error state.",
                        "Bad uploads fail locally before the backend generation call.",
                        "2-4",
                        ["File selection and validation are wired."],
                    ),
                    _task(
                        "Display selected file name and size to the user",
                        "Show which file has been selected and its size before upload.",
                        "The selected file is displayed with filename and size visible.",
                        "1-2",
                        ["File picker is available."],
                    ),
                    _task(
                        "Handle file read errors gracefully",
                        "Catch and display errors if file reading fails (permissions, encoding, etc).",
                        "File read errors show a readable error message.",
                        "2-3",
                        ["File upload is wired."],
                    ),
                ],
            ),
            _story(
                "Ask clarifying questions",
                "project contributor",
                "to answer clarifying questions before generation",
                "I can provide the missing detail the generator needs",
                [
                    "Vague input returns focused clarifying questions.",
                    "Each question includes why it matters.",
                    "Answers can be sent back for regeneration.",
                ],
                "Generation",
                "small",
                "high",
                [
                    _task(
                        "Render clarifying question cards and answer inputs",
                        "Show the clarifying questions and collect answers in the UI.",
                        "Questions appear with answer fields and explanatory text.",
                        "4-6",
                        ["Clarifying questions are returned from the generator."],
                    ),
                    _task(
                        "Resubmit generation with captured answers",
                        "Send the answers back alongside the original input and continue the flow.",
                        "The second-pass generation uses the collected clarifications.",
                        "2-4",
                        ["The clarifying question UI is working."],
                    ),
                    _task(
                        "Validate that all questions have been answered before allowing resubmission",
                        "Block resubmission if any required questions are left empty.",
                        "Resubmit button is disabled until all questions have answers.",
                        "1-2",
                        ["The clarifying question UI is present."],
                    ),
                    _task(
                        "Allow users to go back and edit their original input",
                        "Provide a button to return to the original input tab for editing.",
                        "Users can switch back to the input tab without losing their answers.",
                        "2-3",
                        ["The clarifying question UI is working."],
                    ),
                ],
            ),
            _story(
                "Stream generation progress and parse the response",
                "project contributor",
                "to see the generation stages and final JSON parse correctly",
                "I can tell whether the backend is still working and whether the output is valid",
                [
                    "The UI shows connecting, generating, parsing, and scoring stages.",
                    "Token chunks appear in the preview area.",
                    "Invalid JSON and provider errors are visible to the user.",
                ],
                "Generation",
                "medium",
                "high",
                [
                    _task(
                        "Emit SSE progress stages and token preview updates",
                        "Stream status events and token chunks so the UI can show live progress.",
                        "The progress box shows the expected states and token preview text.",
                        "4-6",
                        ["The generation request is streaming end to end."],
                    ),
                    _task(
                        "Parse the final JSON response and surface provider errors",
                        "Validate the final response and convert provider failures into readable UI errors.",
                        "Malformed JSON and provider errors are shown without crashing the page.",
                        "3-5",
                        ["SSE progress events are working."],
                    ),
                    _task(
                        "Show a progress indicator during token streaming",
                        "Display a spinner or progress bar while tokens are being received.",
                        "A visual progress indicator is shown during the generating stage.",
                        "2-3",
                        ["SSE progress events are working."],
                    ),
                    _task(
                        "Log errors to console for debugging provider issues",
                        "Write diagnostic information about failures to the browser console.",
                        "Provider errors and JSON parse failures are logged for debugging.",
                        "1-2",
                        ["The UI is handling errors."],
                    ),
                ],
            ),
            _story(
                "Persist completed generations",
                "project contributor",
                "to save completed generations for later reuse",
                "I can reload or export a result without rerunning the generator",
                [
                    "Completed generations are saved to SQLite.",
                    "Saved generations receive a `generation_id`.",
                    "Normalized rows are written for later updates.",
                ],
                "Generation",
                "medium",
                "high",
                [
                    _task(
                        "Save the raw output and metrics into `generations`",
                        "Persist the original input, generated JSON, and computed metrics.",
                        "Completed runs are visible in the generation history table.",
                        "3-5",
                        ["The generation output validates successfully."],
                    ),
                    _task(
                        "Normalize epics, stories, and tasks for later reloads",
                        "Write the generated hierarchy into relational tables with stable local IDs.",
                        "The normalized hierarchy can be queried back after generation.",
                        "4-6",
                        ["The raw generation record has been saved."],
                    ),
                    _task(
                        "Create database indexes for fast querying by generation_id",
                        "Add indexes on the foreign key columns to speed up lookups.",
                        "Queries by generation_id return results in <100ms for any size backlog.",
                        "2-4",
                        ["The normalized tables exist."],
                    ),
                    _task(
                        "Add created_at timestamp to all generations",
                        "Record when each generation was created for audit and sorting purposes.",
                        "The generations table includes a created_at timestamp column.",
                        "1-2",
                        ["The generations table exists."],
                    ),
                ],
            ),
        ],
    ),
    EpicSpec(
        title="Output Review and History",
        description="Help users inspect, copy, and revisit generated work.",
        feature_area="Review",
        priority="high",
        stories=[
            _story(
                "View generated hierarchy and metrics",
                "reviewer",
                "to inspect epics, stories, tasks, and the quality scorecard",
                "I can judge whether the output is ready to hand to a team",
                [
                    "Hierarchy and metrics are visible after generation.",
                    "Sprint summary shows stories, tasks, hours, and quality.",
                    "Gaps panel appears only when gaps exist.",
                ],
                "Review",
                "medium",
                "high",
                [
                    _task(
                        "Render epics, stories, tasks, and scorecards",
                        "Bind the generated data into the hierarchy and metrics panels.",
                        "The review surface shows the generated backlog and scorecard.",
                        "4-6",
                        ["A generation result exists."],
                    ),
                    _task(
                        "Render the sprint summary and gaps panel",
                        "Compute and display the summary chips plus the gaps list.",
                        "The summary and gaps sections match the generated result.",
                        "2-4",
                        ["The hierarchy view is present."],
                    ),
                    _task(
                        "Add color coding to priority levels in the hierarchy display",
                        "Use CSS colors to distinguish critical, high, medium, and low priorities.",
                        "Priority levels are visually distinct using the defined color scheme.",
                        "1-2",
                        ["The hierarchy view is rendering."],
                    ),
                    _task(
                        "Calculate and display total hours estimate from tasks",
                        "Sum the estimate_hours from all tasks and show in the summary.",
                        "The summary shows total estimated hours for the backlog.",
                        "2-3",
                        ["Task estimates are available."],
                    ),
                ],
            ),
            _story(
                "Expand, collapse, and copy items",
                "reviewer",
                "to quickly scan and share individual stories and tasks",
                "I can review the backlog without losing context",
                [
                    "Epic, story, and task cards expand and collapse.",
                    "Copy buttons place sanitized text on the clipboard.",
                    "Expand/collapse all toggles the visible cards.",
                ],
                "Review",
                "small",
                "high",
                [
                    _task(
                        "Add card collapse toggles and the global expand/collapse control",
                        "Implement the hierarchy card toggles and the all-cards control.",
                        "The hierarchy can be expanded or collapsed in one click.",
                        "3-5",
                        ["The hierarchy view is visible."],
                    ),
                    _task(
                        "Add clipboard copy actions for story and task cards",
                        "Copy story and task text with sanitized markup so it can be pasted elsewhere.",
                        "Copy buttons produce the expected text in the clipboard.",
                        "2-4",
                        ["The hierarchy cards render correctly."],
                    ),
                    _task(
                        "Preserve expand/collapse state in browser local storage",
                        "Remember which cards were expanded when the page is reloaded.",
                        "Card expansion state persists across page reloads.",
                        "2-3",
                        ["The expand/collapse toggles work."],
                    ),
                    _task(
                        "Add visual feedback when copy action succeeds",
                        "Show a brief success message or icon change when text is copied.",
                        "Successful copy shows a confirmation message or toast notification.",
                        "1-2",
                        ["Copy buttons exist."],
                    ),
                ],
            ),
            _story(
                "Browse, reload, and delete history",
                "reviewer",
                "to revisit previous generations and remove stale ones",
                "I can manage saved outputs without rerunning generation",
                [
                    "History list shows past generations.",
                    "Clicking a history item reloads the saved output.",
                    "Deleting removes the record from history.",
                ],
                "Review",
                "medium",
                "high",
                [
                    _task(
                        "Load past generations from `/history` and reload a selected item",
                        "Fetch the history list and restore a selected generation into the output panes.",
                        "A saved generation can be reopened from the history view.",
                        "3-5",
                        ["The history endpoint returns saved generations."],
                    ),
                    _task(
                        "Add delete handling for saved generations with confirmation",
                        "Remove a history item after an explicit user confirmation.",
                        "Users can delete a saved generation from the history view.",
                        "2-4",
                        ["The history list is visible."],
                    ),
                    _task(
                        "Sort history by creation date with newest first",
                        "Display history items sorted by created_at timestamp in descending order.",
                        "History list shows newest generations at the top.",
                        "1-2",
                        ["The history endpoint returns generations with timestamps."],
                    ),
                    _task(
                        "Add search or filter by project name in history",
                        "Allow users to search for past generations by project name.",
                        "Users can filter history by typing project name.",
                        "3-4",
                        ["The history list is displaying."],
                    ),
                ],
            ),
            _story(
                "Show sprint summary and quality notes",
                "reviewer",
                "to review the high-level delivery summary and confidence notes",
                "I can see the readiness of the generated sprint at a glance",
                [
                    "Summary shows story count, task count, hours, and quality.",
                    "Confidence summary is visible.",
                    "Quality notes reflect the generated metrics.",
                ],
                "Review",
                "small",
                "medium",
                [
                    _task(
                        "Compute summary chips from stories, tasks, and estimates",
                        "Aggregate the counts and total hours for the sprint summary area.",
                        "The summary chips reflect the generated backlog.",
                        "2-4",
                        ["The generated data is available in the review view."],
                    ),
                    _task(
                        "Show confidence and quality notes from metrics",
                        "Render the confidence summary and supporting notes from the computed metrics.",
                        "The scorecard includes a readable readiness note.",
                        "2-4",
                        ["Metrics have been computed for the generation."],
                    ),
                    _task(
                        "Display individual metric scores (specificity, testability, sizing, etc)",
                        "Render detailed scores for story and task quality dimensions.",
                        "Individual metric scores are visible in the metrics panel.",
                        "2-3",
                        ["Metrics have been computed."],
                    ),
                    _task(
                        "Highlight low-quality areas that need attention",
                        "Call out metrics below 70 with a warning color or icon.",
                        "Low-quality dimensions are visually highlighted.",
                        "2-3",
                        ["Metrics are being displayed."],
                    ),
                ],
            ),
        ],
    ),
    EpicSpec(
        title="Tracking and Persistence",
        description="Keep generated work stateful and editable after creation.",
        feature_area="Tracking",
        priority="high",
        stories=[
            _story(
                "Update epic, story, and task statuses",
                "delivery lead",
                "to move work items through planned, review, testing, and done states",
                "I can keep the generated backlog aligned with actual progress",
                [
                    "Status changes persist for epics, stories, and tasks.",
                    "Allowed statuses are validated.",
                    "Changes survive refresh.",
                ],
                "Tracking",
                "small",
                "high",
                [
                    _task(
                        "Add PATCH endpoints for status updates",
                        "Expose backend endpoints for epic, story, and task status changes.",
                        "Status changes can be saved through the API.",
                        "3-5",
                        ["The normalized hierarchy tables exist."],
                    ),
                    _task(
                        "Wire hierarchy dropdowns to persist status changes",
                        "Connect the UI dropdowns to the status endpoints and refresh the view after save.",
                        "Status changes are visible after a reload.",
                        "3-5",
                        ["The status endpoints are available."],
                    ),
                    _task(
                        "Add optimistic UI updates for status changes",
                        "Update the UI immediately before server confirmation for better UX.",
                        "Status changes appear immediately in the UI.",
                        "2-3",
                        ["Status endpoints exist."],
                    ),
                    _task(
                        "Show error notification if status update fails on server",
                        "Display an error message and revert UI if the server rejects the change.",
                        "Failed status updates show an error message and roll back.",
                        "2-3",
                        ["Status endpoints exist."],
                    ),
                ],
            ),
            _story(
                "Assign tasks to people",
                "delivery lead",
                "to attach owners to individual implementation tasks",
                "I can coordinate work without leaving the app",
                [
                    "Assignee changes are saved.",
                    "Clearing assignee stores null.",
                    "Assignments survive refresh.",
                ],
                "Tracking",
                "small",
                "medium",
                [
                    _task(
                        "Add task assignee persistence in the database and API",
                        "Store assignee updates for task records through a dedicated endpoint.",
                        "A task owner can be written and cleared through the API.",
                        "2-4",
                        ["The task table includes an assignee column."],
                    ),
                    _task(
                        "Wire the assignee input to update on blur",
                        "Push task assignee edits from the hierarchy UI when the field loses focus.",
                        "The UI updates task owners without a full page refresh.",
                        "2-4",
                        ["The assignee endpoint is available."],
                    ),
                    _task(
                        "Add autocomplete for team member names when assigning",
                        "Provide a dropdown list of known team members while typing assignee name.",
                        "Autocomplete suggestions appear while editing assignee field.",
                        "2-3",
                        ["Team member list is available."],
                    ),
                    _task(
                        "Show which tasks are assigned to each person",
                        "Add a filter or summary view showing all tasks assigned to a specific person.",
                        "Users can see all tasks assigned to a team member.",
                        "2-3",
                        ["Assignee data is being stored."],
                    ),
                ],
            ),
            _story(
                "Persist normalized hierarchy and Redmine IDs",
                "delivery lead",
                "to keep the generated hierarchy queryable and linked to external issues",
                "I can track the same item locally and in Redmine",
                [
                    "Hierarchy rows remain queryable by generation.",
                    "Redmine IDs are stored locally.",
                    "Reloaded hierarchy shows updated metadata.",
                ],
                "Tracking",
                "medium",
                "high",
                [
                    _task(
                        "Store normalized rows for epics, stories, and tasks",
                        "Write generated items into relational tables with stable local IDs.",
                        "The normalized hierarchy can be queried after generation.",
                        "3-5",
                        ["A generation result has been saved."],
                    ),
                    _task(
                        "Update local rows with returned Redmine IDs after push",
                        "Persist external issue IDs after a Redmine push succeeds.",
                        "Local rows show the created Redmine issue IDs.",
                        "2-4",
                        ["The Redmine push flow returns issue IDs."],
                    ),
                    _task(
                        "Add foreign key constraints between epics, stories, and tasks",
                        "Enforce referential integrity in the database schema.",
                        "Database enforces parent-child relationships via constraints.",
                        "2-3",
                        ["Normalized tables exist."],
                    ),
                    _task(
                        "Create a view that shows the full hierarchy with all IDs",
                        "Build a database view for easy querying of the entire hierarchy.",
                        "A single SQL query can fetch the full hierarchy for a generation.",
                        "3-4",
                        ["Normalized tables have been populated."],
                    ),
                ],
            ),
        ],
    ),
    EpicSpec(
        title="Export and Redmine Integration",
        description="Export generated work and push it into Redmine.",
        feature_area="Integrations",
        priority="critical",
        stories=[
            _story(
                "Export the plan to Excel",
                "delivery lead",
                "to download the generated backlog as a spreadsheet",
                "I can share the plan with stakeholders who prefer Excel",
                [
                    "XLSX download is available from the UI.",
                    "The workbook includes epics, stories, and tasks sheets.",
                    "Text is wrapped and formatted.",
                ],
                "Integrations",
                "small",
                "high",
                [
                    _task(
                        "Build the workbook writer for epics, stories, and tasks",
                        "Create a formatted Excel workbook with separate sheets for each hierarchy level.",
                        "The workbook matches the generated backlog structure.",
                        "4-6",
                        ["A generated backlog is available."],
                    ),
                    _task(
                        "Expose the download endpoint and UI action",
                        "Wire the export button to the file download endpoint.",
                        "Users can click Export and receive the workbook.",
                        "2-4",
                        ["The workbook writer is available."],
                    ),
                    _task(
                        "Add dependency tracking sheet to Excel workbook",
                        "Include a separate sheet showing task dependencies and their relationships.",
                        "The Excel workbook includes a dependencies sheet.",
                        "2-3",
                        ["The workbook writer is available."],
                    ),
                    _task(
                        "Validate backlog depth before allowing Excel export",
                        "Block export if backlog doesn't meet minimum counts (10 epics, 5 stories/epic, 4 tasks/story).",
                        "Export is blocked for shallow backlogs with an explanatory error message.",
                        "2-3",
                        ["The backlog validation function exists."],
                    ),
                ],
            ),
            _story(
                "Load Redmine workspace and create projects",
                "delivery lead",
                "to see the available Redmine projects and create a new one when needed",
                "I can set up the target workspace before pushing issues",
                [
                    "Nested project options load successfully.",
                    "Missing tracker and custom field warnings are shown.",
                    "New projects can be created from the modal.",
                ],
                "Integrations",
                "medium",
                "high",
                [
                    _task(
                        "List nested Redmine projects and workspace defaults",
                        "Read the Redmine workspace and surface project and tracker metadata.",
                        "The modal shows nested projects and readiness warnings.",
                        "4-6",
                        ["Valid Redmine credentials are configured."],
                    ),
                    _task(
                        "Add the create-project modal and API call",
                        "Create the project creation form and call the backend create endpoint.",
                        "A new Redmine project can be created from the UI.",
                        "3-5",
                        ["The workspace list is loaded."],
                    ),
                    _task(
                        "Validate Redmine tracker types exist before project creation",
                        "Check that Epic, Story, and Task trackers are present in the workspace.",
                        "User sees warning if required trackers are missing.",
                        "2-3",
                        ["Tracker metadata is available from Redmine."],
                    ),
                    _task(
                        "Add project parent selection for creating sub-projects",
                        "Allow selecting a parent project when creating nested projects.",
                        "Users can create sub-projects under existing parent projects.",
                        "2-3",
                        ["Workspace projects are loaded."],
                    ),
                ],
            ),
            _story(
                "Push generated backlog to Redmine",
                "delivery lead",
                "to create the generated hierarchy as Redmine issues",
                "I can move from planning to execution without retyping the backlog",
                [
                    "Redmine issues are created with parent-child relationships.",
                    "Issue URLs are shown to the user.",
                    "Warnings and failures are surfaced per issue.",
                ],
                "Integrations",
                "medium",
                "critical",
                [
                    _task(
                        "Map epics, stories, and tasks to Redmine payloads and parent links",
                        "Build the issue mapping and parent-child relationships for Redmine creation.",
                        "The generated hierarchy can be transformed into Redmine payloads.",
                        "4-6",
                        ["The Redmine project target is configured."],
                    ),
                    _task(
                        "Show created links, warnings, and persist returned IDs",
                        "Render push results and store the returned Redmine IDs locally.",
                        "The push modal shows links, warnings, and local IDs are updated.",
                        "3-5",
                        ["The Redmine issue mapping is working."],
                    ),
                    _task(
                        "Handle and retry failed issue creation",
                        "Allow retrying individual failed issues without recreating all issues.",
                        "Users can retry failed issue creations without losing progress.",
                        "3-4",
                        ["The Redmine push flow is implemented."],
                    ),
                    _task(
                        "Show summary of push results (created, failed, skipped)",
                        "Display a summary report of which issues were created and which failed.",
                        "Push result summary shows count of created, failed, and skipped issues.",
                        "2-3",
                        ["The push results are being processed."],
                    ),
                ],
            ),
        ],
    ),
    EpicSpec(
        title="Local Operations and Quality",
        description="Make the app easy to run locally and robust under failure.",
        feature_area="Operations",
        priority="medium",
        stories=[
            _story(
                "Run locally with environment config",
                "developer",
                "to start the app with a small set of environment variables",
                "I can get the service running quickly on my machine",
                [
                    "The app starts with the documented command.",
                    "Env variables configure the provider and Redmine.",
                    "The health endpoint returns provider status.",
                ],
                "Operations",
                "small",
                "medium",
                [
                    _task(
                        "Document startup steps and required env variables",
                        "Keep the local setup instructions and `.env` example aligned with the app behavior.",
                        "A new developer can start the app using the documented steps.",
                        "2-4",
                        ["The backend command works locally."],
                    ),
                    _task(
                        "Expose `/health` and provider status",
                        "Return a lightweight health response that includes the selected provider.",
                        "Readiness checks can confirm the app is alive.",
                        "1-2",
                        ["The app is running."],
                    ),
                    _task(
                        "Validate all required environment variables on startup",
                        "Check that required env vars are set before the app starts, fail fast if missing.",
                        "Missing env vars cause clear error messages at startup.",
                        "1-2",
                        ["The app has environment configuration."],
                    ),
                    _task(
                        "Create a .env.example template file",
                        "Provide a template showing all required and optional environment variables.",
                        ".env.example file exists with all variable templates.",
                        "1-2",
                        ["Documentation is available."],
                    ),
                ],
            ),
            _story(
                "Provision the local Redmine stack",
                "developer",
                "to bring up Redmine and its seed data locally",
                "I can test the integration without depending on a remote server",
                [
                    "Redmine and Postgres start locally.",
                    "Epic, Story, and Task trackers are seeded.",
                    "Project provisioning is repeatable.",
                ],
                "Operations",
                "small",
                "medium",
                [
                    _task(
                        "Keep the Docker Compose and tracker seeding flow working",
                        "Maintain the local Redmine stack and the seeding script so the environment is reproducible.",
                        "The local Redmine environment starts with the expected trackers.",
                        "3-5",
                        ["Docker is available locally."],
                    ),
                    _task(
                        "Document project provisioning and API key setup",
                        "Explain how to seed the sample project and where to get the Redmine API key.",
                        "The local Redmine workflow is repeatable from the docs.",
                        "1-2",
                        ["The Redmine stack is running."],
                    ),
                    _task(
                        "Add health check to Docker Compose for Redmine readiness",
                        "Ensure the docker-compose waits until Redmine is ready before returning.",
                        "Docker Compose startup waits for Redmine to be ready.",
                        "2-3",
                        ["Docker Compose is configured."],
                    ),
                    _task(
                        "Document how to reset the local Redmine database",
                        "Provide commands to clear and reseed the local Redmine stack.",
                        "Developers can reset Redmine data from documented commands.",
                        "1-2",
                        ["Redmine seeding is documented."],
                    ),
                ],
            ),
            _story(
                "Surface backend and provider errors clearly",
                "developer",
                "to see readable failures when something goes wrong",
                "I can debug provider and API issues without guessing",
                [
                    "Provider failures show a readable message.",
                    "File and API errors are surfaced in the UI.",
                    "The UI remains usable after a failure.",
                ],
                "Operations",
                "small",
                "medium",
                [
                    _task(
                        "Map provider and API failures into readable UI errors",
                        "Convert backend and provider exceptions into messages that are safe for the browser.",
                        "Failures no longer crash the generation flow.",
                        "2-4",
                        ["The SSE generation flow is running."],
                    ),
                    _task(
                        "Keep the progress UI responsive during failures",
                        "Ensure the progress box and buttons recover cleanly after errors.",
                        "Users can retry after a failure without reloading the page.",
                        "1-2",
                        ["Readable error messages are available."],
                    ),
                    _task(
                        "Log full error details to server logs for debugging",
                        "Write complete error stack traces to server logs while showing sanitized messages to users.",
                        "Server logs contain full error details for debugging.",
                        "2-3",
                        ["Error handling is in place."],
                    ),
                    _task(
                        "Add error recovery instructions in UI messages",
                        "Suggest actions users can take to resolve common errors (retry, check config, etc).",
                        "Error messages include recovery instructions when applicable.",
                        "2-3",
                        ["Error messages are being displayed."],
                    ),
                ],
            ),
            _story(
                "Add automated tests and smoke checks",
                "developer",
                "to keep the core flows from regressing",
                "I can trust the deterministic compiler, Redmine integration, and UI interactions",
                [
                    "Core flows are covered by regression tests.",
                    "Redmine API calls are mocked in tests.",
                    "Browser smoke paths cover history and hierarchy updates.",
                ],
                "Operations",
                "medium",
                "medium",
                [
                    _task(
                        "Add regression coverage for the parser and generation flow",
                        "Write unit tests for the structured brief compiler and the generation path.",
                        "The deterministic compiler has automated coverage.",
                        "3-5",
                        ["The structured brief compiler exists."],
                    ),
                    _task(
                        "Add mocked Redmine and browser smoke coverage",
                        "Cover the Redmine API contract and the most important browser interactions.",
                        "The major integration paths are exercised in tests.",
                        "3-5",
                        ["The generation flow is testable."],
                    ),
                    _task(
                        "Add test coverage for backlog validation rules",
                        "Test the validate_backlog_depth function with shallow and valid outputs.",
                        "Validation function has test coverage for all edge cases.",
                        "2-3",
                        ["Validation function exists."],
                    ),
                    _task(
                        "Set up CI/CD pipeline to run tests on every commit",
                        "Configure GitHub Actions or similar to run tests automatically.",
                        "Tests run automatically on pull requests and commits.",
                        "3-4",
                        ["Tests are available."],
                    ),
                ],
            ),
        ],
    ),
]


def _build_story(story_spec: StorySpec, epic_id: str, story_id: str, task_counter: list[int]) -> tuple[Story, list[Task]]:
    story = Story(
        id=story_id,
        title=story_spec.title,
        as_a=story_spec.as_a,
        i_want=story_spec.i_want,
        so_that=story_spec.so_that,
        acceptance_criteria=story_spec.acceptance_criteria,
        feature_area=story_spec.feature_area,
        size=story_spec.size,
        confidence=story_spec.confidence,
        epic_id=epic_id,
        priority=story_spec.priority,
        status="planned",
    )

    tasks: list[Task] = []
    for task_spec in story_spec.tasks:
        task_counter[0] += 1
        task_id = f"T{task_counter[0]}"
        task_priority = task_spec.priority or story_spec.priority
        tasks.append(
            Task(
                id=task_id,
                title=task_spec.title,
                description=task_spec.description,
                definition_of_done=task_spec.definition_of_done,
                estimate_hours=task_spec.estimate_hours,
                dependencies=task_spec.dependencies,
                story_id=story_id,
                confidence=task_spec.confidence,
                priority=task_priority,
                status="todo",
                assignee=None,
            )
        )

    return story, tasks


def generate_rule_based_output(text: str) -> GenerationOutput:
    if not looks_like_structured_brief(text):
        raise ValueError("Input does not look like the structured AutoSDLC brief.")

    epics: list[Epic] = []
    stories: list[Story] = []
    tasks: list[Task] = []

    story_counter = [0]
    task_counter = [0]

    for epic_index, epic_spec in enumerate(BLUEPRINTS, start=1):
        epic_id = f"E{epic_index}"
        epics.append(
            Epic(
                id=epic_id,
                title=epic_spec.title,
                description=epic_spec.description,
                feature_area=epic_spec.feature_area,
                priority=epic_spec.priority,
                status="planned",
            )
        )

        for story_spec in epic_spec.stories:
            story_counter[0] += 1
            story_id = f"S{story_counter[0]}"
            story, story_tasks = _build_story(story_spec, epic_id, story_id, task_counter)
            stories.append(story)
            tasks.extend(story_tasks)

    output = GenerationOutput(
        needs_clarification=False,
        clarifying_questions=[],
        epics=epics,
        stories=stories,
        tasks=tasks,
        gaps=[],
        metrics=None,
    )
    normalize_task_dependencies(output)
    return output


def validate_backlog_depth(output: GenerationOutput) -> list[str]:
    """Validate backlog has sufficient depth. Returns list of error messages (empty = valid)."""
    errors: list[str] = []

    if len(output.epics) < MIN_EPICS:
        errors.append(f"Too few epics: {len(output.epics)} (minimum {MIN_EPICS})")

    stories_by_epic: dict[str, int] = {}
    for s in output.stories:
        if s.epic_id:
            stories_by_epic[s.epic_id] = stories_by_epic.get(s.epic_id, 0) + 1

    for epic in output.epics:
        cnt = stories_by_epic.get(epic.id, 0)
        if cnt < MIN_STORIES_PER_EPIC:
            errors.append(f"Epic {epic.id} '{epic.title}': {cnt} stories (min {MIN_STORIES_PER_EPIC})")

    tasks_by_story: dict[str, int] = {}
    for t in output.tasks:
        if t.story_id:
            tasks_by_story[t.story_id] = tasks_by_story.get(t.story_id, 0) + 1

    for story in output.stories:
        cnt = tasks_by_story.get(story.id, 0)
        if cnt < MIN_TASKS_PER_STORY:
            errors.append(f"Story {story.id} '{story.title}': {cnt} tasks (min {MIN_TASKS_PER_STORY})")

    return errors
