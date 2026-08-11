/* Shared client for the live database demo.
 *
 * One event source, one reducer, four pages. The reducer lives here rather
 * than in each page on purpose: four independent reductions of the same stream
 * is four chances for two screens to disagree about what happened, in front of
 * an audience.
 *
 * Two sources, one interface:
 *   live    — EventSource on /stream. Backlog first, then live, so a page
 *             opened at question 14 still shows the first thirteen.
 *   replay  — ?replay=<path.jsonl>[&speed=N][&from=migration]. Re-emits a
 *             recording on a scaled clock. The recording is self-contained:
 *             run.config carries the schedule and the reference bands, so
 *             replay needs no other input.
 *
 * Scores are never computed from raw task output here. Per-question rewards
 * arrive only in harness.snapshot events, digested from CL-Bench's own live
 * trace files. This file does arithmetic ON those numbers (means, normalized
 * gain) and nothing else.
 */
(function () {
  "use strict";

  const R_MAX = 1.0; // database_exploration; matches scripts/extract.py

  // ---- state ------------------------------------------------------------

  const state = {
    config: null,
    connected: false,
    caughtUp: false,
    source: null, // "live" | "replay"
    firstTs: null,
    lastTs: null,
    driftIndex: 10,
    questions: [], // index-aligned; see ensureQuestion()
    store: [], // lessons written by the stateful arm, in write order
    ledger: [], // chronological Mubit wire entries
    harness: { stateful: null, stateless: null },
    arms: { stateful: { current: null, done: 0 }, stateless: { current: null, done: 0 } },
    indexById: Object.create(null), // instance_id → true question index
    pending: [], // stateless events awaiting a mapping
    pendingOutcomes: new Map(), // baseline outcomes awaiting a mapping
    pairingConflict: null,
    dropped: 0,
    events: 0,
  };

  /* The stateless arm cannot number its own questions.
   *
   * CL-Bench runs each baseline instance in its own process against a task
   * sliced to that one instance (`reset_baseline_instance`), so the sliced task
   * reports `instance_index: 0` for whichever question it holds — every
   * stateless event and every baseline outcome claims index 0. Only
   * `instance_id` (the question id) tells them apart.
   *
   * Keying on the index that is right there in the event would silently pile
   * the entire control arm onto question 0, and it would look plausible. So
   * position comes from `instance_id`, resolved through a map learned from the
   * stateful arm — whose task is not sliced and whose indices are real.
   * Stateless events that arrive before their mapping is known are parked and
   * replayed rather than dropped or guessed at. */
  const NEEDS_SLOT = new Set([
    "instance.start", "turn.start", "recall.request", "recall.response",
    "prompt.injected", "llm.response", "env.feedback",
    "remember.request", "remember.response", "instance.end",
  ]);

  function learnMapping(id, idx) {
    if (id == null || idx == null) return false;
    const key = String(id);
    const prev = state.indexById[key];
    if (prev === idx) return false;
    // One question id must mean one position. If it ever means two, every
    // comparison downstream is suspect and the pages say so.
    if (prev !== undefined && prev !== idx) {
      state.pairingConflict = {
        instanceId: id,
        was: prev,
        now: idx,
        note: "the same question id was reported at two different positions",
      };
    }
    state.indexById[key] = idx;
    return true;
  }

  function resolveIndex(ev, arm) {
    if (arm === "stateful") return ev.instance_index;
    if (ev.instance_id != null) {
      const v = state.indexById[String(ev.instance_id)];
      return v === undefined ? null : v;
    }
    return ev.instance_index;
  }

  let draining = false;
  function drainPending() {
    drainPendingOutcomes();
    if (draining || !state.pending.length) return;
    draining = true;
    const queued = state.pending;
    state.pending = [];
    for (const ev of queued) reduce(ev);
    draining = false;
  }

  function drainPendingOutcomes() {
    if (!state.pendingOutcomes.size) return;
    for (const [id, o] of [...state.pendingOutcomes]) {
      const idx = state.indexById[id];
      if (idx === undefined) continue;
      state.pendingOutcomes.delete(id);
      const q = ensureQuestion(idx);
      if (q) applyOutcome(q, "stateless", o);
    }
  }

  /** Copy one harness instance outcome onto a question's arm. Harness fields
   *  only — nothing here is derived or recomputed. */
  function applyOutcome(q, phase, o) {
    const slot = q[phase];
    slot.reward = o.reward;
    if (o.success != null) slot.correct = o.success;
    /* The per-instance outcome is where the baseline's detail actually lives:
     * its trace carries no question_history at all, so num_queries, cost and
     * latency for the memory-OFF arm exist nowhere else. */
    const md = o.metadata || {};
    if (md.num_queries != null) slot.numQueries = md.num_queries;
    if (md.num_actions != null) slot.numActions = md.num_actions;
    if (o.cost_usd != null) slot.costUsd = o.cost_usd;
    if (o.latency_seconds != null) slot.latencySeconds = o.latency_seconds;
    if (q.difficulty == null && md.difficulty) q.difficulty = md.difficulty;
  }

  function ensureQuestion(i) {
    if (i == null || i < 0) return null;
    while (state.questions.length <= i) {
      const idx = state.questions.length;
      state.questions.push({
        index: idx,
        stage: idx >= state.driftIndex ? "post" : "pre",
        id: null,
        num: null,
        difficulty: null,
        budget: null,
        prompt: null,
        driftNotice: false,
        stateful: blankArm(),
        stateless: blankArm(),
      });
    }
    return state.questions[i];
  }

  function blankArm() {
    return {
      started: false,
      done: false,
      turns: [], // {action, content, latencyMs, usage, feedback}
      recall: null, // {query, limit, latencyMs, evidence:[…]}
      injected: null, // {lessonCount, block, charsAdded}
      wrote: null, // {content, upsertKey, metadata, latencyMs}
      reward: null, // harness only
      correct: null, // harness only
      numQueries: null, // harness only
    };
  }

  function armOf(ev) {
    return ev.arm === "stateless" ? "stateless" : ev.arm === "stateful" ? "stateful" : null;
  }

  /* Attributing a retrieved lesson back to the write that created it.
   *
   * A store row cannot know its own Mubit entry id. `mubit` calls
   * `remember(..., wait=False)`, so the ack is `{accepted, deduplicated,
   * job_id, status: "queued"}` — a JOB id, not an entry id. Writing that back
   * as the entry id would look like it worked and never match anything, which
   * is worse than admitting the gap.
   *
   * The lesson text is the join that actually holds: the content written is
   * the content that comes back as evidence, verified against a real
   * recording. Match on normalised text, then remember the entry id the
   * evidence supplies so later hits match directly. Two lessons with byte
   * identical text would collide, but `upsert_key` is unique per question and
   * the text embeds that question's feedback, so a collision would mean two
   * questions produced the same feedback and the same action. */
  /* 1000 chars, not 200. The generic distiller emits
   * "Prior instance feedback: {feedback[:200]}. My action: {action[:200]}" —
   * a 200-char window is entirely consumed by the prefix and the feedback, so
   * the action never participates and two questions that produced the same
   * long feedback would be indistinguishable. 1000 sits above the whole
   * lesson and below both wire trims (evidence 1200, content 4000), so the
   * two sides stay comparable. */
  const normText = (s) => String(s == null ? "" : s).replace(/\s+/g, " ").trim().slice(0, 1000);

  function attributeRetrievals(evidence) {
    for (const e of evidence) {
      let hit = e.id ? state.store.find((s) => s.id === e.id) : null;
      if (!hit) {
        const key = normText(e.text);
        if (!key) continue;
        hit = state.store.find((s) => normText(s.text) === key);
      }
      if (!hit) continue;
      if (!hit.id && e.id) hit.id = e.id;
      hit.retrieved++;
      hit.lastScore = e.score;
    }
  }

  // ---- reducer ----------------------------------------------------------

  const listeners = { "*": [] };

  function reduce(ev) {
    const arm = armOf(ev);

    // The stateful arm is the only source of truth for question numbering.
    if (arm === "stateful" && learnMapping(ev.instance_id, ev.instance_index)) {
      queueMicrotask(drainPending);
    }

    const index = resolveIndex(ev, arm);
    if (index == null && arm === "stateless" && ev.instance_id != null && NEEDS_SLOT.has(ev.type)) {
      state.pending.push(ev);
      return;
    }

    state.events++;
    if (state.firstTs == null) state.firstTs = ev.ts;
    state.lastTs = ev.ts;

    const q = index != null ? ensureQuestion(index) : null;
    const slot = q && arm ? q[arm] : null;
    const p = ev.payload || {};

    switch (ev.type) {
      case "run.config":
        state.config = p;
        // A schedule with no migration reports drift_index null; Infinity
        // keeps every question honestly labelled pre-migration without a
        // sentinel number leaking onto the screens.
        state.driftIndex = p.drift_index == null ? Infinity : p.drift_index;
        break;

      case "instance.start":
        if (q) {
          q.id = q.id ?? p.question_id;
          q.num = q.num ?? p.question_num;
          q.difficulty = q.difficulty ?? p.difficulty;
          q.budget = q.budget ?? p.query_budget;
          if (p.prompt && !q.prompt) q.prompt = p.prompt;
          if (p.carries_drift_notice) q.driftNotice = true;
        }
        if (slot) slot.started = true;
        if (arm) state.arms[arm].current = index;
        break;

      case "recall.request":
        if (slot) {
          slot.recall = {
            query: (p.kwargs && p.kwargs.query) ?? (p.args && p.args[0]) ?? null,
            limit: p.kwargs && p.kwargs.limit,
            entryTypes: p.kwargs && p.kwargs.entry_types,
            evidence: null,
            latencyMs: null,
          };
        }
        break;

      case "recall.response":
        if (slot && slot.recall) {
          slot.recall.evidence = p.evidence || [];
          slot.recall.latencyMs = p.latency_ms;
          slot.recall.error = p.error || null;
        }
        state.ledger.push({
          gseq: ev.gseq,
          ts: ev.ts,
          arm,
          index,
          stage: ev.stage,
          op: "recall",
          query: slot && slot.recall ? slot.recall.query : null,
          count: p.count,
          latencyMs: p.latency_ms,
          evidence: p.evidence || [],
          error: p.error || null,
        });
        /* Only the stateful arm's recalls may credit the store. `state.store`
         * holds stateful writes alone, so an unguarded call would let a
         * control-arm recall increment a stateful entry whenever their texts
         * matched — impossible under share_scope="run", reachable under a
         * shared scope, and wrong either way. */
        if (arm === "stateful") attributeRetrievals(p.evidence || []);
        break;

      case "prompt.injected":
        /* Keep the FIRST injection of the instance, not the last.
         *
         * `MubitMemorySystem.respond()` calls `_inject_memory()` on every turn
         * but only retrieves at an instance boundary, so a multi-turn question
         * emits one injection carrying the lessons followed by several empty
         * ones. Overwriting would leave every completed question claiming zero
         * lessons injected — silently erasing the one thing this whole demo is
         * about. */
        if (slot) {
          if (slot.injected == null) {
            slot.injected = {
              lessonCount: p.lesson_count,
              block: p.block || "",
              charsAdded: p.chars_added,
              injected: !!p.injected,
              turnsSeen: 1,
            };
          } else {
            slot.injected.turnsSeen++;
          }
        }
        break;

      case "llm.response":
        if (slot)
          slot.turns.push({
            action: p.action,
            content: p.content,
            latencyMs: p.latency_ms,
            usage: p.usage || null,
            retrievedCount: p.retrieved_count,
            feedback: null,
          });
        break;

      case "env.feedback":
        if (slot && slot.turns.length) {
          const t = slot.turns[slot.turns.length - 1];
          if (t.feedback == null) t.feedback = p.content;
        }
        break;

      case "remember.request":
        if (slot)
          slot.wrote = {
            content: (p.kwargs && p.kwargs.content) ?? null,
            upsertKey: p.kwargs && p.kwargs.upsert_key,
            metadata: (p.kwargs && p.kwargs.metadata) || {},
            intent: p.kwargs && p.kwargs.intent,
            lessonType: p.kwargs && p.kwargs.lesson_type,
            importance: p.kwargs && p.kwargs.lesson_importance,
            scope: p.kwargs && p.kwargs.lesson_scope,
            latencyMs: null,
          };
        // Only the stateful arm accumulates a visible store; the stateless arm
        // writes too, but into a run_id that is discarded before the next
        // question, which is precisely what makes it the control.
        if (arm === "stateful" && slot && slot.wrote) {
          state.store.push({
            id: null,
            text: slot.wrote.content,
            upsertKey: slot.wrote.upsertKey,
            metadata: slot.wrote.metadata,
            writtenAt: index,
            stage: ev.stage,
            retrieved: 0,
          });
        }
        state.ledger.push({
          gseq: ev.gseq,
          ts: ev.ts,
          arm,
          index,
          stage: ev.stage,
          op: "remember",
          content: (p.kwargs && p.kwargs.content) ?? null,
          upsertKey: p.kwargs && p.kwargs.upsert_key,
          metadata: (p.kwargs && p.kwargs.metadata) || {},
          latencyMs: null,
        });
        break;

      case "remember.response": {
        if (slot && slot.wrote) {
          slot.wrote.latencyMs = p.latency_ms;
          slot.wrote.jobId = (p.result && p.result.job_id) || null;
        }
        /* Match arm and question, not just "the newest unfilled remember".
         * Both arms write into one collector concurrently at --max-workers 2,
         * so a bare back-scan hands one arm's latency to the other whenever
         * two writes interleave. */
        for (let i = state.ledger.length - 1; i >= 0; i--) {
          const row = state.ledger[i];
          if (
            row.op === "remember" &&
            row.latencyMs == null &&
            row.arm === arm &&
            row.index === index
          ) {
            row.latencyMs = p.latency_ms;
            row.error = p.error || null;
            row.jobId = (p.result && p.result.job_id) || null;
            break;
          }
        }
        break;
      }

      case "instance.end":
        if (slot) slot.done = true;
        if (arm) state.arms[arm].done++;
        break;

      case "harness.snapshot": {
        /* Only the two phases CL-Bench actually writes are accepted. Treating
         * "anything not baseline" as the stateful arm would file an unlabelled
         * or partial snapshot against the wrong arm and corrupt the
         * comparison; ignoring it merely delays a number. */
        const phase =
          p.phase === "baseline" ? "stateless" : p.phase === "run" ? "stateful" : null;
        if (!phase) break;
        state.harness[phase] = p;
        applyHarness(phase, p);
        break;
      }

      default:
        break;
    }

    emit("*", ev);
    emit(ev.type, ev);
  }

  /* Rewards come from here and nowhere else. `outcomes` is the harness's own
   * per-instance record; `questions` is its question_history. Both are read,
   * neither is recomputed. */
  function applyHarness(phase, p) {
    let learned = false;
    (p.outcomes || []).forEach((o) => {
      let idx;
      if (phase === "stateful") {
        idx = o.instance_index;
        learned = learnMapping(o.instance_id, idx) || learned;
      } else {
        /* Baseline outcomes all claim instance_index 0 for the same slicing
         * reason, and array POSITION is no help either: a partial baseline
         * snapshot is compacted to the instances that have finished, in
         * completion order, so position 0 is simply whichever instance
         * happened to finish first. (Observed directly — the first smoke run
         * completed baseline instance #2 before #1.)
         *
         * The id→index map from the stateful arm is therefore the only sound
         * placement. An outcome whose id is not mapped yet is parked, not
         * guessed at; it lands as soon as the stateful arm names that id. */
        const mapped = o.instance_id != null ? state.indexById[String(o.instance_id)] : undefined;
        if (mapped === undefined) {
          if (o.instance_id != null) state.pendingOutcomes.set(String(o.instance_id), o);
          return;
        }
        idx = mapped;
      }
      const q = ensureQuestion(idx);
      if (!q) return;
      applyOutcome(q, phase, o);
    });
    if (learned) queueMicrotask(drainPending);
    (p.questions || []).forEach((row, i) => {
      const q = ensureQuestion(i);
      if (!q) return;
      if (row.correct != null) q[phase].correct = row.correct;
      if (row.num_queries != null) q[phase].numQueries = row.num_queries;
      if (q.difficulty == null && row.difficulty) q.difficulty = row.difficulty;
    });
  }

  // ---- derived ----------------------------------------------------------

  /** Normalized gain over the questions BOTH arms have scored.
   *  g_b = (mean r_sf − mean r_sl) / (r_max − mean r_sl)  — CL-Bench's metric.
   *  Returns null until at least one question is complete on both arms. */
  function gain() {
    const sf = [], sl = [];
    for (const q of state.questions) {
      if (q.stateful.reward == null || q.stateless.reward == null) continue;
      sf.push(q.stateful.reward);
      sl.push(q.stateless.reward);
    }
    if (!sf.length) return null;
    const m = (a) => a.reduce((x, y) => x + y, 0) / a.length;
    const a = m(sf), b = m(sl);
    if (R_MAX - b === 0) return null;
    return { g: (a - b) / (R_MAX - b), n: sf.length, rsf: a, rsl: b };
  }

  /** Cumulative gain after each paired question — the race curve.
   *
   * A point with no denominator (memory-off already at r_max) is OMITTED, not
   * plotted as zero. Emitting 0 there would draw a confident "no gain" for a
   * quantity that is undefined, and would disagree with gain(), which returns
   * null in exactly that case. */
  function gainCurve() {
    const pts = [];
    let sf = 0, sl = 0, n = 0;
    for (const q of state.questions) {
      if (q.stateful.reward == null || q.stateless.reward == null) continue;
      sf += q.stateful.reward;
      sl += q.stateless.reward;
      n++;
      const b = sl / n;
      if (R_MAX - b === 0) continue;
      pts.push([n, (sf / n - b) / (R_MAX - b)]);
    }
    return pts;
  }

  // ---- event source -----------------------------------------------------

  function emit(type, ev) {
    for (const fn of listeners[type] || []) {
      try {
        fn(ev, state);
      } catch (err) {
        console.error("listener for", type, err);
      }
    }
  }

  function on(type, fn) {
    (listeners[type] = listeners[type] || []).push(fn);
    return () => {
      listeners[type] = listeners[type].filter((f) => f !== fn);
    };
  }

  const replay = {
    active: false,
    speed: 4,
    playing: true,
    events: [],
    cursor: 0,
    timer: null,
    budgetMs: 0, // scaled time paid for but not yet spent
    lastTick: null,
  };

  function connectLive() {
    state.source = "live";
    const es = new EventSource("/stream");
    es.onmessage = (m) => {
      try {
        reduce(JSON.parse(m.data));
      } catch (err) {
        console.error("bad event", err);
      }
      render();
    };
    es.addEventListener("caught-up", () => {
      state.caughtUp = true;
      render();
    });
    es.onopen = () => {
      state.connected = true;
      render();
    };
    es.onerror = () => {
      state.connected = false;
      render();
    };
  }

  async function connectReplay(path, opts) {
    state.source = "replay";
    replay.active = true;
    replay.speed = opts.speed || 4;
    const res = await fetch(path);
    if (!res.ok) throw new Error(`replay fetch ${res.status} for ${path}`);
    const text = await res.text();
    replay.events = text
      .split("\n")
      .filter((l) => l.trim())
      .map((l) => {
        try {
          return JSON.parse(l);
        } catch {
          return null;
        }
      })
      .filter(Boolean);
    state.connected = true;
    if (opts.from === "migration") {
      const at = replay.events.findIndex((e) => e.type === "stage.change");
      if (at > 0) fastForward(at);
    }
    step();
  }

  function fastForward(to) {
    while (replay.cursor < to && replay.cursor < replay.events.length) {
      reduce(replay.events[replay.cursor++]);
    }
    render();
  }

  /** Scaled wait before the event at `i`, capped so a stall in the run does
   *  not become a stall in the replay. The clock is scaled, never faked. */
  function scaledGapMs(i) {
    if (i <= 0) return 0;
    const dtSec = Math.max(0, (replay.events[i].ts || 0) - (replay.events[i - 1].ts || 0));
    return Math.min((dtSec * 1000) / replay.speed, 1500 / replay.speed);
  }

  const TICK_MS = 40;

  /* A virtual clock, not one timer per event.
   *
   * The obvious loop — schedule a timeout per event, reduce, paint, repeat —
   * couples event flow to paint cost. Measured on a real recording: the
   * timers accounted for 3 seconds across 199 events while the run took over
   * a minute, because each paint cost ~370 ms and only one event landed per
   * paint. Playback speed silently became "however fast the slowest page can
   * render", which is not a speed control at all.
   *
   * Instead: accumulate real elapsed time into a scaled budget, drain every
   * event the budget has paid for, then paint once. Events keep true relative
   * timing regardless of render cost, and a heavy page simply coalesces more
   * events per frame. */
  function step() {
    clearTimeout(replay.timer);
    if (replay.cursor >= replay.events.length) {
      state.caughtUp = true;
      render();
      return;
    }
    if (!replay.playing) return;

    const now = performance.now();
    if (replay.lastTick == null) replay.lastTick = now;
    replay.budgetMs += now - replay.lastTick;
    replay.lastTick = now;

    let drained = 0;
    while (replay.cursor < replay.events.length) {
      const wait = scaledGapMs(replay.cursor);
      if (wait > replay.budgetMs) break;
      replay.budgetMs -= wait;
      reduce(replay.events[replay.cursor++]);
      drained++;
      // Never let one tick monopolise the thread on a huge recording.
      if (drained >= 500) break;
    }
    if (drained) render();
    replay.timer = setTimeout(step, TICK_MS);
  }

  function connect() {
    const u = new URLSearchParams(location.search);
    const path = u.get("replay");
    if (path) {
      return connectReplay(path, {
        speed: Number(u.get("speed")) || 4,
        from: u.get("from"),
      }).catch((err) => {
        console.error(err);
        const el = document.getElementById("conn");
        if (el) el.textContent = "replay failed: " + err.message;
      });
    }
    connectLive();
  }

  // ---- shared chrome ----------------------------------------------------

  const renderers = [];
  let pending = false;

  function onRender(fn) {
    renderers.push(fn);
  }

  /* Coalesce to one paint per frame. Events arrive in bursts — a recall
   * response and four lesson rows land within a millisecond of each other —
   * and re-rendering per event drops frames on the ledger page. */
  function render() {
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => {
      pending = false;
      for (const fn of renderers) {
        try {
          fn(state);
        } catch (err) {
          console.error("render", err);
        }
      }
      paintChrome();
    });
  }

  const PAGES = [
    ["race.html", "Race"],
    ["turn.html", "Turn"],
    ["ledger.html", "Mubit I/O"],
    ["store.html", "Store"],
  ];

  /* The committed analysis pages — the full 3-run results and their charts.
   * They live outside the demo, so they take no replay parameters (they would
   * not know what to do with them) and open in a new tab: clicking one mid-run
   * must not navigate a live stream away, and inside the tiled view it would
   * otherwise replace a single frame. Paths are relative to demo/web/. */
  const ANALYSIS = [
    ["../../viz/bsm.html", "Spectrum", "Blind spectrum monitoring — full runs and charts"],
    ["../../viz/db.html", "Database", "Database exploration — full runs and charts"],
    ["../../viz/poker.html", "Poker", "Exploitable poker — full runs and charts"],
  ];

  function mountChrome(title, subtitle) {
    const bar = document.createElement("header");
    bar.className = "chrome";
    const params = location.search;
    bar.innerHTML =
      `<div class="chrome-l"><a class="home" href="index.html${params}">◱</a>` +
      `<div><div class="chrome-t">${title}</div><div class="chrome-s">${subtitle || ""}</div></div></div>` +
      `<nav class="chrome-nav">` +
      PAGES.map(
        ([href, label]) =>
          `<a href="${href}${params}"${
            location.pathname.endsWith(href) ? ' class="on"' : ""
          }>${label}</a>`
      ).join("") +
      `<span class="nav-sep" aria-hidden="true"></span>` +
      `<span class="nav-lbl">full runs</span>` +
      ANALYSIS.map(
        ([href, label, title]) =>
          `<a class="alt" href="${href}" target="_blank" rel="noopener" title="${title}">${label}</a>`
      ).join("") +
      `</nav>` +
      `<div class="chrome-r"><span id="clock" class="mono"></span><span id="conn" class="pill">connecting…</span>` +
      `<span id="replayctl"></span></div>`;
    document.body.insertBefore(bar, document.body.firstChild);

    if (new URLSearchParams(location.search).get("replay")) {
      const c = bar.querySelector("#replayctl");
      c.innerHTML =
        `<button data-sp="1">1×</button><button data-sp="4">4×</button>` +
        `<button data-sp="16">16×</button><button data-jump="1">↦ migration</button>` +
        `<button data-play="1">⏸</button>`;
      c.className = "rctl";
      c.addEventListener("click", (e) => {
        const b = e.target.closest("button");
        if (!b) return;
        if (b.dataset.sp) {
          replay.speed = Number(b.dataset.sp);
          [...c.querySelectorAll("[data-sp]")].forEach((x) =>
            x.classList.toggle("on", x === b)
          );
        } else if (b.dataset.jump) {
          const at = replay.events.findIndex((ev) => ev.type === "stage.change");
          if (at > replay.cursor) fastForward(at);
        } else if (b.dataset.play) {
          replay.playing = !replay.playing;
          b.textContent = replay.playing ? "⏸" : "▶";
          if (replay.playing) step();
        }
      });
      const four = c.querySelector('[data-sp="4"]');
      if (four) four.classList.add("on");
    }
    paintChrome();
  }

  function paintChrome() {
    const conn = document.getElementById("conn");
    if (conn) {
      const label = state.source === "replay" ? "replay" : "live";
      // Parked events have been received but not yet placed; counting only
      // `events` makes a healthy run look stalled while a mapping is pending.
      const parked = state.pending.length ? ` · ${state.pending.length} parked` : "";
      conn.textContent = state.connected
        ? `${label} · ${state.events} events${parked}${state.caughtUp ? "" : " · loading"}`
        : `${label} · disconnected`;
      conn.className = "pill " + (state.connected ? "ok" : "bad");
    }
    /* A pairing conflict means the two arms may be lined up wrong, which
     * invalidates every comparison on every page. It gets a banner on all four
     * rather than a footnote on one. */
    if (state.pairingConflict && !document.getElementById("pairwarn")) {
      const bar = document.querySelector(".chrome");
      if (bar) {
        const w = el("div", "flag warn");
        w.id = "pairwarn";
        w.style.margin = "0 0 16px";
        w.textContent =
          "Arm pairing conflict: " +
          state.pairingConflict.note +
          ` (question id ${state.pairingConflict.instanceId} was ${state.pairingConflict.was},` +
          ` now ${state.pairingConflict.now}). Comparisons on this page may be misaligned.`;
        bar.insertAdjacentElement("afterend", w);
      }
    }
    const clock = document.getElementById("clock");
    if (clock && state.firstTs != null) {
      const s = Math.max(0, Math.round(state.lastTs - state.firstTs));
      clock.textContent = `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(
        s % 60
      ).padStart(2, "0")}`;
    }
  }

  // ---- small helpers pages share ---------------------------------------

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(
      /[&<>"']/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );
  }

  const fmtMs = (v) => (v == null ? "—" : v < 1000 ? `${Math.round(v)} ms` : `${(v / 1000).toFixed(2)} s`);
  const pct = (v, d) => (v == null ? "—" : (v * 100).toFixed(d == null ? 1 : d) + "%");

  window.D = {
    state,
    connect,
    on,
    onRender,
    render,
    mountChrome,
    gain,
    gainCurve,
    replay,
    el,
    esc,
    fmtMs,
    pct,
    R_MAX,
  };
})();
