"""CC-0124: the development tasks of the factory and of the center, read only
(`GET /api/dev/tasks`, `/api/dev/tasks/{id}`, `/api/dev/roadmap`).

Where they are read - always from git, never from a working tree:

* the factory: `tasks/CF-*.md` and `tasks/archive/<v>/CF-*.md` and
  `ROADMAP.md` of the root's repo, on the branch `main` and on every version
  line in work (`agents_lock.versions_in_work`, CF-0716: a `release/<v>` a
  live worktree has checked out). A task on a version line wins over its copy
  on `main` (the version's work happens there) when the two files differ; the
  row says its `branch`.
  The roadmap is the last version line's when one is in work, else `main`'s;
* the center: `tasks/CC-*.md`, `tasks/archive/<v>/CC-*.md` and `ROADMAP.md`
  on `main` of the center's repo - the module `frontend` of the root's
  `agents.lock.json` (`<root>/<its path>`, `frontend` when the lock does not
  say). That checkout is often detached (the production build); `main` is
  the dev line every worktree of that repo shares.

Every git child goes through the factory's door (`factory.git_read().run`,
CF-0717) with optional locks off; nothing here writes.

Kept: a branch's parsed tree per its sha. A request asks each repo for the
shas of its branches (one `git for-each-ref`) and parses only a sha it has
not seen; the version lines in work are asked again after `LINES_TTL_S`.
The commits of a task are kept per (id, the shas searched).

No absolute path of this machine leaves: the sources' paths and refusals go
through `paths.clean`; the markdown (titles, bodies, checklist lines, commit
subjects) has the root's, this checkout's and the working copy's prefixes cut,
the home directory `~` and an absolute path under a system directory
(`/Users`, `/home`, `/private`, `/tmp`, `/Volumes`, ...) `.../<last part>` -
an API path like `/api/dev/tasks` is text and stays.
"""
import json
import os
import re
import threading
import time
from pathlib import Path

from . import factory, paths
from .batches import BatchFault

GIT_TIMEOUT_S = 60
LINES_TTL_S = 30.0
COMMITS_LIMIT = 30
#: how many messages `git log --grep` hands over before the subject is checked
COMMITS_SCAN = 200
MAIN = "main"
PROJECTS = ("factory", "center")
PREFIX = {"factory": "CF", "center": "CC"}
CENTER_MODULE = "frontend"

ID = re.compile(r"^(CF|CC)-\d{4}$")
ANY_ID = re.compile(r"(?<![A-Za-z0-9])((?:CF|CC)-\d{4})(?!\d)")
FILE = re.compile(r"^tasks/(?:archive/([^/]+)/)?((CF|CC)-\d{4})[^/]*\.md$")
CHECK = re.compile(r"^\s*[-*+] \[([ xX])\]\s+(.*?)\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")
#: a top-level list item that starts with a task id (the older milestones: `- `CF-0003` — ...`)
ITEM = re.compile(r"^(?:[-*+]|\d+\.)\s+[`*\[]{0,3}((?:CF|CC)-\d{4})(?!\d)")
EMPTY = {"", "—", "-", "–", "null", "~", "none"}
FIELDS = ("id", "title", "type", "status", "milestone", "repo", "created", "closed", "dod")
VERSION = re.compile(r"^\d+(?:\.\d+)+$")
DONE = re.compile(r"\*\*DONE (\d{4}-\d{2}-\d{2})")
#: an absolute path under a directory of the system (not `/api/...`)
SYS_ABS = re.compile(r"(?<![\w.~/])/(?:Users|home|private|Volumes|tmp|var|opt|mnt|srv|root|"
                     r"etc|Library|Applications)/(?:[^\s/:;,'\"()`<>]+/)*([^\s/:;,'\"()`<>]+)")

_LOCK = threading.RLock()
_TREES = {}       # (repo, branch) -> (sha, {"tasks": {id: task}, "roadmap": text|None})
_INDEX = {}       # key of the shas -> index
_LINES = {}       # root -> (monotonic, [release/<v>])
_COMMITS = {}     # (id, shas) -> [commit]


