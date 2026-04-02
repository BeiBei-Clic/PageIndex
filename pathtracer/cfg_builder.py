"""Control Flow Graph builder for static code analysis."""

import ast
from typing import List, Optional

from .models import CodeBranch, BranchType


class CFGBuilder:
    """Builds Control Flow Graph from Python source to identify all branches."""

    def __init__(self):
        self.branches: List[CodeBranch] = []

    def build_from_file(self, file_path: str) -> List[CodeBranch]:
        """Parse Python file and extract all branch points."""
        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()

        tree = ast.parse(source, filename=file_path)
        self.branches = []

        # Walk AST to find control structures
        for node in ast.walk(tree):
            branch = self._extract_branch(file_path, node)
            if branch:
                self.branches.append(branch)

        return self.branches

    def _extract_branch(self, file_path: str, node: ast.AST) -> Optional[CodeBranch]:
        """Extract branch information from AST node."""

        # If statement
        if isinstance(node, ast.If):
            return CodeBranch(
                file_path=file_path,
                line_no=node.lineno,
                branch_type=BranchType.IF,
                end_line=self._get_end_line(node)
            )

        # For loop
        elif isinstance(node, ast.For):
            return CodeBranch(
                file_path=file_path,
                line_no=node.lineno,
                branch_type=BranchType.FOR,
                end_line=self._get_end_line(node)
            )

        # While loop
        elif isinstance(node, ast.While):
            return CodeBranch(
                file_path=file_path,
                line_no=node.lineno,
                branch_type=BranchType.WHILE,
                end_line=self._get_end_line(node)
            )

        # Try/Except
        elif isinstance(node, ast.ExceptHandler):
            return CodeBranch(
                file_path=file_path,
                line_no=node.lineno,
                branch_type=BranchType.EXCEPT,
                end_line=self._get_end_line(node)
            )

        return None

    def _get_end_line(self, node: ast.AST) -> int:
        """Get the last line of a code block."""
        if hasattr(node, 'end_lineno') and node.end_lineno is not None:
            return node.end_lineno
        if hasattr(node, 'body') and node.body:
            return max(self._get_end_line(n) for n in node.body)
        return getattr(node, 'lineno', 0)

    def get_branches_by_type(self, branch_type: BranchType) -> List[CodeBranch]:
        """Filter branches by type."""
        return [b for b in self.branches if b.branch_type == branch_type]
