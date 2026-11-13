#!/usr/bin/env python3
"""CF-0491: this repository's README follows the factory's README template.

The template is one file at the root - `docs/readme-template.md`, read by path
through `_runlog.factory_root()` (CF-0159: no copy of it here). What is this
repository's own: its name, its pin and its blocks of the pipeline diagram.
The README holds

* the template's level-2 sections, in the template's order, and a Contents
  list whose every `#anchor` is one of them;
* the template's pipeline diagram unchanged, with one `class ... here` line
  naming this repository's own blocks;
* the pin line `agents.lock.json` -> `<agent>` @ `<rev>` of the root's lock,
  in the lead and in the Version section (CF-0834: `main` too when `rev` is a
  tag - a tag is cut from main);
* relative links only to files of this repository (between repositories the
  template asks for GitHub URLs).
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "scripts"))
import _runlog  # noqa: E402

AGENT = "trend-hunter"
BLOCKS = "TH"             # the `class <ids> here` line of the template's table
README = REPO / "README.md"
LOCK = _runlog.factory_root() / "agents.lock.json"
CLASS_LINE = re.compile(r"\s*class (\S+) here\s*$")
LINK = re.compile(r"\]\(([^)\s]+)\)")
TAG_LIKE = re.compile(r"v\d+(\.\d+)*")




def _readme():
    return README.read_text(encoding="utf-8")


def _h2(text):
    out, fence = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fence = not fence
        elif not fence and line.startswith("## "):
            out.append(line[3:].strip())
    return out


def _mermaid(text):
    return re.findall(r"```mermaid\n(.*?)```", text, re.S)




def _slug(title):
    s = re.sub(r"[^\w\- ]", "", title.lower())
    return s.replace(" ", "-")


def _outside_fences(text):
    fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fence = not fence
            continue
        if not fence:
            yield line






def test_title_names_the_line():
    first = _readme().splitlines()[0]
    assert re.match(r"# .+ — \d+\.\d+$", first), f"title {first!r}: '# <Name> — <version>' expected"




def _is_tag(rev, repo=REPO):
    """CF-0834: is the lock's `rev` a tag of this repository? Asked of git
    (`rev-parse -q --verify refs/tags/<rev>`); with no git or no `.git` here,
    a rev shaped like `v2.18` counts as a tag."""
    if (repo / ".git").exists():
        try:
            r = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "-q", "--verify", f"refs/tags/{rev}"],
                capture_output=True, timeout=30)
            return r.returncode == 0
        except (OSError, subprocess.SubprocessError):
            pass
    return bool(TAG_LIKE.fullmatch(rev))


def _pin_faults(text, rev, tag):
    """What is wrong with the README's pin against the lock's `rev`. CF-0834:
    a tag is cut from main and its README describes that line, so with a tag in
    the lock the README may pin `main` instead; with a branch or a sha it pins
    exactly `rev`."""
    ok = [rev, "main"] if tag and rev != "main" else [rev]
    lines = [f"`agents.lock.json` → `{AGENT}` @ `{r}`" for r in ok]
    lead = text.split("\n## ", 1)[0]
    version = text.split("\n## Version\n", 1)[-1]
    faults = []
    if not any(l in lead for l in lines):
        faults.append(f"the lead does not carry the pin line {' or '.join(lines)}")
    if not any(l in version for l in lines):
        faults.append(f"the Version section does not carry the pin line {' or '.join(lines)}")
    stale = set(re.findall(rf"`{re.escape(AGENT)}` @ `([^`]+)`", text)) - set(ok)
    if stale:
        faults.append(f"pins {sorted(stale)} in the README, the root's lock says {rev}"
                      + (" (a tag: `main` is also fine)" if len(ok) > 1 else ""))
    return faults


def test_pin_matches_the_root_lock():
    rev = json.loads(LOCK.read_text(encoding="utf-8"))["agents"][AGENT]["rev"]
    faults = _pin_faults(_readme(), rev, _is_tag(rev))
    assert not faults, "; ".join(faults)


def test_relative_links_resolve():
    broken = []
    for line in _outside_fences(_readme()):
        for target in LINK.findall(line):
            if re.match(r"[a-z]+:", target) or target.startswith("#"):
                continue
            if not (REPO / target.split("#", 1)[0]).exists():
                broken.append(target)
    assert not broken, "broken relative links: " + ", ".join(broken)


def test_no_relative_link_leaves_the_repository():
    out = [t for line in _outside_fences(_readme()) for t in LINK.findall(line)
           if t.startswith("../") or t.startswith("/")]
    assert not out, f"links out of this repository must be GitHub URLs: {out}"


def test_the_guard_bites():
    """Negative controls on the helpers the tests above lean on."""
    assert _h2("## A\n```\n## not\n```\n## B\n") == ["A", "B"]
    assert _slug("Place in the pipeline") == "place-in-the-pipeline"
    assert CLASS_LINE.match("    class CC1,CC2 here") and not CLASS_LINE.match("classDef here fill")
    assert list(_outside_fences("a\n```sh\n[x](nope)\n```\nb")) == ["a", "b"]


def _sample_readme(pin):
    line = f"pin: `agents.lock.json` → `{AGENT}` @ `{pin}`"
    return f"# X — 2.20\n\n{line}\n\n## Contents\n\n## Version\n\n{line}\n"


def test_the_pin_guard_bites():
    """CF-0834: the pin check against a lock that pins a tag, a sha, a branch."""
    sha = "e0bc7df0123456789abcdef0123456789abcdef0"
    assert _pin_faults(_sample_readme("main"), "v2.18", tag=True) == []
    assert _pin_faults(_sample_readme("v2.18"), "v2.18", tag=True) == []
    assert _pin_faults(_sample_readme("v2.17"), "v2.18", tag=True)
    assert _pin_faults(_sample_readme("main"), sha, tag=False)
    assert _pin_faults(_sample_readme("main"), "release/2.20", tag=False)
    assert _pin_faults(_sample_readme("main"), "main", tag=False) == []
    stale = _sample_readme("main") + f"\nold: `{AGENT}` @ `v2.17`\n"
    assert _pin_faults(stale, "v2.18", tag=True), "a stale pin beside `main` passed"
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        assert _is_tag("v2.18", d) and _is_tag("v2", d)
        assert not _is_tag(sha, d) and not _is_tag("main", d) and not _is_tag("v2.18-rc", d)
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        for cmd in (["init", "-q"], ["commit", "-q", "--allow-empty", "-m", "x"],
                    ["tag", "cut-from-main"]):
            subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
                            "-c", "tag.gpgsign=false", "-C", str(d), *cmd], check=True, env=env,
                           capture_output=True, timeout=30)
        assert _is_tag("cut-from-main", d), "git knows the tag, _is_tag does not"
        assert not _is_tag("v2.18", d), "with git here the shape of a rev decides nothing"


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
