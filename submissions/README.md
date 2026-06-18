# Registered submissions

One folder per submission lives here, each added by a pull request — see the repo
[README](../README.md) and the [submission guide](https://programbench.com/blog/submission-guide).

Each entry is small and self-contained:

```
<submission_id>/
  pointer.yaml      # the submission repo URL + the exact commit that was scored
  submission.yaml   # the manifest (model, provider, score headline), copied from that repo
  _stats/
    score.json      # per-instance, per-test pass/fail (always present)
    cost.json       # per-instance cost (optional)
    calls.json      # per-instance model calls (optional)
```

The easiest way to add one is `programbench submit register <your-run-dir>`, which opens the
PR for you. On merge, the leaderboard is recompiled from these entries.
