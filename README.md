# ProgramBench Leaderboard Registry

This repo is the **authoritative registry** of ProgramBench submissions.
The public website leaderboard at [prograbench.com](https://programbench.com/) is compiled directly from the entries here.

## Registering a submission (PR)

For instructions on how to create a submission, see.

* Our public [repository](https://github.com/facebookresearch/ProgramBench) for information on how to run inference with your own model + harness.
* Our [submission guide](https://programbench.com/blog/submission-guide) for how to surface evaluation results properly as submission artifacts.

Each submission should be surfaced as a PR to this repository contributing a folder `submissions/<submission_id>/`, containing:

```
submissions/<submission_id>/
  pointer.yaml      # fork URL + pinned commit SHA (the exact commit that was scored)
  submission.yaml   # the manifest (model, provider, score headline) — copied from the fork
  _stats/           # one stat file per metric, a flat {instance_id: value} map — copied from the fork
    score.json      #   per-instance score (from evaluation; required)
    cost.json       #   per-instance cost (from trajectories; optional)
    calls.json      #   per-instance model calls (from trajectories; optional)
```

`submission.yaml` and `_stats/score.json` are automatically produced by `programbench submit package`.

## Verifying a submission

To verify any submission, run the following commands:

```bash
git clone <a-public-submission-fork> && cd <fork>
uvx programbench submit verify .            # Tier-0: recompute headline vs manifest. No Docker.
uvx programbench submit verify . --tier1    # Tier-1: re-run eval and confirm the artifacts reproduce it.
```

- **Tier 0** recomputes the headline from the submission's own `eval.json` files (with
  ignored-test filtering) and checks it matches `submission.yaml`.
- **Tier 1** re-runs `programbench eval` on each `submission.tar.gz` and confirms the
  fresh scores match what was reported.
