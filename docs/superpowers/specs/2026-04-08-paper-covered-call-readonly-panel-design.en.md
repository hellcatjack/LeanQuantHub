# Paper Covered Call Read-Only Panel Design

## Summary
Add a read-only `Covered Call Pilot` panel to `LiveTrade` for paper mode only. The panel will surface recent covered call reviews plus aggregated audit/timeline details for a selected `review_id`. This phase does not introduce any real options submission flow and must not affect the existing stock trading path.

## Goals
- Show recent covered call reviews from `audit/recent`
- Show aggregated audit details from `audit`
- Keep the feature explicitly `paper-only` and read-only
- Fail safely without breaking current live-trade workflows

## Scope
Included:
- New presentational component for covered call audit display
- `LiveTradePage` integration and data fetching
- Unit tests and Playwright read-only regression

Excluded:
- Real options submit
- Any live-mode options flow
- Token approval UI
- Backend behavior changes

## Design
- `LiveTradePage` owns data fetching and selected `review_id`
- `CoveredCallAuditPanel` renders list/detail/loading/error states
- Recent list auto-selects the latest review when none is selected
- Separate manual refresh actions for recent list and current audit

## Success Criteria
- Recent reviews are visible from `LiveTrade`
- Selecting a review shows audit and timeline summary
- Empty/error states are explicit
- No submit button or executable action is exposed
