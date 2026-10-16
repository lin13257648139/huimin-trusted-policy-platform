from __future__ import annotations

import io
import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "evaluation" / "ocr_synthetic"

TEMPLATES = (
    {
        "material_type": "medical_expense",
        "title": "医疗支出凭据",
        "fields": (("就诊日期", "2026-09-15"), ("医疗费用合计", "30,000.00 元"), ("医保结算", "待核验")),
        "date": "2026-09-15",
        "amount": "30,000.00元",
    },
    {
        "material_type": "income",
        "title": "工资收入证明",
        "fields": (("证明日期", "2026-09-20"), ("工资收入", "5,200.00 元/月"), ("用途", "社会救助演示")),
        "date": "2026-09-20",
        "amount": "5,200.00元",
    },
    {
        "material_type": "residence",
        "title": "广东省居住证明",
        "fields": (("居住地址", "广州市示例区"), ("签发日期", "2026-09-01"), ("有效期至", "2027-09-30")),
        "date": "2026-09-01",
        "amount": None,
    },
    {
        "material_type": "verification_authorization",
        "title": "家庭经济状况核对授权书",
        "fields": (("授权事项", "家庭经济状况核对"), ("授权日期", "2026-09-18"), ("材料属性", "合成演示")),
        "date": "2026-09-18",
        "amount": None,
    },
    {
        "material_type": "identity",
        "title": "居民身份证明",
        "fields": (("签发日期", "2026-08-09"), ("证件状态", "仅供合成测试"), ("住址", "广州市示例地址")),
        "date": "2026-08-09",
        "amount": None,
    },
    {
        "material_type": "household_register",
        "title": "居民户口簿信息页",
        "fields": (("登记日期", "2026-07-11"), ("户口性质", "合成测试"), ("家庭人数", "3 人")),
        "date": "2026-07-11",
        "amount": None,
    },
    {
        "material_type": "medical_diagnosis",
        "title": "医院诊断证明",
        "fields": (("诊断日期", "2026-09-12"), ("诊断结论", "合成测试内容"), ("复核状态", "待人工核验")),
        "date": "2026-09-12",
        "amount": None,
    },
    {
        "material_type": "education_expense",
        "title": "教育学费支出凭据",
        "fields": (("缴费日期", "2026-09-05"), ("学费金额", "8,800.00 元"), ("学期", "合成测试学期")),
        "date": "2026-09-05",
        "amount": "8,800.00元",
    },
)

