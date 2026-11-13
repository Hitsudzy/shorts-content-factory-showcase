#!/usr/bin/env python3
"""CF-0247: расхождение с origin должно быть видно в тот же день, а не через двое суток.

Что здесь закреплено. Автопуш (CF-0036) при ошибке молчит - по замыслу, коммит
из-за сети ронять нельзя. Единственный сигнал был `/tmp/post-*-push-error.log`,
и он не сработал: `agents/video-editor` прожил с 40 незапушенными коммитами двое
суток. Поэтому сигнал перенесён в статусную строку - в место, куда человек и так
смотрит при каждом вводе. Контракт, который тут проверяется:

- пока всё сведено, статусная строка не меняется ни на символ (иначе пометку
  перестанут замечать ещё быстрее, чем лог);
- незапушенный коммит виден как `+N`, отставание - как `-N`;
- statusline никогда не ждёт git: она читает кэш, а пересчёт с `fetch` уходит в
  отвязанный процесс;
- сломанный repo_sync (нет кэша, битый JSON, исключение внутри) не имеет права
  испортить или уронить статусную строку - вывод делегата уходит как есть.

Работает на настоящих git-репозиториях в tmp (bare origin + клоны), сети не
трогает; секунды.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "runlog"))

from _tmproot import tmp_root   # noqa: E402  (CF-0339: stops the samplers, removes the tree)

TMP = tmp_root("repo-sync-test-")
os.environ["RUNLOG_STATE_DIR"] = str(TMP / "state")   # никогда не трогаем ~/.shorts-content-factory

import repo_sync  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
import install_git_hooks as hooks  # noqa: E402

MODULE = str(ROOT / "shared" / "runlog" / "repo_sync.py")
STATUSLINE = str(ROOT / "shared" / "runlog" / "statusline_hook.py")
_n = [0]


def git(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True,
                          timeout=30, check=True).stdout.strip()


def commit(path, text):
    (Path(path) / "f.txt").write_text(text)
    git(path, "add", "-A")
    git(path, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", text)


def fake_project(agents=("video-editor",), placeholders=()):
    """Корень-репозиторий и `agents/*`, у каждого свой bare origin."""
    _n[0] += 1
    root = TMP / f"p{_n[0]}"
    for name in (".", *[f"agents/{a}" for a in agents]):
        work = root / name if name != "." else root
        bare = TMP / f"p{_n[0]}-origin-{name.replace('/', '-')}.git"
        work.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True, timeout=30)
        git(work, "init", "-q", "-b", "main")
        commit(work, "first")
        git(work, "remote", "add", "origin", str(bare))
        git(work, "push", "-q", "-u", "origin", "main")
    for name in placeholders:
        (root / "agents" / name).mkdir(parents=True, exist_ok=True)
    return root


def scan(root, **kw):
    kw.setdefault("fetch", False)
    return repo_sync.scan(root=root, **kw)


def statusline(env_extra=None, delegate_body="print('Opus · 5h 12%')"):
    """Запуск настоящего statusline_hook с подставным делегатом."""
    _n[0] += 1
    dele = TMP / f"delegate{_n[0]}.py"
    dele.write_text(delegate_body + "\n")
    env = dict(os.environ)
    env["RUNLOG_STATUSLINE_DELEGATE"] = str(dele)
    #  A stale cache makes the hook refresh in the background; without this it
    #  would scan the real checkout, whose state (an unpushed worker branch in a
    #  worktree, CF-0479) then leaks into the next test's segment.
    env["REPO_SYNC_ROOT"] = str(TMP / "no-project")
    #  CF-0503: and no factory either - the hook's limits half looks for the
    #  running batch (limits.active_batch: a live RUN_SAMPLER.pid under
    #  <factory>/pipeline/*/*/), which on the real checkout walks the live
    #  pipeline/ and may write a reading into a running batch. (The state dir
    #  is this file's TMP already, line 35.)
    env["FACTORY_ROOT"] = str(TMP / "no-factory")
    env.pop("RUNLOG_BATCH", None)
    env.update(env_extra or {})
    return subprocess.run([sys.executable, STATUSLINE], input=b"{}", capture_output=True,
                          timeout=60, env=env).stdout.decode()


# --------------------------------------------------------------------------

def test_everything_pushed_means_zero_and_no_segment():
    root = fake_project()
    data = scan(root)
    assert set(data["repos"]) == {root.name, "agents/video-editor"}, data["repos"]
    assert all(i["ahead"] == 0 and i["behind"] == 0 and not i["error"]
               for i in data["repos"].values()), data
    assert repo_sync.segment(spawn=False) == ""


def test_unpushed_commit_shows_up_as_plus_n():
    root = fake_project()
    commit(root / "agents" / "video-editor", "работа, которая никуда не уехала")
    commit(root / "agents" / "video-editor", "и ещё одна")
    data = scan(root)
    assert data["repos"]["agents/video-editor"]["ahead"] == 2, data
    assert data["repos"][root.name]["ahead"] == 0, data
    seg = repo_sync.segment(spawn=False)
    assert "video-editor +2" in seg, seg
    assert root.name not in seg, seg          # сведённые репозитории строку не занимают


def test_an_agent_detached_on_its_pin_is_measured_by_its_main():
    """CF-0479: in the working copy an agent sits on its lock pin (a tag) with a
    detached HEAD; that is no error, and unpushed work on its `main` still shows."""
    root = fake_project()
    ve = root / "agents" / "video-editor"
    git(ve, "tag", "v1.4")
    git(ve, "checkout", "-q", "--detach", "v1.4")
    data = scan(root)
    info = data["repos"]["agents/video-editor"]
    assert not info["error"] and info["ahead"] == 0, info
    assert repo_sync.segment(spawn=False) == ""
    git(ve, "checkout", "-q", "main")
    commit(ve, "работа версии на main агента")
    git(ve, "checkout", "-q", "--detach", "v1.4")
    info = scan(root)["repos"]["agents/video-editor"]
    assert info["ahead"] == 1 and not info["error"], info
    git(ve, "push", "-q", "origin", "main")       # leave the shared cache clean for the next test
    assert scan(root)["repos"]["agents/video-editor"]["ahead"] == 0


def test_commit_pushed_from_another_checkout_shows_up_as_minus_n():
    """Ровно то, что случилось 14 сентября: чужой чекаут запушил, локальный не знает."""
    root = fake_project()
    work = root / "agents" / "video-editor"
    other = TMP / f"other{_n[0]}"
    subprocess.run(["git", "clone", "-q", git(work, "remote", "get-url", "origin"), str(other)],
                   check=True, timeout=60)
    commit(other, "отметка из чужого чекаута")
    git(other, "push", "-q", "origin", "main")
    assert scan(root)["repos"]["agents/video-editor"]["behind"] == 0, "без fetch знать неоткуда"
    data = scan(root, fetch=True)             # fetch по локальному bare - сети не требует
    assert data["repos"]["agents/video-editor"]["behind"] == 1, data
    assert "video-editor -1" in repo_sync.segment(spawn=False)


def test_ahead_and_behind_at_once_is_the_reported_shape():
    root = fake_project()
    work = root / "agents" / "video-editor"
    other = TMP / f"other-both{_n[0]}"
    subprocess.run(["git", "clone", "-q", git(work, "remote", "get-url", "origin"), str(other)],
                   check=True, timeout=60)
    commit(other, "пустая отметка")
    git(other, "push", "-q", "origin", "main")
    commit(work, "локальная работа")
    data = scan(root, fetch=True)
    info = data["repos"]["agents/video-editor"]
    assert (info["ahead"], info["behind"]) == (1, 1), info
    assert "video-editor +1-1" in repo_sync.segment(spawn=False)


def test_directory_without_git_is_skipped_but_named():
    root = fake_project(placeholders=("analyst", "publisher"))
    data = scan(root)
    assert "agents/analyst" not in data["repos"]
    assert data["skipped"] == ["agents/analyst", "agents/publisher"], data["skipped"]
    assert repo_sync.segment(spawn=False) == ""      # заглушка не повод ставить предупреждение


def test_branch_without_upstream_is_an_error_not_a_silent_zero():
    root = fake_project()
    git(root / "agents" / "video-editor", "checkout", "-qb", "wip/CF-0999")
    info = scan(root)["repos"]["agents/video-editor"]
    assert info["error"] == "нет upstream", info
    assert "video-editor?" in repo_sync.segment(spawn=False)


def test_statusline_is_byte_identical_while_everything_is_pushed():
    scan(fake_project())
    assert statusline() == "Opus · 5h 12%\n"


def test_statusline_carries_the_warning_on_the_delegate_line():
    root = fake_project()
    commit(root / "agents" / "video-editor", "незапушенное")
    scan(root)
    out = statusline()
    assert out.startswith("Opus · 5h 12%"), out
    assert "⚠ git: video-editor +1" in out, out
    assert out.count("\n") == 1, f"пометка не должна добавлять строку: {out!r}"


def test_statusline_appends_to_the_last_line_of_a_multiline_delegate():
    root = fake_project()
    commit(root / "agents" / "video-editor", "незапушенное")
    scan(root)
    out = statusline(delegate_body="print('line one')\nprint('line two')")
    assert out == "line one\nline two · ⚠ git: video-editor +1\n", out


def test_statusline_survives_a_broken_cache():
    repo_sync.cache_path().parent.mkdir(parents=True, exist_ok=True)
    repo_sync.cache_path().write_text("{не json")
    assert repo_sync.read_cache() is None
    assert statusline() == "Opus · 5h 12%\n"


def test_statusline_survives_repo_sync_blowing_up():
    """Внутренняя поломка проверки не имеет права стоить человеку статусной строки."""
    sys.path.insert(0, str(ROOT / "shared" / "runlog"))
    import statusline_hook

    def boom(*a, **kw):
        raise RuntimeError("git пропал")

    orig, repo_sync.segment = repo_sync.segment, boom
    try:
        assert statusline_hook.sync_segment() == ""
        assert statusline_hook.with_segment("Opus · 5h 12%\n", "") == "Opus · 5h 12%\n"
    finally:
        repo_sync.segment = orig


def test_statusline_ignores_a_project_root_that_is_not_there():
    assert statusline(env_extra={"REPO_SYNC_ROOT": str(TMP / "нет-такого")}) == "Opus · 5h 12%\n"


def test_statusline_does_not_wait_on_git():
    """Пересчёт уходит в сторону: сама строка обязана уложиться в кэш-чтение."""
    root = fake_project()
    scan(root)
    repo_sync.cache_path().write_text(json.dumps({"checked_at": 0, "repos": {}}))   # протухший
    #  CF-0609: отвязанный пересчёт наследует окружение этого процесса - без
    #  REPO_SYNC_ROOT он делал `git fetch` настоящего checkout (github.com).
    saved = os.environ.get(repo_sync.ROOT_ENV)
    os.environ[repo_sync.ROOT_ENV] = str(root)
    try:
        t = time.perf_counter()
        seg = repo_sync.segment()          # spawn=True: отвязанный пересчёт
        assert time.perf_counter() - t < 0.5, "segment() не должен ждать git"
    finally:
        if saved is None:
            os.environ.pop(repo_sync.ROOT_ENV, None)
        else:
            os.environ[repo_sync.ROOT_ENV] = saved
    assert seg == ""


# --- сам хук автопуша: провал обязан оставлять улику, а не затирать прошлую ----

def install_hooks(work):
    for hook in hooks.HOOKS:
        target = Path(work) / ".git" / "hooks" / hook
        target.write_text(hooks.body(hook))
        target.chmod(0o755)


def hook_env(root, tmpdir):
    return dict(os.environ, TMPDIR=str(tmpdir), REPO_SYNC_ROOT=str(root),
                GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")


def commit_via_hook(work, root, tmpdir, text):
    (Path(work) / "f.txt").write_text(text)
    subprocess.run(["git", "-C", str(work), "add", "-A"], check=True, timeout=30)
    return subprocess.run(["git", "-C", str(work), "commit", "-m", text],
                          capture_output=True, text=True, timeout=120, env=hook_env(root, tmpdir))


def test_failed_push_does_not_block_the_commit_and_leaves_a_record():
    root = fake_project()
    work = root / "agents" / "video-editor"
    install_hooks(work)
    logs = TMP / f"logs{_n[0]}"
    logs.mkdir()
    git(work, "remote", "set-url", "origin", str(TMP / "нет-такого-origin.git"))
    cp = commit_via_hook(work, root, logs, "работа при упавшем пуше")
    assert cp.returncode == 0, cp.stderr                      # коммит не роняем - в этом весь замысел
    assert git(work, "log", "-1", "--format=%s") == "работа при упавшем пуше"
    assert "статусной строке" in cp.stderr, cp.stderr
    log = logs / "push-failures-video-editor.log"
    assert log.is_file(), sorted(p.name for p in logs.iterdir())
    assert "main" in log.read_text()


def test_second_failure_appends_instead_of_erasing_the_first():
    """Прежний хук писал через `2>`: каждый пуш затирал предыдущую улику."""
    root = fake_project()
    work = root / "agents" / "video-editor"
    install_hooks(work)
    logs = TMP / f"logs-append{_n[0]}"
    logs.mkdir()
    git(work, "remote", "set-url", "origin", str(TMP / "нет-такого-origin.git"))
    commit_via_hook(work, root, logs, "первый провал")
    commit_via_hook(work, root, logs, "второй провал")
    log = (logs / "push-failures-video-editor.log").read_text()
    assert log.count("\tpost-commit\t") == 2, log


def test_successful_push_writes_no_log_at_all():
    """Непустой лог должен значить провал. Раньше git сыпал туда прогресс и при успехе."""
    root = fake_project()
    work = root / "agents" / "video-editor"
    install_hooks(work)
    logs = TMP / f"logs-ok{_n[0]}"
    logs.mkdir()
    cp = commit_via_hook(work, root, logs, "обычная работа")
    assert cp.returncode == 0, cp.stderr
    assert list(logs.iterdir()) == [], list(logs.iterdir())
    assert scan(root)["repos"]["agents/video-editor"]["ahead"] == 0


def test_worker_branches_are_still_left_alone():
    root = fake_project()
    work = root / "agents" / "video-editor"
    install_hooks(work)
    logs = TMP / f"logs-wip{_n[0]}"
    logs.mkdir()
    git(work, "checkout", "-qb", "wip/CF-0999")
    git(work, "remote", "set-url", "origin", str(TMP / "нет-такого-origin.git"))
    cp = commit_via_hook(work, root, logs, "ветка воркера")
    assert cp.returncode == 0 and cp.stderr.strip() == "", cp.stderr
    assert list(logs.iterdir()) == []


def test_installed_hooks_match_the_tracked_source():
    """Хуки больше не живут только в .git/hooks: расхождение - это провал теста."""
    cp = subprocess.run([sys.executable, str(ROOT / "scripts" / "install_git_hooks.py"), "--check"],
                        capture_output=True, text=True, timeout=120)
    assert cp.returncode == 0, cp.stdout + cp.stderr


def test_cli_exit_code_marks_divergence():
    root = fake_project()
    env = dict(os.environ, REPO_SYNC_ROOT=str(root))
    clean = subprocess.run([sys.executable, MODULE, "--no-fetch"], capture_output=True,
                           text=True, timeout=60, env=env)
    assert clean.returncode == 0, clean.stdout
    commit(root / "agents" / "video-editor", "незапушенное")
    dirty = subprocess.run([sys.executable, MODULE, "--no-fetch"], capture_output=True,
                           text=True, timeout=60, env=env)
    assert dirty.returncode == 1, dirty.stdout
    assert "agents/video-editor" in dirty.stdout and " 1 " in dirty.stdout, dirty.stdout


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
