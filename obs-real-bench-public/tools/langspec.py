"""
Per-language configuration registry for polyglot obs-bench pipelines.

Adding a new language = add one `LangSpec` entry below. Everything downstream
(extractor, stripper, function_io, build_siblings, mine) routes through this
table; there should be NO hard-coded `if language == "python"` branches in
those files — they should dispatch on `LANGSPECS[lang]` instead.

Python intentionally keeps its `ast`-based code path (see Python AST notes in
session memory) for F1 parity. The Python entry here is documentation /
fall-through for non-pipeline consumers (e.g. file-extension lookup).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class LangSpec:
    # -----------------------------------------------------------------
    # identification
    # -----------------------------------------------------------------
    name: str                              # canonical full name, e.g. 'go'
    aliases: tuple[str, ...]               # accepted spellings in --language args, e.g. ('go', 'golang')
    short: str                             # short code used in instance ids, e.g. 'go'
    extensions: tuple[str, ...]            # source-file extensions, e.g. ('.go',)
    fence: str                             # markdown code-block tag, e.g. 'go'

    # -----------------------------------------------------------------
    # tree-sitter grammar — node kinds we care about
    # the names here are the strings returned by Node.kind()
    # -----------------------------------------------------------------
    fn_kinds: tuple[str, ...]              # function/method declaration nodes
    fn_name_fields: tuple[str, ...]        # field names to find the symbol identifier on a fn node
    class_kinds: tuple[str, ...] = ()      # class-like wrappers (Python/Java/C++/C#)
    call_kinds: tuple[str, ...] = ()       # call/invocation expression nodes
    call_func_field: str = "function"      # field on a call node holding the receiver expression
    call_args_field: str = "arguments"     # field on a call node holding the arg list
    assign_kinds: tuple[str, ...] = ()     # assignment statement nodes (incl. short-var-decl etc.)
    with_kinds: tuple[str, ...] = ()       # `with`-equivalent scoped resource statements (Python/C# using/Java try-w/r)
    defer_kinds: tuple[str, ...] = ()      # Go-only: `defer X`
    string_literal_kinds: tuple[str, ...] = ("string_literal",)
    identifier_kinds: tuple[str, ...] = ("identifier",)
    attribute_kinds: tuple[str, ...] = ()  # foo.bar style member access; varies by lang

    # -----------------------------------------------------------------
    # obs vocabulary (method names that count as obs-on-receiver)
    # each set is method-name strings; receiver classification is via
    # `receiver_kind()` (substring-on-lowercased-name-chain, same shape
    # for every lang).
    # -----------------------------------------------------------------
    span_methods: frozenset[str] = frozenset()
    tracer_methods: frozenset[str] = frozenset()
    logger_methods: frozenset[str] = frozenset()
    metric_methods: frozenset[str] = frozenset()

    # methods that on receiver of kind=tracer/metric BEGIN a setup expression
    # (e.g. `tracer.Tracer("name")`, `meter.NewCounter(...)`); detected for
    # `is_obs_assignment` purposes. Use prefix-match.
    setup_method_prefixes: tuple[str, ...] = ("get_", "create_", "start_", "New", "Get")

    # words anywhere in the name chain that mark a receiver as obs.
    # Same lexicon for every language.
    obs_word_tokens: frozenset[str] = field(
        default_factory=lambda: frozenset({
            "span", "spans",
            "tracer", "tracers", "trace", "traces",
            "logger", "log",
            "meter", "counter", "histogram", "gauge",
            "metric", "metrics",
            "telemetry", "otel",
            "instrument", "instruments", "instr",
        })
    )

    # -----------------------------------------------------------------
    # mapping: logger method → ObsSite.type label
    # all langs share the same 4-bucket logger type schema
    # -----------------------------------------------------------------
    log_method_to_type: dict[str, str] = field(
        default_factory=lambda: {
            "debug": "log_debug",
            "info": "log_info",
            "warning": "log_warn",
            "warn": "log_warn",
            "error": "log_error",
            "exception": "log_error",
            "critical": "log_error",
            "fatal": "log_error",
        }
    )


# -----------------------------------------------------------------------------
# registry
# -----------------------------------------------------------------------------

LANGSPECS: dict[str, LangSpec] = {}


def _register(spec: LangSpec) -> None:
    LANGSPECS[spec.name] = spec
    for alias in spec.aliases:
        LANGSPECS[alias] = spec


def get(language: str) -> Optional[LangSpec]:
    """Resolve a language tag (case-insensitive) to its LangSpec, or None."""
    if not language:
        return None
    return LANGSPECS.get(language.lower())


def require(language: str) -> LangSpec:
    """Like `get()` but raises if the language is not registered."""
    spec = get(language)
    if spec is None:
        raise ValueError(
            f"langspec: unknown language={language!r}. "
            f"Known: {sorted(set(s.name for s in LANGSPECS.values()))}"
        )
    return spec


# -----------------------------------------------------------------------------
# Python
#
# IMPORTANT: the obs-detection pipeline for Python uses the legacy `ast`-based
# code in `extract/python_extract.py`, `strip/python_strip.py`,
# `function_io.py`, and `score_anchor.py`. The LangSpec entry below is only
# consulted for non-pipeline concerns (file extension, fence tag, mine_polyglot
# grammar config). It MUST NOT diverge from the `ast` code.
# -----------------------------------------------------------------------------

_register(LangSpec(
    name="python",
    aliases=("py",),
    short="py",
    extensions=(".py",),
    fence="python",
    fn_kinds=("function_definition",),
    fn_name_fields=("name",),
    class_kinds=("class_definition",),
    call_kinds=("call",),
    call_func_field="function",
    call_args_field="arguments",
    assign_kinds=("assignment", "augmented_assignment"),
    with_kinds=("with_statement",),
    defer_kinds=(),
    attribute_kinds=("attribute",),
    span_methods=frozenset({
        "set_attribute", "set_attributes",
        "add_event",
        "record_exception", "set_status",
    }),
    tracer_methods=frozenset({"start_span", "start_as_current_span"}),
    logger_methods=frozenset({
        "debug", "info", "warning", "warn",
        "error", "exception", "critical", "fatal",
    }),
    metric_methods=frozenset({"add", "inc", "record", "observe"}),
    setup_method_prefixes=("get_", "create_", "start_"),
))


# -----------------------------------------------------------------------------
# Go
#
# Tree-sitter-go's relevant node kinds:
#   function_declaration, method_declaration
#   call_expression                       (no `field name` for func, just first child)
#   selector_expression                   foo.bar  (operand + field)
#   short_var_declaration                 ctx, span := tracer.Start(ctx, "F")
#   assignment_statement                  span = tracer.Start(...)
#   defer_statement                       defer span.End()
#   interpreted_string_literal            "..."  (also raw_string_literal for backtick)
#   identifier                            x
#
# OTel-Go SDK call shapes:
#   span: SetAttributes, AddEvent, RecordError, SetStatus, End
#   tracer: Start (returns ctx, span; usually via :=)
#   logger (zerolog typical OTel-demo style): tied to .Info().Str(...).Msg("...")
#     We treat the .Info / .Debug / .Warn / .Error / .Fatal call as obs.
#   metric: Add (counter), Record (histogram/recorder), Observe (gauge async)
# -----------------------------------------------------------------------------

_register(LangSpec(
    name="go",
    aliases=("golang",),
    short="go",
    extensions=(".go",),
    fence="go",
    fn_kinds=("function_declaration", "method_declaration"),
    fn_name_fields=("name",),
    class_kinds=(),
    call_kinds=("call_expression",),
    call_func_field="function",
    call_args_field="arguments",
    assign_kinds=("short_var_declaration", "assignment_statement", "var_spec"),
    with_kinds=(),
    defer_kinds=("defer_statement",),
    string_literal_kinds=("interpreted_string_literal", "raw_string_literal"),
    identifier_kinds=("identifier", "type_identifier", "field_identifier"),
    attribute_kinds=("selector_expression",),
    span_methods=frozenset({
        "SetAttributes", "SetAttribute",
        "AddEvent",
        "RecordError", "SetStatus",
    }),
    tracer_methods=frozenset({"Start"}),
    logger_methods=frozenset({
        # zerolog-style level openers; treated as a log site even though the
        # full chain ends with .Msg(...). Capture happens at the level method.
        "Debug", "Info", "Warn", "Error", "Fatal", "Panic",
        # zap / logr conventions
        "Debugw", "Infow", "Warnw", "Errorw",
        # log/slog (Go 1.21+)
        "DebugContext", "InfoContext", "WarnContext", "ErrorContext",
        # slog's canonical zero-alloc API
        "Log", "LogAttrs",
        # logrus / sugared methods (less common in this corpus but cheap)
        "Print", "Printf", "Println",
        "Tracef", "Debugf", "Infof", "Warnf", "Errorf", "Fatalf",
    }),
    metric_methods=frozenset({"Add", "Record", "Observe"}),
    setup_method_prefixes=("Get", "New", "Tracer", "Meter", "SpanFrom", "From"),
    log_method_to_type={
        # Go convention is capitalised; reuse the same 4-bucket schema
        "Debug": "log_debug", "DebugContext": "log_debug", "Debugw": "log_debug",
        "Debugf": "log_debug",
        "Info": "log_info",   "InfoContext": "log_info",   "Infow": "log_info",
        "Infof": "log_info",
        "Log": "log_info", "LogAttrs": "log_info",  # slog: level inside args
        "Print": "log_info", "Printf": "log_info", "Println": "log_info",
        "Warn": "log_warn",   "WarnContext": "log_warn",   "Warnw": "log_warn",
        "Warnf": "log_warn",
        "Error": "log_error", "ErrorContext": "log_error", "Errorw": "log_error",
        "Errorf": "log_error",
        "Fatal": "log_error", "Fatalf": "log_error", "Panic": "log_error",
    },
))


# -----------------------------------------------------------------------------
# Java
# -----------------------------------------------------------------------------

_register(LangSpec(
    name="java",
    aliases=(),
    short="java",
    extensions=(".java",),
    fence="java",
    fn_kinds=("method_declaration", "constructor_declaration"),
    fn_name_fields=("name",),
    class_kinds=("class_declaration", "interface_declaration", "enum_declaration"),
    call_kinds=("method_invocation",),
    call_func_field="name",  # for method_invocation, `name` field holds the method identifier; receiver is `object`
    call_args_field="arguments",
    assign_kinds=("assignment_expression", "local_variable_declaration"),
    with_kinds=("try_with_resources_statement",),
    defer_kinds=(),
    string_literal_kinds=("string_literal",),
    identifier_kinds=("identifier", "type_identifier"),
    attribute_kinds=("field_access",),
    span_methods=frozenset({
        "setAttribute", "setAttributes",
        "addEvent",
        "recordException", "setStatus",
        "end",
    }),
    tracer_methods=frozenset({"spanBuilder", "startSpan"}),
    logger_methods=frozenset({
        "debug", "info", "warn", "error", "trace", "fatal",
        "atDebug", "atInfo", "atWarn", "atError",  # SLF4J 2.x fluent API
    }),
    metric_methods=frozenset({"add", "record", "observe"}),
    setup_method_prefixes=("get", "create", "build"),
))


# -----------------------------------------------------------------------------
# TypeScript / JavaScript (OTel JS SDK)
# -----------------------------------------------------------------------------

_register(LangSpec(
    name="typescript",
    aliases=("ts",),
    short="ts",
    extensions=(".ts", ".tsx"),
    fence="typescript",
    fn_kinds=(
        "function_declaration", "method_definition",
        "arrow_function", "function_expression",
    ),
    fn_name_fields=("name",),
    class_kinds=("class_declaration",),
    call_kinds=("call_expression",),
    call_func_field="function",
    call_args_field="arguments",
    assign_kinds=("variable_declarator", "assignment_expression"),
    with_kinds=(),
    defer_kinds=(),
    string_literal_kinds=("string", "template_string"),
    identifier_kinds=("identifier", "property_identifier", "type_identifier"),
    attribute_kinds=("member_expression",),
    span_methods=frozenset({
        "setAttribute", "setAttributes",
        "addEvent",
        "recordException", "setStatus",
        "end",
    }),
    tracer_methods=frozenset({"startSpan", "startActiveSpan"}),
    logger_methods=frozenset({
        "debug", "info", "warn", "error", "fatal", "trace",
    }),
    metric_methods=frozenset({"add", "record", "observe"}),
    setup_method_prefixes=("get", "create"),
))

_register(LangSpec(
    name="javascript",
    aliases=("js",),
    short="js",
    extensions=(".js", ".jsx", ".mjs", ".cjs"),
    fence="javascript",
    fn_kinds=(
        "function_declaration", "method_definition",
        "arrow_function", "function_expression",
    ),
    fn_name_fields=("name",),
    class_kinds=("class_declaration",),
    call_kinds=("call_expression",),
    call_func_field="function",
    call_args_field="arguments",
    assign_kinds=("variable_declarator", "assignment_expression"),
    with_kinds=(),
    defer_kinds=(),
    string_literal_kinds=("string", "template_string"),
    identifier_kinds=("identifier", "property_identifier"),
    attribute_kinds=("member_expression",),
    span_methods=frozenset({
        "setAttribute", "setAttributes",
        "addEvent",
        "recordException", "setStatus",
        "end",
    }),
    tracer_methods=frozenset({"startSpan", "startActiveSpan"}),
    logger_methods=frozenset({
        "debug", "info", "warn", "error", "fatal", "trace",
    }),
    metric_methods=frozenset({"add", "record", "observe"}),
    setup_method_prefixes=("get", "create"),
))


# -----------------------------------------------------------------------------
# C# (.NET / OTel .NET SDK)
#
# Idioms:
#   ActivitySource.StartActivity("name") returns Activity (≈ span)
#   activity.SetTag("k", v) / .AddEvent(...) / .RecordException(...)
#   ILogger.LogInformation / LogDebug / LogWarning / LogError
#   counter.Add(1, KeyValuePair[]) / histogram.Record(value, ...)
# -----------------------------------------------------------------------------

_register(LangSpec(
    name="csharp",
    aliases=("cs", "c#"),
    short="cs",
    extensions=(".cs",),
    fence="csharp",
    fn_kinds=("method_declaration", "constructor_declaration", "local_function_statement"),
    fn_name_fields=("name",),
    class_kinds=("class_declaration", "struct_declaration", "interface_declaration"),
    call_kinds=("invocation_expression",),
    call_func_field="function",
    call_args_field="arguments",
    assign_kinds=(
        "assignment_expression",
        "variable_declarator",
        "local_declaration_statement",
    ),
    with_kinds=("using_statement",),
    defer_kinds=(),
    string_literal_kinds=("string_literal", "verbatim_string_literal", "raw_string_literal"),
    identifier_kinds=("identifier",),
    attribute_kinds=("member_access_expression",),
    span_methods=frozenset({
        "SetTag", "SetAttribute",
        "AddEvent", "AddTag",
        "RecordException", "SetStatus",
    }),
    tracer_methods=frozenset({"StartActivity", "StartActivityWithLinks"}),
    logger_methods=frozenset({
        "LogDebug", "LogInformation", "LogWarning", "LogError",
        "LogCritical", "LogTrace",
        # plain ILogger.Log(level, ...)
        "Log",
    }),
    metric_methods=frozenset({"Add", "Record", "Observe"}),
    setup_method_prefixes=("Get", "Create", "Start"),
    log_method_to_type={
        "LogTrace": "log_debug", "LogDebug": "log_debug",
        "LogInformation": "log_info",
        "LogWarning": "log_warn",
        "LogError": "log_error", "LogCritical": "log_error",
        "Log": "log_info",  # generic, default bucket
    },
))


# -----------------------------------------------------------------------------# Rust
#
# Tree-sitter-rust kinds:
#   function_item                         fn name(...) -> T { ... }
#     fields: name -> identifier, parameters -> parameters, body -> block
#     modifiers: visibility_modifier, function_modifiers (async/unsafe/extern)
#   call_expression                       foo.bar(args) or foo(args)
#     fields: function -> expression, arguments -> arguments
#   field_expression                      foo.bar (member access)
#   let_declaration                       let x = ...
#   string_literal / raw_string_literal
#
# OTel-Rust SDK shapes (otel demo uses tracing crate):
#   span.set_attribute(K::new("k", v)) / span.add_event(...) / span.record(...)
#   tracer.start("name") / tracer.in_span("name", |_cx| { ... })
#   tracing::info!("msg") / debug! / warn! / error! (macros; expand to events)
# -----------------------------------------------------------------------------

_register(LangSpec(
    name="rust",
    aliases=("rs",),
    short="rs",
    extensions=(".rs",),
    fence="rust",
    fn_kinds=("function_item",),
    fn_name_fields=("name",),
    class_kinds=("impl_item", "trait_item"),
    # `macro_invocation` catches the tracing-crate idiom (info!/warn!/error!
    # /event!/info_span! ...), which is the dominant obs surface in real
    # Rust code. See ts_obs.is_obs_call / call_args / _selector_chain for
    # the macro-aware branches.
    call_kinds=("call_expression", "macro_invocation"),
    call_func_field="function",
    call_args_field="arguments",
    assign_kinds=("let_declaration", "assignment_expression"),
    with_kinds=(),
    defer_kinds=(),
    string_literal_kinds=("string_literal", "raw_string_literal"),
    identifier_kinds=("identifier", "type_identifier", "field_identifier"),
    attribute_kinds=("field_expression", "scoped_identifier"),
    span_methods=frozenset({
        "set_attribute", "set_attributes",
        "add_event",
        "record_error", "record_exception", "set_status",
        "record",  # tracing::Span::record(k, v)
        "end",
    }),
    tracer_methods=frozenset({
        "start", "start_as_current", "in_span", "span",
        # tracing-crate span macros (recognised when used as macro_invocation)
        "info_span", "warn_span", "error_span", "debug_span", "trace_span",
        "event", "instrument",
    }),
    logger_methods=frozenset({
        "debug", "info", "warn", "error", "trace",
        # Catches both `logger.info(...)` (call_expression) and the
        # tracing crate's bare `info!(...)` (macro_invocation).
    }),
    metric_methods=frozenset({"add", "record", "observe", "inc"}),
    setup_method_prefixes=("get_", "new_", "create_", "start_"),
))


# -----------------------------------------------------------------------------
# Ruby
#
# Tree-sitter-ruby kinds:
#   method, singleton_method              def name(args); body; end
#     fields: name -> identifier, parameters -> method_parameters, body
#   call                                  receiver.method(args)
#     fields: method, receiver, arguments
#   identifier
#   string                                 "..." or '...'
#
# OTel-Ruby SDK shapes:
#   OpenTelemetry.tracer_provider.tracer("name")
#   span.set_attribute("k", v) / span.add_event("name", attributes: {...})
#   logger.info "msg" / logger.error  (Ruby has implicit calls; tree-sitter
#   uses `command` for paren-less calls but treats them as `call` shapes too)
# -----------------------------------------------------------------------------

_register(LangSpec(
    name="ruby",
    aliases=("rb",),
    short="rb",
    extensions=(".rb",),
    fence="ruby",
    fn_kinds=("method", "singleton_method"),
    fn_name_fields=("name",),
    class_kinds=("class", "module"),
    call_kinds=("call", "command", "command_call"),
    call_func_field="method",
    call_args_field="arguments",
    assign_kinds=("assignment", "operator_assignment", "multiple_assignment"),
    with_kinds=(),
    defer_kinds=(),
    string_literal_kinds=("string",),
    identifier_kinds=("identifier", "constant"),
    attribute_kinds=("scope_resolution",),
    span_methods=frozenset({
        "set_attribute", "add_attributes", "add_event",
        "record_exception", "status=", "set_status",
        "finish",
    }),
    tracer_methods=frozenset({"in_span", "start_span", "start_root_span"}),
    logger_methods=frozenset({"debug", "info", "warn", "error", "fatal"}),
    metric_methods=frozenset({"add", "record", "observe", "inc"}),
    setup_method_prefixes=("get_", "create_", "start_"),
))


# -----------------------------------------------------------------------------
# PHP
#
# Tree-sitter-php kinds:
#   function_definition, method_declaration
#     fields: name -> name, parameters, body -> compound_statement
#   function_call_expression                  foo(args)
#   member_call_expression                    $obj->foo(args)
#     fields: object, name, arguments
#   variable_name, assignment_expression
#   string                                    "..." 'literal'
#   namespace_use_declaration                 use Foo\Bar;
#
# OTel-PHP SDK shapes:
#   $tracer->spanBuilder("name")->startSpan()
#   $span->setAttribute("k", v) / $span->addEvent(...) / $span->end()
#   $logger->info("msg")
# -----------------------------------------------------------------------------

_register(LangSpec(
    name="php",
    aliases=(),
    short="php",
    extensions=(".php",),
    fence="php",
    fn_kinds=("function_definition", "method_declaration"),
    fn_name_fields=("name",),
    class_kinds=("class_declaration", "interface_declaration", "trait_declaration"),
    call_kinds=("function_call_expression", "member_call_expression", "scoped_call_expression"),
    call_func_field="function",
    call_args_field="arguments",
    assign_kinds=("assignment_expression",),
    with_kinds=(),
    defer_kinds=(),
    string_literal_kinds=("string", "encapsed_string", "string_value"),
    identifier_kinds=("name", "variable_name"),
    attribute_kinds=("member_access_expression",),
    span_methods=frozenset({
        "setAttribute", "setAttributes",
        "addEvent",
        "recordException", "setStatus",
        "end", "finish",
    }),
    tracer_methods=frozenset({"spanBuilder", "startSpan", "startAndActivateSpan"}),
    logger_methods=frozenset({
        "debug", "info", "warning", "warn", "error", "critical",
        "alert", "emergency", "notice", "log",
    }),
    metric_methods=frozenset({"add", "record", "observe"}),
    setup_method_prefixes=("get", "create", "build"),
))


# -----------------------------------------------------------------------------
# C++ (gRPC + OTel C++ SDK)
#
# Tree-sitter-cpp kinds:
#   function_definition
#     fields: type, declarator -> function_declarator, body -> compound_statement
#   function_declarator
#     fields: declarator -> identifier | field_identifier | qualified_identifier
#             parameters -> parameter_list
#   call_expression                       foo(args), foo->bar(args), foo.bar(args)
#     fields: function -> expression, arguments -> argument_list
#   field_expression                      a.b or a->b
#   declaration / init_declarator         T x = ...
#   string_literal                        "..."
#   qualified_identifier                  Foo::bar
#
# OTel-C++ SDK shapes:
#   tracer->StartSpan("name", options) -> nostd::shared_ptr<Span>
#   span->SetAttribute("k", v) / span->AddEvent(...) / span->End()
#   logger->Log(severity, "msg") / EmitLogRecord(...)
# -----------------------------------------------------------------------------

_register(LangSpec(
    name="cpp",
    aliases=("c++", "cplusplus"),
    short="cpp",
    extensions=(".cpp", ".cc", ".cxx", ".hpp", ".h"),
    fence="cpp",
    fn_kinds=("function_definition",),
    fn_name_fields=("declarator",),  # nested: declarator->declarator->identifier
    class_kinds=("class_specifier", "struct_specifier"),
    call_kinds=("call_expression",),
    call_func_field="function",
    call_args_field="arguments",
    assign_kinds=("declaration", "init_declarator", "assignment_expression"),
    with_kinds=(),
    defer_kinds=(),
    string_literal_kinds=("string_literal", "raw_string_literal"),
    identifier_kinds=("identifier", "field_identifier", "type_identifier", "qualified_identifier"),
    attribute_kinds=("field_expression",),
    span_methods=frozenset({
        "SetAttribute", "SetAttributes",
        "AddEvent",
        "RecordException", "SetStatus",
        "End",
    }),
    tracer_methods=frozenset({"StartSpan", "StartActiveSpan"}),
    logger_methods=frozenset({
        "Debug", "Info", "Warn", "Warning", "Error", "Fatal", "Trace",
        "Log", "EmitLogRecord",
    }),
    metric_methods=frozenset({"Add", "Record", "Observe"}),
    setup_method_prefixes=("Get", "Create", "Make", "New"),
))


# -----------------------------------------------------------------------------# Convenience lookups
# -----------------------------------------------------------------------------

def is_polyglot_pipeline(language: str) -> bool:
    """True when this language's pipeline routes through the tree-sitter path.

    Python alone keeps the legacy `ast` path for F1 parity; everything else
    goes through the tree-sitter implementations.
    """
    return language.lower() not in ("python", "py")
