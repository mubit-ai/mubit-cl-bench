# Demo Data Report — Mubit on CL-Bench

**Audit date:** 2026-08-11
**Repo:** `/Users/eldaru/Mubit/Benchmarking/mubit-cl-bench` @ `40bccc6`
**Scope:** exhaustive inventory of `results/*/*.json.gz`, `chart_data.json`, `charts/*.png`, `scripts/`, plus demo visual/UI recommendations.

Every number in this document was extracted from the actual files. Nothing is invented. Where a number is *not* derivable from the repo, it is explicitly marked **[NOT IN REPO]**.

---

## 0. Executive summary

**What exists:** 12 gzipped CL-Bench "viewer artifact" files (9.6 MB compressed) spanning 3 tasks, containing **11,835 fully-recorded agent interactions**. Each interaction stores the complete prompt, the structured action, the environment observation, per-call latency, per-call token usage, and — critically — **the verbatim text of the memory entries Mubit retrieved for that step**. Rich per-instance ground-truth structures exist for all three tasks.

**Headline capability for a demo:** you can build a *full agent replay* UI (step-by-step prompt → retrieved memory → action → outcome) plus a *spectrum-occupancy visualizer* with ground truth, entirely from data already on disk. No new collection needed.

**Biggest risk:** three of the repo's most eye-catching published numbers do not survive scrutiny. See §7. In particular the **BSM +53.7%** headline is driven almost entirely by the *stateless baseline collapsing*, not by the stateful system improving, and the BSM system prompt hardcodes the task's ground-truth grid geometry.

---

## 1. File inventory

| Task | File | Size (gz) | System | Model | Runs | Instances | Stored interactions* |
|---|---|---|---|---|---|---|---|
| blind_spectrum_monitoring | `mubit-bsm-3.5flash.json.gz` | 429,863 B | `mubit_genai` | gemini-3.5-flash | 3 | 90 | 360 |
| blind_spectrum_monitoring | `mubit-bsm-registry-3.5flash.json.gz` | 344,515 B | `mubit_bsm` | gemini-3.5-flash | 3 | 90 | 360 |
| blind_spectrum_monitoring | `mubit-bsm-v4-3.5flash.json.gz` | 333,449 B | `mubit_bsm` | gemini-3.5-flash | 3 | 90 | 360 |
| database_exploration | `icl-db-3.json.gz` | 668,553 B | `icl` | gemini/gemini-2.5-flash | 3 | 40 | 946 |
| database_exploration | `mubit-db-3.json.gz` | 1,087,266 B | `mubit` | gemini/gemini-2.5-flash | 3 | 40 | 1,391 |
| database_exploration | `mubit-full-db-3.json.gz` | 1,028,949 B | `mubit_full` | gemini/gemini-2.5-flash | 3 | 40 | 1,432 |
| database_exploration | `mubit-genai-db-3.json.gz` | 1,889,330 B | `mubit_genai` | gemini-3.5-flash | 3 | 40 | 2,332 |
| database_exploration | `mubit-genai-db-full-3.5flash.json.gz` | 1,873,643 B | `mubit_genai` | gemini-3.5-flash | 3 | 40 | 2,345 |
| exploitable_poker | `icl-quick-3.json.gz` | 74,972 B | `icl` | gemini/gemini-2.5-flash | 3 | 5 | 59 |
| exploitable_poker | `mubit-quick-3.json.gz` | 69,979 B | `mubit` | gemini/gemini-2.5-flash | 3 | 5 | 60 |
| exploitable_poker | `mubit-poker-full-3.5flash.json.gz` | 1,115,283 B | `mubit_genai` | gemini-3.5-flash | 3 | 120 | 1,066 |
| exploitable_poker | `mubit-poker-v5-3.5flash.json.gz` | 699,693 B | `mubit_genai` | gemini-3.5-flash | 3 | 120 | 1,124 |

\* sum of `run_traces[*].trace.interactions` + `baseline_trace.interactions`. **Total: 11,835.**

### Directly comparable artifact sets

Comparability requires same task **and** same schedule **and** same model. Grouping:

| Comparison group | Members | Valid head-to-head? |
|---|---|---|
| **DB, `default` schedule, gemini-2.5-flash** | `icl-db-3`, `mubit-db-3`, `mubit-full-db-3` | **Yes — this is the cleanest head-to-head in the repo.** Same task params (seed 42, 40 instances), same model, 3 runs each. |
| DB, `default`, gemini-3.5-flash | `mubit-genai-db-3`, `mubit-genai-db-full-3.5flash` | Yes vs each other. **No ICL counterpart at this model** — so no baseline comparison. |
| Poker, `quick_test`, gemini-2.5-flash | `icl-quick-3`, `mubit-quick-3` | Yes, but n=5 instances. Too small to claim anything (see §7). |
| Poker, `default` (120 hands), gemini-3.5-flash | `mubit-poker-full-3.5flash`, `mubit-poker-v5-3.5flash` | Yes vs each other. **No ICL counterpart** at 120 hands. |
| BSM, `default`, gemini-3.5-flash | `mubit-bsm-3.5flash` (v1), `mubit-bsm-registry-3.5flash` (v2), `mubit-bsm-v4-3.5flash` (v4) | **Only partly.** Different *adapters*, and the adapter changes the baseline too — see §7.1. **No ICL counterpart at all.** |

**Critical gap:** there is **no ICL baseline artifact for blind_spectrum_monitoring** and **none for the 120-hand poker schedule**. Every ICL comparison in `chart_data.json` for those tasks comes from the paper, not from this repo.

---

## 2. Full schema tree

All 12 files share one schema. Root: `{"kind": "viewer_artifact", "summary": {...}, "baseline_trace": {...}, "run_traces": [...]}`.

### 2.1 `$.summary` (18 keys)

```
$: dict[4] keys=['kind', 'summary', 'baseline_trace', 'run_traces']
  kind: str = 'viewer_artifact'
  summary: dict[18]
    run_group_id: str = 'mubit-quick-3'
    status: str = 'completed'
    system: dict[3]
      name: str = 'mubit'
      params: dict[4] keys=['model', 'top_k', 'system_prompt', 'share_scope']
        model: str = 'gemini/gemini-2.5-flash'
        top_k: int = 6
        system_prompt: str = ''          # NOTE: empty in ALL artifacts
        share_scope: str
      continuity: dict[6] keys=['mode','always_continue','allow_resume_during_instance',
                                'reset_behavior','description','baseline_scope']
        mode: str = 'fresh_per_turn'
        always_continue: bool = False
        allow_resume_during_instance: bool = False
        reset_behavior: str = 'reset_clears_conversation'
        description: str = 'The system starts fresh CLI turns unless its own
                            non-conversation memory mechanism is configured.'
        baseline_scope: str = 'Baseline workers instantiate a fresh system per baseline
                               instance; conversation continuity does not cross baseline instances.'
    task: dict[2]
      name: str = 'exploitable_poker'
      params: dict[7]   # task-specific, see 2.1.1
    task_brief: dict[5] keys=['objective','instance_unit','reward_definition',
                              'completion_definition','constraints']
    variant: NoneType = None
    schedule: str = 'quick_test'
    rollout_schedule: str = 'quick_test'
    run_count: int = 3
    rollouts: int = 3
    max_workers: int = 6
    run_mode: str = 'permute'
    rollout_mode: str = 'permute'
    baseline_mode: str = 'reset_each_instance'
    baseline: dict[4] keys=['trace_path','execution','status','instance_outcomes']
    sequence_signature: list[N] of {instance_id: str, instance_index: int}
    aggregate: dict[16..18]              # see 2.2
    runs: list[3] of {run_index, score, trace_path, execution, status,
                      instance_outcomes, aggregate}   # see 2.3
```

#### 2.1.1 `summary.task.params` — real values per task

**exploitable_poker** (`mubit-poker-v5-3.5flash`):
```json
{"num_instances": 120, "starting_chips": 1000, "small_blind": 5, "big_blind": 10,
 "seed": 42, "schedule": "default", "expected_num_instances": 120}
```

**database_exploration** (`mubit-db-3`):
```json
{"schedule": "default",
 "db_path": "/private/tmp/continual-learning-bench/data/database_exploration/products.db",
 "questions_path": ".../questions.json", "num_questions": 30,
 "max_queries_per_question": 15, "seed": 42,
 "response_timeout_seconds": 60.0, "expected_num_instances": 40}
```

