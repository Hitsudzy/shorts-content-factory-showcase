#!/usr/bin/env python3
"""CF-0259: the host of a fact's source is held to the channel's two lists
here, before TTS, instead of stopping the render plan after it.

The source badge (`CF-0164`, split in two by `CF-0166`) reads two lists of
hosts out of the channel config and knows three outcomes:

    host in `video_editor.comparison_line.publishers`   a publication -> a badge
    host in `video_editor.comparison_line.platforms`    a place -> a line, no badge
    host in neither                                     the stage stops

The third outcome is the point of the split: a *real* publication we simply
have not entered would otherwise vanish from the screen and nobody would
learn the table has a hole in it. That rule is right and is not touched here.

What was wrong was where it fired. On batch `example-film/2026-09-16T2148Z`
the batch's only script carried `stroudtimes.com` - a real local paper, not
in the table - and every check of this stage passed it. The Video Editor then
synthesised 38.55 s of speech, aligned 152/152 words and resolved 11/11
anchors before `build_render_plan.py` stopped on the last step
(`SOURCE BADGE NOT PLANNED ... host 'stroudtimes.com' is in neither list`).
The batch delivered nothing, and the four expensive steps were spent on a
verdict that was already decidable when the writer chose the source: the url
is in the script, the lists are in the config, and nothing in between adds a
fact. DoD 1.4.4 item 3 asks for a topic refused **before the render**; this
is the cheapest place that answer exists.

So this checker is the same rule, one stage earlier. A script whose source
host is in neither list is refused as `source_host_unlisted` and, with
`--write`, leaves `scripts[]` for `skipped[]` - the loss is the funnel's to
read (`shared/runlog/funnel.py`), not a topic that merely vanished. A host in
`platforms` is **not** a refusal: for the Video Editor that is a line without
a badge (`source_is_platform`), a perfectly good video. The Editor's own
check stays exactly where it is, as the backstop for the day the two sides
drift apart.

**The lists are read, never carried.** `publishers()`, `platforms()`,
`enabled()` and `host_of()` below mirror
`agents/video-editor/scripts/comparison_line.py` line for line, including its
built-in tables, because that module belongs to another agent's repository
and importing across the two would tie this stage to a checkout it does not
own. The mirror is the risk the split creates, so it is what
`tests/test_source_hosts.py` pins: when the Editor's module is reachable the
test compares both default tables and the normalisation itself against it and
fails the moment they part. Normalisation is exactly the Editor's - lowercase,
no `www.`, no port, no userinfo, no trailing dot - and in particular a
subdomain is **not** collapsed: `en.wikipedia.org` is its own entry in the
table, and a checker that collapsed it to `wikipedia.org` would pass hosts
the Editor then stops on, which is the one failure this task exists to end.

What is checked, per script, is every url that can reach the badge: the
script's `production_fact.source_url` and each `proofs[].source.url`. The
contract already says the second is the first (`inserts/proof.json`
script_contract.source_rule, enforced by `check_proofs.py`), so on a
well-formed batch these are one url - they are both read anyway, because a
checker that only looked at the field the other checker guarantees would go
quiet on exactly the batch where that guarantee broke.

Usage:

    python3 scripts/check_source_hosts.py <03-content-researcher.json>
    python3 scripts/check_source_hosts.py <03-content-researcher.json> \
        [--write] [--channel <id>] [--root <checkout>]

Exit codes:

    0  every source host is in one of the two lists (or the line is off on
       this channel) - the stage may go on
    1  a `source_url` with no host to read: a malformed field, and the fix is
       the field, not the table
    3  cannot answer: no channel config, no readable batch file. Nothing is
       claimed about any script
    4  at least one script is refused as `source_host_unlisted`; with
       `--write` it is recorded in `skipped[]`. There is nothing to rewrite -
       pick another source for the same fact, or the host belongs in a list,
       and that is a decision outside this stage

Stdlib only; no venv in this repository.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ - for _runlog
from _runlog import runlog  # noqa: E402
from _channel_ids import resolve_channel  # noqa: E402

from check_narration_budget import find_root  # noqa: E402
from check_reactions import load_channel_config  # noqa: E402
import _no_waiting as nw  # noqa: E402

# CF-0232's shape, CF-0233's precedent: the code, the stage and the entry a
# refusal writes into `skipped[]`. The word is the one the funnel and the
# root's pipeline contract have to know
# (shared/runlog/funnel.py FUNNEL_CODES, tests/test_pipeline_contracts.py
# SKIP_CODES); a code neither of them knows is a loss recorded as
# `unexplained`, which is the silence this whole mechanism exists to break.
SKIP_REASON_CODE = "source_host_unlisted"
FUNNEL_STAGE = "scripts"

# Where a url came from, named in the refusal so that the operator knows
# which field to change.
FROM_FACT = "production_fact.source_url"
FROM_PROOF = "proofs[{i}].source.url"

VERDICT_NAMED = "named"          # in `publishers` -> the badge carries that name
VERDICT_PLATFORM = "platform"    # in `platforms` -> a line without a badge
VERDICT_UNLISTED = "unlisted"    # in neither -> the refusal
VERDICT_NO_HOST = "no_host"      # not a url at all -> a malformed field

CONFIG_PUBLISHERS = "video_editor.comparison_line.publishers"
CONFIG_PLATFORMS = "video_editor.comparison_line.platforms"
CONFIG_ENABLED = "video_editor.comparison_line.enabled"

EXIT_OK, EXIT_FIX_FIELD, EXIT_CANNOT_ANSWER, EXIT_UNLISTED = 0, 1, 3, 4

# ----------------------------------------------------------------- the mirror
# comparison_line.DEFAULT_PUBLISHERS / DEFAULT_PLATFORMS, copied rather than
# imported (see the module docstring) and pinned to the original by
# tests/test_source_hosts.py whenever the Video Editor's checkout is reachable.
DEFAULT_PUBLISHERS = {
    "variety.com": "Variety",
    "deadline.com": "Deadline",
    "hollywoodreporter.com": "The Hollywood Reporter",
    "vulture.com": "Vulture",
}
DEFAULT_PLATFORMS = frozenset({
    "youtube.com",
    "youtu.be",
    "x.com",
    "twitter.com",
    "reddit.com",
    "tiktok.com",
    "instagram.com",
    "facebook.com",
})

EDITOR_MODULE_REL = Path("agents") / "video-editor" / "scripts" / "comparison_line.py"


# CF-0317: this checker reaches the channel config through check_reactions', so
# it ends in the same two register points its siblings do.
POINT_ENV = "researcher_env_broken"


class CannotAnswer(nw.CannotAnswer):
    """The question could not be put. Never a verdict on a script."""

    def __init__(self, message, point=POINT_ENV, **fields):
        super().__init__(message, point, **fields)

    def note_fields(self):
        fields = super().note_fields()
        if self.point == POINT_ENV and not fields.get("cause"):
            fields["cause"] = str(self).splitlines()[0].strip()
        return fields


def host_of(url):
    """The registrable host of `url`, lowercased and without `www.` or a
    port. None when there is no host to read.

    comparison_line.host_of, character for character. A subdomain is kept:
    the table's own entries carry them (`en.wikipedia.org`)."""
    if not isinstance(url, str) or "://" not in url:
        return None
    host = url.split("://", 1)[1].split("/", 1)[0].split("@")[-1].split(":")[0]
    host = host.strip().lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host or None


