"""Build a searchable, single A4 resume locally; never crop or discard content."""

import base64
import binascii
import io
import os
import re
import threading
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Flowable, Paragraph, Spacer


_FONT_LOCK = threading.Lock()
INK = colors.HexColor("#253342")
MUTED = colors.HexColor("#5c6977")
ACCENT = colors.HexColor("#246b75")
LINE = colors.HexColor("#d7e2e5")
PANEL = colors.HexColor("#f3f6f8")
PHOTO_MAX_WIDTH, PHOTO_MAX_HEIGHT = 44, 58
CAPACITY_ERROR = "简历内容较多，压成一页会使文字过小。请先精简较长的项目描述后再导出；原简历内容已保留。"


def _fonts():
    with _FONT_LOCK:
        if not {"ResumeSans", "ResumeSansBold"}.issubset(pdfmetrics.getRegisteredFontNames()):
            directory = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
            for regular, bold in (("msyh.ttc", "msyhbd.ttc"), ("Deng.ttf", "Dengb.ttf")):
                try:
                    pdfmetrics.registerFont(TTFont("ResumeSans", str(directory / regular), subfontIndex=0))
                    pdfmetrics.registerFont(TTFont("ResumeSansBold", str(directory / bold), subfontIndex=0))
                    pdfmetrics.registerFontFamily("ResumeSans", normal="ResumeSans", bold="ResumeSansBold", italic="ResumeSans", boldItalic="ResumeSansBold")
                    break
                except (OSError, ValueError):
                    continue
            else:
                raise ValueError("缺少 PDF 中文字体，请安装微软雅黑或等线后重试。")


def _text(value, limit=6000):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError("简历导出内容格式不正确或过长。")
    return " ".join(value.replace("\x00", "").split())


def validate_resume(payload):
    if not isinstance(payload, dict):
        raise ValueError("简历导出内容格式不正确。")
    result = {key: _text(payload.get(key, ""), 160) for key in ("name", "role")}
    photo = payload.get("photo", "")
    if not isinstance(photo, str) or len(photo) > 120_000:
        raise ValueError("简历照片格式不正确。")
    result["photo"] = None
    result["photo_dimensions"] = None
    if photo:
        match = re.fullmatch(r"data:image/jpeg;base64,([A-Za-z0-9+/]+={0,2})", photo)
        if not match:
            raise ValueError("简历照片必须是 JPG 图片。")
        try:
            photo_bytes = base64.b64decode(match.group(1), validate=True)
            image_width, image_height = ImageReader(io.BytesIO(photo_bytes)).getSize()
        except (ValueError, OSError, binascii.Error) as exc:
            raise ValueError("简历照片无法读取。") from exc
        if not photo_bytes or image_width > 2000 or image_height > 2000:
            raise ValueError("简历照片尺寸过大。")
        result["photo"] = photo_bytes
        result["photo_dimensions"] = (image_width, image_height)
    contacts = payload.get("contacts", [])
    if not isinstance(contacts, list) or len(contacts) > 8:
        raise ValueError("简历联系方式格式不正确。")
    result["contacts"] = [_text(item, 240) for item in contacts]
    for column in ("main", "aside", "footer"):
        sections = payload.get(column, [])
        if not isinstance(sections, list) or len(sections) > 16:
            raise ValueError("简历栏目格式不正确。")
        result[column] = []
        for section in sections:
            if not isinstance(section, dict):
                raise ValueError("简历栏目格式不正确。")
            items = section.get("items", [])
            if not isinstance(items, list) or len(items) > 400:
                raise ValueError("简历条目过多，请先精简后导出。")
            clean = []
            for item in items:
                if not isinstance(item, dict) or item.get("type") not in ("title", "meta", "label", "paragraph", "bullet"):
                    raise ValueError("简历条目格式不正确。")
                text = _text(item.get("text", ""))
                if text:
                    clean.append({"type": item["type"], "text": text})
            if clean:
                result[column].append({"title": _text(section.get("title", ""), 80), "items": clean})
    if not any(result[key] for key in ("main", "aside", "footer")):
        raise ValueError("简历中暂无可导出的内容。")
    return result


def _paragraph(text, size, *, bold=False, color=INK, bullet=False, leading=1.28):
    text = re.sub(r"([\u3400-\u9fff][。！？；])", r"<nobr>\1</nobr>", text)
    style = ParagraphStyle(
        "resume", fontName="ResumeSansBold" if bold else "ResumeSans", fontSize=size,
        leading=size * leading, wordWrap="CJK", textColor=color, alignment=TA_LEFT,
        leftIndent=size * .95 if bullet else 0, firstLineIndent=0, splitLongWords=True,
        bulletIndent=0, bulletFontName="ResumeSans", bulletFontSize=size * .8,
        bulletColor=ACCENT,
    )
    return Paragraph(text, style, bulletText="•" if bullet else None)


