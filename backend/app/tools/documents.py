"""用户私有 PDF 导出：固定目录、内容寻址、原子写入与认证下载。"""

import hashlib
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from xml.sax.saxutils import escape

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from backend.app.core.config import DATA_DIR
from backend.app.infrastructure.store import store

EXPORT_DIR = DATA_DIR / "exports"
_font_lock = threading.Lock()


class ReportSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    heading: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=12000)


def report_font():
    with _font_lock:
        if "ShiguangCN" in pdfmetrics.getRegisteredFontNames():
            return "ShiguangCN"
        configured = os.getenv("PDF_FONT_PATH", "")
        path = Path(configured) if configured else Path("C:/Windows/Fonts/simsun.ttc")
        if path.is_file():
            pdfmetrics.registerFont(TTFont("ShiguangCN", str(path)))
            return "ShiguangCN"
        if configured:
            raise ValueError("PDF_FONT_PATH 指定的字体不存在")
        if "STSong-Light" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        return "STSong-Light"


def render_pdf(path, title, sections, sources):
    font = report_font()
    body = ParagraphStyle(
        "Body", fontName=font, fontSize=10.5, leading=18, wordWrap="CJK", spaceAfter=8
    )
    heading = ParagraphStyle(
        "Heading",
        parent=body,
        fontSize=13,
        leading=21,
        textColor=colors.HexColor("#20536b"),
        spaceBefore=12,
        keepWithNext=True,
    )
    cover = ParagraphStyle(
        "Title", parent=body, fontSize=21, leading=30, alignment=TA_CENTER, spaceAfter=18
    )
    story = [
        Paragraph(escape(title), cover),
        Paragraph(
            "拾光电商咨询资料 | 内容由对话整理，重要信息请以所列来源及平台实际审核为准。", body
        ),
        Spacer(1, 8),
    ]
    for section in sections:
        story.append(Paragraph(escape(section["heading"]), heading))
        # 不执行用户/模型提供的HTML，也不读取任何远程图片或本机文件。
        for line in section["content"].splitlines():
            if line.strip():
                story.append(Paragraph(escape(line), body))
    if sources:
        story.append(Paragraph("参考来源", heading))
        for index, url in enumerate(sources, 1):
            story.append(Paragraph(escape(f"{index}. {url}"), body))

    def footer(canvas, doc):
        canvas.setFont(font, 9)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawCentredString(A4[0] / 2, 25, f"拾光电商咨询资料 | {doc.page}")

    SimpleDocTemplate(
        str(path),
        pagesize=A4,
        rightMargin=44,
        leftMargin=44,
        topMargin=40,
        bottomMargin=45,
        title=title,
        author="拾光电商助手",
    ).build(story, onFirstPage=footer, onLaterPages=footer)


def public_document(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "format": "pdf",
        "download_url": f"/documents/{row['id']}/download",
        "created": row["created"],
    }


def list_documents(user_id, run_id=None):
    with store.connect() as db:
        rows = db.execute(
            "SELECT * FROM documents WHERE user_id=? AND (? IS NULL OR run_id=?) ORDER BY created DESC LIMIT 50",
            (user_id, run_id, run_id),
        ).fetchall()
    return [public_document(row) for row in rows]


def owned_document(identifier, user_id):
    if not re.fullmatch(r"[a-f0-9]{64}", identifier):
        raise HTTPException(404, "文件不存在")
    with store.connect() as db:
        row = db.execute(
            "SELECT * FROM documents WHERE id=? AND user_id=?", (identifier, user_id)
        ).fetchone()
    if not row:
        raise HTTPException(404, "文件不存在")
    path = EXPORT_DIR / (identifier + ".pdf")
    if not path.is_file():
        raise HTTPException(404, "文件已不可用，请重新导出")
    return dict(row), path


def create_report(user_id, run_id, title, sections, sources=()):
    if not user_id or not run_id or not 1 <= len(title.strip()) <= 120:
        raise ValueError("缺少用户、任务或有效标题")
    sections = [ReportSection.model_validate(s).model_dump() for s in sections]
    if not 1 <= len(sections) <= 20 or sum(len(s["content"]) for s in sections) > 30000:
        raise ValueError("报告限1至20节、总正文不超过30000字")
    sources = list(dict.fromkeys(str(s)[:2000] for s in sources))[:20]
    payload = json.dumps(
        [user_id, run_id, title, sections, sources], ensure_ascii=False, sort_keys=True
    )
    identifier = hashlib.sha256(payload.encode()).hexdigest()
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = EXPORT_DIR / (identifier + ".pdf")
    if not path.exists():
        temporary = EXPORT_DIR / (uuid.uuid4().hex + ".tmp")
        try:
            render_pdf(temporary, title, sections, sources)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    with store.connect() as db:
        db.execute(
            "INSERT OR IGNORE INTO documents VALUES(?,?,?,?,?)",
            (identifier, user_id, run_id, title, time.time()),
        )
        row = db.execute("SELECT * FROM documents WHERE id=?", (identifier,)).fetchone()
    return public_document(row)
