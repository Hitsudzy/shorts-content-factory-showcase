#!/usr/bin/env python3
"""CF-0421 (the writer side is CF-0017): a video's metadata, read from its note
`publish/<channel>/<YYYY-MM-DD>/<slug>.md` - the day it goes out, Moscow time -
or `publish/<channel>/_queue/<slug>.md` while it has no slot (CF-0475,
`shared/runlog/publish_layout.py`).

Today a human-and-agent session writes the note by the rules of
`docs/publisher-metadata-rules.md`; CF-0017 will generate it from the script.
Either way this reader is the one door metadata goes through into
`videos.insert`, and it refuses what YouTube would refuse or what the rules call
a defect, before a byte is uploaded:

* `## Название` - non-empty, ≤ 100 characters, no `<` or `>`;
* `## Описание` - non-empty, ≤ 5000 bytes, no `<` or `>`, and no template
  placeholder `[SOURCE NAME ...]` (rules, "Описание", block 2 - a placeholder
  that reached publication is a defect);
* `## Теги` - comma-separated, ≤ 500 characters the way YouTube counts them
  (a tag with a space is counted with its quotes);
* `## Публикация` - the scheduled time in bold, `**YYYY-MM-DD[,] HH:MM <zone>**`
  with zone `America/New_York` / `ET` / `МСК` / `UTC`; when the same section
  also says `HH:MM UTC`, the two must agree - a note that says two different
  times is refused, not guessed;
* `## Настройки` - `ИИ/синтетический контент: да|нет`, when present, becomes
  `containsSyntheticMedia`.
"""
import re
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:                                             # pragma: no cover
    ZoneInfo = None

TITLE_MAX = 100
DESCRIPTION_MAX_BYTES = 5000
TAGS_MAX = 500
PLACEHOLDER = re.compile(r"\[\s*SOURCE\s+NAME", re.I)
ZONES = {"america/new_york": "America/New_York", "et": "America/New_York",
         "мск": "Europe/Moscow", "europe/moscow": "Europe/Moscow", "utc": "UTC"}
WHEN = re.compile(r"\*\*(\d{4}-\d{2}-\d{2}),?\s+(\d{1,2}):(\d{2})\s+"
                  r"(America/New_York|ET|МСК|Europe/Moscow|UTC)\*\*", re.I)
UTC_MENTION = re.compile(r"(?<![\d:])(\d{1,2}):(\d{2})\s*UTC\b")
SYNTHETIC = re.compile(r"ИИ\s*/\s*синтетический контент:\s*(да|нет)", re.I)


class NoteError(Exception):
    pass


def sections(text):
    """{heading: body} for every `## heading` of the note, bodies stripped."""
    out, name, buf = {}, None, []
    for line in text.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m and not line.startswith("###"):
            if name is not None:
                out[name] = "\n".join(buf).strip()
            name, buf = m.group(1), []
        elif name is not None:
            buf.append(line)
    if name is not None:
        out[name] = "\n".join(buf).strip()
    return out


def title_and_description(sec):
    """`(title, description)` of the note's sections as they go to YouTube:
    the title's lines joined by a space, the description as written. The one
    reading of the two - the upload body and the claim check of CF-0555
    (`note_claims.py`) fingerprint the same strings."""
    title = " ".join(line.strip() for line in sec.get("Название", "").splitlines() if line.strip())
    return title, sec.get("Описание", "").strip()


def tags_length(tags):
    return sum(len(t) + (2 if " " in t else 0) for t in tags) + max(len(tags) - 1, 0)


def publish_time(section):
    """The scheduled time of a `## Публикация` body, as an aware UTC datetime,
    or None when the body names no time in the recognised form."""
    m = WHEN.search(section or "")
    if not m:
        return None
    if ZoneInfo is None:                                        # pragma: no cover
        raise NoteError("zoneinfo is unavailable (Python < 3.9)")
    day, hh, mm, zone = m.groups()
    tz = ZoneInfo(ZONES[zone.lower()])
    local = datetime.strptime(f"{day} {int(hh):02d}:{mm}", "%Y-%m-%d %H:%M").replace(tzinfo=tz)
    when = local.astimezone(timezone.utc)
    for u in UTC_MENTION.finditer(section[m.end():] + " " + section[:m.start()]):
        if (int(u.group(1)), int(u.group(2))) != (when.hour, when.minute):
            raise NoteError(f"`## Публикация` names two different times: {m.group(0)} is "
                            f"{when:%H:%M} UTC, the text also says {u.group(0)}")
        break
    return when


def parse(path):
    """The note as the upload needs it: title, description, tags, publish_at
    (aware UTC or None), contains_synthetic (bool or None). NoteError on
    anything YouTube would refuse or the rules call a defect."""
    try:
        text = open(path, encoding="utf-8").read()
    except OSError as e:
        raise NoteError(f"{path}: cannot read the note ({e})") from e
    sec = sections(text)
    problems = []

    title, description = title_and_description(sec)
    if not title:
        problems.append("`## Название` is empty or missing")
    elif len(title) > TITLE_MAX:
        problems.append(f"title is {len(title)} characters, YouTube allows {TITLE_MAX}")
    if not description:
        problems.append("`## Описание` is empty or missing")
    elif len(description.encode("utf-8")) > DESCRIPTION_MAX_BYTES:
        problems.append(f"description is {len(description.encode('utf-8'))} bytes, "
                        f"YouTube allows {DESCRIPTION_MAX_BYTES}")
    if PLACEHOLDER.search(description):
        problems.append("description still carries the template placeholder [SOURCE NAME ...] - "
                        "the real source goes there (docs/publisher-metadata-rules.md)")
    for field, value in (("title", title), ("description", description)):
        if "<" in value or ">" in value:
            problems.append(f"{field} contains '<' or '>', which YouTube rejects")

    tags = [t.strip() for t in re.split(r"[,\n]", sec.get("Теги", "")) if t.strip()]
    if tags_length(tags) > TAGS_MAX:
        problems.append(f"tags take {tags_length(tags)} characters, YouTube allows {TAGS_MAX}")

    publish_at = None
    try:
        publish_at = publish_time(sec.get("Публикация", ""))
    except NoteError as e:
        problems.append(str(e))

    synth = SYNTHETIC.search(sec.get("Настройки", ""))
    contains_synthetic = None if not synth else synth.group(1).lower() == "да"

    if problems:
        raise NoteError(f"{path}: " + "; ".join(problems))
    return {"title": title, "description": description, "tags": tags,
            "publish_at": publish_at, "contains_synthetic": contains_synthetic}
