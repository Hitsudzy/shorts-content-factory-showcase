#!/usr/bin/env python3
"""CF-0817: somebody else's host is not our backdrop.

The incident. A viewer wrote under the Reel `vanguards-doomsday` (published
2026-10-19): "Stop stealing content. Especially from the basement yard
podcast". Ten of its 25 clips - and all 16 of the 2026-10-11 video of the same
topic - came out of Zenith's own "Countdown to Vanguards: Doomsday Official
Podcast" (`nSWnovHSDaY`, `pdAeUavzpE8`, `xe3qx0kXArA`), the co-hosts talking to
camera under our narration. The audit (CF-0818, root
`docs/audit-talking-hosts-2026-10-20.md`) found ten published videos like it:
Fallon with Tom Carver for Delver (`ZLXL1L0TfsI`, 8 of 10 clips), Kimmel with
Jessica Chastain for Other Mommy (`uTi2Yiz-8vs`), Sam Meadows with Dakota
Reyes for WNL (`d7b1ilF5290`), LIVE with Kelly and Mark with Jessica Lange
for American Dread Story (`keeX8htyf3I`). Eight of the nine sources came from
this stage's own `evidence.footage_candidates`, which already labelled them
`interview` or `commentary` - and offered them anyway, because every sieve
before this one exempts an official channel (the user's rule of 2026-09-20:
no word in a studio's title may cost its trailer), and Zenith Entertainment,
Jimmy Kimmel Live and The Evening Show are on the channel's official list.

The rule (the user, 2026-10-20): other people's podcast, interview and
talk-show hosts are not used as backdrop under our voice. Trailers, official
clips, featurettes and on-set footage stay as before. So:

  * an upload is a **host show** when its title or its channel names a show
    (`shows`: Fallon, Kimmel, Colbert, Sam Meadows, Graham Norton, Hot Ones,
    Kelly and Mark, The View, ... - `config/host_show.json`), or its title or
    channel says the format (`formats`: podcast, talk show, late night,
    morning show, interview, press junket, roundtable, reaction, review /
    commentary; review and reaction not on an official channel, where they
    are promo words - "Social Review", "Fan Reactions"), or its footage
    nature is a talk (`natures`: interview, commentary - off a channel that
    is not official, and read off the title or the room, not the
    description: a studio's "Talk about hanging by a thread" is a promo, and
    a premiere arrival is event footage), or - on an upload whose own
    metadata says nothing
    (nature `unknown`) - every search facet that found it is a talk facet
    (`facets`: interview, press conference, podcast);
  * `origin: official` does **not** exempt it: the Zenith podcast is
    Zenith's;
  * a host show is refused with `reason_code: "host_show"` and stays in the
    artifact (`evidence.footage_candidates_dropped`, the supplement's
    `candidates_dropped`) with the signals that made it one;
  * **one exception**, read off existing fields only: the topic's subject is
    a person and the source's title names that person - their own interview
    (`subject_is_guest`). The subject is a person when the topic's
    `title_ref.kind` is `person` and its name *is* that person (CF-0439's
    "a story about the person"; a person-topic whose name is a work - "Saturday
    Night Live" with `person: Dana Reyes` - is a story about the work), or
    when the supplement searched a `kind: person` entity (the uncovered anchor
    is about them - Danny Vermette's interview for backrooms). A mechanical
    second one: the topic's own name names the show (`topic_is_the_show` - a
    story about The Late Show is told with The Late Show). The kept candidate
    carries `host_show` with the exception and why.

The verdict, on a record (`host_show`, None when the upload is no host show):

    {"refused": bool, "exception": null | "subject_is_guest" | "topic_is_the_show",
     "subject": <the person or show the exception was read on> | null,
     "signals": [{"by": "show" | "format" | "nature" | "facets", "code": ...,
                  "field": ..., "match": ...}, ...],
     "reason": "<one sentence>"}

The same question is asked of a source already in `shared/footage`, twice:

  * the Footage Indexer's pool reuse (`from_pool`, `pool_sources.vet()`) does
    not read `config/host_show.json` itself - it runs its
    `scripts/pool_work_check.py` as a separate process under **this** agent's
    venv with this `scripts/` on `sys.path`, and that process imports this
    module and calls `judge(video, nature=None, official=<the channel's
    footage_origin list>, title_ref=<the topic's>)` on the pool's title and
    uploader (`channel_title`);
  * this stage's own pool bonus (`pool_coverage.host_judge`) asks it the same
    way, so a source the indexer will refuse earns a topic no rank.

`judge()` is therefore a **cross-agent interface**: keep its signature
(`video, nature=None, official=False, title_ref=None, person=None,
config=None, read=None`, keyword-callable) and the verdict's keys
(`refused`, `exception`, `subject`, `signals`, `reason`) stable, or change
footage-indexer's `pool_work_check.host_show_of` in the same release.

CLI (no network): scripts/host_show.py <batch-dir|01-trend-hunter.json> -
the host shows among a written batch's candidates, what this rule would do.
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from fact_probe_topics import normalise  # noqa: E402  - one normalisation, as topic_relevance

CONFIG_PATH = HERE.parent / "config" / "host_show.json"
HOST_SHOW_CODE = "host_show"
HOST_SHOW_KEY = "host_show"
SUBJECT_IS_GUEST = "subject_is_guest"
TOPIC_IS_THE_SHOW = "topic_is_the_show"
EXCEPTIONS = (SUBJECT_IS_GUEST, TOPIC_IS_THE_SHOW)
FIELDS = ("title", "channel_title")
# Where a nature may have been read for it to count (`classify_with_source`):
# the title and the room, not the head of a description.
NATURE_READS = ("title", "room")
TOKEN_EDGE = r"(?<![0-9a-z])(?:{})(?![0-9a-z])"

_CACHE = {}


class ConfigError(ValueError):
    pass


def load_config(path=None):
    """The lists, compiled. A broken file is a ConfigError, never an empty
    sieve: an empty list would offer every podcast again without a word."""
    path = Path(path or CONFIG_PATH)
    key = str(path)
    if key in _CACHE:
        return _CACHE[key]
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ConfigError(f"{path}: unreadable ({exc}) - CF-0817") from exc
    out = {"natures": tuple(raw.get("natures") or ()),
           "facets": tuple(str(f).lower() for f in raw.get("facets") or ()),
           "spared_natures": {k: tuple(v) for k, v in (raw.get("spared_natures") or {}).items()},
           "shows": [], "formats": []}
    for section in ("shows", "formats"):
        entries = raw.get(section)
        if not isinstance(entries, list) or not entries:
            raise ConfigError(f"{path}: `{section}` is missing or empty - CF-0817")
        for e in entries:
            if not e.get("code") or not e.get("pattern"):
                raise ConfigError(f"{path}: a `{section}` entry without code/pattern: {e}")
            if not (e.get("seen_in") or e.get("named_by")):
                raise ConfigError(f"{path}: {section} {e['code']!r} carries neither "
                                  f"`seen_in` nor `named_by`")
            body = e["pattern"]
            rx = re.compile((r"^(?:{})$".format(body)) if e.get("whole")
                            else TOKEN_EDGE.format(body), re.I)
            out[section].append(dict(e, rx=rx, fields=tuple(e.get("fields") or FIELDS)))
    if not out["natures"]:
        raise ConfigError(f"{path}: `natures` is missing or empty - CF-0817")
    _CACHE[key] = out
    return out


def _flat(text):
    """Lower case, the curly apostrophe folded, whitespace collapsed - what a
    pattern is matched on (`&` and `'` kept: 'kelly & mark', "jake's takes")."""
    return " ".join(str(text or "").replace("’", "'").lower().split())


def _hits(video, entries, by, official=False):
    out = []
    for e in entries:
        if official and e.get("official") is False:
            continue
        for field in e["fields"]:
            m = e["rx"].search(_flat((video or {}).get(field)))
            if m:
                sig = {"by": by, "code": e["code"], "field": field, "match": m.group(0)}
                if e.get("show"):
                    sig["show"] = e["show"]
                if e.get("outlet"):
                    sig["outlet"] = True
                out.append(sig)
                break
    return out


def signals(video, nature=None, official=False, config=None, read=None):
    """-> the list of signals that make this upload a host show ([] = it is
    not one). Title and channel name only, never the description.

    `read` is where the nature was read (`footage_candidates.classify_with_source`:
    title / room / keywords / description / channel / none); None when the
    caller does not know (a written record), and then the nature counts."""
    config = config or load_config()
    out = (_hits(video, config["shows"], "show")
           + _hits(video, config["formats"], "format", official))
    if (nature in config["natures"] and not official
            and (read is None or read in NATURE_READS)):
        out.append({"by": "nature", "code": nature, "field": "nature", "match": nature})
    facets = [str(f).lower() for f in (video or {}).get("facets") or []]
    if (nature in (None, "unknown") and facets
            and all(f in config["facets"] for f in facets)):
        out.append({"by": "facets", "code": "facets", "field": "facets",
                    "match": ", ".join(facets)})
    # A programme's or a press outlet's re-upload of the work's own cut is the
    # cut: only a channel-name show hit, nothing else, and the nature read is
    # one the kind of channel may re-upload (`spared_natures`).
    if out and all(s["by"] == "show" and s["field"] == "channel_title" for s in out):
        kind = "outlet" if all(s.get("outlet") for s in out) else "programme"
        if nature in config["spared_natures"].get(kind, ()):
            return []
    return out


def subject_person(title_ref):
    """-> the person the topic is about, or None. Existing fields only: a
    `title_ref.kind: person` whose name is that person (`person` empty or the
    same name). A person-topic whose name is a work ("Weekend Night Live",
    `person: Dana Reyes`) is a story about the work - its subject is not a
    person, and its star's talk-show couch is not its footage."""
    ref = title_ref if isinstance(title_ref, dict) else {"name": title_ref}
    if (ref or {}).get("kind") != "person":
        return None
    name = str(ref.get("name") or "").strip()
    person = str(ref.get("person") or "").strip()
    if person and name and normalise(person) != normalise(name):
        return None
    return person or name or None


