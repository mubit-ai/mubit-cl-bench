# Live database demo

A real CL-Bench run on `database_exploration`, instrumented so you can watch what
Mubit is asked for and what it gives back while the agent works.

Twenty questions: ten on the original schema, a live schema migration, then ten
on the new one. The stateless baseline runs alongside as the control, so every
screen shows memory ON and memory OFF answering the same question at the same
moment.

```bash
python demo/run_demo.py                  # the demo — ~12 min, real API calls
python demo/run_demo.py --smoke 2        # wiring check — ~1 min, a few calls
python demo/run_demo.py --dry-run        # preflight only, nothing runs
python demo/run_demo.py --replay LATEST  # replay a recording, no API spend
```

Then open the URL it prints: `http://127.0.0.1:8799/demo/web/index.html`.

---

## What actually runs

```
clbench run database_exploration \
  --task.schedule demo_drift --system mubit_demo \
  --system.model gemini/gemini-2.5-flash \
  --runs 1 --max-workers 2 \
  --live-dashboard --no-live-server
```

The real harness, unmodified. `run_demo.py` only sets it up, watches it, and
checks the result afterwards.

**`mubit_demo` is `systems/mubit` with a wire tap and no behavioural
difference.** Same retrieval key, same lesson text, same `upsert_key`, same
metadata — including the known warts, which the demo shows deliberately rather
than hiding:

| | |
|---|---|
| retrieval key | no `database` branch in `_build_retrieval_key` → the raw question prompt, truncated to 300 chars |
| lesson text | no `database` branch in `_distill_lesson_text` → `"Prior instance feedback: {feedback[:200]}. My action: {action[:200]}"` |
| `metadata["task"]` | hardcoded `"exploitable_poker"` on every write, database lessons included |
| `upsert_key` | `lesson:{instance_id}` — unique per question, so lessons accumulate and never converge |

That is the code path that produced the committed 13.7% result. Changing it to
look better would make the live number incomparable to the published one, so it
is left alone.

`--max-workers 2` is deliberate. The stateful rollout is one long job and the
baseline is twenty short ones; at the default pool width the baseline sprints
ahead and finishes before the stateful arm reaches question three, which would
leave half of every screen showing a recording next to a live run. Two workers
keeps the arms advancing together. Instances are independent, so scoring is
unaffected.

---

## The four screens

| | |
|---|---|
| **Race** | Memory on versus memory off, question by question, against the published result and the range a run this short is expected to produce. The verdict screen. |
| **Turn theatre** | One question end to end on both arms: the task prompt, the block Mubit injected in front of it, every SQL query, the rows that came back, the answer, the verdict. |
| **Mubit I/O** | Every `recall()` and every `remember()`, unedited, in order, with payloads, scores and latencies. |
| **Store** | What has accumulated: each lesson, when it was written, how often it has been retrieved since, and which entries describe a schema that no longer exists. |

All four subscribe to the same event stream, so open as many as you have
monitors, or use **Tile all four** on the index for a single screen-share.

---

## Where the numbers come from

**Nothing on any screen recomputes a reward.** The collector polls CL-Bench's
own live trace snapshots, digests them, and injects them into the stream as
`harness.snapshot` events. Correctness, query counts and per-question rewards
are read from those; the pages do arithmetic on them (means, normalized gain)
and nothing else.

After the run, `verify()` recomputes the displayed gain from the recording and
compares it to `summary.aggregate.final_cumulative_mean_gain` in the harness's
final artifact. It prints **PASS** or **MISMATCH**. A mismatch means the screens
showed something the benchmark does not agree with — don't present that run.

### One run is one run

Twenty questions, n=1. Bootstrapping a run this short from the three committed
runs puts the median at 14.2%, the 90% interval at 2.1%–23.6%, and P(gain ≤ 0)
at 2.5%. Both reference bands are drawn on the race screen for exactly this
reason. The bootstrap's own caveat: it resamples questions the committed runs
already answered, and assumes memory built over ten questions helps as much as
memory built over twenty — it probably helps less, so the true distribution
likely sits below that band.

---

## Architecture

```
clbench (subprocess)
  └─ worker processes
       └─ mubit_demo ──POST /event──┐
                                    ▼
CL-Bench live snapshots ──poll──► collector.py ──SSE /stream──► the four pages
                                    │
                                    └──► demo/recordings/<run>.jsonl
```

