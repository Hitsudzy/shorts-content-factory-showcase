#!/usr/bin/env python3
"""CF-0652: carry the open lines of the old Notebook NEEDS-YOU.md into the
journal of questions (shared/needs_you.py) - once, by the driver.

The note is only read, never written (the vault is Claude's; its path is kept
in shared/vault_write_guard.py, `LEGACY_NEEDS_YOU_NOTE`, the one place allowed
to name it). The driver deletes the note himself after the run.

What is carried: every open line (`- [ ] ...`, at any depth) whose project tag
is this factory's - no tag, `[shorts-content-factory]`, `[factory]`,
`[frontend]` (the command center lives in this root). A line of another
project's tag stays in the note and is listed. Each line becomes one question:

    source   needs-you-md
    key      needs-you-md:<sha1 of the line's text, 12>  - a second run (or a
             line already carried and resolved since) asks nothing again
    text     the line without its checkbox and tag, plus the section it stood
             in («раздел …»)
    channel  the channel when exactly one channel of channels/*.json is named
    created  the line's own date when it starts with YYYY-MM-DD, else now

Nothing goes to Telegram: these questions are old, the user knows them.

    python3 scripts/needs_you_migrate.py [--file NOTE] [--dir JOURNAL_DIR] [--apply]
        # without --apply: the plan, nothing written (exit 0)
        # exit 1 - the note is not there; 2 - a bad call
"""
import argparse
import hashlib
import importlib.util
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TASK = "CF-0652"
SOURCE = "needs-you-md"
OPEN_LINE_RE = re.compile(r"^\s*- \[ \]\s+(.*)$")
TAG_RE = re.compile(r"^\[([^\]]+)\]\s*")
DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\b")
OURS = (None, "shorts-content-factory", "factory", "frontend")


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def note_path(explicit=None):
    if explicit:
        return Path(explicit).expanduser()
    vwg = _load("vault_write_guard", "shared/vault_write_guard.py")
    return Path(vwg.LEGACY_NEEDS_YOU_NOTE).expanduser()


def channels(root=REPO):
    return sorted(p.stem for p in (Path(root) / "channels").glob("*.json"))


def parse(text):
    """[{heading, tag, text, date}] for every open line of the note."""
    out, heading = [], None
    for raw in text.splitlines():
        if raw.startswith("#"):
            heading = raw.lstrip("#").strip()
            continue
        m = OPEN_LINE_RE.match(raw)
        if not m:
            continue
        body = m.group(1).strip()
        t = TAG_RE.match(body)
        tag = t.group(1) if t else None
        if t:
            body = body[t.end():].strip()
        d = DATE_RE.match(body)
        out.append({"heading": heading, "tag": tag, "text": body,
                    "date": d.group(1) if d else None})
    return out


def key_of(line):
    return f"{SOURCE}:" + hashlib.sha1(line["text"].encode("utf-8")).hexdigest()[:12]


def plan(note_text, known_keys, chans=()):
    """(carry, already, foreign): the lines to carry as questions, the ones
    the journal has, the ones of another project."""
    carry, already, foreign = [], [], []
    for ln in parse(note_text):
        if ln["tag"] not in OURS:
            foreign.append(ln)
            continue
        k = key_of(ln)
        if k in known_keys:
            already.append(ln)
            continue
        named = [c for c in chans if c in ln["text"]]
        text = ln["text"] + (f" (из NEEDS-YOU.md, раздел «{ln['heading']}»)" if ln["heading"]
                             else " (из NEEDS-YOU.md)")
        carry.append(dict(ln, key=k, question=text,
                          channel=named[0] if len(named) == 1 else None,
                          created=f"{ln['date']}T00:00:00Z" if ln["date"] else None))
        known_keys = set(known_keys) | {k}
    return carry, already, foreign


def main(argv=None, out=sys.stdout):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], allow_abbrev=False)
    ap.add_argument("--file", help="the note (default: the guard's LEGACY_NEEDS_YOU_NOTE)")
    ap.add_argument("--dir", help="the journal's directory (default: shared/needs_you.py's)")
    ap.add_argument("--root", default=str(REPO), help="the factory root (channels/)")
    ap.add_argument("--apply", action="store_true", help="write the questions")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    ny = _load("needs_you", "shared/needs_you.py")
    path = note_path(a.file)
    if not path.is_file():
        print(f"нет заметки {path} - переносить нечего", file=out)
        return 1
    known = {q["key"] for q in ny.questions(status="all", directory=a.dir)}
    carry, already, foreign = plan(path.read_text(encoding="utf-8"), known, channels(a.root))
    where = ny.journal_path(directory=a.dir)
    print(f"{path}: открытых строк {len(carry) + len(already) + len(foreign)} - перенести "
          f"{len(carry)}, уже в журнале {len(already)}, чужого проекта {len(foreign)} "
          f"(остаются в заметке); журнал {where}", file=out)
    for ln in carry:
        print(f"  + {ln['created'] or 'сейчас'} {ln['channel'] or '-'}: {ln['question'][:160]}",
              file=out)
    for ln in foreign:
        print(f"  ~ [{ln['tag']}] {ln['text'][:160]}", file=out)
    if not a.apply:
        print(f"сухой прогон - ничего не записано (`--apply` - записать; {TASK})", file=out)
        return 0
    n = 0
    for ln in carry:
        q, created = ny.add(SOURCE, ln["key"], ln["question"], channel=ln["channel"],
                            by=SOURCE, now=ln["created"], notify=False, directory=a.dir)
        n += created
    print(f"записано вопросов: {n}; заметку {path} удаляет драйвер "
          f"(её чужие строки - {len(foreign)} - перенести руками до удаления)", file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
