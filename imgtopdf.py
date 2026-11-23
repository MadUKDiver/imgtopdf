import sys
import os
from pathlib import Path
from io import BytesIO
from PIL import Image

import img2pdf
import configparser

from pypdf import PdfReader, PdfWriter, Transformation
from natsort import natsorted

from PySide6.QtCore import QObject, QThread, Signal, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QComboBox,
    QListWidget, QListWidgetItem, QFileDialog, QProgressBar, QMessageBox,
    QGroupBox, QFormLayout, QAbstractItemView, QCheckBox,
    QDialog, QLineEdit, QPlainTextEdit
)

VERSION = "2.1"

PAGE_SIZES = {
    "A1": (594, 841),
    "A2": (420, 594),
    "A3": (297, 420),
    "A4": (210, 297),
    "A5": (148, 210),
    "A6": (105, 148),
    "A7": (74, 105),
    "Letter": (215.9, 279.4),
}

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".bmp",
    ".tif", ".tiff", ".webp"
}

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys._MEIPASS)
else:
    APP_DIR = Path(__file__).resolve().parent

ICON_FILE = APP_DIR / "imgtopdf.ico"


def get_settings_directory():
    """
    Return the dedicated imgtopdf settings directory.
    """

    appdata = os.environ.get("APPDATA")

    if appdata:
        return Path(appdata) / "imgtopdf"

    return Path.home() / ".config" / "imgtopdf"

SETTINGS_DIR = get_settings_directory()
SETTINGS_FILE = SETTINGS_DIR / "settings.ini"


def is_image(path):
    return Path(path).suffix.lower() in IMAGE_EXTENSIONS


def natural_sort(files, merge_mode):
    if merge_mode == "Ascending":
        return natsorted(files, key=lambda p: str(p).lower())

    if merge_mode == "Descending":
        return natsorted(
            files,
            key=lambda p: str(p).lower(),
            reverse=True
        )

    # None and Custom retain the supplied order.
    return list(files)


def get_page_dimensions(image_width, image_height,
                        page_name, orientation):

    width_mm, height_mm = PAGE_SIZES[page_name]

    if orientation == "Auto":
        if image_width > image_height:
            width_mm, height_mm = height_mm, width_mm

    elif orientation == "Landscape":
        width_mm, height_mm = max(width_mm, height_mm), min(
            width_mm, height_mm
        )

    else:
        width_mm, height_mm = min(width_mm, height_mm), max(
            width_mm, height_mm
        )

    # Convert millimetres to PDF points.
    return (
        width_mm * 72 / 25.4,
        height_mm * 72 / 25.4
    )


