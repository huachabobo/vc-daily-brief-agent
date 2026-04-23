from __future__ import annotations

import re
from pathlib import Path
from textwrap import wrap

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "docs" / "assets"
BRIEF_PATH = ROOT / "sample_output" / "2026-04-23_brief.md"
TITLE_FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"
BODY_FONT = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"


def load_font(path: str, size: int):
    return ImageFont.truetype(path, size=size)


def parse_brief():
    lines = BRIEF_PATH.read_text(encoding="utf-8").splitlines()

    def collect_numbered(header: str):
        items = []
        active = False
        for line in lines:
            if line.strip() == header:
                active = True
                continue
            if active and line.startswith("## "):
                break
            if active and re.match(r"^\d+\.\s", line.strip()):
                items.append(re.sub(r"^\d+\.\s*", "", line.strip()))
        return items

    highlights = collect_numbered("## 今日 3 个重点")
    shifts = collect_numbered("## 今日变化")

    first_entry_title = ""
    first_entry_source = ""
    first_entry_selected = ""
    for index, line in enumerate(lines):
        if line.startswith("### "):
            first_entry_title = re.sub(r"^###\s*\d+\.\s*", "", line).strip()
            for follow in lines[index + 1 : index + 8]:
                if follow.startswith("**Why selected**："):
                    first_entry_selected = follow.split("：", 1)[1].strip()
                if follow.startswith("**来源**："):
                    match = re.search(r"\[([^\]]+)\]", follow)
                    if match:
                        first_entry_source = match.group(1)
            break

    return {
        "highlights": highlights[:3],
        "shifts": shifts[:3],
        "entry_title": first_entry_title,
        "entry_source": first_entry_source,
        "entry_selected": first_entry_selected,
    }


def draw_wrapped(draw, text, xy, font, fill, width_chars, line_height, max_lines=None):
    x, y = xy
    lines = wrap(text, width=width_chars) or [text]
    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1].rstrip()
        if len(last) >= 2:
            last = last[:-1].rstrip()
        lines[-1] = last + "…"
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height
    return y


def pill(draw, xy, text, fill, text_fill, font):
    x1, y1, x2, y2 = xy
    draw.rounded_rectangle((x1, y1, x2, y2), radius=20, fill=fill)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_x = x1 + (x2 - x1 - (bbox[2] - bbox[0])) / 2
    text_y = y1 + (y2 - y1 - (bbox[3] - bbox[1])) / 2 - 1
    draw.text((text_x, text_y), text, font=font, fill=text_fill)


def render_brief_preview(data):
    image = Image.new("RGB", (1600, 1100), "#f5efe6")
    draw = ImageDraw.Draw(image)

    title_font = load_font(TITLE_FONT, 58)
    subtitle_font = load_font(TITLE_FONT, 24)
    section_font = load_font(TITLE_FONT, 28)
    body_font = load_font(BODY_FONT, 24)
    small_font = load_font(BODY_FONT, 20)

    draw.rounded_rectangle((60, 60, 1540, 1040), radius=40, fill="#fffaf3")
    draw.text((100, 110), "VC Daily Brief", font=title_font, fill="#1f2937")
    draw.text((100, 190), "YouTube + RSS -> Rank -> Summary -> Feishu", font=subtitle_font, fill="#725f4f")

    pill(draw, (100, 250, 220, 292), "YouTube", "#e0f2fe", "#0c4a6e", small_font)
    pill(draw, (235, 250, 320, 292), "RSS", "#dcfce7", "#166534", small_font)
    pill(draw, (335, 250, 445, 292), "Feishu", "#fde68a", "#92400e", small_font)

    draw.text((100, 340), "今日 3 个重点", font=section_font, fill="#111827")
    y = 390
    for idx, item in enumerate(data["highlights"], start=1):
        draw.rounded_rectangle((100, y, 720, y + 92), radius=24, fill="#ffffff")
        draw.text((126, y + 18), f"{idx}.", font=section_font, fill="#9a3412")
        draw_wrapped(draw, item, (170, y + 18), body_font, "#374151", 24, 30, max_lines=3)
        y += 112

    draw.text((100, 745), "今日变化", font=section_font, fill="#111827")
    y = 795
    for item in data["shifts"]:
        draw.rounded_rectangle((100, y, 720, y + 72), radius=20, fill="#fff7ed")
        draw_wrapped(draw, item, (126, y + 18), small_font, "#7c2d12", 34, 24)
        y += 92

    draw.rounded_rectangle((860, 130, 1400, 980), radius=44, fill="#1f2937")
    draw.rounded_rectangle((890, 175, 1370, 930), radius=28, fill="#fcfbf7")
    draw.text((930, 215), "2026-04-23", font=small_font, fill="#9ca3af")
    draw.text((930, 255), "AI / 芯片 / 机器人", font=subtitle_font, fill="#111827")
    draw.line((930, 305, 1335, 305), fill="#e5e7eb", width=3)
    entry_title_bottom = draw_wrapped(
        draw, data["entry_title"], (930, 340), section_font, "#111827", 24, 36, max_lines=3
    )
    source_y = entry_title_bottom + 10
    draw.text((930, source_y), f"Source: {data['entry_source']}", font=small_font, fill="#6b7280")
    why_y = source_y + 48
    draw.text((930, why_y), "Why selected", font=small_font, fill="#9a3412")
    draw_wrapped(draw, data["entry_selected"], (930, why_y + 32), body_font, "#374151", 16, 32, max_lines=3)

    pill(draw, (930, 742, 1110, 792), "👍 useful", "#dcfce7", "#166534", small_font)
    pill(draw, (1130, 742, 1310, 792), "👎 dislike", "#fee2e2", "#991b1b", small_font)
    draw.text((930, 840), "Mobile-first briefing with explainable selection", font=small_font, fill="#6b7280")

    image.save(ASSET_DIR / "brief-preview.png")


