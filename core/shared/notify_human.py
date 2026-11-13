#!/usr/bin/env python3
"""CF-0925: the factory's Telegram messages in words a human reads.

The user, 2026-11-09: «давай обновим вид сообщений в телеграм, чтобы я лучше
понимал что сейчас происходит. Более человеко понятно. "запустился батч по
расписанию - батч закончился получилось N роликов (оценки, названия) -
загрузил ролики в studio (даты) и тп».

Each builder here turns a source's data into a few short Russian lines: the
first says what happened («▶️ Reel: батч запущен по расписанию»), the next
ones what it gave. No file paths, no internal ids (a channel is `Reel`, not
`example-film` - `notify.channel_label`), Moscow time. The sources hand the
lines to `notify.send(..., multiline=True)`: Telegram gets them as they are
with the center's link as the last line, the journal keeps one line.

Builders (each pure: data in, text out; the readers below never raise):

    batch_started_text(channel, day, chan, root=None, now=None)
        the tick's planned day (`batch_schedule.plan()["days"][0]`) and the
        plan's channel row (`["channels"][channel]`)
    batch_done_text(channel, batch_dir, root=None, broken=None)
        the finished batch's `05-video-editor.json` (videos, refusals) and
        `06-frame-judge.json`, the titles from `03-content-researcher.json`
        (`title_ref.name`), the standing publication holds of the batch
    acceptance_text(channel, batch_id, rows, root=None, batch_dir=None)
        the acceptance record's rows of one batch (`verdict`, `reason`)
    uploaded_text(channel, title, publish_at, root=None)
        one video put into Studio on its slot
    studio_read_text(rows, root=None)
        CF-0926: the planned Studio read came to «прочитано» - per channel the
        videos read and the copyright marks standing (agents/analyst/
        studio_center.py `read_summary`)
    studio_failed_text(code, channels=(), root=None, detail=None, retry_at=None)
        CF-0926: the planned read did not read - what stood in the way and
        what only the user can do about it
"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.append(str(HERE))
import notify  # noqa: E402

TASK = "CF-0925"
VIDEO_EDITOR = "05-video-editor.json"
FRAME_JUDGE = "06-frame-judge.json"
SCRIPTS = "03-content-researcher.json"
TOPICS = "01-trend-hunter.json"
HOLDS_REL = Path("publish") / "publication-holds.json"


def resolve_channel(channel, root=None):
    """The channel's id today: a batch file or a hold row froze the name it was
    written under (CF-0180 rename), so it is resolved at the door."""
    if not channel:
        return channel
    try:
        import channel_ids  # noqa: PLC0415  shared/, beside this file
        return channel_ids.resolve_channel(channel, root=Path(root) if root else None)
    except Exception:  # noqa: BLE001
        return channel

# the frame judge's findings, in the user's words (06 `counts`, `footage_defects[].kind`)
JUDGE_WORDS = {
    "wrong_person": "чужое лицо под именем",
    "foreign_text": "чужой вшитый текст",
    "smeared": "смазанный кадр",
    "thin_strip": "тонкая полоса на размытии",
    "cut_subject": "кроп режет героя",
    "screen_recording": "запись экрана",
    "contradicts": "картинка спорит с текстом",
    "foreign": "кадр не по теме",
}
JUDGE_ORDER = ("wrong_person", "smeared", "thin_strip", "cut_subject", "foreign_text",
               "screen_recording", "contradicts", "foreign")
HARD_RE = re.compile(r"жёсткий:\s*([^;]+)")
ITEM_RE = re.compile(r"^[−-]\s*(\d+(?:[.,]\d+)?)\s+(.+?)\s*$")


# ------------------------------------------------------------------ small words
def plural(n, one, few, many):
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def videos_word(n):
    return f"{n} {plural(n, 'ролик', 'ролика', 'роликов')}"


def topics_word(n):
    return f"{n} {plural(n, 'темы', 'тем', 'тем')}"


def human_slug(slug):
    """`kaijura-minus-zero` -> `Kaijura minus zero` (when nothing better is known)."""
    s = re.sub(r"~.*$", "", str(slug or "")).replace("-", " ").replace("_", " ").strip()
    return (s[:1].upper() + s[1:]) if s else "без названия"


def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None


def slug_of(video):
    out = video.get("slug") or Path(str(video.get("output_path") or "")).stem
    return out or None


def batch_day(batch_id):
    """`08.11` for `2026-11-08T1117Z` (Moscow), else ""."""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})T(\d{2})(\d{2})Z", str(batch_id or ""))
    if not m:
        m2 = re.match(r"(\d{4}-\d{2}-\d{2})", str(batch_id or ""))
        return notify.msk_day_short(m2.group(1)) if m2 else ""
    y, mo, d, h, mi = (int(x) for x in m.groups())
    return notify.msk_day_short(datetime(y, mo, d, h, mi, tzinfo=timezone.utc))


# ------------------------------------------------------------------ the score line
def score_short(line):
    """`C · 71,1 — ...` -> `C 71,1`; "" when there is no line."""
    head = str(line or "").split("—")[0].strip()
    m = re.match(r"^([A-FS][+-]?)\s*·\s*([\d.,]+)", head)
    return f"{m.group(1)} {m.group(2)}" if m else head


def score_items(line):
    """The priced items of a score line: [(points, label)], the label without
    its parenthesised count."""
    tail = str(line or "").partition("—")[2]
    tail = HARD_RE.sub("", tail).strip(" ;")
    out = []
    for part in re.split(r",\s*(?=[−-]\s*\d)", tail):
        m = ITEM_RE.match(part.strip())
        if not m:
            continue
        pts = float(m.group(1).replace(",", "."))
        label = re.sub(r"\s*\([^)]*\)\s*$", "", m.group(2)).strip()
        out.append((pts, label))
    return out


def hard_reason(line):
    m = HARD_RE.search(str(line or ""))
    return m.group(1).strip() if m else ""


def judge_findings(judged):
    """The frame judge's findings on one video, in words, worst first."""
    counts = dict(judged.get("counts") or {})
    for d in judged.get("footage_defects") or []:
        k = d.get("kind") if isinstance(d, dict) else None
        if k and not counts.get(k):
            counts[k] = 1
    wp = judged.get("wrong_person") or {}
    if isinstance(wp, dict) and wp.get("entries"):
        counts["wrong_person"] = max(counts.get("wrong_person") or 0, len(wp["entries"]))
    return [JUDGE_WORDS[k] for k in JUDGE_ORDER if counts.get(k)]


