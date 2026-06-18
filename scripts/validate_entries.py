#!/usr/bin/env python3
"""Validate every registered submission entry.

Each ``submissions/<id>/`` must be a well-formed registry entry:

  - pointer.yaml    parses; submission_id matches the folder; has a ``source``
  - submission.yaml parses; has system.model / system.provider / headline.n_instances_total
                    (and none left as the ``TODO`` placeholder)
  - _stats/score.json parses and is a non-empty {instance_id: ...} map

CI runs this on every PR so a malformed entry fails the check. Exits nonzero on any problem,
emitting GitHub Actions ``::error::`` annotations.
"""

import json
import sys
from pathlib import Path

import yaml

REGISTRY = Path(__file__).resolve().parent.parent / "submissions"


def _dig(d, dotted: str):
    for key in dotted.split("."):
        d = d.get(key) if isinstance(d, dict) else None
    return d


def check_entry(entry: Path) -> list[str]:
    errs: list[str] = []

    pointer = entry / "pointer.yaml"
    if not pointer.exists():
        errs.append("missing pointer.yaml")
    else:
        p = yaml.safe_load(pointer.read_text()) or {}
        if p.get("submission_id") != entry.name:
            errs.append(f"pointer.yaml submission_id ({p.get('submission_id')!r}) != folder name")
        if not p.get("source"):
            errs.append("pointer.yaml missing 'source'")

    manifest = entry / "submission.yaml"
    if not manifest.exists():
        errs.append("missing submission.yaml")
    else:
        m = yaml.safe_load(manifest.read_text()) or {}
        for field in ("system.model", "system.provider", "headline.n_instances_total"):
            if _dig(m, field) in (None, "", "TODO"):
                errs.append(f"submission.yaml missing/placeholder '{field}'")

    score = entry / "_stats" / "score.json"
    if not score.exists():
        errs.append("missing _stats/score.json")
    elif not (isinstance(data := json.loads(score.read_text()), dict) and data):
        errs.append("_stats/score.json is empty or not an object")

    return errs


def main() -> None:
    entries = [d for d in sorted(REGISTRY.iterdir()) if d.is_dir()]
    problems = {e.name: errs for e in entries if (errs := check_entry(e))}
    for name, errs in problems.items():
        for e in errs:
            print(f"::error::{name}: {e}")
    if problems:
        sys.exit(f"{len(problems)} invalid submission entr{'y' if len(problems) == 1 else 'ies'}.")
    print(f"OK: {len(entries)} submission entr{'y' if len(entries) == 1 else 'ies'} valid.")


if __name__ == "__main__":
    main()