**blind_spectrum_monitoring** (`mubit-bsm-v4-3.5flash`):
```json
{"W": 20.0, "G": 10.0, "seed": 42, "num_instances": 90, "noise_sigma": 3.0,
 "noise_floor_dbm": -50.0, "channel_power_dbm": -30.0, "p_active": 0.9,
 "p_interference": 0.1, "band_width": 180.0, "freq_step": 0.5, "schedule": "default",
 "response_timeout_seconds": 90.0, "probe_mode": false, "center_jitter": 0.0,
 "freq_noise": 3.0, "power_noise": 5.0, "p_miss": 0.15, "p_false_alarm": 0.2,
 "max_steps_per_instance": 1, "repeat_instructions": true, "expected_num_instances": 90}
```

#### 2.1.2 `summary.task_brief` — real values (BSM)

```json
{"objective": "Maximize scan-by-scan long-run spectrum availability accuracy by reporting persistent transmitter occupancy across scans.",
 "instance_unit": "One transmitter-occupancy report.",
 "reward_definition": "Reward is the per-scan IoU between the true long-run available spectrum and the availability implied by complementing your reported transmitters.",
 "completion_definition": "An instance completes after you submit one transmitter-occupancy report for the current scan.",
 "constraints": ["Use the structured transmitter report schema.",
                 "Transfer knowledge of persistent transmitters and stable gaps across scans."]}
```

### 2.2 `$.summary.aggregate` — **the primary plotting surface**

```
aggregate: dict[16-18]
  score: {mean: float, std: float, min: float, max: float}
  eval_metrics: {optimal_performance:{mean,std,min,max},
                 actual_performance:{...}, cumulative_loss:{...}}
  metrics: dict[N]                        # task-specific, each {mean,std,min,max}
  execution: {avg_response_seconds:{...}, max_response_seconds:{...},
              run_index:{...}, total_interactions:{...},
              total_response_seconds:{...}, usage:{...}, wall_duration_seconds:{...}}
  baseline_reward_by_index:      list[N] float   # r_sl per instance  ← STATELESS CURVE
  baseline_cost_by_index:        list[N] float
  mean_reward_by_index:          list[N] float   # r_sf per instance  ← STATEFUL CURVE
  mean_gain_by_index:            list[N] float   # r_sf − r_sl per instance
  mean_cost_by_index:            list[N] float|null
  mean_cost_increase_by_index:   list[N] float|null
  mean_latency_by_index:         list[N] float|null
  cumulative_mean_gain_by_index: list[N] float   ← CUMULATIVE LEARNING CURVE
  final_cumulative_mean_gain:    float
  raw_metric_name:               str|None        # 'exploration_regret' for DB, None elsewhere
  mean_raw_metric_by_index:      list[N]         # DB only
  runs_total: int = 3
  runs_completed: int = 3
  runs_blocked: int = 0
```

**Real values** (`mubit-db-3`, N=40):

```
mean_gain_by_index = [-0.022233, -0.177767, -0.1111, -0.0222, 0.111133, 0.222233,
  0.377767, 0.2, 0.2, 0.244433, 0.133333, 0.177767, 0.0, 0.0, 0.266667, 0.0,
  0.444467, 0.2, 0.0, 0.0, 0.1111, 0.022233, 0.0, 0.0222, -0.0889, 0.2, 0.0,
  0.377767, 0.466667, 0.0, 0.222233, 0.266667, 0.177767, -0.0889, 0.0, 0.355533,
  0.0, 0.6889, 0.0, 0.2222]

cumulative_mean_gain_by_index = [-0.022233, -0.1, -0.1037, -0.083325, -0.044433,
  0.000011, 0.053976, 0.072229, 0.086426, 0.102227, 0.105054, 0.111114, 0.102567,
  0.09524, 0.106669, 0.100002, 0.120265, 0.124694, 0.118132, 0.112225, 0.112171,
  0.108083, 0.103384, 0.100001, 0.092445, 0.096582, 0.093005, 0.103175, 0.115709,
  0.111852, 0.115413, 0.12014, 0.121886, 0.115686, 0.112381, 0.119135, 0.115915,
  0.130994, 0.127635, 0.129999]

final_cumulative_mean_gain = 0.129999
mean_latency_by_index[:6] = [29.848483, 40.821653, 23.207531, 74.491496, 19.731922, 22.353504]
mean_cost_by_index[:6]    = [0.018861, 0.033319, 0.02256, 0.069531, 0.02537, 0.027844]
```

**`aggregate.metrics` keys per task** (each value is `{mean,std,min,max}`):

- **DB:** `accuracy`, `avg_queries_per_question`, `correct`, `cumulative_regret`, `first_half_accuracy`, `first_half_avg_queries`, `normalized_regret`, `query_reduction`, `score`, `second_half_accuracy`, `second_half_avg_queries`, `total_queries`, `total_questions`
- **Poker:** `avg_profit_per_hand`, `baseline_profit_per_hand`, `bb_per_hand`, `cumulative_loss`, `first_half_avg`, `hands_played`, `improvement`, `normalized_loss`, `regret_rate`, `second_half_avg`, `total_profit`
- **BSM:** `first_half_score`, `learning_delta`, `mean_score`, `n_scans_completed`, `second_half_score`, `total_interactions`

Real BSM v4 values: `first_half_score.mean = 0.544`, `second_half_score.mean = 0.7497`, `learning_delta.mean = 0.2057` (std 0.0421, min 0.162, max 0.246), `mean_score.mean = 0.6468`.

### 2.3 `$.summary.runs[i]` — per-run detail (enables 3 individual curves, not just the mean)

```
runs[0]: {run_index: int, score: float, trace_path: str, execution: {...},
          status: str, instance_outcomes: list[N], aggregate: {...}}
runs[0].aggregate (mubit-db-3, real):
  {"instances_completed": 40, "total_reward": 8.1999, "mean_reward": 0.204997,
   "reward_by_index": list[40], "total_cost": 1.025413, "mean_cost": 0.025635,
   "cost_by_index": list[40], "total_gain": 6.1999, "mean_gain": 0.154997,
   "gain_by_index": list[40], "gain_instances_matched": 40, "gain_coverage_ratio": 1.0,
   "total_cost_increase": 0.022087, "mean_cost_increase": 0.000552,
   "cost_increase_by_index": list[40], "raw_metric_name": "exploration_regret",
   "raw_metric_by_index": list[40]}
```

This is important: **`reward_by_index` and `gain_by_index` exist per run**, so error bands / spaghetti plots over 3 runs are fully supported.

### 2.4 `$.baseline_trace` and `$.run_traces[i].trace` (14 / 13 keys)

```
trace: dict
  status: str = 'completed'
  phase: str = 'baseline' | 'run'
  schedule: str
  task_brief: {...}
  system: {name, params, continuity}
  task: {name, params}
  execution: dict[19]
    start_time: str = '2026-08-09T14:38:05.997388'
    end_time: str = '2026-08-09T14:42:03.615078'
    total_interactions: int
    wall_duration_seconds: float
    total_response_seconds: float
    avg_response_seconds: float
    max_response_seconds: float
    run_group_id: str
    run_index: int|None
    status, phase, task_brief
    instances_total: int
    instances_completed: int
    instances_blocked: int
    coverage_ratio: float = 1.0
    blocked_instances: list[0]            # EMPTY in every artifact audited
    usage: {respond:{...}, observe:{...}, interaction:{...}}
    instance_outcomes: list[N]
  artifacts: {instances: [...]}           # baseline only; each element is just {"type": "mubit"}
  system_memory: None                     # ← ALWAYS None. See §5.
  system_artifacts: None                  # ← ALWAYS None. See §5.
  interactions: list[N]                   # ← THE TRAJECTORY. See 2.5
  instance_outcomes: list[N]              # see 2.6
  blocked_instances: list[0]              # baseline only
  instance_traces: list[N]                # baseline ONLY (absent from run_traces)
  result: {score, metrics, summary, eval_metrics, instance_outcomes}
```

Two asymmetries worth knowing:
- `instance_traces` (a nested per-instance sub-trace, each with its own `interactions`) exists **only on `baseline_trace`**, not on `run_traces`. E.g. `baseline_trace.instance_traces` = 40 elements for `mubit-db-3`, `instance_traces[0].interactions` = 12.
- `artifacts.instances[i]` is degenerate: literally `{"type": "mubit"}`. No memory payload.

### 2.5 `interactions[i]` — **the replay record** (8 keys)