def publishers(channel_cfg):
    """The host -> name table for this channel: the built-in one with the
    channel's own entries merged over it (comparison_line.publishers)."""
    ve = (channel_cfg or {}).get("video_editor") or {}
    switch = ve.get("comparison_line") if isinstance(ve, dict) else None
    table = dict(DEFAULT_PUBLISHERS)
    extra = switch.get("publishers") if isinstance(switch, dict) else None
    if isinstance(extra, dict):
        for host, name in extra.items():
            if isinstance(host, str) and isinstance(name, str) and name.strip():
                table[host_of(f"https://{host.strip()}") or host.strip().lower()] = name.strip()
    return table


def platforms(channel_cfg):
    """The hosts that are places rather than publications: the built-in list
    plus the channel's (comparison_line.platforms). Added to, never
    replaced."""
    ve = (channel_cfg or {}).get("video_editor") or {}
    switch = ve.get("comparison_line") if isinstance(ve, dict) else None
    hosts = set(DEFAULT_PLATFORMS)
    extra = switch.get("platforms") if isinstance(switch, dict) else None
    if isinstance(extra, (list, tuple, set, frozenset)):
        for host in extra:
            if isinstance(host, str) and host.strip():
                hosts.add(host_of(f"https://{host.strip()}") or host.strip().lower())
    return hosts


