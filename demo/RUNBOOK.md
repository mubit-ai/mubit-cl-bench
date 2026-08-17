# Live database demo — runbook

Every command in the order you need it. One real CL-Bench run: 10 questions on
the original schema, a live migration, then 10 on the new one — with the
stateless baseline running alongside as the control.

| | |
|---|---|
| wall clock | 13.0 min |
| model spend | ~$0.47 |
| questions | 20 (10 + migration + 10) |
| model | `gemini/gemini-2.5-flash` |
| pages on | `127.0.0.1:8799` |

---

## The whole thing, if you are in a hurry

Preflight spends nothing and names whatever is missing. If it passes, the second
command is the demo.

```bash
cd ~/Mubit/Benchmarking/mubit-cl-bench
python3 demo/run_demo.py --dry-run
python3 demo/run_demo.py
```

Then open the URL it prints. Everything below is the same thing, slower and with
the reasons.

---

## Before the first run

Four things have to be true. `--dry-run` checks all four and tells you which one
is not, so you never discover it 40 seconds into a paid run.

- **CL-Bench checked out** at `~/Mubit/Benchmarking/continual-learning-bench`,
  with `.venv` built and `data/database_exploration` fetched.
- **Keys in its `.env`** — `GEMINI_API_KEY` and `MUBIT_API_KEY`.
- **The embedding service answering** on `127.0.0.1:8080`. Mubit needs it to
  embed lessons; without it the run starts and then fails.
