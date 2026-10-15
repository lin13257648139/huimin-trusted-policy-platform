from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "evaluation" / "ocr_synthetic"

TEMPLATES = {
    "medical_expense": {
        "title": "医疗支出凭据",
        "fields": [("就诊日期", "2026-09-15"), ("费用合计", "30,000.00 元"), ("医保结算", "待核验")],
        "date": "2026-09-15",
        "amount": "30,000.00元",
    },
    "income": {
        "title": "收入证明",
        "fields": [("证明日期", "2026-09-20"), ("工资收入", "5,200.00 元/月"), ("用途", "社会救助演示")],
        "date": "2026-09-20",
        "amount": "5,200.00元",
    },
    "residence": {
        "title": "广东省居住证",
        "fields": [("居住地址", "广州市示例区"), ("签发日期", "2026-09-01"), ("有效期至", "2027-09-30")],
        "date": "2026-09-01",
        "amount": None,
    },
    "verification_authorization": {
        "title": "家庭经济状况核对授权书",
        "fields": [("授权事项", "经济状况核对"), ("授权日期", "2026-09-18"), ("材料属性", "合成演示")],
        "date": "2026-09-18",
        "amount": None,
    },
}


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        Path(r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def build_document(title: str, fields: list[tuple[str, str]]) -> Image.Image:
    image = Image.new("RGB", (1200, 820), "#f5f8f7")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((55, 45, 1145, 775), radius=24, fill="white", outline="#bacdc8", width=3)
    draw.rectangle((55, 45, 1145, 160), fill="#123f3f")
    draw.text((95, 80), title, fill="white", font=font(34, bold=True))
    draw.text((920, 91), "SYNTHETIC", fill="#77ddc9", font=font(18, bold=True))
    y = 225
    for label, value in fields:
        draw.text((105, y), label, fill="#667b78", font=font(24))
        draw.text((365, y), value, fill="#173536", font=font(28, bold=True))
        draw.line((105, y + 50, 1095, y + 50), fill="#dce7e4", width=2)
        y += 115
    draw.rounded_rectangle((100, 665, 1100, 730), radius=13, fill="#e8f6f1")
    draw.text((220, 684), "比赛合成材料 · 不含真实个人信息", fill="#087866", font=font(23, bold=True))
    return image


def variants(image: Image.Image) -> dict[str, Image.Image]:
    return {
        "clear": image,
        "low_contrast": ImageEnhance.Contrast(image).enhance(0.45),
        "slight_blur": image.filter(ImageFilter.GaussianBlur(radius=1.6)),
        "rotate": image.rotate(2.0, resample=Image.Resampling.BICUBIC, expand=False, fillcolor="white"),
    }


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    index = 1
    for material_type, template in TEMPLATES.items():
        for variant, image in variants(build_document(template["title"], template["fields"])).items():
            name = f"OCR-{index:03d}.png"
            image.save(OUTPUT / name, optimize=True)
            manifest.append(
                {
                    "case_id": f"OCR-{index:03d}",
                    "file": name,
                    "material_type": material_type,
                    "variant": variant,
                    "expected_date": template["date"],
                    "expected_amount": template["amount"],
                    "data_role": "synthetic_ocr_benchmark",
                }
            )
            index += 1
    (OUTPUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"OCR_SYNTHETIC_CASES={len(manifest)}")


if __name__ == "__main__":
    main()