DEGRADATIONS = (
    "clear",
    "low_contrast",
    "slight_blur",
    "rotate_left",
    "rotate_right",
    "grayscale",
    "jpeg_roundtrip",
    "shadow",
    "mild_noise",
    "warm_tint",
)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = (
        Path(r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    )
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def build_document(template: dict[str, object], layout_index: int) -> Image.Image:
    palettes = (
        ("#123f3f", "#e8f6f1"),
        ("#263a73", "#eef1fb"),
        ("#6c3d2e", "#faf0ec"),
        ("#31523b", "#eef7f0"),
        ("#5b356f", "#f7eefb"),
    )
    accent, pale = palettes[layout_index % len(palettes)]
    image = Image.new("RGB", (1200, 820), "#f2f4f3")
    draw = ImageDraw.Draw(image)
    title = str(template["title"])
    fields = list(template["fields"])
    layout = layout_index % 10

    draw.rounded_rectangle((45, 35, 1155, 785), radius=18, fill="white", outline="#b8c7c3", width=3)
    if layout in {0, 5}:
        draw.rectangle((45, 35, 1155, 155), fill=accent)
        draw.text((90, 75), title, fill="white", font=font(34, True))
        positions = [(110, 225), (110, 355), (110, 485)]
    elif layout in {1, 6}:
        draw.text((600, 75), title, anchor="ma", fill=accent, font=font(36, True))
        draw.line((120, 135, 1080, 135), fill=accent, width=4)
        positions = [(150, 210), (150, 350), (150, 490)]
    elif layout in {2, 7}:
        draw.rectangle((45, 35, 300, 785), fill=accent)
        draw.text((172, 155), title, anchor="ma", fill="white", font=font(29, True))
        positions = [(355, 170), (355, 330), (355, 490)]
    elif layout in {3, 8}:
        draw.rounded_rectangle((80, 65, 1120, 180), radius=12, fill=pale, outline=accent, width=3)
        draw.text((600, 105), title, anchor="ma", fill=accent, font=font(34, True))
        positions = [(105, 240), (620, 240), (105, 450)]
    else:
        draw.text((95, 75), "合成材料 / SYNTHETIC", fill="#687a76", font=font(19, True))
        draw.text((95, 125), title, fill=accent, font=font(38, True))
        positions = [(95, 240), (95, 375), (95, 510)]

    for (label, value), (x, y) in zip(fields, positions, strict=True):
        width = 455 if layout in {3, 8} else 760
        draw.rounded_rectangle((x, y, min(1120, x + width), y + 95), radius=10, fill=pale)
        draw.text((x + 22, y + 15), str(label), fill="#667b78", font=font(21))
        draw.text((x + 185, y + 13), str(value), fill="#173536", font=font(26, True))
    draw.text((600, 748), "比赛程序生成 · 不含真实个人信息", anchor="ma", fill="#087866", font=font(21, True))
    return image


def degrade(image: Image.Image, name: str, seed: int) -> Image.Image:
    if name == "clear":
        return image
    if name == "low_contrast":
        return ImageEnhance.Contrast(image).enhance(0.55)
    if name == "slight_blur":
        return image.filter(ImageFilter.GaussianBlur(radius=1.3))
    if name == "rotate_left":
        return image.rotate(-1.6, resample=Image.Resampling.BICUBIC, fillcolor="white")
    if name == "rotate_right":
        return image.rotate(1.8, resample=Image.Resampling.BICUBIC, fillcolor="white")
    if name == "grayscale":
        return image.convert("L").convert("RGB")
    if name == "jpeg_roundtrip":
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=58)
        return Image.open(io.BytesIO(buffer.getvalue())).convert("RGB")
    if name == "shadow":
        overlay = Image.new("L", image.size, 0)
        draw = ImageDraw.Draw(overlay)
        draw.rectangle((0, 0, 390, image.height), fill=80)
        return Image.composite(ImageEnhance.Brightness(image).enhance(0.65), image, overlay)
    if name == "mild_noise":
        randomizer = random.Random(seed)
        noise = Image.new("RGB", image.size)
        noise.putdata(
            [
                (value, value, value)
                for value in (randomizer.randint(222, 255) for _ in range(image.width * image.height))
            ]
        )
        return Image.blend(image, noise, 0.10)
    if name == "warm_tint":
        tint = Image.new("RGB", image.size, (255, 240, 215))
        return Image.blend(image, tint, 0.12)
    raise ValueError(f"unknown degradation: {name}")


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, object]] = []
    index = 1
    for layout_index in range(10):
        template = TEMPLATES[layout_index % len(TEMPLATES)]
        base = build_document(template, layout_index)
        for degradation in DEGRADATIONS:
            name = f"OCR-{index:03d}.png"
            degrade(base, degradation, index).save(OUTPUT / name, optimize=True)
            manifest.append(
                {
                    "case_id": f"OCR-{index:03d}",
                    "file": name,
                    "split": "frozen_final_test",
                    "material_type": template["material_type"],
                    "layout": f"layout-{layout_index + 1:02d}",
                    "degradation": degradation,
                    "expected_date": template["date"],
                    "expected_amount": template["amount"],
                    "data_role": "programmatically_rendered_synthetic_ocr_benchmark",
                }
            )
            index += 1
    if len(manifest) != 100 or len({item["layout"] for item in manifest}) != 10:
        raise RuntimeError("OCR冻结集必须为100张且包含10种版式")
    (OUTPUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("OCR_SYNTHETIC_CASES=100 layouts=10 degradations=10")


if __name__ == "__main__":
    main()
