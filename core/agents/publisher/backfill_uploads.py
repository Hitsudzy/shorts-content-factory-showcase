#!/usr/bin/env python3
"""CF-0586: carry the videos that went up before `publish/uploads.json`
existed into it - every video already published or scheduled in Studio.

Until 2.0 the `video_id` of a published video was written down only as prose:
the table of `publish/README.md` (a `youtube.com/shorts/<id>` link in the row of
`<channel>/<day>/<slug>.mp4` or of its Archive archive pointer) and the video's note
`publish/<channel>/<day>/<slug>.md` (the "Загружен и запланирован" line). This
script reads both, links each video to its acceptance row of
`publish/acceptance-log.json` and writes the journal rows with
`source: backfill` through `upload_records.record()` - the journal's one
writer.

Where each field comes from:

* the video - a README row naming `<channel>/<day>/<slug>.mp4` (or the archive
  pointer), a note in `publish/<channel>/<day>/`, or an accepted acceptance row
  whose `publish_path` names a day folder. Rows of the flat root and of
  `_queue/` name no day: with an id they are unresolved, without one ignored.
* `video_id` - the note first (its last `youtube.com/shorts/<id>`; earlier ids
  of the note are deleted earlier uploads, `superseded_video_ids`), else the
  README row (struck `~~...~~` ids are the superseded ones). The two disagree
  only if the README's id is not among the note's superseded ones - then the
  video is unresolved.
* the slot - the note's `## Публикация` (`publish_note.publish_time`), else
  the README row: the last `на DD.MM HH:MM МСК` / `слот YYYY-MM-DD HH:MM МСК`
  of the cell, else `отложенная публикация YYYY-MM-DD HH:MM ET`. A README row
  whose id was replaced (`~~old~~ → new`) says the slot of the *old* upload,
  so its slot is left empty; so is a video published at once ("опубликован").
  Empty is written as `publish_at: null` with the reason in `gaps` - never
  guessed. A slot whose MSK day is not the day folder is a contradiction.
* `entry_id` - the acceptance row whose `publish_path` is this video; else
  the README row's batch cell + slug. It must be `accepted`.

Unresolved (reported, never written): no `video_id` anywhere, no acceptance
row, a contradiction (two live ids, note vs README, slot vs folder, a rejected
acceptance), an id twice, or a row already in the journal that says otherwise.

It is idempotent and meant to be run again: a video already in the journal
with the same row is "already in the journal", and only what is new is
written. On the 2.0 release it is run once more against `main`
(`--root <main checkout>`), where the videos uploaded since the branch was cut
are.

    python3 agents/publisher/backfill_uploads.py                 # dry run: the plan
    python3 agents/publisher/backfill_uploads.py --write         # write the journal
    python3 agents/publisher/backfill_uploads.py --root /path/to/checkout [--json]
"""
import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

AGENT = Path(__file__).resolve().parent
ROOT = AGENT.parent.parent
sys.path.insert(0, str(ROOT / "shared" / "runlog"))
sys.path.insert(0, str(AGENT))
import publish_layout                                           # noqa: E402
import publish_note                                             # noqa: E402
import upload_records                                           # noqa: E402

TASK = "CF-0586"
SHORTS_RE = re.compile(r"youtube\.com/shorts/([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])")
STRUCK_RE = re.compile(r"~~(.*?)~~", re.S)
CELL_PATH_RE = re.compile(r"`([^`|]+\.mp4)`")
BATCH_RE = re.compile(r"`([^`|]+)`")
SLOT_MSK_RE = re.compile(r"(?:\bна\s+(?P<dm>\d{1,2})\.(?P<mo>\d{2})(?:\.(?P<y>\d{4}))?"
                         r"|\bслот\s+(?P<iso>\d{4}-\d{2}-\d{2}))\s+(?P<hh>\d{1,2}):(?P<mm>\d{2})\s+МСК")
SLOT_ET_RE = re.compile(r"отложенная публикация\s+(?P<iso>\d{4}-\d{2}-\d{2})\s+"
                        r"(?P<hh>\d{1,2}):(?P<mm>\d{2})\s+ET\b")
PUBLISHED_AT_ONCE_RE = re.compile(r"опубликован\s+(?:сразу|\d{4}-\d{2}-\d{2})", re.I)


