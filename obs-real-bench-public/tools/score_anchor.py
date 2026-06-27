"""
obs-real-bench: anchor-based F1 scorer.

Position-level scoring with **no magic numbers / no thresholds**.

Idea: treat each *business statement* in the target function as an "anchor".
The positions BETWEEN consecutive anchors are "slots". For each slot we ask a
single binary question: does observability code live there?

    gt_has_obs[i]   in {True, False}     # was there obs in this slot in the ORIGINAL
    llm_has_obs[i]  in {True, False}     # did the LLM put obs in the corresponding slot

The two anchor sequences are aligned via stdlib `difflib.SequenceMatcher`
(longest-common-subsequence; no tunable thresholds). For each aligned pair we
compare the corresponding slots:

    TP: gt=True  AND llm=True
    FP: gt=False AND llm=True
    FN: gt=True  AND llm=False

Then standard precision / recall / F1 — no grade ladder, no Jaccard.

To make alignment robust to LLM refactoring (renamed kwargs, reordered call
args, added wrapper helpers), we canonicalise each statement to a structural
shape that ignores literal values and call argument lists.
"""
from __future__ import annotations

import ast
import difflib
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_HERE = Path(__file__).resolve().parent
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))

from tools.extract.python_extract import _receiver_kind, _string_arg  # noqa: E402
from tools.strip.python_strip import _is_obs_call, _is_obs_assignment  # noqa: E402


# ---------------------------------------------------------------------------
# obs detection (broader than the strict extractor — catches helpers too)
# ---------------------------------------------------------------------------

# Tokens that, when present as a *whole word* in a function name, mark the
# call as an obs/telemetry helper. Word boundaries = underscores, dots.
_OBS_WORD_TOKENS = {
    "span", "spans",
    "tracer", "tracers", "trace", "traces",
    "logger", "log",
    "meter", "counter", "histogram", "gauge",
    "metric", "metrics",
    "telemetry", "otel",
    "instrument", "instruments", "instr",
}


def _name_tokens(name: str) -> set[str]:
    """Tokenise a callable name into lowercase words.

    `_set_span_attribute`           -> {'set', 'span', 'attribute'}
    `recommendation.log_warn`       -> {'recommendation', 'log', 'warn'}
    `instruments[*].add`            -> {'instruments', 'add'}
    """
    cleaned = name.lower()
    for sep in (".", "[", "]", "*", "(", ")", " ", "\t"):
        cleaned = cleaned.replace(sep, "_")
    parts: list[str] = []
    for chunk in cleaned.split("_"):
        if chunk:
            parts.append(chunk)
    return set(parts)


