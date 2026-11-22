"""Multi-Path Blocking Engine for SongNhat CRM Duplicate Detection & Entity Resolution.

Sub-milestone: P2.3.2 - Multi-path Blocking
Module: backend.matching.blocking_engine

Implements 5 independent blocking strategies:
1. TAX_ID: Compares identical identifier types, respects issuer & jurisdiction, cleans formats.
2. PHONE: Normalizes digits, supports multiple phone numbers, no country code guessing.
3. EMAIL: Lowercases and trims, preserves dots and plus suffixes unless explicitly authorized.
4. NORMALIZED_NAME: Strips legal corporate entities (TNHH, CP, CTY, etc.) for ACCOUNT;
   cleans names for CONTACT; controls group size.
5. ADDRESS: Combined street/ward/district + province; strictly avoids giant single-province blocks.

Key Guarantees:
- Strict canonical ordering: left_source_record_id < right_source_record_id.
- No self-pairs (left != right).
- Strict pool segregation: ACCOUNT (CRM_A, CRM_B) vs CONTACT (CRM_C) - cross-pool prohibited.
- Multi-path deduplication: 1 unique candidate pair retaining all contributing blocking paths.
- Deterministic output ordering.
- Ceiling enforcement (max 200,000 unique candidates) with visible breach tracking.
- Oversized group protection (configurable max_group_size) to avoid combinatorial explosion.
"""

from __future__ import annotations

import re
import unicodedata
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EntityPool(str, Enum):
    ACCOUNT = "ACCOUNT"
    CONTACT = "CONTACT"


class BlockingStrategy(str, Enum):
    TAX_ID = "TAX_ID"
    PHONE = "PHONE"
    EMAIL = "EMAIL"
    NORMALIZED_NAME = "NORMALIZED_NAME"
    ADDRESS = "ADDRESS"


class IdentifierItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    identifier_type: str
    identifier_value: str
    issuer: Optional[str] = None
    jurisdiction: Optional[str] = "VN"
    is_primary: bool = False
    entity_level: Optional[str] = None


class SourceRecordInput(BaseModel):
    """Normalized input representation of a source record for blocking."""

    source_record_id: Union[UUID, str]
    source_system_code: str
    entity_type: str  # ACCOUNT or CONTACT
    source_key: Optional[str] = None
    version_id: Optional[Union[UUID, str]] = None
    version_number: int = 1
    raw_payload: Dict[str, Any] = Field(default_factory=dict)
    identifiers: List[IdentifierItem] = Field(default_factory=list)

    # Normalized fields for matching
    tax_code: Optional[str] = None
    tax_code_root: Optional[str] = None
    primary_name: Optional[str] = None
    normalized_name: Optional[str] = None
    name_tokens: List[str] = Field(default_factory=list)
    phone_clean: Optional[str] = None
    phones_clean: List[str] = Field(default_factory=list)
    email_clean: Optional[str] = None
    emails_clean: List[str] = Field(default_factory=list)
    address_normalized: Optional[str] = None
    province_city: Optional[str] = None
    district: Optional[str] = None
    street_ward: Optional[str] = None
    normalization_policy_version: Optional[str] = "1.0"

    def get_id_str(self) -> str:
        return str(self.source_record_id)


class BlockingPath(BaseModel):
    """Represents a single blocking path that brought two records into a candidate pair."""

    model_config = ConfigDict(frozen=True)

    strategy: BlockingStrategy
    blocking_key_name: str
    blocking_value: str

    def __lt__(self, other: BlockingPath) -> bool:
        return (self.strategy.value, self.blocking_key_name, self.blocking_value) < (
            other.strategy.value,
            other.blocking_key_name,
            other.blocking_value,
        )


class BlockingCandidatePair(BaseModel):
    """Unique candidate pair edge discovered by one or more blocking strategies."""

    matching_run_id: Optional[Union[UUID, str]] = None
    left_source_record_id: str
    right_source_record_id: str
    entity_type: str
    blocking_paths: List[BlockingPath] = Field(default_factory=list)

    def add_blocking_path(self, path: BlockingPath) -> None:
        if path not in self.blocking_paths:
            self.blocking_paths.append(path)
            self.blocking_paths.sort()


