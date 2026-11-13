#!/usr/bin/env python3
"""Where macOS Vision runs its models: CPU on an Intel Mac (CF-0711).

Left to itself Vision hands its CoreML models (text recognition, faces,
saliency, body pose) to the GPU. On this pipeline's machine - a MacBookPro16,1
with an Intel UHD 630 and a Radeon - that is what took the laptop down on
12.10 23:44: the warm Vision worker (vision_worker.py, python3.12, pid 67739)
was serving footage-indexer's accurate-mode `text_regions` probes back to
back for 25 minutes, the machine was thermally throttled to 35-46% CPU speed,
and the GPU's blitter ring hung under it ("GPU Reset", Application: Python,
BCS ring "Appears hung"). The system spindump taken a few seconds later shows
that worker - the only Python on the machine with GPU frames - blocked in the
kernel inside IOAcceleratorFamily2, called from CoreML -> CoreVideo ->
IOSurface under VNRecognizeTextRequest. WindowServer then missed its
watchdog twice and the machine shut down.

The same iGPU had already reset seven times in the three days before
(mediaanalysisd, the Claude app), so the chip is the weak part; what is ours
to change is that the factory stops feeding it. On an Intel Mac every Vision
request this repo makes is pinned to the CPU, both ways Vision offers:
`usesCPUOnly` (deprecated since macOS 14 but still honoured) and, where the
OS has it, `setComputeDevice:forComputeStage:` with the MLCPUComputeDevice
for every stage. Apple Silicon keeps Vision's own choice - its GPU/ANE are a
different story and nothing there has hung.

The same decision - `gpu_off()` - keeps render_video.py's Remotion render off
`--gl=angle` (Chrome's GPU rasteriser) on an Intel Mac: the Claude app's own
Chromium GPU process reset this chip on 11.10, and the factory has no business
adding a second Chrome on it.

Override with FACTORY_GPU: `off` (or `cpu`) keeps every factory GPU path off
on any machine, `on` (or `auto`) gives Vision and Remotion their own choice
back (the old behaviour - for measuring, not for runs).

Every step is best-effort: a request that answers neither selector, or an
enumeration that fails, is left as it was. Pinning is about the machine's
health, and a frame must never fail because of it.
"""
import os
import platform

ENV = "FACTORY_GPU"


def gpu_off(env=None, machine=None):
    """True when the factory keeps its work off this machine's GPU.

    `env`/`machine` are for tests; by default they come from the process
    environment and the interpreter's own architecture (`x86_64` is every
    Intel Mac; an x86 interpreter under Rosetta also reads x86_64 and is
    kept off the GPU too, which costs only speed)."""
    value = (os.environ.get(ENV, "") if env is None else env).strip().lower()
    if value in ("off", "cpu"):
        return True
    if value in ("on", "auto"):
        return False
    return (platform.machine() if machine is None else machine) == "x86_64"


# Vision's reading of the same decision: pinned to the CPU when the GPU is off.
wants_cpu = gpu_off


def _is_cpu_device(device):
    return "CPU" in type(device).__name__


def pin(request, cpu=None):
    """Pin one Vision request to the CPU when `wants_cpu()`; returns it.

    Call on every VN*Request before `performRequests_error_`."""
    if not (wants_cpu() if cpu is None else cpu):
        return request
    try:
        if request.respondsToSelector_(b"setUsesCPUOnly:"):
            request.setUsesCPUOnly_(True)
    except Exception:
        pass
    try:
        if not (request.respondsToSelector_(b"supportedComputeStageDevicesAndReturnError:")
                and request.respondsToSelector_(b"setComputeDevice:forComputeStage:")):
            return request
        found = request.supportedComputeStageDevicesAndReturnError_(None)
        stages = found[0] if isinstance(found, tuple) else found
        for stage, devices in dict(stages or {}).items():
            cpu_device = next((d for d in (devices or []) if _is_cpu_device(d)), None)
            if cpu_device is not None:
                request.setComputeDevice_forComputeStage_(cpu_device, stage)
    except Exception:
        pass
    return request


def pin_all(requests, cpu=None):
    """pin() over a list of requests; returns the list."""
    for r in requests:
        pin(r, cpu=cpu)
    return requests
