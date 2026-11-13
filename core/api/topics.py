"""CC-0091: what each stage of a batch found and decided about its topics,
while the batch runs - read only, from what the stages already wrote to the
batch's directory. Through the factory's own reader (`api/factory.py`):

    shared/runlog/funnel.py   read_artifacts - every stage file of the batch,
                              parsed, never raising (a file that does not parse
                              is a line of `_errors`); PRODUCTION_VERDICTS (the
                              verdicts a topic goes on with); _pool_depth and
                              _substitutions (01b's per-topic depth and the
                              reserve's refills, as the funnel reads them)

The files, in the order the stages write them:

    01-trend-hunter.json        topics[] (the shortlist), skipped_topics[],
                                selection, search_quota
    02-compliance-checker.json  results[] (the verdict of each), reserve[], cut
    01b-footage-index.json      sources_by_topic, pool_depth, skipped_topics[],
                                failed[], warnings[], reserve_substitution
    03-content-researcher.json  scripts[], skipped[]
    04-compliance-checker.json  results[] (the verdict of each script)
    05-video-editor.json        videos[] (qc), refusals[]
    06-frame-judge.json         videos[] (gate, reason_code, score_line)

**Not written yet is an answer.** A stage that has not finished has no file:
its block is `null` and `files[]` says `present: false`. Without 01 the answer
is a batch with no topics (`topics: []`, `trend_hunter_done: false`). A file
that does not parse (a stage caught writing it, or broken) is a `BatchFault`
500 `stage_broken` naming the file - `{message, code, details}`.

**The topic's state** (`state`): one Russian line of where it is, from the
furthest stage that wrote about it - «отсеяна: за темой не нашлось факта,
проходящего правило фактов», «в резерве»,
«в работе: футаж», «сценарий готов, в работе: проверка сценария», «ролик
готов». `phase` is its stable word: `in_work`, `stalled` (the batch is not
going - closed, stopped or failed - and the topic did not get to the end),
`reserve`, `dropped`, `done`. The batch is going while its run-state
`status` is `new` / `running` (`done` is closed; with no run-state.json, the
last marker batch-done closes it) - RUN_EVENTS.jsonl is not read.

**The codes in Russian** (CC-0113, CF-0714): every object of the answer
that carries a `reason_code` carries `reason_ru` beside it - the factory's
`funnel.reason_ru` (`api/factory.py` `with_reason_ru`), null for a code
outside its vocabulary - and the state's line says the code by the same
words (a code outside it as it is). The API keeps no table of its own.
A fact candidate's `failures` (fact_rule codes) carry `failures_ru` beside
them (CC-0119, CF-0752): `[{code, ru}]` in the same order, `ru` from
`fact_rule_ru.reason_ru` (`api/factory.py` `fact_failures_ru`), null for a
code the factory has no word for.

**Footage of a topic**: `pool` is the Trend Hunter's measure of the shared
pool (`topics[].pool`: shots, usable, retired, floor; `deep_enough` is
`usable >= floor`); `indexer` is what the footage indexer wrote (01b): the
sources it registered, the depth record (`pool_depth.topics[]`: shots,
usable_shots, floor, deep_enough, exhausted), thin or not, its failed
downloads, its refusal and warnings, a reserve refill. `indexed_at` is the
time 01b was written - the indexer writes no per-topic time (the factory's
gap, CC-0091 report).

**The second chances** (CC-0171, factory 2.37; `api/repair_refill.py`):
a script's `frame.repair` is the one repair pass of its video after the frame
judge (CF-0881, `funnel.judge_repairs`): `repaired`
(its 06 row is the ready one now) or `repair_failed` (the refusal stands), the
blocks and their defect, the codes before and after; the batch's `repairs` the
counts. A topic's `refill` (shortlisted or skipped) is what the refill from
below the shortlist did with it (CF-0882): promoted into 01 `topics[]`,
admitted into 02 `reserve[]`, refused by the compliance check on the fly or by
the Trend Hunter's sieve, and why; the batch's `refill` its rounds. CC-0173
(factory 2.38, CF-0888): the blocks' defect and the rounds come from the funnel
(`judge_repairs`, `below_shortlist_refill`), not from the raw files. A batch
before 2.37: all of them null.

**Never a path out**: the files carry absolute paths (`output_path`, the
indexer's `batch`, a plan check's verdict path); none of those fields is
passed, a video is its slug, and every string that goes out has the factory
root's prefix taken off (`_scrub`).
"""
import json
from pathlib import Path

