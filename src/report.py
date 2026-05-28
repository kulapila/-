"""Final survey report integration from accumulated weekly digests."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from openai import OpenAI

from .config import AppConfig
from .models import PaperCard, ArxivPaper
from .utils import load_jsonl, load_json, get_logger

logger = get_logger(__name__)

REPORT_PROMPT = """You are writing a final survey report on code generation research. Integrate the provided materials into a coherent 6-10 page report.

## Materials

### Research Taxonomy
{taxonomy}

### Method Comparison Summary
{comparison_summary}

### Weekly Digests (accumulated)
{digests_combined}

### Paper Statistics
- Total papers surveyed: {total_papers}
- Categories covered: {categories}
- Time span: {time_span}

## Report Structure
1. **Abstract** (150 words) — Scope, key findings, and main conclusions.
2. **Introduction** — Background on code generation research, survey scope, and methodology.
3. **Research Taxonomy** — Hierarchical overview of sub-areas with representative papers.
4. **Method Landscape** — Comparative analysis of technical approaches, organized by category.
5. **Key Findings and Trends** — Synthesized insights across the entire survey period.
6. **Research Gaps and Future Directions** — Actionable opportunities for future work (must include original analysis).
7. **Most Influential Papers** — Shortlist of 5-10 papers with brief rationale for each.
8. **Conclusion** — Summary and outlook.

## Rules
- Write a smooth narrative flow, NOT a concatenation of digests.
- Remove redundant content that appeared across multiple weeks.
- Use specific paper citations (Author et al., Year) when making claims.
- Academic tone, rigorous but readable.
- Target length: 6-10 pages (approximately 3000-5000 words).
- Output ONLY the final markdown report, no preamble."""


class ReportBuilder:
    """Integrates accumulated materials into a final survey report."""

    def __init__(self, config: AppConfig) -> None:
        api_cfg = config.api.deepseek
        self.llm = OpenAI(
            api_key=api_cfg.api_key,
            base_url=api_cfg.base_url,
            timeout=api_cfg.timeout,
        )
        self.model = api_cfg.model_digest
        self.data_dir = Path(config.pipeline.data_dir)
        self.output_dir = Path(config.pipeline.output_dir)

    def build(self) -> str:
        """Collect all materials and generate the final report."""
        # Load cards
        cards_data = load_jsonl(str(self.data_dir / "paper_cards.jsonl"))
        cards = [PaperCard(**d) for d in cards_data]
        logger.info(f"Loaded {len(cards)} paper cards")

        # Load taxonomy
        taxonomy_path = self.data_dir / "taxonomy.md"
        taxonomy = taxonomy_path.read_text(encoding="utf-8") if taxonomy_path.exists() else ""

        # Load comparison
        comparison_path = self.data_dir / "comparison_table.csv"
        comparison_summary = ""
        if comparison_path.exists():
            df = pd.read_csv(comparison_path)
            comparison_summary = self._summarize_comparison(df)

        # Collect digests
        digests_combined = self._collect_digests()

        # Time span — load from raw papers which have published dates
        papers_data = load_json(str(self.data_dir / "papers_raw.json")) or []
        dates = [p.get("published", "") for p in papers_data if p.get("published")]
        time_span = f"{min(dates)} to {max(dates)}" if dates else "N/A"

        # Categories
        categories = sorted(set(c.best_fit_category for c in cards))

        # Generate report
        report = self._generate_report(
            taxonomy=taxonomy or "Taxonomy not available.",
            comparison_summary=comparison_summary or "Comparison data not available.",
            digests_combined=digests_combined or "No accumulated digests.",
            total_papers=len(cards),
            categories=", ".join(categories),
            time_span=time_span,
        )

        return report

    def _collect_digests(self) -> str:
        """Read and combine all weekly digest files."""
        weekly_dir = self.data_dir / "weekly"
        if not weekly_dir.exists():
            return ""

        digest_files = sorted(weekly_dir.glob("digest_*.md"))
        if not digest_files:
            return ""

        parts = []
        for f in digest_files:
            content = f.read_text(encoding="utf-8")
            parts.append(f"### From {f.stem}\n\n{content}")

        return "\n\n---\n\n".join(parts)

    def _generate_report(self, **kwargs) -> str:
        """Call DeepSeek to generate the final report."""
        # If report is very long, truncate some inputs
        digests = kwargs.get("digests_combined", "")
        if len(digests) > 8000:
            kwargs["digests_combined"] = digests[:8000] + "\n\n[... earlier digests truncated ...]"
        taxonomy = kwargs.get("taxonomy", "")
        if len(taxonomy) > 3000:
            kwargs["taxonomy"] = taxonomy[:3000] + "\n\n[... taxonomy truncated ...]"

        try:
            prompt = REPORT_PROMPT
            for key, val in kwargs.items():
                prompt = prompt.replace("{" + key + "}", str(val))
            response = self.llm.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=16384,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"Report generation failed: {e}")
            return f"*Report generation failed: {e}*"

    def _summarize_comparison(self, df: pd.DataFrame) -> str:
        """Brief summary of the comparison table."""
        if df.empty:
            return ""
        lines = [f"{len(df)} methods analyzed."]
        if "complexity" in df.columns:
            lines.append(f"Complexity: {df['complexity'].value_counts().to_dict()}")
        if "scenario" in df.columns:
            top = df["scenario"].value_counts().head(10).to_dict()
            lines.append(f"Top scenarios: {json.dumps(top)}")
        return "\n".join(lines)

    def save(self, report_md: str) -> str:
        """Save final report to output directory."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / "final_report.md"
        path.write_text(report_md, encoding="utf-8")
        logger.info(f"Final report saved to {path}")
        return str(path)


def run_report(config: AppConfig) -> None:
    """CLI entry point."""
    builder = ReportBuilder(config)
    report = builder.build()
    builder.save(report)
    logger.info("Final report generated successfully.")
