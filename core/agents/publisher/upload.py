#!/usr/bin/env python3
"""CF-0421: upload one accepted video to the channel through the YouTube Data API.

    python3 agents/publisher/upload.py publish/<channel>/<YYYY-MM-DD>/<slug>.md --dry-run
    python3 agents/publisher/upload.py <slug> --dry-run      # the latest note of the name
    python3 agents/publisher/upload.py --authorize
    python3 agents/publisher/upload.py publish/<channel>/<YYYY-MM-DD>/<slug>.md [--entry CH/BATCH/SLUG] [--publish-at ISO]

The note and the video lie side by side in the folder of the channel and the day
the video goes out (CF-0475, `shared/runlog/publish_layout.py`); a bare slug is
looked up there.

Replaces the browser path (Chrome extension, a ≤ 10 MB re-encoded copy, the
time picked by hand in Studio): the full file goes up by resumable
`videos.insert`, `privacyStatus: private` with `publishAt` - YouTube makes it
public at that moment - and `selfDeclaredMadeForKids: false` (the writable form
of `madeForKids`).

Every check that can be made without the user is made first - the note and
its claim check (CF-0555: the block «Утверждения» of `note_claims.py`, fresh
for the title and the description), the acceptance, the publication hold, the journal, the token and its channel - and
only then is the user asked, at the terminal, to type "да". There is no flag
that answers for him (CF-0018): see `upload_gate.py`.

`--dry-run` stops before the credentials: it needs no Google libraries, no
token and no network, and prints the request body that would be sent.
`--authorize` is the one-time sign-in (a browser opens; the user signs in to the
channel's account) and uploads nothing.

`--authorize` asks for every scope the factory uses, the Analytics one too
(CF-0589), and records when the token expires (7 days while the app is in
Testing; no fixed term in Production - `PUBLISHER_OAUTH_MODE`, CF-0607);
`publisher_auth.py status` says how long it has left.

CF-0607 - one path among two, behind a switch. The API upload waits for the
YouTube API audit (CF-0470): every channel's switch (`api_switch.py`,
`schedule/api-upload.json`) is off until the user turns it on, and while it is
off a real run stops before anything reaches Google with one line - «API-загрузка
для <канал> выключена: ...; публикация — через Studio». `--dry-run` still checks
and says the switch's state. What the API path uploads is what the Studio path
(CF-0018, `studio_fields.py`) would fill in: a ready card (CF-0017,
`publish_card.card_state`) of the accepted entry, at the card's slot of the
queue (CF-0587) inside its day folder, the channel not paused (CF-0569), not
in the journal (CF-0586, the API-deleted rows of CF-0618 too); the row it writes
(`source: api`) is the one both paths' gates and the queue read, and the
ledger's publication columns are brought up to date (`publish_window.py`,
CF-0042) as the Studio path does.

Exit codes: 0 - uploaded (or dry run / authorized); 1 - refused, with the
reason; 2 - bad arguments; 3 - the user must re-authorize (the token expired or
was revoked - `invalid_grant` - or lacks a scope, CF-0589).
"""
import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

AGENT = Path(__file__).resolve().parent
sys.path.insert(0, str(AGENT))
sys.path.insert(0, str(AGENT.parent.parent / "shared" / "runlog"))

import publish_layout                                           # noqa: E402
import api_switch                                               # noqa: E402
import note_claims                                              # noqa: E402
import publish_card                                             # noqa: E402
import publish_note                                             # noqa: E402
import publisher_auth                                           # noqa: E402
import publisher_config                                         # noqa: E402
import upload_gate                                              # noqa: E402
import upload_records                                           # noqa: E402
import youtube_client                                           # noqa: E402

ROOT = AGENT.parent.parent
MIN_LEAD = timedelta(minutes=10)        # publishAt must be in the future; leave room for the upload


class Refused(Exception):
    pass


