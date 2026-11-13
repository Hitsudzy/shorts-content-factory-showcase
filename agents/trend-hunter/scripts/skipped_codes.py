#!/usr/bin/env python3
"""CF-0708: every `reason_code` in `01-trend-hunter.json` -> `skipped_topics[]`
is a word of the topic funnel's vocabulary - checked, never trusted.

    scripts/skipped_codes.py <batch-dir|01-trend-hunter.json>   # exit 1 on a code outside it

`example-science/2026-10-12T2001Z`: the stage's model dropped a topic whose only
news source had no publication date and wrote `reason_code: "no_dated_source"`
by hand - a word no code of the factory writes. The funnel counted it as an
unknown code, the run's triage filed a contract defect (CF-0708) and the live
monitor `test_every_real_batch_on_disk_draws_a_funnel_with_no_code_outside_the_vocabulary`
went red (CF-0710). The vocabulary is the root's `shared/runlog/funnel.py`
`FUNNEL_CODES`, loaded by path - no copy here, so the two can never disagree
about a word. A pre-rename word (`funnel.LEGACY_CODES`: `no_production_fact`,
and since CF-0708 `no_dated_source`) is still read in the old batches that
carry it and is never written again: here it is a problem naming the word to
write instead.

`check_scenes.py --check` (the finished-batch check the stage runs before it
closes) runs this too, so a coined code stops the stage while its model can
still fix it.

A code this stage's own scripts write is never refused here, whether or not
the funnel knows it yet: `stage_codes()` reads them out of `scripts/*.py`
itself (no list kept by hand) - the `reason_code` of every topic-refusal row
literal (`topic_id` + `reason_code`), and, where that value is a parameter of
the function building the row (`footage_candidates.refuse(code=...)`,
`fact_probe_topics.refusal_record(topic, code, ...)`), the argument of every
call to it, defaults included. A stage code the funnel does not know yet still
passes here, and the CLI names it as a note: how the funnel classifies a word
is the root's question, not this check's. The one such code there was,
`footage_evidence_quota` (CF-0317, `footage_candidates.EVIDENCE_QUOTA_CODE`),
is in FUNNEL_CODES since CF-0714 - a loss of the topic, like `no_source`.
"""
import argparse
import ast
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from _runlog import factory_root  # noqa: E402

TASK = "CF-0708"
FUNNEL_REL = Path("shared") / "runlog" / "funnel.py"
ROWS_KEY = "skipped_topics"

_FUNNEL = None