class _SectionHeading(Flowable):
    def __init__(self, title, size, compact=False, tight=False):
        super().__init__()
        self.title = _paragraph(escape(title), size + 2, bold=True, color=ACCENT, leading=1.26 if tight else 1.28)
        self.size = size
        self.compact = compact
        self.spacing = .6 if tight else 1

    def wrap(self, width, height):
        self.width = width
        self.title_height = self.title.wrap(width - 9, height)[1]
        self.height = self.title_height + self.size * .65 * self.spacing
        return width, self.height

    def draw(self):
        self.canv.setFillColor(ACCENT)
        self.canv.roundRect(0, self.height - self.title_height + 2, 2.2, self.title_height - 4, 1, fill=1, stroke=0)
        self.title.drawOn(self.canv, 8, self.height - self.title_height)
        if not self.compact:
            self.canv.setStrokeColor(LINE)
            self.canv.setLineWidth(.4)
            self.canv.line(0, 1, self.width, 1)


class _EntryHeading(Flowable):
    """Keep a distinct title and date; wrap long dates instead of colliding."""

    def __init__(self, title, metadata, size):
        super().__init__()
        self.size = size
        self.title = _paragraph(escape(title), size + .75, bold=True, leading=1.25)
        self.metadata = metadata

    def wrap(self, width, height):
        self.width = width
        self.title_width = width
        self.meta = None
        self.inline = False
        if self.metadata:
            self.meta = _paragraph(escape("  ·  ".join(self.metadata)), self.size - .4, color=MUTED, leading=1.26)
            natural = pdfmetrics.stringWidth("  ·  ".join(self.metadata), "ResumeSans", self.size - .4)
            # Measure title and metadata together rather than reserving an arbitrary
            # percentage for dates. Only wrap when the two actually collide.
            if natural < width - 10:
                self.title_width = width - natural - 10
                self.inline = self.title.wrap(self.title_width, height)[1] <= (self.size + .75) * 1.26
            if not self.inline:
                self.title_width = width
            self.meta_width = natural + .1 if self.inline else width
            self.meta_height = self.meta.wrap(self.meta_width, height)[1]
        self.title_height = self.title.wrap(self.title_width, height)[1]
        self.height = self.title_height
        if self.meta and not self.inline:
            self.height += self.meta_height + 1.5
        return width, self.height

    def draw(self):
        self.title.drawOn(self.canv, 0, self.height - self.title_height)
        if self.meta:
            self.meta.drawOn(self.canv, self.width - self.meta_width if self.inline else 0,
                             self.height - self.meta_height - .5 if self.inline else 0)


def _flows(sections, size, *, sidebar=False, tight=False):
    flow = []
    spacing = .75 if tight else 1
    for section in sections:
        if flow:
            flow.append(Spacer(1, size * .9 * spacing))
        flow.append(_SectionHeading(section["title"], size, compact=sidebar, tight=tight))
        flow.append(Spacer(1, size * .35 * spacing))
        items = section["items"]
        index = 0
        while index < len(items):
            item = items[index]
            kind, text = item["type"], escape(item["text"])
            if kind == "title":
                if index:
                    flow.append(Spacer(1, size * .65 * spacing))
                metadata = []
                while index + 1 < len(items) and items[index + 1]["type"] == "meta":
                    index += 1
                    metadata.append(items[index]["text"])
                flow.append(_EntryHeading(item["text"], metadata, size))
                flow.append(Spacer(1, size * .25 * spacing))
                index += 1
                continue
            elif kind == "label":
                if index:
                    flow.append(Spacer(1, size * (.4 if sidebar else .25) * spacing))
                text = "<b>" + text + "</b>"
                if not sidebar and index + 1 < len(items) and items[index + 1]["type"] == "paragraph":
                    index += 1
                    text += "：" + escape(items[index]["text"])
            flow.append(_paragraph(text, size, color=MUTED if kind == "meta" else INK,
                                   bullet=kind == "bullet", leading=1.26 if tight else 1.28))
            flow.append(Spacer(1, size * (.2 if sidebar else .15) * spacing))
            index += 1
    return flow


def _height(flow, width):
    return sum(item.wrap(width, 10000)[1] for item in flow)


def _draw(canvas, flow, x, top, width):
    for item in flow:
        _, height = item.wrap(width, 10000)
        item.drawOn(canvas, x, top - height)
        top -= height
    return top


def _page_profile(data, *, tight):
    page_width, page_height = A4
    margin, gap, panel_padding = (20, 10, 6) if tight else (24, 14, 8)
    width = page_width - margin * 2
    photo_width = photo_height = 0
    if data["photo"]:
        image_width, image_height = data["photo_dimensions"]
        photo_scale = min(PHOTO_MAX_WIDTH / image_width, PHOTO_MAX_HEIGHT / image_height)
        photo_width, photo_height = image_width * photo_scale, image_height * photo_scale
    header_width = width - photo_width - 12 if data["photo"] else width
    name_size = 20 if tight else 22
    # Header and footer are measured too, including long contact information.
    header = [_EntryHeading(data["name"], [], name_size)] if data["name"] else []
    # Role aligns alongside the name when it fits; a long role wraps below it.
    role = _paragraph(escape(data["role"]), 10, color=ACCENT) if data["role"] else None
    role_inline = bool(role and header and pdfmetrics.stringWidth(data["role"], "ResumeSans", 10) < header_width * .55
                       and pdfmetrics.stringWidth(data["name"], "ResumeSansBold", name_size + .75) < header_width * .4)
    if role and not role_inline:
        header.append(role)
    if data["contacts"]:
        header.append(Spacer(1, 4 if tight else 6))
        header.append(_paragraph(escape("   ·   ".join(data["contacts"])), 8.3, color=MUTED))
    header_height = max(_height(header, header_width), photo_height)
    top = page_height - margin - header_height - (16 if tight else 20)
    return dict(margin=margin, gap=gap, panel_padding=panel_padding, width=width,
                header=header, header_width=header_width, role=role, role_inline=role_inline,
                photo_width=photo_width, photo_height=photo_height, top=top, tight=tight)


