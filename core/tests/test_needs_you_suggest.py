#!/usr/bin/env python3
"""CF-0703: the suggested answer of a question and its acceptance
(shared/needs_you.py).

The user, 12.10: «ты обычно предлагаешь мне свое решение по вопросам. давай
так и будет в центре. в поле ответа плейсхолдером будет написано твое решение
и удобный способ сразу применить его».

Everything in a temp directory; the bus is a stand-in - nothing leaves the
machine, nothing of the live journal is read.

Pinned:
* `add(..., suggestion, why)` writes a `suggest` op right after the `add`;
  `suggest()` adds / replaces it on an open or answered question and refuses
  a resolved or unknown one; `questions()` hands out suggestion,
  suggestion_why, suggested_by, suggested_at;
* `answer(..., via, accepted_suggestion)` writes `via` / `accepted_suggestion`
  only when given / true; an accepted answer without a text is the suggestion,
  accepting where there is none is refused; `questions()` hands out
  answered_via, accepted_suggestion;
* without the new parameters the rows are byte for byte the old ones, and a
  journal written before CF-0703 reads (the new fields None / False);
* `by` / `via` are checked (<= 40 characters, one line) before a write;
* the Telegram message of a new question carries the suggestion, short;
* the CLI: `add --suggest --why`, `suggest`, `answer --via --accept`.
"""
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "shared"))

import needs_you as ny              # noqa: E402

from _tmproot import tmp_root       # noqa: E402

TMP = tmp_root("needs-you-suggest-test-")
_n = [0]
AT = "2026-10-12T10:00:00Z"


def fresh():
    _n[0] += 1
    d = TMP / f"j{_n[0]}"
    d.mkdir()
    return d


def rows(d):
    return [json.loads(ln) for ln in (d / ny.JOURNAL).read_text(encoding="utf-8").splitlines()]


def refused(fn):
    try:
        fn()
    except ny.QuestionError:
        return True
    return False


def test_add_with_a_suggestion_writes_a_suggest_op_after_the_add():
    d = fresh()
    q, created = ny.add("publisher-auth", "oauth-token:t1", "токен истекает", directory=d,
                        notify=False, now=AT, suggestion="переподключить сегодня",
                        why="через 2 дня истечёт")
    assert created and q["suggestion"] == "переподключить сегодня"
    assert q["suggestion_why"] == "через 2 дня истечёт"
    assert q["suggested_by"] == "publisher-auth" and q["suggested_at"] == AT
    got = rows(d)
    assert [r["op"] for r in got] == ["add", "suggest"], got
    assert got[1] == {"op": "suggest", "id": "Q1", "suggestion": "переподключить сегодня",
                      "why": "через 2 дня истечёт", "by": "publisher-auth", "at": AT,
                      "task": "CF-0652"}, got[1]
    # the same suggestion again is no new row; a new one is
    ny.add("publisher-auth", "oauth-token:t1", "токен истекает", directory=d, notify=False,
           suggestion="переподключить сегодня", why="через 2 дня истечёт")
    assert len(rows(d)) == 2
    q2, created2 = ny.add("publisher-auth", "oauth-token:t1", "токен истекает", directory=d,
                          notify=False, suggestion="переподключить завтра", by="claude")
    assert not created2 and q2["suggestion"] == "переподключить завтра"
    assert q2["suggested_by"] == "claude" and q2["suggestion_why"] is None
    assert ny.get("Q1", directory=d)["suggestion"] == "переподключить завтра"
    assert refused(lambda: ny.add("s", "k2", "t", directory=d, notify=False, why="без решения"))


