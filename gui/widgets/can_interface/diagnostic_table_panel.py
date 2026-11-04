import re

from dataclasses import replace

from uuid import uuid4

from core.diagnostic_request import SECURITY_SEED_REQUESTS

from html import escape

from pathlib import Path

from PySide6.QtCore import Qt, QSignalBlocker, Signal, QTimer

from PySide6.QtGui import QColor, QFontDatabase, QKeySequence, QShortcut

from PySide6.QtWidgets import (

    QApplication, QHBoxLayout, QHeaderView, QSizePolicy, QWidget,

    QLineEdit, QStyledItemDelegate, QTableWidget, QFileDialog, QMessageBox

)
from core.services.can_diagnostic_report_service import (
    CanDiagnosticReportService,
    CanDiagnosticReportSheet,
    CanDiagnosticReportStep,
)
from gui.themes.theme_manager import ThemeManager

from gui.themes.styles.controls.scrollbar_style import fn_apply_scrollbar_style

from gui.widgets.controls.action_button import ActionButton

from gui.widgets.controls.primary_combobox import PrimaryComboBox

from gui.widgets.controls.primary_label import PrimaryLabel

from gui.widgets.diagnostic.diagnostic_sequence_table import DiagnosticSequenceTable

from gui.widgets.can_interface.panel_theme import apply_panel_theme

from services.can.diag_ecu_mapper import find_ecu_by_can_ids

from gui.themes.styles.controls.lineedit_style import fn_lineedit_style
from gui.themes.styles.controls.table_style import fn_table_style

HEX_FONT_SIZE = 11

HEX_FONT_FAMILY = QFontDatabase.systemFont(
    QFontDatabase.FixedFont
).family()


def fn_hex_font():
    font = QFontDatabase.systemFont(
        QFontDatabase.FixedFont
    )
    font.setPointSize(HEX_FONT_SIZE)
    font.setBold(True)
    return font

def validate_and_format_hex(raw_text: str):

    """

    Validates and formats hex strings for Payload and Expected Response.

    Returns: (is_valid: bool, formatted_text: str, warning_message: str)

    """

    text = str(raw_text or "").strip()

    if not text:

        return True, "", ""

    clean_hex = set("0123456789abcdefABCDEF")
    if any(not (c in clean_hex or c.isspace()) for c in text):
        return False, str(raw_text), "Chứa ký tự không phải HEX"

    tokens = text.split()

    if not tokens:

        return True, "", ""

    bytes_list = []

    for token in tokens:

        if len(token) == 1:

            return False, str(raw_text), "Byte chưa đủ 2 ký tự"

        if len(token) % 2 != 0:

            if len(tokens) == 1:

                return False, str(raw_text), "Số ký tự HEX lẻ"

            return False, str(raw_text), "Byte không đúng định dạng"

        for i in range(0, len(token), 2):

            bytes_list.append(token[i:i+2].upper())

    return True, " ".join(bytes_list), ""


class HexItemDelegate(QStyledItemDelegate):
    """HEX editor for compact diagnostic table cells."""

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor.setObjectName("diagnosticHexEditor")

        editor.setFont(fn_hex_font())

        editor.setAlignment(
            Qt.AlignLeft | Qt.AlignVCenter
        )

        editor.textChanged.connect(
            lambda text: self._on_text_changed(editor, text)
        )

        self._on_text_changed(editor, "")
        
        return editor

    def _apply_editor_style(self, editor, invalid=False):
        colors = ThemeManager.fn_colors()

        state = (ThemeManager.fn_theme(), bool(invalid))
        if getattr(editor, "_hex_style_state", None) == state:
            return

        border_color = (
            colors.WARNING if invalid else colors.PRIMARY
        )
        text_color = (
            colors.WARNING if invalid else colors.TEXT
        )

        selected_text = (
            colors.WINDOW
            if ThemeManager.fn_is_dark()
            else colors.TEXT_INVERT
        )

        mono_font = QFontDatabase.systemFont(
            QFontDatabase.FixedFont
        ).family()

        style = fn_lineedit_style() + f"""
        QLineEdit#diagnosticHexEditor,
        QLineEdit#diagnosticHexEditor:focus {{
            background-color: {colors.WINDOW};
            color: {text_color};

            border: 1px solid {border_color};
            border-radius: 2px;

            padding: 0px 4px;

            font-family: "{mono_font}";

            selection-background-color: {colors.PRIMARY};
            selection-color: {selected_text};
        }}
        """

        editor.setStyleSheet(style)
        editor._hex_style_state = state

    def _on_text_changed(self, editor, text):
        is_valid, _, warning = validate_and_format_hex(text)

        colors = ThemeManager.fn_colors()

        text_color = (
            colors.TEXT if is_valid else colors.WARNING
        )

        border_color = (
            colors.BORDER if is_valid else colors.WARNING
        )

        style = fn_lineedit_style() + f"""
            QLineEdit#diagnosticHexEditor,
            QLineEdit#diagnosticHexEditor:focus {{
                background-color: {colors.WINDOW};
                color: {text_color};
                border: 1px solid {border_color};
                border-radius: 0px;
                padding: 0px;

                font-family: "{HEX_FONT_FAMILY}";
                font-size: {HEX_FONT_SIZE}pt;
                font-weight: bold;
            }}
        """

        editor.setStyleSheet(style)
        editor.setToolTip(
            f"Warning: {warning}" if not is_valid else ""
        )

    def setModelData(self, editor, model, index):
        raw_text = editor.text()
        is_valid, formatted, _ = validate_and_format_hex(
            raw_text
        )

        new_text = (
            formatted if is_valid and formatted else raw_text
        )

        model.setData(index, new_text, Qt.EditRole)



