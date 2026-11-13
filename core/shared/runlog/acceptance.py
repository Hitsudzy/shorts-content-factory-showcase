#!/usr/bin/env python3
"""CF-0328: the user's acceptance of a video, written down under the video's name.

The defect, 2026-09-22. Six finished videos were shown to the user, he answered
with three yes and three no, and the answers were filed against the wrong
videos: the three files heavier than 30 MB went over in a second group, the
order of his list did not match the order they were sent in, and three verdicts
of the six landed on videos that had not earned them. The mistake held exactly
until he named the videos himself. One conclusion about the reasons for refusal
was built on it and withdrawn.

Nothing recorded any of this anywhere: the verdicts lived in a chat window and
died with the session. That is the whole reason this module exists, and the two
rules it is built out of:

* **the verdict is tied to the name of the video, never to a position in a
  list.** `question()` shows the files by name and numbers nothing; `record()`
  refuses a verdict whose answer does not name the video it is being filed
  against, and says so with the video's name in the error. An answer that is a
  bare position ("1, 3 and 4") is refused by the same check, under its own
  sentence.
* **the machine never invents the verdict.** It is copied from the user's
  explicit answer, the answer is kept on the row beside it, and nothing here
  reads an acceptance out of the state of the `publish/` directory - the same
  rule as `signature` in `shared/gate-prices.json` (CF-0320) and in
  `publish/publication-holds.json` (CF-0318): a verdict written by the code
  that wants it is not a verdict.

**Where the record lives.** `publish/acceptance-log.json`, beside the hold
registry and for the same reason (CF-0318): `scripts/monthly_archive.py`
*zips* a batch onto Archive and deletes it after 30 days, so a record kept inside the batch
directory is a record that leaves. One row per video per batch, keyed
`<channel>/<batch>/<slug>`, carrying the four fields the task asks for - the
name of the video, the batch, the verdict, the reason in one phrase - plus the
answer it was taken from. `publish/README.md` stays what it is: prose a human
reads, the list of what lay here and why. This file is the machine half of the
same story and neither is generated from the other.

**A rejected video does not reach `publish/`, and its reason outlives it.**
CF-0738: every verdict `accepted` goes through `queue_accepted` in the step
that records it (`record_and_commit`, `commit_pending`, `--record --write`) -
nobody has to remember to call `place()` after it any more (Science
`sophie-adenot`, 13.10: accepted from the center, found nowhere);
`repair_queue` / `--enqueue-accepted` finds the rows that missed it.
`place()` copies an accepted video into `publish/<channel>/_queue/` (or straight
into its day folder `publish/<channel>/<YYYY-MM-DD>/` when the slot is known - the
layout of CF-0475, `publish_layout.py`) and refuses a video the user
did not accept, naming the reason on its row; `check()` reads the directory back
against the record and reports a video sitting in `publish/` with a rejection or
with no verdict at all - which is what the 2026-09-22 misreading did to `delver`
and `dtf-st-louis` before the user's own correction took them out again.
**Nothing here uploads anything.** Copying a file into `publish/` is not
publishing: the button is pressed by a human (CF-0018), and an acceptance
recorded here is not a permission to press it.

**The acceptance and the publication hold are two different facts.** A hold
(`publish/publication-holds.json`, CF-0318) blocks the upload until a human
signs it; an acceptance says the user wants the video out at all. They are never
folded into one field - `state()` answers with both, and `publishable` is the
conjunction, not a third verdict.

**The dictionary of reasons, and when a reason becomes a machine check.**
`reasons()` counts every rejection ever recorded - standing and superseded -
under its `reason_code`, with the videos and batches it was named on.
`candidates()` applies the repeatability rule of CF-0319 (as CF-0322 puts it: a
task is filed out of the repeatability of a code, not out of one run): a reason
named on `REPEAT` different videos is no longer an incident. Three outcomes, and
the third one matters as much as the first:

    machine_check_candidate  the reason repeats and a machine could read it -
                             `qc_render` or the frame judge, named on the row
    check_regression         the reason repeats and a machine check already
                             claims it (`covered_by`): the check is failing,
                             and a new task about the defect would be the wrong
                             task
    not_a_machine_check      the reason repeats and nothing mechanical can read
                             it - "not interesting" is not a DoD item (decision
                             of 2026-09-11) and is deliberately not measured.
                             Counted, kept, and never turned into a gate

CLI: `runlog acceptance [--ask CHANNEL/BATCH SLUG...] [--record CHANNEL/BATCH/SLUG
--verdict V --answer TEXT [--reason ...]] [--reasons] [--check] [--state ...]
[--json] [--write [--commit --by WHO]] [--commit-pending]`.

CF-0675: `record_and_commit` / `--commit` - a verdict is one git commit of the
record, or, while a batch is going, a line of the gitignored queue
`publish/acceptance-pending.jsonl` that `commit_pending` (the schedule's tick
after the batch, or the next verdict) commits as one. See the section below.
"""
import argparse
import contextlib
import copy
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import publish_layout                                       # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent

# The record. `publish/` and not `pipeline/<channel>/<batch>/`: a batch is moved
# off this disk after 31 days (CF-0056), and the questions this record answers
# ("why was that one refused?") are asked months later.
ACCEPTANCE_LOG_ENV = "ACCEPTANCE_LOG"
ACCEPTANCE_LOG_REL = Path("publish") / "acceptance-log.json"
# CF-0675: the verdicts given while a batch is going wait here (gitignored) -
# a commit of the record under an open batch moves the root's HEAD under it.
PENDING_NAME = "acceptance-pending.jsonl"
PENDING_LOCK_NAME = "acceptance-pending.lock"


def default_log():
    """Where the record is: `$ACCEPTANCE_LOG` (the file itself - a test names a
    temp path, a missing file reads as no verdicts), else
    `$FACTORY_ROOT/publish/acceptance-log.json`, else this checkout's. CF-0523:
    the same variable and the same order as the video editor's
    `retired_shots.default_acceptance_log()` - one knob for one record."""
    log = os.environ.get(ACCEPTANCE_LOG_ENV)
    if log:
        return Path(log).expanduser()
    env = os.environ.get("FACTORY_ROOT")
    if env:
        return Path(env).expanduser().resolve() / ACCEPTANCE_LOG_REL
    return ROOT / ACCEPTANCE_LOG_REL


LOG = default_log()
PUBLISH = ROOT / "publish"
# CF-0318. Read here, never written here.
HOLDS = ROOT / "publish" / "publication-holds.json"

ACCEPTED, REJECTED = "accepted", "rejected"
VERDICTS = (ACCEPTED, REJECTED)

# The two machine readers a repeating reason can become - `qc_render` in the
# Editor (CF-0294, CF-0327) and the frame judge over the finished frames
# (CF-0298). A reason that belongs to neither is not a defect a gate can hold.
QC_RENDER, FRAME_JUDGE = "qc_render", "frame_judge"
CHECKS = (QC_RENDER, FRAME_JUDGE)

# CF-0319 / CF-0322: one video is an incident, the same reason on a second video
# is a pattern. Two, not three: the corpus is six to nine videos a fortnight, so
# a threshold of three would need a month of refusals before it said anything.
REPEAT = 2

VIDEO_SUFFIX = ".mp4"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
CODE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
# `publish/` holds files that are not a video's note.
NOT_A_SLUG = publish_layout.NOT_A_SLUG

KIND_CANDIDATE = "machine_check_candidate"
KIND_REGRESSION = "check_regression"
KIND_NOT_MACHINE = "not_a_machine_check"

NOTE = (
    "CF-0328. One row per video per batch: the user's acceptance verdict, under the "
    "name of the video and never a position in a list. `verdict` is copied from an "
    "explicit answer of the user that names the video, kept on the row as `answer`; "
    "nothing in shared/runlog/acceptance.py ever writes a verdict of its own and "
    "nothing reads one out of the state of publish/ - the same rule as `signature` in "
    "shared/gate-prices.json (CF-0320) and publish/publication-holds.json (CF-0318). "
    "This is the machine half of publish/README.md, which stays prose for a human; "
    "neither is generated from the other. An acceptance is NOT a permission to upload: "
    "the button is pressed by a human (CF-0018). The publication hold of CF-0318 is a "
    "different fact in a different file and is never folded into `verdict` - read both "
    "through acceptance.state(). A row is never deleted: a verdict the user changed is "
    "replaced in place and the old one moves into `history`, which is where the "
    "2026-09-22 misattribution and the videos the user later pulled himself are "
    "readable. `reason_code` is the dictionary key the repeatability rule of CF-0319 "
    "counts; `covered_by` names the machine check that already claims that reason, so "
    "a repeat under a covered code reads as a failing check rather than a new task."
)


class AcceptanceError(Exception):
    """A verdict that may not be recorded, or a video that may not be placed.

    CF-0676: every refusal carries a stable `code` and `text_ru`, the Russian
    line for a person (the command center shows it), filled from REFUSALS_RU
    with the values the raise passes (`slug`, `batch`, ...). The English text -
    `str(e)` - stays what it was: journals and tests read it. A code with no
    row in REFUSALS_RU is a KeyError here, at the raise, and
    tests/test_acceptance_refusals_ru.py finds every raise without one."""

    def __init__(self, text, *, code, **values):
        super().__init__(text)
        self.code = code
        self.values = values
        self.text_ru = REFUSALS_RU[code].format_map(values)

    def as_dict(self):
        """{code, text_ru, text} - the refusal as the center reads it."""
        return {"code": self.code, "text_ru": self.text_ru, "text": str(self)}


# CF-0676: code -> the Russian line of a refusal. One table beside the class
# rather than a Russian argument at each raise: the wording is reviewed in one
# place, a code is checked against it once (in the constructor), and a raise
# names only its code and the values its line needs. No task numbers, no paths
# in these lines - the English text keeps those.
REFUSALS_RU = {
    "key_malformed": "«{key}» - не адрес ролика или батча: нужно «{want}».",
    "record_unreadable": "Журнал приёмки не читается - ни одного вердикта из него не прочесть.",
    "record_not_a_log": "Файл журнала приёмки - не журнал: в нём нет списка вердиктов.",
    "nothing_to_show": "Нет ни одного ролика, о котором спросить.",
    "verdict_unknown": "Ролик «{slug}»: «{verdict}» - не вердикт; бывает «принят» или «отклонён».",
    "not_a_video_name": "«{slug}» - не имя ролика (строчные латинские буквы, цифры, дефисы). "
                        "Вердикт записывается под именем ролика, не под номером.",
    "video_not_shown": "Ролика «{slug}» нет среди показанных роликов батча - вердикт не записан.",
    "answer_missing": "У вердикта по ролику «{slug}» нет ответа пользователя - вердикт берётся "
                      "только из его слов.",
    "answer_without_name": "В ответе нет имени ролика «{slug}» - вердикт привязывается к ролику "
                           "по имени. Впишите имя ролика в ответ.",
    "answer_is_position": "Ответ про ролик «{slug}» - номер в списке, а не имя. Номер вердиктом "
                          "не считается: спросите ещё раз, с именем ролика.",
    "rejection_without_reason": "Отказ без причины не записывается - нужна причина одной фразой.",
    "rejection_without_code": "Для отказа нужен код причины (латиница, цифры, подчёркивание: "
                              "blurry_footage) - по нему фабрика считает повторы причин.",
    "acceptance_with_code": "У «принят» не бывает кода причины - уберите его.",
    "acceptance_with_check": "У «принят» не бывает проверки, которая поймала бы дефект - "
                             "она бывает только у отказа.",
    "check_unknown": "«{check}» - не название проверки фабрики.",
    "code_shas_broken": "Запись о коде, которым собран ролик «{slug}», испорчена - вердикт "
                        "не записан.",
    "topic_mismatch": "Тема «{topic}» не совпадает с темой ролика «{slug}» в батче («{found}») - "
                      "удержание по чужой теме ничего не держит. Вердикт не записан.",
    "topic_not_found": "Тема ролика «{slug}» не находится в батче - без неё вердикт не держит "
                       "удержание публикации. Вердикт не записан.",
    "verdict_already_given": "У ролика «{slug}» уже есть вердикт. Заменить его можно, только "
                             "сказав, почему пользователь передумал (поле «почему меняем»).",
    "holds_unreadable": "Список удержаний публикации не читается.",
    "place_without_row": "У ролика нет записанного вердикта - в папку публикации он не идёт.",
    "place_not_accepted": "Ролик «{slug}» не принят - в папку публикации он не идёт. "
                          "Причина: {reason}.",
    "render_missing": "Нет готового файла ролика «{slug}».",
    "channel_unknown": "Не понять, какого канала ролик «{slug}» - назовите канал явно.",
    "publish_layout_refused": "Ролик «{slug}» не разложить по папке публикации: {why}.",
    "queue_unreadable": "Очередь вердиктов не читается (строка {line}) - вердикт из неё "
                        "не потерян, но и не применён.",
    "queue_not_a_verdict": "В очереди вердиктов строка {line} - не вердикт.",
    "record_outside_repo": "Журнал приёмки лежит вне репозитория фабрики - его нельзя "
                           "закоммитить.",
    "not_committed": "Журнал приёмки не закоммичен - запись осталась как была.",
    "cli_needs_verdict": "Для записи нужен вердикт: принят или отклонён.",
    "cli_commit_needs_write": "Коммит записывает журнал - нужен и флаг записи.",
}


# --------------------------------------------------------------------------
# the code the video was built by (CF-0399)
# --------------------------------------------------------------------------

VIDEO_EDITOR_FILE = "05-video-editor.json"
# The explicit "we do not know what code built this video". Never an absent key
# and never an empty mapping: an absent key is how a row written before CF-0399
# reads, and an empty mapping would read as "no repo was involved". A verdict
# whose code is unknown cannot be tied to a commit - that is a fact about the
# row, and it is written down as one.
CODE_SHAS_UNKNOWN = "unknown"
_FROM_05 = object()
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def code_shas_problems(value):
    """What is wrong with a `code_shas` value of the shape the Editor writes
    (`videos[].code_shas`, CF-0399): `None` (runlog was unreachable), or a
    mapping `repo label -> {"commit": <40 hex>, "dirty": bool|None}` or `None`
    (a non-git directory). Empty list = the shape holds."""
    if value is None:
        return []
    if not isinstance(value, dict):
        return [f"code_shas is {type(value).__name__}, not a mapping or null"]
    out = []
    for label, st in value.items():
        if not isinstance(label, str) or not label:
            out.append(f"code_shas label {label!r} is not a repo name")
        if st is None:
            continue
        if not isinstance(st, dict):
            out.append(f"code_shas[{label}] is {type(st).__name__}, not {{commit, dirty}} or null")
            continue
        if not _SHA_RE.match(str(st.get("commit") or "")):
            out.append(f"code_shas[{label}].commit {st.get('commit')!r} is not a 40-hex SHA")
        if "dirty" not in st or st.get("dirty") not in (True, False, None):
            out.append(f"code_shas[{label}].dirty {st.get('dirty')!r} is not true/false/null")
    return out


def batch_pool(root=None):
    """Where `pipeline/<channel>/<batch>` lives: under `root` when one is named,
    else `$RUNLOG_POOL` (the variable gate_price.pool_root reads - a checkout
    that holds the batches, or the frozen corpus the root tests point it at,
    CF-0503), else the repository's own `pipeline/`."""
    if root is None and os.environ.get("RUNLOG_POOL"):
        return Path(os.environ["RUNLOG_POOL"])
    return Path(root or ROOT) / "pipeline"


def _batch_dirs(channel, batch_id, batch_dir=None, channel_as_given=None, root=None):
    base = Path(root or ROOT)
    if batch_dir:
        b = Path(batch_dir)
        yield b if b.is_absolute() else base / b
        return
    seen = set()
    # A batch written under a channel's former name sits in that name's directory
    # (CF-0197): look under both, the current id first.
    for ch in (channel, channel_as_given):
        if ch and ch not in seen:
            seen.add(ch)
            yield batch_pool(root) / ch / batch_id


