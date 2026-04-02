---
phase: quick-260402-g3p
plan: 01
subsystem: developer-tools
tags: [coverage, tracing, html, json, cli, sys.settrace]

requires: []
provides:
  - FunctionCall dataclass for tracking function invocations
  - HTML report formatter with syntax highlighting
  - JSON report formatter for programmatic consumption
  - CLI --format option for output selection
affects: []

tech-stack:
  added: []
  patterns: [sys.settrace event handling, dataclass tree structures]

key-files:
  created: []
  modified:
    - pathtracer/models.py
    - pathtracer/tracer.py
    - pathtracer/reporter.py
    - pathtracer/cli.py

key-decisions:
  - "Use repr() for argument/return value serialization to handle arbitrary Python objects"
  - "Track function calls as tree structure with children list for nested calls"
  - "Default HTML output to coverage-report.html, JSON to coverage-report.json"

patterns-established:
  - "Event-based tracing: handle 'call', 'return', 'line' events in _trace_callback"
  - "Call stack tracking: use internal _call_stack to maintain depth and parent-child relationships"

requirements-completed: [FEATURE-1, FEATURE-2]

duration: 4min
completed: 2026-04-02
---

# Quick Task 260402-g3p: HTML/JSON Reports and Function Call Tracing

**Extended pathtracer with multi-format reports (HTML/JSON) and function call tracing with arguments, return values, and call depth.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-04-02T03:41:51Z
- **Completed:** 2026-04-02T03:45:51Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments
- Added FunctionCall dataclass with recursive tree structure for nested calls
- Extended PathTracer to capture call/return events with argument and return value extraction
- Created HTML report formatter with syntax highlighting and executed/non-executed line styling
- Created JSON report formatter for programmatic consumption
- Added --format CLI option supporting text, html, and json output

## Task Commits

Each task was committed atomically:

1. **Task 1: Add FunctionCall model and tracing support** - `a60d756` (feat)
2. **Task 2: Add HTML and JSON report formatters** - `68f8542` (feat)
3. **Task 3: Update CLI with --format option** - `0aad9c9` (feat)

## Files Created/Modified
- `pathtracer/models.py` - Added FunctionCall dataclass, updated ExecutionPath with function_calls field
- `pathtracer/tracer.py` - Added call/return event handling, _call_stack tracking, get_function_calls() method
- `pathtracer/reporter.py` - Added format_report_json() and format_report_html() methods with full styling
- `pathtracer/cli.py` - Added --format/-f option with text/html/json choices

## Decisions Made
- Used repr() for argument/return value serialization to safely handle any Python object type
- Implemented function calls as a tree structure with children list for proper nesting representation
- Default file outputs: coverage-report.html for HTML format, coverage-report.json for JSON format

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - all verification commands passed on first attempt.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- All must-have truths satisfied:
  - CLI accepts --format html|json|text option
  - HTML report shows syntax-highlighted code with executed/non-executed branches
  - JSON report contains structured data for programmatic consumption
  - Function calls are tracked with arguments, return values, and call depth

---
*Phase: quick-260402-g3p*
*Completed: 2026-04-02*

## Self-Check: PASSED
- All 4 modified files verified to exist
- All 3 task commits verified in git history
