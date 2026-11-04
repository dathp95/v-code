from __future__ import annotations

import re

from PySide6.QtCore import QMimeData, Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QFrame,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)

from core.coding_value_workspace import CodingEcuWorkspace
from gui.themes.styles.controls.menu_style import fn_apply_menu_style
from gui.themes.styles.controls.scrollbar_style import fn_apply_scrollbar_style
from gui.themes.theme_manager import ThemeManager
from gui.widgets.controls.quick_access_button import QuickAccessButton
from gui.widgets.controls.primary_button import PrimaryButton
from gui.widgets.controls.secondary_button import SecondaryButton

from gui.widgets.controls.primary_lineedit import PrimaryLineEdit
from gui.widgets.log_analyzer.reorderable_filter_area import ReorderableFilterArea


class WorkspaceReorderArea(ReorderableFilterArea):
    MIME_TYPE = "application/x-vcode-coding-workspace"

    def fn_mime_data(self, button):
        mime = QMimeData()
        mime.setData(self.MIME_TYPE, button.workspace.id.encode("utf-8"))
        return mime


class EcuWorkspaceItemWidget(QuickAccessButton):

    add_panel_requested = Signal()
    clone_requested = Signal(str)
    workspace_clicked = Signal(str)
    save_requested = Signal(str)
    order_save_requested = Signal()
    delete_requested = Signal(str)
    rename_requested = Signal(str)

    def __init__(self, workspace: CodingEcuWorkspace, sidebar=None, parent=None):
        self.workspace = workspace
        self.sidebar = sidebar
        self._active = False
        self._dirty = False
        super().__init__(workspace.name, height=26, parent=parent, )
        self.setFixedHeight(26)
        self.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Fixed,
        )
        self.setObjectName("ecuWorkspaceItem")
        self.setCursor(Qt.PointingHandCursor)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        super().clicked.connect(
            lambda checked=False: self.workspace_clicked.emit(self.workspace.id)
        )
        self.setToolTip(self.workspace.name)

    def set_active(self, active: bool):
        self._active = active
        self.fn_refresh_theme()

    def set_dirty(self, dirty: bool):
        self._dirty = dirty
        self._refresh_text()

    def set_workspace_name(self, name: str):
        self._refresh_text()
        self.setToolTip(name)

    def workspace_name(self) -> str:
        return self.workspace.name

    def _refresh_text(self):
        suffix = " *" if self._dirty else ""
        self.setText(f"{self.workspace.name}{suffix}")

    def _show_context_menu(self, position):
        menu = self._create_context_menu()
        action = menu.exec(self.mapToGlobal(position))
        self._handle_context_action(action)
        menu.deleteLater()

    def _is_order_dirty(self) -> bool:
        if self.sidebar is not None and hasattr(self.sidebar, "order_is_dirty"):
            return self.sidebar.order_is_dirty()
        parent = self.parent()
        while parent is not None:
            if hasattr(parent, "order_is_dirty"):
                return parent.order_is_dirty()
            parent = parent.parent()
        return False

    def _create_context_menu(self):
        menu = QMenu(self)
        fn_apply_menu_style(menu)
        action_add = menu.addAction("+ Add Panel")
        action_add.setData("add_panel")
        action_clone = menu.addAction("Clone panel")
        action_clone.setData("clone_panel")
        menu.addSeparator()
        action_save = menu.addAction("Save")
        action_save.setData("save")
        is_order_dirty = self._is_order_dirty()
        save_order_text = "Save Order *" if is_order_dirty else "Save Order"
        action_save_order = menu.addAction(save_order_text)
        action_save_order.setData("save_order")
        action_save_order.setEnabled(is_order_dirty)
        menu.addSeparator()
        action_rename = menu.addAction("Rename")
        action_rename.setData("rename")
        action_delete = menu.addAction("Delete")
        action_delete.setData("delete")
        return menu

    def _handle_context_action(self, action):
        if action is None:
            return

        action_id = action.data()
        if action_id == "add_panel":
            self.add_panel_requested.emit()
        elif action_id == "clone_panel":
            self.clone_requested.emit(self.workspace.id)
        elif action_id == "save":
            self.save_requested.emit(self.workspace.id)
        elif action_id == "save_order":
            self.order_save_requested.emit()
        elif action_id == "rename":
            self.rename_requested.emit(self.workspace.id)
        elif action_id == "delete":
            self.delete_requested.emit(self.workspace.id)

    def fn_refresh_theme(self):
        super().fn_refresh_theme()

        if not self._active:
            return

        colors = ThemeManager.fn_colors()

        base_style = self.styleSheet()

        self.setStyleSheet(
            base_style
            + f"""
            QPushButton#ecuWorkspaceItem {{
                background-color: {colors.QUICK_FILTER_SELECTED_BG};
                color: {colors.QUICK_FILTER_SELECTED_TEXT};
                border: 1px solid {colors.QUICK_ACCESS_SELECTED_BORDER};
                font-weight: 600;
            }}
            """
        )