class GitFailed(Exception):
    pass


# ------------------------------------------------------------------------ git
def _git(repo, *args, input=None):
    """git `args` in `repo` through the factory's door - bytes out."""
    gr = factory.git_read()
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_TERMINAL_PROMPT="0", LC_ALL="C", **gr.GIT_READ_ENV)
    cp = gr.run(["-C", str(repo), *args], capture_output=True, input=input, env=env,
                timeout=GIT_TIMEOUT_S)
    if cp.returncode != 0:
        raise GitFailed(f"git {' '.join(args[:3])}: exit {cp.returncode}: "
                        f"{(cp.stderr or b'').decode('utf-8', 'replace').strip()}")
    return cp.stdout


def _text(b):
    return b.decode("utf-8", "replace")


def _refs(repo, branches):
    """{branch: sha} of the branches that exist - one `git for-each-ref`."""
    out = _text(_git(repo, "for-each-ref", "--format=%(objectname) %(refname)",
                     *[f"refs/heads/{b}" for b in branches]))
    got = {}
    for line in out.splitlines():
        sha, _, ref = line.partition(" ")
        name = ref[len("refs/heads/"):]
        if name in branches:
            got[name] = sha
    return got


def _blobs(repo, sha, rels):
    """{rel: text} of `rels` at `sha` - one `git cat-file --batch`."""
    if not rels:
        return {}
    data = _git(repo, "cat-file", "--batch",
                input="".join(f"{sha}:{r}\n" for r in rels).encode("utf-8"))
    out, i = {}, 0
    for rel in rels:
        nl = data.index(b"\n", i)
        head = data[i:nl].split()
        i = nl + 1
        if len(head) < 3 or head[1] != b"blob":
            continue
        size = int(head[2])
        out[rel] = _text(data[i:i + size])
        i += size + 1
    return out


# ------------------------------------------------------------------------ parse
def _value(raw):
    v = raw.strip()
    if len(v) >= 2 and v[0] == v[-1] == '"':
        try:
            v = json.loads(v)
        except ValueError:
            v = v[1:-1]
    elif len(v) >= 2 and v[0] == v[-1] == "'":
        v = v[1:-1].replace("''", "'")
    v = str(v).strip()
    return None if v.casefold() in EMPTY else v


def parse_task(text):
    """(frontmatter dict, body) of a task file; None when it has none."""
    if not text.startswith("---"):
        return None
    lines = text.split("\n")
    if lines[0].strip() != "---":
        return None
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return None
    fm = {}
    for line in lines[1:end]:
        m = re.match(r"^([A-Za-z_][\w-]*):(.*)$", line)
        if m:
            fm[m.group(1)] = _value(m.group(2))
    return fm, "\n".join(lines[end + 1:]).lstrip("\n")


def checklist(body):
    """[{text, done}] of the `- [ ]` / `- [x]` lines (not inside a code fence)."""
    items, fenced = [], False
    for line in (body or "").split("\n"):
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        m = CHECK.match(line)
        if m:
            items.append({"text": m.group(2), "done": m.group(1) != " "})
    return items


def _task(project, branch, rel, text):
    m = FILE.match(rel)
    if not m or m.group(3) != PREFIX[project]:
        return None
    got = parse_task(text)
    if got is None:
        return None
    fm, body = got
    tid = fm.get("id") if fm.get("id") and ID.match(fm["id"]) else m.group(2)
    row = {k: fm.get(k) for k in FIELDS}
    row["id"] = tid
    raw_blocked = fm.get("blocked_by")
    row["blocked_by"] = ANY_ID.findall(raw_blocked or "")
    row["extra"] = {k: v for k, v in fm.items() if k not in FIELDS and k != "blocked_by"}
    items = checklist(body)
    row.update(project=project, archived=m.group(1) is not None, archive=m.group(1),
               path=rel, branch=branch,
               checklist={"done": sum(1 for i in items if i["done"]), "total": len(items)})
    return {"row": row, "body": body, "items": items, "raw": text}


