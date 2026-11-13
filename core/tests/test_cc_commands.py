#!/usr/bin/env python3
"""CC-0034: «всё, что мы умеем, должно иметь интерфейс» - every command a user
runs today has its API address and its screen in the center, or says why not.

The list is `api/commands.json` (beside `api/openapi.json`, the contract it is
checked against): one row per command - `command`, `what`, `api`, `screen`,
`not_in_center`, and optionally `also` (the command's other addresses: its
plan, its sub-reads), `task` (the filed CC- task for what is missing) or `gap`
(the title of a gap the driver is still to file - it becomes `task` then).

Red when:
* a row's `api` / `also` is not an operation of `api/openapi.json`;
* an operation of the contract is no row's `api` / `also` and not in
  `infrastructure` - a new endpoint without a command row;
* a command has no address and no `not_in_center` reason, no `task`, no `gap`;
* a command has an address but no screen and no `task` / `gap` / reason;
* a `screen` is not one of `screens` (the center's routes, copied from the
  frontend's `src/app/areas.ts` / `routes.tsx` at `frontend.commit` - the
  frontend checkout itself is never read);
* the shape is off (unknown keys, a reason or a description not in Russian,
  a duplicate command, a reason beside a screen).

Reads only these two files of the repository - no network, no live data.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMMANDS = ROOT / "api" / "commands.json"
OPENAPI = ROOT / "api" / "openapi.json"

METHODS = ("get", "post", "put", "patch", "delete")
KEYS = {"command", "what", "api", "screen", "not_in_center"}
OPTIONAL = {"also", "task", "gap"}
ADDRESS = re.compile(r"^(GET|POST|PUT|PATCH|DELETE) (/api/\S*)$")
TASK = re.compile(r"^CC-\d{4}$")
CYRILLIC = re.compile(r"[А-Яа-яЁё]")


def _doc():
    return json.loads(COMMANDS.read_text(encoding="utf-8"))


def _operations():
    spec = json.loads(OPENAPI.read_text(encoding="utf-8"))
    return {f"{m.upper()} {p}" for p, ops in spec["paths"].items() for m in ops if m in METHODS}


def _rows():
    rows = _doc()["commands"]
    assert isinstance(rows, list) and rows, "api/commands.json has no commands"
    return rows


def _addresses(row):
    out = [row["api"]] if row["api"] else []
    return out + list(row.get("also") or [])


def _russian(text, min_len=4):
    return isinstance(text, str) and len(text.strip()) >= min_len and bool(CYRILLIC.search(text))


def test_every_row_has_its_shape():
    bad, seen = [], set()
    for i, r in enumerate(_rows()):
        name = r.get("command", f"#{i}")
        missing, extra = KEYS - set(r), set(r) - KEYS - OPTIONAL
        if missing or extra:
            bad.append(f"{name}: missing {sorted(missing)}, unknown {sorted(extra)}")
            continue
        if not isinstance(r["command"], str) or not r["command"].strip():
            bad.append(f"#{i}: empty command")
        if r["command"] in seen:
            bad.append(f"{name}: the command twice")
        seen.add(r["command"])
        if not _russian(r["what"]):
            bad.append(f"{name}: `what` is not a Russian line")
        if r["not_in_center"] is not None and not _russian(r["not_in_center"], 10):
            bad.append(f"{name}: `not_in_center` is not a Russian reason")
        if r["not_in_center"] is not None and r["screen"] is not None:
            bad.append(f"{name}: a screen and a reason why it is not in the center")
        if "also" in r and (not isinstance(r["also"], list) or not r["also"]):
            bad.append(f"{name}: `also` is not a list of addresses")
        if "also" in r and not r["api"]:
            bad.append(f"{name}: `also` without `api`")
        if "task" in r and not (isinstance(r["task"], str) and TASK.match(r["task"])):
            bad.append(f"{name}: `task` {r['task']!r} is not CC-NNNN")
        if "gap" in r and not _russian(r.get("gap"), 10):
            bad.append(f"{name}: `gap` is not a Russian title")
        if "task" in r and "gap" in r:
            bad.append(f"{name}: both `task` and `gap` - a filed gap is a task")
        for a in _addresses(r):
            if not (isinstance(a, str) and ADDRESS.match(a)):
                bad.append(f"{name}: {a!r} is not `METHOD /api/path`")
    assert not bad, "api/commands.json:\n  " + "\n  ".join(bad)


def test_every_address_is_in_the_contract():
    ops = _operations()
    bad = [f"{r['command']}: {a}" for r in _rows() for a in _addresses(r) if a not in ops]
    bad += [f"infrastructure: {x['api']}" for x in _doc()["infrastructure"] if x["api"] not in ops]
    assert not bad, "addresses not in api/openapi.json:\n  " + "\n  ".join(bad)


def test_every_operation_of_the_contract_has_a_command():
    used = {a for r in _rows() for a in _addresses(r)}
    infra = _doc()["infrastructure"]
    for x in infra:
        assert _russian(x.get("why"), 10), f"infrastructure {x.get('api')}: no Russian `why`"
    used |= {x["api"] for x in infra}
    lost = sorted(_operations() - used)
    assert not lost, ("operations of api/openapi.json no command of api/commands.json names "
                      "(add the command's row, or `infrastructure` with why):\n  " + "\n  ".join(lost))


def test_every_command_has_an_address_or_says_why_not():
    bad = [r["command"] for r in _rows()
           if not r["api"] and not r["not_in_center"] and "task" not in r and "gap" not in r]
    assert not bad, ("commands with no API address and no `not_in_center` reason, `task` or "
                     "`gap`:\n  " + "\n  ".join(bad))


def test_every_address_has_a_screen_or_its_task():
    bad = [r["command"] for r in _rows()
           if r["api"] and not r["screen"] and not r["not_in_center"]
           and "task" not in r and "gap" not in r]
    assert not bad, ("commands with an address but no screen, `task` or `gap`:\n  "
                     + "\n  ".join(bad))


def test_every_screen_is_a_route_of_the_center():
    doc = _doc()
    screens = set(doc["screens"])
    assert "/" in screens and doc["frontend"]["commit"], "screens / frontend.commit lost"
    for route, task in doc["screens_soon"].items():
        assert route not in screens and TASK.match(task), f"screens_soon {route}: {task!r}"
    bad = [f"{r['command']}: {r['screen']}" for r in _rows()
           if r["screen"] is not None and r["screen"] not in screens]
    assert not bad, "screens that are not routes of the center:\n  " + "\n  ".join(bad)


def test_the_tally():
    """Not a check - the numbers, printed for the report and the driver."""
    rows = _rows()
    both = sum(1 for r in rows if r["api"] and r["screen"])
    api_only = sum(1 for r in rows if r["api"] and not r["screen"])
    none = sum(1 for r in rows if not r["api"] and not r["not_in_center"])
    nic = sum(1 for r in rows if r["not_in_center"])
    gaps = sorted({r["gap"] for r in rows if "gap" in r})
    print(f"  {len(rows)} commands: api+screen {both}, api only {api_only}, "
          f"no api {none}, not in center {nic}; unfiled gaps {len(gaps)}")
    for g in gaps:
        print(f"    gap: {g}")
    assert both + api_only + none + nic == len(rows)


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