def _ids(text):
    """`(live, superseded)` ids of a text in order of appearance: an id inside
    `~~...~~` is superseded, the others live."""
    struck = {m for s in STRUCK_RE.findall(text) for m in SHORTS_RE.findall(s)}
    live, sup = [], []
    for vid in SHORTS_RE.findall(text):
        (sup if vid in struck else live).append(vid)
    return list(dict.fromkeys(live)), list(dict.fromkeys(sup))


# --------------------------------------------------------------------------
# sources
# --------------------------------------------------------------------------

def readme_rows(readme):
    """[{cell, key (channel, day, slug) | None, slug, batch, live, superseded,
    slot, slot_note, text}] for every table row naming a `.mp4`."""
    p = Path(readme)
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        m = CELL_PATH_RE.fullmatch(cells[0]) if cells else None
        if not m:
            continue
        ref = m.group(1)
        key = upload_records.placement(ref)
        batch = BATCH_RE.search(cells[1]).group(1) if len(cells) > 1 and BATCH_RE.search(cells[1]) else None
        text = " | ".join(cells[2:])
        live, sup = _ids(line)
        row = {"cell": ref, "key": key, "slug": Path(ref.split("#")[-1]).stem, "batch": batch,
               "live": live, "superseded": sup, "text": text, "slot": None, "slot_note": None}
        if key:
            row["slot"], row["slot_note"] = readme_slot(text, key[1], replaced=bool(sup))
        out.append(row)
    return out


def _year_for(day, month, dd):
    """The year of `dd.month` nearest to the folder day `day`."""
    base = date.fromisoformat(day)
    best = None
    for y in (base.year - 1, base.year, base.year + 1):
        try:
            d = date(y, month, dd)
        except ValueError:
            continue
        if best is None or abs((d - base).days) < abs((best - base).days):
            best = d
    return best


def readme_slot(text, day, replaced=False):
    """`(slot text for parse_slot | None, why none)` of a README cell."""
    if replaced:
        return None, ("перезалит (~~старый id~~ → новый): слот в строке README - у старой "
                      "загрузки, у новой не записан")
    hits = list(SLOT_MSK_RE.finditer(text))
    if hits:
        m = hits[-1]
        if m.group("iso"):
            d = m.group("iso")
        else:
            got = _year_for(day, int(m.group("mo")), int(m.group("dm")))
            if m.group("y"):
                got = date(int(m.group("y")), int(m.group("mo")), int(m.group("dm")))
            d = got.isoformat()
        return f"{d} {int(m.group('hh')):02d}:{m.group('mm')} МСК", None
    m = SLOT_ET_RE.search(text)
    if m:
        return f"{m.group('iso')} {int(m.group('hh')):02d}:{m.group('mm')} ET", None
    if PUBLISHED_AT_ONCE_RE.search(text):
        return None, "опубликован сразу, время выхода в строке README не записано"
    return None, "слот в строке README не записан"


def day_notes(publish):
    """{(channel, day, slug): {path, live, superseded, slot, slot_error}} of
    the notes in day folders; `_queue` notes with an id under day None."""
    out = {}
    pub = Path(publish)
    if not pub.is_dir():
        return out
    for ch in sorted(d for d in pub.iterdir() if d.is_dir()):
        if not publish_layout.CHANNEL_RE.match(ch.name):
            continue
        for bucket in sorted(d for d in ch.iterdir() if d.is_dir()):
            is_day = publish_layout.DAY_RE.match(bucket.name)
            if not is_day and bucket.name != publish_layout.QUEUE:
                continue
            for md in sorted(bucket.glob("*.md")):
                text = md.read_text(encoding="utf-8")
                live, sup = _ids(text)
                if not live and not sup and not is_day:
                    continue
                # in a note the last id is the one on the channel; earlier ones
                # are deleted earlier uploads ("Перезалит ... Новый адрес")
                if len(live) > 1:
                    sup = list(dict.fromkeys(sup + live[:-1]))
                    live = live[-1:]
                slot, err = None, None
                try:
                    when = publish_note.publish_time(publish_note.sections(text).get("Публикация", ""))
                    slot = when.isoformat() if when else None
                except publish_note.NoteError as e:
                    err = str(e)
                key = (ch.name, bucket.name if is_day else None, md.stem)
                out[key] = {"path": f"publish/{ch.name}/{bucket.name}/{md.name}", "live": live,
                            "superseded": [v for v in sup if v not in live], "slot": slot,
                            "slot_error": err}
    return out