from . import batches, factory, paths, repair_refill
from .batches import BatchFault

TH, C02, IDX = "01-trend-hunter.json", "02-compliance-checker.json", "01b-footage-index.json"
CR, C04, VE, FJ = ("03-content-researcher.json", "04-compliance-checker.json",
                   "05-video-editor.json", "06-frame-judge.json")
#: (the stage's id as the run plan names it, its file, its Russian name)
STAGES = (("trend-hunter", TH, "трендхантер"),
          ("compliance-shortlist", C02, "проверка правил"),
          ("footage-indexer", IDX, "футаж"),
          ("content-researcher", CR, "сценарий"),
          ("compliance-scripts", C04, "проверка сценария"),
          ("video-editor", VE, "монтаж"),
          ("frame-judge", FJ, "судья кадров"))
STAGE_RU = {s: ru for s, _f, ru in STAGES}
STAGE_RU.update({"trend_hunter": "трендхантер", "scripts": "сценарий",
                 "footage": "футаж", "compliance": "проверка правил"})
GOING_STATUSES = ("new", "running")
SCENE_TEXT_MAX = 600
QUOTA_KEYS = ("task", "daily_limit_searches", "units_per_search", "resets_at",
              "searches_before_stage", "spent_searches", "spent_units", "remaining_searches",
              "remaining_units", "spent_api_units", "spent_units_all",
              "substitutions_made", "substitutions_affordable", "summary_line")
POOL_KEYS = ("rule", "sources", "shots", "retired", "usable", "floor", "measured", "coverage",
             "coverage_by", "error")
DEPTH_KEYS = ("sources", "shots", "usable_shots", "weak_shots", "available_shots",
              "usable_seconds", "floor", "deep_enough", "measured", "at_source_floor",
              "exhausted", "attempts", "error", "indexed_at")
CUT_KEYS = ("cut_at", "shortlist_size", "judged", "eligible", "carried", "reserve", "refused",
            "held", "target", "target_from", "reason_code", "pass_verdicts",
            "production_verdicts", "publish_verdicts")
SELECTION_KEYS = ("stage", "shortlist_size", "scored", "viable", "carried")


def _fn():
    return factory.funnel()


# ---------------------------------------------------------------- reading
def _scrub(obj, prefixes):
    """Every string with the root's prefix taken off (a path under the root
    becomes relative), recursively - the API's one cutter (`api/paths.py`,
    CC-0097), without its `.../` cut: the stage files carry URLs."""
    return paths.scrub(obj, prefixes, outside=False)


def _prefixes(root):
    return paths.prefixes(root)


def _read(d):
    """{file: parsed} of the stage files present; a file that does not parse
    is `stage_broken` (500)."""
    a = _fn().read_artifacts(d)
    errs = list(a.get("_errors") or [])
    if errs:
        names = [e.split(":", 1)[0] for e in errs]
        raise BatchFault(500, "stage_broken",
                         f"Файл этапа {', '.join(names)} не читается - битый JSON или не "
                         f"объект (этап мог писать его в эту секунду; спросите ещё раз "
                         f"позже). Остальные этапы не показаны.", errs)
    return {k: v for k, v in a.items() if not k.startswith("_")}


def _files(root, d, a):
    out = []
    for stage, name, ru in STAGES:
        p = d / name
        at = None
        if name in a:
            try:
                at = factory.utc_iso(p.stat().st_mtime)
            except OSError:
                at = None
        out.append({"stage": stage, "name": ru, "file": name, "present": name in a,
                    "written_at": at})
    return out


