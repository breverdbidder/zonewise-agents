---
description: Execute an implementation plan from .agents/plans/. Implements tasks in order, validates each step, updates TODO.md on completion.
argument-hint: [path-to-plan]
---

# Execute: Implement from Plan

## Plan: $ARGUMENTS

---

## Execution Rules

1. Read the ENTIRE plan before touching any file
2. Validate patterns by reading referenced files at the specified lines
3. Execute tasks in exact order (dependencies matter)
4. Run each task's VALIDATE command before moving to next
5. Never skip validation
6. If a task fails after 3 attempts → log to insights table and surface to Ariel

---

## Pre-execution Checklist

- [ ] Read full plan
- [ ] Read all MANDATORY READING files
- [ ] Confirm dev server is not needed for this (or start it)
- [ ] Confirm Supabase connection: `psql "$DATABASE_URL" -c "SELECT 1"`
- [ ] Check current git status: `git status`

---

## Execution Loop

For EACH task in "STEP-BY-STEP TASKS":

### a. Read task fully

Understand: file, action, imports, gotchas, validation command.

### b. Read existing file (if modifying)

Never modify a file you haven't read. Use Read tool first.

### c. Implement

- Follow the pattern from the referenced file exactly
- Match naming conventions (camelCase TS, snake_case Python/SQL)
- Add Supabase insights logging on error:
  ```typescript
  await supabase.from('insights').insert({
    task: '[task name]',
    status: 'ERROR',
    message: error.message
  })
  ```
- Include proper TypeScript types (no `any`)

### d. Validate immediately

Run the task's VALIDATE command. If it fails:
1. Fix the issue
2. Re-run
3. Do not proceed until passing

### e. Check types

```bash
npx tsc --noEmit
```

---

## After All Tasks Complete

### Run Full Validation Suite

```bash
# 1. Lint
npm run lint

# 2. Types
npx tsc --noEmit

# 3. Unit tests
npm run test:run

# 4. DB validation (from plan's VALIDATION COMMANDS)
psql "$DATABASE_URL" -c "[plan's verification query]"
```

### Update TODO.md

Find the task in `TODO.md` that corresponds to this plan.
Mark it complete:
```
[x] [task description]  ← was [ ]
```

Commit the TODO.md update along with implementation.

### Log Success to Supabase

```bash
psql "$DATABASE_URL" -c "
INSERT INTO insights (task, status, message, created_at)
VALUES ('claude-code-execute', 'COMPLETED', 'Implemented: [feature name]', NOW())"
```

---

## Commit

```bash
git add -A
git commit -m "feat: [concise description from plan]

- [key change 1]
- [key change 2]
- Closes TODO: [task name]"
git push origin main
```

---

## Output Report

```
## Execution Complete: [Feature Name]

### Tasks Completed
- [ task 1 ] — [files changed]
- [ task 2 ] — [files changed]

### Files Created
- [path] — [purpose]

### Files Modified
- [path] — [what changed]

### Validation Results
✅ Lint: passed
✅ Types: passed
✅ Unit tests: [N] passed
✅ DB verification: [result]

### TODO.md
[x] [task] marked complete and pushed

### Next Step
→ Run `/e2e-test` to validate UI journeys before Render deploy
```

---

## Escalation (if blocked after 3 attempts)

```
BLOCKED: [specific issue]
Tried:
1. [attempt 1 + result]
2. [attempt 2 + result]
3. [attempt 3 + result]
Recommend: [suggested solution]
Approve?
```

Log to Supabase insights table with `status='BLOCKED'` before surfacing to Ariel.
