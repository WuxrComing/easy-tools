import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass

try:
    import fitz  # PyMuPDF
except ModuleNotFoundError:
    import pymupdf as fitz
from PIL import Image

if sys.platform == "win32":
    for path_item in sys.path:
        qt_bin = os.path.join(path_item, "PyQt6", "Qt6", "bin")
        if os.path.isdir(qt_bin):
            try:
                os.add_dll_directory(qt_bin)
            except (AttributeError, FileNotFoundError):
                pass
            os.environ["PATH"] = qt_bin + os.pathsep + os.environ.get("PATH", "")
            break
elif sys.platform == "darwin":
    if "QT_QPA_PLATFORM_PLUGIN_PATH" not in os.environ:
        for path_item in sys.path:
            qt_platforms = os.path.join(path_item, "PyQt6", "Qt6", "plugins", "platforms")
            if os.path.isdir(qt_platforms):
                os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = qt_platforms
                break

from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QThread,
    Qt,
    pyqtSignal,
    pyqtSlot,
)
from PyQt6.QtGui import QIcon, QImage, QPixmap
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsOpacityEffect,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QComboBox,
)


@dataclass
class ConvertOptions:
    pdf_path: str
    output_path: str
    dpi: int
    image_format: str
    page_spec: str


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


class ConvertWorker(QObject):
    progress = pyqtSignal(int)
    finished = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, options: ConvertOptions) -> None:
        super().__init__()
        self.options = options

    @pyqtSlot()
    def run(self) -> None:
        try:
            self._convert()
            self.finished.emit(self.options.output_path)
        except Exception as e:
            self.failed.emit(str(e))

    def _convert(self) -> None:
        options = self.options
        if not os.path.isfile(options.pdf_path):
            raise FileNotFoundError("PDF 文件不存在。")

        doc = fitz.open(options.pdf_path)
        if doc.page_count == 0:
            doc.close()
            raise ValueError("PDF 没有可渲染的页面。")

        page_indices = parse_page_spec(options.page_spec, doc.page_count)
        zoom = options.dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)

        pil_images = []
        widths = []
        heights = []

        total = len(page_indices)
        for i, page_index in enumerate(page_indices):
            page = doc.load_page(page_index)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            pil_images.append(img)
            widths.append(img.width)
            heights.append(img.height)
            self.progress.emit(int(((i + 1) / total) * 90))

        doc.close()

        max_width = max(widths)
        total_height = sum(heights)
        long_image = Image.new("RGB", (max_width, total_height), color=(255, 255, 255))

        current_y = 0
        for idx, img in enumerate(pil_images):
            x = (max_width - img.width) // 2
            long_image.paste(img, (x, current_y))
            current_y += img.height
            self.progress.emit(min(90 + int(((idx + 1) / len(pil_images)) * 10), 100))

        save_format = options.image_format.upper()
        save_kwargs = {}
        if save_format in ("JPG", "JPEG"):
            save_format = "JPEG"
            save_kwargs["quality"] = 95

        output_dir = os.path.dirname(os.path.abspath(options.output_path))
        os.makedirs(output_dir, exist_ok=True)
        long_image.save(options.output_path, format=save_format, **save_kwargs)


class CollapsibleSection(QWidget):
    def __init__(self, title: str, content: QWidget, expanded: bool = False) -> None:
        super().__init__()
        self.toggle_btn = QToolButton()
        self.toggle_btn.setText(title)
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(expanded)
        self.toggle_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle_btn.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)

        self.content = content
        self.content.setVisible(expanded)
        self.content.setMaximumHeight(self.content.sizeHint().height() if expanded else 0)
        self._expanded = expanded

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.toggle_btn)
        layout.addWidget(self.content)

        self.anim = QPropertyAnimation(self.content, b"maximumHeight", self)
        self.anim.setDuration(180)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.finished.connect(self._on_anim_finished)

        self.toggle_btn.toggled.connect(self._on_toggled)

    @pyqtSlot(bool)
    def _on_toggled(self, checked: bool) -> None:
        self.toggle_btn.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        self._expanded = checked
        self.anim.stop()
        if checked:
            self.content.setVisible(True)
            self.anim.setStartValue(self.content.maximumHeight())
            self.anim.setEndValue(max(self.content.sizeHint().height(), 1))
        else:
            self.anim.setStartValue(max(self.content.height(), 1))
            self.anim.setEndValue(0)
        self.anim.start()

    @pyqtSlot()
    def _on_anim_finished(self) -> None:
        if not self._expanded:
            self.content.setVisible(False)