```
interactions[0]: {step_number: int, timestamp: str, query: {...}, response: {...},
                  observation: {...}, timing: {...}, usage: {...}, done: bool}
  query:    {prompt: str, instance_id: str, instance_index: int,
             metadata: dict, response_schema: str, feedback: null}
  response: {action: dict, action_type: str = 'structured', metadata: dict}
  observation: {content: str, instance_complete: bool, metadata: dict}
  timing:   {response_start_time, response_end_time,
             response_latency_seconds: float, response_latency_ms: float}
  usage:    {respond: {...}, observe: {...}, interaction: {...}}
```

`usage.respond` is a full token/cost record per call:
```json
{"call_count": 1, "priced_call_count": 1, "unpriced_call_count": 0, "pricing_complete": true,
 "input_tokens": 621, "output_tokens": 460, "total_tokens": 1081, "reasoning_tokens": 303,
 "cached_input_tokens": 0, "cache_creation_input_tokens": 0,
 "missing_input_token_count": 0, "missing_output_token_count": 0,
 "input_tokens_complete": true, "output_tokens_complete": true,
 "reasoning_tokens_complete": true, "cached_input_tokens_complete": false,
 "cost_usd": 0.0013363,
 "by_model": {"gemini/gemini-2.5-flash": { ...same fields... }},
 "by_call_type": {"completion": { ...same fields... }}}
```

**`response.metadata` key sets differ by system** — this is how you tell them apart:

| System | `response.metadata` keys |
|---|---|
| `icl` | `context_tokens`, `has_truncated`, `interaction_count`, `model`, `provider_state`, `system_type`, `truncation_count`, `usage` |
| `mubit` | `interaction_count`, `model`, `mubit_run_id`, `retrieved_count`, `retrieved_lessons`, `system_type`, `usage` |
| `mubit` (DB) / `mubit_full` | above **+ `retrieved_lessons_meta`** |
| `mubit_genai` | above **+ `llm_backend`** |
| `mubit_bsm` | `interaction_count`, `model`, `registry_size`, `scan_peaks`, `system_type`, `usage` |

`observation.metadata` is thin: union of keys across a poker run is just `{'done'}`; across a DB run just `{'instance_complete'}`; BSM is `{}`.

### 2.6 `instance_outcomes[i]` (10 keys)

```json
{"instance_id": "poker:calling_station:hand:stage0_seed42_hand1",
 "instance_index": 0, "reward": -2.0, "success": false,
 "raw_metric_name": null, "raw_metric_value": null, "raw_metric_higher_is_better": null,
 "metadata": {"variant_id": "calling_station", "total_profit": -20},
 "cost_usd": 0.0117447, "latency_seconds": 22.217006}
```

DB variant carries a richer metadata block and a populated raw metric:
```json
{"instance_id": "1", "instance_index": 0, "reward": 0.0, "success": false,
 "raw_metric_name": "exploration_regret", "raw_metric_value": 15.0,
 "raw_metric_higher_is_better": false,
 "metadata": {"num_queries": 14, "num_actions": 15, "regret": 15.0, "difficulty": "hard"},
 "cost_usd": 0.03412329, "latency_seconds": 54.536559}
```

BSM variant:
```json
{"instance_id": "blind_spectrum_monitoring:five_ch_wide:corpus:mixed_grid_lifecycle:scan:1",
 "instance_index": 0, "reward": 0.2391, "success": false,
 "raw_metric_name": null, "raw_metric_value": null, "raw_metric_higher_is_better": null,
 "metadata": {"unsafe_bandwidth_claimed": 105.0, "missed_available_bandwidth": 0.0},
 "cost_usd": 0.0, "latency_seconds": 8.161773}
```

### 2.7 `trace.result.metrics` — **the richest per-instance ground-truth structures**

| Task | List/dict fields | Length | Contents |
|---|---|---|---|
| Poker | `loss_curve` | N hands | float |
| Poker | **`hand_history`** | N hands | `{hand_num, actions[], profit, total_profit, instance_id, variant_id}` |
| DB | `loss_curve` | 40 | float |
| DB | **`question_history`** | 40 | `{question_id, question, difficulty, submitted_answer, ground_truth, correct, num_queries, num_actions, regret, timed_out, budget_exceeded}` |
| BSM | `score_curve` | 90 | float |
| BSM | **`scan_results`** | 90 | `{scan_idx, scoring{...}, report{transmitters[]}}` |
| BSM | `dgp` | — | `{W, G, seed}` |
| BSM | `corpus` | — | `{id, dataset_path, schema_version}` |

#### Real `question_history[20]` (DB, post-drift):
```json
{"question_id": 114,
 "question": "What is the median list price in dollars for electronics that have at least one catalog image and a positive list price? Round to 2 decimal places.",
 "difficulty": "hard", "submitted_answer": "20.95", "ground_truth": 22.09,
 "correct": false, "num_queries": 3, "num_actions": 4, "regret": 15.0,
 "timed_out": false, "budget_exceeded": false}
```

Real `correct` flag sequence for `mubit-db-3` run 0 (40 questions):
```
F F F F F T T F T T T T F F F F F F F F  F F F F F F F T T F T F T F F T F T F T
```
Real `num_queries` sequence: `[14,8,6,14,5,5,4,11,6,4,6,4,5,12,10,4,8,7,4,8, 3,10,4,15,3,7,6,3,6,5,5,4,7,7,10,10,6,5,4,7]`

**All 40 questions are `difficulty: "hard"`** — there is no difficulty variation to plot.

#### Real `scan_results[0]` (BSM v4) — abridged:
```json
{"scan_idx": 0,
 "scoring": {"score": 0.2391, "n_gt": 13, "n_reported": 3, "n_matched": 13,
   "checks": [
     {"type": "gt_available", "center_freq": 16.0, "bandwidth": 2.0},
     {"type": "gt_available", "center_freq": 23.0, "bandwidth": 2.0},
     ... 13 gt_available entries at 16,23,40,47,64,71,88,95,112,119,136,143,163.5 ...
     {"type": "reported_available", "center_freq": 12.0,  "bandwidth": 24.0},
     {"type": "reported_available", "center_freq": 55.5,  "bandwidth": 33.0},
     {"type": "reported_available", "center_freq": 127.5, "bandwidth": 81.0},
     {"type": "overlap", "center_freq": 16.0, "bandwidth": 2.0}, ... ],
   "gt_available_bandwidth": 33.0, "reported_available_bandwidth": 138.0,
   "overlap_bandwidth": 33.0, "unsafe_bandwidth_claimed": 105.0,
   "missed_available_bandwidth": 0.0},
 "report": {"transmitters": [
     {"center_freq": 31.5, "bandwidth": 15.0, "currently_active": true, "estimated_power": -39.0},
     {"center_freq": 79.5, "bandwidth": 15.0, "currently_active": true, "estimated_power": -39.0}]}}
```

Real `scan_results[89]` (last scan, v4): `score: 1.0, n_gt: 13, n_reported: 13, n_matched: 13` — all 13 reported_available regions exactly match all 13 gt_available regions.

**This is the single richest visual asset in the repo:** for each of 90 scans you have the true available bands, the claimed available bands, the overlap, and the agent's transmitter list. It draws a spectrum ribbon directly.

---

## 3. Every plottable time-series / per-instance array

| # | Data path | Length | Available in |
|---|---|---|---|
| 1 | `summary.aggregate.baseline_reward_by_index` | N | all 12 |
| 2 | `summary.aggregate.mean_reward_by_index` | N | all 12 |
| 3 | `summary.aggregate.mean_gain_by_index` | N | all 12 |
| 4 | `summary.aggregate.cumulative_mean_gain_by_index` | N | all 12 |
| 5 | `summary.aggregate.mean_latency_by_index` | N | all 12 (1 null at idx 119 in poker-120) |
| 6 | `summary.aggregate.mean_cost_by_index` | N | populated only for gemini-2.5-flash artifacts; **all zeros for gemini-3.5-flash** |
| 7 | `summary.aggregate.mean_cost_increase_by_index` | N | same limitation |
| 8 | `summary.aggregate.mean_raw_metric_by_index` | 40 | DB only (`exploration_regret`) |
| 9 | `summary.runs[i].aggregate.reward_by_index` | N | all 12, ×3 runs |
| 10 | `summary.runs[i].aggregate.gain_by_index` | N | all 12, ×3 runs |
| 11 | `summary.runs[i].aggregate.cost_by_index` | N | all 12, ×3 runs |
| 12 | `trace.result.metrics.loss_curve` / `score_curve` | N | all 12 |
| 13 | `trace.result.metrics.question_history[*].num_queries` / `.correct` | 40 | DB |
| 14 | `trace.result.metrics.hand_history[*].profit` / `.total_profit` / `.variant_id` | N hands | poker |
| 15 | `trace.result.metrics.scan_results[*].scoring.score` | 90 | BSM |
| 16 | `scan_results[*].scoring.{n_gt,n_reported,n_matched}` | 90 | BSM |
| 17 | `scan_results[*].scoring.{unsafe_bandwidth_claimed, missed_available_bandwidth, overlap_bandwidth, gt_available_bandwidth, reported_available_bandwidth}` | 90 | BSM |
| 18 | `interactions[*].response.metadata.registry_size` | 90 | BSM v2/v4 — **memory-size curve** |
| 19 | `interactions[*].response.metadata.scan_peaks` | 90 | BSM v2/v4 |
| 20 | `interactions[*].response.metadata.retrieved_count` | per step | mubit/mubit_full/mubit_genai |
| 21 | `interactions[*].response.metadata.context_tokens` | per step | **ICL only** — context-growth curve |
| 22 | `interactions[*].usage.respond.input_tokens` / `.output_tokens` / `.reasoning_tokens` / `.cost_usd` | per step | all |
| 23 | `interactions[*].timing.response_latency_seconds` | per step | all |
| 24 | distinct `retrieved_lessons_meta[*].id` over time (derived) | per step | mubit DB/poker — **memory-growth curve** |

