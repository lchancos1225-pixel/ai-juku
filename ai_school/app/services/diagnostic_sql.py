"""
PostgreSQL recursive-CTE SQL definitions for the prerequisite diagnostic engine.

This module centralizes all raw SQL strings used by
``prerequisite_diagnostic_service`` so they can be reviewed, fuzz-tested, and
explained in isolation. Every statement here is intentionally written for
PostgreSQL only — the recursive CTE relies on ``ARRAY`` cycle detection,
``DISTINCT ON``, and named parameters passed via SQLAlchemy ``text()``.

Conventions
-----------
* Bind parameters use ``:name`` style and are documented next to each query.
* No string interpolation of user-supplied values is permitted; the service
  layer must always pass values as bound parameters.
* Each statement is idempotent and side-effect-free (read-only ``SELECT``).

The CTE design has three guard rails:

1. **Cycle detection** via ``path`` ``ARRAY[VARCHAR]`` accumulator and
   ``NOT (next = ANY(path))`` predicate — prevents infinite recursion if the
   ``unit_prerequisites`` graph ever contains a back-edge.
2. **Depth cap** via ``a.depth < :max_depth`` — bounds worst-case CTE width
   even when the graph is huge or accidentally fan-out heavy.
3. **Per-unit shortest-depth collapse** via ``DISTINCT ON (unit_id)`` —
   diamond DAGs (two parents reaching the same ancestor) collapse to a single
   row at the minimum depth, deterministically broken by descending
   ``path_weight`` then ascending ``unit_id``.

Mastery aggregation is folded into the same query via ``LEFT JOIN`` so the
caller never needs to issue follow-up round trips per node.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Existence probe for the target unit. Cheap, always run first so we can raise
# a precise "target not found" error before paying for the recursive CTE.
# ---------------------------------------------------------------------------
SQL_TARGET_EXISTS: str = """
SELECT 1
FROM unit_dependency
WHERE unit_id = :target_unit
LIMIT 1
""".strip()


# ---------------------------------------------------------------------------
# Statement-level guard rails applied per transaction. We set a tight
# statement_timeout to bound worst-case query time even on degenerate graphs
# and force a deterministic search_path.
#
# These are issued separately rather than embedded in the recursive query so
# they only affect the active transaction and do not leak across the pool.
# ---------------------------------------------------------------------------
# PostgreSQL utility commands cannot accept bind parameters, so the caller
# formats validated integer values directly. The service layer guarantees
# these are positive ints before any string formatting reaches this module.
SQL_SET_STATEMENT_TIMEOUT_TEMPLATE: str = "SET LOCAL statement_timeout = {timeout_ms:d}"
SQL_SET_LOCK_TIMEOUT_TEMPLATE: str = "SET LOCAL lock_timeout = {timeout_ms:d}"


# ---------------------------------------------------------------------------
# Core recursive CTE: prerequisite tree traversal + mastery aggregation.
#
# Bind parameters
# ---------------
# :target_unit         VARCHAR  — unit id whose prerequisites we explore
# :student_id          INTEGER  — student whose mastery we join
# :max_depth           INTEGER  — hard cap on recursion depth (>=1)
# :mastery_threshold   FLOAT    — mastery_score below this is considered weak
#
# Result columns
# --------------
# unit_id        : VARCHAR    — node identifier (target itself appears at depth 0)
# display_name   : VARCHAR    — denormalized for UI consumption
# depth          : INTEGER    — distance from target (0 = target)
# via_unit       : VARCHAR    — parent on the shortest path (NULL at depth 0)
# path           : VARCHAR[]  — full path from target to this node, used to
#                              reconstruct learning order without extra joins
# path_weight    : FLOAT      — multiplicative product of edge weights;
#                              tie-breaker for shortest-path collapse and
#                              future weighted-routing extensions
# mastery_score  : FLOAT      — 0.0 if the student has no mastery record
# correct_count  : INTEGER    — practice attempts answered correctly
# wrong_count    : INTEGER    — practice attempts answered incorrectly
# is_weak        : BOOLEAN    — mastery_score < :mastery_threshold
# ---------------------------------------------------------------------------
SQL_PREREQUISITE_TREE: str = """
WITH RECURSIVE
ancestors AS (
    -- Anchor: the target unit itself sits at depth 0 so callers can read
    -- the target's own mastery from the same result set.
    SELECT
        ud.unit_id                             AS unit_id,
        ud.display_name                        AS display_name,
        0                                      AS depth,
        ARRAY[ud.unit_id]::VARCHAR[]           AS path,
        CAST(NULL AS VARCHAR)                  AS via_unit,
        CAST(1.0 AS DOUBLE PRECISION)          AS path_weight
    FROM unit_dependency ud
    WHERE ud.unit_id = :target_unit

    UNION ALL

    -- Recursion: walk one prerequisite hop at a time. Cycle detection uses
    -- the accumulated path array; depth cap bounds runaway expansion.
    SELECT
        p.prerequisite_id                      AS unit_id,
        udp.display_name                       AS display_name,
        a.depth + 1                            AS depth,
        a.path || p.prerequisite_id            AS path,
        a.unit_id                              AS via_unit,
        a.path_weight * p.weight               AS path_weight
    FROM ancestors a
    JOIN unit_prerequisites p
        ON p.unit_id = a.unit_id
    JOIN unit_dependency udp
        ON udp.unit_id = p.prerequisite_id
    WHERE
        a.depth < :max_depth
        AND NOT (p.prerequisite_id = ANY(a.path))
),
shortest AS (
    -- Diamond DAGs: keep only the shortest depth per ancestor.
    -- Tie-break by larger path_weight then by unit_id for determinism.
    SELECT DISTINCT ON (unit_id)
        unit_id,
        display_name,
        depth,
        path,
        via_unit,
        path_weight
    FROM ancestors
    ORDER BY unit_id, depth ASC, path_weight DESC, via_unit NULLS FIRST
),
with_mastery AS (
    SELECT
        s.unit_id,
        s.display_name,
        s.depth,
        s.path,
        s.via_unit,
        s.path_weight,
        COALESCE(um.mastery_score, 0.0)        AS mastery_score,
        COALESCE(um.correct_count, 0)          AS correct_count,
        COALESCE(um.wrong_count, 0)            AS wrong_count,
        (COALESCE(um.mastery_score, 0.0) < :mastery_threshold) AS is_weak
    FROM shortest s
    LEFT JOIN unit_mastery um
        ON um.unit_id = s.unit_id
       AND um.student_id = :student_id
)
SELECT
    unit_id,
    display_name,
    depth,
    via_unit,
    path,
    path_weight,
    mastery_score,
    correct_count,
    wrong_count,
    is_weak
