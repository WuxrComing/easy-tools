import io
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

import fitz
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"


@dataclass
class PdfDoc:
    name: str
    data: bytes
    page_count: int


DOCS: dict[str, PdfDoc] = {}


def parse_page_spec(spec: str, page_count: int) -> list[int]:
    if page_count <= 0:
        raise ValueError("PDF 没有可导出的页面。")

    text = (spec or "").strip()
    if not text:
        return list(range(page_count))

    normalized = (
        text.replace("，", ",")
        .replace("；", ",")
        .replace("、", ",")
        .replace("~", "-")
        .replace("～", "-")
        .replace("—", "-")
        .replace("–", "-")
        .replace("至", "-")
        .replace("到", "-")
    )

    pages: list[int] = []
    seen: set[int] = set()

    for raw in normalized.split(","):
        token = raw.strip()
        if not token:
            continue

        m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", token)
        if m:
            start = int(m.group(1))
            end = int(m.group(2))
            if start > end:
                start, end = end, start
            if start < 1 or end > page_count:
                raise ValueError(f"页码范围超出限制：{token}（有效范围 1-{page_count}）")
            for p in range(start, end + 1):
                p0 = p - 1
                if p0 not in seen:
                    seen.add(p0)
                    pages.append(p0)
            continue

        if token.isdigit():
            p = int(token)
            if p < 1 or p > page_count:
                raise ValueError(f"页码超出限制：{p}（有效范围 1-{page_count}）")
            p0 = p - 1
            if p0 not in seen:
                seen.add(p0)
                pages.append(p0)
            continue

        raise ValueError(f"无法识别的页码输入：{token}。示例：9-11 或 1,3,9-11")

    if not pages:
        raise ValueError("未解析到有效页码。")
    return pages


def get_doc_or_404(doc_id: str) -> PdfDoc:
    doc = DOCS.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在或已过期")
    return doc


class ConvertPayload(BaseModel):
    doc_id: str
    page_spec: str = ""
    dpi: int = Field(150, ge=72, le=600)
    image_format: str = "PNG"


app = FastAPI(title="Easy Tools Web API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


app.mount("/web", StaticFiles(directory=WEB_DIR), name="web")


@app.post("/api/pdf/upload")
async def upload_pdf(file: UploadFile = File(...)) -> JSONResponse:
    filename = file.filename or "document.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="仅支持 PDF 文件")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")

    try:
        doc = fitz.open(stream=data, filetype="pdf")
        page_count = doc.page_count
        doc.close()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"PDF 解析失败: {e}")

    if page_count <= 0:
        raise HTTPException(status_code=400, detail="PDF 没有可用页面")

    doc_id = uuid.uuid4().hex
    DOCS[doc_id] = PdfDoc(name=filename, data=data, page_count=page_count)

    return JSONResponse({"doc_id": doc_id, "name": filename, "page_count": page_count})


@app.get("/api/pdf/meta/{doc_id}")
def pdf_meta(doc_id: str) -> JSONResponse:
    doc = get_doc_or_404(doc_id)
    return JSONResponse({"doc_id": doc_id, "name": doc.name, "page_count": doc.page_count})


@app.get("/api/pdf/preview")
def pdf_preview(
    doc_id: str,
    page: int = Query(1, ge=1),
    mode: str = Query("fit-width"),
    viewport_width: int = Query(900, ge=100, le=4000),
    viewport_height: int = Query(900, ge=100, le=4000),
    zoom_percent: int = Query(100, ge=20, le=400),
) -> StreamingResponse:
    doc_info = get_doc_or_404(doc_id)
    if page > doc_info.page_count:
        raise HTTPException(status_code=400, detail="页码超出范围")

    doc = fitz.open(stream=doc_info.data, filetype="pdf")
    pdf_page = doc.load_page(page - 1)

    page_w = pdf_page.rect.width
    page_h = pdf_page.rect.height

    if mode == "fit-page":
        ratio = min((viewport_width - 20) / page_w, (viewport_height - 20) / page_h)
    elif mode == "percent":
        ratio = zoom_percent / 100.0
    else:
        ratio = (viewport_width - 20) / page_w

    ratio = max(0.2, min(ratio, 4.0))
    pix = pdf_page.get_pixmap(matrix=fitz.Matrix(ratio, ratio), alpha=False)
    doc.close()

    return StreamingResponse(io.BytesIO(pix.tobytes("png")), media_type="image/png")


@app.post("/api/pdf/convert")
def pdf_convert(payload: ConvertPayload) -> StreamingResponse:
    doc_info = get_doc_or_404(payload.doc_id)
    image_format = payload.image_format.upper()
    if image_format not in ("PNG", "JPG", "JPEG"):
        raise HTTPException(status_code=400, detail="仅支持 PNG/JPG")

    doc = fitz.open(stream=doc_info.data, filetype="pdf")
    try:
        page_indices = parse_page_spec(payload.page_spec, doc.page_count)
    except ValueError as e:
        doc.close()
        raise HTTPException(status_code=400, detail=str(e))

    zoom = payload.dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    images = []
    widths = []
    heights = []

    for idx in page_indices:
        page = doc.load_page(idx)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        images.append(img)
        widths.append(img.width)
        heights.append(img.height)

    doc.close()

    max_width = max(widths)
    total_height = sum(heights)
    canvas = Image.new("RGB", (max_width, total_height), color=(255, 255, 255))

    y = 0
    for img in images:
        x = (max_width - img.width) // 2
        canvas.paste(img, (x, y))
        y += img.height

    out = io.BytesIO()
    if image_format in ("JPG", "JPEG"):
        canvas.save(out, format="JPEG", quality=95)
        media_type = "image/jpeg"
        ext = "jpg"
    else:
        canvas.save(out, format="PNG")
        media_type = "image/png"
        ext = "png"

    out.seek(0)
    file_base = Path(doc_info.name).stem
    headers = {"Content-Disposition": f'attachment; filename="{file_base}_long.{ext}"'}
    return StreamingResponse(out, media_type=media_type, headers=headers)


@app.delete("/api/pdf/{doc_id}")
def remove_pdf(doc_id: str) -> JSONResponse:
    DOCS.pop(doc_id, None)
    return JSONResponse({"ok": True})
