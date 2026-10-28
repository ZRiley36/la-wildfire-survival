"""Step 8: figures in docs/figures/. Static PNGs for the docs.

Colors follow a validated categorical order (blue, orange, aqua). The hazard-zone line also gets a dashed
style and a direct label, because aqua is below 3:1 contrast on the light background.
"""
import json

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import precision_recall_curve, roc_curve

from wildfire.config import FIGURES, PROCESSED, interim

SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
MODELS = [("hgb", "Gradient boosting", BLUE, "-"), ("logistic", "Logistic regression", ORANGE, "-"),
          ("fhsz_in_effect", "Hazard zone (in effect Jan 2025)", AQUA, "--")]
FIRES = [("EATON", "Eaton", BLUE), ("PALISADES", "Palisades", ORANGE)]
NICE = {"elevation_m": "Elevation (m)", "dist_wildland_m": "Distance to wildland (m)", "year_built": "Year built",
        "n_buildings_50m": "Buildings within 50 m", "dist_nearest_building_m": "Nearest building (m)",
        "burnable_share_300m": "Burnable share, 300 m", "burnable_share_100m": "Burnable share, 100 m",
        "burnable_share_30m": "Burnable share, 30 m", "slope_deg": "Slope (deg)", "aspect_cos": "Aspect (north)",
        "aspect_sin": "Aspect (east)", "footprint_area_m2": "Footprint area (m²)",
        "n_buildings_30m": "Buildings within 30 m", "n_buildings_10m": "Buildings within 10 m",
        "fuel_burnable_at_building": "Burnable fuel at building", "built_after_2008": "Built after 2008"}

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "axes.titlecolor": INK, "axes.titlesize": 12,
    "axes.titleweight": "bold", "axes.titlelocation": "left", "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "xtick.color": MUTED, "ytick.color": MUTED,
    "xtick.labelcolor": INK2, "ytick.labelcolor": INK2, "font.size": 10, "legend.frameon": False,
    "legend.labelcolor": INK2, "lines.linewidth": 2, "lines.solid_capstyle": "round",
})


def log(msg):
    print(f"  {msg}")


def save(fig, name):
    p = FIGURES / name
    fig.savefig(p, dpi=160, bbox_inches="tight")
    plt.close(fig)
    log(f"{name}")


def note(fig, text):
    fig.text(0.0, -0.02, text, ha="left", va="top", fontsize=8.5, color=MUTED, wrap=True)


def roc_pr(pred, metrics):
    y = pred.destroyed.values
    fm = metrics["main"]["block_cv"]["fold_mean"]
    fig, (a, b) = plt.subplots(1, 2, figsize=(11, 4.6))
    for key, label, color, ls in MODELS:
        p = pred[f"oof_{key}"].values
        fpr, tpr, _ = roc_curve(y, p)
        a.plot(fpr, tpr, color=color, ls=ls, label=f"{label}  AUC {fm[key]['roc_auc']:.2f}")
        prec, rec, _ = precision_recall_curve(y, p)
        b.plot(rec, prec, color=color, ls=ls, label=f"{label}  AP {fm[key]['pr_auc']:.2f}")
    a.plot([0, 1], [0, 1], color=AXIS, lw=1, ls=":")
    a.text(0.62, 0.55, "random", color=MUTED, fontsize=8.5, rotation=38)
    b.axhline(y.mean(), color=AXIS, lw=1, ls=":")
    b.text(0.02, y.mean() - 0.035, f"base rate {y.mean():.0%}", color=MUTED, fontsize=8.5)
    a.set(title="ROC curve", xlabel="False positive rate", ylabel="True positive rate", xlim=(0, 1), ylim=(0, 1.01))
    b.set(title="Precision-recall curve", xlabel="Recall (destroyed homes found)", ylabel="Precision",
          xlim=(0, 1), ylim=(0.5, 1.01))
    a.legend(loc="lower right", fontsize=9)
    b.legend(loc="lower left", fontsize=9)
    fig.suptitle("Out-of-fold predictions, 5-fold cross-validation over 500 m blocks (16,306 homes)",
                 x=0.0, ha="left", color=INK2, fontsize=10, y=1.0)
    note(fig, "Legend values are the mean across folds. Curves pool all out-of-fold predictions.")
    save(fig, "fig1_roc_pr.png")


