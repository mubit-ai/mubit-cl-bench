#!/usr/bin/env python3
"""Run the live database-exploration demo.

One command: preflight, install, start Mubit, start the collector, run the real
CL-Bench benchmark, then verify what the screens showed against the harness's
own final artifact.

    python demo/run_demo.py                 # live run (~12 min, real API calls)
    python demo/run_demo.py --dry-run       # preflight and print the command only
    python demo/run_demo.py --replay LATEST # serve a recording, no benchmark

What actually runs is ``clbench run database_exploration --system mubit_demo``.
``mubit_demo`` is ``mubit`` with a wire tap and no behavioural difference, so
the gain this produces is comparable to the committed artifacts. Both arms —
memory on (the rollout) and memory off (the stateless baseline) — are run by
the harness in a single pool; ``--max-workers 2`` is what keeps them advancing
at similar rates so both are genuinely live on screen at the same moment.

Scores are never computed here. The collector digests CL-Bench's own live trace
snapshots, the pages read those, and :func:`verify` checks the result against
the final artifact's ``summary.aggregate``.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import random
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collector as collector_mod  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DEFAULT_CLBENCH = REPO.parent / "continual-learning-bench"
DEFAULT_RICEDB = Path.home() / "Mubit" / "ricedb"

# `database_exploration_fixed` is `database_exploration` with the baseline
# slicing corrected — same questions, same seed, same budget, same grader; see
# demo/tasks/database_exploration_fixed/task.py. Stock, the control never
# receives the migrated database, reports instance_index 0 for every instance,
# and reads "Question 1/1" throughout. The first of those inflates the gain, so
# a number produced here is NOT comparable to the published 13.7%, which was
# measured with the uncorrected control.
TASK = "database_exploration_fixed"
# The corrected task is a subclass registered under its own name, so the harness
# writes its results under that name — but it reads the same databases and
# question pools, and the committed 3-run artifacts this demo compares against
# were produced under the original name. Anything addressing *data* or
# *published results* uses the family; anything addressing *this run* uses TASK.
TASK_FAMILY = "database_exploration"
SCHEDULE = "demo_drift"
SYSTEM = "mubit_demo"
MODEL = "gemini/gemini-2.5-flash"
QUESTIONS = 20
DRIFT_INDEX = 10
MAX_WORKERS = 2
R_MAX = 1.0  # database_exploration; matches scripts/extract.py

RECORDINGS = REPO / "demo" / "recordings"


# ---------------------------------------------------------------------------
# small utilities
# ---------------------------------------------------------------------------


class Fail(Exception):
    """A preflight condition the user has to fix before a run can happen."""


def say(msg: str, kind: str = "") -> None:
    mark = {"ok": "  ✓", "bad": "  ✗", "warn": "  !", "": "   "}[kind]
    print(f"{mark} {msg}", flush=True)


def head(msg: str) -> None:
    print(f"\n\033[1m{msg}\033[0m", flush=True)


def port_open(host: str, port: int, timeout: float = 0.6) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def free_port(preferred: int) -> int:
    if not port_open("127.0.0.1", preferred):
        return preferred
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


# ---------------------------------------------------------------------------
# reference bands
# ---------------------------------------------------------------------------


def _rewards(artifact: Path) -> tuple[list[list[float]], list[float]]:
    """Per-run stateful reward series and the shared baseline series.

    Reward on this task is ``correct ? (budget − queries)/budget : 0`` — graded
    on query efficiency, not binary correctness. That formula was reverse
    engineered and verified elementwise across all five committed database
    artifacts during the analysis pass (see FINDINGS.md §2.5).
    """
    with gzip.open(artifact) as f:
        d = json.load(f)
    baseline = d["summary"]["aggregate"]["baseline_reward_by_index"]
    budget = 15
    runs = []
    for rt in d["run_traces"]:
        metrics = (rt["trace"].get("result") or {}).get("metrics") or {}
        history = metrics.get("question_history") or []
        runs.append(
            [((budget - q["num_queries"]) / budget) if q["correct"] else 0.0 for q in history]
        )
    return runs, baseline


def _correct_counts(artifact: Path) -> dict[str, Any]:
    """How often each arm actually answered correctly in the committed runs.

    Context for the race grid, which is mostly red on both arms and reads like
    a broken display until you know the task: every question is
    ``difficulty: hard`` and a wrong answer scores 0 no matter how efficiently
    it was reached. Read off the artifact rather than typed in, for the same
    reason the gains are.
    """
    with gzip.open(artifact) as f:
        d = json.load(f)
    per_run = []
    for rt in d["run_traces"]:
        metrics = (rt["trace"].get("result") or {}).get("metrics") or {}
        hist = metrics.get("question_history") or []
        per_run.append(sum(1 for q in hist if q.get("correct")))
    outs = d["summary"]["baseline"]["instance_outcomes"]
    return {
        "questions": len(outs),
        "runs": len(per_run),
        "stateful_mean": round(sum(per_run) / len(per_run), 1) if per_run else None,
        "stateless": sum(1 for o in outs if o.get("success")),
    }


def _gain(sf: list[float], sl: list[float]) -> float:
    a = sum(sf) / len(sf)
    b = sum(sl) / len(sl)
    return (a - b) / (R_MAX - b)


def build_reference() -> dict[str, Any]:
    """Both reference bands the race screen sits tonight's number against.

    * ``published`` — the committed 3-run, 40-question result, read from the
      artifact rather than hardcoded so it cannot drift out of agreement.
    * ``bootstrap`` — what a run THIS short is expected to produce, by
      resampling 10 pre-drift + 10 post-drift questions from those same runs.

    The bootstrap's honest caveat, which the page states: it resamples
    questions the committed runs already answered, and it assumes memory built
    over 10 questions helps as much as memory built over 20. It probably helps
    less, so the true distribution likely sits below this band.
    """
    out: dict[str, Any] = {}
    mubit = REPO / "results" / TASK_FAMILY / "mubit-db-3.json.gz"
    icl = REPO / "results" / TASK_FAMILY / "icl-db-3.json.gz"

    if mubit.exists():
        runs, baseline = _rewards(mubit)
        out["published_gain"] = round(sum(_gain(r, baseline) for r in runs) / len(runs), 5)
        out["published_runs"] = len(runs)
        out["published_questions"] = len(baseline)
        out["published_correct"] = _correct_counts(mubit)

        rng = random.Random(7)
        samples = []
        for _ in range(20000):
            r = rng.choice(runs)
            idx = rng.sample(range(0, DRIFT_INDEX * 2), DRIFT_INDEX) + rng.sample(
                range(DRIFT_INDEX * 2, len(baseline)), DRIFT_INDEX
            )
            samples.append(_gain([r[i] for i in idx], [baseline[i] for i in idx]))
        samples.sort()
        q = lambda p: samples[int(p * len(samples))]  # noqa: E731
        out["bootstrap"] = {
            "p05": round(q(0.05), 5),
            "p25": round(q(0.25), 5),
            "p50": round(q(0.50), 5),
            "p75": round(q(0.75), 5),
            "p95": round(q(0.95), 5),
            "p_le_zero": round(sum(1 for s in samples if s <= 0) / len(samples), 5),
            "resamples": len(samples),
            # The run length this band describes, so the page can say "for a
            # run this short" and name the number instead of implying it.
            "questions": DRIFT_INDEX * 2,
            "drift_index": DRIFT_INDEX,
        }

    if icl.exists():
        runs, baseline = _rewards(icl)
        out["icl_gain"] = round(sum(_gain(r, baseline) for r in runs) / len(runs), 5)

    return out


# ---------------------------------------------------------------------------
# preflight
# ---------------------------------------------------------------------------


def preflight(clbench: Path, ricedb: Path) -> dict[str, Any]:
    head("Preflight")
    ctx: dict[str, Any] = {}

    if not (clbench / "src").is_dir():
        raise Fail(f"CL-Bench not found at {clbench} (pass --clbench)")
    say(f"CL-Bench {clbench}", "ok")

    venv_bin = clbench / ".venv" / "bin"
    exe = venv_bin / "clbench"
    if not exe.exists():
        raise Fail(f"clbench entry point missing at {exe} — run `uv sync --all-extras` in {clbench}")
    ctx["clbench_exe"] = exe
    say(f"entry point {exe.name}", "ok")

    data = clbench / "data" / TASK_FAMILY
    if not data.is_dir():
        raise Fail(f"task data missing at {data} — run `clbench setup {TASK_FAMILY}`")
    say(f"task data {data}", "ok")

    env_file = read_env_file(clbench / ".env")
    missing = [k for k in ("GEMINI_API_KEY", "MUBIT_API_KEY") if not env_file.get(k) and not os.environ.get(k)]
    if missing:
        raise Fail(f"missing key(s) in {clbench / '.env'}: {', '.join(missing)}")
    ctx["env_file"] = env_file
    say("GEMINI_API_KEY and MUBIT_API_KEY present", "ok")

    if not port_open("127.0.0.1", 8080):
        raise Fail(
            "embedding service is not answering on 127.0.0.1:8080.\n"
            "  Mubit needs it to embed lessons; start it and re-run."
        )
    say("embedding service on :8080", "ok")

    mubit_bin = ricedb / "target" / "release" / "mubit"
    ctx["mubit_bin"] = mubit_bin if mubit_bin.exists() else None
    if mubit_bin.exists():
        say(f"mubit binary {mubit_bin}", "ok")
    else:
        say(f"no mubit binary at {mubit_bin} — an already-running instance will be required", "warn")

    return ctx


# ---------------------------------------------------------------------------
# Mubit lifecycle
# ---------------------------------------------------------------------------


def start_mubit(ctx: dict[str, Any], port: int, keep_data: bool) -> tuple[Optional[subprocess.Popen], str, Optional[Path]]:
    """Start a Mubit instance on a fresh data directory.

    A fresh directory is the point: the store screen has to begin empty, and a
    demo that inherits yesterday's lessons is not showing memory being built.
    If something is already listening on the port, that instance is adopted and
    left alone — this script does not kill a server it did not start.
    """
    head("Mubit")
    endpoint = f"http://127.0.0.1:{port}"

    if port_open("127.0.0.1", port):
        say(f"adopting the instance already listening on :{port} (not managed by this script)", "warn")
        say("the store screen may show entries from earlier runs", "warn")
        return None, endpoint, None

    binary = ctx.get("mubit_bin")
    if binary is None:
        raise Fail(f"nothing is listening on :{port} and no mubit binary was found to start one")

    api_key = ctx["env_file"].get("MUBIT_API_KEY") or os.environ["MUBIT_API_KEY"]
    parts = api_key.split("_")
    if len(parts) < 4 or parts[0] != "mbt":
        raise Fail("MUBIT_API_KEY is not in the expected mbt_<instance_tag>_<key_id>_<secret> form")
    instance_id = parts[1]

    data_dir = Path(f"/tmp/mubit-demo-{int(time.time())}")
    data_dir.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env.update(
        {
            # The bootstrap key must be the same credential the benchmark will
            # present, and the instance id must match its tag or auth rejects it.
            "MUBIT_BOOTSTRAP_ADMIN_API_KEY": api_key,
            "MUBIT_INSTANCE_ID": instance_id,
            "MUBIT_CORE_EMBEDDING_SERVICE_URL": "http://127.0.0.1:8080",
        }
    )
    RECORDINGS.mkdir(parents=True, exist_ok=True)
    log_path = RECORDINGS / "mubit.log"
    log = log_path.open("w", encoding="utf-8")

    # The runtime binds gRPC as well as HTTP and treats a failed gRPC bind as
    # fatal, so a stray instance holding the default 50051 would take this one
    # down a few seconds after its HTTP port started answering — which looks
    # exactly like a healthy start followed by mysterious connection refusals.
    # The SDK is pinned to HTTP transport, so any free port will do.
    grpc_port = free_port(50051)
    if grpc_port != 50051:
        say(f"gRPC 50051 is taken; using :{grpc_port} instead", "warn")

    proc = subprocess.Popen(
        [
            str(binary),
            "--http-port", str(port),
            "--grpc-port", str(grpc_port),
            "--data-dir", str(data_dir),
        ],
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )

    for _ in range(90):
        if proc.poll() is not None:
            raise Fail(f"mubit exited during startup (rc={proc.returncode}); see {log_path}")
        if port_open("127.0.0.1", port):
            break
        time.sleep(0.4)
    else:
        proc.terminate()
        raise Fail(f"mubit did not come up on :{port} within 36s")

    # Answering TCP is not the same as staying up. Settle, then confirm the
    # process is alive AND that an authenticated call actually round-trips —
    # the smoke run that motivated this check passed a bare port probe and then
    # died on a late gRPC bind failure, taking every remember() with it.
    time.sleep(1.5)
    if proc.poll() is not None:
        raise Fail(f"mubit exited {proc.returncode} just after binding :{port}; see {log_path}")
    try:
        req = urllib.request.Request(
            f"{endpoint}/v2/control/recall",
            data=json.dumps({"query": "startup probe", "limit": 1}).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=8).close()
    except urllib.error.HTTPError as exc:
        # A 4xx means the server is up and talking; only auth failure matters.
        if exc.code in (401, 403):
            raise Fail(f"mubit rejected MUBIT_API_KEY (HTTP {exc.code}) for instance '{instance_id}'")
    except Exception as exc:
        raise Fail(f"mubit is not answering on {endpoint}: {exc}")

    say(f"started on :{port}, instance '{instance_id}', fresh data dir {data_dir}", "ok")
    return proc, endpoint, (None if keep_data else data_dir)


# ---------------------------------------------------------------------------
# verification
# ---------------------------------------------------------------------------


def _latest_artifact(clbench: Path, run_group_id: str) -> Optional[Path]:
    root = clbench / "results" / TASK
    matches = sorted(root.glob(f"*{run_group_id}*.json.gz"), key=lambda p: p.stat().st_mtime)
    return matches[-1] if matches else None


def verify(recording: Path, artifact: Optional[Path], expected_questions: int = QUESTIONS) -> bool:
    """Cross-check what the screens showed against the harness's final artifact.

    The pages derive their gain from ``harness.snapshot`` events, which are
    digests of CL-Bench's own live traces. This recomputes the same arithmetic
    from the recording and compares it to the number the harness itself wrote
    at the end. A MISMATCH means the demo displayed something the benchmark
    does not agree with, which is the only failure worth gating on.
    """
    head("Verification")
    if artifact is None:
        say("no final artifact found — cannot verify", "bad")
        return False

    snapshots: dict[str, dict] = {}
    with recording.open(encoding="utf-8") as f:
        for line in f:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "harness.snapshot":
                p = ev.get("payload") or {}
                snapshots["stateless" if p.get("phase") == "baseline" else "stateful"] = p

    if len(snapshots) < 2:
        say(f"recording has snapshots for {sorted(snapshots) or 'no'} arm(s) — need both", "bad")
        return False

    def rewards(p: dict) -> dict[str, float]:
        """Map instance_id → reward.

        Keyed on ``instance_id``, not ``instance_index``: the baseline runs each
        instance against a task sliced to that one question, so every baseline
        outcome reports ``instance_index: 0``. Pairing on the index would
        collapse the whole control arm onto a single question and quietly
        compare one baseline result against twenty stateful ones.
        """
        return {
            str(o["instance_id"]): o["reward"]
            for o in p.get("outcomes") or []
            if o.get("instance_id") is not None and o.get("reward") is not None
        }

    sf, sl = rewards(snapshots["stateful"]), rewards(snapshots["stateless"])
    paired = sorted(set(sf) & set(sl))
    if not paired:
        say("no question was scored on both arms", "bad")
        return False
    shown = _gain([sf[i] for i in paired], [sl[i] for i in paired])

    with gzip.open(artifact) as f:
        final = json.load(f)
    agg = (final.get("summary") or {}).get("aggregate") or {}
    official = agg.get("final_cumulative_mean_gain")

    say(f"artifact          {artifact.name}")
    say(f"questions paired  {len(paired)} of {expected_questions}")
    say(f"gain shown        {shown * 100:.2f}%")
    if official is None:
        say("artifact carries no final_cumulative_mean_gain — nothing to compare against", "bad")
        return False
    say(f"gain in artifact  {official * 100:.2f}%")

    delta = abs(shown - official)
    if delta <= 5e-3:
        say(f"PASS — agree to {delta * 100:.3f} percentage points", "ok")
        return True
    say(f"MISMATCH — differ by {delta * 100:.3f} percentage points", "bad")
    say("the screens showed a number the harness does not agree with; do not present this run", "bad")
    return False


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def hold(server=None, hub=None) -> None:
    """Block until Ctrl-C, keeping the pages served.

    Not ``signal.pause()``: that returns as soon as ANY handled signal
    arrives, and tearing down Mubit and the benchmark's process group
    immediately beforehand generates exactly such signals — so the process
    printed "pages stay up" and then exited. ``time.sleep`` retries across
    interruptions since PEP 475, so this only ends on KeyboardInterrupt.
    """
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        if server is not None:
            server.shutdown()
        if hub is not None:
            hub.close()


def resolve_replay(value: str) -> Path:
    if value.upper() == "LATEST":
        files = sorted(RECORDINGS.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
        if not files:
            raise Fail(f"no recordings in {RECORDINGS}")
        return files[-1]
    # A bare filename means a recording; the "replay it" hint printed at the
    # end of a run is exactly that, so it has to resolve here or the hint is
    # a command that does not work.
    for candidate in (Path(value), RECORDINGS / value, REPO / value):
        if candidate.is_absolute() and candidate.exists():
            return candidate
        if not candidate.is_absolute() and (REPO / candidate).exists():
            return REPO / candidate
        if candidate.exists():
            return candidate
    raise Fail(
        f"recording not found: {value}\n"
        f"  looked in {RECORDINGS} and {REPO}\n"
        f"  available: {', '.join(p.name for p in sorted(RECORDINGS.glob('*.jsonl'))) or 'none'}"
    )


def serve_pages(
    recording: Optional[Path],
    live_dir: Optional[Path],
    port: int,
    run_group: Optional[str] = None,
):
    server, hub, _ = collector_mod.serve(
        root=REPO,
        recording=recording or (RECORDINGS / "scratch.jsonl"),
        live_dir=live_dir,
        port=port,
        run_group=run_group,
    )
    return server, hub


def terminate_group(proc: subprocess.Popen) -> None:
    """Kill the benchmark and everything it spawned.

    ``clbench`` runs its instances in a ProcessPoolExecutor, and those workers
    are spawned with their own command lines — killing or pkill-ing the parent
    leaves them reparented to init, still running the OLD configuration and
    still posting events. Observed directly: orphans from an interrupted
    40-question run contaminated the next 20-question recording, and the only
    visible symptom was two different totals in the prompts.

    The child is started with ``start_new_session=True`` so it leads its own
    process group; signalling the group takes the workers with it.
    """
    if proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        proc.terminate()
    try:
        proc.wait(timeout=15)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        proc.kill()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clbench", default=str(DEFAULT_CLBENCH))
    ap.add_argument("--ricedb", default=str(DEFAULT_RICEDB))
    ap.add_argument("--port", type=int, default=8799, help="collector / page server port")
    ap.add_argument("--mubit-port", type=int, default=3320)
    ap.add_argument("--max-workers", type=int, default=MAX_WORKERS)
    ap.add_argument("--replay", metavar="PATH|LATEST", help="serve a recording instead of running")
    ap.add_argument(
        "--smoke",
        type=int,
        metavar="N",
        default=0,
        help="wiring check: run the `smoke` schedule with N questions and no migration "
        "(~1 min, a few API calls) to prove the rig end to end before presenting",
    )
    ap.add_argument("--dry-run", action="store_true", help="preflight, then print the command")
    ap.add_argument("--keep-mubit-data", action="store_true", help="do not delete the temp data dir")
    ap.add_argument(
        "--no-hold",
        action="store_true",
        help="exit after verification instead of keeping the pages served (for scripted checks)",
    )
    args = ap.parse_args()

    clbench = Path(args.clbench).expanduser().resolve()
    RECORDINGS.mkdir(parents=True, exist_ok=True)

    try:
        # -- replay: pages only, no benchmark, no Mubit, no API spend --------
        if args.replay:
            recording = resolve_replay(args.replay)
            port = free_port(args.port)
            serve_pages(None, None, port)
            url = f"http://127.0.0.1:{port}/demo/web/index.html?replay=/demo/recordings/{recording.name}&speed=4"
            head("Replay")
            say(f"recording {recording.name} ({recording.stat().st_size // 1024} KB)", "ok")
            print(f"\n    {url}\n")
            print("    Ctrl-C to stop.", flush=True)
            hold()
            return 0

        ctx = preflight(clbench, Path(args.ricedb).expanduser().resolve())

        head("Install")
        sys.path.insert(0, str(REPO / "demo"))
        import install as install_mod

        if install_mod.install(clbench, dry_run=args.dry_run) != 0:
            return 2

        # Smoke mode swaps in the stock single-stage schedule. It has no
        # migration, so drift_index is reported as null rather than as a
        # sentinel number — the pages read null as "no migration in this run"
        # and label every question pre-migration, instead of printing
        # "migration lands before question 1000000".
        smoke = args.smoke > 0
        schedule = "smoke" if smoke else SCHEDULE
        questions = args.smoke if smoke else QUESTIONS
        drift_index = None if smoke else DRIFT_INDEX

        run_group_id = f"{'smoke' if smoke else 'demo'}-{time.strftime('%Y%m%d-%H%M%S')}"
        live_dir = clbench / "results" / TASK / "live" / run_group_id
        recording = RECORDINGS / f"{run_group_id}.jsonl"
        port = free_port(args.port)

        cmd = [
            str(ctx["clbench_exe"]), "run", TASK,
            "--task.schedule", schedule,
            "--system", SYSTEM,
            "--system.model", MODEL,
            "--runs", "1",
            "--max-workers", str(args.max_workers),
            "--live-dashboard", "--no-live-server",
            "--run-group-id", run_group_id,
        ]
        if smoke:
            cmd += ["--task.num-questions", str(questions)]

        if args.dry_run:
            head("Dry run")
            say(f"cwd  {clbench}")
            say(f"cmd  {' '.join(cmd)}")
            say(f"live {live_dir}")
            reference = build_reference()
            say(f"reference {json.dumps(reference)}")
            return 0

        mubit_proc, endpoint, temp_data = start_mubit(ctx, args.mubit_port, args.keep_mubit_data)

        head("Collector")
        server, hub = serve_pages(recording, live_dir, port, run_group=run_group_id)
        say(f"http://127.0.0.1:{port}  recording → {recording.name}", "ok")

        reference = build_reference()
        hub.publish(
            {
                "type": "run.config",
                "payload": {
                    "run_group_id": run_group_id,
                    "task": TASK,
                    "schedule": schedule,
                    "system": SYSTEM,
                    "model": MODEL,
                    "runs": 1,
                    "questions": questions,
                    "drift_index": drift_index,
                    "has_migration": not smoke,
                    "smoke": smoke,
                    "max_workers": args.max_workers,
                    "mubit_endpoint": endpoint,
                    "started_at": time.time(),
                    **reference,
                },
            }
        )

        print(f"\n    Open  http://127.0.0.1:{port}/demo/web/index.html\n", flush=True)

        head("Benchmark")
        env = dict(os.environ)
        env.update(
            {
                "MUBIT_DEMO_COLLECTOR": f"http://127.0.0.1:{port}",
                "MUBIT_DEMO_RUN_GROUP": run_group_id,
                "MUBIT_DEMO_DRIFT_INDEX": str(drift_index if drift_index is not None else 10**9),
                "MUBIT_ENDPOINT": endpoint,
            }
        )
        for key in ("GEMINI_API_KEY", "MUBIT_API_KEY"):
            if ctx["env_file"].get(key):
                env[key] = ctx["env_file"][key]

        started = time.time()
        proc = subprocess.Popen(cmd, cwd=clbench, env=env, start_new_session=True)
        try:
            rc = proc.wait()
        except KeyboardInterrupt:
            say("interrupted — stopping the benchmark and its workers", "warn")
            terminate_group(proc)
            rc = proc.returncode if proc.returncode is not None else 130
        finally:
            # Even on a clean exit: a worker that outlives its parent would
            # keep posting into whatever collector comes next.
            terminate_group(proc)
        elapsed = time.time() - started
        say(f"clbench exited rc={rc} after {elapsed / 60:.1f} min", "ok" if rc == 0 else "bad")

        hub.publish({"type": "run.finished", "payload": {"rc": rc, "elapsed_seconds": round(elapsed, 1)}})
        time.sleep(_SETTLE_SECONDS)  # let the snapshot watcher pick up the final write

        ok = verify(recording, _latest_artifact(clbench, run_group_id), questions)

        if mubit_proc is not None:
            mubit_proc.terminate()
            try:
                mubit_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                mubit_proc.kill()
            say("mubit stopped", "ok")
        if temp_data is not None and temp_data.exists():
            shutil.rmtree(temp_data, ignore_errors=True)

        head("Done")
        say(f"recording  {recording}")
        say(f"replay it  python demo/run_demo.py --replay {recording.name}")
        print(
            f"\n    Pages stay up at http://127.0.0.1:{port}/demo/web/index.html — Ctrl-C to stop.\n",
            flush=True,
        )
        if args.no_hold:
            server.shutdown()
            hub.close()
        else:
            hold(server, hub)
        return 0 if (rc == 0 and ok) else 1

    except Fail as exc:
        print(f"\n\033[31mpreflight failed\033[0m\n  {exc}\n", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


_SETTLE_SECONDS = 2.5


if __name__ == "__main__":
    raise SystemExit(main())
