#!/usr/bin/env python3
"""CF-0108: resource sampler - one background process per run, `kind: sample` every ~5 s.

Answers "are we bound by the laptop or by the code?": a stage that keeps the
CPU at 100 % of all cores is hardware-bound, a stage at 8 % is waiting on the
network or an API. Wall time alone cannot tell the two apart.

    sampler.start(batch_dir)     idempotent; pid-file <batch>/RUN_SAMPLER.pid,
                                 spawns `python3 sampler.py --daemon <batch>` detached
    sampler.stop(batch_dir)      SIGTERM (then SIGKILL) the daemon, remove the pid-file
    sampler.running(batch_dir)   pid of a live daemon, or None (a stale pid-file is removed)
    sampler.sample(batch_dir)    one measurement: (params, stage, video)

runlog.marker() calls start() on batch-start (and on stage-start when nothing
is alive) and stop() on batch-done. The daemon also exits by itself when the
pid-file no longer names it, when a batch-done marker appears in the events,
when the batch directory disappears, or after --max-hours (24) - a run that
never reached batch-done does not leave a sampler behind forever.

CF-0339: those conditions all assume the batch dies visibly, and 140 daemons
survived a day of test runs because nothing of the sort happened - the tests'
temp trees were never removed, so every daemon kept a valid directory and a
pid-file naming itself and sampled an empty machine for 24 h (~270 % CPU
together). Two more exits close that by construction:

    --idle-minutes (10)  no process belongs to the run (`procs == []`, not
                         null) and no event but our own samples was written
                         for that long: the run is over, however it ended.
                         The next stage-start marker starts a fresh daemon,
                         so the only samples this can cost are those of an
                         interval in which nothing was happening anyway, and
                         the last sample carries `idle_exit: true`.
    events file lost     RUN_EVENTS.jsonl was removed or replaced by another
                         inode (a temp tree wiped under the daemon). A sample
                         is never emitted into a directory that disappeared
                         while it was being measured either: runlog.emit()
                         creates the parents it needs, and a daemon that
                         re-creates its own deleted batch is immortal.

Event: kind=sample, stage=<open stage from the markers, or null>,
video=<slug of the most recent open script event, or null>, params:

    cpu_total_pct      % of *all* cores busy, 0..100, over the interval since the
                       previous sample (mach host ticks on macOS, /proc/stat on
                       Linux; sum of per-process %cpu / core count as a fallback).
                       null when no probe could measure it
    cpu_pipeline_pct   the same, counted over the run's own processes only; null
                       when the process table could not be read
    cpu_cores          core count
    procs              top pipeline processes by cpu: [{pid, name, cpu_pct, rss_mb}]
                       (descendants of a script that has an open `start` event, or
                       any process whose argv mentions the batch directory);
                       [] when the run owns no live process, null when the process
                       table could not be read
    mem_used_mb        active + wired + compressed (macOS) / MemTotal - MemAvailable (Linux)
    mem_free_mb        total - used
    swap_mb            swap in use
    gpu                {util_pct} from `ioreg` (macOS) or nvidia-smi, else null
    thermal            {speed_limit_pct, scheduler_limit_pct, available_cpus, thermal_level}
                       from `pmset -g therm` + sysctl (macOS), else null
    interval_s         the sampling interval
    sampler_cpu_s      CPU seconds the daemon itself has used so far (its own overhead)
    probe_errors       names of the probes that failed for this sample, or null
    idle_exit          true on the last sample of a daemon that left because the run
                       went idle (CF-0339); absent on every other sample. The silence
                       after it is the run standing still, not the machine stopping

CF-0167: a failed probe must never be written as a measured zero. The first
instrumented run wrote `cpu_total_pct: 0.0` / `procs: []` in all 3007 samples
because `_ps()` returned an empty list both when `ps` had listed no process
and when `ps` could not run at all (it is the one probe that needs to
enumerate other processes, so a sandbox that forbids that kills it while
vm_stat/ioreg/pmset keep answering). Two changes: CPU is now taken natively on
macOS (`host_statistics` for the machine, `libproc` for the processes), which
needs no subprocess at all, and a probe that fails writes `null` plus its name
into `probe_errors` instead of a zero.

Stdlib + system utilities only (libproc/mach via ctypes, ps, vm_stat, sysctl,
ioreg, pmset; /proc on Linux), no profilers. Nothing here raises into a run:
every probe that fails becomes a null field, and start()/stop() swallow errors
into a stderr line.
"""
import ctypes
import ctypes.util
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runlog  # noqa: E402