def calibration(metrics):
    cal = metrics["main"]["block_cv"]["calibration"]
    fig, ax = plt.subplots(figsize=(5.4, 5))
    ax.plot([0, 1], [0, 1], color=AXIS, lw=1, ls=":")
    ax.text(0.08, 0.13, "perfect calibration", color=MUTED, fontsize=8.5, rotation=42)
    for key, label, color, ls in MODELS:
        c = cal[key]
        ax.plot(c["predicted"], c["observed"], color=color, ls=ls, marker="o", ms=5, mec=SURFACE, mew=1.5, label=label)
    ax.set(title="Calibration", xlabel="Predicted chance of destruction", ylabel="Observed share destroyed",
           xlim=(0, 1), ylim=(0, 1))
    ax.legend(loc="upper left", fontsize=9)
    note(fig, "Out-of-fold predictions grouped into tenths. The hazard zone's predictions only vary by zone and fold "
              "(each fold's training destruction rate), so they cover a narrow band.")
    save(fig, "fig2_calibration.png")


def cross_fire(metrics):
    s = metrics["main"]["cross_fire"]["splits"]
    no_elev = metrics["sensitivity_no_elevation"]["cross_fire"]["splits"]
    groups = [("eaton->palisades", "Train Eaton → test Palisades"), ("palisades->eaton", "Train Palisades → test Eaton")]
    series = [("hgb", "Gradient boosting", BLUE, s), ("logistic", "Logistic regression", ORANGE, s),
              ("fhsz_in_effect", "Hazard zone (in effect)", AQUA, s)]
    fig, ax = plt.subplots(figsize=(9, 4.2))
    width = 0.24
    x = np.arange(len(groups))
    for i, (key, label, color, src) in enumerate(series):
        vals = [src[g][key]["roc_auc"] for g, _ in groups]
        bars = ax.bar(x + (i - 1) * width, vals, width - 0.02, color=color, label=label, zorder=3)
        for bar, v in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width() / 2, v + 0.01, f"{v:.2f}", ha="center", color=INK2, fontsize=9)
    ax.axhline(0.5, color=AXIS, lw=1, ls=":", zorder=2)
    ax.set_xticks(x, [g for _, g in groups])
    ax.set(title="Does it transfer to the other fire?", ylabel="ROC AUC on the other fire", ylim=(0.4, 0.8))
    ax.legend(loc="upper right", fontsize=9, ncols=3)
    ax.grid(axis="x", visible=False)
    ne = [no_elev[g]["logistic"]["roc_auc"] for g, _ in groups]
    note(fig, "0.5 is random ranking. The hazard zone can only predict a constant across fires: every Palisades home "
              f"was in a Very High zone.\nWithout elevation, logistic regression scores {ne[0]:.2f} and {ne[1]:.2f}: "
              "absolute elevation doesn't carry over between the fires.")
    save(fig, "fig3_cross_fire.png")


def importance(metrics):
    bc = pd.DataFrame(metrics["main"]["block_cv"]["permutation_importance_hgb"]).set_index("feature")
    xf = pd.DataFrame(metrics["main"]["cross_fire"]["permutation_importance_hgb"]).set_index("feature")
    order = (bc["mean"] + xf["mean"]).sort_values().index[-10:]
    fig, ax = plt.subplots(figsize=(8, 5))
    y = np.arange(len(order))
    for off, t, label, color in [(0.2, bc, "Block cross-validation", BLUE), (-0.2, xf, "Cross-fire (mean of both)", ORANGE)]:
        ax.barh(y + off, t.loc[order, "mean"], 0.38, color=color, label=label, zorder=3)
    ax.set_yticks(y, [NICE.get(f, f) for f in order])
    ax.set(title="What the model leans on", xlabel="Drop in ROC AUC when the feature is shuffled")
    ax.axvline(0, color=AXIS, lw=1)
    ax.grid(axis="y", visible=False)
    ax.legend(loc="lower right", fontsize=9)
    note(fig, "Permutation importance for gradient boosting, measured on held-out data only, 10 repeats.")
    save(fig, "fig4_importance.png")


