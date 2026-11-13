"""CC-0066: the publication writes that may reach beyond this machine - the
API-upload switch, the upload through the YouTube Data API and the Studio
record - each a plan (read only) and a confirm, as the writes of
`api/publish.py` (CC-0065): the same token store (`batches._issue` /
`_spend`, single use, CONFIRM_TTL), the same one-write-at-a-time lock and
re-check (`publish._confirm`), the same refusals. Only through the factory's
own functions:

    agents/publisher/api_switch.py     read, channel_state, no_pipeline,
                                       warnings, set_switch (CF-0607)
    agents/publisher/upload.py         run - with `dry_run` in the plan, for
                                       real in the confirm (CF-0421/CF-0607:
                                       `switch_gate`, `card_gate` and every
                                       gate of `upload_gate` are its own)
    agents/publisher/studio_fields.py  locate, verify, record (CF-0018)

**What goes out.** The switch is a local file (`schedule/api-upload.json`);
its warnings read the publisher's `.env`, the token's file
(`publisher_auth.status` - never the network) and the tick's timer. The
upload is the only thing here that talks to Google: `upload.run` asks its
`client_factory` for a client - `upload.default_client` in production
(`publisher_auth.load_credentials`, which may refresh the token over the
network, and `youtube_client.YouTubeClient`: `channels.list`,
resumable `videos.insert`). The plan runs it with `dry_run` and a client
factory that refuses to be called, so a plan never reaches Google. The
Studio record writes the journal (`publish/uploads.json`) and the ledger's
publication columns - `studio_fields.record` sends no notification (its
bus, `shared/notify.py`, is called by `studio_fields.py prepare` from the
command line, `notify_upload`; never here).

**The switch** (`api_upload_switch`): `set_switch(channel, on, by=user,
note=«… (из центра)»)`. The plan says the state now, the row it writes and -
turning it on - `warnings(...)`: what is not ready yet (the OAuth app in
Testing, the tick's timer, the token); none of them refuses, it is the
user's call. Turning it on takes a note in the plan (where and when the user
decided, after the audit - CF-0470) and, in the confirm, the words
`AUDIT_PHRASE` typed by the user (`audit`); without them 422
`audit_unconfirmed`, nothing written. Turning it off takes neither.

**The upload** (`api_upload`): the plan is `api_switch.check` (off: the
factory's line, no token) and `upload.run(dry_run=True)` - the note, its
claim check, the acceptance, the holds, the switch, the card, the slot, the
pause, the journal, the video file - with the summary the user is shown
(`summary`) and the Terms notice (`tos_notice`, CF-0618). The confirm takes
the user's own answer (`answer`: «да» - `upload_gate.YES`); anything else is
422 `answer_required` before the token is spent. The answer stands in for
the terminal `upload_gate.ask_user` reads: the summary and the notice are
written to it, the answer read from it, and the factory makes its own
`Confirmation` - there is no other way to one. Then `upload.run` for real,
with `FACTORY_KW["client_factory"]` (the tests' stand-in) or the factory's
default. The run holds the publication write lock for as long as it takes.

**The Studio record** (`studio_record`): `studio_fields.verify` and
`record(dry_run=True)` in the plan (the mismatches, the row it would add),
`record` in the confirm - the row (`source: studio`, `user_edited: false`)
and the ledger's columns; the streak after it.

**The hand edit** (`studio_edited`, CC-0106): the user corrected a field of a
Studio video by hand (`studio_fields.py edited`) - or, the undo
(`studio_edited_undo`, `edited --undo`), the mark was wrong. The factory's
one writer is `upload_records.mark_user_edited(video_id | slug, channel,
edited, note, by, via, dry_run)`; the plan is its own dry run (CF-0720,
`dry_run=True`: the row as the mark would leave it, nothing written) on the
journal itself - which row answers, its refusal (no row, two live rows of
the slug, not a
`studio` row: the factory's line, no token), the row as it would be, the
streak after it (`studio_fields.streak`). A row of another channel than the
route's is refused; a row already so (marked / not marked) has nothing to
change. The confirm makes the same dry run (the journal's bytes, the row
before, the row after but its time - else `check_changed`), then
`mark_user_edited` on the journal itself. Who and from where go on the row
(`by="user", via="center"` -> `user_edited_by` / `user_edited_via`, the
mark's and the undo's alike); `user_edit_note` is the user's note as given
(none given: the factory keeps the row's note on a mark, drops it on an
undo). The journal is not a file a running batch reads (its readers are
the publisher, the analyst, the tick, the dashboard, pool-release), as for
the Studio record: no open-batch refusal.

`FACTORY_KW` is `api/publish.py`'s (`now`, `env_file`, `environ`, `timer`,
and here `client_factory`, `sleep`) - empty in production.
"""
import io
import re
import time
from argparse import Namespace
from pathlib import Path

