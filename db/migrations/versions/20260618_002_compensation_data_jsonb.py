"""Align compensation_data column type to JSONB

Revision ID: 20260618_002
Revises: 20260618_001

修复 P3 残留问题：
- evidence_cases.compensation_data 在 20260701_001 用 sa.JSON() 创建，对应 PostgreSQL 的 json 类型；
  而 ORM 模型 (db/models_evidence.py:63) 使用 JSONB。
- alembic autogenerate 会持续报告类型差异，并且 json 类型查询性能比 JSONB 差。
- 此迁移将类型对齐为 JSONB（如果当前是 json）。

幂等：通过 information_schema 检查当前类型，仅在不为 jsonb 时执行 ALTER。
"""
import sqlalchemy as sa
from alembic import op

revision = "20260618_002"
down_revision = "20260618_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # 检查表是否存在（如果 evidence_cases 表都没建，跳过）
    table_exists = bind.execute(sa.text(
        "SELECT 1 FROM information_schema.tables WHERE table_name='evidence_cases'"
    )).scalar()
    if not table_exists:
        return

    # 检查当前列类型
    current_type = bind.execute(sa.text(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name='evidence_cases' AND column_name='compensation_data'"
    )).scalar()

    if current_type and current_type.lower() == "json":
        # ALTER 为 jsonb
        op.execute(
            "ALTER TABLE evidence_cases "
            "ALTER COLUMN compensation_data TYPE jsonb USING compensation_data::jsonb"
        )


def downgrade() -> None:
    # 不回滚（jsonb → json 会丢索引/性能，无意义）
    pass
