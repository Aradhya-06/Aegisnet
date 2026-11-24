"""Train and honestly evaluate the congestion classifier (needs requirements-ml.txt).

  python -m ml_extension.train data/ml/dataset.csv

Method: stratified 70/30 train/test split (random_state=42), RandomForest (200 trees).
All reported numbers are computed on the held-out TEST set only. The conventional
threshold detector is evaluated on the same test rows for comparison.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .features import FEATURES, LABELS, threshold_baseline


class MLError(ValueError):
    pass


def _import():
    try:
        import joblib
        import pandas as pd
        from sklearn import metrics
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.model_selection import train_test_split
    except ImportError as exc:
        raise MLError("scikit-learn / pandas are not installed: pip install -r requirements-ml.txt") from exc
    return joblib, pd, metrics, RandomForestClassifier, train_test_split


def load_dataset(csv_path):
    _, pd, *_ = _import()
    df = pd.read_csv(csv_path)
    missing = [c for c in FEATURES + ["label"] if c not in df.columns]
    if missing:
        raise MLError("dataset is missing columns: " + ", ".join(missing))
    df = df[FEATURES + ["label"]].dropna(subset=["label"])
    df = df[df["label"].isin(LABELS)]
    return df


def evaluate(y_true, y_pred, metrics):
    p, r, f, support = metrics.precision_recall_fscore_support(y_true, y_pred, labels=LABELS, zero_division=0)
    macro = metrics.precision_recall_fscore_support(y_true, y_pred, labels=LABELS, average="macro", zero_division=0)
    return {
        "accuracy": round(float(metrics.accuracy_score(y_true, y_pred)), 4),
        "macro_precision": round(float(macro[0]), 4), "macro_recall": round(float(macro[1]), 4), "macro_f1": round(float(macro[2]), 4),
        "per_class": {lab: {"precision": round(float(p[i]), 4), "recall": round(float(r[i]), 4), "f1": round(float(f[i]), 4), "support": int(support[i])}
                      for i, lab in enumerate(LABELS)},
        "confusion_matrix": metrics.confusion_matrix(y_true, y_pred, labels=LABELS).tolist(),
        "labels": LABELS,
    }


def train(csv_path, out_dir, min_per_class=20):
    joblib, pd, metrics, RF, split = _import()
    df = load_dataset(csv_path)
    counts = df["label"].value_counts().to_dict()
    short = [lab for lab in LABELS if counts.get(lab, 0) < min_per_class]
    if short:
        raise MLError(f"need at least {min_per_class} samples per class; too few for: {', '.join(short)} (have {counts})")
    X_train, X_test, y_train, y_test = split(df[FEATURES], df["label"], test_size=0.3, stratify=df["label"], random_state=42)
    model = RF(n_estimators=200, random_state=42, n_jobs=-1).fit(X_train, y_train)
    ml = evaluate(y_test, model.predict(X_test), metrics)
    base = evaluate(y_test, [threshold_baseline(r) for _, r in X_test.iterrows()], metrics)
    result = {
        "dataset": {"rows": int(len(df)), "per_class": {k: int(v) for k, v in counts.items()},
                    "train_rows": int(len(X_train)), "test_rows": int(len(X_test)), "source": str(csv_path)},
        "method": "RandomForest(200 trees), stratified 70/30 split, random_state=42; metrics on the test set only",
        "ml": ml, "threshold_baseline": base,
        "feature_importance": {f: round(float(i), 4) for f, i in sorted(zip(FEATURES, model.feature_importances_), key=lambda t: -t[1])},
    }
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, out_dir / "model.joblib")
    (out_dir / "metrics.json").write_text(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "data/ml/dataset.csv"
    print(json.dumps(train(path, Path(path).parent), indent=2))
