"""RecordingSession — owns one run's lifecycle: source → ring → consumers → live frames, then
finalize on stop/completion. State machine: idle → recording → finalizing → done (or error)."""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
import uuid

import numpy as np

from . import virtual_channels
from .acquisition.consumers import CutDetector, Decimator, FrmIntegrator
from .acquisition.ring import Ring
from .backup import BackupStreamer, mark_remote_deleted
from .backup import load_config as load_backup_config
from .clipping import RailDetector, dyno_gain_array
from .config import RecordConfig
from .d1rw import RawWriter
from .dsp import sum_axes, tacho_column, welch_spectra
from .finalize import finalize
from .recovery import raw_info, write_manifest
from .storage import atomic_write_json, disk_usage_for
from .stream.broadcast import Broadcaster
from .stream.frame import encode_frame

log = logging.getLogger("force_app.session")

# The 8 dyno sub-channels in raw-file column order (data[:, :8]) — matches the client SUB_NAMES.
SUB_NAMES = ["Fx1", "Fx2", "Fy1", "Fy2", "Fz1", "Fz2", "Fz3", "Fz4", "Tacho"]

# Disk-full protection during an active recording (independent of the frontend's own low-disk UI
# alarm, which is advisory only). At DISK_BACKUP_GB, if remote backup is configured but wasn't
# already streaming, switch it on now — BackupStreamer always reads from just after the raw
# header, so it catches the whole recording up, not just what's written from here on. At
# DISK_STOP_GB — a genuine "about to fill the disk" floor — force-stop regardless, since a
# completely full system disk can make Windows itself misbehave, not just this recording.
DISK_BACKUP_GB = 3.0
DISK_STOP_GB = 1.0
DISK_CHECK_INTERVAL = 10.0
RAIL_REPUBLISH_SEC = 2.0
# Live FFT window length (samples) when the rolling buffer holds that many; see _update_fft.
FFT_NPERSEG = 8192


def _raw_rows(capture_dir: str) -> int:
    """Rows actually in the capture's raw file (0 when it is missing or has only its header)."""
    info = raw_info(capture_dir)
    return info["n_rows"] if info else 0


class CutStartRefusedError(Exception):
    """A manual cut-start mark that must not be applied; the message is the reason shown to the
    operator (HTTP 409)."""


