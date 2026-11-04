from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QShortcut, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QMessageBox,
    QPlainTextEdit,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from config.paths import EXPORT_CODING_FILES_DIR
from core.coding_value import CodingDefinition
from core.crc import calculate_crc8_sae_j1850
from core.coding_value_definition import (
    export_coding_definition_to_json,
    load_coding_definition,
    load_coding_definition_from_excel,
    load_coding_definition_from_json,
)
from core.coding_value_payload import (
    extract_raw_value,
    format_payload_bytes,
    parse_payload_text,
    write_raw_value,
)
from core.coding_value_workspace_snapshot import (
    CodingWorkspaceRowSnapshot,
    CodingWorkspaceSnapshot,
)
from core.coding_value_report_export import (
    CODING_VALUE_REPORT_HEADERS,
    CodingValueReportData,
    CodingValueReportRow,
)
from core.services.coding_value_report_service import CodingValueReportService
from gui.themes.theme_manager import ThemeManager
from gui.themes.styles.containers.groupbox_style import fn_groupbox_style
from gui.themes.styles.controls.scrollbar_style import fn_apply_scrollbar_style
from gui.utils.text_selection import clear_text_selection_on_focus_out
from gui.widgets.coding_value.coding_value_table import CodingValueTable
from gui.widgets.controls.primary_button import PrimaryButton
from gui.widgets.controls.primary_combobox import PrimaryComboBox
from gui.widgets.controls.primary_lineedit import PrimaryLineEdit

from gui.themes.theme import ThemeType
from gui.themes.theme_manager import ThemeManager

from gui.widgets.controls.action_button import ActionButton

DEFAULT_CODING_DIR = Path("config/Coding")
POSITION_COPY_DATA_PAYLOAD = 3
ACTION_PANEL_WIDTH = 300
ACTION_PANEL_SPACING = 8