def _funnel():
    """The root's funnel module, loaded once by path."""
    global _FUNNEL
    if _FUNNEL is None:
        path = factory_root() / FUNNEL_REL
        if not path.is_file():
            raise RuntimeError(f"{path} not found - the funnel's vocabulary lives in the "
                               f"factory root ({TASK})")
        spec = importlib.util.spec_from_file_location("funnel_th", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _FUNNEL = module
    return _FUNNEL


def vocabulary():
    """-> (FUNNEL_CODES as a frozenset, LEGACY_CODES as a dict)."""
    f = _funnel()
    return frozenset(f.FUNNEL_CODES), dict(getattr(f, "LEGACY_CODES", {}) or {})


# --------------------------------------------------------------------------
# the codes this stage's own scripts write (read from the code, CF-0708)
# --------------------------------------------------------------------------

_STAGE_CODES = None


def _module_constants(tree):
    """{NAME: value node} of the module's top-level `NAME = <expr>`."""
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = node.value
    return out


class _Scripts:
    def __init__(self, scripts_dir):
        self.dir = Path(scripts_dir)
        self.trees, self.srcs, self.consts = {}, {}, {}
        for path in sorted(self.dir.glob("*.py")):
            try:
                src = path.read_text(encoding="utf-8")
                tree = ast.parse(src)
            except (OSError, SyntaxError, ValueError):
                continue
            self.trees[path.stem], self.srcs[path.stem] = tree, src
            self.consts[path.stem] = _module_constants(tree)

    def resolve(self, node, module, depth=0):
        """A string constant behind `node` in `module`, or None."""
        if depth > 8 or node is None:
            return None
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            value = self.consts.get(module, {}).get(node.id)
            return self.resolve(value, module, depth + 1) if value is not None else None
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            other = node.value.id
            value = self.consts.get(other, {}).get(node.attr)
            return self.resolve(value, other, depth + 1) if value is not None else None
        return None


def _parents(tree):
    out = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            out[child] = node
    return out


def _enclosing_function(node, parents):
    while node in parents:
        node = parents[node]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node
    return None


def _row_code(d):
    """The `reason_code` value node of a topic-refusal row literal, or None
    when `d` is not one (`topic_id` and `reason_code` both keyed, `topic_id`
    not the constant None - the substitution block's slot rows)."""
    pairs = {k.value: v for k, v in zip(d.keys, d.values)
             if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    if "reason_code" not in pairs or "topic_id" not in pairs:
        return None
    tid = pairs["topic_id"]
    if isinstance(tid, ast.Constant) and tid.value is None:
        return None
    return pairs["reason_code"]


def stage_codes(scripts_dir=None):
    """-> (codes, unresolved). `codes` = {code: ["file:line", ...]} for every
    `reason_code` this repo's scripts put on a topic-refusal row; `unresolved`
    = ["file:line what", ...] for a row or a call whose code is not a string
    constant this reading can follow (a new writer has to name its code as a
    constant, or this check could not know it)."""
    s = _Scripts(scripts_dir or HERE)
    codes, unresolved = {}, []
    writers = {}   # function name -> (module, parameter index, parameter name, default node)

    def add(code, where):
        codes.setdefault(code, []).append(where)

    for module, tree in s.trees.items():
        parents = _parents(tree)
        for d in ast.walk(tree):
            if not isinstance(d, ast.Dict):
                continue
            value = _row_code(d)
            if value is None:
                continue
            where = f"{module}.py:{d.lineno}"
            code = s.resolve(value, module)
            if code is not None:
                add(code, where)
                continue
            fn = _enclosing_function(d, parents)
            names = [a.arg for a in fn.args.args] if fn is not None else []
            if isinstance(value, ast.Name) and value.id in names:
                i = names.index(value.id)
                defaults = fn.args.defaults
                first_default = len(names) - len(defaults)
                default = defaults[i - first_default] if i >= first_default else None
                writers[fn.name] = (module, i, value.id, default)
                if default is not None:
                    code = s.resolve(default, module)
                    if code is not None:
                        add(code, f"{where} (default of {fn.name})")
                    else:
                        unresolved.append(f"{where} default of {fn.name}")
            else:
                unresolved.append(f"{where} {ast.unparse(value)}")
    for module, tree in s.trees.items():
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call):
                continue
            f = call.func
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
            if name not in writers:
                continue
            _, i, pname, _default = writers[name]
            arg = next((k.value for k in call.keywords if k.arg == pname), None)
            if arg is None and len(call.args) > i:
                arg = call.args[i]
            if arg is None:
                continue                      # the default, already counted
            where = f"{module}.py:{call.lineno} ({name})"
            code = s.resolve(arg, module)
            if code is not None:
                add(code, where)
            else:
                unresolved.append(f"{where} {ast.unparse(arg)}")
    return codes, unresolved


def own_codes():
    """The set of codes `stage_codes()` finds in this repo, read once."""
    global _STAGE_CODES
    if _STAGE_CODES is None:
        _STAGE_CODES = frozenset(stage_codes()[0])
    return _STAGE_CODES


def check_batch(batch, codes=None, legacy=None, own=None):
    """-> [problem, ...] for every `skipped_topics[]` row whose `reason_code`
    is missing, or is neither a code this stage's own scripts write nor a word
    of the funnel's vocabulary, or is an old word the funnel only reads."""
    if codes is None or legacy is None:
        got_codes, got_legacy = vocabulary()
        codes = got_codes if codes is None else codes
        legacy = got_legacy if legacy is None else legacy
    own = own_codes() if own is None else own
    problems = []
    rows = batch.get(ROWS_KEY) if isinstance(batch, dict) else None
    if not isinstance(rows, list):
        return problems
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            problems.append(f"{ROWS_KEY}[{i}]: not an object")
            continue
        tid = row.get("topic_id") or f"#{i}"
        code = row.get("reason_code")
        if not code:
            problems.append(f"{ROWS_KEY} {tid}: no reason_code - a refusal names its code ({TASK})")
        elif code in own:
            continue                          # this stage's scripts write it
        elif code in legacy:
            problems.append(f"{ROWS_KEY} {tid}: reason_code {code!r} is an old word the funnel "
                            f"reads as {legacy[code]!r} in old batches; write {legacy[code]!r} "
                            f"({TASK})")
        elif code not in codes:
            problems.append(
                f"{ROWS_KEY} {tid}: reason_code {code!r} is outside the funnel's vocabulary "
                f"(shared/runlog/funnel.py FUNNEL_CODES) - never coin a code: use the one the "
                f"rule gives (SKILL.md, the codes of skipped_topics[]); a topic whose every "
                f"news link was dropped as uncitable is `no_source` ({TASK})")
    return problems


def _batch_path(arg):
    path = Path(arg).expanduser()
    return path / "01-trend-hunter.json" if path.is_dir() else path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("batch", help="batch directory or its 01-trend-hunter.json")
    args = ap.parse_args(argv)
    path = _batch_path(args.batch)
    if not path.exists():
        print(f"no {path}", file=sys.stderr)
        return 2
    batch = json.load(open(path))
    problems = check_batch(batch)
    rows = batch.get(ROWS_KEY) if isinstance(batch.get(ROWS_KEY), list) else []
    print(f"{path.name}: {len(rows)} skipped topic(s), {len(problems)} code problem(s)",
          file=sys.stderr)
    for p in problems:
        print(f"  {p}", file=sys.stderr)
    codes, _legacy = vocabulary()
    for code in sorted({r.get("reason_code") for r in rows if isinstance(r, dict)}
                       & (own_codes() - codes)):
        print(f"  note: {code!r} is written by this stage's own scripts and is not in the "
              f"funnel's FUNNEL_CODES yet - passed here ({TASK})", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