def test_suggest_adds_or_replaces_on_a_live_question_and_refuses_a_resolved_one():
    d = fresh()
    ny.add("monitor", "alert:example-film:E1", "нарушение", directory=d, notify=False, now=AT)
    q = ny.get("Q1", directory=d)
    for k in ("suggestion", "suggestion_why", "suggested_by", "suggested_at"):
        assert q[k] is None, k
    s = ny.suggest("q1", "оспорить", why="фрагмент 3 с", directory=d,
                   now="2026-10-12T11:00:00Z")
    assert s["suggestion"] == "оспорить" and s["suggested_by"] == "claude"
    s = ny.suggest("Q1", "снять ролик", by="auto-dev", directory=d,
                   now="2026-10-12T12:00:00Z")
    got = ny.get("Q1", directory=d)
    assert (got["suggestion"], got["suggestion_why"], got["suggested_by"], got["suggested_at"]) \
        == ("снять ролик", None, "auto-dev", "2026-10-12T12:00:00Z"), got
    assert got["status"] == "open" and got["updated"] == "2026-10-12T12:00:00Z"
    ny.answer("Q1", "оспорить", directory=d)
    ny.suggest("Q1", "оспорить и ждать", directory=d)      # an answered one still takes it
    assert ny.get("Q1", directory=d)["suggestion"] == "оспорить и ждать"
    ny.resolve("Q1", directory=d)
    n = len(rows(d))
    assert refused(lambda: ny.suggest("Q1", "x", directory=d)), "a resolved question"
    assert refused(lambda: ny.suggest("Q9", "x", directory=d)), "an unknown question"
    assert refused(lambda: ny.suggest("Q1", "  ", directory=d)), "an empty suggestion"
    assert len(rows(d)) == n, "a refusal writes nothing"


def test_accepting_the_suggestion_and_the_via():
    d = fresh()
    ny.add("s", "k1", "вопрос", directory=d, notify=False, suggestion="да, сделать")
    a = ny.answer("Q1", None, via="center", accepted_suggestion=True, directory=d, now=AT)
    assert a["answer"] == "да, сделать" and a["accepted_suggestion"] is True
    assert a["answered_via"] == "center" and a["answered_by"] == "user"
    last = rows(d)[-1]
    assert last == {"op": "answer", "id": "Q1", "answer": "да, сделать", "by": "user", "at": AT,
                    "via": "center", "accepted_suggestion": True, "task": "CF-0652"}, last
    got = ny.get("Q1", directory=d)
    assert got["accepted_suggestion"] is True and got["answered_via"] == "center"
    # a later own answer replaces it: not accepted any more
    ny.answer("Q1", "нет, иначе", via="telegram", directory=d)
    got = ny.get("Q1", directory=d)
    assert got["accepted_suggestion"] is False and got["answered_via"] == "telegram"
    assert got["answer"] == "нет, иначе"
    # accepting where nothing was suggested is refused, nothing written
    ny.add("s", "k2", "другой", directory=d, notify=False)
    n = len(rows(d))
    assert refused(lambda: ny.answer("Q2", None, accepted_suggestion=True, directory=d))
    assert refused(lambda: ny.answer("Q2", None, directory=d))
    assert len(rows(d)) == n


def test_without_the_new_parameters_the_rows_are_byte_for_byte_the_old_ones():
    d = fresh()
    ny.add("archive", "archive:debt", "подключите Archive", channel="example-film", link="http://x",
           directory=d, notify=False, now=AT)
    ny.answer("Q1", "подключу", directory=d, now="2026-10-12T11:00:00Z")
    want = [
        {"op": "add", "id": "Q1", "key": "archive:debt", "source": "archive",
         "channel": "example-film", "text": "подключите Archive", "link": "http://x",
         "by": "archive", "at": AT, "task": "CF-0652"},
        {"op": "answer", "id": "Q1", "answer": "подключу", "by": "user",
         "at": "2026-10-12T11:00:00Z", "task": "CF-0652"},
    ]
    text = (d / ny.JOURNAL).read_text(encoding="utf-8")
    assert text == "".join(json.dumps(w, ensure_ascii=False) + "\n" for w in want), text


def test_a_journal_written_before_reads_with_the_new_fields_empty():
    d = fresh()
    old = [
        {"op": "add", "id": "Q1", "key": "k", "source": "s", "channel": None, "text": "t",
         "link": None, "by": "s", "at": AT, "task": "CF-0652"},
        {"op": "answer", "id": "Q1", "answer": "a", "by": "user", "at": AT, "task": "CF-0652"},
        {"op": "add", "id": "Q2", "key": "k2", "source": "s", "channel": None, "text": "t2",
         "link": None, "by": "s", "at": AT, "task": "CF-0652"},
    ]
    (d / ny.JOURNAL).write_text("".join(json.dumps(o) + "\n" for o in old), encoding="utf-8")
    q1, q2 = ny.questions(directory=d)
    for q in (q1, q2):
        for k in ("suggestion", "suggestion_why", "suggested_by", "suggested_at", "answered_via"):
            assert q[k] is None, (q["id"], k)
        assert q["accepted_suggestion"] is False
    assert q1["status"] == "answered" and q1["answer"] == "a"


