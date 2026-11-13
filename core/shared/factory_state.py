#!/usr/bin/env python3
"""CF-0590: the factory's state, as data - one collector per section, every
one of them a reader of the module that already owns the record. Written for
the read-only console of 2.2 (`shared/dashboard/collect.py`); since CC-0035
(the command center 1.0, the console retired) it lives here and is read by
the center's API (api/factory.py `collect()`) and by shared/batch_schedule.py.

Nothing here writes, asks the network or reads a secret's value. Each section
is `{"ok": ...}` / `{"missing": why}` / `{"error": why}`: a file that is not
there is said, a file that does not parse is said, and neither stops the page
(`_guard`). The data root (`root`) and the code (this checkout) are two things:
a worktree's code can be pointed at any factory tree with `root`.

Sections, per channel of `channels/*.json` (no channel is spelled here):

    feed        publish_queue.table/waiting (CF-0587), channel_pause.status
                (CF-0569), upload journal rows ahead (CF-0586), unsigned holds
                of publication-holds.json (CF-0318)
    batch       runlog.open_batches (CF-0398) + <batch>/run-state.json of the
                executor (CF-0203); the estimate to the end is from the mean
                wall of the channel's runs in pipeline/runs.jsonl (an estimate,
                said so) and the stage's `timeout_min` ceiling (CF-0204)
    acceptance  videos of the channel's recent batches (05-video-editor.json)
                with no row in publish/acceptance-log.json (CF-0328), each with
                its card (publish_card.card_state, CF-0017) and mp4 path
    metrics     the last analytics/<ch>/summary/<day>.json (CF-0021) and the
                top of analytics/<ch>/footage-wanted.json (CF-0023)
    schedule    the batch plan (CF-0592, shared/batch_schedule.py): the days this
                channel gets the factory's batch, its window and estimates, the
                switch - registered in `SCHEDULE_PROVIDERS`

A channel whose config says `status: no_pipeline` (CF-0562: the channel exists,
its pipeline is a later milestone) gets none of these: its entry is `{"id",
"no_pipeline": "конвейера нет - батча не будет (...)", "schedule"}`. A config
whose `status` is unknown or half a stub gets the sections and a
`config_error`.

and, for the whole factory: the batch plan of every day and the switch
(CF-0592), the user's pending reminders (shared/notify.py, CF-0606 - read
only), the OAuth token (publisher_auth.status, CF-0589 -
the kind and its line, never a value), the questions still waiting in the
journal of questions (shared/needs_you.py, CF-0652 - until then NEEDS-YOU.md).
"""
import importlib.util
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

CODE = Path(__file__).resolve().parents[1]
TASK = "CF-0590"
ACCEPTANCE_HORIZON_DAYS = 14
FEED_DAYS = 14
RUNS_FOR_ESTIMATE = 10
FOOTAGE_TOP = 5
BATCH_ID_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2})(\d{2})Z")

# A callable (channel, root, now) -> {"rows": [...], ...} or None; the first
# that answers is the channel's section. CF-0592 registers `batch_plan` below.
SCHEDULE_PROVIDERS = []

