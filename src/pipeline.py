"""Pipeline orchestrator — CLI entry point for all modules."""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

from .config import load_config, AppConfig
from .models import PipelineState, WeekSummary
from .utils import setup_logging, load_json, save_json, get_logger

logger = get_logger(__name__)


class Pipeline:
    """Full pipeline orchestrator with incremental state management."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.data_dir = Path(config.pipeline.data_dir)
        self.output_dir = Path(config.pipeline.output_dir)
        self.state_path = self.data_dir / "state.json"

    def run(self, incremental: bool = False) -> None:
        """Execute the full pipeline in sequence."""
        logger.info("=" * 60)
        logger.info(f"Survey Pipeline starting ({'incremental' if incremental else 'full'} mode)")
        logger.info("=" * 60)

        state = self._load_state()

        # Step 1: Fetch papers
        logger.info("--- Step 1: Fetching papers from arXiv ---")
        from .fetcher import ArxivFetcher
        fetcher = ArxivFetcher(self.config)
        since_date = state.last_arxiv_published_date if incremental else None
        result = fetcher.fetch(incremental=incremental, since_date=since_date)
        fetcher.save_papers(result, incremental=incremental)

        if result.total_new == 0 and incremental:
            logger.info("No new papers found. Pipeline complete.")
            return

        papers_list = result.new_papers if incremental else result.papers
        state.papers_processed = result.total_fetched

        # Step 2: Generate paper cards
        logger.info(f"--- Step 2: Generating cards for {len(papers_list)} papers ---")
        from .paper_card import PaperCardGenerator
        import asyncio
        card_gen = PaperCardGenerator(self.config)
        cards = asyncio.run(card_gen.generate_all(papers_list, skip_existing=True))
        state.cards_generated += len(cards)

        # Reload all cards for clustering (existing + new)
        all_cards = self._load_all_cards()
        if not all_cards:
            logger.error("No cards available. Stopping.")
            return

        # Step 3: Cluster
        logger.info(f"--- Step 3: Clustering {len(all_cards)} papers ---")
        from .clustering import PaperClusterer
        clusterer = PaperClusterer(self.config)
        cluster_result = clusterer.fit(all_cards)
        clusterer.save_results(cluster_result)

        # Step 4: Comparison table
        logger.info("--- Step 4: Building comparison table ---")
        from .comparison import ComparisonBuilder
        comp_builder = ComparisonBuilder(self.config)
        comp_df = comp_builder.build(all_cards)
        comp_builder.save(comp_df)

        # Step 5: Weekly digest
        logger.info("--- Step 5: Generating weekly digest ---")
        from .digest import DigestGenerator
        digest_gen = DigestGenerator(self.config)
        taxonomy = (self.data_dir / "taxonomy.md").read_text(encoding="utf-8") if (self.data_dir / "taxonomy.md").exists() else ""
        digest_md = digest_gen.generate(all_cards, taxonomy, comp_df, state)
        digest_path = digest_gen.save(digest_md)

        # Update state
        now = dt.datetime.now()
        state.last_run = now.isoformat()
        state.week_num = now.isocalendar().week
        state.year = now.year
        state.version += 1

        # Update last_arxiv_published_date from the latest paper
        if result.new_papers:
            latest_date = max(p.published for p in result.new_papers if p.published)
            if latest_date:
                state.last_arxiv_published_date = latest_date

        # Add week summary
        state.history.append(WeekSummary(
            week_label=f"{state.year}-W{state.week_num:02d}",
            new_papers=result.total_new,
            key_themes=list(cluster_result.cluster_labels.values()),
            generated_at=now.isoformat(),
        ))

        self._save_state(state)

        # Step 6: Final report (if we have enough weeks)
        weekly_dir = self.data_dir / "weekly"
        digest_count = len(list(weekly_dir.glob("digest_*.md"))) if weekly_dir.exists() else 0
        if digest_count >= 1:
            logger.info("--- Step 6: Generating final report ---")
            from .report import ReportBuilder
            report_builder = ReportBuilder(self.config)
            report_md = report_builder.build()
            report_builder.save(report_md)

        logger.info("=" * 60)
        logger.info(f"Pipeline complete. Version: {state.version}, "
                     f"Papers: {state.papers_processed}, Cards: {state.cards_generated}")
        logger.info(f"Digest: {digest_path}")
        logger.info("=" * 60)

    def _load_state(self) -> PipelineState:
        """Load or initialize pipeline state."""
        data = load_json(str(self.state_path))
        if data:
            return PipelineState(**data)
        return PipelineState()

    def _save_state(self, state: PipelineState) -> None:
        """Save pipeline state atomically."""
        save_json(state.model_dump(), str(self.state_path))

    def _load_all_cards(self):
        """Load all paper cards from JSONL."""
        from .utils import load_jsonl
        from .models import PaperCard
        cards_data = load_jsonl(str(self.data_dir / "paper_cards.jsonl"))
        return [PaperCard(**d) for d in cards_data]


# ---- CLI ----

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Automated Survey Pipeline for Code Generation Research"
    )
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--full", action="store_true", help="Run full pipeline")
    parser.add_argument("--incremental", action="store_true", help="Run incremental update")
    parser.add_argument(
        "--step",
        choices=["fetcher", "cards", "cluster", "compare", "digest", "report"],
        help="Run a single module",
    )
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    args = parser.parse_args()

    config = load_config(args.config)
    setup_logging(args.log_level or config.pipeline.log_level, config.pipeline.log_file)

    if args.step:
        _run_single_step(args.step, config)
    elif args.incremental:
        pipeline = Pipeline(config)
        pipeline.run(incremental=True)
    else:
        pipeline = Pipeline(config)
        pipeline.run(incremental=False)


def _run_single_step(step: str, config: AppConfig) -> None:
    """Execute a single pipeline step standalone."""
    logger.info(f"Running single step: {step}")
    if step == "fetcher":
        from .fetcher import run_fetcher
        run_fetcher(config)
    elif step == "cards":
        from .paper_card import run_card_generation
        run_card_generation(config)
    elif step == "cluster":
        from .clustering import run_clustering
        run_clustering(config)
    elif step == "compare":
        from .comparison import run_comparison
        run_comparison(config)
    elif step == "digest":
        from .digest import run_digest
        run_digest(config)
    elif step == "report":
        from .report import run_report
        run_report(config)


if __name__ == "__main__":
    main()
