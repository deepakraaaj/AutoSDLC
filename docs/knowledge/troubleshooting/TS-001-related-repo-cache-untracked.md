---
id: TS-001
title: Related repo cache appeared as untracked source files
date: 2026-08-28
status: resolved
area: repository hygiene
tags: [git, cache, related-repos]
---

# Related Repo Cache Appeared As Untracked Source Files

## TL;DR

The related-repo review feature creates persistent local Git clones under `app/services/related_repo_cache/`. During review, that cache showed up as untracked files, including an embedded `.git` directory. The fix was to ignore the cache path in the root `.gitignore` and keep the runtime clone out of the commit.

## Issue

After the related-repo context feature had been exercised, `git status` showed an untracked `app/services/related_repo_cache/` directory. The directory contained a real cloned repository metadata directory, so accidentally staging broad paths such as `app/services/` could have committed local cache state.

## Investigation

The status output showed:

```bash
?? app/services/related_repo_cache/
```

The directory was inspected before staging. It contained files such as:

```text
app/services/related_repo_cache/<hash>/.git/config
app/services/related_repo_cache/<hash>/.git/index
app/services/related_repo_cache/<hash>/.gitignore
```

That matched the behavior in `app/services/related_repo_context.py`: related repositories are cloned persistently and reused across PR reviews to avoid repeated Bitbucket API calls.

## Approaches Considered

One option was to delete the local cache manually before committing. That would clean the current worktree but would not prevent the same issue after the next related-repo review.

The better option was to add the runtime cache path to `.gitignore`, because the cache is generated local state and not source code.

## Chosen Approach

The root `.gitignore` now ignores:

```text
app/services/related_repo_cache/
```

This keeps persistent local clones available for development while preventing accidental commits.

## Root Cause

The related-repo review implementation introduced a persistent clone cache under the source tree, but the cache path was not ignored by Git.

## Fix & Verification

Updated `.gitignore` to ignore `app/services/related_repo_cache/`.

Verification:

```bash
git status --short
```

After the ignore rule, the runtime cache no longer appears as an untracked source change.

## Takeaway

When adding a persistent local cache, especially one that may contain nested Git repositories or downloaded source, add the ignore rule with the feature. Do not rely on developers remembering to avoid broad staging commands.
