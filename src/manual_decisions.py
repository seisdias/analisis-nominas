"""Validate portable decisions and rebuild only into an exclusively new file.

No activation/swap, corpus ingestion or economic effect is implemented. Successful
validation is a snapshot result, not a lasting authorization after evidence changes.
Failed builds retain an unpopulated v7 file for inspection, never a publish result.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from src.canonical.decisions import decode_decisions
from src.persistence import open_database, verify_schema
from src.persistence.decisions import DecisionPreconditionConflict, DecisionRepository

__all__ = ['DecisionPreconditionConflict', 'import_decisions', 'rebuild_with_decisions']


@dataclass(frozen=True)
class ValidatedDecisions:
    decision_ids: tuple[str, ...]


def import_decisions(repository: DecisionRepository, portable: bytes) -> ValidatedDecisions:
    """All-or-nothing validation/registration; never apply stale decisions."""
    decisions = decode_decisions(portable)
    with repository.transaction():
        for decision in decisions:
            repository.register_decision(decision)
        # Existing decisions must remain valid too, not just the imported subset.
        for decision in repository.list_decisions():
            repository.validate_decision(decision)
        return ValidatedDecisions(tuple(item.decision_id for item in decisions))


@dataclass(frozen=True)
class RebuildResult:
    path: Path
    validated: ValidatedDecisions
    decisions_validated: bool = True


def rebuild_with_decisions(destination: Path, portable: bytes,
                           populate: Callable[[DecisionRepository], object], *,
                           application_revision: str = 'development') -> RebuildResult:
    """Caller supplies deterministic synthetic population; never opens a source DB.

    Exclusive creation rejects existing files/symlinks (including the source),
    avoiding a check-then-create overwrite. No automatic cleanup or activation.
    Population and decision replay commit together only after integrity succeeds.
    """
    decode_decisions(portable)  # Reject malformed exports before filesystem mutation.
    path = Path(destination)
    with path.open('xb'):
        pass
    with open_database(path, mode='create', application_revision=application_revision) as db:
        repository = DecisionRepository(db.connection)
        with repository.transaction():
            populate(repository)
            validated = import_decisions(repository, portable)
            verify_schema(db.connection)
    return RebuildResult(path, validated)
