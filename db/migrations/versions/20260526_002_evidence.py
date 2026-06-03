"""add evidence slot and office file types

Revision ID: 20260526_002_evidence
Revises: 20260526_001_complaint
Create Date: 2026-05-26
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260526_002_evidence'
down_revision = '20260526_001_complaint'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE complaint_uploads DROP CONSTRAINT ck_complaint_uploads_slot"
    )
    op.execute(
        "ALTER TABLE complaint_uploads ADD CONSTRAINT ck_complaint_uploads_slot "
        "CHECK (slot IN ('plaintiff','guardian','defendant','fee','medical','appraisal','staff_error','evidence'))"
    )

    op.execute(
        "ALTER TABLE complaint_uploads DROP CONSTRAINT ck_complaint_uploads_file_type"
    )
    op.execute(
        "ALTER TABLE complaint_uploads ADD CONSTRAINT ck_complaint_uploads_file_type "
        "CHECK (file_type IN ('pdf','image','manual_input','docx','xlsx','pptx'))"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE complaint_uploads DROP CONSTRAINT ck_complaint_uploads_slot"
    )
    op.execute(
        "ALTER TABLE complaint_uploads ADD CONSTRAINT ck_complaint_uploads_slot "
        "CHECK (slot IN ('plaintiff','guardian','defendant','fee','medical','appraisal','staff_error'))"
    )

    op.execute(
        "ALTER TABLE complaint_uploads DROP CONSTRAINT ck_complaint_uploads_file_type"
    )
    op.execute(
        "ALTER TABLE complaint_uploads ADD CONSTRAINT ck_complaint_uploads_file_type "
        "CHECK (file_type IN ('pdf','image','manual_input'))"
    )
