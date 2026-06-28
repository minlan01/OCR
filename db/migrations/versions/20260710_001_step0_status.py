"""step0 原始素材预处理 — 空迁移

Revision ID: 20260710_001
Revises: 20260618_002

说明：步骤0 仅使用 EvidenceCase.metadata_ 和 EvidenceMaterial.metadata_ 的 JSONB 字段，
不涉及任何 DDL 变更（无新增表、无新增列、无索引变更）。
此空迁移仅用于标记版本链。
"""
from alembic import op

revision = "20260710_001"
down_revision = "20260618_002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # step0 仅用 metadata_ JSONB 字段，无 DDL
    pass


def downgrade() -> None:
    # 无 DDL 变更，无需回滚
    pass
