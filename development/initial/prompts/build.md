# Initial Build Prompt — Initial Implementation

> **Loop state:** The `## Loop State` block prepended above this prompt is auto-injected fresh each iteration by the loop runner. Read it before anything else — it tells you progress %, which units are in-progress (resume those first), the next unit to start, and any blocked units that need re-evaluation.

## 0. Sources of truth

Read before each unit; spec wins on behavior conflicts:

- **Spec:** [development/initial/spec/spec.md](development/initial/spec/spec.md)
- **Plan:** [development/initial/plan/full-implementation-plan.md](development/initial/plan/full-implementation-plan.md)
- **Project standards:** [CLAUDE.md](CLAUDE.md) — UI/frontend work binds to these standards.
- **Operational:** [AGENTS.md](AGENTS.md) — run/build/test commands.


## 1. Task

Implement Initial unit-by-unit per plan §"Implementation Order". Each unit's Goal / Requirements / Acceptance Criteria / Test Plan / DoD are binding.

- Pick the highest-priority unit whose deps are met and is not yet complete.
- Before writing any file: (1) read AGENTS.md to confirm run/build/test commands, (2) search for at least 2 existing files that use the pattern you are about to write, (3) match their structure exactly — do not invent new patterns.
- Implement fully — no placeholders, no TODOs, no stubs.
- Write the unit's tests in the same change. Tests are part of the deliverable.
- Run the relevant suite (§3); fix every failure, including unrelated pre-existing ones you uncover.

You may use up to 200 parallel Sonnet subagents for searches and reads, and up to 1 subagent for build/test execution.

## 2. Critical rules — read before every unit

- After completing each unit, re-read the spec and plan before picking the next one.
- Do not mark a unit [x] until every test in its Test Plan section passes unmodified.
- If stuck on a single blocker for more than 3 tool-call rounds, mark the unit [!] Blocked with a clear reason and move on.
- Never skip, xfail, or comment out failing tests — fix the root cause or mark the unit blocked.
- Schema changes must be strictly additive unless the spec explicitly requires otherwise.
- All schema changes via Alembic migrations — no raw SQL. Verify the down-migration runs cleanly before marking a migration unit complete.
- Every protected endpoint must have an explicit auth check; missing auth fails the unit.
- Async paths must not contain sync I/O (no `requests`, no blocking SQL in async views).
- Pydantic models for all request/response shapes; no untyped dict passthrough.
- All colors via CSS variables or Tailwind utilities — no raw hex in component code.
- Define TypeScript types before implementation; no `any` escapes in new code.
- Server state via React Query; client UI state via Zustand. No `useState` for server data.
- Components with lists > 50 items must use virtualization (`react-window` or equivalent).

## 3. Progress tracking

Maintain [development/initial/progress/implementation-progress.md](development/initial/progress/implementation-progress.md). For each unit:

- **Unit ID** + one-line description (reference plan; do not duplicate).
- **Status:** `[ ] Not Started` / `[~] In Progress` / `[x] Complete` / `[!] Blocked`.
- **Date completed.**
- **Notes:** issues, deviations, follow-ups.

Update on start, completion, or block. Keep a PR-rollup summary at the top.

## 4. Testing — required after every unit

Run tests in three layers after every unit:

**Layer 1 — Unit tests** (always, no Docker — fast feedback):
- `bash scripts/test-unit.sh`

**Layer 2 — API integration tests** (after any backend unit):
- `bash scripts/test-api.sh`
  Starts `test-db` + `backend-test` in Docker, runs `backend/tests/api/`, tears down with `down -v`.

**Layer 3 — E2E / UI tests** (after any frontend unit, or when Layer 2 passes):
- `bash scripts/test-e2e.sh`
  Full Docker stack (test-db → backend-test → frontend-test). Playwright tests in `e2e/tests/`.
  For an interactive Playwright MCP session: `bash scripts/test-e2e.sh --up`, then use the playwright MCP browser tools against http://localhost:5174, then `docker compose -f docker-compose.test.yml down -v`.

All three layers must be green before marking a unit `[x]` complete.

**Never** skip, xfail, or disable a test to make it pass. If you uncover an unrelated regression, fix the root cause in the same increment.

## 5. Commit cadence

When a unit's tests pass and acceptance criteria are met:

1. Update the progress file (mark unit complete, date).
2. `git add -A && git commit -m "<message referencing unit IDs>"`
3. Git push is handled automatically by the loop runner — do not push manually.

**Completion gate** — when all units are `[x]` complete, before creating the git tag:
1. Spawn a subagent to verify each top-level acceptance criterion from the spec against the current implementation and produce a sign-off checklist (AC-001 ✓/✗ with evidence).
2. Fix any failing ACs before tagging.
3. Only then: `git tag v0.1.0`.

## 6. Technology constraints — do not deviate

- Backend: Python 3.11+, FastAPI, SQLAlchemy, Pydantic, pytest.
- Frontend: TypeScript 5+, React 19, Vite, Tailwind CSS, Vitest.
- No new dependencies without user confirmation.

## 7. Scope guardrails

- Edits confined to files within the scope of Initial (per plan §"In Scope").
- Do not add new dependencies without confirming with the user.
- Do not introduce feature flags — the PR sequencing IS the rollout.
- Schema changes must be strictly additive unless the spec explicitly requires otherwise.

## 8. When something is wrong or missing

- **New requirement or contradiction:** update the plan (via subagent — add a new unit or amend the affected unit's Requirements/ACs) and reflect the change in the progress file.
- **Spec contradicts observed behavior:** propose a spec update via a Sonnet subagent; do not proceed on the ambiguous unit until the spec is updated.
- **Blocked unit in the loop state header:** re-read the unit's Notes in the progress file. If the blocker is now resolved, change `[!]` back to `[ ]` and implement it. Only skip if the blocker is still live.
- **Operational knowledge** (new run/build/test commands, environment quirks): add to [AGENTS.md](AGENTS.md). Keep `AGENTS.md` purely operational.

## 9. Special notes

(none)