---

## 4. Trajectory richness — is an "agent replay" demo possible?

**Yes, fully, with no new data collection.** Every one of the 11,835 interactions stores the complete prompt text, the structured action, the environment's response, latency, and tokens.

### 4.1 Concrete stored step — Poker, `mubit-quick-3`, baseline, step 1

```json
{"step_number": 1, "timestamp": "2026-08-09T14:38:10.269172",
 "query": {
   "prompt": "=== Brief ===\nObjective: Maximize profit against the opponent across independent poker hands.\n...\nHand #1 - PREFLOP\nTable: Heads-up Texas Hold'em (2 players)\nOpponent: Tom\nYour position: Big blind\nYour hand: [ J ♣ ] [ 7 ♥ ]\nBoard: No cards yet\nPot: 20 chips\nYour chips: 990\nOpponent's action: CALL\n\nSituation: Opponent called your bet of 10 (you can check or raise)\n...",
   "instance_id": "poker:calling_station:hand:stage0_seed42_hand1",
   "instance_index": 0,
   "metadata": {"hand_num": 1, "phase": "PREFLOP", "pot": 20, "chips_to_call": 0,
                "player_chips": 990, "min_raise": 20, "max_raise": 1000,
                "legal_actions": ["FOLD","CHECK","RAISE"], "num_players": 2,
                "position": "Big blind", "opponent_name": "Tom",
                "instance_id": "poker:calling_station:hand:stage0_seed42_hand1"},
   "response_schema": "PokerAction", "feedback": null},
 "response": {
   "action": {"thinking": "This is the first hand, so I have no information about opponent tendencies. I am in the big blind with J7 offsuit, which is a very weak hand. The opponent (Tom) has limped (called 10 chips from the small blind). Since I am the big blind and Tom only called, I have the option to check and see the flop for free. ...",
              "action": "CHECK", "amount": null},
   "action_type": "structured",
   "metadata": {"interaction_count": 1, "system_type": "mubit",
                "model": "gemini/gemini-2.5-flash",
                "mubit_run_id": "clbench-mubit-be372ca73322",
                "retrieved_count": 0, "retrieved_lessons": [], "usage": {...}}},
 "observation": {"content": "Action taken", "instance_complete": false, "metadata": {}},
 "timing": {"response_start_time": "2026-08-09T14:38:06.935759",
            "response_end_time": "2026-08-09T14:38:10.268866",
            "response_latency_seconds": 3.333115}}
```

Note the model's **`thinking` field is stored verbatim** on every poker step. That's a chain-of-thought you can render in a replay panel.

### 4.2 Concrete stored step — Database, `mubit-db-3`, run 0, step 1

```json
{"step_number": 1,
 "query": {"prompt": "Question 1/40\n\nHow many office product reviews have timestamps that correspond to dates in the year 2031 or later?\n\nYou have access to a SQLite database ... You may run up to 15 exploratory SQL queries ...",
   "instance_id": "1", "instance_index": 0,
   "metadata": {"question_id": 1, "question_num": 1, "difficulty": "hard",
                "queries_used": 0, "query_budget": 15,
                "db_path": "/var/folders/.../tmpmn_cxx4y.db"},
   "response_schema": "DatabaseAction"},
 "response": {"action": {"action": "QUERY", "content": ".tables"}, "action_type": "structured",
   "metadata": {"interaction_count": 1, "system_type": "mubit",
                "mubit_run_id": "clbench-mubit-6fd029f68dd0",
                "retrieved_count": 0, "retrieved_lessons": [], "retrieved_lessons_meta": []}},
 "observation": {"content": "Query result (1/15 queries used, 14 remaining):\n\nattrs_g1\nattrs_g3\nfdbk_g1\nfdbk_g2\nfdbk_g3\nfdbk_stats_g1\nitems_g1\nitems_g2\nitems_g3\nsqlite_sequence\ntaxn_g1\ntaxn_g2",
   "instance_complete": false},
 "timing": {"response_latency_seconds": 1.4433410830097273, "response_latency_ms": 1443.341}}
```

Step 2 shows a real agent error being captured:
```
action:      {"action": "QUERY", "content": "PRAGMA table_info(taxn_g1); PRAGMA table_info(taxn_g2); PRAGMA table_info(taxn_g3);"}
observation: "Query result (2/15 queries used, 13 remaining):\n\nERROR: You can only execute one statement at a time."
```

**Every SQL query the agent typed and every result it got back is on disk.** A "watch the agent explore the database" replay is directly buildable.

### 4.3 Concrete stored step — BSM, `mubit-bsm-v4`, run 0, step 1

The prompt ends with the raw sensor feed:
```
--- Scan 51/90 ---

Scan metadata:
  scan_id: scan-a28ef9c8-bf27-2a5d-c08f-d8ae4eb96ba7
  timestamp_utc: 2026-01-01T04:10:00Z
  sensor_id: sensor-bsm-7c1a
  detector_version: peakdet-v2.4
  integration_time_ms: 250
  estimated_noise_floor_dbm: -60.0

Detected peaks:
  - peak_id: peak-cf71b101-... | freq: 31.4 MHz | power: -37.4 dBm | width: 14.9 MHz
  - peak_id: peak-c1022808-... | freq: 42.8 MHz | power: -44.7 dBm | width: 4.7 MHz
  - peak_id: peak-14d85907-... | freq: 66.6 MHz | power: -43.7 dBm | width: 4.9 MHz
Band: 0.0-168.0 MHz

Submit your report.
```
Response action: `{"transmitters": [{"center_freq": 31.5, "bandwidth": 15.0, "currently_active": true, "estimated_power": -39.0}, {"center_freq": 79.5, ...}]}`
Response metadata: `{"interaction_count": 1, "system_type": "mubit_bsm", "model": "gemini-3.5-flash", "registry_size": 2, "scan_peaks": 2}`
Observation: `{"content": "Scan 1 recorded.", "instance_complete": true, "metadata": {}}`

---

## 5. Are Mubit's stored "lessons" in the artifacts? — **Yes, verbatim, for poker + DB. No, for BSM.**

This is the most demo-valuable finding.

### 5.1 What IS stored

`interactions[i].response.metadata.retrieved_lessons` is a **list of the exact lesson strings Mubit's `recall()` injected into that prompt**. Coverage in run 0:

| Artifact | Steps with ≥1 retrieved lesson | mean `retrieved_count` | max |
|---|---|---|---|
| `mubit-quick-3` (poker, 5 hands) | 10 / 14 | 1.79 | 4 |
| `mubit-poker-full-3.5flash` | 259 / 263 | 5.76 | 6 |
| `mubit-poker-v5-3.5flash` | — | 5.75 | 6 |
| `mubit-db-3` | 297 / 312 | 5.28 | 6 |
| `mubit-full-db-3` | — | 5.31 | 6 |
| `mubit-genai-db-3` | — | 5.49 | 6 |

**Verbatim lesson text** (poker, `mubit-quick-3` run 0, step 5, `retrieved_count: 1`):