def main_penalty(line):
    """The biggest priced item of a score line («кроп режет героя»), or ""."""
    items = [it for it in score_items(line) if not it[1].startswith("судья")]
    if not items:
        return ""
    return max(items, key=lambda it: it[0])[1]


def refusal_reason(line, judged=None):
    """Why a video went no further, in a few words: the hard rule
    («брак футажа»), the judge's findings, or the biggest price."""
    hard = hard_reason(line)
    found = judge_findings(judged) if judged else []
    if hard and found:
        return f"{hard} ({', '.join(found[:2])})"
    if hard:
        return hard
    if judged and any(it[1].startswith("судья") for it in score_items(line)) and found:
        return ", ".join(found[:2])
    return main_penalty(line) or (", ".join(found[:2]) if found else "")


# ------------------------------------------------------------------ titles and holds
def titles_of(batch_dir):
    """{script_id or topic_id: the work's name} - the scripts of
    `03-content-researcher.json`, then the topics of `01-trend-hunter.json`
    (a topic the writer dropped still has its name there)."""
    out = {}
    if not batch_dir:
        return out
    for name, key, id_key in ((SCRIPTS, "scripts", "script_id"), (TOPICS, "topics", "topic_id")):
        doc = _read(Path(batch_dir) / name)
        for s in (doc or {}).get(key) or []:
            if not isinstance(s, dict):
                continue
            ref = s.get("title_ref") if isinstance(s.get("title_ref"), dict) else {}
            if s.get(id_key) and ref.get("name"):
                out.setdefault(s[id_key], str(ref["name"]).strip())
    return out


def topic_of_script(script_id):
    return re.sub(r"-script\d+$", "", str(script_id or "")) or None


def standing_holds(channel, batch_id, root=None):
    """The topic ids of the batch that carry a publication hold still standing
    (unresolved, unsigned) - `publish/publication-holds.json`."""
    if not root:
        return set()
    doc = _read(Path(root) / HOLDS_REL)
    out = set()
    for row in (doc or {}).get("holds") or []:
        if not isinstance(row, dict) or row.get("resolved_at"):
            continue
        sig = row.get("signature")
        if isinstance(sig, dict) and sig.get("user"):
            continue
        if (resolve_channel(row.get("channel"), root) == resolve_channel(channel, root)
                and row.get("batch_id") == batch_id and row.get("topic_id")):
            out.add(row["topic_id"])
    return out


