# Local Redmine Stack

This folder contains the local Redmine install plus a repeatable template flow for creating many projects from the same baseline.

## What it runs

- Redmine: `redmine:6.1.2-alpine3.23`
- Database: `postgres:16.13-alpine3.23`
- Host port: `3001` by default

## Start

```bash
cd /home/deepakrajb/Desktop/AutoSDLC-1/story-generator/redmine-local
docker compose up -d
```

Open:

```text
http://localhost:3001
```

Default login:

- User: `admin`
- Password: `admin`

Change the password immediately after logging in.

## Template flow

The Redmine REST API can create projects, versions, issue categories, and memberships.
It does not expose tracker or issue custom field creation, so this template flow seeds the
`Epic`, `Story`, and `Task` trackers plus the shared issue custom fields locally with
Redmine's Rails runner, then uses `curl` for the REST calls.

### Template file

Edit [projects.template.json](projects.template.json) to add as many projects as you want.
Each entry inherits the defaults, so you only need to change the name and identifier for most projects.

### Provision

```bash
export REDMINE_URL=http://localhost:3001
export REDMINE_API_KEY=<your-redmine-api-key>
python3 provision_projects.py --template projects.template.json
```

The script will:

- seed the `Epic`, `Story`, and `Task` trackers if they do not exist
- seed the shared issue custom fields if they do not exist
- create every project listed in the template
- attach the configured trackers to each project
- create issue categories for each project
- create versions for each project

Those custom fields are global Redmine issue fields, so they are created once and then reused by every project.

## App integration

Set these values in the story-generator environment:

```bash
REDMINE_URL=http://localhost:3001
REDMINE_API_KEY=<your-redmine-api-key>
REDMINE_PROJECT_ID=autosdlc-template
REDMINE_EPIC_TRACKER_ID=Epic
REDMINE_STORY_TRACKER_ID=Story
REDMINE_TASK_TRACKER_ID=Task
```

`REDMINE_PROJECT_ID` can be either the numeric project id or the project identifier.
The app resolves the identifier to the numeric id before creating issues.

## Stop

```bash
docker compose down
```

To remove data as well:

```bash
docker compose down -v
```

## Notes

- Data is stored in Docker volumes, so it persists across restarts.
- The Redmine image can auto-create and migrate its schema on startup.
- The provisioning script is idempotent for tracker and issue custom field seeding, but project creation will fail if a project identifier already exists.
- If you want more projects, add more objects to `projects.template.json` and rerun the provisioning command.
