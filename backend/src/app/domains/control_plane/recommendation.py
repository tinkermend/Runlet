from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class CheckCandidateStats:
    page_asset_id: UUID
    page_check_id: UUID
    asset_key: str
    check_code: str
    goal: str
    leaf_text: str | None
    display_chain: str | None
    chain_complete: bool
    alias_confidence: float
    success_rate: float | None
    last_run_at: datetime | None
    sample_count: int


@dataclass(frozen=True)
class RankedCheckCandidate:
    page_asset_id: UUID
    page_check_id: UUID
    asset_key: str
    check_code: str
    goal: str
    leaf_text: str | None
    display_chain: str | None
    chain_complete: bool
    alias_confidence: float
    success_rate: float
    sample_count: int
    recency_score: float
    rank_score: float


def _clamp_score(value: float | None) -> float:
    if value is None:
        return 0.0
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return float(value)


def _build_recency_scores(candidates: list[CheckCandidateStats]) -> dict[UUID, float]:
    last_runs = [item.last_run_at for item in candidates if item.last_run_at is not None]
    if not last_runs:
        return {item.page_check_id: 0.0 for item in candidates}

    max_timestamp = max(last_runs).timestamp()
    if max_timestamp <= 0:
        return {item.page_check_id: 0.0 for item in candidates}

    recency_scores: dict[UUID, float] = {}
    for item in candidates:
        if item.last_run_at is None:
            recency_scores[item.page_check_id] = 0.0
            continue
        score = item.last_run_at.timestamp() / max_timestamp
        recency_scores[item.page_check_id] = _clamp_score(score)
    return recency_scores


def rank_candidates(
    candidates: list[CheckCandidateStats],
    *,
    success_rate_weight: float = 0.7,
    alias_confidence_weight: float = 0.2,
    recency_weight: float = 0.1,
    cold_start_threshold: int = 20,
) -> list[RankedCheckCandidate]:
    if not candidates:
        return []

    recency_scores = _build_recency_scores(candidates)
    ranked: list[RankedCheckCandidate] = []
    for item in candidates:
        success_rate = _clamp_score(item.success_rate)
        alias_confidence = _clamp_score(item.alias_confidence)
        recency_score = recency_scores.get(item.page_check_id, 0.0)
        is_cold_start = item.sample_count < cold_start_threshold
        if is_cold_start:
            # Cold-start candidates prioritize alias confidence; recency is tie-breaker.
            rank_score = alias_confidence
        else:
            rank_score = (
                success_rate_weight * success_rate
                + alias_confidence_weight * alias_confidence
                + recency_weight * recency_score
            )
        ranked.append(
            RankedCheckCandidate(
                page_asset_id=item.page_asset_id,
                page_check_id=item.page_check_id,
                asset_key=item.asset_key,
                check_code=item.check_code,
                goal=item.goal,
                leaf_text=item.leaf_text,
                display_chain=item.display_chain,
                chain_complete=item.chain_complete,
                alias_confidence=alias_confidence,
                success_rate=success_rate,
                sample_count=item.sample_count,
                recency_score=recency_score,
                rank_score=rank_score,
            )
        )

    def candidate_key(item: RankedCheckCandidate) -> tuple[float, float, float, float, str]:
        if item.sample_count < cold_start_threshold:
            return (
                item.rank_score,
                item.recency_score,
                item.success_rate,
                item.alias_confidence,
                str(item.page_check_id),
            )
        return (
            item.rank_score,
            item.alias_confidence,
            item.recency_score,
            item.success_rate,
            str(item.page_check_id),
        )

    ranked.sort(key=candidate_key, reverse=True)
    return ranked
