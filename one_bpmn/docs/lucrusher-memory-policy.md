# LuCrusher's memory posture

WI-002168. Recorded because the ticket that raised it (config validation for
`AI Agent Configuration`) asked for a decision here, not a code change — this
is that decision, not a design.

## Current state (verified 2026-09-07, live BA site)

`Lucrusher`: `long_term_memory = Disabled`, every memory field blank. Recall
and write are both fully gated on `long_term_memory == 'Enabled'`
(`dispatchers.py`), so this is architecturally consistent with "zero memories
across 63 runs, same doc re-fetched repeatedly, topology re-derived every
session" — nothing is silently half-working; the agent simply has no memory
at all.

## Decision

**Stay transcript-only for now.** Do not flip `long_term_memory` to `Enabled`
in this change. MEM-1..3 (referenced by the originating ticket as the
prerequisite for turning this on) have unknown status as of this writing —
nobody could confirm from this codebase that they've landed, and enabling
Agent-scope distilled memory blind, without that confirmation, is exactly the
kind of silent misconfiguration this ticket exists to prevent.

## To reverse this decision

Once MEM-1..3 are confirmed done:
1. Set on the `Lucrusher` config: `long_term_memory=Enabled`,
   `memory_scope=Agent`, `memory_write_mode=distilled`. Leave
   `memory_distill_model`/`memory_reconcile_model` blank to ride the fallback
   chain onto Lucrusher's own `ai_model` (see `model_resolution.py`) unless a
   specific model is wanted.
2. `validate_memory_config()` (WI-002168) will block the save if nothing
   resolves — the Effective Models preview on the form shows what will run
   before you save.
3. Add a test confirming a topology fact confirmed in one conversation is
   recalled in a later one (the acceptance criterion the originating ticket
   asked for) — `test_memory_model_config.py` has the fixtures to build this
   from (`TestMemoryConfigValidation`, `TestMemoryModelConfig`).
