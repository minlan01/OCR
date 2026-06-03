"""Add neonatal case type + seed requirements

Revision ID: 20260602_001
"""
from alembic import op

# ─── revision markers ───
revision = "20260602_001"
down_revision = "20260526_002_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 放宽 evidence_cases CHECK 约束：加入 'neonatal'
    op.execute(
        "ALTER TABLE evidence_cases DROP CONSTRAINT IF EXISTS ck_evidence_cases_case_type"
    )
    op.execute(
        "ALTER TABLE evidence_cases ADD CONSTRAINT ck_evidence_cases_case_type "
        "CHECK (case_type IN ('injury','death','neonatal'))"
    )

    # 2. 放宽 evidence_requirements CHECK 约束
    op.execute(
        "ALTER TABLE evidence_requirements DROP CONSTRAINT IF EXISTS ck_evidence_requirements_case_type"
    )
    op.execute(
        "ALTER TABLE evidence_requirements ADD CONSTRAINT ck_evidence_requirements_case_type "
        "CHECK (case_type IN ('injury','death','neonatal'))"
    )

    # 3. 插入 neonatal 种子数据（模板暂用伤残模板，is_minor=True）
    # id 列为 serial integer，不需要显式指定
    op.execute("""
        INSERT INTO evidence_requirements (case_type, is_minor, category, category_name, description, is_required, sort_order, check_rules)
        VALUES
            ('neonatal', TRUE, 'identity_id_card', '原告（法定代理人）身份证信息',
             '法定代理人身份证正反面', TRUE, 1, '{"min_count": 1}'),
            ('neonatal', TRUE, 'identity_hukou', '户口本信息',
             '户口本主页及本人页（含新生儿页）', FALSE, 2, '{}'),
            ('neonatal', TRUE, 'identity_other', '其他身份信息',
             '出生医学证明、监护证明等', TRUE, 3, '{"min_count": 1}'),
            ('neonatal', TRUE, 'identity_defendant', '被告身份信息',
             '医疗机构营业执照/执业许可证、统一社会信用代码等', TRUE, 4, '{"min_count": 1}'),
            ('neonatal', TRUE, 'medical_record', '病历资料',
             '门诊病历、住院病历、分娩记录、新生儿病历、检查报告等', TRUE, 6, '{"min_count": 1}'),
            ('neonatal', TRUE, 'appraisal', '司法鉴定意见书',
             '伤残等级鉴定、因果关系鉴定、参与度鉴定等', FALSE, 7, '{}'),
            ('neonatal', TRUE, 'fee_receipt', '医疗费用及相关票据',
             '医疗费发票、收费收据、费用结算单等', TRUE, 8, '{"min_count": 1}'),
            ('neonatal', TRUE, 'other_evidence', '其他证据',
             '其他与案件有关的证据材料', FALSE, 9, '{}')
        ON CONFLICT DO NOTHING
    """)

    # 4. complaint_cases 表也需要放宽（如果存在）
    op.execute(
        "ALTER TABLE complaint_cases DROP CONSTRAINT IF EXISTS ck_complaint_cases_case_type"
    )
    op.execute(
        "ALTER TABLE complaint_cases ADD CONSTRAINT ck_complaint_cases_case_type "
        "CHECK (case_type IN ('injury','death','neonatal'))"
    )


def downgrade() -> None:
    # 删除 neonatal 种子数据
    op.execute("DELETE FROM evidence_requirements WHERE case_type = 'neonatal'")

    # 恢复 CHECK 约束（不含 neonatal）
    op.execute(
        "ALTER TABLE evidence_cases DROP CONSTRAINT IF EXISTS ck_evidence_cases_case_type"
    )
    op.execute(
        "ALTER TABLE evidence_cases ADD CONSTRAINT ck_evidence_cases_case_type "
        "CHECK (case_type IN ('injury','death'))"
    )

    op.execute(
        "ALTER TABLE evidence_requirements DROP CONSTRAINT IF EXISTS ck_evidence_requirements_case_type"
    )
    op.execute(
        "ALTER TABLE evidence_requirements ADD CONSTRAINT ck_evidence_requirements_case_type "
        "CHECK (case_type IN ('injury','death'))"
    )

    op.execute(
        "ALTER TABLE complaint_cases DROP CONSTRAINT IF EXISTS ck_complaint_cases_case_type"
    )
    op.execute(
        "ALTER TABLE complaint_cases ADD CONSTRAINT ck_complaint_cases_case_type "
        "CHECK (case_type IN ('injury','death'))"
    )