- **A Mubit API key** from [console.mubit.ai](https://console.mubit.ai) (the demo talks to the hosted instance). If it is
  missing, an already-running Mubit is adopted instead.

---

## Running it

### 1. Preflight — free, seconds

Checks the four requirements, syncs the demo's files into the CL-Bench checkout,
prints the exact `clbench` command it would run, and stops.

```bash
cd ~/Mubit/Benchmarking/mubit-cl-bench
python3 demo/run_demo.py --dry-run
```

### 2. Smoke test — ~1 min, $0.016

Two questions, end to end, through the real harness. Run this before presenting:
it proves Mubit starts, the collector streams and the pages fill. Expect both
questions to score 0 — see [why almost everything is red](#reading-the-result).

```bash
python3 demo/run_demo.py --smoke 2
```

### 3. The demo — 13 min, ~$0.47

The full 10 + migration + 10. It prints the page URL within a few seconds and
keeps serving after the benchmark finishes, so the screens stay up for questions.

```bash
python3 demo/run_demo.py
```

Leave the terminal visible. It ends with a verification gate that recomputes the
displayed gain from the recording and compares it to the harness's own artifact.

### 4. Watch it

```
http://127.0.0.1:8799/demo/web/index.html
```

All four screens tiled for a single share:

```
http://127.0.0.1:8799/demo/web/index.html?tile=1
```

### 5. Replay it — free, no API calls

Every run is recorded to `demo/recordings/`. A replay needs no Mubit, no keys and
no network — and it has speed control and a jump to the migration.

```bash
python3 demo/run_demo.py --replay LATEST
```

```bash
python3 demo/run_demo.py --replay demo-20260811-205341.jsonl
```

### Stopping

```bash
pkill -f run_demo.py
```

Ctrl-C in the terminal does the same thing and shuts Mubit down cleanly.

---

## The four screens

| Screen | What it answers | Worth showing |
|---|---|---|
| `race.html` | Does memory help? Question by question, against the published result and the range a run this short produces by chance. | The gain curve crossing the migration. |
| `turn.html` | One question on both arms, turn by turn on the same row — the injected block, every query, the answer submitted and the answer expected. Under the prompt, exactly how the two arms' copies of it differ. | **Chip 10**, the first question after the migration (it labels itself *question 11 of 20*). The memory arm's prompt opens with the `NOTICE:` paragraph and the baseline's does not — the delta strip flags it in amber. |
| `ledger.html` | Every `recall()` and every `remember()`, unedited, in order, with payloads and latencies. | A recall returning six candidates with their scores. |
| `store.html` | What has accumulated, how often each entry is retrieved, and which entries describe a schema that no longer exists. | The step chart climbing past the migration line. |

Each opens on its own at `http://127.0.0.1:8799/demo/web/<name>.html`. Open as
many as you have monitors — but not more than four at once, since browsers cap
connections per origin at six.

---

## Jumping straight to a moment

Any page accepts replay parameters, so you can open a screen already at the
migration and running at 16×. Paste this into a browser while a replay server is
up:

```
http://127.0.0.1:8799/demo/web/turn.html?replay=/demo/recordings/demo-20260811-205341.jsonl&speed=16&from=migration
```

`speed` takes 1, 4 or 16; drop `from=migration` to start at question 0. The same
parameters work on all four pages.

---

## Flags

| Flag | Default | What it does |
|---|---|---|
| `--dry-run` | — | Preflight, print the command, stop. Spends nothing. |
| `--smoke N` | — | Run N questions with no migration. |
| `--replay PATH\|LATEST` | — | Serve a recording instead of running. Bare filenames resolve against `demo/recordings/`. |
| `--port` | `8799` | Collector and page server port. |
| `--mubit-port` | `3320` | Mubit HTTP port. The gRPC port is picked free automatically. |
| `--max-workers` | `2` | Keeps both arms advancing together. Raising it makes the baseline finish before the memory arm reaches question three. |
| `--clbench PATH` | `../continual-learning-bench` | The CL-Bench checkout to run. |
| `--mubit-endpoint URL` | `https://api.mubit.ai` | Hosted Mubit endpoint. |
| `--keep-mubit-data` | off | Keep the temp Mubit data directory after the run. |
| `--no-hold` | off | Exit after verification instead of keeping the pages served. |

---

## Reading the result

The run ends with a gate. This is the line that matters:

```
questions paired  20 of 20
gain shown        4.33%
gain in artifact  4.33%
✓ PASS — agree to 0.000 percentage points
```

**MISMATCH** means the screens showed something the benchmark does not agree
with. Do not present that run.

**Almost every cell is red, and that is the task, not a bug.** Every question in
the pool is `difficulty: hard`, and grading is all-or-nothing — integers exact,
floats within 1%, text exact. Reward is `(15 − queries) / 15` when correct and
**0** when not, so a near miss scores the same as no answer. For scale, the
committed 3-run result on this same system averages **12.7 of 40** correct with
memory and **6 of 40** without. The verdict row on the turn screen prints the
submitted answer beside the expected one, so any red cell can be checked rather
than taken on faith.

**Your number is not comparable to the published 13.7%, and that is deliberate.**
The demo runs `database_exploration_fixed`, which repairs a CL-Bench defect that
left the stateless control answering every post-migration question against the
*pre-migration* database — where the data required to answer is simply absent
(the reference SQL for 19 of the 20 post-drift questions errors outright on it).
That depressed the control and inflated the gain across the whole post-migration
half. The published 13.7% was measured before the fix and is biased high, so
expect a corrected run to land **below** the reference tiles and the bootstrap
band. The race screen labels them accordingly. Detail:
[UPSTREAM_ISSUE_baseline_slicing.md](../UPSTREAM_ISSUE_baseline_slicing.md).

**One run is one run.** Twenty questions, n = 1. The published 13.7% is the mean
of three runs of forty. The shaded band on the gain curve is the range a run this
short produces by chance alone — a live number inside that band is noise, not a
result.

---

## If something goes wrong

**Pages are blank, or the terminal says the port is in use.** Something is
already on 8799 — most likely a demo server from earlier.

```bash
lsof -i :8799
pkill -f run_demo.py
```

**`gRPC server failed: transport error`, then connection refused.** Something
else holds Mubit's gRPC port. The runtime treats a failed bind as fatal a few
seconds *after* HTTP starts answering, which looks like a healthy start followed
by inexplicable failures. `run_demo.py` picks a free port and probes the API
before launching the benchmark, so this should not recur — if you start Mubit by
hand, pass `--grpc-port`.

**Prompts read "/40" instead of "/20".** Workers from a killed run survived and
are posting to the collector. Their events are rejected by run-group stamping,
but clear them anyway.

```bash
pkill -f clbench
```

**The embedding service is not answering.** Preflight fails on
`127.0.0.1:8080`. Start it and re-run — nothing has been spent at that point.

**The baseline's recall key says `Question 1/1`.** You are replaying a recording
made before the fix. Stock CL-Bench slices the baseline task to one instance, so
its copy of the prompt was headed 1 of 1 on every question and the retrieval key
— `prompt[:300]` — carried that along. `database_exploration_fixed` corrects it;
a fresh run shows the same header on both arms. Old recordings still replay,
they just show what they recorded.

**A wall of `ConnectionResetError` tracebacks in the terminal.** Fixed — the
collector now swallows the disconnect family, which is what a closed SSE stream
or one of Chrome's speculative connections looks like. If you still see them,
your checkout predates that change; `git pull`. Any *other* traceback is real
and still prints.

---

Full detail — architecture, the three traps the code exists to avoid, and what
the first run actually produced — is in [README.md](README.md). The demo runs
`systems/mubit` unchanged; `mubit_demo` adds a pass-through wire tap and nothing
else, which is the only reason its gain is comparable to the published one.

The CL-Bench defects found while building this — the broken post-migration
control, the `1/1` counter, and baseline instances all reporting
`instance_index: 0` — are written up with a runnable repro and a proposed patch
in [UPSTREAM_ISSUE_baseline_slicing.md](../UPSTREAM_ISSUE_baseline_slicing.md).
Not filed yet.
