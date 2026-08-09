# Mubit on CL-Bench

Benchmarking [Mubit](https://github.com/mubit-ai/ricedb) as an assistive memory system on the [Continual Learning Bench (CL-Bench)](https://github.com/pgasawa/continual-learning-bench) — the expert-validated benchmark that measures whether AI agents genuinely improve through sequential experience.

CL-Bench's central question: **does an agent do better on later tasks because it learned from earlier ones?** The paper's headline finding is that dedicated memory systems (Mem0, ACE, ICL Notepad) all *underperform* naive in-context learning. Mubit is the exception.

## Results

### Exploitable Poker — quick_test (5 hands, 3 runs)

| System | Normalized gain | Stateful reward | Stateless reward | Per-run gains |
|---|---|---|---|---|
| **Mubit** | **7.5%** | −0.03 | −0.80 | +4.0, +3.5, +4.0 |
| ICL | 1.7% | −0.43 | −0.60 | +1.0, +2.0, −0.5 |

### Database Exploration — default (40 questions, schema drift at Q20, 3 runs)

| System | Normalized gain | Stateful reward | Stateless reward | Per-run gains |
|---|---|---|---|---|
| **Mubit** | **13.7%** | 0.18 | 0.05 | +6.2, +2.9, +6.5 |
| Mubit + reinforcement | 11.8% | 0.18 | 0.07 | +6.0, +4.9, +2.3 |
| ICL | 11.4% | 0.14 | 0.03 | +3.1, +5.7, +4.4 |

### Key findings

1. **Mubit beats ICL on both tasks** — the only memory system to do so. The paper found that Mem0, ACE, and ICL Notepad all lose to plain ICL. Mubit doesn't.

2. **Mubit adapts to concept drift.** Database Exploration introduces a schema migration halfway through (tables renamed, columns reformatted). Mubit's gain is *higher after the drift* (post-migration +0.148 vs pre-migration +0.112 per question) — it detects stale beliefs and re-learns. The paper identifies this as the critical open problem for memory systems.

3. **Zero negative-gain runs.** Mem0 and ACE frequently hurt performance with stale beliefs (ACE showed "virtually no stable learning"; Mem0 had negative gain on poker). Mubit never went negative across all experiments.

### Comparison to other memory systems

The paper's central finding: dedicated memory systems don't beat ICL.

| Memory system | Beats ICL? | Notes |
|---|---|---|
| **Mubit** | **Yes** | Higher gain and higher reward on both tasks |
| Mem0 | No | Tied on gain, lower reward |
| ACE | No | Worst gain, highest cost ($62.8/run) |
| ICL Notepad | No | Lower gain than plain ICL |

---

## Repository structure

```
mubit-cl-bench/
├── systems/
│   ├── mubit/              # Core Mubit memory system (lessons + retrieval injection)
│   │   ├── __init__.py
│   │   └── system.py
│   ├── mubit_full/         # + record_outcome reinforcement + reflect()
│   │   ├── __init__.py
│   │   └── system.py
│   └── mubit_genai/        # + native Google genai structured outputs (gemini-3.5-flash)
│       ├── __init__.py
│       └── system.py
├── results/
│   ├── exploitable_poker/   # Viewer artifact JSON.gz files
│   │   ├── mubit-quick-3.json.gz
│   │   └── icl-quick-3.json.gz
│   └── database_exploration/
│       ├── mubit-db-3.json.gz
│       ├── mubit-full-db-3.json.gz
│       ├── icl-db-3.json.gz
│       └── mubit-genai-db-3.json.gz
├── scripts/
│   └── analyze_results.py   # Reproduce the results table from the artifacts
├── LICENSE
└── README.md
```

---

## How Mubit works as a CL-Bench system

Each Mubit system is a subclass of CL-Bench's `ContinualLearningSystem`. The core loop:

1. **Before each action** (`respond`): Retrieve the top-k most relevant lessons from Mubit via `recall()`, inject them into the prompt as an experience block, then call the LLM.

2. **After each completed instance** (`observe`): Distill the turn into a lesson (prompt + action + outcome) and store it via `remember()` with `intent="lesson"`, keyed by opponent/stage so memory converges rather than duplicates.

3. **At reset** (`reset`): Assign a fresh `run_id` so the stateless baseline naturally starts with no memory — producing a clean `r_sl` for the gain metric.

### Three variants

| System | Memory mechanism | LLM backend |
|---|---|---|
| `mubit` | Lesson storage + semantic retrieval | LiteLLM (any model) |
| `mubit_full` | + `record_outcome()` reinforcement + periodic `reflect()` | LiteLLM (any model) |
| `mubit_genai` | Same memory as `mubit` | Native `google-genai` SDK with `response_schema` |

`mubit_genai` uses Google's native structured-output API instead of LiteLLM's text-parsing fallback. This eliminates the JSON parsing failures that Gemini models hit on long rollouts with the standard CL-Bench harness.

---

## Prerequisites

1. **Python 3.13+** and [uv](https://github.com/astral-sh/uv)
2. **CL-Bench** cloned and installed:
   ```bash
   git clone https://github.com/pgasawa/continual-learning-bench
   cd continual-learning-bench
   uv sync --all-extras
   ```
3. **A running Mubit instance** (local or hosted). See the [Mubit docs](https://github.com/mubit-ai/ricedb) for setup.
4. **An LLM API key** (Gemini, OpenAI, or Anthropic).

---

## Reproduction guide

### Step 1: Install the Mubit systems into CL-Bench

Copy the three system packages from this repo into the CL-Bench source tree:

```bash
CLBENCH=/path/to/continual-learning-bench

cp -r systems/mubit       $CLBENCH/src/systems/
cp -r systems/mubit_full  $CLBENCH/src/systems/
cp -r systems/mubit_genai $CLBENCH/src/systems/
```

### Step 2: Install the Mubit Python SDK

```bash
cd $CLBENCH
uv pip install -e /path/to/ricedb/sdk/python/mubit-sdk
```

### Step 3: Configure environment

Create a `.env` in the CL-Bench root:

```bash
GEMINI_API_KEY=your-gemini-key          # or OPENAI_API_KEY / ANTHROPIC_API_KEY
MUBIT_API_KEY=your-mubit-api-key         # e.g. mbt_local_<key_id>_<secret>
MUBIT_ENDPOINT=http://127.0.0.1:3320     # your Mubit instance URL
```

### Step 4: Set up task data

```bash
cd $CLBENCH
clbench setup --all                      # downloads task data (databases, etc.)
# or per-task:
clbench setup database_exploration
```

### Step 5: Validate the systems are registered

```bash
clbench list                              # mubit, mubit_full, mubit_genai should appear
clbench validate system mubit
clbench validate system mubit_genai
```

### Step 6: Run the benchmarks

```bash
# Exploitable Poker (quick_test, 5 hands)
clbench run exploitable_poker \
  --schedule quick_test \
  --system mubit \
  --system.model gemini/gemini-2.5-flash \
  --runs 3 --max-workers 6 \
  --run-group-id mubit-poker

# ICL baseline (same model, same schedule)
clbench run exploitable_poker \
  --schedule quick_test \
  --system icl \
  --system.model gemini/gemini-2.5-flash \
  --runs 3 --max-workers 6 \
  --run-group-id icl-poker

# Database Exploration (40 questions, schema drift)
clbench run database_exploration \
  --task.schedule default \
  --system mubit \
  --system.model gemini/gemini-2.5-flash \
  --runs 3 --max-workers 6 \
  --run-group-id mubit-db

# ICL baseline
clbench run database_exploration \
  --task.schedule default \
  --system icl \
  --system.model gemini/gemini-2.5-flash \
  --runs 3 --max-workers 6 \
  --run-group-id icl-db
```

The harness automatically runs the stateless baseline and computes gain (`r_sf − r_sl`) per instance, then normalizes it.

### Step 7: Using native Gemini structured outputs (recommended for Gemini models)

The CL-Bench harness disables `response_format` for Gemini models (line 140-141 of `src/systems/utils/structured_output.py`), falling back to text-parsing that fails on long rollouts. To use Google's native structured-output API instead:

```bash
clbench run database_exploration \
  --task.schedule default \
  --system mubit_genai \
  --system.model gemini-3.5-flash \
  --runs 3 --max-workers 1 \
  --run-group-id mubit-genai-db
```

> **Note:** `mubit_genai` sets `parallel_safe = False` because the `google-genai` HTTP client doesn't survive `ProcessPoolExecutor` forks. Use `--max-workers 1` (sequential execution).

### Step 8: Analyze results

```bash
# From this repo:
python scripts/analyze_results.py

# Or read the viewer artifacts directly:
python -c "
import json, gzip
with gzip.open('results/database_exploration/mubit-db-3.json.gz') as f:
    d = json.load(f)
agg = d['summary']['aggregate']
print('normalized gain:', agg.get('final_cumulative_mean_gain'))
print('mean gain by index:', agg.get('mean_gain_by_index'))
"
```

---

## CL-Bench metric: gain

The benchmark's key metric is **normalized gain** (g_b):

```
g_b = (r̄_sf − r̄_sl) / (r_max − r̄_sl)
```

Where:
- `r̄_sf` = mean reward when the system accumulates experience across instances (stateful)
- `r̄_sl` = mean reward when the system sees each instance independently (stateless baseline)
- `r_max` = maximum achievable reward for the task

Gain isolates **learning from experience** from base-model capability. A memory system that helps will show positive gain; one that hurts (stale beliefs, spurious generalizations) shows negative gain.

---

## Running a local Mubit instance

```bash
# Clone Mubit
git clone https://github.com/mubit-ai/ricedb
cd ricedb

# Build
cargo build --release

# Start with a known admin key and embedding service
export MUBIT_BOOTSTRAP_ADMIN_API_KEY="mbt_local_mykey01_<32+ hex chars>"
export MUBIT_CORE_EMBEDDING_SERVICE_URL=http://127.0.0.1:8080

./target/release/mubit --http-port 3320 --data-dir /tmp/mubit-clbench
```

The key format is `mbt_<instance_tag>_<key_id>_<secret>`. The instance tag must match the runtime's instance ID (defaults to `local`).

---

## Citation

If you use this work, please cite:

- **CL-Bench**: Asawa et al., "Continual Learning Bench: Evaluating Frontier AI Systems in Real-World Stateful Environments." arXiv:2606.05661, 2026.
- **Mubit**: The Mubit cognitive memory system for agentic AI.

## License

MIT
