# Live Trade Floating Chart Window Controls Design

## Goal
Extend the floating position chart into a desktop-style window with drag, edge snap, size persistence, minimize/restore, and responsive fallback while preserving row avoidance behavior.

## Design
- Keep the current full-width positions table.
- Allow desktop users to drag the chart window by its header.
- Snap the window to the nearest card edge after dragging.
- Allow resizing within safe bounds so the symbol and action columns remain visible.
- Support minimize/restore without losing remembered size or snap position.
- Persist desktop floating state in `localStorage`.
- Keep narrow viewports stacked below the table with no floating controls.

## Validation
- Unit tests for snap resolution, persisted state sanitization, and minimized layout fallback.
- Playwright checks for drag, persisted restore, minimize/restore, and resize.