> ```
> Prior instance:
> PROMPT: Hand #1 - RIVER
> Table: Heads-up Texas Hold'em (2 players)
> Opponent: Tom
> Your position: Big blind
> Your hand: [ J ♣ ] [ 7 ♥ ]
> Board: [ 6 ♣ ] [ A ♠ ] [ 6 ♠ ] [ 9 ♣ ] [ 9 ♠ ]
> Pot: 40 chips
> Your chips: 980
> Opponent's action: CALL
> ...
> MY ACTION: {"thinking":"My hand (J7o) has no showdown value on the A6699 board. I bluffed on the turn, and the opponent (Tom) called. This call indicates Tom likely has some equity, a weak pair, or a weak Ace, or perhaps a 9. Given that Tom called my turn bet, it's very unlikely they will fold to another bluff on the river. ...","action":"CHECK","amount":null}
> OUTCOME: Hand 1 complete: You LOST!
>
> SHOWDOWN:
>   Board: [ 6 ♣ ] [ A ♠ ] [ 6 ♠ ] [ 9 ♣ ] [ 9 ♠ ]
>   Your hand: [ J ♣ ] [ 7 ♥ ]
>   Opponent's hand: [ K ♠ ] [ 9 ♦ ]
>
> Final pot: 40 chips
> Ending stack: 980 chips
> Net chip change this hand: -20 chips
> Total profit: -20 chips
> ```

**Verbatim lesson text** (DB, `mubit-db-3` run 0, step 16, `retrieved_count: 1`) — tail:

> ```
> Queries used so far this question: 14/15
> MY ACTION: {"action":"ANSWER","content":"3"}
> OUTCOME: Question 1: INCORRECT.
> Your answer: 3
> Correct answer: 58
> Exploratory queries used: 14
> ```

**Verbatim lesson text** (BSM v1 `mubit-bsm-3.5flash`, which used `mubit_genai` prose lessons):

> `"Scan 1: detected 2 peaks: [32.3MHz/15MHz/-39dBm, 79.8MHz/17MHz/-39dBm]. Reported 2 transmitters: [32.3MHz/14.8MHz, 79.8MHz/16.7MHz]. Accumulate dormant channels — they may not appear in every scan."`

### 5.2 Memory identity + growth

`retrieved_lessons_meta` (present on DB and 120-hand-poker artifacts) carries **stable Mubit memory IDs**:
```json
{"id": "647144ae-e7d4-4b55-bb5c-44b7b91eb666",
 "text": "Prior instance:\nPROMPT: Question 1/40\n\nHow many office product reviews ...",
 "metadata": {}}
```
Keys: `['id', 'text', 'metadata']`. **`metadata` is an empty dict in every sample checked** — no intent, no scope, no score, no timestamp.

Derived memory-growth curve for `mubit-db-3` run 0 (distinct lesson IDs ever retrieved, sampled every 20 steps over 312 steps):
```
[0, 1, 3, 6, 8, 10, 13, 16, 18, 19, 21, 23, 25, 28, 31, 33] → final 34
```
34 distinct lessons, 1,646 total retrieval references. This is a real, plottable "memory accumulates and gets reused" curve.

For BSM v2/v4 the analogous signal is `registry_size`, and it's a beautiful monotone saturating curve (run 0, 90 scans):
```
2,5,7,9,10,10,11,11,12,13,14,14,14,14,14,14,14,15,15,15,15,15,15,16,16,17,17,17,
18,18,18,18,18,18,18,18,18,18,18,18,18,18,18,18,19,19,19,20,20,20,20,20,20,20,20,
20,20,20,20,20,21,21,21,21,21,21,21,21,21,21,21,21,21,21,21,21,21,21,21,21,21,21,
21,21,21,21,21,21,21,21
```
2 → 21 transmitters, saturating around scan 60. Ground truth is 13 gt_available regions (i.e. the band contains a fixed channel set), so the registry slightly over-counts at 21.

### 5.3 What is NOT stored

- **`trace.system_memory` is `None` in every artifact.** The dedicated field for dumping the memory store is unused.
- **`trace.system_artifacts` is `None` in every artifact.**
- **`trace.artifacts.instances[i]` is `{"type": "mubit"}`** — no payload.
- **For BSM v2/v4, the actual registry *contents* are never stored** — only `registry_size` (an int) and `scan_peaks`. You can reconstruct an approximation from `scan_results[*].report.transmitters`, but the adapter's internal registry (with `hit_count`, `first_seen_scan`, `last_seen_scan`, `inferred` flags) is lost.
- **`query.prompt` is the harness-side prompt, not the augmented prompt actually sent to the LLM.** Verified: BSM prompts in the artifacts contain no `REGISTRY` block even though `systems/mubit_bsm/system.py` injects one. So for BSM you cannot show "what the model actually saw."

---

## 6. Real headline numbers extracted from the artifacts

Reproduced by running `scripts/analyze_results.py`. `g_b = (r̄_sf − r̄_sl) / (r_max − r̄_sl)`; `r_max` = 1.0 for DB/BSM, **9.4875** for poker.

### Blind Spectrum Monitoring (r_max = 1.0)

| Artifact | System | g_b | raw Σgain | r_sf | r_sl | per-run gains | per-run IoU |
|---|---|---|---|---|---|---|---|
| `mubit-bsm-3.5flash` (v1) | mubit_genai | **11.6%** | +8.14 | 0.310 | 0.220 | +8.67, +9.33, +6.42 | 0.3158, 0.3232, 0.2909 |
| `mubit-bsm-registry-3.5flash` (v2) | mubit_bsm | **31.8%** | +15.19 | 0.638 | **0.470** | +11.43, +21.68, +12.45 | 0.5967, 0.7106, 0.6080 |
| `mubit-bsm-v4-3.5flash` (v4) | mubit_bsm | **53.7%** | +36.92 | 0.647 | **0.237** | +32.91, +40.54, +37.31 | 0.6022, 0.6871, 0.6512 |

BSM v4 half-split: `first_half_score = 0.544`, `second_half_score = 0.7497`, `learning_delta = 0.2057`.

### Database Exploration (r_max = 1.0)

| Artifact | System | Model | g_b | raw | r_sf | r_sl | per-run gains | pre-drift | post-drift |
|---|---|---|---|---|---|---|---|---|---|
| `icl-db-3` | icl | 2.5-flash | 11.4% | +4.40 | 0.145 | 0.035 | +3.13, +5.67, +4.40 | +0.0844 | +0.1355 |
| `mubit-db-3` | mubit | 2.5-flash | **13.7%** | +5.20 | 0.180 | 0.050 | +6.20, +2.87, +6.53 | +0.1122 | +0.1478 |
| `mubit-full-db-3` | mubit_full | 2.5-flash | 11.8% | +4.40 | 0.182 | 0.072 | +6.00, +4.87, +2.33 | +0.0967 | +0.1233 |
| `mubit-genai-db-3` | mubit_genai | 3.5-flash | 1.9% | +0.71 | 0.089 | 0.072 | +0.67, +1.47, −0.00 | +0.0144 | +0.0211 |
| `mubit-genai-db-full-3.5flash` | mubit_genai | 3.5-flash | 1.1% | +0.40 | 0.070 | 0.060 | +0.13, +0.87, +0.20 | +0.0078 | +0.0122 |

Task-quality metrics (means over 3 runs):

| Artifact | accuracy | correct/40 | avg queries/Q | 1st-half acc | 2nd-half acc | cumulative_regret |
|---|---|---|---|---|---|---|
| `icl-db-3` | 0.1917 | 7.67 | 3.225 | 0.150 | 0.2333 | 513.0 |
| `mubit-db-3` | **0.3167** | 12.67 | 6.85 | 0.2833 | 0.350 | 492.0 |
| `mubit-full-db-3` | 0.3333 | 13.33 | 7.29 | 0.300 | 0.3667 | 491.0 |
| `mubit-genai-db-3` | 0.6667 | 26.67 | 13.51 | 0.7167 | 0.6167 | 546.3 |
| `mubit-genai-db-full-3.5flash` | **0.7167** | 28.67 | 13.62 | 0.7667 | 0.6667 | 558.0 |

### Exploitable Poker (r_max = 9.4875)

| Artifact | System | Sched | g_b | raw | r_sf | r_sl | per-run gains |
|---|---|---|---|---|---|---|---|
| `mubit-quick-3` | mubit | quick_test (5) | **+7.5%** | +3.83 | −0.033 | −0.800 | +4.00, +3.50, +4.00 |
| `icl-quick-3` | icl | quick_test (5) | +1.7% | +0.83 | −0.433 | −0.600 | +1.00, +2.00, −0.50 |
| `mubit-poker-v5-3.5flash` | mubit_genai | default (120) | **−1.0%** | −10.63 | 0.297 | 0.386 | −11.80, −8.30, −11.80 |
| `mubit-poker-full-3.5flash` | mubit_genai | default (120) | **−1.4%** | −15.00 | 0.175 | 0.300 | −22.00, −4.00, −19.00 |

