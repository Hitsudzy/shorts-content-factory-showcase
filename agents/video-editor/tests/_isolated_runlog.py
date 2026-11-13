"""CF-0482: every test file of this repo keeps its run accounting out of real
batches by itself, not only when `run_tests.py` exports the isolation.

The instrumented scripts resolve their batch, when RUNLOG_BATCH is not set,
from any argv path shaped `pipeline/<channel>/<batch>` (runlog lookup rule 3),
and many tests here replay real batch paths. Under `run_tests.py` that is
harmless - the runner exports RUNLOG_BATCH to a temp dir (CF-0107) - but a
test file run on its own (the repo interpreter on `tests/test_x.py`, the way every
worker checks one file) had no such export and wrote straight into the real
batch: 2026-09-28..10-02, `test_degrade_blocks.py` (plan/qc/metadata on
rapid-reckless-neon-drift) and `test_rhythm_execution.py` (qc on
wren-hollow-lockhart) appended ~60 KB per run to
`pipeline/legacy-film/2026-08-31T2155Z/RUN_EVENTS.jsonl`, and a full suite
running at the same time failed its run-accounting guard on somebody else's
direct run.

Imported first by every `test_*.py` (a guard in `test_runlog_isolation.py`
keeps it that way). An environment that already names a batch is kept, as the
runner keeps it; otherwise a temp batch and a temp state dir are exported for
this process and every script it starts, and removed when it exits.
"""
import atexit
import os
import shutil
import tempfile

BATCH_ENV = "RUNLOG_BATCH"
STATE_DIR_ENV = "RUNLOG_STATE_DIR"

if not os.environ.get(BATCH_ENV) or not os.environ.get(STATE_DIR_ENV):
    _tmp = tempfile.mkdtemp(prefix="cf0482-runlog-")
    atexit.register(shutil.rmtree, _tmp, True)
    if not os.environ.get(BATCH_ENV):
        os.environ[BATCH_ENV] = os.path.join(_tmp, "batch")
        os.makedirs(os.environ[BATCH_ENV])
    if not os.environ.get(STATE_DIR_ENV):
        os.environ[STATE_DIR_ENV] = os.path.join(_tmp, "state")
        os.makedirs(os.environ[STATE_DIR_ENV])

# CF-0519: the pool's shots.json are looked up by id from `$FOOTAGE_DIR`, else
# the factory's live `shared/footage/` (still_share.footage_dirs, and through it
# build_render_plan.py). A test's synthetic ids (AAAAAAAAAAA, "starved", ...)
# were looked up in the live pool on every run; a test that wants a pool hands
# its own. An environment that already names one is kept.
if not os.environ.get("FOOTAGE_DIR"):
    _pool = tempfile.mkdtemp(prefix="cf0519-pool-")
    atexit.register(shutil.rmtree, _pool, True)
    os.environ["FOOTAGE_DIR"] = _pool

# CF-0523: the user's verdicts (`publish/acceptance-log.json`) are read by
# retired_shots inside every write_batch_metadata.py subprocess, from
# `$ACCEPTANCE_LOG`, else the factory's live log. A test that wants verdicts
# hands its own log; everyone else reads a path that does not exist - no
# verdicts. An environment that already names one is kept.
if not os.environ.get("ACCEPTANCE_LOG"):
    _publish = tempfile.mkdtemp(prefix="cf0523-publish-")
    atexit.register(shutil.rmtree, _publish, True)
    os.environ["ACCEPTANCE_LOG"] = os.path.join(_publish, "acceptance-log.json")
