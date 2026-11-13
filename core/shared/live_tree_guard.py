#!/usr/bin/env python3
"""CF-0505: the shared half of the "a test does not reach the live tree" guards.

Two root guards judge the same `/` chains: CF-0250
(tests/test_channel_dirs_not_spelled.py - a test never spells
`pipeline/<channel>` as a string; the corpus stops at that one name the day
the channel is renamed) and CF-0503 (tests/test_no_live_tree_reads.py - a test
never reads the live `pipeline/` or `shared/footage/`, DoD 1.6.1 #2). The
agents' tests do both too (CF-0505), and a copy of these rules in every agent
repository would be the CF-0159 drift. So, as with shared/timeout_guard.py
(CF-0229) and shared/summary_line_guard.py (CF-0234), the rule is split:

  * here, what is the same everywhere: which `/` chain starts at the real
    factory checkout, which of them name a channel directory, which of them
    reach the live tree, who owns each one, and which file::test entries of a
    live-monitor registry are allowed to;
  * in each repository's own test: the files it scans, its registry of live
    monitors (`{"test_x.py::test_y": "why"}`), the files exempt on purpose.

A chain starts at the real checkout when its head is

  * a name in CHECKOUT_NAMES (`ROOT`, `REPO`, `REAL_ROOT`, `LIVE_ROOT`, `FACTORY`,
    `REPO_ROOT`, `FACTORY_ROOT`);
  * an attribute in CHECKOUT_ATTRS (`repo_paths.FACTORY_ROOT`,
    `ib.FACTORY_ROOT` - CF-0523: the module constant of production code is
    the real checkout; a bare `ROOT` attribute is not judged, `cls.ROOT` is as
    often a temp tree);
  * a call of anything named `factory_root` (`factory_root()`,
    `_runlog.factory_root()`, `fp.factory_root()`);
  * `Path.home() / "shorts-content-factory"`;
  * `Path("<anything>/shorts-content-factory[/more]")` - the segments after
    the checkout in the literal count as the chain's first ones.

A chain starts at the live pipeline/ itself when its head is a name or an
attribute in LIVE_PIPELINE_NAMES (`PIPELINE_DIR`, `repo_paths.PIPELINE_DIR`,
`text_gates.repo_paths.PIPELINE_DIR` - CF-0523: production code's own default,
always the live tree), including `PIPELINE_DIR.glob(...)`; used bare
(`PIPELINE_DIR.exists()`, `.iterdir()`, as an argument) it is a live read
by itself (CF-0523 step 4). A chain or a glob is judged when it reaches
pipeline/, publish/ or shared/footage/ (LIVE_CHAIN_DIRS). `PIPELINE` and
`PIPELINE_ROOT` (PIPELINE_NAMES) also stand for pipeline/, but only for the
channel-spelling check: in the root `PIPELINE` is the frozen-or-live switch
(`_real_batches.PIPELINE`, CF-0505 step 0), so it is never a live read.

And a string literal that is an absolute path into the live tree
(`"/home/x/shorts-content-factory/pipeline"`, `".../publish/..."`,
`".../shared/footage"`; `os.environ.get("PIPELINE_DIR") or "<that>"`) is a
live read wherever it stands - a docstring is not judged, and a checkout with
nothing before it (`"/shorts-content-factory/shared/footage/"`, a suffix a
test strips off) is a name, not an address.

A synthetic tree (`root`, `tmp`, `Path(tmp)`, `FAKE_ROOT`, `FIX_ROOT`) spells
whatever it likes: that is the fixture, not a read of the real tree. In an
agent repository `ROOT` may be the agent's own checkout - a `ROOT / "pipeline"`
there is refused all the same: the agent has no pipeline/, so the chain is a
live read in waiting or a dead path. Read by AST, so comments and docstrings
quoting a path are free; a name held in a variable is not judged (only a
literal is a spelling); `"pipeline/x"` written as one string is the same path.

Everything here returns findings as data. Nothing is imported from beside this
file, so a neighbouring repository loads it by path (`spec_from_file_location`
on `_runlog.factory_root() / "shared" / "live_tree_guard.py"`).
"""
import ast
from pathlib import Path

