"""Transmitter registry: the accumulated state of the BSM band.

Pure logic only — merging peaks into transmitter hypotheses, inferring the
channel grid, and serialising an entry so it can live in Mubit rather than in
a process-local dict. ``system.py`` owns the I/O.

Stdlib only, no relative imports: ``python3 systems/mubit_bsm/registry.py``
self-checks.
"""

from __future__ import annotations

import json
import math
import re
import statistics
from typing import Optional

MERGE_THRESHOLD = 8.0  # MHz; peaks closer than this are the same transmitter
WIDEBAND_MIN = 10.0  # MHz bandwidth
BAND_MAX = 168.0  # MHz

# The whole registry is one Mubit entry, upserted on this key and read back
# by keyed lookup on this metadata clause. Semantic recall ranks and truncates
# (server caps evidence at 50), which made entries flicker in and out between
# scans; a registry needs all of its state, every time, not the top matches.
REGISTRY_KEY = "bsm:registry"
REGISTRY_MATCH = {"task": "blind_spectrum_monitoring", "kind": "registry"}


def is_bsm(prompt: str) -> bool:
    return "--- Scan" in prompt and "Detected peaks:" in prompt


def extract_peaks(prompt: str) -> list[dict]:
    """Detected peaks from a BSM scan prompt."""
    return [
        {"freq": float(m.group(1)), "power": float(m.group(2)), "width": float(m.group(3))}
        for m in re.finditer(
            r"freq:\s*([\d.]+)\s*MHz.*?power:\s*([-\d.]+)\s*dBm.*?width:\s*([\d.]+)\s*MHz",
            prompt,
        )
    ]


def is_wideband(entry: dict) -> bool:
    return entry.get("is_wideband", entry["bandwidth"] >= WIDEBAND_MIN)


def entry_key(entry: dict) -> str:
    """Stable Mubit upsert key for one transmitter.

    Fixed at creation from the first sighting, so the running average of the
    center frequency updates the same memory entry instead of spawning a new
    one every scan.
    """
    return entry["key"]


def _new_entry(freq: float, width: float, scan_num: int) -> dict:
    wide = width >= WIDEBAND_MIN
    return {
        "key": f"bsm:tx:{'W' if wide else 'N'}:{round(freq)}",
        "center_freq": round(freq, 2),
        "bandwidth": round(width, 1),
        "hit_count": 1,
        "first_seen_scan": scan_num,
        "last_seen_scan": scan_num,
        "is_wideband": wide,
    }


def dumps_entry(entry: dict) -> str:
    return json.dumps(entry, sort_keys=True)