The recording is self-contained — `run.config` carries the schedule, the drift
index and both reference bands — so replaying the JSONL reproduces the demo with
no other input, no Mubit, and no API spend.

Event shape:

```
{ts, gseq, seq, type, arm, emitter, pid, mubit_run_id,
 instance_index, instance_id, stage, turn, payload}
```

`type` ∈ `run.config` · `system.ready` · `system.reset` · `instance.start` ·
`stage.change` · `turn.start` · `recall.request` · `recall.response` ·
`prompt.injected` · `llm.response` · `env.feedback` · `lesson.distilled` ·
`remember.request` · `remember.response` · `instance.end` ·
`harness.snapshot` · `harness.manifest` · `run.finished`

### Two traps this code exists to avoid

**The stateless arm cannot number its own questions.** CL-Bench runs each
baseline instance against a task *sliced to that one instance*, so the sliced
task reports `instance_index: 0` for whichever question it holds — every
stateless event and every baseline outcome claims index 0. Only `instance_id`
distinguishes them. Keying on the index that is right there in the event would
pile the entire control arm onto question 0, and it would look completely
plausible. `demo.js` resolves position through an `instance_id → index` map
learned from the stateful arm, parks stateless events that arrive before their
mapping is known, and raises a banner on all four pages if position and mapping
ever disagree.

**The system is told nothing about which arm it is in.** `phase` reaches the
trace recorder but never the system, and both arms are constructed with
identical `system_params`. The worker pool also reuses processes across arms, so
PID proves nothing. `_detect_arm()` reads the call stack instead: the baseline
builds its system inside `_run_baseline_instance`, the rollout inside
`run_single`. If CL-Bench ever renames those, it degrades to `"unknown"` rather
than guessing.

---

## Install

`demo/install.py` copies three things into the CL-Bench checkout, all as files
CL-Bench itself does not own:

```
systems/mubit/                 → $CLBENCH/src/systems/mubit/
systems/mubit_demo/            → $CLBENCH/src/systems/mubit_demo/
demo/schedules/demo_drift.json → $CLBENCH/src/tasks/database_exploration/schedules/
```

`systems/mubit` is synced deliberately. A checkout can be carrying an older
generation of that file; the version in this repo is the one whose constructor
signature and `mubit_run_id` metadata match the committed viewer artifacts. If
the demo ran against a different parent it would no longer be the measured
system, and the comparison to the published gain would be void — silently. A
differing copy is reported before it is replaced.

`run_demo.py` runs the install itself, so you rarely need to call it directly.

---

## Requirements

- CL-Bench checked out with `.venv` built and `data/database_exploration` fetched
- `.env` in the CL-Bench root with `GEMINI_API_KEY` and `MUBIT_API_KEY`
- The embedding service answering on `127.0.0.1:8080`
- A built Mubit binary at `ricedb/target/release/mubit`

`run_demo.py` checks all of these before spending anything and names whichever
one is missing.

Mubit is started on a **fresh temp data directory** so the store screen begins
empty, with `MUBIT_INSTANCE_ID` set from the API key's instance tag, and is shut
down afterwards. If something is already listening on the port, that instance is
adopted and left alone — the script does not kill a server it did not start, and
warns that the store may show entries from earlier runs.

## Troubleshooting

**`gRPC server failed: transport error`, then connection refused.** Something
else holds port 50051. The runtime treats a failed gRPC bind as fatal a few
seconds *after* HTTP starts answering, which looks like a healthy start followed
by inexplicable failures. `run_demo.py` picks a free gRPC port and probes the
HTTP API after a settle delay, so this should not recur — but if you start Mubit
by hand, pass `--grpc-port`.

**Everything scores 0.** Normal for a 2-question smoke; the questions are drawn
`difficulty: hard` and reward is graded on query efficiency, so a wrong answer
scores exactly zero regardless of effort.

**Pages blank in tiled mode.** Browsers cap connections per origin at six on
HTTP/1.1. The index drops its own stream when tiling for this reason; opening
more than four framed pages at once will starve them.

## Cost

The 2-question smoke cost **$0.016** across 16 model calls. A full demo run is
roughly 380 calls across both arms — expect well under a dollar at
`gemini-2.5-flash` rates. `clbench` prints the exact figure at the end.
