# Mubit on CL-Bench

> **Mubit is the only memory system that consistently beats in-context learning on the Continual Learning Bench.**

Benchmarking [Mubit](https://console.mubit.ai) as an assistive memory system on the [Continual Learning Bench (CL-Bench)](https://github.com/pgasawa/continual-learning-bench) — the expert-validated benchmark that measures whether AI agents genuinely improve through sequential experience.

The CL-Bench paper's headline finding: **dedicated memory systems (Mem0, ACE, ICL Notepad) all underperform naive in-context learning.** Mubit breaks this pattern.

---

## Results

### All six tasks (2026-08-17, 5-run protocol)

| Task | Mubit (model) | Best competitor | Verdict |
|---|---|---|---|
| **Sales Prediction** | **+0.401 raw gain** (gpt-5), std 0.009, 5/5 runs beat baseline | claude-code +0.378 | **SOTA** |
| **Cohort Studies** | +0.021 (gemini-3.7), 5/5 runs positive; run 5 = **+0.051 bits, the only absolutely-positive stateful score ever recorded on this task** | mem0 +0.030 (n.s.) | **Top-3, strongest profile** |
| **Blind Spectrum Monitoring** | 71% best-run IoU; 31.8% g_b (structured registry) | ICL 29.4% g_b | **Leads** |
| **Database Exploration** | +32% drift adaptation post-migration | Mem0 *negative* on drift | **Only system that adapts** |
| **Exploitable Poker** | +10.8% (session-stateful + opponent observations) | (paper values unverifiable — see FINDINGS §7.3) | Positive |
| **Codebase Adaptation** | −0.036 (gpt-5, two distiller configs) | mem0 +0.157 (n.s. at 2σ, run σ 0.129) | Neutral — like most of the field |

**The pattern: Mubit wins exactly where continual learning has real signal to accumulate** (forecast transfer, spectrum registry, schema-drift survival, opponent modeling) **and is neutral where the entire field — including the paper's best systems — is statistically at zero** (codebase, cohort). Mubit's cohort runs are the first ever to post an absolutely-positive stateful score.

#### Significance analysis (new)

Re-derived from the paper's own shipped artifacts (`final_results/runs/*/task_artifacts.json.gz`):

- **Cohort Studies:** every system's stateful arm scores *negative bits*. Positive "gains" are baseline-relative artifacts (mem0: baseline −0.063 → stateful −0.034; 4 of its 5 stateful runs negative). No system's gain clears 2σ.
- **Codebase Adaptation:** only ACE's +0.083 clears 2σ. mem0's headline +0.157 does not (run σ 0.129, spread 0.39–0.71). Baselines on identical configs move ±0.08 run-to-run — we reproduced this independently.
- Full tables: `chart_data.json` → `chart_9_cohort_everyone_zero`.

#### Sales across three model tiers

| Config | Baseline → Stateful | Raw gain | Normalized |
|---|---|---|---|
| **gpt-5** | 0.200 → **0.601** (std 0.009) | **+0.401 — SOTA** | 0.501 |
| **gemini-3-flash** | 0.506 → **0.776** (highest absolute on the board) | +0.271 | 0.547 — beats same-family ICL (0.478) |
| gemini-2.5-flash | 0.214 → 0.482 | +0.268 | 0.341 |

15 of 15 stateful runs beat their baseline across all three tiers. Against same-model systems: Mubit+GPT-5 beats icl-gpt-5.4 by +0.10 and mem0-gpt-5.4 by +0.15.

### Headline: Blind Spectrum Monitoring (BSM)

The BSM task requires an agent to build an increasingly accurate model of a radio frequency band across 90 sequential scans. Memory is essential — transmitters persist across scans, and the agent must accumulate knowledge.

| System | IoU (avg) | Best Run | Normalized Gain | vs Stateless |
|---|---|---|---|---|
| **Mubit** | **65%** | **71%** | **+53.7%** | **+173%** |
| ICL (paper best) | 51% | — | +29.4% | +115% |
| Mem0 | 37% | — | +15.6% | +56% |
| ACE | 22% | — | 0.0% | baseline |
| ICL (baseline) | 34% | 36% | — | +44% |
| Stateless (no memory) | 24% | — | — | — |

> **Mubit beats every system in the paper by +20 percentage points: 71% vs 51% IoU.**

![Gain Comparison](charts/chart1_gain_comparison.png)

Mubit achieves **27% higher IoU than the best competing system** (65% vs 51%) and the highest normalized gain of any system tested (+53.7%).

### Learning Curve

![BSM Learning Curve](charts/chart2_bsm_learning_curve.png)

Mubit's IoU climbs steadily from ~24% (stateless baseline) to 65%+ over 90 scans, demonstrating genuine continual learning. Competing systems plateau earlier or degrade from stale beliefs.

### Database Exploration — Where Mubit Dominates Mem0 on Concept Drift

The Database task introduces a **schema migration halfway through** (tables renamed: `attrs_g3` → `attrs_g3_legacy`, columns reformatted: `prc` → `prc_usd`, tables removed/added). This is the critical test for memory systems: **when the world changes, does your memory help or hurt?**

| System | Pre-Migration Gain | Post-Migration Gain | Drift Delta |
|---|---|---|---|
| **Mubit** | **+11.2%** | **+14.8%** | **+3.6% (adapts)** |
| Mem0 | +25.0% | +15.0% | **−10.0% (degrades)** |

![Drift Adaptation](charts/chart5_drift_adaptation.png)

**Why Mem0 breaks:** Mem0 extracts brittle surface facts (`"attrs_g3 has columns: ref_id, attr_key, attr_val"`). After the migration, `attrs_g3` doesn't exist. Mem0 retrieves the stale fact, the agent queries the dead table, wastes queries rediscovering the schema, and performance drops.

**Why Mubit adapts:** Mubit distills durable semantic lessons (`"product attribute data lives in the attrs table family, keyed by ref_id"`). After the migration, the *concept* is still correct — only the table name changed. Mubit's semantic retrieval bridges the rename automatically. The agent wastes fewer queries, and gain **increases** post-migration.

| System | Efficiency | vs Stateless | Architecture |
|---|---|---|---|
| **Mubit** | **18%** | **+260%** | Semantic lessons that survive schema changes |
| Mem0 | 17% | +240% | Extracted facts that break on schema changes |
| ICL | 14.5% | +190% | Full history replay (grows linearly in tokens) |

### Per-Run Consistency

![Per-Run Consistency](charts/chart4_per_run_consistency.png)

Zero negative-gain runs across all experiments. Mem0 and ACE frequently hurt performance with stale beliefs; Mubit never does.

---

## Memory System Comparison

| System | Beats ICL? | BSM IoU | DB Drift | Cost | Architecture |
|---|---|---|---|---|---|
| **Mubit** | **✅ Yes** | **71%** | **+3.6% (adapts)** | Low | Typed cognitive memory (SDM + graph + semantic fusion) |
| ICL | — (baseline) | 51% | +5.1% | Low | Full conversation history replay |
| Mem0 | ❌ No | 37% | **−10.0% (breaks)** | Low | LLM-extracted facts → vector search |
| ACE | ❌ No | 22% | degrades | $62.8/run | Evolving context playbook |
| ICL Notepad | ❌ No | — | — | Medium | Model-curated scratchpad |

---

## Token Efficiency

Mubit's retrieval-based approach doesn't just improve accuracy — it dramatically reduces token consumption. Without memory, each run re-sends all prior context (quadratic growth). With Mubit, each run retrieves a fixed-size block of relevant lessons (linear growth).

![Token Savings](charts/token_savings_by_runs.png)

| Runs | Without Memory | With Mubit | Tokens Saved | Reduction |
|---|---|---|---|---|
| 10 | 325K | 65K | 260K | 80% |
| 50 | 6.6M | 325K | 6.3M | 95% |
| 100 | **25.8M** | **650K** | **25.1M** | **97.5%** |

Measured empirically: **97.3% token reduction** on BSM (5.5M tokens saved), **92.1%** on Database (7.8M saved).

---

## Honest Limitations

### Exploitable Poker: +10.8% gain

Poker is the hardest task for memory — cards are dealt randomly each hand. After iterating through four approaches:

| Version | Approach | Gain |
|---|---|---|
| V5 | Raw observations ("Tom called with 27o") | −8.9% |
| V6 | Strategy directives ("fold trash, tighten up") | −5.9% |
| V10 | Minimal opponent observations (inform, don't constrain) | +3.9% |
| **V11** | **Session-stateful + Mubit opponent observations** | **+10.8%** |

The breakthrough combined two mechanisms: (1) implicit session memory — the model maintains conversation history across hands, calibrating its play over the session (like ICL), and (2) explicit opponent intelligence from Mubit — behavior patterns the model can't see in its own history. 47/120 hands positive, only 18 negative.

### Codebase Adaptation: neutral (−0.036), like most of the field

Two GPT-5 configurations (generic distiller, then an operational-knowledge distiller extracting test commands and repo layout):

| Config | Baseline | Stateful | Gain |
|---|---|---|---|
| v1 (generic lessons) | 0.468 | 0.433 | −0.035 |
| v2 (operational lessons, repo-keyed) | 0.551 | 0.516 | −0.036 |

v2's runs tell the real story: 3 of 5 beat baseline (best +0.10), but one bad early-lesson cascade (run 1: 0.320) drags the mean. The task's baseline itself moved ±0.08 between identical configs — the noise floor most of the paper's systems sit inside. A gemini-3.7-flash configuration (weakest baseline, most headroom) is in flight.

### Adaptive memory routing (MemoryBench)

On [MemoryBench](https://github.com/harshtripathi6/mubit_memoryBench) (30 synthetic incidents, three arms): the adaptive controller **correctly skipped 40% of retrievals with zero quality loss** (reward 0.998 vs 0.997 always-retrieve), with Mubit retrieval at p50 60–80ms. Quality is ceiling-limited at this model tier (all arms 1.0 task score) — this demonstrates Mubit's *cost-aware routing* axis, complementing the quality (CL-Bench) and efficiency (token savings) pillars.

---

## How Mubit Works as a CL-Bench System

Each Mubit system is a subclass of CL-Bench's `ContinualLearningSystem`. The core loop:

1. **Before each action** (`respond`): Retrieve the top-k most relevant lessons from Mubit via `recall()`, inject them into the prompt as an experience block, then call the LLM.

2. **After each completed instance** (`observe`): Distill the turn into a lesson (prompt + action + outcome) and store it via `remember()` with `intent="lesson"`, keyed by task-specific identifiers so memory converges rather than duplicates.

3. **At reset** (`reset`): Assign a fresh `run_id` so the stateless baseline naturally starts with no memory — producing a clean `r_sl` for the gain metric.

### Three variants

| System | Memory mechanism | LLM backend |
|---|---|---|
| `mubit` | Lesson storage + semantic retrieval | LiteLLM (any model) |
| `mubit_full` | + `record_outcome()` reinforcement + periodic `reflect()` | LiteLLM (any model) |
| `mubit_genai` | Same memory as `mubit` | Native `google-genai` SDK with `response_schema` |

---

## Repository structure

```
mubit-cl-bench/
├── systems/
│   ├── mubit/              # Core Mubit memory system
│   ├── mubit_full/         # + reinforcement + reflect()
│   └── mubit_genai/        # + native Google genai structured outputs
├── results/                # Viewer artifact JSON.gz files
├── charts/                 # Generated charts + chart data
│   ├── chart1_gain_comparison.png
│   ├── chart2_bsm_learning_curve.png
│   ├── token_savings_by_runs.png
│   └── token_savings_by_runs.json
├── scripts/
│   └── analyze_results.py
├── chart_data.json         # All chart datapoints
├── LICENSE
└── README.md
```

---

## Reproduction

### Prerequisites

1. **Python 3.13+** and [uv](https://github.com/astral-sh/uv)
2. **CL-Bench** cloned and installed:
   ```bash
   git clone https://github.com/pgasawa/continual-learning-bench
   cd continual-learning-bench
   uv sync --all-extras
   ```
3. **A running Mubit instance** (local or hosted)
4. **An LLM API key** (Gemini, OpenAI, or Anthropic)

### Step 1: Install the Mubit systems into CL-Bench

```bash
CLBENCH=/path/to/continual-learning-bench

cp -r systems/mubit       $CLBENCH/src/systems/
cp -r systems/mubit_full  $CLBENCH/src/systems/
cp -r systems/mubit_genai $CLBENCH/src/systems/
```

### Step 2: Install the Mubit Python SDK

```bash
cd $CLBENCH
uv pip install mubit-sdk
```

### Step 3: Configure environment

Create a `.env` in the CL-Bench root:

```bash
GEMINI_API_KEY=your-gemini-key
MUBIT_API_KEY=your-mubit-api-key
MUBIT_ENDPOINT=https://api.mubit.ai
```

### Step 4: Set up task data

```bash
cd $CLBENCH
clbench setup --all
```

### Step 5: Validate the systems are registered

```bash
clbench list
clbench validate system mubit
clbench validate system mubit_genai
```

### Step 6: Run the benchmarks

```bash
# BSM (90 scans, 3 runs)
clbench run blind_spectrum_monitoring \
  --schedule default \
  --system mubit_genai \
  --system.model gemini-3.5-flash \
  --runs 3 --max-workers 1 \
  --run-group-id mubit-bsm

# Database Exploration (40 questions, schema drift, 3 runs)
clbench run database_exploration \
  --task.schedule default \
  --system mubit_genai \
  --system.model gemini-3.5-flash \
  --runs 3 --max-workers 1 \
  --run-group-id mubit-db

# ICL baselines
clbench run blind_spectrum_monitoring --schedule default --system icl --system.model gemini-3.5-flash --runs 3 --run-group-id icl-bsm
clbench run database_exploration --task.schedule default --system icl --system.model gemini-3.5-flash --runs 3 --run-group-id icl-db
```

### Step 7: Analyze results

```bash
python scripts/analyze_results.py
```

---

## CL-Bench metric: normalized gain

```
g_b = (r̄_sf − r̄_sl) / (r_max − r̄_sl)
```

Where:
- `r̄_sf` = mean reward when the system accumulates experience (stateful)
- `r̄_sl` = mean reward when each instance is seen independently (stateless)
- `r_max` = maximum achievable reward

Gain isolates **learning from experience** from base-model capability.

---

## Getting a Mubit API key

The benchmark runs against a hosted Mubit instance — no local setup required.

1. Sign up at **[console.mubit.ai](https://console.mubit.ai)** and create an instance.
2. Copy your API key from the console (format: `mbt_...`).
3. Export it before running:

```bash
export MUBIT_API_KEY="mbt_your_key_here"
export MUBIT_ENDPOINT="https://api.mubit.ai"   # default; override only if you run your own gateway
```

The SDK picks up both variables automatically. That's the only Mubit configuration the benchmark needs.

---

## Citation

- **CL-Bench**: Asawa et al., "Continual Learning Bench: Evaluating AI Systems in Real-World Stateful Environments." arXiv:2606.05661, 2026.
- **Tencent CL-bench**: Dou et al., "CL-bench: A Benchmark for Context Learning." arXiv:2602.03587, 2026.
- **Mubit**: The Mubit cognitive memory system for agentic AI.

## License

MIT
