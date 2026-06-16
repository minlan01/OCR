"""SaaS auth tables: tenants + users

Revision ID: 20260616_001
Revises: 20260701_001
- Create tenants table
- Create users table
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# ─── revision markers ───
revision = "20260616_001"
down_revision = "20260701_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 租户表
    op.create_table(
        "tenants",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("plan", sa.String(20), nullable=False, server_default="free"),
        sa.Column("max_cases", sa.Integer, nullable=False, server_default="20"),
        sa.Column("max_concurrent", sa.Integer, nullable=False, server_default="2"),
        sa.Column("storage_quota_mb", sa.Integer, nullable=False, server_default="2048"),
        sa.Column("storage_used_mb", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    op.execute(
        "ALTER TABLE tenants ADD CONSTRAINT ck_tenants_plan "
        "CHECK (plan IN ('free','pro','enterprise'))"
    )
    op.execute(
        "ALTER TABLE tenants ADD CONSTRAINT ck_tenants_status "
        "CHECK (status IN ('active','suspended'))"
    )

    op.create_index("idx_tenants_status", "tenants", ["status"])
    op.create_index("idx_tenants_plan", "tenants", ["plan"])

    # 2. 用户表
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(255)),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="member"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("TRUE")),
        sa.Column("last_login", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    op.execute(
        "ALTER TABLE users ADD CONSTRAINT ck_users_role "
        "CHECK (role IN ('super_admin','tenant_admin','member'))"
    )

    op.create_index("idx_users_tenant_id", "users", ["tenant_id"])
    op.create_index("idx_users_email", "users", ["email"], unique=True)
    op.create_index("idx_users_role", "users", ["role"])


def downgrade() -> None:
    op.drop_table("users")
    op.drop_table("tenants")
