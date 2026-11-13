#!/usr/bin/env python3
"""CF-0652: the journal of questions (shared/needs_you.py).

Everything in a temp directory; the bus is a stand-in (a recorder, or the real
bus with a recording backend and its state in the temp dir) - nothing leaves
the machine, nothing of the live journal is read.

Pinned:
* one question per event key: a second `add` of a live key returns it (a new
  wording is a `text` op, not a second question), a resolved key asks again
  under a new number;
* open -> answered -> resolved, a resolved question takes no answer;
  `resolve --key-prefix` with `keep` (the token's next term);
* a new question goes to the bus once, `notify=False` sends nothing, a bus
  that raises leaves the question;
* concurrent writers (separate processes) on one key make one question and
  every line of the journal is whole JSON;
* the CLI: add / list / answer / resolve and its exit codes;
* the journal is gitignored and lives in <root>/needs-you by default.
"""
import io
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "shared"))

import needs_you as ny              # noqa: E402

from _tmproot import tmp_root       # noqa: E402

TMP = tmp_root("needs-you-test-")
_n = [0]


def fresh():
    _n[0] += 1
    d = TMP / f"j{_n[0]}"
    d.mkdir()
    return d


def test_one_question_per_key_and_a_new_wording_is_not_a_second():
    d, sent = fresh(), []
    q, created = ny.add("archive", "archive:publish-debt", "подключите Archive", directory=d,
                        notifier=sent.append, now="2026-10-10T10:00:00Z")
    assert created and q["id"] == "Q1" and q["status"] == "open" and q["n"] == 1
    q2, created2 = ny.add("archive", "archive:publish-debt", "подключите Archive", directory=d,
                          notifier=sent.append)
    assert not created2 and q2["id"] == "Q1"
    q3, created3 = ny.add("archive", "archive:publish-debt", "подключите Archive: 2 месяца",
                          directory=d, notifier=sent.append, now="2026-10-11T10:00:00Z")
    assert not created3 and q3["id"] == "Q1" and q3["text"].endswith("2 месяца")
    assert [q["text"] for q in ny.questions(directory=d)] == ["подключите Archive: 2 месяца"]
    assert len(sent) == 1, "a question goes to the bus once"
    ops = [json.loads(ln)["op"] for ln in (d / ny.JOURNAL).read_text().splitlines()]
    assert ops == ["add", "text"], ops


def test_a_resolved_key_asks_again_under_a_new_number():
    d, sent = fresh(), []
    ny.add("archive", "k", "t", directory=d, notifier=sent.append)
    assert [q["id"] for q in ny.resolve(key="k", by="archive", directory=d)] == ["Q1"]
    q, created = ny.add("archive", "k", "t", directory=d, notifier=sent.append)
    assert created and q["id"] == "Q2" and len(sent) == 2
    assert [q["status"] for q in ny.questions(status="all", directory=d)] == ["resolved", "open"]


def test_open_answered_resolved_and_the_fields():
    d = fresh()
    q, _ = ny.add("monitor", "alert:example-film:E1", "нарушение", channel="example-film",
                  link="http://127.0.0.1:8790/#ch-example-film-rights", directory=d,
                  notify=False, now="2026-10-10T10:00:00Z")
    a = ny.answer(q["id"].lower(), "снять ролик", by="user", directory=d,
                  now="2026-10-10T11:00:00Z")
    assert a["status"] == "answered" and a["answered_by"] == "user"
    got = ny.get("Q1", directory=d)
    for k in ("id", "n", "key", "source", "channel", "text", "link", "created", "status",
              "answer", "answered_by", "answered_at", "resolved_by", "resolved_at", "note"):
        assert k in got, k
    assert got["answer"] == "снять ролик" and got["answered_at"] == "2026-10-10T11:00:00Z"
    assert [x["id"] for x in ny.live(directory=d)] == ["Q1"], "answered is still live"
    r = ny.resolve("Q1", by="claude", note="снят", directory=d, now="2026-10-10T12:00:00Z")
    assert r[0]["status"] == "resolved"
    got = ny.get("Q1", directory=d)
    assert got["status"] == "resolved" and got["resolved_by"] == "claude" and got["note"] == "снят"
    assert got["answer"] == "снять ролик", "the answer is kept"
    assert ny.live(directory=d) == []
    for bad in (lambda: ny.answer("Q1", "x", directory=d), lambda: ny.resolve("Q1", directory=d),
                lambda: ny.resolve("Q9", directory=d), lambda: ny.answer("Q9", "x", directory=d)):
        try:
            bad()
        except ny.QuestionError:
            continue
        raise AssertionError("a resolved / unknown question took a step")


def test_resolve_by_prefix_spares_the_kept_key():
    d = fresh()
    for k in ("oauth-token:a", "oauth-token:b", "other:a"):
        ny.add("publisher-auth", k, k, directory=d, notify=False)
    done = ny.resolve(key_prefix="oauth-token:", keep="oauth-token:b", directory=d)
    assert [q["key"] for q in done] == ["oauth-token:a"]
    assert [q["key"] for q in ny.live(directory=d)] == ["oauth-token:b", "other:a"]
    assert ny.resolve(key="nothing", directory=d) == []


