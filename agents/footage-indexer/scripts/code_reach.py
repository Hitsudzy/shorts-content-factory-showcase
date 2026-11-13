#!/usr/bin/env python3
"""The part of a set of source files a given entry point can actually run,
and a digest of only that part (CF-0387).

`caption_cache` used to key `crop_bottom_cached` on the bytes of seven whole
files. That is safe and it is also a pool-wide invalidation for every edit to
any of them, including ones the measurement never executes: CF-0177 (an
`ImportError` guard around a CLI-only import), CF-0316 (the no-root stand-in in
`_runlog.py`), CF-0392 (two unused meme constants in `common.py`). CF-0179
measured that 15 of 38 invalidations in a month were of that kind, nearly all
from `common.py`, and declined to narrow the key on cost. Two incidents in
three days on a 4818-shot pool changed that arithmetic.

## What is digested

Every file is parsed, docstrings are dropped (comments never reach the AST),
and its top-level statements become *units*. Starting from the roots, a unit
is taken when it binds a name something already taken refers to:

* a bare name `n` in module M -> every top-level unit of M that binds `n`
  (a `def`, a `class`, an assignment, an import, or an `if`/`try` that binds
  it inside - `try: import x except ImportError: x = None` is one unit);
* `from X import a` (X in the set) -> `a` in X, followed across files, so a
  name re-exported through `common.py` from `repo_paths.py` lands in
  `repo_paths.py`;
* `X.attr` where `X` is an imported module of the set, top-level or imported
  inside the function -> `attr` in X; `X` used bare (passed as a value) ->
  all of X.

A module listed as *whole* contributes every unit, `if __name__ ==
"__main__":` included - that is for a file that is spawned as a script
rather than imported (`vision_worker.py`), where the entry point is the file.
Everywhere else the `__main__` block is dropped: an imported module does not
run it.

A module listed as *opaque* is never followed into. That is a claim that has
to be pinned by a behavioural test, not by the digest: for `_runlog` it is
"`run_child(cmd, **kw)` returns what `subprocess.run(cmd, **kw)` returns",
which is what accounting means.

Units are serialised by their own walker, not `ast.dump()`: `ast.dump`'s
output changed in 3.13 (empty fields omitted) and new node fields appear
between releases (`type_params` in 3.12), so a key computed by the indexer's
venv and one computed by the editor's must not depend on either. Fields that
are `None` or empty are skipped, and line/column attributes never enter.

## Failing closed

A demanded name that no unit of its module binds (`from common import
grab_frames` after a rename), an unreadable file, or a syntax error, gives
`None` - never a digest of less code. `None` compares unequal to every stamp.
"""
import ast
import hashlib
from pathlib import Path

DIGEST_CHARS = 12

# Attributes of a module object that are not definitions in it.
_DUNDER_OK = frozenset({"__file__", "__name__", "__doc__", "__dict__", "__spec__"})


class Unresolved(Exception):
    """A name the reached code demands that its module does not define."""


def _strip_docstrings(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:] or [ast.Pass()]
    return tree


def _is_main_guard(node):
    if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
        return False
    t = node.test
    sides = [t.left] + list(t.comparators)
    return (any(isinstance(s, ast.Name) and s.id == "__name__" for s in sides)
            and any(isinstance(s, ast.Constant) and s.value == "__main__" for s in sides))


def _target_names(target):
    if isinstance(target, ast.Name):
        yield target.id
    elif isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            yield from _target_names(elt)
    elif isinstance(target, ast.Starred):
        yield from _target_names(target.value)


def _import_bindings(node):
    """[(bound name, module, imported name or None for the module itself)]."""
    if isinstance(node, ast.Import):
        return [((a.asname or a.name.split(".")[0]), a.name.split(".")[0], None)
                for a in node.names]
    if isinstance(node, ast.ImportFrom) and not node.level and node.module:
        return [((a.asname or a.name), node.module.split(".")[0], a.name)
                for a in node.names]
    return []


def _bound(stmt):
    """Names a top-level statement binds at module scope."""
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {stmt.name}
    if isinstance(stmt, (ast.Import, ast.ImportFrom)):
        return {b for b, _, _ in _import_bindings(stmt)}
    if isinstance(stmt, ast.Assign):
        return {n for t in stmt.targets for n in _target_names(t)}
    if isinstance(stmt, (ast.AnnAssign, ast.AugAssign)):
        return set(_target_names(stmt.target))
    out = set()
    blocks = []
    if isinstance(stmt, (ast.If, ast.For, ast.While, ast.With)):
        blocks = [stmt.body, getattr(stmt, "orelse", [])]
        if isinstance(stmt, ast.For):
            out |= set(_target_names(stmt.target))
        if isinstance(stmt, ast.With):
            out |= {n for it in stmt.items if it.optional_vars is not None
                    for n in _target_names(it.optional_vars)}
    elif isinstance(stmt, ast.Try):
        blocks = [stmt.body, stmt.orelse, stmt.finalbody] + [h.body for h in stmt.handlers]
    for block in blocks:
        for s in block:
            out |= _bound(s)
    return out


