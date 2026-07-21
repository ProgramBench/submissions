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

A submission id listed in ``.compile_skip`` (repo root, one id per line; blank lines and
``#`` comments ignored) is left untouched: its existing website row + details are carried
over verbatim instead of recompiled from ``_stats``. This is for entries whose website data
was set by hand and would be regressed by stale/partial ``_stats``. The file is local-only
(gitignored); the skip is a no-op wherever it is absent.

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

PROVIDER_LOGOS = {
    "Anthropic": "anthropic.svg",
    "Google": "google.svg",
    "OpenAI": "openai.svg",
    "Z.ai (Zhipu AI)": "zai.png",
}
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


def _load_skip(path: Path) -> set[str]:
    """Submission ids to leave untouched. One id per line; blank lines and #-comments ignored."""
    if not path or not path.exists():
        return set()
    ids = set()
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            ids.add(line)
    return ids


def _existing_rows(leaderboard_path: Path) -> dict[str, dict]:
    """Existing leaderboard rows keyed by submission id (the ``details`` dir basename)."""
    if not leaderboard_path.exists():
        return {}
    raw = json.loads(leaderboard_path.read_text())
    rows = raw.get("entries", []) if isinstance(raw, dict) else raw
    return {Path(r["details"]).name: r for r in rows if r.get("details")}


def compile_leaderboard(registry: Path, website: Path, ignore_path: Path, skip_path: Path = None) -> None:
    ignore_map = json.loads(ignore_path.read_text()) if ignore_path.exists() else {}
    data_dir = website / "data"
    data_dir.mkdir(parents=True, exist_ok=True)  # so an empty registry still writes leaderboard.json
    skip = _load_skip(skip_path)
    preserved = _existing_rows(data_dir / "leaderboard.json") if skip else {}
    entries: list[dict] = []
    for entry_dir in sorted(d for d in registry.iterdir() if d.is_dir()):
        if entry_dir.name in skip:
            row = preserved.get(entry_dir.name)
            if row is not None:
                entries.append(row)  # keep existing row; leave data/details/<id>/ untouched
                print(f"preserve {entry_dir.name}: kept existing leaderboard row + details (.compile_skip)")
            else:
                print(f"skip {entry_dir.name}: in .compile_skip but no existing row to preserve")
            continue
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
                "mean_score": round(100 * sum(per_instance.values()) / n_total, 1),
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
    parser.add_argument("--skip", type=Path, default=root / ".compile_skip",
                        help="Local-only list of submission ids to leave untouched (not refreshed).")
    parser.add_argument("--website", type=Path, required=True, help="Website repo root (writes under its data/).")
    args = parser.parse_args()
    compile_leaderboard(args.registry, args.website, args.ignore, args.skip)


if __name__ == "__main__":
    main()
