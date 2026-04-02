"""Runtime execution tracer using sys.settrace."""

import sys
from typing import Optional, Callable, Set, Dict, List

from .models import ExecutionPath, FunctionCall


class PathTracer:
    """Traces Python program execution using sys.settrace."""

    def __init__(self):
        self.execution_paths: Dict[str, ExecutionPath] = {}
        self._original_trace: Optional[Callable] = None
        self._target_file: Optional[str] = None
        self.function_calls: List[FunctionCall] = []
        self._call_stack: List[FunctionCall] = []

    def trace_file(self, file_path: str) -> 'PathTracer':
        """Set target file to trace."""
        self._target_file = file_path
        self.execution_paths[file_path] = ExecutionPath(file_path=file_path)
        return self

    def _trace_callback(self, frame, event: str, arg) -> Optional[Callable]:
        """Internal trace callback for sys.settrace."""
        if not self._target_file:
            return None

        # Only trace events in target file
        code = frame.f_code
        if not code.co_filename.endswith(self._target_file):
            return self._trace_callback

        if event == 'line':
            line_no = frame.f_lineno
            self.execution_paths[self._target_file].executed_lines.add(line_no)

        elif event == 'call':
            # Extract function name and arguments
            func_name = code.co_name
            line_no = frame.f_lineno

            # Extract arguments from frame locals
            args = {}
            try:
                # Get argument names from code object
                arg_count = code.co_argcount
                arg_names = code.co_varnames[:arg_count]
                for arg_name in arg_names:
                    if arg_name in frame.f_locals:
                        try:
                            args[arg_name] = repr(frame.f_locals[arg_name])
                        except Exception:
                            args[arg_name] = '<unable to repr>'
            except Exception:
                pass

            # Create FunctionCall with current depth
            call_depth = len(self._call_stack)
            func_call = FunctionCall(
                function_name=func_name,
                file_path=code.co_filename,
                line_no=line_no,
                call_depth=call_depth,
                arguments=args
            )

            # Append to parent's children or top-level list
            if self._call_stack:
                self._call_stack[-1].children.append(func_call)
            else:
                self.function_calls.append(func_call)
                # Also add to ExecutionPath
                self.execution_paths[self._target_file].function_calls.append(func_call)

            # Push to call stack
            self._call_stack.append(func_call)

        elif event == 'return':
            # Pop from call stack and set return value
            if self._call_stack:
                func_call = self._call_stack.pop()
                if arg is not None:
                    try:
                        func_call.return_value = repr(arg)
                    except Exception:
                        func_call.return_value = '<unable to repr>'

        return self._trace_callback

    def __enter__(self):
        """Start tracing."""
        self._original_trace = sys.gettrace()
        sys.settrace(self._trace_callback)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Stop tracing."""
        sys.settrace(self._original_trace)
        return False

    def get_executed_lines(self, file_path: str) -> Set[int]:
        """Get set of executed line numbers."""
        if file_path in self.execution_paths:
            return self.execution_paths[file_path].executed_lines
        return set()

    def get_function_calls(self) -> List[FunctionCall]:
        """Get list of function calls recorded during execution."""
        return self.function_calls