def acceptance_rows(log):
    p = Path(log)
    if not p.is_file():
        return []
    return json.loads(p.read_text(encoding="utf-8")).get("acceptances") or []


# --------------------------------------------------------------------------
# the plan
# --------------------------------------------------------------------------

def plan(root=None, journal=None):
    """{"add": [row], "exists": [row], "unresolved": [{key, why}], "gaps": [...]}."""
    root = Path(root or ROOT)
    publish = root / "publish"
    readme = readme_rows(publish / "README.md")
    notes = day_notes(publish)
    acc = acceptance_rows(publish / "acceptance-log.json")
    jrows = upload_records.uploads(journal or publish / "uploads.json")
    by_entry = {r.get("entry_id"): r for r in acc}
    by_place = {}
    for r in acc:
        k = upload_records.placement(r.get("publish_path"))
        if k:
            by_place.setdefault(k, []).append(r)

    unresolved = []

    def bad(where, why):
        unresolved.append({"video": where, "why": why})

    keys = []

    def want(k):
        if k not in keys:
            keys.append(k)

    for r in readme:
        if r["key"] is None:
            if r["live"]:
                bad(r["cell"], f"строка README с id {', '.join(r['live'])} не называет канал и день")
            continue
        if r["live"] or r["superseded"]:
            want(r["key"])
    for k, n in notes.items():
        if k[1] is None:
            bad(n["path"], f"заметка в очереди, но с id {', '.join(n['live'] + n['superseded'])}")
        elif n["live"]:
            want(k)
    for k, rows in by_place.items():
        if any(r.get("verdict") == "accepted" for r in rows):
            want(k)
    keys.sort(key=lambda k: (k[0], k[1], k[2]))

    candidates = []
    for k in keys:
        ch, day, slug = k
        where = f"{ch}/{day}/{slug}"
        rrows = [r for r in readme if r["key"] == k]
        note = notes.get(k)
        evidence = []
        # -- the id
        r_live = list(dict.fromkeys(v for r in rrows for v in r["live"]))
        r_sup = list(dict.fromkeys(v for r in rrows for v in r["superseded"]))
        if rrows:
            evidence.append("publish/README.md")
        if note and (note["live"] or note["superseded"]):
            evidence.append(note["path"])
        if len(r_live) > 1:
            bad(where, f"в README у ролика несколько живых id: {', '.join(r_live)}")
            continue
        vid, superseded, gaps = None, [], []
        if note and note["live"]:
            vid = note["live"][0]
            superseded = list(note["superseded"])
            if r_live and r_live[0] != vid:
                if r_live[0] in note["superseded"]:
                    gaps.append(f"README называет удалённую копию {r_live[0]}; живой id - из заметки")
                else:
                    bad(where, f"id расходятся: заметка {vid}, README {r_live[0]}")
                    continue
            superseded += [v for v in r_sup if v not in superseded and v != vid]
        elif r_live:
            vid, superseded = r_live[0], [v for v in r_sup if v != r_live[0]]
        if not vid:
            src = ", ".join(r.get("entry_id") for r in by_place.get(k, []))
            bad(where, f"принят и разложен ({src or 'README'}), но video_id нет ни в README, "
                       f"ни в заметке")
            continue
        # -- the acceptance row
        arow = None
        placed = [r for r in by_place.get(k, []) if r.get("verdict") == "accepted"]
        if len(placed) > 1:
            bad(where, "две принятые строки приёмки с одним publish_path: "
                       + ", ".join(r.get("entry_id") for r in placed))
            continue
        if placed:
            arow = placed[0]
            evidence.append("publish/acceptance-log.json (publish_path)")
        else:
            for r in rrows:
                e = f"{r['batch']}/{slug}" if r["batch"] else None
                if e and e in by_entry:
                    arow = by_entry[e]
                    other = upload_records.placement(arow.get("publish_path"))
                    if other and other != k:
                        bad(where, f"строка приёмки {e} указывает на другой ролик "
                                   f"({arow.get('publish_path')})")
                        arow = False
                    break
            if arow is None:
                bad(where, f"{vid}: нет строки приёмки (ни publish_path, ни батч строки README)")
                continue
            if arow is False:
                continue
            evidence.append("publish/acceptance-log.json (батч строки README)")
        if arow.get("verdict") != "accepted":
            bad(where, f"{vid}: строка приёмки {arow.get('entry_id')} - {arow.get('verdict')}, не принят")
            continue
        # -- the slot
        slot, why = None, None
        if note and note["slot_error"]:
            bad(where, f"{vid}: заметка: {note['slot_error']}")
            continue
        if note and note["slot"]:
            slot = note["slot"]
        else:
            for r in rrows:
                if r["slot"]:
                    slot = r["slot"]
                    break
                why = why or r["slot_note"]
            if not rrows and note:
                why = "в заметке нет слота `## Публикация`"
        publish_at, publish_tz, publish_day = None, None, day
        if slot:
            try:
                publish_at, publish_tz, sday = upload_records.parse_slot(slot)
            except upload_records.JournalError as e:
                bad(where, f"{vid}: слот {slot!r}: {e}")
                continue
            if sday != day:
                bad(where, f"{vid}: слот {publish_at} - день {sday} по МСК, а ролик в папке дня {day}")
                continue
        else:
            gaps.append(why or "слот нигде не записан")
        note_ref = note["path"] if note else upload_records.note_of(
            arow.get("publish_path") if upload_records.placement(arow.get("publish_path")) == k
            else (rrows[0]["cell"] if rrows else None))
        extra = {"evidence": evidence}
        if superseded:
            extra["superseded_video_ids"] = superseded
        if gaps:
            extra["gaps"] = gaps
        row = upload_records.make_row(arow, ch, vid, "backfill", publish_at=publish_at,
                                      publish_tz=publish_tz, publish_day=publish_day,
                                      note=note_ref, task=TASK, **extra)
        candidates.append((where, row))

    # -- one id, one video
    seen = {}
    for where, row in candidates:
        for v in upload_records.ids_of(row):
            seen.setdefault(v, []).append(where)
    twice = {v: w for v, w in seen.items() if len(set(w)) > 1}
    add, exists = [], []
    for where, row in candidates:
        clash = [v for v in upload_records.ids_of(row) if v in twice]
        if clash:
            bad(where, f"id {', '.join(clash)} назван у нескольких роликов: "
                       + "; ".join(sorted(set(sum((twice[v] for v in clash), [])))))
            continue
        try:
            status = upload_records.plan_record(row, jrows + add)
        except upload_records.JournalError as e:
            bad(where, f"расходится с журналом: {e}")
            continue
        (add if status == "added" else exists).append(row)
    return {"add": add, "exists": exists, "unresolved": unresolved}