### Cost / token / latency (only fully priced on gemini-2.5-flash artifacts)

Aggregate `respond` usage, mean across 3 runs:

| Artifact | calls | input tokens | output tokens | cost USD |
|---|---|---|---|---|
| `mubit-db-3` | 314.0 | **3,226,824** | 189,471 | **$1.073** |
| `icl-db-3` | 169.0 | **6,396,228** | 219,739 | **$1.113** |
| `mubit-full-db-3` | 331.7 | 3,670,429 | 217,802 | $1.249 |

Baselines: `mubit-db-3` baseline = 449 calls / 1,336,500 in / $1.003. `icl-db-3` baseline = 439 calls / 1,259,071 in / $1.057.

Per-step context growth, run 0:
- **ICL** `context_tokens`: `522, 860, 1385, 1897, 2393, 2683, 3117, 3689, 3981, 4402 → … → 96,260` (max). `truncation_count` max = 0, `has_truncated` = false — it never truncated, it just grew.
- **Mubit** `usage.respond.input_tokens`: `579, 916, 1232, 1602, 1972 → … → 19,817` (last), max 37,183 — resets at each question boundary.

Wall time, run 0: `mubit-db-3` 1039.3 s (avg 3.24 s/call) vs `icl-db-3` 1654.8 s (avg 7.04 s/call). BSM v4 run 0: 2186.0 s, avg 24.25 s/call, max 49.97 s.

### Concept-drift structure that actually exists in the data

**DB — schema migration at Q20.** `trace.result.metrics.variant_id = "schema_drift"`, `variant_display_name = "Schema Drift (Migration)"`. Real evidence from observation text in `mubit-db-3` run 0: a table named **`attrs_g3` pre-drift becomes `product_attributes_g3` post-drift**; new columns `review_year` / `review_month` appear post-drift replacing pre-drift `review_ct` / `review_count` usage.

**Poker — opponent switches.** `hand_history[*].variant_id` over 120 hands in `mubit-poker-v5-3.5flash` run 0:
```
hand   1 → calling_station
hand  21 → loose_aggressive
hand  51 → calling_station
hand  61 → fit_or_fold
hand  96 → loose_aggressive
```
Five opponent-regime segments. **This is unused by every existing chart** and is the best untapped drift story in the repo.

**BSM — stage boundaries.** `chart_data.json` asserts stage boundaries at scan 30 and 60. **These boundaries are NOT recorded per-scan in the artifacts** — `scan_results[i]` has only `scan_idx`, `scoring`, `report`. The run-level `variant_id` is a single value (`full_grid_active`). So the stage annotations are an external assumption, not data.

---

## 7. Integrity findings — read before building anything

### 7.1 The BSM +53.7% headline is a baseline artifact, not a learning result

| Version | r_sf (stateful) | r_sl (stateless) | g_b |
|---|---|---|---|
| v2 `registry` | 0.6385 | **0.4697** | 31.8% |
| v4 | 0.6468 | **0.2366** | **53.7%** |

The stateful score moved **0.6385 → 0.6468 (+1.3% relative)**. The entire jump from 31.8% to 53.7% comes from the denominator: the stateless baseline fell from 0.4697 to 0.2366.

Why the baseline fell: in v2 the baseline sometimes reported far more transmitters than its registry held — mean reported transmitters per scan in the v2 baseline is **8.11**, with individual scans reporting 13–14 and scoring **IoU = 1.000** (baseline scans 7 and 10 both = 1.0). In v4 the `_filter_to_registry` post-filter clamps reports to the registry, dropping mean reported per scan to **3.31** and eliminating the accidental perfect-score baseline scans (v4 baseline max IoU = 0.320 vs v2 baseline max = 1.000).

The v4 filter is a legitimate improvement to the *system*, but because CL-Bench's baseline runs **the same system with memory reset**, the filter hurt the baseline more than it helped the stateful run. Presenting "+53.7% gain" as evidence of better learning is not defensible.

**Recommendation:** present BSM as `r_sf` (mean IoU 0.647 vs 0.639) and show the stateful-vs-stateless curve, not the normalized-gain delta between adapter versions.

### 7.2 The BSM system prompt hardcodes the task's ground-truth grid

`systems/mubit_bsm/system.py`, `BSM_SYSTEM_PROMPT`, injected into **every** LLM call in `_respond_bsm` (line: `llm_messages.insert(0, {"role": "system", "content": BSM_SYSTEM_PROMPT})`):

> "Key insight: transmitters follow a regular grid pattern. Wideband channels are spaced 24 MHz apart (center = slot × 24 + 7.5 MHz, bandwidth = 15 MHz). Narrowband channels (bandwidth = 5 MHz) sit inside the guard gaps between wideband channels.
> If you have observed wideband channels at slots 0-4, you should INFER that slots 5 and 6 likely also exist (**at 127.5 and 151.5 MHz**), even if you haven't seen them yet."

The artifacts confirm the ground truth matches this formula exactly (observed wideband reports at 31.5 and 79.5 MHz = slot 1 and slot 3 of `slot × 24 + 7.5`). The prompt names two specific frequencies that are ground truth.

`git log -S'24 MHz apart'` shows this text was introduced in **7d85ee6 (2026-08-10 18:25, "BSM optimization: structured transmitter registry")** and is still present at HEAD. The commit **819d134 (22:02) "Revert BSM to legitimate v2 results (structured registry, no hardcoded grid)"** reverted the *results*, not this prompt. The v4 artifact's run 0 started **2026-08-10T23:19:29**, i.e. after that revert and with this prompt still in place.

The commit message for v4 says "legitimate, no hardcoding". The code comment `# Infer missing grid channels by pattern detection (NOT hardcoded)` is accurate about `_infer_grid_channels()`, but the system prompt is a separate channel that does contain the grid.

**Recommendation:** do not put BSM v2/v4 numbers in a demo without either (a) re-running with a neutral system prompt, or (b) an explicit on-screen disclosure. **BSM v1 (`mubit-bsm-3.5flash`, `mubit_genai`, g_b 11.6%) does not use this prompt and is clean.**

### 7.3 `chart_data.json` chart 1 duplicates competitor numbers between two different tasks

```json
{"task": "Database Exploration", "ICL (GPT-5.4)": 20.1, "Mem0 (GPT-5.4)": 20.2, "ACE (GPT-5.4)": 8.6}
{"task": "Exploitable Poker",    "ICL (GPT-5.4)": 20.1, "Mem0 (GPT-5.4)": 20.2, "ACE (GPT-5.4)": 8.6}
```
Identical competitor values for two unrelated tasks. At least one row is wrong. `charts/chart1_gain_comparison.png` renders this error. **Fix or drop before demoing.**

### 7.4 README and `chart_data.json` disagree on poker because they use different runs

- README: "Exploitable Poker — quick_test (5 hands): Mubit **7.5%**, ICL 1.7%"
- `chart_data.json`: `"Exploitable Poker": {"Mubit": -1.0}`, `summary_stats.poker.verdict: "Memory hurts — cards are independent per hand"`

Both are real: 7.5% is `mubit-quick-3` (5 hands), −1.0% is `mubit-poker-v5-3.5flash` (120 hands). **The 5-hand number is the one that should be dropped** — n=5 with a 3-run mean is noise, and the 120-hand result contradicts it. Showing 7.5% while a 120-hand run says −1.0% is the single most obvious thing a skeptical viewer will find.

### 7.5 The drift story favours ICL, not Mubit

| System | pre-drift mean gain | post-drift mean gain | relative increase |
|---|---|---|---|
| `mubit-db-3` | +0.1122 | +0.1478 | **+31.7%** |
| `icl-db-3` | +0.0844 | +0.1355 | **+60.5%** |

Mubit's gain does rise after the migration, and Mubit's absolute post-drift gain (0.1478) is higher than ICL's (0.1355). But ICL's *relative* improvement is nearly double. `charts/chart5_drift_adaptation.png` annotates "+32% gain increase after schema drift" pointing at Mubit while plotting ICL's larger jump right beside it. Reframe to the absolute comparison, or the chart argues against itself.

Also note the underlying driver: `mubit-db-3` stateless reward actually *fell* post-drift (r_sl pre 0.0533 → post 0.0467) while ICL's *rose* (0.0233 → 0.0467). Part of the "post-drift gain increase" is baseline movement, not learning.

### 7.6 `chart_data.json` chart 6 numbers don't match the artifacts

