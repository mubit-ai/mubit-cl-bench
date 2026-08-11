#!/usr/bin/env python3
"""Event collector for the live database demo.

Three jobs, one process, stdlib only:

1. **Ingest.** ``POST /event`` accepts a JSON event from any benchmark worker
   process, stamps it with a global sequence number and appends it to a JSONL
   recording.
2. **Fan out.** ``GET /stream`` is a Server-Sent Events endpoint. A client that
   connects mid-run is sent the entire backlog first and then joins live, so a
   page opened at question 14 shows the first thirteen too.
3. **Watch the harness.** A poller digests CL-Bench's own live trace snapshots
   and injects them into the same stream as ``harness.snapshot`` events. Every
   score the demo displays originates here, from the harness's own files —
   nothing on any screen is a reward this process computed.

The recording is the complete record: the ``run.config`` event carries the
schedule, the drift index and the reference bands, so replaying the JSONL alone
reproduces the demo with no other input.

Design constraints worth stating, because they are load-bearing:

* Ingest must never block a benchmark worker. The handler appends and returns;
  fan-out happens on the subscriber's own thread and a slow or dead subscriber
  is dropped rather than back-pressured.
* Static files are served from the repository root so the demo pages can share
  ``viz/chart.js`` and ``viz/style.css`` rather than forking them.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

# A subscriber this far behind is not going to catch up; dropping it protects
# ingest latency, which matters more than one stalled browser tab.
_SUBSCRIBER_BACKLOG = 2048
_SNAPSHOT_POLL_SECONDS = 1.0


class Hub:
    """Sequenced event log with SSE fan-out."""

    def __init__(self, recording_path: Path, run_group: Optional[str] = None) -> None:
        self.recording_path = recording_path
        self.recording_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.recording_path.open("a", encoding="utf-8")
        self._lock = threading.Lock()
        self._history: list[dict] = []
        self._subscribers: list[queue.Queue] = []
        self._gseq = 0
        # Events tagged with a different run are refused. A killed benchmark
        # leaves worker processes reparented to init — they keep running the
        # OLD configuration and keep posting, and their events are otherwise
        # indistinguishable from the current run's. Observed in practice: a
        # 40-question orphan contaminated a 20-question recording.
        self.expected_group = run_group
        self.rejected = 0

    def publish(self, event: dict) -> dict:
        with self._lock:
            self._gseq += 1
            event["gseq"] = self._gseq
            event.setdefault("ts", time.time())
            line = json.dumps(event, default=str)
            self._fh.write(line + "\n")
            self._fh.flush()
            self._history.append(event)
            subscribers = list(self._subscribers)
        for q in subscribers:
            try:
                q.put_nowait(event)
            except queue.Full:
                self.unsubscribe(q)
        return event

    def subscribe(self) -> tuple[queue.Queue, list[dict]]:
        q: queue.Queue = queue.Queue(maxsize=_SUBSCRIBER_BACKLOG)
        with self._lock:
            backlog = list(self._history)
            self._subscribers.append(q)
        return q, backlog

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Harness snapshot digest
# ---------------------------------------------------------------------------


def digest_snapshot(trace: dict) -> dict:
    """Reduce a CL-Bench live trace to what the race screen needs.

    Defensive by intent: a partial snapshot is a genuinely partial document,
    and a field that is not there yet must read as absent rather than as zero.
    """
    result = trace.get("result") or {}
    metrics = result.get("metrics") or {}
    outcomes = []
    for o in result.get("instance_outcomes") or trace.get("instance_outcomes") or []:
        if not isinstance(o, dict):
            continue
        # metadata / cost / latency are carried deliberately. The baseline
        # trace has no question_history at all, so the per-instance outcome is
        # the ONLY place the memory-off arm's query count, cost and latency
        # exist — dropping them would leave half of every comparison blank.
        outcomes.append(
            {
                "instance_index": o.get("instance_index"),
                "instance_id": o.get("instance_id"),
                "reward": o.get("reward"),
                "success": o.get("success"),
                "metadata": o.get("metadata") or {},
                "cost_usd": o.get("cost_usd"),
                "latency_seconds": o.get("latency_seconds"),
                "raw_metric_name": o.get("raw_metric_name"),
                "raw_metric_value": o.get("raw_metric_value"),
            }
        )
    questions = []
    for q in metrics.get("question_history") or []:
        if not isinstance(q, dict):
            continue
        questions.append(
            {
                "question_id": q.get("question_id"),
                "correct": q.get("correct"),
                "num_queries": q.get("num_queries"),
                "difficulty": q.get("difficulty"),
                "timed_out": q.get("timed_out"),
                "budget_exceeded": q.get("budget_exceeded"),
            }
        )
    execution = trace.get("execution") or {}
    return {
        "phase": trace.get("phase"),
        "status": trace.get("status"),
        "outcomes": outcomes,
        "questions": questions,
        "eval_metrics": result.get("eval_metrics"),
        "usage": execution.get("usage"),
        "total_interactions": execution.get("total_interactions"),
    }


class SnapshotWatcher(threading.Thread):
    """Poll the harness's live snapshot directory and republish changes."""

    def __init__(self, hub: Hub, live_dir: Path) -> None:
        super().__init__(name="snapshot-watcher", daemon=True)
        self.hub = hub
        self.live_dir = live_dir
        self._seen: dict[str, float] = {}
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.wait(_SNAPSHOT_POLL_SECONDS):
            try:
                if not self.live_dir.exists():
                    continue
                for path in sorted(self.live_dir.glob("*.json")):
                    try:
                        mtime = path.stat().st_mtime
                    except OSError:
                        continue
                    if self._seen.get(path.name) == mtime:
                        continue
                    try:
                        trace = json.loads(path.read_text(encoding="utf-8"))
                    except (json.JSONDecodeError, OSError):
                        # Mid-write or manifest, not a trace — try again next tick.
                        continue
                    self._seen[path.name] = mtime
                    if path.name == "manifest.json":
                        self.hub.publish(
                            {"type": "harness.manifest", "payload": trace, "source": path.name}
                        )
                        continue
                    self.hub.publish(
                        {
                            "type": "harness.snapshot",
                            "source": path.name,
                            "payload": digest_snapshot(trace),
                        }
                    )
            except Exception:
                # A watcher fault must not take the collector down.
                continue


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


