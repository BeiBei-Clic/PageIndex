"""Demo script showcasing all pathtracer features.

Run with: python pathtracer/demo.py

This script demonstrates:
- if/elif/else conditionals
- for loops
- while loops
- try/except error handling
- Function calls with arguments and return values
- Nested structures (loops inside conditionals)
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def demo_conditionals(value: int) -> str:
    """Demonstrate if/elif/else branching.

    Args:
        value: Integer to classify

    Returns:
        Classification string based on value ranges
    """
    if value < 0:
        return "negative"
    elif value == 0:
        return "zero"
    elif value <= 10:
        return "small"
    elif value <= 50:
        return "medium"
    else:
        return "large"


def demo_for_loop(items: list) -> int:
    """Demonstrate for loop iteration.

    Args:
        items: List of numbers to sum

    Returns:
        Sum of all items
    """
    total = 0
    for item in items:
        total += item
    return total


def demo_while_loop(limit: int) -> list:
    """Demonstrate while loop.

    Args:
        limit: Maximum number of iterations

    Returns:
        List of accumulated values
    """
    results = []
    counter = 0
    while counter < limit:
        results.append(counter * 2)
        counter += 1
    return results


def demo_exception_handling(dividend: int, divisor: int) -> float:
    """Demonstrate try/except/else/finally.

    Args:
        dividend: Number to divide
        divisor: Number to divide by

    Returns:
        Result of division or 0.0 on error
    """
    result = 0.0
    try:
        result = dividend / divisor
    except ZeroDivisionError:
        result = 0.0
    else:
        result = result * 1.0  # Ensure float
    finally:
        pass  # Cleanup would go here
    return result


def demo_nested_structures(data: list, threshold: int) -> list:
    """Demonstrate nested loops inside conditionals.

    Args:
        data: List of integers to process
        threshold: Controls whether processing happens

    Returns:
        Processed list of values
    """
    results = []

    if threshold > 0:
        for item in data:
            count = 0
            while count < threshold and item > 0:
                results.append(item - count)
                count += 1
    else:
        results = data.copy()

    return results


def demo_function_calls(name: str, count: int) -> dict:
    """Demonstrate function call graph with arguments and returns.

    Calls multiple other demo functions to show the call graph feature.

    Args:
        name: Name to include in results
        count: Count parameter for various operations

    Returns:
        Dictionary containing results from all called functions
    """
    results = {}

    # Call demo_conditionals with different values
    results["conditional_1"] = demo_conditionals(count)
    results["conditional_2"] = demo_conditionals(count * 10)
    results["conditional_3"] = demo_conditionals(-5)

    # Call demo_for_loop
    items = list(range(count))
    results["for_loop_sum"] = demo_for_loop(items)

    # Call demo_while_loop
    results["while_loop_list"] = demo_while_loop(count)

    # Call demo_exception_handling (success and error cases)
    results["division_success"] = demo_exception_handling(100, count)
    results["division_error"] = demo_exception_handling(100, 0)

    # Call demo_nested_structures
    results["nested_result"] = demo_nested_structures([5, 10, 15], count)

    # Add name to results
    results["name"] = name

    return results


def _print_call_tree(call, depth: int = 0):
    """Helper to print function call tree recursively.

    Args:
        call: FunctionCall object to print
        depth: Current indentation depth
    """
    indent = "  " * depth
    args = ", ".join(f"{k}={v}" for k, v in call.arguments.items())
    ret = f" -> {call.return_value}" if call.return_value else ""
    print(f"{indent}{call.function_name}({args}){ret}")
    for child in call.children:
        _print_call_tree(child, depth + 1)


def main():
    """Main entry point demonstrating pathtracer usage."""
    # Import pathtracer components
    from pathtracer import PathTracer, CoverageReporter

    # Get own file path for tracing
    import os
    demo_file = os.path.abspath(__file__)

    print("=" * 60)
    print("PATHTRACER DEMO - Showcasing All Features")
    print("=" * 60)

    # Create tracer and trace execution
    tracer = PathTracer().trace_file(demo_file)
    with tracer:
        # Run demo functions with various inputs
        print("\nRunning demo functions...")

        # Conditionals
        result1 = demo_conditionals(25)
        print(f"  demo_conditionals(25) = {result1}")

        result1b = demo_conditionals(-5)
        print(f"  demo_conditionals(-5) = {result1b}")

        result1c = demo_conditionals(0)
        print(f"  demo_conditionals(0) = {result1c}")

        # For loop
        result2 = demo_for_loop([1, 2, 3, 4, 5])
        print(f"  demo_for_loop([1,2,3,4,5]) = {result2}")

        # While loop
        result3 = demo_while_loop(5)
        print(f"  demo_while_loop(5) = {result3}")

        # Exception handling (success case)
        result4 = demo_exception_handling(10, 2)
        print(f"  demo_exception_handling(10, 2) = {result4}")

        # Exception handling (error case - triggers except)
        result5 = demo_exception_handling(10, 0)
        print(f"  demo_exception_handling(10, 0) = {result5}")

        # Nested structures
        result6 = demo_nested_structures([3, 7, 2], 5)
        print(f"  demo_nested_structures([3,7,2], 5) = {result6}")

        # Function calls (demonstrates call graph)
        result7 = demo_function_calls("test", 3)
        print(f"  demo_function_calls('test', 3) = {result7}")

    # Generate and print coverage report
    reporter = CoverageReporter()
    report = reporter.analyze(demo_file, tracer)

    print("\n" + reporter.format_report(report))

    # Print function call tree
    print("\n" + "=" * 60)
    print("FUNCTION CALL TREE:")
    print("-" * 60)

    function_calls = tracer.get_function_calls()
    for call in function_calls:
        _print_call_tree(call, 0)

    print("\n" + "=" * 60)
    print("Demo complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