def enabled(channel_cfg):
    """The comparison line is on unless the channel says otherwise
    (comparison_line.enabled). With the line off the Editor never asks about
    a host, so neither does this: refusing a topic for a badge nobody draws
    would be this checker inventing a rule of its own."""
    ve = (channel_cfg or {}).get("video_editor") or {}
    switch = ve.get("comparison_line") if isinstance(ve, dict) else None
    if isinstance(switch, dict) and switch.get("enabled") is False:
        return False
    return True


# ------------------------------------------------------------- the judgement

def source_urls(script):
    """[(where, url)] - every url of this script that can reach the badge.

    The fact's own `source_url` first (it is the one the Editor falls back
    to), then each proof's. A url seen twice is reported once, under the
    first field that carried it: on a well-formed batch the proof's url *is*
    the fact's, and one refusal naming two fields reads as two problems."""
    out, seen = [], set()
    fact = script.get("production_fact")
    if isinstance(fact, dict):
        fact = [fact]
    if isinstance(fact, list):
        for f in fact:
            url = f.get("source_url") if isinstance(f, dict) else None
            if isinstance(url, str) and url.strip() and url.strip() not in seen:
                seen.add(url.strip())
                out.append((FROM_FACT, url.strip()))
    proofs = script.get("proofs")
    if isinstance(proofs, list):
        for i, pr in enumerate(proofs):
            src = pr.get("source") if isinstance(pr, dict) else None
            url = src.get("url") if isinstance(src, dict) else None
            if isinstance(url, str) and url.strip() and url.strip() not in seen:
                seen.add(url.strip())
                out.append((FROM_PROOF.format(i=i), url.strip()))
    return out


def classify(url, where, table, platform_hosts):
    """One url's verdict, as a record: `{where, url, host, verdict, name}`.

    The three outcomes are comparison_line.publisher_of's, with its two
    failures kept apart: a host in neither list is the topic's refusal, a url
    with no host at all is a malformed field. (The Editor's third refusal -
    a name too wide for the 620px panel - is not mirrored: it is a fact about
    the glyphs the Editor measures, and a copy of its font metrics here would
    be exactly the second source of truth this file is written to avoid.)"""
    host = host_of(url)
    if host is None:
        return {"where": where, "url": url, "host": None,
                "verdict": VERDICT_NO_HOST, "name": None}
    name = table.get(host)
    if name:
        return {"where": where, "url": url, "host": host,
                "verdict": VERDICT_NAMED, "name": name}
    if host in platform_hosts:
        return {"where": where, "url": url, "host": host,
                "verdict": VERDICT_PLATFORM, "name": None}
    return {"where": where, "url": url, "host": host,
            "verdict": VERDICT_UNLISTED, "name": None}


def judge_script(script, table, platform_hosts):
    """Every source url of one script, classified, in the order read."""
    return [classify(url, where, table, platform_hosts)
            for where, url in source_urls(script)]


