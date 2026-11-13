#!/usr/bin/env python3
"""CF-0325: "is this pool source the topic's work?" - Trend Hunter's own
checks, run over the sources `topics[].pool.matched` names.

Run as a **separate process** by `pool_sources.py`, under Trend Hunter's venv,
with Trend Hunter's `scripts/` on `sys.path`. Separate on purpose: the two
repos both have a `_runlog` and a `_channel_ids` module, and importing Trend
Hunter's `topic_relevance` into the indexer's process would hand one repo the
other's module under the same name. Nothing of the indexer is imported here.

The checks are the ones Trend Hunter already runs over a *candidate* before
it is offered - the same rule, now asked of a source that came from the pool
instead of from a search:

  wrong_work / work_not_in_title   CF-0272 / CF-0309 - the upload's own title
                                   names no form of the work
                                   (`topic_relevance.work_forms`)
  other_works_name, news_wrap,     CF-0309 `footage_sieve.sieve()`, the other
  hashtag_title, opinion,          five rules, official channels exempt as
  press_outlet                     there
  unofficial_source                CF-0297 `footage_origin.stop_word()` - a fan
                                   edit, a concept trailer, a reaction

and one rule of this task, because the pool's match is by title and a title
match cannot tell two works of one franchise apart:

  other_installment  the topic's name has a franchise stem ("Vanguards:
                     Doomsday") or a `parent_work`, and the upload's title
                     names the work **only** by that stem or parent - never by
                     the full name or the subtitle. Batch 2026-09-29T0705Z gave
                     Vanguards: Doomsday the candidate list of Vanguards:
                     Endgame, and the judge rejected the render with
                     `wrong_work_footage`: "Vanguards: Endgame | Official
                     Trailer" names "Vanguards" and passes CF-0272, and is not
                     one frame of Doomsday. `work_forms` is generous on
                     purpose for a *search* (a false drop costs a candidate);
                     a pool source counted for a topic costs a download that
                     is then not made, so here the stem alone is not enough.

CF-0631 (CF-0627, CF-0561): the official footage channels `footage_origin`
exempts are the batch's channel's own list now
(`channels/<id>/footage-origin.json` of the factory root, read by Trend
Hunter's `footage_origin.load_config(channel, root=)`), so the request names
the channel and the factory root. No channel named is an `error` - every
source "not checked", never counted - and never another channel's list.

CF-0817: and one question that is not "is it the work": is it somebody
else's host show - a podcast, an interview, a talk show (Trend Hunter's
`host_show.judge()`, the lists in its `config/host_show.json`, read here and
never copied). Asked of every source the work check lets through, on its
pool title and uploader, with the channel's official list for `official`
and the topic's `title_ref` for the two exceptions (`subject_is_guest`,
`topic_is_the_show`). The answer rides on the verdict as `host_show`: None
(no host show), or Trend Hunter's verdict - refused or kept under an
exception - and `host_show_unknown` lists the fields the pool did not have
(an old entry with no title or uploader). Trend Hunter's classifier that
cannot be imported is an `error` naming it - every source "not checked",
never counted - not a quiet pass.

Input (stdin, JSON):
    {"trend_hunter_scripts": "<dir>", "channel": "<id>", "factory_root": "<dir>",
     "topics": [{"topic_id": ..., "title_ref": {...},
                 "sources": [{"video_id", "title", "channel_title"}]}]}
Output (stdout, JSON):
    {"error": null | "<why>",
     "topics": {topic_id: {video_id: {"ok": bool, "rule": str|null,
                                      "reason_code": str|null,
                                      "reason": str|null,
                                      "host_show": null | {...},
                                      "host_show_unknown": [field, ...]}}}}
Never raises: a failure is `error` with no verdicts, and the caller reads a
missing verdict as "not checked" - which never counts a source.
"""
import json
import sys

RULE = "CF-0325"
OTHER_INSTALLMENT = "other_installment"
HOST_SHOW_RULE = "CF-0817"
HOST_SHOW_FIELDS = ("title", "channel_title")
WRONG_WORK = "wrong_work"


def _strict_forms(ref, work_forms):
    """CF-0325's own copy of the rule, **no longer used by `check()`** - since
    CF-0444 the pool check asks Trend Hunter's
    `topic_relevance.installment_forms` directly (one rule for the candidate
    sieve and the pool check). Kept only because Trend Hunter's
    `tests/test_other_installment.py::test_the_indexers_pool_check_says_the_same_thing`
    still calls it by name; drop it once that test stops. Differs from
    `installment_forms` on a degenerate name (nothing left after the franchise
    is taken out): `[]` here, None there - `check()` follows None."""
    name = str(ref.get("name") or "").strip()
    parent = str(ref.get("parent_work") or ref.get("parent") or "").strip()
    stem = name.partition(":")[0].strip() if ":" in name else ""
    if not stem and not parent:
        return None
    wide = set()
    for broad in (stem, parent):
        if broad:
            wide.update(work_forms({"name": broad}))
    strict = [f for f in work_forms({"name": name}) if f not in wide]
    subtitle = name.partition(":")[2].strip() if ":" in name else ""
    if subtitle:
        strict += [f for f in work_forms({"name": subtitle})
                   if f not in wide and f not in strict]
    return strict


