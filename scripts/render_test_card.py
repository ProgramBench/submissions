#!/usr/bin/env python3
"""Render a "test card" PNG that highlights a single ProgramBench test.

The card is the dark code image used in the model-release tweet threads: a bold
title, a monospace file/test subtitle, and the verbatim test source drawn inside a
rounded box (docstrings/comments dimmed, ``assert`` lines accented).

Two ways to supply the code:

  1. Fetch it from the task mirror (``github.com/gnever-reveng/<instance>``) by
     naming the instance + the dotted pytest id. Needs ``$GITHUB_TOKEN`` and, to
     resolve which branch holds the test, the local task registry checkout
     (``--repo-tasks``, defaults to ``../repo/tasks`` relative to this repo).

         source ../repo/.env   # exports GITHUB_TOKEN
         uv run --with matplotlib scripts/render_test_card.py \
             --instance agourlay__zip-password-finder.704700d \
             --test tests.test_performance.test_empty_charset_file_error \
             --model "Opus 4.8" --score "676 / 677" \
             --out /tmp/zip.png

  2. Point it at a local file (or stdin) and set the title/subtitle yourself:

         uv run --with matplotlib scripts/render_test_card.py \
             --code-file mytest.py --title "..." --subtitle "..." --out card.png

Title/subtitle are auto-built in fetch mode but any of --title/--subtitle always win.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import textwrap
import urllib.request
from pathlib import Path

GH_ORG = "gnever-reveng"
DPI = 200

# ---- theme -----------------------------------------------------------------
BG = "#161B2E"          # page background
BOX_FILL = "#1C2338"    # code box fill
BOX_EDGE = "#33405E"    # code box border
TITLE_C = "#FFFFFF"
SUB_C = "#8893A8"
CODE_C = "#D7DEEA"      # normal code
DIM_C = "#7A88A8"       # docstrings + comments
HL_C = "#FFCB6B"        # accented (assert) lines

# ---- font sizes (points) ---------------------------------------------------
FS_CODE = 13
FS_TITLE = 18
FS_SUB = 12

# ---- spacing (inches) ------------------------------------------------------
TOP = 0.26              # above the title (kept tight; content sits high)
TITLE_GAP = 0.10        # title -> subtitle
SUB_GAP = 0.30          # subtitle -> code box
BOX_PADX = 0.34         # code box inner horizontal padding
BOX_PADY = 0.26         # code box inner vertical padding
BOTTOM = 0.28           # below the box
SIDE = 0.42             # left/right page margin


# ============================================================================
# Fetching test source from the mirror
# ============================================================================
def _http_get(url: str, token: str | None) -> str | None:
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"token {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode("utf-8", "replace")
    except Exception:
        return None
    if body.strip() == "404: Not Found":
        return None
    return body


def resolve_branch(instance: str, test_id: str, repo_tasks: Path) -> str | None:
    """Find the mirror branch whose tests.json lists ``test_id``."""
    tj = repo_tasks / instance / "tests.json"
    if not tj.exists():
        return None
    branches = json.loads(tj.read_text()).get("branches", {})
    for name, val in branches.items():
        if test_id in val.get("tests", []):
            return name
    return None


def candidate_paths(test_id: str) -> list[str]:
    """Map a dotted pytest id to candidate repo-relative file paths.

    ``eval.tests.test_execution.TestX.test_y`` -> ``eval/tests/test_execution.py``
    ``tests.test_performance.test_empty_...``  -> ``tests/test_performance.py``
                                              (and ``eval/`` prefixed as a fallback,
                                               since the pytest rootdir is ``eval/``)
    """
    parts = test_id.split(".")
    mod_i = next((i for i, p in enumerate(parts) if p.startswith("test_")), None)
    if mod_i is None:
        raise ValueError(f"could not find a test_* module segment in {test_id!r}")
    rel = "/".join(parts[: mod_i + 1]) + ".py"
    cands = [rel]
    if not rel.startswith("eval/"):
        cands.append("eval/" + rel)
    return cands


def extract_function(src: str, func: str) -> str:
    """Return the source of ``def <func>`` (dedented), body included."""
    lines = src.splitlines()
    start = next(
        (i for i, ln in enumerate(lines) if re.match(rf"\s*def {re.escape(func)}\s*\(", ln)),
        None,
    )
    if start is None:
        raise ValueError(f"function {func!r} not found in source")
    indent = len(lines[start]) - len(lines[start].lstrip())
    body = [lines[start]]
    for ln in lines[start + 1 :]:
        if ln.strip() and (len(ln) - len(ln.lstrip())) <= indent:
            break
        body.append(ln)
    while body and not body[-1].strip():
        body.pop()
    return textwrap.dedent("\n".join(body))


def fetch_source(instance: str, test_id: str, repo_tasks: Path, branch: str | None) -> str:
    token = os.environ.get("GITHUB_TOKEN")
    branch = branch or resolve_branch(instance, test_id, repo_tasks)
    if not branch:
        sys.exit(
            f"error: could not resolve a test branch for {test_id} in {instance}.\n"
            f"       checked {repo_tasks / instance / 'tests.json'} — pass --branch to override."
        )
    func = test_id.split(".")[-1]
    for path in candidate_paths(test_id):
        url = f"https://raw.githubusercontent.com/{GH_ORG}/{instance}/{branch}/{path}"
        body = _http_get(url, token)
        if body is not None:
            return extract_function(body, func)
    sys.exit(
        f"error: could not fetch test source from mirror {GH_ORG}/{instance}@{branch}.\n"
        f"       tried {candidate_paths(test_id)} — is $GITHUB_TOKEN set and valid?"
    )


def auto_title(instance: str, model: str | None, score: str | None) -> str:
    owner, rest = instance.split("__", 1)
    repo = rest.rsplit(".", 1)[0]
    who = f"{owner}/{repo}"
    if model and score:
        return f"{model}: {score} tests on  {who}"
    if model:
        return f"{model} on  {who}"
    return who


def auto_subtitle(test_id: str) -> str:
    parts = test_id.split(".")
    mod_i = next(i for i, p in enumerate(parts) if p.startswith("test_"))
    path = "/".join(parts[: mod_i + 1]) + ".py"
    if not path.startswith("eval/"):
        path = "eval/" + path
    return f"{path}  ·  {parts[-1]}"


# ============================================================================
# Rendering
# ============================================================================
def classify(lines: list[str], hl_prefixes: tuple[str, ...]) -> list[tuple[str, str]]:
    out, in_doc = [], False
    for ln in lines:
        s, tq = ln.strip(), ln.count('"""')
        if in_doc:
            out.append((ln, "dim"))
            if tq % 2 == 1:
                in_doc = False
        elif s.startswith('"""') and tq == 1:
            out.append((ln, "dim"))
            in_doc = True
        elif s.startswith('"""'):
            out.append((ln, "dim"))
        elif s.startswith("#"):
            out.append((ln, "dim"))
        elif any(s.startswith(p) for p in hl_prefixes):
            out.append((ln, "hl"))
        else:
            out.append((ln, "code"))
    return out


