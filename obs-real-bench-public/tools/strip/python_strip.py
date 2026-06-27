"""
Python observability stripper (stdlib ast-based).

Removes observability calls INSIDE the named target function. Everything
outside that function (imports, module-level globals, sibling functions) is
left byte-for-byte untouched.

Approach:
    1. Parse the source.
    2. Locate the target function (supports 'Class.method' too).
    3. Within that function only, rewrite the AST to drop obs nodes.
    4. Unparse the modified function body and splice it back into the
       original source text, preserving the rest of the file verbatim.

The splice step uses `lineno`/`end_lineno` (Python 3.8+) so comments and
blank lines outside the target function survive intact. Inside the target
function, comments are NOT preserved (ast does not retain them) — this is an
acceptable price for the function-level pilot.
"""
from __future__ import annotations

import ast
import textwrap
from typing import Optional

# Re-use the same heuristics as the extractor so strip / extract stay in sync.
from ..extract.python_extract import _LOG_METHOD_TO_TYPE, _receiver_kind


# ---------------------------------------------------------------------------
# classifier: is this stmt / expr observability?
# ---------------------------------------------------------------------------

def _is_obs_call(node: ast.AST) -> bool:
    """Return True iff node is a Call expression that we treat as obs."""
    if not isinstance(node, ast.Call):
        return False
    if not isinstance(node.func, ast.Attribute):
        return False
    kind = _receiver_kind(node.func.value)
    method = node.func.attr

    if kind == "span":
        return method in {
            "set_attribute", "set_attributes", "add_event",
            "record_exception", "set_status",
        }
    if kind == "tracer":
        return method in {"start_span", "start_as_current_span"}
    if kind == "logger":
        return method in _LOG_METHOD_TO_TYPE
    if kind == "metric":
        return method in {"add", "inc", "record", "observe"}
    return False


def _is_obs_assignment(node: ast.AST) -> bool:
    """Catch `span = trace.get_current_span()` and similar setup."""
    if not isinstance(node, ast.Assign):
        return False
    if not isinstance(node.value, ast.Call):
        return False
    if not isinstance(node.value.func, ast.Attribute):
        return False
    func = node.value.func
    # trace.get_current_span() / trace.get_tracer(...)
    receiver_name = ""
    if isinstance(func.value, ast.Name):
        receiver_name = func.value.id.lower()
    if receiver_name in ("trace", "metrics"):
        return True
    # tracer.get_tracer / meter.create_counter
    if _receiver_kind(func.value) in ("tracer", "metric") and func.attr.startswith(
        ("get_", "create_", "start_")
    ):
        return True
    return False


def _is_obs_stmt(stmt: ast.stmt) -> bool:
    """Whole-statement classifier: drop True; keep False."""
    if isinstance(stmt, ast.Expr) and _is_obs_call(stmt.value):
        return True
    if _is_obs_assignment(stmt):
        return True
    return False


# ---------------------------------------------------------------------------
# function body rewriter
# ---------------------------------------------------------------------------