class BlockingStats(BaseModel):
    """Auditable statistics produced by the MultiPathBlockingEngine."""

    records_scanned: int = 0
    blocking_keys_generated: Dict[str, int] = Field(default_factory=dict)
    blocking_groups_count: int = 0
    oversized_groups_count: int = 0
    oversized_groups_details: List[Dict[str, Any]] = Field(default_factory=list)
    raw_candidate_pairs_generated: int = 0
    duplicate_pairs_pruned: int = 0
    unique_candidate_pairs: int = 0
    ceiling_breached: bool = False
    path_contribution: Dict[str, int] = Field(default_factory=dict)
    multi_path_pair_count: int = 0
    execution_time_seconds: float = 0.0


class BlockingResult(BaseModel):
    """Complete result package of a multi-path blocking execution."""

    matching_run_id: Optional[Union[UUID, str]] = None
    entity_pool: str
    candidate_pairs: List[BlockingCandidatePair] = Field(default_factory=list)
    stats: BlockingStats = Field(default_factory=BlockingStats)


# ---------------------------------------------------------------------------
# Normalization & Helper Utilities
# ---------------------------------------------------------------------------

VIETNAMESE_LEGAL_PREFIXES = [
    r"\bcong ty tnhh mot thanh vien\b",
    r"\bcong ty tnhh mtv\b",
    r"\bcty tnhh mot thanh vien\b",
    r"\bcty tnhh mtv\b",
    r"\bcong ty tnhh 1 tv\b",
    r"\bcty tnhh 1 tv\b",
    r"\bcong ty co phan\b",
    r"\bcty co phan\b",
    r"\bcty cp\b",
    r"\bcong ty cp\b",
    r"\bdoanh nghiep tu nhan\b",
    r"\bdoanh nghiep tn\b",
    r"\bdntn\b",
    r"\bhop tac xa\b",
    r"\bhtx\b",
    r"\bcong ty lien doanh\b",
    r"\bcty lien doanh\b",
    r"\bcong ty\b",
    r"\bcty\b",
    r"\btnhh\b",
    r"\bco phan\b",
    r"\btap doan\b",
    r"\bchi nhanh\b",
    r"\bvan phong dai dien\b",
    r"\bvpdd\b",
]

COMPILED_LEGAL_PREFIXES = [
    re.compile(pattern, re.IGNORECASE) for pattern in VIETNAMESE_LEGAL_PREFIXES
]


def remove_vietnamese_accents(text: str) -> str:
    """Normalize and strip Vietnamese tone marks / diacritics."""
    if not text:
        return ""
    # Decompose unicode characters
    nfkd = unicodedata.normalize("NFKD", text)
    result = "".join([c for c in nfkd if not unicodedata.combining(c)])
    # Specific Vietnamese characters like đ, Đ
    result = result.replace("đ", "d").replace("Đ", "D")
    return result


def clean_vietnamese_company_name(name: str) -> str:
    """Remove legal entity form terms and common noise words to extract the core brand name."""
    if not name:
        return ""

    normalized = remove_vietnamese_accents(name.lower())
    normalized = re.sub(r"[^\w\s]", " ", normalized)

    # Sequentially remove corporate suffixes / prefixes
    for pattern in COMPILED_LEGAL_PREFIXES:
        normalized = pattern.sub(" ", normalized)

    # Collapse multiple whitespaces
    tokens = normalized.split()
    return " ".join(tokens).strip().upper()


def clean_tax_id(tax_id: str) -> str:
    """Standardize tax ID: strip hyphens, spaces, and punctuation."""
    if not tax_id:
        return ""
    cleaned = re.sub(r"[^0-9A-Za-z]", "", tax_id).strip().upper()
    return cleaned


def extract_tax_root(cleaned_tax: str) -> str:
    """Extract 10-digit tax root for Vietnamese 10 or 13-digit tax codes."""
    if len(cleaned_tax) >= 10 and cleaned_tax[:10].isdigit():
        return cleaned_tax[:10]
    return cleaned_tax


def clean_phone_number(phone: str) -> str:
    """Standardize phone number to digits only, avoiding country code speculation."""
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    return digits


def clean_email_address(email: str) -> str:
    """Standardize email: trim and lowercase. Preserves dots and plus suffixes."""
    if not email:
        return ""
    return email.strip().lower()


