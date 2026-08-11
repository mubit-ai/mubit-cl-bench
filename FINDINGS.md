# Findings — what the data supports

**Branch:** `viz-instrument` · **Date:** 2026-08-11 · **Source:** `results/*.json.gz` only

This is the output of an analysis pass, not a demo. Its job was to decide what a
demo is allowed to claim. Every number below was re-derived from the artifacts by
`scripts/extract.py`; `chart_data.json`, `README.md` and `DEMO_DATA_REPORT.md` were
treated as claims to test, never as sources. No benchmark was re-run.

**Reproduce:** `python3 scripts/extract.py` (stdlib only), then open `viz/index.html`.

---

## 0. Verification gate

**125 checks re-derived from the artifacts. 0 mismatches.** Every claim in
DEMO_DATA_REPORT.md §1, §5, §6, §7, §11 that is derivable from the artifacts
reproduces within the report's own displayed precision. The report is accurate.

That result matters mainly because §7 is a list of accusations against this repo's
own published numbers. They all hold.

---

## 1. Verdicts on each §7 accusation

| # | Accusation | Verdict | The number that settles it |
|---|---|---|---|
| 7.1 | BSM's +53.7% is a baseline artifact, not learning | **CONFIRMED** | Stateful 0.6385 → 0.6468 (+1.3%). Stateless 0.4697 → **0.2366** (−49.6%) |
| 7.2 | BSM v2/v4 system prompt contains ground-truth grid frequencies | **OPEN — not testable here** | Lives in source + git history, not in any artifact |
| 7.3 | `chart_data.json` duplicates competitor values across two tasks | **CONFIRMED** | Database and Poker rows are byte-identical: ICL 20.1 / Mem0 20.2 / ACE 8.6 |
| 7.4 | README and `chart_data.json` disagree on poker | **CONFIRMED** | +7.5% at 5 hands; −1.0% and −1.4% at 120 hands |
| 7.5 | The drift story favours ICL, not Mubit | **CONFIRMED** | Relative post-drift gain increase: Mubit +31.68%, ICL +60.51% |
| 7.6 | `chart_data.json` chart 6 contradicts the artifacts | **CONFIRMED, but narrower than stated** | ICL `db_efficiency` "17%" vs actual 14.5%. Mubit's "18%" and "65%" are both correct |
| 7.7 | Rendering bugs in the committed PNGs | **NOT RE-TESTED** | Charts rebuilt from scratch instead; old pipeline left untouched |

### 7.1 in more detail — the mechanism is sharper than the report says

The report attributes the baseline collapse to v4's `_filter_to_registry` post-filter.
Measured across all three runs, that filter moved:

- the **stateful** system from 16.74 → 16.16 reported transmitters per scan (**−3.5%**)
- the **stateless** baseline from 8.11 → 3.31 (**−59%**)

It barely touched the system it was written for and gutted the control. In v2 the
baseline over-reported often enough to hit accidental exact matches — **10 of its 90
scans scored IoU 1.000**. In v4, zero do, and its best scan is 0.320.

**Ruling:** the +53.7% figure must not be presented as evidence of learning. Present
`r_sf` (0.647) against `r_sl` (0.237) with the per-scan curve, or present v1.

---

## 2. Findings the report does not contain

### 2.1 The stateless control's per-scan spectrum geometry is recoverable

The report states `baseline_trace.result.metrics` is empty. That is true, but
`baseline_trace.instance_traces[i].result.metrics.scan_results[0]` holds one fully
scored scan each — 90 of them, stitchable by `scan_idx`.

**Consequence:** the spectrum occupancy visual can show stateful *beside* stateless
rather than stateful alone. That is what turns §7.1 from an assertion into something
visible: the stateless band never resolves, across all 90 scans. This is the single
best asset produced by this pass.

### 2.2 On Database Exploration, accuracy separates at n=3 — normalized gain does not

| Artifact | Accuracy (min → max over 3 runs) | Per-run score |
|---|---|---|
| `icl-db-3` | 0.175 → 0.225 | 0.113 / 0.177 / 0.145 |
| `mubit-db-3` | **0.250 → 0.375** | 0.205 / 0.122 / 0.213 |
| `mubit-full-db-3` | **0.300 → 0.375** | 0.222 / 0.193 / 0.130 |

Mubit's **worst** accuracy run (0.250) beats ICL's **best** (0.225). No overlap, in
either memory configuration. The report's §11.1 warning about overlapping runs is
correct — but it is about the gain-derived *scores*, and it does not carry over to
accuracy.

**Ruling:** accuracy is the defensible head-to-head claim. Normalized gain on this
task is not separable at n=3 and should not be the headline.

### 2.3 "Half the input tokens" is an artifact of one outlier run

The 6.40M vs 3.23M comparison is a mean of three. ICL's three runs are
**10,317,862 / 4,230,964 / 4,639,859** — run 0 is more than double the other two and
drags the mean up. Mubit's are 3,216,449 / 3,748,460 / 2,715,562.

The ranges still separate (Mubit's max 3.75M sits below ICL's min 4.23M), so the
direction is real. The magnitude is not.