def render_feedback_preview(data):
    image = Image.new("RGB", (1600, 960), "#eef4ff")
    draw = ImageDraw.Draw(image)

    title_font = load_font(TITLE_FONT, 52)
    subtitle_font = load_font(TITLE_FONT, 26)
    section_font = load_font(TITLE_FONT, 24)
    body_font = load_font(BODY_FONT, 22)
    small_font = load_font(BODY_FONT, 18)

    draw.rounded_rectangle((50, 50, 1550, 910), radius=40, fill="#f8fbff")
    draw.text((90, 100), "Feishu Delivery + Feedback Learning", font=title_font, fill="#0f172a")
    draw.text((90, 170), "One click feeds the next ranking pass", font=subtitle_font, fill="#475569")

    draw.rounded_rectangle((90, 250, 760, 820), radius=30, fill="#ffffff")
    draw.text((125, 290), "飞书卡片预览", font=section_font, fill="#111827")
    entry_title_bottom = draw_wrapped(
        draw, data["entry_title"], (125, 340), section_font, "#1f2937", 28, 34, max_lines=3
    )
    source_y = entry_title_bottom + 12
    draw.text((125, source_y), f"来源：{data['entry_source']}", font=small_font, fill="#64748b")
    draw_wrapped(
        draw,
        "Why selected：" + data["entry_selected"],
        (125, source_y + 42),
        body_font,
        "#334155",
        28,
        30,
        max_lines=3,
    )
    pill(draw, (125, 680, 300, 732), "👍 有用", "#dcfce7", "#166534", body_font)
    pill(draw, (325, 680, 500, 732), "👎 不想看", "#fee2e2", "#991b1b", body_font)
    draw.text((125, 770), "Long connection callback -> SQLite feedback", font=small_font, fill="#64748b")

    draw.rounded_rectangle((865, 250, 1470, 820), radius=30, fill="#ffffff")
    draw.text((900, 290), "偏好状态变化", font=section_font, fill="#111827")
    rows = [
        ("source_weight", "Asianometry", "+0.12"),
        ("source_weight", "Agility", "+0.12"),
        ("topic_weight", "芯片", "+0.06"),
        ("topic_weight", "机器人", "+0.06"),
        ("exploration_slot", "保持 1 个探索位", "ON"),
    ]
    y = 350
    for label, key, value in rows:
        draw.rounded_rectangle((900, y, 1430, y + 76), radius=22, fill="#f8fafc")
        draw.text((926, y + 16), label, font=small_font, fill="#64748b")
        draw.text((1130, y + 16), key, font=body_font, fill="#0f172a")
        draw.text((1330, y + 16), value, font=body_font, fill="#0f766e")
        y += 96

    draw.line((760, 536, 865, 536), fill="#60a5fa", width=6)
    draw.polygon([(865, 536), (840, 520), (840, 552)], fill="#60a5fa")
    draw.text((760, 500), "feedback", font=small_font, fill="#2563eb")

    image.save(ASSET_DIR / "feedback-preview.png")


def main():
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    data = parse_brief()
    render_brief_preview(data)
    render_feedback_preview(data)


if __name__ == "__main__":
    main()