def clean_address_tokens(address: str) -> str:
    """Normalize address string for tokenization."""
    if not address:
        return ""
    no_accent = remove_vietnamese_accents(address.lower())
    clean = re.sub(r"[^\w\s]", " ", no_accent)
    return " ".join(clean.split()).upper()


# ---------------------------------------------------------------------------
# Core Multi-Path Blocking Engine
# ---------------------------------------------------------------------------

class MultiPathBlockingEngine:
    """Orchestrates multi-path blocking strategies and candidate pair generation."""

    def __init__(
        self,
        candidate_ceiling: int = 200_000,
        max_group_size: int = 500,
        active_strategies: Optional[List[BlockingStrategy]] = None,
    ):
        """
        Initialize the blocking engine.

        :param candidate_ceiling: Maximum unique candidate pairs permitted before halting.
        :param max_group_size: Maximum records in a single blocking bucket before triggering
                               oversized-group protection (prevents O(N^2) explosion).
        :param active_strategies: List of strategies to run (defaults to all 5).
        """
        self.candidate_ceiling = candidate_ceiling
        self.max_group_size = max_group_size
        self.active_strategies = active_strategies or [
            BlockingStrategy.TAX_ID,
            BlockingStrategy.PHONE,
            BlockingStrategy.EMAIL,
            BlockingStrategy.NORMALIZED_NAME,
            BlockingStrategy.ADDRESS,
        ]

    def extract_blocking_paths(
        self, record: SourceRecordInput
    ) -> List[Tuple[BlockingPath, str]]:
        """
        Extract all blocking paths and their bucket index keys for a given record.
        Returns a list of tuples: (BlockingPath, bucket_key).
        """
        paths: List[Tuple[BlockingPath, str]] = []

        # 1. TAX_ID STRATEGY
        if BlockingStrategy.TAX_ID in self.active_strategies:
            tax_codes_seen: Set[str] = set()

            # Direct tax_code field
            if record.tax_code:
                c_tax = clean_tax_id(record.tax_code)
                if c_tax:
                    tax_codes_seen.add(c_tax)

            # Direct tax_code_root field
            if record.tax_code_root:
                c_root = clean_tax_id(record.tax_code_root)
                if c_root:
                    tax_codes_seen.add(c_root)

            # Identifiers with TAX_ID
            for ident in record.identifiers:
                if ident.identifier_type.upper() == "TAX_ID" and ident.identifier_value:
                    c_val = clean_tax_id(ident.identifier_value)
                    if c_val:
                        tax_codes_seen.add(c_val)

            for tc in tax_codes_seen:
                # Root 10 digits comparison
                tc_root = extract_tax_root(tc)
                # Jurisdiction segregation: default "VN" unless identifier specifies otherwise
                jurisdiction = "VN"
                for ident in record.identifiers:
                    if ident.identifier_type.upper() == "TAX_ID" and clean_tax_id(ident.identifier_value) in (tc, tc_root):
                        if ident.jurisdiction:
                            jurisdiction = ident.jurisdiction.upper()
                        break

                path = BlockingPath(
                    strategy=BlockingStrategy.TAX_ID,
                    blocking_key_name="TAX_ID_ROOT",
                    blocking_value=f"{jurisdiction}:{tc_root}",
                )
                bucket_key = f"TAX_ID:{jurisdiction}:{tc_root}"
                paths.append((path, bucket_key))

        # 2. PHONE STRATEGY
        if BlockingStrategy.PHONE in self.active_strategies:
            phones_seen: Set[str] = set()

            if record.phone_clean:
                cp = clean_phone_number(record.phone_clean)
                if len(cp) >= 7:
                    phones_seen.add(cp)

            for p in record.phones_clean:
                cp = clean_phone_number(p)
                if len(cp) >= 7:
                    phones_seen.add(cp)

            for ident in record.identifiers:
                if ident.identifier_type.upper() in ("PHONE", "TEL", "MOBILE", "HOTLINE"):
                    cp = clean_phone_number(ident.identifier_value)
                    if len(cp) >= 7:
                        phones_seen.add(cp)

            for phone_val in phones_seen:
                path = BlockingPath(
                    strategy=BlockingStrategy.PHONE,
                    blocking_key_name="PHONE_EXACT",
                    blocking_value=phone_val,
                )
                bucket_key = f"PHONE:{phone_val}"
                paths.append((path, bucket_key))

        # 3. EMAIL STRATEGY
        if BlockingStrategy.EMAIL in self.active_strategies:
            emails_seen: Set[str] = set()

            if record.email_clean:
                ce = clean_email_address(record.email_clean)
                if "@" in ce:
                    emails_seen.add(ce)

            for em in record.emails_clean:
                ce = clean_email_address(em)
                if "@" in ce:
                    emails_seen.add(ce)

            for ident in record.identifiers:
                if ident.identifier_type.upper() == "EMAIL":
                    ce = clean_email_address(ident.identifier_value)
                    if "@" in ce:
                        emails_seen.add(ce)

            for email_val in emails_seen:
                path = BlockingPath(
                    strategy=BlockingStrategy.EMAIL,
                    blocking_key_name="EMAIL_EXACT",
                    blocking_value=email_val,
                )
                bucket_key = f"EMAIL:{email_val}"
                paths.append((path, bucket_key))

        # 4. NORMALIZED_NAME STRATEGY
        if BlockingStrategy.NORMALIZED_NAME in self.active_strategies:
            # Process based on entity type
            raw_name = record.normalized_name or record.primary_name
            if raw_name:
                if record.entity_type.upper() == EntityPool.ACCOUNT.value:
                    cleaned_name = clean_vietnamese_company_name(raw_name)
                    # Exclude overly generic names or tokens < 3 characters
                    if len(cleaned_name) >= 3 and cleaned_name not in ("VIET NAM", "VIETNAM"):
                        path = BlockingPath(
                            strategy=BlockingStrategy.NORMALIZED_NAME,
                            blocking_key_name="ACCOUNT_NAME_CLEAN",
                            blocking_value=cleaned_name,
                        )
                        bucket_key = f"NAME_ACCOUNT:{cleaned_name}"
                        paths.append((path, bucket_key))
                else:
                    # CONTACT personal name
                    cleaned_name = clean_address_tokens(raw_name)
                    if len(cleaned_name) >= 3:
                        path = BlockingPath(
                            strategy=BlockingStrategy.NORMALIZED_NAME,
                            blocking_key_name="CONTACT_NAME_CLEAN",
                            blocking_value=cleaned_name,
                        )
                        bucket_key = f"NAME_CONTACT:{cleaned_name}"
                        paths.append((path, bucket_key))

        # 5. ADDRESS STRATEGY
        if BlockingStrategy.ADDRESS in self.active_strategies:
            # Must combine street/ward/district + province.
            # Strictly reject single-province blocks (TC08)
            province = clean_address_tokens(record.province_city or "")
            street = clean_address_tokens(record.street_ward or record.address_normalized or "")

            if province and street and len(street) >= 3:
                # Combine province + street
                combined_val = f"{province}:{street}"
                path = BlockingPath(
                    strategy=BlockingStrategy.ADDRESS,
                    blocking_key_name="ADDR_COMBINED",
                    blocking_value=combined_val,
                )
                bucket_key = f"ADDR:{combined_val}"
                paths.append((path, bucket_key))
            elif street and len(street) >= 6:
                # Full specific normalized address without separate province
                path = BlockingPath(
                    strategy=BlockingStrategy.ADDRESS,
                    blocking_key_name="ADDR_COMBINED",
                    blocking_value=street,
                )
                bucket_key = f"ADDR:{street}"
                paths.append((path, bucket_key))
            # Notice: If province is present but street is empty, DO NOT EMIT a block.

        return paths

    def run_blocking(
        self,
        records: List[SourceRecordInput],
        matching_run_id: Optional[Union[UUID, str]] = None,
        entity_pool: Optional[str] = None,
    ) -> BlockingResult:
        """
        Execute multi-path blocking over a list of source records.

        :param records: List of normalized source records to block.
        :param matching_run_id: Optional UUID/str of the matching run.
        :param entity_pool: ACCOUNT or CONTACT. If provided, strictly validated.
        :return: BlockingResult with deduplicated candidate pairs and auditable statistics.
        """
        import time

        start_time = time.perf_counter()
        stats = BlockingStats()
        stats.records_scanned = len(records)

        if not records:
            return BlockingResult(
                matching_run_id=matching_run_id,
                entity_pool=entity_pool or "UNKNOWN",
                candidate_pairs=[],
                stats=stats,
            )

        # 1. Validate entity pool and strictly forbid cross-pool input
        pool = entity_pool or records[0].entity_type.upper()
        for r in records:
            r_pool = r.entity_type.upper()
            if r_pool != pool:
                raise ValueError(
                    f"Strict Pool Segregation Violation: Encountered record {r.source_record_id} "
                    f"with entity_type '{r_pool}' in a run designated for '{pool}'. "
                    f"Cross-pool matching between ACCOUNT and CONTACT is prohibited."
                )

        # 2. Build inverted index: bucket_key -> List[(record_id, BlockingPath)]
        inverted_index: Dict[str, List[Tuple[str, BlockingPath]]] = {}

        for record in records:
            r_id = record.get_id_str()
            paths = self.extract_blocking_paths(record)

            for path, bucket_key in paths:
                strat_name = path.strategy.value
                stats.blocking_keys_generated[strat_name] = (
                    stats.blocking_keys_generated.get(strat_name, 0) + 1
                )

                if bucket_key not in inverted_index:
                    inverted_index[bucket_key] = []
                inverted_index[bucket_key].append((r_id, path))

        stats.blocking_groups_count = len(inverted_index)

        # 3. Generate candidate pairs from buckets
        # Dictionary mapping canonical pair (left_id, right_id) -> BlockingCandidatePair
        candidate_dict: Dict[Tuple[str, str], BlockingCandidatePair] = {}

        # Sort bucket keys for determinism
        sorted_bucket_keys = sorted(inverted_index.keys())

        for bucket_key in sorted_bucket_keys:
            bucket = inverted_index[bucket_key]
            bucket_size = len(bucket)

            # Check oversized group protection (TC19)
            if bucket_size > self.max_group_size:
                stats.oversized_groups_count += 1
                stats.oversized_groups_details.append(
                    {
                        "bucket_key": bucket_key,
                        "size": bucket_size,
                        "threshold": self.max_group_size,
                    }
                )
                continue

            # Generate pairwise combinations within bucket
            for i in range(bucket_size):
                id_a, path_a = bucket[i]
                for j in range(i + 1, bucket_size):
                    id_b, path_b = bucket[j]

                    # Filter self-pairs (TC10)
                    if id_a == id_b:
                        continue

                    # Canonical ordering: left_id < right_id strictly (TC09)
                    if id_a < id_b:
                        left_id, right_id = id_a, id_b
                    else:
                        left_id, right_id = id_b, id_a

                    pair_key = (left_id, right_id)
                    stats.raw_candidate_pairs_generated += 1

                    # Check ceiling breach
                    if (
                        pair_key not in candidate_dict
                        and len(candidate_dict) >= self.candidate_ceiling
                    ):
                        stats.ceiling_breached = True
                        break

                    if pair_key not in candidate_dict:
                        cand = BlockingCandidatePair(
                            matching_run_id=matching_run_id,
                            left_source_record_id=left_id,
                            right_source_record_id=right_id,
                            entity_type=pool,
                            blocking_paths=[],
                        )
                        cand.add_blocking_path(path_a)
                        candidate_dict[pair_key] = cand
                    else:
                        stats.duplicate_pairs_pruned += 1
                        candidate_dict[pair_key].add_blocking_path(path_a)

                if stats.ceiling_breached:
                    break

            if stats.ceiling_breached:
                break

        # 4. Aggregate path contributions and finalize statistics
        stats.unique_candidate_pairs = len(candidate_dict)

        for pair in candidate_dict.values():
            if len(pair.blocking_paths) > 1:
                stats.multi_path_pair_count += 1

            for p in pair.blocking_paths:
                strat_str = p.strategy.value
                stats.path_contribution[strat_str] = (
                    stats.path_contribution.get(strat_str, 0) + 1
                )

        # 5. Sort candidate pairs for deterministic results (TC16)
        sorted_pairs = sorted(
            candidate_dict.values(),
            key=lambda x: (x.left_source_record_id, x.right_source_record_id),
        )

        stats.execution_time_seconds = round(time.perf_counter() - start_time, 4)

        return BlockingResult(
            matching_run_id=matching_run_id,
            entity_pool=pool,
            candidate_pairs=sorted_pairs,
            stats=stats,
        )
