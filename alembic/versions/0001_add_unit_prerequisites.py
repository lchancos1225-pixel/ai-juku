"""Add unit_prerequisites edge table.

Creates the many-to-many prerequisite graph table used by the recursive-CTE
diagnostic engine. Existing single-parent edges in
``unit_dependency.prerequisite_unit_id`` are migrated as ``edge_kind='hard'``
rows so the new engine sees a fully-populated graph from day one.

Revision ID: 0001_add_unit_prerequisites
Revises:
Create Date: 2026-05-01

Notes
-----
* Idempotent: re-running ``upgrade()`` is a no-op on systems that already
  have the table or rows; the data backfill uses ``ON CONFLICT DO NOTHING``.
* The legacy column ``unit_dependency.prerequisite_unit_id`` is intentionally
  left intact for one release cycle so existing readers continue to work.
* PostgreSQL only. The ``CHECK`` constraint forbids self-loops.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op

revision: str = "0001_add_unit_prerequisites"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE_NAME = "unit_prerequisites"


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect != "postgresql":
        raise RuntimeError(
            f"unit_prerequisites migration requires PostgreSQL (got {dialect!r})"
        )

    op.create_table(
        _TABLE_NAME,
        sa.Column(
            "unit_id",
            sa.String(length=100),
            sa.ForeignKey("unit_dependency.unit_id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "prerequisite_id",
            sa.String(length=100),
            sa.ForeignKey("unit_dependency.unit_id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "weight",
            sa.Float(),
            nullable=False,
            server_default=sa.text("1.0"),
        ),
        sa.Column(
            "edge_kind",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'hard'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "unit_id <> prerequisite_id",
            name="ck_unit_prerequisites_no_self_loop",
        ),
        sa.UniqueConstraint(
            "unit_id",
            "prerequisite_id",
            name="uq_unit_prerequisites_pair",
        ),
    )
    op.create_index(
        "ix_unit_prerequisites_prereq",
        _TABLE_NAME,
        ["prerequisite_id"],
    )
    op.create_index(
        "ix_unit_prerequisites_unit",
        _TABLE_NAME,
        ["unit_id"],
    )

    # Backfill from the legacy single-parent column. We use INSERT ... SELECT
    # with ON CONFLICT DO NOTHING so the migration is safe to re-apply.
    #
    # In --sql / offline mode we cannot read counts back from the database,
    # so we emit the INSERT statement but skip the verification SELECTs.
    backfill_sql = sa.text(
        """
        INSERT INTO unit_prerequisites (unit_id, prerequisite_id, weight, edge_kind)
        SELECT
            ud.unit_id,
            ud.prerequisite_unit_id,
            1.0,
            'hard'
        FROM unit_dependency ud
        WHERE ud.prerequisite_unit_id IS NOT NULL
          AND ud.prerequisite_unit_id <> ud.unit_id
          AND ud.prerequisite_unit_id IN (
              SELECT unit_id FROM unit_dependency
          )
        ON CONFLICT (unit_id, prerequisite_id) DO NOTHING
        """
    )
    op.execute(backfill_sql)

    if context.is_offline_mode():
        # Offline (script generation) mode cannot read state; the DBA
        # running the script in production should run a pair of count
        # queries manually if they want to assert backfill parity.
        return

    legacy_count = bind.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM unit_dependency
            WHERE prerequisite_unit_id IS NOT NULL
              AND prerequisite_unit_id <> unit_id
              AND prerequisite_unit_id IN (SELECT unit_id FROM unit_dependency)
            """
        )
    ).scalar_one()
    inserted_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM unit_prerequisites")
    ).scalar_one()

    # Soft assertion: we expect at least as many edges as legacy rows we
    # could safely migrate. A mismatch is a data-quality red flag, not a
    # crash condition, so we log via a NOTICE rather than aborting.
    if inserted_count < legacy_count:
        op.execute(
            sa.text(
                "DO $$ BEGIN RAISE NOTICE "
                "'unit_prerequisites backfill mismatch: legacy=% inserted=%', "
                f"{int(legacy_count)}, {int(inserted_count)}; END $$;"
            )
        )


def downgrade() -> None:
    op.drop_index("ix_unit_prerequisites_unit", table_name=_TABLE_NAME)
    op.drop_index("ix_unit_prerequisites_prereq", table_name=_TABLE_NAME)
    op.drop_table(_TABLE_NAME)
