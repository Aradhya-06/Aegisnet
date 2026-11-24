"""Predict congestion class for the current lab measurements (uses the trained model)."""
from __future__ import annotations

from pathlib import Path

from .features import FEATURES, threshold_baseline
from .train import MLError, _import


def load_model(model_dir):
    joblib, *_ = _import()
    path = Path(model_dir) / "model.joblib"
    if not path.exists():
        raise MLError("no trained model yet - collect a dataset and train first")
    return joblib.load(path)


def predict_row(model_dir, row: dict) -> dict:
    _, pd, *_ = _import()
    model = load_model(model_dir)
    frame = pd.DataFrame([[row.get(f) or 0 for f in FEATURES]], columns=FEATURES)
    proba = model.predict_proba(frame)[0]
    return {"ml": str(model.predict(frame)[0]),
            "probabilities": {str(c): round(float(p), 3) for c, p in zip(model.classes_, proba)},
            "threshold": threshold_baseline(row), "features": {f: row.get(f) for f in FEATURES}}