def partial_dependence(metrics):
    pdd = metrics["partial_dependence_hgb"]
    feats = list(pdd)
    fig, axes = plt.subplots(1, len(feats), figsize=(3.1 * len(feats), 3.2), sharey=True)
    for ax, f in zip(axes, feats):
        ax.plot(pdd[f]["grid"], pdd[f]["average"], color=BLUE)
        ax.set_title(NICE.get(f, f), fontsize=10)
        if f == "dist_nearest_building_m":
            ax.set_xlim(0, 30)
        if f == "dist_wildland_m":
            ax.set_xlim(0, None)
    axes[0].set_ylabel("Average predicted\nchance of destruction")
    fig.suptitle("Partial dependence, gradient boosting fit on all 16,306 homes", x=0.0, ha="left",
                 color=INK, fontsize=12, fontweight="bold", y=1.04)
    note(fig, "Each line holds every other feature at its observed values. Ranges cover the 2nd to 98th percentile. "
              "Distance to wildland is partly a selection effect (see findings).")
    save(fig, "fig5_partial_dependence.png")


def destruction_rates():
    b = gpd.read_parquet(interim("04_features"))
    m = b[b.pop_main]
    panels = [
        ("dist_nearest_building_m", [-0.01, 2, 5, 10, 20, np.inf], ["≤2 m", "2–5 m", "5–10 m", "10–20 m", ">20 m"],
         "By distance to the nearest building"),
        ("year_built", [0, 1939, 1959, 1979, 1999, 2008, 2100], ["<1940", "1940–59", "1960–79", "1980–99",
                                                                 "2000–08", "2009+"], "By year built"),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), sharey=True)
    for ax, (col, bins, labels, title) in zip(axes, panels):
        x = np.arange(len(labels))
        for i, (fire, name, color) in enumerate(FIRES):
            g = m[m.fire == fire]
            r = g.groupby(pd.cut(g[col], bins, labels=labels), observed=False).destroyed.agg(["mean", "size"])
            bars = ax.bar(x + (i - 0.5) * 0.38, r["mean"], 0.36, color=color, label=name, zorder=3)
            for bar, (v, n) in zip(bars, r.itertuples(index=False)):
                if n:
                    ax.text(bar.get_x() + bar.get_width() / 2, v + 0.015, f"{v:.0%}", ha="center", color=INK2, fontsize=8)
        ax.set_xticks(x, labels)
        ax.set_title(title, fontsize=11)
        ax.grid(axis="x", visible=False)
    axes[0].set_ylabel("Share destroyed")
    axes[0].yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1, decimals=0))
    axes[0].set_ylim(0, 1.05)
    axes[1].legend(loc="upper right", fontsize=9)
    fig.suptitle("Destruction rates inside the perimeters", x=0.0, ha="left", color=INK, fontsize=12,
                 fontweight="bold", y=1.03)
    note(fig, "Residential buildings inside each fire's perimeter. Raw rates, not model output.")
    save(fig, "fig6_destruction_rates.png")


def main():
    FIGURES.mkdir(parents=True, exist_ok=True)
    metrics = json.loads((PROCESSED / "model_metrics.json").read_text())
    pred = pd.read_parquet(interim("05_predictions"))
    roc_pr(pred, metrics)
    calibration(metrics)
    cross_fire(metrics)
    importance(metrics)
    partial_dependence(metrics)
    destruction_rates()


if __name__ == "__main__":
    main()
