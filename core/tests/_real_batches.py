"""The root's live-monitor registry (read by AST by shared/runlog/monitors.py).

Empty in this snapshot: the production registry names checks that read the
live batch tree, which is not part of the snapshot. The format is kept so the
monitor runner has something to read:

    LIVE_ENV = "<switch that turns the live parts on>"
    LIVE_MONITORS = {"test_x.py::check_name": "what the live check is for"}
"""
LIVE_ENV = "FACTORY_LIVE"
LIVE_MONITORS = {}
