#!/usr/bin/env python3
"""CF-0499: the shared half of the "no mirror into the Notebook vault" guard.

The vault is the operator's workspace - design logs, handoff notes - not a place
for copies of repo files the user would read. Until 1.6 two such
copies existed: `pipeline/RUNS.notebook.md` (written by `runlog runs`, copied
by the driver into a vault note) and a symlink of `tasks/` inside the vault.
Both went to the archive; this module is what keeps them from growing back
the same way.

Refused in a production script (read by AST, so comments and docstrings are
free; a shell script line by line, `#` comments skipped):

  * any string naming a `*.notebook.md` file - the shape of the old mirror;
  * any string reaching into the vault (`Notebook` as a path segment,
    `Operator's vault`, `Operator-Notes`).

CF-0652: until 2.3 one vault file was allowed - `NEEDS-YOU.md`, the note the
question writers appended to. The questions are now the journal of questions
in the root (shared/needs_you.py) - the root's writers and the indexer's sieve
fallback (footage-indexer c13ce6f) alike - so no script may name it any more,
with no exception. `LEGACY_NEEDS_YOU_NOTE` is where the note lived - read
once, by scripts/needs_you_migrate.py, to carry its open lines into the
journal (the guard's module is the one place allowed to name it).

Everything returns findings as data, nothing is imported from beside this
file: a neighbouring repository loads it by path (`spec_from_file_location`),
like shared/live_tree_guard.py.
"""
import ast
import os
from pathlib import Path

MIRROR_SUFFIX = ".notebook.md"
VAULT_MARKERS = ("Operator's vault", "Operator-Notes", "/Notebook/", "Notebook/")
VAULT_SEGMENT = "Notebook"
ALLOWED_VAULT_FILES = ()
LEGACY_NEEDS_YOU = "NEEDS-YOU.md"
LEGACY_NEEDS_YOU_NOTE = "~/Notebook/Operator's vault/Operator-Notes/" + LEGACY_NEEDS_YOU
# Directories never scanned: tests (they name the forbidden shapes on purpose),
# virtualenvs, caches, run scratch, other checkouts and archives.
SKIP_DIRS = frozenset({"tests", ".venv", "venv", "__pycache__", "node_modules", ".git",
                       ".worktrees", "work", "archive", "pipeline", "publish", "footage"})


def scripts(roots):
    """Every .py / .sh file under the given roots, skipping SKIP_DIRS."""
    out = []
    for root in roots:
        root = Path(root)
        if root.is_file():
            out.append(root)
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
            out += [Path(dirpath) / f for f in sorted(filenames) if f.endswith((".py", ".sh"))]
    return out


def _docstring_ids(tree):
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
                    and isinstance(body[0].value.value, str):
                ids.add(id(body[0].value))
    return ids


def _vaultish(text):
    return text == VAULT_SEGMENT or any(m in text for m in VAULT_MARKERS)


def _allowed(texts, allowed=ALLOWED_VAULT_FILES):
    return any(f in t for t in texts for f in allowed)


def python_findings(source, filename="<src>", allowed=ALLOWED_VAULT_FILES):
    """[(line, what)] for one Python source."""
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as e:
        return [(e.lineno or 0, f"unparseable: {e.msg}")]
    docs = _docstring_ids(tree)
    found = []
    for stmt in ast.walk(tree):
        if not isinstance(stmt, ast.stmt):
            continue
        # constants of this statement itself, not of the statements nested in it
        consts, stack = [], [c for c in ast.iter_child_nodes(stmt) if not isinstance(c, ast.stmt)]
        while stack:
            n = stack.pop()
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs:
                consts.append(n)
            stack += [c for c in ast.iter_child_nodes(n) if not isinstance(c, ast.stmt)]
        texts = [c.value for c in consts]
        for c in consts:
            if MIRROR_SUFFIX in c.value:
                found.append((c.lineno, f"names a *{MIRROR_SUFFIX} file: {c.value!r}"))
            elif _vaultish(c.value) and not _allowed(texts, allowed):
                found.append((c.lineno, f"reaches into the vault: {c.value!r}"))
    return sorted(set(found))


def shell_findings(source, allowed=ALLOWED_VAULT_FILES):
    found = []
    for n, line in enumerate(source.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if MIRROR_SUFFIX in s:
            found.append((n, f"names a *{MIRROR_SUFFIX} file"))
        elif _vaultish(s) and not _allowed([s], allowed):
            found.append((n, "reaches into the vault"))
    return found


def offenders(files, base=None):
    """['<file>:<line>: <what>'] over the given files."""
    out = []
    for f in files:
        f = Path(f)
        text = f.read_text(encoding="utf-8", errors="replace")
        hits = shell_findings(text) if f.suffix == ".sh" else python_findings(text, str(f))
        name = f.relative_to(base) if base else f
        out += [f"{name}:{line}: {what}" for line, what in hits]
    return out
