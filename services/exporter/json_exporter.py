"""
JSON 导出器

将结构化的扫描结果序列化为标准 JSON 文件并写入磁盘。
"""
import json
from pathlib import Path


def export_json(structured: dict, output_path: Path) -> Path:
    """
    将结构化数据导出为 JSON 文件

    Args:
        structured: ScanStruct 管线输出的结构化文档数据
        output_path: 输出文件路径（自动创建父目录）

    Returns:
        写入完成后的文件路径
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(structured, f, ensure_ascii=False, indent=2)
    return output_path