def code_shas_from_05(channel, batch_id, slug, batch_dir=None, channel_as_given=None,
                      root=None):
    """`(code_shas, source)` for one video, read from its batch's
    `05-video-editor.json`. `code_shas` is the Editor's value copied as it is
    (a mapping, or `None` when the Editor could not reach runlog), or
    `CODE_SHAS_UNKNOWN` when the file, the video or the key is not there -
    `source` then says which, so an unknown is never mistaken for a clean
    build. A video is matched by the stem of its `output_path` (the reading of
    `runlog.editor_videos`), never by its position in the list."""
    tried = []
    for bdir in _batch_dirs(channel, batch_id, batch_dir, channel_as_given, root):
        p = bdir / VIDEO_EDITOR_FILE
        try:
            rel = str(p.relative_to(Path(root or ROOT)))
        except ValueError:
            rel = str(p)
        if not p.is_file():
            tried.append(rel)
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            return CODE_SHAS_UNKNOWN, f"{rel}: unreadable ({e})"
        for v in (data.get("videos") or []) if isinstance(data, dict) else []:
            if not isinstance(v, dict):
                continue
            vslug = Path(v.get("output_path") or "").stem or v.get("script_id")
            if vslug != slug:
                continue
            if "code_shas" not in v:
                return CODE_SHAS_UNKNOWN, (f"{rel}: the video carries no code_shas "
                                           f"(built before CF-0399)")
            return v["code_shas"], rel
        return CODE_SHAS_UNKNOWN, f"{rel}: no video named {slug}"
    return CODE_SHAS_UNKNOWN, f"no {VIDEO_EDITOR_FILE} at {' or '.join(tried) or '(nowhere)'}"


def _publish_profile():
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    import publish_profile                                  # noqa: PLC0415
    return publish_profile


def topic_from_batch(channel, batch_id, slug, batch_dir=None, channel_as_given=None,
                     root=None):
    """CF-0544: `(topic_id, script_id, source)` of one video, read from its
    batch the way `code_shas` is: the Editor's `videos[]` entry named by the
    stem of its `output_path` gives the `script_id`, and the script of
    `03-content-researcher.json` carrying that id gives the `topic_id`
    (`publish_profile.find_script`, which falls back to `title_ref.name`).
    `topic_id` is None when nothing lands, and `source` then says why - the
    hold of CF-0318 is keyed by topic, and a row filed with a null topic was
    a hold that silently held nothing (harbourlights 0701Z, 05.10)."""
    pp = _publish_profile()
    tried = []
    for bdir in _batch_dirs(channel, batch_id, batch_dir, channel_as_given, root):
        try:
            rel = str(bdir.relative_to(Path(root or ROOT)))
        except ValueError:
            rel = str(bdir)
        if not bdir.is_dir():
            tried.append(rel)
            continue
        script, how = pp.find_script(bdir, slug)
        if script is None:
            return None, None, f"{rel}: {how}"
        sid = script.get("script_id")
        if not script.get("topic_id"):
            return None, sid, f"{rel}: the script {sid} of 03 carries no topic_id"
        return script["topic_id"], sid, f"{rel}/03 ({how})"
    return None, None, f"no batch at {' or '.join(tried) or '(nowhere)'}"


# --------------------------------------------------------------------------
# the channel a row or a hold was written under (CF-0197)
# --------------------------------------------------------------------------

_CHANNEL_IDS = []


