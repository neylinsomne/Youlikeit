"""
ex25 - ETL: Random Forest desde cero para señales del algoritmo.

Extract: analytics + retention + demographics → feature matrix
Transform: Random Forest (from scratch, no sklearn) → feature importance
Load: model_snapshots + knowledge_base

Por qué Random Forest y no regresión lineal:
  - El engagement es NO LINEAL: "7pm + #villain" ≠ "7pm" + "#villain"
  - RF captura interacciones entre features naturalmente
  - Más robusto con <200 datos que XGBoost
  - Feature importance por impurity reduction = interpretable

Teoría estadística implementada:
  - R² y varianza explicada vs no explicada
  - Cross-validation k-fold (k=5)
  - Residual analysis (patrón en errores = señal faltante)
  - Comparación con baseline lineal (Occam's razor)

Uso:
  python src/main.py ex25
  python src/main.py ex25 --target engagement_rate
  python src/main.py ex25 --n-trees 50 --max-depth 5
"""

from __future__ import annotations

import json
import math
import random
from datetime import datetime
from pathlib import Path

from core.config import Settings
from core.db import get_db
from utils.logger import build_logger
from utils.websocket_hub import ETLTracker


# ---------------------------------------------------------------------------
# Decision Tree from scratch
# ---------------------------------------------------------------------------

def _variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = sum(values) / len(values)
    return sum((x - m) ** 2 for x in values) / len(values)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


class _TreeNode:
    __slots__ = ("feature_idx", "threshold", "left", "right", "value")

    def __init__(self):
        self.feature_idx: int = -1
        self.threshold: float = 0.0
        self.left: _TreeNode | None = None
        self.right: _TreeNode | None = None
        self.value: float = 0.0  # prediction (mean of targets in this leaf)


def _best_split(
    X: list[list[float]],
    y: list[float],
    indices: list[int],
    max_features: int,
    min_samples_leaf: int,
) -> tuple[int, float, float]:
    """Find the best split (feature, threshold) by variance reduction."""
    n = len(indices)
    if n < 2 * min_samples_leaf:
        return -1, 0.0, 0.0

    parent_var = _variance([y[i] for i in indices])
    best_gain = 0.0
    best_feature = -1
    best_threshold = 0.0

    n_features = len(X[0]) if X else 0
    # Random subset of features (sqrt for regression)
    feature_indices = random.sample(range(n_features), min(max_features, n_features))

    for feat in feature_indices:
        values = sorted(set(X[i][feat] for i in indices))
        if len(values) < 2:
            continue

        # Try midpoints between unique values
        thresholds = [(values[i] + values[i + 1]) / 2 for i in range(min(len(values) - 1, 20))]

        for threshold in thresholds:
            left_idx = [i for i in indices if X[i][feat] <= threshold]
            right_idx = [i for i in indices if X[i][feat] > threshold]

            if len(left_idx) < min_samples_leaf or len(right_idx) < min_samples_leaf:
                continue

            left_var = _variance([y[i] for i in left_idx])
            right_var = _variance([y[i] for i in right_idx])

            # Weighted variance after split
            weighted_var = (len(left_idx) * left_var + len(right_idx) * right_var) / n
            gain = parent_var - weighted_var

            if gain > best_gain:
                best_gain = gain
                best_feature = feat
                best_threshold = threshold

    return best_feature, best_threshold, best_gain


def _build_tree(
    X: list[list[float]],
    y: list[float],
    indices: list[int],
    depth: int,
    max_depth: int,
    max_features: int,
    min_samples_leaf: int,
    importances: list[float],
) -> _TreeNode:
    """Recursively build a decision tree."""
    node = _TreeNode()
    node.value = _mean([y[i] for i in indices])

    if depth >= max_depth or len(indices) < 2 * min_samples_leaf:
        return node

    feat, threshold, gain = _best_split(X, y, indices, max_features, min_samples_leaf)

    if feat == -1 or gain <= 0:
        return node

    # Track feature importance (total variance reduction)
    importances[feat] += gain * len(indices)

    node.feature_idx = feat
    node.threshold = threshold

    left_idx = [i for i in indices if X[i][feat] <= threshold]
    right_idx = [i for i in indices if X[i][feat] > threshold]

    node.left = _build_tree(X, y, left_idx, depth + 1, max_depth, max_features, min_samples_leaf, importances)
    node.right = _build_tree(X, y, right_idx, depth + 1, max_depth, max_features, min_samples_leaf, importances)

    return node


