#!/usr/bin/env python3
"""CF-0421 (continued by CF-0018): what must be true before `videos.insert`.

Three facts, each read from where it already lives, none invented here:

1. **The user accepted this video, by its name** - `publish/acceptance-log.json`
   (CF-0328), read through `shared/runlog/acceptance.py`. An acceptance is not
   a permission to upload; it is the precondition for asking.
2. **No unsigned publication hold stands on its topic** -
   `publish/publication-holds.json` (CF-0318), read through the same module's
   `held()`: an unsigned, unresolved `review` is a hard stop; a registry that
   does not parse holds everything (fail closed); a missing registry holds
   nothing. A row filed before topic ids were recorded (topic_id null) cannot be
   matched by topic, so it is checked by batch: any open hold in its batch stops
   it.
3. **The user said "да" for this upload, at the terminal** (CF-0018: an
   explicit human yes per upload, never automatic, at any volume). The answer
   is read from `/dev/tty` - the controlling terminal - and never from stdin or
   a flag: `echo да | upload.py` does not answer it, and a process with no
   terminal (an agent's shell, cron, CI) cannot upload at all. A
   `Confirmation` exists only as the result of that read, and the upload
   requires one for exactly this video.
4. **The channel is not paused** (CF-0569) - `publish/channel-pauses.json`,
   read through `channel_pause.py` (its one reader): a paused channel uploads
   nothing (`check_channel_not_paused`). The same function is the gate of the
   Studio path (CF-0018): it is called before the schedule is filled in Studio,
   and a refusal means the video stays unscheduled. An expired pause holds
   nothing but comes back as a notice to print; a registry that does not parse
   pauses every channel (fail closed).

Before the question, `ask_user` shows `TOS_NOTICE` (CF-0618, YouTube API
Services Terms of Service 9.1(i), 2026-09-14): an API client that uploads
tells the user, before the upload, that the content must comply with the
YouTube Terms of Service and Community Guidelines and must not violate others'
copyright or privacy rights - with the URL of the Terms. The terminal has no
"upload" button; the answer «да» is that click.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

AGENT = Path(__file__).resolve().parent
ROOT = AGENT.parent.parent
sys.path.insert(0, str(ROOT / "shared" / "runlog"))
sys.path.insert(0, str(AGENT))

YES = {"да", "yes"}

# CF-0618: ToS 9.1(i) - the wording of the Terms, "clicking 'upload'" being the
# «да» typed here; the URL is the desktop one the Terms name.
TOS_URL = "https://www.youtube.com/t/terms"
COMMUNITY_GUIDELINES_URL = "https://www.youtube.com/howyoutubeworks/policies/community-guidelines/"
TOS_NOTICE = (
    f"By typing «да» (upload), you certify that the content you are uploading complies with "
    f"the YouTube Terms of Service (including the YouTube Community Guidelines) at {TOS_URL}. "
    f"Please be sure not to violate others' copyright or privacy rights.\n"
    f"Отвечая «да», вы подтверждаете, что загружаемое соответствует Условиям использования "
    f"YouTube ({TOS_URL}) и Правилам сообщества ({COMMUNITY_GUIDELINES_URL}) и не нарушает "
    f"чужих авторских прав и права на частную жизнь.")
_ISSUED = object()      # only ask_user() holds this; see Confirmation


class GateError(Exception):
    pass


def _acceptance():
    import acceptance                                           # noqa: PLC0415
    return acceptance


def resolve_entry(slug, entry=None, log_path=None):
    """The acceptance row of the video named `slug`. `entry` (`channel/batch/slug`)
    picks one when the name was accepted in more than one batch (a rebuild);
    without it, two standing acceptances of one name are refused, not guessed."""
    acc = _acceptance()
    try:
        rows = acc.entries(path=log_path)
    except acc.AcceptanceError as e:
        raise GateError(str(e)) from e
    if entry:
        try:
            channel, batch_id, eslug = acc.parse_key(entry, parts=3)
        except acc.AcceptanceError as e:
            raise GateError(str(e)) from e
        if eslug != slug:
            raise GateError(f"--entry {entry} names {eslug!r}, the note is {slug!r}")
        row = acc.find(channel, batch_id, slug, rows=rows)
        if row is None:
            raise GateError(f"no acceptance row {entry} in the acceptance log")
        return row
    mine = [r for r in rows if r.get("slug") == slug and r.get("verdict") == acc.ACCEPTED]
    if not mine:
        named = [r for r in rows if r.get("slug") == slug]
        if named:
            r = named[-1]
            raise GateError(f"{slug}: the user did not accept this video "
                            f"({r.get('verdict')}: {r.get('reason') or 'no reason on the row'})")
        raise GateError(f"{slug}: no acceptance recorded - the user was never asked about this "
                        f"video by name (runlog acceptance --ask, CF-0328)")
    if len(mine) > 1:
        keys = ", ".join(r.get("entry_id") for r in mine)
        raise GateError(f"{slug} was accepted in more than one batch ({keys}) - pick one with "
                        f"--entry CHANNEL/BATCH/SLUG")
    return mine[0]


def check_publishable(row, log_path=None, holds_path=None):
    """Stop unless the row is a standing acceptance with no open hold on it.
    Returns the acceptance module's `state()` for the record."""
    acc = _acceptance()
    channel, batch_id, slug = row.get("channel"), row.get("batch_id"), row.get("slug")
    try:
        st = acc.state(channel, batch_id, slug, path=log_path, holds_path=holds_path)
        if not st["accepted"]:
            raise GateError(f"{slug}: not accepted by the user ({st['verdict'] or 'no verdict'})")
        if st["held"]:
            raise GateError(f"{slug}: publication hold {st['hold_id']} stands unsigned "
                            f"({st['hold_reason']}) - hard stop until the user signs it in "
                            f"publish/publication-holds.json (CF-0318)")
        if not row.get("topic_id"):
            here = acc.resolve_channel(channel)
            for h in acc.holds(holds_path):
                if (acc.resolve_channel(h.get("channel")) == here
                        and h.get("batch_id") == batch_id and h.get("verdict") == "review"
                        and not h.get("resolved_at") and not h.get("signature")):
                    raise GateError(f"{slug}: the acceptance row carries no topic_id, and "
                                    f"batch {batch_id} has an open hold {h.get('hold_id')} - it "
                                    f"may be this video's; stop until the hold is signed or the "
                                    f"row names its topic")
    except acc.AcceptanceError as e:
        raise GateError(f"{slug}: {e} - fail closed, nothing is uploaded") from e
    return st


