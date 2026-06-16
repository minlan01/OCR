"""SaaS tenant isolation: add tenant_id to evidence_cases

Revision ID: 20260616_002
Revises: 20260616_001
- Add tenant_id column to evidence_cases (nullable for backward compat)
- Add index on tenant_id
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# ─── revision markers ───
revision = "20260616_002"
down_revision = "20260616_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. evidence_cases 加 tenant_id
    op.add_column(
        "evidence_cases",
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="SET NULL"),
            nullable=True,
            comment="租户ID（SaaS隔离用，开发模式可为null）",
        ),
    )

    op.create_index("idx_evidence_cases_tenant_id", "evidence_cases", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("idx_evidence_cases_tenant_id", table_name="evidence_cases")
    op.drop_column("evidence_cases", "tenant_id")
