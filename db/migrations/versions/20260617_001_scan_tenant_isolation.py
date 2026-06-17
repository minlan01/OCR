"""SaaS tenant isolation: add tenant_id to scan_tasks and output_templates

Revision ID: 20260617_001
Revises: 20260616_002
- Add tenant_id column to scan_tasks (nullable for backward compat)
- Add index on scan_tasks.tenant_id
- Add tenant_id column to output_templates (nullable, null = global template)
- Add index on output_templates.tenant_id
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# ─── revision markers ───
revision = "20260617_001"
down_revision = "20260616_002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. scan_tasks 加 tenant_id
    op.add_column(
        "scan_tasks",
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="SET NULL"),
            nullable=True,
            comment="租户ID（SaaS隔离用，开发模式可为null）",
        ),
    )
    op.create_index("idx_scan_tasks_tenant_id", "scan_tasks", ["tenant_id"])

    # 2. output_templates 加 tenant_id（null 表示全局模板）
    op.add_column(
        "output_templates",
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="SET NULL"),
            nullable=True,
            comment="租户ID（SaaS隔离用，null表示全局模板）",
        ),
    )
    op.create_index("idx_output_templates_tenant_id", "output_templates", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("idx_output_templates_tenant_id", table_name="output_templates")
    op.drop_column("output_templates", "tenant_id")

    op.drop_index("idx_scan_tasks_tenant_id", table_name="scan_tasks")
    op.drop_column("scan_tasks", "tenant_id")
