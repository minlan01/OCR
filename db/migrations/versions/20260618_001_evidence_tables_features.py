"""Evidence tables creation + tenant features + user tenant_id fix

Revision ID: 20260618_001
Revises: 20260617_001

补救历史遗留的迁移问题：
1. 创建 evidence_cases / evidence_materials / evidence_steps / evidence_requirements 4 张表
   （这些表在 models_evidence.py 中定义，但之前的迁移从未 create_table）
2. 添加 tenants.features JSONB 列
3. 修复 users.tenant_id 的 ondelete + nullable（CASCADE+NOT NULL → SET NULL+NULL）

注意：使用 IF NOT EXISTS / 检查列是否存在的方式，确保对已存在的开发数据库幂等。
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "20260618_001"
down_revision = "20260617_001"
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    """检查列是否存在（幂等用）"""
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table_name, "c": column_name},
    ).scalar()
    return bool(result)


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables WHERE table_name = :t"
        ),
        {"t": table_name},
    ).scalar()
    return bool(result)


def upgrade() -> None:
    # ─────────────────────────────────────────────────────
    # 1. tenants.features 列（之前漏建）
    # ─────────────────────────────────────────────────────
    if not _column_exists("tenants", "features"):
        op.add_column(
            "tenants",
            sa.Column("features", JSONB(), nullable=True, comment="功能开关 JSON"),
        )

    # ─────────────────────────────────────────────────────
    # 2. evidence_cases 表
    # ─────────────────────────────────────────────────────
    if not _table_exists("evidence_cases"):
        op.create_table(
            "evidence_cases",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True),
                      sa.ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True),
            sa.Column("complaint_case_id", UUID(as_uuid=True), nullable=True),
            sa.Column("case_type", sa.String(20), nullable=False),
            sa.Column("is_minor", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
            sa.Column("compensation_data", JSONB(),
                      server_default=sa.text("'{}'::jsonb"), nullable=False),
            sa.Column("error_msg", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("NOW()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.text("NOW()"), nullable=False),
        )
        op.create_index("idx_evidence_cases_tenant_id", "evidence_cases", ["tenant_id"])
        op.create_index("idx_evidence_cases_status", "evidence_cases", ["status"])
        op.create_check_constraint(
            "ck_evidence_cases_case_type",
            "evidence_cases",
            "case_type IN ('injury','death')",
        )
        op.create_check_constraint(
            "ck_evidence_cases_status",
            "evidence_cases",
            "status IN ('draft','processing','analyzing','exporting','done','failed','cancelled')",
        )

    # ─────────────────────────────────────────────────────
    # 3. evidence_materials 表
    # ─────────────────────────────────────────────────────
    if not _table_exists("evidence_materials"):
        op.create_table(
            "evidence_materials",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("evidence_case_id", UUID(as_uuid=True),
                      sa.ForeignKey("evidence_cases.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("filename", sa.String(500), nullable=False),
            sa.Column("file_size", sa.BigInteger(), nullable=False),
            sa.Column("mime_type", sa.String(100), nullable=True),
            sa.Column("minio_key", sa.String(1000), nullable=False),
            sa.Column("page_count", sa.Integer(), nullable=True),
            sa.Column("ocr_text", sa.Text(), nullable=True),
            sa.Column("ocr_confidence", sa.Float(), nullable=True),
            sa.Column("auto_category", sa.String(100), nullable=True),
            sa.Column("manual_category", sa.String(100), nullable=True),
            sa.Column("metadata_json", JSONB(),
                      server_default=sa.text("'{}'::jsonb"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("NOW()"), nullable=False),
        )
        op.create_index("idx_evidence_materials_case", "evidence_materials",
                        ["evidence_case_id"])

    # ─────────────────────────────────────────────────────
    # 4. evidence_steps 表
    # ─────────────────────────────────────────────────────
    if not _table_exists("evidence_steps"):
        op.create_table(
            "evidence_steps",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("evidence_case_id", UUID(as_uuid=True),
                      sa.ForeignKey("evidence_cases.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("step", sa.String(50), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("progress", sa.Integer(), server_default="0", nullable=False),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("metadata_json", JSONB(),
                      server_default=sa.text("'{}'::jsonb"), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.text("NOW()"), nullable=False),
        )
        op.create_index("idx_evidence_steps_case", "evidence_steps",
                        ["evidence_case_id"])
        op.create_unique_constraint(
            "uq_evidence_steps_case_step", "evidence_steps",
            ["evidence_case_id", "step"],
        )

    # ─────────────────────────────────────────────────────
    # 5. evidence_requirements 表
    # ─────────────────────────────────────────────────────
    if not _table_exists("evidence_requirements"):
        op.create_table(
            "evidence_requirements",
            sa.Column("id", UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("case_type", sa.String(20), nullable=False),
            sa.Column("category", sa.String(100), nullable=False),
            sa.Column("priority", sa.String(20), nullable=False, server_default="optional"),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("metadata_json", JSONB(),
                      server_default=sa.text("'{}'::jsonb"), nullable=False),
        )
        op.create_index("idx_evidence_requirements_case_type",
                        "evidence_requirements", ["case_type"])

    # ─────────────────────────────────────────────────────
    # 6. 修复 users.tenant_id（如果是 NOT NULL，改为可空 + ON DELETE SET NULL）
    # ─────────────────────────────────────────────────────
    bind = op.get_bind()
    is_nullable = bind.execute(sa.text(
        "SELECT is_nullable FROM information_schema.columns "
        "WHERE table_name='users' AND column_name='tenant_id'"
    )).scalar()
    if is_nullable == "NO":
        op.alter_column("users", "tenant_id", nullable=True)

    # 重建外键约束为 SET NULL（如果当前是 CASCADE）
    fk_action = bind.execute(sa.text(
        "SELECT confdeltype FROM pg_constraint c "
        "JOIN pg_class t ON c.conrelid = t.oid "
        "WHERE t.relname='users' AND c.contype='f' "
        "AND pg_get_constraintdef(c.oid) LIKE '%tenant_id%'"
    )).scalar()
    # confdeltype: 'a'=NO ACTION, 'r'=RESTRICT, 'c'=CASCADE, 'n'=SET NULL, 'd'=SET DEFAULT
    if fk_action == "c":
        # 获取约束名后重建
        constraint_name = bind.execute(sa.text(
            "SELECT conname FROM pg_constraint c "
            "JOIN pg_class t ON c.conrelid = t.oid "
            "WHERE t.relname='users' AND c.contype='f' "
            "AND pg_get_constraintdef(c.oid) LIKE '%tenant_id%' LIMIT 1"
        )).scalar()
        if constraint_name:
            op.drop_constraint(constraint_name, "users", type_="foreignkey")
            op.create_foreign_key(
                "fk_users_tenant_id", "users", "tenants",
                ["tenant_id"], ["id"], ondelete="SET NULL",
            )


def downgrade() -> None:
    # 仅回滚 evidence 表（其他改动不便回滚）
    for tbl in ("evidence_requirements", "evidence_steps", "evidence_materials", "evidence_cases"):
        if _table_exists(tbl):
            op.drop_table(tbl)
    if _column_exists("tenants", "features"):
        op.drop_column("tenants", "features")
