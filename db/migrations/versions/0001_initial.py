"""initial

Revision ID: 0001
Revises:
Create Date: 2026-05-13 12:05:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- scan_tasks ---
    op.create_table(
        "scan_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("scanner_id", sa.String(100), nullable=True),
        sa.Column("source_type", sa.String(30), nullable=False, server_default="watch_folder"),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("original_path", sa.String(1000), nullable=True),
        sa.Column("result_path", sa.String(1000), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("file_md5", sa.String(32), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("confidence_avg", sa.Numeric(5, 4), nullable=True),
        sa.Column("structure_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("table_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("heading_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("paragraph_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("callback_url", sa.String(1000), nullable=True),
        sa.Column("callback_status", sa.String(30), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_scan_tasks_md5", "scan_tasks", ["file_md5"],
                    unique=True, postgresql_where=sa.text("file_md5 IS NOT NULL"))
    op.create_index("idx_scan_tasks_status", "scan_tasks", ["status"])
    op.create_index("idx_scan_tasks_created_at", "scan_tasks", [sa.text("created_at DESC")])
    op.create_index("idx_scan_tasks_scanner_id", "scan_tasks", ["scanner_id"])
    op.create_index("idx_scan_tasks_priority", "scan_tasks", ["priority"])

    # --- task_steps ---
    op.create_table(
        "task_steps",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("scan_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_name", sa.String(50), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("output_path", sa.String(1000), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("step_metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_task_steps_task_id", "task_steps", ["task_id"])
    op.create_index("idx_task_steps_step_name", "task_steps", ["step_name"])

    # --- scan_files ---
    op.create_table(
        "scan_files",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("scan_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_type", sa.String(50), nullable=False),
        sa.Column("page_no", sa.Integer(), nullable=True),
        sa.Column("bucket", sa.String(100), nullable=False),
        sa.Column("object_key", sa.String(1000), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_scan_files_task_id", "scan_files", ["task_id"])
    op.create_index("idx_scan_files_type", "scan_files", ["file_type"])


def downgrade() -> None:
    op.drop_table("scan_files")
    op.drop_table("task_steps")
    op.drop_table("scan_tasks")
