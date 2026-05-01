"""Integration tests for the prerequisite diagnostic service.

These tests require a live PostgreSQL instance. The connection string is read
from ``PG_TEST_DSN`` (e.g. ``postgresql+psycopg://user@localhost/ai_juku_test``).
If unset or unreachable, the entire integration suite is skipped — but pure
unit tests for input validation and dialect guarding still run against any
SQLAlchemy connection.

The integration tests build their own isolated schema (``unit_dependency``,
``unit_prerequisites``, ``unit_mastery``) inside a unique schema namespace
created per test session, so they do not depend on the application's
production migrations and never touch shared data.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Iterator
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from ai_school.app.services import prerequisite_diagnostic_service as pds
from ai_school.app.services.prerequisite_diagnostic_service import (
    DatabaseDialectError,
    DiagnosticTimeoutError,
    DiagnosticTransientError,
    PrerequisiteGraphError,
    PrerequisiteNode,
    TargetUnitNotFoundError,
    build_shortest_remediation_path,
    collect_prerequisite_tree,
    find_root_weakness,
)


# ---------------------------------------------------------------------------
# DSN discovery + skip plumbing
# ---------------------------------------------------------------------------
def _candidate_dsns() -> list[str]:
    explicit = os.getenv("PG_TEST_DSN", "").strip()
    if explicit:
        return [explicit]
    user = os.getenv("USER", "postgres")
    return [
        f"postgresql+psycopg://{user}@127.0.0.1:5432/postgres",
        f"postgresql+psycopg://{user}@localhost:5432/postgres",
        "postgresql+psycopg://postgres@127.0.0.1:5432/postgres",
    ]


def _try_create_engine() -> Engine | None:
    last_err: Exception | None = None
    for dsn in _candidate_dsns():
        try:
            eng = sa.create_engine(dsn, future=True, pool_pre_ping=True)
            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))
            return eng
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            continue
    if last_err is not None:
        logging.getLogger(__name__).info(
            "skipping PG integration tests: %s", last_err
        )
    return None


@pytest.fixture(scope="session")
def pg_engine() -> Iterator[Engine]:
    eng = _try_create_engine()
    if eng is None:
        pytest.skip("PostgreSQL not reachable for integration tests")
    yield eng
    eng.dispose()


@pytest.fixture(scope="function")
def pg_session(pg_engine: Engine) -> Iterator[Session]:
    """Spin up an isolated schema per test for full isolation.

    Each test gets a unique schema; tables are created fresh and dropped at
    teardown. The session's ``search_path`` is pinned to the schema so the
    service's unqualified table references resolve correctly.
    """
    schema = "diag_test_" + uuid.uuid4().hex[:8]
    with pg_engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        conn.execute(text(f'SET search_path TO "{schema}"'))
        conn.execute(
            text(
                """
                CREATE TABLE unit_dependency (
                    unit_id VARCHAR(100) PRIMARY KEY,
                    display_name VARCHAR(100) NOT NULL,
                    subject VARCHAR(30) NOT NULL DEFAULT 'math',
                    prerequisite_unit_id VARCHAR(100),
                    next_unit_id VARCHAR(100),
                    display_order INTEGER NOT NULL DEFAULT 0,
                    grade INTEGER,
                    intro_html TEXT,
                    lecture_steps_json TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE unit_prerequisites (
                    unit_id VARCHAR(100) NOT NULL
                        REFERENCES unit_dependency(unit_id) ON DELETE CASCADE,
                    prerequisite_id VARCHAR(100) NOT NULL
                        REFERENCES unit_dependency(unit_id) ON DELETE CASCADE,
                    weight DOUBLE PRECISION NOT NULL DEFAULT 1.0,
                    edge_kind VARCHAR(20) NOT NULL DEFAULT 'hard',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (unit_id, prerequisite_id),
                    CHECK (unit_id <> prerequisite_id)
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE unit_mastery (
                    student_id INTEGER NOT NULL,
                    unit_id VARCHAR(100) NOT NULL,
                    mastery_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
                    correct_count INTEGER NOT NULL DEFAULT 0,
                    wrong_count INTEGER NOT NULL DEFAULT 0,
                    hint_count INTEGER NOT NULL DEFAULT 0,
                    avg_elapsed_sec DOUBLE PRECISION NOT NULL DEFAULT 0.0,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (student_id, unit_id)
                )
                """
            )
        )

    Session_ = sessionmaker(bind=pg_engine, expire_on_commit=False, future=True)
    sess = Session_()
    # Pin search_path for every checkout-bound connection used by the session.
    @event.listens_for(sess.connection(), "begin")  # type: ignore[arg-type]
    def _set_search_path(conn):  # noqa: ANN001
        conn.exec_driver_sql(f'SET search_path TO "{schema}"')

    sess.execute(text(f'SET search_path TO "{schema}"'))
    sess.commit()
    try:
        yield sess
    finally:
        sess.close()
        with pg_engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


# ---------------------------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------------------------
def _seed_units(session: Session, units: list[tuple[str, str]]) -> None:
    for order, (uid, name) in enumerate(units):
        session.execute(
            text(
                "INSERT INTO unit_dependency (unit_id, display_name, display_order)"
                " VALUES (:u, :n, :o)"
            ),
            {"u": uid, "n": name, "o": order},
        )
    session.commit()


def _seed_edges(
    session: Session,
    edges: list[tuple[str, str]],
    *,
    weight: float = 1.0,
) -> None:
    for unit_id, prereq_id in edges:
        session.execute(
            text(
                "INSERT INTO unit_prerequisites"
                " (unit_id, prerequisite_id, weight)"
                " VALUES (:u, :p, :w)"
            ),
            {"u": unit_id, "p": prereq_id, "w": weight},
        )
    session.commit()


def _seed_mastery(
    session: Session, student_id: int, scores: dict[str, float]
) -> None:
    for uid, score in scores.items():
        session.execute(
            text(
                "INSERT INTO unit_mastery"
                " (student_id, unit_id, mastery_score, correct_count, wrong_count)"
                " VALUES (:s, :u, :m, :c, :w)"
                " ON CONFLICT (student_id, unit_id) DO UPDATE"
                "   SET mastery_score = EXCLUDED.mastery_score"
            ),
            {"s": student_id, "u": uid, "m": score, "c": 0, "w": 0},
        )
    session.commit()


# ---------------------------------------------------------------------------
# Pure unit tests (no PG required)
# ---------------------------------------------------------------------------
class _FakeBind:
    def __init__(self, name: str) -> None:
        class _D:
            pass

        self.dialect = _D()
        self.dialect.name = name


class _FakeSession:
    def __init__(self, dialect_name: str) -> None:
        self._bind = _FakeBind(dialect_name)

    def get_bind(self) -> _FakeBind:
        return self._bind


def test_dialect_guard_rejects_sqlite() -> None:
    fake = _FakeSession("sqlite")
    with pytest.raises(DatabaseDialectError) as exc_info:
        collect_prerequisite_tree(
            fake,  # type: ignore[arg-type]
            student_id=1,
            target_unit_id="math_a",
        )
    assert exc_info.value.dialect_name == "sqlite"


@pytest.mark.parametrize(
    "kwargs, message_fragment",
    [
        ({"student_id": 0, "target_unit_id": "u"}, "student_id"),
        ({"student_id": -1, "target_unit_id": "u"}, "student_id"),
        ({"student_id": 1, "target_unit_id": ""}, "non-empty"),
        ({"student_id": 1, "target_unit_id": "bad id with space"}, "disallowed"),
        ({"student_id": 1, "target_unit_id": "u", "max_depth": 0}, "max_depth"),
        ({"student_id": 1, "target_unit_id": "u", "max_depth": 999}, "max_depth"),
        (
            {"student_id": 1, "target_unit_id": "u", "mastery_threshold": -0.1},
            "mastery_threshold",
        ),
        (
            {"student_id": 1, "target_unit_id": "u", "mastery_threshold": 1.1},
            "mastery_threshold",
        ),
        (
            {"student_id": 1, "target_unit_id": "u", "statement_timeout_ms": 0},
            "statement_timeout_ms",
        ),
        (
            {"student_id": 1, "target_unit_id": "u", "lock_timeout_ms": -1},
            "lock_timeout_ms",
        ),
        ({"student_id": True, "target_unit_id": "u"}, "student_id"),
    ],
)
def test_input_validation_raises(kwargs: dict, message_fragment: str) -> None:
    fake = _FakeSession("postgresql")
    with pytest.raises(ValueError) as exc_info:
        collect_prerequisite_tree(fake, **kwargs)  # type: ignore[arg-type]
    assert message_fragment in str(exc_info.value)


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------
class TestLinearChain:
    """A → B → C → D, target = A. Expect depth 0..3."""

    def test_collect_full_tree(self, pg_session: Session) -> None:
        _seed_units(
            pg_session,
            [("a", "A"), ("b", "B"), ("c", "C"), ("d", "D")],
        )
        _seed_edges(
            pg_session,
            [("a", "b"), ("b", "c"), ("c", "d")],
        )
        _seed_mastery(
            pg_session, 1, {"a": 0.1, "b": 0.2, "c": 0.3, "d": 0.4}
        )

        nodes = collect_prerequisite_tree(
            pg_session, student_id=1, target_unit_id="a"
        )
        depths = {n.unit_id: n.depth for n in nodes}
        assert depths == {"a": 0, "b": 1, "c": 2, "d": 3}
        # Path tail equals unit_id; first row is the anchor.
        assert nodes[0].unit_id == "a"
        assert nodes[0].via_unit is None
        assert all(n.path[-1] == n.unit_id for n in nodes)

    def test_input_validation_within_integration(
        self, pg_session: Session
    ) -> None:
        with pytest.raises(ValueError):
            collect_prerequisite_tree(
                pg_session, student_id=1, target_unit_id=""
            )


class TestDiamondDAG:
    """A→B, A→C, B→D, C→D. Diamond: D reachable via two paths."""

    def test_d_collapsed_to_shortest_depth(self, pg_session: Session) -> None:
        _seed_units(
            pg_session,
            [("a", "A"), ("b", "B"), ("c", "C"), ("d", "D")],
        )
        _seed_edges(
            pg_session,
            [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")],
        )
        nodes = collect_prerequisite_tree(
            pg_session, student_id=1, target_unit_id="a"
        )
        d_rows = [n for n in nodes if n.unit_id == "d"]
        assert len(d_rows) == 1
        assert d_rows[0].depth == 2  # 1 hop from b OR c, both at depth 1


class TestCycleGuard:
    """Cycle A→B, B→A must not blow up the recursion."""

    def test_cycle_terminates(self, pg_session: Session) -> None:
        _seed_units(pg_session, [("a", "A"), ("b", "B")])
        _seed_edges(pg_session, [("a", "b"), ("b", "a")])

        nodes = collect_prerequisite_tree(
            pg_session, student_id=1, target_unit_id="a", max_depth=8
        )
        ids = sorted(n.unit_id for n in nodes)
        # Cycle is cut: each unit appears at most once in the shortest layer.
        assert ids == ["a", "b"]


class TestDepthCap:
    """A→B→C→D→E with max_depth=2 truncates and warns."""

    def test_truncation_warning(
        self, pg_session: Session, caplog: pytest.LogCaptureFixture
    ) -> None:
        _seed_units(
            pg_session,
            [("a", "A"), ("b", "B"), ("c", "C"), ("d", "D"), ("e", "E")],
        )
        _seed_edges(
            pg_session, [("a", "b"), ("b", "c"), ("c", "d"), ("d", "e")]
        )
        with caplog.at_level(
            logging.WARNING,
            logger="ai_school.app.services.prerequisite_diagnostic_service",
        ):
            nodes = collect_prerequisite_tree(
                pg_session, student_id=1, target_unit_id="a", max_depth=2
            )
        assert max(n.depth for n in nodes) == 2
        assert any(
            "possible_truncation" in rec.message for rec in caplog.records
        )


class TestUnlearnedDefaults:
    """Missing unit_mastery rows resolve to 0.0 / is_weak=True."""

    def test_missing_mastery_is_weak(self, pg_session: Session) -> None:
        _seed_units(pg_session, [("a", "A"), ("b", "B")])
        _seed_edges(pg_session, [("a", "b")])
        nodes = collect_prerequisite_tree(
            pg_session,
            student_id=42,
            target_unit_id="a",
            mastery_threshold=0.5,
        )
        for n in nodes:
            assert n.mastery_score == pytest.approx(0.0)
            assert n.is_weak is True


class TestRootWeakness:
    """All weak ⇒ root_weakness picks the deepest non-target ancestor."""

    def test_returns_deepest_weak_ancestor(self, pg_session: Session) -> None:
        _seed_units(
            pg_session,
            [("a", "A"), ("b", "B"), ("c", "C"), ("d", "D")],
        )
        _seed_edges(
            pg_session, [("a", "b"), ("b", "c"), ("c", "d")]
        )
        _seed_mastery(
            pg_session, 1, {"a": 0.0, "b": 0.0, "c": 0.0, "d": 0.0}
        )
        node = find_root_weakness(
            pg_session, student_id=1, target_unit_id="a"
        )
        assert node is not None
        assert node.unit_id == "d"
        assert node.depth == 3


class TestStrongFoundation:
    """All ancestors above threshold ⇒ remediation path is empty."""

    def test_path_empty_when_solid(self, pg_session: Session) -> None:
        _seed_units(pg_session, [("a", "A"), ("b", "B"), ("c", "C")])
        _seed_edges(pg_session, [("a", "b"), ("b", "c")])
        _seed_mastery(
            pg_session, 1, {"a": 0.9, "b": 0.9, "c": 0.9}
        )
        path = build_shortest_remediation_path(
            pg_session,
            student_id=1,
            target_unit_id="a",
            mastery_threshold=0.55,
        )
        assert path == []
        # And root_weakness reports None.
        assert (
            find_root_weakness(
                pg_session, student_id=1, target_unit_id="a"
            )
            is None
        )

    def test_remediation_path_orders_foundation_first(
        self, pg_session: Session
    ) -> None:
        _seed_units(
            pg_session,
            [("a", "A"), ("b", "B"), ("c", "C"), ("d", "D")],
        )
        _seed_edges(
            pg_session, [("a", "b"), ("b", "c"), ("c", "d")]
        )
        _seed_mastery(
            pg_session, 1, {"a": 0.9, "b": 0.9, "c": 0.1, "d": 0.1}
        )
        path = build_shortest_remediation_path(
            pg_session, student_id=1, target_unit_id="a"
        )
        ids = [n.unit_id for n in path]
        # Deepest weak = d. Path back to target a in learning order.
        assert ids == ["d", "c", "b", "a"]


class TestUnknownTarget:
    """Target unit absent from unit_dependency raises a precise error."""

    def test_target_not_found(self, pg_session: Session) -> None:
        _seed_units(pg_session, [("a", "A")])
        with pytest.raises(TargetUnitNotFoundError):
            collect_prerequisite_tree(
                pg_session, student_id=1, target_unit_id="ghost"
            )
        with pytest.raises(TargetUnitNotFoundError):
            find_root_weakness(
                pg_session, student_id=1, target_unit_id="ghost"
            )


class TestRetryBehavior:
    """Transient OperationalError retries; logical errors do not."""

    def test_transient_error_retries_then_succeeds(
        self, pg_session: Session
    ) -> None:
        _seed_units(pg_session, [("a", "A"), ("b", "B")])
        _seed_edges(pg_session, [("a", "b")])

        # Simulate one transient failure on the recursive query, then let
        # subsequent attempts hit the real DB. We patch ``Session.execute``
        # surgically and only intercept the recursive-CTE statement.
        call_log: list[int] = []
        real_execute = Session.execute

        class _FakeOrig:
            pgcode = "08006"  # connection_failure → retryable

        def flaky_execute(self, statement, *args, **kwargs):  # noqa: ANN001
            stmt_text = str(statement)
            if "WITH RECURSIVE" in stmt_text and not call_log:
                call_log.append(1)
                raise OperationalError(
                    statement="SELECT", params=None, orig=_FakeOrig()
                )
            return real_execute(self, statement, *args, **kwargs)

        # Disable the inter-attempt sleep so the test is fast.
        with patch.object(Session, "execute", flaky_execute), patch.object(
            pds, "RETRY_BASE_BACKOFF_SEC", 0.0
        ):
            nodes = collect_prerequisite_tree(
                pg_session, student_id=1, target_unit_id="a"
            )
        assert {n.unit_id for n in nodes} == {"a", "b"}
        assert call_log == [1]

    def test_fatal_error_not_retried(self, pg_session: Session) -> None:
        _seed_units(pg_session, [("a", "A")])

        class _FatalOrig:
            pgcode = "42P01"  # undefined_table → not retryable

        real_execute = Session.execute

        def fatal_execute(self, statement, *args, **kwargs):  # noqa: ANN001
            stmt_text = str(statement)
            if "WITH RECURSIVE" in stmt_text:
                raise OperationalError(
                    statement="SELECT", params=None, orig=_FatalOrig()
                )
            return real_execute(self, statement, *args, **kwargs)

        with patch.object(Session, "execute", fatal_execute):
            with pytest.raises(DiagnosticTransientError):
                collect_prerequisite_tree(
                    pg_session, student_id=1, target_unit_id="a"
                )

    def test_timeout_is_classified(self, pg_session: Session) -> None:
        _seed_units(pg_session, [("a", "A")])

        class _TimeoutOrig:
            pgcode = "57014"  # query_canceled

        real_execute = Session.execute

        def timeout_execute(self, statement, *args, **kwargs):  # noqa: ANN001
            stmt_text = str(statement)
            if "WITH RECURSIVE" in stmt_text:
                raise OperationalError(
                    statement="SELECT", params=None, orig=_TimeoutOrig()
                )
            return real_execute(self, statement, *args, **kwargs)

        with patch.object(Session, "execute", timeout_execute):
            with pytest.raises(DiagnosticTimeoutError):
                collect_prerequisite_tree(
                    pg_session, student_id=1, target_unit_id="a"
                )


class TestNodeInvariants:
    """Postcondition assertions reject corrupted rows."""

    def test_assert_invariants_catches_bad_node(self) -> None:
        bad = PrerequisiteNode(
            unit_id="x",
            display_name="X",
            depth=2,
            via_unit=None,  # contradicts depth>0
            path=("x", "y", "x"),
            path_weight=1.0,
            mastery_score=0.5,
            correct_count=0,
            wrong_count=0,
            is_weak=True,
        )
        with pytest.raises(PrerequisiteGraphError):
            pds._assert_invariants(bad)  # noqa: SLF001