def _tree(project, repo, branch, sha):
    """The parsed tree of `branch` at `sha`, kept per sha."""
    key = (str(repo), branch)
    with _LOCK:
        got = _TREES.get(key)
        if got is not None and got[0] == sha:
            return got[1]
    names = _text(_git(repo, "ls-tree", "-r", "-z", "--name-only", sha, "--", "tasks",
                       "ROADMAP.md")).split("\0")
    rels = sorted(n for n in names if FILE.match(n))
    want = rels + (["ROADMAP.md"] if "ROADMAP.md" in names else [])
    blobs = _blobs(repo, sha, want)
    tasks = {}
    for rel in rels:            # the root's own before the archive's (sorted: "tasks/C" < "tasks/a")
        t = _task(project, branch, rel, blobs.get(rel, ""))
        if t is None:
            continue
        have = tasks.get(t["row"]["id"])
        if have is None or (have["row"]["archived"] and not t["row"]["archived"]):
            tasks[t["row"]["id"]] = t
    tree = {"tasks": tasks, "roadmap": blobs.get("ROADMAP.md")}
    with _LOCK:
        _TREES[key] = (sha, tree)
    return tree


# ------------------------------------------------------------------------ the sources
def center_repo(root):
    """`<root>/<the lock's module frontend path>` (`frontend` when the lock
    says nothing)."""
    rel = CENTER_MODULE
    try:
        lock = factory.agents_lock().load(root, required=False) or {}
        ent = (lock.get("modules") or {}).get(CENTER_MODULE) or {}
        if isinstance(ent.get("path"), str) and ent["path"].strip():
            rel = ent["path"].strip()
    except Exception:                                   # noqa: BLE001 - the default path
        pass
    return Path(root) / rel


def version_lines(root, now=None):
    """`agents_lock.versions_in_work(root)`, asked again after LINES_TTL_S."""
    key = str(Path(root).absolute())
    t = time.monotonic() if now is None else now
    with _LOCK:
        got = _LINES.get(key)
        if got is not None and t - got[0] < LINES_TTL_S:
            return got[1]
    try:
        with factory.git_reads():
            lines = list(factory.agents_lock().versions_in_work(root))
    except Exception:                                   # noqa: BLE001 - main only then
        lines = []
    with _LOCK:
        _LINES[key] = (t, lines)
    return lines


def sources(root):
    """[{project, repo, branch, sha, error}] in reading order (main first, the
    version lines after: a later one wins)."""
    root = Path(root)
    out = []
    plan = (("factory", root, [MAIN] + version_lines(root)),
            ("center", center_repo(root), [MAIN]))
    for project, repo, branches in plan:
        try:
            if not repo.is_dir():
                raise GitFailed(f"{repo}: no such directory")
            refs = _refs(repo, branches)
            err = None
        except (GitFailed, OSError) as e:
            refs, err = {}, str(e)
        for b in branches:
            out.append({"project": project, "repo": repo, "branch": b, "sha": refs.get(b),
                        "error": err if err else (None if b in refs else f"no branch {b}")})
    return out


def _index(root):
    srcs = sources(root)
    key = (str(Path(root).absolute()),) + tuple((s["project"], str(s["repo"]), s["branch"],
                                                 s["sha"]) for s in srcs)
    with _LOCK:
        got = _INDEX.get(key)
    if got is not None:
        return got
    tasks, roadmaps = {}, {}
    for s in srcs:
        if not s["sha"]:
            continue
        try:
            tree = _tree(s["project"], s["repo"], s["branch"], s["sha"])
        except (GitFailed, OSError, ValueError) as e:
            s["error"] = str(e)
            continue
        for tid, t in tree["tasks"].items():
            have = tasks.get(tid)
            # a later source (a version line) wins - unless its file is main's, byte for byte
            if have is None or (have["raw"], have["row"]["path"]) != (t["raw"], t["row"]["path"]):
                tasks[tid] = t
        if tree["roadmap"] is not None:
            roadmaps[s["project"]] = (s, tree["roadmap"])
    for t in tasks.values():
        t["hay"] = "\n".join([t["row"]["id"], t["row"]["title"] or "", t["body"]]).casefold()
    order = sorted(tasks, key=lambda i: (PROJECTS.index(tasks[i]["row"]["project"]), i))
    idx = {"sources": srcs, "tasks": tasks, "order": order, "roadmaps": roadmaps}
    with _LOCK:
        _INDEX.clear()                           # one root's answer at a time is enough
        _INDEX[key] = idx
    return idx


