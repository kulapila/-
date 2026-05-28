"""Semantic clustering and taxonomy generation for paper cards."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import numpy as np
from openai import OpenAI
from sentence_transformers import SentenceTransformer

from .config import AppConfig
from .models import PaperCard, ClusterResult
from .utils import load_jsonl, get_logger

logger = get_logger(__name__)


def _parse_json_response(raw_text: str) -> dict:
    """Parse LLM JSON response, stripping code fences and repairing if needed."""
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:])
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            from json_repair import repair_json
            return json.loads(repair_json(text))
        except Exception:
            logger.warning(f"JSON repair failed, returning empty dict")
            return {}

CLUSTER_LABEL_PROMPT = """You are categorizing academic papers in the field of code generation.

Below are the titles and key ideas of a cluster of related papers.
Based on their content, assign a concise, descriptive category label for this cluster (3-7 words, e.g., "Code Completion with LLMs", "Program Repair and Debugging", "Benchmark and Evaluation").

Then, write a 2-3 sentence description of what unifies these papers.

Return ONLY a JSON object (no markdown, no code fences):
{"label": "...", "description": "..."}

Papers:
{paper_summaries}"""

TAXONOMY_PROMPT = """You are building a research taxonomy for the field of code generation.

Given the following cluster labels and descriptions, organize them into a hierarchical taxonomy tree (2-3 levels deep). Group related clusters under broader parent categories.

Clusters:
{cluster_descriptions}

