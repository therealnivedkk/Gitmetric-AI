
from __future__ import annotations

import csv
import json
import os
import sys
from typing import Any

# Import extractors with path-agnostic fallback
try:
    from extractors import analyze_repository
except ImportError:
    from backend.extractors import analyze_repository


# ============================================================
# Thresholds
# ============================================================
HEALTHY_THRESHOLD = 73.0
STABLE_THRESHOLD = 63.0


# ============================================================
# Corpus Reference Distribution Loader
# ============================================================
def _find_training_csv() -> str | None:
    """Locate training_data.csv relative to this file."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(base_dir, "..", "ml", "training_data.csv"),
        os.path.join(base_dir, "ml", "training_data.csv"),
        os.path.join(base_dir, "training_data.csv"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return os.path.abspath(path)
    return None


def load_corpus_reference_values() -> dict[str, list[float]]:
    """
    Load reference distribution vectors from training_data.csv for
    percentile ranking. Falls back to baseline defaults if file is missing.
    """
    csv_path = _find_training_csv()
    references: dict[str, list[float]] = {
        "commit_freq": [],
        "contributors": [],
        "merge_count": [],
        "branch_count": [],
        "total_churn": [],
        "churn_concentration": [],
    }

    if csv_path and os.path.isfile(csv_path):
        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    for key in references:
                        if key in row and row[key] != "":
                            try:
                                references[key].append(float(row[key]))
                            except ValueError:
                                pass
            if references["commit_freq"]:
                return references
        except Exception:
            pass

    # Fallback corpus baseline defaults (from 48-repo training dataset)
    return {
        "commit_freq": [0.5, 1.2, 2.4, 3.8, 5.5, 8.0, 12.0, 20.0],
        "contributors": [1, 3, 10, 25, 50, 100, 250, 500],
        "merge_count": [0, 5, 20, 50, 150, 300, 700, 1200],
        "branch_count": [1, 2, 4, 8, 15, 25, 50],
        "total_churn": [1000, 5000, 15000, 35000, 75000, 150000, 300000],
        "churn_concentration": [0.10, 0.20, 0.35, 0.50, 0.65, 0.80, 0.95],
    }


CORPUS_REFERENCES = load_corpus_reference_values()


# ============================================================
# Scoring Core Functions
# ============================================================

def classify_complexity_bands(complexities: list[float]) -> dict[str, float]:
    """
    Classify functions into McCabe's published risk categories:
        1-10   Low risk
        11-20  Moderate risk
        21-50  High risk
        50+    Very high risk
    """
    if not complexities:
        return {"low": 1.0, "moderate": 0.0, "high": 0.0, "very_high": 0.0}

    total = len(complexities)
    low = sum(1 for c in complexities if c <= 10)
    moderate = sum(1 for c in complexities if 10 < c <= 20)
    high = sum(1 for c in complexities if 20 < c <= 50)
    very_high = sum(1 for c in complexities if c > 50)

    return {
        "low": low / total,
        "moderate": moderate / total,
        "high": high / total,
        "very_high": very_high / total,
    }


def code_quality_from_bands(band_proportions: dict[str, float]) -> float:
    """
    Severity-weighted penalty score using McCabe's (1976) complexity risk bands.
    Weights: 100 for moderate, 300 for high, 600 for very high.
    """
    penalty = (
        band_proportions.get("moderate", 0.0) * 100
        + band_proportions.get("high", 0.0) * 300
        + band_proportions.get("very_high", 0.0) * 600
    )
    return max(0.0, 100.0 - min(100.0, penalty))


def percentile_rank(value: float, reference_values: list[float]) -> float:
    """Calculate percentile rank of a value against reference values (0 to 100)."""
    if not reference_values:
        return 50.0
    count = sum(v <= value for v in reference_values)
    return (count / len(reference_values)) * 100.0


def calculate_rhi(
    extracted_data: dict[str, Any],
    references: dict[str, list[float]] | None = None,
) -> dict[str, Any]:
    """
    Takes the output dictionary of extractors.analyze_repository() and computes
    sub-scores, overall RHI, and health label.
    """
    refs = references or CORPUS_REFERENCES

    # 1. Code Quality Score
    if "pct_low_risk" in extracted_data:
        bands = {
            "low": extracted_data["pct_low_risk"],
            "moderate": extracted_data["pct_moderate_risk"],
            "high": extracted_data["pct_high_risk"],
            "very_high": extracted_data["pct_very_high_risk"],
        }
    else:
        # Extract from file-level function details
        files = extracted_data.get("files", [])
        all_complexities = [
            fn["complexity"]
            for f in files
            for fn in f.get("functions", [])
            if "complexity" in fn
        ]
        bands = classify_complexity_bands(all_complexities)

    code_quality_score = round(code_quality_from_bands(bands), 2)

    # 2. Maintainability Score (avg MI capped 0 to 100)
    avg_mi = extracted_data.get("avg_mi", 0.0)
    maintainability_score = round(max(0.0, min(100.0, float(avg_mi))), 2)

    # 3. Development Activity Score
    commit_freq = float(extracted_data.get("commit_freq", 0.0))
    contributors = float(extracted_data.get("contributors", 0))
    merge_count = float(extracted_data.get("merge_count", 0))
    branch_count = float(extracted_data.get("branch_count", 0))

    commit_p = percentile_rank(commit_freq, refs["commit_freq"])
    contributor_p = percentile_rank(contributors, refs["contributors"])
    merge_p = percentile_rank(merge_count, refs["merge_count"])
    branch_p = percentile_rank(branch_count, refs["branch_count"])

    development_score = round(
        (commit_p + contributor_p + merge_p + branch_p) / 4.0, 2
    )

    # 4. Change Risk Score
    total_churn = float(extracted_data.get("total_churn", 0))
    churn_conc = float(extracted_data.get("churn_concentration", 0.0))

    churn_p = percentile_rank(total_churn, refs["total_churn"])
    conc_p = percentile_rank(churn_conc, refs["churn_concentration"])

    # Higher churn/concentration = higher change risk -> lower score
    change_risk_score = round(100.0 - ((churn_p + conc_p) / 2.0), 2)

    # 5. Overall RHI
    overall_rhi = round(
        (
            code_quality_score
            + maintainability_score
            + development_score
            + change_risk_score
        )
        / 4.0,
        2,
    )

    # 6. Health Label
    if overall_rhi >= HEALTHY_THRESHOLD:
        label = "Healthy"
    elif overall_rhi >= STABLE_THRESHOLD:
        label = "Stable"
    else:
        label = "Needs Attention"

    return {
        "code_quality_score": code_quality_score,
        "maintainability_score": maintainability_score,
        "development_score": development_score,
        "change_risk_score": change_risk_score,
        "overall_rhi": overall_rhi,
        "label": label,
        "bands": {k: round(v, 4) for k, v in bands.items()},
        "sub_percentiles": {
            "commit_freq_percentile": round(commit_p, 2),
            "contributor_percentile": round(contributor_p, 2),
            "merge_percentile": round(merge_p, 2),
            "branch_percentile": round(branch_p, 2),
            "churn_percentile": round(churn_p, 2),
            "concentration_percentile": round(conc_p, 2),
        },
    }


# ============================================================
# End-to-End Connector (Extract -> Score)
# ============================================================

def score_repository(repo_path: str) -> dict[str, Any]:
    """
    Connects extractors.py and scoring.py end-to-end:
      1. Calls analyze_repository(repo_path)
      2. Computes the 4 RHI sub-scores, overall score, and health label
      3. Returns the full combined analysis result
    """
    extracted = analyze_repository(repo_path)
    score_data = calculate_rhi(extracted)

    return {
        "repo_name": extracted["repo_name"],
        "repo_path": extracted["repo_path"],
        "scores": {
            "overall_rhi": score_data["overall_rhi"],
            "label": score_data["label"],
            "code_quality_score": score_data["code_quality_score"],
            "maintainability_score": score_data["maintainability_score"],
            "development_score": score_data["development_score"],
            "change_risk_score": score_data["change_risk_score"],
        },
        "complexity_bands": score_data["bands"],
        "aggregates": {
            "total_loc": extracted["total_loc"],
            "file_count": len(extracted["files"]),
            "avg_cc": round(extracted["avg_cc"], 3),
            "avg_mi": round(extracted["avg_mi"], 3),
            "avg_halstead_volume": round(extracted["avg_halstead_volume"], 3),
            "documentation_coverage": round(extracted["documentation_coverage"], 2),
            "commit_count": extracted["commit_count"],
            "commit_freq": round(extracted["commit_freq"], 3),
            "contributors": extracted["contributors"],
            "total_churn": extracted["total_churn"],
            "churn_concentration": round(extracted["churn_concentration"], 4),
            "branch_count": extracted["branch_count"],
            "merge_count": extracted["merge_count"],
        },
        "percentiles": score_data["sub_percentiles"],
        "files": extracted["files"],  # Retained for Module 5 (Issue Detection)
    }


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "repositories/InquirerPy"
    print(f"Analyzing and scoring repository: {target}...")
    
    result = score_repository(target)
    
    # Print clean summary without drowning terminal in the per-file array
    summary = {k: v for k, v in result.items() if k != "files"}
    summary["file_count"] = len(result["files"])
    
    print("\n--- FINAL RHI EVALUATION RESULT ---")
    print(json.dumps(summary, indent=2))