def _name_chain(node: ast.AST) -> str:
    """Best-effort dotted form of a callable expression."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _name_chain(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    if isinstance(node, ast.Subscript):
        prefix = _name_chain(node.value)
        return f"{prefix}[*]" if prefix else "[*]"
    if isinstance(node, ast.Call):
        return _name_chain(node.func)
    return ""


def _is_obs_stmt(stmt: ast.stmt) -> bool:
    """True if the *whole* statement is observability-related.

    Catches three flavours:
        1. Strict obs call:   `span.set_attribute(...)`, `logger.info(...)`, ...
        2. Obs setup assign:  `span = trace.get_current_span()`
        3. Helper-wrapped:    `_set_span_attribute(span, ...)` — a bare-name
           call whose name contains an obs token as a word.
    """
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        if _is_obs_call(stmt.value):
            return True
        # helper-name heuristic
        chain = _name_chain(stmt.value.func)
        tokens = _name_tokens(chain)
        if tokens & _OBS_WORD_TOKENS:
            return True
    if isinstance(stmt, ast.Assign) and _is_obs_assignment(stmt):
        return True
    return False


def _is_tracer_with(stmt: ast.stmt) -> bool:
    """`with tracer.start_as_current_span(...) as span:` style."""
    if not isinstance(stmt, ast.With):
        return False
    for item in stmt.items:
        ctx = item.context_expr
        if isinstance(ctx, ast.Call) and isinstance(ctx.func, ast.Attribute):
            if _receiver_kind(ctx.func.value) == "tracer" and (
                ctx.func.attr.startswith("start_") or ctx.func.attr == "start_span"
            ):
                return True
    return False


# ---------------------------------------------------------------------------
# canonical "shape" of an expression / statement — robust to small edits
# ---------------------------------------------------------------------------

def _shape(node: Optional[ast.AST]) -> str:
    """Recursive structural fingerprint that drops literals & call args."""
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_shape(node.value)}.{node.attr}"
    if isinstance(node, ast.Subscript):
        return f"{_shape(node.value)}[*]"
    if isinstance(node, ast.Call):
        return f"{_shape(node.func)}(...)"
    if isinstance(node, ast.Constant):
        return "<lit>"
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return "<seq>"
    if isinstance(node, ast.Dict):
        return "<dict>"
    if isinstance(node, ast.ListComp):
        return "<listcomp>"
    if isinstance(node, ast.SetComp):
        return "<setcomp>"
    if isinstance(node, ast.DictComp):
        return "<dictcomp>"
    if isinstance(node, ast.GeneratorExp):
        return "<genexp>"
    if isinstance(node, ast.BinOp):
        return f"({_shape(node.left)} {type(node.op).__name__} {_shape(node.right)})"
    if isinstance(node, ast.BoolOp):
        return f"<boolop:{type(node.op).__name__}>"
    if isinstance(node, ast.Compare):
        return f"<cmp:{_shape(node.left)}>"
    if isinstance(node, ast.UnaryOp):
        return f"<unary:{_shape(node.operand)}>"
    if isinstance(node, ast.IfExp):
        return "<ifexp>"
    if isinstance(node, ast.Lambda):
        return "<lambda>"
    if isinstance(node, ast.Await):
        return f"await {_shape(node.value)}"
    if isinstance(node, ast.Starred):
        return f"*{_shape(node.value)}"
    return f"<{type(node).__name__}>"


def _canonical_stmt(stmt: ast.stmt) -> str:
    """Single-line canonical form. Body / orelse / handlers ignored."""
    if isinstance(stmt, ast.Assign):
        targets = ", ".join(_shape(t) for t in stmt.targets)
        return f"{targets} = {_shape(stmt.value)}"
    if isinstance(stmt, ast.AnnAssign):
        return f"{_shape(stmt.target)}: <ann> = {_shape(stmt.value)}"
    if isinstance(stmt, ast.AugAssign):
        return f"{_shape(stmt.target)} <aug>= {_shape(stmt.value)}"
    if isinstance(stmt, ast.Expr):
        return _shape(stmt.value)
    if isinstance(stmt, ast.Return):
        return f"return {_shape(stmt.value)}"
    if isinstance(stmt, ast.If):
        return f"if {_shape(stmt.test)}:"
    if isinstance(stmt, ast.For):
        return f"for {_shape(stmt.target)} in {_shape(stmt.iter)}:"
    if isinstance(stmt, ast.AsyncFor):
        return f"async for {_shape(stmt.target)} in {_shape(stmt.iter)}:"
    if isinstance(stmt, ast.While):
        return f"while {_shape(stmt.test)}:"
    if isinstance(stmt, ast.With):
        items = ", ".join(_shape(it.context_expr) for it in stmt.items)
        return f"with {items}:"
    if isinstance(stmt, ast.AsyncWith):
        items = ", ".join(_shape(it.context_expr) for it in stmt.items)
        return f"async with {items}:"
    if isinstance(stmt, ast.Try):
        return "try:"
    if isinstance(stmt, ast.Raise):
        return f"raise {_shape(stmt.exc)}"
    if isinstance(stmt, ast.Global):
        return f"global {','.join(stmt.names)}"
    if isinstance(stmt, ast.Nonlocal):
        return f"nonlocal {','.join(stmt.names)}"
    if isinstance(stmt, ast.Pass):
        return "pass"
    if isinstance(stmt, ast.Break):
        return "break"
    if isinstance(stmt, ast.Continue):
        return "continue"
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return f"def {stmt.name}(...)"
    if isinstance(stmt, ast.ClassDef):
        return f"class {stmt.name}"
    return f"<stmt:{type(stmt).__name__}>"


# ---------------------------------------------------------------------------
# key extraction (mirrors python_extract: span / event / attribute names)
# ---------------------------------------------------------------------------

def _obs_stmt_keys(stmt: ast.stmt) -> set[str]:
    """Pull the attribute / span / event keys named by a single obs statement.

    Mirrors the key-extraction logic in ``tools/extract/python_extract.py``
    but operates on one statement at a time, returning the set of string
    literals that act as *keys* for this obs call:

      - ``tracer.start_as_current_span("name", ...)``  -> {"name"}
      - ``tracer.start_span("name", ...)``             -> {"name"}
      - ``span.set_attribute("k", v)``                  -> {"k"}
      - ``span.set_attributes({"k1": v1, "k2": v2})``  -> {"k1", "k2"}
      - ``span.add_event("evt")``                       -> {"evt"}
      - logger.*, record_exception, set_status,
        counter.add, histogram.record, gauge.observe  -> {}  (no keys)

    Only string-literal keys are recorded; computed / variable keys are
    skipped (consistent with the extractor).
    """
    keys: set[str] = set()

    # `with tracer.start_*(name, ...) as span:` — only mine the context_expr,
    # the body is walked separately by `_walk`.
    if isinstance(stmt, ast.With):
        for item in stmt.items:
            ctx = item.context_expr
            if (
                isinstance(ctx, ast.Call)
                and isinstance(ctx.func, ast.Attribute)
                and (ctx.func.attr.startswith("start_") or ctx.func.attr == "start_span")
                and ctx.args
            ):
                name = _string_arg(ctx.args[0])
                if name:
                    keys.add(name)
        return keys

    for child in ast.walk(stmt):
        if not (isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)):
            continue
        method = child.func.attr
        if method == "set_attribute" and child.args:
            k = _string_arg(child.args[0])
            if k:
                keys.add(k)
        elif method == "set_attributes" and child.args and isinstance(child.args[0], ast.Dict):
            for k_node in child.args[0].keys:
                if k_node is None:
                    continue
                sk = _string_arg(k_node)
                if sk:
                    keys.add(sk)
        elif method == "add_event" and child.args:
            k = _string_arg(child.args[0])
            if k:
                keys.add(k)
        elif method in ("start_span", "start_as_current_span") and child.args:
            k = _string_arg(child.args[0])
            if k:
                keys.add(k)
    return keys


# ---------------------------------------------------------------------------
# keyword bag extraction (lenient — token-level, for Key F1 (bag) axis)
# ---------------------------------------------------------------------------
#
# The strict ``_obs_stmt_keys`` above only harvests *attribute / event / span
# names* recorded by an obs call (e.g. ``set_attribute("app.product.id", v)``
# -> {"app.product.id"}). That's a precise but unforgiving signal: namespace
# differences (`app.product.id` vs `product.id`) read as full misses, and the
# rich content recorded in log messages and attribute *values* is ignored.
#
# The token-bag extractor below is the lenient counterpart: it sweeps every
# string literal, identifier, attribute reference and keyword-arg name in the
# obs statement, tokenizes them (dot / underscore / camelCase / whitespace),
# drops obvious framework noise (``logger`` / ``span`` / ``set_attribute`` /
# ...) and short / numeric tokens. The resulting set captures what the obs
# statement is *talking about*, not how it's spelled.

# Words dropped from keyword bags. Two categories:
#   1. observability framework vocabulary — these say "this is obs code", not
#      "this is what is being observed". `logger` and `log` are stop words by
#      design so that they read as equivalent.
#   2. python keyword-ish identifiers / generic short variable names that
#      otherwise show up in almost every statement and add no signal.
_KW_STOP = frozenset({
    # obs framework / call-site vocabulary
    "log", "logs", "logger", "logging", "info", "debug", "warning", "warn",
    "error", "errors", "exception", "exceptions", "critical", "fatal", "trace",
    "span", "spans", "tracer", "tracers", "context", "attribute", "attributes",
    "event", "events", "metric", "metrics", "counter", "histogram", "gauge",
    "add_event", "set_attribute", "set_attributes", "set_status",
    "record_exception", "start_as_current_span", "start_span",
    "get_tracer", "get_meter", "get_logger", "extra", "kwargs", "args",
    # python keywords / generics that show up as Name nodes constantly
    "self", "cls", "true", "false", "none", "null", "return", "raise",
    "exc", "ex", "err", "msg", "message",
})

_KW_CAMEL_RX = re.compile(r"([a-z0-9])([A-Z])")
_KW_SPLIT_RX = re.compile(r"[\s._\-/:]+")


def _tokenize_text(s: str) -> set[str]:
    """Lower-case, split on common separators + camelCase boundaries,
    drop stop-words / tokens shorter than 3 chars / pure-digit tokens."""
    s = _KW_CAMEL_RX.sub(r"\1_\2", s)
    out: set[str] = set()
    for p in _KW_SPLIT_RX.split(s.lower()):
        if not p or p.isdigit() or len(p) < 3 or p in _KW_STOP:
            continue
        out.add(p)
    return out


def _obs_stmt_keywords(stmt: ast.stmt) -> set[str]:
    """Lenient keyword bag for a single obs statement.

    Sweeps the statement's AST and tokenises every:
      * string-literal value  (``ast.Constant`` with str value)
      * variable name         (``ast.Name``)
      * attribute reference   (``.attr`` of ``ast.Attribute``)
      * keyword arg name      (``ast.keyword.arg``)

    For ``with tracer.start_*(...)`` blocks we only scan the items
    (``context_expr``), NOT the body — the body is walked separately by
    ``_walk`` and contributes its own keyword bags via its own statements.
    Skipping the body here avoids leaking business-statement tokens into the
    span-start statement's bag.
    """
    if isinstance(stmt, (ast.With, ast.AsyncWith)):
        roots: list[ast.AST] = [it.context_expr for it in stmt.items]
    else:
        roots = [stmt]

    out: set[str] = set()
    for root in roots:
        for node in ast.walk(root):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                out |= _tokenize_text(node.value)
            elif isinstance(node, ast.Name):
                out |= _tokenize_text(node.id)
            elif isinstance(node, ast.Attribute):
                out |= _tokenize_text(node.attr)
            elif isinstance(node, ast.keyword) and node.arg:
                out |= _tokenize_text(node.arg)
    return out


# ---------------------------------------------------------------------------
# walk: DFS the function body, emit a flat ('B'|'O', canonical, keys) sequence
# ---------------------------------------------------------------------------

@dataclass
class Anchor:
    canonical: str            # structural fingerprint
    depth: int                # nesting level (debug only)


@dataclass
class FunctionWalk:
    anchors: list[Anchor]                 # length = N business stmts
    slot_has_obs: list[bool]              # length = N + 1  (binary: any obs?)
    slot_keys: list[set[str]]             # length = N + 1  (union of obs keys, strict)
    slot_keywords: list[set[str]]         # length = N + 1  (union of obs keyword tokens, lenient)


def _walk(
    body: list[ast.stmt],
    depth: int,
    out: list[tuple[str, int, str, set[str], set[str]]],
) -> None:
    """DFS — emit ('B'|'O', depth, canonical, keys, keywords) tuples for every stmt.

    ``keys`` is the strict string-literal key set for obs statements; empty
    for business statements. ``keywords`` is the lenient token bag (string
    literals + identifiers tokenised) for obs statements; empty for business
    statements.
    """
    for stmt in body:
        # obs statement?
        if _is_obs_stmt(stmt):
            out.append((
                "O", depth, _canonical_stmt(stmt),
                _obs_stmt_keys(stmt), _obs_stmt_keywords(stmt),
            ))
            continue
        # `with tracer.start_*` is the span-start marker AND its body extends
        # the surrounding scope. Emit O, then walk body at the SAME depth so
        # the body's statements look siblings-of-the-with.
        if _is_tracer_with(stmt):
            out.append((
                "O", depth, _canonical_stmt(stmt),
                _obs_stmt_keys(stmt), _obs_stmt_keywords(stmt),
            ))
            _walk(stmt.body, depth, out)
            continue
        # business statement (compound or simple) — no keys / no keywords
        out.append(("B", depth, _canonical_stmt(stmt), set(), set()))
        # recurse into nested bodies (each at depth+1)
        for sub_name in ("body", "orelse", "finalbody"):
            sub = getattr(stmt, sub_name, None)
            if sub:
                _walk(sub, depth + 1, out)
        for h in getattr(stmt, "handlers", []) or []:
            _walk(getattr(h, "body", []), depth + 1, out)


def _find_function(tree: ast.Module, target: str) -> Optional[ast.AST]:
    if "." in target:
        cls, method = target.split(".", 1)
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == cls:
                for item in node.body:
                    if (
                        isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and item.name == method
                    ):
                        return item
        return None
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == target
        ):
            return node
    return None


def collect(source: str, function_name: str) -> FunctionWalk:
    """Parse `source`, find `function_name`, return anchor + slot info.

    Returns an empty walk (`anchors=[], slot_has_obs=[False], slot_keys=[{}],
    slot_keywords=[{}]`) when the target function isn't found in the LLM
    output (LLM refused / produced no code) or the source can't be parsed.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return FunctionWalk(
            anchors=[], slot_has_obs=[False],
            slot_keys=[set()], slot_keywords=[set()],
        )
    target = _find_function(tree, function_name)
    if target is None:
        return FunctionWalk(
            anchors=[], slot_has_obs=[False],
            slot_keys=[set()], slot_keywords=[set()],
        )

    flat: list[tuple[str, int, str, set[str], set[str]]] = []
    _walk(target.body, depth=0, out=flat)

    anchors: list[Anchor] = []
    slots: list[bool] = [False]              # slot 0: before first business stmt
    slot_keys: list[set[str]] = [set()]      # parallel to `slots`
    slot_keywords: list[set[str]] = [set()]  # parallel to `slots`
    for kind, depth, canonical, keys, kws in flat:
        if kind == "O":
            slots[-1] = True
            slot_keys[-1] |= keys
            slot_keywords[-1] |= kws
        else:
            anchors.append(Anchor(canonical=canonical, depth=depth))
            slots.append(False)
            slot_keys.append(set())
            slot_keywords.append(set())
    return FunctionWalk(
        anchors=anchors, slot_has_obs=slots,
        slot_keys=slot_keys, slot_keywords=slot_keywords,
    )


