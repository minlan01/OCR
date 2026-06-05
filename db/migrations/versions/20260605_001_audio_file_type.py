"""Add audio file type + not_applicable OCR status

Revision ID: 20260605_001
"""
from alembic import op

# ─── revision markers ───
revision = "20260605_001"
down_revision = "20260602_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 放宽 evidence_materials file_type CHECK 约束：加入 'audio'
    op.execute(
        "ALTER TABLE evidence_materials DROP CONSTRAINT IF EXISTS ck_evidence_materials_file_type"
    )
    op.execute(
        "ALTER TABLE evidence_materials ADD CONSTRAINT ck_evidence_materials_file_type "
        "CHECK (file_type IN ('pdf','image','docx','xlsx','audio','other'))"
    )

    # 2. 放宽 evidence_materials ocr_status CHECK 约束：加入 'not_applicable'
    op.execute(
        "ALTER TABLE evidence_materials DROP CONSTRAINT IF EXISTS ck_evidence_materials_ocr_status"
    )
    op.execute(
        "ALTER TABLE evidence_materials ADD CONSTRAINT ck_evidence_materials_ocr_status "
        "CHECK (ocr_status IN ('pending','processing','completed','failed','skipped','not_applicable'))"
    )


def downgrade() -> None:
    # 恢复原 CHECK（仅理论上使用，生产不下调）
    op.execute(
        "ALTER TABLE evidence_materials DROP CONSTRAINT IF EXISTS ck_evidence_materials_ocr_status"
    )
    op.execute(
        "ALTER TABLE evidence_materials ADD CONSTRAINT ck_evidence_materials_ocr_status "
        "CHECK (ocr_status IN ('pending','processing','completed','failed','skipped'))"
    )

    op.execute(
        "ALTER TABLE evidence_materials DROP CONSTRAINT IF EXISTS ck_evidence_materials_file_type"
    )
    op.execute(
        "ALTER TABLE evidence_materials ADD CONSTRAINT ck_evidence_materials_file_type "
        "CHECK (file_type IN ('pdf','image','docx','xlsx','other'))"
    )
