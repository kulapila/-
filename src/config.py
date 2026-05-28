"""Configuration management — load YAML, resolve env vars, return typed config."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv


@dataclass
class DeepSeekConfig:
    api_key: str
    base_url: str = "https://api.deepseek.com"
    model_cards: str = "deepseek-chat"
    model_digest: str = "deepseek-chat"
    model_reasoner: str = "deepseek-reasoner"
    max_rpm: int = 60
    max_retries: int = 5
    initial_backoff: float = 1.0
    max_backoff: float = 60.0
    timeout: int = 120


@dataclass
class ArxivConfig:
    search_query: str
    max_results: int = 100
    date_range_years: int = 2
    sort_by: str = "submittedDate"
    sort_order: str = "descending"
    batch_size: int = 50


@dataclass
class ClusteringConfig:
    embedding_model: str = "all-MiniLM-L6-v2"
    algorithm: str = "hdbscan"
    min_cluster_size: int = 3
    min_samples: int = 1
    cluster_selection_epsilon: float = 0.15


@dataclass
class PipelineMeta:
    data_dir: str = "data"
    output_dir: str = "output"
    log_level: str = "INFO"
    log_file: str = "pipeline.log"
    concurrent_card_generation: int = 5


@dataclass
class ApiSection:
    deepseek: DeepSeekConfig


@dataclass
class AppConfig:
    api: ApiSection
    arxiv: ArxivConfig
    clustering: ClusteringConfig
    pipeline: PipelineMeta
    digest: dict = field(default_factory=dict)
    report: dict = field(default_factory=dict)


_ENV_VAR_RE = re.compile(r"\$\{(\w+)(?::-([^}]*))?\}")


def _resolve_env_vars(value):
    """Recursively replace ${VAR} and ${VAR:-default} patterns in strings."""
    if isinstance(value, str):
        def _replace(match):
            var_name = match.group(1)
            default = match.group(2)
            return os.environ.get(var_name, default if default is not None else match.group(0))
        return _ENV_VAR_RE.sub(_replace, value)
    if isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env_vars(item) for item in value]
    return value


def load_config(path: str = "config.yaml") -> AppConfig:
    """Load YAML configuration, resolve env vars, return typed AppConfig."""
    load_dotenv()

    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    raw = _resolve_env_vars(raw)

    api = ApiSection(
        deepseek=DeepSeekConfig(**raw["api"]["deepseek"]),
    )
    arxiv = ArxivConfig(**raw["arxiv"])
    clustering = ClusteringConfig(**raw["clustering"])
    pipeline = PipelineMeta(**raw["pipeline"])

    return AppConfig(
        api=api,
        arxiv=arxiv,
        clustering=clustering,
        pipeline=pipeline,
        digest=raw.get("digest", {}),
        report=raw.get("report", {}),
    )
