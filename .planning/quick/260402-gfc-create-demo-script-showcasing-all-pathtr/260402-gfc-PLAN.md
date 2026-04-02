---
phase: quick
plan: 01
type: execute
wave: 1
depends_on: []
files_modified: [pathtracer/demo.py]
autonomous: true
requirements: [QUICK-01]
user_setup: []

must_haves:
  truths:
    - "Demo script demonstrates if/else control flow"
    - "Demo script demonstrates for and while loops"
    - "Demo script demonstrates try/except error handling"
    - "Demo script demonstrates function calls with arguments and return values"
    - "Demo script demonstrates nested structures (loops inside conditionals)"
    - "Demo script runs without errors: python pathtracer/demo.py"
    - "Demo script produces visible output showing all features"
  artifacts:
    - path: "pathtracer/demo.py"
      provides: "Comprehensive demo of pathtracer features"
      min_lines: 50
      contains: "def main"
  key_links:
    - from: "pathtracer/demo.py"
      to: "pathtracer/tracer.py"
      via: "PathTracer context manager"
      pattern: "PathTracer"
---

<objective>
Create a standalone demo script that showcases all pathtracer features for testing and documentation purposes.

Purpose: Provide a self-contained example demonstrating all control flow types (if/else, for, while, try/except), function calls with arguments/returns, and nested structures that pathtracer can trace.

Output: `pathtracer/demo.py` - runnable demo script serving as both test case and usage example.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>

## PathTracer API Summary

From `pathtracer/__init__.py`:
```python
from .models import BranchType, CodeBranch, ExecutionPath, CoverageReport
from .tracer import PathTracer
from .cfg_builder import CFGBuilder
from .reporter import CoverageReporter
```

From `pathtracer/models.py`:
```python
class BranchType(Enum):
    SEQUENTIAL = "sequential"
    IF = "if"
    ELSE = "else"
    ELIF = "elif"
    FOR = "for"
    WHILE = "while"
    TRY = "try"
    EXCEPT = "except"
```

From `pathtracer/tracer.py`:
```python
class PathTracer:
    def trace_file(self, file_path: str) -> 'PathTracer'  # Set target file
    def __enter__(self) -> 'PathTracer'                    # Start tracing
    def __exit__(self, exc_type, exc_val, exc_tb)          # Stop tracing
    def get_executed_lines(self, file_path: str) -> Set[int]
    def get_function_calls(self) -> List[FunctionCall]
```

From `pathtracer/reporter.py`:
```python
class CoverageReporter:
    def analyze(self, file_path: str, tracer: PathTracer) -> CoverageReport
    def format_report(self, report: CoverageReport) -> str           # Text format
    def format_report_json(self, report: CoverageReport) -> str      # JSON format
    def format_report_html(self, report: CoverageReport) -> str      # HTML format
```

## Demo Requirements

The demo must showcase these control flow types (matching BranchType enum):
1. **if/else/elif** - Conditional branching
2. **for** - Iteration over sequences
3. **while** - Conditional loops
4. **try/except** - Exception handling

Plus:
- Function calls with arguments and return values
- Nested structures (e.g., loops inside conditionals)
- Multiple functions to demonstrate call graph

</context>

<tasks>

<task type="auto">
  <name>Task 1: Create comprehensive demo script</name>
  <files>pathtracer/demo.py</files>
  <action>
Create a self-contained demo script `pathtracer/demo.py` that demonstrates all pathtracer features.

Structure the demo with these functions (to show call graph):