FROM with_mastery
ORDER BY depth ASC, path_weight DESC, unit_id ASC
""".strip()


# ---------------------------------------------------------------------------
# Single-row root-cause finder. Wraps the same recursive CTE but filters to
# weak ancestors (excluding the target itself) and returns the deepest weak
# node — i.e. the foundational unit the student should remediate first.
#
# Same bind parameters as SQL_PREREQUISITE_TREE.
# ---------------------------------------------------------------------------
SQL_ROOT_WEAKNESS: str = """
WITH RECURSIVE
ancestors AS (
    SELECT
        ud.unit_id                             AS unit_id,
        ud.display_name                        AS display_name,
        0                                      AS depth,
        ARRAY[ud.unit_id]::VARCHAR[]           AS path,
        CAST(NULL AS VARCHAR)                  AS via_unit,
        CAST(1.0 AS DOUBLE PRECISION)          AS path_weight
    FROM unit_dependency ud
    WHERE ud.unit_id = :target_unit

    UNION ALL

    SELECT
        p.prerequisite_id                      AS unit_id,
        udp.display_name                       AS display_name,
        a.depth + 1                            AS depth,
        a.path || p.prerequisite_id            AS path,
        a.unit_id                              AS via_unit,
        a.path_weight * p.weight               AS path_weight
    FROM ancestors a
    JOIN unit_prerequisites p
        ON p.unit_id = a.unit_id
    JOIN unit_dependency udp
        ON udp.unit_id = p.prerequisite_id
    WHERE
        a.depth < :max_depth
        AND NOT (p.prerequisite_id = ANY(a.path))
),
shortest AS (
    SELECT DISTINCT ON (unit_id)
        unit_id,
        display_name,
        depth,
        path,
        via_unit,
        path_weight
    FROM ancestors
    ORDER BY unit_id, depth ASC, path_weight DESC, via_unit NULLS FIRST
)
SELECT
    s.unit_id,
    s.display_name,
    s.depth,
    s.via_unit,
    s.path,
    s.path_weight,
    COALESCE(um.mastery_score, 0.0)        AS mastery_score,
    COALESCE(um.correct_count, 0)          AS correct_count,
    COALESCE(um.wrong_count, 0)            AS wrong_count,
    TRUE                                   AS is_weak
FROM shortest s
LEFT JOIN unit_mastery um
    ON um.unit_id = s.unit_id
   AND um.student_id = :student_id
WHERE s.unit_id <> :target_unit
  AND COALESCE(um.mastery_score, 0.0) < :mastery_threshold
ORDER BY s.depth DESC, s.path_weight DESC, s.unit_id ASC
LIMIT 1
""".strip()


__all__ = [
    "SQL_TARGET_EXISTS",
    "SQL_SET_STATEMENT_TIMEOUT_TEMPLATE",
    "SQL_SET_LOCK_TIMEOUT_TEMPLATE",
    "SQL_PREREQUISITE_TREE",
    "SQL_ROOT_WEAKNESS",
]