__all__ = ["PID_FILE", "KIND_SAMPLE", "INTERVAL_S", "start", "stop", "running", "sample",
           "pid_alive", "main"]

PID_FILE = "RUN_SAMPLER.pid"
KIND_SAMPLE = "sample"
INTERVAL_S = 5.0
MAX_HOURS = 24.0
IDLE_MINUTES = 10.0         # CF-0339: no process of the run and no event of its own for this long
TOP_PROCS = 8
BOOTSTRAP_S = 0.3           # first call in a process: window for the delta-based probes
MAX_ARGV_LOOKUPS = 64       # per sample, for processes that are not descendants of a script
PIPELINE_NAMES = ("python", "python3", "ffmpeg", "ffprobe", "node", "whisper", "whisper-cli",
                  "main", "kokoro", "yt-dlp", "chrome", "chromium", "google chrome",
                  "vision", "sox", "magick", "convert")

_darwin = sys.platform == "darwin"
_page_size = None


def _warn(msg):
    runlog._warn(f"sampler: {msg}")


def pid_file(batch_dir):
    return Path(batch_dir) / PID_FILE


def pid_alive(pid):
    try:
        pid = int(pid)
        try:                                      # reap it when it is our own exited child:
            done, _ = os.waitpid(pid, os.WNOHANG)  # a zombie still answers kill(pid, 0)
            if done == pid:
                return False
        except ChildProcessError:
            pass
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, ValueError, TypeError):
        return False


def _read_pid(batch_dir):
    try:
        return int(pid_file(batch_dir).read_text().strip().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def running(batch_dir):
    """Pid of a live daemon for the batch, else None (a stale pid-file is removed)."""
    pid = _read_pid(batch_dir)
    if pid is None:
        return None
    if pid_alive(pid):
        return pid
    try:
        pid_file(batch_dir).unlink()
    except OSError:
        pass
    return None


def start(batch_dir, interval=INTERVAL_S, idle_minutes=IDLE_MINUTES):
    """Start the daemon for the batch unless one is alive. Returns its pid, or None."""
    try:
        bdir = Path(batch_dir).expanduser().resolve()
        alive = running(bdir)
        if alive:
            return alive
        if not bdir.is_dir():
            _warn(f"no batch dir {bdir}")
            return None
        env = dict(os.environ)
        env[runlog.BATCH_ENV] = str(bdir)
        env.pop(runlog.PARENT_ENV, None)
        proc = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--daemon", str(bdir),
             "--interval", str(interval), "--idle-minutes", str(idle_minutes)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True, close_fds=True, env=env, cwd=str(bdir))
        tmp = pid_file(bdir).with_suffix(".pid.tmp")
        tmp.write_text(f"{proc.pid}\n")
        os.replace(tmp, pid_file(bdir))
        return proc.pid
    except Exception as e:                        # accounting never breaks a run
        _warn(f"not started ({e.__class__.__name__}: {e})")
        return None


