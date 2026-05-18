# Live Trade Single-Line Positions And Floating Chart Design

## Goal
Compress the live-trade positions table into a dense single-line row layout and move the professional chart into a floating desktop panel so the table can use full width without losing chart access.

## Design
- Keep the positions card full-width.
- Convert the actions cell into a single-line compact toolbar.
- Render the chart as an absolute-position floating card on desktop.
- Place the floating chart above or below the selected row so it does not cover the selected symbol row.
- Keep the floating panel on the right side so key left-side columns like the symbol column remain visible.
- Fall back to a static stacked chart below the table on narrower viewports.

## Validation
- Unit tests for floating layout calculation.
- Playwright checks for compact row height, floating chart avoidance, and narrow-screen fallback.