class CodingValuePanel(QGroupBox):

    coding_file_changed = Signal(str)
    state_changed = Signal()

    def __init__(self):
        super().__init__("Coding Value")

        self._payload_preview_bytes: list[int] = []
        self._payload_baseline_bytes: list[int] = []
        self._has_encoded_payload: bool = False
        self._preview_editing: bool = False
        self._restoring_snapshot: bool = False
        self._report_service: CodingValueReportService = CodingValueReportService()
        self._coding_definition: CodingDefinition | None = None
        self._coding_file: str = ""
        self._setup_ui()
        self._connect_signals()
        self._setup_shortcuts()
        self.fn_refresh_theme()

    def _setup_ui(self):
        self.content = QWidget()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            12,
            14,
            12,
            12,
        )
        layout.setSpacing(8)

        self.file_path = PrimaryLineEdit(
            placeholder="Select coding Excel file"
        )
        self.btn_browse = PrimaryButton(
            "Browse",
            width=100,
        )

        self.cmb_coding_json = PrimaryComboBox()
        self.cmb_coding_json.setFixedWidth(260)
        self.cmb_coding_json.setMaxVisibleItems(10)
        fn_apply_scrollbar_style(self.cmb_coding_json.view())
        self.cmb_coding_json.setCurrentIndex(-1)

        # Button width
        file_button_width = (
            ACTION_PANEL_WIDTH - ACTION_PANEL_SPACING
        ) // 2

        # Import button
        self.btn_import = PrimaryButton(
            "Import",
            width=80,
        )

        # Default button
        self.btn_default = PrimaryButton(
            "Default",
            width=file_button_width,
        )
        self.btn_default.setFixedWidth(file_button_width)

        # Default value combobox (0 / 1)
        self.cmb_default_value = PrimaryComboBox()
        self.cmb_default_value.addItems(["0", "1"])
        self.cmb_default_value.setCurrentIndex(-1)
        self.cmb_default_value.setPlaceholderText("")
        self.cmb_default_value.setFixedWidth(file_button_width)

        # File action row: Combobox + Default
        self.file_action_row = QWidget()
        file_action_layout = QHBoxLayout(self.file_action_row)
        file_action_layout.setContentsMargins(0, 0, 0, 0)
        file_action_layout.setSpacing(ACTION_PANEL_SPACING)

        file_action_layout.addWidget(self.cmb_default_value)
        file_action_layout.addWidget(self.btn_default)

        self.file_action_row.setFixedWidth(ACTION_PANEL_WIDTH)

        # Main file row
        self.file_row = QWidget()
        file_layout = QHBoxLayout(self.file_row)
        file_layout.setContentsMargins(0, 0, 0, 0)
        file_layout.setSpacing(8)

        file_layout.addWidget(self.file_path, 1)
        file_layout.addWidget(self.btn_browse)
        file_layout.addWidget(self.cmb_coding_json)
        file_layout.addWidget(self.btn_import)
        file_layout.addWidget(self.file_action_row)

        self._refresh_coding_json_options()

        self.txt_coding_value = QPlainTextEdit()
        self.txt_coding_value.setPlaceholderText(
            "Paste coding value payload here"
        )
        self.txt_coding_value.setVerticalScrollBarPolicy(
            Qt.ScrollBarAsNeeded
        )

        self.txt_coding_preview = QPlainTextEdit()
        self.txt_coding_preview.setPlaceholderText(
            "Coding payload preview"
        )
        self.txt_coding_preview.setReadOnly(True)
        self.txt_coding_preview.setVerticalScrollBarPolicy(
            Qt.ScrollBarAsNeeded
        )
        self._set_payload_editor_height()

        self.btn_encode = ActionButton(
            "Encode",
            width=100,
            variant="primary",
        )

        self.btn_copy = ActionButton(
            "Copy",
            width=100,
            variant="secondary",
        )

        self.btn_clear = ActionButton(
            "Clear",
            width=100,
            variant="danger",
        )

        self.btn_preview_refresh = ActionButton(
            "Refresh",
            width=100,
            variant="secondary",
        )

        self.btn_copy_preview = ActionButton(
            "Copy",
            width=100,
            variant="secondary",
        )

        self.btn_preview_edit = ActionButton(
            "EDIT",
            width=100,
            variant="primary",
        )

        self.payload_input_row = QWidget()
        input_layout = QHBoxLayout(self.payload_input_row)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(8)
        input_layout.addWidget(self.btn_clear, 0, Qt.AlignTop)
        input_layout.addWidget(self.btn_copy, 0, Qt.AlignTop)
        input_layout.addWidget(self.btn_encode, 0, Qt.AlignTop)
        input_layout.addWidget(self.txt_coding_value, 1)

        self.payload_preview_row = QWidget()
        preview_layout = QHBoxLayout(self.payload_preview_row)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(8)
        preview_layout.addWidget(self.btn_preview_refresh, 0, Qt.AlignTop)
        preview_layout.addWidget(self.btn_copy_preview, 0, Qt.AlignTop)
        preview_layout.addWidget(self.btn_preview_edit, 0, Qt.AlignTop)
        preview_layout.addWidget(self.txt_coding_preview, 1)

        self.payload_row = QWidget()
        payload_layout = QVBoxLayout(self.payload_row)
        payload_layout.setContentsMargins(0, 0, 0, 0)
        payload_layout.setSpacing(6)
        payload_layout.addWidget(self.payload_input_row)
        payload_layout.addWidget(self.payload_preview_row)

        self.txt_parameter_filter = PrimaryLineEdit(
            placeholder="Filter parameter"
        )
        filter_button_width = (ACTION_PANEL_WIDTH - ACTION_PANEL_SPACING) // 2
        self.btn_filter_no_m = PrimaryButton(
            "No-M",
            width=filter_button_width,
        )
        self.btn_filter_no_m.setFixedWidth(filter_button_width)
        self.btn_refresh_filter = PrimaryButton(
            "Refresh",
            width=filter_button_width,
        )
        self.btn_refresh_filter.setFixedWidth(filter_button_width)

        self.filter_action_row = QWidget()
        self.filter_action_row.setFixedWidth(ACTION_PANEL_WIDTH)
        filter_action_layout = QHBoxLayout(self.filter_action_row)
        filter_action_layout.setContentsMargins(0, 0, 0, 0)
        filter_action_layout.setSpacing(ACTION_PANEL_SPACING)
        filter_action_layout.addWidget(self.btn_filter_no_m)
        filter_action_layout.addWidget(self.btn_refresh_filter)

        self.filter_row = QWidget()
        filter_layout = QHBoxLayout(self.filter_row)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(8)
        filter_layout.addWidget(self.txt_parameter_filter, 1)
        filter_layout.addWidget(self.filter_action_row, 0)

        self.table = CodingValueTable()

        self.btn_check = PrimaryButton(
            "CHECK",
            width=ACTION_PANEL_WIDTH,
        )
        self.btn_check.setFixedWidth(ACTION_PANEL_WIDTH)
        self.btn_copy_data_payload = PrimaryButton(
            "COPY DATA PAYLOAD",
            width=ACTION_PANEL_WIDTH,
        )
        self.btn_copy_data_payload.setFixedWidth(ACTION_PANEL_WIDTH)
        self.btn_export = PrimaryButton(
            "EXPORT",
            width=ACTION_PANEL_WIDTH,
        )
        self.btn_export.setFixedWidth(ACTION_PANEL_WIDTH)
        self.btn_table_clear = PrimaryButton(
            "CLEAR",
            width=ACTION_PANEL_WIDTH,
        )
        self.btn_table_clear.setFixedWidth(ACTION_PANEL_WIDTH)

        self.table_action_panel = QWidget()
        self.table_action_panel.setFixedWidth(ACTION_PANEL_WIDTH)
        action_layout = QVBoxLayout(self.table_action_panel)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(8)
        action_layout.addWidget(self.btn_check)
        action_layout.addWidget(self.btn_copy_data_payload)
        action_layout.addWidget(self.btn_export)
        action_layout.addWidget(self.btn_table_clear)
        action_layout.addStretch(1)

        self.txt_working_log = QPlainTextEdit()
        self.txt_working_log.setPlaceholderText(
            "Working log"
        )
        self.txt_working_log.setReadOnly(True)
        self.txt_working_log.setFixedWidth(ACTION_PANEL_WIDTH)
        self.txt_working_log.setVerticalScrollBarPolicy(
            Qt.ScrollBarAsNeeded
        )

        self.table_side_panel = QWidget()
        self.table_side_panel.setFixedWidth(ACTION_PANEL_WIDTH)
        side_layout = QVBoxLayout(self.table_side_panel)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(8)
        side_layout.addWidget(self.table_action_panel, 0)
        side_layout.addWidget(self.txt_working_log, 1)

        self.table_area = QWidget()
        table_area_layout = QHBoxLayout(self.table_area)
        table_area_layout.setContentsMargins(0, 0, 0, 0)
        table_area_layout.setSpacing(8)
        table_area_layout.addWidget(self.table, 1)
        table_area_layout.addWidget(self.table_side_panel, 0)

        layout.addWidget(self.file_row)
        layout.addWidget(self.payload_row)
        layout.addWidget(self.filter_row)
        layout.addWidget(self.table_area, 1)

        self._install_text_selection_handlers()

    def _install_text_selection_handlers(self):
        clear_text_selection_on_focus_out(
            self,
            [
                self.file_path,
                self.txt_coding_value,
                self.txt_coding_preview,
                self.txt_parameter_filter,
                self.txt_working_log,
            ],
        )

    def _set_payload_editor_height(self):
        self._set_editor_three_line_height(self.txt_coding_value)
        self._set_editor_three_line_height(self.txt_coding_preview)

    @staticmethod
    def _set_editor_three_line_height(editor):
        line_height = editor.fontMetrics().lineSpacing()
        frame_width = editor.frameWidth() * 2
        vertical_padding = 12
        height = line_height * 3 + frame_width + vertical_padding
        editor.setMinimumHeight(height)
        editor.setMaximumHeight(height)

    def _setup_shortcuts(self):
        shortcuts = (
            ("Ctrl+R", self.btn_check),
            ("Ctrl+F", self.btn_filter_no_m),
            ("Ctrl+Z", self.btn_refresh_filter),
            ("Ctrl+Q", self.btn_encode),
        )
        self._coding_value_shortcuts = []
        for sequence, button in shortcuts:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(button.click)
            self._coding_value_shortcuts.append(shortcut)

    def _connect_signals(self):
        self.btn_browse.clicked.connect(
            self.browse_file
        )
        self.btn_import.clicked.connect(
            self.import_coding_value
        )
        self.btn_default.clicked.connect(
            self.set_default_coding_payload
        )
        self.cmb_coding_json.currentIndexChanged.connect(
            self.load_selected_coding_json
        )
        self.btn_encode.clicked.connect(
            self.encode_coding_payload
        )
        self.btn_copy.clicked.connect(
            self.copy_coding_payload
        )
        self.btn_clear.clicked.connect(
            self.clear_coding_payload
        )
        self.btn_preview_refresh.clicked.connect(
            self.refresh_coding_preview
        )
        self.btn_preview_edit.clicked.connect(
            self.toggle_preview_edit_import
        )
        self.btn_copy_preview.clicked.connect(
            self.copy_coding_preview
        )
        self.btn_check.clicked.connect(
            self.check_coding_value
        )
        self.btn_copy_data_payload.clicked.connect(
            self.copy_data_payload
        )
        self.btn_export.clicked.connect(
            self.export_coding_value
        )
        self.btn_table_clear.clicked.connect(
            self.clear_table_coding_values
        )
        self.table.raw_value_changed.connect(
            self.update_payload_preview_from_raw
        )
        self.table.raw_value_changed.connect(
            lambda *_args: self._emit_state_changed()
        )
        self.txt_coding_value.textChanged.connect(
            self._emit_state_changed
        )
        self.txt_coding_preview.textChanged.connect(
            self._emit_state_changed
        )
        self.txt_parameter_filter.textChanged.connect(
            self._emit_state_changed
        )
        self.txt_parameter_filter.textChanged.connect(
            self.filter_parameter_table
        )
        self.btn_filter_no_m.clicked.connect(
            self.filter_no_match_rows
        )
        self.btn_refresh_filter.clicked.connect(
            self.refresh_parameter_filter
        )
        self.txt_coding_value.textChanged.connect(
            self._update_action_states
        )

    def _emit_state_changed(self):
        if self._restoring_snapshot:
            return

        self.state_changed.emit()

    def browse_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Coding Excel",
            str(DEFAULT_CODING_DIR),
            "Excel Files (*.xlsx *.xlsm *.xltx *.xltm)",
        )

        if file_path:
            self.file_path.setText(file_path)

    def _refresh_coding_json_options(self, selected_path=None):
        selected = str(selected_path) if selected_path else ""
        export_dir = Path(EXPORT_CODING_FILES_DIR)
        json_files = (
            sorted(
                export_dir.glob("*.json"),
                key=self._coding_json_sort_key,
            )
            if export_dir.exists()
            else []
        )

        self.cmb_coding_json.blockSignals(True)
        self.cmb_coding_json.clear()
        for json_file in json_files:
            self.cmb_coding_json.addItem(
                json_file.stem,
                str(json_file),
            )

        if selected:
            self.cmb_coding_json.setCurrentIndex(
                self._find_coding_json_option(selected)
            )
        else:
            self.cmb_coding_json.setCurrentIndex(-1)
        self.cmb_coding_json.blockSignals(False)

    @staticmethod
    def _coding_json_sort_key(json_file: Path):
        try:
            modified_time = json_file.stat().st_mtime
        except OSError:
            modified_time = 0

        return (-modified_time, json_file.name.casefold())

    def _find_coding_json_option(self, selected_path: str) -> int:
        for index in range(self.cmb_coding_json.count()):
            if self._same_coding_json_path(
                self.cmb_coding_json.itemData(index),
                selected_path,
            ):
                return index

        return -1

    @staticmethod
    def _same_coding_json_path(left, right) -> bool:
        left_text = str(left or "").strip()
        right_text = str(right or "").strip()
        if not left_text or not right_text:
            return False

        left_path = Path(left_text)
        right_path = Path(right_text)
        try:
            return (
                left_path.resolve(strict=False)
                == right_path.resolve(strict=False)
            )
        except (OSError, RuntimeError, ValueError):
            return (
                left_text.replace("\\", "/").casefold()
                == right_text.replace("\\", "/").casefold()
            )

    def load_selected_coding_json(self):
        json_path = self.cmb_coding_json.currentData()
        if not json_path:
            return

        try:
            definition = load_coding_definition_from_json(json_path)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Coding value",
                f"Cannot import coding JSON file:\n{exc}",
            )
            return

        # Reset Filter / No-M khi chuyển file thành công
        self.txt_parameter_filter.clear()

        # Load toàn bộ dữ liệu file mới
        self._set_coding_definition(
            definition,
            coding_file=json_path,
        )
        self.cmb_default_value.setCurrentIndex(-1)

    def _set_coding_definition(
            self,
            definition: CodingDefinition,
            coding_file: str = "",
            emit_coding_file_changed: bool = True,
        ):
        self._coding_definition = definition
        self._coding_file = str(coding_file or "")
        self.table.set_rows(definition.rows)
        self.filter_parameter_table()
        self._update_action_states()
        if coding_file and emit_coding_file_changed:
            self.coding_file_changed.emit(str(coding_file))
        self._emit_state_changed()

    def create_workspace_snapshot(self) -> CodingWorkspaceSnapshot:
        return CodingWorkspaceSnapshot(
            coding_file=self._coding_file,
            payload_input=self.txt_coding_value.toPlainText(),
            payload_preview=self._format_payload_bytes(self._payload_preview_bytes),
            baseline_payload=self._format_payload_bytes(self._payload_baseline_bytes),
            parameter_filter=self.txt_parameter_filter.text(),
            checked=self._has_check_results(),
            raw_values=tuple(self._snapshot_raw_values()),
            working_log=self.txt_working_log.toPlainText(),
        )

    def restore_workspace_snapshot(
            self,
            snapshot: CodingWorkspaceSnapshot,
        ) -> bool:
        self._restoring_snapshot = True
        try:
            definition_loaded = False
            if snapshot.coding_file:
                definition_loaded = self.load_coding_definition_file(
                    snapshot.coding_file,
                    emit_coding_file_changed=False,
                )

            self.txt_coding_value.setPlainText(snapshot.payload_input)
            self._payload_baseline_bytes = self._parse_snapshot_payload(
                snapshot.baseline_payload
            )
            self._payload_preview_bytes = self._parse_snapshot_payload(
                snapshot.payload_preview
            )
            self.txt_coding_preview.setPlainText(
                self._format_payload_bytes(self._payload_preview_bytes)
            )
            self.txt_coding_preview.setExtraSelections([])
            self._has_encoded_payload = bool(self._payload_preview_bytes)

            if definition_loaded or self._coding_definition is not None:
                self._restore_table_snapshot(snapshot)

            self.txt_parameter_filter.setText(snapshot.parameter_filter)
            self.filter_parameter_table()
            if snapshot.working_log:
                self.txt_working_log.setPlainText(snapshot.working_log)
            self._update_action_states()
            return True
        finally:
            self._finish_preview_edit()
            self._restoring_snapshot = False

    def _snapshot_raw_values(self):
        for row_index in range(self.table.rowCount()):
            raw_item = self.table.item(row_index, 4)
            raw_value = raw_item.text() if raw_item is not None else ""
            yield CodingWorkspaceRowSnapshot(
                parameter=self._table_item_text(row_index, 0),
                byte_pos=self._table_item_text(row_index, 1),
                bit_pos=self._table_item_text(row_index, 2),
                bit_length=self._table_item_text(row_index, 3),
                raw_value=raw_value,
            )

    def _restore_table_snapshot(self, snapshot: CodingWorkspaceSnapshot):
        if snapshot.baseline_payload:
            self.table.encode_payload(
                snapshot.baseline_payload,
                update_original=True,
            )

        row_by_key = {
            self._snapshot_row_key(row_index): row_index
            for row_index in range(self.table.rowCount())
        }
        for raw_snapshot in snapshot.raw_values:
            row_index = row_by_key.get(self._snapshot_key(raw_snapshot))
            if row_index is None:
                continue

            self.table.fn_set_raw_value_at_row(
                row_index,
                raw_snapshot.raw_value,
                emit_raw_change=False,
            )

        if snapshot.checked:
            self.table.apply_check_results()
            if not snapshot.working_log:
                self._write_check_working_log()

    def _snapshot_row_key(self, row_index: int) -> tuple[str, str, str, str]:
        return (
            self._table_item_text(row_index, 0),
            self._table_item_text(row_index, 1),
            self._table_item_text(row_index, 2),
            self._table_item_text(row_index, 3),
        )

    @staticmethod
    def _snapshot_key(
            raw_snapshot: CodingWorkspaceRowSnapshot,
        ) -> tuple[str, str, str, str]:
        return (
            raw_snapshot.parameter,
            raw_snapshot.byte_pos,
            raw_snapshot.bit_pos,
            raw_snapshot.bit_length,
        )

    @staticmethod
    def _parse_snapshot_payload(payload: str) -> list[int]:
        if not str(payload or "").strip():
            return []

        try:
            return parse_payload_text(payload)
        except ValueError:
            return []

    def load_coding_definition_file(
            self,
            coding_file: str,
            notify_errors: bool = False,
            emit_coding_file_changed: bool = True,
        ) -> bool:
        coding_file = str(coding_file or "").strip()
        if not coding_file:
            return False

        try:
            definition = load_coding_definition(coding_file)
        except Exception as exc:
            if notify_errors:
                QMessageBox.warning(
                    self,
                    "Coding value",
                    f"Cannot import coding file:\n{exc}",
                )
            return False

        self._set_coding_definition(
            definition,
            coding_file=coding_file,
            emit_coding_file_changed=emit_coding_file_changed,
        )
        self._refresh_coding_json_options(coding_file)
        return True

    def import_coding_value(self):
        selected_json = self.cmb_coding_json.currentData()
        excel_path = self.file_path.text().strip()
        if selected_json and not excel_path:
            self.load_selected_coding_json()
            return

        if not excel_path:
            QMessageBox.warning(
                self,
                "Coding value",
                "Please select a coding Excel file before importing.",
            )
            return

        try:
            definition = load_coding_definition_from_excel(
                excel_path,
                "",
            )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Coding value",
                f"Cannot import coding Excel file:\n{exc}",
            )
            return

        json_path = export_coding_definition_to_json(
            definition,
            EXPORT_CODING_FILES_DIR,
        )
        self._refresh_coding_json_options(json_path)
        self._set_coding_definition(
            load_coding_definition_from_json(json_path),
            coding_file=str(json_path),
        )
        self.file_path.clear()

    def filter_parameter_table(self):
        self.table.filter_by_parameter(
            self.txt_parameter_filter.text()
        )

    def set_default_coding_payload(self):
        byte_count = self._default_coding_payload_byte_count()
        if byte_count <= 0:
            return

        selected = self.cmb_default_value.currentText().strip()

        if selected not in ("0", "1"):
            return

        fill_byte = 0x00 if selected == "0" else 0x11

        self.txt_coding_value.setPlainText(
            self._format_payload_bytes([fill_byte] * byte_count)
        )
        self._update_action_states()

    def _default_coding_payload_byte_count(self):
        byte_count = 0
        for row_index in range(self.table.rowCount()):
            byte_pos = CodingValueTable._to_int(
                self._table_item_text(row_index, 1)
            )
            bit_pos = CodingValueTable._to_int(
                self._table_item_text(row_index, 2)
            )
            bit_length = CodingValueTable._to_int(
                self._table_item_text(row_index, 3)
            )
            if (
                    byte_pos is None
                    or bit_pos is None
                    or bit_length is None
                    or byte_pos < 0
                    or bit_pos < 0
                    or bit_length <= 0
                ):
                continue

            row_byte_count = (bit_pos + bit_length + 7) // 8
            byte_count = max(byte_count, byte_pos + row_byte_count)

        return byte_count

    def _table_item_text(self, row_index, column):
        item = self.table.item(row_index, column)
        return item.text() if item is not None else ""

    def filter_no_match_rows(self):
        self.txt_parameter_filter.setText("No-M")
        self.filter_parameter_table()

    def refresh_parameter_filter(self):
        self.txt_parameter_filter.clear()
        self.filter_parameter_table()

    def fn_set_crc_value(self, crc_value):
        value = str(crc_value or "").strip()
        if not value:
            return False

        row_index = self.table.fn_find_row_index_by_parameter("crc")
        if row_index < 0:
            QMessageBox.warning(
                self,
                "Coding value",
                "Cannot find CRC parameter row.",
            )
            return False

        updated = self.table.fn_set_raw_value_at_row(
            row_index,
            value,
            emit_raw_change=False,
        )
        if not updated:
            return False

        self._update_crc_payload_preview(row_index)
        self._update_action_states()
        return True

    def _update_crc_payload_preview(self, row_index):
        if not self._payload_preview_bytes:
            return

        byte_pos, bit_pos, bit_length = self.table.fn_payload_location_for_row(
            row_index
        )
        preview_byte_pos = self._crc_preview_byte_pos(byte_pos)
        if preview_byte_pos is None:
            return

        raw_item = self.table.item(row_index, 4)
        raw_value = raw_item.text() if raw_item is not None else ""
        changed_bytes = self._apply_raw_to_payload_bytes(
            preview_byte_pos,
            bit_pos,
            bit_length,
            raw_value,
        )
        if not changed_bytes:
            return

        self.txt_coding_preview.setPlainText(
            self._format_payload_bytes(self._payload_preview_bytes)
        )
        self._highlight_payload_bytes(changed_bytes)

    def _crc_preview_byte_pos(self, byte_pos):
        if byte_pos is None:
            return None

        header_offset = 3
        shifted_byte_pos = byte_pos + header_offset
        if shifted_byte_pos < len(self._payload_preview_bytes):
            return shifted_byte_pos

        if byte_pos < len(self._payload_preview_bytes):
            return byte_pos

        return None

    def encode_coding_payload(self):
        self._encode_payload_to_table(
            warn_when_empty=True,
            warn_when_no_rows=True,
        )

    def _encode_payload_to_table(
            self,
            warn_when_empty=False,
            warn_when_no_rows=False,
        ):
        payload = self.txt_coding_value.toPlainText()
        if not payload.strip():
            if warn_when_empty:
                QMessageBox.warning(
                    self,
                    "Coding value",
                    "Please input coding value payload before encoding.",
                )
            self._update_action_states()
            return 0

        updated = self.table.encode_payload(payload)
        if updated > 0:
            self.set_payload_preview(payload)
            self._has_encoded_payload = True
        elif warn_when_no_rows:
            QMessageBox.warning(
                self,
                "Coding value",
                "No raw value row could be updated from this payload.",
            )
        self._update_action_states()
        return updated

    def check_coding_value(self):
        if not self._can_use_table_actions():
            return

        self._update_calculated_crc_value()
        self.table.apply_check_results()
        self._write_check_working_log()
        self._update_action_states()

    def export_coding_value(self):
        if not self._can_use_table_actions():
            return

        output_file = self._choose_coding_report_file()
        if output_file is None:
            return

        try:
            output_file = self._report_service.export_report(
                self._build_coding_report_data(),
                output_file,
            )
        except PermissionError:
            QMessageBox.warning(
                self,
                "Coding value",
                "Cannot save Coding value report. Please close the Excel file and try again.",
            )
            return

        QMessageBox.information(
            self,
            "Coding value",
            f"Coding value report saved:\n\n{output_file}",
        )

    def _choose_coding_report_file(self):
        default_path = self._default_coding_report_path()
        output_file, _ = QFileDialog.getSaveFileName(
            self,
            "Save Coding Value Report",
            str(default_path),
            "Excel Files (*.xlsx)",
        )
        if not output_file:
            return None

        selected_path = Path(output_file)
        if selected_path.suffix.lower() != ".xlsx":
            selected_path = selected_path.with_suffix(".xlsx")
        return selected_path

    def _default_coding_report_path(self):
        return self._report_service.default_report_path()

    def _build_coding_report_data(self):
        return CodingValueReportData(
            sheet_name=self._coding_export_sheet_name(),
            headers=self._coding_table_headers(),
            rows=tuple(self._coding_report_rows()),
        )

    def _coding_report_rows(self):
        headers = self._coding_table_headers()
        for row_index in range(self.table.rowCount()):
            if self.table.isRowHidden(row_index):
                continue

            values = self._coding_table_row_values(row_index)
            values_by_header = dict(zip(headers, values))
            yield CodingValueReportRow(
                parameter=values_by_header.get("Parameter", ""),
                byte_pos=values_by_header.get("Byte Pos", ""),
                bit_pos=values_by_header.get("Bit Pos", ""),
                bit_length=values_by_header.get("Bit Lengh", ""),
                raw_value=values_by_header.get("Raw value", ""),
                decoded_value=values_by_header.get("Decoded Value (Editable)", ""),
                raw_value_before=values_by_header.get("Raw value (before)", ""),
                decoded_value_before=values_by_header.get("Decoded value (before)", ""),
                result=values_by_header.get("Result", ""),
            )

    def _coding_export_sheet_name(self):
        return f"Coding value_{self._coding_export_identifier()}"

    def _coding_export_identifier(self):
        payload_bytes = self._payload_baseline_bytes or self._payload_preview_bytes
        return " ".join(
            f"{value:02X}"
            for value in payload_bytes[:3]
        )

    def _coding_table_headers(self):
        headers = [
            self.table.horizontalHeaderItem(column).text()
            for column in range(self.table.columnCount())
        ]
        return [
            header
            for header in headers
            if header in CODING_VALUE_REPORT_HEADERS
        ]

    def _coding_table_row_values(self, row_index):
        values = []
        for column in range(self.table.columnCount()):
            widget = self.table.cellWidget(row_index, column)
            if hasattr(widget, "currentText"):
                values.append(widget.currentText())
                continue

            item = self.table.item(row_index, column)
            values.append(item.text() if item is not None else "")

        return values[:len(self._coding_table_headers())]

    def copy_coding_payload(self):
        QApplication.clipboard().setText(
            self.txt_coding_value.toPlainText()
        )

    def copy_coding_preview(self):
        preview_text = self.txt_coding_preview.toPlainText()
        if not preview_text.strip():
            return

        QApplication.clipboard().setText(preview_text)

    def copy_data_payload(self):
        preview_text = self.txt_coding_preview.toPlainText()
        if not preview_text.strip():
            return

        try:
            payload_bytes = parse_payload_text(preview_text)
        except ValueError:
            return

        data_payload = payload_bytes[POSITION_COPY_DATA_PAYLOAD:]
        if not data_payload:
            return

        QApplication.clipboard().setText(
            self._format_payload_bytes(data_payload)
        )

    def clear_coding_payload(self):
        self.txt_coding_value.clear()
        self.clear_coding_preview()

    def clear_table_coding_values(self):
        self._coding_definition = None
        self._coding_file = ""
        self.table.clear_rows()
        self.txt_working_log.clear()
        self.clear_coding_preview()
        self.coding_file_changed.emit("")

    def refresh_coding_preview(self):
        if self._encode_payload_to_table() == 0:
            self.set_payload_preview(
                self.txt_coding_value.toPlainText()
            )

    def toggle_preview_edit_import(self):
        if self._preview_editing:
            self.import_preview_payload()
            return

        self.start_preview_edit()

    def start_preview_edit(self):
        if not self._can_edit_preview_payload():
            return

        self._preview_editing = True
        self.txt_coding_preview.setReadOnly(False)
        self.btn_preview_edit.setText("IMPORT")
        self.txt_coding_preview.setFocus()
        self._update_action_states()

    def import_preview_payload(self):
        payload = self.txt_coding_preview.toPlainText()
        if not payload.strip():
            return

        updated = self.table.encode_payload(
            payload,
            update_original=False,
        )
        if updated <= 0:
            QMessageBox.warning(
                self,
                "Coding value",
                "No raw value row could be updated from this payload.",
            )
            return

        self._payload_preview_bytes = parse_payload_text(payload)
        self.txt_coding_preview.setPlainText(
            self._format_payload_bytes(self._payload_preview_bytes)
        )
        self.txt_coding_preview.setExtraSelections([])
        if self._has_check_results():
            self._write_check_working_log()
        self._finish_preview_edit()

    def _finish_preview_edit(self):
        self._preview_editing = False
        self.txt_coding_preview.setReadOnly(True)
        self.btn_preview_edit.setText("EDIT")
        self._update_action_states()

    def _can_edit_preview_payload(self):
        return (
            self._can_use_table_actions()
            and self._has_check_results()
            and bool(self.txt_coding_preview.toPlainText().strip())
        )

    def _has_check_results(self):
        return self.table.columnCount() >= 9

    def clear_coding_preview(self):
        self.txt_coding_preview.clear()
        self.txt_coding_preview.setReadOnly(True)
        self.btn_preview_edit.setText("EDIT")
        self._preview_editing = False
        self.txt_coding_preview.setExtraSelections([])
        self._payload_preview_bytes = []
        self._payload_baseline_bytes = []
        self._has_encoded_payload = False
        self._update_action_states()

    def _update_action_states(self):
        has_input_payload = bool(self.txt_coding_value.toPlainText().strip())
        has_preview_payload = bool(self.txt_coding_preview.toPlainText().strip())
        has_table_rows = self.table.rowCount() > 0
        can_use_default = self._default_coding_payload_byte_count() > 0
        can_encode = has_table_rows and has_input_payload
        can_use_preview = has_preview_payload
        can_use_table_actions = self._can_use_table_actions()

        self.btn_default.setEnabled(can_use_default)
        self.btn_encode.setEnabled(can_encode)
        self.btn_copy.setEnabled(has_input_payload)
        self.btn_clear.setEnabled(has_input_payload)
        self.btn_preview_refresh.setEnabled(can_encode)
        self.btn_copy_preview.setEnabled(can_use_preview)
        self.btn_preview_edit.setEnabled(self._can_edit_preview_payload())
        self.btn_filter_no_m.setEnabled(
            can_use_table_actions and self._has_check_results()
        )
        self.btn_refresh_filter.setEnabled(has_table_rows)
        self.btn_check.setEnabled(can_use_table_actions)
        self.btn_copy_data_payload.setEnabled(
            len(self._payload_preview_bytes) > 3
        )
        self.btn_export.setEnabled(can_use_table_actions)
        self.btn_table_clear.setEnabled(can_use_table_actions)

    def _can_use_table_actions(self):
        return (
            self._has_encoded_payload
            and self.table.rowCount() > 0
            and bool(self._payload_preview_bytes)
        )

    def _update_calculated_crc_value(self):
        crc_range = self._crc_calculation_range()
        if crc_range is None:
            return False

        start, end = crc_range
        if start >= end:
            return False

        crc = calculate_crc8_sae_j1850(
            bytes(self._payload_preview_bytes[start:end])
        )
        return self.fn_set_crc_value(f"{crc:02X}")

    def _crc_calculation_range(self):
        crc_row_index = self.table.fn_find_row_index_by_parameter("crc")
        if crc_row_index < 0 or not self._payload_preview_bytes:
            return None

        crc_start, _, _, _ = self._payload_span_for_row(crc_row_index)
        if crc_start is None:
            return None

        short_vin_row_index = self._find_parameter_row("short", "vin")
        if short_vin_row_index >= 0:
            _, short_vin_end, _, _ = self._payload_span_for_row(
                short_vin_row_index
            )
            if short_vin_end is not None:
                return short_vin_end, crc_start

        format_row_index = self._find_parameter_row("format")
        if format_row_index < 0:
            return None

        _, format_end, _, _ = self._payload_span_for_row(format_row_index)
        if format_end is None:
            return None

        return format_end, crc_start

    def _find_parameter_row(self, *keywords):
        lowered_keywords = [
            str(keyword or "").lower()
            for keyword in keywords
            if str(keyword or "").strip()
        ]
        if not lowered_keywords:
            return -1

        for row_index in range(self.table.rowCount()):
            parameter = self._table_item_text(row_index, 0).lower()
            if all(keyword in parameter for keyword in lowered_keywords):
                return row_index

        return -1

    def _payload_span_for_row(self, row_index):
        byte_pos, bit_pos, bit_length = self.table.fn_payload_location_for_row(
            row_index
        )
        preview_byte_pos = self._preview_byte_pos_for_row(row_index, byte_pos)
        if preview_byte_pos is None or bit_pos is None or bit_length is None:
            return None, None, bit_pos, bit_length

        byte_count = (bit_pos + bit_length + 7) // 8
        if byte_count <= 0:
            return None, None, bit_pos, bit_length

        return (
            preview_byte_pos,
            preview_byte_pos + byte_count,
            bit_pos,
            bit_length,
        )

    def _preview_byte_pos_for_row(self, row_index, byte_pos):
        if byte_pos is None:
            return None

        parameter = self._table_item_text(row_index, 0).lower()
        if "crc" in parameter:
            return self._crc_preview_byte_pos(byte_pos)

        raw_value = self._table_item_text(row_index, 4)
        direct_pos = (
            byte_pos
            if byte_pos < len(self._payload_preview_bytes)
            else None
        )
        shifted_pos = byte_pos + 3
        if shifted_pos >= len(self._payload_preview_bytes):
            shifted_pos = None

        if (
                shifted_pos is not None
                and byte_pos < 3
                and self._payload_preview_has_uds_header()
            ):
            return shifted_pos
        if (
                direct_pos is not None
                and self._row_raw_matches_preview(row_index, direct_pos, raw_value)
            ):
            return direct_pos
        if (
                shifted_pos is not None
                and self._row_raw_matches_preview(row_index, shifted_pos, raw_value)
            ):
            return shifted_pos
        if shifted_pos is not None and self._payload_preview_has_uds_header():
            return shifted_pos

        return direct_pos

    def _row_raw_matches_preview(self, row_index, preview_byte_pos, raw_value):
        _, bit_pos, bit_length = self.table.fn_payload_location_for_row(row_index)
        expected = extract_raw_value(
            self._payload_preview_bytes,
            preview_byte_pos,
            bit_pos,
            bit_length,
        )
        return bool(raw_value) and expected == raw_value

    def _payload_preview_has_uds_header(self):
        return (
            len(self._payload_preview_bytes) >= 3
            and self._payload_preview_bytes[0] == 0x62
        )

    def _write_check_working_log(self):
        self.txt_working_log.setPlainText(
            self._build_check_working_log()
        )

    def _build_check_working_log(self):
        changes = []
        for row_index in range(self.table.rowCount()):
            result_item = self.table.item(row_index, 8)
            if result_item is None or result_item.text() != "No-M":
                continue

            byte_item = self.table.item(row_index, 1)
            before_decoded_item = self.table.item(row_index, 7)
            current_raw_item = self.table.item(row_index, 4)
            current_raw = current_raw_item.text() if current_raw_item else ""
            byte_text = byte_item.text() if byte_item else str(row_index)
            before_decoded = (
                before_decoded_item.text()
                if before_decoded_item is not None
                else ""
            )
            after_decoded = self.table._decoded_text_for_raw(
                row_index,
                current_raw,
            )
            changes.append(
                f"Byte {byte_text}: {before_decoded} -> {after_decoded}"
            )

        lines = [
            f"Total No-M: {len(changes)}",
            "",
            "Changes: Decode value before -> after",
            "",
        ]
        lines.extend(changes)
        lines.extend([
            "",
            (
                "CRC: "
                f"{self._crc_text(self._payload_baseline_bytes)} -> "
                f"{self._crc_text(self._payload_preview_bytes)}"
            ),
        ])
        return "\n".join(lines)

    @staticmethod
    def _crc_text(payload_bytes):
        if not payload_bytes:
            return ""

        return f"{payload_bytes[-1]:02X}"

    def set_payload_preview(self, payload):
        self._payload_preview_bytes = parse_payload_text(payload)
        self._payload_baseline_bytes = list(self._payload_preview_bytes)
        self.txt_coding_preview.setPlainText(
            self._format_payload_bytes(self._payload_preview_bytes)
        )
        self.txt_coding_preview.setExtraSelections([])

    def update_payload_preview_from_raw(
            self,
            _row_index,
            byte_pos,
            bit_pos,
            bit_length,
            raw_value,
        ):
        changed_bytes = self._apply_raw_to_payload_bytes(
            byte_pos,
            bit_pos,
            bit_length,
            raw_value,
        )
        if not changed_bytes:
            return

        self.txt_coding_preview.setPlainText(
            self._format_payload_bytes(self._payload_preview_bytes)
        )
        self._highlight_payload_bytes(changed_bytes)

    def _apply_raw_to_payload_bytes(
            self,
            byte_pos,
            bit_pos,
            bit_length,
            raw_value,
        ):
        result = write_raw_value(
            self._payload_preview_bytes,
            byte_pos,
            bit_pos,
            bit_length,
            raw_value,
        )
        if not result.success:
            return []

        self._payload_preview_bytes = result.payload
        return result.changed_indexes

    @staticmethod
    def _format_payload_bytes(payload_bytes):
        return format_payload_bytes(payload_bytes)

    def _highlight_payload_bytes(self, byte_indexes):
        selections = []

        is_dark = ThemeManager.fn_theme() == ThemeType.DARK

        color = QColor(
            "#FFD54F" if is_dark else "#FFE08A"
        )

        text_color = QColor("#111827")

        for byte_index in byte_indexes:
            start = byte_index * 3

            cursor = QTextCursor(
                self.txt_coding_preview.document()
            )
            cursor.setPosition(start)
            cursor.movePosition(
                QTextCursor.Right,
                QTextCursor.KeepAnchor,
                2,
            )

            selection = QTextEdit.ExtraSelection()
            selection.cursor = cursor
            selection.format = QTextCharFormat()

            selection.format.setBackground(color)
            selection.format.setForeground(text_color)

            selections.append(selection)

        self.txt_coding_preview.setExtraSelections(selections)

    def fn_refresh_theme(self):
        self.setStyleSheet(
            fn_groupbox_style()
        )
        self.file_path.fn_refresh_theme()
        self.cmb_coding_json.fn_refresh_theme()
        self.cmb_default_value.fn_refresh_theme()  
        self.txt_parameter_filter.fn_refresh_theme()

        self.btn_filter_no_m.fn_refresh_theme()
        self.btn_refresh_filter.fn_refresh_theme()
        self.btn_browse.fn_refresh_theme()
        self.btn_import.fn_refresh_theme()
        self.btn_default.fn_refresh_theme()
        self.btn_encode.fn_refresh_theme()
        self.btn_copy.fn_refresh_theme()
        self.btn_clear.fn_refresh_theme()
        self.btn_preview_refresh.fn_refresh_theme()
        self.btn_copy_preview.fn_refresh_theme()
        self.btn_preview_edit.fn_refresh_theme()
        self.btn_check.fn_refresh_theme()
        self.btn_copy_data_payload.fn_refresh_theme()
        self.btn_export.fn_refresh_theme()
        self.btn_table_clear.fn_refresh_theme()
        self.table.fn_refresh_theme()
        self._update_action_states()
        fn_apply_scrollbar_style(
            self.txt_coding_value
        )
        fn_apply_scrollbar_style(
            self.txt_coding_preview
        )
        fn_apply_scrollbar_style(
            self.txt_working_log
        )