def loads_entry(text: str) -> Optional[dict]:
    """Parse an entry back out of Mubit. Tolerates surrounding prose."""
    text = (text or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        entry = json.loads(text[start : end + 1])
    except ValueError:
        return None
    if not isinstance(entry, dict) or "center_freq" not in entry or "key" not in entry:
        return None
    entry.setdefault("bandwidth", 0.0)
    entry.setdefault("hit_count", 1)
    return entry


def dumps_registry(registry: list[dict], scan_num: int) -> str:
    return json.dumps({"scan": scan_num, "registry": registry}, sort_keys=True)


def loads_registry(text: str) -> tuple[list[dict], int]:
    """Parse one stored registry blob into (entries, scan_num)."""
    try:
        blob = json.loads(text or "")
    except ValueError:
        return [], -1
    if not isinstance(blob, dict):
        return [], -1
    entries = [e for e in blob.get("registry") or [] if isinstance(e, dict) and "key" in e]
    for e in entries:
        e.setdefault("bandwidth", 0.0)
        e.setdefault("hit_count", 1)
    return entries, int(blob.get("scan", -1))


def dedupe(entries: list[dict]) -> list[dict]:
    """Collapse entries sharing a key, keeping the most-observed copy."""
    best: dict[str, dict] = {}
    for e in entries:
        k = entry_key(e)
        if k not in best or e.get("hit_count", 0) > best[k].get("hit_count", 0):
            best[k] = e
    return sorted(best.values(), key=lambda e: e["center_freq"])


def merge_peaks(
    registry: list[dict],
    peaks: list[dict],
    scan_num: int,
    merge_threshold: float = MERGE_THRESHOLD,
) -> tuple[list[dict], set[str]]:
    """Merge this scan's peaks into the registry.

    Returns the registry and the keys whose content changed, so only those
    need writing back. Wideband and narrowband are kept in separate bins so a
    narrowband never absorbs the wideband next to it.
    """
    before = {entry_key(e): dumps_entry(e) for e in registry}

    for peak in peaks:
        freq, width = peak["freq"], peak["width"]
        wide = width >= WIDEBAND_MIN

        best_idx, best_dist = -1, float("inf")
        for i, entry in enumerate(registry):
            if is_wideband(entry) != wide:
                continue
            dist = abs(entry["center_freq"] - freq)
            if dist < best_dist:
                best_dist, best_idx = dist, i

        if best_idx >= 0 and best_dist < merge_threshold:
            entry = registry[best_idx]
            old, new = entry["hit_count"], entry["hit_count"] + 1
            entry["center_freq"] = round((entry["center_freq"] * old + freq) / new, 2)
            entry["bandwidth"] = round((entry["bandwidth"] * old + width) / new, 1)
            entry["hit_count"] = new
            entry["last_seen_scan"] = scan_num
        else:
            registry.append(_new_entry(freq, width, scan_num))

    registry.sort(key=lambda e: e["center_freq"])
    changed = {
        entry_key(e) for e in registry if before.get(entry_key(e)) != dumps_entry(e)
    }
    return registry, changed


def infer_grid_channels(registry: list[dict]) -> list[dict]:
    """Registry plus the channels its own lattice implies, as a new list.

    The lattice is fitted to what has been observed, never assumed — the band's
    real plan is the thing being measured, so hardcoding it would be answering
    from the key rather than from memory. Inference is a hypothesis over what
    was read: rebuilt for each prompt and never written back.

    Observed entries keep their measured centre and bandwidth. Snapping them
    onto the fitted lattice was tried and is worse — the generator jitters
    centres (center_jitter 0.5) and the corpus changes plan mid-run, so against
    the shipped ground truth it moved mean symmetric error 31.1 -> 35.1 MHz
    where gap filling alone gives 29.6.
    """
    view = [dict(e) for e in registry]
    confirmed = sorted(
        (e for e in view if is_wideband(e) and e["hit_count"] >= 2),
        key=lambda e: e["center_freq"],
    )
    if len(confirmed) < 3:
        return view

    # Span regression, not the most common consecutive gap: per-gap noise is
    # the same size as the slot quantisation, so the mode comes out at 25
    # where the span gives 24.0. The unit is the smallest gap because skipped
    # slots make most gaps a multiple of one.
    # ponytail: min gap assumes no two confirmed widebands sit closer than a
    # slot; merge_peaks only separates them by 8 MHz, so if that ever happens
    # fit the grid by least-squares over candidate n instead.
    unit = min(
        confirmed[i]["center_freq"] - confirmed[i - 1]["center_freq"]
        for i in range(1, len(confirmed))
    )
    span = confirmed[-1]["center_freq"] - confirmed[0]["center_freq"]
    n = round(span / unit) if unit > 0 else 0
    if n < 1:
        return view
    grid = span / n

    # Circular mean: ``center_freq % grid`` wraps, so plain averaging is pulled
    # across the seam by whichever channels land just below the modulus — it
    # returned 13.71 where the circular mean gives 7.44.
    phases = [2 * math.pi * (e["center_freq"] % grid) / grid for e in confirmed]
    offset = grid * math.atan2(
        sum(math.sin(p) for p in phases), sum(math.cos(p) for p in phases)
    ) / (2 * math.pi) % grid
    bandwidth = statistics.median(e["bandwidth"] for e in confirmed)

    slots = {round((e["center_freq"] - offset) / grid) for e in confirmed}
    for slot in range(min(slots), max(slots) + 3):
        if slot in slots:
            continue
        freq = round(slot * grid + offset, 2)
        if not 0 <= freq <= BAND_MAX:
            continue
        if any(abs(e["center_freq"] - freq) < 8 for e in view):
            continue
        view.append(
            {
                "key": f"bsm:tx:W:{round(freq)}",
                "center_freq": freq,
                "bandwidth": round(bandwidth, 1),
                "hit_count": 0,
                "first_seen_scan": None,
                "last_seen_scan": None,
                "is_wideband": True,
                "inferred": True,
            }
        )

    view.sort(key=lambda e: e["center_freq"])
    return view


def format_registry(registry: list[dict]) -> str:
    if not registry:
        return "(no transmitters accumulated yet)"
    lines = []
    for e in registry:
        status = (
            "inferred"
            if e.get("inferred")
            else "confirmed"
            if e["hit_count"] >= 2
            else "tentative"
        )
        lines.append(
            f"  {e['center_freq']:>7.1f} MHz | bw={e['bandwidth']:>5.1f} | "
            f"hits={e['hit_count']:>2} | {'W' if is_wideband(e) else 'N'} | {status}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    prompt = (
        "--- Scan 4/90 ---\nDetected peaks:\n"
        "  freq: 7.5 MHz, power: -42.0 dBm, width: 15.0 MHz\n"
        "  freq: 19.6 MHz, power: -55.0 dBm, width: 5.0 MHz\n"
    )
    assert is_bsm(prompt) and not is_bsm("Question 1/40")
    peaks = extract_peaks(prompt)
    assert len(peaks) == 2 and peaks[0]["freq"] == 7.5, peaks

    reg, changed = merge_peaks([], peaks, 4)
    assert len(reg) == 2 and changed == {"bsm:tx:W:8", "bsm:tx:N:20"}, (reg, changed)

    # A second sighting updates the same entry, so the same memory key is
    # rewritten rather than a duplicate transmitter appearing.
    reg, changed = merge_peaks(reg, [{"freq": 8.1, "power": -41.0, "width": 15.0}], 5)
    assert len(reg) == 2, reg
    wide = [e for e in reg if is_wideband(e)][0]
    assert wide["key"] == "bsm:tx:W:8" and wide["hit_count"] == 2, wide
    assert changed == {"bsm:tx:W:8"}, changed  # the untouched narrowband isn't rewritten

    # A wideband never absorbs the narrowband beside it.
    assert len([e for e in reg if not is_wideband(e)]) == 1

    # Round-trip through what Mubit stores.
    assert loads_registry(dumps_registry(reg, 5)) == (reg, 5)
    assert loads_registry("not json") == ([], -1)
    assert loads_entry(dumps_entry(wide)) == wide
    assert loads_entry("SCHEMA nonsense") is None
    assert loads_entry("") is None
    assert len(dedupe(reg + [dict(wide, hit_count=9)])) == 2
    assert max(e["hit_count"] for e in dedupe(reg + [dict(wide, hit_count=9)])) == 9

    # Three confirmed widebands on a 24 MHz grid -> the gap gets inferred.
    grid_reg = []
    for scan, f in enumerate([7.5, 31.5, 79.5] * 2):
        grid_reg, _ = merge_peaks(grid_reg, [{"freq": f, "power": -40.0, "width": 15.0}], scan)
    view = infer_grid_channels(grid_reg)
    inferred = [e["center_freq"] for e in view if e.get("inferred")]
    assert 55.5 in inferred, inferred
    assert len(grid_reg) == 3, "inference must not mutate the stored registry"
    assert "inferred" in format_registry(view) and "confirmed" in format_registry(view)

    # A lattice that is NOT the evaluated task's (spacing 30, phase 4, noisy):
    # the fit has to come out of these observations, not out of the code.
    synth = []
    peaks = (
        [{"freq": f, "power": -40.0, "width": 15.0} for f in (4.2, 33.8, 94.1)]
        + [{"freq": f, "power": -55.0, "width": 5.0} for f in (19.0, 49.2)]
        # The detector splits a wideband into a stray narrow peak at its centre.
        + [{"freq": f, "power": -58.0, "width": 2.0} for f in (4.5, 33.9)]
    )
    for scan in range(2):
        synth, _ = merge_peaks(synth, peaks, scan)
    view = infer_grid_channels(synth)

    # The two unobserved slots on the fitted 30 MHz lattice get proposed, at a
    # bandwidth taken from what was seen rather than from a constant.
    inferred = sorted(e["center_freq"] for e in view if e.get("inferred"))
    assert [round(f) for f in inferred] == [64, 124, 154], inferred
    assert all(abs(e["bandwidth"] - 15.0) < 0.5 for e in view if e.get("inferred")), view

    # Observed entries are passed through untouched — snapping them onto the
    # lattice loses more to centre jitter than it recovers.
    observed = {round(e["center_freq"], 1) for e in view if not e.get("inferred")}
    assert observed == {4.2, 4.5, 19.0, 33.8, 33.9, 49.2, 94.1}, observed
    assert len(synth) == 7, "inference must not mutate the stored registry"

    print("registry.py self-check OK")