def _measure(text: str, size: int, weight: str = "normal", family: str = "monospace") -> tuple[float, float]:
    """Width/height of ``text`` in inches at ``DPI`` (via a throwaway figure)."""
    import matplotlib.pyplot as plt

    fig = plt.figure(dpi=DPI)
    t = fig.text(0, 0, text, fontsize=size, fontweight=weight, family=family)
    fig.canvas.draw()
    bb = t.get_window_extent(renderer=fig.canvas.get_renderer())
    plt.close(fig)
    return bb.width / DPI, bb.height / DPI


def render(title: str, subtitle: str, code: str, out: Path, hl_prefixes: tuple[str, ...]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch

    lines = code.rstrip("\n").split("\n")
    tagged = classify(lines, hl_prefixes)
    n = len(lines)

    charw, _ = _measure("M" * 80, FS_CODE)
    charw /= 80
    line_in = FS_CODE * 1.6 / 72  # comfortable code line spacing
    maxlen = max((len(ln) for ln in lines), default=1)

    title_w, title_h = _measure(title, FS_TITLE, weight="bold", family="sans-serif")
    sub_w, sub_h = _measure(subtitle, FS_SUB)

    block_w = maxlen * charw
    block_h = n * line_in
    box_w = block_w + 2 * BOX_PADX
    box_h = block_h + 2 * BOX_PADY

    content_w = max(box_w, title_w, sub_w)
    fig_w = content_w + 2 * SIDE
    fig_h = TOP + title_h + TITLE_GAP + sub_h + SUB_GAP + box_h + BOTTOM

    fig = plt.figure(figsize=(fig_w, fig_h), dpi=DPI)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    def fy(y_in: float) -> float:  # inches-from-top -> figure fraction
        return 1 - y_in / fig_h

    cx = 0.5

    # title + subtitle (centered)
    ax.text(cx, fy(TOP), title, ha="center", va="top", transform=ax.transAxes,
            fontsize=FS_TITLE, fontweight="bold", color=TITLE_C)
    ax.text(cx, fy(TOP + title_h + TITLE_GAP), subtitle, ha="center", va="top",
            transform=ax.transAxes, fontsize=FS_SUB, family="monospace", color=SUB_C)

    # code box
    box_top = TOP + title_h + TITLE_GAP + sub_h + SUB_GAP
    box_left_frac = (fig_w - box_w) / 2 / fig_w
    ax.add_patch(FancyBboxPatch(
        (box_left_frac, fy(box_top + box_h)),
        box_w / fig_w, box_h / fig_h,
        boxstyle="round,pad=0,rounding_size=0.02",
        mutation_aspect=fig_w / fig_h,
        facecolor=BOX_FILL, edgecolor=BOX_EDGE, linewidth=1.4,
        transform=ax.transAxes, zorder=1,
    ))

    # code lines
    code_left = (box_left_frac * fig_w + BOX_PADX) / fig_w
    cmap = {"code": CODE_C, "dim": DIM_C, "hl": HL_C}
    y = box_top + BOX_PADY
    for ln, kind in tagged:
        ax.text(code_left, fy(y), ln or " ", ha="left", va="top", transform=ax.transAxes,
                fontsize=FS_CODE, family="monospace", color=cmap[kind], zorder=2)
        y += line_in

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor=BG)
    plt.close(fig)
    print(f"saved: {out}")


