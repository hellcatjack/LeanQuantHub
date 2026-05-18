# SGOV Defensive Default Unification Design

**Goal**

Unify the system-wide default defensive symbol and defensive basket to `SGOV`, and migrate currently saved project and algorithm configuration sources to `SGOV`. Historical runtime artifacts remain untouched.

## Scope

This change updates:
- New defaults in backend project config, frontend project page, frontend algorithms page, and `configs/default_algorithm.json`
- Runtime fallback defaults inside Lean algorithms
- Saved configuration sources in `project_versions.content` and `algorithm_versions.params`

This change does not update:
- `backtest_runs.params`
- `decision_snapshots`
- `trade_runs.params`
- Other historical execution or audit artifacts

## Design

1. Canonical defensive default becomes `SGOV` everywhere.
2. Backend adds normalization so old defensive values are rewritten to `SGOV` when config sources are loaded or saved.
3. A MySQL patch force-migrates existing configuration sources:
   - `project_versions.content`
   - `algorithm_versions.params`
4. Lean algorithm fallbacks move from legacy baskets such as `VGSH/IEF` or `SHY/IEF` to `SGOV`.

## Safety

- Migration is limited to configuration sources, not historical facts.
- The SQL patch must be idempotent and record itself in `schema_migrations`.
- `project_versions.content_hash` must be refreshed after content changes.

## Validation

- Backend tests for default config and normalization behavior
- Patch review to ensure migration targets and rollback guidance are present
- Frontend build and service restart after UI default updates