def refusal_reason(script, records, channel, table, platform_hosts):
    """The sentence a refusal carries - written to be read alone, because the
    funnel copies it verbatim into its `detail` column and nothing else in
    the batch will explain the loss."""
    unlisted = [r for r in records if r["verdict"] == VERDICT_UNLISTED]
    hosts = ", ".join(sorted({r["host"] for r in unlisted}))
    fields = ", ".join(r["where"] for r in unlisted)
    return (
        f"{script.get('script_id')}: the source of this script's production fact is hosted at "
        f"{hosts} ({fields}: {unlisted[0]['url']}), and that host is in neither of the two "
        f"lists the source badge reads from channels/{channel}.json - "
        f"{CONFIG_PUBLISHERS} (hosts the badge may name: "
        f"{', '.join(sorted(table)) or 'none'}) and {CONFIG_PLATFORMS} (hosts that are places "
        f"rather than publications, shown as a line with no badge: "
        f"{', '.join(sorted(platform_hosts)) or 'none'}). CF-0164/CF-0166: a host in neither "
        f"list stops the video, so that a real publication missing from the table cannot "
        f"disappear from the screen quietly - and CF-0259 moved that stop here, before the "
        f"voice is synthesised, because the url and the lists are both already known. The "
        f"topic is refused rather than rewritten: this is the table, not the script. Naming "
        f"the host in one of the two lists is a decision about the channel and is not this "
        f"stage's to make.")


def skip_entry(script, records, channel, table, platform_hosts):
    """The `skipped[]` entry a refusal writes - CF-0232's shape, as
    check_anchor_coverage.thin_skip_entry writes it, with the host and the
    field that carried it kept for an audit afterwards."""
    unlisted = [r for r in records if r["verdict"] == VERDICT_UNLISTED]
    return {
        "topic_id": script.get("topic_id"),
        "reason_code": SKIP_REASON_CODE,
        "reason": refusal_reason(script, records, channel, table, platform_hosts),
        "stage": FUNNEL_STAGE,
        "source_hosts": [{"host": r["host"], "url": r["url"], "field": r["where"]}
                         for r in unlisted],
    }


def check_batch_data(data, channel_cfg, channel="<channel>", out=print):
    """Judge every script of a parsed batch. Returns `(problems, refused)`:
    `problems` are malformed `source_url` fields (fix the field), `refused`
    is `[(script, records)]` for the topics whose host is in neither list.

    Nothing is written here; `check_batch` does that, and only with
    `--write`."""
    scripts = data.get("scripts") or []
    if not enabled(channel_cfg):
        out(f"  note: channels/{channel}.json {CONFIG_ENABLED} is false - the "
            f"comparison line is off on this channel, so no host is asked about and no topic "
            f"is refused here")
        return [], []
    table = publishers(channel_cfg)
    platform_hosts = platforms(channel_cfg)
    out(f"  lists: {len(table)} named host(s), {len(platform_hosts)} platform host(s) "
        f"(channels/{channel}.json {CONFIG_PUBLISHERS} / {CONFIG_PLATFORMS}, each merged over "
        f"the Video Editor's built-in table)")
    problems, refused = [], []
    for script in scripts:
        sid = script.get("script_id")
        records = judge_script(script, table, platform_hosts)
        if not records:
            out(f"  none {sid}: no source url to badge")
            continue
        bad = [r for r in records if r["verdict"] == VERDICT_NO_HOST]
        unlisted = [r for r in records if r["verdict"] == VERDICT_UNLISTED]
        if bad:
            for r in bad:
                out(f"  FAIL   {sid}: {r['where']} {r['url']!r} has no host to read")
                problems.append(
                    f"{sid}: {r['where']}: {r['url']!r} has no host to read, so no list can "
                    f"be asked about it and the Video Editor would stop on the same url "
                    f"(comparison_line.publisher_of). Write the document's own http(s) "
                    f"address - this one is the field, not the table")
            continue
        if unlisted:
            out(f"  REFUSE {sid}: {SKIP_REASON_CODE} - "
                f"{', '.join(sorted({r['host'] for r in unlisted}))} is in neither list")
            refused.append((script, records))
            continue
        for r in records:
            if r["verdict"] == VERDICT_NAMED:
                out(f"  ok   {sid}: {r['host']} -> badge {r['name']!r} ({r['where']})")
            else:
                out(f"  ok   {sid}: {r['host']} is a platform - the line goes up without a "
                    f"badge ({r['where']})")
    return problems, refused


