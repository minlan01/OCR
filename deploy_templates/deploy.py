#!/usr/bin/env python3
"""Deploy updated template files to database and local directory."""

import json
import os
import sys

DEPLOY_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_NAME = "通用诉状模板"
LOCAL_COPY_DIR = os.environ.get("TEMPLATE_OUTPUT_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "template_output"))

DB_URL = os.environ.get("DATABASE_URL_SYNC", "postgresql://scanstruct:scanstruct123@localhost:5433/scanstruct")


def deploy_to_database(schema_json: dict, rules_md: str, generator_code: str):
    import psycopg2
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name FROM output_templates WHERE name = %s",
            (TEMPLATE_NAME,)
        )
        row = cur.fetchone()
        if row:
            template_id = row[0]
            print(f"Found template: {row[1]} (id={template_id})")
            cur.execute(
                "UPDATE output_templates SET schema_json = %s, rules_md = %s, generator_code = %s, updated_at = NOW() WHERE id = %s",
                (json.dumps(schema_json, ensure_ascii=False), rules_md, generator_code, template_id)
            )
            print(f"Updated template {template_id} in database")
        else:
            cur.execute(
                "INSERT INTO output_templates (name, description, schema_json, rules_md, generator_code) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (TEMPLATE_NAME, "医疗损害责任纠纷民事起诉状通用模板", json.dumps(schema_json, ensure_ascii=False), rules_md, generator_code)
            )
            template_id = cur.fetchone()[0]
            print(f"Created template {template_id} in database")
        conn.commit()
        cur.close()
    except Exception as e:
        conn.rollback()
        print(f"Database error: {e}")
        raise
    finally:
        conn.close()


def copy_to_local(schema_json: dict, rules_md: str, generator_code: str):
    os.makedirs(LOCAL_COPY_DIR, exist_ok=True)

    schema_path = os.path.join(LOCAL_COPY_DIR, "complaint_schema.json")
    with open(schema_path, "w", encoding="utf-8") as f:
        json.dump(schema_json, f, ensure_ascii=False, indent=2)
    print(f"Wrote {schema_path}")

    rules_path = os.path.join(LOCAL_COPY_DIR, "通用诉状模板_规则手册.md")
    with open(rules_path, "w", encoding="utf-8") as f:
        f.write(rules_md)
    print(f"Wrote {rules_path}")

    gen_path = os.path.join(LOCAL_COPY_DIR, "generate_complaint.py")
    with open(gen_path, "w", encoding="utf-8") as f:
        f.write(generator_code)
    print(f"Wrote {gen_path}")


def main():
    schema_path = os.path.join(DEPLOY_DIR, "complaint_schema.json")
    rules_path = os.path.join(DEPLOY_DIR, "通用诉状模板_规则手册.md")
    gen_path = os.path.join(DEPLOY_DIR, "generate_complaint.py")

    with open(schema_path, "r", encoding="utf-8") as f:
        schema_json = json.load(f)

    with open(rules_path, "r", encoding="utf-8") as f:
        rules_md = f.read()

    with open(gen_path, "r", encoding="utf-8") as f:
        generator_code = f.read()

    print("=== Deploying to database ===")
    deploy_to_database(schema_json, rules_md, generator_code)

    print("\n=== Copying to local directory ===")
    copy_to_local(schema_json, rules_md, generator_code)

    print("\nDeployment complete!")


if __name__ == "__main__":
    main()
