"""Coverage reporter for comparing traced paths with static CFG."""

import json
from typing import Dict, Any, List

from .models import CodeBranch, ExecutionPath, CoverageReport, BranchType, FunctionCall
from .cfg_builder import CFGBuilder
from .tracer import PathTracer


class CoverageReporter:
    """Generates coverage reports by comparing traced paths with CFG."""

    def __init__(self):
        self.cfg_builder = CFGBuilder()

    def analyze(self, file_path: str, tracer: PathTracer) -> CoverageReport:
        """Analyze coverage for a traced file."""
        # Get all branches from static analysis
        all_branches = self.cfg_builder.build_from_file(file_path)

        # Get executed lines
        executed_lines = tracer.get_executed_lines(file_path)

        # Mark branches as executed if their line was hit
        for branch in all_branches:
            if branch.line_no in executed_lines:
                branch.is_executed = True

        # Calculate statistics
        total = len(all_branches)
        executed = sum(1 for b in all_branches if b.is_executed)

        by_type: Dict[BranchType, int] = {}
        for branch_type in BranchType:
            type_branches = [b for b in all_branches if b.branch_type == branch_type]
            by_type[branch_type] = len(type_branches)

        return CoverageReport(
            total_branches=total,
            executed_branches=executed,
            branches_by_type=by_type,
            coverage_percentage=(executed / total * 100) if total > 0 else 0.0,
            file_reports={file_path: ExecutionPath(
                file_path=file_path,
                executed_lines=executed_lines,
                executed_branches={b.line_no: b for b in all_branches if b.is_executed}
            )}
        )

    def format_report(self, report: CoverageReport) -> str:
        """Format coverage report as human-readable text."""
        lines = [
            "=" * 60,
            "EXECUTION PATH COVERAGE REPORT",
            "=" * 60,
            "",
            f"Total Branches: {report.total_branches}",
            f"Executed Branches: {report.executed_branches}",
            f"Coverage: {report.coverage_percentage:.1f}%",
            "",
            "Branches by Type:",
        ]

        for branch_type, count in report.branches_by_type.items():
            if count > 0:
                lines.append(f"  {branch_type.value:12s}: {count}")

        lines.extend([
            "",
            "=" * 60,
            "EXECUTED BRANCHES:",
            "-" * 60,
        ])

        for file_path, exec_path in report.file_reports.items():
            lines.append(f"\n{file_path}:")
            for line_no, branch in sorted(exec_path.executed_branches.items()):
                lines.append(
                    f"  Line {branch.line_no:4d}: {branch.branch_type.value:10s} [executed]"
                )

        return "\n".join(lines)

    def format_report_json(self, report: CoverageReport) -> str:
        """Format coverage report as JSON string."""
        data: Dict[str, Any] = {
            "coverage_percentage": report.coverage_percentage,
            "total_branches": report.total_branches,
            "executed_branches": report.executed_branches,
            "branches_by_type": {
                bt.value: count for bt, count in report.branches_by_type.items()
            },
            "file_reports": {},
            "function_calls": []
        }

        for file_path, exec_path in report.file_reports.items():
            file_data: Dict[str, Any] = {
                "executed_lines": sorted(list(exec_path.executed_lines)),
                "executed_branches": []
            }
            for line_no, branch in sorted(exec_path.executed_branches.items()):
                file_data["executed_branches"].append({
                    "line_no": branch.line_no,
                    "branch_type": branch.branch_type.value,
                    "end_line": branch.end_line
                })
            data["file_reports"][file_path] = file_data

            # Include function calls if present
            if exec_path.function_calls:
                data["function_calls"] = self._serialize_function_calls(exec_path.function_calls)

        return json.dumps(data, indent=2)

    def _serialize_function_calls(self, calls: List[FunctionCall]) -> List[Dict[str, Any]]:
        """Serialize function calls to JSON-serializable dicts."""
        result = []
        for call in calls:
            call_dict = {
                "function_name": call.function_name,
                "file_path": call.file_path,
                "line_no": call.line_no,
                "call_depth": call.call_depth,
                "arguments": call.arguments,
                "return_value": call.return_value,
                "children": self._serialize_function_calls(call.children)
            }
            result.append(call_dict)
        return result

    def format_report_html(self, report: CoverageReport) -> str:
        """Format coverage report as self-contained HTML document."""
        html_parts = [
            "<!DOCTYPE html>",
            "<html lang='en'>",
            "<head>",
            "    <meta charset='UTF-8'>",
            "    <meta name='viewport' content='width=device-width, initial-scale=1.0'>",
            "    <title>Coverage Report</title>",
            "    <style>",
            "        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }",
            "        .container { max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }",
            "        h1 { color: #333; border-bottom: 2px solid #007bff; padding-bottom: 10px; }",
            "        h2 { color: #555; margin-top: 30px; }",
            "        .summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 30px; }",
            "        .stat-card { background: #f8f9fa; padding: 15px; border-radius: 6px; text-align: center; }",
            "        .stat-value { font-size: 2em; font-weight: bold; color: #007bff; }",
            "        .stat-label { color: #666; font-size: 0.9em; }",
            "        .code-container { background: #1e1e1e; border-radius: 6px; padding: 15px; overflow-x: auto; }",
            "        .code-line { display: flex; font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace; font-size: 13px; line-height: 1.5; }",
            "        .line-number { min-width: 50px; padding-right: 15px; text-align: right; color: #858585; user-select: none; }",
            "        .line-content { flex: 1; white-space: pre; }",
            "        .executed { background: rgba(40, 167, 69, 0.15); border-left: 3px solid #28a745; }",
            "        .executed .line-content { color: #e0e0e0; }",
            "        .not-executed { background: rgba(220, 53, 69, 0.15); border-left: 3px solid #dc3545; }",
            "        .not-executed .line-content { color: #b0b0b0; }",
            "        .function-call { background: rgba(0, 123, 255, 0.1); border-left: 3px solid #007bff; margin: 5px 0; padding: 8px 10px; border-radius: 4px; }",
            "        .function-call-tree { margin-top: 20px; }",
            "        .call-item { margin-left: 20px; padding: 5px 0; border-left: 1px dashed #ccc; padding-left: 10px; }",
            "        .call-name { font-weight: bold; color: #007bff; }",
            "        .call-args { color: #666; font-family: monospace; font-size: 0.9em; }",
            "        .call-return { color: #28a745; font-family: monospace; font-size: 0.9em; }",
            "    </style>",
            "</head>",
            "<body>",
            "    <div class='container'>",
            "        <h1>Execution Path Coverage Report</h1>",
            "",
            "        <div class='summary'>",
            f"            <div class='stat-card'><div class='stat-value'>{report.coverage_percentage:.1f}%</div><div class='stat-label'>Coverage</div></div>",
            f"            <div class='stat-card'><div class='stat-value'>{report.executed_branches}</div><div class='stat-label'>Executed Branches</div></div>",
            f"            <div class='stat-card'><div class='stat-value'>{report.total_branches}</div><div class='stat-label'>Total Branches</div></div>",
            "        </div>",
            "",
            "        <h2>Branches by Type</h2>",
            "        <div class='summary'>",
        ]

        for branch_type, count in report.branches_by_type.items():
            if count > 0:
                html_parts.append(f"            <div class='stat-card'><div class='stat-value'>{count}</div><div class='stat-label'>{branch_type.value}</div></div>")

        html_parts.extend([
            "        </div>",
            "",
        ])

        # Add source code display for each file
        for file_path, exec_path in report.file_reports.items():
            html_parts.extend([
                f"        <h2>Source: {file_path}</h2>",
                "        <div class='code-container'>",
            ])

            try:
                with open(file_path, 'r') as f:
                    source_lines = f.readlines()

                for i, line in enumerate(source_lines, start=1):
                    line_escaped = line.rstrip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    if i in exec_path.executed_lines:
                        css_class = "executed"
                    else:
                        css_class = "not-executed"
                    html_parts.append(f"            <div class='code-line {css_class}'><span class='line-number'>{i}</span><span class='line-content'>{line_escaped}</span></div>")
            except Exception as e:
                html_parts.append(f"            <div>Error reading file: {e}</div>")

            html_parts.append("        </div>")

            # Add function call tree if present
            if exec_path.function_calls:
                html_parts.extend([
                    "        <h2>Function Calls</h2>",
                    "        <div class='function-call-tree'>",
                ])
                html_parts.extend(self._render_function_calls_html(exec_path.function_calls))
                html_parts.append("        </div>")

        html_parts.extend([
            "    </div>",
            "</body>",
            "</html>",
        ])

        return "\n".join(html_parts)

    def _render_function_calls_html(self, calls: List[FunctionCall], depth: int = 0) -> List[str]:
        """Render function calls as HTML list items."""
        result = []
        for call in calls:
            args_str = ", ".join(f"{k}={v}" for k, v in call.arguments.items())
            return_str = f" -> {call.return_value}" if call.return_value else ""
            result.append(f"            <div class='call-item' style='margin-left: {depth * 20}px;'>")
            result.append(f"                <span class='call-name'>{call.function_name}</span>")
            result.append(f"                <span class='call-args'>({args_str})</span>")
            result.append(f"                <span class='call-return'>{return_str}</span>")
            result.append("            </div>")
            if call.children:
                result.extend(self._render_function_calls_html(call.children, depth + 1))
        return result