class ReadOnlyHexCell(QLineEdit):
    """Read-only HEX cell using the existing V-CODE theme."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)

        self.setObjectName("receiveMessageCell")
        self.setReadOnly(True)
        self.setFrame(False)
        self.setFont(fn_hex_font())

        self.setAlignment(
            Qt.AlignLeft | Qt.AlignVCenter
        )

        self._style_signature = None
        self.fn_refresh_theme()

    def fn_refresh_theme(self, selected=False, row=0):
        signature = (
            ThemeManager.fn_theme(),
            bool(selected),
            row % 2,
        )

        if signature == self._style_signature:
            return

        colors = ThemeManager.fn_colors()

        # Match the selected-row colors of V-CODE.
        selected_text = (
            colors.WINDOW
            if ThemeManager.fn_is_dark()
            else colors.TEXT_INVERT
        )

        background = (
            colors.PRIMARY
            if selected
            else (
                colors.TABLE_ROW
                if row % 2 == 0
                else colors.TABLE_ROW_ALT
            )
        )

        foreground = (
            selected_text if selected else colors.TEXT
        )

        # Make text selection visible even when the row is selected.
        selection_bg = (
            colors.TABLE_HEADER if selected else colors.PRIMARY
        )

        selection_fg = (
            colors.TEXT if selected else selected_text
        )

        self.setStyleSheet(
            fn_lineedit_style()
            + f"""
            QLineEdit#receiveMessageCell {{
                background-color: {background};
                color: {foreground};
                border: none;
                border-radius: 0px;
                padding: 0px 4px;
                selection-background-color: {selection_bg};
                selection-color: {selection_fg};
                font-family: "{HEX_FONT_FAMILY}";
                font-size: {HEX_FONT_SIZE}pt;
                font-weight: bold;
            }}

            QLineEdit#receiveMessageCell:focus {{
                border: none;
            }}
            """
        )

        self._style_signature = signature

    def mousePressEvent(self, event):
        super().mousePressEvent(event)

        table = self.parent()

        while table is not None and not isinstance(
            table, QTableWidget
        ):
            table = table.parent()

        if table is None:
            return

        point = table.viewport().mapFrom(
            self, event.position().toPoint()
        )

        index = table.indexAt(point)

        if index.isValid():
            table.selectRow(index.row())


class _RowButton(ActionButton):

    def __init__(self):

        super().__init__(">", width=32, height=28)

        self.setToolTip("Send one manual UDS request on the connected channel.")

        self.setAccessibleName("Send this one diagnostic step")

    def fn_refresh_theme(self):

        super().fn_refresh_theme()

        self.setStyleSheet(self.styleSheet() + "QPushButton { padding: 0px; }")

class CanDiagnosticTablePanel(DiagnosticSequenceTable):

    row_selected = Signal(str)

    row_send_requested = Signal(str)

    selected_rows_changed = Signal(tuple)

    save_requested = Signal()

    load_requested = Signal()

    vehicle_changed = Signal(str)

    document_changed=Signal()

    vehicle_configuration_changed=Signal()

    vehicle_resources_changed=Signal()

    sequence_stop_requested = Signal()

    COL_CHECK, COL_STEP, COL_SEQUENCE_NAME, COL_ECU, COL_REQUEST, COL_SEND, COL_DELAY, COL_REPEAT, COL_EXPECTED, COL_RECEIVE, COL_RESULT, COL_COMMENT = range(12)

    HEADERS = ("✓", "Step", "Test sequence name", "ECU", "Payload (HEX)", ">", "Delay (ms)", "Repeat",

               "Expected Response (HEX)", "Receive Message (HEX)", "Results", "Comment")

    OUTCOMES = frozenset(("Pending", "Running", "Passed", "Failed", "Timeout", "Error", "Not Evaluated", "Cancelled"))

    def __init__(self, parent=None, vehicle_service=None):

        self.step_ids = []

        self._checked = set()

        self._runtime = {}

        self._auto_comments = {}

        self._step_signatures = {}

        self._request_busy=False

        self._send_available=True  # Standalone view can still emit typed action intent.

        self.import_diagnostics = ()

        self._is_sequence_running = False
        self._sequence_run_index = -1
        self._step_repeat_counter = 0
        self._sequence_current_loop = 1
        self._sequence_target_loops = 1
        self._sequences_export_provider = None
        self._report_service = CanDiagnosticReportService()

        super().__init__(parent, vehicle_service)

        self._sequence_run_timer = QTimer(self)
        self._sequence_run_timer.setSingleShot(True)
        self._sequence_run_timer.timeout.connect(self._run_next_step)

    def _setup_ui(self):

        super()._setup_ui()

        layout = self.layout()

        layout.setContentsMargins(8, 8, 8, 8)

        layout.removeItem(self.execution_layout)

        self.execution_settings = QWidget()

        self.execution_settings.setLayout(self.execution_layout)

        self.execution_settings.hide()

        self.title = PrimaryLabel("Select a sequence")

        self.title.setTextFormat(Qt.PlainText)

        self.title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        self.title.setMinimumWidth(60)

        self.title.hide()

        self.notice = PrimaryLabel("")

        self.notice.setTextFormat(Qt.PlainText)

        self.notice.setWordWrap(True)

        self.notice.setMaximumHeight(40)

        self.notice.hide()

        self.btn_delete = ActionButton("Delete", width=62, height=30)

        self.btn_load = ActionButton("Load .diag", width=85, height=30)

        self.btn_load.hide()

        self.btn_settings = ActionButton("Setting", width=72, height=30)

        self.btn_settings.setCheckable(True)

        self.btn_settings.toggled.connect(self.execution_settings.setVisible)

        self.btn_add.setText("+Add Row")
        self.btn_add.setFixedHeight(30)
        self.btn_add.setMinimumWidth(80)

        self.btn_delete.setFixedHeight(30)

        self.btn_run.setText("RUN")
        self.btn_run.setFixedWidth(200)
        self.btn_run.setFixedHeight(30)
        self.btn_run.setEnabled(True)
        self.btn_run.show()
        self.btn_run.setToolTip("Run sequence from top to bottom")

        self.btn_export.setText("EXPORT")
        self.btn_export.setFixedWidth(200)
        self.btn_export.setFixedHeight(30)
        self.btn_export.setEnabled(True)
        self.btn_export.show()
        self.btn_export.setToolTip("Export checked sequences to Excel")

        self.btn_stop.setText("STOP")
        self.btn_stop.setFixedWidth(200)
        self.btn_stop.setFixedHeight(30)
        self.btn_stop.setEnabled(False)
        self.btn_stop.show()
        self.btn_stop.setToolTip("Stop sequence execution")

        self.vehicle_selector.setMaximumWidth(210)

        self.vehicle_selector.cmb_vehicle.setMinimumContentsLength(6)

        self.vehicle_selector.cmb_vehicle.setPlaceholderText("Select Vehicle")

        toolbar = QHBoxLayout()

        toolbar.setSpacing(6)

        toolbar.addWidget(self.vehicle_selector)
        toolbar.addWidget(self.btn_add)
        toolbar.addWidget(self.btn_delete)
        toolbar.addWidget(self.btn_run)
        toolbar.addWidget(self.btn_export)
        toolbar.addWidget(self.btn_stop)
        toolbar.addWidget(self.btn_settings)
        toolbar.addStretch(1)

        layout.insertLayout(0, toolbar)

        layout.insertWidget(1, self.execution_settings)

        layout.addWidget(self.notice)

        self.btn_delete.clicked.connect(self.fn_remove_selected_step)

        self.btn_load.clicked.connect(self.load_requested)

        self.btn_run.clicked.connect(self.run_sequence)

        self.btn_stop.clicked.connect(self.stop_sequence)

        self.btn_export.clicked.connect(self.export_diagnostic_report)

        self.table.currentCellChanged.connect(self._selection_changed)
        self.table.itemSelectionChanged.connect(
            self._refresh_receive_selection_colors
        )

        self._copy_shortcut = QShortcut(QKeySequence.Copy, self.table)

        self._copy_shortcut.setContext(Qt.WidgetWithChildrenShortcut)

        self._copy_shortcut.activated.connect(self.copy_current_cell)

        self.hex_delegate = HexItemDelegate(self.table)

        self.receive_delegate = ReceiveMessageDelegate(self.table)

        self.table.setItemDelegateForColumn(
            self.COL_RECEIVE,
            self.receive_delegate
        )

        self.table.setItemDelegateForColumn(self.COL_REQUEST, self.hex_delegate)

        self.table.setItemDelegateForColumn(self.COL_EXPECTED, self.hex_delegate)

    def _configure_columns(self):

        for column, width in enumerate((34, 50, 160, 110, 165, 36, 85, 65, 185, 185, 100, 160)):

            self.table.setColumnWidth(column, width)

            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.Interactive)

        self.table.setMinimumHeight(120)

    def fn_load_sequence(self, test_case):

        if self._is_sequence_running:
            self.stop_sequence()

        self._auto_comments.clear()

        self.step_ids = [uuid4().hex for _ in test_case.steps] if test_case else []

        self._checked.clear()

        self._runtime.clear()

        self.import_diagnostics = ()

        super().fn_load_sequence(test_case)

        self._step_signatures = self._runtime_signatures()

        self.title.setText(test_case.name if test_case else "Select a sequence")

        self.title.setToolTip(self.title.text())

        self.btn_run.setEnabled(bool(test_case and test_case.steps))
        self.btn_stop.setEnabled(False)

        self.notice.clear()

        self.notice.hide()

        self._selection_changed()

        self.document_changed.emit()

    def mark_saved(self):

        self._is_dirty = False

        self.title.setText(self._test_case.name if self._test_case else "Select a sequence")

    def fn_add_step_after_selected(self):

        if self._is_sequence_running:
            self.stop_sequence("Sequence execution stopped: step added.")

        self._ensure_test_case()

        self.step_ids.insert(self._selected_insert_index(), uuid4().hex)

        super().fn_add_step_after_selected()

        self.btn_run.setEnabled(bool(self.step_ids))

    def _replace_steps(self, steps):

        # Preserve user-entered values, including empty names.

        super()._replace_steps(steps)

    def fn_remove_selected_step(self):

        if self._is_sequence_running:
            self.stop_sequence("Sequence execution stopped: step removed.")

        removed = set(self._selected_rows())

        ids = [key for index, key in enumerate(self.step_ids) if index not in removed]

        self._checked.intersection_update(ids)

        self._runtime = {key: value for key, value in self._runtime.items() if key in ids}

        self._auto_comments = {key: value for key, value in self._auto_comments.items() if key in ids}

        self.step_ids = ids

        super().fn_remove_selected_step()

        self.btn_run.setEnabled(bool(self.step_ids))

        self.selected_rows_changed.emit(self.checked_step_ids())

        self._selection_changed()

    def _populate_step_row(self, row, step):

        step_id = self.step_ids[row]

        self._set_item(row, self.COL_CHECK, "", editable=False)

        check = self.table.item(row, self.COL_CHECK)

        check.setFlags(check.flags() | Qt.ItemIsUserCheckable)

        check.setCheckState(Qt.Checked if step_id in self._checked else Qt.Unchecked)

        self._set_item(row, self.COL_STEP, step.step, editable=False)

        self._set_item(row, self.COL_SEQUENCE_NAME, step.sequence_name, editable=True)

        self._set_ecu_combo(row, step.ecu)

        for column, value in ((self.COL_REQUEST, step.request), (self.COL_DELAY, self._format_optional_int(step.delay_ms)),

                              (self.COL_REPEAT, step.repeat), (self.COL_EXPECTED, step.expected_response),

                              (self.COL_COMMENT, step.comment)):

            self._set_item(row, column, value, editable=True)

        button = _RowButton()

        button.clicked.connect(lambda checked=False, key=step_id: self._request_step(key))

        self.table.setCellWidget(row, self.COL_SEND, button)

        cell = self.table.cellWidget(row, self.COL_RECEIVE)

        if not isinstance(cell, ReadOnlyHexCell):

            self.table.setCellWidget(row, self.COL_RECEIVE, ReadOnlyHexCell("—", self.table))

        self._set_button_state(row)

        self._render_runtime(row)

    def _set_item(self, row, column, value, editable):

        super()._set_item(row, column, value, editable)

        item = self.table.item(row, column)

        if item is None:

            return

        item.setToolTip(escape(str(value)))

       
        if column in (
            self.COL_REQUEST,
            self.COL_EXPECTED,
            self.COL_RECEIVE
        ):
            item.setFont(fn_hex_font())

            item.setTextAlignment(
                Qt.AlignLeft | Qt.AlignVCenter
            )

        if column in (self.COL_REQUEST, self.COL_EXPECTED):

            is_valid, formatted, warning = validate_and_format_hex(value)

            colors = ThemeManager.fn_colors()

            if not is_valid:

                item.setForeground(QColor(colors.WARNING))

                item.setToolTip(f"Warning: {warning}")

            else:

                item.setForeground(QColor(colors.TEXT))

    def _updated_step_from_item(self, step, column, text):

        if column == self.COL_SEQUENCE_NAME:

            return replace(

                step,

                sequence_name=text

            )

        if column == self.COL_COMMENT:

            return replace(step, comment=text)

        if column == self.COL_REQUEST:

            is_valid, formatted, _ = validate_and_format_hex(text)

            new_text = formatted if is_valid and formatted else text

            return replace(step, request=new_text)

        if column == self.COL_EXPECTED:

            is_valid, formatted, _ = validate_and_format_hex(text)

            new_text = formatted if is_valid and formatted else text

            return replace(step, expected_response=new_text)

        return super()._updated_step_from_item(

            step, column, text

        )

    def _on_item_changed(self, item):
        if self._is_populating:
            return
        try:
            row = item.row()
            col = item.column()
        except RuntimeError:
            return
        if col == self.COL_CHECK and row < len(self.step_ids):
            key = self.step_ids[row]
            if item.checkState() == Qt.Checked:
                self._checked.add(key)
            else:
                self._checked.discard(key)
            self.selected_rows_changed.emit(self.checked_step_ids())
            return
        super()._on_item_changed(item)
        if row < len(self.step_ids):
            self._set_button_state(row)

    def _mark_dirty(self):

        current = self._runtime_signatures()

        for key in self._step_signatures.keys() | current.keys():

            if self._step_signatures.get(key) != current.get(key):

                self.invalidate_step_result(key)

        self._step_signatures = current

        super()._mark_dirty()

    def _runtime_signatures(self):

        return {key: (step.ecu, step.request, step.expected_response, step.match)

                for key, step in zip(self.step_ids, self._test_case.steps if self._test_case else ())}

    def invalidate_step_result(self, key):

        self._auto_comments.pop(key, None)

        self._runtime.pop(key, None)

        if key in self.step_ids:

            row = self.step_ids.index(key)

            with QSignalBlocker(self.table):

                self._render_runtime(row)

                self._set_button_state(row)

    def _request_step(self, key):

        if key in self.step_ids:

            row=self.step_ids.index(key)

            step=self._test_case.steps[row]

            req_valid, req_fmt, req_warn = validate_and_format_hex(step.request)

            if not req_valid or not step.request.strip():

                self.show_notice(f"Cannot send: {req_warn or 'Invalid or empty HEX payload.'}"); return False

            exp_valid, exp_fmt, exp_warn = validate_and_format_hex(step.expected_response)

            if not exp_valid and step.expected_response.strip():

                self.show_notice(f"Cannot send: {exp_warn}"); return False

            payload = self._request_payload(step.request)

            if payload is None:

                self.show_notice('Invalid or empty HEX payload.'); return False

            if payload[0] == 0x27 and payload not in SECURITY_SEED_REQUESTS:

                self.show_notice('Security Access permits only exact 27 01 requestSeed; key submission is not enabled.'); return False

            if not self._resolved_ecu(step.ecu):

                self.show_notice('Select Vehicle and a configured ECU before sending.'); return False

            if not self._request_busy and self._send_available:
                self.row_send_requested.emit(key)
                return True

        return False

    def set_request_busy(self,busy):

        self._request_busy=bool(busy)

        for row in range(self.table.rowCount()): self._set_button_state(row)

    def set_send_available(self,available):

        self._send_available=bool(available)

        if not self._send_available and self._is_sequence_running:
            self.stop_sequence("Sequence execution stopped: CAN channel not available.")

        if not self._is_sequence_running:
            self.btn_run.setEnabled(bool(self.step_ids))

        for row in range(self.table.rowCount()): self._set_button_state(row)

    def _set_button_state(self, row):

        button = self.table.cellWidget(row, self.COL_SEND)

        if button is None or self._test_case is None or row >= len(self._test_case.steps):

            return

        step = self._test_case.steps[row]

        req_valid, req_fmt, req_warn = validate_and_format_hex(step.request)

        exp_valid, exp_fmt, exp_warn = validate_and_format_hex(step.expected_response)

        payload = self._request_payload(step.request)

        payload_valid = req_valid and payload is not None and bool(step.request.strip())

        security = (

            payload_valid

            and payload[0] == 0x27 and payload not in SECURITY_SEED_REQUESTS

        )

        target_valid = self._resolved_ecu(step.ecu)

        exp_has_error = (not exp_valid) and bool(step.expected_response.strip())

        enabled = (

            self._send_available

            and not self._request_busy

            and not security

            and target_valid

            and payload_valid

            and not exp_has_error

        )

        button.setEnabled(enabled)

        if not req_valid:

            tooltip = f"Warning: {req_warn}"

        elif exp_has_error:

            tooltip = f"Warning: {exp_warn}"

        elif not payload_valid:

            tooltip = "Invalid or empty HEX payload."

        elif security:

            tooltip = "Only exact 27 01 requestSeed is enabled; key submission is disabled."

        elif not target_valid:

            tooltip = "Select a configured ECU."

        elif self._request_busy:

            tooltip = "A diagnostic request is running."

        elif not self._send_available:

            tooltip = "Connect Vector first."

        elif payload in SECURITY_SEED_REQUESTS:

            tooltip = ("Auto SecurityAccess L1: two UDS transactions; final ECU 67 02 required."

                       if self._request_payload(step.expected_response) == b'\x67\x02' else

                       "Request seed manually with 27 01; no key submission or ECU unlock.")

        else:

            tooltip = "Send one manual UDS request."

        button.setToolTip(tooltip)

    def show_notice(self, text):

        self.notice.setText(text)

        self.notice.setToolTip(escape(text))

        self.notice.setVisible(bool(text))

    def checked_step_ids(self):

        return tuple(key for key in self.step_ids if key in self._checked)

    def selected_step_id(self):

        row = self.table.currentRow()

        return self.step_ids[row] if 0 <= row < len(self.step_ids) else ""

    def _selection_changed(self, *_):

        self.row_selected.emit(self.selected_step_id())

    def step_for_id(self, key):

        if key not in self.step_ids:

            return None

        return self._test_case.steps[self.step_ids.index(key)]

    def set_step_running(self, key):

        self.set_step_result(key, "", "Running")

    def set_auto_step_result(self, key, received_payload, outcome, detail):

        """Runtime-only annotation; never mutate the editable sequence model."""

        self._auto_comments[key] = detail

        return self.set_step_result(key, received_payload, outcome, detail)

    def set_step_result(self, key, received_payload, outcome, detail=""):

        if key not in self.step_ids:

            return False

        payload = self._normalize_hex(received_payload, allow_empty=True)

        if payload is None or outcome not in self.OUTCOMES:

            raise ValueError("Invalid runtime result")

        self._runtime[key] = (payload, outcome, detail)

        with QSignalBlocker(self.table):

            self._render_runtime(self.step_ids.index(key))

        if self._is_sequence_running and outcome != "Running":
            if 0 <= self._sequence_run_index < len(self.step_ids) and self.step_ids[self._sequence_run_index] == key:
                self._schedule_next_step()

        return True

    def _render_runtime(self, row):

        payload, outcome, detail = self._runtime.get(self.step_ids[row], ("—", "—", ""))

        self._set_item(row, self.COL_RECEIVE, payload, editable=False)

        self._set_item(row, self.COL_RESULT, outcome, editable=False)

        self.table.item(row, self.COL_RESULT).setToolTip(detail or outcome)

        # Update ReadOnlyHexCell widget in COL_RECEIVE

        cell = self.table.cellWidget(row, self.COL_RECEIVE)

        if not isinstance(cell, ReadOnlyHexCell):

            cell = ReadOnlyHexCell(payload, self.table)

            self.table.setCellWidget(row, self.COL_RECEIVE, cell)

        else:
            if cell.text() != payload:
                cell.setText(payload)

        # Task 5: Comment is 100% user-managed: never overwrite with auto_comments

        selection_model = self.table.selectionModel()
        model = self.table.model()

        if selection_model is None:
            return

        index = model.index(row, self.COL_RECEIVE)
        is_selected = selection_model.isSelected(index)

        cell.fn_refresh_theme(
            selected=is_selected,
            row=row,
        )


        step = self._test_case.steps[row]

        self._set_item(row, self.COL_COMMENT, step.comment, editable=True)

        colors = ThemeManager.fn_colors()

        color = colors.SUCCESS if outcome == "Passed" else colors.DANGER if outcome in ("Failed", "Error", "Timeout") else colors.WARNING if outcome in ("Pending", "Running") else colors.TEXT

        self.table.item(row, self.COL_RESULT).setForeground(QColor(color))

    def reset_runtime_results(self):

        self._auto_comments.clear()

        self._runtime.clear()

        with QSignalBlocker(self.table):

            for row in range(self.table.rowCount()):

                self._render_runtime(row)

    def run_sequence(self):
        if self._is_sequence_running:
            return
        if not self.step_ids:
            self.show_notice("No steps in the sequence to run.")
            return
        if not self._send_available:
            self.show_notice("Connect Vector first.")
            return
        self._is_sequence_running = True
        self._sequence_run_index = 0
        self._step_repeat_counter = 0
        self._sequence_current_loop = 1
        self._sequence_target_loops = self.spn_loop.value() if hasattr(self, "spn_loop") else 1
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._execute_step_at_index(0)

    def stop_sequence(self, notice: str = "Sequence execution stopped."):
        self._is_sequence_running = False
        self._sequence_run_timer.stop()
        self.btn_run.setEnabled(bool(self.step_ids))
        self.btn_stop.setEnabled(False)
        self.sequence_stop_requested.emit()
        if notice:
            self.show_notice(notice)

    def _execute_step_at_index(self, index: int):
        if not self._is_sequence_running:
            return
        if index >= len(self.step_ids):
            self.stop_sequence("Sequence execution completed.")
            return
        key = self.step_ids[index]
        self._select_row(index)
        sent = self._request_step(key)
        if not sent:
            if not self._send_available:
                self.stop_sequence("Sequence execution stopped: CAN channel not available.")
            else:
                self.set_step_result(key, "", "Error", "Cannot send request")

    def _schedule_next_step(self):
        if not self._is_sequence_running:
            return

        delay_ms = 100
        repeat = 1
        if 0 <= self._sequence_run_index < len(self.step_ids) and self._test_case is not None:
            if self._sequence_run_index < len(self._test_case.steps):
                step = self._test_case.steps[self._sequence_run_index]
                repeat = max(1, step.repeat)
                if step.delay_ms is not None and step.delay_ms >= 0:
                    delay_ms = step.delay_ms
                elif hasattr(self, "spn_command_delay"):
                    delay_ms = self.spn_command_delay.value()

        if self._step_repeat_counter + 1 < repeat:
            self._step_repeat_counter += 1
            self._sequence_run_timer.start(delay_ms)
            return

        self._step_repeat_counter = 0
        self._sequence_run_index += 1

        if self._sequence_run_index >= len(self.step_ids):
            if self._sequence_current_loop < self._sequence_target_loops:
                self._sequence_current_loop += 1
                self._sequence_run_index = 0
                self._sequence_run_timer.start(delay_ms)
                return
            self.stop_sequence("Sequence execution completed.")
            return

        self._sequence_run_timer.start(delay_ms)

    def _run_next_step(self):
        if not self._is_sequence_running:
            return
        if self._sequence_run_index >= len(self.step_ids):
            self.stop_sequence("Sequence execution completed.")
            return
        self._execute_step_at_index(self._sequence_run_index)

    def fn_set_sequences_export_provider(self, provider):
        self._sequences_export_provider = provider

    def get_export_rows(self) -> list[CanDiagnosticReportStep]:
        rows: list[CanDiagnosticReportStep] = []
        for row_idx in range(self.table.rowCount()):
            step_id = self.step_ids[row_idx] if row_idx < len(self.step_ids) else ""
            step_item = self.table.item(row_idx, self.COL_STEP)
            step_val = step_item.text() if step_item else str(row_idx + 1)

            name_item = self.table.item(row_idx, self.COL_SEQUENCE_NAME)
            name_val = name_item.text() if name_item else ""

            ecu_widget = self.table.cellWidget(row_idx, self.COL_ECU)
            ecu_val = ecu_widget.currentText() if ecu_widget and hasattr(ecu_widget, "currentText") else ""

            req_item = self.table.item(row_idx, self.COL_REQUEST)
            req_val = req_item.text() if req_item else ""

            delay_item = self.table.item(row_idx, self.COL_DELAY)
            delay_val = delay_item.text() if delay_item else ""

            repeat_item = self.table.item(row_idx, self.COL_REPEAT)
            repeat_val = repeat_item.text() if repeat_item else "1"

            exp_item = self.table.item(row_idx, self.COL_EXPECTED)
            exp_val = exp_item.text() if exp_item else ""

            recv_widget = self.table.cellWidget(row_idx, self.COL_RECEIVE)
            recv_val = recv_widget.text() if recv_widget and hasattr(recv_widget, "text") else ""
            if recv_val == "—":
                recv_val = ""
            if not recv_val and step_id in self._runtime:
                recv_val = self._runtime[step_id][0] or ""

            res_item = self.table.item(row_idx, self.COL_RESULT)
            res_val = res_item.text() if res_item else ""
            if (not res_val or res_val == "—") and step_id in self._runtime:
                res_val = self._runtime[step_id][1] or ""

            comment_item = self.table.item(row_idx, self.COL_COMMENT)
            comment_val = comment_item.text() if comment_item else ""

            rows.append(
                CanDiagnosticReportStep(
                    step=step_val,
                    sequence_name=name_val,
                    ecu=ecu_val,
                    payload=req_val,
                    delay_ms=delay_val,
                    repeat=repeat_val,
                    expected_response=exp_val,
                    receive_message=recv_val,
                    results=res_val,
                    comment=comment_val,
                )
            )
        return rows

    def _build_diagnostic_report_sheets(self) -> list[CanDiagnosticReportSheet]:
        sheets: list[CanDiagnosticReportSheet] = []
        if self._sequences_export_provider is not None:
            sequences_data = self._sequences_export_provider()
        else:
            sequences_data = []

        if not sequences_data:
            if self._test_case is not None:
                title = self._test_case.name or "Diagnostic"
                sheets.append(CanDiagnosticReportSheet(title=title, rows=self.get_export_rows()))
            return sheets

        for case, custom_rows in sequences_data:
            if case is None:
                continue
            title = case.name or "Diagnostic"
            if custom_rows is not None:
                sheet_rows = list(custom_rows)
            else:
                sheet_rows = []
                for step in case.steps:
                    sheet_rows.append(
                        CanDiagnosticReportStep(
                            step=str(step.step),
                            sequence_name=step.sequence_name,
                            ecu=step.ecu,
                            payload=step.request,
                            delay_ms=str(step.delay_ms if step.delay_ms is not None else ""),
                            repeat=str(step.repeat),
                            expected_response=step.expected_response,
                            receive_message="",
                            results="",
                            comment=step.comment,
                        )
                    )
            sheets.append(CanDiagnosticReportSheet(title=title, rows=sheet_rows))
        return sheets

    def _choose_diagnostic_report_file(self) -> Path | None:
        default_path = self._report_service.default_report_path()
        output_file, _ = QFileDialog.getSaveFileName(
            self,
            "Save Diagnostic Report",
            str(default_path),
            "Excel Files (*.xlsx)",
        )
        if not output_file:
            return None
        path = Path(output_file)
        if path.suffix.lower() != ".xlsx":
            path = path.with_suffix(".xlsx")
        return path

    def export_diagnostic_report(self, output_file: str | Path | None = None) -> Path | None:
        sheets = self._build_diagnostic_report_sheets()
        if not sheets:
            self.show_notice("No sequence data to export.")
            return None

        if output_file is None:
            output_file = self._choose_diagnostic_report_file()
            if output_file is None:
                return None

        try:
            exported_path = self._report_service.export_report(
                sheets,
                output_file,
            )
        except PermissionError:
            QMessageBox.warning(
                self,
                "Diagnostic Report",
                "Cannot save Diagnostic report. Please close the Excel file and try again.",
            )
            return None
        except Exception as error:
            self.show_notice(f"Export error: {error}")
            return None

        self.show_notice(f"Diagnostic report exported: {exported_path.name}")
        QMessageBox.information(
            self,
            "Diagnostic Report",
            f"Diagnostic report saved:\n\n{exported_path}",
        )
        return exported_path

    def copy_current_cell(self):
        focus = QApplication.focusWidget()
        if isinstance(focus, QLineEdit) and focus.hasSelectedText():
            QApplication.clipboard().setText(focus.selectedText())
            return
        for r in range(self.table.rowCount()):
            cell = self.table.cellWidget(r, self.COL_RECEIVE)
            if isinstance(cell, QLineEdit) and cell.hasSelectedText():
                QApplication.clipboard().setText(cell.selectedText())
                return
        item = self.table.currentItem()
        if item is not None:
            QApplication.clipboard().setText(item.text())

    def _transport_configuration(self):

        if self._current_vehicle is None:

            return None

        return (self._current_vehicle_name, tuple(sorted(

            (ecu.name, ecu.request_id, ecu.response_id) for ecu in self._available_ecus)))

    
    def _refresh_receive_selection_colors(self):
        selection_model = self.table.selectionModel()
        model = self.table.model()

        if selection_model is None:
            return

        for row in range(self.table.rowCount()):
            cell = self.table.cellWidget(
                row, self.COL_RECEIVE
            )

            if not isinstance(cell, ReadOnlyHexCell):
                continue

            index = model.index(row, self.COL_RECEIVE)
            is_selected = selection_model.isSelected(index)

            cell.fn_refresh_theme(
                selected=is_selected,
                row=row,
            )

    
    def fn_refresh_vehicles(self, selected_vehicle_name="", *, preserve_unchanged=False):

        previous = self._transport_configuration()

        chosen = selected_vehicle_name or self._current_vehicle_name

        try:

            names = self._vehicle_service.list_vehicles()

        except Exception as error:

            names = []

            self.show_notice(f"Cannot load vehicles: {error}")

        self.vehicle_selector.fn_set_vehicles(names, chosen if chosen in names else "", allow_empty_selection=True)

        self._load_vehicle_by_name(self.vehicle_selector.fn_vehicle())

        self._apply_diag_ecu_mapping()

        self._refresh_ecu_combos()

        if preserve_unchanged and previous is not None and previous == self._transport_configuration():

            self.vehicle_resources_changed.emit()

        else:

            self.reset_runtime_results()

            self.vehicle_configuration_changed.emit()

    def _on_vehicle_changed(self, vehicle_name):

        self.reset_runtime_results()

        # Load newly selected Vehicle and its ECU definitions.

        super()._on_vehicle_changed(vehicle_name)

        # Map imported .diag addressing to V-CODE ECU names.

        self._apply_diag_ecu_mapping()

        if vehicle_name and self._current_vehicle is None:

            self.show_notice(

                f"Cannot load Vehicle '{vehicle_name}'."

            )

        self.vehicle_changed.emit(vehicle_name)

        self.vehicle_configuration_changed.emit()

    def fn_set_vehicle(self, vehicle):

        self.reset_runtime_results()

        super().fn_set_vehicle(vehicle)

        self._apply_diag_ecu_mapping()

        self.vehicle_configuration_changed.emit()

    def _set_ecu_combo(self, row, ecu):

        combo = PrimaryComboBox(minimum_height=28)

        # Populate only valid, uniquely named ECU definitions.

        valid_ecus = [

            item

            for item in self._available_ecus

            if self._resolved_ecu(item.name)

        ]

        for item in valid_ecus:

            combo.addItem(item.name, item)

        # No empty item at index 0.

        # -1 means no ECU has been selected.

        selected_index = combo.findText(ecu) if ecu else -1

        if selected_index >= 0:

            combo.setCurrentIndex(selected_index)

        else:

            combo.setCurrentIndex(-1)

        # Show empty editor text when no ECU is selected,

        # without creating a selectable blank option.

        combo.setPlaceholderText("")

        if self._current_vehicle is None:

            tooltip = "Select a Vehicle first."

        elif not ecu:

            tooltip = "Select an ECU."

        elif selected_index < 0:

            tooltip = (

                f"ECU '{ecu}' is not configured "

                "in the selected Vehicle."

            )

        else:

            tooltip = ecu

        combo.setToolTip(escape(tooltip))

        key = self.step_ids[row]

        combo.currentIndexChanged.connect(

            lambda index, target=key, control=combo:

                self._ecu_changed(target, control)

        )

        fn_apply_scrollbar_style(combo.view())

        self.table.setCellWidget(

            row,

            self.COL_ECU,

            combo,

        )

    def _resolved_ecu(self, name):

        return bool(name and name.strip() and self._current_vehicle is not None

                    and sum(ecu.name == name for ecu in self._available_ecus) == 1)

    def unresolved_ecus(self):

        if self._current_vehicle is None or self._test_case is None:

            return ()

        return tuple((row + 1, step.ecu) for row, step in enumerate(self._test_case.steps)

                     if not self._resolved_ecu(step.ecu))

    def _refresh_ecu_combos(self):

        super()._refresh_ecu_combos()

        for row in range(self.table.rowCount()):

            self._set_button_state(row)

        # Empty ECU is a valid draft state.

        # Only show a warning for nonempty unresolved ECU names.

        unknown = tuple(

            (row, name)

            for row, name in self.unresolved_ecus()

            if str(name or "").strip()

        )

        if unknown:

            details = "\n".join(

                f"Row {row}: {name}"

                for row, name in unknown

            )

            self.show_notice(

                f"{len(unknown)} unresolved ECU(s)."

            )

            self.notice.setToolTip(details)

        else:

            # Clear only an ECU warning previously set by this method.

            if self.notice.text().endswith("unresolved ECU(s)."):

                self.show_notice("")

    def sequence_for_save(self):

        """

        Save editor content as-is.

        Empty ECU, incomplete HEX and empty sequence names

        are allowed in saved drafts.

        ECU resolution and HEX validation are required

        before sending diagnostic requests.

        """

        return self._test_case

    def exchange_text(self):

        from core.sequence_exchange import export_sequence_text

        case = self.sequence_for_save()

        return export_sequence_text(case.steps if case else (),

                                    [self._runtime.get(key, ('', '', ''))[1] for key in self.step_ids])

    def apply_import(self, imported, mode):

        if mode not in ('append', 'replace') or self._test_case is None:

            raise ValueError('Select an active document and explicit Append or Replace mode.')

        if mode == 'replace':

            self.fn_load_sequence(replace(self._test_case, steps=list(imported.steps)))

        else:

            self.step_ids.extend(uuid4().hex for _ in imported.steps)

            self._replace_steps([*self._test_case.steps, *imported.steps])

            self._reload_steps_into_table()

        self.import_diagnostics = imported.diagnostics

        self._mark_dirty()

        self._refresh_ecu_combos()

        if imported.diagnostics:

            self.show_notice('\n'.join(imported.diagnostics))

    def _ecu_changed(self, key, combo):

        value = combo.currentData()

        if key not in self.step_ids or self._is_populating:

            return

        row = self.step_ids.index(key)

        name = value.name if value is not None else ''

        step = self._test_case.steps[row]

        if step.ecu != name:

            steps = list(self._test_case.steps)

            steps[row] = replace(step, ecu=name)

            self._replace_steps(steps)

            self._mark_dirty()

    def _apply_diag_ecu_mapping(self):

        """

        Remap steps imported from .diag using the

        currently selected Vehicle.

        Do not alter steps without original CAN IDs.

        """

        if self._test_case is None:

            return False

        changed = False

        steps = list(self._test_case.steps)

        for index, step in enumerate(steps):

            # Native manually created steps remain untouched.

            if (

                step.source_request_id is None

                or step.source_response_id is None

            ):

                continue

            mapped_name = find_ecu_by_can_ids(

                self._current_vehicle,

                step.source_request_id,

                step.source_response_id,

            )

            # No match or ambiguous match -> empty ECU.

            if step.ecu != mapped_name:

                steps[index] = replace(

                    step,

                    ecu=mapped_name,

                )

                changed = True

        if not changed:

            return False

        # Update the document model.

        self._replace_steps(steps)

        # Update ECU comboboxes without triggering user edits.

        self._refresh_ecu_combos()

        # Update unsaved RAM draft and the "*" indicator.

        self._mark_dirty()

        return True

    @staticmethod

    def _is_valid_request_hex(value):

        text = str(value or "").strip()

        if not text:

            return False

        tokens = text.split()

        return all(

            re.fullmatch(r"[0-9A-Fa-f]{2}", token)

            for token in tokens

        )

    @classmethod
    def _request_payload(cls, value):
        tokens = str(value or "").split()
        if not tokens or not all(len(t) == 2 and set(t) <= set("0123456789abcdefABCDEF") for t in tokens):
            return None
        try:
            return bytes.fromhex(" ".join(tokens))
        except ValueError:
            return None

    
    def fn_refresh_theme(self):
        apply_panel_theme(self, "canDiagnosticTablePanel")

        with QSignalBlocker(self.table):
            super().fn_refresh_theme()

            colors = ThemeManager.fn_colors()

            # Match the foreground of selected table rows.
            selected_text = (
                colors.WINDOW
                if ThemeManager.fn_is_dark()
                else colors.TEXT_INVERT
            )

            # Reuse the existing V-CODE table style.
            # Only override selection foreground locally.
            self.table.setStyleSheet(
                fn_table_style()
                + f"""
                QTableWidget::item:selected {{
                    background-color: {colors.PRIMARY};
                    color: {selected_text};
                }}
                """
            )

            for widget in (
                self.title,
                self.notice,
                self.btn_delete,
                self.btn_load,
                self.btn_settings,
            ):
                widget.fn_refresh_theme()

            for row in range(self.table.rowCount()):
                send_button = self.table.cellWidget(
                    row, self.COL_SEND
                )

                if send_button is not None:
                    send_button.fn_refresh_theme()

                ecu_combo = self.table.cellWidget(
                    row, self.COL_ECU
                )

                if ecu_combo is not None:
                    fn_apply_scrollbar_style(
                        ecu_combo.view()
                    )

                self._render_runtime(row)

        self._refresh_receive_selection_colors()


class ReceiveMessageDelegate(QStyledItemDelegate):
    """Keep model data but do not paint duplicate text."""

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.text = ""