def _fit_resume(data):
    # Reject obviously impossible requests without rewrapping huge paragraphs for
    # every candidate. Use the smallest metadata font and the whole usable page
    # as a conservative lower bound, so normal resumes still get a full fit search.
    minimum_size = 6.8
    advance = sum(
        min(pdfmetrics.stringWidth(row["text"], font, minimum_size)
            for font in ("ResumeSans", "ResumeSansBold"))
        for column in ("main", "aside", "footer")
        for section in data[column] for row in section["items"]
    )
    if advance * minimum_size * 1.2 > (A4[0] - 40) * (A4[1] - 40):
        raise ValueError(CAPACITY_ERROR)
    profiles = [_page_profile(data, tight=False), _page_profile(data, tight=True)]
    # Search using the final typography so extra whitespace does not appear
    # after fitting; never crop text, add a page, or shrink below 6.8 pt.
    for step in range(92, 67, -1):
        size = step / 10
        for profile in profiles:
            width, gap, padding = profile["width"], profile["gap"], profile["panel_padding"]
            tight = profile["tight"]
            footer = _flows(data["footer"], size, tight=tight)
            footer_height = _height(footer, width)
            body_bottom = profile["margin"] + (footer_height + (10 if tight else 14) if footer else 0)
            available = profile["top"] - body_bottom
            main = _flows(data["main"], size, tight=tight)
            aside = _flows(data["aside"], size if tight else size + .1, sidebar=True, tight=tight)
            ratios = (.69, .70, .71, .68, .72, .67, .73, .66, .74, .65) if main and aside else (1,)
            for ratio in ratios:
                main_width = (width - gap) * ratio if main and aside else width
                aside_width = width - gap - main_width - padding * 2 if main and aside else width - padding * 2
                if _height(main, main_width) <= available and _height(aside, aside_width) + padding * 2 <= available:
                    return dict(profile, size=size, main=main, aside=aside, footer=footer,
                                main_width=main_width, aside_width=aside_width,
                                footer_height=footer_height, body_bottom=body_bottom)
    raise ValueError(CAPACITY_ERROR)


def render_resume_pdf(payload):
    data = validate_resume(payload)
    _fonts()
    layout = _fit_resume(data)
    page_width, page_height = A4
    margin, width, top = layout["margin"], layout["width"], layout["top"]
    main, aside, footer = layout["main"], layout["aside"], layout["footer"]
    main_width, aside_width = layout["main_width"], layout["aside_width"]
    stream = io.BytesIO()
    canvas = Canvas(stream, pagesize=A4, pageCompression=1)
    canvas.setTitle((data["name"] or "个人") + " - 单页简历")
    canvas.setAuthor(data["name"])
    _draw(canvas, layout["header"], margin, page_height - margin, layout["header_width"])
    if layout["role_inline"]:
        role = layout["role"]
        role_width = pdfmetrics.stringWidth(data["role"], "ResumeSans", 10) + 1
        role_height = role.wrap(role_width, 10000)[1]
        role.drawOn(canvas, margin + layout["header_width"] - role_width, page_height - margin - role_height - 6)
    if data["photo"]:
        photo_width, photo_height = layout["photo_width"], layout["photo_height"]
        photo_x = page_width - margin - photo_width
        photo_y = page_height - margin - photo_height
        canvas.drawImage(ImageReader(io.BytesIO(data["photo"])), photo_x, photo_y,
                         width=photo_width, height=photo_height)
    canvas.setStrokeColor(ACCENT)
    canvas.setLineWidth(1.6)
    canvas.line(margin, top + 10, margin + 42, top + 10)
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(.5)
    canvas.line(margin + 48, top + 10, page_width - margin, top + 10)
    if main:
        _draw(canvas, main, margin, top, main_width)
    if aside:
        aside_x = margin + main_width + layout["gap"] if main else margin
        panel_padding = layout["panel_padding"]
        panel_bottom = top - _height(aside, aside_width) - panel_padding * 2
        canvas.setFillColor(PANEL)
        canvas.roundRect(aside_x, panel_bottom, aside_width + panel_padding * 2, top - panel_bottom, 5, fill=1, stroke=0)
        _draw(canvas, aside, aside_x + panel_padding, top - panel_padding, aside_width)
    if footer:
        footer_top = margin + layout["footer_height"]
        _draw(canvas, footer, margin, footer_top, width)
    canvas.showPage()
    canvas.save()
    return stream.getvalue()