def forget():
    """Drop everything kept (tests)."""
    with _LOCK:
        _TREES.clear()
        _INDEX.clear()
        _LINES.clear()
        _COMMITS.clear()


# ------------------------------------------------------------------------ cleaning
def _texter(root):
    pre = paths.prefixes(root)
    home = str(Path.home()).rstrip("/")

    def clean(s):
        if s is None:
            return None
        s = paths.scrub(s, pre, outside=False)
        if len(home) > 1:
            s = s.replace(home + "/", "~/")
        return SYS_ABS.sub(lambda m: ".../" + m.group(1), s)
    return clean


def _src_out(root, s):
    return paths.clean({"project": s["project"], "repo": paths.rel(root, s["repo"]),
                        "branch": s["branch"], "sha": s["sha"], "error": s["error"]}, root)


def _row_out(row, clean):
    out = dict(row)
    for k in ("title", "dod"):
        out[k] = clean(out[k])
    out["extra"] = {k: clean(v) for k, v in row["extra"].items()}
    return out


# ------------------------------------------------------------------------ the answers
def _split(v):
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def tasks(root, project=None, milestone=None, status=None, type=None, repo=None, q=None):
    """{tasks: [row], total, count, sources} - the rows that pass every filter
    (each a comma-separated list, exact values; `q`: every word in the id,
    the title or the body, case-insensitive)."""
    if project and project not in PROJECTS:
        raise BatchFault(422, "bad_project", f"Нет такого проекта «{project}»: только "
                         f"factory или center.", [f"project={project!r}"])
    idx = _index(root)
    want = {"project": _split(project), "milestone": _split(milestone),
            "status": _split(status), "type": _split(type), "repo": _split(repo)}
    terms = (q or "").casefold().split()
    clean = _texter(root)
    rows = []
    for tid in idx["order"]:
        t = idx["tasks"][tid]
        r = t["row"]
        if any(vals and r.get(k) not in vals for k, vals in want.items()):
            continue
        if terms and not all(w in t["hay"] for w in terms):
            continue
        rows.append(_row_out(r, clean))
    return {"tasks": rows, "count": len(rows), "total": len(idx["order"]),
            "sources": [_src_out(root, s) for s in idx["sources"]]}


def _commits(root, idx, tid):
    by_repo = {}
    for s in idx["sources"]:
        if s["sha"]:
            by_repo.setdefault((s["project"], str(s["repo"])), []).append(s)
    key = (tid,) + tuple((k, tuple(x["sha"] for x in v)) for k, v in sorted(by_repo.items()))
    with _LOCK:
        got = _COMMITS.get(key)
    if got is not None:
        return got
    pat = re.compile(r"(?<![A-Za-z0-9])" + re.escape(tid) + r"(?!\d)")
    seen, out = set(), []
    for (project, repo), srcs in by_repo.items():
        try:
            raw = _text(_git(repo, "log", "-F", f"--grep={tid}", f"-n{COMMITS_SCAN}",
                             "--format=%H%x1f%cI%x1f%s%x1e", *[x["sha"] for x in srcs]))
        except (GitFailed, OSError):
            continue
        for rec in raw.split("\x1e"):
            parts = rec.strip("\n").split("\x1f")
            if len(parts) != 3 or parts[0] in seen or not pat.search(parts[2]):
                continue
            seen.add(parts[0])
            out.append({"sha": parts[0], "date": parts[1], "subject": parts[2],
                        "project": project})
    out.sort(key=lambda c: c["date"], reverse=True)
    out = out[:COMMITS_LIMIT]
    with _LOCK:
        _COMMITS[key] = out
    return out


