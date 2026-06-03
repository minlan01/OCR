"""add complaint tables

Revision ID: 20260526_001
Revises: 20260520_1155_8d050963af48
Create Date: 2026-05-26
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260526_001_complaint'
down_revision = '8d050963af48'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'complaint_cases',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('case_type', sa.String(20), nullable=False),
        sa.Column('is_minor', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('status', sa.String(30), nullable=False, server_default='draft'),
        sa.Column('generated_doc_path', sa.String(1000), nullable=True),
        sa.Column('metadata', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.CheckConstraint("case_type IN ('injury','death')", name='ck_complaint_cases_case_type'),
        sa.CheckConstraint("status IN ('draft','processing','completed','failed')", name='ck_complaint_cases_status'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_complaint_cases_status', 'complaint_cases', ['status'])
    op.create_index('idx_complaint_cases_created_at', 'complaint_cases', [sa.text('created_at DESC')])

    op.create_table(
        'complaint_uploads',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('case_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('complaint_cases.id', ondelete='CASCADE'), nullable=False),
        sa.Column('slot', sa.String(30), nullable=False),
        sa.Column('file_type', sa.String(30), nullable=False, server_default='pdf'),
        sa.Column('original_filename', sa.String(500), nullable=True),
        sa.Column('minio_bucket', sa.String(100), nullable=True),
        sa.Column('minio_key', sa.String(1000), nullable=True),
        sa.Column('manual_input', sa.Text(), nullable=True),
        sa.Column('ocr_status', sa.String(30), nullable=False, server_default='pending'),
        sa.Column('ocr_result', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('extracted_data', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('manual_edit', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.CheckConstraint("slot IN ('plaintiff','guardian','defendant','fee','medical','appraisal','staff_error')", name='ck_complaint_uploads_slot'),
        sa.CheckConstraint("file_type IN ('pdf','image','manual_input')", name='ck_complaint_uploads_file_type'),
        sa.CheckConstraint("ocr_status IN ('pending','processing','completed','failed','skipped')", name='ck_complaint_uploads_ocr_status'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_complaint_uploads_case_id', 'complaint_uploads', ['case_id'])
    op.create_index('idx_complaint_uploads_slot', 'complaint_uploads', ['slot'])

    op.create_table(
        'complaint_steps',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('case_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('complaint_cases.id', ondelete='CASCADE'), nullable=False),
        sa.Column('step_name', sa.String(50), nullable=False),
        sa.Column('status', sa.String(30), nullable=False, server_default='pending'),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('step_metadata', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_complaint_steps_case_id', 'complaint_steps', ['case_id'])


def downgrade() -> None:
    op.drop_table('complaint_steps')
    op.drop_table('complaint_uploads')
    op.drop_table('complaint_cases')
