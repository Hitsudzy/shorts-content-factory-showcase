#!/usr/bin/env python3
"""CF-0229: the shared half of the "no subprocess without a ceiling" guard.

The rule was built in agents/video-editor over CF-0077 -> CF-0128 -> CF-0132
-> CF-0135 and lived in one file there (tests/test_common_timeouts.py). The
root starts children too, and a second copy of that file would be a second
copy of the rule - the CF-0159 drift. So the rule is split:

  * here, the part that is the same in every repository: how an AST scan
    finds a child being started, what counts as "carries a ceiling", and the
    structural rule CF-0135 found the hard way (a function that starts a
    child and drains its pipe on the same thread cannot hold a deadline);
  * in each repository's own test, the part that is not: which directories
    are scanned, the registry of Popen sites with the one line saying what
    bounds each wait (POPEN_SITES), and the behavioural checks of that
    repository's helpers.

Everything here returns findings as data; the repository's test turns them
into `_check(...)` lines with its own wording and fix hints. Nothing is
imported from beside this file, so a neighbouring repository loads it by path
(`spec_from_file_location`) the same way it loads shared/channel_ids.py.
"""
import ast
from pathlib import Path

# subprocess functions that wait on the child and take `timeout=`.
WAITING_STARTERS = ("run", "call", "check_call", "check_output")
# every way to start a child through the subprocess module.
STARTERS = WAITING_STARTERS + ("Popen",)


def python_files(base, skip=()):
    """`*.py` under `base`, plus extension-less files that are Python scripts
    (`#!/usr/bin/env python...`), e.g. scripts/runlog. `skip` names directory
    parts never entered (a media pool, a venv) - they are pruned, not walked,
    so a directory of thousands of clips costs nothing."""
    base = Path(base)
    skip = set(skip) | {"__pycache__", ".venv", "venv", "node_modules", ".git"}
    out = []
    if not base.is_dir():
        return out
    stack = [base]
    while stack:
        d = stack.pop()
        for p in sorted(d.iterdir()):
            if p.is_dir():
                if p.name not in skip and not p.name.startswith("."):
                    stack.append(p)
            elif p.suffix == ".py":
                out.append(p)
            elif p.suffix == "" and p.is_file():
                try:
                    with p.open("rb") as fh:
                        head = fh.read(32)
                except OSError:
                    continue
                if head.startswith(b"#!") and b"python" in head:
                    out.append(p)
    return sorted(out)


def parse(path):
    return ast.parse(Path(path).read_text(encoding="utf-8"), filename=str(path))


def subprocess_calls(tree, attrs=STARTERS):
    """Every `subprocess.<attr>(...)` call in the module."""
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr in attrs and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "subprocess"]


def has_ceiling(call):
    """True when the call names `timeout=` itself. A `**kw` pass-through does
    not count: the ceiling is then a property of every caller, which an AST
    scan of this call cannot see - such a site is either rewritten to name it
    or exempted by the repository with a reason."""
    return any(kw.arg == "timeout" for kw in call.keywords)


def waits_without_ceiling(tree):
    """subprocess.run/call/check_call/check_output calls with no `timeout=`."""
    return [c for c in subprocess_calls(tree, WAITING_STARTERS) if not has_ceiling(c)]


def popen_calls(tree):
    return subprocess_calls(tree, ("Popen",))


def functions(tree):
    return [n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def own_nodes(fn):
    """A function's own body, not counting functions defined inside it - a
    reader defined there runs on another thread, which is the whole point."""
    out = []

    def walk(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            out.append(child)
            walk(child)

    walk(fn)
    return out


def reads_a_pipe(node):
    """`for line in <x>.stdout|stderr:` - a read with no deadline of its own."""
    return (isinstance(node, ast.For) and isinstance(node.iter, ast.Attribute)
            and node.iter.attr in ("stdout", "stderr"))


def popen_functions(tree):
    """`[(fn, first pipe read in its own body or None)]` for every function
    that starts a child with `.Popen(...)` in its own body (CF-0135's rule:
    the read belongs on another thread or behind a bounded wait)."""
    out = []
    for fn in functions(tree):
        own = own_nodes(fn)
        if not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                   and n.func.attr == "Popen" for n in own):
            continue
        reads = [n for n in own if reads_a_pipe(n)]
        out.append((fn, reads[0] if reads else None))
    return out


def catches_timeout(try_node):
    for handler in try_node.handlers:
        raised = handler.type
        candidates = raised.elts if isinstance(raised, ast.Tuple) else [raised]
        for node in candidates:
            if isinstance(node, ast.Attribute) and node.attr == "TimeoutExpired":
                return True
    return False


def calls_named(tree, attr):
    """Every `<x>.<attr>(...)` call, each paired with whether it sits inside a
    `try` that catches subprocess.TimeoutExpired (CF-0132's run_child scan)."""
    found = []

    def walk(node, guarded):
        if isinstance(node, ast.Try):
            inner = guarded or catches_timeout(node)
            for child in node.body:
                walk(child, inner)
            for child in node.handlers + node.orelse + node.finalbody:
                walk(child, guarded)
            return
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == attr):
            found.append((node, guarded))
        for child in ast.iter_child_nodes(node):
            walk(child, guarded)

    walk(tree, False)
    return found


def popen_registry_drift(found, registry):
    """`found` is `{site: [lineno, ...]}` of the Popen calls a scan saw,
    `registry` the repository's POPEN_SITES. Returns (unregistered, stale):
    sites that start a Popen nobody has described, and descriptions of sites
    that no longer start one."""
    unregistered = sorted(s for s in found if s not in registry)
    stale = sorted(s for s in registry if s not in found)
    return unregistered, stale


def owners(tree):
    """`{id(node): name of the innermost function that holds it}` - for a
    repository that exempts a pass-through site by (file, function) rather
    than by a line number that moves with every edit above it."""
    out = {}

    def walk(node, name):
        for child in ast.iter_child_nodes(node):
            inner = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else name
            out[id(child)] = inner
            walk(child, inner)

    walk(tree, None)
    return out