# ---------------------------------------------------------------------------
# alignment + F1
# ---------------------------------------------------------------------------

def _polyglot_unmeasured() -> dict:
    """Return the "not yet measured" anchor result for non-Python languages.

    The shape matches `score_anchor`'s real output so callers (pilot.py /
    rescore.py) can serialise it without special-casing. All counts are 0
    and F1-class fields are None so downstream `_mean_harsh` aggregation
    treats them as N/A rather than zeros.
    """
    return {
        "n_anchors_gt": 0, "n_anchors_llm": 0, "n_anchors_aligned": 0,
        "n_buckets": 0, "n_gt_obs_buckets": 0, "n_llm_obs_buckets": 0,
        "tp": 0, "fp": 0, "fn": 0,
        "precision": None, "recall": None, "f1": None,
        "key_tp": 0, "key_fp": 0, "key_fn": 0,
        "key_n_comparable_buckets": 0,
        "key_precision": None, "key_recall": None, "key_f1": None,
        "key_bag_tp": 0, "key_bag_fp": 0, "key_bag_fn": 0,
        "key_bag_n_comparable_buckets": 0,
        "key_bag_precision": None, "key_bag_recall": None, "key_bag_f1": None,
        "buckets": [],
        "_note": "score_anchor: polyglot scoring not yet implemented; "
                 "only obs-site counts (n_gt / n_llm) are measured.",
    }