def _serialise(node, h):
    if isinstance(node, ast.AST):
        h.update(type(node).__name__.encode())
        h.update(b"(")
        for field in node._fields:
            value = getattr(node, field, None)
            if value is None or value == []:
                continue
            h.update(field.encode())
            h.update(b"=")
            _serialise(value, h)
            h.update(b",")
        h.update(b")")
    elif isinstance(node, list):
        h.update(b"[")
        for item in node:
            _serialise(item, h)
            h.update(b";")
        h.update(b"]")
    else:
        h.update(type(node).__name__.encode())
        h.update(b":")
        h.update(repr(node).encode("utf-8", "backslashreplace"))


class Module:
    def __init__(self, name, text):
        self.name = name
        tree = _strip_docstrings(ast.parse(text))
        self.units = list(tree.body)
        self.binders = {}
        # module-level `import X` bindings: bound name -> X
        self.module_aliases = {}
        # For an import line taken for some of its names only: which. A line
        # absent here was taken whole.
        self.import_names = {}
        for i, stmt in enumerate(self.units):
            for n in _bound(stmt):
                self.binders.setdefault(n, []).append(i)
            for node in ast.walk(stmt) if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else ():
                for b, mod, what in _import_bindings(node):
                    if what is None:
                        self.module_aliases[b] = mod


def reach(sources, roots, whole=(), opaque=()):
    """({module name: Module}, {module name: [unit indexes taken, in source
    order]}).

    `sources` is {module name: source text}; `roots` is [(module, name)];
    `whole` and `opaque` are module names. Raises SyntaxError on a file that
    does not parse and `Unresolved` on a demanded name nobody defines.
    """
    mods = {name: Module(name, text) for name, text in sources.items()}
    opaque = set(opaque)
    taken = {name: set() for name in mods}
    seen = set()
    queue = list(roots) + [(m, "*") for m in whole]

    def demand(module, name):
        if module in mods and module not in opaque:
            queue.append((module, name))

    def take(m, i, demanded):
        first = i not in taken[m.name]
        taken[m.name].add(i)
        unit = m.units[i]
        if isinstance(unit, (ast.Import, ast.ImportFrom)) and demanded != "*":
            if first or i in m.import_names:
                m.import_names.setdefault(i, set()).add(demanded)
            # One line can import several names; follow only the one asked
            # for. `import X` itself demands nothing - what of X is used is
            # decided by the `X.attr` sites that referred to it.
            for b, mod, what in _import_bindings(unit):
                if b == demanded and what is not None:
                    demand(mod, what)
            return
        m.import_names.pop(i, None)
        if not first:
            return
        local_aliases = dict(m.module_aliases)
        for node in ast.walk(unit):
            for b, mod, what in _import_bindings(node):
                if what is None:
                    local_aliases[b] = mod
                else:
                    demand(mod, what)
        attr_bases = set()
        for node in ast.walk(unit):
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and node.value.id in local_aliases):
                attr_bases.add(id(node.value))
                if node.attr not in _DUNDER_OK:
                    demand(local_aliases[node.value.id], node.attr)
        for node in ast.walk(unit):
            if isinstance(node, ast.Name):
                if node.id in local_aliases and id(node) not in attr_bases:
                    demand(local_aliases[node.id], "*")
                if node.id in m.binders:
                    queue.append((m.name, node.id))

    while queue:
        module, name = queue.pop()
        if (module, name) in seen:
            continue
        seen.add((module, name))
        m = mods[module]
        if name == "*":
            for i, unit in enumerate(m.units):
                if module in whole or not _is_main_guard(unit):
                    take(m, i, "*")
            continue
        idx = m.binders.get(name)
        if not idx:
            raise Unresolved(f"{module}.{name}")
        for i in idx:
            take(m, i, name)
    return mods, {name: sorted(ix) for name, ix in taken.items()}


def _only_taken_names(unit, names):
    """An import line reduced to the names the reach took from it, so that
    `from _runlog import runlog, video_attempt` -> `from _runlog import runlog`
    (CF-0159 moving a CLI-only import into `main()`) is not a change."""
    if names is None:
        return unit
    kept = [a for a in unit.names
            if (a.asname or (a.name.split(".")[0] if isinstance(unit, ast.Import)
                             else a.name)) in names]
    if isinstance(unit, ast.Import):
        return ast.Import(names=kept)
    return ast.ImportFrom(module=unit.module, names=kept, level=unit.level)


def reach_digest(paths, roots, whole=(), opaque=()):
    """Digest of what `roots` reach in `paths` (module name = file stem), or
    None when it cannot be computed honestly - see "Failing closed"."""
    sources = {}
    for p in paths:
        try:
            sources[Path(p).stem] = Path(p).read_text()
        except OSError:
            return None
    return digest_sources(sources, [Path(p).stem for p in paths], roots, whole, opaque)


def digest_sources(sources, order, roots, whole=(), opaque=()):
    try:
        mods, taken = reach(sources, roots, whole, opaque)
    except (SyntaxError, Unresolved):
        return None
    h = hashlib.sha256()
    for name in order:
        h.update(name.encode())
        h.update(b"\0")
        m = mods[name]
        for i in taken.get(name, ()):
            _serialise(_only_taken_names(m.units[i], m.import_names.get(i)), h)
            h.update(b"\n")
        h.update(b"\0")
    return h.hexdigest()[:DIGEST_CHARS]