# ============================================================================
def main() -> None:
    here = Path(__file__).resolve()
    default_tasks = here.parent.parent.parent / "repo" / "tasks"

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_argument_group("source (fetch mode)")
    src.add_argument("--instance", help="Task instance id, e.g. agourlay__zip-password-finder.704700d")
    src.add_argument("--test", help="Dotted pytest id, e.g. tests.test_performance.test_empty_charset_file_error")
    src.add_argument("--branch", help="Mirror test branch (else resolved from --repo-tasks).")
    src.add_argument("--repo-tasks", type=Path, default=default_tasks, help="Path to repo/tasks/ (for branch lookup).")
    man = p.add_argument_group("source (manual mode)")
    man.add_argument("--code-file", type=Path, help="Read code from this file ('-' for stdin).")
    txt = p.add_argument_group("labels + output")
    txt.add_argument("--title", help="Override the title.")
    txt.add_argument("--subtitle", help="Override the subtitle.")
    txt.add_argument("--model", help="Model name for the auto title, e.g. 'Opus 4.8'.")
    txt.add_argument("--score", help="'passed / total' string for the auto title, e.g. '676 / 677'.")
    txt.add_argument("--highlight", default="assert", help="Comma-separated line prefixes to accent (default: assert).")
    txt.add_argument("--out", type=Path, required=True, help="Output PNG path.")
    args = p.parse_args()

    if args.code_file:
        code = sys.stdin.read() if str(args.code_file) == "-" else args.code_file.read_text()
        title = args.title or ""
        subtitle = args.subtitle or ""
    elif args.instance and args.test:
        code = fetch_source(args.instance, args.test, args.repo_tasks, args.branch)
        title = args.title or auto_title(args.instance, args.model, args.score)
        subtitle = args.subtitle or auto_subtitle(args.test)
    else:
        p.error("supply either --code-file, or both --instance and --test")

    hl = tuple(s.strip() for s in args.highlight.split(",") if s.strip())
    render(title, subtitle, code, args.out, hl)


if __name__ == "__main__":
    main()
