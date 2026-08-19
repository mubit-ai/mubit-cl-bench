"""Offline check that the registry really round-trips through Mubit.

Fake Mubit client (an upsert-keyed dict, like the real store) and a fake LLM,
so it needs no API keys. Run from the CL-Bench root:

    uv run python src/systems/mubit_bsm/test_roundtrip.py
"""

import os
import sys
import types

store: dict = {}  # (run_id, upsert_key) -> content
calls = {"remember": 0, "lookup": 0}


class FakeClient:
    def __init__(self, endpoint=None):
        self.run_id = None

    def set_api_key(self, key):
        pass

    def set_transport(self, transport):
        pass

    def set_run_id(self, run_id):
        self.run_id = run_id

    def remember(self, content, upsert_key=None, metadata=None, **kw):
        calls["remember"] += 1
        store[(self.run_id, upsert_key)] = (content, metadata or {})

    def lookup(self, match=None, limit=256):
        """Metadata-matched enumeration, like the real keyed lookup."""
        calls["lookup"] += 1
        out = []
        for (run, _), (content, metadata) in store.items():
            if run != self.run_id:
                continue
            if match and not any(
                all(metadata.get(k) == v for k, v in clause.items()) for clause in match
            ):
                continue
            out.append({"id": str(len(out)), "metadata": {**metadata, "content": content}})
        return out[:limit]


fake = types.ModuleType("mubit")
fake.Client = FakeClient
sys.modules["mubit"] = fake
os.environ["MUBIT_API_KEY"] = "test"

from src.interface import Observation, Query  # noqa: E402
from src.systems.mubit_bsm.system import MubitBSMSystem  # noqa: E402
from src.tasks.blind_spectrum_monitoring.task import ScanReport, Transmitter  # noqa: E402


def scan_prompt(n, peaks):
    lines = "\n".join(f"  freq: {f} MHz, power: -42.0 dBm, width: {w} MHz" for f, w in peaks)
    return f"--- Scan {n}/90 ---\nDetected peaks:\n{lines}\n"


system = MubitBSMSystem.__new__(MubitBSMSystem)  # skip the real genai client
MubitBSMSystem.__init__(system, model="fake")

reported = {}


def fake_completion(system_content, contents, schema):
    """Parrot the injected registry back, which is what the real prompt asks for."""
    txs = []
    for line in contents[-1]["parts"][0]["text"].splitlines():
        if "MHz | bw=" in line:
            txs.append(
                Transmitter(
                    center_freq=float(line.split("MHz")[0].strip()),
                    bandwidth=float(line.split("bw=")[1].split("|")[0]),
                    currently_active=True,
                    estimated_power=-42.0,
                )
            )
    reported["n"] = len(txs)
    return ScanReport(transmitters=txs), None


system._genai_completion = fake_completion

BAND = [(7.5, 15.0), (31.5, 15.0), (55.5, 15.0), (19.6, 5.0)]
for n in range(1, 7):
    visible = BAND if n % 2 else BAND[:2]  # transmitters go dormant
    query = Query(
        prompt=scan_prompt(n, visible),
        instance_id=str(n),
        instance_index=n - 1,
        response_schema=ScanReport,
    )
    response = system.respond(query)
    system.observe(Observation(content=f"Scan {n} scored.", instance_complete=True))
    print(
        f"scan {n}: visible={len(visible)} registry={response.metadata['registry_size']} "
        f"written={response.metadata['registry_written']} "
        f"reported={len(response.action.transmitters)}"
    )

stateful_run = system._run_id
# One entry holds the whole registry, so a scan is one read and one write.
assert len([k for k in store if k[0] == stateful_run]) == 1, store
assert calls["lookup"] == 6 and calls["remember"] == 6, calls
# Dormant transmitters survive a scan that could not see them.
assert reported["n"] >= 4, reported

# Baseline arm: reset assigns a new run_id, so it recalls an empty registry.
system.reset()
assert system._run_id != stateful_run
response = system.respond(
    Query(prompt=scan_prompt(1, BAND[:1]), instance_id="b", instance_index=0, response_schema=ScanReport)
)
assert response.metadata["registry_size"] == 1, response.metadata
assert len([k for k in store if k[0] == stateful_run]) == 1, "baseline leaked into the run"

print("\nregistry lives in Mubit; dormant channels survive; baseline is isolated — OK")