from . import batches, factory
from .batches import SAFE_NAME, BatchFault, _channel
from . import paths as _cut
from .publish import (ACCEPTANCE_LOG, FACTORY_KW, HOLDS, JOURNAL, PUBLISH_DIR,
                      WRITE_BY, _col, _confirm, _contained, _file_sha, _iso, _issue_plan, _jsonable, _marked,
                      _now, _pq, _rel, card_scope, named_note)

PAUSES = "channel-pauses.json"           # = channel_pause's registry
README = "README.md"                     # = upload_records.README
#: What the plan says before the answer - `upload_gate.ask_user`'s question.
QUESTION = "Загрузить этот ролик? Введите «да»"

#: The words that turn the API upload on - typed by the user in the confirm.
AUDIT_PHRASE = "аудит подтверждаю"
ACTIONS = {
    "api_upload_switch": ("план переключения API-загрузки", "переключатель не тронут",
                          "переключения API-загрузки канала"),
    "api_upload": ("план загрузки через API", "ничего не загружено", "загрузки через API канала"),
    "studio_record": ("план записи загрузки из Studio", "запись не сделана",
                      "записи загрузки из Studio канала"),
    # CC-0106: the user's hand edit of a Studio video, and its undo
    "studio_edited": ("план отметки ручной правки", "отметка не поставлена",
                      "отметки ручной правки канала"),
    "studio_edited_undo": ("план снятия отметки ручной правки", "отметка не снята",
                           "снятия отметки ручной правки канала"),
}
batches.register_actions(ACTIONS)


def _words(text):
    return re.sub(r"\s+", " ", str(text or "")).strip().lower().replace("ё", "е")


def _kw():
    return (FACTORY_KW.get("env_file"), FACTORY_KW.get("environ"), FACTORY_KW.get("timer"))


def _broken(e):
    return BatchFault(500, "factory_broken", f"Фабрика ответила ошибкой: {e}",
                      [f"{type(e).__name__}: {e}"])


# ---------------------------------------------------------------- the API-upload switch
def _switch_check(root, cid, bound):
    sw = _col().api_switch()
    env_file, environ, timer = _kw()
    on = bool(bound.get("on"))
    note = (bound.get("note") or "").strip()
    if on and not note:
        raise BatchFault(422, "note_required", "Включение API-загрузки - с заметкой: где и когда "
                                               "вы так решили (после аудита YouTube API, "
                                               "CF-0470).",
                         ["api_switch.set_switch: --note is required to turn it on"])
    doc = sw.read(root, environ)
    st = sw.channel_state(cid, root, environ, doc)
    if doc.get("error"):
        raise BatchFault(409, "switch_unreadable", st["line"], [f"{doc['path']}: {doc['error']}"])
    stub = sw.no_pipeline(cid, root)
    why, warn = None, None
    if on and stub:
        why = f"{cid}: {stub} - API-загрузке нечего грузить (CF-0562)."
    elif st["on"] == on:
        why = f"API-загрузка {cid} уже {'включена' if on else 'выключена'} - менять нечего."
    if on and why is None:
        try:
            warn = sw.warnings(cid, root, env_file, environ, _now(_pq()), timer)
        except Exception as e:                                  # noqa: BLE001
            raise _broken(e) from e
    row = {"channel": cid, "on": on, "by": WRITE_BY, "note": _marked(note)}
    out = {"ok": why is None, "why": why, "on": on, "state": st, "line": st["line"], "row": row,
           "warnings": warn, "audit_phrase": AUDIT_PHRASE if on else None,
           "path": _rel(root, sw.state_path(root, environ))}
    facts = {"action": "api_upload_switch", "channel": cid, "row": row, "warnings": warn,
             "state": {k: st.get(k) for k in ("on", "at", "by", "note")},
             "history": len(st.get("history") or []), "stub": stub, "ok": why is None}
    return out, facts


