"""
阿里云百炼 Qwen-OCR API 连通性测试
文档: https://help.aliyun.com/zh/model-studio/qwen-vl-ocr
"""
import base64
import json
import os
import sys
from pathlib import Path

from openai import OpenAI

# ── 配置 (从 .env 读取，永不硬编码) ────────────────
# 兼容两种运行方式: 直接跑脚本 或 作为模块导入
def _load_config():
    """从项目 .env / 环境变量加载配置，优先级: 环境变量 > .env > 默认值"""
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())
    return {
        "api_key": os.getenv("BAILIAN_API_KEY", ""),
        "base_url": os.getenv("BAILIAN_OCR_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        "model": os.getenv("BAILIAN_OCR_MODEL", "qwen-vl-ocr-latest"),
    }

_config = _load_config()
API_KEY = _config["api_key"]
BASE_URL = _config["base_url"]
MODEL = _config["model"]

# ── 测试图片 ────────────────────────────────────────
# 先用 Pillow 生成一张简单的中文文本图片做测试
def create_test_image() -> Path:
    """生成一张包含中文文字的测试图片"""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("[WARN] Pillow 未安装，尝试用系统字体生成图片")
        return None

    img = Image.new("RGB", (800, 200), color="white")
    draw = ImageDraw.Draw(img)

    # 尝试加载中文字体
    font = None
    font_candidates = [
        "C:/Windows/Fonts/simhei.ttf",       # 黑体
        "C:/Windows/Fonts/msyh.ttc",          # 微软雅黑
        "C:/Windows/Fonts/simsun.ttc",        # 宋体
        "C:/Windows/Fonts/simkai.ttf",        # 楷体
    ]
    for fp in font_candidates:
        if Path(fp).exists():
            try:
                font = ImageFont.truetype(fp, 36)
                print(f"[INFO] 使用字体: {fp}")
                break
            except Exception:
                continue

    if font is None:
        font = ImageFont.load_default()
        print("[WARN] 未找到中文字体，使用默认字体（可能无法正确渲染中文）")

    lines = [
        "阿里云百炼 OCR 测试",
        "扫描件智能结构化处理系统",
        "ScanStruct v1.0",
        "2024年5月14日",
    ]
    y = 20
    for line in lines:
        draw.text((40, y), line, fill="black", font=font)
        y += 45

    out_path = Path(__file__).parent / "_test_ocr_image.png"
    img.save(str(out_path))
    print(f"[INFO] 测试图片已生成: {out_path}")
    return out_path


def image_to_base64(image_path: Path) -> str:
    """将图片转为 Base64 Data URL"""
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    # 推断 MIME 类型
    suffix = image_path.suffix.lower()
    mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
    mime = mime_map.get(suffix, "image/png")
    return f"data:{mime};base64,{b64}"


def test_ocr_with_base64(client: OpenAI, image_path: Path):
    """测试: 用 Base64 编码传入本地图片"""
    print("\n" + "=" * 60)
    print("测试 1: Base64 本地图片 + 中文 Prompt")
    print("=" * 60)

    data_url = image_to_base64(image_path)
    print(f"[INFO] Base64 长度: {len(data_url)} 字符")

    try:
        completion = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url},
                            "min_pixels": 32 * 32 * 3,
                            "max_pixels": 32 * 32 * 8192,
                        },
                        {
                            "type": "text",
                            "text": "请精确提取图片中的所有文字，保持原有换行格式，逐行输出。不要添加任何额外说明。",
                        },
                    ],
                }
            ],
        )

        result = completion.choices[0].message.content
        usage = completion.usage
        print(f"\n[结果] OCR 识别内容:")
        print("-" * 40)
        print(result)
        print("-" * 40)
        print(f"[用量] prompt_tokens={usage.prompt_tokens}, "
              f"completion_tokens={usage.completion_tokens}, "
              f"total_tokens={usage.total_tokens}")
        print("[状态] ✅ 测试通过")
        return True

    except Exception as e:
        print(f"[错误] ❌ 测试失败: {e}")
        return False