class Handler(SimpleHTTPRequestHandler):
    hub: Hub = None  # type: ignore[assignment]
    root: Path = None  # type: ignore[assignment]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(type(self).root), **kwargs)

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A002
        return

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        super().end_headers()

    # -- ingest -------------------------------------------------------------

    def do_POST(self) -> None:  # noqa: N802
        if self.path.rstrip("/") != "/event":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            event = json.loads(raw.decode("utf-8"))
            if not isinstance(event, dict):
                raise ValueError("event must be an object")
        except Exception as exc:
            self.send_response(400)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(f"bad event: {exc}".encode())
            return
        hub = type(self).hub
        group = event.get("run_group")
        if hub.expected_group and group and group != hub.expected_group:
            hub.rejected += 1
            if hub.rejected in (1, 10, 100):
                print(
                    f"collector: refused {hub.rejected} event(s) from run '{group}' "
                    f"(this collector serves '{hub.expected_group}') — "
                    "an orphaned worker from an earlier run is still alive",
                    flush=True,
                )
            self.send_response(409)
            self.end_headers()
            return
        hub.publish(event)
        self.send_response(204)
        self.end_headers()

    # -- fan-out ------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path == "/stream":
            self._stream()
            return
        if path == "/health":
            self._json({"ok": True, "events": type(self).hub._gseq})
            return
        super().do_GET()

    def _json(self, obj: Any) -> None:
        body = json.dumps(obj, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _stream(self) -> None:
        hub = type(self).hub
        q, backlog = hub.subscribe()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            for event in backlog:
                self._send_event(event)
            # Tells the page the replay of history is done and it is now live.
            self._send_raw("event: caught-up\ndata: {}\n\n")
            while True:
                try:
                    event = q.get(timeout=15.0)
                except queue.Empty:
                    self._send_raw(": keepalive\n\n")
                    continue
                self._send_event(event)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            hub.unsubscribe(q)

    def _send_event(self, event: dict) -> None:
        self._send_raw(f"id: {event.get('gseq')}\ndata: {json.dumps(event, default=str)}\n\n")

    def _send_raw(self, text: str) -> None:
        self.wfile.write(text.encode("utf-8"))
        self.wfile.flush()


def serve(
    *,
    root: Path,
    recording: Path,
    live_dir: Optional[Path],
    host: str = "127.0.0.1",
    port: int = 8799,
    run_group: Optional[str] = None,
) -> tuple[ThreadingHTTPServer, Hub, Optional[SnapshotWatcher]]:
    hub = Hub(recording, run_group=run_group)
    handler = type("BoundHandler", (Handler,), {"hub": hub, "root": root})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    watcher = None
    if live_dir is not None:
        watcher = SnapshotWatcher(hub, live_dir)
        watcher.start()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, hub, watcher


def main() -> None:
    ap = argparse.ArgumentParser(description="Live demo event collector.")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--recording", required=True)
    ap.add_argument("--live-dir", default=None)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--run-group", default=None)
    args = ap.parse_args()

    server, hub, _ = serve(
        root=Path(args.root),
        recording=Path(args.recording),
        live_dir=Path(args.live_dir) if args.live_dir else None,
        host=args.host,
        port=args.port,
        run_group=args.run_group,
    )
    print(f"collector on http://{args.host}:{args.port}  recording={args.recording}")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        hub.close()


if __name__ == "__main__":
    main()