def api_upload_switch_plan(root, channel, on, note=None):
    """What «включить / выключить API-загрузку» would write: the state now, the
    row (by WRITE_BY, the note marked «из центра»), on enable the warnings and
    the words the confirm takes. Nothing written."""
    cid = _channel(root, channel)
    bound = {"on": bool(on), "note": note}
    out, facts = _switch_check(root, cid, bound)
    return _issue_plan(root, "api_upload_switch", cid, out, facts, bound)


def api_upload_switch(root, channel, token, audit=None):
    """The confirmed switch: `api_switch.set_switch(by=WRITE_BY)`; turning it
    on only with AUDIT_PHRASE in `audit`."""
    cid = _channel(root, channel)
    sw = _col().api_switch()
    env_file, environ, timer = _kw()

    def act(b):
        on = bool(b.get("on"))
        if on and _words(audit) != _words(AUDIT_PHRASE):
            raise BatchFault(422, "audit_unconfirmed",
                             f"API-загрузка включается только после аудита YouTube API: "
                             f"напишите «{AUDIT_PHRASE}». Переключатель не тронут - запросите "
                             f"план заново.",
                             [f"audit {audit!r} is not {AUDIT_PHRASE!r}; the token is spent"])
        got = sw.set_switch(cid, on, WRITE_BY, _marked(b.get("note")), root=root,
                            now=FACTORY_KW.get("now"), environ=environ, env_file=env_file,
                            timer=timer)
        return {"action": "api_upload_switch", "channel": cid, "on": on,
                "changed": got["changed"], "warnings": got["warnings"], "state": got["state"]}
    return _confirm(root, cid, "api_upload_switch", token,
                    lambda b: _switch_check(root, cid, b), act, (sw.SwitchError,))


# ---------------------------------------------------------------- a placed note
def _locate(root, cid, slug, day, batch_id=None):
    """`publish/<channel>/<day>/<file>.md` of a request (`publish.named_note`: as
    `studio_fields.locate` finds it, or by its batch, CC-0182) - `(path, bucket, slug)`;
    404 `unknown_note`, 409 `namesakes`."""
    want, _ch, bucket, s = named_note(root, cid, slug, day, batch_id,
                                      (factory.publish_layout().QUEUE,))
    return want, bucket, s


def _paths(root):
    """What `upload.run` reads and writes, all under the root's publish/ - none
    left to the factory's defaults (its own checkout)."""
    pub = _contained(root, PUBLISH_DIR, code="unknown_note", what="publish/")
    return {"publish": pub, "log": pub / ACCEPTANCE_LOG, "holds": pub / HOLDS,
            "journal": pub / JOURNAL, "readme": pub / README}


# ---------------------------------------------------------------- the upload
def _no_client(*_a, **_k):
    """The plan's client factory: a dry run stops before the credentials."""
    raise BatchFault(500, "factory_broken", "Сухой прогон загрузки попросил клиент YouTube - "
                                            "ничего не отправлено.",
                     ["upload.run(dry_run=True) called its client_factory"])


class _Said:
    """The terminal `upload_gate.ask_user` writes the summary and the Terms
    notice to and reads the answer from: the answer the user typed in the
    center (the confirm's `answer`)."""

    def __init__(self, answer):
        self.answer, self.shown = str(answer or ""), ""

    def write(self, text):
        self.shown += text

    def flush(self):
        pass

    def readline(self):
        return self.answer + "\n"

    def close(self):
        pass


def _upload_errors(up):
    return (up.Refused, up.publish_note.NoteError, up.upload_gate.GateError,
            up.publisher_config.ConfigError, up.publisher_auth.AuthError,
            factory.publish_layout().LayoutError, ValueError)


def _args(note, bound, dry_run):
    return Namespace(note=str(note), entry=bound.get("entry"), publish_at=None, dry_run=dry_run,
                     authorize=False, env=FACTORY_KW.get("env_file"))