# ------------------------------------------------------------------ 1. the batch started
def _when(at, now=None):
    """`15:40` when `at` is on the day of `now` (Moscow), else `10.11 02:10`."""
    if not at:
        return ""
    try:
        t = notify._utc(at).astimezone(notify.msk_zone())
        n = notify._utc(now).astimezone(notify.msk_zone())
    except (TypeError, ValueError):
        return str(at)
    return t.strftime("%H:%M") if t.date() == n.date() else t.strftime("%d.%m %H:%M")


def batch_started_text(channel, day, chan=None, root=None, now=None):
    """«▶️ Reel: батч запущен по расписанию.» and what the feed has, why the
    batch runs, when it ends."""
    chan = chan or {}
    name = notify.channel_label(channel, root)
    second = bool(day.get("budget_admission"))
    lines = [f"▶️ {name}: {'второй батч дня' if second else 'батч'} запущен по расписанию."]
    until = chan.get("feed_until")
    q, pend = chan.get("queue"), chan.get("pending")
    feed = (f"Опубликовано вперёд до {notify.msk_day_short(until)}" if until
            else "В ленте вперёд ничего не стоит")
    if q is not None:
        feed += f", в копилке {q}"
    if pend:
        feed += f", ждут приёмки {pend}"
    lines.append(feed + ".")
    bfd = chan.get("batch_feed_days")
    why = []
    if bfd:
        why.append(f"готовых роликов меньше чем на {bfd} дн. вперёд (с копилкой)")
    fe = day.get("first_empty_slot")
    if fe:
        why.append(f"первый пустой слот {notify.msk_short(fe)}")
    if why:
        lines.append("Зачем: " + ", ".join(why) + ".")
    end = day.get("est_end")
    tail = f"Конец ≈ {_when(end, now)}" if end else ""
    if day.get("est_videos"):
        tail += (", " if tail else "") + f"ожидаем ~{videos_word(day['est_videos'])}"
    if tail:
        lines.append(tail + ".")
    return "\n".join(lines)


# ------------------------------------------------------------------ 2. the batch is done
def batch_done_text(channel, batch_dir, root=None, broken=None):
    """«✅ Reel: батч готов — 4 ролика из 9 тем» and a line per video (its
    name, the score gate's grade, the frame judge's word, a hold), then the
    topics the score gate stopped before a video."""
    name = notify.channel_label(channel, root)
    bdir = Path(batch_dir)
    d05 = _read(bdir / VIDEO_EDITOR)
    if broken:
        return f"⚠️ {name}: батч закончился с ошибкой на стадии {broken} — нужен разбор."
    if not isinstance(d05, dict):
        return f"✅ {name}: батч закончен — итог стадии монтажа не прочитан, смотрите центр."
    d06 = _read(bdir / FRAME_JUDGE) or {}
    titles = titles_of(bdir)
    judged = {v.get("script_id"): v for v in d06.get("videos") or [] if isinstance(v, dict)}
    held = standing_holds(resolve_channel(d05.get("channel") or channel, root),
                          d05.get("batch_id") or bdir.name, root)
    videos = [v for v in d05.get("videos") or [] if isinstance(v, dict)]
    refusals = [r for r in d05.get("refusals") or [] if isinstance(r, dict)]
    made = {v.get("script_id") for v in videos}
    refusals = [r for r in refusals if r.get("script_id") not in made]
    topics = len(made | {r.get("script_id") for r in refusals})

    def title(sid, slug=None):
        return (titles.get(sid) or titles.get(topic_of_script(sid))
                or human_slug(slug or "без названия"))

    passed = 0
    rows = []
    for v in videos:
        sid = v.get("script_id")
        j = judged.get(sid)
        line_src = (j or {}).get("score_line") or v.get("score_line")
        grade = score_short(line_src)
        row = f"• {title(sid, slug_of(v))}" + (f" — {grade}" if grade else "")
        if j is None:
            mark = "судья кадров не смотрел"
        elif j.get("gate") == "pass":
            mark = "судья кадров пропустил"
            passed += 1
        elif j.get("gate") == "reject":
            why = refusal_reason(j.get("score_line"), j)
            mark = "отклонён судьёй кадров" + (f": {why}" if why else "")
        else:
            mark = "судья кадров не досмотрел"
        if topic_of_script(sid) in held:
            mark += "; на удержании — ждёт подписи"
        rows.append(f"{row}, {mark}")
    head = f"✅ {name}: батч готов — {videos_word(len(videos))} из {topics_word(topics)}"
    if d06.get("videos"):
        head += f", судья кадров пропустил {passed}"
    lines = [head]
    lines += rows
    if refusals:
        lines += ["", "Не дошли до ролика:"]
        for r in refusals:
            sid = r.get("script_id")
            line_src = r.get("score_line") or ""
            grade = score_short(line_src)
            if r.get("gate") == "score_below_threshold" or r.get("reason_code") == \
                    "score_below_threshold":
                why = "отклонён гейтом счёта" + (f": {main_penalty(line_src)}"
                                                 if main_penalty(line_src) else "")
            else:
                why = f"отказ ({str(r.get('reason_code') or r.get('gate') or 'без кода')})"
            lines.append(f"• {title(sid)}" + (f" — {grade}" if grade else "") + f", {why}")
    if not videos:
        lines.append("Роликов к приёмке нет.")
    return "\n".join(lines)