def _channel_ids():
    """shared/channel_ids.py, loaded by path (CF-0231 / tests/
    test_module_path_loading.py: `shared` is a guarded directory and a bare
    `import channel_ids` would only work by accident of how we were reached).

    Loaded once - `resolve_channel` is called per row and per hold, and the
    module keeps its own mtime-keyed cache of the mapping, so re-executing it
    each time would throw that away."""
    if _CHANNEL_IDS:
        return _CHANNEL_IDS[0]
    path = Path(__file__).resolve().parents[1] / "channel_ids.py"
    try:
        spec = importlib.util.spec_from_file_location("channel_ids_for_acceptance", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception:                                   # noqa: BLE001
        mod = None
    _CHANNEL_IDS.append(mod)
    return mod


def resolve_channel(channel, root=None):
    """The channel's id *today*, from a name that may be one it used to carry.

    Every `channel` string this module meets is a frozen record: the field a
    batch wrote into its artifacts, the field a row of this log or of the
    CF-0318 hold registry froze on the day it was answered, the name an
    operator types. A channel can be renamed (CF-0180: `legacy-film` ->
    `example-film`) and none of those strings are rewritten when it is - they
    are dated records and are correct under the name they happened under. So
    they are resolved *at the door*, in the same statement that reads them,
    and never held in a local and looked up later.

    A name nobody renamed comes back unchanged, and so does everything when
    the mapping cannot be loaded at all: this module answers about verdicts,
    and a missing `channels/` is not its error to raise."""
    cid = _channel_ids()
    if cid is None or not channel:
        return channel
    try:
        return cid.resolve_channel(channel, root=Path(root or ROOT))
    except Exception:                                   # noqa: BLE001
        return channel


# --------------------------------------------------------------------------
# the name of the video is the key
# --------------------------------------------------------------------------

_NOT_WORD = re.compile(r"[^a-z0-9]+")


def _norm(text):
    return _NOT_WORD.sub(" ", str(text).lower()).strip()


def names_video(answer, slug):
    """True when `answer` names this video - the one thing that ties a verdict
    to a file. The name is matched the way a person writes it: any separators
    (`paper-dragon`, `paper dragon`, `Paper_Dragon`), the file name with its
    suffix, any case, and inside a sentence in any language."""
    a, s = _norm(answer), _norm(slug)
    if not s:
        return False
    if f" {s} " in f" {a} ":
        return True
    return s.replace(" ", "") in a.replace(" ", "")


def entry_id(channel, batch_id, slug):
    """The key of one video's row: `<channel>/<batch>/<slug>`, with the channel
    under the name it carries *today*.

    The key has to be one string for one video, and a rename must not make a
    second one - so the resolved id goes into the key and the string the row
    was written from is kept beside it (`channel_as_given`). Nothing about the
    rows already on the record changes: their keys were written under ids that
    are current, and `row_key()` resolves both sides of every comparison, so a
    row frozen under a former name is found by the current one without the file
    being rewritten."""
    return f"{resolve_channel(channel)}/{batch_id}/{slug}"


def row_key(row):
    """One row's key as it reads today.

    The `entry_id` string stored on a row is a dated record like any other: a
    row written before a rename carries the old id inside it and the file is not
    rewritten (CF-0197). So the key a row *answers to* is rebuilt from its
    fields with the channel resolved, and the stored string is kept as a second
    name the row also answers to - never overwritten, never lost."""
    stored = str(row.get("entry_id") or "")
    channel = resolve_channel(row.get("channel"))
    if not (channel and row.get("batch_id") and row.get("slug")):
        return stored
    return entry_id(channel, row.get("batch_id"), row.get("slug"))


def row_keys(row):
    """Every key this row answers to: the one it reads as today, and the one
    frozen into it when it was written."""
    out = [row_key(row)]
    stored = str(row.get("entry_id") or "")
    if stored and stored not in out:
        out.append(stored)
    return [k for k in out if k]


def stale_channel_keys(rows=None, path=None):
    """The rows whose stored `entry_id` was frozen under a name the channel no
    longer carries - i.e. what a migration of this file *would* change.

    It is reported and never applied. A stale key is not a defect here: the row
    answers to both its stored key and its resolved one (`row_keys`), so the
    record is read correctly without being touched, and the alternative - a
    rewrite of `entry_id` on rows the user answered weeks ago - is a silent edit
    of history to fix a lookup that is not broken. This function exists so the
    claim "nothing needs migrating" is a check rather than a belief, and so that
    the day a rename does reach these rows, the operator sees exactly which ones
    and decides."""
    out = []
    for r in (entries(path=path) if rows is None else rows):
        stored, now = str(r.get("entry_id") or ""), row_key(r)
        if stored and now and stored != now:
            out.append({"entry_id": stored, "reads_as": now, "slug": r.get("slug"),
                        "answered_at": r.get("answered_at")})
    return out


def parse_key(key, parts=3):
    """`<channel>/<batch>/<slug>` (or `<channel>/<batch>`) off the command line.

    The channel is resolved here too: an operator typing the name a channel used
    to have is the third door a former id comes in through (CF-0197), beside a
    frozen batch field and a directory name on disk."""
    bits = [b for b in str(key).split("/") if b]
    if len(bits) != parts:
        want = "CHANNEL/BATCH/SLUG" if parts == 3 else "CHANNEL/BATCH"
        raise AcceptanceError(f"{key!r} is not {want}", code="key_malformed", key=key,
                              want="канал/батч/ролик" if parts == 3 else "канал/батч")
    return (resolve_channel(bits[0]),) + tuple(bits[1:])


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today():
    return datetime.now(timezone.utc).date().isoformat()


# --------------------------------------------------------------------------
# the record on disk
# --------------------------------------------------------------------------

def read_log(path=None):
    """The record, or an empty one when the file is not there.

    An absent record means nothing was accepted - which is the safe reading:
    `state()` then says the video is not publishable, exactly as it should for a
    video nobody was asked about. A record that does not parse is an error and
    is never read as an empty one."""
    p = Path(path or LOG)
    if not p.exists():
        return {"note": NOTE, "task": "CF-0328", "acceptances": []}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise AcceptanceError(f"{p}: the acceptance record does not parse ({e}) - "
                              f"no verdict can be read from it",
                              code="record_unreadable") from e
    if not isinstance(doc, dict) or not isinstance(doc.get("acceptances"), list):
        raise AcceptanceError(f"{p}: no `acceptances` list - this is not an acceptance record",
                              code="record_not_a_log")
    return doc


def entries(log=None, path=None, pending=None):
    """The rows of the record. Read from a file (`log` not given), the verdicts
    still waiting in the queue of CF-0675 (`pending_path`) come with them, each
    marked `pending: true` and standing in place of the row it will replace - the
    user sees his verdict at once, while a batch keeps it out of git. A `log`
    document (what a writer reads, then hands to `write_log`) gives the record's
    own rows only. `pending` says it explicitly either way."""
    rows = list((log if log is not None else read_log(path)).get("acceptances") or [])
    if pending is None:
        pending = log is None
    if pending:
        rows = with_pending(rows, pending_path(path))
    return rows


def find(channel, batch_id, slug, rows=None, path=None):
    eid = entry_id(channel, batch_id, slug)
    for r in (entries(path=path) if rows is None else rows):
        if eid in row_keys(r):
            return r
    return None


def _sort_key(row):
    # The channel is resolved before it is sorted on, or a renamed channel's
    # rows fall into two blocks of the listing under two names (CF-0197).
    return (str(row.get("answered_at") or ""),
            str(resolve_channel(row.get("channel")) or ""),
            str(row.get("batch_id") or ""), str(row.get("slug") or ""))


def log_text(rows, note=None):
    """The record's text as `write_log` writes it. A row still `pending` (CF-0675:
    shown from the queue, not yet on the record) is never written - it goes in
    through `commit_pending`, by `record`, or not at all; the row it stands in for
    (`on_record`) is written in its place."""
    kept = []
    for r in rows:
        if r.get("pending"):
            r = r.get("on_record")
            if not r:
                continue
        kept.append(r)
    doc = {"note": note or NOTE, "task": "CF-0328", "acceptances": sorted(kept, key=_sort_key)}
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


def write_log(rows, path=None, note=None):
    """Write the record. Chronological by the day the user answered - the order
    a person reads it in - and never sorted by anything positional."""
    p = Path(path or LOG)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(log_text(rows, note), encoding="utf-8")
    os.replace(tmp, p)
    return p


# --------------------------------------------------------------------------
# showing the videos: every file by its name, nothing numbered
# --------------------------------------------------------------------------

def score_lines(channel, batch_id, slugs, batch_dir=None, root=None):
    """CF-0434: {slug: score line} of the videos shown, read from the batch's
    artifacts by shared/runlog/scores.py (after the judge where it ran, else
    after QC). A slug the batch has no record of is left out; no batch on disk
    - `{}`. Never raises: the question is asked whether or not it can be
    scored."""
    try:
        here = str(Path(__file__).resolve().parent)
        if here not in sys.path:
            sys.path.insert(0, here)
        import scores                                       # noqa: PLC0415
        for bdir in _batch_dirs(channel, batch_id, batch_dir, root=root):
            if (bdir / VIDEO_EDITOR_FILE).is_file():
                out = {}
                for s in slugs:
                    line = scores.line_of(bdir, s)
                    if line:
                        out[s] = line
                return out
    except Exception:                                       # noqa: BLE001
        pass
    return {}


def question(channel, batch_id, slugs, note=None, batch_dir=None, root=None):
    """The lines shown to the user beside the files.

    Every file is named, in backticks, and the list is not numbered - not as
    `1.`, not as `(2)`, not as "the first one". A numbered list is what made the
    2026-09-22 misattribution possible: the answer came back as positions and
    the positions had shifted when the heavy files went over separately.

    CF-0434: beside each name, the video's score line - tier, points and what
    was charged, `B · 74 — −9 похожесть (3 блока), ...` - read from its batch
    (`batch_dir`, else `pipeline/<channel>/<batch>`). Shown, never decided on
    (Q14): every video here is still the user's to accept or refuse."""
    slugs = list(slugs)
    if not slugs:
        raise AcceptanceError("no video to show", code="nothing_to_show")
    lines = [f"Приёмка: {channel}/{batch_id}. По каждому ролику нужен вердикт — "
             f"принят или отклонён, **с именем ролика** в ответе; если отклонён — "
             f"причина одной фразой. Номер в списке вердиктом не считается (CF-0328)."]
    scored = score_lines(channel, batch_id, slugs, batch_dir=batch_dir, root=root)
    for s in slugs:
        line = f" — {scored[s]}" if s in scored else ""
        lines.append(f"- `{s}{VIDEO_SUFFIX}`{line} — принят или отклонён?")
    if note:
        lines.append(str(note))
    return lines


NUMBERED = re.compile(r"^\s*[-*]?\s*[(\[]?\d+[.)\]]")


def is_numbered(lines):
    """True when any line of a listing carries a position number. The guard
    under `question()`."""
    return any(NUMBERED.match(l) for l in lines)


# --------------------------------------------------------------------------
# recording a verdict
# --------------------------------------------------------------------------

def record(channel, batch_id, slug, verdict, answer, rows=None, reason=None,
           reason_code=None, checkable_by=None, covered_by=None, topic_id=None,
           batch_artifact=None, answered_at=None, shown=None, note=None,
           verbatim=True, answer_source=None, amend=None, recorded_at=None,
           code_shas=_FROM_05, batch_dir=None, strict_topic=False):
    """Put one verdict on the record and give the row back. `rows` is the list
    from `entries()` and is mutated in place; the caller writes it.

    Refused - with `AcceptanceError`, never a silent skip:

    * an answer that does not name this video (including an answer that is a
      position in a list): the verdict would have nothing tying it to the file,
      which is precisely what happened on 2026-09-22;
    * a rejection with no reason, or with no `reason_code` for the dictionary:
      the reasons for refusal are the only data the factory has on the axis the
      DoD does not measure, and a rejection filed without one loses it;
    * a second verdict on a video that already has one, unless `amend` says in
      words why the user changed it - the old verdict then moves into
      `history` rather than disappearing.

    `verbatim=False` marks a row whose `answer` is not a quotation but a
    reconstruction from a written record (the 2026-09-22/24 backfill), with
    `answer_source` naming where it was read from. The name-of-the-video rule
    holds either way.

    The channel is resolved at the door (CF-0197): `channel` and `entry_id` on
    the row carry the id the channel has today, and the string the caller
    actually passed - a batch field frozen before a rename, an operator typing
    the old name - is kept beside them as `channel_as_given`, so the row still
    says which name this verdict happened under.

    CF-0399: the row carries `code_shas`, the commits the video was built by,
    copied from the video's own record in `05-video-editor.json` (looked up
    under `batch_dir`, else `batch_artifact`, else `pipeline/<channel>/<batch>`)
    - so a verdict can be read back to the code it judged. When that record has
    no such set the row says `"unknown"` and `code_shas_source` says why; it is
    never left out and never guessed. A caller may pass `code_shas` itself.

    CF-0544: `topic_id`, when the caller does not pass one, is read from the
    same batch (`topic_from_batch`), and `topic_id_source` says where from. A
    hold of CF-0318 is keyed by topic, so `strict_topic` (what `runlog
    acceptance --record` passes) refuses a row whose topic cannot be found,
    and a given topic the batch contradicts - never a silent null."""
    rows = entries() if rows is None else rows
    channel_as_given = channel
    channel = resolve_channel(channel)
    if verdict not in VERDICTS:
        raise AcceptanceError(f"{slug}: verdict must be one of {VERDICTS}, got {verdict!r}",
                              code="verdict_unknown", slug=slug, verdict=verdict)
    if not SLUG_RE.match(str(slug or "")):
        raise AcceptanceError(f"{slug!r} is not a video name (lowercase, digits, dashes) - "
                              f"and a video is recorded under its name, never a number",
                              code="not_a_video_name", slug=slug)
    if shown is not None and slug not in list(shown):
        raise AcceptanceError(f"{slug}: not among the videos shown "
                              f"({', '.join(shown) or 'none'}) - a verdict about a video "
                              f"the user was not shown is not his verdict",
                              code="video_not_shown", slug=slug)
    answer = str(answer or "").strip()
    if not answer:
        raise AcceptanceError(f"{slug}: no answer behind the verdict. The verdict is copied "
                              f"from what the user said; the machine does not have one of "
                              f"its own", code="answer_missing", slug=slug)
    if not names_video(answer, slug):
        why = (f"{slug}: the answer {answer!r} does not name this video, so nothing ties the "
               f"verdict to the file (the defect of 2026-09-22). Record it under the name "
               f"the user actually said")
        code = "answer_without_name"
        if re.search(r"(?<!\w)\d+(?!\w)", answer):
            # The answer points at a place in a list. That is the shape the
            # three misfiled verdicts of 2026-09-22 arrived in, and the order of
            # the list had shifted under it.
            why += (" - and a position in a list is not a name: ask again, with the video "
                    "named")
            code = "answer_is_position"
        raise AcceptanceError(why, code=code, slug=slug)
    reason = str(reason or "").strip()
    if verdict == REJECTED:
        if not reason:
            raise AcceptanceError(f"{slug}: a rejection with no reason. The reason in one "
                                  f"phrase is the point of the record",
                                  code="rejection_without_reason", slug=slug)
        if not CODE_RE.match(str(reason_code or "")):
            raise AcceptanceError(f"{slug}: a rejection needs a `reason_code` "
                                  f"([a-z][a-z0-9_]*) - it is the dictionary key the "
                                  f"repeatability rule of CF-0319 counts, got {reason_code!r}",
                                  code="rejection_without_code", slug=slug)
    else:
        if reason_code:
            raise AcceptanceError(f"{slug}: an acceptance carries no `reason_code` - the "
                                  f"dictionary counts refusals; put a remark in `note`",
                                  code="acceptance_with_code", slug=slug)
        if checkable_by:
            raise AcceptanceError(f"{slug}: `checkable_by` belongs to a rejection - it names "
                                  f"the machine check that could have caught the defect",
                                  code="acceptance_with_check", slug=slug)
    if checkable_by is not None and checkable_by not in CHECKS:
        raise AcceptanceError(f"{slug}: checkable_by must be one of {CHECKS} or None, "
                              f"got {checkable_by!r}", code="check_unknown", slug=slug,
                              check=checkable_by)
    if code_shas is _FROM_05:
        code_shas, code_shas_source = code_shas_from_05(
            channel, batch_id, slug, batch_dir=batch_dir or batch_artifact,
            channel_as_given=channel_as_given)
    else:
        code_shas_source = "given by the caller"
    if code_shas != CODE_SHAS_UNKNOWN:
        bad = code_shas_problems(code_shas)
        if bad:
            raise AcceptanceError(f"{slug}: {'; '.join(bad)}", code="code_shas_broken",
                                  slug=slug)
    found, _sid, found_from = topic_from_batch(
        channel, batch_id, slug, batch_dir=batch_dir or batch_artifact,
        channel_as_given=channel_as_given)
    if topic_id:
        if strict_topic and found and found != topic_id:
            raise AcceptanceError(
                f"{slug}: --topic {topic_id} but the batch says {found} ({found_from}) - "
                f"a hold keyed by the wrong topic holds nothing (CF-0544)",
                code="topic_mismatch", slug=slug, topic=topic_id, found=found)
        topic_source = "given by the caller"
    elif found:
        topic_id, topic_source = found, found_from
    elif strict_topic:
        raise AcceptanceError(
            f"{slug}: no topic_id - {found_from}. A row without its topic is not held by "
            f"a CF-0318 hold (harbourlights 0701Z, CF-0544): point --batch-dir at the batch or "
            f"pass --topic", code="topic_not_found", slug=slug)
    else:
        topic_source = f"unknown: {found_from}"
    profile = _profile(channel, batch_id, slug, topic_id, batch_dir or batch_artifact,
                       channel_as_given)
    eid = entry_id(channel, batch_id, slug)
    prev = find(channel, batch_id, slug, rows=rows)
    if prev is not None and not amend:
        raise AcceptanceError(
            f"{eid} already carries a verdict ({prev.get('verdict')}, "
            f"{prev.get('answered_at')}). A verdict is replaced only by the user changing "
            f"it: pass `amend` saying in words what he said",
            code="verdict_already_given", slug=slug, batch=batch_id)
    row = {
        "entry_id": eid,
        "slug": slug,
        "video": f"{slug}{VIDEO_SUFFIX}",
        "channel": channel,
        # The name this verdict happened under, when it is not the current one.
        # A dated record beside the key, never instead of it (CF-0197).
        "channel_as_given": channel_as_given if channel_as_given != channel else None,
        "batch_id": batch_id,
        "topic_id": topic_id,
        "topic_id_source": topic_source,
        "verdict": verdict,
        "reason_code": reason_code or None,
        "reason": reason or None,
        "checkable_by": checkable_by,
        "covered_by": covered_by,
        "answered_at": answered_at or _today(),
        "answer": answer,
        "answer_verbatim": bool(verbatim),
        "answer_source": answer_source,
        # CF-0463: where the file lies is set by whoever puts it there -
        # `place()` and `runlog publish assign` - never by the verdict. An
        # accepted rebuild of a video that went out as another version never
        # lies in publish/ (01.10: six such rows carried a path by hand-null).
        # An amendment keeps the path of the row it replaces while the video
        # stays accepted.
        "publish_path": ((prev or {}).get("publish_path")
                         if verdict == ACCEPTED else None),
        "batch_artifact": batch_artifact,
        # CF-0399: the code this verdict judged, or "unknown" - never absent.
        "code_shas": code_shas,
        "code_shas_source": code_shas_source,
        # CF-0440: fact kind and source, pattern, hook opener, score - read from
        # the same batch by shared/runlog/publish_profile.py, never typed.
        "profile": profile,
        "note": note,
        "task": "CF-0328",
        "recorded_at": recorded_at or _now(),
        "history": [],
    }
    if prev is not None:
        hist = list(prev.get("history") or [])
        old = {k: prev.get(k) for k in ("verdict", "reason_code", "reason", "checkable_by",
                                       "covered_by", "answered_at", "answer", "note")}
        old["superseded_at"] = row["recorded_at"]
        old["superseded_because"] = str(amend)
        hist.append(old)
        row["history"] = hist
        row["amended_because"] = str(amend)
        rows[rows.index(prev)] = row
    else:
        rows.append(row)
    return row


def _profile(channel, batch_id, slug, topic_id, batch_dir, channel_as_given):
    """CF-0440: the video's profile (`publish_profile.profile_of`), or a
    profile saying why there is none - never a failed verdict because of it."""
    try:
        here = str(Path(__file__).resolve().parent)
        if here not in sys.path:
            sys.path.insert(0, here)
        import publish_profile                              # noqa: PLC0415
        bdir = next((b for b in _batch_dirs(channel, batch_id, batch_dir, channel_as_given)
                     if b.is_dir()), None)
        return publish_profile.profile_of(bdir, slug, topic_id)
    except Exception as e:                                  # noqa: BLE001
        return {"task": "CF-0440", "problem": f"profile unreadable: {e}"}


# --------------------------------------------------------------------------
# the dictionary of reasons for refusal
# --------------------------------------------------------------------------

def rejections(rows=None, path=None):
    """Every rejection verdict on the record - the standing ones and the ones a
    later verdict superseded. A refusal the user took back still happened, and
    its reason is still data on the axis nothing else measures."""
    out = []
    for r in (entries(path=path) if rows is None else rows):
        seen = [(r, True)] + [(h, False) for h in (r.get("history") or [])]
        for src, standing in seen:
            if src.get("verdict") != REJECTED:
                continue
            out.append({"entry_id": row_key(r), "slug": r.get("slug"),
                        "channel": resolve_channel(r.get("channel")),
                        "batch_id": r.get("batch_id"),
                        "reason_code": src.get("reason_code"), "reason": src.get("reason"),
                        "checkable_by": src.get("checkable_by"),
                        "covered_by": src.get("covered_by"),
                        "answered_at": src.get("answered_at"), "standing": standing})
    return out


def reasons(rows=None, path=None):
    """`{reason_code: {count, videos, batches, phrases, checkable_by, covered_by,
    repeats}}`, the most-named code first. This is the answer to "which reasons
    for refusal repeat" - by code, with the videos it was named on, so that a
    count of two can always be read back to the two videos behind it."""
    d = {}
    for rj in rejections(rows=rows, path=path):
        code = rj.get("reason_code") or "unnamed"
        e = d.setdefault(code, {"reason_code": code, "count": 0, "videos": [], "batches": [],
                                "phrases": [], "checkable_by": None, "covered_by": None,
                                "repeats": False})
        e["count"] += 1
        for key, val in (("videos", rj.get("slug")), ("batches", rj.get("batch_id")),
                         ("phrases", rj.get("reason"))):
            if val and val not in e[key]:
                e[key].append(val)
        for key in ("checkable_by", "covered_by"):
            if rj.get(key) and not e[key]:
                e[key] = rj[key]
    for e in d.values():
        # Repeatability is counted over *videos*, not over rows: the same video
        # refused twice for the same reason is one defect that was not fixed,
        # and the second refusal of it is not independent evidence.
        e["repeats"] = len(e["videos"]) >= REPEAT
    return dict(sorted(d.items(), key=lambda kv: (-kv[1]["count"], kv[0])))


def candidates(rows=None, path=None):
    """The repeatability rule of CF-0319 over the dictionary above: what a
    repeating reason for refusal becomes. Three kinds, and only the first one is
    a new machine check - see the module docstring."""
    out = []
    for code, e in reasons(rows=rows, path=path).items():
        if not e["repeats"]:
            continue
        row = {"reason_code": code, "count": e["count"], "videos": list(e["videos"]),
               "batches": list(e["batches"]), "check": e["checkable_by"],
               "covered_by": e["covered_by"], "phrases": list(e["phrases"])}
        if e["covered_by"]:
            row["kind"] = KIND_REGRESSION
            row["why"] = (f"named on {len(e['videos'])} videos and {e['covered_by']} already "
                          f"claims this reason: the check is letting it through, so the task "
                          f"is about the check and not about the defect")
        elif e["checkable_by"]:
            row["kind"] = KIND_CANDIDATE
            row["why"] = (f"named on {len(e['videos'])} videos and a machine can read it: "
                          f"candidate for {e['checkable_by']} (CF-0319 repeatability, "
                          f"threshold {REPEAT})")
        else:
            row["kind"] = KIND_NOT_MACHINE
            row["why"] = ("repeats, and nothing mechanical reads it: no `checkable_by`. "
                          "Kept and counted, never turned into a gate - \"not interesting\" "
                          "is not a DoD item (decision of 2026-09-11)")
        out.append(row)
    return out


# --------------------------------------------------------------------------
# the acceptance, the hold, and the publish/ directory
# --------------------------------------------------------------------------

def holds(path=None):
    """The CF-0318 registry. Read-only from here; nothing in this module writes
    a hold or a signature."""
    p = Path(path or HOLDS)
    if not p.exists():
        return []
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise AcceptanceError(f"{p}: the hold registry does not parse ({e})",
                              code="holds_unreadable") from e
    return [h for h in (doc.get("holds") or []) if isinstance(h, dict)]


def held(channel, batch_id, topic_id, path=None, script_id=None):
    """The standing publication hold on this video's topic, or None. A hold that
    was resolved or signed holds nothing; an unsigned `review` holds the upload
    no matter what the user's acceptance says.

    CF-0544: with no `topic_id`, a hold is matched by its `script_id` instead -
    a row filed without its topic is still the video the hold names."""
    if not topic_id and not script_id:
        return None
    channel = resolve_channel(channel)
    for h in holds(path):
        # Both sides resolved: the hold registry froze its `channel` on the day
        # the hold was signed, and a hold missed because the channel has been
        # renamed since is an upload that goes out unsigned (CF-0197/CF-0318).
        if not (resolve_channel(h.get("channel")) == channel
                and h.get("batch_id") == batch_id and h.get("verdict") == "review"
                and not h.get("resolved_at") and not h.get("signature")):
            continue
        if topic_id and h.get("topic_id") == topic_id:
            return h
        if not topic_id and script_id and h.get("script_id") == script_id:
            return h
    return None


def row_topic(row, root=None):
    """CF-0544: `(topic_id, script_id, source)` of an acceptance row - its own
    `topic_id`, else the one its batch gives (`topic_from_batch`, under
    `batch_artifact` or `pipeline/<channel>/<batch>`). `script_id` is the
    row's profile's, else the batch's."""
    sid = ((row.get("profile") or {}).get("script_id")
           if isinstance(row.get("profile"), dict) else None) or row.get("script_id")
    if row.get("topic_id"):
        return row["topic_id"], sid, "row"
    t, bsid, src = topic_from_batch(resolve_channel(row.get("channel")), row.get("batch_id"),
                                    row.get("slug"), batch_dir=row.get("batch_artifact"),
                                    channel_as_given=row.get("channel_as_given")
                                    or row.get("channel"), root=root)
    return t, sid or bsid, src


def held_row(row, path=None, root=None):
    """The standing hold on the video of this acceptance row, or None. A row
    without `topic_id` (13 of 24 accepted rows on 05.10) is matched by the
    topic its batch gives, then by `script_id`; a row that names neither, on a
    batch with an open hold, is held by that hold - unknown is not clear
    (CF-0544). The hold returned says how it was matched - on every path
    (CF-0709: the live monitor met a topic-less row whose batch is on disk, so
    the batch's topic matched it, and the hold came back naming nothing)."""
    if not row:
        return None
    channel = resolve_channel(row.get("channel"))
    batch_id = row.get("batch_id")
    t, sid, src = row_topic(row, root=root)
    h = held(channel, batch_id, t, path=path, script_id=sid)
    if h is not None:
        if t:
            how = ("topic_id: the row's own" if src == "row"
                   else f"topic_id: the batch's, the row names none ({src})")
        else:
            how = "script_id: the row names no topic_id (CF-0544)"
        return dict(h, matched_by=how)
    if t or sid:
        return None
    for h in holds(path):
        if (resolve_channel(h.get("channel")) == channel and h.get("batch_id") == batch_id
                and h.get("verdict") == "review" and not h.get("resolved_at")
                and not h.get("signature")):
            return dict(h, matched_by="batch: the row names no topic_id and no script_id "
                                      "(CF-0544)")
    return None


def state(channel, batch_id, slug, rows=None, path=None, holds_path=None):
    """What the record says about one video: the user's verdict and, separately,
    the publication hold. Two facts, two fields, never merged.

    `publishable` is `accepted and not held` - and it means only that nothing on
    the record stands in the way. It is not a permission to upload: the button
    is pressed by a human (CF-0018), and nothing in this module uploads
    anything."""
    row = find(channel, batch_id, slug, rows=rows, path=path)
    h = held_row(row, path=holds_path)
    accepted = bool(row and row.get("verdict") == ACCEPTED)
    return {"entry_id": entry_id(channel, batch_id, slug),
            "slug": slug, "recorded": row is not None,
            "verdict": (row or {}).get("verdict"),
            "accepted": accepted,
            "reason": (row or {}).get("reason"),
            "answered_at": (row or {}).get("answered_at"),
            "held": h is not None,
            "hold_id": (h or {}).get("hold_id"),
            "hold_reason": (h or {}).get("reason_code"),
            "publishable": accepted and h is None,
            # CF-0675: the verdict is the user's, but it waits in the queue for
            # the batch to end before it is committed to the record.
            "pending": bool((row or {}).get("pending")),
            "queued_at": (row or {}).get("queued_at"),
            "upload": "a human presses the button (CF-0018)"}


def is_accepted(channel, batch_id, slug, **kw):
    """`(accepted, reason)` for a caller that only wants the verdict. A video
    with no row is not accepted, and the reason says so."""
    st = state(channel, batch_id, slug, **kw)
    if not st["recorded"]:
        return False, "no acceptance recorded - the user was never asked about this video"
    if st["accepted"]:
        return True, st["reason"] or "accepted by the user"
    return False, st["reason"] or "rejected by the user"


def publish_slugs(publish_dir=None, channel=None):
    """The video names `publish/` carries - the rendered files and the metadata
    notes, in every `<channel>/<day>/` and `<channel>/_queue/` folder (one
    channel's, when `channel` is given) and in the flat root of before CF-0475.
    `.mp4` is gitignored, so in a fresh checkout the notes are all there is,
    and that is enough for the check below."""
    return publish_layout.slugs(Path(publish_dir or PUBLISH), channel)


def place(row, src, publish_dir=None, day=None, channel=None, stem=None):
    """Copy an accepted video into `publish/`. Item 4 of CF-0328, and the one
    place in the module that touches a video file.

    CF-0475: into `publish/<channel>/_queue/` while the video has no slot, or
    into `publish/<channel>/<YYYY-MM-DD>/` when the caller knows it - `day` is
    that day or the slot itself (an aware datetime, read as a Moscow day). The
    channel is the row's (`publish_layout.channel_of_row`: a former name
    resolves, a `rebuilds` row goes to the one channel on file) unless
    `channel` is given. The row's `publish_path` is set to where the file
    went; the caller writes the log.

    A video the user rejected is refused here, with the reason off its row: that
    is the whole mechanism keeping a refused render out of the directory a human
    uploads from. A video with no row at all is refused too - `publish/` is not
    where a verdict comes from.

    Copying is not publishing (CF-0018): nothing is uploaded, no form is filled,
    and the file being here does not make it published."""
    if not isinstance(row, dict) or not row.get("entry_id"):
        raise AcceptanceError("place() takes a row of the acceptance record - a video with "
                              "no recorded verdict is not placed into publish/",
                              code="place_without_row")
    if row.get("verdict") != ACCEPTED:
        raise AcceptanceError(
            f"{row.get('slug')}: {row.get('verdict')} - a video the user did not accept does "
            f"not go into publish/. The reason stays on the record: "
            f"{row.get('reason') or '(none)'}", code="place_not_accepted",
            slug=row.get("slug"), reason=row.get("reason") or "не названа")
    src = Path(src)
    if not src.is_file():
        raise AcceptanceError(f"{row.get('slug')}: no rendered file at {src}",
                              code="render_missing", slug=row.get("slug"))
    pub = Path(publish_dir or PUBLISH)
    ch = channel or publish_layout.channel_of_row(row, root=pub.parent)
    if not ch:
        raise AcceptanceError(f"{row.get('slug')}: the channel of {row.get('entry_id')} cannot "
                              f"be read - pass channel= (publish/<channel>/..., CF-0475)",
                              code="channel_unknown", slug=row.get("slug"))
    bucket = publish_layout.QUEUE if day is None else publish_layout.release_day(day)
    name = stem or row["slug"]
    try:
        dst = publish_layout.bucket_dir(pub, ch, bucket) / f"{name}{VIDEO_SUFFIX}"
    except publish_layout.LayoutError as e:
        raise AcceptanceError(f"{row.get('slug')}: {e}", code="publish_layout_refused",
                              slug=row.get("slug"), why=e) from e
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    row["publish_path"] = publish_layout.rel(ch, bucket, name)
    return dst


# --------------------------------------------------------------------------
# CF-0738: an accepted video with no slot always lies in its channel's _queue/
# --------------------------------------------------------------------------
#
# The defect, 2026-10-13. Science `sophie-adenot` (rebuild 0524Z) was accepted
# by the user in Telegram and recorded through the center
# (`record_and_commit`) - and found nowhere: `publish_path: null`, no
# `publish/example-science/` at all, `publish_queue.waiting` empty. Nothing
# called `place()` after a verdict: the docs said "the video is placed by
# acceptance.place()", but that was a step an operator did by hand in a
# session (every example-film video in publish/ got there so), and a verdict
# given from the center or Telegram had no operator behind it. Not because it
# was a rebuild and not because the channel had no folder (`place()` makes
# it) - nobody called it.
#
# Now every verdict `accepted` goes through `queue_accepted` in the same step
# that records it (`record_and_commit`, `commit_pending`, `--record --write`):
# the render is copied into `publish/<channel>/_queue/` and `publish_path`
# says so, in the same commit as the verdict. Idempotent: a row that already
# has a `publish_path` is left alone, a file already in the channel's folder
# for this batch is adopted, never copied twice. Never refused for it: a
# verdict is the user's and is kept even when the file cannot be put there -
# the answer says why (`queued`), and `repair_queue` finds the row later.
#
# What is NOT queued, by design (CF-0463): an accepted version of a video
# whose other version (same channel, same slug, and - CF-0821 - a rebuild,
# rerun, the same script, topic or fact: `same_video`) already lies in
# publish/ or went out - `other_version_placed`. The seven such example-film
# rows of 2026-09/10 stay where the user's corrections put them
# (`CF0463_SETTLED`). Another video under an old name (another topic and
# fact) is queued like any other, its answer naming the namesake.

QUEUE_FIX_TASK = "CF-0738"
Q_PLACED, Q_ADOPTED, Q_ALREADY = "placed", "adopted", "already_placed"
Q_NOT_ACCEPTED, Q_OTHER_VERSION = "not_accepted", "other_version_placed"
Q_SLUG_TAKEN, Q_BATCH_MISSING, Q_RENDER_MISSING = "slug_taken", "batch_missing", "render_missing"
Q_CHANNEL_UNKNOWN, Q_FAILED = "channel_unknown", "queue_failed"
QUEUE_OK = (Q_PLACED, Q_ADOPTED, Q_ALREADY)
QUEUE_SKIPS = (Q_NOT_ACCEPTED, Q_OTHER_VERSION)
QUEUE_REFUSALS = (Q_SLUG_TAKEN, Q_BATCH_MISSING, Q_RENDER_MISSING, Q_CHANNEL_UNKNOWN, Q_FAILED)
# CF-0821: an accepted video the копилка did not get - said in the answer
# (`left_out`, `alert_ru`, `text_ru` opening with LEFT_OUT_MARK) and on the
# notification bus (`shared/notify.py`, Telegram when it is on), never only in
# the CLI.
LEFT_OUT_TASK = "CF-0821"
LEFT_OUT = (Q_OTHER_VERSION,) + QUEUE_REFUSALS
LEFT_OUT_MARK = "НЕ В КОПИЛКЕ: "
LEFT_OUT_RU = {
    Q_OTHER_VERSION: "под этим именем уже размещена его версия - если это новый ролик, "
                     "решает драйвер (--other-version-ok)",
    Q_SLUG_TAKEN: "имя и файл с суффиксом батча заняты в копилке publish/<канал>/_queue/",
    Q_BATCH_MISSING: "батч ролика не найден",
    Q_RENDER_MISSING: "в батче нет файла ролика",
    Q_CHANNEL_UNKNOWN: "канал не читается",
    Q_FAILED: "ошибка при копировании",
}
LEFT_OUT_NOTIFY_KIND = "needs_human"
# CF-0920: a clash of names is not the user's level (04.11 percy-jackson, the user's words,
# the same as 25.10 «все делай сам»): what the automatic rule could not settle goes
# to the driver and the center - the answer, `stash.not_queued`, `stash_event` - and
# not on the bus. The other codes of LEFT_OUT stay there.
# CF-0921: `other_version_placed` is about names and versions too (the user's order of
# 25.10: the driver settles it) - the answer, `stash_event` at the verdict, and, when
# the rule could not tell a new video from a version (`VERSION_UNSURE`), the driver's
# list `stash.other_version` (`publish_stash show`).
LEFT_OUT_QUIET = (Q_SLUG_TAKEN, Q_OTHER_VERSION)
NAMES_TASK = "CF-0920"
STASH_EVENTS = "stash-events.jsonl"
QUEUE_RU = {
    Q_PLACED: "ролик положен в копилку publish/{channel}/_queue/",
    Q_ADOPTED: "ролик уже лежал в publish/{channel}/ - путь записан в приёмку",
    Q_ALREADY: "у ролика уже есть место в publish/ ({publish_path})",
    Q_NOT_ACCEPTED: "ролик не принят - в копилку не идёт",
    Q_OTHER_VERSION: "другая версия этого ролика уже размещена ({other}; {other_why}) - эта "
                     "в копилку не идёт (CF-0463). Если это новый ролик под старым именем: "
                     "runlog acceptance --enqueue-accepted --entry {entry_id} "
                     "--other-version-ok --apply",
    Q_SLUG_TAKEN: "в publish/{channel}/_queue/ заняты и имя {slug}, и файл с суффиксом батча "
                  "{batch_id} - копия не положена (CF-0920: разбирает драйвер, "
                  "notify/stash-events.jsonl; повтор - runlog acceptance --enqueue-accepted)",
    Q_BATCH_MISSING: "батч ролика не найден (pipeline/*/{batch_id}) - копировать нечего",
    Q_RENDER_MISSING: "в батче нет файла ролика {slug}.mp4 - копировать нечего",
    Q_CHANNEL_UNKNOWN: "канал строки приёмки не читается - папку publish/<канал>/ не выбрать",
    Q_FAILED: "копилка не записана: {error}",
}
REPAIR_BAD_WHO, REPAIR_BATCH_OPEN, REPAIR_CHECK_CHANGED = "bad_who", "batch_open", "check_changed"
REPAIR_COMMIT_REFUSED, REPAIR_NOT_FOUND = "commit_refused", "not_found"
WHO_MAX = 40
_BATCH_REL_RE = re.compile(r"^(pipeline/[^/\s]+/[^/\s]+)/")


def batch_dir_of_row(row, root=None, batch_dir=None):
    """The directory the row's video was rendered in, or None: `batch_dir`
    (the caller's, trusted), else the first existing `pipeline/<x>/<batch_id>`
    among the row's own pointers (`code_shas_source`, `topic_id_source`,
    `batch_artifact` - only when it names this batch: a rebuild's
    `batch_artifact` names the batch it was rebuilt from), its channel, its
    former name, `rebuilds`, and any `pipeline/*/<batch_id>`."""
    base = Path(root or ROOT)
    if batch_dir:
        b = Path(batch_dir)
        b = b if b.is_absolute() else base / b
        return b if b.is_dir() else None
    bid = str(row.get("batch_id") or "")
    if not bid:
        return None
    pool = batch_pool(root)
    cands = []
    for key in ("code_shas_source", "topic_id_source", "batch_artifact"):
        v = str(row.get(key) or "")
        m = _BATCH_REL_RE.match(v + ("/" if key == "batch_artifact" else ""))
        if m:
            cands.append(Path(m.group(1)))
    for ch in (resolve_channel(row.get("channel"), root=root), row.get("channel_as_given"),
               "rebuilds"):
        if ch:
            cands.append(pool / ch / bid)
    if pool.is_dir():
        cands += sorted(pool.glob(f"*/{bid}"))
    for c in cands:
        c = c if c.is_absolute() else base / c
        if c.name == bid and c.is_dir():
            return c
    return None


def rendered_files(row, root=None, batch_dir=None):
    """`{batch_dir, mp4, thumbnail}` of the row's render - paths, or None for
    what is not there. `<batch>/videos/<slug>.mp4|.jpg` first, then the
    Editor's `output_path` / `thumbnail_path` of the video named by its stem."""
    b = batch_dir_of_row(row, root, batch_dir)
    slug = str(row.get("slug") or "")
    out = {"batch_dir": b, "mp4": None, "thumbnail": None}
    if b is None or not slug:
        return out
    mp4, jpg = b / "videos" / f"{slug}{VIDEO_SUFFIX}", b / "videos" / f"{slug}.jpg"
    out["mp4"] = mp4 if mp4.is_file() else None
    out["thumbnail"] = jpg if jpg.is_file() else None
    if out["mp4"] and out["thumbnail"]:
        return out
    try:
        data = json.loads((b / VIDEO_EDITOR_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    for v in (data.get("videos") or []) if isinstance(data, dict) else []:
        if not isinstance(v, dict) or Path(str(v.get("output_path") or "")).stem != slug:
            continue
        for key, field in (("mp4", "output_path"), ("thumbnail", "thumbnail_path")):
            if out[key] is None and v.get(field):
                p = Path(v[field])
                p = p if p.is_absolute() else b / p
                out[key] = p if p.is_file() else None
    return out


# CF-0821: a version of one video vs a new video under an old name. 20.10 Reel
# `2026-10-18T0841Z` `you-can-see-everything` (topic `lf-2026-10-18-002`, the
# Telluride premiere) was accepted and left out of the копилка as "another
# version" of the 25.09 video of the same name (`2026-09-23T1722Z`, topic
# `lf-2026-09-23-004`, a fact about the shoot) - the name was all that was
# compared. A version is a rebuild or a rerun (the same batch, a batch naming
# the other's), or the same script, topic or fact; a new video is another
# topic AND another fact. What cannot be told (a topic or a fact missing on
# either side) stays a version - the person decides, and is told (CF-0821
# item 2).
SAME_VIDEO_TASK = "CF-0821"
# The seven accepted rows of 2026-09/10 a person settled as versions by hand
# (CF-0463: their paths nulled on 01.10). One of them - american-dread-story
# of 2210Z - carries another topic and fact than the one that went out, and the
# rule above would call it new; a person's call is not reopened by a rule.
CF0463_SETTLED = frozenset({
    "example-film/2026-09-15T1034Z/widows-bay",
    "example-film/2026-09-30T2210Z/american-dread-story",
    "example-film/2026-09-30T2210Z/backrooms",
    "example-film/2026-09-30T2210Z/day-drinker",
    "example-film/2026-09-30T2210Z/wolfhame",
    "example-film/2026-10-01T0200Z/american-dread-story",
    "example-film/2026-10-05T0701Z/harbourlights",
})


def _fact_of(row):
    """`(url, text)` of the row's fact (`profile.fact_source.url`,
    `profile.fact_text` normalised), each None when not on the row."""
    prof = row.get("profile") if isinstance(row.get("profile"), dict) else {}
    src = prof.get("fact_source") if isinstance(prof.get("fact_source"), dict) else {}
    url = str(src.get("url") or "").strip() or None
    text = _norm(prof.get("fact_text") or "") or None
    return url, text


def _script_of(row):
    prof = row.get("profile") if isinstance(row.get("profile"), dict) else {}
    return str(prof.get("script_id") or "").strip() or None


def _names_batch(row, batch_id):
    return bool(batch_id) and str(row.get("batch_artifact") or "").rstrip("/").endswith(
        f"/{batch_id}")


# CF-0921: the two answers of `same_video` that are a version only because nothing
# tells the two apart - what the driver still decides (`--other-version-ok`)
UNSURE_NO_TOPIC = "темы нет в записи - новый ролик от версии не отличить"
UNSURE_NO_FACT = "факта нет в записи - новый ролик от версии не отличить"
VERSION_UNSURE = (UNSURE_NO_TOPIC, UNSURE_NO_FACT)


def same_video(row, other):
    """CF-0821: `(True, why)` when `other` is a version of the video `row` is -
    a rebuild or rerun, or the same script, topic or fact - and `(False, why)`
    when it is another video that only carries the same name (another topic and
    another fact). Nothing to tell them by is a version, and `why` says so -
    in Russian, it goes into the answer's `text_ru`."""
    if row.get("entry_id") in CF0463_SETTLED:
        return True, "версию решил человек (CF-0463)"
    a, b = row.get("batch_id"), other.get("batch_id")
    if a and a == b:
        return True, f"тот же батч {a}"
    if _names_batch(row, b) or _names_batch(other, a):
        return True, "пересборка того батча"
    ta, tb = row.get("topic_id"), other.get("topic_id")
    if ta and ta == tb:
        return True, f"та же тема {ta}"
    sa, sb = _script_of(row), _script_of(other)
    if sa and sa == sb:
        return True, f"тот же сценарий {sa}"
    (ua, xa), (ub, xb) = _fact_of(row), _fact_of(other)
    if xa and xa == xb:
        return True, "тот же текст факта"
    # CF-0855: a fact is its text - one page (one Wikipedia section) holds many
    # facts, so the source's url names the fact only when a text is missing on
    # a side (23.10 Tech `anthropic`: two facts of `Anthropic#History` read as one)
    if ua and ua == ub and not (xa and xb):
        return True, f"тот же факт {ua}"
    if not (ta and tb):
        return True, UNSURE_NO_TOPIC
    if not ((ua or xa) and (ub or xb)):
        return True, UNSURE_NO_FACT
    return False, f"другая тема ({ta} / {tb}) и другой факт" + (
        f" (тот же источник {ua})" if ua and ua == ub else "")


def _placed_namesakes(row, rows, root=None):
    """The other accepted rows of the same name on the same channel (a row
    whose channel cannot be read counts as the same) that carry a
    `publish_path`."""
    me = publish_layout.channel_of_row(row, root=root)
    out = []
    for r in rows or []:
        if r is row or r.get("entry_id") == row.get("entry_id"):
            continue
        if r.get("slug") != row.get("slug") or r.get("verdict") != ACCEPTED \
                or not r.get("publish_path"):
            continue
        ch = publish_layout.channel_of_row(r, root=root)
        if ch is None or me is None or ch == me:
            out.append(r)
    return out


def placed_version(row, rows, root=None):
    """Another accepted row of the same video - same channel, same slug, a
    version by `same_video` (CF-0821) - that carries a `publish_path`; None
    when there is none. Such a row means this version is not the one that goes
    out (CF-0463). A row of another video that only carries the same name is
    not one: that video goes into the копилка by itself (`placed_namesake`).
    `queue_accepted(..., other_version_ok=True)` - a person's call - places a
    video past a version the rule could not tell apart."""
    for r in _placed_namesakes(row, rows, root=root):
        if same_video(row, r)[0]:
            return r
    return None


def placed_namesake(row, rows, root=None):
    """CF-0821: `(other row, why)` of a placed accepted row that carries this
    video's name but is another video (another topic and fact), or None."""
    for r in _placed_namesakes(row, rows, root=root):
        same, why = same_video(row, r)
        if not same:
            return r, why
    return None


def _queue_answer(row, code, apply, **extra):
    values = {"channel": extra.get("channel") or "?", "slug": row.get("slug"),
              "batch_id": row.get("batch_id"), "publish_path": row.get("publish_path"),
              "other": extra.get("other") or "?", "error": extra.get("error") or "?",
              "other_why": extra.get("other_why") or "?", "entry_id": row.get("entry_id")}
    text = QUEUE_RU[code].format_map(values)
    left_out = code in LEFT_OUT
    out = {"entry_id": row.get("entry_id"), "slug": row.get("slug"),
           "batch_id": row.get("batch_id"), "channel": None, "code": code,
           "ok": code in QUEUE_OK, "skipped": code in QUEUE_SKIPS,
           "refused": code in QUEUE_REFUSALS, "dry_run": not apply, "changed": False,
           "publish_path": row.get("publish_path"), "source": None,
           # CF-0821: an accepted video that is not in the копилка is said loudly -
           # the center shows `text_ru` as is
           "text_ru": (LEFT_OUT_MARK + text) if left_out else text,
           "left_out": left_out, "alert_ru": None, "task": QUEUE_FIX_TASK}
    out.update(extra)
    if left_out:
        out["alert_ru"] = (f"Ролик {row.get('slug')} ({row.get('batch_id')}) принят, но в "
                           f"копилку publish/{values['channel']}/_queue/ "
                           f"не попал: {LEFT_OUT_RU[code]}")
    return out


def stash_event(root, action, row, **extra):
    """CF-0920: one line of what the копилка settled by itself or could not -
    `<notify state>/stash-events.jsonl` (gitignored, beside the bus's journal; no
    backend, nobody is called), for the driver and the center. Never raises."""
    try:
        shared = str(Path(__file__).resolve().parent.parent)
        if shared not in sys.path:
            sys.path.append(shared)
        import notify as bus                                    # noqa: PLC0415
        d = bus.state_dir(root)
        d.mkdir(parents=True, exist_ok=True)
        line = {"at": _now(), "task": NAMES_TASK, "action": action,
                "entry_id": row.get("entry_id"), "slug": row.get("slug"),
                "batch_id": row.get("batch_id"), **extra}
        with open(d / STASH_EVENTS, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(_jsonable(line), ensure_ascii=False) + "\n")
    except Exception as e:                                      # noqa: BLE001
        print(f"STASH EVENT {action}: {e.__class__.__name__}: {e}", file=sys.stderr)


def _upload_records():
    records = str(ROOT / "agents" / "publisher")
    if records not in sys.path:
        sys.path.append(records)
    import upload_records                                       # noqa: PLC0415
    return upload_records


def _withdrawn_of(entry, ch, pub):
    """CF-0920: the withdrawn row of the upload journal this pair in `_queue/` is
    the leftover of (the old layout, before `_reserve/`), or None: the row's `note`
    names the pair, or its batch is the pair's (a bare render with no note: only by
    the `note`). An unreadable journal says nothing - the new video goes under its
    own name then, no harm done."""
    upload_records = _upload_records()
    try:
        rows = upload_records.uploads(Path(pub) / "uploads.json", ch)
    except (upload_records.JournalError, ValueError):
        return None
    note = publish_layout.rel(ch, entry["bucket"], publish_layout.stem_of(entry),
                              publish_layout.NOTE)
    owner = publish_layout.batch_of(entry)
    for r in rows:
        if r.get("slug") == entry["slug"] and upload_records.is_withdrawn(r) \
                and not r.get("removed_at") \
                and (r.get("note") == note or (owner and owner == r.get("batch_id"))):
            return r
    return None


def _withdrawn_to_reserve(entry, gone, ch, pub, root, rows, apply):
    """CF-0920: the withdrawn pair that holds a name in `_queue/` goes to `_reserve/`
    - the step of `--migrate-reserve` for one video, its own commit, before the
    verdict's: the pair, the README row, `publish_path` (on disk and in `rows`, which
    the caller writes after this) and the journal's `note`. `{slug, video_id,
    batch_id, from, to, commit, commit_error?}`, or None when it cannot go."""
    slug = entry["slug"]
    src = publish_layout.rel(ch, entry["bucket"], publish_layout.stem_of(entry),
                             publish_layout.NOTE)
    try:
        plan = publish_layout.to_reserve(slug, ch, publish=pub, apply=apply,
                                         stem=publish_layout.stem_of(entry),
                                         batch=gone.get("batch_id"))
    except (publish_layout.LayoutError, OSError):
        return None
    to = publish_layout.note_rel(plan)
    out = {"slug": slug, "video_id": gone.get("video_id"), "batch_id": gone.get("batch_id"),
           "from": src, "to": to, "commit": None}
    if not apply:
        return out
    for moved in plan["log"]:
        for r in rows or []:
            if r.get("entry_id") in moved["entries"]:
                r["publish_path"] = moved["to"]
    records = _upload_records()
    gc = _git_commit()
    data = Path(root)
    paths = [src, to]
    try:
        if records.repoint_notes({src: to}, Path(pub) / "uploads.json"):
            paths.append(gc.rel(data, Path(pub) / "uploads.json"))
        if plan["readme"]:
            paths.append(gc.rel(data, Path(pub) / "README.md"))
        if plan["log"]:
            paths.append(gc.rel(data, Path(pub) / "acceptance-log.json"))
        if gc.is_repo(data):
            out["commit"], _done = gc.commit_paths(
                data, paths, f"Запас {ch}: {slug} из _queue/ в _reserve/ ({NAMES_TASK})\n\n"
                             f"Снятый ролик {gone.get('video_id')} ({gone.get('batch_id')}) "
                             f"держал имя в _queue/; его место занимает новый ролик этого "
                             f"имени.\n")
    except (records.JournalError, gc.CommitError, OSError) as e:
        out["commit_error"] = f"{e.__class__.__name__}: {e}"
    return out


def queue_accepted(row, rows=None, root=None, publish_dir=None, batch_dir=None, apply=True,
                   other_version_ok=False, move_reserve=True):
    """CF-0738: put an accepted video with no place yet into
    `publish/<channel>/_queue/` (the channel's folder is made when missing)
    and set the row's `publish_path`; the caller writes the log. Answers a
    dict, never raises for a video it cannot place:

        {entry_id, slug, batch_id, channel, code, ok, skipped, refused,
         dry_run, changed, publish_path, source, text_ru, task, line?}

    `code`: `placed` (copied), `adopted` (already in the channel's folder for
    this batch - only the path is written), `already_placed` (the row has a
    path); skipped by design: `not_accepted`, `other_version_placed`
    (CF-0463); refused: `slug_taken` (the name and `<slug>~<batch>` are both taken
    in `_queue/`, or no batch to name it by), `batch_missing`, `render_missing`,
    `channel_unknown`.

    CF-0920: a name is not a reason to leave a video out. Another batch's pair in
    a day folder or in `_reserve/` is not in the way (CF-0855, CF-0919). In `_queue/`:
    a withdrawn video (the old layout) goes to `_reserve/` first, its own commit, the
    answer's `reserve_move` - `move_reserve=False` when no commit may be made (a batch
    is going, a bare `--record --write`): it stays, the new one goes under the suffix;
    a live one stays and this video's file is `<slug>~<batch>`, the answer's `name_taken`.
    `slug`, the entry id and the card keep the plain name; `publish_path` names the file.

    `apply=False` says what would happen and changes nothing;
    `other_version_ok=True` (a person said this is another video under an old
    name) places it past `other_version_placed`."""
    if row.get("verdict") != ACCEPTED:
        return _queue_answer(row, Q_NOT_ACCEPTED, apply)
    if row.get("publish_path"):
        return _queue_answer(row, Q_ALREADY, apply)
    pub = Path(publish_dir) if publish_dir else (Path(root) / "publish" if root else PUBLISH)
    data_root = Path(root) if root else pub.parent
    other = None if other_version_ok else placed_version(row, rows, root=data_root)
    if other is not None:
        why = same_video(row, other)[1]
        # CF-0921: `version_unsure` - the rule took it for a version only for want of a
        # topic or a fact on the record, and nobody settled it (CF0463_SETTLED): the
        # driver's call, `publish_stash show` lists it
        return _queue_answer(row, Q_OTHER_VERSION, apply,
                             other=f"{other.get('entry_id')}: {other.get('publish_path')}",
                             other_why=why, other_entry=other.get("entry_id"),
                             other_path=other.get("publish_path"),
                             version_unsure=why in VERSION_UNSURE,
                             repair=f"runlog acceptance --enqueue-accepted --entry "
                                    f"{row.get('entry_id')} --other-version-ok --apply")
    # CF-0821: another video that only carries this name goes on by itself; the
    # answer names the namesake so nobody reads the two as one
    ns = placed_namesake(row, rows, root=data_root)
    extra = {"namesake": {"entry_id": ns[0].get("entry_id"),
                          "publish_path": ns[0].get("publish_path"), "why": ns[1]}} \
        if ns else {}
    ch = publish_layout.channel_of_row(row, root=data_root)
    if not ch or not publish_layout.CHANNEL_RE.match(str(ch)):
        return _queue_answer(row, Q_CHANNEL_UNKNOWN, apply, **extra)
    slug = row["slug"]
    here = [e for e in publish_layout.locate(slug, pub, ch) if e["channel"] == ch]
    batch = row.get("batch_id")
    # CF-0920: a bare render whose path another row names is that row's copy (its
    # card is still being built), not the copy of this verdict
    claimed = {r.get("publish_path") for r in rows or []
               if r is not row and r.get("entry_id") != row.get("entry_id")}
    mine, theirs = None, []
    for e in here:
        owner, name = publish_layout.batch_of(e), publish_layout.stem_of(e)
        if owner is not None and owner == batch:
            mine = mine or e
        elif owner is None and e["bucket"] == publish_layout.QUEUE \
                and publish_layout.rel(ch, e["bucket"], name) not in claimed:
            mine = mine or e            # a bare render in _queue/: the copy of this verdict
        elif e["bucket"] == publish_layout.QUEUE and name == slug:
            theirs.append(e)
        # CF-0855: another batch's pair in a day folder is a namesake that holds
        # its own day (`delver`, `anthropic`) - the copy goes to _queue/, the day
        # folder tells the two apart; only the plain name in _queue/ is in the way
    if mine is not None:
        path = publish_layout.rel(ch, mine["bucket"], publish_layout.stem_of(mine))
        if apply:
            row["publish_path"] = path
        return _queue_answer(row, Q_ADOPTED, apply, channel=ch, publish_path=path,
                             changed=bool(apply), **extra)
    files = rendered_files(row, root=data_root, batch_dir=batch_dir)
    if files["batch_dir"] is None:
        return _queue_answer(row, Q_BATCH_MISSING, apply, channel=ch, **extra)
    if files["mp4"] is None:
        return _queue_answer(row, Q_RENDER_MISSING, apply, channel=ch,
                             line=f"{files['batch_dir']}/videos/{slug}{VIDEO_SUFFIX}", **extra)
    moved = None
    if theirs and move_reserve:
        gone = _withdrawn_of(theirs[0], ch, pub)
        moved = _withdrawn_to_reserve(theirs[0], gone, ch, pub, data_root, rows, apply) \
            if gone else None
        if moved:
            extra["reserve_move"] = moved
            extra["line"] = f"{moved['from']} -> {moved['to']}"
            if apply:
                stash_event(data_root, "moved_to_reserve", row, channel=ch, **moved)
    # a dry run has not moved it: the name is as good as free
    stem = slug if moved and not apply else publish_layout.free_stem(
        pub, ch, publish_layout.QUEUE, slug, batch)
    if stem is None:
        at = ", ".join(publish_layout.rel(ch, e["bucket"], publish_layout.stem_of(e))
                       for e in theirs) or publish_layout.rel(ch, publish_layout.QUEUE, slug)
        if apply:
            stash_event(data_root, Q_SLUG_TAKEN, row, channel=ch, at=at)
        extra["line"] = f"{slug}: {at}"
        return _queue_answer(row, Q_SLUG_TAKEN, apply, channel=ch, **extra)
    path = publish_layout.rel(ch, publish_layout.QUEUE, stem)
    if stem != slug:
        at = publish_layout.rel(ch, publish_layout.QUEUE, slug)
        extra["name_taken"] = {"by": at, "batch_id": publish_layout.batch_of(theirs[0])
                               if theirs else None, "task": NAMES_TASK}
        extra["line"] = f"{slug}: {at} is another video - {path}"
    if apply:
        place(row, files["mp4"], publish_dir=pub, channel=ch, stem=stem)
        if stem != slug:
            stash_event(data_root, "named_by_batch", row, channel=ch, path=path,
                        **extra["name_taken"])
    return _queue_answer(row, Q_PLACED, apply, channel=ch, publish_path=path,
                         source=str(files["mp4"]), changed=bool(apply), **extra)


def _queue_verdict(row, rows, root, publish_dir, batch_dir=None, move_reserve=True):
    """`queue_accepted` for a verdict just recorded - None for a rejection,
    and an unexpected error is an answer (`queue_failed`), never a lost verdict.

    CF-0747: a video that took its place in the копилка gets its publication
    card built by itself - `agents/publisher/card_center.py` `on_accepted`, a
    detached build with its own log (idempotent: not while one runs, not over a
    ready card of the same script); the answer carries it as `card_build`.
    `PUBLISH_CARD_AUTOBUILD=0` switches it off. It never refuses the verdict.

    CF-0821: a video it did not place (`left_out`) is sent on the notification
    bus at once (`notify_left_out`; the answer carries the bus's answer as
    `notified`) - CF-0920: not a clash of names, `LEFT_OUT_QUIET`, `notified` None.
    CF-0921: nor another version of the video (`other_version_placed`) - one line
    in `stash-events.jsonl` instead (`slug_taken` writes its own in `queue_accepted`).

    CF-0920: `move_reserve=False` - no commit may be made now (`queue_accepted`)."""
    if row.get("verdict") != ACCEPTED:
        return None
    try:
        q = queue_accepted(row, rows, root=root, publish_dir=publish_dir,
                           batch_dir=batch_dir, move_reserve=move_reserve)
    except Exception as e:                                      # noqa: BLE001
        q = _queue_answer(row, Q_FAILED, True, error=f"{e.__class__.__name__}: {e}")
    if q.get("ok"):
        q["card_build"] = _card_build(row, root, publish_dir, batch_dir)
    if q.get("left_out") and q.get("code") not in LEFT_OUT_QUIET:
        q["notified"] = notify_left_out(q, row, root or Path(publish_dir).parent)
    elif q.get("code") == Q_OTHER_VERSION:
        data_root = Path(root) if root else Path(publish_dir).parent
        stash_event(data_root, Q_OTHER_VERSION, row,
                    channel=publish_layout.channel_of_row(row, root=data_root),
                    other=q.get("other_entry"), other_path=q.get("other_path"),
                    why=q.get("other_why"), unsure=q.get("version_unsure"),
                    repair=q.get("repair"))
    return q


# A stand-in for the bus (tests): called as NOTIFY(kind, key, text, channel=,
# link=, root=) and answering like `notify.send`.
NOTIFY = None
# CF-0925: the stand-in of the batch's acceptance message alone (tests) - called
# as ACCEPTED_NOTIFY(kind, key, text, channel=, link=, root=, multiline=True)
ACCEPTED_NOTIFY = None
ACCEPTED_KIND = "accepted"
ACCEPTED_TASK = "CF-0925"


def batch_verdicts(channel, batch_id, root=None, log=None, batch_dir=None):
    """CF-0925: `(rows, waiting)` of one batch - the record's rows of it (a
    verdict still in the queue of CF-0675 counts) and the slugs of its videos
    (`05-video-editor.json` videos) that have no verdict yet."""
    ch = resolve_channel(channel, root)
    rows = [r for r in entries(path=log)
            if resolve_channel(r.get("channel"), root) == ch and r.get("batch_id") == batch_id]
    have = {r.get("slug") for r in rows}
    waiting = []
    for b in _batch_dirs(ch, batch_id, batch_dir, root=root):
        try:
            d05 = json.loads((b / "05-video-editor.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for v in d05.get("videos") or []:
            vslug = Path(str((v or {}).get("output_path") or "")).stem if isinstance(v, dict) \
                else ""
            if vslug and vslug not in have and vslug not in waiting:
                waiting.append(vslug)
        break
    return rows, waiting


def notify_acceptance(channel, batch_id, root=None, log=None, batch_dir=None, force=False):
    """CF-0925: one message per batch once every video of it has the user's
    verdict - «👀 Reel 08.11: принято 2 из 6 — X, Y» and a line per refusal
    with its reason (shared/notify_human.py), kind `accepted`, key
    `accepted:<channel>:<batch>` (a second call is the bus's `duplicate`).
    `force` (`--notify CH/BATCH`): sent with videos still waiting too.
    Answers `{status, key?, waiting?, text?}` - status `waiting`, `nothing`,
    or the bus's; never raises."""
    try:
        ch = resolve_channel(channel, root)
        rows, waiting = batch_verdicts(ch, batch_id, root, log, batch_dir)
        if waiting and not force:
            return {"status": "waiting", "waiting": waiting}
        if not rows:
            return {"status": "nothing", "waiting": waiting}
        bdir = next(iter(_batch_dirs(ch, batch_id, batch_dir, root=root)), None)
        shared = str(Path(__file__).resolve().parent.parent)
        if shared not in sys.path:
            sys.path.append(shared)
        import notify_human                                     # noqa: PLC0415
        text = notify_human.acceptance_text(ch, batch_id, rows, root=root, batch_dir=bdir)
        if waiting:
            text += "\nЕщё ждут вердикта: " + ", ".join(notify_human.human_slug(w)
                                                      for w in waiting)
        key = f"{ACCEPTED_KIND}:{ch}:{batch_id}"
        if ACCEPTED_NOTIFY is not None:
            res = ACCEPTED_NOTIFY(ACCEPTED_KIND, key, text, channel=ch, link=None, root=root,
                                  multiline=True)
        else:
            bus = notify_human.notify
            res = bus.send(ACCEPTED_KIND, key, text, channel=ch,
                           link=bus.link_of(ch, "acceptance"),
                           root=Path(root) if root else None, multiline=True)
        return dict(res or {}, text=text, waiting=waiting)
    except Exception as e:                                      # noqa: BLE001
        print(f"NOTIFY {ACCEPTED_KIND}: {e.__class__.__name__}: {e}", file=sys.stderr)
        return {"status": "error", "error": str(e)}


def notify_left_out(q, row, root=None):
    """CF-0821: one line on the notification bus for an accepted video the
    копилка did not get - kind `needs_human`, one per video and code (a second
    call is the bus's `duplicate`), a link to the channel's publishing page.
    Answers the bus's `{status, ...}`; never raises."""
    # CF-0835 (CF-0197): `q` may be a stored answer and the row a dated record -
    # either can carry a channel's former id, so it is resolved at the door
    ch = resolve_channel(q.get("channel") or publish_layout.channel_of_row(row, root=root)
                         or row.get("channel"), root)
    key = f"stash-left-out:{q.get('entry_id')}:{q.get('code')}"
    text = (f"{ch}: принятый ролик {row.get('slug')} ({row.get('batch_id')}) не в копилке - "
            f"{LEFT_OUT_RU.get(q.get('code'), q.get('code'))}")
    try:
        if NOTIFY is not None:
            return NOTIFY(LEFT_OUT_NOTIFY_KIND, key, text, channel=ch, link=None, root=root)
        shared = str(Path(__file__).resolve().parent.parent)
        if shared not in sys.path:
            sys.path.append(shared)
        import notify as bus                                    # noqa: PLC0415
        return bus.send(LEFT_OUT_NOTIFY_KIND, key, text, channel=ch,
                        link=bus.link_of(ch, "feed"), root=root)
    except Exception as e:                                      # noqa: BLE001
        print(f"NOTIFY {LEFT_OUT_NOTIFY_KIND}: {e.__class__.__name__}: {e}", file=sys.stderr)
        return {"status": "error", "key": key, "error": str(e)}


CARD_BUILD_TASK = "CF-0747"


def _card_build(row, root, publish_dir, batch_dir=None):
    """CF-0747: start the accepted video's card build - the short answer of
    `card_center.on_accepted`, or {ok: False, error} - never raises."""
    try:
        if str(os.environ.get("PUBLISH_CARD_AUTOBUILD", "1")).strip().lower() in (
                "0", "off", "no", "false"):
            return {"ok": True, "launched": False, "skipped": "off", "run_id": None,
                    "log": None, "refusals": []}
        data_root = Path(root) if root else Path(publish_dir).parent
        spec = importlib.util.spec_from_file_location(
            "card_center_acceptance", ROOT / "agents" / "publisher" / "card_center.py")
        cc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cc)
        return cc.short(cc.on_accepted(row, root=data_root, batch_dir=batch_dir))
    except Exception as e:                                      # noqa: BLE001
        return {"ok": False, "launched": False, "skipped": None, "run_id": None, "log": None,
                "refusals": ["spawn_failed"], "error": f"{e.__class__.__name__}: {e}"}


def card_not_started(queued):
    """CF-0891: why the accepted video's card build did not start (the refusal
    line of `card_center`, or its codes / error), or None - said in the
    commit and on the CLI instead of being lost in the answer."""
    cb = (queued or {}).get("card_build") if isinstance(queued, dict) else None
    if not isinstance(cb, dict) or cb.get("launched") or cb.get("skipped"):
        return None
    if not (cb.get("refusals") or cb.get("error") or cb.get("why")):
        return None
    return cb.get("why") or cb.get("error") or ", ".join(map(str, cb.get("refusals")))


def unqueued(rows):
    """The accepted rows with no `publish_path` - what `repair_queue` reads."""
    return [r for r in rows or [] if r.get("verdict") == ACCEPTED and not r.get("publish_path")]


def _sha256_file(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def _who(value, what):
    if not isinstance(value, str) or not value.strip():
        return f"{what}={value!r}: the repair is somebody's - a short non-empty string"
    if len(value.strip()) > WHO_MAX or any(c in value for c in "\r\n\t"):
        return f"{what}={value!r}: at most {WHO_MAX} characters on one line"
    return None


def repair_queue(root=None, log=None, publish_dir=None, apply=False, by=None, via=None,
                 base_sha256=None, open_rows=None, only=None, other_version_ok=False):
    """CF-0738 item 2: find the accepted videos the record has no place for and
    put them into their channel's `_queue/` (`queue_accepted` on each). A dry
    run unless `apply`; with `apply`, `by` and `via` are required, no batch may
    be going (the copy and the commit of the record wait for it, CF-0675), and
    `base_sha256` - when given - must still be the record's sha256. The record
    is committed once (`Копилка: ...`), the files are gitignored copies.

    Answer (the shape of CF-0726):
        {ok, written, dry_run, task, by, via, log, base_sha256, sha256,
         new_sha256, commit, items [queue_accepted answers - CF-0919: a video that
         took its place carries `card_build`, its card started as at a verdict],
         refusals [{code, line, entry_id?}], lines}
    Top-level refusal codes: bad_who, batch_open, check_changed,
    commit_refused, not_found (an `only` entry id with no accepted row
    lacking a place); per video: the refused codes of `queue_accepted`.
    `only`: the entry ids to repair (default: every such row);
    `other_version_ok` goes to `queue_accepted` and needs `only`."""
    root, log, rel = _where(root, log)
    pub = Path(publish_dir) if publish_dir else log.parent
    res = {"ok": True, "written": False, "dry_run": not apply, "task": QUEUE_FIX_TASK,
           "by": by, "via": via, "log": str(rel), "base_sha256": base_sha256,
           "sha256": _sha256_file(log), "new_sha256": None, "commit": None, "items": [],
           "refusals": [], "lines": []}
    top = []
    if apply:
        for value, what in ((by, "by"), (via, "via")):
            why = _who(value, what)
            if why:
                top.append({"code": REPAIR_BAD_WHO, "line": why})
        if base_sha256 is not None and base_sha256 != res["sha256"]:
            top.append({"code": REPAIR_CHECK_CHANGED,
                        "line": f"{rel} changed since it was read ({base_sha256} -> "
                                f"{res['sha256']}) - read it again"})
        going = open_now(root, open_rows)
        if going:
            top.append({"code": REPAIR_BATCH_OPEN,
                        "line": f"a batch is going ({going[0]['dir']}) - the repair commits "
                                f"the record and waits for it (CF-0675)"})
    if only:
        ids = {r.get("entry_id") for r in unqueued(entries(log=read_log(log)))}
        top += [{"code": REPAIR_NOT_FOUND, "line": f"{e}: no accepted row without a place "
                                                   f"in {rel}"} for e in only if e not in ids]
    do = apply and not top
    lock = _queue_lock(log) if do else contextlib.nullcontext()
    with lock:
        doc = read_log(log)
        rows = entries(log=doc)
        todo = unqueued(rows)
        if only:
            todo = [r for r in todo if r.get("entry_id") in set(only)]
        done_rows = []
        for r in todo:
            item = queue_accepted(r, rows, root=root, publish_dir=pub, apply=do,
                                  other_version_ok=bool(other_version_ok and only))
            res["items"].append(item)
            done_rows.append(r)
            res["lines"].append(f"{item['code']:<20} {item['entry_id']}"
                                + (f" -> {item['publish_path']}" if item.get("publish_path")
                                   else "") + (f" ({item['line']})" if item.get("line") else ""))
        res["refusals"] = top + [{"code": i["code"], "line": i["text_ru"],
                                  "entry_id": i["entry_id"]}
                                 for i in res["items"] if i["refused"]]
        changed = [i for i in res["items"] if i["changed"]]
        if do and changed:
            placed = [i for i in changed if i["code"] == Q_PLACED]
            subject = (f"Копилка: {len(changed)} принятых без слота - в _queue/ "
                       f"({by}, {via})")
            body = [f"{QUEUE_FIX_TASK}: принятый ролик без слота лежит в копилке "
                    f"publish/<канал>/_queue/; починка записи приёмки."]
            body += [f"- {i['entry_id']}: {i['code']} -> {i['publish_path']}" for i in changed]
            message = (subject + "\n\n" + "\n".join(body) + "\n\n"
                       + "\n".join(f"Acceptance: {i['entry_id']}" for i in changed) + "\n")
            try:
                res["commit"] = _commit_log(root, log, rows, doc.get("note"), message)
            except AcceptanceError as e:
                res["refusals"].append({"code": REPAIR_COMMIT_REFUSED, "line": str(e)})
            res["written"] = bool(res["commit"] or placed)
            res["new_sha256"] = _sha256_file(log)
    if do:
        # CF-0919: a video the repair put in place gets its card as at a verdict
        # (`_queue_verdict`) - the commit is made, the build is detached and idempotent
        for item, r in zip(res["items"], done_rows):
            if item["changed"] and item.get("ok"):
                item["card_build"] = _card_build(r, root, pub)
                why = card_not_started(item)
                res["lines"].append(f"card {item['entry_id']}: "
                                    + (f"not started - {why}" if why else "build started"
                                       if item["card_build"].get("launched") else
                                       str(item["card_build"].get("skipped") or "not started")))
    res["ok"] = not res["refusals"]
    return res


def check(rows=None, path=None, publish_dir=None, holds_path=None):
    """Read `publish/` back against the record. `{"problems": [...],
    "held": [...], "layout": [...]}`. Every `<channel>/<day>/` and
    `<channel>/_queue/` folder and the flat root of before CF-0475 are read,
    and a video under a channel is held against that channel's rows only.

    A problem is a video in `publish/` that the record does not stand behind: a
    rejection sitting in the directory, or a video with no verdict at all. The
    second one is not pedantry - on 2026-09-22 `delver` and `dtf-st-louis` were
    put here on a misread verdict and taken out again by the user's own
    correction, and nothing but this check would have noticed.

    An accepted video whose `.mp4` is absent is not a problem: the files are
    gitignored and a checkout has none of them.

    A video accepted by the user and still held by CF-0318 is a *state*, not a
    problem - it is reported on its own list, because that is the one question
    the record has to be able to answer about a hold.

    `archived` (CF-0476) lists the accepted videos whose `publish_path` points
    into a month's zip on the archive volume - moved there, not missing.

    `layout` (CF-0475) names a file that is not where the layout says - still
    in the flat root, or a note in a day folder whose `## Публикация` names
    another day. It is a note to act on, never a problem: where a file lies is
    not a verdict.

    `pending` (CF-0870) names the verdicts read from the queue of CF-0675 that
    stand in for a row: given under a batch, not committed yet. The video they
    put into `_queue/` (CF-0738) is backed by them - a verdict written down and
    waiting for the batch to end is a verdict, so it is not `no_verdict`. They
    come with `rows` read from a file (`entries`); a caller that hands its own
    rows passes them through `with_pending` to have them counted."""
    rows = entries(path=path) if rows is None else rows
    pub = Path(publish_dir or PUBLISH)
    by_key = {}
    for r in rows:
        ch = publish_layout.channel_of_row(r, root=pub.parent)
        by_key.setdefault((ch, r.get("slug")), []).append(r)
        by_key.setdefault((None, r.get("slug")), []).append(r)     # the flat root: any channel
    places = {}
    for e in publish_layout.entries(pub):
        places.setdefault((e["channel"], e["slug"]), []).append(e)
    problems = []
    for (ch, slug), found in sorted(places.items(), key=lambda kv: (kv[0][1], kv[0][0] or "")):
        at = ", ".join(f"`publish/{publish_layout.prefix(e['channel'], e['bucket'])}"
                       f"{publish_layout.stem_of(e)}`" for e in found)
        mine = by_key.get((ch, slug)) or []
        if not mine:
            problems.append({"slug": slug, "channel": ch, "problem": "no_verdict",
                             "detail": f"{at} is there and no row of the record "
                                       + (f"of {ch} " if ch else "")
                                       + "carries a verdict for it - ask the user by name "
                                       "(CF-0328) instead of reading the directory"})
            continue
        if not any(r.get("verdict") == ACCEPTED for r in mine):
            why = "; ".join(f"{r.get('batch_id')}: {r.get('reason')}" for r in mine)
            problems.append({"slug": slug, "channel": ch, "problem": "rejected_but_present",
                             "detail": f"{at} is there and the user rejected "
                                       f"every version of it ({why})"})
    held_rows = []
    for r in rows:
        if r.get("verdict") != ACCEPTED:
            continue
        h = held_row(r, path=holds_path)
        if h:
            held_rows.append({"slug": r.get("slug"), "entry_id": row_key(r),
                              "hold_id": h.get("hold_id"),
                              "detail": "accepted by the user and held from publication by "
                                        "CF-0318 until a human signs the hold - two facts, "
                                        "both true"})
    # CF-0476: a video of a month that is over has left `publish/` for the
    # month's zip on the archive volume; its row's `publish_path` says so. That
    # is where it is, not something missing - its own list, never a problem.
    gone = []
    for r in rows:
        a = publish_layout.parse_archive_ref(r.get("publish_path"))
        if a and r.get("verdict") == ACCEPTED:
            gone.append({"slug": r.get("slug"), "entry_id": row_key(r),
                         "ref": r.get("publish_path"), "volume": a["volume"],
                         "zip": a["zip"], "member": a["member"],
                         "detail": f"in the archive: {a['volume']}:{a['zip']} "
                                   f"(inside {a['member']}, CF-0476)"})
    # CF-0544: a row without its topic is a hold that may not hold - named
    # here, with what its batch would give (`--backfill-topics`).
    no_topic = []
    for r in rows:
        if r.get("topic_id"):
            continue
        t, _sid, src = row_topic(r)
        no_topic.append({"slug": r.get("slug"), "entry_id": row_key(r),
                         "verdict": r.get("verdict"), "batch_gives": t,
                         "detail": (f"no topic_id on the row; the batch gives {t} ({src}) - "
                                    f"runlog acceptance --backfill-topics" if t else
                                    f"no topic_id on the row and none in the batch ({src})")})
    waiting = [{"slug": r.get("slug"), "entry_id": row_key(r), "verdict": r.get("verdict"),
                "queued_at": r.get("queued_at"),
                "detail": f"{r.get('verdict')} in the queue since {r.get('queued_at')} - "
                          f"committed to the record after the batch (CF-0675)"}
               for r in rows if r.get("pending")]
    return {"problems": problems, "held": held_rows, "archived": gone,
            "no_topic": no_topic, "pending": waiting,
            "layout": publish_layout.layout_notes(pub)}


def backfill_topics(rows):
    """CF-0544: `(filled, left)` - fill `topic_id` on every row that has none
    from its batch (`row_topic`), mutating `rows` in place; the caller writes.
    `filled` names each change with its source, `left` each row nothing was
    found for. A row that has a topic is never touched."""
    filled, left = [], []
    for r in rows:
        if r.get("topic_id"):
            continue
        t, _sid, src = row_topic(r)
        if t:
            r["topic_id"] = t
            r["topic_id_source"] = f"backfilled by CF-0544 from {src}"
            filled.append({"entry_id": row_key(r), "topic_id": t, "source": src})
        else:
            left.append({"entry_id": row_key(r), "why": src})
    return filled, left


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def render(rows=None, path=None):
    """One line per video, name first. Never numbered."""
    rows = entries(path=path) if rows is None else rows
    lines = []
    for r in sorted(rows, key=_sort_key):
        mark = "+" if r.get("verdict") == ACCEPTED else "-"
        tail = f" ({r.get('reason_code')}: {r.get('reason')})" if r.get("reason") else ""
        # The listing names the channel as it is called today; the string the
        # row froze is on the row, in `channel_as_given`.
        lines.append(f"{mark} {r.get('slug')}  "
                     f"{resolve_channel(r.get('channel'))}/{r.get('batch_id')}  "
                     f"{r.get('verdict')} {r.get('answered_at')}{tail}")
        for h in r.get("history") or []:
            was = f"    was {h.get('verdict')} {h.get('answered_at')}"
            if h.get("reason"):
                was += f": {h['reason']}"
            lines.append(f"{was} -> {h.get('superseded_because')}")
    return lines


def render_reasons(rows=None, path=None):
    lines = []
    for code, e in reasons(rows=rows, path=path).items():
        lines.append(f"{code}  x{e['count']} on {', '.join(e['videos'])}"
                     f"{'  [repeats]' if e['repeats'] else ''}")
        if e["checkable_by"]:
            lines.append(f"    machine check: {e['checkable_by']}")
        if e["covered_by"]:
            lines.append(f"    already covered by: {e['covered_by']}")
        for ph in e["phrases"]:
            lines.append(f"    \"{ph}\"")
    cands = candidates(rows=rows, path=path)
    lines.append("")
    if not cands:
        lines.append(f"No reason has been named on {REPEAT} different videos yet - "
                     f"nothing is a machine-check candidate (CF-0319 repeatability).")
    for c in cands:
        lines.append(f"{c['kind']}: {c['reason_code']} - {c['why']}")
    return lines


# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# CF-0675: a verdict is a commit - or waits in the queue while a batch is going
# --------------------------------------------------------------------------
# `publish/acceptance-log.json` is tracked. A verdict written and left
# uncommitted leaves the root dirty, and `batch-start` wants a clean `main`; a
# verdict committed while a batch is going moves the root's HEAD under it.
# So, as the channel edits of the command center (CC-0008): with no batch or
# rebuild open (`runlog.open_batches`, the fresh ones - a live executor's lock
# counts, CF-0670), one verdict is one commit of the record and of nothing else;
# under an open batch the verdict goes into `publish/acceptance-pending.jsonl`
# (gitignored) and the record is not touched. The queue is applied - through
# `record`, one commit for all of it - by `commit_pending`: the schedule's tick
# once the batch is done (`batch_schedule.tick`), or the next verdict given
# with no batch open. The same video twice in the queue: the last verdict wins,
# and the commit message says so. Readers see the queue at once (`entries`,
# `state`: `pending: true`).

VERDICT_RU = {ACCEPTED: "принят", REJECTED: "отклонён"}
QUEUE_TASK = "CF-0675"


def pending_path(path=None):
    """The queue beside the record `path` (default: the record this module reads)."""
    return Path(path or LOG).with_name(PENDING_NAME)


def read_pending(path):
    """The queued verdicts, oldest first: [{entry_id, slug, verdict, by, queued_at,
    batches, args, row}]. No file - no queue. A line that does not parse is an
    error: a verdict is never dropped in silence."""
    p = Path(path)
    if not p.is_file():
        return []
    out = []
    for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except ValueError as e:
            raise AcceptanceError(f"{p}:{n}: a queued verdict does not parse ({e})",
                                  code="queue_unreadable", line=n) from e
        if not isinstance(item, dict) or not item.get("entry_id") or not isinstance(
                item.get("args"), dict):
            raise AcceptanceError(f"{p}:{n}: not a queued verdict",
                                  code="queue_not_a_verdict", line=n)
        out.append(item)
    return out


def _last_per_video(queue):
    """{entry_id: [items, oldest first]} in the order the videos were first queued."""
    groups = {}
    for item in queue:
        groups.setdefault(item["entry_id"], []).append(item)
    return groups


def with_pending(rows, queue_path):
    """`rows` with the queue's last verdict per video standing in for the row it
    will replace (or added), marked `pending: true`. `rows` is not mutated."""
    out = list(rows)
    for eid, items in _last_per_video(read_pending(queue_path)).items():
        last = items[-1]
        prow = dict(last.get("row") or {}, pending=True, queued_at=last.get("queued_at"),
                    queued_by=last.get("by"))
        if len(items) > 1:
            prow["queued_verdicts"] = len(items)
        for i, r in enumerate(out):
            if eid in row_keys(r):
                prow["on_record"] = r                 # what the record says until the commit
                out[i] = prow
                break
        else:
            prow["on_record"] = None
            out.append(prow)
    return out


def _runlog():
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    import runlog                                           # noqa: PLC0415
    return runlog


def _git_commit():
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    import git_commit                                       # noqa: PLC0415
    return git_commit


def open_now(root, open_rows=None):
    """[{dir, why}] of the batches and rebuilds going under `root` - the fresh
    rows of `runlog.open_batches` (`open_rows`: its rows, from a caller that
    already has them)."""
    rows = open_rows if open_rows is not None else _runlog().open_batches(root)
    out = []
    for row in rows:
        d, _last, fresh = row[0], row[1], row[2]
        if fresh:
            out.append({"dir": str(d), "why": getattr(row, "why", None)})
    return out


def _where(root=None, log=None):
    """(root, log, rel) - the repository the record is committed in and the record."""
    if root is None:
        env = os.environ.get("FACTORY_ROOT")
        root = Path(env).expanduser() if env else ROOT
    root = Path(root).resolve()
    log = Path(log) if log else root / ACCEPTANCE_LOG_REL
    gc = _git_commit()
    try:
        rel = gc.rel(root, log)
    except gc.CommitError as e:
        raise AcceptanceError(f"the record {log} is not in {root} - it cannot be committed "
                              f"there ({e})", code="record_outside_repo") from e
    return root, root / rel, rel


@contextlib.contextmanager
def _queue_lock(log):
    """One writer of the record and its queue at a time - the center and the tick."""
    lp = Path(log).with_name(PENDING_LOCK_NAME)
    with open(lp, "a", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _jsonable(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return value


def _verdicts_word(n):
    if n % 10 == 1 and n % 100 != 11:
        return "вердикт"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "вердикта"
    return "вердиктов"


def _commit_error(e):
    return AcceptanceError(f"the record was not committed: {e} "
                           f"{' '.join(getattr(e, 'details', []) or [])}".strip(),
                           code="not_committed")


def _commit_log(root, log, rows, note, message):
    gc = _git_commit()
    try:
        return gc.write_and_commit(root, {log: log_text(rows, note).encode("utf-8")}, message)
    except (gc.CommitError, OSError) as e:
        raise _commit_error(e) from e


def _commit_pending(root, log, by, batches):
    qp = pending_path(log)
    queue = read_pending(qp)
    res = {"committed": False, "commit": None, "subject": None, "applied": [],
           "conflicts": [], "failed": [], "left": len(queue), "why": None, "queued": [],
           "left_out": []}
    if not queue:
        res["why"] = "очередь приёмки пуста"
        return res
    if batches:
        b = batches[0]
        res["why"] = (f"идёт батч {b['dir']}" + (f" ({b['why']})" if b.get("why") else "")
                      + " - вердикты ждут в очереди")
        return res
    doc = read_log(log)
    rows = entries(log=doc)
    applied, failed, conflicts = [], [], []
    for eid, items in _last_per_video(queue).items():
        last = items[-1]
        if len(items) > 1:
            conflicts.append({"entry_id": eid, "won": last["verdict"],
                              "verdicts": [{"verdict": i["verdict"], "by": i.get("by"),
                                            "queued_at": i.get("queued_at")} for i in items]})
        args = dict(last["args"])
        prev = find(args["channel"], args["batch_id"], args["slug"], rows=rows)
        if (prev is not None and prev.get("recorded_at") == args.get("recorded_at")
                and prev.get("verdict") == args.get("verdict")):
            applied.append(dict(last, already=True))      # committed before the queue was cut
            continue
        try:
            record(rows=rows, **args)
        except AcceptanceError as e:
            failed.append({"entry_id": eid, "error": str(e), "code": e.code,
                           "text_ru": e.text_ru, "items": items})
            continue
        applied.append(last)
    res["applied"] = [a["entry_id"] for a in applied]
    # CF-0738: an accepted verdict lands in its channel's _queue/ in the same commit
    by_id = {r.get("entry_id"): r for r in rows}
    queued = [q for q in (_queue_verdict(by_id[a["entry_id"]], rows, root, log.parent,
                                         (a.get("args") or {}).get("batch_dir"))
                          for a in applied if a["entry_id"] in by_id) if q]
    res["queued"] = queued
    res["conflicts"] = conflicts
    res["failed"] = [{"entry_id": f["entry_id"], "error": f["error"], "code": f["code"],
                      "text_ru": f["text_ru"]} for f in failed]
    if not applied:
        res["why"] = "ни один вердикт очереди не применился - очередь оставлена как есть"
        return res
    bys = sorted({a.get("by") or "?" for a in applied})
    if len(applied) == 1:
        a = applied[0]
        subject = f"Приёмка: {a['slug']} {VERDICT_RU.get(a['verdict'], a['verdict'])} ({a.get('by')})"
    else:
        subject = (f"Приёмка: {len(applied)} {_verdicts_word(len(applied))} из очереди "
                   f"после батча ({', '.join(bys)})")
    body = [f"Из очереди {PENDING_NAME} ({QUEUE_TASK}), записано после батча; "
            f"применил: {by}."]
    for a in applied:
        body.append(f"- {a['entry_id']}: {VERDICT_RU.get(a['verdict'], a['verdict'])} "
                    f"({a.get('by')}, в очереди с {a.get('queued_at')})")
    for c in conflicts:
        seq = "; ".join(f"{VERDICT_RU.get(v['verdict'], v['verdict'])} от {v['by']} в "
                        f"{v['queued_at']}" for v in c["verdicts"])
        body.append(f"Конфликт: {c['entry_id']} - в очереди {len(c['verdicts'])} "
                    f"{_verdicts_word(len(c['verdicts']))} ({seq}), последний побеждает: "
                    f"{VERDICT_RU.get(c['won'], c['won'])}.")
    for f in failed:
        body.append(f"Не применено, осталось в очереди: {f['entry_id']} - {f['error'][:300]}")
    for q in queued:
        if q["changed"]:
            body.append(f"Копилка ({QUEUE_FIX_TASK}): {q['entry_id']} -> {q['publish_path']}")
        elif q.get("left_out"):
            body.append(f"Не в копилке ({LEFT_OUT_TASK}): {q['entry_id']} - {q['code']}")
    res["left_out"] = [_left_out(q) for q in queued if q.get("left_out")]
    trailers = [f"Acceptance: {a['entry_id']}" for a in applied]
    message = subject + "\n\n" + "\n".join(body) + "\n\n" + "\n".join(trailers) + "\n"
    if all(a.get("already") for a in applied) and not any(q["changed"] for q in queued):
        sha = None                                       # nothing new for the record
    else:
        sha = _commit_log(root, log, rows, doc.get("note"), message)
    left = [i for f in failed for i in f["items"]]
    if left:
        tmp = qp.with_name(qp.name + ".tmp")
        tmp.write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in left),
                       encoding="utf-8")
        os.replace(tmp, qp)
    else:
        qp.unlink(missing_ok=True)
    res.update(committed=sha is not None, commit=sha, subject=subject, left=len(left))
    return res


def _drop_queued(qp, eid):
    """Take the queued verdicts of one video out of the queue (a verdict given
    after them, on the record now, has won)."""
    queue = read_pending(qp)
    keep = [i for i in queue if i["entry_id"] != eid]
    if len(keep) == len(queue):
        return
    if not keep:
        qp.unlink(missing_ok=True)
        return
    tmp = qp.with_name(qp.name + ".tmp")
    tmp.write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in keep),
                   encoding="utf-8")
    os.replace(tmp, qp)


def commit_pending(root=None, by="расписание", log=None, open_rows=None):
    """Apply the queue to the record through `record` and commit it as one
    commit - when no batch is going. Answers {committed, commit (sha or None),
    subject, applied [entry_id], conflicts [{entry_id, won, verdicts}], failed
    [{entry_id, error}] (they stay queued), left (queued after), why (None, or the
    words for nothing done: an empty queue, a batch going)}."""
    root, log, _rel = _where(root, log)
    with _queue_lock(log):
        return _commit_pending(root, log, by, open_now(root, open_rows))


def record_and_commit(channel, batch_id, slug, verdict, answer, by, root=None, log=None,
                      open_rows=None, **record_kw):
    """`_record_and_commit` (below), then CF-0925: when that verdict was the
    last one the batch waited for, one message of the batch's acceptance
    (`notify_acceptance`, never raises)."""
    res = _record_and_commit(channel, batch_id, slug, verdict, answer, by, root=root, log=log,
                             open_rows=open_rows, **record_kw)
    row = res.get("row") or {}
    try:
        r, lg, _rel = _where(root, log)
    except AcceptanceError:
        return res
    notify_acceptance(resolve_channel(row.get("channel") or channel, r),
                      row.get("batch_id") or batch_id,
                      root=r, log=lg, batch_dir=record_kw.get("batch_dir"))
    return res


def _record_and_commit(channel, batch_id, slug, verdict, answer, by, root=None, log=None,
                       open_rows=None, **record_kw):
    """`record` + `write_log`, and then: with no batch going, one commit of the
    record (`Приёмка: <slug> <вердикт> (<by>)`), after the queue has been applied
    (its own commit); under an open batch, the verdict into the queue instead -
    checked by `record` now against the record, so a refusal is said at once.
    `record_kw` are `record`'s keywords (`strict_topic` defaults to True, as the
    CLI's). Answers {row, pending, committed, commit, subject, queue (the queue's
    path, when queued), batches [{dir, why}] going, flushed (commit_pending's
    answer, or None), queued (`queue_accepted`'s answer, None for a rejection),
    left_out (CF-0821: an accepted video the копилка did not get - `_left_out`,
    also sent on the notification bus - or None)}. Raises `AcceptanceError`
    for a refused verdict or a commit
    git did not make (the record is then left as it was)."""
    root, log, rel = _where(root, log)
    kw = dict(record_kw)
    kw.setdefault("strict_topic", True)
    with _queue_lock(log):
        batches = open_now(root, open_rows)
        if batches:
            kw["answered_at"] = kw.get("answered_at") or _today()
            kw["recorded_at"] = kw.get("recorded_at") or _now()
            rows = copy.deepcopy(entries(log=read_log(log)))
            row = record(channel, batch_id, slug, verdict, answer, rows=rows, **kw)
            # CF-0738: the render goes into _queue/ now (a gitignored copy - the tree
            # stays clean); its path is written when the queue is committed. CF-0920:
            # under a batch nothing is committed, so a withdrawn namesake stays put
            queued = _queue_verdict(copy.deepcopy(row), rows, root, log.parent,
                                    kw.get("batch_dir"), move_reserve=False)
            item = {"entry_id": row["entry_id"], "slug": row["slug"], "verdict": verdict,
                    "by": by, "queued_at": _now(), "batches": [b["dir"] for b in batches],
                    "task": QUEUE_TASK,
                    "args": _jsonable(dict(kw, channel=channel, batch_id=batch_id, slug=slug,
                                           verdict=verdict, answer=answer)),
                    "row": row}
            qp = pending_path(log)
            with open(qp, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(item, ensure_ascii=False) + "\n")
            prow = dict(row, pending=True, queued_at=item["queued_at"], queued_by=by)
            return {"row": prow, "pending": True, "committed": False, "commit": None,
                    "subject": None, "queue": str(qp), "batches": batches, "flushed": None,
                    "queued": queued, "left_out": _left_out(queued)}
        flushed = (_commit_pending(root, log, by, []) if read_pending(pending_path(log))
                   else None)
        doc = read_log(log)
        rows = entries(log=doc)
        row = record(channel, batch_id, slug, verdict, answer, rows=rows, **kw)
        queued = _queue_verdict(row, rows, root, log.parent, kw.get("batch_dir"))
        subject = f"Приёмка: {row['slug']} {VERDICT_RU.get(verdict, verdict)} ({by})"
        body = [f"{row['entry_id']}: {VERDICT_RU.get(verdict, verdict)}"
                + (f" - {row['reason']} ({row['reason_code']})" if row.get("reason") else "")
                + f"; записал: {by} ({QUEUE_TASK})."]
        if queued and queued["changed"]:
            body.append(f"Копилка ({QUEUE_FIX_TASK}): {queued['publish_path']}")
        elif queued and queued.get("left_out"):
            body.append(f"Не в копилке ({LEFT_OUT_TASK}): {queued['code']}")
        if card_not_started(queued):
            body.append(f"Карточка ({CARD_BUILD_TASK}) не запущена: {card_not_started(queued)}")
        message = subject + "\n\n" + "\n".join(body) + f"\n\nAcceptance: {row['entry_id']}\n"
        sha = _commit_log(root, log, rows, doc.get("note"), message)
        _drop_queued(pending_path(log), row["entry_id"])   # the newer verdict wins
        return {"row": row, "pending": False, "committed": True, "commit": sha,
                "subject": subject, "queue": None, "batches": [], "flushed": flushed,
                "queued": queued, "left_out": _left_out(queued)}


def _left_out(q):
    """CF-0821: `{entry_id, slug, code, text_ru, alert_ru, notified}` of an
    accepted video the копилка did not get, or None."""
    if not q or not q.get("left_out"):
        return None
    return {k: q.get(k) for k in ("entry_id", "slug", "batch_id", "code", "text_ru",
                                  "alert_ru", "namesake", "notified")}


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="runlog acceptance",
        description="the user's acceptance of a video, recorded under the video's name "
                    "(CF-0328)")
    ap.add_argument("--log", default=None, help="the record to read/write "
                                                "(default publish/acceptance-log.json)")
    ap.add_argument("--publish-dir", default=None)
    ap.add_argument("--holds", default=None,
                    help="the CF-0318 hold registry --state and --check read "
                         "(default publish/publication-holds.json; CF-0683)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--ask", metavar="CHANNEL/BATCH", default=None,
                    help="the question to show the user, one named file per line")
    ap.add_argument("slugs", nargs="*", help="video names for --ask")
    ap.add_argument("--record", metavar="CHANNEL/BATCH/SLUG", default=None)
    ap.add_argument("--notify", metavar="CHANNEL/BATCH", default=None,
                    help="CF-0925: send the batch's acceptance message now (videos still "
                         "waiting are named in it)")
    ap.add_argument("--verdict", choices=VERDICTS, default=None)
    ap.add_argument("--answer", default=None,
                    help="what the user said; it must name the video")
    ap.add_argument("--reason", default=None, help="one phrase, for a rejection")
    ap.add_argument("--reason-code", default=None, help="the dictionary key of the reason")
    ap.add_argument("--checkable-by", choices=CHECKS, default=None)
    ap.add_argument("--covered-by", default=None,
                    help="the machine check that already claims this reason")
    ap.add_argument("--topic", default=None, help="topic_id, for the CF-0318 hold")
    ap.add_argument("--date", default=None, help="the day the user answered (YYYY-MM-DD)")
    ap.add_argument("--note", default=None)
    ap.add_argument("--batch-dir", default=None,
                    help="where the batch's 05-video-editor.json is, for code_shas "
                         "(default pipeline/CHANNEL/BATCH)")
    ap.add_argument("--amend", default=None, metavar="WHY",
                    help="the user changed his verdict; the old one moves into history")
    ap.add_argument("--reasons", action="store_true", help="the dictionary of refusals")
    ap.add_argument("--channel-keys", action="store_true",
                    help="rows whose entry_id was frozen under a channel name that has "
                         "since been renamed; reported, never rewritten (CF-0197)")
    ap.add_argument("--check", action="store_true",
                    help="read publish/ back against the record; exit 1 on a problem")
    ap.add_argument("--state", metavar="CHANNEL/BATCH/SLUG", default=None,
                    help="one video: the verdict and the CF-0318 hold; exit 1 when it is "
                         "not publishable")
    ap.add_argument("--backfill-topics", action="store_true",
                    help="fill topic_id on the rows that have none from their batches "
                         "(CF-0544); a dry run unless --write")
    ap.add_argument("--write", action="store_true",
                    help="commit a --record or --backfill-topics to the file")
    ap.add_argument("--commit", action="store_true",
                    help="with --record --write: one git commit of the record in the "
                         "factory root, or - under an open batch - the verdict into the "
                         "queue publish/acceptance-pending.jsonl (CF-0675)")
    ap.add_argument("--commit-pending", action="store_true",
                    help="apply the queue to the record and commit it, unless a batch "
                         "is going (CF-0675)")
    ap.add_argument("--by", default="терминал",
                    help="who gave the verdict, for the commit message (CF-0675)")
    ap.add_argument("--enqueue-accepted", action="store_true",
                    help="CF-0738: put every accepted video with no place in publish/ into "
                         "its channel's _queue/ - a dry run unless --apply (--by, --via)")
    ap.add_argument("--apply", action="store_true", help="with --enqueue-accepted")
    ap.add_argument("--entry", action="append", default=None, metavar="CHANNEL/BATCH/SLUG",
                    help="with --enqueue-accepted: only this row (repeatable)")
    ap.add_argument("--other-version-ok", action="store_true",
                    help="with --enqueue-accepted --entry: a new video under an old name - "
                         "place it although another version of the name is placed")
    ap.add_argument("--via", default=None, help="with --enqueue-accepted --apply: through what")
    ap.add_argument("--base-sha256", default=None,
                    help="with --enqueue-accepted --apply: the record's sha256 as read")
    ap.add_argument("--root", default=None,
                    help="the factory root the record is committed in (default "
                         "$FACTORY_ROOT, else this checkout)")
    ns = ap.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        doc = read_log(ns.log)
        rows = entries(log=doc)
        if ns.ask:
            channel, batch_id = parse_key(ns.ask, parts=2)
            lines = question(channel, batch_id, ns.slugs, batch_dir=ns.batch_dir)
            print(json.dumps(lines, ensure_ascii=False, indent=2) if ns.json
                  else "\n".join(lines))
            return 0
        if ns.enqueue_accepted:
            res = repair_queue(root=ns.root, log=ns.log, publish_dir=ns.publish_dir,
                               apply=ns.apply, by=ns.by, via=ns.via,
                               base_sha256=ns.base_sha256, only=ns.entry,
                               other_version_ok=ns.other_version_ok)
            if ns.json:
                print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
            else:
                print("\n".join(res["lines"]) or "every accepted video has its place")
                for r in res["refusals"]:
                    print(f"REFUSED {r['code']}: {r['line']}")
                print(f"committed {res['commit']}" if res["commit"] else
                      "(dry run: pass --apply --by WHO --via WHAT)" if res["dry_run"] else
                      "nothing committed")
            return 0 if res["ok"] else 1
        if ns.notify:
            channel, batch_id = parse_key(ns.notify, parts=2)
            res = notify_acceptance(channel, batch_id, root=ns.root, log=ns.log,
                                    batch_dir=ns.batch_dir, force=True)
            if ns.json:
                print(json.dumps(res, ensure_ascii=False, indent=2))
            else:
                print(f"{res.get('status')}: {res.get('key') or ''}".rstrip())
                if res.get("text"):
                    print(res["text"])
            return 0 if res.get("status") in ("sent", "duplicate") else 1
        if ns.commit_pending:
            res = commit_pending(root=ns.root, by=ns.by, log=ns.log)
            if ns.json:
                print(json.dumps(res, ensure_ascii=False, indent=2))
            else:
                print(f"committed {res['commit']}: {res['subject']}" if res["committed"]
                      else f"nothing committed: {res['why']}")
                for f in res["failed"]:
                    print(f"left in the queue {f['entry_id']}: {f['error']}")
            return 0
        if ns.record and ns.commit:
            channel, batch_id, slug = parse_key(ns.record)
            if not ns.verdict:
                raise AcceptanceError("--record needs --verdict accepted|rejected",
                                     code="cli_needs_verdict")
            if not ns.write:
                raise AcceptanceError("--commit writes the record: pass --write too",
                                     code="cli_commit_needs_write")
            res = record_and_commit(
                channel, batch_id, slug, ns.verdict, ns.answer, by=ns.by, root=ns.root,
                log=ns.log, reason=ns.reason, reason_code=ns.reason_code,
                checkable_by=ns.checkable_by, covered_by=ns.covered_by, topic_id=ns.topic,
                answered_at=ns.date, note=ns.note, amend=ns.amend, batch_dir=ns.batch_dir)
            if ns.json:
                print(json.dumps(res, ensure_ascii=False, indent=2))
            else:
                print("\n".join(render([res["row"]])))
                if res["pending"]:
                    print(f"queued in {res['queue']}: a batch is going "
                          f"({res['batches'][0]['dir']}) - committed after it")
                else:
                    print(f"committed {res['commit']}: {res['subject']}")
            return 0
        if ns.record:
            channel, batch_id, slug = parse_key(ns.record)
            if not ns.verdict:
                raise AcceptanceError("--record needs --verdict accepted|rejected",
                                     code="cli_needs_verdict")
            row = record(channel, batch_id, slug, ns.verdict, ns.answer, rows=rows,
                         reason=ns.reason, reason_code=ns.reason_code,
                         checkable_by=ns.checkable_by, covered_by=ns.covered_by,
                         topic_id=ns.topic, answered_at=ns.date, note=ns.note,
                         amend=ns.amend, batch_dir=ns.batch_dir, strict_topic=True)
            queued = None
            if ns.write:
                # CF-0738: an accepted video goes into its channel's _queue/ now
                queued = _queue_verdict(row, rows, ns.root,
                                        ns.publish_dir or Path(ns.log or default_log()).parent,
                                        ns.batch_dir, move_reserve=False)
                write_log(rows, path=ns.log, note=doc.get("note"))
                notify_acceptance(resolve_channel(row.get("channel") or channel, ns.root),
                                  row.get("batch_id") or batch_id,
                                  root=ns.root, log=ns.log, batch_dir=ns.batch_dir)
            if ns.json:
                print(json.dumps(row, ensure_ascii=False, indent=2))
            else:
                print("\n".join(render([row])))
                if not ns.write:
                    print("(not written: pass --write)")
                if queued:
                    print(f"queue {queued['code']}: {queued['text_ru']}")
                if card_not_started(queued):
                    print(f"card not started: {card_not_started(queued)}")
            return 0
        if ns.backfill_topics:
            filled, left = backfill_topics(rows)
            if ns.write and filled:
                write_log(rows, path=ns.log, note=doc.get("note"))
            if ns.json:
                print(json.dumps({"filled": filled, "left": left, "written": bool(
                    ns.write and filled)}, ensure_ascii=False, indent=2))
            else:
                for f in filled:
                    print(f"fill  {f['entry_id']}: topic_id {f['topic_id']} ({f['source']})")
                for l in left:
                    print(f"left  {l['entry_id']}: {l['why']}")
                print(f"{len(filled)} row(s) to fill, {len(left)} left without a topic"
                      + ("" if ns.write else " (dry run: pass --write)"))
            return 0
        if ns.state:
            channel, batch_id, slug = parse_key(ns.state)
            # CF-0875: like --check (CF-0870), the state reads a verdict still
            # waiting in the queue of CF-0675 - a video accepted during a batch
            # is shown with its verdict, marked pending, not as one with none
            st = state(channel, batch_id, slug, rows=with_pending(rows, pending_path(ns.log)),
                       holds_path=ns.holds)
            if ns.json:
                print(json.dumps(st, ensure_ascii=False, indent=2))
            else:
                held_bit = f", held by {st['hold_id']}" if st["held"] else ""
                pending_bit = (f" (pending since {st['queued_at']}: committed after the batch)"
                               if st["pending"] else "")
                print(f"{st['slug']}: {st['verdict'] or 'no verdict'}{pending_bit}{held_bit} -> "
                      f"{'publishable' if st['publishable'] else 'not publishable'} "
                      f"({st['upload']})")
            return 0 if st["publishable"] else 1
        if ns.check:
            # CF-0870: a verdict given under a batch waits in the queue of
            # CF-0675 while its video already lies in `_queue/` (CF-0738); the
            # check reads it as the module's readers do (`entries`), or a
            # verdict given during a batch reads as a video with none
            res = check(rows=with_pending(rows, pending_path(ns.log)),
                        publish_dir=ns.publish_dir, holds_path=ns.holds)
            if ns.json:
                print(json.dumps(res, ensure_ascii=False, indent=2))
            else:
                for h in res["held"]:
                    print(f"held  {h['slug']}: {h['detail']} ({h['hold_id']})")
                for p in res["problems"]:
                    print(f"PROBLEM {p['slug']}: {p['detail']}")
                for n in res.get("no_topic") or []:
                    print(f"no-topic {n['entry_id']} ({n['verdict']}): {n['detail']}")
                for g in res.get("archived") or []:
                    print(f"archived {g['slug']}: {g['detail']}")
                for n in res.get("layout") or []:
                    print(f"layout  {n['slug']}: {n['detail']}")
                for w in res.get("pending") or []:
                    print(f"pending {w['entry_id']}: {w['detail']}")
                if not res["problems"]:
                    print(f"publish/ agrees with the record "
                          f"({len(publish_slugs(ns.publish_dir))} video(s) there)")
            return 1 if res["problems"] else 0
        if ns.channel_keys:
            stale = stale_channel_keys(rows=rows)
            if ns.json:
                print(json.dumps(stale, ensure_ascii=False, indent=2))
            elif not stale:
                print(f"every row's entry_id names a channel under its current id "
                      f"({len(rows)} row(s)) - nothing to migrate")
            else:
                for s in stale:
                    print(f"{s['entry_id']} reads as {s['reads_as']} "
                          f"({s['slug']}, {s['answered_at']}) - found under both, "
                          f"the file is not rewritten")
            return 0
        if ns.reasons:
            if ns.json:
                print(json.dumps({"reasons": reasons(rows=rows),
                                  "candidates": candidates(rows=rows)},
                                 ensure_ascii=False, indent=2))
            else:
                print("\n".join(render_reasons(rows=rows)))
            return 0
        if ns.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        else:
            print("\n".join(render(rows)) or "no verdict recorded yet")
        return 0
    except AcceptanceError as e:
        sys.stderr.write(f"runlog acceptance: error: {e}\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