def host_show_of(video, ref, hs, fo, origin_cfg):
    """CF-0817: Trend Hunter's host-show verdict on one pool source, and the
    metadata fields the pool had nothing in. Judged on what there is: a
    title that says "Official Podcast" is a podcast with no uploader known."""
    missing = [f for f in HOST_SHOW_FIELDS if not str(video.get(f) or "").strip()]
    verdict = hs.judge(video, nature=None, official=bool(fo.is_official(video, origin_cfg)),
                       title_ref=ref)
    return verdict, missing


def check(topics, mods, channel=None, root=None):
    tr, fs, fo = mods["topic_relevance"], mods["footage_sieve"], mods["footage_origin"]
    hs = mods["host_show"]
    sieve_cfg = fs.load_config()
    origin_cfg = fo.load_config(channel, root=root)     # CF-0631: the channel's list
    out = {}
    for t in topics or []:
        ref = dict(t.get("title_ref") or {})
        forms = tr.work_forms(ref)
        # CF-0444: Trend Hunter's own rule. None = the rule does not apply
        # (no stem, no parent, or nothing left once the franchise is out) -
        # nothing is refused as another installment then.
        strict = tr.installment_forms(ref) if forms else None
        verdicts = {}
        for src in t.get("sources") or []:
            vid = src.get("video_id")
            video = {"video_id": vid, "title": src.get("title") or "",
                     "channel_title": src.get("channel_title") or "",
                     "description": ""}
            verdict = {"ok": True, "rule": None, "reason_code": None, "reason": None}
            # An official channel is exempt from footage_sieve's rules, never
            # from CF-0272: the official Harbourlights trailer is not Wren Hollow.
            what = fs.rule_work_not_in_title(video, forms) if forms else None
            code = "work_not_in_title" if what else None
            if not code:
                code, what = fs.sieve(video, config=sieve_cfg, forms=forms,
                                     origin=origin_cfg)
            if code:
                rc = WRONG_WORK if code == "work_not_in_title" else fs.NOT_FOOTAGE_CODE
                verdict = {"ok": False, "rule": code, "reason_code": rc,
                           "reason": f"{what} ({code}, CF-0309/CF-0272)"}
            else:
                hit, field, text = fo.stop_word(video, origin_cfg)
                if hit:
                    verdict = {"ok": False, "rule": hit.get("code"),
                               "reason_code": fo.UNOFFICIAL_CODE,
                               "reason": f"its {field} says {text!r} - {hit.get('why')} "
                                         f"({hit.get('code')}, CF-0297)"}
                elif strict is not None and not fs._named_in_title(video, strict):
                    shown = ", ".join(repr(f) for f in strict[:3]) or "nothing"
                    verdict = {"ok": False, "rule": OTHER_INSTALLMENT,
                               "reason_code": OTHER_INSTALLMENT,
                               "reason": (f"its title names the work only by its franchise "
                                          f"or parent, never as {shown} - another work of "
                                          f"the same name ({OTHER_INSTALLMENT}, {RULE})")}
            if verdict["ok"]:
                got, missing = host_show_of(video, ref, hs, fo, origin_cfg)
                verdict["host_show"] = got
                if missing and not (got and got.get("refused")):
                    verdict["host_show_unknown"] = missing
            verdicts[vid] = verdict
        out[t.get("topic_id")] = verdicts
    return out


def main():
    try:
        req = json.load(sys.stdin)
        sys.path.insert(0, req["trend_hunter_scripts"])
        import footage_origin
        import footage_sieve
        import topic_relevance
        try:
            import host_show
            host_show.load_config()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"{HOST_SHOW_RULE}: Trend Hunter's host-show classifier could not be "
                f"loaded from {req['trend_hunter_scripts']} (host_show.py + "
                f"config/host_show.json): {type(exc).__name__}: {exc} - no pool source "
                f"is counted without it") from exc
        mods = {"topic_relevance": topic_relevance, "footage_sieve": footage_sieve,
                "footage_origin": footage_origin, "host_show": host_show}
        ans = {"error": None, "topics": check(req.get("topics"), mods,
                                              channel=req.get("channel"),
                                              root=req.get("factory_root") or None)}
    except Exception as exc:  # noqa: BLE001 - see the docstring
        ans = {"error": f"{type(exc).__name__}: {exc}", "topics": {}}
    sys.stdout.write(json.dumps(ans))
    return 0


if __name__ == "__main__":
    sys.exit(main())
