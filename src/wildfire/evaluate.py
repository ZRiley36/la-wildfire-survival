"""Step 5: spatial validation. Writes data/processed/model_metrics.json and data/interim/05_predictions.parquet.

Why no random row splits: neighbors share outcomes (a whole block either burned or didn't), so a random split
puts a building's next-door neighbor in the training set and the model gets graded on near-copies of what it
trained on. Every split here keeps whole areas apart:

  cross_fire   train on one fire, test on the other (both directions)
  block_cv     500 m grid blocks dealt into 5 folds; a block is never on both sides of a split

Models: a constant base rate, the hazard-zone baselines, logistic regression and gradient boosting, all fit on the
training fold only. Metrics: ROC AUC, PR AUC (average precision), Brier score, calibration curve.
"""
import json

import geopandas as gpd
import numpy as np
import pandas as pd
from sklearn.calibration import calibration_curve
from sklearn.inspection import partial_dependence, permutation_importance
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from wildfire.config import PROCESSED, cfg, interim
from wildfire.model import ConstantBaseline, ZoneBaseline, make_model

ZONE_COLS = ["vhfhsz_in_effect", "vhfhsz_lra_2025"]
POST_FIRE_DEMO = ["post_roofconstruction", "post_eaves", "post_ventscreen", "post_exteriorsiding", "post_windowpane",
                  "post_deckporchongrade", "post_deckporchelevated", "post_patiocovercarport",
                  "post_fenceattachedtostructure"]


def log(msg):
    print(f"  {msg}")


def block_ids(points, size_m):
    """Grid-cell label for each point (metric CRS)."""
    return (np.floor(points.x / size_m).astype(int).astype(str) + "_" +
            np.floor(points.y / size_m).astype(int).astype(str)).values


def assign_block_folds(blocks, n_folds, seed):
    """Deal whole blocks into folds. Blocks are shuffled with a fixed seed and assigned greedily to the fold with
    the fewest buildings so far, so folds come out about the same size. Returns a fold number per row."""
    counts = pd.Series(blocks).value_counts()
    rng = np.random.default_rng(seed)
    order = rng.permutation(counts.index.to_numpy())
    load = np.zeros(n_folds)
    fold_of = {}
    for blk in sorted(order, key=lambda b: -counts[b]):  # big blocks first, ties in shuffled order
        k = int(np.argmin(load))
        fold_of[blk] = k
        load[k] += counts[blk]
    return np.array([fold_of[b] for b in blocks])


def splits(df, scheme, c):
    if scheme == "cross_fire":
        for train_fire, test_fire in [("EATON", "PALISADES"), ("PALISADES", "EATON")]:
            yield f"{train_fire.lower()}->{test_fire.lower()}", (df.fire == train_fire).values, (df.fire == test_fire).values
    elif scheme == "block_cv":
        for k in range(c["validation"]["n_folds"]):
            yield f"fold{k}", (df.fold != k).values, (df.fold == k).values


def metrics(y, p):
    return {"roc_auc": round(float(roc_auc_score(y, p)), 4), "pr_auc": round(float(average_precision_score(y, p)), 4),
            "brier": round(float(brier_score_loss(y, p)), 4), "n": int(len(y)), "base_rate": round(float(np.mean(y)), 4)}


def models(c, features):
    seed = c["seed"]
    return {
        "constant": (ConstantBaseline, None),
        "fhsz_in_effect": (lambda: ZoneBaseline("vhfhsz_in_effect"), ["vhfhsz_in_effect"]),
        "fhsz_lra_2025_postfire": (lambda: ZoneBaseline("vhfhsz_lra_2025"), ["vhfhsz_lra_2025"]),
        "logistic": (lambda: make_model("logistic", c["models"]["logistic"], seed), features),
        "hgb": (lambda: make_model("hgb", c["models"]["hgb"], seed), features),
    }


