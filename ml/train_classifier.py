"""
train_classifier.py

Offline ML Training Pipeline for GitMetric AI — Module 7.

Trains a RandomForestClassifier on training_data.csv to predict
repository health labels: "Healthy", "Stable", or "Needs Attention".

Class Imbalance Handling:
    The 47-repository corpus has a severe class imbalance:
        Stable:          29 samples (majority)
        Needs Attention: 13 samples
        Healthy:          5 samples (minority)

    This is addressed via SMOTE (Synthetic Minority Over-sampling Technique),
    Chawla et al., 2002, "SMOTE: Synthetic Minority Over-sampling Technique,"
    Journal of Artificial Intelligence Research, 16, pp. 321-357.

    SMOTE generates synthetic minority-class examples by interpolating between
    existing real feature vectors in k-nearest-neighbor space. It is applied
    ONLY to the training split inside each cross-validation fold (to prevent
    data leakage). The training_data.csv remains 100% real observed repositories.

Output:
    ml/model.pkl          — serialized trained model (joblib format)
    ml/feature_names.json — ordered list of feature names used at train time

Run from GitMetricAI/ml/:
    python train_classifier.py

Or from root:
    backend\\venv\\Scripts\\python.exe ml\\train_classifier.py
"""

from __future__ import annotations

import json
import os
import sys

import joblib
import numpy as np
import pandas as pd
from imblearn.over_sampling import SMOTE
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.preprocessing import LabelEncoder

# ============================================================
# Configuration
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE_DIR, "training_data.csv")
MODEL_PATH = os.path.join(BASE_DIR, "model.pkl")
FEATURE_NAMES_PATH = os.path.join(BASE_DIR, "feature_names.json")

# Raw feature columns — excludes computed sub-scores and RHI to prevent
# data leakage (those are derived outputs, not raw inputs).
FEATURE_COLUMNS = [
    "avg_cc",
    "avg_mi",
    "avg_halstead_volume",
    "total_loc",
    "documentation_coverage",
    "pct_low_risk",
    "pct_moderate_risk",
    "pct_high_risk",
    "pct_very_high_risk",
    "commit_count",
    "commit_freq",
    "contributors",
    "total_churn",
    "churn_concentration",
    "branch_count",
    "merge_count",
]

TARGET_COLUMN = "label"
LABEL_ORDER = ["Healthy", "Stable", "Needs Attention"]

RANDOM_STATE = 42
N_ESTIMATORS = 200
CV_FOLDS = 5


# ============================================================
# Helpers
# ============================================================

def load_data(csv_path: str) -> tuple[pd.DataFrame, pd.Series]:
    """Load and validate training data from CSV."""
    if not os.path.isfile(csv_path):
        sys.exit(f"ERROR: Training CSV not found at: {csv_path}")

    df = pd.read_csv(csv_path)

    missing = [c for c in FEATURE_COLUMNS + [TARGET_COLUMN] if c not in df.columns]
    if missing:
        sys.exit(f"ERROR: Missing columns in CSV: {missing}")

    X = df[FEATURE_COLUMNS].copy()
    y = df[TARGET_COLUMN].copy()

    if X.isnull().any().any():
        print("WARNING: NaN values found — filling with column median.")
        X = X.fillna(X.median())

    return X, y


def describe_class_balance(y: pd.Series, stage: str) -> None:
    """Print class distribution at a given pipeline stage."""
    counts = y.value_counts().to_dict()
    total = len(y)
    print(f"\n  Class distribution ({stage}):")
    for label in LABEL_ORDER:
        n = counts.get(label, 0)
        bar = "█" * int((n / total) * 30)
        print(f"    {label:<20} {n:>3}  {bar}")


