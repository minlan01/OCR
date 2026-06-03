"""文件变更检测脚本 — 由自动化调用，输出变更内容"""
import os
import json
import hashlib

WATCH_FILES = [
    r"E:\OCRScanStruct\api\schemas\evidence.py",
    r"E:\OCRScanStruct\api\routes\evidence.py",
    r"E:\OCRScanStruct\services\evidence\document_analyzer.py",
    r"E:\OCRScanStruct\static\src\api\evidence.ts",
    r"E:\OCRScanStruct\static\src\views\EvidencePage.vue",
]
STATE_FILE = r"E:\OCRScanStruct\.file_monitor_state.json"

def get_file_hash(path):
    """快速获取文件哈希（前1024字节+大小+修改时间）"""
    try:
        st = os.stat(path)
        with open(path, "rb") as f:
            head = f.read(1024)
        h = hashlib.md5()
        h.update(head)
        h.update(str(st.st_size).encode())
        h.update(str(st.st_mtime).encode())
        return h.hexdigest()
    except OSError:
        return None

def read_last_lines(path, n=10):
    """读取文件最后n行"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        return "".join(lines[-n:])
    except:
        return "(无法读取)"

def main():
    # 读取上次状态
    old_state = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                old_state = json.load(f)
        except:
            pass

    changes = []
    current_state = {}

    for f in WATCH_FILES:
        h = get_file_hash(f)
        fname = os.path.basename(f)
        current_state[fname] = h
        
        if h is None:
            changes.append(f"  ❌ {fname} — 文件不存在或无法读取")
        elif fname not in old_state:
            changes.append(f"  🆕 {fname} — 新增文件（首次监控）")
        elif old_state[fname] != h:
            # 有变更！读取最后几行显示
            tail = read_last_lines(f)
            changes.append(f"  🔄 {fname} — 内容已修改，文件尾：\n{tail[:300]}")
            changes.append("")

    # 保存当前状态
    with open(STATE_FILE, "w") as f:
        json.dump(current_state, f)

    if changes:
        print("=" * 50)
        print("文件变更检测结果：")
        print("=" * 50)
        for c in changes:
            print(c)
    else:
        print("✅ 所有监控文件无变更")

if __name__ == "__main__":
    main()
