# AI Workflow Rules

## Approach

Build against `context/progress-tracker.md`, which names the current stage and the next
unit. Work one unit at a time, verify it, commit it, then move on. Do not infer the next
piece of work — read it.

The staged plan exists because this project was audited and found broken in ways that only
appeared when the pieces were exercised together. Follow the order.

## Scoping Rules

- Work on one unit at a time.
- Do not make speculative changes. If something looks wrong but is out of scope, note it
  in `progress-tracker.md` under Open Questions.
- Do not combine unrelated system boundaries in one step.
- Commit each unit separately with a message explaining **why**, not just what.

## When to Split Work

Split if a step combines:

- A schema migration and the feature that uses it
- Several unrelated blueprints
- Behaviour that is not clearly defined in these context files
- Anything that cannot be verified end to end in one run

## Handling Missing Requirements

- Do not invent product behaviour. If it is not in these files, it is not decided.
- If a requirement is ambiguous, resolve it in the relevant context file **before**
  implementing.
- If a decision is genuinely the user's — pricing, market assumptions, anything
  irreversible — ask. Do not pick a default and proceed.
- Record the answer in `progress-tracker.md` under Architecture Decisions, with the reason.

## Testing Rules

These are not style preferences. Each cost real debugging time.

1. **Prove a test can fail.** Break the code, watch it go red, restore it. A green test
   that cannot fail is worse than no test — it is false assurance.
2. **Never assert against a value from the same query as the actual.** Filtering by
   `business_id` then asserting every row has it is a tautology.
3. Test against real PostgreSQL through migrations. SQLite would not exercise
   `NULLS LAST`, `ON CONFLICT` or `Numeric`.
4. Add the regression test with the fix, in the same commit.
5. Prefer route-level tests over model-level. The permission grid crashed on every render
   while its model-level tests passed.

## Verification Before Moving On

1. `python -m pytest` passes.
2. `pytest` (bare, no `-m`) also passes — CI runs it that way, and the two resolve
   `sys.path` differently.
3. `flask db upgrade` succeeds against an **empty** database.
4. `python seed_db.py --yes` completes and the affected pages render.
5. `flask reconcile-stock` reports no drift if stock was touched.
6. `progress-tracker.md` reflects the work.

## Protected Files

Do not modify without explicit instruction:

- `migrations/versions/*` that are already applied — write a new migration instead
- `backfill_business.py`, `backfill_milestone3.py` — historical one-shot scripts
- `ghana-wholesaler-roadmap.md` — the original strategy document, superseded in places by
  these files but kept as the record of intent

## Keeping Docs in Sync

Update the relevant context file whenever implementation changes system boundaries, the
storage model, an invariant, a code convention, or feature scope. Update
`progress-tracker.md` after every unit.

## Communication

The user has asked for plain-English detail first, then the technical detail in the same
order so the two map onto each other. Always end with a concrete next step — an exact
command, or the buttons to click. Never assume a technical statement implies an action.

The user runs **PowerShell on Windows**. `&&` is a parser error there; give separate
commands or use `;`.