```python
"""Demo script showcasing all pathtracer features.

Run with: python pathtracer/demo.py
"""

from __future__ import annotations

# Demo functions that showcase different control flow types

def demo_conditionals(value: int) -> str:
    """Demonstrate if/elif/else branching."""
    # Implement if/elif/else returning different strings based on value
    # Use value ranges: <0, 0-10, 11-50, >50

def demo_for_loop(items: list) -> int:
    """Demonstrate for loop iteration."""
    # Iterate over items, sum values, return total

def demo_while_loop(limit: int) -> list:
    """Demonstrate while loop."""
    # Build list using while loop until limit reached

def demo_exception_handling(dividend: int, divisor: int) -> float:
    """Demonstrate try/except/else/finally."""
    # Attempt division, handle ZeroDivisionError
    # Use try/except/else/finally structure

def demo_nested_structures(data: list, threshold: int) -> list:
    """Demonstrate nested loops inside conditionals."""
    # If threshold > 0:
    #   For each item in data:
    #     While item > 0:
    #       Modify item

def demo_function_calls(name: str, count: int) -> dict:
    """Demonstrate function call graph with arguments and returns."""
    # Call other demo functions with various arguments
    # Collect and return results in a dict

def main():
    """Main entry point demonstrating pathtracer usage."""
    # Import pathtracer components
    from pathtracer import PathTracer, CFGBuilder, CoverageReporter

    # Get own file path for tracing
    import os
    demo_file = os.path.abspath(__file__)

    print("=" * 60)
    print("PATHTRACER DEMO - Showcasing All Features")
    print("=" * 60)

    # Create tracer and trace execution
    with PathTracer().trace_file(demo_file) as tracer:
        # Run demo functions with various inputs
        result1 = demo_conditionals(25)
        result2 = demo_for_loop([1, 2, 3, 4, 5])
        result3 = demo_while_loop(5)
        result4 = demo_exception_handling(10, 2)
        result5 = demo_exception_handling(10, 0)  # Triggers except
        result6 = demo_nested_structures([3, 7, 2], 5)
        result7 = demo_function_calls("test", 3)

    # Generate and print coverage report
    reporter = CoverageReporter()
    report = reporter.analyze(demo_file, tracer)

    print("\n" + reporter.format_report(report))

    # Print function call tree
    print("\n" + "=" * 60)
    print("FUNCTION CALL TREE:")
    print("-" * 60)
    for call in tracer.get_function_calls():
        _print_call_tree(call, 0)

    print("\nDemo complete!")

def _print_call_tree(call, depth: int):
    """Helper to print function call tree."""
    indent = "  " * depth
    args = ", ".join(f"{k}={v}" for k, v in call.arguments.items())
    ret = f" -> {call.return_value}" if call.return_value else ""
    print(f"{indent}{call.function_name}({args}){ret}")
    for child in call.children:
        _print_call_tree(child, depth + 1)

if __name__ == "__main__":
    main()
```

Key requirements:
- All control flow types must be exercised: if/elif/else, for, while, try/except
- Functions must have meaningful arguments and return values
- demo_nested_structures must have loops inside conditionals (depth >= 2)
- demo_function_calls must call other demo functions to show call graph
- Main must use PathTracer context manager and CoverageReporter
- Print output must clearly show all features were exercised
  </action>
  <verify>
    <automated>python pathtracer/demo.py 2>&1 | head -50</automated>
  </verify>
  <done>
Demo script runs without errors and produces output showing:
- Coverage report with all branch types (if, for, while, except)
- Function call tree with nested calls
- All demo functions executed
  </done>
</task>

</tasks>

<verification>
- Run `python pathtracer/demo.py` - must complete without errors
- Output must contain "EXECUTION PATH COVERAGE REPORT"
- Output must show function call tree with nested calls
- Coverage percentage must be > 0%
</verification>

<success_criteria>
- `pathtracer/demo.py` exists and is runnable
- Demo demonstrates if/elif/else conditionals
- Demo demonstrates for loop iteration
- Demo demonstrates while loop
- Demo demonstrates try/except error handling
- Demo demonstrates function calls with arguments and returns
- Demo demonstrates nested structures (loops in conditionals)
- Demo uses PathTracer to trace itself
- Demo generates coverage report via CoverageReporter
- Output is human-readable and educational
</success_criteria>

<output>
After completion, create `.planning/quick/260402-gfc-create-demo-script-showcasing-all-pathtr/260402-gfc-SUMMARY.md`
</output>
