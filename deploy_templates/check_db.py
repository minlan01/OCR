import psycopg2, json

conn = psycopg2.connect('postgresql://scanstruct:scanstruct123@localhost:5433/scanstruct')
cur = conn.cursor()

cur.execute("SELECT id, status FROM scan_tasks ORDER BY created_at DESC LIMIT 1")
task = cur.fetchone()
if task:
    task_id = task[0]
    print(f"Latest task: {task_id}")

    cur.execute("SELECT step_name, step_metadata FROM task_steps WHERE task_id = %s ORDER BY started_at", (task_id,))
    steps = cur.fetchall()
    for step in steps:
        print(f"\nStep: {step[0]}")
        meta = step[1]
        if meta:
            if isinstance(meta, str):
                meta = json.loads(meta)
            if isinstance(meta, dict):
                print(f"  Keys: {list(meta.keys())[:20]}")
                if 'plaintiffs' in meta:
                    print(f"  PLAINTIFFS: {json.dumps(meta['plaintiffs'], ensure_ascii=False, indent=2)[:2000]}")
                if 'extracted_data' in meta:
                    ed = meta['extracted_data']
                    if isinstance(ed, dict):
                        print(f"  EXTRACTED keys: {list(ed.keys())[:20]}")
                        if 'plaintiffs' in ed:
                            print(f"  EXTRACTED PLAINTIFFS: {json.dumps(ed['plaintiffs'], ensure_ascii=False, indent=2)[:2000]}")
                text = json.dumps(meta, ensure_ascii=False)
                if len(text) > 500:
                    print(f"  Preview: {text[:500]}...")
                else:
                    print(f"  Data: {text}")
            else:
                print(f"  Type: {type(meta)}")
        else:
            print("  No metadata")

conn.close()