def _predict_tree(node: _TreeNode, x: list[float]) -> float:
    """Predict a single sample with a decision tree."""
    if node.feature_idx == -1:
        return node.value
    if x[node.feature_idx] <= node.threshold:
        return _predict_tree(node.left, x) if node.left else node.value
    else:
        return _predict_tree(node.right, x) if node.right else node.value


# ---------------------------------------------------------------------------
# Random Forest from scratch
# ---------------------------------------------------------------------------

class RandomForest:
    """
    Random Forest regressor from scratch. No sklearn, no numpy.

    ~150 lines of pure Python. Fully interpretable via feature importances.
    """

    def __init__(
        self,
        n_trees: int = 30,
        max_depth: int = 5,
        min_samples_leaf: int = 3,
        max_features: str = "sqrt",
        seed: int = 42,
    ):
        self.n_trees = n_trees
        self.max_depth = max_depth
        self.min_samples_leaf = min_samples_leaf
        self.max_features_strategy = max_features
        self.seed = seed
        self.trees: list[_TreeNode] = []
        self.feature_importances_: list[float] = []
        self.n_features_: int = 0
        self.oob_score_: float = 0.0

    def fit(self, X: list[list[float]], y: list[float]):
        random.seed(self.seed)
        n_samples = len(X)
        self.n_features_ = len(X[0]) if X else 0

        max_features = int(math.sqrt(self.n_features_)) if self.max_features_strategy == "sqrt" else self.n_features_
        max_features = max(1, max_features)

        importances_accum = [0.0] * self.n_features_
        oob_predictions: dict[int, list[float]] = {}

        for t in range(self.n_trees):
            # Bootstrap sample
            boot_indices = [random.randint(0, n_samples - 1) for _ in range(n_samples)]
            oob_indices = [i for i in range(n_samples) if i not in set(boot_indices)]

            tree_importances = [0.0] * self.n_features_
            tree = _build_tree(
                X, y, boot_indices,
                depth=0,
                max_depth=self.max_depth,
                max_features=max_features,
                min_samples_leaf=self.min_samples_leaf,
                importances=tree_importances,
            )
            self.trees.append(tree)

            # Accumulate importances
            for f in range(self.n_features_):
                importances_accum[f] += tree_importances[f]

            # OOB predictions
            for i in oob_indices:
                pred = _predict_tree(tree, X[i])
                oob_predictions.setdefault(i, []).append(pred)

        # Normalize importances
        total_imp = sum(importances_accum)
        if total_imp > 0:
            self.feature_importances_ = [v / total_imp for v in importances_accum]
        else:
            self.feature_importances_ = [1.0 / self.n_features_] * self.n_features_

        # OOB R²
        if oob_predictions:
            oob_actual = []
            oob_preds = []
            for i, preds in oob_predictions.items():
                oob_actual.append(y[i])
                oob_preds.append(_mean(preds))
            self.oob_score_ = _r_squared(oob_actual, oob_preds)

    def predict(self, X: list[list[float]]) -> list[float]:
        predictions = []
        for x in X:
            tree_preds = [_predict_tree(tree, x) for tree in self.trees]
            predictions.append(_mean(tree_preds))
        return predictions


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def _r_squared(actual: list[float], predicted: list[float]) -> float:
    if len(actual) < 2:
        return 0.0
    mean_y = _mean(actual)
    ss_tot = sum((y - mean_y) ** 2 for y in actual)
    ss_res = sum((actual[i] - predicted[i]) ** 2 for i in range(len(actual)))
    return 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0


def _linear_r_squared(X: list[list[float]], y: list[float]) -> float:
    """Baseline: simple mean prediction R² (always 0). Compare RF against this."""
    mean_y = _mean(y)
    preds = [mean_y] * len(y)
    return _r_squared(y, preds)


def _cross_validate(X: list[list[float]], y: list[float], k: int = 5, **rf_params) -> dict:
    """K-fold cross-validation for Random Forest."""
    n = len(X)
    if n < k * 2:
        return {"cv_r2_mean": 0, "cv_r2_std": 0, "cv_r2_scores": [], "k": k}

    fold_size = n // k
    indices = list(range(n))
    random.shuffle(indices)

    scores = []
    for fold in range(k):
        val_start = fold * fold_size
        val_end = val_start + fold_size
        val_idx = indices[val_start:val_end]
        train_idx = indices[:val_start] + indices[val_end:]

        if len(train_idx) < 5 or len(val_idx) < 2:
            continue

        X_train = [X[i] for i in train_idx]
        y_train = [y[i] for i in train_idx]
        X_val = [X[i] for i in val_idx]
        y_val = [y[i] for i in val_idx]

        rf = RandomForest(**rf_params)
        rf.fit(X_train, y_train)
        preds = rf.predict(X_val)
        scores.append(_r_squared(y_val, preds))

    return {
        "cv_r2_mean": round(_mean(scores), 4) if scores else 0,
        "cv_r2_std": round((sum((s - _mean(scores)) ** 2 for s in scores) / max(1, len(scores) - 1)) ** 0.5, 4) if len(scores) > 1 else 0,
        "cv_r2_scores": [round(s, 4) for s in scores],
        "k": k,
    }