for _p in (CODE / "agents" / "publisher", CODE / "agents" / "analyst",
           CODE / "shared" / "runlog", CODE / "shared"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_MODS = {}


def _mod(name, rel):
    """A module of this checkout, loaded once by path."""
    if name not in _MODS:
        if name in sys.modules and Path(getattr(sys.modules[name], "__file__", "") or "") \
                .resolve() == (CODE / rel).resolve():
            _MODS[name] = sys.modules[name]
        else:
            spec = importlib.util.spec_from_file_location(name, CODE / rel)
            m = importlib.util.module_from_spec(spec)
            sys.modules[name] = m
            spec.loader.exec_module(m)
            _MODS[name] = m
    return _MODS[name]


def queue():
    return _mod("publish_queue", "agents/publisher/publish_queue.py")


def pause():
    return _mod("channel_pause", "agents/publisher/channel_pause.py")


def journal():
    return _mod("upload_records", "agents/publisher/upload_records.py")


def card():
    return _mod("publish_card", "agents/publisher/publish_card.py")


def note():
    return _mod("publish_note", "agents/publisher/publish_note.py")


def auth():
    return _mod("publisher_auth", "agents/publisher/publisher_auth.py")


def api_data():
    return _mod("api_data", "agents/publisher/api_data.py")


def api_switch():
    return _mod("api_switch", "agents/publisher/api_switch.py")


def pubcfg():
    return _mod("publisher_config", "agents/publisher/publisher_config.py")


def needs_you_journal():
    return _mod("needs_you", "shared/needs_you.py")


def acceptance():
    return _mod("acceptance", "shared/runlog/acceptance.py")


def runlog():
    return _mod("runlog", "shared/runlog/runlog.py")


def run_plan():
    return _mod("run_plan", "shared/run_plan.py")


def channel_ids():
    return _mod("channel_ids", "shared/channel_ids.py")


def batch_schedule():
    return _mod("batch_schedule", "shared/batch_schedule.py")


def notify_bus():
    return _mod("notify", "shared/notify.py")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def now_utc(now=None):
    if now is None:
        return datetime.now(timezone.utc).replace(microsecond=0)
    if isinstance(now, datetime):
        return now
    dt = datetime.fromisoformat(str(now).strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"{now!r} has no zone")
    return dt


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def parse_ts(text):
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(str(text).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def batch_time(batch_id):
    m = BATCH_ID_RE.match(str(batch_id or ""))
    if not m:
        return None
    return datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}:{m.group(3)}:00+00:00")


def rel(path, root):
    """`path` relative to the data root when it lies under it (a symlinked
    `pipeline/` of a worktree too), else as given."""
    for a, b in ((Path(path).absolute(), Path(root).absolute()),
                 (Path(path).resolve(), Path(root).resolve())):
        try:
            return str(a.relative_to(b))
        except ValueError:
            continue
    return str(path)


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _guard(fn, *args, **kw):
    """A section never takes the page down: an exception is its `error`."""
    try:
        return fn(*args, **kw)
    except Exception as e:                                      # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


def channels(root):
    d = Path(root) / "channels"
    return sorted(p.stem for p in d.glob("*.json")) if d.is_dir() else []


def resolve_channel(channel, root):
    """A channel read out of a record, under its current id (CF-0250)."""
    try:
        return channel_ids().resolve_channel(channel, root)
    except Exception:                                           # noqa: BLE001
        return channel


# --------------------------------------------------------------------------
# 1. the feed: slots, empty days, pause, holds
# --------------------------------------------------------------------------

def feed(channel, root, now, days=FEED_DAYS):
    pq = queue()
    out = {}
    try:
        st = pause().status(channel, root, now)
        out["pause"] = {"state": st["state"], "line": st["line"]}
    except Exception as e:                                      # noqa: BLE001
        out["pause"] = {"state": "error", "line": f"{type(e).__name__}: {e}"}
    out["holds"] = _guard(holds, channel, root)
    cfg = pq.slot_config(channel, root)
    if cfg is None:
        out["missing"] = (f"в channels/{channel}.json нет publisher.slot - у канала нет очереди "
                          f"публикаций (CF-0587)")
        return out
    jpath = Path(root) / "publish" / "uploads.json"
    if not jpath.is_file():
        out["journal_missing"] = "publish/uploads.json нет - занятость только по папкам дней"
    rows = pq.table(channel, root, now, days, journal=jpath, cfg=cfg)
    try:
        nxt = pq.next_free(channel, root, now, journal=jpath, cfg=cfg)
    except pq.QueueError:
        nxt = None
    studio = {}
    for r in journal().uploads(jpath, channel) if jpath.is_file() else []:
        if not r.get("removed_at") and not r.get("withdrawn") and r.get("slug"):
            studio[r["slug"]] = r.get("video_id")
    slots, per_day = [], {}
    for r in rows:
        slots.append({"at": iso(r["at"]), "label": pq.label(r["at"], cfg), "day": r["day"],
                      "taken_by": r["taken_by"], "in_studio": r["taken_by"] in studio,
                      "next_free": nxt is not None and r["at"] == nxt})
        per_day.setdefault(r["day"], []).append(r["taken_by"])
    out["ok"] = True
    out["rule"] = (f"{cfg['per_day']}/день в {', '.join(t.strftime('%H:%M') for t in cfg['times'])} "
                   f"{cfg['tz']}, не позже чем за {cfg['lead'].total_seconds() / 3600:g} ч до слота")
    out["slots"] = slots
    out["empty_days"] = sorted(d for d, taken in per_day.items() if not any(taken))
    out["next_free"] = pq.label(nxt, cfg) if nxt else None
    out["waiting"] = sorted(pq.waiting(channel, root))
    return out


def holds(channel, root):
    p = Path(root) / "publish" / "publication-holds.json"
    if not p.is_file():
        return {"missing": "publish/publication-holds.json нет"}
    rows = acceptance().holds(p)
    mine = [h for h in rows if resolve_channel(h.get("channel"), root) == channel
            and h.get("verdict") == "review" and not h.get("resolved_at") and not h.get("signature")]
    return {"ok": True, "rows": [{"hold_id": h.get("hold_id"), "batch_id": h.get("batch_id"),
                                  "topic_id": h.get("topic_id"), "reason": h.get("reason_code")
                                  or h.get("reason")} for h in
                                 sorted(mine, key=lambda h: str(h.get("hold_id")))]}


# --------------------------------------------------------------------------
# 2. the batch that is going
# --------------------------------------------------------------------------

def _events(batch):
    p = Path(batch) / "RUN_EVENTS.jsonl"
    out = []
    if not p.is_file():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _markers(batch):
    """(started, current stage, its start) from the batch's markers."""
    started, open_ = None, {}
    for e in _events(batch):
        if e.get("kind") != "marker":
            continue
        if e.get("status") == "batch-start" and started is None:
            started = parse_ts(e.get("ts"))
        elif e.get("status") == "stage-start" and e.get("stage"):
            open_[e["stage"]] = parse_ts(e.get("ts"))
        elif e.get("status") == "stage-done" and e.get("stage"):
            open_.pop(e["stage"], None)
    cur = max(open_.items(), key=lambda kv: kv[1] or datetime.min.replace(tzinfo=timezone.utc)) \
        if open_ else (None, None)
    return started, cur[0], cur[1]


def _batch_channel(batch, root):
    p = Path(batch) / "run-state.json"
    if p.is_file():
        try:
            ch = resolve_channel(_read_json(p).get("channel"), root)
            if ch:
                return ch
        except (OSError, ValueError):
            pass
    parent = Path(batch).parent.name
    if parent != "rebuilds":
        return resolve_channel(parent, root)
    for name in ("05-video-editor.json", "03-content-researcher.json"):
        try:
            ch = resolve_channel(_read_json(Path(batch) / name).get("channel"), root)
            if ch:
                return ch
        except (OSError, ValueError):
            continue
    return None


def mean_wall(channel, root):
    """(seconds, n) - the mean wall time of the channel's last runs, or (None, 0)."""
    p = Path(root) / "pipeline" / "runs.jsonl"
    if not p.is_file():
        return None, 0
    walls = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if resolve_channel(r.get("channel"), root) == channel and isinstance(r.get("wall_s"), (int, float)):
            walls.append(float(r["wall_s"]))
    walls = walls[-RUNS_FOR_ESTIMATE:]
    return (sum(walls) / len(walls), len(walls)) if walls else (None, 0)


def _timeouts(channel, root):
    try:
        plan = run_plan().load(channel, root)
    except Exception:                                           # noqa: BLE001
        return {}
    return {s.get("id"): s.get("timeout_min") for s in plan.get("stages") or []
            if isinstance(s, dict) and s.get("timeout_min")}


def batches(root, now, open_rows=None):
    """Every open batch: `[{dir, channel, ...}]`."""
    rows = open_rows if open_rows is not None else runlog().open_batches(root, now=now)
    out = []
    for d, last, fresh in rows:
        out.append(_batch(Path(d), last, fresh, root, now))
    return sorted(out, key=lambda b: b["dir"])


def _batch(d, last, fresh, root, now):
    b = {"dir": rel(d, root), "batch_id": d.name, "fresh": bool(fresh),
         "last_event": iso(last) if last else None, "channel": _batch_channel(d, root)}
    started, stage, stage_at = _markers(d)
    state = None
    sp = d / "run-state.json"
    if sp.is_file():
        try:
            state = _read_json(sp)
        except (OSError, ValueError) as e:
            b["state_error"] = f"run-state.json не читается ({e})"
    if state:
        b["source"] = "run-state.json (CF-0203)"
        b["status"] = state.get("status")
        cur = (state.get("current") or {}).get("stage")
        st = (state.get("stages") or {}).get(cur) or {}
        stage, stage_at = cur or stage, parse_ts(st.get("started")) or stage_at
        started = parse_ts(state.get("created")) or started
        order = state.get("order") or []
        b["stages"] = [{"id": s, "status": ((state.get("stages") or {}).get(s) or {})
                        .get("status", "pending")} for s in order]
        b["next"] = state.get("next")
        b["needs_human"] = [f"{h.get('stage')}: {h.get('took')}" for h in state.get("needs_human") or []]
        # CF-0713: a stage that changed the factory's tracked code (run_executor's check)
        b["code_edits"] = [f"{c.get('stage')}: " + "; ".join(
            f"{e.get('repo')}: {', '.join(e.get('files') or []) or 'commit'}"
            for e in c.get("edits") or []) for c in state.get("code_edits") or []]
        if state.get("halt_reason"):
            b["halt_reason"] = state["halt_reason"]
    else:
        b["source"] = "маркеры RUN_EVENTS.jsonl (без run-state.json)"
    b["started"] = iso(started)
    b["stage"] = stage
    b["stage_started"] = iso(stage_at)
    b["elapsed_s"] = int((now - started).total_seconds()) if started else None
    b["stage_elapsed_s"] = int((now - stage_at).total_seconds()) if stage_at else None
    if b["channel"]:
        ceiling = _timeouts(b["channel"], root).get(stage)
        if ceiling:
            b["stage_timeout_min"] = ceiling
        mean, n = mean_wall(b["channel"], root)
        if mean is not None and b["elapsed_s"] is not None:
            b["estimate"] = {"mean_wall_s": int(mean), "runs": n,
                             "left_s": int(mean - b["elapsed_s"])}
    return b


# --------------------------------------------------------------------------
# 3. videos waiting for the user's acceptance, with their cards
# --------------------------------------------------------------------------

def _batch_dirs(channel, root, now, horizon):
    pipe = Path(root) / "pipeline"
    cands = list((pipe / channel).glob("*/05-video-editor.json")) if (pipe / channel).is_dir() else []
    try:
        for former in channel_ids().channel_names(channel, root):
            if former != channel and (pipe / former).is_dir():
                cands += list((pipe / former).glob("*/05-video-editor.json"))
    except Exception:                                           # noqa: BLE001
        pass
    cands += [p for p in (pipe / "rebuilds").glob("*/05-video-editor.json")
              if _batch_channel(p.parent, root) == channel] if (pipe / "rebuilds").is_dir() else []
    out = []
    for p in sorted(set(cands)):
        t = batch_time(p.parent.name)
        if t is None or now - t > timedelta(days=horizon):
            continue
        out.append(p.parent)
    return out


def waiting_acceptance(channel, root, now, horizon=ACCEPTANCE_HORIZON_DAYS):
    log = Path(root) / "publish" / "acceptance-log.json"
    acc = acceptance()
    rows = acc.entries(path=log) if log.is_file() else []
    out = {"ok": True, "horizon_days": horizon, "videos": []}
    if not log.is_file():
        out["log_missing"] = "publish/acceptance-log.json нет - ни один вердикт не записан"
    known, latest = set(), {}
    for r in rows:
        known.update(acc.row_keys(r))
        if resolve_channel(r.get("channel"), root) == channel and r.get("slug"):
            t = batch_time(r.get("batch_id")) or datetime.max.replace(tzinfo=timezone.utc)
            latest[r["slug"]] = max(latest.get(r["slug"], t), t)
    superseded = 0
    for bdir in _batch_dirs(channel, root, now, horizon):
        try:
            d05 = _read_json(bdir / "05-video-editor.json")
        except (OSError, ValueError) as e:
            out["videos"].append({"batch_id": bdir.name, "error": f"05-video-editor.json: {e}"})
            continue
        for v in d05.get("videos") or []:
            if not isinstance(v, dict) or not v.get("output_path"):
                continue
            slug = Path(str(v["output_path"])).stem
            if f"{channel}/{bdir.name}/{slug}" in known or \
                    acc.find(channel, bdir.name, slug, rows=rows) is not None:
                continue
            if slug in latest and latest[slug] >= batch_time(bdir.name):
                superseded += 1     # the same video got its verdict in this batch's rebuild or later
                continue
            mp4 = bdir / "videos" / f"{slug}.mp4"
            if not mp4.is_file() and Path(str(v["output_path"])).is_file():
                mp4 = Path(str(v["output_path"]))
            out["videos"].append({"batch_id": bdir.name, "slug": slug,
                                  "script_id": v.get("script_id"),
                                  "mp4": rel(mp4, root), "mp4_exists": mp4.is_file(),
                                  "card": _card(bdir / "work" / "publish-card" / f"{slug}.md", root)})
    out["videos"].sort(key=lambda x: (x.get("batch_id") or "", x.get("slug") or ""))
    out["superseded"] = superseded
    return out


def _card(path, root):
    if not path.is_file():
        return {"missing": f"карточки нет ({rel(path, root)}) - publish_card.py build не запускался"}
    text = path.read_text(encoding="utf-8")
    pc, pn = card(), note()
    ready, why = pc.card_state(text)
    sec = pn.sections(text)
    title, description = pn.title_and_description(sec)
    mark = pc.mark_of(text) or {}
    claims = (mark.get("claims") or {}).get("verdict")
    return {"path": rel(path, root), "ready": ready, "why": why, "title": title,
            "about": description.split("\n\n")[0].strip() if description else "",
            "claims_block": "Утверждения" in sec, "claims_verdict": claims}


# --------------------------------------------------------------------------
# 4. open questions (CF-0652: the journal of questions, shared/needs_you.py)
# --------------------------------------------------------------------------

def needs_you_where(explicit=None, root=None):
    """--needs-you-dir, else the journal of the root shown."""
    if explicit:
        return Path(explicit).expanduser()
    return needs_you_journal().journal_dir(root)


QUESTION_FIELDS = ("id", "status", "source", "channel", "text", "link", "created", "updated",
                   "answer", "answered_by", "answered_at")


def needs_you(directory, chans=(), root=None):
    """The questions still waiting (open, answered), oldest first. No journal
    yet is no question, not a missing section."""
    j = needs_you_journal()
    d = Path(directory)
    lines = []
    for q in j.live(root=root, directory=d):      # the channel resolved by the journal
        row = {k: q.get(k) for k in QUESTION_FIELDS}
        row["channels"] = sorted({q["channel"]} if q["channel"] in chans else
                                 {c for c in chans if c in (q.get("text") or "")})
        lines.append(row)
    return {"ok": True, "path": str(d / j.JOURNAL), "lines": lines,
            "open": sum(1 for x in lines if x["status"] == "open"),
            "answered": sum(1 for x in lines if x["status"] == "answered")}


# --------------------------------------------------------------------------
# 6. the OAuth token - status only
# --------------------------------------------------------------------------

def token(now, env_file=None, environ=None, root=None):
    """CF-0618: with the token, the API Data line (`api_data.status`): the
    revocation mark and the day the API Data is deleted, or the journal's API
    rows and their refresh."""
    pc, pa = pubcfg(), auth()
    try:
        cfg = pc.load(env_file, environ)
    except pc.ConfigError as e:
        return {"error": f"конфигурация публикатора: {e}"}
    st = pa.status(cfg, now)
    try:
        ad = api_data().status(cfg, root or CODE, now)
    except Exception as e:                                       # noqa: BLE001
        ad = {"kind": "bad", "line": f"API Data: статус не прочитан ({type(e).__name__}: {e})"}
    return {"ok": True, "kind": st.kind, "code": st.code, "line": st.line,
            "oauth_mode": cfg.oauth_mode, "token_mode": st.mode,         # CF-0607
            "expires_at": iso(st.expires_at) if st.expires_at else None,
            "hours_left": round(st.hours_left, 1) if st.hours_left is not None else None,
            "api_data": ad}


# --------------------------------------------------------------------------
# 6b. the API upload's switch (CF-0607)
# --------------------------------------------------------------------------

def api_upload(root, now, env_file=None, environ=None):
    """`{"warnings": [...], "channels": {ch: state}}` - the switch of every
    channel (`api_switch.channel_state`) and what enabling it would warn about
    now (the same warnings `enable` writes into the history)."""
    sw = api_switch()
    root = Path(root)
    try:
        warn = sw.warnings(None, root, env_file, environ, now)
    except Exception as e:                                       # noqa: BLE001
        warn = [f"предупреждения не посчитаны ({type(e).__name__}: {e})"]
    states = {}
    for st in sw.status(root, environ):
        states[st["channel"]] = {"on": st["on"], "line": st["line"],
                                 "warnings": st["warnings"], "history": st["history"][-3:]}
    return {"ok": True, "warnings": warn, "channels": states}


# --------------------------------------------------------------------------
# 7. metrics in short
# --------------------------------------------------------------------------

def metrics(channel, root):
    base = Path(root) / "analytics" / channel
    out = {}
    days = sorted((base / "summary").glob("*.json")) if (base / "summary").is_dir() else []
    if not days:
        out["summary"] = {"missing": f"сводки нет (analytics/{channel}/summary/<день>.json, CF-0021)"}
    else:
        try:
            s = _read_json(days[-1])
            out["summary"] = {"ok": True, "day": s.get("day") or days[-1].stem,
                              "path": rel(days[-1].with_suffix(".md"), root),
                              "counts": s.get("counts") or {},
                              "first_days": s.get("first_days")}
        except (OSError, ValueError) as e:
            out["summary"] = {"error": f"{rel(days[-1], root)}: {e}"}
    fw = base / "footage-wanted.json"
    if not fw.is_file():
        out["footage_wanted"] = {"missing": f"analytics/{channel}/footage-wanted.json нет (CF-0023)"}
    else:
        try:
            d = _read_json(fw)
            rows = []
            for r in (d.get("rows") or [])[:FOOTAGE_TOP]:
                reasons = r.get("reasons") or {}
                top = max(sorted(reasons), key=lambda k: reasons[k]) if isinstance(reasons, dict) \
                    and reasons else None
                rows.append({"name": r.get("name"), "kind": r.get("kind"),
                             "misses": r.get("misses"), "batches": r.get("batches"),
                             "reason": top, "in_pool_now": r.get("in_pool_now")})
            out["footage_wanted"] = {"ok": True, "built_at": d.get("built_at"),
                                     "path": rel(fw.with_suffix(".md"), root), "rows": rows}
        except (OSError, ValueError) as e:
            out["footage_wanted"] = {"error": f"{rel(fw, root)}: {e}"}
    return out


# --------------------------------------------------------------------------
# 8. the batch plan (CF-0592)
# --------------------------------------------------------------------------

# One plan per page: `collect()` makes it once (with its open batches) and the
# provider of each channel reads it; a provider called on its own makes its own.
_PLAN = {}


def schedule_plan(root, now, open_rows=None):
    return batch_schedule().plan(root, now, open_rows=open_rows)


def _plan_for(root, now):
    if _PLAN.get("key") == (str(root), iso(now)):
        return _PLAN["plan"]
    return schedule_plan(root, now)


def batch_plan(channel, root, now):
    """CF-0592: the channel's days of the factory's batch plan."""
    p = _plan_for(root, now)
    if isinstance(p, dict) and p.get("error"):
        return {"error": p["error"]}
    return batch_schedule().channel_section(channel, p)


SCHEDULE_PROVIDERS.append(batch_plan)


def schedule(channel, root, now):
    for provider in SCHEDULE_PROVIDERS:
        got = provider(channel, root, now)
        if got is not None:
            return got if got.get("error") else dict(got, ok=True)
    return {"missing": "плана батчей для канала нет"}


def schedule_factory(plan):
    if isinstance(plan, dict) and plan.get("error"):
        return plan
    return dict(batch_schedule().factory_section(plan), ok=True)


# --------------------------------------------------------------------------
# CF-0606: the user's reminders (shared/notify.py) - read only
# --------------------------------------------------------------------------

def reminders(root, now, environ=None):
    bus = notify_bus()
    env = os.environ if environ is None else environ
    allr = bus.reminders(root, env)
    pending = bus.pending_reminders(root, env)
    unsent = bus.unsent_reminders(root, env)
    return {"ok": True, "path": str(bus.reminders_path(root, env)),
            "pending": [dict(r, due_msk=bus.msk_text(r["due"]),
                             overdue=bus._utc(r["due"]) <= now)
                        for r in pending if r["status"] == "pending"],
            # CF-0617: tried and not delivered - `failed` (another try at the
            # next tick) and `exhausted` (no more tries), with the reason
            "unsent": [dict(r, due_msk=bus.msk_text(r["due"]),
                            last_try_msk=bus.msk_text(r["last_try"]) if r.get("last_try") else None)
                       for r in unsent],
            "max_attempts": bus.REMINDER_MAX_ATTEMPTS,
            "sent": sum(1 for r in allr if r["status"] == "sent"),
            "cancelled": sum(1 for r in allr if r["status"] == "cancelled")}


# --------------------------------------------------------------------------
# everything
# --------------------------------------------------------------------------

def collect(root=None, now=None, needs_you_dir=None, env_file=None, environ=None,
            open_rows=None, horizon=ACCEPTANCE_HORIZON_DAYS, feed_days=FEED_DAYS):
    """The whole page as data. `open_rows` stands in for `runlog.open_batches`
    (tests); `environ` for os.environ (the token's configuration)."""
    root = Path(root or CODE).resolve()
    now = now_utc(now)
    chans = channels(root)
    open_b = _guard(batches, root, now, open_rows)
    data = {"task": TASK, "root": str(root), "now": iso(now), "channels": [],
            "token": _guard(token, now, env_file, environ, root),
            "needs_you": _guard(needs_you, needs_you_where(needs_you_dir, root), chans, root),
            "reminders": _guard(reminders, root, now, environ),
            "batches": open_b}
    plan = _guard(schedule_plan, root, now, open_rows)
    data["schedule"] = _guard(schedule_factory, plan)
    api = _guard(api_upload, root, now, env_file, environ)
    _PLAN.update(key=(str(root), iso(now)), plan=plan)
    try:
        _channels_into(data, chans, open_b, root, now, horizon, feed_days)
    finally:
        _PLAN.clear()
    for c in data["channels"]:
        c["api_upload"] = (dict(api["channels"].get(c["id"]) or {"on": False}, ok=True,
                                enable_warnings=api["warnings"]) if api.get("ok") else api)
    return data


def no_pipeline(channel, root):
    """CF-0562: «конвейера нет - батча не будет (...)» for a channel whose
    config says `status: no_pipeline`, None for a channel with a pipeline."""
    return channel_ids().channel_no_pipeline(channel, root)


def _channels_into(data, chans, open_b, root, now, horizon, feed_days):
    for ch in chans:
        stub = _guard(no_pipeline, ch, root)
        if isinstance(stub, str):
            # No feed, batch, acceptance or metrics to read: the page
            # says the one line and the plan's own line for it (CF-0562).
            data["channels"].append({"id": ch, "no_pipeline": stub,
                                     "schedule": _guard(schedule, ch, root, now)})
            continue
        mine = [b for b in open_b if b["channel"] == ch]   # resolved by _batch if isinstance(open_b, list) else open_b
        data["channels"].append({
            "config_error": stub.get("error") if isinstance(stub, dict) else None,
            "id": ch,
            "feed": _guard(feed, ch, root, now, feed_days),
            "batch": mine,
            "acceptance": _guard(waiting_acceptance, ch, root, now, horizon),
            "metrics": _guard(metrics, ch, root),
            "schedule": _guard(schedule, ch, root, now),
        })