CHECKOUT_NAMES = frozenset({"ROOT", "REPO", "REAL_ROOT", "LIVE_ROOT", "REPO_ROOT", "FACTORY_ROOT", "FACTORY"})
# `<module>.ATTR` heads that are the real checkout (CF-0523).
CHECKOUT_ATTRS = frozenset({"FACTORY_ROOT"})
# Names that already stand for <checkout>/pipeline - for the channel spelling
# only: `PIPELINE` is the root's frozen-or-live switch, not a live read.
PIPELINE_NAMES = frozenset({"PIPELINE", "PIPELINE_ROOT"})
# Names (bare or as an attribute) that are the live <checkout>/pipeline
# itself - production code's default (`repo_paths.PIPELINE_DIR`, CF-0523).
LIVE_PIPELINE_NAMES = frozenset({"PIPELINE_DIR"})
CHECKOUT_DIRNAME = "shorts-content-factory"
# Files directly under pipeline/ that are records in git, not batches (CF-0111).
TRACKED_TABLES = frozenset({"runs.jsonl", "RUNS.md"})
# Attributes that are the live tree by name: (module alias, attribute).
LIVE_ATTRS = frozenset({("_real_batches", "LIVE_PIPELINE")})
# Top directories of the checkout a literal absolute path may not reach.
LIVE_LITERAL_DIRS = ("pipeline", "publish", "shared/footage")
# Top directories of the checkout a `/` chain or a glob may not reach (CF-0523
# step 4: publish/ joined - `ROOT / "publish" / "acceptance-log.json"` is the
# live acceptance log as much as the literal is).
LIVE_CHAIN_DIRS = ("pipeline", "publish", "shared/footage")


def parse(path):
    return ast.parse(Path(path).read_text(encoding="utf-8"), str(path))


def not_channels(factory_root):
    """`gate_price.NOT_CHANNELS` (pipeline/ directories that are not channels:
    rebuilds, backfill), read off gate_price.py's AST - so the guard does not
    import the runlog package and the list stays in one place."""
    tree = parse(Path(factory_root) / "shared" / "runlog" / "gate_price.py")
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "NOT_CHANNELS"):
            return tuple(ast.literal_eval(node.value))
    raise LookupError("gate_price.py has no NOT_CHANNELS literal - the guard reads it by AST")