class _BodyStripper(ast.NodeTransformer):
    """Rewrite stmts inside a function body.

    - Drop pure-obs statements.
    - For `with tracer.start_as_current_span(...) as span: <body>`, replace
      the whole With with the recursively-stripped body (effectively dedenting).
    - Recurse into nested If / For / While / Try / With.
    """

    def visit_With(self, node: ast.With) -> ast.AST | list[ast.stmt]:
        is_tracer_with = False
        for item in node.items:
            ctx = item.context_expr
            if isinstance(ctx, ast.Call) and isinstance(ctx.func, ast.Attribute):
                if _receiver_kind(ctx.func.value) == "tracer" and ctx.func.attr.startswith(
                    "start_"
                ):
                    is_tracer_with = True
                    break
        # recurse first
        self.generic_visit(node)
        if is_tracer_with:
            # Replace the With node with its (now-stripped) body. ast.NodeTransformer
            # supports returning a list of stmts when transforming a statement.
            return self._filter(node.body)
        return node

    def _filter(self, stmts: list[ast.stmt]) -> list[ast.stmt]:
        out: list[ast.stmt] = []
        for s in stmts:
            if _is_obs_stmt(s):
                continue
            out.append(s)
        return out

    def _visit_block_attr(self, node: ast.AST, attr: str, *, required: bool = True) -> None:
        """Filter a block attribute; inject ast.Pass() when stripping leaves a\n        required-non-empty block empty (otherwise the resulting source would not\n        parse). For optional blocks like If.orelse / Try.finalbody, leave the\n        empty list — ast.unparse will simply omit the clause.\n        """
        if not hasattr(node, attr):
            return
        filtered = self._filter(getattr(node, attr))
        if required and not filtered:
            filtered = [ast.Pass()]
        setattr(node, attr, filtered)

    def visit_If(self, node: ast.If) -> ast.AST:
        self.generic_visit(node)
        self._visit_block_attr(node, "body", required=True)
        self._visit_block_attr(node, "orelse", required=False)
        return node

    def visit_For(self, node: ast.For) -> ast.AST:
        self.generic_visit(node)
        self._visit_block_attr(node, "body", required=True)
        self._visit_block_attr(node, "orelse", required=False)
        return node

    def visit_AsyncFor(self, node: ast.AsyncFor) -> ast.AST:
        self.generic_visit(node)
        self._visit_block_attr(node, "body", required=True)
        self._visit_block_attr(node, "orelse", required=False)
        return node

    def visit_While(self, node: ast.While) -> ast.AST:
        self.generic_visit(node)
        self._visit_block_attr(node, "body", required=True)
        self._visit_block_attr(node, "orelse", required=False)
        return node

    def visit_Try(self, node: ast.Try) -> ast.AST:
        self.generic_visit(node)
        self._visit_block_attr(node, "body", required=True)
        self._visit_block_attr(node, "orelse", required=False)
        self._visit_block_attr(node, "finalbody", required=False)
        for h in node.handlers:
            self._visit_block_attr(h, "body", required=True)
        return node


def _strip_function_body(fn_node: ast.AST) -> ast.AST:
    """In-place: rewrite fn_node.body to drop obs."""
    if not isinstance(fn_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        raise TypeError(f"expected FunctionDef, got {type(fn_node).__name__}")
    stripper = _BodyStripper()
    fn_node.body = stripper._filter(
        [stripper.visit(s) or s if not isinstance(s, list) else s for s in fn_node.body]
    )
    # flatten any list-replacements (from visit_With returning a list)
    flat: list[ast.stmt] = []
    for s in fn_node.body:
        if isinstance(s, list):
            flat.extend(s)
        else:
            flat.append(s)
    fn_node.body = flat or [ast.Pass()]
    return fn_node


# ---------------------------------------------------------------------------
# splice back into original source preserving outside-fn formatting
# ---------------------------------------------------------------------------

def _find_function_node(tree: ast.Module, target: str) -> ast.AST:
    if "." in target:
        cls_name, mtd_name = target.split(".", 1)
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == cls_name:
                for item in node.body:
                    if (
                        isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and item.name == mtd_name
                    ):
                        return item
        raise ValueError(f"function not found: {target}")
    for node in tree.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == target
        ):
            return node
    raise ValueError(f"function not found: {target}")


def _indent_of_line(source_lines: list[str], lineno_1based: int) -> str:
    line = source_lines[lineno_1based - 1]
    return line[: len(line) - len(line.lstrip())]


def strip(source: str, *, function: str) -> str:
    tree = ast.parse(source)
    fn_node = _find_function_node(tree, function)

    # capture line bounds BEFORE we mutate AST
    start = fn_node.lineno          # 1-indexed, line of 'def ...'
    end = fn_node.end_lineno        # inclusive
    assert end is not None, "Python 3.8+ required for end_lineno"

    # detect indentation of the function's `def`
    src_lines = source.splitlines(keepends=True)
    def_indent = _indent_of_line(src_lines, start)

    # strip body
    _strip_function_body(fn_node)
    new_fn_text = ast.unparse(fn_node)

    # ast.unparse outputs at column 0; re-indent to match the original `def`
    new_fn_text = textwrap.indent(new_fn_text, def_indent)
    # ensure trailing newline
    if not new_fn_text.endswith("\n"):
        new_fn_text += "\n"

    # splice
    before = "".join(src_lines[: start - 1])
    after = "".join(src_lines[end:])
    return before + new_fn_text + after
