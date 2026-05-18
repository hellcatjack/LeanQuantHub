# Paper Covered Call Execution Prep Design

**Goal**
Add a safer execution-preparation layer on top of the existing `paper-only covered call pilot`, converting recommendations into auditable option order plans with explicit gate states before any real paper options submit is considered.

**Recommended scope**
- `paper` only
- `covered call` only
- `dry-run` only
- single-symbol preparation
- explicit `ready / review_required / blocked` outcomes
- separate option order model and execution artifacts

**Why now**
The current pilot can discover candidates, read IB option contracts, and generate recommendations, but it still lacks a clean boundary between “recommendation” and “execution-ready order.” This phase adds that boundary without introducing actual options trading.

**Not in scope**
- real paper options submit
- live options trading
- rolling, assignment handling, or multi-leg structures
- frontend UI

**New pieces**
- `covered_call_execution.py`: build execution prep result for one symbol
- expand `trade_option_models.py`: request/response and option order plan models
- new route: `POST /api/trade/options/covered-call/prepare`

**Gate states**
- `blocked`: invalid mode, invalid dry-run flag, unhealthy runtime, no eligible recommendation, invalid limit price, or zero contracts
- `review_required`: recommendation exists but includes warning-level risk tags
- `ready`: recommendation exists, no blockers, no warning tags, complete order plan

**Success criteria**
- recommendation and execution plan are separated cleanly
- stock trading path remains untouched
- execution prep output is auditable and stable
- still no real options submit