def smote_augment(
    X_train: np.ndarray,
    y_train: np.ndarray,
    encoder: LabelEncoder,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Apply SMOTE to training data.

    k_neighbors is set to min(n_minority_samples - 1, 5) to handle
    the case where minority class has very few examples (Healthy: 5 real samples).

    Reference:
        Chawla, N.V., Bowyer, K.W., Hall, L.O., Kegelmeyer, W.P. (2002).
        SMOTE: Synthetic Minority Over-sampling Technique.
        Journal of Artificial Intelligence Research, 16, 321-357.
    """
    unique, counts = np.unique(y_train, return_counts=True)
    min_count = counts.min()
    k_neighbors = min(min_count - 1, 5)

    if k_neighbors < 1:
        print("    [SMOTE] Too few minority samples to oversample — skipping.")
        return X_train, y_train

    smote = SMOTE(
        random_state=RANDOM_STATE,
        k_neighbors=k_neighbors,
    )
    X_resampled, y_resampled = smote.fit_resample(X_train, y_train)

    y_labels = encoder.inverse_transform(y_resampled)
    resampled_counts = dict(zip(*np.unique(y_labels, return_counts=True)))
    print(f"    [SMOTE] After oversampling: {resampled_counts}")

    return X_resampled, y_resampled


# ============================================================
# Cross-Validation with Per-Fold SMOTE
# ============================================================

def cross_validate_with_smote(
    X: np.ndarray,
    y: np.ndarray,
    encoder: LabelEncoder,
) -> list[float]:
    """
    Stratified K-Fold cross-validation where SMOTE is applied
    inside each training fold only — preventing synthetic samples
    from leaking into validation sets.
    """
    skf = StratifiedKFold(n_splits=CV_FOLDS, shuffle=True, random_state=RANDOM_STATE)
    clf = RandomForestClassifier(
        n_estimators=N_ESTIMATORS,
        random_state=RANDOM_STATE,
        class_weight="balanced",  # Secondary guard alongside SMOTE
    )

    fold_scores: list[float] = []
    print(f"\n  Running {CV_FOLDS}-Fold Stratified Cross-Validation with per-fold SMOTE...")

    for fold_idx, (train_idx, val_idx) in enumerate(skf.split(X, y), start=1):
        X_train_fold, X_val_fold = X[train_idx], X[val_idx]
        y_train_fold, y_val_fold = y[train_idx], y[val_idx]

        print(f"\n  Fold {fold_idx}/{CV_FOLDS}:")
        X_train_smote, y_train_smote = smote_augment(X_train_fold, y_train_fold, encoder)

        clf.fit(X_train_smote, y_train_smote)
        fold_acc = clf.score(X_val_fold, y_val_fold)
        fold_scores.append(fold_acc)
        print(f"    Validation accuracy: {fold_acc:.4f}")

    return fold_scores


# ============================================================
# Final Training on Full Dataset
# ============================================================

def train_final_model(
    X: np.ndarray,
    y: np.ndarray,
    encoder: LabelEncoder,
) -> RandomForestClassifier:
    """
    Train the final model on the full dataset with SMOTE applied.
    This is the model saved to model.pkl for production inference.
    """
    print("\n  Training final model on full dataset with SMOTE...")
    X_resampled, y_resampled = smote_augment(X, y, encoder)

    clf = RandomForestClassifier(
        n_estimators=N_ESTIMATORS,
        random_state=RANDOM_STATE,
        class_weight="balanced",
    )
    clf.fit(X_resampled, y_resampled)

    # Full-dataset classification report (training performance, not held-out)
    y_pred = clf.predict(X)
    print("\n  In-sample Classification Report (training data — not held-out):")
    y_labels = encoder.inverse_transform(y)
    y_pred_labels = encoder.inverse_transform(y_pred)
    print(classification_report(y_labels, y_pred_labels, target_names=LABEL_ORDER))

    return clf


# ============================================================
# Feature Importance Report
# ============================================================

def print_feature_importances(
    clf: RandomForestClassifier,
    feature_names: list[str],
) -> None:
    """Print corpus-level feature importances ranked by contribution."""
    importances = clf.feature_importances_
    ranked = sorted(
        zip(feature_names, importances),
        key=lambda x: x[1],
        reverse=True,
    )

    print("\n  Feature Importances (corpus-level, from trained RandomForest):")
    print(f"  {'Feature':<30} {'Importance':>10}  {'Bar'}")
    print("  " + "-" * 60)
    for name, imp in ranked:
        bar = "█" * int(imp * 50)
        print(f"  {name:<30} {imp:>10.4f}  {bar}")


# ============================================================
# Save Artifacts
# ============================================================

def save_artifacts(
    clf: RandomForestClassifier,
    encoder: LabelEncoder,
    feature_names: list[str],
) -> None:
    """Save model.pkl and feature_names.json to ml/ directory."""
    artifact = {
        "model": clf,
        "label_encoder": encoder,
    }
    joblib.dump(artifact, MODEL_PATH)
    print(f"\n  Model saved to: {MODEL_PATH}")

    with open(FEATURE_NAMES_PATH, "w", encoding="utf-8") as f:
        json.dump(feature_names, f, indent=2)
    print(f"  Feature names saved to: {FEATURE_NAMES_PATH}")


# ============================================================
# Main
# ============================================================

def main() -> None:
    print("=" * 60)
    print("  GitMetric AI — ML Training Pipeline")
    print("  SMOTE (Chawla et al., 2002) for class balance")
    print("=" * 60)

    # 1. Load data
    print(f"\n[1/5] Loading training data from: {CSV_PATH}")
    X_df, y_series = load_data(CSV_PATH)
    print(f"  Loaded {len(X_df)} repositories, {len(FEATURE_COLUMNS)} features.")
    describe_class_balance(y_series, "raw dataset")

    # 2. Encode labels
    print("\n[2/5] Encoding class labels...")
    encoder = LabelEncoder()
    encoder.fit(LABEL_ORDER)
    y_encoded = encoder.transform(y_series)
    print(f"  Label mapping: { {k: int(v) for k, v in zip(encoder.classes_, encoder.transform(encoder.classes_))} }")

    X = X_df.values

    # 3. Cross-validation with per-fold SMOTE
    print("\n[3/5] Cross-Validation with per-fold SMOTE...")
    fold_scores = cross_validate_with_smote(X, y_encoded, encoder)

    print(f"\n  Cross-Validation Results ({CV_FOLDS} folds):")
    print(f"    Fold Accuracies: {[round(s, 4) for s in fold_scores]}")
    print(f"    Mean Accuracy:   {np.mean(fold_scores):.4f}")
    print(f"    Std Deviation:   {np.std(fold_scores):.4f}")

    # 4. Final model on full dataset
    print("\n[4/5] Training final model on full dataset...")
    final_clf = train_final_model(X, y_encoded, encoder)
    print_feature_importances(final_clf, FEATURE_COLUMNS)

    # 5. Save artifacts
    print("\n[5/5] Saving model artifacts...")
    save_artifacts(final_clf, encoder, FEATURE_COLUMNS)

    print("\n" + "=" * 60)
    print("  Training complete. model.pkl is ready for inference.")
    print("=" * 60)


if __name__ == "__main__":
    main()