def _upload_check(root, cid, bound):
    up, sw = factory.upload(), _col().api_switch()
    note, bucket, slug = _locate(root, cid, bound.get("slug"), bound.get("day"),
                                 bound.get("batch_id"))
    paths = _paths(root)
    environ = FACTORY_KW.get("environ")
    now = _now(_pq())
    st = sw.channel_state(cid, root, environ)
    out = {"ok": False, "why": None, "slug": slug, "day": bucket, "note": _rel(root, note),
           "video": _rel(root, note.with_suffix(".mp4")), "entry_id": None, "switch": st,
           "dry_run": [], "summary": None, "body": None, "tos_notice": None, "question": None,
           "channel_id": None, "token": None, "publish_at": None}
    facts = {"action": "api_upload", "channel": cid, "note": _file_sha(note),
             "switch": {k: st.get(k) for k in ("on", "at", "by")}}
    try:
        sw.check(cid, root, environ)
    except sw.SwitchError as e:
        out["why"] = str(e)
        return out, dict(facts, why=out["why"])
    buf = io.StringIO()
    try:
        up.run(_args(note, bound, True), client_factory=_no_client, terminal=_Said(""),
               paths=paths, now=now, sleep=lambda _s: None, out=buf)
        row = up.upload_gate.resolve_entry(slug, entry=bound.get("entry"), log_path=paths["log"])
        meta = up.publish_note.parse(note)
        cfg = up.publisher_config.load(FACTORY_KW.get("env_file"))
    except _upload_errors(up) as e:
        out.update(why=str(e), dry_run=buf.getvalue().splitlines())
        return out, dict(facts, why=out["why"], dry_run=out["dry_run"])
    video = note.with_suffix(".mp4")
    body = up.build_body(meta, meta["publish_at"], cfg.category_id, cfg.language)
    why = None
    if not cfg.channel_id:
        why = ("PUBLISHER_CHANNEL_ID пуст - загрузка должна знать, для какого канала она "
               "(agents/publisher/.env).")
    elif not paths["readme"].is_file():
        why = (f"{_rel(root, paths['readme'])} нет - запись загрузки туда не ляжет; загрузка "
               f"не начинается.")
    out.update(ok=why is None, why=why, entry_id=row.get("entry_id"),
               dry_run=buf.getvalue().splitlines(),
               summary=up.summary(row, video, body, cfg.channel_id), body=body,
               tos_notice=up.upload_gate.TOS_NOTICE, question=QUESTION,
               channel_id=cfg.channel_id, token=up.publisher_auth.status(cfg, now).line,
               publish_at=body["status"]["publishAt"])
    stat = video.stat()
    facts.update(why=why, entry_id=out["entry_id"], summary=out["summary"], body=body,
                 video={"size": stat.st_size, "mtime_ns": stat.st_mtime_ns},
                 files={k: _file_sha(paths[k]) for k in ("log", "holds", "journal")},
                 pauses=_file_sha(paths["publish"] / PAUSES))
    return out, facts


def api_upload_plan(root, channel, slug, day=None, entry=None, batch_id=None):
    """What «загрузить через API» would do: the switch on (`api_switch.check`),
    then `upload.run(dry_run=True)` - every gate of the factory, no
    credentials, no client - with the summary and the Terms notice the user is
    shown before his «да». Nothing written, nothing sent. CC-0182: `batch_id` names the
    video and its acceptance row (the factory's `--entry CHANNEL/BATCH/SLUG`)."""
    cid = _channel(root, channel)
    if batch_id and entry and entry != f"{cid}/{batch_id}/{slug}":
        raise BatchFault(422, "invalid", "entry и batch_id называют разные ролики - укажите одно.",
                         [f"entry {entry!r}, batch_id {batch_id!r}"])
    bound = {"slug": slug, "day": day, "entry": entry or (f"{cid}/{batch_id}/{slug}" if batch_id
                                                          else None), "batch_id": batch_id}
    out, facts = _upload_check(root, cid, bound)
    return _issue_plan(root, "api_upload", cid, out, facts, bound)


