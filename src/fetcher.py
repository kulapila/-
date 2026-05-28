"""arXiv API fetcher — search, parse, deduplicate, incremental fetch."""

from __future__ import annotations

import datetime as dt
import urllib.parse
from pathlib import Path

import feedparser
import httpx

from .config import AppConfig
from .models import ArxivPaper, FetchResult
from .utils import save_json, load_json, get_logger

logger = get_logger(__name__)

ARXIV_API_BASE = "http://export.arxiv.org/api/query"


class ArxivFetcher:
    """Fetches papers from arXiv API with dedup and incremental support."""

    def __init__(self, config: AppConfig) -> None:
        self.cfg = config.arxiv
        self.data_dir = Path(config.pipeline.data_dir)

    def fetch(self, incremental: bool = False, since_date: str | None = None) -> FetchResult:
        """
        Fetch papers from arXiv.
        - incremental: if True, only fetch papers newer than since_date.
        - since_date: ISO date string (e.g. '2024-01-01'), used in incremental mode.
        """
        all_papers: list[ArxivPaper] = []
        existing_ids = self._load_existing_ids()

        # Build date filter for incremental mode
        date_filter = ""
        if incremental and since_date:
            # arXiv date format: YYYYMMDDHHMMSS
            since_arxiv = since_date.replace("-", "") + "000000"
            date_filter = f" AND submittedDate:[{since_arxiv} TO 99991231235959]"

        start = 0
        total_expected = None

        while True:
            url = self._build_query(start, date_filter)
            logger.info(f"Fetching: start={start}, max={self.cfg.batch_size}")
            try:
                # arXiv requires a delay between requests
                response = httpx.get(url, timeout=60, follow_redirects=True)
                response.raise_for_status()
            except httpx.HTTPError as e:
                logger.error(f"HTTP error fetching arXiv: {e}")
                break

            feed = feedparser.parse(response.text)
            if feed.bozo and not feed.entries:
                logger.error(f"Feed parse error: {feed.bozo_exception}")
                break

            if total_expected is None:
                total_expected = int(feed.feed.get("opensearch_totalresults", 0))
                total_expected = min(total_expected, self.cfg.max_results)
                logger.info(f"Total results available: {total_expected}")

            for entry in feed.entries:
                paper = self._parse_entry(entry)
                if paper:
                    all_papers.append(paper)

            # Truncate if we got more than needed in one batch
            if total_expected and len(all_papers) > total_expected:
                all_papers = all_papers[:total_expected]
            logger.info(f"Fetched {len(all_papers)}/{total_expected} papers so far")
            if total_expected and len(all_papers) >= total_expected:
                break
            start += self.cfg.batch_size
            if len(feed.entries) < self.cfg.batch_size:
                break

            # Be polite to arXiv API
            import time
            time.sleep(1)

        # Deduplicate
        new_papers = [p for p in all_papers if p.arxiv_id not in existing_ids]
        logger.info(f"Total fetched: {len(all_papers)}, New: {len(new_papers)}")

        return FetchResult(
            papers=all_papers,
            new_papers=new_papers,
            total_fetched=len(all_papers),
            total_new=len(new_papers),
        )

    def _build_query(self, start: int, date_filter: str = "") -> str:
        """Build arXiv API query URL."""
        query = self.cfg.search_query.strip() + date_filter
        params = {
            "search_query": query,
            "start": start,
            "max_results": self.cfg.batch_size,
            "sortBy": self.cfg.sort_by,
            "sortOrder": self.cfg.sort_order,
        }
        return f"{ARXIV_API_BASE}?{urllib.parse.urlencode(params)}"

    def _parse_entry(self, entry: dict) -> ArxivPaper | None:
        """Parse a single Atom feed entry into an ArxivPaper object."""
        try:
            arxiv_id = entry.get("id", "").split("/abs/")[-1]
            # Strip version suffix (e.g., v1, v2)
            arxiv_id = arxiv_id.split("v")[0] if "v" in arxiv_id else arxiv_id

            title = " ".join(entry.get("title", "").split()).strip()
            authors = [a.get("name", "") for a in entry.get("authors", [])]

            abstract = " ".join(entry.get("summary", "").split()).strip()

            published = entry.get("published", "")
            if published:
                try:
                    published = dt.datetime.strptime(
                        published[:19], "%Y-%m-%dT%H:%M:%S"
                    ).strftime("%Y-%m-%d")
                except ValueError:
                    pass

            link = entry.get("id", "")

            tags = entry.get("tags", [])
            categories = [t.get("term", "") for t in tags]
            primary_category = categories[0] if categories else ""

            return ArxivPaper(
                arxiv_id=arxiv_id,
                title=title,
                authors=authors,
                abstract=abstract,
                published=published,
                url=link,
                primary_category=primary_category,
                categories=categories,
            )
        except Exception as e:
            logger.warning(f"Failed to parse entry: {e}")
            return None

    def _load_existing_ids(self) -> set[str]:
        """Load known arxiv_ids from existing papers_raw.json."""
        raw_path = self.data_dir / "papers_raw.json"
        existing = load_json(str(raw_path))
        if existing is None:
            return set()
        return {p.get("arxiv_id", "") for p in existing}

    def save_papers(self, result: FetchResult, incremental: bool = False) -> str:
        """Save or append papers to papers_raw.json."""
        raw_path = self.data_dir / "papers_raw.json"
        if incremental and raw_path.exists():
            existing = load_json(str(raw_path)) or []
            existing_ids = {p.get("arxiv_id", "") for p in existing}
            for paper in result.new_papers:
                if paper.arxiv_id not in existing_ids:
                    existing.append(paper.model_dump())
            save_json(existing, str(raw_path))
        else:
            save_json([p.model_dump() for p in result.papers], str(raw_path))
        return str(raw_path)


def run_fetcher(config: AppConfig) -> None:
    """CLI entry point."""
    fetcher = ArxivFetcher(config)
    result = fetcher.fetch(incremental=False)
    path = fetcher.save_papers(result, incremental=False)
    logger.info(f"Saved {result.total_fetched} papers to {path}")
