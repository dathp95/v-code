from collections import deque
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget, QSizePolicy
from core.can_interface_view import CanFrameView
from gui.widgets.controls.action_button import ActionButton
from gui.widgets.controls.primary_combobox import PrimaryComboBox
from gui.widgets.controls.primary_lineedit import PrimaryLineEdit
from gui.widgets.controls.primary_label import PrimaryLabel
from gui.widgets.can_interface.can_monitor_model import CanMonitorTable
from gui.widgets.can_interface.panel_theme import apply_panel_theme


class CanMonitorPanel(QWidget):
    def __init__(self, capacity=2000):
        super().__init__()
        if isinstance(capacity, bool) or not isinstance(capacity, int) or not 1 <= capacity <= 10000:
            raise ValueError("Monitor display capacity must be in range 1..10000.")
        self._buffer = deque(maxlen=capacity)
        self._monitoring_state='Not monitoring'
        self._recording_state=''
        self._recording_error=''
        self._export_notice=''
        self._filter_error=''
        self.frames = self.displayed = self.dropped = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        header = QHBoxLayout()
        self.title = PrimaryLabel("CAN Monitor")
        self.title.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred)
        self.title.setMinimumWidth(80)
        self.status = PrimaryLabel("Not monitoring")
        self.status.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Preferred)
        self.status.setMinimumWidth(105)
        self.btn_clear = ActionButton("Clear", width=55, height=30)
        self.btn_export = ActionButton("Export CSV", width=85, height=30)
        self.btn_blf = ActionButton("Start BLF Log", width=100, height=30)
        self.btn_logs = ActionButton("Logs", width=55, height=30)
        self.btn_export.setEnabled(False)
        self.btn_blf.setEnabled(False)
        self.btn_export.setToolTip("Export retained frames matching the view filters, not a complete raw log.")
        self.btn_blf.setToolTip("Connect a CAN channel to record raw traffic independently of this view.")
        self.btn_logs.setToolTip("Open diagnostic anomalies and application logs folder.")
        header.addWidget(self.title, 1)
        header.addWidget(self.status)
        for button in (self.btn_clear, self.btn_export, self.btn_blf, self.btn_logs): header.addWidget(button)
        filters = QHBoxLayout()
        self.edit_can_id = PrimaryLineEdit("CAN ID filter (HEX)")
        self.cmb_direction = PrimaryComboBox(minimum_height=30)
        self.cmb_direction.addItems(("All", "TX", "RX"))
        filters.addWidget(self.edit_can_id, 1)
        filters.addWidget(self.cmb_direction)
        self.table = CanMonitorTable()
        for column, width in enumerate((85, 45, 85, 45, 180)): self.table.setColumnWidth(column, width)
        self.feedback = PrimaryLabel("")
        self.feedback.setWordWrap(True)
        self.feedback.hide()
        self.counters = PrimaryLabel("")
        layout.addLayout(header)
        layout.addLayout(filters)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.feedback)
        layout.addWidget(self.counters)
        self.btn_clear.clicked.connect(self.clear_display)
        self.btn_logs.clicked.connect(self._open_logs)
        self.edit_can_id.textChanged.connect(self._render)
        self.cmb_direction.currentTextChanged.connect(self._render)
        self._render()

    def append_frame_batch(self, frames, *, dropped=0):
        if QThread.currentThread() != self.thread():
            raise RuntimeError("Monitor view updates must run on the GUI thread.")
        try:
            self.dropped+=dropped
            for frame in frames:
                if not isinstance(frame, CanFrameView):
                    raise TypeError("Expected CanFrameView presentation data.")
                if len(self._buffer) == self._buffer.maxlen:
                    self.dropped += 1
                self._buffer.append(frame)
                self.frames += 1
        finally:
            self._render()

    def clear_display(self):
        self._buffer.clear()
        self.frames = self.displayed = self.dropped = 0
        self._render()

    def set_monitoring_state(self, state):
        if state not in ('Not monitoring','Captured during request','Capture stopped','Monitoring','Stopped'):
            raise NotImplementedError("Continuous monitoring is not implemented.")
        self._monitoring_state=state
        self._status()

    def _status(self):
        self.status.setText(self._monitoring_state+('\n'+self._recording_state if self._recording_state else ''))

    def set_recording_snapshot(self,snapshot,connected):
        state=snapshot.state
        self._recording_state=state if state!='STOPPED' else 'Saved' if snapshot.complete else ''
        self._recording_error=snapshot.error
        self.btn_blf.setText('Stop BLF Log' if state=='RECORDING' else 'Opening...' if state=='STARTING' else 'Stopping...' if snapshot.busy else 'Start BLF Log')
        self.btn_blf.setEnabled(state=='RECORDING' or (connected and not snapshot.busy))
        detail=(f'{snapshot.path}\nState: {state}; captured: {snapshot.captured}; written: {snapshot.written}; '
                f'dropped/rejected: {snapshot.dropped}; paired echoes: {snapshot.echoes}; '
                f'adjusted timestamps: {snapshot.adjusted_timestamps}; fallback: {snapshot.fallback_timestamps}; '
                f'finalized: {snapshot.finalized}\n{snapshot.error}')
        self.btn_blf.setToolTip(detail)
        self.status.setToolTip(detail)
        self._status()
        self._feedback()

    def show_export_notice(self,text):
        self._export_notice=text
        self._feedback()

    def _feedback(self):
        text='\n'.join(value for value in (self._filter_error,self._recording_error,self._export_notice) if value)
        self.feedback.setText(text)
        self.feedback.setVisible(bool(text))

    def retained_frames(self,filtered=False):
        if not filtered: return tuple(self._buffer)
        text=self.edit_can_id.text().strip()
        try:
            can_id=int(text,16) if text else None
            if can_id is not None and not 0<=can_id<=0x1FFFFFFF: return ()
        except ValueError: return ()
        return tuple(frame for frame in self._buffer if (can_id is None or frame.can_id==can_id)
            and (self.cmb_direction.currentText()=='All' or frame.direction==self.cmb_direction.currentText()))

    def set_logging_state(self, state, path=None):
        if state != "Stopped" or path is not None:
            raise NotImplementedError("BLF logging is unavailable in M03.")

    def _render(self, *_):
        text = self.edit_can_id.text().strip()
        try:
            can_id = int(text, 16) if text else None
            if can_id is not None and not 0 <= can_id <= 0x1FFFFFFF:
                raise ValueError()
            self._filter_error=''
            frames = [frame for frame in self._buffer if (can_id is None or frame.can_id == can_id)
                      and (self.cmb_direction.currentText() == 'All' or frame.direction == self.cmb_direction.currentText())]
        except ValueError:
            frames = []
            self._filter_error="Invalid CAN ID filter. Enter HEX digits."
        self._feedback()
        self.table.model().set_frames(frames)
        self.displayed = len(frames)
        self.btn_export.setEnabled(bool(self._buffer))
        self.counters.setText(f"Frames: {self.frames}    Displayed: {self.displayed}    Dropped: {self.dropped}")

    def _open_logs(self):
        from services.logging_service import open_logs_folder
        open_logs_folder()

    def fn_refresh_theme(self):
        apply_panel_theme(self, "canMonitorPanel")
        self.title.fn_refresh_theme()
        self.table.fn_refresh_theme()
        for widget in (self.status, self.btn_clear, self.btn_export, self.btn_blf, self.btn_logs, self.edit_can_id, self.cmb_direction, self.feedback, self.counters):
            widget.fn_refresh_theme()
        from gui.themes.styles.controls.scrollbar_style import fn_apply_scrollbar_style
        fn_apply_scrollbar_style(self.cmb_direction.view())