def check_channel_not_paused(channel, root=None, now=None):
    """CF-0569: stop when `channel` is paused. Returns the notice of an
    expired pause still on record (print it), or None. `root` is the data
    root (`publish/` lives under it); None is this checkout.

    CF-0018 (the Studio path) calls this before it fills a schedule in Studio;
    CF-0421/CF-0585 (`upload.py`) before `videos.insert`."""
    import channel_pause                                        # noqa: PLC0415
    if not channel:
        raise GateError("no channel to check the pause of - fail closed, nothing is uploaded")
    reason, notice = channel_pause.gate(channel, root, now)
    if reason:
        raise GateError(f"{channel}: publications are paused - {reason}; nothing is uploaded and "
                        f"no schedule is set in Studio until the pause is cleared "
                        f"(channel_pause.py show --channel {channel})")
    return notice


def check_not_uploaded(row, journal_rows):
    """Stop when the journal already has an upload of this acceptance row."""
    keys = set(_acceptance().row_keys(row))
    for u in journal_rows:
        if u.get("entry_id") in keys and u.get("api_data_deleted_at"):
            # CF-0618: an API upload whose YouTube fields were deleted under the
            # API policy (api_data.py) - the video is still on the channel
            raise GateError(f"{row.get('slug')}: already uploaded through the API "
                            f"({u.get('uploaded_at')}); its YouTube id was deleted "
                            f"{u.get('api_data_deleted_at')} ({u.get('api_data_deleted_reason')}) - "
                            f"see `api_data_deleted` in publish/uploads.json; to bring it back, "
                            f"read the id in Studio: upload_records.py studio ...")
        if u.get("entry_id") in keys and u.get("video_id") and not u.get("removed_at"):
            raise GateError(f"{row.get('slug')}: already uploaded as {u.get('video_id')} "
                            f"({u.get('uploaded_at')}, {u.get('source') or u.get('method')}) - see publish/uploads.json")


class Confirmation:
    """Proof that the user typed "да" for this video. Made only by `ask_user()`."""

    def __init__(self, slug, answer, at, _issued=None):
        if _issued is not _ISSUED:
            raise TypeError("a Confirmation comes only from upload_gate.ask_user() - "
                            "the user's answer at the terminal (CF-0018)")
        self.slug, self.answer, self.at = slug, answer, at


def open_terminal():
    """The controlling terminal, for reading and writing. No terminal - no upload."""
    try:
        return open("/dev/tty", "r+", encoding="utf-8")
    except OSError as e:
        raise GateError("no terminal to ask at: an upload needs the user's \"да\" typed at the "
                        "keyboard (CF-0018); it cannot come from stdin, a flag, or an agent's "
                        f"shell ({e.strerror or e})") from e


def ask_user(slug, summary, terminal=None):
    """Show `summary`, read one line from the terminal, and return a
    Confirmation only for "да"/"yes". Anything else refuses the upload."""
    tty = terminal if terminal is not None else open_terminal()
    try:
        tty.write(summary.rstrip() + "\n\n" + TOS_NOTICE + "\n\nЗагрузить этот ролик? Введите «да»: ")
        tty.flush()
        answer = (tty.readline() or "").strip()
    finally:
        if terminal is None:
            tty.close()
    if answer.lower() not in YES:
        raise GateError(f"{slug}: the user did not confirm (answer {answer!r}) - nothing uploaded")
    return Confirmation(slug, answer, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        _issued=_ISSUED)


def require_confirmation(confirmation, slug):
    if not isinstance(confirmation, Confirmation) or confirmation.slug != slug:
        raise GateError(f"{slug}: no confirmation from the user for this video - nothing uploaded")
    return confirmation