class HomePage(QWidget):
    open_pdf_tool = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("Easy Tools")
        title.setStyleSheet("font-size: 22px; font-weight: 600;")
        desc = QLabel("工具集合主页。选择左侧工具快速进入。")

        card = QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 14, 14, 14)
        card_layout.setSpacing(8)
        card_layout.addWidget(QLabel("PDF 转长图"))
        card_layout.addWidget(QLabel("支持页码区间、实时预览与导出长图。"))

        open_btn = QPushButton("进入工具")
        open_btn.setFixedWidth(110)
        open_btn.clicked.connect(self.open_pdf_tool)
        card_layout.addWidget(open_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        layout.addWidget(title)
        layout.addWidget(desc)
        layout.addWidget(card)
        layout.addStretch(1)


class PdfLongImagePage(QWidget):
    PREVIEW_ZOOMS = ["适应宽度", "适应页面", "75%", "100%", "125%", "150%", "200%"]

    def __init__(self) -> None:
        super().__init__()

        self.worker_thread: QThread | None = None
        self.worker: ConvertWorker | None = None
        self.preview_doc: fitz.Document | None = None
        self.current_page_index = 0
        self.last_output_path = ""
        self.external_open_supported = self._detect_external_open_support()

        self.pdf_path_edit = QLineEdit()
        self.output_path_edit = QLineEdit()
        self.page_range_edit = QLineEdit()
        self.dpi_spin = QSpinBox()
        self.format_combo = QComboBox()

        self.convert_btn = QPushButton("开始转换")
        self.open_file_btn = QPushButton("打开文件")
        self.open_dir_btn = QPushButton("打开目录")
        self.progress_bar = QProgressBar()
        self.progress_hint = QLabel("正在导出，请稍候...")

        self.preview_label = QLabel("请选择 PDF 以预览")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_opacity = QGraphicsOpacityEffect(self.preview_label)
        self.preview_label.setGraphicsEffect(self.preview_opacity)
        self.preview_fade = QPropertyAnimation(self.preview_opacity, b"opacity", self)
        self.preview_fade.setDuration(160)
        self.preview_fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.page_spin = QSpinBox()
        self.total_pages_label = QLabel("/ 0")
        self.zoom_combo = QComboBox()
        self.preview_scroll = QScrollArea()

        self._apply_defaults()
        self._build_ui()

    def _apply_defaults(self) -> None:
        self.dpi_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.page_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)

        # 根据平台调整控件高度：Mac 上原生控件更高，用 Fusion 后统一用像素值
        # Fusion 样式下不同平台字体行高不同，用平台分支保持视觉一致
        row_h = 32 if sys.platform == "darwin" else 30
        btn_h = 30 if sys.platform == "darwin" else 28

        for w in (
            self.pdf_path_edit,
            self.output_path_edit,
            self.page_range_edit,
            self.dpi_spin,
            self.page_spin,
            self.format_combo,
            self.zoom_combo,
            self.convert_btn,
        ):
            w.setFixedHeight(row_h)

        self.open_file_btn.setFixedHeight(btn_h)
        self.open_dir_btn.setFixedHeight(btn_h)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        header = QLabel("PDF 转长图")
        header.setStyleSheet("font-size: 20px; font-weight: 600;")
        root.addWidget(header)

        body = QHBoxLayout()
        body.setSpacing(10)

        control_panel = QFrame()
        control_panel.setFrameShape(QFrame.Shape.StyledPanel)
        control_panel.setMaximumWidth(400)
        control_layout = QVBoxLayout(control_panel)
        control_layout.setContentsMargins(10, 10, 10, 10)
        control_layout.setSpacing(10)

        basic_group = QGroupBox("基础设置")
        basic_form = QFormLayout(basic_group)
        basic_form.setSpacing(8)

        pdf_row = QHBoxLayout()
        pdf_row.addWidget(self.pdf_path_edit)
        pick_btn = QPushButton("选择 PDF")
        pick_btn.clicked.connect(self.choose_pdf)
        pdf_row.addWidget(pick_btn)
        basic_form.addRow("PDF 文件", self._wrap(pdf_row))

        out_row = QHBoxLayout()
        out_row.addWidget(self.output_path_edit)
        out_btn = QPushButton("保存为")
        out_btn.clicked.connect(self.choose_output)
        out_row.addWidget(out_btn)
        basic_form.addRow("导出到", self._wrap(out_row))

        control_layout.addWidget(basic_group)

        advanced_widget = QWidget()
        adv_form = QFormLayout(advanced_widget)
        adv_form.setSpacing(8)

        self.page_range_edit.setPlaceholderText("留空=全部页，例如：9-11")
        adv_form.addRow("页码范围", self.page_range_edit)

        self.dpi_spin.setRange(72, 600)
        self.dpi_spin.setValue(150)
        adv_form.addRow("清晰度(DPI)", self.dpi_spin)

        self.format_combo.addItems(["PNG", "JPG"])
        adv_form.addRow("图片格式", self.format_combo)

        control_layout.addWidget(CollapsibleSection("高级选项", advanced_widget, expanded=False))

        action_row = QHBoxLayout()
        self.convert_btn.clicked.connect(self.start_convert)
        self.open_file_btn.setEnabled(False)
        self.open_dir_btn.setEnabled(False)
        if not self.external_open_supported:
            self.open_file_btn.setToolTip("当前系统未检测到可用的文件打开命令")
            self.open_dir_btn.setToolTip("当前系统未检测到可用的目录打开命令")
        self.open_file_btn.clicked.connect(self.open_output_file)
        self.open_dir_btn.clicked.connect(self.open_output_dir)

        action_row.addWidget(self.convert_btn)
        action_row.addWidget(self.open_file_btn)
        action_row.addWidget(self.open_dir_btn)
        control_layout.addLayout(action_row)

        self.progress_bar.setRange(0, 100)
        self.progress_bar.setVisible(False)
        self.progress_hint.setVisible(False)
        control_layout.addWidget(self.progress_hint)
        control_layout.addWidget(self.progress_bar)
        control_layout.addStretch(1)

        preview_panel = QFrame()
        preview_panel.setFrameShape(QFrame.Shape.StyledPanel)
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(10, 10, 10, 10)
        preview_layout.setSpacing(8)

        toolbar = QHBoxLayout()
        prev_btn = QPushButton("上一页")
        next_btn = QPushButton("下一页")
        prev_btn.clicked.connect(self.prev_page)
        next_btn.clicked.connect(self.next_page)

        self.page_spin.setRange(1, 1)
        self.page_spin.valueChanged.connect(self.goto_page)

        self.zoom_combo.addItems(self.PREVIEW_ZOOMS)
        self.zoom_combo.setCurrentText("适应宽度")
        self.zoom_combo.currentTextChanged.connect(self.refresh_preview)

        toolbar.addWidget(prev_btn)
        toolbar.addWidget(next_btn)
        toolbar.addSpacing(6)
        toolbar.addWidget(QLabel("页码"))
        toolbar.addWidget(self.page_spin)
        toolbar.addWidget(self.total_pages_label)
        toolbar.addStretch(1)
        toolbar.addWidget(QLabel("显示"))
        toolbar.addWidget(self.zoom_combo)
        preview_layout.addLayout(toolbar)

        self.preview_scroll.setWidgetResizable(True)
        self.preview_scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.preview_scroll.setWidget(self.preview_label)
        self.preview_scroll.viewport().installEventFilter(self)
        preview_layout.addWidget(self.preview_scroll, 1)

        body.addWidget(control_panel)
        body.addWidget(preview_panel, 1)
        root.addLayout(body, 1)

    @staticmethod
    def _wrap(row_layout: QHBoxLayout) -> QWidget:
        w = QWidget()
        w.setLayout(row_layout)
        return w

    def eventFilter(self, watched, event):  # type: ignore[override]
        if watched is self.preview_scroll.viewport() and event.type() == QEvent.Type.Resize:
            mode = self.zoom_combo.currentText()
            if mode in ("适应宽度", "适应页面") and self.preview_doc is not None:
                self.render_preview_page()
        return super().eventFilter(watched, event)

    def cleanup(self) -> None:
        if self.preview_doc is not None:
            self.preview_doc.close()
            self.preview_doc = None

    @pyqtSlot()
    def choose_pdf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 PDF 文件", "", "PDF Files (*.pdf)")
        if not path:
            return

        self.pdf_path_edit.setText(path)
        ext = self.format_combo.currentText().lower()
        self.output_path_edit.setText(f"{os.path.splitext(path)[0]}_long.{ext}")
        self.load_preview(path)

    @pyqtSlot()
    def choose_output(self) -> None:
        file_filter = "PNG Image (*.png);;JPEG Image (*.jpg)"
        path, selected = QFileDialog.getSaveFileName(self, "保存长图", "", file_filter)
        if not path:
            return
        if selected.startswith("PNG") and not path.lower().endswith(".png"):
            path += ".png"
        if selected.startswith("JPEG") and not (path.lower().endswith(".jpg") or path.lower().endswith(".jpeg")):
            path += ".jpg"
        self.output_path_edit.setText(path)

    def load_preview(self, pdf_path: str) -> None:
        self.cleanup()
        try:
            self.preview_doc = fitz.open(pdf_path)
        except Exception as e:
            self.preview_label.setText(f"预览加载失败:\n{e}")
            self.page_spin.setRange(1, 1)
            self.total_pages_label.setText("/ 0")
            return

        if self.preview_doc.page_count == 0:
            self.preview_label.setText("PDF 无可预览页面")
            self.page_spin.setRange(1, 1)
            self.total_pages_label.setText("/ 0")
            return

        self.current_page_index = 0
        self.page_spin.blockSignals(True)
        self.page_spin.setRange(1, self.preview_doc.page_count)
        self.page_spin.setValue(1)
        self.page_spin.blockSignals(False)
        self.total_pages_label.setText(f"/ {self.preview_doc.page_count}")
        self.render_preview_page()

    @pyqtSlot()
    def prev_page(self) -> None:
        if self.preview_doc is None or self.current_page_index <= 0:
            return
        self.current_page_index -= 1
        self.page_spin.blockSignals(True)
        self.page_spin.setValue(self.current_page_index + 1)
        self.page_spin.blockSignals(False)
        self.render_preview_page()

    @pyqtSlot()
    def next_page(self) -> None:
        if self.preview_doc is None or self.current_page_index >= self.preview_doc.page_count - 1:
            return
        self.current_page_index += 1
        self.page_spin.blockSignals(True)
        self.page_spin.setValue(self.current_page_index + 1)
        self.page_spin.blockSignals(False)
        self.render_preview_page()

    @pyqtSlot(int)
    def goto_page(self, page_num: int) -> None:
        if self.preview_doc is None:
            return
        self.current_page_index = max(0, min(page_num - 1, self.preview_doc.page_count - 1))
        self.render_preview_page()

    @pyqtSlot()
    def refresh_preview(self) -> None:
        self.render_preview_page()

    def _compute_zoom_ratio(self, page) -> float:
        mode = self.zoom_combo.currentText()
        if mode.endswith("%"):
            try:
                return max(0.2, min(int(mode.replace("%", "")) / 100.0, 4.0))
            except ValueError:
                return 1.0

        viewport = self.preview_scroll.viewport().size()
        if viewport.width() <= 0 or viewport.height() <= 0:
            return 1.0

        page_w = page.rect.width
        page_h = page.rect.height
        if page_w <= 0 or page_h <= 0:
            return 1.0

        fit_w = max((viewport.width() - 20) / page_w, 0.2)
        fit_h = max((viewport.height() - 20) / page_h, 0.2)

        if mode == "适应页面":
            return min(fit_w, fit_h)
        return fit_w

    def render_preview_page(self) -> None:
        if self.preview_doc is None:
            self.preview_label.setText("请选择 PDF 以预览")
            self.preview_label.setPixmap(QPixmap())
            return

        page = self.preview_doc.load_page(self.current_page_index)
        zoom_ratio = self._compute_zoom_ratio(page)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom_ratio, zoom_ratio), alpha=False)

        image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()
        qpix = QPixmap.fromImage(image)

        self.preview_label.setPixmap(qpix)
        self.preview_label.resize(qpix.size())
        self.preview_fade.stop()
        self.preview_opacity.setOpacity(0.0)
        self.preview_fade.setStartValue(0.0)
        self.preview_fade.setEndValue(1.0)
        self.preview_fade.start()

    @pyqtSlot()
    def start_convert(self) -> None:
        pdf_path = self.pdf_path_edit.text().strip()
        output_path = self.output_path_edit.text().strip()

        if not pdf_path:
            QMessageBox.warning(self, "提示", "请先选择 PDF 文件。")
            return
        if not output_path:
            QMessageBox.warning(self, "提示", "请先选择输出路径。")
            return

        if self.preview_doc is None or self.pdf_path_edit.text().strip() != pdf_path:
            self.load_preview(pdf_path)
        if self.preview_doc is None:
            QMessageBox.warning(self, "提示", "PDF 加载失败，请重新选择文件。")
            return

        page_spec = self.page_range_edit.text().strip()
        try:
            parse_page_spec(page_spec, self.preview_doc.page_count)
        except ValueError as e:
            QMessageBox.warning(self, "页码范围错误", str(e))
            return

        img_format = self.format_combo.currentText().upper()
        if img_format == "PNG" and not output_path.lower().endswith(".png"):
            output_path += ".png"
            self.output_path_edit.setText(output_path)
        if img_format == "JPG" and not (output_path.lower().endswith(".jpg") or output_path.lower().endswith(".jpeg")):
            output_path += ".jpg"
            self.output_path_edit.setText(output_path)

        options = ConvertOptions(
            pdf_path=pdf_path,
            output_path=output_path,
            dpi=self.dpi_spin.value(),
            image_format=img_format,
            page_spec=page_spec,
        )

        self.convert_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_hint.setVisible(True)
        self.progress_bar.setValue(0)

        self.worker_thread = QThread(self)
        self.worker = ConvertWorker(options)
        self.worker.moveToThread(self.worker_thread)

        self.worker_thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.progress_bar.setValue)
        self.worker.finished.connect(self.on_finished)
        self.worker.failed.connect(self.on_failed)

        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.failed.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)

        self.worker_thread.start()

    @pyqtSlot(str)
    def on_finished(self, output_path: str) -> None:
        self.convert_btn.setEnabled(True)
        self.progress_bar.setValue(100)
        self.progress_bar.setVisible(False)
        self.progress_hint.setVisible(False)

        self.last_output_path = output_path
        self.open_file_btn.setEnabled(self.external_open_supported)
        self.open_dir_btn.setEnabled(self.external_open_supported)
        QMessageBox.information(self, "完成", f"转换成功:\n{output_path}")

    @pyqtSlot(str)
    def on_failed(self, error: str) -> None:
        self.convert_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.progress_hint.setVisible(False)
        QMessageBox.critical(self, "转换失败", error)

    @pyqtSlot()
    def open_output_file(self) -> None:
        if not self.last_output_path or not os.path.isfile(self.last_output_path):
            return
        self._open_path(self.last_output_path)

    @pyqtSlot()
    def open_output_dir(self) -> None:
        if not self.last_output_path:
            return
        folder = os.path.dirname(os.path.abspath(self.last_output_path))
        if os.path.isdir(folder):
            self._open_path(folder)

    @staticmethod
    def _detect_external_open_support() -> bool:
        if sys.platform == "win32":
            return hasattr(os, "startfile")
        if sys.platform == "darwin":
            return shutil.which("open") is not None
        if sys.platform.startswith("linux"):
            return shutil.which("xdg-open") is not None
        return False

    def _open_path(self, path: str) -> None:
        try:
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", path], check=False)
            elif sys.platform.startswith("linux"):
                subprocess.run(["xdg-open", path], check=False)
            else:
                QMessageBox.warning(self, "提示", "当前系统暂不支持自动打开路径。")
        except Exception as e:
            QMessageBox.warning(self, "提示", f"打开失败：{e}")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Easy Tools")
        self.setWindowIcon(_pdf_tool_icon())
        self.resize(1320, 860)

        self.nav_collapsed = False
        self.nav_panel = QFrame()
        self.nav_anim_group = QParallelAnimationGroup(self)
        self.nav_min_anim = QPropertyAnimation(self.nav_panel, b"minimumWidth", self)
        self.nav_max_anim = QPropertyAnimation(self.nav_panel, b"maximumWidth", self)
        for anim in (self.nav_min_anim, self.nav_max_anim):
            anim.setDuration(180)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self.nav_anim_group.addAnimation(anim)

        self.nav_list = QListWidget()
        self.nav_header = QLabel("工具集合")
        self.nav_toggle_btn = QToolButton()

        self.mini_nav = QWidget()
        self.mini_home_btn = QToolButton()
        self.mini_pdf_btn = QToolButton()

        self.stack = QStackedWidget()
        self.home_page = HomePage()
        self.pdf_page = PdfLongImagePage()

        self._build_ui()

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        style = self.style()
        home_icon = style.standardIcon(QStyle.StandardPixmap.SP_DesktopIcon)
        pdf_icon = _pdf_tool_icon()
        future_icon = style.standardIcon(QStyle.StandardPixmap.SP_DirIcon)

        self.nav_panel.setFrameShape(QFrame.Shape.StyledPanel)
        self.nav_panel.setMinimumWidth(220)
        self.nav_panel.setMaximumWidth(220)
        nav_layout = QVBoxLayout(self.nav_panel)
        nav_layout.setContentsMargins(8, 8, 8, 8)
        nav_layout.setSpacing(8)

        header_row = QHBoxLayout()
        self.nav_header.setStyleSheet("font-size: 15px; font-weight: 600;")
        self.nav_toggle_btn.setAutoRaise(True)
        self.nav_toggle_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._update_nav_toggle_icon()
        self.nav_toggle_btn.clicked.connect(self.toggle_nav)
        header_row.addWidget(self.nav_header)
        header_row.addStretch(1)
        header_row.addWidget(self.nav_toggle_btn)
        nav_layout.addLayout(header_row)

        home_item = QListWidgetItem("工作台")
        home_item.setIcon(home_icon)
        pdf_item = QListWidgetItem("PDF 转长图")
        pdf_item.setIcon(pdf_icon)
        future_item = QListWidgetItem("图片工具（即将支持）")
        future_item.setIcon(future_icon)
        future_item.setFlags(future_item.flags() & ~Qt.ItemFlag.ItemIsEnabled)

        self.nav_list.addItem(home_item)
        self.nav_list.addItem(pdf_item)
        self.nav_list.addItem(future_item)
        self.nav_list.setCurrentRow(0)
        self.nav_list.currentRowChanged.connect(self.on_nav_changed)
        nav_layout.addWidget(self.nav_list)

        mini_layout = QVBoxLayout(self.mini_nav)
        mini_layout.setContentsMargins(0, 0, 0, 0)
        mini_layout.setSpacing(6)

        self.mini_home_btn.setIcon(home_icon)
        self.mini_pdf_btn.setIcon(pdf_icon)
        self.mini_home_btn.setToolTip("工作台")
        self.mini_pdf_btn.setToolTip("PDF 转长图")
        self.mini_home_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.mini_pdf_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.mini_home_btn.setAutoRaise(True)
        self.mini_pdf_btn.setAutoRaise(True)
        self.mini_home_btn.setFixedSize(44, 36)
        self.mini_pdf_btn.setFixedSize(44, 36)
        self.mini_home_btn.clicked.connect(lambda: self.nav_list.setCurrentRow(0))
        self.mini_pdf_btn.clicked.connect(lambda: self.nav_list.setCurrentRow(1))

        mini_layout.addWidget(self.mini_home_btn)
        mini_layout.addWidget(self.mini_pdf_btn)
        mini_layout.addStretch(1)
        self.mini_nav.setVisible(False)
        nav_layout.addWidget(self.mini_nav)

        self.stack.addWidget(self.home_page)
        self.stack.addWidget(self.pdf_page)
        self.home_page.open_pdf_tool.connect(self.open_pdf_tool)

        layout.addWidget(self.nav_panel)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(root)

    @pyqtSlot()
    def toggle_nav(self) -> None:
        self.set_nav_collapsed(not self.nav_collapsed)

    def set_nav_collapsed(self, collapsed: bool) -> None:
        self.nav_collapsed = collapsed
        start_w = self.nav_panel.width()
        end_w = 72 if collapsed else 220

        self.nav_anim_group.stop()
        self.nav_min_anim.setStartValue(start_w)
        self.nav_min_anim.setEndValue(end_w)
        self.nav_max_anim.setStartValue(start_w)
        self.nav_max_anim.setEndValue(end_w)

        self.nav_header.setVisible(not collapsed)
        self.nav_list.setVisible(not collapsed)
        self.mini_nav.setVisible(collapsed)
        self._update_nav_toggle_icon()
        self.nav_anim_group.start()

    def _update_nav_toggle_icon(self) -> None:
        style = self.style()
        if self.nav_collapsed:
            self.nav_toggle_btn.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowRight))
            self.nav_toggle_btn.setToolTip("展开导航")
        else:
            self.nav_toggle_btn.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowLeft))
            self.nav_toggle_btn.setToolTip("收起导航")

    @pyqtSlot(int)
    def on_nav_changed(self, row: int) -> None:
        if row in (0, 1):
            self.stack.setCurrentIndex(row)
            if row == 1:
                self.set_nav_collapsed(True)

    @pyqtSlot()
    def open_pdf_tool(self) -> None:
        self.nav_list.setCurrentRow(1)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.pdf_page.cleanup()
        super().closeEvent(event)