Return ONLY a JSON object (no markdown, no code fences):
{{
  "taxonomy_markdown": "## Research Taxonomy\\n\\n- **Parent Category A**\\n  - Sub-category A1: description\\n  - Sub-category A2: description\\n- **Parent Category B**\\n  - ...",
  "rationale": "Brief rationale for the top-level split"
}}"""


def _paper_text(card: PaperCard) -> str:
    """Build embedding text from the most semantically rich fields."""
    parts = [card.title, card.problem, card.key_idea, card.method]
    return " ".join(p for p in parts if p and p != "Not specified in the abstract")


def _paper_summary(card: PaperCard) -> str:
    """Short summary for cluster labeling prompts."""
    return f"- Title: {card.title}\n  Key Idea: {card.key_idea}\n  Method: {card.method}"


class PaperClusterer:
    """Clusters papers via sentence-transformers + HDBSCAN, labels via DeepSeek."""

    def __init__(self, config: AppConfig) -> None:
        self.cfg = config.clustering
        api_cfg = config.api.deepseek
        self.llm = OpenAI(api_key=api_cfg.api_key, base_url=api_cfg.base_url, timeout=api_cfg.timeout)
        self.llm_model = api_cfg.model_cards
        self.data_dir = Path(config.pipeline.data_dir)
        self.embedding_model = None  # lazy load

    def fit(self, cards: list[PaperCard]) -> ClusterResult:
        """Full clustering pipeline: embed -> cluster -> label -> taxonomy."""
        if len(cards) < 3:
            logger.warning("Too few papers for clustering (need >= 3)")
            return ClusterResult(
                cluster_labels={},
                cluster_descriptions={},
                assignments={},
                taxonomy_markdown="",
                n_clusters=0,
                noise_papers=[c.arxiv_id for c in cards],
            )

        # Step 1: Generate embeddings
        embeddings = self._generate_embeddings(cards)

        # Step 2: Run HDBSCAN
        cluster_ids = self._cluster(embeddings)
        assignments = {card.arxiv_id: int(cluster_ids[i]) for i, card in enumerate(cards)}
        noise = [card.arxiv_id for card, cid in zip(cards, cluster_ids) if cid == -1]
        unique_clusters = sorted(set(int(c) for c in cluster_ids if c >= 0))
        n_clusters = len(unique_clusters)
        logger.info(f"Found {n_clusters} clusters, {len(noise)} noise papers")

        # Step 3: Label each cluster via DeepSeek
        cluster_labels, cluster_descriptions = self._label_clusters(cards, cluster_ids, unique_clusters)

        # Step 4: Build taxonomy
        taxonomy_md = self._build_taxonomy(cluster_descriptions)

        return ClusterResult(
            cluster_labels=cluster_labels,
            cluster_descriptions=cluster_descriptions,
            assignments=assignments,
            taxonomy_markdown=taxonomy_md,
            n_clusters=n_clusters,
            noise_papers=noise,
        )

    def _generate_embeddings(self, cards: list[PaperCard]) -> np.ndarray:
        """Generate embeddings via local sentence-transformers."""
        if self.embedding_model is None:
            logger.info(f"Loading embedding model: {self.cfg.embedding_model}")
            self.embedding_model = SentenceTransformer(self.cfg.embedding_model)

        texts = [_paper_text(card) for card in cards]
        embeddings = self.embedding_model.encode(texts, show_progress_bar=True)
        logger.info(f"Generated embeddings: shape={embeddings.shape}")
        return embeddings  # type: ignore

    def _cluster(self, embeddings: np.ndarray) -> np.ndarray:
        """Run HDBSCAN clustering. Returns cluster labels (-1 = noise)."""
        import hdbscan
        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=self.cfg.min_cluster_size,
            min_samples=self.cfg.min_samples,
            cluster_selection_epsilon=self.cfg.cluster_selection_epsilon,
            metric="euclidean",
        )
        labels = clusterer.fit_predict(embeddings)
        logger.info(
            f"HDBSCAN: {len(set(labels)) - (1 if -1 in labels else 0)} clusters, "
            f"{(labels == -1).sum()} noise points"
        )
        return labels

    def _label_clusters(
        self, cards: list[PaperCard], cluster_ids: np.ndarray, unique_clusters: list[int]
    ) -> tuple[dict[int, str], dict[int, str]]:
        """Label each cluster via DeepSeek API."""
        cluster_labels: dict[int, str] = {}
        cluster_descriptions: dict[int, str] = {}

        for cid in unique_clusters:
            cluster_cards = [cards[i] for i in range(len(cards)) if cluster_ids[i] == cid]
            summaries = "\n".join(_paper_summary(c) for c in cluster_cards[:10])  # cap at 10

            try:
                response = self.llm.chat.completions.create(
                    model=self.llm_model,
                    messages=[
                        {"role": "user", "content": CLUSTER_LABEL_PROMPT.replace("{paper_summaries}", summaries)},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.1,
                    max_tokens=512,
                )
                data = _parse_json_response(response.choices[0].message.content or "{}")
                cluster_labels[cid] = data.get("label", f"Cluster {cid}")
                cluster_descriptions[cid] = data.get("description", "")
                logger.info(f"Cluster {cid} labeled: {cluster_labels[cid]}")
            except Exception as e:
                logger.error(f"Failed to label cluster {cid}: {e}")
                cluster_labels[cid] = f"Cluster {cid}"
                cluster_descriptions[cid] = ""

        return cluster_labels, cluster_descriptions

    def _build_taxonomy(self, cluster_descriptions: dict[int, str]) -> str:
        """Build hierarchical taxonomy from cluster descriptions via DeepSeek."""
        if not cluster_descriptions:
            return ""

        descriptions_text = "\n".join(
            f"- Cluster {cid}: {desc}" for cid, desc in cluster_descriptions.items() if desc
        )
        if not descriptions_text.strip():
            return ""

        try:
            response = self.llm.chat.completions.create(
                model=self.llm_model,
                messages=[
                    {"role": "user", "content": TAXONOMY_PROMPT.replace("{cluster_descriptions}", descriptions_text)},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=2048,
            )
            data = _parse_json_response(response.choices[0].message.content or "{}")
            taxonomy = data.get("taxonomy_markdown", "")
            logger.info("Taxonomy generated successfully")
            return taxonomy
        except Exception as e:
            logger.error(f"Failed to build taxonomy: {e}")
            return ""

    def save_results(self, result: ClusterResult) -> None:
        """Save taxonomy to markdown file."""
        if result.taxonomy_markdown:
            path = self.data_dir / "taxonomy.md"
            path.write_text(result.taxonomy_markdown, encoding="utf-8")
            logger.info(f"Taxonomy saved to {path}")

        # Also save cluster assignments
        path = self.data_dir / "cluster_assignments.json"
        path.write_text(
            json.dumps({
                "assignments": result.assignments,
                "labels": {str(k): v for k, v in result.cluster_labels.items()},
                "descriptions": {str(k): v for k, v in result.cluster_descriptions.items()},
                "noise_papers": result.noise_papers,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def run_clustering(config: AppConfig) -> None:
    """CLI entry point."""
    data_dir = Path(config.pipeline.data_dir)
    cards_data = load_jsonl(str(data_dir / "paper_cards.jsonl"))
    if not cards_data:
        logger.error("No paper cards found. Run card generation first.")
        return
    cards = [PaperCard(**d) for d in cards_data]

    clusterer = PaperClusterer(config)
    result = clusterer.fit(cards)
    clusterer.save_results(result)

    logger.info(f"Clustering complete: {result.n_clusters} clusters, {len(result.noise_papers)} noise papers")