def names_person(video, person):
    """Whether the upload's **title** names the person, whole words."""
    needle = normalise(person)
    return bool(needle.strip()) and needle in normalise((video or {}).get("title"))


def _topic_names(title_ref):
    ref = title_ref if isinstance(title_ref, dict) else {"name": title_ref}
    return [_flat(x) for x in ((ref or {}).get("name"), (ref or {}).get("parent_work"))
            if x]


def judge(video, nature=None, official=False, title_ref=None, person=None, config=None,
          read=None):
    """-> the verdict (see the module doc) or None when the upload is no host
    show. `person` is the subject person when the caller knows it (a
    supplement's person entity); else it is read off `title_ref`. `nature` and
    `read` as `signals()` takes them.

    Cross-agent interface (CF-0817): footage-indexer's `pool_work_check.py`
    calls this by keyword from its own process under this agent's venv - the
    signature and the verdict's keys are a contract with it (module doc)."""
    config = config or load_config()
    sigs = signals(video, nature, official, config, read)
    if not sigs:
        return None
    by = ", ".join(f"{s['by']} {s['match']!r}" + (f" in {s['field']}" if s['by'] in ("show", "format") else "")
                   for s in sigs)
    # The topic is the show: its own name names a show this upload is.
    names = _topic_names(title_ref)
    shows = {s["code"] for s in sigs if s["by"] == "show"}
    for e in config["shows"]:
        if e["code"] in shows and any(e["rx"].search(n) for n in names):
            return {"refused": False, "exception": TOPIC_IS_THE_SHOW, "subject": e.get("show"),
                    "signals": sigs,
                    "reason": (f"a host show ({by}), kept: the topic itself is "
                               f"{e.get('show')!r} - its own footage (CF-0817)")}
    subject = person or subject_person(title_ref)
    if subject and names_person(video, subject):
        return {"refused": False, "exception": SUBJECT_IS_GUEST, "subject": subject,
                "signals": sigs,
                "reason": (f"a host show ({by}), kept: the topic is about {subject!r} and "
                           f"the title names them - their own interview (CF-0817)")}
    why = (f"a host show ({by}) - somebody else's host or interviewer talking to "
           f"camera is not backdrop under our voice (the user, 2026-10-20, CF-0817)")
    if subject:
        why += f"; the topic's subject {subject!r} is not named in its title"
    if official:
        why += "; an official channel does not exempt it"
    return {"refused": True, "exception": None, "subject": subject, "signals": sigs,
            "reason": why}