def stop(batch_dir, timeout=3.0):
    """Stop the daemon of the batch. True when a live daemon was stopped."""
    try:
        bdir = Path(batch_dir).expanduser().resolve()
        pid = _read_pid(bdir)
        stopped = False
        if pid and pid_alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
            t0 = time.monotonic()
            while pid_alive(pid) and time.monotonic() - t0 < timeout:
                time.sleep(0.05)
            if pid_alive(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
            stopped = True
        try:
            pid_file(bdir).unlink()
        except OSError:
            pass
        return stopped
    except Exception as e:
        _warn(f"not stopped ({e.__class__.__name__}: {e})")
        return False


# --------------------------------------------------------------------------
# probes
# --------------------------------------------------------------------------

def _sh(cmd, timeout=4):
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return cp.stdout if cp.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _cores():
    try:
        return os.cpu_count() or 1
    except Exception:
        return 1


# --------------------------------------------------------------------------
# native probes (macOS): no subprocess, so a blocked or missing `ps` cannot
# turn a measurement into a silent zero - CF-0167
# --------------------------------------------------------------------------

_CTL_KERN, _KERN_PROCARGS2 = 1, 49
_PROC_PIDTASKALLINFO = 2
_HOST_CPU_LOAD_INFO = 3
_ARGV_BUF = 262144

_libc = None


class _ProcBSDInfo(ctypes.Structure):
    _fields_ = [("pbi_flags", ctypes.c_uint32), ("pbi_status", ctypes.c_uint32),
                ("pbi_xstatus", ctypes.c_uint32), ("pbi_pid", ctypes.c_uint32),
                ("pbi_ppid", ctypes.c_uint32), ("pbi_uid", ctypes.c_uint32),
                ("pbi_gid", ctypes.c_uint32), ("pbi_ruid", ctypes.c_uint32),
                ("pbi_rgid", ctypes.c_uint32), ("pbi_svuid", ctypes.c_uint32),
                ("pbi_svgid", ctypes.c_uint32), ("rfu_1", ctypes.c_uint32),
                ("pbi_comm", ctypes.c_char * 16), ("pbi_name", ctypes.c_char * 32),
                ("pbi_nfiles", ctypes.c_uint32), ("pbi_pgid", ctypes.c_uint32),
                ("pbi_pjobc", ctypes.c_uint32), ("e_tdev", ctypes.c_uint32),
                ("e_tpgid", ctypes.c_uint32), ("pbi_nice", ctypes.c_int32),
                ("pbi_start_tvsec", ctypes.c_uint64), ("pbi_start_tvusec", ctypes.c_uint64)]


class _ProcTaskInfo(ctypes.Structure):
    _fields_ = [("pti_virtual_size", ctypes.c_uint64), ("pti_resident_size", ctypes.c_uint64),
                ("pti_total_user", ctypes.c_uint64), ("pti_total_system", ctypes.c_uint64),
                ("pti_threads_user", ctypes.c_uint64), ("pti_threads_system", ctypes.c_uint64),
                ("pti_policy", ctypes.c_int32), ("pti_faults", ctypes.c_int32),
                ("pti_pageins", ctypes.c_int32), ("pti_cow_faults", ctypes.c_int32),
                ("pti_messages_sent", ctypes.c_int32), ("pti_messages_received", ctypes.c_int32),
                ("pti_syscalls_mach", ctypes.c_int32), ("pti_syscalls_unix", ctypes.c_int32),
                ("pti_csw", ctypes.c_int32), ("pti_threadnum", ctypes.c_int32),
                ("pti_numrunning", ctypes.c_int32), ("pti_priority", ctypes.c_int32)]


class _ProcTaskAllInfo(ctypes.Structure):
    _fields_ = [("pbsd", _ProcBSDInfo), ("ptinfo", _ProcTaskInfo)]


class _HostCPULoadInfo(ctypes.Structure):
    _fields_ = [("cpu_ticks", ctypes.c_uint * 4)]      # user, system, idle, nice


def _libc_handle():
    """libSystem, or None when ctypes cannot reach it (then everything falls back to `ps`)."""
    global _libc
    if _libc is None:
        try:
            _libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.dylib", use_errno=True)
        except (OSError, AttributeError):
            _libc = False
    return _libc or None


def _libproc_raw():
    """[(pid, ppid, cpu_ns, rss_mb, name, start_epoch_s)] for every readable process, or None."""
    libc = _libc_handle()
    if libc is None:
        return None
    try:
        n = libc.proc_listallpids(None, 0)
        if n <= 0:
            return None
        buf = (ctypes.c_int * (n + 128))()
        got = libc.proc_listallpids(buf, ctypes.sizeof(buf))
        if got <= 0:
            return None
        info = _ProcTaskAllInfo()
        size = ctypes.sizeof(info)
        rows = []
        for i in range(min(got, len(buf))):
            pid = buf[i]
            if pid <= 0:
                continue
            # another user's process, or one that exited between the two calls
            if libc.proc_pidinfo(pid, _PROC_PIDTASKALLINFO, ctypes.c_uint64(0),
                                 ctypes.byref(info), size) != size:
                continue
            name = (info.pbsd.pbi_name or info.pbsd.pbi_comm or b"?").decode("utf-8", "replace")
            rows.append((pid, int(info.pbsd.pbi_ppid),
                         int(info.ptinfo.pti_total_user) + int(info.ptinfo.pti_total_system),
                         info.ptinfo.pti_resident_size / 2**20, name,
                         int(info.pbsd.pbi_start_tvsec)))
        return rows or None
    except Exception:
        return None


def _argv(pid):
    """The full command line of a process (KERN_PROCARGS2), or None when it is not readable."""
    libc = _libc_handle()
    if libc is None:
        return None
    try:
        mib = (ctypes.c_int * 3)(_CTL_KERN, _KERN_PROCARGS2, int(pid))
        size = ctypes.c_size_t(_ARGV_BUF)
        buf = ctypes.create_string_buffer(_ARGV_BUF)
        if libc.sysctl(mib, 3, buf, ctypes.byref(size), None, ctypes.c_size_t(0)) != 0:
            return None
        data = buf.raw[:size.value]
        argc = int.from_bytes(data[:4], sys.byteorder)
        rest = data[4:]
        zero = rest.find(b"\0")
        if zero < 0:
            return None
        exec_path, rest = rest[:zero], rest[zero:].lstrip(b"\0")
        parts = [p for p in rest.split(b"\0")[:max(argc, 1)] if p]
        line = b" ".join(parts) or exec_path
        return line.decode("utf-8", "replace")
    except Exception:
        return None


_host_prev = None


def _cpu_total_darwin():
    """% of all cores busy since the previous call (mach host ticks), or None on the first."""
    global _host_prev
    libc = _libc_handle()
    if libc is None:
        return None
    try:
        libc.mach_host_self.restype = ctypes.c_uint
        data, count = _HostCPULoadInfo(), ctypes.c_uint(4)
        if libc.host_statistics(libc.mach_host_self(), _HOST_CPU_LOAD_INFO,
                                ctypes.byref(data), ctypes.byref(count)) != 0:
            return None
        ticks = tuple(int(x) for x in data.cpu_ticks)
    except Exception:
        return None
    prev, _host_prev = _host_prev, ticks
    if prev is None:
        return None
    delta = [a - b for a, b in zip(ticks, prev)]
    total = sum(delta)
    if total <= 0 or any(d < 0 for d in delta):        # first call, or the 32-bit counters wrapped
        return None
    return round(100.0 * (total - delta[2]) / total, 1)


_proc_prev = None                                      # (monotonic_s, {pid: cpu_ns})


def _libproc_rows():
    """[(pid, ppid, cpu_pct, rss_mb, name, args)] from libproc, or None.

    cpu_pct is the share of one core over the window since the previous call - a
    real interval measurement, not the decaying lifetime average `ps` reports. A
    process seen for the first time is measured over its own age, so the short
    ffmpeg calls that live for less than one interval still count.
    """
    global _proc_prev
    raw = _libproc_raw()
    if raw is None:
        return None
    now, wall = time.monotonic(), time.time()
    prev_t, prev = _proc_prev if _proc_prev else (None, {})
    cur, rows = {}, []
    for pid, ppid, cpu_ns, rss_mb, name, started in raw:
        cur[pid] = cpu_ns
        if prev_t is not None and pid in prev:
            window, delta = now - prev_t, cpu_ns - prev[pid]
        else:
            window, delta = (wall - started if started else 0.0), cpu_ns
        pct = 100.0 * (delta / 1e9) / window if window > 0.02 and delta > 0 else 0.0
        rows.append((pid, ppid, max(0.0, pct), rss_mb, name, ""))
    _proc_prev = (now, cur)
    return rows


def _ps():
    """[(pid, ppid, cpu_pct, rss_mb, name, args)] for every process, or None when `ps` failed."""
    out = _sh(["ps", "-A", "-o", "pid=,ppid=,pcpu=,rss=,args="])
    if out is None:                       # not "no processes" - the probe itself did not run
        return None
    rows = []
    for line in out.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 4:
            continue
        try:
            pid, ppid, cpu, rss = int(parts[0]), int(parts[1]), float(parts[2]), int(parts[3])
        except ValueError:
            continue
        args = parts[4] if len(parts) > 4 else ""
        name = os.path.basename(args.split(" ", 1)[0]) if args else "?"
        rows.append((pid, ppid, cpu, rss / 1024.0, name, args))
    if not rows:                          # `ps` printed something we could not parse: also a failure
        return None
    return rows


def _proc_rows(errors):
    """Live process table, or None when no probe could produce one (names go into `errors`)."""
    if _darwin:
        rows = _libproc_rows()
        if rows is not None:
            return rows
        errors.append("libproc")
    rows = _ps()
    if rows is None:
        errors.append("ps")
    return rows


_primed = False


def _prime():
    """Baseline for the delta-based probes; only the first call in a process pays for it."""
    global _primed
    if _primed:
        return
    _primed = True
    if _darwin:
        _cpu_total_darwin()
        _libproc_rows()
    else:
        _cpu_total_linux()
    time.sleep(BOOTSTRAP_S)


def _open_pids_and_context(events):
    """Pids of scripts with an open start, the open stage, the latest open video."""
    open_scripts = {}
    stage = None
    for e in events:
        k, st = e.get("kind"), e.get("status")
        if k == runlog.KIND_MARKER:
            if st == runlog.M_STAGE_START:
                stage = e.get("stage")
            elif st in (runlog.M_STAGE_DONE, runlog.M_BATCH_DONE):
                stage = None
        elif k == runlog.KIND_SCRIPT and e.get("id"):
            if st == runlog.ST_START:
                open_scripts[e["id"]] = e
            else:
                open_scripts.pop(e["id"], None)
    video = None
    pids = set()
    for e in open_scripts.values():
        if e.get("pid"):
            pids.add(int(e["pid"]))
        if e.get("video"):
            video = e["video"]
    return pids, stage, video


def _name_is_pipeline(name):
    n = (name or "").lower()
    return any(n.startswith(p) for p in PIPELINE_NAMES)


def _pipeline_set(rows, roots, batch_dir, self_pid, argv_of=_argv):
    children = {}
    for pid, ppid, *_ in rows:
        children.setdefault(ppid, []).append(pid)
    wanted = set()
    stack = [p for p in roots if p != self_pid]
    while stack:
        p = stack.pop()
        if p in wanted:
            continue
        wanted.add(p)
        stack.extend(children.get(p, []))
    key = str(batch_dir)
    base = Path(batch_dir).name
    budget = MAX_ARGV_LOOKUPS
    for pid, ppid, cpu, rss, name, args in rows:
        if pid == self_pid or name == "ps" or pid in wanted:
            continue
        if not args and argv_of and budget > 0 and _name_is_pipeline(name):
            budget -= 1                   # libproc gives no command line; ask for it only here
            args = argv_of(pid) or ""
        if not args:
            continue
        if "sampler.py" in args and "--daemon" in args:
            continue
        if key in args or (base and f"/{base}" in args):
            wanted.add(pid)
    wanted.discard(self_pid)
    return wanted


def _mem_darwin():
    global _page_size
    out = _sh(["vm_stat"])
    if not out:
        return None, None
    m = re.search(r"page size of (\d+)", out)
    if m:
        _page_size = int(m.group(1))
    ps = _page_size or 4096
    vals = {}
    for line in out.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            v = v.strip().rstrip(".")
            if v.isdigit():
                vals[k.strip().lower()] = int(v)
    used = (vals.get("pages active", 0) + vals.get("pages wired down", 0)
            + vals.get("pages occupied by compressor", 0)) * ps
    total = None
    t = _sh(["sysctl", "-n", "hw.memsize"])
    if t and t.strip().isdigit():
        total = int(t.strip())
    used_mb = round(used / 2**20)
    free_mb = round((total - used) / 2**20) if total else None
    return used_mb, free_mb


def _swap_darwin():
    out = _sh(["sysctl", "-n", "vm.swapusage"])
    m = re.search(r"used\s*=\s*([\d.]+)([MGK])", out or "")
    if not m:
        return None
    n, unit = float(m.group(1)), m.group(2)
    return round(n * {"K": 1 / 1024, "M": 1, "G": 1024}[unit], 1)


def _gpu_darwin():
    out = _sh(["ioreg", "-r", "-d", "1", "-c", "IOAccelerator"])
    if not out:
        return None
    best = None
    for m in re.finditer(r'"Device Utilization %"=(\d+)', out):
        v = int(m.group(1))
        best = v if best is None else max(best, v)
    return {"util_pct": best} if best is not None else None


def _thermal_darwin():
    out = _sh(["pmset", "-g", "therm"])
    if out is None:
        return None
    th = {}
    for key, name in (("CPU_Speed_Limit", "speed_limit_pct"),
                      ("CPU_Scheduler_Limit", "scheduler_limit_pct"),
                      ("CPU_Available_CPUs", "available_cpus")):
        m = re.search(key + r"\s*=\s*(\d+)", out)
        if m:
            th[name] = int(m.group(1))
    lvl = _sh(["sysctl", "-n", "machdep.xcpm.cpu_thermal_level"])
    if lvl and lvl.strip().lstrip("-").isdigit():
        th["thermal_level"] = int(lvl.strip())
    return th or None


_linux_prev = None


def _cpu_total_linux():
    """% of all cores busy since the previous call (/proc/stat delta), or None on the first."""
    global _linux_prev
    try:
        with open("/proc/stat") as fh:
            f = fh.readline().split()[1:]
        vals = [int(x) for x in f]
        idle, total = vals[3] + vals[4], sum(vals)
    except (OSError, ValueError, IndexError):
        return None
    prev, _linux_prev = _linux_prev, (idle, total)
    if not prev or total == prev[1]:
        return None
    return round(100.0 * (1 - (idle - prev[0]) / (total - prev[1])), 1)


def _mem_linux():
    try:
        info = {}
        with open("/proc/meminfo") as fh:
            for line in fh:
                k, v = line.split(":", 1)
                info[k] = int(v.strip().split()[0])
        total, avail = info["MemTotal"], info.get("MemAvailable", info.get("MemFree", 0))
        swap = info.get("SwapTotal", 0) - info.get("SwapFree", 0)
        return round((total - avail) / 1024), round(avail / 1024), round(swap / 1024, 1)
    except (OSError, ValueError, KeyError):
        return None, None, None


def _gpu_linux():
    out = _sh(["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"])
    if not out:
        return None
    try:
        return {"util_pct": max(int(x) for x in out.split())}
    except ValueError:
        return None


def _self_cpu_s():
    try:
        t = os.times()
        return round(t.user + t.system, 3)
    except Exception:
        return None


def sample(batch_dir, events=None, interval=INTERVAL_S):
    """One measurement: (params, stage, video). Never raises."""
    bdir = Path(batch_dir)
    try:
        ev = events if events is not None else runlog.read_events(bdir)
    except Exception:
        ev = []
    roots, stage, video = _open_pids_and_context(ev)
    cores = _cores()
    errors = []
    _prime()
    rows = _proc_rows(errors)
    if rows is None:                      # no process table: report "unknown", never a zero
        pipe_pct, procs = None, None
    else:
        wanted = _pipeline_set(rows, roots, bdir, os.getpid())
        pipe_rows = [r for r in rows if r[0] in wanted]
        pipe_pct = min(100.0, round(sum(r[2] for r in pipe_rows) / cores, 1))
        top = sorted(pipe_rows, key=lambda r: (-r[2], -r[3]))[:TOP_PROCS]
        procs = [{"pid": r[0], "name": r[4][:40], "cpu_pct": round(r[2], 1),
                  "rss_mb": round(r[3], 1)} for r in top]
    cpu_total = _cpu_total_darwin() if _darwin else _cpu_total_linux()
    if cpu_total is None and rows is not None:        # fall back to the sum over the processes
        cpu_total = round(sum(r[2] for r in rows) / cores, 1)
    if cpu_total is None:
        errors.append("cpu_total")
    if _darwin:
        used, free = _mem_darwin()
        swap, gpu, thermal = _swap_darwin(), _gpu_darwin(), _thermal_darwin()
    else:
        used, free, swap = _mem_linux()
        gpu, thermal = _gpu_linux(), None
    for name, value in (("mem", used), ("swap", swap), ("gpu", gpu), ("thermal", thermal)):
        if value is None:
            errors.append(name)
    params = {
        "cpu_total_pct": min(100.0, max(0.0, cpu_total)) if cpu_total is not None else None,
        "cpu_pipeline_pct": pipe_pct,
        "cpu_cores": cores,
        "procs": procs,
        "mem_used_mb": used,
        "mem_free_mb": free,
        "swap_mb": swap,
        "gpu": gpu,
        "thermal": thermal,
        "interval_s": interval,
        "sampler_cpu_s": _self_cpu_s(),
        "probe_errors": errors or None,
    }
    return params, stage, video


# --------------------------------------------------------------------------
# daemon
# --------------------------------------------------------------------------

class _Tail:
    """Incremental reader of RUN_EVENTS.jsonl: keeps the events seen so far.

    CF-0339: it also answers two questions the daemon needs to know when to
    stop - whether the file it has been following is still the same file
    (`gone`: removed or replaced by another inode, i.e. the batch was wiped)
    and how many events of the run itself (everything but our own samples)
    have been written so far (`others`)."""

    def __init__(self, batch_dir):
        self.path = runlog.events_path(batch_dir)
        self.pos = 0
        self.events = []
        self.ino = None
        self.gone = False
        self.others = 0

    def refresh(self):
        try:
            try:
                st = self.path.stat()
            except OSError:
                if self.ino is not None:              # the file we followed was removed
                    self.gone = True
                return self.events
            if self.ino is None:
                self.ino = st.st_ino
            elif st.st_ino != self.ino:               # replaced: this is another run's file
                self.gone = True
                return self.events
            size = st.st_size
            if size < self.pos:                       # truncated / replaced
                self.pos, self.events, self.others = 0, [], 0
            if size == self.pos:
                return self.events
            with open(self.path, "rb") as fh:
                fh.seek(self.pos)
                chunk = fh.read()
            nl = chunk.rfind(b"\n")
            if nl < 0:
                return self.events
            for line in chunk[:nl].decode("utf-8", "replace").splitlines():
                line = line.strip()
                if line:
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    self.events.append(e)
                    if e.get("kind") != KIND_SAMPLE:
                        self.others += 1
            self.pos += nl + 1
        except OSError:
            pass
        return self.events


def _daemon(batch_dir, interval, max_hours, idle_minutes=IDLE_MINUTES):
    bdir = Path(batch_dir)
    stop_flag = {"stop": False}

    def _term(signum, frame):
        stop_flag["stop"] = True

    signal.signal(signal.SIGTERM, _term)
    signal.signal(signal.SIGINT, _term)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    tail = _Tail(bdir)
    deadline = time.monotonic() + max_hours * 3600
    idle_limit = max(0.0, idle_minutes) * 60.0
    idle_since, others = None, -1
    me = os.getpid()
    while not stop_flag["stop"] and time.monotonic() < deadline:
        t0 = time.monotonic()
        if not bdir.is_dir() or _read_pid(bdir) != me:
            break
        events = tail.refresh()
        if tail.gone:                       # CF-0339: our events file was removed or replaced
            break
        if any(e.get("kind") == runlog.KIND_MARKER and e.get("status") == runlog.M_BATCH_DONE
               for e in events[-50:]):
            break
        try:
            params, stage, video = sample(bdir, events=events, interval=interval)
            if not bdir.is_dir():           # wiped while we measured: never re-create it
                break
            # CF-0339: a run that owns no live process and writes no event of its own is
            # over - whether it crashed, was a test, or forgot its batch-done marker. The
            # next stage-start marker starts a fresh daemon, so this can only cost the
            # samples of an interval in which, by definition, nothing happened. The last
            # sample says so (`idle_exit`), so the silence after it has a reason on record
            # rather than looking like a machine that stopped (gaps.py).
            procs = params.get("procs")
            live = procs is None or bool(procs)       # None: the process table is unreadable
            if live or tail.others != others:
                idle_since, others = None, tail.others
            elif idle_since is None:
                idle_since = t0
            leaving = bool(idle_limit) and idle_since is not None \
                and t0 - idle_since >= idle_limit
            if leaving:
                params["idle_exit"] = True
            runlog.emit(bdir, KIND_SAMPLE, stage, video=video, params=params)
            if leaving:
                break
        except Exception as e:
            _warn(f"sample skipped ({e.__class__.__name__}: {e})")
        # sleep in slices so SIGTERM is honoured within ~100 ms
        wake = t0 + interval
        while not stop_flag["stop"] and time.monotonic() < wake:
            time.sleep(min(0.1, max(0.0, wake - time.monotonic())))
    if _read_pid(bdir) == me:
        try:
            pid_file(bdir).unlink()
        except OSError:
            pass
    return 0


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="sampler")
    ap.add_argument("--daemon", metavar="BATCH_DIR")
    ap.add_argument("--interval", type=float, default=INTERVAL_S)
    ap.add_argument("--max-hours", type=float, default=MAX_HOURS)
    ap.add_argument("--idle-minutes", type=float, default=IDLE_MINUTES,
                    help="exit after this long with no process and no event of the run (0: never)")
    ap.add_argument("--once", metavar="BATCH_DIR", help="print one sample as JSON and exit")
    ap.add_argument("--start", metavar="BATCH_DIR")
    ap.add_argument("--stop", metavar="BATCH_DIR")
    ns = ap.parse_args(argv)
    if ns.daemon:
        return _daemon(ns.daemon, max(0.5, ns.interval), ns.max_hours, ns.idle_minutes)
    if ns.once:
        p, stage, video = sample(ns.once)
        print(json.dumps({"stage": stage, "video": video, "params": p}, ensure_ascii=False, indent=2))
        return 0
    if ns.start:
        pid = start(ns.start, ns.interval)
        print(pid or "")
        return 0 if pid else 1
    if ns.stop:
        print("stopped" if stop(ns.stop) else "not running")
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