def api_upload(root, channel, token, answer=None):
    """The confirmed upload: the user's «да» (`answer`) as the terminal's
    answer, then `upload.run` for real - its switch gate and card gate, the
    client (`FACTORY_KW["client_factory"]`, else the factory's own), the
    journal row, the note, the README, the ledger."""
    cid = _channel(root, channel)
    up = factory.upload()
    if _words(answer) not in {_words(y) for y in up.upload_gate.YES}:
        raise BatchFault(422, "answer_required", "Загрузка - только после вашего «да»: прочитайте "
                                                 "сводку и условия YouTube и напишите «да».",
                         [f"answer {answer!r} is not one of upload_gate.YES; the token is not "
                          f"spent, nothing was called"])

    def act(b):
        note, _bucket, slug = _locate(root, cid, b.get("slug"), b.get("day"), b.get("batch_id"))
        paths = _paths(root)
        said, buf = _Said(answer), io.StringIO()
        try:
            rc = up.run(_args(note, b, False), client_factory=FACTORY_KW.get("client_factory"),
                        terminal=said, paths=paths, now=_now(_pq()),
                        sleep=FACTORY_KW.get("sleep") or time.sleep, out=buf)
        except up.publisher_auth.ReauthorizeRequired as e:
            raise BatchFault(409, "reauthorize", f"Токен YouTube надо переразрешить - ничего не "
                                                 f"загружено: {e}",
                             [f"{type(e).__name__}: {e}", "python3 agents/publisher/upload.py "
                                                          "--authorize (the user, at the "
                                                          "terminal)"]) from e
        except up.youtube_client.UploadError as e:
            raise BatchFault(409, "upload_failed", f"YouTube не принял загрузку: {e}",
                             [f"{type(e).__name__}: {e}", *buf.getvalue().splitlines()]) from e
        lines = buf.getvalue().splitlines()
        if rc != 0:
            raise BatchFault(500, "uploaded_unrecorded",
                             "Ролик загружен, но запись о загрузке не легла - внесите её по "
                             "строкам ниже, прежде чем что-то повторять.", lines)
        entry = up.upload_gate.resolve_entry(slug, entry=b.get("entry"), log_path=paths["log"])
        rows = [r for r in up.upload_records.uploads(paths["journal"])
                if r.get("entry_id") == entry.get("entry_id") and r.get("source") == "api"]
        return {"action": "api_upload", "channel": cid, "slug": slug,
                "row": rows[-1] if rows else None, "lines": lines, "shown": said.shown}

    def message(_b, answer):
        vid = (answer.get("row") or {}).get("video_id")
        return (f"Публикация: {answer['slug']} загружен через API" + (f" ({vid})" if vid else "")
                + f" ({WRITE_BY}, center)",
                "CC-0153: загрузка через API из центра (publish_net.api_upload, upload.run) - "
                "журнал загрузок, заметка, README, леджер.")
    return _confirm(root, cid, "api_upload", token, lambda b: _upload_check(root, cid, b), act,
                    _upload_errors(up), commit=(card_scope(cid), message, "Ролик загружен"))


# ---------------------------------------------------------------- the Studio record
def _record_check(root, cid, bound):
    sf, jr = factory.studio_fields(), _col().journal()
    note, bucket, slug = _locate(root, cid, bound.get("slug"), bound.get("day"),
                                 bound.get("batch_id"))
    paths = _paths(root)
    read, vid, replaces = bound.get("read") or {}, bound.get("video_id"), bound.get("replaces")
    mism, status, row, why = [], None, None, None
    try:
        _fields, mism = sf.verify(str(note), read, root, cid, bucket, _now(_pq()))
        if not mism:
            res = sf.record(str(note), vid, read, root, cid, bucket, _now(_pq()),
                            replaces=replaces, dry_run=True)
            status, row = res["status"], _jsonable(res["row"])
    except (sf.FieldsError, jr.JournalError) as e:
        why = str(e)
    if mism:
        why = ("Studio показывает не то, что в карточке - ничего не записано: "
               + "; ".join(m["field"] for m in mism) + ". Скажите пользователю до слота.")
    elif why is None and status != "would-add":
        why = f"{slug}: {vid} уже в журнале ({status}) - записывать нечего."
    out = {"ok": why is None, "why": why, "slug": slug, "day": bucket, "note": _rel(root, note),
           "video_id": vid, "replaces": replaces, "mismatches": _jsonable(mism),
           "status": status, "row": row}
    facts = dict(out, row={k: v for k, v in (row or {}).items() if k != "recorded_at"},
                 note_sha=_file_sha(note), read=read,
                 files={k: _file_sha(paths[k]) for k in ("log", "holds", "journal")})
    return out, facts


