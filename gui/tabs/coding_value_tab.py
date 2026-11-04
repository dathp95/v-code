from dataclasses import replace

from PySide6.QtWidgets import (
    QHBoxLayout,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.coding_value_workspace import CodingEcuWorkspace
from core.coding_value_workspace_store import (
    CodingWorkspaceState,
    CodingWorkspaceStore,
)
from gui.widgets.coding_value.coding_value_panel import CodingValuePanel
from gui.widgets.coding_value.ecu_workspace_sidebar import EcuWorkspaceSidebar


class CodingValueTab(QWidget):

    def __init__(self, workspace_store: CodingWorkspaceStore | None = None):
        super().__init__()

        self._workspace_store = workspace_store or CodingWorkspaceStore()
        self._panel_by_workspace_id: dict[str, CodingValuePanel] = {}
        self._restoring_workspaces = False
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(
            12,
            12,
            12,
            12,
        )
        main_layout.setSpacing(12)

        self.workspace_sidebar = EcuWorkspaceSidebar()
        self.workspace_stack = QStackedWidget()
        self.workspace_sidebar.workspace_added.connect(self._add_workspace_panel)
        self.workspace_sidebar.workspace_cloned.connect(self._clone_workspace_panel)
        self.workspace_sidebar.workspace_selected.connect(self._select_workspace_panel)
        self.workspace_sidebar.workspace_save_requested.connect(
            self._save_workspace_snapshot
        )
        self.workspace_sidebar.workspace_deleted.connect(self._remove_workspace_panel)
        self.workspace_sidebar.order_save_requested.connect(self._save_workspace_order)
        self.workspace_sidebar.workspace_renamed.connect(
            lambda _workspace_id, _name: self._save_workspace_state()
        )

        self.workspace_row = QWidget()
        workspace_layout = QHBoxLayout(self.workspace_row)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(12)
        workspace_layout.addWidget(self.workspace_sidebar, 0)
        workspace_layout.addWidget(self.workspace_stack, 1)

        main_layout.addWidget(
            self.workspace_row,
            1,
        )

        self._restore_workspace_state()

    @property
    def coding_value_panel(self) -> CodingValuePanel | None:
        return self.active_coding_value_panel()

    def active_coding_value_panel(self) -> CodingValuePanel | None:
        workspace_id = self.workspace_sidebar.active_workspace_id()
        if workspace_id is None:
            return None

        return self._panel_by_workspace_id.get(workspace_id)

    def _add_workspace_panel(self, workspace: CodingEcuWorkspace):
        if workspace.id in self._panel_by_workspace_id:
            return

        panel = CodingValuePanel()
        panel.coding_file_changed.connect(
            lambda coding_file, workspace_id=workspace.id:
                self._on_workspace_coding_file_changed(workspace_id, coding_file)
        )
        panel.state_changed.connect(
            lambda workspace_id=workspace.id:
                self._on_panel_state_changed(workspace_id)
        )
        self._panel_by_workspace_id[workspace.id] = panel
        self.workspace_stack.addWidget(panel)
        if (
                not self._restore_saved_workspace_snapshot(workspace.id)
                and workspace.coding_file
            ):
            panel.load_coding_definition_file(
                self._workspace_store.path_for_use(workspace.coding_file),
                emit_coding_file_changed=False,
            )
        self._save_workspace_state()

    def _clone_workspace_panel(
            self,
            source_workspace_id: str,
            cloned_workspace: CodingEcuWorkspace,
        ):
        if cloned_workspace.id in self._panel_by_workspace_id:
            return

        source_panel = self._panel_by_workspace_id.get(source_workspace_id)
        snapshot = None
        if source_panel is not None:
            snapshot = source_panel.create_workspace_snapshot()
        else:
            snapshot = self._workspace_store.load_snapshot(source_workspace_id)

        panel = CodingValuePanel()
        panel.coding_file_changed.connect(
            lambda coding_file, workspace_id=cloned_workspace.id:
                self._on_workspace_coding_file_changed(workspace_id, coding_file)
        )
        panel.state_changed.connect(
            lambda workspace_id=cloned_workspace.id:
                self._on_panel_state_changed(workspace_id)
        )
        self._panel_by_workspace_id[cloned_workspace.id] = panel
        self.workspace_stack.addWidget(panel)

        if source_panel is not None and getattr(source_panel, "_coding_definition", None) is not None:
            panel._set_coding_definition(source_panel._coding_definition)

        if snapshot is not None:
            panel.restore_workspace_snapshot(
                replace(
                    snapshot,
                    coding_file=self._workspace_store.path_for_use(
                        snapshot.coding_file
                    ),
                )
            )
            cloned_workspace.set_coding_file(snapshot.coding_file)
            try:
                self._workspace_store.save_snapshot(cloned_workspace.id, snapshot)
                self.workspace_sidebar.set_workspace_dirty(cloned_workspace.id, False)
            except OSError:
                self.workspace_sidebar.set_workspace_dirty(cloned_workspace.id, True)
        elif cloned_workspace.coding_file:
            panel.load_coding_definition_file(
                self._workspace_store.path_for_use(cloned_workspace.coding_file),
                emit_coding_file_changed=False,
            )

        self._save_workspace_state()

    def _remove_workspace_panel(self, workspace_id: str):
        panel = self._panel_by_workspace_id.pop(workspace_id, None)
        if panel is not None:
            self.workspace_stack.removeWidget(panel)
            panel.deleteLater()

        active_panel = self.active_coding_value_panel()
        if active_panel is not None:
            self.workspace_stack.setCurrentWidget(active_panel)
        self._workspace_store.delete_snapshot(workspace_id)
        self._save_workspace_state()

    def _select_workspace_panel(self, workspace_id: str):
        panel = self._panel_by_workspace_id.get(workspace_id)
        if panel is None:
            return

        if (
                self.workspace_sidebar.active_workspace_id() == workspace_id
                and self.workspace_stack.currentWidget() is panel
            ):
            return

        self.workspace_stack.setCurrentWidget(panel)
        if hasattr(panel, "table") and getattr(panel.table, "_needs_theme_refresh", False):
            panel.table._needs_theme_refresh = False
            panel.table._apply_row_themes()
        if not self._restoring_workspaces:
            try:
                self._restore_saved_workspace_snapshot(workspace_id)
            except Exception:
                pass
        self._save_workspace_state()

    def _restore_workspace_state(self):
        self._restoring_workspaces = True
        try:
            state = self._workspace_store.load()
            if state is None:
                state = CodingWorkspaceState(
                    workspaces=(CodingEcuWorkspace.create("Panel default"),),
                    active_workspace_id=None,
                )

            for workspace in state.workspaces:
                if not self.workspace_sidebar.add_workspace(workspace, select=False):
                    continue
                self._add_workspace_panel(workspace)

            active_workspace_id = (
                state.active_workspace_id
                if self.workspace_sidebar.workspace_by_id(state.active_workspace_id)
                else None
            )
            if active_workspace_id is None and state.workspaces:
                active_workspace_id = state.workspaces[0].id

            if active_workspace_id is not None:
                self.workspace_sidebar.select_workspace(
                    active_workspace_id,
                    emit_signal=False,
                )
                self._select_workspace_panel(active_workspace_id)
        finally:
            self._restoring_workspaces = False

    def _save_workspace_state(self, *, save_order: bool = False):
        if self._restoring_workspaces:
            return

        self._workspace_store.save(
            CodingWorkspaceState(
                workspaces=tuple(
                    self.workspace_sidebar.workspaces() if save_order
                    else self.workspace_sidebar.workspaces_in_saved_order()
                ),
                active_workspace_id=self.workspace_sidebar.active_workspace_id(),
            )
        )

    def _save_workspace_order(self):
        try:
            self._save_workspace_state(save_order=True)
        except OSError as exc:
            QMessageBox.warning(self, "Save Order", f"Cannot save Panel order:\n{exc}")
            return
        self.workspace_sidebar.mark_order_saved()

    def _on_workspace_coding_file_changed(
            self,
            workspace_id: str,
            coding_file: str,
        ):
        workspace = self.workspace_sidebar.workspace_by_id(workspace_id)
        if workspace is None:
            return

        workspace.set_coding_file(coding_file)
        self._save_workspace_state()

    def _on_panel_state_changed(self, workspace_id: str):
        if self._restoring_workspaces:
            return

        self.workspace_sidebar.set_workspace_dirty(workspace_id, True)

    def _restore_saved_workspace_snapshot(self, workspace_id: str) -> bool:
        panel = self._panel_by_workspace_id.get(workspace_id)
        workspace = self.workspace_sidebar.workspace_by_id(workspace_id)
        if panel is None or workspace is None:
            return False

        snapshot = self._workspace_store.load_snapshot(workspace_id)
        if snapshot is None:
            return False

        panel.restore_workspace_snapshot(
            replace(
                snapshot,
                coding_file=self._workspace_store.path_for_use(
                    snapshot.coding_file
                ),
            )
        )
        workspace.set_coding_file(snapshot.coding_file)
        self.workspace_sidebar.set_workspace_dirty(workspace_id, False)
        return True

    def _save_workspace_snapshot(self, workspace_id: str):
        panel = self._panel_by_workspace_id.get(workspace_id)
        workspace = self.workspace_sidebar.workspace_by_id(workspace_id)
        if panel is None or workspace is None:
            return

        snapshot = panel.create_workspace_snapshot()
        try:
            self._workspace_store.save_snapshot(workspace_id, snapshot)
        except OSError as exc:
            QMessageBox.warning(
                self,
                "Save Panel",
                f"Cannot save Panel state:\n{exc}",
            )
            return

        workspace.set_coding_file(snapshot.coding_file)
        self.workspace_sidebar.set_workspace_dirty(workspace_id, False)
        self._save_workspace_state()

    def fn_set_crc_value(self, crc_value):
        panel = self.active_coding_value_panel()
        if panel is None:
            return False

        return panel.fn_set_crc_value(crc_value)

    def fn_refresh_theme(self):
        self.workspace_sidebar.fn_refresh_theme()
        for panel in self._panel_by_workspace_id.values():
            panel.fn_refresh_theme()