def resolve_note(arg, publish=None, entry=None, log_path=None):
    """`publish/<channel>/<day>/<slug>.md` as given, or the latest note of a
    bare slug (CF-0475: a day folder or `_queue/` of any channel, or the flat
    root before migration).

    CF-0857: with `entry` (`channel/batch/slug`, `--entry`) a bare slug is the
    note of that batch's video (`publish_layout.of_batch`) - a channel reuses
    names, the latest note of the name may be another batch's."""
    p = Path(arg)
    if p.is_file() or p.suffix == ".md" or "/" in str(arg):
        return p
    if entry:
        acc = upload_gate._acceptance()
        try:
            channel, batch_id, eslug = acc.parse_key(entry, parts=3)
            e, why = publish_layout.of_batch(str(arg), batch_id, publish,
                                             channel, log_path=log_path)
        except acc.AcceptanceError as err:
            raise Refused(f"--entry {entry}: {err}") from err
        if eslug != str(arg):
            raise Refused(f"--entry {entry} names {eslug!r}, the note is {arg!r}")
        if not e or not e.get("md"):
            raise Refused(f"no note of {entry} in publish/" + (f" ({why})" if why else "")
                          + f" - give the path publish/<channel>/<YYYY-MM-DD>/{arg}.md")
        return e["md"]
    found = publish_layout.card(str(arg), publish=publish)
    if found is None:
        raise Refused(f"no note of `{arg}` in publish/ (looked in every day folder and "
                      f"{publish_layout.QUEUE}/ of every channel) - give the path "
                      f"publish/<channel>/<YYYY-MM-DD>/{arg}.md")
    return found


def card_gate(note, text, row, publish_at, publish_root=None):
    """CF-0607: the API path uploads what the Studio path would fill in - a
    ready card (CF-0017) of this acceptance row, its slot in its day folder."""
    ready, why = publish_card.placeable(text)       # ready, or ruled by the user (CF-0747)
    if not ready:
        raise Refused(f"{note}: the card is not ready ({why}) - the API path, like Studio, uploads "
                      f"only a ready card (publish_card.py, CF-0017)")
    mark = publish_card.mark_of(text) or {}
    batch = Path(str(mark.get("batch") or "")).name
    if batch and row.get("batch_id") and batch != row.get("batch_id"):
        raise Refused(f"{note}: the card is of batch {batch}, the acceptance row of "
                      f"{row.get('entry_id')} - name the right one with --entry")
    at = publish_layout.bucket_of(note, publish_root or note.parent.parent.parent)
    if at and publish_layout.DAY_RE.match(str(at[1])):
        day = upload_records.parse_slot(rfc3339(publish_at), "UTC")[2]     # the Moscow day
        if day != at[1]:
            raise Refused(f"{note}: the slot {rfc3339(publish_at)} is not the day folder {at[1]} - "
                          f"move it (runlog publish assign) or fix the slot (CF-0475)")


def switch_gate(row, data_root, dry_run, out):
    """CF-0607: the channel's API switch - off refuses a real run before any
    credentials or client; a dry run says it and goes on."""
    channel = row.get("channel") or publish_layout.channel_of_row(row)
    try:
        api_switch.check(channel, root=data_root)
    except api_switch.SwitchError as e:
        if not dry_run:
            raise Refused(str(e)) from e
        print(f"API-SWITCH {e} (сухой прогон идёт дальше)", file=out)


def default_client(cfg, authorize=False):
    creds = publisher_auth.load_credentials(cfg, authorize=authorize)
    return youtube_client.YouTubeClient(creds)


def parse_when(text):
    """An ISO time with a zone (`2026-10-01T22:00:00Z`, `...+03:00`) -> aware UTC."""
    try:
        when = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError as e:
        raise Refused(f"--publish-at {text!r} is not an ISO time") from e
    if when.tzinfo is None:
        raise Refused(f"--publish-at {text!r} has no zone - write it in UTC with Z")
    return when.astimezone(timezone.utc)


def rfc3339(when):
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_body(meta, publish_at, cfg_category="24", language="en"):
    status = {"privacyStatus": "private", "publishAt": rfc3339(publish_at),
              "selfDeclaredMadeForKids": False}
    if meta.get("contains_synthetic") is not None:
        status["containsSyntheticMedia"] = bool(meta["contains_synthetic"])
    return {"snippet": {"title": meta["title"], "description": meta["description"],
                        "tags": list(meta["tags"]), "categoryId": str(cfg_category),
                        "defaultLanguage": language, "defaultAudioLanguage": language},
            "status": status}