def _pdf_tool_icon() -> QIcon:
    """从 assets/ 目录加载 PDF 工具图标，若不存在则降级为标准图标。"""
    asset = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "pdf_tool.png")
    if os.path.isfile(asset):
        return QIcon(asset)
    from PyQt6.QtWidgets import QApplication, QStyle
    return QApplication.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)


def _hex(color) -> str:  # type: ignore[no-untyped-def]
    """QPalette QColor → CSS #rrggbb 字符串。"""
    return "#{:02x}{:02x}{:02x}".format(color.red(), color.green(), color.blue())


def _lighter(color, factor: int = 120):  # type: ignore[no-untyped-def]
    from PyQt6.QtGui import QColor
    return QColor(color).lighter(factor)


def _darker(color, factor: int = 120):  # type: ignore[no-untyped-def]
    from PyQt6.QtGui import QColor
    return QColor(color).darker(factor)


def _configure_app(app: QApplication) -> None:
    """统一跨平台显示风格，自动适配深色/浅色模式。"""
    from PyQt6.QtGui import QFont, QPalette

    # 使用 Fusion 样式：Qt 内置跨平台风格，在 Win/Mac/Linux 表现一致
    app.setStyle("Fusion")

    # 设置平台对应的系统字体，保证中文显示正常
    if sys.platform == "darwin":
        font = QFont("-apple-system", 13)
    elif sys.platform == "win32":
        font = QFont("Microsoft YaHei UI", 9)
    else:
        font = QFont("Noto Sans CJK SC", 10)
    app.setFont(font)

    # 从调色板读取实际颜色，自动兼容深色/浅色模式
    pal = app.palette()
    is_dark = pal.color(QPalette.ColorRole.Window).lightness() < 128

    # --- 基础色 ---
    btn      = pal.color(QPalette.ColorRole.Button)
    btn_text = pal.color(QPalette.ColorRole.ButtonText)
    base     = pal.color(QPalette.ColorRole.Base)
    text     = pal.color(QPalette.ColorRole.Text)
    mid      = pal.color(QPalette.ColorRole.Mid)

    # 按钮渐变：顶部略亮，底部略暗
    btn_top    = _hex(_lighter(btn, 108))
    btn_bot    = _hex(_darker(btn, 108))
    btn_border = _hex(_darker(btn, 140) if not is_dark else _lighter(btn, 80))

    # 悬停：蓝色语调，叠加在按钮色上
    hover_top  = _hex(_lighter(btn, 115))
    hover_bot  = _hex(btn)
    hover_brd  = "#4a90d9"

    # 按下：比按钮色深一档
    press_top  = _hex(_darker(btn, 108))
    press_bot  = _hex(_darker(btn, 120))

    # 禁用
    dis_bg     = _hex(_lighter(btn, 103) if not is_dark else _darker(btn, 110))
    dis_text   = _hex(pal.color(QPalette.ColorRole.PlaceholderText))
    dis_border = _hex(mid)

    # 输入框
    input_bg   = _hex(base)
    input_text = _hex(text)
    input_brd  = _hex(_darker(base, 150) if not is_dark else _lighter(base, 160))

    app.setStyleSheet(f"""
        QGroupBox {{
            font-weight: 600;
            margin-top: 8px;
            padding-top: 6px;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 8px;
            top: 0px;
        }}
        QLineEdit, QSpinBox, QComboBox {{
            padding: 2px 6px;
            border: 1px solid {input_brd};
            border-radius: 4px;
            background: {input_bg};
            color: {input_text};
        }}
        QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
            border-color: #4a90d9;
        }}
        QPushButton {{
            padding: 4px 14px;
            border: 1px solid {btn_border};
            border-radius: 4px;
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                        stop:0 {btn_top}, stop:1 {btn_bot});
            color: {_hex(btn_text)};
        }}
        QPushButton:hover {{
            border-color: {hover_brd};
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                        stop:0 {hover_top}, stop:1 {hover_bot});
        }}
        QPushButton:pressed {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                        stop:0 {press_top}, stop:1 {press_bot});
            border-color: #3a7ac9;
        }}
        QPushButton:disabled {{
            background: {dis_bg};
            border-color: {dis_border};
            color: {dis_text};
        }}
        QProgressBar {{
            border: 1px solid {input_brd};
            border-radius: 4px;
            text-align: center;
        }}
        QProgressBar::chunk {{
            border-radius: 4px;
            background-color: #4a90d9;
        }}
        QScrollArea {{ border: none; }}
    """)


def main() -> None:
    app = QApplication(sys.argv)
    _configure_app(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