class EcuWorkspaceSidebar(QWidget):

    workspace_added = Signal(object)
    workspace_cloned = Signal(str, object)
    workspace_selected = Signal(str)
    workspace_save_requested = Signal(str)
    workspace_renamed = Signal(str, str)
    workspace_deleted = Signal(str)
    order_save_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._workspaces: list[CodingEcuWorkspace] = []
        self._active_workspace_id: str | None = None
        self._item_by_id: dict[str, EcuWorkspaceItemWidget] = {}
        self._saved_order: list[str] = []
        self._setup_ui()
        self._connect_signals()
        self.fn_refresh_theme()

    def _setup_ui(self):
        self.setObjectName("ecuWorkspaceSidebar")
        self.setFixedWidth(380)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.lbl_title = QLabel("PANEL")
        self.lbl_title.setObjectName("ecuWorkspaceTitle")

        self.edit_search = PrimaryLineEdit(
            placeholder="Search Panel..."
        )


        self.btn_add = SecondaryButton("+ Add Panel", height=42)
        self.btn_save = PrimaryButton("Save Panel", height=42)
        self.btn_save_order = SecondaryButton("Save Order", height=42)
        self.btn_save_order.setEnabled(False)
        self.lbl_order_status = QLabel()
        self.lbl_order_status.hide()
        self._feedback_timer = QTimer(self)
        self._feedback_timer.setSingleShot(True)
        self._feedback_timer.timeout.connect(self.lbl_order_status.hide)

        self.scroll_area = WorkspaceReorderArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setFrameShape(QFrame.NoFrame)

        self.list_container = QWidget()
        self.list_container.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(6, 6, 6, 6)
        self.list_layout.setSpacing(4)
        self.list_layout.addStretch(1)
        self.scroll_area.setWidget(self.list_container)

        self.bottom_action_row = QWidget()

        bottom_action_layout = QHBoxLayout(self.bottom_action_row)

        # Padding của hàng button
        bottom_action_layout.setContentsMargins(4, 4, 4, 4)

        # Khoảng cách giữa các button
        bottom_action_layout.setSpacing(12)

        bottom_action_layout.addWidget(self.btn_add, 1)
        bottom_action_layout.addWidget(self.btn_save, 1)
        bottom_action_layout.addWidget(self.btn_save_order, 1)

        bottom_action_layout.addWidget(self.btn_add, 1)
        bottom_action_layout.addWidget(self.btn_save, 1)
        bottom_action_layout.addWidget(self.btn_save_order, 1)

        layout.addWidget(self.lbl_title)
        layout.addWidget(self.edit_search)

        layout.addWidget(self.scroll_area, 1)
        layout.addWidget(self.bottom_action_row)
        layout.addWidget(self.lbl_order_status)

    def _connect_signals(self):
        self.btn_add.clicked.connect(self._add_workspace_from_dialog)
        self.btn_save.clicked.connect(self._save_active_workspace)
        self.btn_save_order.clicked.connect(self.order_save_requested)
        self.scroll_area.order_changed.connect(self._on_order_changed)

        self.edit_search.textChanged.connect(self._filter_workspaces)

        self.list_container.customContextMenuRequested.connect(
            self._show_empty_context_menu
        )

    def _scroll_to_bottom(self):
        scroll_bar = self.scroll_area.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum())

    def _filter_workspaces(self, text):
        keyword = str(text or "").strip().lower()
        self.scroll_area.fn_set_reorder_enabled(not keyword)

        for workspace_id, item in self._item_by_id.items():
            workspace = self.workspace_by_id(workspace_id)

            if workspace is None:
                continue

            name = workspace.name.lower()

            item.setVisible(
                not keyword or keyword in name
            )

    def workspace_count(self) -> int:
        return len(self._workspaces)

    def workspaces(self) -> list[CodingEcuWorkspace]:
        return list(self._workspaces)

    def workspaces_in_saved_order(self) -> list[CodingEcuWorkspace]:
        """Metadata auto-saves must not commit a pending drag order."""
        return [self._item_by_id[key].workspace for key in self._saved_order]

    def _on_order_changed(self, buttons):
        self._workspaces = [button.workspace for button in buttons]
        self._refresh_order_state()

    def order_is_dirty(self) -> bool:
        return [workspace.id for workspace in self._workspaces] != self._saved_order

    def _refresh_order_state(self):
        dirty = self.order_is_dirty()
        self.btn_save_order.setEnabled(dirty)
        self.btn_save_order.setText("Save Order *" if dirty else "Save Order")
        self._feedback_timer.stop()
        self.lbl_order_status.setText("Order not saved." if dirty else "")
        self.lbl_order_status.setVisible(dirty)

    def mark_order_saved(self):
        self._saved_order = [workspace.id for workspace in self._workspaces]
        self._refresh_order_state()
        self.lbl_order_status.setText("Order saved.")
        self.lbl_order_status.show()
        self._feedback_timer.start(2500)

    def workspace_by_id(self, workspace_id: str) -> CodingEcuWorkspace | None:
        for workspace in self._workspaces:
            if workspace.id == workspace_id:
                return workspace

        return None

    def active_workspace_id(self) -> str | None:
        return self._active_workspace_id

    def active_workspace(self) -> CodingEcuWorkspace | None:
        if self._active_workspace_id is None:
            return None

        return self.workspace_by_id(self._active_workspace_id)

    def add_workspace(
            self,
            workspace: CodingEcuWorkspace,
            select: bool = False,
        ) -> bool:
        if self.workspace_by_id(workspace.id) is not None:
            return False

        self._workspaces.append(workspace)
        self._saved_order.append(workspace.id)
        item = EcuWorkspaceItemWidget(workspace, sidebar=self)

        item.add_panel_requested.connect(self._add_workspace_from_dialog)
        item.clone_requested.connect(self._clone_workspace_from_dialog)
        item.workspace_clicked.connect(self.select_workspace)
        item.save_requested.connect(self.workspace_save_requested)
        item.order_save_requested.connect(self.order_save_requested)
        item.delete_requested.connect(self.remove_workspace)
        item.rename_requested.connect(self._rename_workspace_from_dialog)
        self._item_by_id[workspace.id] = item
        self.list_layout.insertWidget(
            max(0, self.list_layout.count() - 1),
            item,
        )
        self.scroll_area.fn_set_buttons(self._item_widgets())
        self._refresh_order_state()
        self._filter_workspaces(
            self.edit_search.text()
        )
        

        self.fn_refresh_theme()
        if select:
            self.select_workspace(workspace.id)
        self._update_save_button_state()
        return True

    def set_workspace_dirty(self, workspace_id: str, dirty: bool):
        item = self._item_by_id.get(workspace_id)
        if item is not None:
            item.set_dirty(dirty)

    def select_workspace(
            self,
            workspace_id: str,
            emit_signal: bool = True,
        ) -> bool:
        if self.workspace_by_id(workspace_id) is None:
            return False

        self._active_workspace_id = workspace_id
        self._refresh_active_items()
        self._update_save_button_state()
        if emit_signal:
            self.workspace_selected.emit(workspace_id)
        return True

    def rename_workspace(
            self,
            workspace_id: str,
            name: str,
            emit_signal: bool = True,
        ) -> bool:
        workspace = self.workspace_by_id(workspace_id)
        if workspace is None:
            return False

        try:
            workspace.rename(name)
        except ValueError:
            return False

        item = self._item_by_id.get(workspace_id)
        if item is not None:
            item.set_workspace_name(workspace.name)
        if emit_signal:
            self.workspace_renamed.emit(workspace.id, workspace.name)
        return True

    def remove_workspace(
            self,
            workspace_id: str,
            emit_signal: bool = True,
        ) -> bool:
        removed_index = self._workspace_index(workspace_id)
        if removed_index < 0:
            return False

        was_active = self._active_workspace_id == workspace_id
        workspace = self._workspaces.pop(removed_index)
        self._saved_order.remove(workspace.id)
        item = self._item_by_id.pop(workspace.id, None)
        if item is not None:
            self.list_layout.removeWidget(item)
            self.scroll_area.fn_set_buttons(self._item_widgets())
            item.setParent(None)
            item.deleteLater()
        self._refresh_order_state()

        if was_active:
            self._select_fallback_after_delete(removed_index)
        else:
            self._refresh_active_items()

        if emit_signal:
            self.workspace_deleted.emit(workspace.id)
        self._update_save_button_state()
        return True

    def _workspace_index(self, workspace_id: str) -> int:
        for index, workspace in enumerate(self._workspaces):
            if workspace.id == workspace_id:
                return index

        return -1

    def _select_fallback_after_delete(self, removed_index: int):
        if not self._workspaces:
            self._active_workspace_id = None
            self._refresh_active_items()
            self._update_save_button_state()
            return

        fallback_index = min(removed_index, len(self._workspaces) - 1)
        self.select_workspace(self._workspaces[fallback_index].id)

    def _refresh_active_items(self):
        for workspace_id, item in self._item_by_id.items():
            item.set_active(workspace_id == self._active_workspace_id)

    def _item_widgets(self) -> list[EcuWorkspaceItemWidget]:
        return [
            self.list_layout.itemAt(index).widget()
            for index in range(self.list_layout.count())
            if isinstance(
                self.list_layout.itemAt(index).widget(),
                EcuWorkspaceItemWidget,
            )
        ]

    def _add_workspace_from_dialog(self):
        name, accepted = QInputDialog.getText(
            self,
            "Add Panel",
            "Panel name:",
        )
        if not accepted:
            return

        try:
            workspace = CodingEcuWorkspace.create(name)
        except ValueError:
            QMessageBox.warning(
                self,
                "Add Panel",
                "Please enter a panel name.",
            )
            return

        self.add_workspace(workspace, select=False)
        self.workspace_added.emit(workspace)
        self.select_workspace(workspace.id)

        QTimer.singleShot(
            50,
            self._scroll_to_bottom,
        )

    def _show_empty_context_menu(self, position):
        menu = self._create_empty_context_menu()
        action = menu.exec(self.list_container.mapToGlobal(position))
        if action is not None and action.data() == "add_panel":
            self._add_workspace_from_dialog()
        menu.deleteLater()

    def _create_empty_context_menu(self):
        menu = QMenu(self.list_container)
        fn_apply_menu_style(menu)
        action_add = menu.addAction("+ Add Panel")
        action_add.setData("add_panel")
        return menu

    def _generate_clone_name(self, base_name: str) -> str:
        existing_names = {ws.name for ws in self._workspaces}
        match = re.match(r"^(.*?)\s+\(Clone(?:\s+\d+)?\)$", base_name)
        root_name = match.group(1) if match else base_name

        candidate = f"{root_name} (Clone)"
        if candidate not in existing_names:
            return candidate

        index = 2
        while f"{root_name} (Clone {index})" in existing_names:
            index += 1
        return f"{root_name} (Clone {index})"

    def _clone_workspace_from_dialog(self, source_workspace_id: str):
        source_workspace = self.workspace_by_id(source_workspace_id)
        if source_workspace is None:
            return

        suggested_name = self._generate_clone_name(source_workspace.name)
        name, accepted = QInputDialog.getText(
            self,
            "Clone Panel",
            "Panel name:",
            text=suggested_name,
        )
        if not accepted:
            return

        name = str(name or "").strip()
        if not name:
            QMessageBox.warning(
                self,
                "Clone Panel",
                "Please enter a panel name.",
            )
            return

        self.clone_workspace(source_workspace_id, name, select=True)

    def clone_workspace(
            self,
            source_workspace_id: str,
            new_name: str,
            select: bool = True,
        ) -> CodingEcuWorkspace | None:
        source_workspace = self.workspace_by_id(source_workspace_id)
        if source_workspace is None:
            return None

        try:
            cloned_workspace = CodingEcuWorkspace.create(
                new_name,
                coding_file=source_workspace.coding_file,
            )
        except ValueError:
            return None

        if not self.add_workspace(cloned_workspace, select=False):
            return None

        self.workspace_cloned.emit(source_workspace_id, cloned_workspace)
        if select:
            self.select_workspace(cloned_workspace.id)

        QTimer.singleShot(
            50,
            self._scroll_to_bottom,
        )
        return cloned_workspace

    def _save_active_workspace(self):
        active_workspace_id = self.active_workspace_id()
        if active_workspace_id is None:
            return

        self.workspace_save_requested.emit(active_workspace_id)

    def _rename_workspace_from_dialog(self, workspace_id: str):
        workspace = self.workspace_by_id(workspace_id)
        if workspace is None:
            return

        name, accepted = QInputDialog.getText(
            self,
            "Rename Panel",
            "Panel name:",
            text=workspace.name,
        )
        if not accepted:
            return

        if not self.rename_workspace(workspace_id, name):
            QMessageBox.warning(
                self,
                "Rename Panel",
                "Please enter a panel name.",
            )

    def _update_save_button_state(self):
        self.btn_save.setEnabled(self._active_workspace_id is not None)

    def fn_refresh_theme(self):
        colors = ThemeManager.fn_colors()
        self.setStyleSheet(
            f"""
            QWidget#ecuWorkspaceSidebar {{
                background-color: {colors.PANEL};
                border: 1px solid {colors.BORDER};
                border-radius: 6px;
            }}
            QLabel#ecuWorkspaceTitle {{
                color: {colors.TEXT};
                font-weight: 600;
            }}
            QScrollArea {{
                background-color: transparent;
                border: none;
            }}
            """
        )
        self.lbl_title.setStyleSheet(
            f"""
            QLabel {{
                color: {colors.TEXT};
                font-weight: 600;
            }}
            """
        )
        self.btn_add.fn_refresh_theme()
        self.btn_save.fn_refresh_theme()
        self.btn_save_order.fn_refresh_theme()
        self.lbl_order_status.setStyleSheet(f"color: {colors.TEXT};")
        self.scroll_area.fn_refresh_theme()
        self.edit_search.fn_refresh_theme()
        self._update_save_button_state()
        for item in self._item_widgets():
            item.fn_refresh_theme()
        fn_apply_scrollbar_style(self.scroll_area)
