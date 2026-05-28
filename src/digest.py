"""Weekly survey digest generation via DeepSeek API."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd
from openai import OpenAI

from .config import AppConfig
from .models import PaperCard, PipelineState, WeekSummary
from .utils import load_json, load_jsonl, save_json, get_logger

logger = get_logger(__name__)

DIGEST_PROMPT = """You are a research survey writer specializing in code generation and LLMs for code.

Create a weekly survey digest (1-2 pages in markdown) covering the following sections.

## 2. Research Taxonomy
Here is the current research taxonomy:
{taxonomy}

## 3. Method Comparison Highlights
Key observations from the method comparison table:
{comparison_summary}

## 4. Trend Analysis
This week's paper statistics:
- Total papers analyzed: {total_papers}
- New papers this week: {n_new}
- Innovation type distribution: {innovation_dist}
- Category distribution: {category_dist}

Analyze whether the field is shifting toward particular approaches, new problem formulations, or deployment-focused research.

## 5. Research Gaps and Future Directions
Based on the collected papers, identify:
- Under-explored areas that show promise
- Missing evaluation dimensions
- Opportunities for novel contributions
- Risks or concerns (e.g., benchmark saturation, reproducibility)

RULES:
- Base analysis on the provided data. Do not invent trends.
- Provide specific paper citations (title, authors, year) when making claims.
- Keep to 1-2 pages (approximately 800-1200 words).
- Use academic tone.
- Output ONLY the markdown content, no preamble."""

TITLE_PROMPT = """Given the following summary of this week's code generation papers, generate a concise, informative title for the weekly digest.

Topics: {topics}

Return ONLY a JSON object:
{{"title": "Weekly Digest: ...", "highlights": ["bullet point 1", "bullet point 2", "bullet point 3"]}}"""


class DigestGenerator:
    """Generates weekly survey digest using DeepSeek."""

    def __init__(self, config: AppConfig) -> None:
        api_cfg = config.api.deepseek
        self.llm = OpenAI(
            api_key=api_cfg.api_key,
            base_url=api_cfg.base_url,
            timeout=api_cfg.timeout,
        )
        self.model = api_cfg.model_digest
        self.data_dir = Path(config.pipeline.data_dir)

    def generate(
        self,
        cards: list[PaperCard],
        taxonomy: str,
        comparison_df: pd.DataFrame,
        state: PipelineState | None = None,
    ) -> str:
        """Generate the weekly digest markdown."""
        now = dt.datetime.now()
        week_num = now.isocalendar().week
        year = now.year

        # Determine new papers
        new_cards = cards  # All cards for first run; incremental handles this later
        n_new = len(new_cards)

        # Innovation type distribution
        innov_dist = {}
        for c in cards:
            innov_dist[c.innovation_type] = innov_dist.get(c.innovation_type, 0) + 1

        # Category distribution
        cat_dist = {}
        for c in cards:
            cat = c.best_fit_category
            cat_dist[cat] = cat_dist.get(cat, 0) + 1

        # Comparison summary
        comparison_summary = self._summarize_comparison(comparison_df)

        # Generate title and highlights
        topics = ", ".join(list(cat_dist.keys())[:10])
        title_md = self._generate_title(topics)

        # Generate full digest
        digest_body = self._generate_body(
            taxonomy=taxonomy,
            comparison_summary=comparison_summary,
            total_papers=len(cards),
            n_new=n_new,
            innovation_dist=json.dumps(innov_dist, indent=2),
            category_dist=json.dumps(cat_dist, indent=2),
        )

        # Assemble final digest
        full_digest = f"{title_md}\n\n---\n\n**Week {week_num}, {year}**  |  Papers: {len(cards)} total ({n_new} new)\n\n{digest_body}"

        return full_digest

    def _generate_title(self, topics: str) -> str:
        """Generate a descriptive title for the digest."""
        try:
            response = self.llm.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": TITLE_PROMPT.replace("{topics}", topics)}],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=512,
            )
            data = json.loads(response.choices[0].message.content or "{}")
            title = data.get("title", "# Weekly Survey Digest: Code Generation Research")
            highlights = data.get("highlights", [])
            hl_text = "\n".join(f"- {h}" for h in highlights)
            return f"# {title}\n\n## Highlights\n{hl_text}"
        except Exception as e:
            logger.warning(f"Title generation failed: {e}")
            return "# Weekly Survey Digest: Code Generation Research"

    def _generate_body(self, **kwargs) -> str:
        """Generate the main digest body via DeepSeek."""
        try:
            prompt = DIGEST_PROMPT
            for key, val in kwargs.items():
                prompt = prompt.replace("{" + key + "}", str(val))
            response = self.llm.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=4096,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"Digest generation failed: {e}")
            return f"*Digest generation failed: {e}*"

    def _summarize_comparison(self, df: pd.DataFrame) -> str:
        """Create a compact text summary of the comparison table."""
        if df.empty:
            return "No comparison data available."
        lines = []
        lines.append(f"Methods analyzed: {len(df)}")
        if "complexity" in df.columns:
            comp = df["complexity"].value_counts().to_dict()
            lines.append(f"Complexity distribution: {comp}")
        if "data_driven" in df.columns:
            dd = df["data_driven"].value_counts().to_dict()
            lines.append(f"Data-driven vs Qualitative: {dd}")
        if "scenario" in df.columns:
            top_scenarios = df["scenario"].value_counts().head(5).to_dict()
            lines.append(f"Top evaluation scenarios: {top_scenarios}")
        return "\n".join(lines)

    def save(self, digest_md: str) -> str:
        """Save digest to data/weekly/ directory."""
        now = dt.datetime.now()
        week_num = now.isocalendar().week
        year = now.year
        weekly_dir = self.data_dir / "weekly"
        weekly_dir.mkdir(parents=True, exist_ok=True)
        filename = f"digest_{year}_W{week_num:02d}.md"
        path = weekly_dir / filename
        path.write_text(digest_md, encoding="utf-8")
        logger.info(f"Digest saved to {path}")
        return str(path)


def run_digest(config: AppConfig) -> None:
    """CLI entry point."""
    data_dir = Path(config.pipeline.data_dir)
    cards_data = load_jsonl(str(data_dir / "paper_cards.jsonl"))
    if not cards_data:
        logger.error("No paper cards found.")
        return
    cards = [PaperCard(**d) for d in cards_data]

    # Load taxonomy
    taxonomy_path = data_dir / "taxonomy.md"
    taxonomy = taxonomy_path.read_text(encoding="utf-8") if taxonomy_path.exists() else "Taxonomy not yet generated."

    # Load comparison
    comparison_path = data_dir / "comparison_table.csv"
    df = pd.read_csv(comparison_path) if comparison_path.exists() else pd.DataFrame()

    # Load state
    state_data = load_json(str(data_dir / "state.json"))
    state = PipelineState(**state_data) if state_data else None

    generator = DigestGenerator(config)
    digest_md = generator.generate(cards, taxonomy, df, state)
    generator.save(digest_md)
    logger.info("Weekly digest generated successfully.")