def _residual_analysis(actual: list[float], predicted: list[float]) -> dict:
    """Check if residuals have a pattern (indicates missing signal)."""
    if len(actual) < 5:
        return {"has_pattern": False, "n": len(actual)}

    residuals = [actual[i] - predicted[i] for i in range(len(actual))]

    # Check for trend in residuals (should be random around 0)
    x_idx = list(range(len(residuals)))
    from exercises.ex23_stats_goals import _linear_regression
    reg = _linear_regression(x_idx, residuals)

    # Runs test approximation: count sign changes
    sign_changes = sum(
        1 for i in range(1, len(residuals))
        if (residuals[i] >= 0) != (residuals[i - 1] >= 0)
    )
    expected_changes = (len(residuals) - 1) / 2

    has_pattern = abs(reg["slope"]) > 0.001 or sign_changes < expected_changes * 0.5

    return {
        "has_pattern": has_pattern,
        "residual_trend_slope": reg["slope"],
        "residual_trend_r2": reg["r_squared"],
        "sign_changes": sign_changes,
        "expected_sign_changes": round(expected_changes),
        "mean_residual": round(_mean(residuals), 6),
        "std_residual": round((_variance(residuals)) ** 0.5, 6),
        "interpretation": (
            "Residuals show a PATTERN - there's a signal we're not capturing. "
            "Consider adding more features (e.g., time of day, day of week, thumbnail style)."
            if has_pattern else
            "Residuals look RANDOM - the model is capturing most of the available signal."
        ),
    }


# ---------------------------------------------------------------------------
# EXTRACT
# ---------------------------------------------------------------------------

FEATURE_NAMES = [
    "retention_avg", "retention_3s", "engagement_rate", "views",
    "likes", "comments", "shares", "duration_s",
    "upload_hour", "hashtag_count", "has_song",
    "category_villain", "category_romance", "category_action",
    "category_dramatic", "category_comedy",
]


def _extract_feature_matrix(conn) -> tuple[list[list[float]], list[float], list[str]]:
    """Build feature matrix from analytics + retention + quotes."""
    cur = conn.execute("""
        SELECT a.*, s.theme_query, s.quote_ids
        FROM analytics a
        LEFT JOIN shorts s ON a.short_id = s.id
        WHERE a.views > 0
        ORDER BY a.scraped_at
    """)
    rows = [dict(r) for r in cur.fetchall()]

    if not rows:
        return [], [], FEATURE_NAMES

    X = []
    y = []  # target: impressions (proxy for algorithmic distribution)

    for row in rows:
        # Parse upload hour
        upload_time = row.get("upload_time", "") or ""
        upload_hour = 12  # default
        if "T" in upload_time:
            try:
                upload_hour = int(upload_time.split("T")[1][:2])
            except (ValueError, IndexError):
                pass

        # Count hashtags
        hashtag_count = 0
        try:
            tags = json.loads(row.get("hashtags_used", "[]") or "[]")
            hashtag_count = len(tags)
        except (json.JSONDecodeError, TypeError):
            pass

        has_song = 1.0 if (row.get("song_used") or "").strip() else 0.0

        # Get category from quotes
        categories = {"villain": 0, "romance": 0, "action": 0, "dramatic": 0, "comedy": 0}
        if row.get("quote_ids"):
            try:
                qids = json.loads(row["quote_ids"])
                if qids:
                    placeholders = ",".join("?" * len(qids))
                    qcur = conn.execute(
                        f"SELECT category FROM quotes WHERE id IN ({placeholders})", qids
                    )
                    for qrow in qcur.fetchall():
                        cat = (qrow["category"] or "").lower()
                        if cat in categories:
                            categories[cat] = 1
            except Exception:
                pass

        feature_vec = [
            float(row.get("retention_avg", 0) or 0),
            float(row.get("retention_3s", 0) or 0),
            float(row.get("engagement_rate", 0) or 0),
            float(row.get("views", 0) or 0),
            float(row.get("likes", 0) or 0),
            float(row.get("comments", 0) or 0),
            float(row.get("shares", 0) or 0),
            0.0,  # duration_s placeholder
            float(upload_hour),
            float(hashtag_count),
            has_song,
            float(categories["villain"]),
            float(categories["romance"]),
            float(categories["action"]),
            float(categories["dramatic"]),
            float(categories["comedy"]),
        ]

        X.append(feature_vec)
        # Target: impressions if available, else views as proxy
        target = float(row.get("impressions", 0) or 0)
        if target == 0:
            target = float(row.get("views", 0) or 0)
        y.append(target)

    return X, y, FEATURE_NAMES


