---
description: Create a comprehensive implementation plan with deep codebase analysis. Outputs to .agents/plans/. No code is written in this phase.
argument-hint: [feature description]
---

# Plan Feature: $ARGUMENTS

## Core Principle

**No code in this phase.** Create a context-rich plan that enables one-pass implementation by Claude Code.
Context is king — the plan must contain ALL information needed so execution succeeds on first attempt.

## Planning Process

### Phase 1: Feature Understanding

Extract:
- Core problem being solved
- User value / business impact
- Feature type: New Capability / Enhancement / Bug Fix / Refactor
- Complexity: Low / Medium / High
- Affected systems (pipeline stages, UI components, Supabase tables)

User story format:
```
As a [BidDeed investor / ZoneWise user / Ariel]
I want to [action]
So that [benefit]
```

### Phase 2: Codebase Intelligence (Parallel Sub-agents)

Launch 3 sub-agents simultaneously:

**Sub-agent A: Structure & Patterns**
- Detect framework, runtime, key entry points
- Find similar existing implementations to mirror
- Extract naming conventions, error handling patterns
- Check CLAUDE.md for project-specific rules
- Read TODO.md for related pending work

**Sub-agent B: Data Layer**
- Find relevant Supabase tables and schema
- Identify Drizzle models or SQL files to reference
- Map API routes affected by this feature
- Identify RLS policies that may affect the feature

**Sub-agent C: Dependencies & Docs**
- Find relevant npm packages or Python libraries already in use
- Check `src/lib/`, `src/utils/`, `scripts/` for existing utilities
- Identify test patterns in `tests/` or `*.test.ts` files

Wait for all three before proceeding.

### Phase 3: Design Decisions

Think through:
- How does this fit the 12-stage Everest Ascent pipeline?
- What Supabase tables need new columns or new records?
- Does this affect the nightly GitHub Actions workflow?
- Does this affect any LangGraph agent handoffs?
- What could break? (edge cases, null judgments, missing BCPAO photos, rate limits)
- Performance implications at 67 counties / 2K auctions/day scale?

### Phase 4: Generate Plan

**Output file:** `.agents/plans/[kebab-case-name].md`

Create plan with this structure:

```markdown
# Feature: [name]

Read this entire plan before writing a single line of code.
Check referenced files and validate patterns before implementing.

## Feature Description
[What it does and why]

## User Story
As a [user]
I want to [action]
So that [benefit]

## Complexity: [Low/Medium/High]
## Pipeline Stage Affected: [1-12 or N/A]
## Supabase Tables Affected: [list]

---

## MANDATORY READING — Read Before Implementing

### Codebase Files
- `path/to/file.ts` (lines X-Y) — Why: [pattern to mirror]
- `src/db/schema.ts` — Why: [table definitions to extend]
- `.github/workflows/nightly.yml` — Why: [pipeline integration point]

### New Files to Create
- `path/to/new-file.ts` — [purpose]

### Documentation
- [Link] — [why relevant]

---

## Patterns to Follow

[Extract actual code snippets from the codebase showing the pattern]

**Supabase insert pattern:**
```typescript
// From src/lib/db.ts lines 45-60
```

**Error logging pattern:**
```typescript
// Always log to insights table on error
await supabase.from('insights').insert({ task: '...', status: 'ERROR', message: err.message })
```

---

## STEP-BY-STEP TASKS

### TASK 1: [Action] [target file]
- **IMPLEMENT:** [specific detail]
- **PATTERN:** [file:line to mirror]
- **IMPORTS:** [exact imports needed]
- **GOTCHA:** [known issue or constraint]
- **VALIDATE:** `npm run test:run -- [test-file]`

### TASK 2: ...

[Continue for all tasks in dependency order]

---

## TESTING STRATEGY

### Unit Tests
[What to test, test file location, test framework]

### Integration Tests
[Supabase data validation queries]

### E2E Validation
[agent-browser steps to manually verify UI]

---

## VALIDATION COMMANDS

```bash
# Syntax & types
npm run lint && npx tsc --noEmit

# Unit tests
npm run test:run

# DB validation
psql "$DATABASE_URL" -c "[verification query]"

# GitHub Actions (if pipeline change)
# Trigger manually and check insights table
```

---

## ACCEPTANCE CRITERIA

- [ ] Feature implements all specified functionality
- [ ] All unit tests pass
- [ ] Supabase records verified via psql
- [ ] No regression in existing pipeline stages
- [ ] insights table logs successful run
- [ ] CLAUDE.md patterns followed
- [ ] TODO.md task marked [x]

---

## CONFIDENCE SCORE: [X]/10

[Reason for score — what uncertainty remains]
```

---

## Output

After creating the plan file:

1. Confirm path: `.agents/plans/[name].md`
2. Confidence score for one-pass implementation
3. Any blockers or missing information
4. Next step: run `/execute .agents/plans/[name].md`
