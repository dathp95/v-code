from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QSplitter, QWidget

from gui.controllers.can_connection_controller import CanConnectionController
from gui.controllers.can_workspace_controller import CanWorkspaceController
from gui.controllers.can_diagnostic_controller import CanDiagnosticController
from gui.controllers.can_recording_controller import CanRecordingController
from gui.controllers.can_dll_resource_controller import CanDllResourceController
from gui.widgets.can_interface.can_monitor_panel import CanMonitorPanel
from gui.widgets.can_interface.session_panel import CanSessionPanel
from gui.widgets.can_interface.sequence_sidebar import CanSequenceSidebar
from gui.widgets.can_interface.diagnostic_table_panel import CanDiagnosticTablePanel
from services.can import CANService
from repositories.can_interface_ui_store import CanInterfaceUiStore
from repositories.can_sequence_repository import CanSequenceRepository
from gui.themes.theme_manager import ThemeManager


class CANInterfaceTab(QWidget):
    """Compose the workspace; connection lifecycle belongs to its controller."""

    def __init__(self, service=None, *, vehicle_service=None, sequence_repository=None, ui_store=None):
        super().__init__()
        if vehicle_service is None:
            try:
                from services.vehicle_service import VehicleService
                vehicle_service = VehicleService()
            except Exception:
                vehicle_service = None
        self._service = service if service is not None else CANService()
        if vehicle_service is not None:
            self._service.vehicle_service = vehicle_service
        self.ui_store = ui_store if ui_store is not None else CanInterfaceUiStore()
        preferences = self.ui_store.load()
        repository = (
            sequence_repository
            if sequence_repository is not None
            else CanSequenceRepository()
        )
        self.sequence_list = CanSequenceSidebar(repository=repository, store=self.ui_store)
        self.sequence_table = CanDiagnosticTablePanel(vehicle_service=vehicle_service)
        self.session_panel = CanSessionPanel()
        self.monitor_panel = CanMonitorPanel()
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.right_splitter = QSplitter(Qt.Vertical)
        self.bottom_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.addWidget(self.sequence_list)
        self.main_splitter.addWidget(self.right_splitter)
        self.right_splitter.addWidget(self.sequence_table)
        self.right_splitter.addWidget(self.bottom_splitter)
        self.bottom_splitter.addWidget(self.session_panel)
        self.bottom_splitter.addWidget(self.monitor_panel)
        for splitter, sizes in ((self.main_splitter, (210, 790)), (self.right_splitter, (650, 350)),
                                (self.bottom_splitter, (450, 550))):
            splitter.setChildrenCollapsible(False)
            splitter.setSizes(sizes)
            for index, size in enumerate(sizes):
                splitter.setStretchFactor(index, size)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.main_splitter)
        self.connection_controller = CanConnectionController(self._service, self.session_panel.connection, self)
        # Preserve existing CAN tab action/control access for callers and M02 tests.
        for name in self.session_panel.connection.CONTROLS:
            setattr(self, name, getattr(self.session_panel.connection, name))
        self._connection_task = self.connection_controller._connection_task
        self._discovery_task = self.connection_controller._discovery_task
        self.workspace_controller = CanWorkspaceController(self.sequence_list, self.sequence_table, repository, self.ui_store, self)
        self.diagnostic_controller=CanDiagnosticController(self.sequence_table,self.monitor_panel,self._service,self._connection_task,self)
        self.diagnostic_controller.security_status_changed.connect(self.session_panel.current_test_case.security_status.setText)
        self.diagnostic_controller.security_key_result_changed.connect(self.session_panel.current_test_case.key_result.setText)
        self.diagnostic_controller.bind_unlock_action(self.session_panel.current_test_case.btn_unlock_l1)
        self.session_panel.current_test_case.security_status.setText(self.diagnostic_controller.security_session.status_text)
        self.recording_controller=CanRecordingController(self.monitor_panel,self._connection_task,self._service,
                                                        self.sequence_table.fn_current_vehicle,self)
        self.sequence_table.row_selected.connect(self._update_current_step)
        self.sequence_table.sequence_modified.connect(self._update_current_step)
        self.dll_resource_controller = CanDllResourceController(
            self.sequence_table, self.session_panel.current_test_case, self)
        self.sequence_table.fn_set_sequences_export_provider(self._get_sequences_to_export)
        self.workspace_controller.restore()
        self.fn_refresh_theme()

    def _get_sequences_to_export(self):
        checked_paths = self.sequence_list.checked_ids()
        current_case = self.sequence_table.fn_current_sequence()
        current_source = str(self.workspace_controller.source.resolve()) if self.workspace_controller.source else None

        if not checked_paths:
            if current_case:
                return [(current_case, self.sequence_table.get_export_rows())]
            return []

        result = []
        for path in checked_paths:
            p_res = str(Path(path).resolve()) if path else ""
            if current_source and p_res == current_source and current_case:
                result.append((current_case, self.sequence_table.get_export_rows()))
            else:
                try:
                    case = self.workspace_controller._case_for_source(path)
                    result.append((case, None))
                except Exception:
                    pass
        return result

    def _on_sequence_selected(self, test_case):
        self.sequence_table.fn_load_sequence(test_case)

    def _update_current_step(self, *_):
        key = self.sequence_table.selected_step_id()
        self.session_panel.current_test_case.display_step(self.sequence_table.step_for_id(key), len(self.sequence_table.step_ids))

    def refresh_can_setup(self):
        self.connection_controller.refresh_can_setup()

    def connect_can(self):
        self.connection_controller.connect_can()

    def disconnect_can(self):
        self.connection_controller.disconnect_can()

    def fn_refresh_vehicles(self, changed_name=""):
        self.workspace_controller.refresh_vehicles(changed_name)

    def showEvent(self, event):
        manager = getattr(self.window(), "vehicle_manager_tab", None)
        if manager is not None and manager is not getattr(self, "_vehicle_event_source", None):
            manager.vehicle_data_changed.connect(self.fn_refresh_vehicles)
            self._vehicle_event_source = manager
        super().showEvent(event)

    def closeEvent(self, event):
        self.recording_controller.close()
        self.diagnostic_controller.close()
        self.connection_controller.close()
        super().closeEvent(event)

    def fn_refresh_theme(self):
        self.setObjectName("canInterfaceWorkspace")
        self.setAttribute(Qt.WA_StyledBackground, True)
        colors = ThemeManager.fn_colors()
        self.setStyleSheet(f"QWidget#canInterfaceWorkspace {{ background: {colors.WINDOW}; }} QSplitter::handle {{ background: {colors.BORDER}; }}")
        for widget in (self.sequence_list, self.sequence_table, self.session_panel, self.monitor_panel):
            widget.fn_refresh_theme()
        self.connection_controller.fn_refresh_theme()
