---
description: Create an atomic, well-tagged commit for all uncommitted changes. Updates TODO.md if a task was completed.
---

# Commit: Create Atomic Git Commit

## Step 1: Review Changes

```bash
git status
git diff HEAD
git status --porcelain
```

## Step 2: Check TODO.md

Does any of the changed code complete a `[ ]` task in `TODO.md`?
If yes → mark it `[x]` before committing.

## Step 3: Stage All Changes

```bash
git add -A
```

## Step 4: Determine Commit Type

| Prefix | When to use |
|--------|-------------|
| `feat:` | New feature or capability |
| `fix:` | Bug fix |
| `chore:` | Dependency update, config change |
| `refactor:` | Code restructure, no behavior change |
| `docs:` | Documentation only |
| `test:` | Test additions or fixes |
| `ci:` | GitHub Actions / workflow changes |
| `db:` | Schema changes, migrations |
| `pipeline:` | Auction pipeline stage changes |

## Step 5: Commit

Write a concise, descriptive message:

```bash
git commit -m "[type]: [concise description]

- [key change 1]
- [key change 2]
- [key change 3 if needed]"
```

**Rules:**
- First line: 50 chars max, imperative mood ("add", "fix", "update" — not "added", "fixed")
- Body: bullet list of what changed and why
- If closes a TODO item: add `Closes: [task name]`

## Step 6: Push

```bash
git push origin main
```

## Step 7: Log to Supabase

```bash
psql "$DATABASE_URL" -c "
INSERT INTO insights (task, status, message, created_at)
VALUES ('git-commit', 'COMPLETED', '$(git log -1 --pretty=%s)', NOW())" 2>/dev/null || true
```

## Output

```
## Committed

**Hash:** [short hash]
**Message:** [commit message]
**Files:** [N files changed, X insertions, Y deletions]
**Branch:** main → pushed

[If TODO updated:]
**TODO.md:** [task name] marked [x]
```
