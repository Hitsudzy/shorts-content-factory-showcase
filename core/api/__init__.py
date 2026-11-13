"""CC-0003: the API of the command center (`frontend/`, the CC-* tasks) - a
FastAPI application in the root of the factory.

    python3 -m api serve              # http://127.0.0.1:8790/ - the API under /api/, the
                                      # built center (frontend/dist) on the same address
    python3 -m api openapi [--check]  # write (or check) api/openapi.json, the contract
    python3 -m api launchd --print    # the launchd plist, printed - never installed

Everything it is told comes from the environment (`api/settings.py`); nothing
here knows a path of this machine. It acts only through the factory's own
functions (`api/factory.py`), with no logic of its own on top of them.

This file and `settings.py` / `__main__.py` are stdlib-only, so `python3 -m
api ...` works on any python3: without FastAPI it re-runs itself under the
root's `.venv` (`requirements.txt`).
"""

#: The version of the API's contract (`api/openapi.json` -> info.version).
API_VERSION = "0.79.0"  # CC-0184 (0.79.0, factory 2.52, CF-0922): the batch threshold apart from the feed's horizon - ScheduleSettings.batch_feed_days and PlanChannel.batch_feed_days (int, nullable: the factory's effective value - the channel's or the center's when set, otherwise its default 14 raised to min_feed_days; null only with `error` or from a factory without the key), ScheduleSettingsEdit.batch_feed_days (PUT: whole days 1-30, 422 invalid on a fraction; below the horizon the factory refuses it, 409 refused with its Russian reason); min_feed_days is described as the feed's horizon, kind fed as every feed reaching its batch_feed_days