class RecordingSession:
    def __init__(
        self, cfg: RecordConfig, captures_root: str, source, broadcaster: Broadcaster | None = None
    ):
        self.cfg = cfg
        self.captures_root = captures_root
        self.id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        self.dir = os.path.join(captures_root, self.id)
        os.makedirs(self.dir, exist_ok=True)
        self.broadcaster = broadcaster
        self.backup: BackupStreamer | None = None
        self.state = "idle"
        self.error: str | None = None
        # Which stage failed, when state is "error" (#84): "start" = nothing was captured (the
        # source never produced a sample — e.g. DAQmx refused the rate), and the empty capture
        # directory is removed; "acquisition" = it failed mid-run but the data captured so far was
        # finalized; "finalize" = data was captured but writing the outputs failed, so the raw is
        # still on disk for recovery. The UI words each case differently.
        self.error_kind: str | None = None
        self.summary: dict | None = None
        self.n_total = 0
        self.peaks = [0.0, 0.0, 0.0]
        self._t_last = 0.0

        self.source = source  # SimSource or ReplaySource (any AcquisitionSource)
        self.ring = Ring(maxsize=128)
        self.raw = RawWriter(
            os.path.join(self.dir, "raw.d1raw"),
            n_cols=1 + len(self.source.channels),
            rate=self.source.rate,
            start_unix=time.time(),
        )
        self.decimator = Decimator(bins=2)
        self.frm = FrmIntegrator(cfg, fs=self.source.rate)
        self.cut = CutDetector(cfg, self.source.rate)
        self.cut_started_t: float | None = None
        # Where the cut origin came from ("auto" = the causal detector, "manual" = the operator's
        # "Start FRM now", #184) and the sample index it sits at; both None until a cut starts.
        # `_cut_lock` serialises the consumer thread's per-chunk detect/FRM work with a manual mark
        # arriving on an HTTP thread, so exactly one of them sets the origin.
        self.cut_start_source: str | None = None
        self.cut_start_sample: int | None = None
        self._cut_lock = threading.Lock()
        # Live railing test on the raw volts (see clipping.py); needs the per-channel gains, so
        # it is inert for sim/replay. Its latched set is streamed and reported in status().
        self.rails = RailDetector(cfg.dyno_gains, cfg.analog_fullscale_v, cfg.daq_input_range_v)
        self._rail_sent = 0.0
        # Volts -> N for the live view (#212), the same per-channel gains finalize applies. None
        # when there are none (sim/replay data is already in newtons).
        self._live_gains = dyno_gain_array(cfg.dyno_gains)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._finalize_thread: threading.Thread | None = None
        self._disk_thread: threading.Thread | None = None
        self.disk_action: dict | None = None  # last thing the disk watcher did, for the UI
        # None (not False) so the first chunk always publishes, giving the client its initial state
        # instead of leaving it to assume one. False => the tacho is not producing readable pulses.
        self._tacho_ok: bool | None = None
        # Names of virtual channels whose formula has already failed once this session — logged
        # once, not once per chunk (this runs tens of times a second).
        self._extra_eval_errors: set[str] = set()

        # Rolling windows per channel for the live spectra (per-channel FFT / power / spectrogram /
        # waterfall), plus a wall-clock throttle. We keep the 3 summed axes AND the 8 dyno
        # sub-channels so the client can draw a spectrum for any selected channel, like the force.
        self._fft_axis = cfg.axis if cfg.axis in ("Fx", "Fy", "Fz") else "Fz"
        self._fft_names = ["Fx", "Fy", "Fz", *SUB_NAMES]
        self._fft_bufs: dict[str, np.ndarray] = {
            n: np.zeros(0, dtype=np.float64) for n in self._fft_names
        }
        self._fft_cap = int(max(2048, min(200_000, self.source.rate)))  # ~1 s, bounded
        self._fft_last = 0.0
        # Chunks since the last fold into _fft_bufs. Folding (concatenate + trim a ~1 s window per
        # channel) only when a spectrum is due, not per chunk, avoids re-copying 12 windows tens of
        # times a second for spectra published a few times a second.
        self._fft_pending: dict[str, list[np.ndarray]] = {n: [] for n in self._fft_names}
        self._fft_pending_n = 0

    # ---- lifecycle ----
    def start(self) -> None:
        self.state = "recording"
        write_manifest(self.dir, "recording", self.cfg)
        self._enable_backup_now()  # starts it now if configured; a no-op if it isn't
        self._thread = threading.Thread(target=self._run, name=f"rec-{self.id}", daemon=True)
        self._thread.start()
        self._disk_thread = threading.Thread(
            target=self._watch_disk, name=f"rec-disk-{self.id}", daemon=True
        )
        self._disk_thread.start()

    def stop(self, wait: bool = True, timeout: float = 30.0) -> None:
        t0 = time.perf_counter()
        self._stop.set()
        self.source.stop()
        log.info("session.stop: source.stop() returned in %.2fs", time.perf_counter() - t0)
        if wait and self._thread:
            t1 = time.perf_counter()
            self._thread.join(timeout)
            dt = time.perf_counter() - t1
            if self._thread.is_alive():
                log.warning(
                    "session.stop: acquisition thread still alive after %.2fs join timeout", dt
                )
            else:
                log.info("session.stop: acquisition thread joined in %.2fs", dt)

    def _watch_disk(self) -> None:
        """Runs for the life of the recording. Two escalating responses to a filling disk, cheaper
        than the frontend polling loop and independent of it — this keeps protecting the recording
        even if the browser tab is closed or the network to it drops."""
        backed_up_by_watcher = False
        while not self._stop.is_set() and self.state == "recording":
            try:
                free_gb = disk_usage_for(self.captures_root).get("free_gb")
            except Exception:
                free_gb = None
            # `None` means the stat failed, not that the disk is full — never act on it. Skipping a
            # check is harmless (the next one is DISK_CHECK_INTERVAL away); killing a good recording
            # over a transient stat error is not.
            if free_gb is None:
                self._stop.wait(DISK_CHECK_INTERVAL)
                continue
            if free_gb < DISK_STOP_GB:
                self.disk_action = {"action": "forced_stop", "free_gb": free_gb}
                self._publish_control({"type": "disk_action", **self.disk_action})
                # Deliberately NOT set on self.error: the recording itself is intact and finalize
                # will succeed, so the terminal state must stay "done" or the frontend refuses to
                # load/save it — i.e. the recordings this guard exists to protect would be exactly
                # the ones the user loses. `disk_action` already carries the reason for the UI.
                self.stop(wait=False)
                return
            if free_gb < DISK_BACKUP_GB and self.backup is None and not backed_up_by_watcher:
                backed_up_by_watcher = True
                if self._enable_backup_now():
                    self.disk_action = {"action": "backup_started", "free_gb": free_gb}
                else:
                    self.disk_action = {"action": "backup_unavailable", "free_gb": free_gb}
                self._publish_control({"type": "disk_action", **self.disk_action})
            self._stop.wait(DISK_CHECK_INTERVAL)

    def _enable_backup_now(self) -> bool:
        """Turn on remote backup mid-recording. BackupStreamer always tails from right after the
        raw header, so this catches up the whole recording so far, not just what's written after
        this point — a genuine safety net, not just a "protect what's left" measure."""
        if self.backup is not None:
            return False
        bcfg = load_backup_config(self.captures_root)
        if not bcfg.get("enabled") or not bcfg.get("server_url"):
            return False
        try:
            self.backup = BackupStreamer(
                self.id, os.path.join(self.dir, "raw.d1raw"), bcfg["server_url"], self.cfg
            )
            self.backup.start()
            return True
        except Exception:
            self.backup = None
            return False

    def join_finalize(self, timeout: float | None = None) -> None:
        """Block until the background finalize (mat/live_cache/summary write) completes, if one is
        running. stop() no longer waits for this — only the caller who truly needs the finished
        artifacts (e.g. graceful shutdown, before the process may be killed) should call it."""
        if self._finalize_thread:
            self._finalize_thread.join(timeout)

    # ---- worker ----
    def _run(self) -> None:
        # Start the consumer FIRST so it's always joinable — if source.start() raises (e.g. an
        # invalid NI-DAQ device), ring.close() below unblocks it cleanly.
        consumer = threading.Thread(
            target=self._consume, name=f"rec-consume-{self.id}", daemon=True
        )
        consumer.start()
        started = False
        try:
            self.source.start()
            started = True
            while not self._stop.is_set():
                chunk = self.source.read()
                if chunk is None:
                    break
                if not self.ring.put(chunk[0], chunk[1], timeout=5.0):
                    # A closed ring means the consumer already died and recorded why: keep that.
                    self.error = self.error or "consumer overrun"
                    break
        except Exception as e:
            self.error = (
                f"acquisition error: {e}" if started else f"could not start acquisition: {e}"
            )
        finally:
            self.ring.close()
            t_consumer = time.perf_counter()
            consumer.join(timeout=10.0)
            log.info(
                "session._run: consumer thread joined in %.2fs", time.perf_counter() - t_consumer
            )
            t_raw = time.perf_counter()
            self.raw.close()
            log.info(
                "session._run: raw.close() (flush+fsync) took %.2fs", time.perf_counter() - t_raw
            )
            if self.backup:
                self.backup.stop()
            if self.n_total > 0:
                # finalize() does the CPU-heavy work (full-resolution compressed .mat write, D1LC
                # decimation) — run it off this thread so stop()'s join() (and thus the /record/stop
                # HTTP response) returns as soon as the raw capture is safely flushed, instead of
                # blocking for however long that write takes. The "done" state/summary reach the
                # client via the WS control message published below, same as before.
                self.state = "finalizing"
                write_manifest(self.dir, "finalizing", self.cfg)
                self._finalize_thread = threading.Thread(
                    target=self._finalize_async, name=f"rec-finalize-{self.id}", daemon=True
                )
                self._finalize_thread.start()
            else:
                self.state = "error" if self.error else "done"
                if self.error and (_raw_rows(self.dir) == 0):
                    # Failed before a single sample reached the raw file. There is nothing to
                    # finalize or recover — recovery skips a 0-row raw, so the directory would just
                    # sit on disk as an unnamed "incomplete" capture forever. Remove it.
                    self.error_kind = "start"
                    shutil.rmtree(self.dir, ignore_errors=True)
                else:
                    # n_total is bumped AFTER the raw append in _consume, so a failure while
                    # processing the very first chunk leaves rows on disk with n_total == 0. That
                    # data is real: keep the directory (recoverable from Local Captures) and call it
                    # an acquisition failure, not a failed start.
                    if self.error:
                        self.error_kind = "acquisition"
                    write_manifest(self.dir, self.state, self.cfg, self.error)
                self._publish_control(
                    {
                        "type": "done",
                        "id": self.id,
                        "state": self.state,
                        "error": self.error,
                        "error_kind": self.error_kind,
                        "summary": self.summary,
                    }
                )
                if self.error_kind == "start" and self.backup is not None:
                    # The streamer may have registered the (header-only) session already; label
                    # it like any other deleted capture so it expires instead of reading as a
                    # backup. After the publish: it is a network call and the UI shouldn't wait.
                    mark_remote_deleted(self.backup.server_url, self.id)

    def _finalize_async(self) -> None:
        t0 = time.perf_counter()
        log.info("session._finalize_async: starting (n_total=%d)", self.n_total)
        try:
            self.summary = finalize(self.dir, self.cfg)
            self._record_cut_start()
            self.state = "error" if self.error else "done"
            if self.error:
                self.error_kind = "acquisition"
        except Exception as e:
            self.error = self.error or f"finalize error: {e}"  # keep the original cause
            self.error_kind = "finalize"
            self.state = "error"
        log.info(
            "session._finalize_async: finished in %.2fs (state=%s)",
            time.perf_counter() - t0,
            self.state,
        )
        write_manifest(self.dir, self.state, self.cfg, self.error)
        self._publish_control(
            {
                "type": "done",
                "id": self.id,
                "state": self.state,
                "error": self.error,
                "error_kind": self.error_kind,
                "summary": self.summary,
            }
        )

    def _record_cut_start(self) -> None:
        """Add how the live FRM's cut origin was set to summary.json and the in-memory summary
        (#184): "auto" (causal detector), "manual" ("Start FRM now") or null (it never started),
        plus its time and sample index. Provenance only: finalize's crop and the detector are
        untouched. Best effort, since the capture is already complete without it."""
        extra = {
            "cut_start_source": self.cut_start_source,
            "cut_start_sec": self.cut_started_t,
            "cut_start_sample": self.cut_start_sample,
        }
        try:
            path = os.path.join(self.dir, "summary.json")
            with open(path) as f:
                on_disk = json.load(f)
            atomic_write_json(path, {**on_disk, **extra}, indent=2)
        except Exception:
            log.exception("could not record the cut start in summary.json")
        if self.summary is not None:
            self.summary.update(extra)

    def _in_newtons(self, data: np.ndarray) -> np.ndarray:
        """This chunk with the 8 dyno columns converted from volts to newtons, as finalize.py's
        `gained` does for the saved outputs (#212). The live view used to be the bare volts, so on
        the NI-DAQ path the force plot, the running peaks, the cut detector and, through the
        peaks, the force alarm all read low by the N/V gain: a 300 N hit showed as about 15 and
        never tripped a newton limit. Tacho and extra hardware columns are left as acquired; with
        no per-channel gains (sim/replay) the chunk is returned untouched. Drift compensation
        stays a finalize-only step: it needs the whole capture."""
        if self._live_gains is None:
            return data
        live = np.array(data, dtype=np.float64)
        live[:, :8] *= self._live_gains
        return live

    def _extra_values(self, data: np.ndarray, axes: dict[str, np.ndarray]) -> np.ndarray:
        """This chunk's value for every configured extra (Aux/virtual) channel — see
        virtual_channels.compute_extra_columns for the shared logic (also used by finalize.py, so
        the two can't disagree). `data` is this chunk after `_in_newtons`: columns 0-7 are the
        dyno sub-channels in newtons, 8 is Tacho, and 9+ are any real hardware extra channels
        NidaqSource appended (never gain-corrected, here or in finalize.py; only drift
        compensation separates the live values from the archived ones)."""
        hw_raw = data[:, 9:] if data.shape[1] > 9 else None

        def _on_error(name: str, e: virtual_channels.FormulaError) -> None:
            if name not in self._extra_eval_errors:  # log once per session, not once per chunk
                self._extra_eval_errors.add(name)
                log.warning("virtual channel '%s' evaluation failed: %s", name, e)

        return virtual_channels.compute_extra_columns(
            self.cfg.extra_channels, data[:, :8], data[:, 8], axes, hw_raw, on_error=_on_error
        )

    def _set_cut_start(self, t: float, source: str, sample: int) -> None:
        """The one place a cut origin is set, for the detector and the manual button alike (caller
        holds `_cut_lock`): record it, reset the FRM spiral to the origin, and tell the clients."""
        self.cut_started_t = t
        self.cut_start_source = source
        self.cut_start_sample = sample
        self.frm.mark_cut_start()
        self._publish_control({"type": "cutstart", "t": t, "source": source})

    def mark_cut_start_now(self) -> dict:
        """Operator's "Start FRM now" (#184): set the cut origin at the latest acquired sample, as
        if the causal detector had fired there. Raises CutStartRefusedError (-> 409) when not recording,
        when no sample has arrived yet, when a cut start is already set (auto or manual): the
        origin is never moved once set, or when this recording does not hold the FRM for the cut
        (frm_from_cut off): its FRM has run from the first sample, so a mark would re-origin it."""
        with self._cut_lock:
            if self.state != "recording":
                raise CutStartRefusedError("no recording in progress")
            if not self.cfg.frm_from_cut:
                raise CutStartRefusedError(
                    "the FRM is not waiting for the cut (\"Detect cut start\" is off for this "
                    "recording), so there is nothing to start"
                )
            if self.cut_started_t is not None:
                raise CutStartRefusedError(
                    f"the cut start is already set ({self.cut_start_source}, "
                    f"t={self.cut_started_t:.2f} s)"
                )
            if self.n_total == 0:
                raise CutStartRefusedError("no samples acquired yet")
            t = self._t_last
            self.cut.force_start(t)
            self._set_cut_start(t, "manual", self.n_total - 1)
            return {"t": t, "sample": self.cut_start_sample, "source": "manual"}

    def _consume(self) -> None:
        """Consumer thread. Any failure here (a disk error on the raw append, a bad frame...) must
        end the run cleanly: record why, stop the source, and let `_run` reach raw.close(), backup
        stop and finalize, instead of leaving the producer wedged on a full ring while the session
        reads "recording" forever."""
        try:
            self._consume_loop()
        except Exception as e:
            log.exception("session consumer thread failed; stopping the recording")
            self.error = self.error or f"consumer error: {e}"
            self._stop.set()
            self.ring.close()  # producer's next put() returns False instead of waiting
            try:
                self.source.stop()
            except Exception:
                log.exception("source.stop() failed after a consumer error")
            # Free slots so a producer already blocked in put() wakes up now, not after its timeout.
            self.ring.drain()

    def _consume_loop(self) -> None:
        seq = 0
        while True:
            item = self.ring.get()
            if item is None:
                break
            t, data = item
            if t.size == 0:
                continue
            self.raw.append(t, data)  # never dropped — source of truth
            # Published when a channel newly rails, then re-sent every RAIL_REPUBLISH_SEC while
            # any is railed: a slow client's queue drops control messages under backpressure, and
            # this is the one the operator must not miss.
            newly = self.rails.update(data)
            if newly or (
                self.rails.any and time.monotonic() - self._rail_sent > RAIL_REPUBLISH_SEC
            ):
                self._rail_sent = time.monotonic()
                self._publish_control({"type": "railed", "channels": self.rails.railed})
            # The raw file and the rail test above take the volts as acquired; everything the
            # operator watches from here on is in newtons.
            data = self._in_newtons(data)
            axes = sum_axes(data)
            for i, ax in enumerate(("Fx", "Fy", "Fz")):
                self.peaks[i] = max(self.peaks[i], float(np.max(np.abs(axes[ax]))))
            trace = self.decimator.process(t, axes)
            # Per-sub-channel envelopes (the 8 dyno columns, plus any configured Aux/virtual extra)
            # so the client can plot any single sensor live, not just the summed axes.
            extra = self._extra_values(data, axes)
            sub_cols = np.concatenate([data[:, :9], extra], axis=1) if extra.size else data[:, :9]
            sub = self.decimator.process_cols(t, np.asarray(sub_cols, dtype=np.float64))
            # Only what depends on the cut origin is under the lock, so a manual mark (#184) waits
            # for one detect + FRM step, not the whole chunk.
            with self._cut_lock:
                # Causal cut-start detection: reset the FRM spiral origin + tell the UI when it
                # begins. (A manual mark has already flagged the detector, so it stays silent.)
                ct = self.cut.update(t, np.abs(axes["Fz"]))
                if ct is not None:
                    self._set_cut_start(ct, "auto", self.n_total + int(np.searchsorted(t, ct)))
                pts, rpm, tacho_ok = self.frm.process(t, axes, tacho_column(data))
                self.n_total += t.size
                self._t_last = float(t[-1])
            # Only on a transition — this runs per chunk (tens of times a second), and the client
            # only needs to know when the tacho starts or stops being readable.
            if tacho_ok != self._tacho_ok:
                self._tacho_ok = tacho_ok
                self._publish_control({"type": "tacho", "ok": tacho_ok})
            if self.broadcaster is not None:
                frame = encode_frame(
                    seq, self._t_last, rpm, tuple(self.peaks), self.n_total, trace, pts, sub=sub
                )
                self.broadcaster.publish(frame)
            self._update_fft(axes, data)
            seq += 1

    def _update_fft(self, axes: dict, data: np.ndarray) -> None:
        """Maintain per-channel rolling windows and publish their Welch amplitude spectra a few
        times a second (a JSON control message). The client draws a spectrum per selected channel
        and accumulates the frames into the spectrogram/waterfall views — only the current spectra
        cross the wire. `axis` is the configured default axis."""
        if self.broadcaster is None:
            return
        for n in ("Fx", "Fy", "Fz"):
            y = axes.get(n)
            if y is not None:
                self._fft_pending[n].append(y)
        subcols = np.asarray(data[:, :9], dtype=np.float64)
        for j, n in enumerate(SUB_NAMES):
            if j < subcols.shape[1]:
                # A copy, not a view: the source may reuse its chunk buffer.
                self._fft_pending[n].append(subcols[:, j].copy())
        self._fft_pending_n += data.shape[0]
        now = time.perf_counter()
        if now - self._fft_last < 0.3:
            if self._fft_pending_n >= self._fft_cap:  # bound memory if spectra are slow to come due
                self._fold_fft_pending()
            return
        self._fold_fft_pending()
        if self._fft_bufs[self._fft_axis].size < 256:
            return
        self._fft_last = now
        fs = float(self.source.rate)
        # An 8192-sample Welch window once the buffer holds that many samples, else all of it.
        nper = int(min(self._fft_bufs[self._fft_axis].size, FFT_NPERSEG))
        fout, spectra_out = welch_spectra(self._fft_bufs, fs=fs, nperseg=nper)
        if fout is None:
            return
        self._publish_control(
            {
                "type": "fft",
                "fs": fs,
                "f": fout,
                "spectra": spectra_out,
                "axis": self._fft_axis,
            }
        )

    def _fold_fft_pending(self) -> None:
        for n, parts in self._fft_pending.items():
            if parts:
                self._fft_bufs[n] = np.concatenate([self._fft_bufs[n], *parts])[-self._fft_cap :]
                parts.clear()
        self._fft_pending_n = 0

    def _publish_control(self, msg: dict) -> None:
        if self.broadcaster is not None:
            self.broadcaster.publish(json.dumps(msg))

    # ---- status ----
    def status(self) -> dict:
        s = {
            "id": self.id,
            "state": self.state,
            "error": self.error,
            "error_kind": self.error_kind,
            "elapsed_sec": round(self._t_last, 3),
            "n_total": self.n_total,
            "peaks": {"Fx": self.peaks[0], "Fy": self.peaks[1], "Fz": self.peaks[2]},
            "config": self.cfg.model_dump(),
            # None until the first chunk is processed; False => tacho producing no readable pulses.
            "tacho_ok": self._tacho_ok,
            # Indices (0-7, Fx1..Fz4) of the sensor channels that have railed this cut.
            "railed": self.rails.railed,
            # The cut origin the live FRM runs from (None until it starts), so a client that
            # connects or reloads mid-recording knows whether it is still waiting (#184).
            "cut_start_sec": self.cut_started_t,
            "cut_start_source": self.cut_start_source,
        }
        if self.backup:
            s["backup"] = self.backup.status()
        if self.disk_action:
            s["disk_action"] = self.disk_action
        return s