def _rows(doc, key):
    v = (doc or {}).get(key)
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def _by(rows, key="topic_id"):
    out = {}
    for r in rows:
        if r.get(key):
            out.setdefault(r[key], r)
    return out


def _pick(doc, keys):
    if not isinstance(doc, dict):
        return None
    return {k: doc.get(k) for k in keys}


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _going(d):
    """(going, closed, status): the batch still runs? Its run-state `status`
    (`done` is closed; `new` / `running` is going); a batch with no
    run-state.json (markers only) is closed by its last marker, batch-done.
    The run-state is read, not RUN_EVENTS.jsonl (tens of MB while it runs)."""
    status, have = None, False
    try:
        sp = d / factory.run_executor().STATE_FILE
        if sp.is_file():
            have = True
            st = json.loads(sp.read_text(encoding="utf-8"))
            status = st.get("status") if isinstance(st, dict) else None
    except (OSError, ValueError):
        status = None
    if have:
        closed = status == "done"
    else:
        marks = batches._markers(d)
        closed = bool(marks) and marks[-1].get("marker") == "batch-done"
    going = not closed and (status is None or status in GOING_STATUSES)
    return going, closed, status


# ---------------------------------------------------------------- one topic's parts
def _title(t):
    tr = t.get("title_ref") if isinstance(t.get("title_ref"), dict) else {}
    return {"title": tr.get("name") or t.get("title"), "kind": tr.get("kind") or t.get("kind"),
            "type": tr.get("type"), "year": tr.get("year")}


def _sources(t):
    ev = t.get("evidence") if isinstance(t.get("evidence"), dict) else {}
    out, seen = [], set()
    for s in _rows(ev, "sources"):
        if s.get("url") and s["url"] not in seen:
            seen.add(s["url"])
            out.append({"url": s["url"], "title": s.get("title"),
                        "publication": s.get("publication"),
                        "published_at": s.get("published_at")})
    for u in ev.get("rss_links") or []:
        if isinstance(u, str) and u not in seen:
            seen.add(u)
            out.append({"url": u, "title": None, "publication": None, "published_at": None})
    return out


def _signal(t):
    sig = t.get("signal") if isinstance(t.get("signal"), dict) else {}
    return _num(sig.get("popularity_score")) if sig else _num(t.get("popularity_score"))


def _pool(t):
    p = t.get("pool")
    if not isinstance(p, dict):
        return None
    out = _pick(p, POOL_KEYS)
    u, f = _num(p.get("usable")), _num(p.get("floor"))
    out["deep_enough"] = (u >= f) if u is not None and f is not None else None
    return out


def _indexer(tid, idx, idx_at, ctx):
    if idx is None:
        return None
    depth, thin = ctx["depth"]
    srcs = (idx.get("sources_by_topic") or {}).get(tid) if isinstance(
        idx.get("sources_by_topic"), dict) else None
    rec = depth.get(tid)
    skipped = ctx["idx_skipped"].get(tid)
    sub = ctx["subs"].get(tid)
    return {"indexed_at": idx_at,
            "registered_sources": len(srcs) if isinstance(srcs, list) else None,
            "depth": _pick(rec, DEPTH_KEYS) if rec else None,
            "thin": tid in thin,
            "failed_downloads": sum(1 for f in _rows(idx, "failed") if f.get("topic_id") == tid),
            "skipped": {"reason_code": skipped.get("reason_code"),
                        "reason": skipped.get("reason")} if skipped else None,
            "warnings": [w.get("warning_code") for w in _rows(idx, "warnings")
                         if w.get("topic_id") == tid and w.get("warning_code")],
            "substituted": bool(sub),
            "substitution": {"reason_code": sub.get("reason_code"), "reason": sub.get("reason")}
            if sub else None}