def add_image_to_pdf(writer, filename, scale,
                     orientation, page_size, rotation):

    # Check for transparency using Pillow.
    with Image.open(filename) as source:

        has_alpha = (
            "A" in source.getbands()
            or "transparency" in source.info
        )

        if has_alpha:

            # Convert to RGBA to handle all transparency types.
            image = source.convert("RGBA")

            # Create a white background.
            background = Image.new(
                "RGBA",
                image.size,
                (255, 255, 255, 255)
            )

            # Composite the image onto white.
            background.alpha_composite(image)

            # Convert to RGB and save as an in-memory PNG.
            flattened_image = BytesIO()

            background.convert("RGB").save(
                flattened_image,
                format="PNG"
            )

            flattened_image.seek(0)

            image_pdf = img2pdf.convert(
                flattened_image,
                first_frame_only=True
            )

        else:

            # imgtopdf embeds supported image data without
            # unnecessarily recompressing the original pixels.
            image_pdf = img2pdf.convert(
                str(filename),
                first_frame_only=True
            )

    reader = PdfReader(BytesIO(image_pdf))
    source_page = reader.pages[0]

    # Get original image dimensions.
    source_width = float(source_page.mediabox.width)
    source_height = float(source_page.mediabox.height)

    # Rotation angles in PDF coordinates.
    # Positive PDF rotation is anticlockwise.
    rotation_angles = {
        "None": 0,
        "+90° clockwise": -90,
        "-90° anticlockwise": 90,
        "180°": 180
    }
    
    angle = rotation_angles.get(rotation, 0)

    # Determine rotated image dimensions.
    if angle in (90, -90):
        rotated_width = source_height
        rotated_height = source_width
    else:
        rotated_width = source_width
        rotated_height = source_height

    # Determine destination page dimensions.
    page_width, page_height = get_page_dimensions(
        rotated_width,
        rotated_height,
        page_size,
        orientation
    )

    # Calculate scaling.
    if scale == "Stretch":
        draw_width = page_width
        draw_height = page_height

    elif scale == "None":
        draw_width = rotated_width
        draw_height = rotated_height

    else:
        factor = min(
            page_width / rotated_width,
            page_height / rotated_height
        )

        draw_width = rotated_width * factor
        draw_height = rotated_height * factor

    scale_x = draw_width / rotated_width
    scale_y = draw_height / rotated_height

    # Calculate the PDF transformation matrix.
    # Matrix format: (a, b, c, d, e, f)

    if angle == -90:
        # +90° clockwise
        matrix = (
            0, -scale_y, scale_x, 0, page_width - draw_width, page_height
        )

    elif angle == 90:
        # -90° anticlockwise
        matrix = (
            0, scale_y, -scale_x, 0, draw_width, 0
        )

    elif angle == 180:
        # 180°
        matrix = (
            -scale_x, 0, 0, -scale_y, page_width, draw_height
        )

    else:
        # No rotation
        matrix = (
            scale_x, 0, 0, scale_y, 0, page_height - draw_height
        )

    transformation = Transformation(ctm=matrix)
    # Create the correctly sized destination page.
    destination_page = writer.add_blank_page(
        width=page_width,
        height=page_height
    )

    # Place  original or rotated image content on the page.
    destination_page.merge_transformed_page(
        source_page,
        transformation
    )


def save_pdf(writer, filename):
    with open(filename, "wb") as output:
        writer.write(output)


def convert_images(files, scale, merge_mode,
                   orientation, page_size, rotation,
                   progress_callback=None):

    files = [
        Path(f) for f in files if is_image(f)
    ]

    if not files:
        raise ValueError("No supported image files were supplied.")

    files = natural_sort(files, merge_mode)

    results = []
    errors = []

    total = len(files)

    if merge_mode == "None":

        # Individual PDF for every image.
        for index, filename in enumerate(files):

            try:
                writer = PdfWriter()

                add_image_to_pdf(
                    writer,
                    filename,
                    scale,
                    orientation,
                    page_size,
                    rotation
                )

                output = unique_output_path(
                    filename.with_suffix(".pdf")
                )

                save_pdf(writer, output)
                results.append(str(output))

            except Exception as error:
                errors.append(
                    f"{filename.name}: {error}"
                )

            if progress_callback:
                progress_callback(
                    int((index + 1) / total * 100),
                    filename.name
                )

    else:

        # All images combined into one PDF.
        writer = PdfWriter()
        successful_pages = 0

        output = unique_output_path(
            files[0].with_suffix(".pdf")
        )

        for index, filename in enumerate(files):

            try:
                add_image_to_pdf(
                    writer,
                    filename,
                    scale,
                    orientation,
                    page_size,
                    rotation
                )

                successful_pages += 1

            except Exception as error:
                errors.append(
                    f"{filename.name}: {error}"
                )

            if progress_callback:
                progress_callback(
                    int((index + 1) / total * 100),
                    filename.name
                )

        if successful_pages:
            save_pdf(writer, output)
            results.append(str(output))

    return results, errors


def unique_output_path(path):
    """
    Avoid overwriting an existing PDF.
    """
    if not path.exists():
        return path

    counter = 2

    while True:
        candidate = path.with_name(
            f"{path.stem}_{counter}{path.suffix}"
        )

        if not candidate.exists():
            return candidate

        counter += 1


class ConversionWorker(QObject):
    progress = Signal(int, str)
    finished = Signal(list, list)
    failed = Signal(str)

    def __init__(self, files, settings):
        super().__init__()
        self.files = files
        self.settings = settings

    def run(self):
        try:
            results, errors = convert_images(
                self.files,
                self.settings["scale"],
                self.settings["merge"],
                self.settings["orientation"],
                self.settings["page_size"],
                self.settings["rotation"],
                self.progress.emit
            )

            self.finished.emit(results, errors)

        except Exception as error:
            self.failed.emit(str(error))


