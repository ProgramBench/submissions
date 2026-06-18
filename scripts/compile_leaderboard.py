#!/usr/bin/env python3
"""Compile the website leaderboard from this registry.

Each registered submission lives in ``submissions/<id>/`` and is self-contained:

    submissions/<id>/
      pointer.yaml        # fork URL + pinned commit SHA
      submission.yaml     # manifest (model, provider, agent) — no scores stored
      _stats/score.json   # {instance_id: {test_name: passed_bool}}  (per-test pass/fail)
      _stats/cost.json    # {instance_id: cost}   (optional)
      _stats/calls.json   # {instance_id: calls}  (optional)

Scores are recomputed here from the per-test ``score.json``, so striking out bad tests is
a pure recompile: add the test to ``ignored_tests.json`` (a {instance_id: [test_name]} map
at the repo root) and re-run. (Legacy ``score.json`` that maps {instance_id: float} is
still accepted, but the ignore map can't apply to it — it has no per-test data.)

Writes the shapes the website consumes:

    <website>/data/leaderboard.json            # row per submission
    <website>/data/details/<id>/score.json     # {instance_id: score}  (ignore map applied)
    <website>/data/details/<id>/{cost,calls}.json  # copied verbatim

Usage:
    python scripts/compile_leaderboard.py --website /path/to/website
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import date
from pathlib import Path

import yaml

PROVIDER_LOGOS = {"Anthropic": "anthropic.svg", "Google": "google.svg", "OpenAI": "openai.svg"}
RESOLVED_THRESHOLD = 1.0
NEAR_RESOLVED_THRESHOLD = 0.95
# Benchmark size — the denominator for resolved% / near% (an unattempted task counts as
# unresolved). A fixed property of the benchmark, not of any submission. Bump if it grows.
N_BENCHMARK_INSTANCES = 200


def _instance_score(value, ignore: set[str]) -> float:
    """Score for one instance from per-test {name: passed} (ignore map applied), or a
    legacy float passed through as-is."""
    if isinstance(value, dict):
        kept = [passed for name, passed in value.items() if name not in ignore]
        return sum(kept) / len(kept) if kept else 0.0
    return value


def _total(stats_dir: Path, name: str) -> float:
    path = stats_dir / f"{name}.json"
    return round(sum(json.loads(path.read_text()).values()), 2) if path.exists() else 0


def compile_leaderboard(registry: Path, website: Path, ignore_path: Path) -> None:
    ignore_map = json.loads(ignore_path.read_text()) if ignore_path.exists() else {}
    data_dir = website / "data"
    data_dir.mkdir(parents=True, exist_ok=True)  # so an empty registry still writes leaderboard.json
    entries: list[dict] = []
    for entry_dir in sorted(d for d in registry.iterdir() if d.is_dir()):
        manifest_path = entry_dir / "submission.yaml"
        score_path = entry_dir / "_stats" / "score.json"
        if not (manifest_path.exists() and score_path.exists()):
            print(f"skip {entry_dir.name}: missing submission.yaml or _stats/score.json")
            continue
        manifest = yaml.safe_load(manifest_path.read_text())
        system = manifest["system"]
        n_total = N_BENCHMARK_INSTANCES

        score_data = json.loads(score_path.read_text())
        per_instance = {iid: _instance_score(v, set(ignore_map.get(iid, []))) for iid, v in score_data.items()}
        n = len(per_instance) or 1
        entries.append(
            {
                "model": system["model"],
                "provider": system["provider"],
                "logo": PROVIDER_LOGOS.get(system["provider"], ""),
                "agent": system["agent"],
                "resolved": round(100 * sum(s >= RESOLVED_THRESHOLD for s in per_instance.values()) / n_total, 1),
                "near_resolved": round(100 * sum(s >= NEAR_RESOLVED_THRESHOLD for s in per_instance.values()) / n_total, 1),
                "cost": _total(entry_dir / "_stats", "cost"),
                "calls": _total(entry_dir / "_stats", "calls"),
                "details": f"data/details/{entry_dir.name}",
                "mean_score": round(100 * sum(per_instance.values()) / n, 1),
            }
        )
        out_dir = data_dir / "details" / entry_dir.name
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "score.json").write_text(json.dumps(per_instance, indent=2, sort_keys=True))
        for name in ("cost", "calls"):
            p = entry_dir / "_stats" / f"{name}.json"
            if p.exists():
                shutil.copyfile(p, out_dir / f"{name}.json")

    entries.sort(key=lambda e: (e["resolved"], e["near_resolved"], e["mean_score"]), reverse=True)
    (data_dir / "leaderboard.json").write_text(
        json.dumps({"updated": date.today().isoformat(), "entries": entries}, indent=2)
    )
    print(f"Wrote {data_dir / 'leaderboard.json'} ({len(entries)} entries) + per-submission details.")


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--registry", type=Path, default=root / "submissions", help="Directory of <id>/ entries.")
    parser.add_argument("--ignore", type=Path, default=root / "ignored_tests.json", help="{iid: [test]} ignore map.")
    parser.add_argument("--website", type=Path, required=True, help="Website repo root (writes under its data/).")
    args = parser.parse_args()
    compile_leaderboard(args.registry, args.website, args.ignore)


if __name__ == "__main__":
    main()