def exclusion_record(video, verdict):
    """One `host_show` record, in the shape `footage_candidates_dropped`
    already holds, plus the verdict itself under `host_show`."""
    return {
        "video_id": (video or {}).get("video_id"),
        "title": (video or {}).get("title"),
        "channel_title": (video or {}).get("channel_title"),
        "view_count": (video or {}).get("view_count"),
        "reason_code": HOST_SHOW_CODE,
        "reason": verdict["reason"],
        HOST_SHOW_KEY: verdict,
    }


def partition(videos, nature_of, official_of, title_ref=None, person_of=None, config=None):
    """-> (kept, dropped_records), the pool order preserved. `nature_of` /
    `official_of` are the caller's readings (footage_candidates.classify_with_source
    -> (kind, nature, read), or a bare nature; footage_origin.is_official);
    `person_of(video)` the subject person when the caller knows one per upload
    (the supplement). A host show kept under the exception is returned as a
    copy carrying its verdict under `host_show`."""
    config = config or load_config()
    kept, dropped = [], []
    for video in videos or []:
        got = nature_of(video)
        nature, read = (got[1], got[2]) if isinstance(got, tuple) else (got, None)
        verdict = judge(video, nature, bool(official_of(video)), title_ref,
                        person_of(video) if person_of else None, config, read)
        if verdict is None:
            kept.append(video)
        elif verdict["refused"]:
            dropped.append(exclusion_record(video, verdict))
        else:
            kept.append(dict(video, **{HOST_SHOW_KEY: verdict}))
    return kept, dropped


