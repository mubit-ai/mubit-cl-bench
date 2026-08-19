"""Pre-flight: does this API key allow direct bypass?

The adapters swallow recall failures and run memoryless, so a key without
direct-mode permission produces a full-length benchmark that silently scores
at baseline. Run this before spending an hour on a benchmark.

    uv run python scripts/check_direct_bypass.py
"""

import os
import time

from mubit import Client  # type: ignore

client = Client(endpoint=os.environ.get("MUBIT_ENDPOINT", "https://api.mubit.ai"))
client.set_api_key(os.environ["MUBIT_API_KEY"])
client.set_run_id("preflight-direct-bypass")

client.remember(
    content="SCHEMA users: id INTEGER, email TEXT",
    intent="lesson",
    upsert_key="preflight:probe",
    source="agent",
    agent_id="preflight",
    wait=True,
)

start = time.monotonic()
out = client.recall(
    query="database schema: table names, column names and types",
    limit=4,
    entry_types=["lesson"],
    include_working_memory=False,
    mode="direct_bypass",
    evidence_only=True,
)
elapsed = time.monotonic() - start

evidence = out.get("evidence") or []
print(f"direct recall: {elapsed:.2f}s, {len(evidence)} evidence")
if elapsed > 5:
    print("SLOW — this is the gateway path, not the bypass. Ask Shankha for a key.")
elif not evidence:
    print("EMPTY — bypass ran but returned nothing; check entry_types/scope.")
else:
    print("OK — bypass active.")
