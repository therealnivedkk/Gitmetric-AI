
from __future__ import annotations

import json
import os
from typing import Any

import joblib
import numpy as np

# Paths

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ML_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "ml"))

MODEL_PATH = os.path.join(ML_DIR, "model.pkl")
FEATURE_NAMES_PATH = os.path.join(ML_DIR, "feature_names.json")

# Lazy Singleton Loader

_model_artifact: dict | None = None
_feature_names: list[str] | None = None


def _load_artifacts() -> tuple[Any, Any, list[str]]:
    """
    Load model.pkl and feature_names.json once and cache them.
    Raises RuntimeError if artifacts are missing (train_classifier.py not yet run).
    """
    global _model_artifact, _feature_names

    if _model_artifact is None:
        if not os.path.isfile(MODEL_PATH):
            raise RuntimeError(
                f"model.pkl not found at: {MODEL_PATH}\n"
                "Run ml/train_classifier.py first to train and save the model."
            )
        _model_artifact = joblib.load(MODEL_PATH)

    if _feature_names is None:
        if not os.path.isfile(FEATURE_NAMES_PATH):
            raise RuntimeError(
                f"feature_names.json not found at: {FEATURE_NAMES_PATH}\n"
                "Run ml/train_classifier.py first."
            )
        with open(FEATURE_NAMES_PATH, "r", encoding="utf-8") as f:
            _feature_names = json.load(f)

    clf = _model_artifact["model"]
    encoder = _model_artifact["label_encoder"]
    return clf, encoder, _feature_names


# Feature Vector Builder

def _build_feature_vector(
    data: dict[str, Any],
    feature_names: list[str],
) -> np.ndarray:
    """
    Extracts the ordered feature vector from an aggregates dict or full
    score_repository() dictionary. Automatically handles nested complexity bands.
    """
    # Flatten aggregates and complexity bands if passed the full scored dict
    flat_data = dict(data)
    if "aggregates" in data and isinstance(data["aggregates"], dict):
        flat_data.update(data["aggregates"])

    # Resolve complexity band keys
    bands = data.get("complexity_bands") or data.get("bands") or {}
    if bands:
        flat_data.setdefault("pct_low_risk", bands.get("low", 1.0))
        flat_data.setdefault("pct_moderate_risk", bands.get("moderate", 0.0))
        flat_data.setdefault("pct_high_risk", bands.get("high", 0.0))
        flat_data.setdefault("pct_very_high_risk", bands.get("very_high", 0.0))

    vector = []
    missing = []
    for name in feature_names:
        val = flat_data.get(name)
        if val is None:
            missing.append(name)
            vector.append(0.0)
        else:
            vector.append(float(val))

    if missing:
        print(f"[ml_predictor] WARNING: Missing features defaulted to 0: {missing}")

    return np.array(vector).reshape(1, -1)


# Core Prediction Function

def predict(aggregates: dict[str, Any]) -> dict[str, Any]:
    
    clf, encoder, feature_names = _load_artifacts()

    # Build feature vector
    X = _build_feature_vector(aggregates, feature_names)

    # Predict class and probabilities
    class_idx = clf.predict(X)[0]
    probabilities = clf.predict_proba(X)[0]

    ml_label = encoder.inverse_transform([class_idx])[0]

    # Map probabilities to label names
    confidence = {
        str(label): round(float(prob), 4)
        for label, prob in zip(encoder.classes_, probabilities)
    }

    # Global feature importances (corpus-level, from trained forest)
    importances = clf.feature_importances_
    feature_contributions = {
        name: round(float(imp), 4)
        for name, imp in zip(feature_names, importances)
    }

    # Sort by importance descending (for Module 5 / dashboard)
    feature_contributions = dict(
        sorted(feature_contributions.items(), key=lambda x: x[1], reverse=True)
    )

    return {
        "ml_label": str(ml_label),
        "confidence": confidence,
        "feature_contributions": feature_contributions,
        "model_info": {
            "n_estimators": clf.n_estimators,
            "n_features": len(feature_names),
            "training_classes": list(encoder.classes_),
        },
    }


# Health Status Checker

def is_model_ready() -> bool:
    """Returns True if model.pkl and feature_names.json both exist."""
    return os.path.isfile(MODEL_PATH) and os.path.isfile(FEATURE_NAMES_PATH)



# CLI Test Runner

if __name__ == "__main__":
    import sys
    import json as _json

    try:
        from scoring import score_repository
    except ImportError:
        from backend.scoring import score_repository

    target = sys.argv[1] if len(sys.argv) > 1 else "../repositories/tqdm"
    print(f"Running ML prediction pipeline on: {target}...")

    # Extract + Score (Modules 2 & 3)
    scored = score_repository(target)

    # Predict (Module 4)
    prediction = predict(scored)

    rhi_label = scored["scores"]["label"]
    ml_label = prediction["ml_label"]
    agreement = "✅ AGREE" if rhi_label == ml_label else "⚠️  DIVERGE"

    print("\n--- ML PREDICTION RESULT ---")
    print(f"  RHI Rule-Based Label : {rhi_label}")
    print(f"  ML Predicted Label   : {ml_label}  {agreement}")

    print("\n  Confidence Scores:")
    for label, prob in sorted(prediction["confidence"].items(), key=lambda x: -x[1]):
        bar = "█" * int(prob * 30)
        print(f"    {label:<20} {prob:.4f}  {bar}")

    print("\n  Top 5 Feature Contributions:")
    for i, (feat, imp) in enumerate(prediction["feature_contributions"].items()):
        if i >= 5:
            break
        bar = "█" * int(imp * 50)
        print(f"    {feat:<30} {imp:.4f}  {bar}")