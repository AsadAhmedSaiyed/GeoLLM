---
target_identity: "file:/mnt/d/My Programmes/Internship/Stellaria/geollm/templates/index.html"
target_fingerprint: "sha256:d7b4919745f732da0a065bc733ac03f83b2175a410f3da3f7d636d1e4355d12a"
target_path: /mnt/d/My Programmes/Internship/Stellaria/geollm/templates/index.html
timestamp: 2026-10-19T09-34-31Z
slug: templates-index-html
---
# GeoLLM Workbench — Impeccable Design Critique

Method: design review only (browser visualization unavailable — server not running; detector CLI ran successfully)

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 3 | Strong SSE-based live streaming, per-slot spinners, attempt pills, timers. But no global progress bar or estimated completion time; activity feed lacks timestamps. |
| 2 | Match System / Real World | 3 | Domain language is well-matched (GeoTIFF, bands, EPSG, sandboxes). "Pi RPC" and "Astryx Sandbox" label in the navbar are internal jargon that leaks into the user-facing surface. |
| 3 | User Control and Freedom | 2 | Abort button exists but is disabled in done/idle states with no visual explanation. No undo for submitted tasks. No way to re-run a completed task with one click. Plan approval has no "dismiss/defer" option. |
| 4 | Consistency and Standards | 3 | Component patterns are consistent (card topbar query progress feed artifacts footer). Minor deviation: status-pill text uses replace producing "pending approval" while CSS class remains pending_approval. Some inline styles break the design-system convention. |
| 5 | Error Prevention | 1 | No confirmation before task submission on expensive runs. File selection auto-selects first 2 files on load with no user consent. No guard against submitting duplicate identical queries. |
| 6 | Recognition Rather Than Recall | 2 | Deliverable buttons use emoji-only differentiation without clear type labels. Dataset list shows only filename and size. |
| 7 | Flexibility and Efficiency | 1 | No keyboard shortcuts beyond Ctrl+Enter. No batch operations. No template/recent queries feature. No side-by-side comparison. |
| 8 | Aesthetic and Minimalist Design | 3 | Clean dark/light hybrid is coherent. Some visual noise from decorative pills and marketing copy in navbar. |
| 9 | Error Recovery | 1 | Failed tasks show only a pill and truncated error. alert() used for errors. No structured error display or recovery suggestions. |
| 10 | Help and Documentation | 0 | No help button, no tooltips, no contextual guidance, no documentation link, no onboarding flow. |
| **Total** | | **19/40** | **Poor** |

## Design Specificity Verdict

The interface is competently themed as a geospatial workbench but the structure is category-interchangeable. Nothing in the layout reflects the spatial nature of the work.

Detector found 4 side-tab antipattern warnings in astryx.css (lines 718, 1001, 1002, 1003).

## What's Working

1. Real-time SSE streaming architecture with thinking blocks, tool cards, and vision check rows.
2. Human-in-the-loop plan approval gate with revision feedback.
3. Dark/light hybrid zoning creates clear visual separation.

## Priority Issues

### [P1] No error recovery or structured error display
Replace alert() with toast notifications. Build structured error panel with retry actions.

### [P1] No help, onboarding, or contextual guidance
Add example queries, help icon, tooltips, and clearer labels.

### [P2] Excessive side-tab borders (AI slop pattern)
Replace with subtler status differentiation using background tint + icon.

### [P2] No spatial context in the workspace
Add raster metadata in dataset picker and spatial preview.

### [P2] Inline styles undermining the design system
Extract to named CSS classes using design tokens.

## Persona Red Flags

Alex (Power User): No keyboard shortcuts, no batch operations, no side-by-side comparison.
Jordan (First-Timer): Empty landing state, jargon everywhere, no help or guidance.
Dr. Priya (GIS Researcher): No spatial metadata, no band validation, no quality metrics.

## Minor Observations

- formatSeconds shows 00:00 for idle tasks instead of --:--
- Redundant "3 Isolated Docker Containers" pill
- replace('_', ' ') only replaces first underscore
- Clear button wipes activity log with no confirmation
- CRS hardcoded to EPSG:32640 in TiffPreviewModal