def test_by_and_via_are_checked_before_anything_is_written():
    d = fresh()
    ny.add("s", "k", "t", directory=d, notify=False, suggestion="x")
    n = len(rows(d))
    long_ = "x" * 41
    for bad in (lambda: ny.answer("Q1", "a", via=long_, directory=d),
                lambda: ny.answer("Q1", "a", via="two\nlines", directory=d),
                lambda: ny.answer("Q1", "a", by=long_, directory=d),
                lambda: ny.answer("Q1", "a", via="  ", directory=d),
                lambda: ny.answer("Q1", "a", via=7, directory=d),
                lambda: ny.answer("Q1", "a", accepted_suggestion="yes", directory=d),
                lambda: ny.suggest("Q1", "y", by=long_, directory=d),
                lambda: ny.suggest("Q1", "y", by="a\tb", directory=d),
                lambda: ny.add("s", "k3", "t", by=long_, directory=d, notify=False)):
        assert refused(bad)
    assert len(rows(d)) == n
    assert ny.answer("Q1", "a", via="x" * 40, by="  center  ", directory=d)["answered_by"] \
        == "center"
    assert ny.answer("Q1", "a", by="", directory=d)["answered_by"] == "user", \
        "an empty by is the user, as it always was (the API's AnswerIn)"
    assert ny.add("src", "k4", "t", by="", directory=d, notify=False)[0]["created_by"] == "src"


def test_the_telegram_message_of_a_new_question_carries_the_suggestion_short():
    d = fresh()
    sent = []
    ny.add("s", "k1", "вопрос", directory=d, notifier=sent.append,
           suggestion="решение " + "очень " * 100)
    ny.add("s", "k2", "вопрос без решения", directory=d, notifier=sent.append)
    one, two = (ny.push_text(q) for q in sent)
    assert one.startswith("Вопрос Q1: вопрос — предлагаю: решение очень")
    assert len(one.split(" — предлагаю: ", 1)[1]) <= ny.PUSH_SUGGESTION_MAX
    assert two == "Вопрос Q2: вопрос без решения"
    # through the real bus with a recording backend
    got = []
    env = {"NOTIFY_STATE_DIR": str(d / "notify-state"), "NOTIFY_BACKENDS": "rec"}
    ny.add("s", "k3", "через шину", directory=d, suggestion="принять",
           notifier=lambda q: ny._push(q, root=d, environ=env,
                                       backends={"rec": lambda ev, cfg: got.append(ev)}))
    assert len(got) == 1 and got[0]["text"] == "Вопрос Q3: через шину — предлагаю: принять", got


def _cli(argv):
    out = io.StringIO()
    return ny.main(argv, out=out), out.getvalue()


def test_cli_suggest_and_accept():
    d = str(fresh())
    code, out = _cli(["--dir", d, "add", "--source", "s", "--key", "k", "--text", "вопрос",
                      "--no-notify", "--suggest", "сделать так", "--why", "дешевле"])
    assert code == 0 and "предложение (s): сделать так" in out, out
    code, out = _cli(["--dir", d, "suggest", "Q1", "сделать иначе", "--by", "auto-dev"])
    assert code == 0 and "предложение (auto-dev): сделать иначе" in out, out
    code, out = _cli(["--dir", d, "list", "--json"])
    q = json.loads(out)[0]
    assert q["suggestion"] == "сделать иначе" and q["suggestion_why"] is None
    code, out = _cli(["--dir", d, "answer", "Q1", "--accept", "--via", "center"])
    assert code == 0 and "сделать иначе" in out and "принято предложение" in out, out
    q = json.loads(_cli(["--dir", d, "list", "--json"])[1])[0]
    assert q["accepted_suggestion"] is True and q["answered_via"] == "center"
    assert _cli(["--dir", d, "suggest", "Q9", "x"])[0] == 1, "no such question"
    assert _cli(["--dir", d, "answer", "Q1", "a", "--via", "x" * 41])[0] == 2, "a bad via"
    assert _cli(["--dir", d, "answer", "Q1"])[0] == 2, "no text, no --accept"
    _cli(["--dir", d, "resolve", "Q1"])
    assert _cli(["--dir", d, "suggest", "Q1", "x"])[0] == 1, "resolved"


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