class DropArea(QLabel):
    files_dropped = Signal(list)

    def __init__(self):
        super().__init__(
            "DROP IMAGE FILES HERE\n\n"
            "or use the Browse button below"
        )

        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(80)
        self.setAcceptDrops(True)

        self.setStyleSheet("""
            QLabel {
                border: 2px dashed #5599CC;
                border-radius: 10px;
                background-color: #F0F5FA;
                color: #315A78;
                font-size: 15px;
                padding: 10px;
            }
        """)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        files = []

        for url in event.mimeData().urls():
            path = url.toLocalFile()

            if os.path.isfile(path) and is_image(path):
                files.append(path)

        if files:
            self.files_dropped.emit(files)

        event.acceptProposedAction()


class FileListWidget(QListWidget):
    files_reordered = Signal()

    def __init__(self):
        super().__init__()

        self.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )

        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)

        self.setDragDropMode(
            QAbstractItemView.DragDropMode.InternalMove
        )

        self.setDefaultDropAction(
            Qt.DropAction.MoveAction
        )

    def dropEvent(self, event):
        original_order = [
            self.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.count())
        ]

        super().dropEvent(event)

        new_order = [
            self.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.count())
        ]

        if original_order != new_order:
            self.files_reordered.emit()


class CompletionDialog(QDialog):

    def __init__(self, results, errors, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Conversion completed")
        self.setMinimumWidth(480)

        self.output_folders = list(dict.fromkeys(
            str(Path(result).parent)
            for result in results
        ))

        layout = QVBoxLayout(self)

        title = QLabel("Conversion completed")
        title.setStyleSheet(
            "font-size: 18px; font-weight: bold;"
        )
        layout.addWidget(title)

        message = QLabel(
            f"Successfully created {len(results)} PDF file(s)."
        )
        layout.addWidget(message)

        if self.output_folders:

            layout.addWidget(QLabel("Output location:"))

            self.folder_combo = QComboBox()
            self.folder_combo.addItems(
                self.output_folders
            )
            layout.addWidget(self.folder_combo)

        if errors:
            error_label = QLabel(
                f"{len(errors)} file(s) could not be converted."
            )
            error_label.setStyleSheet("color: #B52B27;")
            layout.addWidget(error_label)

            error_details = QPlainTextEdit()
            error_details.setReadOnly(True)
            error_details.setPlainText(
                "\n".join(errors)
            )
            error_details.setMaximumHeight(110)
            layout.addWidget(error_details)

        buttons = QHBoxLayout()

        if self.output_folders:

            open_button = QPushButton(
                "Open Output Folder"
            )

            open_button.clicked.connect(
                self.open_output_folder
            )

            buttons.addWidget(open_button)

        buttons.addStretch()

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)

        buttons.addWidget(close_button)

        layout.addLayout(buttons)

    def open_output_folder(self):

        folder = self.folder_combo.currentText()

        if Path(folder).is_dir():
            os.startfile(folder)