**Ruling:** claim "consistently fewer input tokens across every run," not "half."
Do not use the 2× framing. Cost tells the same story: ICL $1.73 / $0.78 / $0.83 vs
Mubit $1.03 / $1.29 / $0.90 — overlapping, i.e. **cost is a wash**, and ICL's mean is
again inflated by run 0.

---

## 3. What each task can claim

### Database Exploration — the only clean head-to-head in the repo

Same task, same seed, same 40 instances, same model, 3 runs each.

- **Can claim:** accuracy 31.7% (Mubit) and 33.3% (Mubit+reinforcement) against ICL's
  19.2%, with no run-to-run overlap, at consistently lower input-token usage and
  equal cost.
- **Cannot claim:** a normalized-gain win (13.7% vs 11.4% — the per-run scores
  overlap), or a 2× token reduction.
- **Must disclose:** the two `mubit_genai` artifacts reach the best accuracy in the
  repo (66.7% and 71.7%) at nearly the worst gain (1.9%, 1.1%), because they spend
  13.5 of a 15-query budget so the stateless baseline nearly matches them. Accuracy
  and gain point in opposite directions here; pick one and say why.

### Blind Spectrum Monitoring — the best visual, the worst provenance

- **Can claim (v1, `mubit-bsm-3.5flash`):** 11.6% normalized gain. This adapter does
  not use the disputed system prompt and is clean.
- **Blocked pending §7.2 (v2, v4):** everything else on this task, including the
  occupancy heatmap, the 0.647-vs-0.237 comparison, and the unsafe-bandwidth curve —
  which is otherwise the most persuasive chart produced by this pass (stateful
  reaches 0 unsafe MHz; the control holds ~100 MHz for all 90 scans).
- **Must never claim:** +53.7% as a learning result. See §7.1.
- **No ICL counterpart exists** for this task at any model, so no head-to-head is
  possible without new runs.

### Exploitable Poker — memory does not help

- **The honest reading:** at 5 hands, +7.5%; at 120 hands, −1.0% and −1.4%. The
  120-hand result is the one with enough data behind it. Memory does not help on
  poker, and at 120 hands the system scores below its own stateless control
  (r_sf 0.297 vs r_sl 0.386).
- **Recommendation:** say so explicitly. It costs nothing and makes the Database
  claim more credible, not less. Drop the 5-hand number entirely — n=5 × 3 runs
  cannot support a claim in either direction.
- **No ICL counterpart at 120 hands.**

---

## 4. Actions required before any demo

1. **Resolve §7.2.** Read `BSM_SYSTEM_PROMPT` in `systems/mubit_bsm/system.py` and
   decide: re-run v4 with a neutral prompt, disclose on screen, or use v1 only. This
   is the one open item and it gates the strongest visual.
2. **Regenerate `chart_data.json` from `scripts/extract.py`.** It currently carries a
   duplicated competitor row (§7.3) and one wrong cell (§7.6).
3. **Retire or rebuild `charts/*.png`.** Left untouched by this pass, and per §7.7
   they contain axis bugs and undisclosed smoothing. They are committed at HEAD.
4. **Decide the poker framing** — currently README says +7.5% and `chart_data.json`
   says −1.0%. Both are real; they are different runs. One has to go.
5. **Never ship paper figures without on-screen labelling.** Mem0, ACE and
   ICL-GPT-5.4 have zero artifacts in this repo. This instrument omits them entirely.

## 5. Cheap data changes that would unlock the most

1. One ICL baseline on BSM at gemini-3.5-flash — converts the best visual from a solo
   curve into a real head-to-head.
2. Raise n from 3 to 10 on the Database comparison — would settle whether the gain
   claim separates, as accuracy already does.
3. Log `remember()` writes into `trace.system_memory` (currently `None` in all 12
   artifacts) — unlocks a memory-timeline and any forgetting/reinforcement story.
   Today only *retrieved* lessons are visible, never the store.

---

## 6. What this pass built

`scripts/extract.py` → `viz_data/` → four pages under `viz/` (open `viz/index.html`
directly from disk; no server, no build).

| Page | Contents |
|---|---|
| `index.html` | Verification gate, per-artifact gain in comparability bands, paired r_sf/r_sl, per-run dots, and an explicit list of what was never measured |
| `bsm.html` | Frequency × scan occupancy heatmap for stateful **and** stateless, unsmoothed IoU curves with min/max envelope, registry accumulation, unsafe-bandwidth curve, and the §7.1 finding |
| `db.html` | Head-to-head panels, accuracy-vs-gain tension, context growth, cumulative gain, drift, per-question grid, per-run dots, latency and cost |
| `poker.html` | The 5-vs-120 contradiction, opponent-regime drift, stateful-vs-stateless, per-run dots, per-regime profit, latency |

Conventions held throughout: mean line with a **min/max** envelope (never a bar with
an error bar at n=3); artifacts grouped into comparability bands so different models
never sit adjacent; red reserved exclusively for unsafe spectrum claims; measured
data only, with missing counterparts drawn as labelled empty slots; no smoothing
anywhere; a table view on every chart.

**Deferred:** the three-pane agent replay. It is persuasive but it cannot tell you
whether a claim is true, which was this pass's only job. The interaction-level data
it needs is already extracted.