def run(df, y_col, c, features, schemes=("cross_fire", "block_cv"), keep_oof=True, importance=True):
    out, oof = {}, {}
    for scheme in schemes:
        out[scheme] = {}
        preds = {m: np.full(len(df), np.nan) for m in models(c, features)}
        imp = []
        for split_name, tr, te in splits(df, scheme, c):
            y_tr, y_te = df.loc[tr, y_col].values, df.loc[te, y_col].values
            for name, (factory, cols) in models(c, features).items():
                X_tr = df.loc[tr, cols] if cols else df.loc[tr, features]
                X_te = df.loc[te, cols] if cols else df.loc[te, features]
                m = factory().fit(X_tr, y_tr)
                p = m.predict_proba(X_te)[:, 1]
                preds[name][te] = p
                if scheme == "cross_fire":
                    out[scheme].setdefault(split_name, {})[name] = metrics(y_te, p)
                if importance and name == "hgb":
                    r = permutation_importance(m, X_te, y_te, scoring="roc_auc", n_repeats=c["validation"]["permutation_repeats"],
                                               random_state=c["seed"], n_jobs=-1)
                    imp.append(pd.DataFrame({"feature": features, "importance": r.importances_mean, "split": split_name}))
        if scheme == "block_cv":
            y = df[y_col].values
            out[scheme]["pooled_oof"] = {name: metrics(y, p) for name, p in preds.items()}
            out[scheme]["pooled_oof_by_fire"] = {
                fire: {name: metrics(y[(df.fire == fire).values], p[(df.fire == fire).values]) for name, p in preds.items()}
                for fire in df.fire.unique()}
            out[scheme]["calibration"] = {}
            for name in ["logistic", "hgb", "fhsz_in_effect"]:
                pt, pp = calibration_curve(y, preds[name], n_bins=c["validation"]["calibration_bins"], strategy="quantile")
                out[scheme]["calibration"][name] = {"predicted": np.round(pp, 4).tolist(), "observed": np.round(pt, 4).tolist()}
            if keep_oof:
                oof = preds
        if importance and imp:
            t = pd.concat(imp).groupby("feature").importance.agg(["mean", "std"]).sort_values("mean", ascending=False)
            out[scheme]["permutation_importance_hgb"] = t.round(4).reset_index().to_dict("records")
    return out, oof


def block_bootstrap_auc_diff(df, y_col, p_a, p_b, reps, seed):
    """95% interval for AUC(a) - AUC(b), resampling whole 500 m blocks rather than buildings."""
    rng = np.random.default_rng(seed)
    blocks = df.block.values
    uniq = np.unique(blocks)
    idx_by_block = pd.Series(np.arange(len(df))).groupby(blocks).apply(np.array)
    y = df[y_col].values
    diffs = []
    for _ in range(reps):
        take = np.concatenate(idx_by_block.loc[rng.choice(uniq, len(uniq))].values)
        if y[take].min() == y[take].max():
            continue
        diffs.append(roc_auc_score(y[take], p_a[take]) - roc_auc_score(y[take], p_b[take]))
    return [round(float(np.percentile(diffs, 2.5)), 4), round(float(np.percentile(diffs, 97.5)), 4)]


def partial_dependence_curves(df, y_col, c, features, which):
    m = make_model("hgb", c["models"]["hgb"], c["seed"]).fit(df[features], df[y_col])
    out = {}
    for f in which:
        r = partial_dependence(m, df[features], [f], grid_resolution=30, percentiles=(0.02, 0.98), kind="average")
        out[f] = {"grid": np.round(r["grid_values"][0], 3).tolist(), "average": np.round(r["average"][0], 4).tolist()}
    return out


def leakage_demo(df, y_col, c, features):
    """Clearly separate from the main model: what happens if the post-fire DINS fields are let in."""
    X = pd.get_dummies(df[POST_FIRE_DEMO].fillna("missing").astype(str), dtype=float)
    d2 = pd.concat([df[[y_col, "fold", "fire", "block"]], df[features], X], axis=1)
    res = {}
    for label, feats in [("pre_fire_only", features), ("post_fire_fields_only", list(X.columns)),
                         ("pre_plus_post_fire", features + list(X.columns))]:
        preds = np.full(len(d2), np.nan)
        for _, tr, te in splits(d2, "block_cv", c):
            m = make_model("hgb", c["models"]["hgb"], c["seed"]).fit(d2.loc[tr, feats], d2.loc[tr, y_col])
            preds[te] = m.predict_proba(d2.loc[te, feats])[:, 1]
        res[label] = metrics(d2[y_col].values, preds)
    unknown_only = [col for col in X.columns if col.endswith("_Unknown")]
    preds = np.full(len(d2), np.nan)
    for _, tr, te in splits(d2, "block_cv", c):
        m = make_model("logistic", c["models"]["logistic"], c["seed"]).fit(d2.loc[tr, unknown_only], d2.loc[tr, y_col])
        preds[te] = m.predict_proba(d2.loc[te, unknown_only])[:, 1]
    res["unknown_flags_only_logistic"] = metrics(d2[y_col].values, preds)
    return res


