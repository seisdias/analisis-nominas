"""Diagnostic results, distinct from T6 CandidateDecision and candidate authorization."""
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from src.canonical.certification import EconomicEligibility
from src.canonical.readiness import CandidacyEvaluation


class SnapshotIntegrity(StrEnum):
    VERIFIED = 'verified'
    INVALID = 'invalid'
    UNAVAILABLE = 'unavailable'


class RelationalStatus(StrEnum):
    CONTEXT_ONLY = 'context_only'
    DISPLACED = 'displaced'
    UNRESOLVED = 'unresolved'
    NOT_EVALUATED = 'not_evaluated'


class RelationalReason(StrEnum):
    SNAPSHOT_INVALID = 'snapshot.invalid'
    SNAPSHOT_UNAVAILABLE = 'snapshot.unavailable'
    LOCAL_SUPPORT_UNSUPPORTED = 'local.support_scope_unsupported'
    DOCUMENT_SUPERSEDES = 'document.supersedes'
    OBSERVATION_REPLACES = 'observation.replaces'
    DUPLICATE = 'document.duplicate_of'
    RECONCILIATION = 'document.same_logical_unit_pending_reconciliation'
    CONTEXT_RELATION = 'relations.context_only'
    COMPETING_SOURCES = 'relations.competing_sources_unresolved'
    PRECEDENCE = 'relations.precedence_unresolved'
    INTERPRETATIONS = 'relations.interpretations_unresolved'


@dataclass(frozen=True, slots=True)
class RelationalDiagnostic:
    reason: RelationalReason
    relation_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RelationAwareReadinessEvaluation:
    """No combined candidate/ready flag: local checks and relational diagnostics differ.

    DISPLACED records an explicit incoming assertion, regardless of source
    admissibility. CONTEXT_ONLY means no target restriction diagnosed here, not
    permission to use/add the value. NOT_EVALUATED preserves unresolved precedence
    or source-admissibility questions rather than creating another selector.
    """
    observation_id: str
    persisted_eligibility: EconomicEligibility | None
    local: CandidacyEvaluation | None
    snapshot_integrity: SnapshotIntegrity
    relational_status: RelationalStatus
    diagnostics: tuple[RelationalDiagnostic, ...]
    contract: Literal['relation-aware-readiness/v1'] = 'relation-aware-readiness/v1'
