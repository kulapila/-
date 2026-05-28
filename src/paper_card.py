"""Paper card generation via DeepSeek API — structured analysis of each paper."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from openai import AsyncOpenAI
from pydantic import ValidationError

from .config import AppConfig
from .models import ArxivPaper, PaperCard
from .rate_limiter import RateLimiter
from .utils import load_json, load_jsonl, append_jsonl, get_logger, retry_with_backoff

logger = get_logger(__name__)

SYSTEM_PROMPT = """You are an expert academic researcher analyzing papers in the field of code generation and large language models for code.

Analyze the provided paper and produce a structured JSON object. You MUST return ONLY a valid JSON object, nothing else. No markdown, no code fences, no additional text.

The JSON must have exactly these fields:
- arxiv_id: string (copy from input)
- title: string (copy from input)
- problem: string (1-2 sentences on the research problem addressed)
- key_idea: string (1-2 sentences on the core novelty or key insight)
- method: string (1-3 sentences on the technical approach)
- dataset_or_scenario: string (datasets or evaluation scenarios used)
- metrics: string (metrics reported, e.g. pass@k, BLEU, execution accuracy)
- results_summary: string (1-2 sentences on key results)
- innovation_type: one of ["novel_architecture", "benchmark", "analysis", "application", "framework", "dataset"]
- limitations: string (1-2 sentences on acknowledged or inferred limitations)
- best_fit_category: string (sub-area of code generation, e.g. "Code Completion", "Program Repair", "Test Generation", "Code Translation", "Benchmark & Evaluation", "Training Techniques", "Security & Robustness", "Agent-based Code Generation")
- confidence_level: one of ["high", "medium", "low"]

CRITICAL RULES:
1. Base ALL information strictly on the provided abstract. Do NOT fabricate or guess.
2. If a field cannot be determined from the abstract, write "Not specified in the abstract".
3. Be specific and concise. Avoid vague generalizations.
4. For innovation_type, pick the single best match from the enum list."""


def _build_user_prompt(paper: ArxivPaper) -> str:
    return f"""Paper Title: {paper.title}
Authors: {', '.join(paper.authors[:5])}
Published: {paper.published}
Primary Category: {paper.primary_category}

Abstract:
{paper.abstract}"""


class PaperCardGenerator:
    """Generates structured PaperCard objects using DeepSeek API."""

    def __init__(self, config: AppConfig) -> None:
        api_cfg = config.api.deepseek
        self.client = AsyncOpenAI(
            api_key=api_cfg.api_key,
            base_url=api_cfg.base_url,
            timeout=api_cfg.timeout,
        )
        self.model = api_cfg.model_cards
        self.rate_limiter = RateLimiter(max_rpm=api_cfg.max_rpm)
        self.concurrent = config.pipeline.concurrent_card_generation
        self.data_dir = Path(config.pipeline.data_dir)
        self.max_retries = api_cfg.max_retries

    async def generate_all(
        self,
        papers: list[ArxivPaper],
        skip_existing: bool = True,
    ) -> list[PaperCard]:
        """Process papers through DeepSeek with controlled concurrency."""
        existing_ids: set[str] = set()
        if skip_existing:
            existing = self._load_existing_cards()
            existing_ids = set(existing.keys())

        new_papers = [p for p in papers if p.arxiv_id not in existing_ids]
        if not new_papers:
            logger.info("All papers already have cards, nothing to generate")
            return []

        logger.info(f"Generating cards for {len(new_papers)} new papers " f"(concurrency={self.concurrent})")
        semaphore = asyncio.Semaphore(self.concurrent)

        async def _process(paper: ArxivPaper) -> PaperCard | None:
            async with semaphore:
                return await self._generate_one(paper)

        tasks = [_process(p) for p in new_papers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        cards: list[PaperCard] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Failed to generate card for {new_papers[i].arxiv_id}: {result}")
            elif result is not None:
                cards.append(result)
                append_jsonl(result.model_dump(), str(self.data_dir / "paper_cards.jsonl"))

        logger.info(f"Generated {len(cards)} new cards")
        return cards

    async def _generate_one(self, paper: ArxivPaper) -> PaperCard | None:
        """Call DeepSeek for a single paper with retry logic."""
        await self.rate_limiter.acquire()

        for attempt in range(self.max_retries + 1):
            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": _build_user_prompt(paper)},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.1,
                    max_tokens=1024,
                )
                raw_text = response.choices[0].message.content or ""
                return self._parse_response(raw_text, paper)

            except Exception as e:
                logger.warning(
                    f"Attempt {attempt + 1}/{self.max_retries} failed for {paper.arxiv_id}: {e}"
                )
                if attempt == self.max_retries:
                    logger.error(f"All retries exhausted for {paper.arxiv_id}")
                    return None
                delay = min(2 ** attempt, 30)
                await asyncio.sleep(delay)

        return None

    def _parse_response(self, raw_text: str, paper: ArxivPaper) -> PaperCard | None:
        """Parse JSON response, repair if needed, validate with Pydantic."""
        # Strip potential code fences
        text = raw_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            try:
                from json_repair import repair_json
                text = repair_json(text)
                data = json.loads(text)
                logger.info(f"JSON repaired for {paper.arxiv_id}")
            except Exception:
                logger.error(f"JSON repair failed for {paper.arxiv_id}")
                return None

        # Force arxiv_id and title from source data, not LLM output
        data["arxiv_id"] = paper.arxiv_id
        data["title"] = paper.title
        for field in PaperCard.model_fields:
            if field not in data:
                data[field] = "Not specified in the abstract"

        try:
            return PaperCard(**data)
        except ValidationError as e:
            logger.error(f"Validation failed for {paper.arxiv_id}: {e}")
            return None

    def _load_existing_cards(self) -> dict[str, dict]:
        """Load existing cards, return dict keyed by arxiv_id."""
        cards_path = self.data_dir / "paper_cards.jsonl"
        rows = load_jsonl(str(cards_path))
        return {row["arxiv_id"]: row for row in rows}


def run_card_generation(config: AppConfig) -> None:
    """CLI entry point — synchronous wrapper."""
    data_dir = Path(config.pipeline.data_dir)
    papers_path = data_dir / "papers_raw.json"
    papers_data = load_json(str(papers_path))
    if not papers_data:
        logger.error("No papers found. Run fetcher first.")
        return
    papers = [ArxivPaper(**p) for p in papers_data]

    generator = PaperCardGenerator(config)
    asyncio.run(generator.generate_all(papers, skip_existing=True))
