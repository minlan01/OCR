"""add missing constraints, indexes and columns

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-19
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. task_steps: 添加唯一约束 (task_id, step_name)
    op.create_unique_constraint("uq_task_steps_task_step", "task_steps", ["task_id", "step_name"])

    # 2. task_steps: 添加 CHECK 约束
    op.execute(
        "ALTER TABLE task_steps ADD CONSTRAINT ck_task_steps_status "
        "CHECK (status IN ('pending','received','processing','completed','failed','cancelled','retrying'))"
    )

    # 3. scan_files: 添加复合索引
    op.create_index("idx_scan_files_task_type", "scan_files", ["task_id", "file_type"])

    # 4. scan_files: 添加 updated_at 列
    op.add_column(
        "scan_files",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    # 5. scan_tasks: 添加 CHECK 约束
    op.execute(
        "ALTER TABLE scan_tasks ADD CONSTRAINT ck_scan_tasks_status "
        "CHECK (status IN ('pending','received','processing','completed','failed','cancelled','retrying'))"
    )

    # 6. scan_tasks: 添加 confidence_avg / structure_score 范围约束
    op.execute(
        "ALTER TABLE scan_tasks ADD CONSTRAINT ck_confidence_avg_range "
        "CHECK (confidence_avg IS NULL OR (confidence_avg >= 0 AND confidence_avg <= 1))"
    )
    op.execute(
        "ALTER TABLE scan_tasks ADD CONSTRAINT ck_structure_score_range "
        "CHECK (structure_score IS NULL OR (structure_score >= 0 AND structure_score <= 1))"
    )


def downgrade() -> None:
    op.drop_constraint("ck_structure_score_range", "scan_tasks")
    op.drop_constraint("ck_confidence_avg_range", "scan_tasks")
    op.drop_constraint("ck_scan_tasks_status", "scan_tasks")
    op.drop_column("scan_files", "updated_at")
    op.drop_index("idx_scan_files_task_type", "scan_files")
    op.drop_constraint("ck_task_steps_status", "task_steps")
    op.drop_constraint("uq_task_steps_task_step", "task_steps")
