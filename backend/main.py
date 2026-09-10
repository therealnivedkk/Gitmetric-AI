
from __future__ import annotations

import json
import os
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import get_current_user, router as auth_router
from database import (
    AnalysisResult,
    Base,
    PredictionResult,
    RiskAnalysisResult,
    User,
    engine,
    get_db,
    init_db,
)
from extractors import analyze_repository
from issues import detect_issues
from ml_predictor import is_model_ready, predict
from recommendations import generate_recommendations
from scoring import calculate_rhi

# ============================================================
# FastAPI App Setup & CORS
# ============================================================

app = FastAPI(
    title="GitMetric AI API",
    description="Automated Repository Health & Risk Assessment Platform",
    version="1.0.0",
)

# Enable CORS for Vite React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auto-initialize database tables on startup
init_db()

# Mount authentication routes (/auth/register, /auth/login, /auth/me)
app.include_router(auth_router)


# ============================================================
# Request / Response Schemas

class AnalyzeRequest(BaseModel):
    repo_path: str


# Health Check & Root

@app.get("/")
def root():
    return {
        "status": "online",
        "app": "GitMetric AI Backend",
        "model_ready": is_model_ready(),
    }


# 1. Main Pipeline: Analyze Repository

@app.post("/api/analyze")
def analyze_repo_endpoint(
    req: AnalyzeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Executes the full end-to-end analysis workflow:
      1. Repository Mining (extractors.py)
      2. Feature Engineering & RHI Scoring (scoring.py)
      3. ML Classification & Feature Importance (ml_predictor.py)
      4. Risk & Hotspot Detection (issues.py)
      5. Actionable Recommendations (recommendations.py)
      6. Persists Analysis, Prediction, and Risks in SQLite DB
    """
    repo_path = os.path.abspath(req.repo_path)
    if not os.path.isdir(repo_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository path not found: {req.repo_path}",
        )

    # 1. Repository Analysis Module
    try:
        extracted = analyze_repository(repo_path)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Repository analysis failed: {str(exc)}",
        )

    # 2. Feature Engineering & RHI Module
    score_data = calculate_rhi(extracted)

    # Combine scored object
    scored_payload = {
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
    }

    # 3. ML Health Prediction Module
    try:
        ml_result = predict(scored_payload)
    except Exception as exc:
        ml_result = {
            "ml_label": score_data["label"],
            "confidence": {score_data["label"]: 1.0},
            "feature_contributions": {},
            "error": str(exc),
        }

    # 4. Risk Analysis & Explainability Module
    issues_data = detect_issues(extracted, repo_path)

    # Attach ML feature contributions to explainability payload
    issues_data["ml_feature_contributions"] = ml_result.get("feature_contributions", {})

    # 5. Recommendation & Reports Module
    recommendations_data = generate_recommendations(
        scored_payload["scores"],
        scored_payload["aggregates"],
        issues_data,
    )

    # 6. Database Storage (Persist User Data, Analysis Data, Prediction Results)
    analysis_record = AnalysisResult(
        user_id=current_user.id,
        repo_name=extracted["repo_name"],
        repo_path=repo_path,
        overall_rhi=score_data["overall_rhi"],
        rhi_label=score_data["label"],
        code_quality_score=score_data["code_quality_score"],
        maintainability_score=score_data["maintainability_score"],
        development_score=score_data["development_score"],
        change_risk_score=score_data["change_risk_score"],
        total_loc=extracted["total_loc"],
        file_count=len(extracted["files"]),
        avg_cc=extracted["avg_cc"],
        avg_mi=extracted["avg_mi"],
        documentation_coverage=extracted["documentation_coverage"],
        commit_count=extracted["commit_count"],
        contributors=extracted["contributors"],
        total_churn=extracted["total_churn"],
        aggregates_json=json.dumps(scored_payload["aggregates"]),
    )
    db.add(analysis_record)
    db.flush()  # Populates analysis_record.id

    # Store Prediction Result
    pred_record = PredictionResult(
        analysis_id=analysis_record.id,
        ml_label=ml_result["ml_label"],
        confidence_json=json.dumps(ml_result["confidence"]),
        feature_contributions_json=json.dumps(ml_result.get("feature_contributions", {})),
    )
    db.add(pred_record)

    # Store Risk Analysis & Recommendations
    risk_record = RiskAnalysisResult(
        analysis_id=analysis_record.id,
        summary_json=json.dumps(issues_data["summary"]),
        hotspots_json=json.dumps(issues_data["hotspots"]),
        issues_json=json.dumps(issues_data.get("complexity_issues", [])[:20]),
        recommendations_json=json.dumps(recommendations_data["recommendations"]),
        executive_summary=recommendations_data["executive_summary"],
    )
    db.add(risk_record)
    db.commit()
    db.refresh(analysis_record)

    # 7. Return complete unified payload for dashboard
    return {
        "analysis_id": analysis_record.id,
        "repo_name": extracted["repo_name"],
        "repo_path": repo_path,
        "scores": scored_payload["scores"],
        "complexity_bands": scored_payload["complexity_bands"],
        "aggregates": scored_payload["aggregates"],
        "ml_prediction": ml_result,
        "issues": {
            "summary": issues_data["summary"],
            "hotspots": issues_data["hotspots"],
            "security_issues": issues_data["security_issues"],
            "top_undocumented": issues_data.get("top_undocumented", []),
            "total_undocumented_count": issues_data.get("total_undocumented_count", 0),
        },
        "recommendations": recommendations_data,
        "created_at": analysis_record.created_at.isoformat(),
    }


# 2. Historical Analyses List

@app.get("/api/analyses")
def list_analyses(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Returns a summary list of all past analyses performed by this user."""
    records = (
        db.query(AnalysisResult)
        .filter(AnalysisResult.user_id == current_user.id)
        .order_by(AnalysisResult.created_at.desc())
        .all()
    )

    history = []
    for r in records:
        pred_label = r.prediction.ml_label if r.prediction else r.rhi_label
        history.append({
            "id": r.id,
            "repo_name": r.repo_name,
            "overall_rhi": r.overall_rhi,
            "rhi_label": r.rhi_label,
            "ml_label": pred_label,
            "total_loc": r.total_loc,
            "file_count": r.file_count,
            "created_at": r.created_at.isoformat(),
        })

    return history


# 3. Retrieve Single Past Analysis

@app.get("/api/analyses/{analysis_id}")
def get_analysis_by_id(
    analysis_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve full saved report for a previous analysis."""
    record = (
        db.query(AnalysisResult)
        .filter(
            AnalysisResult.id == analysis_id,
            AnalysisResult.user_id == current_user.id,
        )
        .first()
    )

    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis not found",
        )

    pred = record.prediction
    risk = record.risk_analysis

    return {
        "analysis_id": record.id,
        "repo_name": record.repo_name,
        "repo_path": record.repo_path,
        "scores": {
            "overall_rhi": record.overall_rhi,
            "label": record.rhi_label,
            "code_quality_score": record.code_quality_score,
            "maintainability_score": record.maintainability_score,
            "development_score": record.development_score,
            "change_risk_score": record.change_risk_score,
        },
        "aggregates": record.get_aggregates(),
        "ml_prediction": {
            "ml_label": pred.ml_label if pred else record.rhi_label,
            "confidence": pred.get_confidence() if pred else {},
            "feature_contributions": pred.get_feature_contributions() if pred else {},
        },
        "issues": {
            "summary": risk.get_summary() if risk else {},
            "hotspots": risk.get_hotspots() if risk else [],
        },
        "recommendations": {
            "executive_summary": risk.executive_summary if risk else "",
            "recommendations": risk.get_recommendations() if risk else [],
        },
        "created_at": record.created_at.isoformat(),
    }


# 4. Global Explainability Endpoint

@app.get("/api/model/explainability")
def get_global_explainability():
    """Returns the corpus-level feature importances from model.pkl."""
    if not is_model_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ML Model not trained yet. Run ml/train_classifier.py first.",
        )

    # Use a dummy prediction vector to fetch the cached feature importances
    result = predict({})
    return {
        "feature_importances": result["feature_contributions"],
        "model_info": result["model_info"],
    }