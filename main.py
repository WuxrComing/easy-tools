import os
import re
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

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QSpinBox,
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

            percent = int(((i + 1) / total) * 90)
            self.progress.emit(percent)

        doc.close()

        max_width = max(widths)
        total_height = sum(heights)
        long_image = Image.new("RGB", (max_width, total_height), color=(255, 255, 255))

        current_y = 0
        for idx, img in enumerate(pil_images):
            x = (max_width - img.width) // 2
            long_image.paste(img, (x, current_y))
            current_y += img.height

            percent = 90 + int(((idx + 1) / len(pil_images)) * 10)
            self.progress.emit(min(percent, 100))

        save_format = options.image_format.upper()
        save_kwargs = {}
        if save_format in ("JPG", "JPEG"):
            save_format = "JPEG"
            save_kwargs["quality"] = 95

        output_dir = os.path.dirname(os.path.abspath(options.output_path))
        os.makedirs(output_dir, exist_ok=True)
        long_image.save(options.output_path, format=save_format, **save_kwargs)


class MainWindow(QMainWindow):
    PREVIEW_ZOOMS = [50, 75, 100, 125, 150, 200]

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PDF 转长图工具")
        self.resize(1150, 720)

        self.worker_thread: QThread | None = None
        self.worker: ConvertWorker | None = None
        self.preview_doc: fitz.Document | None = None
        self.current_page_index = 0

        self.pdf_path_edit = QLineEdit()
        self.output_path_edit = QLineEdit()
        self.page_range_edit = QLineEdit()
        self.dpi_spin = QSpinBox()
        self.dpi_spin.setObjectName("largeSpin")
        self.dpi_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.format_combo = QComboBox()
        self.progress_bar = QProgressBar()
        self.convert_btn = QPushButton("开始转换")

        self.preview_label = QLabel("请选择 PDF 以预览")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumHeight(500)

        self.page_spin = QSpinBox()
        self.page_spin.setObjectName("largeSpin")
        self.page_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.total_pages_label = QLabel("/ 0")
        self.zoom_combo = QComboBox()

        self._apply_native_defaults()
        self._init_ui()

    def _apply_native_defaults(self) -> None:
        for widget in (
            self.pdf_path_edit,
            self.output_path_edit,
            self.page_range_edit,
            self.dpi_spin,
            self.page_spin,
            self.format_combo,
            self.zoom_combo,
        ):
            widget.setFixedHeight(34)

    def _init_ui(self) -> None:
        root = QWidget()
        main_layout = QHBoxLayout(root)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)

        left_panel = QFrame()
        left_panel.setObjectName("leftPanel")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(20, 20, 20, 20)
        left_layout.setSpacing(14)

        title = QLabel("PDF 转长图")
        title.setObjectName("titleLabel")
        subtitle = QLabel("PyQt6 原生界面 / 支持 PDF 实时预览")
        subtitle.setObjectName("subtitleLabel")
        left_layout.addWidget(title)
        left_layout.addWidget(subtitle)

        form_box = QGroupBox("转换参数")
        form = QFormLayout(form_box)
        form.setSpacing(10)

        pdf_row = QHBoxLayout()
        pdf_row.addWidget(self.pdf_path_edit)
        pdf_btn = QPushButton("选择 PDF")
        pdf_btn.clicked.connect(self.choose_pdf)
        pdf_row.addWidget(pdf_btn)
        form.addRow("PDF 文件", self._wrap(pdf_row))

        out_row = QHBoxLayout()
        out_row.addWidget(self.output_path_edit)
        out_btn = QPushButton("保存为")
        out_btn.clicked.connect(self.choose_output)
        out_row.addWidget(out_btn)
        form.addRow("输出图片", self._wrap(out_row))

        self.page_range_edit.setPlaceholderText("留空=全部页，例如：9-11 或 1,3,9-11")
        form.addRow("页码范围", self.page_range_edit)

        self.dpi_spin.setRange(72, 600)
        self.dpi_spin.setValue(150)
        form.addRow("渲染 DPI", self.dpi_spin)

        self.format_combo.addItems(["PNG", "JPG"])
        form.addRow("图片格式", self.format_combo)

        left_layout.addWidget(form_box)

        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        left_layout.addWidget(QLabel("转换进度"))
        left_layout.addWidget(self.progress_bar)

        self.convert_btn.clicked.connect(self.start_convert)
        left_layout.addWidget(self.convert_btn)
        left_layout.addStretch(1)

        preview_panel = QFrame()
        preview_panel.setObjectName("previewPanel")
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(16, 16, 16, 16)
        preview_layout.setSpacing(10)

        toolbar = QHBoxLayout()
        prev_btn = QPushButton("上一页")
        prev_btn.clicked.connect(self.prev_page)
        next_btn = QPushButton("下一页")
        next_btn.clicked.connect(self.next_page)

        self.page_spin.setRange(1, 1)
        self.page_spin.valueChanged.connect(self.goto_page)
        self.zoom_combo.addItems([f"{z}%" for z in self.PREVIEW_ZOOMS])
        self.zoom_combo.setCurrentText("100%")
        self.zoom_combo.currentTextChanged.connect(self.refresh_preview)

        toolbar.addWidget(prev_btn)
        toolbar.addWidget(next_btn)
        toolbar.addSpacing(8)
        toolbar.addWidget(QLabel("页码"))
        toolbar.addWidget(self.page_spin)
        toolbar.addWidget(self.total_pages_label)
        toolbar.addStretch(1)
        toolbar.addWidget(QLabel("缩放"))
        toolbar.addWidget(self.zoom_combo)
        preview_layout.addLayout(toolbar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll.setWidget(self.preview_label)
        preview_layout.addWidget(scroll)

        main_layout.addWidget(left_panel, 1)
        main_layout.addWidget(preview_panel, 2)

        self.setCentralWidget(root)

    @staticmethod
    def _wrap(row_layout: QHBoxLayout) -> QWidget:
        w = QWidget()
        w.setLayout(row_layout)
        return w

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._close_preview_doc()
        super().closeEvent(event)

    def _close_preview_doc(self) -> None:
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
        base = os.path.splitext(path)[0]
        self.output_path_edit.setText(f"{base}_long.{ext}")

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
        self._close_preview_doc()
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

    def render_preview_page(self) -> None:
        if self.preview_doc is None:
            self.preview_label.setText("请选择 PDF 以预览")
            self.preview_label.setPixmap(QPixmap())
            return

        zoom_text = self.zoom_combo.currentText().replace("%", "")
        try:
            zoom_ratio = int(zoom_text) / 100.0
        except ValueError:
            zoom_ratio = 1.0

        page = self.preview_doc.load_page(self.current_page_index)
        matrix = fitz.Matrix(zoom_ratio, zoom_ratio)
        pix = page.get_pixmap(matrix=matrix, alpha=False)

        image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()
        qpix = QPixmap.fromImage(image)

        self.preview_label.setPixmap(qpix)
        self.preview_label.resize(qpix.size())

    @pyqtSlot()
    def start_convert(self) -> None:
        pdf_path = self.pdf_path_edit.text().strip()
        output_path = self.output_path_edit.text().strip()

        if not pdf_path:
            QMessageBox.warning(self, "提示", "请先选择 PDF 文件。")
            return

        if not output_path:
            QMessageBox.warning(self, "提示", "请先选择输出图片路径。")
            return

        if self.preview_doc is None or self.pdf_path_edit.text().strip() != pdf_path:
            self.load_preview(pdf_path)

        if self.preview_doc is None:
            QMessageBox.warning(self, "提示", "PDF 加载失败，请重新选择文件。")
            return

        try:
            parse_page_spec(self.page_range_edit.text().strip(), self.preview_doc.page_count)
        except ValueError as e:
            QMessageBox.warning(self, "页码范围错误", str(e))
            return

        img_format = self.format_combo.currentText().upper()
        if img_format == "PNG" and not output_path.lower().endswith(".png"):
            output_path += ".png"
            self.output_path_edit.setText(output_path)
        if img_format == "JPG" and not (
            output_path.lower().endswith(".jpg") or output_path.lower().endswith(".jpeg")
        ):
            output_path += ".jpg"
            self.output_path_edit.setText(output_path)

        options = ConvertOptions(
            pdf_path=pdf_path,
            output_path=output_path,
            dpi=self.dpi_spin.value(),
            image_format=img_format,
            page_spec=self.page_range_edit.text().strip(),
        )

        self.convert_btn.setEnabled(False)
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
        QMessageBox.information(self, "完成", f"转换成功:\n{output_path}")

    @pyqtSlot(str)
    def on_failed(self, error: str) -> None:
        self.convert_btn.setEnabled(True)
        QMessageBox.critical(self, "转换失败", error)


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
