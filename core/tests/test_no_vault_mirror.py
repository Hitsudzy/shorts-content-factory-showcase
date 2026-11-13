#!/usr/bin/env python3
"""CF-0499: no script of the root or of an agent writes a mirror into the
Notebook vault - neither a `*.notebook.md` text for the driver to copy (the
old `pipeline/RUNS.notebook.md`) nor any path into the vault. CF-0652: not
NEEDS-YOU.md either - the questions are the journal of questions now, the
indexer's sieve fallback included. The rule lives in shared/vault_write_guard.py."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("vault_write_guard", ROOT / "shared" / "vault_write_guard.py")
vwg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vwg)

SCAN = [ROOT / "scripts", ROOT / "shared", ROOT / ".claude"] + (sorted(
    p for p in (ROOT / "agents").iterdir() if p.is_dir()) if (ROOT / "agents").is_dir() else [])
# The guard names the forbidden shapes on purpose.
EXEMPT = {ROOT / "shared" / "vault_write_guard.py"}


def test_no_script_writes_a_vault_mirror():
    files = [f for f in vwg.scripts(p for p in SCAN if p.exists()) if f not in EXEMPT]
    assert len(files) > 100, f"the scan found only {len(files)} scripts - wrong roots?"
    bad = vwg.offenders(files, ROOT)
    assert not bad, "\n  ".join(
        ["scripts write into the Notebook vault (CF-0499: the vault is Claude's "
         "workspace, not a copy of repo files; CF-0652: questions go to shared/needs_you.py):"] + bad)


def test_runs_table_has_no_mirror_writer():
    sys.path.insert(0, str(ROOT / "shared" / "runlog"))
    import runs_table
    assert not hasattr(runs_table, "notebook_note") and not hasattr(runs_table, "RUNS_NOTEBOOK")
    assert ".notebook" not in (ROOT / ".gitignore").read_text(encoding="utf-8")


def test_guard_catches_the_old_shapes():
    old = 'RUNS_NOTEBOOK = "pipeline/RUNS.notebook.md"\n'
    assert vwg.python_findings(old), "the old mirror path went unseen"
    copy = 'dst = Path.home() / "Notebook" / "v" / "Operator-Notes" / "Shorts — Прогоны.md"\n'
    assert vwg.python_findings(copy), "a copy into the vault went unseen"
    link = 'os.symlink(REPO / "tasks", VAULT / "Operator-Notes" / "x" / "tasks")\n'
    assert vwg.python_findings(link), "a tasks symlink into the vault went unseen"
    assert vwg.shell_findings('cp pipeline/RUNS.md "$HOME/Notebook/v/Operator-Notes/r.md"\n')
    assert vwg.shell_findings("cp a b.notebook.md\n")


def test_guard_leaves_comments_and_docstrings_alone():
    ok = ('"""Log: Notebook `Operator-Notes/grill-me-logs/x.md`."""\n'
          '# copied to Operator-Notes/x.notebook.md once\n'
          'def f():\n    """Writes nothing into Operator-Notes."""\n    return 1\n')
    assert vwg.python_findings(ok) == [], vwg.python_findings(ok)
    assert vwg.shell_findings('# Operator-Notes/x.notebook.md\necho ok\n') == []


NOTE = ('NY = (Path.home() / "Notebook" / "example-user\'s vault" / "Operator-Notes"\n'
        '      / "NEEDS-YOU.md")\n')


def test_needs_you_md_is_no_longer_an_exception():
    """CF-0652: a script naming the old note is refused like any vault path."""
    assert vwg.ALLOWED_VAULT_FILES == ()
    assert vwg.python_findings(NOTE), "a NEEDS-YOU.md writer went unseen"
    assert vwg.shell_findings('echo x >> "$HOME/Notebook/v/Operator-Notes/NEEDS-YOU.md"\n')


def test_no_file_is_exempt_any_more_the_indexer_fallback_included():
    """CF-0652: the transition is over (footage-indexer c13ce6f) - the sieve
    fallback naming the note is refused like any other script."""
    import tempfile
    assert not hasattr(vwg, "TRANSITION_WRITERS")
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        fi = d / "agents" / "footage-indexer" / "scripts" / "sieve_answer_claude.py"
        fi.parent.mkdir(parents=True)
        fi.write_text(NOTE, encoding="utf-8")
        assert vwg.offenders([fi], d), "the old fallback shape went unseen"
    sieve = ROOT / "agents" / "footage-indexer" / "scripts" / "sieve_answer_claude.py"
    if sieve.is_file():
        assert "NEEDS-YOU.md" not in sieve.read_text(encoding="utf-8")


def test_the_root_writers_name_no_vault_note():
    """The root's question writers ask the journal, not the vault."""
    for rel in ("agents/publisher/publisher_auth.py", "agents/publisher/publisher_config.py",
                "agents/analyst/metrics.py",
                "scripts/archive_publish_month.py", "scripts/monthly_archive.py",
                "shared/factory_state.py"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert vwg.python_findings(text, rel, ()) == [], rel
        assert "needs_you" in text or rel.endswith("publisher_config.py"), \
            f"{rel} does not use the journal"
    assert "NEEDS_YOU" not in (ROOT / "agents/publisher/publisher_config.py").read_text()


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    ok = 0
    for name, fn in tests:
        try:
            fn()
            ok += 1
            print(f"PASS {name}")
        except AssertionError as e:
            print(f"FAIL {name}: {e}")
    print(f"{ok}/{len(tests)} passed")
    sys.exit(0 if ok == len(tests) else 1)