def _compliance(tid, c02, ctx):
    if c02 is None:
        return None
    r = ctx["c02"].get(tid)
    res = ctx["reserve"].get(tid)
    row = r or res
    if row is None:
        return {"verdict": None, "place": "not_judged", "reason_code": None, "reason": None,
                "rights_reason": None, "rights_matched": None, "sensitivity_flagged": None,
                "sensitivity_notes": None, "sensitivity_scenes": None}
    rh = row.get("rights_holder_check") if isinstance(row.get("rights_holder_check"), dict) else {}
    cs = row.get("content_sensitivity_check") \
        if isinstance(row.get("content_sensitivity_check"), dict) else {}
    place = "reserve" if res is not None and r is None else (
        "batch" if row.get("verdict") in ctx["pass"] else "refused")
    return {"verdict": row.get("verdict"), "place": place,
            "reason_code": row.get("reason_code"), "reason": row.get("reason"),
            "rights_reason": rh.get("reason"), "rights_matched": rh.get("matched"),
            "sensitivity_flagged": cs.get("flagged"), "sensitivity_notes": cs.get("notes"),
            "sensitivity_scenes": factory.sensitivity_scenes(cs)}           # CC-0169


def _slug(v):
    op = v.get("output_path") or ""
    return Path(str(op)).stem or None


def _scripts(tid, a, ctx):
    """Each script of the topic as the later stages saw it."""
    out = []
    for s in ctx["scripts"].get(tid, []):
        sid = s.get("script_id")
        c4 = ctx["c04"].get(sid) if a.get(C04) is not None else None
        v = ctx["videos"].get(sid)
        ref = ctx["refusals"].get(sid)
        j = ctx["judge"].get(sid)
        cc = (c4 or {}).get("contribution_check") \
            if isinstance((c4 or {}).get("contribution_check"), dict) else {}
        qc = (v or {}).get("qc") if isinstance((v or {}).get("qc"), dict) else {}
        out.append({
            "script_id": sid, "scene_id": s.get("scene_id"), "hook": s.get("hook"),
            "duration_s": _num(s.get("estimated_spoken_duration_seconds")),
            "compliance": None if a.get(C04) is None else (
                {"verdict": c4.get("verdict"), "contribution": cc.get("verdict"),
                 "passes": c4.get("verdict") in ctx["pass"]} if c4 else
                {"verdict": None, "contribution": None, "passes": None}),
            "video": None if a.get(VE) is None else (
                {"slug": _slug(v), "qc_passed": qc.get("passed"),
                 "needs_you": bool(v.get("needs_you")), "score_line": v.get("score_line"),
                 "refused": None} if v else
                {"slug": None, "qc_passed": None, "needs_you": False, "score_line": None,
                 "refused": {"reason_code": ref.get("reason_code"), "reason": ref.get("reason")}
                 if ref else None}),
            "frame": None if a.get(FJ) is None or not v else dict(
                {"gate": j.get("gate"), "reason_code": j.get("reason_code"),
                 "reason": j.get("reason"), "score_line": j.get("score_line")} if j else
                {"gate": None, "reason_code": None, "reason": None, "score_line": None},
                repair=ctx["repairs"].get(sid)),                     # CC-0171
        })
    return out


# ---------------------------------------------------------------- the state line
def _st(phase, stage, line, reason_code=None):
    return {"phase": phase, "stage": stage, "line": line, "reason_code": reason_code}


def _why(code):
    """CC-0113: the factory's Russian of the code (`funnel.reason_ru`,
    CF-0714); a code outside its vocabulary said as it is."""
    return factory.reason_ru(code) or code or "без кода"


def _out(obj, root):
    """The answer as it leaves: `reason_ru` beside every `reason_code`
    (`factory.with_reason_ru`, CC-0113), the root's prefix cut."""
    return _scrub(factory.with_reason_ru(obj), _prefixes(root))