class MainWindow(QMainWindow):
    def __init__(self, initial_files=None):
        super().__init__()

        if ICON_FILE.is_file():
            self.setWindowIcon(QIcon(str(ICON_FILE)))

        self.setWindowTitle(f"imgtopdf v{VERSION}")
        
        self.setMinimumSize(540, 650)

        self.files = []
        self.thread = None
        self.worker = None

        self.saved_settings = self.load_settings()
        self.remember_enabled = SETTINGS_FILE.is_file()

        self.last_directory = self.saved_settings.get(
            "last_directory",
            str(Path.home())
        )

        self.create_interface()

        if initial_files:
            self.add_files(initial_files)

    def load_settings(self):
        """
        Load saved settings, if available.
        """

        defaults = {
            "scale": "Fit",
            "merge": "None",
            "orientation": "Auto",
            "page_size": "A4",
            "rotation": "None",
            "last_directory": str(Path.home())
        }

        if not SETTINGS_FILE.is_file():
            return defaults

        config = configparser.ConfigParser()

        try:
            config.read(SETTINGS_FILE, encoding="utf-8")

            if config.has_section("Settings"):
                for key in defaults:
                    if key in config["Settings"]:
                        defaults[key] = config["Settings"][key]

        except Exception:
            pass

        return defaults

    def save_settings(self):
        """ Save current settings only when remembering is enabled."""

        if not self.remember_checkbox.isChecked():
            return

        SETTINGS_DIR.mkdir(
            parents=True,
            exist_ok=True
        )

        config = configparser.ConfigParser()

        config["Settings"] = {
            "scale": self.scale_combo.currentText(),
            "merge": self.merge_combo.currentText(),
            "orientation": self.orientation_combo.currentText(),
            "page_size": self.size_combo.currentText(),
            "rotation": self.rotation_combo.currentText(),
            "last_directory": self.last_directory
        }

        with open(
            SETTINGS_FILE,
            "w",
            encoding="utf-8"
        ) as settings_file:
            config.write(settings_file)

    def remember_settings_toggled(self, checked):

        if checked:
            self.save_settings()

        else:
            # Remove only our own settings file.
            if SETTINGS_FILE.exists():
                SETTINGS_FILE.unlink()

            # Remove our folder only if it is empty.
            if SETTINGS_DIR.exists():
                try:
                    SETTINGS_DIR.rmdir()
                except OSError:
                    pass

    def create_interface(self):
        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 10, 20, 20)

        header_layout = QVBoxLayout()
        header_layout.setSpacing(0)
        header_layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("imgtopdf")
        title.setStyleSheet(
            "font-size: 28px; font-weight: bold;"
        )

        subtitle = QLabel("Image to PDF Converter")
        subtitle.setStyleSheet("color: #777;")

        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)

        layout.addLayout(header_layout)

        self.drop_area = DropArea()
        self.drop_area.files_dropped.connect(self.add_files)
        layout.addWidget(self.drop_area)

        browse_layout = QHBoxLayout()

        self.browse_button = QPushButton("Browse for files...")
        self.browse_button.clicked.connect(self.browse_files)

        self.move_up_button = QPushButton("Move Up")
        self.move_up_button.clicked.connect(lambda: self.move_selected(-1))

        self.move_down_button = QPushButton("Move Down")
        self.move_down_button.clicked.connect(lambda: self.move_selected(1))

        self.remove_button = QPushButton("Remove Selected")
        self.remove_button.clicked.connect(self.remove_selected_files)

        self.clear_button = QPushButton("Clear All")
        self.clear_button.clicked.connect(self.clear_files)

        browse_layout.addWidget(self.browse_button)
        browse_layout.addWidget(self.move_up_button)
        browse_layout.addWidget(self.move_down_button)
        browse_layout.addWidget(self.remove_button)        
        browse_layout.addWidget(self.clear_button)

        layout.addLayout(browse_layout)

        self.file_list = FileListWidget()
        self.file_list.files_reordered.connect(self.on_files_reordered)

        layout.addWidget(self.file_list)

        self.file_count = QLabel("Files selected: 0")
        layout.addWidget(self.file_count)

        # Conversion settings box
        settings_box = QGroupBox("Conversion settings")
        settings_layout = QFormLayout(settings_box)

        self.scale_combo = QComboBox()
        self.scale_combo.addItems(["None", "Stretch", "Fit"])
        self.scale_combo.setCurrentText("Fit")

        self.merge_combo = QComboBox()
        self.merge_combo.addItems([
            "None", "Ascending", "Descending", "Custom"
        ])
        self.merge_combo.setCurrentText("None")

        self.orientation_combo = QComboBox()
        self.orientation_combo.addItems([
            "Auto", "Portrait", "Landscape"
        ])
        self.orientation_combo.setCurrentText("Auto")

        self.rotation_combo = QComboBox()
        self.rotation_combo.addItems([
            "None", "+90° clockwise", "-90° anticlockwise", "180°"
        ])
        self.rotation_combo.setCurrentText("None")

        self.size_combo = QComboBox()
        self.size_combo.addItems(list(PAGE_SIZES.keys()))
        self.size_combo.setCurrentText("A4")

        self.remember_checkbox = QCheckBox("Remember settings")
        self.remember_checkbox.setChecked(self.remember_enabled)

        settings_layout.addRow("Scale:", self.scale_combo)
        settings_layout.addRow("Merge:", self.merge_combo)
        settings_layout.addRow("Orientation:", self.orientation_combo)
        settings_layout.addRow("Rotation:", self.rotation_combo)
        settings_layout.addRow("Page size:", self.size_combo)
        settings_layout.addRow("", self.remember_checkbox)

        layout.addWidget(settings_box)

        # Now restore the saved dropdown selections.
        self.scale_combo.setCurrentText(self.saved_settings["scale"])
        self.merge_combo.setCurrentText(self.saved_settings["merge"])
        self.orientation_combo.setCurrentText(self.saved_settings["orientation"])
        self.size_combo.setCurrentText(self.saved_settings["page_size"])
        self.rotation_combo.setCurrentText(self.saved_settings["rotation"])

        self.remember_checkbox.toggled.connect(self.remember_settings_toggled)

        # Connect the dropdowns to automatic saving.
        self.scale_combo.currentTextChanged.connect(self.save_settings)
        self.merge_combo.currentTextChanged.connect(self.save_settings)
        self.orientation_combo.currentTextChanged.connect(self.save_settings)
        self.size_combo.currentTextChanged.connect(self.save_settings)
        self.rotation_combo.currentTextChanged.connect(self.save_settings)

        # Progress bar.
        self.progress = QProgressBar()
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.status = QLabel("Ready")
        layout.addWidget(self.status)

        self.convert_button = QPushButton("Convert to PDF")
        self.convert_button.setMinimumHeight(42)
        self.convert_button.setStyleSheet("""
            QPushButton {
                background-color: #287FC0;
                color: white;
                font-size: 15px;
                font-weight: bold;
                border-radius: 6px;
            }
            QPushButton:disabled {
                background-color: #999;
            }
        """)

        self.convert_button.clicked.connect(self.start_conversion)
        layout.addWidget(self.convert_button)

    def add_files(self, files):
        for filename in files:
            path = str(Path(filename))

            if is_image(path) and path not in self.files:
                self.files.append(path)

                item = QListWidgetItem(Path(path).name)

                item.setData(
                    Qt.ItemDataRole.UserRole,
                    path
                )

                self.file_list.addItem(item)

        self.update_count()
        self.reset_status()

    def browse_files(self):

        start_directory = self.last_directory

        if not Path(start_directory).is_dir():
            start_directory = str(Path.home())

        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select image files",
            start_directory,
            "Image files (*.jpg *.jpeg *.png *.bmp "
            "*.tif *.tiff *.webp)"
        )

        if files:
            self.last_directory = str(
                Path(files[0]).parent
            )

            self.save_settings()

            self.add_files(files)

    def clear_files(self):
        self.files.clear()
        self.file_list.clear()
        self.update_count()
        self.progress.setValue(0)
        self.reset_status()

    def update_count(self):
        self.file_count.setText(
            f"Files selected: {len(self.files)}"
        )

    def sync_files_from_list(self):
        """Keep self.files in the same order as the list widget."""
        self.files = [
            self.file_list.item(i).data(
                Qt.ItemDataRole.UserRole
            )
            for i in range(self.file_list.count())
        ]

    def on_files_reordered(self):
        """Handle manual drag-and-drop reordering."""
        self.sync_files_from_list()
        self.merge_combo.setCurrentText("Custom")
        self.reset_status()

    def move_selected(self, direction):
        """Move selected files up or down one position."""

        selected_items = self.file_list.selectedItems()

        if not selected_items:
            return

        selected_rows = sorted(
            self.file_list.row(item)
            for item in selected_items
        )

        changed = False

        if direction == -1:
            # Move upwards, starting at the top.
            for row in selected_rows:
                if row > 0 and row - 1 not in selected_rows:
                    item = self.file_list.takeItem(row)
                    self.file_list.insertItem(row - 1, item)
                    changed = True

        elif direction == 1:
            # Move downwards, starting at the bottom.
            for row in reversed(selected_rows):
                if (
                    row < self.file_list.count() - 1
                    and row + 1 not in selected_rows
                ):
                    item = self.file_list.takeItem(row)
                    self.file_list.insertItem(row + 1, item)
                    changed = True

        if changed:
            # Restore selection.
            for i in range(self.file_list.count()):
                self.file_list.item(i).setSelected(False)

            for item in selected_items:
                item.setSelected(True)

            self.sync_files_from_list()
            self.merge_combo.setCurrentText("Custom")
            self.reset_status()

    def remove_selected_files(self):
        selected_rows = sorted(
            [
                self.file_list.row(item)
                for item in self.file_list.selectedItems()
            ],
            reverse=True
        )

        if not selected_rows:
            return

        for row in selected_rows:
            self.file_list.takeItem(row)

        self.sync_files_from_list()
        self.update_count()
        self.reset_status()
    
    def start_conversion(self):
        if not self.files:
            QMessageBox.warning(
                self, "No files",
                "Please add some image files first."
            )
            return

        settings = {
            "scale": self.scale_combo.currentText(),
            "merge": self.merge_combo.currentText(),
            "orientation": self.orientation_combo.currentText(),
            "page_size": self.size_combo.currentText(),
            "rotation": self.rotation_combo.currentText()
        }

        self.convert_button.setEnabled(False)
        self.browse_button.setEnabled(False)
        self.move_up_button.setEnabled(False)
        self.move_down_button.setEnabled(False)
        self.remove_button.setEnabled(False)
        self.clear_button.setEnabled(False)

        self.progress.setValue(0)
        self.status.setText("Starting conversion...")

        self.thread = QThread()
        self.worker = ConversionWorker(self.files, settings)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)

        self.worker.progress.connect(self.update_progress)
        self.worker.finished.connect(self.conversion_finished)
        self.worker.failed.connect(self.conversion_failed)

        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)

        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)

        self.thread.start()

    def reset_status(self):
        self.progress.setValue(0)
        self.status.setText("Ready")

    def update_progress(self, value, filename):
        self.progress.setValue(value)
        self.status.setText(f"Processing: {filename}")

    def enable_controls(self):
        self.convert_button.setEnabled(True)
        self.browse_button.setEnabled(True)
        self.move_up_button.setEnabled(True)
        self.move_down_button.setEnabled(True)
        self.remove_button.setEnabled(True)
        self.clear_button.setEnabled(True)

    def conversion_finished(self, results, errors):

        self.enable_controls()
        self.progress.setValue(100)

        if results:
            self.status.setText(
                f"Finished: {len(results)} PDF file(s) created."
            )
        else:
            self.status.setText("Conversion completed with no PDFs created.")

        dialog = CompletionDialog(
            results,
            errors,
            self
        )

        dialog.exec()

    def conversion_failed(self, message):
        self.enable_controls()
        self.status.setText("Conversion failed.")

        QMessageBox.critical(
            self, "Conversion error", message
        )


def main():
    # Files supplied by Windows drag-and-drop
    supplied_files = [
        arg for arg in sys.argv[1:]
        if os.path.isfile(arg) and is_image(arg)
    ]

    app = QApplication(sys.argv)
    app.setApplicationName("imgtopdf")

    if ICON_FILE.is_file():
        app.setWindowIcon(QIcon(str(ICON_FILE)))

    # Direct EXE drop mode always uses the defaults.
    if supplied_files:
        try:
            results, errors = convert_images(
                supplied_files,
                scale="Fit",
                merge_mode="None",
                orientation="Auto",
                page_size="A4",
                rotation="None"
            )

            message = (
                f"imgtopdf completed.\n\n"
                f"PDF files created: {len(results)}"
            )

            if errors:
                message += (
                    f"\n\nFiles skipped: {len(errors)}\n"
                    + "\n".join(errors)
                )

            QMessageBox.information(
                None, "imgtopdf", message
            )

        except Exception as error:
            QMessageBox.critical(
                None, "imgtopdf error", str(error)
            )

        return 0

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
