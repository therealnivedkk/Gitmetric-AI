
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker

# Engine & Session Setup

DATABASE_URL = "sqlite:///./gitmetric.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


# User Table

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(120), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationship to analyses
    analyses = relationship(
        "AnalysisResult",
        back_populates="user",
        cascade="all, delete-orphan",
    )


# Analysis Table

class AnalysisResult(Base):
    __tablename__ = "analyses"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # Repository Identity
    repo_name = Column(String(100), nullable=False, index=True)
    repo_path = Column(String(255), nullable=True)

    # Core RHI Evaluation
    overall_rhi = Column(Float, nullable=False)
    rhi_label = Column(String(50), nullable=False)
    code_quality_score = Column(Float, nullable=False)
    maintainability_score = Column(Float, nullable=False)
    development_score = Column(Float, nullable=False)
    change_risk_score = Column(Float, nullable=False)

    # Key Aggregates
    total_loc = Column(Integer, default=0)
    file_count = Column(Integer, default=0)
    avg_cc = Column(Float, default=0.0)
    avg_mi = Column(Float, default=0.0)
    documentation_coverage = Column(Float, default=0.0)
    commit_count = Column(Integer, default=0)
    contributors = Column(Integer, default=0)
    total_churn = Column(Integer, default=0)

    # Full JSON payload for complete dashboard restore
    aggregates_json = Column(Text, nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    user = relationship("User", back_populates="analyses")
    prediction = relationship(
        "PredictionResult",
        back_populates="analysis",
        uselist=False,
        cascade="all, delete-orphan",
    )
    risk_analysis = relationship(
        "RiskAnalysisResult",
        back_populates="analysis",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def get_aggregates(self) -> dict[str, Any]:
        return json.loads(self.aggregates_json) if self.aggregates_json else {}


#  Prediction Result Table 

class PredictionResult(Base):
    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True, index=True)
    analysis_id = Column(
        Integer,
        ForeignKey("analyses.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    ml_label = Column(String(50), nullable=False)

    # Stored JSON strings for dictionary data
    confidence_json = Column(Text, nullable=False)
    feature_contributions_json = Column(Text, nullable=False)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationship back to analysis
    analysis = relationship("AnalysisResult", back_populates="prediction")

    def get_confidence(self) -> dict[str, float]:
        return json.loads(self.confidence_json) if self.confidence_json else {}

    def get_feature_contributions(self) -> dict[str, float]:
        return json.loads(self.feature_contributions_json) if self.feature_contributions_json else {}


#  Risk Analysis & Recommendations Table

class RiskAnalysisResult(Base):
    __tablename__ = "risk_analyses"

    id = Column(Integer, primary_key=True, index=True)
    analysis_id = Column(
        Integer,
        ForeignKey("analyses.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    # Issue Counts Summary (Critical, High, Warning)
    summary_json = Column(Text, nullable=False)

    # Granular components stored as JSON
    hotspots_json = Column(Text, nullable=False)
    issues_json = Column(Text, nullable=True)
    security_issues_json = Column(Text, nullable=True)
    recommendations_json = Column(Text, nullable=False)
    executive_summary = Column(Text, nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationship back to analysis
    analysis = relationship("AnalysisResult", back_populates="risk_analysis")

    def get_summary(self) -> dict[str, Any]:
        return json.loads(self.summary_json) if self.summary_json else {}

    def get_hotspots(self) -> list[dict[str, Any]]:
        return json.loads(self.hotspots_json) if self.hotspots_json else []

    def get_security_issues(self) -> list[dict[str, Any]]:
        return json.loads(self.security_issues_json) if self.security_issues_json else []

    def get_recommendations(self) -> list[dict[str, Any]]:
        return json.loads(self.recommendations_json) if self.recommendations_json else []


# Dependency for FastAPI

def get_db():
    """FastAPI dependency that provides a transactional database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables if they do not exist yet."""
    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    print("Initializing database tables...")
    init_db()
    print("Database tables initialized successfully in gitmetric.db!")