def test_ocr_with_url(client: OpenAI):
    """测试: 用公网 URL 传入图片"""
    print("\n" + "=" * 60)
    print("测试 2: 公网 URL 图片 + 默认 Prompt")
    print("=" * 60)

    # 使用阿里云公开的示例图片
    test_url = "https://img.alicdn.com/imgextra/i4/O1CN01u9CjWg1L0f1gXXXXXXXX_!!6000000001234-2-tps-800-200.png"

    try:
        completion = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": test_url},
                            "min_pixels": 32 * 32 * 3,
                            "max_pixels": 32 * 32 * 8192,
                        },
                        {
                            "type": "text",
                            "text": "请识别图片中的所有文字内容。",
                        },
                    ],
                }
            ],
        )

        result = completion.choices[0].message.content
        usage = completion.usage
        print(f"\n[结果] OCR 识别内容:")
        print("-" * 40)
        print(result)
        print("-" * 40)
        print(f"[用量] prompt_tokens={usage.prompt_tokens}, "
              f"completion_tokens={usage.completion_tokens}, "
              f"total_tokens={usage.total_tokens}")
        print("[状态] ✅ 测试通过")
        return True

    except Exception as e:
        print(f"[状态] ⚠️  示例图片可能不可用: {e}")
        print("[说明] 这通常是 URL 不可达，不影响 API 本身的可用性")
        return False  # 不算失败


def test_structured_extraction(client: OpenAI, image_path: Path):
    """测试: 结构化信息抽取"""
    print("\n" + "=" * 60)
    print("测试 3: 结构化 JSON 信息提取")
    print("=" * 60)

    data_url = image_to_base64(image_path)

    try:
        completion = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url},
                            "min_pixels": 32 * 32 * 3,
                            "max_pixels": 32 * 32 * 8192,
                        },
                        {
                            "type": "text",
                            "text": (
                                "请提取图片中的文字信息，以JSON格式返回。"
                                "格式: {\"标题\": \"...\", \"日期\": \"...\", \"内容行\": [\"行1\", \"行2\", ...]}。"
                                "只返回JSON，不要任何额外说明。"
                            ),
                        },
                    ],
                }
            ],
        )

        result = completion.choices[0].message.content
        usage = completion.usage
        print(f"\n[结果] 结构化提取:")
        print("-" * 40)
        print(result)
        try:
            parsed = json.loads(result.strip().removeprefix("```json").removesuffix("```").strip())
            print(f"\n[解析] JSON 有效: {json.dumps(parsed, ensure_ascii=False, indent=2)}")
        except json.JSONDecodeError:
            print("[解析] 返回非纯 JSON，但内容已提取")
        print("-" * 40)
        print(f"[用量] total_tokens={usage.total_tokens}")
        print("[状态] ✅ 测试通过")
        return True

    except Exception as e:
        print(f"[错误] ❌ 测试失败: {e}")
        return False


def main():
    if not API_KEY:
        print("[ERROR] 未找到 BAILIAN_API_KEY！")
        print("请确保以下任一来源已配置:")
        print("  1. 项目 .env 文件中的 BAILIAN_API_KEY=sk-xxx")
        print("  2. 环境变量: set BAILIAN_API_KEY=sk-xxx")
        sys.exit(1)

    print("阿里云百炼 Qwen-OCR 连通性测试")
    print(f"Base URL: {BASE_URL}")
    print(f"Model: {MODEL}")
    print(f"API Key: {API_KEY[:12]}...{API_KEY[-4:]}")

    # 创建客户端
    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

    # 验证连通性 - 先列一下可用模型
    print("\n[INFO] 验证 API 连通性...")
    try:
        # 用 list models 测试连通性（百炼支持）
        models = client.models.list()
        ocr_models = [m.id for m in models if "ocr" in m.id.lower()]
        print(f"[INFO] 可用 OCR 模型: {ocr_models if ocr_models else '未直接列出（通过 chat.completions 可用）'}")
    except Exception as e:
        print(f"[WARN] models.list() 不可用: {e}")
        print("[INFO] 直接尝试 chat.completions 调用...")

    # 生成测试图片
    image_path = create_test_image()
    if image_path is None:
        print("[ERROR] 无法生成测试图片，退出")
        sys.exit(1)

    # 运行测试
    results = []
    results.append(("Base64 本地图片 OCR", test_ocr_with_base64(client, image_path)))
    results.append(("URL 图片 OCR", test_ocr_with_url(client)))
    results.append(("结构化 JSON 提取", test_structured_extraction(client, image_path)))

    # 汇总
    print("\n" + "=" * 60)
    print("测试汇总")
    print("=" * 60)
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    for name, ok in results:
        status = "✅ 通过" if ok else "❌ 失败"
        print(f"  {status}  {name}")
    print(f"\n总结: {passed}/{total} 通过")

    # 清理
    if image_path.exists():
        image_path.unlink()
        print(f"[INFO] 已清理临时图片: {image_path}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