def studio_record_plan(root, channel, slug, video_id, read, day=None, replaces=None,
                       batch_id=None):
    """What «записать загрузку из Studio» would write: `studio_fields.verify`
    of what Studio shows against the card (the mismatches), then
    `record(dry_run=True)` - the journal row it would add. Nothing written."""
    cid = _channel(root, channel)
    if not isinstance(read, dict):
        raise BatchFault(422, "invalid", "Прочитанное из Studio - объект JSON (title, "
                                         "description, tags, visibility, schedule ...).",
                         [f"read is {type(read).__name__}"])
    bound = {"slug": slug, "day": day, "video_id": video_id, "read": read, "replaces": replaces,
             "batch_id": batch_id}
    out, facts = _record_check(root, cid, bound)
    return _issue_plan(root, "studio_record", cid, out, facts, bound)


def studio_record(root, channel, token):
    """The confirmed record: `studio_fields.record` - the row (source studio,
    user_edited false) and the ledger's publication columns; the streak."""
    cid = _channel(root, channel)
    sf, jr = factory.studio_fields(), _col().journal()

    def act(b):
        note, bucket, slug = _locate(root, cid, b.get("slug"), b.get("day"), b.get("batch_id"))
        res = sf.record(str(note), b["video_id"], b.get("read") or {}, root, cid, bucket,
                        _now(_pq()), replaces=b.get("replaces"))
        rows = jr.uploads(_paths(root)["journal"])
        return {"action": "studio_record", "channel": cid, "slug": slug,
                "status": res["status"], "row": _jsonable(res["row"]),
                "ledger": _jsonable(res["ledger"]), "streak": sf.streak(rows, cid)}

    def message(b, answer):
        return (f"Публикация: {answer['slug']} записан из Studio ({b['video_id']}) "
                f"({WRITE_BY}, center)",
                "CC-0153: запись загрузки через Studio из центра (publish_net.studio_record, "
                "studio_fields.record) - журнал загрузок, леджер.")
    return _confirm(root, cid, "studio_record", token, lambda b: _record_check(root, cid, b),
                    act, (sf.FieldsError, jr.JournalError),
                    commit=(card_scope(cid), message, "Загрузка записана"))


# ---------------------------------------------------------------- the hand edit (CC-0106)
def _edit_name(bound):
    vid, slug = (bound.get("video_id") or "").strip(), (bound.get("slug") or "").strip()
    if bool(vid) == bool(slug):
        raise BatchFault(422, "invalid", "Назовите ролик: его id в Studio (video_id) или slug - "
                                         "одно из двух.",
                         ["mark_user_edited: --video-id ID or --slug SLUG, exactly one"])
    if slug and not SAFE_NAME.match(slug):
        raise BatchFault(422, "invalid", f"«{slug}» - не slug ролика.", [f"{slug!r}: not a slug"])
    return vid or None, slug or None


EDIT_BY, EDIT_VIA = WRITE_BY, "center"


def _note(text):
    """The user's note as the factory stores it - None when none was given."""
    return (text or "").strip() or None


def _edit_mark(jr, journal, vid, slug, cid, edited, note, dry_run):
    now = _iso(_now(_pq())) if FACTORY_KW.get("now") else None
    return jr.mark_user_edited(vid, slug, cid, edited=edited, note=note, path=journal, now=now,
                               by=EDIT_BY, via=EDIT_VIA, dry_run=dry_run)


def _edit_dry(jr, journal, vid, slug, cid, edited, note):
    """The factory's own dry run (`mark_user_edited(dry_run=True)`, CF-0720) on
    the journal - nothing written: (row before, row after, the rows after) -
    or its JournalError."""
    after = dict(_edit_mark(jr, journal, vid, slug, cid, edited, note, True))
    rows = jr.uploads(journal)
    key = (after.get("video_id"), after.get("recorded_at"))
    before = next((r for r in rows if (r.get("video_id"), r.get("recorded_at")) == key), None)
    return (dict(before) if before else None), after, [after if r is before else r for r in rows]