def prepare(b, c, pop_col):
    df = b[b[pop_col]].copy().reset_index(drop=True)
    pts = gpd.GeoSeries(df.sample_point, crs=b.crs)
    df["block"] = block_ids(pts, c["validation"]["block_size_m"])
    df["fold"] = assign_block_folds(df.block.values, c["validation"]["n_folds"], c["seed"])
    return df


def main():
    c = cfg()
    features = c["features"]["model"]
    b = gpd.read_parquet(interim("04_features"))
    df = prepare(b, c, "pop_main")
    log(f"main population: {len(df):,} buildings, {df.block.nunique()} blocks of {c['validation']['block_size_m']} m, "
        f"fold sizes {np.bincount(df.fold).tolist()}, destroyed {df.destroyed.mean():.1%}")
    log(f"fold destruction rates: {df.groupby('fold').destroyed.mean().round(3).tolist()}")

    results = {"population": "inside perimeter, residential, accessible", "n": len(df), "features": features,
               "seed": c["seed"]}
    main_res, oof = run(df, "destroyed", c, features)
    results["main"] = main_res
    for k, v in main_res["cross_fire"].items():
        log(f"{k}: " + ", ".join(f"{m} AUC {r['roc_auc']:.3f} Brier {r['brier']:.3f}" for m, r in v.items()))
    for m, r in main_res["block_cv"]["pooled_oof"].items():
        log(f"block CV {m}: AUC {r['roc_auc']:.3f}, PR AUC {r['pr_auc']:.3f}, Brier {r['brier']:.3f}")
    results["main"]["block_cv"]["auc_diff_ci95"] = {
        "hgb_minus_fhsz_in_effect": block_bootstrap_auc_diff(df, "destroyed", oof["hgb"], oof["fhsz_in_effect"], 500, c["seed"]),
        "hgb_minus_logistic": block_bootstrap_auc_diff(df, "destroyed", oof["hgb"], oof["logistic"], 500, c["seed"]),
    }
    log(f"AUC difference 95% CI (block bootstrap): {results['main']['block_cv']['auc_diff_ci95']}")

    top = [r["feature"] for r in main_res["block_cv"]["permutation_importance_hgb"][:4]]
    pd_feats = list(dict.fromkeys(top + ["dist_nearest_building_m", "year_built"]))
    results["partial_dependence_hgb"] = partial_dependence_curves(df, "destroyed", c, features, pd_feats)

    log("sensitivity: Major+Destroyed outcome")
    s1, _ = run(df, "destroyed_or_major", c, features, keep_oof=False, importance=False)
    results["sensitivity_destroyed_or_major"] = s1
    log("sensitivity: population with the 300 ft outside band")
    dfb = prepare(b, c, "pop_buffer")
    s2, _ = run(dfb, "destroyed", c, features, keep_oof=False, importance=False)
    results["sensitivity_buffer_population"] = {"n": len(dfb), "destroyed_rate": round(float(dfb.destroyed.mean()), 4), **s2}
    for name, s in [("major+destroyed", s1), ("buffer", s2)]:
        r = s["block_cv"]["pooled_oof"]
        log(f"  {name}: hgb AUC {r['hgb']['roc_auc']:.3f}, logistic {r['logistic']['roc_auc']:.3f}, "
            f"fhsz {r['fhsz_in_effect']['roc_auc']:.3f}")

    log("leakage demo (post-fire DINS fields, separate from the main results)")
    results["leakage_demo_not_main_model"] = leakage_demo(df, "destroyed", c, features)
    for k, r in results["leakage_demo_not_main_model"].items():
        log(f"  {k}: AUC {r['roc_auc']:.3f}")

    PROCESSED.mkdir(parents=True, exist_ok=True)
    (PROCESSED / "model_metrics.json").write_text(json.dumps(results, indent=1))
    pred = df[["dins_id", "fire", "block", "fold", "destroyed"]].copy()
    for name, p in oof.items():
        pred[f"oof_{name}"] = p
    # cross-fire predictions, each building predicted by the model trained on the other fire
    for name in ["logistic", "hgb"]:
        pred[f"xfire_{name}"] = np.nan
        for fire, other in [("PALISADES", "EATON"), ("EATON", "PALISADES")]:
            tr, te = (df.fire == other).values, (df.fire == fire).values
            m = make_model(name, c["models"][name], c["seed"]).fit(df.loc[tr, features], df.loc[tr, "destroyed"])
            pred.loc[te, f"xfire_{name}"] = m.predict_proba(df.loc[te, features])[:, 1]
    pred.to_parquet(interim("05_predictions"))
    log("wrote model_metrics.json and 05_predictions.parquet")


if __name__ == "__main__":
    main()