def _waits(stage, ctx, prefix=""):
    ru = STAGE_RU[stage]
    if ctx["going"]:
        return _st("in_work", stage, f"{prefix}в работе: {ru}")
    tail = "батч закрыт" if ctx["closed"] else f"батч {ctx['status'] or 'не идёт'}"
    return _st("stalled", stage, f"{prefix}не дошла: {ru} ({tail})")


REFUSED_BY_RU = {"compliance": "проверка правил", "trend_hunter": "сито футажа"}


def _skipped_state(row, refill=None):
    code = row.get("reason_code")
    stage = row.get("stage") or "trend-hunter"
    if code == "below_shortlist":
        if refill and refill["outcome"] == "refused":             # CC-0171 (CF-0882)
            by = REFUSED_BY_RU.get(refill["refused_by"], "отказ")
            return _st("dropped", stage, f"не вошла в шорт-лист; добор: отказ ({by})", code)
        return _st("dropped", stage, "не вошла в шорт-лист", code)
    return _st("dropped", stage, f"отсеяна: {_why(code)}", code)


def _state(tid, a, ctx, comp, idx, scripts):
    if a.get(C02) is None:
        return _waits("compliance-shortlist", ctx)
    if comp["place"] == "reserve" and not (idx or {}).get("substituted"):
        return _st("reserve", "compliance-shortlist", "в резерве", comp["reason_code"])
    if comp["place"] == "refused":
        return _st("dropped", "compliance-shortlist",
                   f"отсеяна: проверка правил ({comp['verdict'] or 'без вердикта'})",
                   comp["reason_code"])
    if comp["place"] == "not_judged":
        return _st("dropped", "compliance-shortlist", "отсеяна: проверка правил (нет записи)")
    if idx is None:
        return _waits("footage-indexer", ctx)
    if idx["skipped"]:
        code = idx["skipped"]["reason_code"]
        if code == "reserve_unused":
            return _st("reserve", "footage-indexer", "в резерве", code)
        return _st("dropped", "footage-indexer", f"отсеяна: футаж ({_why(code)})", code)
    if a.get(CR) is None:
        return _waits("content-researcher", ctx)
    if not scripts:
        sk = ctx["cr_skipped"].get(tid)
        code = (sk or {}).get("reason_code")
        return _st("dropped", "content-researcher",
                   f"отсеяна: сценарий ({_why(code) if sk else 'нет сценария'})", code)
    best = None
    for s in scripts:
        st = _script_state(s, a, ctx)
        if best is None or _RANK[st["phase"]] > _RANK[best["phase"]]:
            best = st
    return best


_RANK = {"dropped": 0, "stalled": 1, "in_work": 2, "reserve": 0, "done": 3}


def _script_state(s, a, ctx):
    if s["compliance"] is None:
        return _waits("compliance-scripts", ctx, "сценарий готов, ")
    if s["compliance"]["passes"] is False:
        return _st("dropped", "compliance-scripts",
                   f"отсеяна: проверка сценария ({s['compliance']['verdict'] or 'без вердикта'})")
    if s["video"] is None:
        return _waits("video-editor", ctx, "сценарий проверен, ")
    if not s["video"]["slug"]:
        ref = s["video"]["refused"]
        code = (ref or {}).get("reason_code")
        return _st("dropped", "video-editor",
                   f"отсеяна: монтаж ({_why(code) if ref else 'ролика нет'})", code)
    if s["video"]["qc_passed"] is False or s["video"]["needs_you"]:
        return _st("dropped", "video-editor", "ролик собран, но не прошёл QC")
    if s["frame"] is None:
        if ctx["going"]:
            return _waits("frame-judge", ctx, "ролик собран, ")
        return _st("done", "video-editor", "ролик собран")
    gate = s["frame"]["gate"]
    rep = (s["frame"].get("repair") or {}).get("outcome")             # CC-0171 (CF-0881)
    if gate == "pass":
        return _st("done", "frame-judge",
                   "ролик готов после ремонта" if rep == "repaired" else "ролик готов")
    if gate == "reject":
        code = s["frame"]["reason_code"]
        tail = "; ремонт не удался" if rep == "repair_failed" else ""
        return _st("dropped", "frame-judge", f"отсеяна: судья кадров ({_why(code)}){tail}",
                   code)
    return _st("stalled", "frame-judge", f"судья кадров не закончил ({gate or 'нет записи'})")


