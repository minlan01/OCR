"""Remove neonatal case type + add compensation_data field

Revision ID: 20260701_001
Revises: 20260605_001
- Migrate existing neonatal data to injury + is_minor
- Update CHECK constraints to remove neonatal
- Add compensation_data JSONB column to evidence_cases
"""
import sqlalchemy as sa
from alembic import op

# ─── revision markers ───
revision = "20260701_001"
down_revision = "20260605_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 迁移 neonatal 数据为 injury + is_minor
    op.execute(
        "UPDATE evidence_cases SET case_type='injury', is_minor=TRUE "
        "WHERE case_type='neonatal'"
    )

    # 2. 如果有 evidence_requirements 表也需要迁移
    op.execute(
        "UPDATE evidence_requirements SET case_type='injury', is_minor=TRUE "
        "WHERE case_type='neonatal'"
    )

    # 3. 更新 evidence_cases 的 case_type 约束（移除 neonatal，保留 injury + death）
    op.execute(
        "ALTER TABLE evidence_cases DROP CONSTRAINT IF EXISTS ck_evidence_cases_case_type"
    )
    op.execute(
        "ALTER TABLE evidence_cases ADD CONSTRAINT ck_evidence_cases_case_type "
        "CHECK (case_type IN ('injury','death'))"
    )

    # 4. 更新 evidence_requirements 的 case_type 约束（如果存在）
    op.execute(
        "ALTER TABLE evidence_requirements DROP CONSTRAINT IF EXISTS ck_evidence_requirements_case_type"
    )
    op.execute(
        "ALTER TABLE evidence_requirements ADD CONSTRAINT ck_evidence_requirements_case_type "
        "CHECK (case_type IN ('injury','death'))"
    )

    # 5. 更新 complaint_cases 的 case_type 约束（如果存在）
    op.execute(
        "ALTER TABLE complaint_cases DROP CONSTRAINT IF EXISTS ck_complaint_cases_case_type"
    )
    op.execute(
        "ALTER TABLE complaint_cases ADD CONSTRAINT ck_complaint_cases_case_type "
        "CHECK (case_type IN ('injury','death'))"
    )

    # 6. 新增 compensation_data 字段
    op.add_column(
        "evidence_cases",
        sa.Column("compensation_data", sa.JSON(), server_default="{}", nullable=False),
    )

    # 7. 删除旧的 neonatal 种子数据（已迁移为 injury）
    op.execute(
        "DELETE FROM evidence_requirements WHERE case_type = 'neonatal'"
    )


def downgrade() -> None:
    # 1. 删除 compensation_data 字段
    op.drop_column("evidence_cases", "compensation_data")

    # 2. 恢复约束包含 neonatal
    op.execute(
        "ALTER TABLE evidence_cases DROP CONSTRAINT IF EXISTS ck_evidence_cases_case_type"
    )
    op.execute(
        "ALTER TABLE evidence_cases ADD CONSTRAINT ck_evidence_cases_case_type "
        "CHECK (case_type IN ('injury','death','neonatal'))"
    )

    op.execute(
        "ALTER TABLE evidence_requirements DROP CONSTRAINT IF EXISTS ck_evidence_requirements_case_type"
    )
    op.execute(
        "ALTER TABLE evidence_requirements ADD CONSTRAINT ck_evidence_requirements_case_type "
        "CHECK (case_type IN ('injury','death','neonatal'))"
    )

    op.execute(
        "ALTER TABLE complaint_cases DROP CONSTRAINT IF EXISTS ck_complaint_cases_case_type"
    )
    op.execute(
        "ALTER TABLE complaint_cases ADD CONSTRAINT ck_complaint_cases_case_type "
        "CHECK (case_type IN ('injury','death','neonatal'))"
    )
