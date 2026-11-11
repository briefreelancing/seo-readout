"""Static PNG charts with one consistent, accessible style.

Colors come from a validated categorical palette (fixed order, never cycled).
Rules followed: one y-axis per chart (no dual axes), thin 2px lines, hairline
gridlines, legend for 2+ series plus direct labels at line ends, text in ink
colors rather than series colors.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"
SHADE = "#f0efec"
GAIN = "#2a78d6"   # diverging pole (blue)
LOSS = "#e34948"   # diverging pole (red)
OTHER = MUTED     # the folded "Other" series is neutral gray
MAX_SERIES = 4     # more than this folds into "Other"


def _style(ax, title: str | None, subtitle: str | None = None):
    ax.set_facecolor(SURFACE)
    for side in ["top", "right", "left"]:
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(BASELINE)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(colors=MUTED, labelsize=9, length=0)
    if title:
        ax.set_title(title, loc="left", fontsize=12, color=INK, fontweight="bold", pad=18 if subtitle else 8)
    if subtitle:
        ax.text(0, 1.02, subtitle, transform=ax.transAxes, fontsize=9, color=INK_2)


def _fmt(v, _=None):
    if abs(v) >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if abs(v) >= 1_000:
        return f"{v / 1_000:.0f}k" if abs(v) >= 10_000 else f"{v / 1_000:.1f}k"
    return f"{v:.0f}"


def _figure(h: float = 3.6, w: float = 9.0, rows: int = 1):
    fig, axes = plt.subplots(rows, 1, figsize=(w, h * rows), dpi=150, sharex=True)
    fig.patch.set_facecolor(SURFACE)
    return fig, axes


def line_chart(
    series: dict[str, tuple[list[date], list[float]]],
    path: Path,
    title: str,
    subtitle: str | None = None,
    shade: tuple[date, date] | None = None,
    shade_label: str = "Current period",
    vlines: list[tuple[date, str]] | None = None,
    ax=None,
):
    own = ax is None
    if own:
        fig, ax = _figure()
    _style(ax, title, subtitle)
    names = list(series)
    ends = []
    for i, name in enumerate(names):
        xs, ys = series[name]
        color = OTHER if name == "Other" else SERIES[i % len(SERIES)]
        ax.plot(xs, ys, color=color, linewidth=2, label=name, solid_capstyle="round")
        if xs:
            ends.append([float(ys[-1]), name, xs[-1]])
    if len(names) > 1 and ends:
        # Direct labels at line ends, nudged apart so they never overlap.
        top = max(max(v[1]) for v in series.values() if v[1]) or 1
        gap = top * 0.07
        ends.sort(key=lambda e: e[0])
        for j in range(1, len(ends)):
            if ends[j][0] - ends[j - 1][0] < gap:
                ends[j][0] = ends[j - 1][0] + gap
        for y, name, x in ends:
            ax.annotate(name, (x, y), xytext=(6, 0), textcoords="offset points",
                        fontsize=8, color=INK_2, va="center", annotation_clip=False)
    if shade:
        ax.axvspan(shade[0], shade[1], color=SHADE, zorder=0, label=None)
        ax.text(shade[0], 1.0, f" {shade_label}", transform=ax.get_xaxis_transform(), fontsize=8, color=MUTED, va="top")
    for d, label in vlines or []:
        ax.axvline(d, color=INK_2, linewidth=1, linestyle=(0, (3, 3)))
        ax.text(d, 0.92, f" {label}", transform=ax.get_xaxis_transform(), fontsize=8, color=INK, va="top")
    ax.yaxis.set_major_formatter(FuncFormatter(_fmt))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=8))
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(ax.xaxis.get_major_locator()))
    ax.set_ylim(bottom=0)
    if len(names) > 1:
        ax.legend(frameon=False, fontsize=8, labelcolor=INK_2, loc="upper left", bbox_to_anchor=(0, -0.12), ncol=min(len(names), 5))
    if own:
        fig.tight_layout()
        fig.savefig(path, facecolor=SURFACE)
        plt.close(fig)
    return path


def small_multiples(panels: list[dict], path: Path, title: str, subtitle: str | None = None,
                    shade=None, vlines=None):
    """Stacked panels sharing the x-axis, one measure per panel (instead of a dual axis)."""
    fig, axes = _figure(h=2.4, rows=len(panels))
    axes = axes if len(panels) > 1 else [axes]
    for ax, panel in zip(axes, panels):
        line_chart({panel["name"]: panel["data"]}, path, None, None, shade=shade, vlines=vlines, ax=ax)
        ax.set_title(panel["name"], loc="left", fontsize=10, color=INK_2, pad=6)
    H = fig.get_figheight()
    fig.text(0.01, 1 - 0.22 / H, title, ha="left", va="top", fontsize=12, color=INK, fontweight="bold")
    if subtitle:
        fig.text(0.01, 1 - 0.48 / H, subtitle, ha="left", va="top", fontsize=9, color=INK_2)
    fig.tight_layout(rect=(0, 0, 1, 1 - 0.75 / H))
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
    return path


def diverging_bars(items: list[tuple[str, float]], path: Path, title: str, subtitle: str | None = None,
                   value_fmt=lambda v: f"{v:+,.0f}"):
    """Horizontal bars for gains (blue) and losses (red) around zero."""
    items = list(reversed(items))
    fig, ax = _figure(h=max(2.4, 0.38 * len(items) + 1.2))
    _style(ax, None, None)
    H = fig.get_figheight()
    fig.text(0.01, 1 - 0.18 / H, title, ha="left", va="top", fontsize=12, color=INK, fontweight="bold")
    if subtitle:
        fig.text(0.01, 1 - 0.44 / H, subtitle, ha="left", va="top", fontsize=9, color=INK_2)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    labels = [lbl if len(lbl) <= 48 else lbl[:45] + "..." for lbl, _ in items]
    vals = [v for _, v in items]
    colors = [GAIN if v >= 0 else LOSS for v in vals]
    ax.barh(range(len(vals)), vals, color=colors, height=0.6)
    ax.axvline(0, color=BASELINE, linewidth=1)
    ax.set_yticks(range(len(vals)))
    ax.set_yticklabels(labels, fontsize=8.5, color=INK_2)
    span = max(abs(v) for v in vals) if vals else 1
    for i, v in enumerate(vals):
        ax.text(v + (span * 0.02 if v >= 0 else -span * 0.02), i, value_fmt(v), va="center",
                ha="left" if v >= 0 else "right", fontsize=8, color=INK)
    lo, hi = min(vals, default=0), max(vals, default=0)
    pad = span * 0.2  # room for the value labels on both sides
    ax.set_xlim(min(lo, 0) - pad, max(hi, 0) + pad)
    ax.xaxis.set_major_formatter(FuncFormatter(_fmt))
    fig.tight_layout(rect=(0, 0, 1, 1 - 0.65 / H))
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
    return path


def short_labels(names: list[str]) -> list[str]:
    """Drop the scheme and a shared domain from URLs so bar labels stay readable."""
    import re
    stripped = [re.sub(r"^https?://", "", str(n)) for n in names]
    domains = {s.split("/", 1)[0] for s in stripped if "/" in s}
    if len(domains) == 1 and all("/" in s for s in stripped):
        return ["/" + s.split("/", 1)[1] if s.split("/", 1)[1] else "/" for s in stripped]
    return stripped


def fold_series(totals: dict[str, float], keep: int = MAX_SERIES) -> list[str]:
    """Names of the largest series to keep; the rest are folded into 'Other'."""
    return [k for k, _ in sorted(totals.items(), key=lambda kv: -kv[1])[:keep]]