`chart_6` lists ICL `db_efficiency: "17%"`. The artifact value is `icl-db-3` score mean = **0.145 (14.5%)**. Mubit's "18%" matches (0.180). ICL/Mem0/ACE IoU values (51/37/22%) and ACE's "$62.8/run" are paper figures — **[NOT IN REPO]**, unverifiable here.

### 7.7 Rendering bugs in the existing PNGs

- **`chart2_bsm_learning_curve.png`** and **`chart4_per_run_consistency.png`**: `mticker.PercentFormatter(decimals=0)` is applied to axes whose data is already in 0–1 range. Every y-tick in chart 2 reads "0%" or "1%"; every x-tick in chart 4 reads "0%" or "1%". Both axes are unreadable. Fix: `PercentFormatter(xmax=1, decimals=0)`.
- **`chart2`**: a 3-wide `np.convolve` moving average is applied before plotting, and raw points are subsampled `[::5]`. The smoothing materially flatters the curve and the legend does not disclose it.
- **`chart4`**: title renders *inside* the plot area and the three reference lines' labels float above the axes, detached. Also `np.random.uniform` jitter with no seed → the chart is not reproducible.

---

## 8. Recommended demo visuals

All of these are backed by data already on disk unless marked. Ordered by persuasive strength.

| # | Visual | Chart type | Exact data path(s) | Why it's persuasive |
|---|---|---|---|---|
| **1** | **Spectrum occupancy ribbon, scan-by-scan** — a horizontal 0–168 MHz band per scan, with true-available regions, agent-claimed-available regions, and their overlap drawn as layered bars. Scrub or animate across 90 scans. | Animated/scrubbable stacked interval plot (SVG or canvas) | `run_traces[i].trace.result.metrics.scan_results[k].scoring.checks[]` filtered by `type ∈ {gt_available, reported_available, overlap}` using `center_freq` ± `bandwidth/2`; overlay `scan_results[k].report.transmitters[]`; headline value `scan_results[k].scoring.score` | This is the only visual that shows *the thing itself*, not a metric about the thing. Scan 1 = score 0.2391 with 3 sloppy claimed regions; scan 90 = score 1.000 with all 13 regions exact. The audience watches the band snap into focus. Nothing else in the repo comes close. |
| **2** | **Stateful vs stateless, unsmoothed, with per-run spread** — 90-point IoU curves, mean line + min/max band from the 3 runs. | Line + shaded band | `summary.aggregate.mean_reward_by_index` (90) and `.baseline_reward_by_index` (90); band from `summary.runs[i].aggregate.reward_by_index` | The gap is enormous and constant: stateless hovers 0.19–0.32 for all 90 scans while stateful climbs 0.24 → ~0.80. It needs no smoothing and no normalization to land. Replaces broken `chart2`. |
| **3** | **Memory accumulation vs performance, dual axis** — `registry_size` (2 → 21, saturating ~scan 60) against IoU. | Line + step line, dual y | `interactions[k].response.metadata.registry_size` (BSM v2/v4); IoU from `scan_results[k].scoring.score` | Directly visualizes the causal claim "the memory fills up, then performance rises." The saturation point and the performance inflection are both visible. Genuinely mechanistic, not just outcome-reporting. |
| **4** | **Head-to-head on the clean comparison: Mubit vs ICL vs Mubit+reinforcement on Database Exploration** — grouped bars for g_b, accuracy, and mean input tokens. | Grouped bar, 3 panels | g_b from `analyze()`; `aggregate.metrics.accuracy.mean`; `aggregate.execution.usage.respond.input_tokens.mean` | The only fully-controlled head-to-head in the repo (same task, seed, model, 3 runs). Mubit 13.7% / 31.7% acc / 3.23M tokens vs ICL 11.4% / 19.2% acc / 6.40M tokens. Beating ICL on accuracy by 12.5 points at half the input tokens is the strongest defensible claim available. |
| **5** | **Context growth: ICL vs Mubit** — per-step input tokens over a full 40-question run. | Two-line step chart, log or linear y | ICL: `interactions[k].response.metadata.context_tokens` (522 → 96,260); Mubit: `interactions[k].usage.respond.input_tokens` (sawtooth, resets per question, max 37,183) | ICL's line is a runaway ramp; Mubit's is a bounded sawtooth. Instantly communicates *why* memory beats stuffing the context. Uses only real per-step values. |
| **6** | **Opponent-regime drift on poker** — 120-hand cumulative profit with 5 shaded opponent bands. | Line with categorical background bands | `trace.result.metrics.hand_history[k].total_profit` and `.variant_id`; boundaries at hands 1/21/51/61/96 | Completely unused today and the cleanest drift narrative in the repo: the opponent type changes 4 times and you can watch adaptation (or failure) per regime. Honest either way. |
| **7** | **Per-question outcome grid, DB** — 40 cells × 3 runs, coloured correct/incorrect, sized or annotated by `num_queries`, with a vertical rule at Q20. | Heatmap / waffle | `trace.result.metrics.question_history[k].{correct, num_queries, question, submitted_answer, ground_truth}` | Every cell is clickable to reveal the real question text, the agent's answer and the ground truth (e.g. Q114: answered 20.95, truth 22.09). Turns an abstract accuracy number into 40 inspectable facts. Also honestly shows the misses. |
| **8** | **Per-run consistency dot plot** — 3 dots per system with the mean marked. | Dot plot | `summary.runs[i].score` for the comparable group | With n=3 this is the *honest* form: show all three points rather than a bar with an implied CI. BSM v4: 0.6022 / 0.6871 / 0.6512. DB Mubit: 0.205 / 0.1217 / 0.2133 vs ICL 0.1133 / 0.1767 / 0.145 — visibly overlapping, which you should not hide. Replaces broken `chart4`. |
| **9** | **Cumulative normalized gain** — `cumulative_mean_gain_by_index` for Mubit vs ICL on DB. | Two-line chart | `summary.aggregate.cumulative_mean_gain_by_index` (40 pts each) | Shows Mubit starting *negative* (−0.022, −0.100, −0.104 for the first three questions — memory costs before it pays) and crossing above ICL and staying there, ending 0.130 vs 0.110. The early dip makes it credible rather than glossy. |
| **10** | **Latency / cost per instance** — mean latency by index, Mubit vs ICL. | Line or box | `summary.aggregate.mean_latency_by_index`, `.mean_cost_by_index` (2.5-flash artifacts only) | Useful as an honest "what does this cost" panel: Mubit run 0 wall 1039 s vs ICL 1655 s; mean cost $1.073 vs $1.113 — essentially equal cost, better result. Note: **cost is null/zero on all gemini-3.5-flash artifacts.** |

### Charts to retire or fix

- `chart1_gain_comparison.png` — **retire** until §7.3 duplicated competitor values are corrected, and until the poker column resolves §7.4.
- `chart2_bsm_learning_curve.png` — **rebuild** (axis bug + undisclosed smoothing) → replaced by visual #2.
- `chart3_optimization_progression.png` — **retire or reframe**: the v1→v2→v4 gain progression is the §7.1 baseline artifact. If kept, plot `r_sf` (0.310 → 0.638 → 0.647), not `g_b`.
- `chart4_per_run_consistency.png` — **rebuild** (axis bug, unseeded jitter, title inside plot) → replaced by visual #8.
- `chart5_drift_adaptation.png` — **reframe** per §7.5; the current annotation argues against itself.

---

## 9. Suggested demo UI flow

A single scrolling page with a sticky scrubber, five acts:

**Act 0 — Hero.** One sentence and one number. Recommend: *"On CL-Bench Database Exploration, Mubit reaches 31.7% accuracy vs in-context learning's 19.2% — using half the input tokens."* (Real, controlled, defensible.) Do **not** hero the BSM 53.7%.