def summary(row, video, body, channel_id):
    size = Path(video).stat().st_size / 1e6
    st, sn = body["status"], body["snippet"]
    when = datetime.strptime(st["publishAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    try:
        from zoneinfo import ZoneInfo                           # noqa: PLC0415
        local = (f"{when.astimezone(ZoneInfo('Europe/Moscow')):%d.%m %H:%M} МСК, "
                 f"{when.astimezone(ZoneInfo('America/New_York')):%d.%m %H:%M} ET")
    except Exception:                                           # noqa: BLE001
        local = ""
    return "\n".join([
        f"Ролик:      {row.get('slug')}  ({row.get('entry_id')})",
        f"Файл:       {video}  ({size:.1f} МБ, без пережатия)",
        f"Канал:      {channel_id or '(проверяется по токену)'}",
        f"Название:   {sn['title']}",
        f"Теги:       {len(sn['tags'])}",
        f"Публикация: {st['publishAt']} ({local}) - до этого времени приватный",
        f"Для детей:  нет" + (f"; синтетический контент: {'да' if st['containsSyntheticMedia'] else 'нет'}"
                              if "containsSyntheticMedia" in st else ""),
        f"Приёмка:    {row.get('verdict')} {row.get('answered_at')} - «{row.get('answer')}»",
        "Пометка публикации (CF-0318): нет",
    ])


def run(args, client_factory=None, terminal=None, paths=None, now=None, sleep=time.sleep,
        out=sys.stdout):
    paths = paths or {}
    now = now or datetime.now(timezone.utc)
    client_factory = client_factory or default_client

    if args.authorize:
        cfg = publisher_config.load(args.env)
        client = client_factory(cfg, authorize=True)
        ids = client.my_channel_ids()
        print(f"authorized; token saved to {cfg.token_file}; channels of this token: "
              f"{', '.join(ids) or 'none'}", file=out)
        print(publisher_auth.status(cfg, now).line, file=out)
        if cfg.channel_id and cfg.channel_id not in ids:
            raise Refused(f"the token belongs to {ids}, not to PUBLISHER_CHANNEL_ID="
                          f"{cfg.channel_id} - sign in again with the channel's account")
        return 0

    note = resolve_note(args.note, paths.get("publish"), args.entry, paths.get("log"))
    meta = publish_note.parse(note)
    # CF-0555: the title and the description went through the claim check
    # (`note_claims.py --write`) and have not changed since.
    unchecked = note_claims.check_block(note.read_text(encoding="utf-8"))
    if unchecked:
        raise Refused(f"{note}: {unchecked}")
    slug = publish_layout.split_name(note.stem)[0]      # CF-0920: the file's suffix is not the name
    publish_at = parse_when(args.publish_at) if args.publish_at else meta["publish_at"]
    if publish_at is None:
        raise Refused(f"{note}: `## Публикация` names no time in the form "
                      f"**YYYY-MM-DD HH:MM <zone>** - add it or pass --publish-at")
    if publish_at < now + MIN_LEAD:
        raise Refused(f"publishAt {rfc3339(publish_at)} is not at least {MIN_LEAD} ahead of now "
                      f"({rfc3339(now)}) - pick the next slot")

    row = upload_gate.resolve_entry(slug, entry=args.entry, log_path=paths.get("log"))
    data_root = Path(paths["publish"]).parent if paths.get("publish") else None
    switch_gate(row, data_root, args.dry_run, out)
    upload_gate.check_publishable(row, log_path=paths.get("log"), holds_path=paths.get("holds"))
    card_gate(note, note.read_text(encoding="utf-8"), row, publish_at, paths.get("publish"))
    if args.publish_at and meta["publish_at"] is not None and publish_at != meta["publish_at"] \
            and not args.dry_run:
        raise Refused(f"--publish-at {rfc3339(publish_at)} is not the card's slot "
                      f"{rfc3339(meta['publish_at'])} - the API path takes the slot of the queue, "
                      f"like Studio (publish_queue.py / publish_card.py place, CF-0587)")
    notice = upload_gate.check_channel_not_paused(row.get("channel"), root=data_root, now=now)
    if notice:
        print(f"PAUSE {notice}", file=out)
    journal_path = paths.get("journal")
    jdoc = upload_records.read_journal(journal_path)
    upload_gate.check_not_uploaded(row, jdoc["uploads"] + list(jdoc.get("api_data_deleted") or []))

    video = note.with_suffix(".mp4")
    if not video.is_file():
        raise Refused(f"{video}: the video file is not there")

    body = build_body(meta, publish_at)
    if args.dry_run:
        print(summary(row, video, body, None), file=out)
        print(json.dumps(body, ensure_ascii=False, indent=2), file=out)
        print("dry run: nothing sent, no credentials read", file=out)
        return 0

    cfg = publisher_config.load(args.env)
    if not cfg.channel_id:
        raise Refused("PUBLISHER_CHANNEL_ID is empty - the upload must know which channel it is for")
    body = build_body(meta, publish_at, cfg.category_id, cfg.language)
    client = client_factory(cfg)
    ids = client.my_channel_ids()
    if cfg.channel_id not in ids:
        raise Refused(f"the OAuth token speaks for {ids or 'no channel'}, not for "
                      f"{cfg.channel_id} - nothing uploaded")

    confirmation = upload_gate.ask_user(slug, summary(row, video, body, cfg.channel_id),
                                        terminal=terminal)
    upload_gate.require_confirmation(confirmation, slug)

    request = client.insert_request(video, body)
    response = youtube_client.run_resumable(
        request, sleep=sleep,
        on_progress=lambda p: print(f"  {p * 100:.0f} %", file=out, flush=True))
    uploaded_at = rfc3339(datetime.now(timezone.utc))
    record = upload_records.build_record(row, response, body, video, confirmation, uploaded_at,
                                         duration=upload_records.probe_duration(video))
    try:
        upload_records.append_journal(record, journal_path)
        upload_records.append_note(note, record)
        upload_records.update_readme(record, paths.get("readme"))
    except Exception as e:                                      # noqa: BLE001
        print(f"UPLOADED as {record['video_id']}, but writing the record failed ({e}). "
              f"The record, to file by hand:\n{json.dumps(record, ensure_ascii=False, indent=2)}",
              file=out)
        return 1
    print(f"uploaded: {record['url']} - private until {record['publish_at']}", file=out)
    try:                        # CF-0607: as the Studio path's record does (CF-0042)
        import publish_window                                   # noqa: PLC0415
        led = publish_window.record_published(record["channel"], data_root, now,
                                              journal=journal_path)
        if led.get("filled"):
            print(f"ledger: {', '.join(led['filled'])}", file=out)
    except Exception as e:                                      # noqa: BLE001
        print(f"ledger not brought up to date ({e.__class__.__name__}: {e}) - "
              f"publish_window.py record --channel {record['channel']}", file=out)
    at = publish_layout.bucket_of(note, paths.get("publish") or note.parent.parent.parent)
    if at and at[1] == publish_layout.QUEUE:
        print(f"the note is still in {at[0]}/{publish_layout.QUEUE}/ - move the pair into its "
              f"day: runlog publish assign {slug} --channel {at[0]} --apply (CF-0475)", file=out)
    return 0


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 allow_abbrev=False)
    ap.add_argument("note", nargs="?", help="publish/<channel>/<YYYY-MM-DD>/<slug>.md, or a bare slug")
    ap.add_argument("--entry", help="CHANNEL/BATCH/SLUG when the name was accepted in several batches")
    ap.add_argument("--publish-at", help="override the note's time, ISO with a zone (…Z)")
    ap.add_argument("--dry-run", action="store_true", help="check everything, send nothing")
    ap.add_argument("--authorize", action="store_true",
                    help="one-time OAuth sign-in in a browser; uploads nothing")
    ap.add_argument("--env", help="the .env file (default agents/publisher/.env)")
    return ap


def main(argv=None, **kw):
    ap = build_parser()
    args = ap.parse_args(argv)
    if not args.authorize and not args.note:
        ap.error("give publish/<channel>/<YYYY-MM-DD>/<slug>.md or a slug (or --authorize)")
    try:
        return run(args, **kw)
    except publisher_auth.ReauthorizeRequired as e:
        print(f"REAUTHORIZE: {e}", file=kw.get("out") or sys.stderr)
        return publisher_auth.EXIT_REAUTHORIZE
    except (Refused, publish_note.NoteError, upload_gate.GateError, publisher_config.ConfigError,
            publisher_auth.AuthError, youtube_client.UploadError, ValueError) as e:
        print(f"REFUSED: {e}", file=kw.get("out") or sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
