"""Shared Pydantic data models for the survey pipeline."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---- ArXiv Paper ----

class ArxivPaper(BaseModel):
    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str
    published: str  # ISO 8601
    url: str
    primary_category: str
    categories: list[str]


# ---- Paper Card (structured analysis) ----

INNOVATION_TYPES = [
    "novel_architecture",
    "benchmark",
    "analysis",
    "application",
    "framework",
    "dataset",
]

CONFIDENCE_LEVELS = ["high", "medium", "low"]


class PaperCard(BaseModel):
    arxiv_id: str
    title: str
    problem: str
    key_idea: str
    method: str
    dataset_or_scenario: str
    metrics: str
    results_summary: str
    innovation_type: str
    limitations: str
    best_fit_category: str
    confidence_level: str

    @staticmethod
    def json_schema_for_prompt() -> dict:
        """Return the JSON schema to embed in the system prompt for DeepSeek."""
        return {
            "type": "object",
            "properties": {
                "arxiv_id": {"type": "string"},
                "title": {"type": "string"},
                "problem": {"type": "string", "description": "Research problem addressed (1-2 sentences)"},
                "key_idea": {"type": "string", "description": "Core novelty or key insight (1-2 sentences)"},
                "method": {"type": "string", "description": "Technical approach used (1-3 sentences)"},
                "dataset_or_scenario": {"type": "string", "description": "Datasets or evaluation scenarios"},
                "metrics": {"type": "string", "description": "Reported metrics (e.g. pass@k, BLEU, execution accuracy)"},
                "results_summary": {"type": "string", "description": "Key quantitative or qualitative results (1-2 sentences)"},
                "innovation_type": {
                    "type": "string",
                    "enum": INNOVATION_TYPES,
                },
                "limitations": {"type": "string", "description": "Acknowledged or inferred limitations (1-2 sentences)"},
                "best_fit_category": {"type": "string", "description": "Sub-area of code generation"},
                "confidence_level": {
                    "type": "string",
                    "enum": CONFIDENCE_LEVELS,
                    "description": "high=clearly covered, medium=partially inferred, low=significant guesswork",
                },
            },
            "required": [
                "arxiv_id", "title", "problem", "key_idea", "method",
                "dataset_or_scenario", "metrics", "results_summary",
                "innovation_type", "limitations", "best_fit_category", "confidence_level",
            ],
        }


# ---- Clustering ----

class ClusterResult(BaseModel):
    cluster_labels: dict[int, str]  # cluster_id -> human-readable label
    cluster_descriptions: dict[int, str]  # cluster_id -> 1-2 sentence description
    assignments: dict[str, int]  # arxiv_id -> cluster_id
    taxonomy_markdown: str
    n_clusters: int
    noise_papers: list[str]  # arxiv_ids not assigned to any cluster


# ---- Pipeline State ----

class WeekSummary(BaseModel):
    week_label: str
    new_papers: int
    key_themes: list[str]
    generated_at: str


class PipelineState(BaseModel):
    last_run: str = ""  # ISO 8601
    papers_processed: int = 0
    cards_generated: int = 0
    last_arxiv_published_date: Optional[str] = None
    week_num: int = 1
    year: int = 2026
    version: int = 0
    history: list[WeekSummary] = []


# ---- Misc ----

class FetchResult(BaseModel):
    papers: list[ArxivPaper]
    new_papers: list[ArxivPaper]
    total_fetched: int
    total_new: int
