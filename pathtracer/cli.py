"""Command-line interface for PathTracer."""

import sys
import argparse
import io
from pathlib import Path

from .tracer import PathTracer
from .reporter import CoverageReporter


def main():
    """Main CLI entry point."""
    raw_argv = sys.argv[1:]
    if not raw_argv:
        parser = argparse.ArgumentParser(
            description='Trace Python program execution paths and generate coverage reports'
        )
        parser.add_argument('program', help='Python program file to trace')
        parser.add_argument('--output', '-o', help='Output file for report (default: stdout)', default=None)
        parser.add_argument('--quiet', '-q', help='Only output report, not program stdout', action='store_true')
        parser.add_argument(
            '--format', '-f',
            choices=['text', 'html', 'json'],
            default='text',
            help='Output format: text, html, or json (default: text)'
        )
        parser.add_argument('program_args', nargs='*', help='Arguments to pass to the target program')
        parser.parse_args(raw_argv)
        return

    cli_argv = []
    program_args = []
    program = None
    index = 0
    while index < len(raw_argv):
        arg = raw_argv[index]
        if arg in ('--output', '-o', '--format', '-f'):
            if index + 1 >= len(raw_argv):
                cli_argv.append(arg)
                break
            cli_argv.extend([arg, raw_argv[index + 1]])
            index += 2
            continue
        if arg in ('--quiet', '-q'):
            cli_argv.append(arg)
            index += 1
            continue
        program = arg
        cli_argv.append(arg)
        program_args = raw_argv[index + 1:]
        break

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
    parser.add_argument(
        'program_args',
        nargs='*',
        help='Arguments to pass to the target program'
    )

    args = parser.parse_args(cli_argv)

    if not Path(args.program).exists():
        print(f"Error: File not found: {args.program}", file=sys.stderr)
        sys.exit(1)

    if program_args[:1] == ['--']:
        program_args = program_args[1:]

    tracer = PathTracer().trace_file(args.program)
    if args.quiet:
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()

    old_argv = sys.argv
    reporter = CoverageReporter()

    try:
        sys.argv = [args.program] + program_args
        with tracer:
            with open(args.program) as f:
                code = compile(f.read(), args.program, 'exec')
                exec(code, {'__name__': '__main__', '__file__': args.program})
    finally:
        sys.argv = old_argv
        if args.quiet:
            sys.stdout = old_stdout

        report = reporter.analyze(args.program, tracer)

        if args.format == 'json':
            output = reporter.format_report_json(report)
        elif args.format == 'html':
            output = reporter.format_report_html(report)
        else:
            output = reporter.format_report(report)

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
