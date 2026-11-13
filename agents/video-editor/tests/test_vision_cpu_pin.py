#!/usr/bin/env python3
"""CF-0711: on an Intel Mac every macOS Vision request runs on the CPU.

12.10 23:44 the warm Vision worker's text recognition hung the Intel UHD 630
(GPU Reset, Application: Python) and the laptop shut down. vision_compute.pin()
is what keeps Vision's CoreML models off the GPU; these checks drive it with
stand-in request objects only - nothing here loads Vision, CoreML or touches
a GPU.

No pytest dependency - plain asserts, run directly.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import inspect
import os
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import vision_compute  # noqa: E402


class MLGPUComputeDevice:
    pass


class MLCPUComputeDevice:
    pass


class FakeRequest:
    """Answers the selectors a VNRequest answers on macOS 14+."""

    def __init__(self, selectors=None, stages=None, enum_raises=False):
        self.selectors = set(selectors if selectors is not None else (
            b"setUsesCPUOnly:", b"supportedComputeStageDevicesAndReturnError:",
            b"setComputeDevice:forComputeStage:"))
        self.stages = stages if stages is not None else {
            "VNComputeStageMain": [MLGPUComputeDevice(), MLGPUComputeDevice(), MLCPUComputeDevice()],
            "VNComputeStagePostProcessing": [MLGPUComputeDevice(), MLCPUComputeDevice()],
        }
        self.enum_raises = enum_raises
        self.cpu_only = False
        self.devices = {}

    def respondsToSelector_(self, sel):
        return sel in self.selectors

    def setUsesCPUOnly_(self, flag):
        self.cpu_only = flag

    def supportedComputeStageDevicesAndReturnError_(self, err):
        if self.enum_raises:
            raise RuntimeError("enumeration failed")
        return (self.stages, None)

    def setComputeDevice_forComputeStage_(self, device, stage):
        self.devices[stage] = device


def _with_env(value, fn):
    old = os.environ.get(vision_compute.ENV)
    try:
        if value is None:
            os.environ.pop(vision_compute.ENV, None)
        else:
            os.environ[vision_compute.ENV] = value
        return fn()
    finally:
        if old is None:
            os.environ.pop(vision_compute.ENV, None)
        else:
            os.environ[vision_compute.ENV] = old


def test_intel_mac_wants_cpu_apple_silicon_does_not():
    assert vision_compute.wants_cpu(env="", machine="x86_64") is True
    assert vision_compute.wants_cpu(env="", machine="arm64") is False


def test_env_overrides_the_architecture():
    assert vision_compute.gpu_off(env="off", machine="arm64") is True
    assert vision_compute.gpu_off(env="CPU ", machine="arm64") is True
    assert vision_compute.gpu_off(env="on", machine="x86_64") is False
    assert vision_compute.gpu_off(env="auto", machine="x86_64") is False
    assert vision_compute.gpu_off(env="nonsense", machine="x86_64") is True


def test_pin_sets_cpu_only_and_the_cpu_device_for_every_stage():
    r = FakeRequest()
    assert vision_compute.pin(r, cpu=True) is r
    assert r.cpu_only is True
    assert set(r.devices) == {"VNComputeStageMain", "VNComputeStagePostProcessing"}
    assert all(isinstance(d, MLCPUComputeDevice) for d in r.devices.values())


def test_pin_leaves_the_request_alone_when_cpu_is_not_wanted():
    r = FakeRequest()
    vision_compute.pin(r, cpu=False)
    assert r.cpu_only is False and r.devices == {}


def test_a_stage_without_a_cpu_device_is_left_to_vision():
    r = FakeRequest(stages={"VNComputeStageMain": [MLGPUComputeDevice()]})
    vision_compute.pin(r, cpu=True)
    assert r.cpu_only is True and r.devices == {}


def test_an_old_os_request_gets_only_uses_cpu_only():
    r = FakeRequest(selectors={b"setUsesCPUOnly:"})
    vision_compute.pin(r, cpu=True)
    assert r.cpu_only is True and r.devices == {}


def test_a_failing_enumeration_never_fails_the_frame():
    r = FakeRequest(enum_raises=True)
    vision_compute.pin(r, cpu=True)
    assert r.cpu_only is True and r.devices == {}


def test_a_request_with_no_selectors_passes_through():
    r = FakeRequest(selectors=set())
    assert vision_compute.pin(r, cpu=True) is r
    assert r.cpu_only is False and r.devices == {}


def test_pin_all_pins_each_request():
    a, b = FakeRequest(), FakeRequest()
    assert vision_compute.pin_all([a, b], cpu=True) == [a, b]
    assert a.cpu_only and b.cpu_only


def test_smart_crop_perform_pins_before_vision_runs():
    import smart_crop

    seen = {}

    class Handler:
        def performRequests_error_(self, requests, err):
            seen["cpu_only_at_perform"] = requests[0].cpu_only
            return (True, None)

    r = FakeRequest()
    r.results = lambda: []
    _with_env("off", lambda: smart_crop._perform(Handler(), r))
    assert seen["cpu_only_at_perform"] is True
    assert isinstance(r.devices["VNComputeStageMain"], MLCPUComputeDevice)


def test_every_vision_call_site_goes_through_the_pin():
    """The three places this repo builds VN*Requests: text recognition (the
    one that hung the GPU), smart_crop's _perform (faces, saliency) and
    held_screen's pose+face pass. A new call site that skips the pin
    would put the iGPU back in the path."""
    import detect_text_band
    import held_screen
    import smart_crop
    assert "vision_compute.pin(req)" in inspect.getsource(detect_text_band._text_regions)
    assert "vision_compute.pin(request)" in inspect.getsource(smart_crop._perform)
    assert "vision_compute.pin_all([pose, face])" in inspect.getsource(held_screen.body_pose)
    for path in sorted(SCRIPTS.glob("*.py")):
        if path.name == "vision_compute.py":
            continue
        src = path.read_text(encoding="utf-8")
        if "performRequests_error_" in src:
            assert "vision_compute.pin" in src, f"{path.name} runs Vision without the CPU pin"


def test_render_stays_off_the_gpu_rasteriser_where_the_gpu_is_off():
    """render_video.gl_here(): a typographic plan wants --gl=angle (CF-0052),
    but not on a machine the factory keeps off its GPU (CF-0711)."""
    import render_video
    plan = {"style": "typographic", "blocks": []}
    assert render_video.gl_for(plan) == "angle"
    assert _with_env("off", lambda: render_video.gl_here(plan)) is None
    assert _with_env("on", lambda: render_video.gl_here(plan)) == "angle"
    src = inspect.getsource(render_video)
    assert "else gl_here(plan)" in src, "the render no longer asks gl_here()"


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
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