def _chain(node):
    """`a / b / c` as [a, b, c]; anything else as [node]."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _chain(node.left) + [node.right]
    return [node]


def _str(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _is_call_named(node, name):
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    return (isinstance(f, ast.Name) and f.id == name) or (isinstance(f, ast.Attribute) and f.attr == name)


def _checkout_rest(text):
    """The segments after `<parent>/shorts-content-factory` in a literal path,
    or None when the literal does not name the checkout with a parent before
    it (a bare `/shorts-content-factory/...` is a suffix, not an address)."""
    segs = [s for s in text.split("/") if s]
    if CHECKOUT_DIRNAME not in segs:
        return None
    i = segs.index(CHECKOUT_DIRNAME)
    if i == 0 and not text.startswith("~"):
        return None
    return segs[i + 1:]


def head_segments(parts, checkout_names=CHECKOUT_NAMES, pipeline_names=PIPELINE_NAMES,
                  checkout_attrs=CHECKOUT_ATTRS, live_pipeline_names=LIVE_PIPELINE_NAMES):
    """(segments the head already stands for, parts consumed) when the chain
    starts at the real checkout, else None. `[]` is the checkout itself,
    `["pipeline"]` its pipeline/ (`PIPELINE_DIR`, or a name in
    `pipeline_names`), `["pipeline", "x"]` a `Path("<..>/shorts-content-factory/pipeline/x")`."""
    head = parts[0]
    if isinstance(head, ast.Name):
        if head.id in checkout_names:
            return [], 1
        if head.id in pipeline_names or head.id in live_pipeline_names:
            return ["pipeline"], 1
        return None
    if isinstance(head, ast.Attribute):
        if head.attr in checkout_attrs:
            return [], 1
        if head.attr in live_pipeline_names:
            return ["pipeline"], 1
        return None
    if _is_call_named(head, "factory_root"):
        return [], 1
    if _is_call_named(head, "Path"):
        arg = _str(head.args[0]) if head.args else None
        rest = _checkout_rest(arg) if arg else None
        if rest is None and arg and arg.rstrip("/") == "/" + CHECKOUT_DIRNAME:
            rest = []
        return (rest, 1) if rest is not None else None
    if (isinstance(head, ast.Call) and isinstance(head.func, ast.Attribute)
            and head.func.attr == "home" and len(parts) > 1
            and (_str(parts[1]) or "").strip("/") == CHECKOUT_DIRNAME):
        return [], 2
    return None


def checkout_head(parts, checkout_names=CHECKOUT_NAMES, pipeline_names=PIPELINE_NAMES, **kw):
    """('checkout' | 'pipeline', parts consumed) when the chain starts at the
    real checkout (or at its pipeline/ by name), else None. Kept for callers
    of the CF-0505 shape; `head_segments` says which segments the head holds."""
    got = head_segments(parts, checkout_names, pipeline_names, **kw)
    if got is None:
        return None
    segs, used = got
    return ("pipeline" if segs[:1] == ["pipeline"] else "checkout"), used


def _owners(tree):
    """{id(node): owner} - the top-level function, or `Class.method` for a
    method of a top-level class (a unittest case), or the class name for its
    body outside methods."""
    out = {}
    for top in tree.body:
        if isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for n in ast.walk(top):
                out[id(n)] = top.name
        elif isinstance(top, ast.ClassDef):
            for n in ast.walk(top):
                out.setdefault(id(n), top.name)
            for m in top.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for n in ast.walk(m):
                        out[id(n)] = f"{top.name}.{m.name}"
    return out


def _segs(parts):
    return [seg for p in parts for seg in (_str(p).strip("/").split("/") if _str(p) else [None])]


def _chains(tree, checkout_names, pipeline_names, checkout_attrs=CHECKOUT_ATTRS,
            live_pipeline_names=LIVE_PIPELINE_NAMES):
    """(outermost `/` node, path segments from the checkout) for every chain
    that starts at the real checkout. A segment that is not a literal is None."""
    divs = [n for n in ast.walk(tree) if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div)]
    inner = {id(n.left) for n in divs}      # one report per chain, at its outermost `/`
    for node in divs:
        if id(node) in inner:
            continue
        parts = _chain(node)
        got = head_segments(parts, checkout_names, pipeline_names, checkout_attrs, live_pipeline_names)
        if not got:
            continue
        head, used = got
        yield node, list(head) + _segs(parts[used:])


def _docstrings(tree):
    """ids of the string constants that are docstrings / bare expression
    statements - prose quoting a path, not a path in use."""
    return {id(n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
            and isinstance(n.value.value, str)}


def live_literal(text, live_dirs=LIVE_LITERAL_DIRS):
    """True when `text` is an absolute path into the live tree:
    `<parent>/shorts-content-factory/<pipeline|publish|shared/footage>[/...]`."""
    rest = _checkout_rest(text) if CHECKOUT_DIRNAME in text else None
    if not rest:
        return False
    return any(rest[:len(d.split("/"))] == d.split("/") for d in live_dirs)


def spelled_channel_dirs(source, filename="<src>", allowed=(), *,
                         checkout_names=CHECKOUT_NAMES, pipeline_names=PIPELINE_NAMES,
                         checkout_attrs=CHECKOUT_ATTRS, live_pipeline_names=LIVE_PIPELINE_NAMES):
    """[(line, text)] for every real-checkout path that names a channel
    directory as a literal. `allowed`: pipeline/ directories that are not
    channels (`not_channels(root)`). A name with a suffix is a file directly
    under pipeline/ (runs.jsonl, RUNS.md), not a channel - channel ids carry none."""
    tree = ast.parse(source, filename)
    out = []
    for node, segs in _chains(tree, checkout_names, pipeline_names, checkout_attrs,
                              live_pipeline_names):
        if len(segs) < 2 or segs[0] != "pipeline":
            continue
        name = segs[1]
        if name is not None and name not in allowed and "." not in name:
            out.append((node.lineno, ast.get_source_segment(source, node) or name))
    return out


def _live_dir(segs, live_dirs):
    """The live directory (`"shared/footage"`) the segments start with, or None."""
    for d in live_dirs:
        ds = d.split("/")
        if list(segs[:len(ds)]) == ds:
            return d
    return None


def live_reads(source, filename="<src>", *, checkout_names=CHECKOUT_NAMES,
               tracked_tables=TRACKED_TABLES, live_attrs=LIVE_ATTRS,
               checkout_attrs=CHECKOUT_ATTRS, live_pipeline_names=LIVE_PIPELINE_NAMES,
               live_literal_dirs=LIVE_LITERAL_DIRS, live_chain_dirs=LIVE_CHAIN_DIRS):
    """[(line, owner or None, what)] for every reference to the live tree: a
    real-checkout chain into `pipeline` (bar a tracked table directly under
    it), `publish` or `shared/footage` (`live_chain_dirs`), a
    `<checkout>.glob("pipeline/...")` (or `rglob`, or into publish/ or
    shared/footage), and every `module.ATTR` in `live_attrs`.
    A bare string "shared/footage/" is not judged - a name, not an open. A
    `PIPELINE / x` is not judged here either: in the root `PIPELINE` is the
    frozen-or-live switch (`_real_batches.PIPELINE`), and where it is the live
    tree the chain that built it is the read. `PIPELINE_DIR` (bare or as an
    attribute) is production code's live pipeline/ and is judged, in a chain
    and in a glob; so is `<module>.FACTORY_ROOT`, and an absolute literal path
    into pipeline/, publish/ or shared/footage/ (CF-0523). A `PIPELINE_DIR`
    used bare - `PIPELINE_DIR.exists()`, `.iterdir()`, passed as an argument -
    is a read too, unless it is part of a chain or glob already counted (one
    finding per line); an import, an assignment to it (the definition, a
    monkeypatch) and a keyword named so are not (CF-0523 step 4)."""
    tree = ast.parse(source, filename)
    owners = _owners(tree)
    found = []
    covered = set()     # a literal head of a judged chain is that one read, not two
    for node, segs in _chains(tree, checkout_names, frozenset(), checkout_attrs,
                              live_pipeline_names):
        d = _live_dir(segs, live_chain_dirs)
        if d is None:
            continue
        # a tracked table is in git, not a read - and its PIPELINE_DIR head is
        # not a bare read either
        covered |= {id(n) for n in ast.walk(node)}
        if d == "pipeline" and len(segs) == 2 and segs[1] in tracked_tables:
            continue
        what = "<checkout> / " + " / ".join(repr(x) for x in d.split("/"))
        found.append((node.lineno, owners.get(id(node)), what))
    prose = _docstrings(tree)
    for node in ast.walk(tree):
        # ROOT.glob("pipeline/*/*/...") - the same read as a chain (CF-0505:
        # footage-indexer test_card_phrase_vocabulary walks every batch so);
        # PIPELINE_DIR.glob("*/*/work/*/plan.json") is one too (CF-0523)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("glob", "rglob") and node.args):
            receiver = _chain(node.func.value)
            got = head_segments(receiver, checkout_names, frozenset(),
                                checkout_attrs, live_pipeline_names)
            if got and got[1] == len(receiver):   # `(ROOT / "pipeline").glob` is the chain's read
                pat = "/".join(list(got[0]) + [(_str(node.args[0]) or "").strip("/")]).strip("/")
                d = _live_dir(pat.split("/"), live_chain_dirs)
                if d is not None:
                    covered |= {id(n) for n in ast.walk(node)}
                    if not (d == "pipeline" and pat.split("/")[-1] in tracked_tables):
                        found.append((node.lineno, owners.get(id(node)), f"<checkout>.glob('{d}/...')"))
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in prose and id(node) not in covered
                and live_literal(node.value, live_literal_dirs)):
            found.append((node.lineno, owners.get(id(node)), "a literal path into the live tree"))
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and (node.value.id, node.attr) in live_attrs):
            found.append((node.lineno, owners.get(id(node)), f"{node.value.id}.{node.attr}"))
    # a bare PIPELINE_DIR: `.exists()`, `.iterdir()`, an argument (CF-0523
    # step 4) - after the walk above, so a chain or glob that holds it is
    # already covered; one finding per line
    seen = {(line, owner) for line, owner, _ in found}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            name = node.id
        elif isinstance(node, ast.Attribute):
            name = node.attr
        else:
            continue
        if (name not in live_pipeline_names or not isinstance(node.ctx, ast.Load)
                or id(node) in covered):
            continue
        key = (node.lineno, owners.get(id(node)))
        if key in seen:
            continue
        seen.add(key)
        found.append((node.lineno, owners.get(id(node)), f"{name} (bare)"))
    found.sort(key=lambda f: f[0])
    return found


def offenders(files, monitors=(), exempt_files=(), **kw):
    """`file:line (owner): what` for every live read outside the registry.
    `monitors`: the repository's live-monitor registry, keys `file.py::owner`
    (owner as `_owners` names it: `test_x` or `Case.test_x`). Any keyword is
    passed on to `live_reads`."""
    out = []
    for f in files:
        f = Path(f)
        if f.name in exempt_files:
            continue
        for line, owner, what in live_reads(f.read_text(encoding="utf-8"), str(f), **kw):
            if owner and f"{f.name}::{owner}" in monitors:
                continue
            out.append(f"{f.name}:{line} ({owner or 'module level'}): {what}")
    return out


def spelled_offenders(files, allowed=(), exempt_files=(), **kw):
    """`file:line: text` for every spelled channel directory in `files`."""
    out = []
    for f in files:
        f = Path(f)
        if f.name in exempt_files:
            continue
        for line, text in spelled_channel_dirs(f.read_text(encoding="utf-8"), str(f), allowed, **kw):
            out.append(f"{f.name}:{line}: {text}")
    return out


def stale_monitors(tests_dir, monitors):
    """Problems with a live-monitor registry: an entry whose file or test is
    gone (a registry entry outlived its test), or one without its reason."""
    out = []
    for key, why in dict(monitors).items():
        fname, _, owner = key.partition("::")
        f = Path(tests_dir) / fname
        if not f.is_file():
            out.append(f"{key}: no such file")
            continue
        names = set(_owners(parse(f)).values())
        if owner not in names:
            out.append(f"{key}: no such test - a registry entry outlived its test")
        if not str(why).strip():
            out.append(f"{key}: a live monitor without its reason")
    return out
