"""Command-line interface for PathTracer."""

import sys
import argparse
import io
from pathlib import Path

from .tracer import PathTracer
from .reporter import CoverageReporter


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Trace Python program execution paths and generate coverage reports'
    )
    parser.add_argument(
        'program',
        help='Python program file to trace'
    )
    parser.add_argument(
        '--output', '-o',
        help='Output file for report (default: stdout)',
        default=None
    )
    parser.add_argument(
        '--quiet', '-q',
        help='Only output report, not program stdout',
        action='store_true'
    )
    parser.add_argument(
        '--format', '-f',
        choices=['text', 'html', 'json'],
        default='text',
        help='Output format: text, html, or json (default: text)'
    )

    args = parser.parse_args()

    if not Path(args.program).exists():
        print(f"Error: File not found: {args.program}", file=sys.stderr)
        sys.exit(1)

    # Trace execution
    tracer = PathTracer().trace_file(args.program)

    # Execute the target program
    if args.quiet:
        # Suppress program output
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()

    with tracer:
        try:
            with open(args.program) as f:
                code = compile(f.read(), args.program, 'exec')
                exec(code, {'__name__': '__main__'})
        except Exception as e:
            print(f"Error executing program: {e}", file=sys.stderr)
            sys.exit(1)
        finally:
            if args.quiet:
                sys.stdout = old_stdout

    # Generate report
    reporter = CoverageReporter()
    report = reporter.analyze(args.program, tracer)

    # Select formatter based on format option
    if args.format == 'json':
        output = reporter.format_report_json(report)
    elif args.format == 'html':
        output = reporter.format_report_html(report)
    else:
        output = reporter.format_report(report)

    # Determine output file
    output_file = args.output
    if not output_file:
        if args.format == 'html':
            output_file = 'coverage-report.html'
        elif args.format == 'json':
            output_file = 'coverage-report.json'

    if output_file:
        with open(output_file, 'w') as f:
            f.write(output)
        print(f"Report written to: {output_file}")
    else:
        print(output)


if __name__ == '__main__':
    main()