# ---------------------------------------------------------------- the answers
def _context(d, a):
    fn = _fn()
    c02, idx, cr = a.get(C02), a.get(IDX), a.get(CR)
    cut = (c02 or {}).get("cut") if isinstance((c02 or {}).get("cut"), dict) else {}
    passing = cut.get("production_verdicts") or list(fn.PRODUCTION_VERDICTS)
    going, closed, status = _going(d)
    scripts = {}
    for s in _rows(cr, "scripts"):
        if s.get("topic_id"):
            scripts.setdefault(s["topic_id"], []).append(s)
    subs, _unmatched = fn._substitutions(idx)
    repair_counts, repairs = repair_refill.repairs(a.get(FJ))
    rf = repair_refill.refill(d, a.get(TH), c02)                         # CC-0173
    return {
        "repair_counts": repair_counts, "repairs": repairs,                  # CC-0171
        "refill_read": rf, "refill": repair_refill.refill_topics(rf, a.get(TH), c02),
        "going": going, "closed": closed, "status": status, "pass": tuple(passing),
        "c02": _by(_rows(c02, "results")), "reserve": _by(_rows(c02, "reserve")),
        "depth": fn._pool_depth(idx), "idx_skipped": _by(_rows(idx, "skipped_topics")),
        "subs": subs, "scripts": scripts, "cr_skipped": _by(_rows(cr, "skipped")),
        "c04": _by(_rows(a.get(C04), "results"), "script_id"),
        "videos": _by(_rows(a.get(VE), "videos"), "script_id"),
        "refusals": _by(_rows(a.get(VE), "refusals"), "script_id"),
        "judge": _by(_rows(a.get(FJ), "videos"), "script_id"),
    }


def _summary(t, rank, a, ctx, idx_at):
    tid = t.get("topic_id")
    comp = _compliance(tid, a.get(C02), ctx)
    idx = _indexer(tid, a.get(IDX), idx_at, ctx)
    scripts = _scripts(tid, a, ctx) if a.get(CR) is not None else None
    state = _state(tid, a, ctx, comp, idx, scripts or [])
    return dict(_title(t), topic_id=tid, rank=rank, popularity_score=_signal(t),
                sources=_sources(t), scenes=len(_rows(t, "scenes")),
                has_fact=(t.get("fact_probe") or {}).get("has_fact")
                if isinstance(t.get("fact_probe"), dict) else None,
                compliance=comp, footage={"pool": _pool(t), "indexer": idx},
                scripts=scripts, state=state, refill=ctx["refill"].get(tid))


def _skipped(row, ctx):
    refill = ctx["refill"].get(row.get("topic_id"))
    return {"topic_id": row.get("topic_id"), "title": row.get("title"), "kind": row.get("kind"),
            "popularity_score": _num(row.get("popularity_score")),
            "reason_code": row.get("reason_code"), "reason": row.get("reason"),
            "stage": row.get("stage"), "state": _skipped_state(row, refill),
            "refill": refill}


def _quota(th):
    q = (th or {}).get("search_quota")
    if not isinstance(q, dict):
        return None
    out = _pick(q, QUOTA_KEYS)
    for k in ("searches_by_topic", "api_units_by_key"):
        v = q.get(k)
        out[k] = {str(x): n for x, n in v.items() if _num(n) is not None} \
            if isinstance(v, dict) else None
    ba = q.get("by_article")
    out["by_article"] = {k: {"search_calls": _num(v.get("search_calls")),
                             "api_units": _num(v.get("api_units")), "what": v.get("what")}
                         for k, v in ba.items() if isinstance(v, dict)} \
        if isinstance(ba, dict) else None
    return out