def check_batch(batch_file, root=None, channel=None, write=False, out=print):
    """The CLI's half: read the file, judge it, and with `write` move the
    refused topics into `skipped[]`. Returns `(problems, refused)`."""
    try:
        data = json.loads(Path(batch_file).read_text())
    except (OSError, ValueError) as exc:
        raise CannotAnswer(f"cannot read {batch_file}: {exc}")
    # CF-0197: a batch written before the channel was renamed carries the old
    # id frozen in this field, so resolve it before anything is looked up.
    channel = resolve_channel(channel or data.get("channel"), root)
    if not channel:
        raise CannotAnswer(f"{batch_file}: no `channel` field and no --channel given")
    try:
        channel_cfg = load_channel_config(channel, root)
    except nw.CannotAnswer as exc:
        # CF-0317: the loader already knows which register point an absent
        # channel config is; carry it through rather than flattening it into
        # "the environment" here.
        raise CannotAnswer(str(exc), point=exc.point, **exc.note_fields()) from None
    except (OSError, ValueError) as exc:
        raise CannotAnswer(f"cannot read the channel config for {channel!r}: {exc}")
    out(f"{batch_file}: {len(data.get('scripts') or [])} script(s); channel {channel}")
    problems, refused = check_batch_data(data, channel_cfg, channel, out=out)
    if refused and write:
        table, platform_hosts = publishers(channel_cfg), platforms(channel_cfg)
        ids = {id(s) for s, _ in refused}
        data["scripts"] = [s for s in (data.get("scripts") or []) if id(s) not in ids]
        data.setdefault("skipped", [])
        for script, records in refused:
            data["skipped"].append(
                skip_entry(script, records, channel, table, platform_hosts))
        Path(batch_file).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        out(f"  wrote {batch_file}: {len(refused)} topic(s) moved to skipped[] as "
            f"`{SKIP_REASON_CODE}`; nothing else in the file was touched")
    elif refused:
        out(f"  note: {len(refused)} topic(s) are refused as `{SKIP_REASON_CODE}` but nothing "
            f"was recorded - re-run with --write so the funnel sees the loss")
    return problems, refused


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("batch_file", help="pipeline/<channel>/<batch>/03-content-researcher.json")
    ap.add_argument("--channel", default=None, help="override the file's `channel`")
    ap.add_argument("--root", default=None, help="shorts-content-factory checkout (default: found)")
    ap.add_argument("--write", action="store_true",
                    help=f"record a `{SKIP_REASON_CODE}` refusal in the batch file: the topic "
                         f"leaves scripts[] and enters skipped[]. Nothing else is written back")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else find_root()
    try:
        problems, refused = check_batch(args.batch_file, root=root, channel=args.channel,
                                        write=args.write)
    except CannotAnswer as exc:
        print(f"check_source_hosts.py: {exc}", file=sys.stderr)
        print("nothing is claimed about the scripts on this run", file=sys.stderr)
        print(nw.refuse(exc.point, **exc.note_fields()), file=sys.stderr)
        return EXIT_CANNOT_ANSWER
    if problems:
        print(f"\n{len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        return EXIT_FIX_FIELD
    if refused:
        print(f"\n{len(refused)} topic(s) refused as `{SKIP_REASON_CODE}` - the channel's two "
              f"lists, not the script; there is nothing to rewrite"
              + ("" if args.write else " and nothing was recorded (--write)"))
        for script, records in refused:
            hosts = sorted({r["host"] for r in records if r["verdict"] == VERDICT_UNLISTED})
            print(f"  - {script.get('script_id')}: {', '.join(hosts)}")
        print("  Pick another source for the same fact - one whose host the badge can name - "
              "or leave the topic refused. Adding the host to "
              f"{CONFIG_PUBLISHERS} / {CONFIG_PLATFORMS} is a decision about the channel and "
              "is not taken inside this stage.")
        return EXIT_UNLISTED
    return EXIT_OK


@runlog.script("content-researcher", "check-source-hosts", name="check_source_hosts.py")
def cli():
    """The command-line entry (CF-0107). Pure Python over the batch file and
    the channel config - no external binary, no model call, so no `child`
    events. A non-zero exit (1 = a malformed url, 3 = the question could not
    be put, 4 = a topic refused) is recorded as `failed`, which is what a
    refusal before TTS should look like in the log."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
