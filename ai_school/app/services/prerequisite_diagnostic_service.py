"""
Prerequisite diagnostic service: PostgreSQL-backed, production-grade.

Given a student and a target unit, this module identifies the minimal,
shortest-path remediation route that brings the student from their root
weakness up to the target unit, using a single recursive-CTE round trip to
PostgreSQL. The implementation is intentionally exhaustive in its handling
of error conditions because the engine is on the critical path of every
diagnostic flow and must never stall, leak, or surface partial data.

Public API
----------
* :class:`PrerequisiteNode`
* :func:`collect_prerequisite_tree`
* :func:`find_root_weakness`
* :func:`build_shortest_remediation_path`

Errors
------
* :class:`DiagnosticServiceError`           — base class
* :class:`TargetUnitNotFoundError`          — :target_unit is unknown
* :class:`PrerequisiteGraphError`           — graph invariant violated
* :class:`DatabaseDialectError`             — non-PostgreSQL connection
* :class:`DiagnosticTimeoutError`           — statement_timeout exceeded
* :class:`DiagnosticTransientError`         — transient DB failure that
                                               survived the retry budget

Design notes
------------
* Every public function is **read-only**: it never writes, never commits,
  never mutates session state beyond opening / closing a SAVEPOINT for the
  ``SET LOCAL`` knobs.
* All SQL lives in :mod:`diagnostic_sql` so the service body contains no
  string-SQL surface area.
* Retries apply *only* to transient SQLAlchemy ``OperationalError`` /
  ``DBAPIError`` instances — logical errors raised by us are never retried.
* Structured log records follow a single ``logger.info`` call per request
  with stable keys so they can be ingested by downstream observability
  pipelines without a parser change.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Final, Iterable, Mapping, Sequence

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.exc import DBAPIError, OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from .diagnostic_sql import (
    SQL_PREREQUISITE_TREE,
    SQL_ROOT_WEAKNESS,
    SQL_SET_LOCK_TIMEOUT_TEMPLATE,
    SQL_SET_STATEMENT_TIMEOUT_TEMPLATE,
    SQL_TARGET_EXISTS,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tunables. Exposed as module-level constants so they can be monkey-patched
# in tests and overridden in deployment-specific bootstraps without touching
# function signatures.
# ---------------------------------------------------------------------------
DEFAULT_MAX_DEPTH: Final[int] = 8
DEFAULT_MASTERY_THRESHOLD: Final[float] = 0.55
HARD_MAX_DEPTH: Final[int] = 32
HARD_MIN_DEPTH: Final[int] = 1
DEFAULT_STATEMENT_TIMEOUT_MS: Final[int] = 2_000
DEFAULT_LOCK_TIMEOUT_MS: Final[int] = 1_000
RETRY_ATTEMPTS: Final[int] = 2  # total tries = RETRY_ATTEMPTS + 1 initial
RETRY_BASE_BACKOFF_SEC: Final[float] = 0.05
RETRY_MAX_BACKOFF_SEC: Final[float] = 0.5

# Allowed character set for unit identifiers. We sanitize at the service
# boundary so callers cannot smuggle whitespace, NULs, or control characters
# even though we never interpolate into SQL — defense in depth.
_UNIT_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_\-]{1,100}$")

# PostgreSQL transient error SQLSTATE prefixes/codes we are willing to retry.
# Class 08 = connection exception, Class 40 = transaction rollback, plus a
# small set of explicit codes for serialization issues and admin shutdowns.
_RETRYABLE_SQLSTATE_PREFIXES: Final[tuple[str, ...]] = ("08", "40")
_RETRYABLE_SQLSTATE_CODES: Final[frozenset[str]] = frozenset({
    "53300",  # too_many_connections
    "57P01",  # admin_shutdown
    "57P02",  # crash_shutdown
    "57P03",  # cannot_connect_now
})
_TIMEOUT_SQLSTATE_CODES: Final[frozenset[str]] = frozenset({
    "57014",  # query_canceled (typically statement_timeout)
})


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class DiagnosticServiceError(Exception):
    """Base error for all prerequisite diagnostic failures."""


class TargetUnitNotFoundError(DiagnosticServiceError):
    """Raised when the supplied target unit id does not exist."""

    def __init__(self, target_unit_id: str) -> None:
        super().__init__(f"target unit not found: {target_unit_id!r}")
        self.target_unit_id = target_unit_id


class PrerequisiteGraphError(DiagnosticServiceError):
    """Raised when the recursive CTE returns rows that violate invariants."""


class DatabaseDialectError(DiagnosticServiceError):
    """Raised when the bound database is not PostgreSQL."""

    def __init__(self, dialect_name: str) -> None:
        super().__init__(
            "prerequisite diagnostic service requires PostgreSQL "
            f"(connected dialect: {dialect_name!r})"
        )
        self.dialect_name = dialect_name


class DiagnosticTimeoutError(DiagnosticServiceError):
    """Raised when the recursive query exceeds statement_timeout."""


class DiagnosticTransientError(DiagnosticServiceError):
    """Raised when a transient DB error survives the retry budget."""


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class PrerequisiteNode:
    """A single node in the prerequisite tree, fully self-describing.

    Invariants (enforced by :func:`_assert_invariants`):

    * ``depth >= 0``
    * ``len(path) == depth + 1``
    * ``path[-1] == unit_id``
    * ``via_unit`` is ``None`` iff ``depth == 0``
    * ``mastery_score`` is in ``[0.0, 1.0]``
    * ``is_weak == (mastery_score < threshold_used_at_query_time)``
      — the threshold itself is not stored on the node; callers that need to
      reason about it should pass the same threshold they used for the query.
    """

    unit_id: str
    display_name: str
    depth: int
    via_unit: str | None
    path: tuple[str, ...]
    path_weight: float
    mastery_score: float
    correct_count: int
    wrong_count: int
    is_weak: bool

    @classmethod
    def from_row(cls, row: Row) -> "PrerequisiteNode":
        """Build a node from a SQLAlchemy ``Row`` returned by the CTE."""
        m = row._mapping
        raw_path = m["path"]
        # PostgreSQL ARRAY comes back as a Python list. Defend against drivers
        # that return tuples or NULL by normalizing here.
        if raw_path is None:
            raw_path_tuple: tuple[str, ...] = ()
        else:
            raw_path_tuple = tuple(str(p) for p in raw_path)
        return cls(
            unit_id=str(m["unit_id"]),
            display_name=str(m["display_name"]),
            depth=int(m["depth"]),
            via_unit=None if m["via_unit"] is None else str(m["via_unit"]),
            path=raw_path_tuple,
            path_weight=float(m["path_weight"]),
            mastery_score=float(m["mastery_score"]),
            correct_count=int(m["correct_count"]),
            wrong_count=int(m["wrong_count"]),
            is_weak=bool(m["is_weak"]),
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class _QueryParams:
    student_id: int
    target_unit_id: str
    max_depth: int
    mastery_threshold: float
    statement_timeout_ms: int
    lock_timeout_ms: int


def _validate_inputs(
    *,
    student_id: int,
    target_unit_id: str,
    max_depth: int,
    mastery_threshold: float,
    statement_timeout_ms: int,
    lock_timeout_ms: int,
) -> _QueryParams:
    """Strict validation of every public-API argument.

    We do this *before* opening any DB resource so misuse never reaches the
    cluster. Each violation raises a precise :class:`ValueError` whose
    message is safe to bubble to API clients.
    """
    if not isinstance(student_id, int) or isinstance(student_id, bool):
        raise ValueError("student_id must be int")
    if student_id <= 0:
        raise ValueError(f"student_id must be positive, got {student_id}")

    if not isinstance(target_unit_id, str):
        raise ValueError("target_unit_id must be str")
    if not target_unit_id:
        raise ValueError("target_unit_id must be non-empty")
    if not _UNIT_ID_PATTERN.match(target_unit_id):
        raise ValueError(
            "target_unit_id contains disallowed characters or exceeds 100 chars"
        )

    if not isinstance(max_depth, int) or isinstance(max_depth, bool):
        raise ValueError("max_depth must be int")
    if max_depth < HARD_MIN_DEPTH or max_depth > HARD_MAX_DEPTH:
        raise ValueError(
            f"max_depth must be in [{HARD_MIN_DEPTH}, {HARD_MAX_DEPTH}], "
            f"got {max_depth}"
        )

    if not isinstance(mastery_threshold, (int, float)) or isinstance(
        mastery_threshold, bool
    ):
        raise ValueError("mastery_threshold must be numeric")
    if not (0.0 <= float(mastery_threshold) <= 1.0):
        raise ValueError(
            f"mastery_threshold must be within [0.0, 1.0], got {mastery_threshold}"
        )

    if not isinstance(statement_timeout_ms, int) or statement_timeout_ms <= 0:
        raise ValueError("statement_timeout_ms must be a positive int")
    if not isinstance(lock_timeout_ms, int) or lock_timeout_ms <= 0:
        raise ValueError("lock_timeout_ms must be a positive int")

    return _QueryParams(
        student_id=student_id,
        target_unit_id=target_unit_id,
        max_depth=max_depth,
        mastery_threshold=float(mastery_threshold),
        statement_timeout_ms=statement_timeout_ms,
        lock_timeout_ms=lock_timeout_ms,
    )


def _ensure_postgres(db: Session) -> None:
    """Refuse to run on non-PostgreSQL connections.

    We never execute the recursive CTE on SQLite / MySQL because they lack
    the array-cycle-detection idiom we depend on.
    """
    bind = db.get_bind()
    dialect_name = getattr(getattr(bind, "dialect", None), "name", "") or ""
    if dialect_name != "postgresql":
        raise DatabaseDialectError(dialect_name)


def _classify_dbapi_error(err: BaseException) -> str:
    """Map a SQLAlchemy DB error onto one of: ``timeout``, ``transient``,
    or ``fatal``.

    Inspection prefers the SQLSTATE code (``orig.pgcode`` for psycopg /
    psycopg2) and falls back to message substring sniffing only as a last
    resort, since substrings are driver-specific.
    """
    pgcode: str | None = None
    orig = getattr(err, "orig", None)
    if orig is not None:
        pgcode = getattr(orig, "pgcode", None) or getattr(orig, "sqlstate", None)
    if pgcode:
        if pgcode in _TIMEOUT_SQLSTATE_CODES:
            return "timeout"
        if pgcode in _RETRYABLE_SQLSTATE_CODES:
            return "transient"
        if any(pgcode.startswith(p) for p in _RETRYABLE_SQLSTATE_PREFIXES):
            return "transient"
        return "fatal"

    # Best-effort fallback when the driver does not surface SQLSTATE.
    msg = str(err).lower()
    if "statement timeout" in msg or "canceling statement" in msg:
        return "timeout"
    if isinstance(err, OperationalError):
        return "transient"
    return "fatal"


def _backoff_delay(attempt_index: int) -> float:
    """Exponential backoff capped at :data:`RETRY_MAX_BACKOFF_SEC`."""
    delay = RETRY_BASE_BACKOFF_SEC * (2 ** attempt_index)
    return min(delay, RETRY_MAX_BACKOFF_SEC)


def _apply_session_timeouts(db: Session, params: _QueryParams) -> None:
    """Bound the recursive query at the transaction level.

    ``SET LOCAL`` only affects the current transaction, so we never leak
    timeouts across connection-pool checkouts.
    """
    # ``SET LOCAL`` does not accept bind parameters in PostgreSQL, so we
    # format validated *integers* directly. ``_validate_inputs`` guarantees
    # both values are strictly positive ``int`` instances, eliminating any
    # injection surface.
    assert isinstance(params.statement_timeout_ms, int)
    assert isinstance(params.lock_timeout_ms, int)
    db.execute(
        text(
            SQL_SET_STATEMENT_TIMEOUT_TEMPLATE.format(
                timeout_ms=params.statement_timeout_ms
            )
        )
    )
    db.execute(
        text(
            SQL_SET_LOCK_TIMEOUT_TEMPLATE.format(
                timeout_ms=params.lock_timeout_ms
            )
        )
    )


def _check_target_exists(db: Session, params: _QueryParams) -> None:
    """Probe ``unit_dependency`` so we can raise a precise error before
    paying for the recursive CTE."""
    row = db.execute(
        text(SQL_TARGET_EXISTS),
        {"target_unit": params.target_unit_id},
    ).first()
    if row is None:
        raise TargetUnitNotFoundError(params.target_unit_id)


def _assert_invariants(node: PrerequisiteNode) -> None:
    """Defensive postconditions on every CTE row.

    These can only fire if the graph data or driver behavior is corrupt.
    A single failure raises :class:`PrerequisiteGraphError` so the caller
    sees an explicit, actionable failure instead of silently wrong data.
    """
    if node.depth < 0:
        raise PrerequisiteGraphError(
            f"negative depth {node.depth} for unit {node.unit_id!r}"
        )
    if len(node.path) != node.depth + 1:
        raise PrerequisiteGraphError(
            f"path/depth mismatch for unit {node.unit_id!r}: "
            f"depth={node.depth} path_len={len(node.path)}"
        )
    if not node.path or node.path[-1] != node.unit_id:
        raise PrerequisiteGraphError(
            f"path tail does not match unit_id {node.unit_id!r}: path={node.path}"
        )
    if (node.depth == 0) != (node.via_unit is None):
        raise PrerequisiteGraphError(
            f"via_unit/depth contradiction for unit {node.unit_id!r}: "
            f"depth={node.depth} via_unit={node.via_unit!r}"
        )
    if not (0.0 <= node.mastery_score <= 1.0):
        raise PrerequisiteGraphError(
            f"mastery_score out of range for unit {node.unit_id!r}: "
            f"{node.mastery_score}"
        )


def _run_query_attempt(
    db: Session,
    params: _QueryParams,
    sql: str,
    bindings: Mapping[str, object],
) -> Sequence[Row]:
    """Execute one full attempt: SAVEPOINT, SET LOCAL, target probe, query.

    The SAVEPOINT is scoped to this single attempt so that a transient
    error rolls back cleanly and the next attempt starts from a known-good
    transaction state. The outer caller chooses whether to retry.
    """
    nested = db.begin_nested()
    try:
        _apply_session_timeouts(db, params)
        _check_target_exists(db, params)
        result = db.execute(text(sql), dict(bindings))
        rows = result.fetchall()
        nested.commit()
        return rows
    except BaseException:
        # rollback() is safe even if the savepoint is already deactivated by
        # the in-flight exception; SQLAlchemy treats the no-op gracefully.
        try:
            if nested.is_active:
                nested.rollback()
        except SQLAlchemyError:  # pragma: no cover — defensive
            logger.exception("prerequisite_diagnostic.savepoint_rollback_failed")
        raise


def _run_with_retry(
    db: Session,
    params: _QueryParams,
    sql: str,
    bindings: Mapping[str, object],
    *,
    op_name: str,
) -> Sequence[Row]:
    """Wrap :func:`_run_query_attempt` with bounded retry on transient errors.

    Retries are budget-capped at :data:`RETRY_ATTEMPTS` and only triggered for
    SQLSTATE classes / codes classified as transient. Logical exceptions
    raised by us (``DiagnosticServiceError`` and subclasses, ``ValueError``)
    are never retried.
    """
    last_exc: BaseException | None = None
    for attempt in range(RETRY_ATTEMPTS + 1):
        try:
            return _run_query_attempt(db, params, sql, bindings)
        except DiagnosticServiceError:
            # Logical errors (e.g. TargetUnitNotFoundError) skip the retry
            # loop entirely.
            raise
        except DBAPIError as exc:
            kind = _classify_dbapi_error(exc)
            last_exc = exc
            if kind == "timeout":
                logger.warning(
                    "prerequisite_diagnostic.timeout op=%s attempt=%d",
                    op_name,
                    attempt,
                )
                raise DiagnosticTimeoutError(
                    f"{op_name} exceeded statement_timeout"
                ) from exc
            if kind == "transient" and attempt < RETRY_ATTEMPTS:
                delay = _backoff_delay(attempt)
                logger.warning(
                    "prerequisite_diagnostic.retry op=%s attempt=%d "
                    "delay_sec=%.3f sqlstate=%s",
                    op_name,
                    attempt,
                    delay,
                    getattr(getattr(exc, "orig", None), "pgcode", None),
                )
                time.sleep(delay)
                continue
            raise DiagnosticTransientError(
                f"{op_name} failed: {exc.__class__.__name__}"
            ) from exc
    raise DiagnosticTransientError(
        f"{op_name} retry budget exhausted"
    ) from last_exc


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def collect_prerequisite_tree(
    db: Session,
    *,
    student_id: int,
    target_unit_id: str,
    max_depth: int = DEFAULT_MAX_DEPTH,
    mastery_threshold: float = DEFAULT_MASTERY_THRESHOLD,
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
    lock_timeout_ms: int = DEFAULT_LOCK_TIMEOUT_MS,
) -> list[PrerequisiteNode]:
    """Return the prerequisite tree rooted at ``target_unit_id``.

    The list is sorted by ``depth ASC, path_weight DESC, unit_id ASC`` and
    contains the target itself at depth 0. Mastery columns reflect the
    student's current ``unit_mastery`` rows; missing rows resolve to 0.0.

    Raises
    ------
    ValueError
        On invalid inputs.
    DatabaseDialectError
        If the bound DB is not PostgreSQL.
    TargetUnitNotFoundError
        If ``target_unit_id`` does not exist in ``unit_dependency``.
    PrerequisiteGraphError
        If the result violates documented invariants.
    DiagnosticTimeoutError
        If the recursive CTE exceeds ``statement_timeout_ms``.
    DiagnosticTransientError
        If transient DB errors survive the retry budget.
    """
    params = _validate_inputs(
        student_id=student_id,
        target_unit_id=target_unit_id,
        max_depth=max_depth,
        mastery_threshold=mastery_threshold,
        statement_timeout_ms=statement_timeout_ms,
        lock_timeout_ms=lock_timeout_ms,
    )
    _ensure_postgres(db)

    started_at = time.perf_counter()
    rows = _run_with_retry(
        db,
        params,
        SQL_PREREQUISITE_TREE,
        {
            "target_unit": params.target_unit_id,
            "student_id": params.student_id,
            "max_depth": params.max_depth,
            "mastery_threshold": params.mastery_threshold,
        },
        op_name="collect_prerequisite_tree",
    )

    nodes: list[PrerequisiteNode] = []
    truncation_warned = False
    for row in rows:
        node = PrerequisiteNode.from_row(row)
        _assert_invariants(node)
        if node.depth >= params.max_depth and not truncation_warned:
            # The CTE caps recursion at max_depth, so any node *at* the cap
            # may have unexplored ancestors. Surface this once per call.
            logger.warning(
                "prerequisite_diagnostic.possible_truncation "
                "student_id=%d target=%s max_depth=%d",
                params.student_id,
                params.target_unit_id,
                params.max_depth,
            )
            truncation_warned = True
        nodes.append(node)

    # Defensive: the anchor row must always exist when target was found.
    if not nodes:
        raise PrerequisiteGraphError(
            "recursive CTE returned no rows despite target existence"
        )
    if nodes[0].depth != 0 or nodes[0].unit_id != params.target_unit_id:
        raise PrerequisiteGraphError(
            "first row of CTE result is not the target anchor"
        )

    elapsed_ms = (time.perf_counter() - started_at) * 1000.0
    weak_count = sum(1 for n in nodes if n.is_weak)
    max_seen = max((n.depth for n in nodes), default=0)
    logger.info(
        "prerequisite_diagnostic.tree "
        "student_id=%d target=%s nodes=%d weak=%d "
        "max_depth_seen=%d max_depth_cap=%d threshold=%.3f elapsed_ms=%.2f",
        params.student_id,
        params.target_unit_id,
        len(nodes),
        weak_count,
        max_seen,
        params.max_depth,
        params.mastery_threshold,
        elapsed_ms,
    )
    return nodes


def find_root_weakness(
    db: Session,
    *,
    student_id: int,
    target_unit_id: str,
    max_depth: int = DEFAULT_MAX_DEPTH,
    mastery_threshold: float = DEFAULT_MASTERY_THRESHOLD,
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
    lock_timeout_ms: int = DEFAULT_LOCK_TIMEOUT_MS,
) -> PrerequisiteNode | None:
    """Return the deepest weak ancestor, or ``None`` if the foundation is solid.

    The "deepest" rule means: the prerequisite the student should remediate
    first, because everything closer to the target depends on it. Ties at
    the same depth are broken by descending ``path_weight`` (more central
    edges win) then by ascending ``unit_id`` for determinism.
    """
    params = _validate_inputs(
        student_id=student_id,
        target_unit_id=target_unit_id,
        max_depth=max_depth,
        mastery_threshold=mastery_threshold,
        statement_timeout_ms=statement_timeout_ms,
        lock_timeout_ms=lock_timeout_ms,
    )
    _ensure_postgres(db)

    started_at = time.perf_counter()
    rows = _run_with_retry(
        db,
        params,
        SQL_ROOT_WEAKNESS,
        {
            "target_unit": params.target_unit_id,
            "student_id": params.student_id,
            "max_depth": params.max_depth,
            "mastery_threshold": params.mastery_threshold,
        },
        op_name="find_root_weakness",
    )

    elapsed_ms = (time.perf_counter() - started_at) * 1000.0
    if not rows:
        logger.info(
            "prerequisite_diagnostic.root_weakness student_id=%d target=%s "
            "result=none elapsed_ms=%.2f",
            params.student_id,
            params.target_unit_id,
            elapsed_ms,
        )
        return None

    node = PrerequisiteNode.from_row(rows[0])
    _assert_invariants(node)
    if node.unit_id == params.target_unit_id or node.depth == 0:
        # Should be impossible given the WHERE clause, but enforce here so
        # the contract is checkable from the calling site.
        raise PrerequisiteGraphError(
            "root weakness must be a strict ancestor of target"
        )

    logger.info(
        "prerequisite_diagnostic.root_weakness student_id=%d target=%s "
        "result=%s depth=%d mastery=%.3f elapsed_ms=%.2f",
        params.student_id,
        params.target_unit_id,
        node.unit_id,
        node.depth,
        node.mastery_score,
        elapsed_ms,
    )
    return node


def build_shortest_remediation_path(
    db: Session,
    *,
    student_id: int,
    target_unit_id: str,
    max_depth: int = DEFAULT_MAX_DEPTH,
    mastery_threshold: float = DEFAULT_MASTERY_THRESHOLD,
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
    lock_timeout_ms: int = DEFAULT_LOCK_TIMEOUT_MS,
    weak_only: bool = False,
) -> list[PrerequisiteNode]:
    """Return the learning order from the root weakness up to the target.

    The list is in *learning order*: index 0 is the root weakness, the last
    element is ``target_unit_id``. If the target's foundations are solid,
    the returned list is empty (caller should advance the student straight
    to the target).

    Parameters
    ----------
    weak_only:
        If ``True``, only nodes with ``is_weak == True`` are kept (the
        target itself is also dropped if it is currently strong).
    """
    # We deliberately call the heavier ``collect_prerequisite_tree`` rather
    # than chaining two CTE round trips — its result already contains both
    # the path information and mastery aggregation, so a single query is
    # sufficient and the in-Python work is O(N).
    nodes = collect_prerequisite_tree(
        db,
        student_id=student_id,
        target_unit_id=target_unit_id,
        max_depth=max_depth,
        mastery_threshold=mastery_threshold,
        statement_timeout_ms=statement_timeout_ms,
        lock_timeout_ms=lock_timeout_ms,
    )

    by_unit: dict[str, PrerequisiteNode] = {n.unit_id: n for n in nodes}
    if len(by_unit) != len(nodes):  # pragma: no cover — defensive
        raise PrerequisiteGraphError(
            "duplicate unit_id rows in prerequisite tree"
        )

    target_node = by_unit.get(target_unit_id)
    if target_node is None:
        # Should be impossible since the anchor invariant was already checked.
        raise PrerequisiteGraphError(
            "target unit missing from collected tree"
        )

    weakest_ancestors = [
        n for n in nodes if n.is_weak and n.unit_id != target_unit_id
    ]
    if not weakest_ancestors:
        return []

    # Pick the deepest weakness deterministically (matches SQL_ROOT_WEAKNESS
    # ordering). Doing it in Python avoids a second round trip.
    weakest_ancestors.sort(
        key=lambda n: (-n.depth, -n.path_weight, n.unit_id)
    )
    root = weakest_ancestors[0]

    # ``root.path`` is recorded as [target, ..., root]. Reverse it so the
    # caller iterates in *learning order*: foundation first, target last.
    learning_order_ids: tuple[str, ...] = tuple(reversed(root.path))
    ordered: list[PrerequisiteNode] = []
    for unit_id in learning_order_ids:
        node = by_unit.get(unit_id)
        if node is None:
            raise PrerequisiteGraphError(
                f"path references unknown unit {unit_id!r}"
            )
        if weak_only and not node.is_weak:
            continue
        ordered.append(node)
    return ordered


__all__ = [
    "PrerequisiteNode",
    "DiagnosticServiceError",
    "TargetUnitNotFoundError",
    "PrerequisiteGraphError",
    "DatabaseDialectError",
    "DiagnosticTimeoutError",
    "DiagnosticTransientError",
    "DEFAULT_MAX_DEPTH",
    "DEFAULT_MASTERY_THRESHOLD",
    "DEFAULT_STATEMENT_TIMEOUT_MS",
    "DEFAULT_LOCK_TIMEOUT_MS",
    "HARD_MAX_DEPTH",
    "HARD_MIN_DEPTH",
    "RETRY_ATTEMPTS",
    "collect_prerequisite_tree",
    "find_root_weakness",
    "build_shortest_remediation_path",
]
