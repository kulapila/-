"""Method comparison table generation from paper cards."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from openai import OpenAI

from .config import AppConfig
from .models import PaperCard
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

COMPARISON_PROMPT = """You are comparing methods from multiple academic papers on code generation.

Given the following paper cards, produce comparison rows for each paper.

For each paper, extract:
- method_name: short name of the technical approach (5-15 words)
- complexity: "Low" | "Medium" | "High" (based on architectural description)
- scenario: evaluation settings used (e.g., HumanEval, MBPP, real-world projects)
- pros: 1-2 key advantages
- cons: 1-2 key disadvantages or limitations
- data_driven: "Yes" if the conclusions are supported by quantitative data, otherwise "Qualitative"

Return ONLY a JSON object (no markdown, no code fences):
{
  "rows": [
    {
      "arxiv_id": "...",
      "method_name": "...",
      "complexity": "Low|Medium|High",
      "scenario": "...",
      "pros": "...",
      "cons": "...",
      "data_driven": "Yes|Qualitative"
    },
    ...
  ]
}

Paper Cards:
{cards_text}"""


class ComparisonBuilder:
    """Builds method comparison table from paper cards via DeepSeek."""

    def __init__(self, config: AppConfig) -> None:
        api_cfg = config.api.deepseek
        self.llm = OpenAI(
            api_key=api_cfg.api_key,
            base_url=api_cfg.base_url,
            timeout=api_cfg.timeout,
        )
        self.model = api_cfg.model_digest
        self.data_dir = Path(config.pipeline.data_dir)

    def build(self, cards: list[PaperCard]) -> pd.DataFrame:
        """Build comparison table from all cards, batching for context limits."""
        all_rows: list[dict] = []
        batch_size = 15  # Keep batches small enough for context window

        for i in range(0, len(cards), batch_size):
            batch = cards[i : i + batch_size]
            logger.info(f"Building comparison: batch {i // batch_size + 1}, size={len(batch)}")
            rows = self._build_rows_for_batch(batch)
            all_rows.extend(rows)

        df = pd.DataFrame(all_rows)
        if df.empty:
            logger.warning("Comparison table is empty — all batches failed")
            return df
        # Add paper title for readability
        title_map = {c.arxiv_id: c.title for c in cards}
        df["title"] = df["arxiv_id"].map(title_map)
        # Reorder columns
        cols = ["arxiv_id", "title", "method_name", "complexity", "scenario", "pros", "cons", "data_driven"]
        df = df[[c for c in cols if c in df.columns]]
        logger.info(f"Comparison table built: {len(df)} rows")
        return df

    def _build_rows_for_batch(self, batch: list[PaperCard]) -> list[dict]:
        """Call DeepSeek to extract comparison rows for a batch."""
        cards_text = "\n\n".join(self._format_card(c) for c in batch)

        try:
            response = self.llm.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", "content": COMPARISON_PROMPT.replace("{cards_text}", cards_text)},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=4096,
            )
            data = _parse_json_response(response.choices[0].message.content or "{}")
            return data.get("rows", [])
        except Exception as e:
            logger.error(f"Comparison batch failed: {e}")
            return []

    @staticmethod
    def _format_card(card: PaperCard) -> str:
        return (
            f"arxiv_id: {card.arxiv_id}\n"
            f"Title: {card.title}\n"
            f"Method: {card.method}\n"
            f"Dataset/Scenario: {card.dataset_or_scenario}\n"
            f"Metrics: {card.metrics}\n"
            f"Results: {card.results_summary}\n"
            f"Limitations: {card.limitations}\n"
            f"Innovation Type: {card.innovation_type}"
        )

    def save(self, df: pd.DataFrame) -> str:
        """Save comparison table as CSV and markdown."""
        csv_path = self.data_dir / "comparison_table.csv"
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")

        md_path = self.data_dir / "comparison_table.md"
        if df.empty:
            md_path.write_text("*Comparison table is empty.*", encoding="utf-8")
        else:
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(df.to_markdown(index=False))
        logger.info(f"Comparison table saved to {csv_path}")
        return str(csv_path)


def run_comparison(config: AppConfig) -> None:
    """CLI entry point."""
    data_dir = Path(config.pipeline.data_dir)
    cards_data = load_jsonl(str(data_dir / "paper_cards.jsonl"))
    if not cards_data:
        logger.error("No paper cards found. Run card generation first.")
        return
    cards = [PaperCard(**d) for d in cards_data]

    builder = ComparisonBuilder(config)
    df = builder.build(cards)
    builder.save(df)