def write(result, journal):
    written = []
    for row in result["add"]:
        written.append((row, upload_records.record(row, journal)))
    return written


def _line(row):
    gaps = f"  [пробел: {'; '.join(row['gaps'])}]" if row.get("gaps") else ""
    sup = f"  (удалённые копии: {', '.join(row['superseded_video_ids'])})" \
        if row.get("superseded_video_ids") else ""
    return (f"  {row['channel']} {row['publish_day']} {row['slug']:26} {row['video_id']}  "
            f"{row['publish_at'] or '-':25}  {row['entry_id']}{sup}{gaps}")


def report(result, wrote, out):
    print(f"к записи: {len(result['add'])}" + ("" if wrote else "  (сухой прогон; запись - --write)"),
          file=out)
    for row in result["add"]:
        print(_line(row), file=out)
    print(f"уже в журнале: {len(result['exists'])}", file=out)
    for row in result["exists"]:
        print(_line(row), file=out)
    print(f"неразрешённые: {len(result['unresolved'])}", file=out)
    for u in result["unresolved"]:
        print(f"  {u['video']} - {u['why']}", file=out)


def main(argv=None, out=sys.stdout):
    ap = argparse.ArgumentParser(description="CF-0586: backfill publish/uploads.json from the "
                                             "README prose, the day notes and the acceptance log")
    ap.add_argument("--root", default=str(ROOT), help="checkout whose publish/ is read and written")
    ap.add_argument("--journal", help="journal path (default <root>/publish/uploads.json)")
    ap.add_argument("--write", action="store_true", help="write the rows (default: print the plan)")
    ap.add_argument("--json", action="store_true", help="print the plan as JSON")
    args = ap.parse_args(argv)
    journal = Path(args.journal or Path(args.root) / "publish" / "uploads.json")
    result = plan(args.root, journal)
    if args.write:
        write(result, journal)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2), file=out)
    else:
        report(result, args.write, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
