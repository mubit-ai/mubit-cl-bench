# Upstream issue draft — `pgasawa/continual-learning-bench`

Not filed. Draft for review before posting.

---

## Baseline instance slicing does not sync task environment state — the control answers post-drift questions against the pre-drift database

### Summary

`_run_baseline_instance` runs each baseline instance against a task sliced to
that one instance (`src/runs/baseline.py:58`, via
`ContinualLearningTask.reset_baseline_instance` →
`select_run_instances([i])`). `select_run_instances` replaces `self.instances`
with a one-element list and sets `num_instances = 1`.

`src/interface.py:508-517` documents the obligation this creates:

> Tasks with additional environment or metadata state should override it,
> typically by syncing that state and then calling
> `super().select_run_instances(instance_indices)`.

`database_exploration` does not override it, and it has exactly that kind of
state — the schema-drift machinery. Three defects follow, in descending order
of severity. All are reproducible from a clean checkout.

`cohort_studies` shares defects **B** and **C**; `codebase_adaptation` shares
**C**.

---

### A. Schema drift is never applied to a baseline instance

`_sync_stage_context` (`src/tasks/database_exploration/task.py:819`) is the only
caller of `_swap_to_drifted_db`, and it is gated on:

```python
if self._current_question_idx >= self._pre_drift_count:
```

In a sliced baseline task `_current_question_idx` is always `0` and
`_pre_drift_count` is the variant's pre-drift count (10 for `demo_drift`, 20 for
`schema_drift`), so the condition is never true. It is also only reached from
`step()` when an instance completes and the run is *not* done
(`task.py:281-282`) — a one-instance run is always done at that point.

The baseline therefore answers **every** post-drift question against
`products.db` while the stateful arm answers them against
`products_drifted.db`.

```
STATEFUL arm at question 15 (post-migration)
  tables: attrs_g1, attrs_g3_legacy, fdbk_g1..g3, fdbk_stats_g1,
          items_g1..g3, product_attributes_g3, taxn_g1, taxn_g2

BASELINE worker, same question (instance_id 110)
  tables: attrs_g1, attrs_g3,      fdbk_g1..g3, fdbk_stats_g1,
          items_g1..g3,                         taxn_g1, taxn_g2
```

This is not cosmetic. Ground truth for the post-drift pool is computed against
the drifted database, and the drift adds columns as well as renaming tables:

| check against `questions_post_drift.json` (20 questions) | result |
|---|---|
| stored `answer` reproduced by reference SQL on `products_drifted.db` | **20 / 20** |
| stored `answer` reproduced by reference SQL on `products.db` | **0 / 20** |
| reference SQL raises `OperationalError` on `products.db` | **19 / 20** |
| reference SQL returns a different value on `products.db` | 1 / 20 |

Sample failures on the pre-drift database:

```
q101: sqlite3.OperationalError: no such column: prc_v2
q102: sqlite3.OperationalError: no such column: i.prc_v2
q106: sqlite3.OperationalError: no such column: i.status
```

So on `schema_drift` variants the control is scored on a half of the benchmark
where the data required to answer is absent from its database. Since
`g_b = (r_mem − r_base) / (r_max − r_base)`, depressing `r_base` inflates the
reported gain, and the inflation is concentrated entirely in the post-drift
half.

The effect is partly masked by a floor: these questions are `difficulty: hard`
and both arms score near zero, so the published 3-run baseline still shows
4/20 pre-drift versus 2/20 post-drift rather than a collapse. That the gap is
small does not make the comparison sound — for the post-drift half the baseline
is not measuring "no-memory performance", it is measuring performance on an
unanswerable task.

### B. `Query.instance_index` is the local index, not the canonical one

`database_exploration/task.py:590` passes `instance_index=self._current_question_idx`.
After slicing that is `0` for every baseline instance, so all N baseline
instances report position 0 — in the live queries, and in
`summary.baseline.instance_outcomes` of the published artifacts. Only
`instance_id` distinguishes them.

`canonical_instance_index()` exists on the interface (`src/interface.py:528`)
for precisely this, and four of the six tasks already use it:

| task | uses of `canonical_instance_index` |
|---|---|
| `sales_prediction` | 7 |
| `codebase_adaptation` | 7 |
| `blind_spectrum_monitoring` | 4 |
| `exploitable_poker` | 3 |
| **`cohort_studies`** | **0** |
| **`database_exploration`** | **0** |

### C. The agent-visible position counter collapses to `1/1`

`task.py:559` builds the prompt header from `total = len(self.instances)`, which
is 1 after slicing. The stateful arm reads `Question 4/20`; the control reads
`Question 1/1` for every question in the run.

This is an uncontrolled difference between the two arms being compared — it
tells one arm it is mid-sequence and the other that it is answering a
standalone question, which is information unrelated to the treatment.

Same pattern elsewhere:

- `cohort_studies/task.py:430-431` — `instance_num` / `total_instances` rendered
  into `instance_brief.j2`
- `codebase_adaptation/task.py:945` — `f"--- Issue {self.current_issue_idx + 1}/{len(self.instances)} ---"`

---

### Reproduction

No API keys or model calls; needs only `clbench setup` data.

```python
import sqlite3
from src.tasks.database_exploration.task import DatabaseExploration as T

# stateful arm, walked to question 15 (post-migration)
full = T(variant="demo_drift", schedule="demo_drift")
full.build_canonical_run_state(); full.select_run_instances(None)
full._current_question_idx = 15
full._sync_stage_context()
q_full = full.build_current_query()

# baseline worker for the SAME question — what _run_baseline_instance does
base = T(variant="demo_drift", schedule="demo_drift")
q_base = base.reset_baseline_instance(15)

def tables(path):
    c = sqlite3.connect(path)
    t = sorted(r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
    c.close(); return t

def counter(p):
    return next(l for l in p.splitlines() if l.startswith("Question "))

assert q_full.instance_id == q_base.instance_id          # same question
print(q_full.instance_index, q_base.instance_index)      # 15 0          <- B
print(counter(q_full.prompt))                            # Question 16/20
print(counter(q_base.prompt))                            # Question 1/1  <- C
print(full._drift_applied, base._drift_applied)          # True False    <- A
print(set(tables(q_full.metadata["db_path"]))
      ^ set(tables(q_base.metadata["db_path"])))         # {attrs_g3, attrs_g3_legacy,
                                                         #  product_attributes_g3}
```

(The stateful arm's *first* line at this point is the `NOTICE:` stage-change
text, which the baseline never receives — a fourth difference, discussed under
**A** above.)

```
```

### Suggested fix

**A** — override `select_run_instances` in `database_exploration` to sync stage
state to the canonical index being selected, per the interface docstring:

```python
def select_run_instances(self, instance_indices):
    super().select_run_instances(instance_indices)
    if self._schema_drift_enabled and instance_indices is not None:
        if min(instance_indices) >= self._pre_drift_count:
            self._swap_to_drifted_db()
            self._drift_applied = True
```

Whether the baseline should also receive the `NOTICE:` stage-change text is a
separate design call — it has no prior exploration to revise, so withholding it
is defensible; running it against the wrong database is not.

**B / C** — carry the canonical position and count. `canonical_instance_index`
already exists; a companion is needed for the total, since
`select_run_instances` overwrites `num_instances` before anyone can read it:

```python
# src/interface.py, in select_run_instances, before self.instances is replaced
self._canonical_num_instances = len(instances)

def canonical_num_instances(self) -> int:
    return getattr(self, "_canonical_num_instances", len(getattr(self, "instances", [])))
```

then in `database_exploration/task.py:558-559`:

```python
question_num = self.canonical_instance_index(self._current_question_idx) + 1
total = self.canonical_num_instances()
```

and the same at `task.py:590` for `instance_index`, `cohort_studies/task.py:430-431`
and `:452`, and `codebase_adaptation/task.py:945`.

### Impact on existing results

Fixing **A** changes baseline scores on every `schema_drift` variant, so
published gains for those variants are not comparable across the fix. **B** and
**C** are smaller but also change the text the control model reads, so they move
baseline scores too. Worth bundling into one release rather than landing
piecemeal.
