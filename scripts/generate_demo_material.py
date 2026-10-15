from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "demo_assets"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        Path(r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def build_document() -> Image.Image:
    image = Image.new("RGB", (1400, 1000), "#f8faf9")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((70, 55, 1330, 940), radius=30, fill="white", outline="#cbdad6", width=3)
    draw.rectangle((70, 55, 1330, 175), fill="#103b3b")
    draw.text((115, 92), "医疗支出凭据（合成演示）", fill="white", font=font(36, bold=True))
    draw.text((1050, 103), "DEMO ONLY", fill="#65d8c2", font=font(20, bold=True))

    fields = [
        ("材料编号", "SYNTH-2026-0001"),
        ("就诊人", "演示用户 A（虚构）"),
        ("就诊日期", "2026-09-15"),
        ("医疗机构", "示例医疗机构（非真实）"),
        ("费用合计", "30,000.00 元"),
        ("医保结算", "待核验"),
        ("材料用途", "仅用于惠民智导材料质量预检演示"),
    ]
    y = 225
    for label, value in fields:
        draw.text((125, y), label, fill="#738684", font=font(23))
        draw.text((390, y), value, fill="#173536", font=font(26, bold=True))
        draw.line((125, y + 48, 1275, y + 48), fill="#e4ece9", width=2)
        y += 90

    draw.rounded_rectangle((120, 830, 1280, 900), radius=16, fill="#eaf7f3")
    draw.text((255, 850), "比赛合成示例 · 不含任何真实个人信息 · 不可用于申报", fill="#087b69", font=font(24, bold=True))
    return image


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    clear = build_document()
    clear.save(OUTPUT / "合成_医疗支出凭据_清晰.png", optimize=True)
    blurred = clear.filter(ImageFilter.GaussianBlur(radius=7))
    blurred.save(OUTPUT / "合成_医疗支出凭据_模糊.png", optimize=True)
    print("DEMO_MATERIALS_CREATED=2")


if __name__ == "__main__":
    main()