# ------------------------------------------------------------------ 3. the acceptance
def acceptance_text(channel, batch_id, rows, root=None, batch_dir=None):
    """«👀 Reel 08.11: принято 2 из 6 — X, Y» and a line per refusal with its reason."""
    name = notify.channel_label(channel, root)
    titles = titles_of(batch_dir) if batch_dir else {}
    by_topic = {topic_of_script(k): v for k, v in titles.items()}

    def title(r):
        return (r.get("title") or by_topic.get(r.get("topic_id"))
                or human_slug(r.get("slug")))

    acc = [r for r in rows if r.get("verdict") == "accepted"]
    rej = [r for r in rows if r.get("verdict") == "rejected"]
    day = batch_day(batch_id)
    head = f"👀 {name}{' ' + day if day else ''}: принято {len(acc)} из {len(rows)}"
    if acc:
        head += " — " + ", ".join(title(r) for r in acc)
    lines = [head]
    if rej:
        lines.append("Отказ:")
        for r in rej:
            why = str(r.get("reason") or "").strip()
            lines.append(f"• {title(r)}" + (f" — {why}" if why else ""))
    if acc:
        lines.append("Принятые уходят в копилку, оттуда — на слоты публикации.")
    return "\n".join(lines)


# ------------------------------------------------------------------ 4. into Studio
def uploaded_text(channel, title, publish_at, root=None):
    name = notify.channel_label(channel, root)
    when = notify.msk_short(publish_at)
    return (f"📤 {name}: «{title}» стоит на {when} (отложенная публикация)" if when
            else f"📤 {name}: «{title}» залит в Studio")


# ------------------------------------------------------------------ 5. Studio read (CF-0926)
STUDIO_FAIL_WORDS = {"no_extension": "расширение Chrome не подключено",
                     "login_needed": "нужен вход в аккаунт Google",
                     "error": "чтение закончилось ошибкой"}
# what only the user can do (the codes the planned read calls him for)
STUDIO_FIX = {"no_extension": "открыть Chrome и включить расширение Claude in Chrome",
              "login_needed": "войти в аккаунт Google в Chrome (studio.youtube.com)"}
STUDIO_BUTTON = "центр → «Прочитать Studio»"


def studio_read_text(rows, root=None):
    """«📊 Studio прочитана: Reel — 10 роликов, Tech — 10».
    `rows`: [{channel, videos}]."""
    parts = []
    for i, r in enumerate(rows):
        name = notify.channel_label(r["channel"], root)
        n = int(r.get("videos") or 0)
        parts.append(f"{name} — {videos_word(n) if i == 0 else n}")
    return "📊 Studio прочитана: " + (", ".join(parts) or "каналов нет")


def studio_failed_text(code, channels=(), root=None, detail=None, retry_at=None):
    """«⚠️ Studio не прочитана (Reel, Tech): расширение Chrome не подключено» +
    what is needed from the user (only for the codes he alone fixes) and when
    the factory tries again."""
    names = ", ".join(notify.channel_label(c, root) for c in channels or ())
    lines = [f"⚠️ Studio не прочитана{f' ({names})' if names else ''}: "
             + STUDIO_FAIL_WORDS.get(code, STUDIO_FAIL_WORDS["error"])]
    if detail and code not in STUDIO_FIX:
        lines[0] += f" — {detail}"
    fix = STUDIO_FIX.get(code)
    if fix:
        lines.append(f"Нужно от вас: {fix}; потом {STUDIO_BUTTON}"
                     + (f" — или я попробую сам ~{retry_at}" if retry_at else ""))
    elif retry_at:
        lines.append(f"Попробую ещё раз ~{retry_at}.")
    return "\n".join(lines)