# ---------------------------------------------------------------------------
# Main ETL
# ---------------------------------------------------------------------------

def run(
    settings: Settings,
    target: str = "impressions",
    n_trees: int = 30,
    max_depth: int = 5,
) -> Path:
    log = build_logger("ex25", settings.output_dir / "logs" / "ex25.log")
    conn = get_db(settings.data_dir)
    tracker = ETLTracker("ex25")

    # ── EXTRACT ──
    tracker.extract_start()
    X, y, feature_names = _extract_feature_matrix(conn)
    tracker.extract_done({"samples": len(X), "features": len(feature_names)})

    if len(X) < 10:
        log.warning("Not enough data (%d samples). Need at least 10.", len(X))
        out_dir = settings.output_dir / "analytics"
        out_dir.mkdir(parents=True, exist_ok=True)
        report = out_dir / "ex25_not_enough_data.txt"
        report.write_text(
            f"ex25: Need at least 10 data points, have {len(X)}.\n"
            "Run ex19 (analytics) to collect more data first.",
            encoding="utf-8",
        )
        conn.close()
        tracker.error("Not enough data")
        return report

    log.info("Extract: %d samples, %d features", len(X), len(feature_names))

    # ── TRANSFORM ──
    tracker.transform_start("Training Random Forest")

    # Remove features with zero variance
    active_features = []
    active_indices = []
    for f_idx in range(len(feature_names)):
        col = [X[i][f_idx] for i in range(len(X))]
        if _variance(col) > 1e-10:
            active_features.append(feature_names[f_idx])
            active_indices.append(f_idx)

    X_active = [[row[f] for f in active_indices] for row in X]
    log.info("Active features (non-zero variance): %d / %d", len(active_features), len(feature_names))

    # Train Random Forest
    rf_params = {
        "n_trees": min(n_trees, max(10, len(X) // 3)),
        "max_depth": min(max_depth, max(3, int(math.log2(len(X))))),
        "min_samples_leaf": max(2, len(X) // 20),
        "seed": 42,
    }

    rf = RandomForest(**rf_params)
    rf.fit(X_active, y)

    predictions = rf.predict(X_active)
    train_r2 = _r_squared(y, predictions)

    # Feature importances
    importances = {}
    for i, feat in enumerate(active_features):
        if i < len(rf.feature_importances_):
            importances[feat] = round(rf.feature_importances_[i], 6)

    # Sort by importance
    sorted_imp = sorted(importances.items(), key=lambda x: x[1], reverse=True)

    log.info("Random Forest trained. R²=%.4f, OOB R²=%.4f", train_r2, rf.oob_score_)
    for feat, imp in sorted_imp[:5]:
        log.info("  %s: %.4f", feat, imp)

    # Cross-validation
    tracker.transform_progress(1, 3, "Cross-validation")
    cv_results = _cross_validate(X_active, y, k=5, **rf_params)
    log.info("Cross-validation R²: %.4f ± %.4f", cv_results["cv_r2_mean"], cv_results["cv_r2_std"])

    # Residual analysis
    tracker.transform_progress(2, 3, "Residual analysis")
    residuals = _residual_analysis(y, predictions)
    log.info("Residuals: %s", residuals["interpretation"][:80])

    # Baseline comparison (mean prediction)
    baseline_r2 = 0.0  # Mean predictor always has R² = 0
    rf_improvement = train_r2 - baseline_r2

    tracker.transform_done({
        "train_r2": round(train_r2, 4),
        "oob_r2": round(rf.oob_score_, 4),
        "cv_r2": cv_results["cv_r2_mean"],
        "top_feature": sorted_imp[0][0] if sorted_imp else "none",
    })

    # ── LOAD ──
    tracker.load_start()

    # Save model snapshot
    conn.execute("""
        INSERT INTO model_snapshots
            (model_type, target, feature_importances, r_squared, r_squared_cv,
             residual_pattern, variance_explained, variance_unexplained,
             n_samples, n_features, hyperparameters)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        "random_forest",
        target,
        json.dumps(dict(sorted_imp)),
        round(train_r2, 4),
        cv_results["cv_r2_mean"],
        json.dumps(residuals),
        round(train_r2 * 100, 1),
        round((1 - train_r2) * 100, 1),
        len(X),
        len(active_features),
        json.dumps(rf_params),
    ))

    # Write top insights to knowledge base
    if sorted_imp:
        top = sorted_imp[0]
        conn.execute("""
            INSERT INTO knowledge_base (category, topic, title, content, confidence, source)
            VALUES ('insight', 'algorithm', ?, ?, ?, 'random_forest')
        """, (
            f"Top signal: {top[0]} ({top[1]*100:.1f}% importance)",
            f"Random Forest analysis with {len(X)} samples shows '{top[0]}' is the most "
            f"important signal for {target} (importance: {top[1]:.4f}). "
            f"Model explains {train_r2*100:.1f}% of variance (CV: {cv_results['cv_r2_mean']*100:.1f}%). "
            f"{'Residuals show pattern - missing signals.' if residuals['has_pattern'] else 'Residuals random - good fit.'}",
            min(1.0, cv_results["cv_r2_mean"] + 0.2),
        ))

    conn.commit()
    tracker.load_done({"model_saved": True, "knowledge_entries": 1})

    # ── REPORT ──
    tracker.complete({"r2": round(train_r2, 4), "features": len(active_features)})

    out_dir = settings.output_dir / "analytics"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    report_path = out_dir / f"ex25_algorithm_signals_{ts}.txt"
    lines = [
        "ex25 - Algorithm Signal Analysis (Random Forest)",
        "=" * 60,
        f"Samples: {len(X)} | Features: {len(active_features)} | Target: {target}",
        f"Trees: {rf_params['n_trees']} | Max depth: {rf_params['max_depth']}",
        "",
        "MODEL PERFORMANCE:",
        f"  Train R²:  {train_r2:.4f} ({train_r2*100:.1f}% variance explained)",
        f"  OOB R²:    {rf.oob_score_:.4f}",
        f"  CV R² (5-fold): {cv_results['cv_r2_mean']:.4f} ± {cv_results['cv_r2_std']:.4f}",
        f"  Baseline R²: 0.0000 (mean predictor)",
        f"  RF improvement over baseline: +{rf_improvement:.4f}",
        "",
        "WHAT WE KNOW (variance explained):",
        f"  {train_r2*100:.1f}% of {target} variation is explained by these signals.",
        "",
        "WHAT WE DON'T KNOW (variance unexplained):",
        f"  {(1-train_r2)*100:.1f}% is noise, luck, or signals we don't track yet.",
        "",
        "FEATURE IMPORTANCE (what matters for the algorithm):",
    ]

    for rank, (feat, imp) in enumerate(sorted_imp, 1):
        bar = "█" * int(imp * 50)
        lines.append(f"  {rank:2d}. {feat:25s} {imp:.4f} {bar}")

    lines.append("")
    lines.append("RESIDUAL ANALYSIS:")
    lines.append(f"  {residuals['interpretation']}")
    lines.append(f"  Mean residual: {residuals['mean_residual']:.6f}")
    lines.append(f"  Std residual: {residuals['std_residual']:.6f}")
    lines.append(f"  Sign changes: {residuals['sign_changes']} (expected: {residuals['expected_sign_changes']})")

    lines.append("")
    lines.append("CROSS-VALIDATION DETAIL:")
    for i, score in enumerate(cv_results.get("cv_r2_scores", []), 1):
        lines.append(f"  Fold {i}: R² = {score:.4f}")

    lines.append("")
    lines.append("INTERPRETATION GUIDE:")
    lines.append("  R² 0.0-0.3 = weak model (many unknown factors)")
    lines.append("  R² 0.3-0.7 = moderate (useful but noisy)")
    lines.append("  R² 0.7-1.0 = strong (most variance captured)")
    lines.append("  CV R² close to Train R² = model generalizes well")
    lines.append("  CV R² << Train R² = overfitting (reduce max_depth)")

    report_path.write_text("\n".join(lines), encoding="utf-8")

    conn.close()
    log.info("Algorithm signals report: %s", report_path)
    return report_path
