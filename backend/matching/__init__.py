"""Matching Engine package for SongNhat CRM Duplicate Detection & Entity Resolution.
"""

from backend.matching.blocking_engine import (
    MultiPathBlockingEngine,
    BlockingStrategy,
    SourceRecordInput,
    IdentifierItem,
    BlockingPath,
    BlockingCandidatePair,
    BlockingResult,
    BlockingStats,
    EntityPool,
)
from backend.matching.pair_deduplicator import (
    PairDeduplicator,
    DeduplicationStats,
)
from backend.matching.candidate_generator import (
    CandidateGenerator,
    CandidateGenerationStats,
    CandidateGenerationResult,
)
from backend.matching.similarity_scorer import (
    SimilarityScorer,
    ScoringPolicy,
    PairScoringResult,
    AttributeScoreDetail,
    AttributeStatus,
    SignalDirection,
    SimilarityTier,
    DEFAULT_ACCOUNT_SCORING_POLICY,
    DEFAULT_CONTACT_SCORING_POLICY,
)
from backend.matching.evidence_builder import (
    EvidenceBuilder,
    EvidenceItemRecord,
    EvidencePackage,
)
from backend.matching.matching_run_service import (
    MatchingRunService,
    PersistenceBatchSummary,
)

__all__ = [
    "MultiPathBlockingEngine",
    "BlockingStrategy",
    "SourceRecordInput",
    "IdentifierItem",
    "BlockingPath",
    "BlockingCandidatePair",
    "BlockingResult",
    "BlockingStats",
    "EntityPool",
    "PairDeduplicator",
    "DeduplicationStats",
    "CandidateGenerator",
    "CandidateGenerationStats",
    "CandidateGenerationResult",
    "SimilarityScorer",
    "ScoringPolicy",
    "PairScoringResult",
    "AttributeScoreDetail",
    "AttributeStatus",
    "SignalDirection",
    "SimilarityTier",
    "DEFAULT_ACCOUNT_SCORING_POLICY",
    "DEFAULT_CONTACT_SCORING_POLICY",
    "EvidenceBuilder",
    "EvidenceItemRecord",
    "EvidencePackage",
    "MatchingRunService",
    "PersistenceBatchSummary",
]