def test_the_bus_gets_one_needs_human_per_question_and_a_failing_bus_is_not_fatal():
    d = fresh()
    state = d / "notify-state"
    got = []

    def rec(ev, cfg):
        got.append(ev)
    env = {"NOTIFY_STATE_DIR": str(state), "NOTIFY_BACKENDS": "rec"}
    q, _ = ny.add("archive", "k1", "вопрос", directory=d,
                  notifier=lambda q: ny._push(q, root=d, environ=env, backends={"rec": rec}))
    ny.add("archive", "k1", "вопрос", directory=d,
           notifier=lambda q: ny._push(q, root=d, environ=env, backends={"rec": rec}))
    assert len(got) == 1 and got[0]["kind"] == "needs_human" and got[0]["key"] == "needs-you:Q1"
    assert got[0]["text"].startswith("Вопрос Q1: ") and got[0]["link"].endswith(":8790/questions")

    def boom(q):
        raise RuntimeError("bus down")
    q2, created = ny.add("archive", "k2", "ещё", directory=d, notifier=boom)
    assert created and ny.get(q2["id"], directory=d)["status"] == "open"


_WRITER = """
import sys
sys.path.insert(0, {shared!r})
import needs_you as ny
for i in range(20):
    ny.add("w", "same-key", "t", directory={d!r}, notify=False)
    ny.add("w", "own-" + sys.argv[1] + "-" + str(i), "t", directory={d!r}, notify=False)
"""


def test_concurrent_writers_make_one_question_per_key_and_whole_lines():
    d = fresh()
    code = _WRITER.format(shared=str(ROOT / "shared"), d=str(d))
    procs = [subprocess.Popen([sys.executable, "-c", code, str(i)]) for i in range(4)]
    assert all(p.wait(timeout=60) == 0 for p in procs)
    lines = (d / ny.JOURNAL).read_text().splitlines()
    docs = [json.loads(ln) for ln in lines]               # every line whole
    qs = ny.questions(directory=d)
    assert sum(1 for q in qs if q["key"] == "same-key") == 1
    assert len(qs) == 1 + 4 * 20 and len(docs) == len(qs)
    assert sorted(q["n"] for q in qs) == list(range(1, len(qs) + 1)), "numbers unique"


def _cli(argv):
    out = io.StringIO()
    return ny.main(argv, out=out), out.getvalue()


def test_cli_add_list_answer_resolve():
    d = str(fresh())
    code, out = _cli(["--dir", d, "add", "--source", "s", "--key", "k", "--text", "вопрос",
                      "--channel", "example-film", "--no-notify"])
    assert code == 0 and out.startswith("new Q1 open"), out
    code, out = _cli(["--dir", d, "add", "--source", "s", "--key", "k", "--text", "вопрос",
                      "--no-notify"])
    assert code == 0 and out.startswith("already asked Q1"), out
    code, out = _cli(["--dir", d, "list"])
    assert code == 0 and "Q1 open" in out and "[example-film]" in out, out
    code, out = _cli(["--dir", d, "answer", "Q1", "да"])
    assert code == 0 and "answered" in out and "да" in out, out
    code, out = _cli(["--dir", d, "list", "--json"])
    assert json.loads(out)[0]["status"] == "answered"
    code, out = _cli(["--dir", d, "resolve", "Q1", "--note", "сделано"])
    assert code == 0 and "resolved" in out, out
    code, out = _cli(["--dir", d, "list"])
    assert "вопросов нет" in out, out
    code, out = _cli(["--dir", d, "list", "--status", "all"])
    assert "Q1 resolved" in out, out
    assert _cli(["--dir", d, "resolve", "Q1"])[0] == 1
    assert _cli(["--dir", d, "resolve", "--key", "nope"])[0] == 1
    assert _cli(["--dir", d, "resolve"])[0] == 2
    assert _cli(["--dir", d, "bogus"])[0] == 2


def test_a_question_of_a_former_channel_id_reads_back_under_the_current_one():
    """The journal is a dated record (CF-0197): a question asked before a
    rename carries the old id; it is resolved where the journal is read."""
    root = fresh()
    (root / "channels").mkdir()
    (root / "channels" / "example-film.json").write_text(json.dumps(
        {"channel_id": "example-film", "former_channel_ids": ["legacy-film"]}))
    ny.add("monitor", "alert:legacy-film:E1", "нарушение", channel="legacy-film",
           root=root, notify=False)
    raw = json.loads((root / "needs-you" / ny.JOURNAL).read_text().splitlines()[0])
    assert raw["channel"] == "legacy-film", "the record is not rewritten"
    assert [q["channel"] for q in ny.live(root=root)] == ["example-film"]
    assert [q["id"] for q in ny.questions(root=root, channel="legacy-film")] == ["Q1"]
    assert [q["id"] for q in ny.questions(root=root, channel="example-film")] == ["Q1"]


def test_the_journal_is_state_gitignored_in_the_root():
    assert "/needs-you/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ny.journal_dir(environ={}) == ROOT / "needs-you"
    assert ny.journal_dir(environ={"NEEDS_YOU_DIR": "/x/y"}) == Path("/x/y")
    assert ny.journal_dir(root="/r", environ={"NEEDS_YOU_DIR": "/x/y"}) == Path("/r/needs-you")
    assert ny.journal_dir(root="/r", directory="/d") == Path("/d")


if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e.__class__.__name__}: {str(e)[:300]}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