def task(root, tid):
    """One task: its row, body, checklist items, the related tasks named in its
    text (known ones only), the commits whose subject names it."""
    tid = (tid or "").strip().upper()
    idx = _index(root)
    t = idx["tasks"].get(tid)
    if t is None:
        raise BatchFault(404, "unknown_task", f"Задачи «{tid}» нет ни у фабрики, ни у центра.",
                         [f"id={tid!r}"] + [f"{s['project']} {s['branch']}: {s['error']}"
                                            for s in idx["sources"] if s["error"]])
    r = t["row"]
    text = "\n".join([r["title"] or "", r["dod"] or "", " ".join(r["blocked_by"]), t["body"]])
    related = []
    for rid in dict.fromkeys(ANY_ID.findall(text)):
        o = idx["tasks"].get(rid)
        if rid != tid and o is not None:
            related.append({"id": rid, "project": o["row"]["project"],
                            "title": o["row"]["title"], "status": o["row"]["status"]})
    clean = _texter(root)
    out = _row_out(r, clean)
    out.update(body=clean(t["body"]),
               items=[{"text": clean(i["text"]), "done": i["done"]} for i in t["items"]],
               related=[dict(x, title=clean(x["title"])) for x in related],
               commits=[dict(c, subject=clean(c["subject"])) for c in _commits(root, idx, tid)])
    return out


def _heading(text):
    """(version|None, title, done|None) of a `## ` / `### ` heading's text."""
    words = text.split(" — ", 1)
    version = words[0].strip() if VERSION.match(words[0].strip()) else None
    rest = words[1] if version and len(words) > 1 else (text if not version else "")
    title = rest.split(" — **", 1)[0].split("**DONE", 1)[0].strip().rstrip("—").strip()
    m = DONE.search(text)
    return version, title, m.group(1) if m else None


def parse_roadmap(text):
    """The milestones (`## `) in order, each with its tasks outside a sprint and
    its sprints (`### `) with theirs - the id in the first cell of a table row
    or at the start of a top-level list item, in the file's order. A `## ` without a version counts only when it has tasks."""
    out, ms, sp, fenced = [], None, None, False
    for line in (text or "").split("\n"):
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        if line.startswith("## "):
            v, title, done = _heading(line[3:].strip())
            ms = {"version": v, "title": title, "heading": line[3:].strip(), "done": done,
                  "tasks": [], "sprints": []}
            sp = None
            out.append(ms)
        elif line.startswith("### ") and ms is not None:
            v, title, done = _heading(line[4:].strip())
            sp = {"version": v, "title": title, "heading": line[4:].strip(), "done": done,
                  "tasks": []}
            ms["sprints"].append(sp)
        elif ms is not None and (line.startswith("|") or ITEM.match(line)):
            if line.startswith("|"):
                cells = line.strip().strip("|").split("|")
                m = ANY_ID.search(cells[0]) if cells else None
            else:
                m = ITEM.match(line)
            if m:
                into = (sp or ms)["tasks"]
                if m.group(1) not in into:
                    into.append(m.group(1))
    return [m for m in out
            if m["version"] or m["tasks"] or any(s["tasks"] for s in m["sprints"])]


def roadmap(root, project=None):
    """{roadmaps: [{project, branch, sha, error, milestones}]}."""
    if project and project not in PROJECTS:
        raise BatchFault(422, "bad_project", f"Нет такого проекта «{project}»: только "
                         f"factory или center.", [f"project={project!r}"])
    idx = _index(root)
    clean = _texter(root)
    out = []
    for p in PROJECTS:
        if project and p != project:
            continue
        got = idx["roadmaps"].get(p)
        if got is None:
            errs = [s["error"] for s in idx["sources"] if s["project"] == p and s["error"]]
            out.append(paths.clean({"project": p, "branch": None, "sha": None,
                                    "error": "; ".join(errs) or "нет ROADMAP.md",
                                    "milestones": []}, root))
            continue
        s, text = got
        ms = parse_roadmap(text)
        for m in ms:
            for x in [m] + m["sprints"]:
                x["title"], x["heading"] = clean(x["title"]), clean(x["heading"])
        out.append({"project": p, "branch": s["branch"], "sha": s["sha"], "error": None,
                    "milestones": ms})
    return {"roadmaps": out}
