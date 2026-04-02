"""Data models for execution path tracing and coverage analysis."""

from dataclasses import dataclass, field
from typing import Set, Dict, List, Optional
from enum import Enum


class BranchType(Enum):
    """Types of code branches that can be traced."""
    SEQUENTIAL = "sequential"
    IF = "if"
    ELSE = "else"
    ELIF = "elif"
    FOR = "for"
    WHILE = "while"
    TRY = "try"
    EXCEPT = "except"


@dataclass
class CodeBranch:
    """Represents a branch point in code."""
    file_path: str
    line_no: int
    branch_type: BranchType
    end_line: int = 0
    is_executed: bool = False


@dataclass
class FunctionCall:
    """Records a function call during execution."""
    function_name: str
    file_path: str
    line_no: int
    call_depth: int
    arguments: Dict[str, str] = field(default_factory=dict)
    return_value: Optional[str] = None
    children: List['FunctionCall'] = field(default_factory=list)


@dataclass
class ExecutionPath:
    """Records execution path through code."""
    file_path: str
    executed_lines: Set[int] = field(default_factory=set)
    executed_branches: Dict[int, CodeBranch] = field(default_factory=dict)
    function_calls: List[FunctionCall] = field(default_factory=list)


@dataclass
class CoverageReport:
    """Aggregated coverage statistics."""
    total_branches: int = 0
    executed_branches: int = 0
    branches_by_type: Dict[BranchType, int] = field(default_factory=dict)
    coverage_percentage: float = 0.0
    file_reports: Dict[str, ExecutionPath] = field(default_factory=dict)
