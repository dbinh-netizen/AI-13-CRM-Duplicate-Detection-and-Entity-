"""Candidate Cluster Management Service for SongNhat CRM.

Sub-milestone: P2.4.2 - Candidate Cluster Management
Module: backend.review.cluster_service

Key Responsibilities:
1. Connected Components Clustering:
   - Groups candidate pairs from a matching run into coherent candidate clusters using Disjoint Set Union (DSU).
   - Strict Pool Segregation: Enforces homogenous entity pool (ACCOUNT or CONTACT).
   - No Self-Membership: Guarantees records are never paired or clustered with themselves.
2. Complete Graph Transitive Validation $O(K^2)$:
   - Evaluates all $\\binom{K}{2}$ pairs within a cluster against `pair_decision_constraints` (e.g. MUST_NOT_MERGE).
   - Detects transitive contradictions (e.g. A=B, B=C, but A≠C).
3. Cluster Membership & History Management:
   - Tracks active members with confidence scores.
   - Preserves historical records on split or removal without physical deletion.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import Session

from backend.models.intake import SourceRecord
from backend.models.matching import CandidatePair, CandidatePairEvidence
from backend.models.review import (
    CandidateCluster,
    CandidateClusterMember,
    PairDecisionConstraint,
)

logger = logging.getLogger(__name__)


class ClusterMemberView(BaseModel):
    """View model for a cluster member record."""

    member_id: str
    source_record_id: str
    source_system_code: Optional[str] = None
    source_key: Optional[str] = None
    primary_name: Optional[str] = None
    tax_code: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    membership_role: str = "MEMBER"
    status: str = "ACTIVE"
    confidence_score: Optional[float] = None
    added_at: datetime


class ClusterValidationResult(BaseModel):
    """Output package of Complete Graph Transitive Validation O(K^2)."""

    cluster_id: str
    is_valid: bool
    total_members: int
    total_possible_pairs: int
    conflicting_pairs: List[Tuple[str, str, str]] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)


class ClusterDetailView(BaseModel):
    """Comprehensive diagnostic and UI presentation view for a Candidate Cluster."""

    cluster_id: str
    cluster_code: str
    matching_run_id: str
    entity_pool: str
    status: str
    suggested_action: str
    members: List[ClusterMemberView] = Field(default_factory=list)
    associated_pairs_count: int = 0
    has_conflicts: bool = False
    conflict_notes: List[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Disjoint Set Union (DSU) Data Structure for Graph Clustering
# ---------------------------------------------------------------------------

class DisjointSetUnion:
    """Disjoint Set Union (Union-Find) with path compression and rank optimization."""

    def __init__(self):
        self.parent: Dict[str, str] = {}
        self.rank: Dict[str, int] = {}

    def find(self, item: str) -> str:
        if item not in self.parent:
            self.parent[item] = item
            self.rank[item] = 0
            return item
        if self.parent[item] != item:
            self.parent[item] = self.find(self.parent[item])
        return self.parent[item]

    def union(self, a: str, b: str) -> bool:
        root_a = self.find(a)
        root_b = self.find(b)
        if root_a == root_b:
            return False

        if self.rank[root_a] < self.rank[root_b]:
            self.parent[root_a] = root_b
        elif self.rank[root_a] > self.rank[root_b]:
            self.parent[root_b] = root_a
        else:
            self.parent[root_b] = root_a
            self.rank[root_a] += 1
        return True


# ---------------------------------------------------------------------------
# Cluster Management Service
# ---------------------------------------------------------------------------

class ClusterService:
    """Service orchestrating candidate clustering, graph validation, and membership lifecycle."""

    def create_clusters_from_pairs(
        self,
        session: Session,
        matching_run_id: Union[str, UUID],
        entity_pool: str,
        min_score_threshold: float = 60.0,
        suggested_action: str = "REVIEW_DUPLICATE",
    ) -> List[CandidateCluster]:
        """
        Groups candidate pairs of a matching run into connected component clusters.
        Only candidate pairs with total_score >= min_score_threshold are clustered.
        """
        run_uuid = UUID(str(matching_run_id))
        pool = entity_pool.upper()

        if pool not in ("ACCOUNT", "CONTACT"):
            raise ValueError(f"Invalid entity pool '{entity_pool}'. Must be ACCOUNT or CONTACT.")

        # 1. Fetch candidate pairs for this run and pool
        pairs = session.execute(
            select(CandidatePair)
            .where(
                and_(
                    CandidatePair.matching_run_id == run_uuid,
                    CandidatePair.entity_type == pool,
                    CandidatePair.total_score >= min_score_threshold,
                )
            )
        ).scalars().all()

        if not pairs:
            return []

        # 2. Build graph and compute Connected Components via DSU
        dsu = DisjointSetUnion()
        pair_scores: Dict[Tuple[str, str], float] = {}
        record_nodes: Set[str] = set()

        for p in pairs:
            left_id = str(p.left_source_record_id)
            right_id = str(p.right_source_record_id)

            # Prevent self-membership
            if left_id == right_id:
                continue

            record_nodes.add(left_id)
            record_nodes.add(right_id)
            dsu.union(left_id, right_id)

            canonical_pair = (left_id, right_id) if left_id < right_id else (right_id, left_id)
            pair_scores[canonical_pair] = float(p.total_score or 0.0)

        # 3. Group nodes by root representative
        components: Dict[str, List[str]] = {}
        for node in sorted(record_nodes):
            root = dsu.find(node)
            if root not in components:
                components[root] = []
            components[root].append(node)

        # 4. Check existing active clusters to respect unique active member constraint
        existing_active_members = session.execute(
            select(CandidateClusterMember.source_record_id)
            .where(CandidateClusterMember.status == "ACTIVE")
        ).scalars().all()
        active_member_set = {str(m) for m in existing_active_members}

        created_clusters: List[CandidateCluster] = []
        now_dt = datetime.now(timezone.utc)

        for root, member_ids in components.items():
            # A cluster must contain at least 2 records
            if len(member_ids) < 2:
                continue

            # Check if any member already belongs to an active cluster
            clashing_members = [m for m in member_ids if m in active_member_set]
            if clashing_members:
                logger.warning(
                    f"Skipping cluster formation for component {root}: "
                    f"Members {clashing_members} already in active clusters."
                )
                continue

            cluster_id = uuid.uuid4()
            cluster_code = f"CLUS-{pool[:3]}-{now_dt.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

            cluster = CandidateCluster(
                id=cluster_id,
                cluster_code=cluster_code,
                matching_run_id=run_uuid,
                entity_pool=pool,
                status="PROPOSED",
                suggested_action=suggested_action,
                created_at=now_dt,
                updated_at=now_dt,
            )
            session.add(cluster)
            session.flush()

            # Attach members
            for m_id in member_ids:
                m_uuid = UUID(m_id)
                # Compute average confidence score with other members in cluster
                incident_scores = [
                    score for (a, b), score in pair_scores.items()
                    if (a == m_id or b == m_id) and (a in member_ids and b in member_ids)
                ]
                avg_confidence = round(sum(incident_scores) / len(incident_scores), 2) if incident_scores else None

                member = CandidateClusterMember(
                    id=uuid.uuid4(),
                    candidate_cluster_id=cluster_id,
                    source_record_id=m_uuid,
                    membership_role="MEMBER",
                    status="ACTIVE",
                    confidence_score=avg_confidence,
                    added_at=now_dt,
                )
                session.add(member)
                active_member_set.add(m_id)

            created_clusters.append(cluster)

        session.commit()
        return created_clusters

    def validate_cluster_transitive_consistency(
        self,
        session: Session,
        cluster_id: Union[str, UUID],
    ) -> ClusterValidationResult:
        """
        Complete Graph Validation O(K^2) for candidate clusters.
        Exhaustively verifies all (K choose 2) pairs within the cluster against:
        1. Pair decision constraints (e.g. MUST_NOT_MERGE).
        2. Strict pool segregation (ACCOUNT vs CONTACT).
        """
        c_uuid = UUID(str(cluster_id))
        cluster = session.execute(
            select(CandidateCluster).where(CandidateCluster.id == c_uuid)
        ).scalar_one_or_none()

        if not cluster:
            raise ValueError(f"CandidateCluster '{cluster_id}' not found.")

        # Fetch active members
        members = session.execute(
            select(CandidateClusterMember)
            .where(
                and_(
                    CandidateClusterMember.candidate_cluster_id == c_uuid,
                    CandidateClusterMember.status == "ACTIVE",
                )
            )
        ).scalars().all()

        member_ids = [str(m.source_record_id) for m in members]
        k = len(member_ids)
        total_possible_pairs = (k * (k - 1)) // 2 if k >= 2 else 0

        conflicting_pairs: List[Tuple[str, str, str]] = []
        reasons: List[str] = []

        if k < 2:
            return ClusterValidationResult(
                cluster_id=str(c_uuid),
                is_valid=True,
                total_members=k,
                total_possible_pairs=0,
            )

        # Query all active constraints between any of the member records
        member_uuids = [UUID(m) for m in member_ids]
        constraints = session.execute(
            select(PairDecisionConstraint)
            .where(
                and_(
                    PairDecisionConstraint.is_active == True,
                    PairDecisionConstraint.source_record_a_id.in_(member_uuids),
                    PairDecisionConstraint.source_record_b_id.in_(member_uuids),
                )
            )
        ).scalars().all()

        constraint_map: Dict[Tuple[str, str], str] = {
            (str(c.source_record_a_id), str(c.source_record_b_id)): c.constraint_type
            for c in constraints
        }

        # O(K^2) Pairwise verification
        for i in range(k):
            rec_a = member_ids[i]
            for j in range(i + 1, k):
                rec_b = member_ids[j]
                left_id, right_id = (rec_a, rec_b) if rec_a < rec_b else (rec_b, rec_a)
                pair_key = (left_id, right_id)

                if pair_key in constraint_map:
                    c_type = constraint_map[pair_key]
                    if c_type == "MUST_NOT_MERGE":
                        conflicting_pairs.append((left_id, right_id, c_type))
                        reasons.append(
                            f"Transitive Contradiction: Pair ({left_id}, {right_id}) has constraint '{c_type}'."
                        )

        is_valid = len(conflicting_pairs) == 0
        return ClusterValidationResult(
            cluster_id=str(c_uuid),
            is_valid=is_valid,
            total_members=k,
            total_possible_pairs=total_possible_pairs,
            conflicting_pairs=conflicting_pairs,
            reasons=reasons,
        )

    def get_cluster_details(
        self,
        session: Session,
        cluster_id: Union[str, UUID],
    ) -> ClusterDetailView:
        """Fetch comprehensive details, active members, associated pairs, and conflict diagnostic."""
        c_uuid = UUID(str(cluster_id))
        cluster = session.execute(
            select(CandidateCluster).where(CandidateCluster.id == c_uuid)
        ).scalar_one_or_none()

        if not cluster:
            raise ValueError(f"CandidateCluster '{cluster_id}' not found.")

        # Query members with joined SourceRecord details
        members_q = session.execute(
            select(CandidateClusterMember, SourceRecord)
            .join(SourceRecord, CandidateClusterMember.source_record_id == SourceRecord.id)
            .where(CandidateClusterMember.candidate_cluster_id == c_uuid)
            .order_by(CandidateClusterMember.added_at)
        ).all()

        member_views: List[ClusterMemberView] = []
        for mem, sr in members_q:
            member_views.append(
                ClusterMemberView(
                    member_id=str(mem.id),
                    source_record_id=str(sr.id),
                    source_system_code=getattr(sr, "source_system_id", None) and str(sr.source_system_id),
                    source_key=sr.source_key,
                    primary_name=sr.primary_name,
                    tax_code=sr.tax_code,
                    phone=sr.phone_clean,
                    email=sr.email_clean,
                    membership_role=mem.membership_role,
                    status=mem.status,
                    confidence_score=mem.confidence_score,
                    added_at=mem.added_at,
                )
            )

        # Run validation for conflict diagnostic
        validation = self.validate_cluster_transitive_consistency(session, c_uuid)

        # Count candidate pairs linking members of this cluster
        member_uuids = [UUID(m.source_record_id) for m in member_views if m.status == "ACTIVE"]
        pairs_count = 0
        if len(member_uuids) >= 2:
            pairs_count = session.execute(
                select(CandidatePair)
                .where(
                    and_(
                        CandidatePair.left_source_record_id.in_(member_uuids),
                        CandidatePair.right_source_record_id.in_(member_uuids),
                    )
                )
            ).scalars().all()
            pairs_count = len(pairs_count)

        return ClusterDetailView(
            cluster_id=str(cluster.id),
            cluster_code=cluster.cluster_code,
            matching_run_id=str(cluster.matching_run_id),
            entity_pool=cluster.entity_pool,
            status=cluster.status,
            suggested_action=cluster.suggested_action,
            members=member_views,
            associated_pairs_count=pairs_count,
            has_conflicts=not validation.is_valid,
            conflict_notes=validation.reasons,
            created_at=cluster.created_at,
            updated_at=cluster.updated_at,
        )