def score_anchor(
    gt_source: str,
    llm_source: str,
    function_name: str,
    *,
    language: str = "python",
) -> dict:
    """Compute the anchor F1 score for a (ground-truth, LLM-output) pair.

    Python uses the legacy `ast`-based `collect()`; every other language
    dispatches to `score_anchor_ts.collect_ts()` (tree-sitter). Returns the
    same dict shape in both cases.
    """
    if language.lower() in ("python", "py"):
        gt_walk = collect(gt_source, function_name)
        llm_walk = collect(llm_source, function_name)
    else:
        # tree-sitter backend for Go / Java / C# / TS / JS / ...
        from tools.score_anchor_ts import collect_ts
        try:
            gt_walk = collect_ts(gt_source, function_name, language)
            llm_walk = collect_ts(llm_source, function_name, language)
        except Exception as e:  # noqa: BLE001
            # Don't take the pipeline down on a single parse glitch; fall
            # back to the "unmeasured" shape and stash the error in _note.
            d = _polyglot_unmeasured()
            d["_note"] = f"score_anchor_ts failed: {type(e).__name__}: {e}"
            return d

    gt_seq = [a.canonical for a in gt_walk.anchors]
    llm_seq = [a.canonical for a in llm_walk.anchors]

    # SequenceMatcher gives us the longest common subsequence of canonicals.
    sm = difflib.SequenceMatcher(a=gt_seq, b=llm_seq, autojunk=False)
    matched: list[tuple[int, int]] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                matched.append((i1 + k, j1 + k))

    # Define "slot buckets" between matched anchors. Each bucket covers
    #   GT  slots gt_slot[g_prev+1 .. g_curr] inclusive  (i.e. the slot
    #            immediately after the previous matched anchor up to the slot
    #            immediately BEFORE the current matched anchor — same idx in
    #            the slot array because slot[i] = "before anchor i").
    # Slot 0 logic: "before the first matched anchor" lumps any obs that lives
    # before the first match.

    def _any(seq: list[bool], lo: int, hi: int) -> bool:
        """True if any seq[i] is True for i in [lo, hi]. Clamps to range."""
        lo = max(0, lo)
        hi = min(len(seq) - 1, hi)
        if lo > hi:
            return False
        return any(seq[lo : hi + 1])

    def _union_keys(seq: list[set[str]], lo: int, hi: int) -> set[str]:
        """Union of key-sets seq[lo..hi]. Clamps to range; empty if invalid."""
        lo = max(0, lo)
        hi = min(len(seq) - 1, hi)
        out: set[str] = set()
        if lo > hi:
            return out
        for s in seq[lo : hi + 1]:
            out |= s
        return out

    buckets: list[dict] = []
    prev_g = -1
    prev_l = -1
    for g, l in matched:
        # "head" / "between matched" bucket: covers slot indices (prev+1) .. g
        # (slot g is the one BEFORE the current matched anchor).
        gt_obs = _any(gt_walk.slot_has_obs, prev_g + 1, g)
        llm_obs = _any(llm_walk.slot_has_obs, prev_l + 1, l)
        gt_keys = _union_keys(gt_walk.slot_keys, prev_g + 1, g)
        llm_keys = _union_keys(llm_walk.slot_keys, prev_l + 1, l)
        gt_kws = _union_keys(gt_walk.slot_keywords, prev_g + 1, g)
        llm_kws = _union_keys(llm_walk.slot_keywords, prev_l + 1, l)
        buckets.append({
            "anchor_gt": gt_seq[g],
            "anchor_llm": llm_seq[l],
            "gt_obs": gt_obs,
            "llm_obs": llm_obs,
            "gt_keys": sorted(gt_keys),
            "llm_keys": sorted(llm_keys),
            "gt_keywords": sorted(gt_kws),
            "llm_keywords": sorted(llm_kws),
        })
        prev_g, prev_l = g, l

    # tail bucket: slots after the last matched anchor (or all slots if no match)
    tail_gt = _any(gt_walk.slot_has_obs, prev_g + 1, len(gt_walk.slot_has_obs) - 1)
    tail_llm = _any(llm_walk.slot_has_obs, prev_l + 1, len(llm_walk.slot_has_obs) - 1)
    tail_gt_keys = _union_keys(gt_walk.slot_keys, prev_g + 1, len(gt_walk.slot_keys) - 1)
    tail_llm_keys = _union_keys(llm_walk.slot_keys, prev_l + 1, len(llm_walk.slot_keys) - 1)
    tail_gt_kws = _union_keys(gt_walk.slot_keywords, prev_g + 1, len(gt_walk.slot_keywords) - 1)
    tail_llm_kws = _union_keys(llm_walk.slot_keywords, prev_l + 1, len(llm_walk.slot_keywords) - 1)
    buckets.append({
        "anchor_gt": "<tail>",
        "anchor_llm": "<tail>",
        "gt_obs": tail_gt,
        "llm_obs": tail_llm,
        "gt_keys": sorted(tail_gt_keys),
        "llm_keys": sorted(tail_llm_keys),
        "gt_keywords": sorted(tail_gt_kws),
        "llm_keywords": sorted(tail_llm_kws),
    })

    # ---- Position F1 ------------------------------------------------------
    # Binary "is there obs in this bucket?" per side.
    tp = sum(1 for b in buckets if b["gt_obs"] and b["llm_obs"])
    fp = sum(1 for b in buckets if (not b["gt_obs"]) and b["llm_obs"])
    fn = sum(1 for b in buckets if b["gt_obs"] and (not b["llm_obs"]))

    if tp + fp == 0:
        precision = 1.0 if fn == 0 else 0.0
    else:
        precision = tp / (tp + fp)
    if tp + fn == 0:
        recall = 1.0 if fp == 0 else 0.0
    else:
        recall = tp / (tp + fn)
    f1 = (
        0.0 if (precision + recall) == 0
        else 2 * precision * recall / (precision + recall)
    )

    # ---- Key F1 (INDEPENDENT axis) ----------------------------------------
    # Asks: "Among buckets where BOTH sides emit obs, did the LLM use the
    # same attribute / span / event keys that GT prescribed?"
    #
    # Comparability rule: a bucket counts toward Key F1 only when
    #   (1) BOTH sides emitted obs in this bucket (position aligned), AND
    #   (2) GT itself emitted at least one named key in this bucket.
    #
    # The second condition is critical. When GT uses log-only telemetry
    # (no keys recorded by the extractor), there is no "suitable key set"
    # to validate against — so any keys the LLM emits there are unanchored,
    # not wrong. Counting LLM's extra keys as FP would conflate a
    # telemetry-type difference (log vs span+attr) with a key-choice error.
    # Position F1 already captures presence; Key F1 stays focused on key
    # agreement when GT defines what the keys should be.
    #
    # If NO buckets are key-comparable, Key F1 is reported as ``None`` (N/A):
    # we cannot legitimately give the LLM a 0 or a 1, we simply have no data
    # on this axis. Downstream aggregators must skip ``None`` cells.
    key_tp = 0
    key_fp = 0
    key_fn = 0
    n_key_comparable = 0
    for b in buckets:
        if not (b["gt_obs"] and b["llm_obs"]):
            continue
        gk = set(b["gt_keys"])
        if not gk:
            # GT defines no keys here — bucket is not comparable.
            continue
        lk = set(b["llm_keys"])
        n_key_comparable += 1
        key_tp += len(gk & lk)
        key_fp += len(lk - gk)
        key_fn += len(gk - lk)

    if n_key_comparable == 0:
        key_precision = None
        key_recall = None
        key_f1 = None
    else:
        if key_tp + key_fp == 0:
            key_precision = 0.0
        else:
            key_precision = key_tp / (key_tp + key_fp)
        if key_tp + key_fn == 0:
            key_recall = 0.0
        else:
            key_recall = key_tp / (key_tp + key_fn)
        key_f1 = (
            0.0 if (key_precision + key_recall) == 0
            else 2 * key_precision * key_recall / (key_precision + key_recall)
        )

    # ---- Key F1 (BAG, lenient token-level, INDEPENDENT axis) -------------
    # Same comparability rule as strict Key F1, but the per-side bag is the
    # full token bag harvested by ``_obs_stmt_keywords`` (string literals +
    # identifiers + attribute names + kwarg names, tokenised + stop-words
    # filtered). This gives credit for things like:
    #   GT  : span.set_attribute('app.product.id', request_product_id)
    #   LLM : span.set_attribute('product.id',     str(request_product_id))
    # Strict Key F1 sees {app.product.id} vs {product.id} -> 0.
    # Bag    Key F1 sees {app,product,request} vs {product,request,str} -> 0.67.
    #
    # Recall is the headline of this axis: it answers "did the LLM record
    # the concepts GT cared about?". Precision is more affected by LLM
    # verbosity (LLMs often add OTel semconv attrs GT didn't bother with).
    key_bag_tp = 0
    key_bag_fp = 0
    key_bag_fn = 0
    n_key_bag_comparable = 0
    for b in buckets:
        if not (b["gt_obs"] and b["llm_obs"]):
            continue
        gkw = set(b["gt_keywords"])
        if not gkw:
            # GT obs in this bucket produced no semantic tokens at all
            # (e.g. ``span.record_exception(exc)`` alone) — not comparable.
            continue
        lkw = set(b["llm_keywords"])
        n_key_bag_comparable += 1
        key_bag_tp += len(gkw & lkw)
        key_bag_fp += len(lkw - gkw)
        key_bag_fn += len(gkw - lkw)

    if n_key_bag_comparable == 0:
        key_bag_precision = None
        key_bag_recall = None
        key_bag_f1 = None
    else:
        if key_bag_tp + key_bag_fp == 0:
            key_bag_precision = 0.0
        else:
            key_bag_precision = key_bag_tp / (key_bag_tp + key_bag_fp)
        if key_bag_tp + key_bag_fn == 0:
            key_bag_recall = 0.0
        else:
            key_bag_recall = key_bag_tp / (key_bag_tp + key_bag_fn)
        key_bag_f1 = (
            0.0 if (key_bag_precision + key_bag_recall) == 0
            else 2 * key_bag_precision * key_bag_recall / (key_bag_precision + key_bag_recall)
        )

    return {
        "n_anchors_gt": len(gt_seq),
        "n_anchors_llm": len(llm_seq),
        "n_anchors_aligned": len(matched),
        "n_buckets": len(buckets),
        "n_gt_obs_buckets": sum(1 for b in buckets if b["gt_obs"]),
        "n_llm_obs_buckets": sum(1 for b in buckets if b["llm_obs"]),
        # Position F1 (kept flat for backward compatibility with rescore.py)
        "tp": tp, "fp": fp, "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        # Key F1 (NEW, independent of position F1). ``None`` when there are
        # no key-comparable buckets (i.e. nothing to measure on this axis).
        "key_tp": key_tp, "key_fp": key_fp, "key_fn": key_fn,
        "key_n_comparable_buckets": n_key_comparable,
        "key_precision": None if key_precision is None else round(key_precision, 4),
        "key_recall":    None if key_recall    is None else round(key_recall, 4),
        "key_f1":        None if key_f1        is None else round(key_f1, 4),
        # Key F1 (BAG, lenient token-level). Headline = recall, since LLMs
        # tend to over-record (precision pessimistic) but GT defines what
        # MUST be covered (recall = concept coverage).
        "key_bag_tp": key_bag_tp, "key_bag_fp": key_bag_fp, "key_bag_fn": key_bag_fn,
        "key_bag_n_comparable_buckets": n_key_bag_comparable,
        "key_bag_precision": None if key_bag_precision is None else round(key_bag_precision, 4),
        "key_bag_recall":    None if key_bag_recall    is None else round(key_bag_recall, 4),
        "key_bag_f1":        None if key_bag_f1        is None else round(key_bag_f1, 4),
        "buckets": buckets,
    }