def check_record(record):
    """The problems of one written candidate's `host_show` (for `--check`)."""
    v = (record or {}).get(HOST_SHOW_KEY)
    if v is None:
        return []
    if not isinstance(v, dict):
        return [f"{HOST_SHOW_KEY} is not an object (CF-0817)"]
    if v.get("refused") or v.get("exception") not in EXCEPTIONS:
        return [f"{record.get('video_id')} is a host show ({v.get('reason')}) offered as "
                f"footage - it belongs in footage_candidates_dropped with reason_code "
                f"{HOST_SHOW_CODE!r} (CF-0817)"]
    return []


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("batch", help="<batch-dir|01-trend-hunter.json>")
    args = ap.parse_args(argv)
    path = Path(args.batch)
    if path.is_dir():
        path = path / "01-trend-hunter.json"
    batch = json.loads(path.read_text())
    n = 0
    for t in batch.get("topics") or []:
        ref = t.get("title_ref")
        for c in (t.get("evidence") or {}).get("footage_candidates") or []:
            v = judge(c, c.get("nature"), c.get("origin") == "official", ref)
            if v:
                n += 1
                print(f"{t.get('topic_id')}\t{c.get('video_id')}\t"
                      f"{'REFUSE' if v['refused'] else 'keep:' + v['exception']}\t"
                      f"{c.get('channel_title')!r}\t{c.get('title')!r}")
    print(f"{path}: {n} host show(s) among the candidates", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