def _edited_check(root, cid, bound):
    jr, sf = _col().journal(), factory.studio_fields()
    journal = _paths(root)["journal"]
    edited = bool(bound.get("edited"))
    vid, slug = _edit_name(bound)
    note = _note(bound.get("note"))
    before, after, rows, why = None, None, None, None
    try:
        before, after, rows = _edit_dry(jr, journal, vid, slug, cid, edited, note)
    except jr.JournalError as e:
        why = str(e)
    except (ValueError, OSError) as e:
        raise BatchFault(409, "journal_unreadable", f"Журнал загрузок не читается: {e}",
                         [f"{type(e).__name__}: {e}"]) from e
    if why is None and after.get("channel") != cid:
        why = (f"{after.get('video_id')} - ролик канала {after.get('channel')}, а не {cid} - "
               f"отмечать его отсюда нельзя.")
    elif why is None and bool((before or {}).get("user_edited")) == edited:
        why = (f"{after.get('slug')} ({after.get('video_id')}): "
               + ("ручная правка уже отмечена" if edited else "отметки ручной правки нет")
               + " - менять нечего.")
    ok = why is None
    out = {"ok": ok, "why": why, "edited": edited, "video_id": (after or {}).get("video_id") or vid,
           "slug": (after or {}).get("slug") or slug, "note": note or "",
           "by": EDIT_BY, "via": EDIT_VIA,
           "before": _jsonable(before) if ok else None, "row": _jsonable(after) if ok else None,
           "streak": sf.streak(rows, cid) if ok else None, "journal": _rel(root, journal)}
    facts = dict(out, row={k: v for k, v in (after or {}).items() if k != "user_edited_at"}
                 if ok else None, streak=None, journal_sha=_file_sha(journal))
    return out, facts


def _edited_plan(root, channel, action, edited, video_id=None, slug=None, note=None):
    cid = _channel(root, channel)
    bound = {"video_id": video_id, "slug": slug, "note": note, "edited": edited}
    out, facts = _edited_check(root, cid, bound)
    return _cut.clean(_issue_plan(root, action, cid, out, facts, bound), root)


def _edited(root, channel, action, token):
    cid = _channel(root, channel)
    jr, sf = _col().journal(), factory.studio_fields()

    def act(b):
        vid, slug = _edit_name(b)
        journal = _paths(root)["journal"]
        row = _edit_mark(jr, journal, vid, slug, cid, bool(b.get("edited")),
                         _note(b.get("note")), False)
        return _cut.clean({"action": action, "channel": cid, "edited": bool(row["user_edited"]),
                           "by": EDIT_BY, "via": EDIT_VIA,
                           "row": _jsonable(row), "streak": sf.streak(jr.uploads(journal), cid)}, root)

    def message(b, answer):
        name = (answer.get("row") or {}).get("video_id") or b.get("video_id") or b.get("slug")
        word = "правлен в Studio руками" if b.get("edited") else "снята отметка правки в Studio"
        return (f"Публикация: {name} - {word} ({EDIT_BY}, {EDIT_VIA})",
                f"CC-0153: отметка правки из центра (publish_net.{action}, "
                f"upload_records.mark_user_edited)." + (f"\nЗаметка: «{_note(b.get('note'))}»"
                                                      if _note(b.get("note")) else ""))
    return _confirm(root, cid, action, token, lambda b: _edited_check(root, cid, b), act,
                    (jr.JournalError,),
                    commit=([f"{PUBLISH_DIR}/{JOURNAL}"], message, "Отметка записана"))


def studio_edited_plan(root, channel, video_id=None, slug=None, note=None):
    """What «правил в Studio руками» would write: `mark_user_edited(edited)` on
    its own dry run (`dry_run=True`) - the row before and after, the streak after."""
    return _edited_plan(root, channel, "studio_edited", True, video_id, slug, note)


def studio_edited(root, channel, token):
    """The confirmed mark: the same dry run, then `mark_user_edited` (edited)."""
    return _edited(root, channel, "studio_edited", token)


def studio_edited_undo_plan(root, channel, video_id=None, slug=None, note=None):
    """What taking the mark off would write: `mark_user_edited(edited=False,
    dry_run=True)`."""
    return _edited_plan(root, channel, "studio_edited_undo", False, video_id, slug, note)


def studio_edited_undo(root, channel, token):
    """The confirmed undo: the same dry run, then `mark_user_edited(edited=False)`."""
    return _edited(root, channel, "studio_edited_undo", token)