def _idx_at(d, a):
    if a.get(IDX) is None:
        return None
    try:
        return factory.utc_iso((d / IDX).stat().st_mtime)
    except OSError:
        return None


def topics(root, channel, batch_id):
    """The batch's topics as every stage that wrote saw them - see the module."""
    d = batches.batch_dir(root, channel, batch_id)
    a = _read(d)
    th, c02 = a.get(TH), a.get(C02)
    ctx = _context(d, a)
    idx_at = _idx_at(d, a)
    shortlist = _rows(th, "topics")
    listed = {t.get("topic_id") for t in shortlist}
    summaries = [_summary(t, i + 1, a, ctx, idx_at) for i, t in enumerate(shortlist)]
    skipped = [_skipped(r, ctx) for r in _rows(th, "skipped_topics")
               if r.get("topic_id") not in listed]
    counts = {"topics": len(summaries), "skipped": len(skipped)}
    for ph in ("in_work", "stalled", "reserve", "dropped", "done"):
        counts[ph] = sum(1 for s in summaries if s["state"]["phase"] == ph)
    cut = (c02 or {}).get("cut")
    out = {
        "batch": f"{channel}/{batch_id}", "channel": channel, "batch_id": batch_id,
        "going": ctx["going"], "closed": ctx["closed"], "status": ctx["status"],
        "files": _files(root, d, a), "trend_hunter_done": th is not None,
        "generated_at": (th or {}).get("generated_at"), "language": (th or {}).get("language"),
        "sources_used": [s for s in (th or {}).get("sources_used") or [] if isinstance(s, str)],
        "selection": _pick((th or {}).get("selection"), SELECTION_KEYS),
        "compliance": None if c02 is None else {
            "checked_at": c02.get("checked_at"), "disclaimer": c02.get("disclaimer"),
            "cut": _pick(cut, CUT_KEYS)},
        "search_quota": _quota(th),
        "repairs": ctx["repair_counts"],                                     # CC-0171
        "refill": repair_refill.refill_batch(ctx["refill_read"]),            # CC-0173
        "counts": counts, "topics": summaries, "skipped": skipped,
    }
    return _out(out, root)


def _scene(s):
    desc = s.get("description")
    return {"scene_id": s.get("scene_id"),
            "description": desc[:SCENE_TEXT_MAX] if isinstance(desc, str) else None,
            "tags": [x for x in s.get("tags") or [] if isinstance(x, str)],
            "source_url": s.get("source_url")}


def _fact(t, scripts_raw):
    fp = t.get("fact_probe") if isinstance(t.get("fact_probe"), dict) else None
    fs = t.get("fact_search") if isinstance(t.get("fact_search"), dict) else None
    sc = t.get("support_check") if isinstance(t.get("support_check"), dict) else None
    cands = []
    for c in _rows(t, "fact_candidates"):
        chk = c.get("check") if isinstance(c.get("check"), dict) else {}
        fails = [str(x) for x in chk.get("failures") or []]
        cands.append({"text": c.get("text"), "kind": c.get("kind"), "source": c.get("source"),
                      "url": c.get("url"), "section": c.get("section"),
                      "passes": chk.get("passes"),
                      "failures": fails,
                      "failures_ru": factory.fact_failures_ru(fails),
                      "scenes": [x for x in c.get("scenes") or [] if isinstance(x, str)]})
    chosen = []
    for s in scripts_raw:
        f = s.get("fact") if isinstance(s.get("fact"), dict) else None
        if f:
            chosen.append({"script_id": s.get("script_id"), "text": f.get("text"),
                           "kind": f.get("kind"), "source": f.get("source"),
                           "url": f.get("url"), "primary_url": f.get("primary_url"),
                           "section": f.get("section")})
    return {
        "probe": None if fp is None else {
            k: fp.get(k) for k in ("outcome", "has_fact", "usable", "article", "article_url",
                                   "source", "candidates", "detail", "asked_at")},
        "candidates": cands,
        "search": None if fs is None else {"found": _num(fs.get("found")),
                                           "passing": _num(fs.get("passing")),
                                           "error": fs.get("error")},
        "support": None if sc is None else {
            "state": sc.get("state"), "detail": sc.get("detail"), "pieces": _num(sc.get("pieces")),
            "texts": [{"id": x.get("id"), "kind": x.get("kind"), "source": x.get("source"),
                       "title": x.get("title"), "url": x.get("url")}
                      for x in _rows(t, "support_text")]},
        "chosen": chosen,
    }


