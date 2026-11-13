#!/usr/bin/env python3
"""CF-0652: scripts/needs_you_migrate.py - the open lines of a NEEDS-YOU note
(a temp file, never the vault's) into a temp journal of questions.

Pinned: a dry run by default writes nothing; `--apply` carries every open line
of this factory (no tag, shorts-content-factory, factory, frontend) once - a
second run asks nothing again, even after a carried question was resolved;
another project's lines and closed lines stay out; the line's date becomes
`created`, one named channel becomes `channel`; the note itself is never
written; the default note path comes from the guard (no vault path in the
script)."""
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "shared"))

import needs_you as ny              # noqa: E402
import needs_you_migrate as mig     # noqa: E402
import vault_write_guard as vwg     # noqa: E402

from _tmproot import tmp_root       # noqa: E402

TMP = tmp_root("needs-you-migrate-test-")
_n = [0]

NOTE = """# Требует вашего решения

## Живое на 2026-09-20 (shorts-content-factory)
- [ ] Просмотр роликов — единственный критерий.
- [ ] [shorts-content-factory] **CF-0199** — канал `example-tech` и хэндлы
- [x] [shorts-content-factory] закрытая строка
  - [ ] [factory] 2026-10-05 вложенная строка про example-film
- [ ] [frontend] вопрос центра
- [ ] [other-project] чужой вопрос

## Старое
- ~~CF-0266~~
- [ ] 2026-09-01 старый открытый
"""


def world():
    _n[0] += 1
    base = TMP / f"w{_n[0]}"
    (base / "root" / "channels").mkdir(parents=True)
    for c in ("example-film", "example-tech"):
        (base / "root" / "channels" / f"{c}.json").write_text("{}")
    note = base / "NEEDS-YOU.md"
    note.write_text(NOTE, encoding="utf-8")
    return base, note, base / "journal"


def run(base, note, jd, *extra):
    out = io.StringIO()
    code = mig.main(["--file", str(note), "--dir", str(jd), "--root", str(base / "root"),
                     *extra], out=out)
    return code, out.getvalue()


def test_dry_run_by_default_writes_nothing():
    base, note, jd = world()
    code, out = run(base, note, jd)
    assert code == 0 and "перенести 5" in out and "чужого проекта 1" in out, out
    assert "сухой прогон" in out and not jd.exists()
    assert note.read_text(encoding="utf-8") == NOTE


def test_apply_carries_this_factorys_open_lines_once():
    base, note, jd = world()
    code, out = run(base, note, jd, "--apply")
    assert code == 0 and "записано вопросов: 5" in out, out
    qs = ny.questions(directory=jd)
    texts = [q["text"] for q in qs]
    assert len(qs) == 5 and all(q["source"] == "needs-you-md" for q in qs), texts
    assert not any("чужой" in t or "закрытая" in t for t in texts), texts
    assert texts[0].startswith("Просмотр роликов") and "раздел «Живое на 2026-09-20" in texts[0]
    nested = next(q for q in qs if "вложенная" in q["text"])
    assert nested["created"] == "2026-10-05T00:00:00Z" and nested["channel"] == "example-film"
    tagged = next(q for q in qs if "CF-0199" in q["text"])
    assert tagged["channel"] == "example-tech" and not tagged["text"].startswith("[")
    assert next(q for q in qs if "старый" in q["text"])["text"].endswith("раздел «Старое»)")
    # a second run, after one was resolved: nothing again
    ny.resolve(qs[0]["id"], directory=jd)
    code, out = run(base, note, jd, "--apply")
    assert code == 0 and "перенести 0" in out and "уже в журнале 5" in out, out
    assert len(ny.questions(status="all", directory=jd)) == 5
    assert note.read_text(encoding="utf-8") == NOTE, "the note is never written"
    assert all(json.loads(ln) for ln in (jd / ny.JOURNAL).read_text().splitlines())


def test_no_note_is_exit_1_and_the_default_path_is_the_guards():
    base, note, jd = world()
    code, out = run(base, base / "none.md", jd)
    assert code == 1 and "нет заметки" in out
    assert mig.note_path() == Path(vwg.LEGACY_NEEDS_YOU_NOTE).expanduser()
    src = (ROOT / "scripts" / "needs_you_migrate.py").read_text(encoding="utf-8")
    assert vwg.python_findings(src, "needs_you_migrate.py", ()) == []


if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e.__class__.__name__}: {str(e)[:300]}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
