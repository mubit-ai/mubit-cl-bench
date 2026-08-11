#!/usr/bin/env python3
"""Install the demo's additions into a CL-Bench checkout.

Nothing belonging to CL-Bench itself is edited — only this repo's own system
packages and one new schedule file are placed into its tree, which is what lets
the demo claim it runs the real harness rather than a modified one:

  systems/mubit/                 → $CLBENCH/src/systems/mubit/
  systems/mubit_demo/            → $CLBENCH/src/systems/mubit_demo/
  demo/tasks/database_exploration_fixed/ → $CLBENCH/src/tasks/database_exploration_fixed/
  demo/schedules/demo_drift.json → $CLBENCH/src/tasks/database_exploration/schedules/

CL-Bench discovers systems by scanning ``src/systems/*`` (registry.py) and
schedules by globbing ``src/tasks/<family>/schedules/*.json`` where the filename
must equal the schedule ``id``, so dropping the files in is the whole install.

``systems/mubit`` is synced deliberately, not incidentally. ``mubit_demo``
subclasses it, and a checkout can easily be carrying an older generation of the
file — the one in this repo is the version whose constructor signature
(``model``/``top_k``/``system_prompt``/``share_scope``) and ``mubit_run_id``
metadata match the committed viewer artifacts. If the demo ran against a
different parent it would no longer be the measured system, and the whole
comparison to the published gain would be void, silently. So a differing copy
is reported loudly rather than replaced quietly.
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_CLBENCH = REPO.parent / "continual-learning-bench"


def _copy_tree(src: Path, dst: Path, dry_run: bool) -> list[str]:
    changes = []
    for path in sorted(src.rglob("*")):
        if "__pycache__" in path.parts or path.name.endswith(".pyc"):
            continue
        target = dst / path.relative_to(src)
        if path.is_dir():
            if not target.exists():
                changes.append(f"mkdir  {target}")
                if not dry_run:
                    target.mkdir(parents=True, exist_ok=True)
            continue
        if target.exists() and filecmp.cmp(path, target, shallow=False):
            continue
        changes.append(f"{'update' if target.exists() else 'create'} {target}")
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    return changes


def install(clbench: Path, dry_run: bool = False) -> int:
    src_root = clbench / "src"
    if not src_root.is_dir():
        print(f"error: {clbench} does not look like a CL-Bench checkout (no src/)", file=sys.stderr)
        return 2
    schedule_dir = src_root / "tasks" / "database_exploration" / "schedules"
    if not schedule_dir.is_dir():
        print(f"error: {schedule_dir} not found", file=sys.stderr)
        return 2

    installed_mubit = src_root / "systems" / "mubit" / "system.py"
    repo_mubit = REPO / "systems" / "mubit" / "system.py"
    stale = installed_mubit.exists() and not filecmp.cmp(repo_mubit, installed_mubit, shallow=False)
    if stale:
        print(
            "note: the mubit system already in this checkout differs from this repo's.\n"
            "      Replacing it — mubit_demo must subclass the version that produced\n"
            "      the committed artifacts, or the demo is not the measured system."
        )

    changes = _copy_tree(REPO / "systems" / "mubit", src_root / "systems" / "mubit", dry_run)
    changes += _copy_tree(REPO / "systems" / "mubit_demo", src_root / "systems" / "mubit_demo", dry_run)

    # A new task directory, not a patch to theirs: CL-Bench discovers tasks by
    # globbing src/tasks/*/task.py, so this registers alongside the stock
    # database_exploration and leaves every shipped file untouched. Delete the
    # directory and the checkout is exactly as it came. See its module docstring
    # for the three baseline-slicing defects it corrects.
    changes += _copy_tree(
        REPO / "demo" / "tasks" / "database_exploration_fixed",
        src_root / "tasks" / "database_exploration_fixed",
        dry_run,
    )

    variant_dir = src_root / "tasks" / "database_exploration" / "variants"
    if not variant_dir.is_dir():
        print(f"error: {variant_dir} not found", file=sys.stderr)
        return 2

    # The variant carries the question count and the drift boundary; the
    # schedule is the two-stage shape. Both are needed — a schedule alone
    # cannot shorten a drift run (see demo/variants/demo_drift.json).
    for src, dst in (
        (REPO / "demo" / "schedules" / "demo_drift.json", schedule_dir / "demo_drift.json"),
        (REPO / "demo" / "variants" / "demo_drift.json", variant_dir / "demo_drift.json"),
    ):
        if dst.exists() and filecmp.cmp(src, dst, shallow=False):
            continue
        changes.append(f"{'update' if dst.exists() else 'create'} {dst}")
        if not dry_run:
            shutil.copy2(src, dst)

    if not changes:
        print(f"already up to date in {clbench}")
    else:
        for line in changes:
            print(("would " if dry_run else "") + line)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clbench", default=str(DEFAULT_CLBENCH), help="path to the CL-Bench checkout")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    return install(Path(args.clbench).expanduser().resolve(), args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