**Act 1 — The mechanism, shown not told (visual #1).** Full-bleed spectrum ribbon with a scan scrubber, autoplaying scan 1 → 90. Left: the raw peaks the sensor detected this scan. Centre: the band with true-available / claimed-available / overlap. Right: the running IoU. The viewer sees a messy 3-region guess become a 13-region exact match. Sticky counter: `registry_size`.

**Act 2 — Head-to-head (visuals #4, #5, #8).** Three compact panels side by side: gain, accuracy, tokens. Then the context-growth chart directly underneath as the "why". Then the per-run dot plot as the "and here is all the data, n=3."

**Act 3 — Learning over time (visuals #2, #9, #3).** The stateful-vs-stateless band chart, then cumulative gain with the early-negative region called out explicitly ("memory costs before it pays — first 4 questions are net-negative"), then memory-size vs performance.

**Act 4 — Drift (visuals #6, #7).** Poker opponent bands, then the DB question grid with the Q20 migration rule. Callout with the real evidence: table `attrs_g3` → `product_attributes_g3`. State the ICL comparison honestly here rather than hiding it.

**Act 5 — Memory inspection + replay (the hero interactive, below).**

**Act 6 — Method & caveats.** n=3, models used per artifact, what `g_b` means, r_max values, and the §7 disclosures you choose to keep.

### Hero interactive element — "Replay the agent, see what it remembered"

This is genuinely supported by the data and is the thing no competitor demo will have.

A three-pane replay for `mubit-db-3` run 0 (312 steps) or `mubit-poker-full-3.5flash` run 0 (263 steps):

- **Left — the memory store.** A live list of lessons, each keyed by real `retrieved_lessons_meta[k].id` (e.g. `647144ae-e7d4-4b55-bb5c-44b7b91eb666`). Lessons appear as they are first seen; the ones retrieved for the current step glow. Counter: "34 lessons learned, 6 recalled now." All from `retrieved_lessons_meta`.
- **Centre — the step.** `query.prompt` at top (the actual question / hand / scan), `response.action` beneath (the SQL, the poker action + its `thinking` text), `observation.content` below (the query result, the showdown, the error message).
- **Right — running score.** Sparkline of `reward_by_index` with the current instance marked, plus `timing.response_latency_seconds` and `usage.respond.input_tokens` for the step.

Playback control scrubs `step_number`. A toggle switches to the **baseline_trace** for the same instance so the viewer sees the identical question answered *without* memory — this is the money shot, and it works because `baseline_trace.instance_traces` gives you per-instance baseline sub-traces for DB (40 of them, e.g. `instance_traces[0].interactions` = 12 steps).

Suggested scripted moment: DB run 0, step 16 — the first step where a lesson is retrieved, and the lesson is literally *"Question 1: INCORRECT. Your answer: 3. Correct answer: 58."* The agent is being handed its own past failure. That is the product, in one screenshot.

---

## 10. Gaps — what a demo would want that is NOT in the data

### Absent entirely (would need new collection)

| Missing | Status | Impact |
|---|---|---|
| **ICL baseline for BSM** | **Absent.** No `icl-bsm-*` artifact exists. | Every BSM-vs-ICL claim in `chart_data.json` is a paper figure, not measured here. Blocks the strongest task from having a real head-to-head. |
| **ICL baseline for 120-hand poker** | **Absent.** Only `icl-quick-3` (5 hands). | Poker head-to-head only exists at n=5. |
| **Mem0 / ACE / ICL-Notepad runs** | **Absent.** Zero artifacts. | All competitor bars are paper values. Must be labelled as such on screen. |
| **The memory store's contents** | `trace.system_memory` is `None` in all 12 files; `system_artifacts` `None`; `artifacts.instances[i]` = `{"type":"mubit"}`. | You can only show lessons that were *retrieved*, never the full store, never lessons written-but-never-recalled. No forgetting/eviction/dedup story. |
| **Lesson write events** | Only reads (`retrieved_lessons`) are recorded. No `remember()` record, no timestamps, no `intent`, no `record_outcome()` reinforcement events. `retrieved_lessons_meta[k].metadata` is `{}`. | Cannot show *when* a lesson was created or how reinforcement changed its weight. The `mubit_full` reinforcement story is invisible in the data. |
| **BSM registry contents** | Only `registry_size` (int) and `scan_peaks` (int). | Cannot show the registry table with `hit_count` / `first_seen_scan` / `inferred` flags that the code maintains. |
| **The augmented prompt actually sent to the LLM** | `query.prompt` is the harness-side prompt. Verified: BSM prompts contain no `REGISTRY` block despite the adapter injecting one. | Cannot show "here is exactly what the model saw" for BSM. Works for poker/DB only because lessons are separately mirrored into `response.metadata`. |
| **BSM per-scan stage/variant labels** | `scan_results[i]` has only `scan_idx`, `scoring`, `report`. Run-level `variant_id` is a single string. | The stage boundaries at scan 30/60 in `chart_data.json` are assumptions. Annotate them as such or drop them. |
| **Retrieval scores / ranks** | `retrieved_lessons` is an ordered list with no similarity scores. | No "why was this lesson retrieved" panel. |
| **Error / failure logs** | `blocked_instances` is `[]` and `instances_blocked` is `0` in every artifact; `coverage_ratio` = 1.0 throughout. | No failure-mode story — though this also means no runs were dropped, which is good for credibility. |
| **Statistical tests** | Nothing. n=3 per config. | Cannot show CIs or p-values honestly at n=3. |

### Present but degraded

| Field | Problem |
|---|---|
| `cost_usd`, `mean_cost_by_index`, `aggregate...usage.cost_usd` | **Zero or null on every gemini-3.5-flash artifact** (all BSM, both 120-hand poker, both genai DB). Real only on the 5 gemini-2.5-flash artifacts. Any cost chart is limited to DB 2.5-flash + poker quick_test. |
| `mean_latency_by_index` | One `null` at index 119 in both 120-hand poker artifacts (119/120 non-null). Handle it. |
| `reasoning_tokens` | Present with `reasoning_tokens_complete: false` on some calls and `missing_reasoning_token_count: 3` on the poker baseline. Slightly lossy. |
| `cached_input_tokens` | Always 0 with `cached_input_tokens_complete: false` and `missing_cached_input_token_count` = call count. Effectively unmeasured — no prompt-caching story. |
| `summary.system.params.system_prompt` | `''` on all three BSM artifacts, so the artifact does **not** record the adapter's internal `BSM_SYSTEM_PROMPT`. Provenance for §7.2 had to come from source + git history, not the data. |
| `question_history[*].difficulty` | All 40 are `"hard"`. No difficulty breakdown possible. |
| `observation.metadata` | Nearly empty — `{'done'}` for poker, `{'instance_complete'}` for DB, `{}` for BSM. |

### Cheap additions that would unlock a lot

1. Log `remember()` writes with timestamp + intent into `trace.system_memory` — unlocks a true memory-timeline and forgetting story.
2. Emit the final memory store into `get_run_artifacts()` — unlocks "here is everything it learned" as a browsable list.
3. Store the augmented prompt (or a diff vs `query.prompt`) — unlocks "what the model actually saw" for BSM.
4. Run one ICL baseline on BSM at gemini-3.5-flash — converts the best visual from a solo curve into a real head-to-head.
5. Tag `scan_results[i]` with the stage/variant — makes the stage annotations data rather than assumption.
6. Raise n from 3 to 10 on the DB comparison — the per-run scores currently overlap between Mubit and ICL (§7.4 in the dot-plot sense).

---

## 11. Caveats to put on screen

Be blunt about these; a skeptical viewer will find them in minutes.

1. **n = 3 runs everywhere.** No config has more. Per-run DB scores overlap between systems (Mubit 0.205/0.1217/0.2133 vs ICL 0.1133/0.1767/0.145). Show all three dots, never a bar with an implied error bar.
2. **Mubit's own runs use different models than the paper's competitors.** Mubit results here are gemini-2.5-flash or gemini-3.5-flash; all Mem0/ACE/ICL comparison numbers are GPT-5.4 paper figures **[NOT IN REPO]**. `chart_data.json` notes this in a `note` field; the rendered PNG does not.
3. **BSM +53.7% is a baseline artifact** (§7.1) and **the BSM v2/v4 system prompt contains the task's ground-truth grid geometry, including two exact ground-truth frequencies** (§7.2). Either disclose or use BSM v1 (11.6%).
4. **Poker is contradictory:** +7.5% at 5 hands, −1.0% and −1.4% at 120 hands. The honest reading is that memory does not help on poker. Say so — it makes the DB and BSM claims more credible, not less.
5. **The drift claim is weaker than the README implies:** ICL's post-drift relative gain increase (+60.5%) exceeds Mubit's (+31.7%), and part of Mubit's increase comes from its stateless baseline falling (0.0533 → 0.0467) rather than its stateful reward rising (§7.5).
6. **Accuracy and normalized gain point in opposite directions on DB.** `mubit-genai-db-full-3.5flash` has the best accuracy in the repo (71.7%) but nearly the worst gain (1.1%), because it burns 13.6 queries/question against a 15 budget so the stateless baseline does nearly as well. Pick one metric and explain why, or show both and explain the tension.
7. **Cost data is missing for every gemini-3.5-flash run.** Do not show a cost chart covering BSM or 120-hand poker.
8. **`chart_data.json` currently contains at least one copy-paste error** (§7.3) and one figure that contradicts the artifacts (§7.6). Regenerate it from the artifacts before it feeds a demo.