def _videos(t):
    ev = t.get("evidence") if isinstance(t.get("evidence"), dict) else {}
    out = []
    for c in _rows(ev, "footage_candidates"):
        vid = c.get("video_id")
        out.append({"video_id": vid,
                    "url": f"https://www.youtube.com/watch?v={vid}" if vid else None,
                    "title": c.get("title"), "channel_title": c.get("channel_title"),
                    "kind": c.get("kind"), "nature": c.get("nature"),
                    "view_count": _num(c.get("view_count")),
                    "duration_seconds": _num(c.get("duration_seconds"))})
    return out


def topic(root, channel, batch_id, topic_id):
    """One topic: the summary's row and its scenes, fact and links."""
    d = batches.batch_dir(root, channel, batch_id)
    if not batches.SAFE_NAME.match(topic_id or ""):
        raise BatchFault(404, "unknown_topic", f"Темы «{topic_id}» в батче нет.",
                         [f"topic {topic_id!r}: not a topic id"])
    a = _read(d)
    th = a.get(TH)
    if th is None:
        raise BatchFault(404, "unknown_topic",
                         f"Темы «{topic_id}» пока нет - трендхантер ещё не записал "
                         f"{TH}.", [f"no {TH} in pipeline/{channel}/{batch_id}"])
    ctx = _context(d, a)
    shortlist = _rows(th, "topics")
    found = [(i, t) for i, t in enumerate(shortlist) if t.get("topic_id") == topic_id]
    q = (th.get("search_quota") or {}) if isinstance(th.get("search_quota"), dict) else {}
    by = q.get("searches_by_topic") if isinstance(q.get("searches_by_topic"), dict) else {}
    searches = {k: n for k, n in by.items()
                if (k == topic_id or str(k).endswith(":" + topic_id)) and _num(n) is not None}
    base = {"batch": f"{channel}/{batch_id}", "channel": channel, "batch_id": batch_id,
            "topic_id": topic_id, "going": ctx["going"], "searches": searches}
    if found:
        i, t = found[0]
        tr = t.get("title_ref") if isinstance(t.get("title_ref"), dict) else {}
        raw = ctx["scripts"].get(topic_id, [])
        out = dict(base, shortlisted=True,
                   summary=_summary(t, i + 1, a, ctx, _idx_at(d, a)), skipped=None,
                   title_ref={k: tr.get(k) for k in ("name", "kind", "type", "year", "season",
                                                     "network", "parent_work", "person",
                                                     "rights_holder")},
                   scenes=[_scene(s) for s in _rows(t, "scenes")],
                   sources=_sources(t), videos=_videos(t), fact=_fact(t, raw))
        return _out(out, root)
    sk = [r for r in _rows(th, "skipped_topics") if r.get("topic_id") == topic_id]
    if not sk:
        raise BatchFault(404, "unknown_topic", f"Темы «{topic_id}» в батче нет.",
                         [f"not in {TH} topics[] nor skipped_topics[]"])
    row = sk[0]
    fp = row.get("fact_probe") if isinstance(row.get("fact_probe"), dict) else None
    out = dict(base, shortlisted=False, summary=None, skipped=_skipped(row, ctx),
               title_ref={"name": row.get("title"), "kind": row.get("kind"), "type": None,
                          "year": None, "season": None, "network": None, "parent_work": None,
                          "person": None, "rights_holder": None},
               scenes=[], sources=[], videos=[],
               fact=_fact({"fact_probe": fp}, []))
    return _out(out, root)
