from copy import deepcopy

from PySide6.QtCore import Qt, Signal, QTimer

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,    
    QLabel,
    QMenu,
    QMessageBox
)
from gui.controllers.quick_access_controller import QuickAccessController
from gui.dialogs.quick_filter_dialog import QuickFilterDialog
from gui.dialogs.import_quick_filters_dialog import ImportQuickFiltersDialog
from gui.dialogs.export_quick_filters_dialog import ExportQuickFiltersDialog
from gui.widgets.controls.quick_access_button import QuickAccessButton
from gui.widgets.controls.primary_lineedit import PrimaryLineEdit
from gui.widgets.log_analyzer.reorderable_filter_area import ReorderableFilterArea
from gui.utils.payload_format import format_payload_input

from gui.themes.theme_manager import ThemeManager
from gui.themes.styles.controls.menu_style import fn_apply_menu_style

from gui.widgets.controls.secondary_button import SecondaryButton
from gui.widgets.controls.primary_button import (
    PrimaryButton
)

from gui.themes.styles.controls.scrollbar_style import (
    fn_apply_scrollbar_style,
)


class QuickAccessWidget(QWidget):

    quick_filter_selected = Signal(dict)
    quick_filter_cleared = Signal()

    def __init__(self):

        super().__init__()

        self.quick_filters = []
        self.buttons = []
        self.selected_filter = None
        self._saved_order = []
        self._order_dirty = False
        self._buttons_enabled = True


        self.quick_access_controller = QuickAccessController()

        self.setup_ui()

        self.fn_reload()
    
    def setup_ui(self):

        root_layout = QVBoxLayout(self)

        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(8)

        self.edit_search = PrimaryLineEdit(
            placeholder="Search Quick Filter..."
        )

        # root_layout.addWidget(

        #     self.edit_search
        # )

        # --------------------------
        # Quick Filter
        # --------------------------

        self.scroll_area = ReorderableFilterArea()
        self.scroll_area.setWidgetResizable(True)

        self.scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarAsNeeded
        )

        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAsNeeded
        )

        self.scroll_widget = QWidget()

        self.button_layout = QVBoxLayout(
            self.scroll_widget
        )

        self.button_layout.setContentsMargins(
            6,
            6,
            6,
            6,
        )

        self.button_layout.setSpacing(4)

        self.scroll_area.setWidget(
            self.scroll_widget
        )

        fn_apply_scrollbar_style(
            self.scroll_area
        )

        self.scroll_area.setMinimumHeight(360)

        # 1 = Quick Filter chiem toan bo dien tich con lai
        root_layout.addWidget(
            self.scroll_area,
            1,
        )

        # --------------------------
        # Filter Actions
        # --------------------------

        self.btn_add = PrimaryButton(
            "+ Add Filter +"
        )

        self.btn_import = SecondaryButton(
            "Import Filters"
        )

        self.btn_export = SecondaryButton(
            "Export Filters"
        )

        self.btn_save_order = SecondaryButton("Save Order")
        self.btn_save_order.setEnabled(False)
        self.lbl_order_status = QLabel()
        self.lbl_order_status.hide()
        self._feedback_timer = QTimer(self)
        self._feedback_timer.setSingleShot(True)
        self._feedback_timer.timeout.connect(self.lbl_order_status.hide)

        self.action_layout = QHBoxLayout()

        self.action_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        self.action_layout.setSpacing(8)

        self.action_layout.addWidget(
            self.btn_add,
            1,
        )

        self.action_layout.addWidget(
            self.btn_import,
            1,
        )

        self.action_layout.addWidget(
            self.btn_export,
            1,
        )
        self.action_layout.addWidget(self.btn_save_order, 1)

        # Let the existing action row fit the narrow Quick Filter column.
        for button in (self.btn_add, self.btn_import, self.btn_export, self.btn_save_order):
            button.setMinimumWidth(button.sizeHint().width() + 16)

        # Hang button nam co dinh duoi cung
        root_layout.addLayout(
            self.action_layout
        )
        root_layout.addWidget(self.lbl_order_status)

        self._connect_signals()

    def _connect_signals(self):

        self.edit_search.textChanged.connect(
            self._fn_apply_search
        )
        self.btn_add.clicked.connect(
            self.fn_add_filter
        )
        self.btn_import.clicked.connect(self.fn_import_filters)
        self.btn_export.clicked.connect(self.fn_export_filters)
        self.btn_save_order.clicked.connect(self.fn_save_order)
        self.scroll_area.order_changed.connect(self._fn_order_changed)

    def _fn_order_changed(self, buttons):
        self.buttons = buttons
        self.quick_filters = [button._quick_filter_data for button in buttons]
        self._order_dirty = [item.get("id") for item in self.quick_filters] != self._saved_order
        self.btn_save_order.setEnabled(self._order_dirty)
        self._feedback_timer.stop()
        self.lbl_order_status.setText("Order not saved" if self._order_dirty else "")
        self.lbl_order_status.setVisible(self._order_dirty)

    def fn_save_order(self) -> bool:
        try:
            self.quick_access_controller.fn_reorder([
                button._quick_filter_data["id"] for button in self.buttons
            ])
        except (ValueError, OSError, KeyError) as error:
            QMessageBox.warning(self, "Save Order", str(error))
            return False
        self._saved_order = [item["id"] for item in self.quick_filters]
        self._order_dirty = False
        self.btn_save_order.setEnabled(False)
        self.lbl_order_status.setText("Order saved.")
        self.lbl_order_status.show()
        self._feedback_timer.start(3000)
        return True

    def _fn_confirm_pending_order(self) -> bool:
        if not self._order_dirty:
            return True
        choice = QMessageBox.question(
            self, "Unsaved Quick Filter Order",
            "Save the changed Quick Filter order before continuing?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if choice == QMessageBox.Save:
            return self.fn_save_order()
        if choice == QMessageBox.Discard:
            self._order_dirty = False
            self.fn_reload()
            return True
        return False

    def _fn_refresh_button_states(self):
        selected_id = None

        if isinstance(self.selected_filter, dict):
            selected_id = self.selected_filter.get("id")

        for button in self.buttons:
            button.fn_refresh_theme()

            filter_data = getattr(
                button,
                "_quick_filter_data",
                {},
            )

            if filter_data.get("id") != selected_id:
                continue

            colors = ThemeManager.fn_colors()
            base_style = button.styleSheet()

            button.setStyleSheet(
                base_style
                + f"""
                QPushButton:enabled {{
                    background-color: {colors.QUICK_FILTER_SELECTED_BG};
                    color: {colors.QUICK_FILTER_SELECTED_TEXT};
                    border: 1px solid {colors.QUICK_ACCESS_SELECTED_BORDER};
                    font-weight: 600;
                }}

                QPushButton:enabled:hover {{
                    background-color: {colors.QUICK_FILTER_SELECTED_BG};
                }}

                QPushButton:enabled:pressed {{
                    background-color: {colors.QUICK_FILTER_SELECTED_BG};
                }}
                """
            )
            
    def fn_import_filters(self):
        if not self._fn_confirm_pending_order():
            return
        dialog = ImportQuickFiltersDialog(self)
        if not dialog.exec():
            return
        try:
            self.quick_access_controller.fn_add_many(dialog.fn_filters())
        except (ValueError, OSError) as error:
            QMessageBox.warning(self, "Import Quick Access", str(error))
            return
        self.fn_reload()


    def fn_export_filters(self):
        dialog = ExportQuickFiltersDialog(
            self.quick_access_controller.fn_export_filters(),
            self,
        )
        dialog.exec()

    def fn_reload(self):
        """
        Reload all quick filter buttons.
        """
        if not self._fn_confirm_pending_order():
            return

        previous_selected_id = None

        if isinstance(self.selected_filter, dict):
            previous_selected_id = self.selected_filter.get("id")

        self._fn_clear_buttons()

        self._fn_load_filters()
        self._saved_order = [item.get("id") for item in self.quick_filters]
        self._order_dirty = False
        self.btn_save_order.setEnabled(False)
        self.lbl_order_status.hide()

        self._fn_build_buttons()

        self._fn_apply_search(self.edit_search.text())

        if previous_selected_id is not None:
            selected_exists = any(
                item.get("id") == previous_selected_id
                for item in self.quick_filters
                if isinstance(item, dict)
            )

            if not selected_exists:
                self.selected_filter = None
                self.quick_filter_cleared.emit()
    
    
    def _fn_load_filters(self):         

        self.quick_filters = self.quick_access_controller.fn_load()
    
    
    def fn_create_from_transaction(
            self,
            row_data: dict,
        ):
        """Create a quick filter draft from a result table transaction."""
        if not self._fn_confirm_pending_order():
            return

        if not isinstance(row_data, dict):
            row_data = {}

        quick_filter = {
            "name": "",
            "filters": {
                "ecu": self._fn_text_value(row_data.get("ECU", "")),
                "request": self._fn_text_value(row_data.get("Request", "")),
                "response": self._fn_text_value(row_data.get("Response", "")),
            },
        }

        dialog = QuickFilterDialog(
            quick_filter=quick_filter,
            parent=self,
        )

        if not dialog.exec():
            return

        self.quick_access_controller.fn_add(
            dialog.fn_get_data()
        )

        self.fn_reload()
    def fn_add_filter(self):
        """
        Show Add Quick Filter dialog.
        """
        if not self._fn_confirm_pending_order():
            return

        dialog = QuickFilterDialog(
            quick_filter=None,
            parent=self
        )

        if dialog.exec():

            quick_filter = dialog.fn_get_data()

            self.quick_access_controller.fn_add(
                quick_filter
            )

            self.fn_reload()
    
    
    def _fn_build_buttons(self):
        """
        Create quick filter buttons.
        """

        for item in self.quick_filters:

            button = QuickAccessButton(

                text=item["name"],

                height=24

            )

            button._quick_filter_data = item
            button.fn_enable(self._buttons_enabled)
            self.buttons.append(button)


            button.setContextMenuPolicy(
                Qt.CustomContextMenu
            )

            button.clicked.connect(

                lambda checked=False, data=item:

                self._fn_button_clicked(data)

            )
            button.customContextMenuRequested.connect(

                lambda pos, data=item, btn=button:

                self._fn_show_context_menu(
                    btn,
                    pos,
                    data
                )

            )

            self.button_layout.addWidget(
                button
            )
        self.button_layout.addStretch(2)
        self.scroll_area.fn_set_buttons(self.buttons)
        self._fn_refresh_button_states()

    
    def _fn_clear_buttons(self):
        """
        Remove all quick filter buttons.
        """
        self.scroll_area.fn_set_buttons([])
        self.buttons.clear()


        while self.button_layout.count():

            item = self.button_layout.takeAt(0)

            widget = item.widget()

            if widget is not None:

                widget.deleteLater()

            del item

    def _fn_apply_search(
            self,
            text: str,
        ):
        keyword = self._fn_search_text(text)
        self.scroll_area.fn_set_reorder_enabled(not text.strip())

        for button in self.buttons:
            filter_data = getattr(button, "_quick_filter_data", {})
            button.setVisible(
                not keyword
                or keyword in self._fn_filter_search_blob(filter_data)
            )

    def _fn_filter_search_blob(
            self,
            filter_data: dict,
        ) -> str:
        if not isinstance(filter_data, dict):
            return ""

        filters = filter_data.get("filters", {})

        if not isinstance(filters, dict):
            filters = {}

        values = [
            filter_data.get("name", ""),
            filters.get("ecu", ""),
            filters.get("request", ""),
            filters.get("response", ""),
        ]

        return " ".join(
            self._fn_search_text(str(value))
            for value in values
            if value is not None
        )

    @staticmethod
    def _fn_search_text(
            value: str,
        ) -> str:
        value = format_payload_input(value.strip())
        return " ".join(value.split()).lower()
    
    
    @staticmethod
    def _fn_text_value(value) -> str:
        if value is None:
            return ""

        return str(value)
    
    
    def _fn_button_clicked(
            self,
            filter_data: dict,
        ):

        self.selected_filter = filter_data

        self._fn_refresh_button_states()

        self.quick_filter_selected.emit(
            filter_data
        )
        
    def _fn_show_context_menu(
            self,
            button,
            pos,
            quick_filter,
        ):
        """
        Show context menu.
        """

        menu = QMenu(self)

        fn_apply_menu_style(menu)

        action_edit = menu.addAction(
            "Edit"
        )
        

        action_clone = menu.addAction("Clone")
        action_delete = menu.addAction("Delete")

        action = menu.exec(button.mapToGlobal(pos))

        if action == action_edit:
            self._fn_edit_filter(quick_filter)
        elif action == action_clone:
            self._fn_clone_filter(quick_filter)
        elif action == action_delete:
            self._fn_delete_filter(quick_filter)

        menu.deleteLater()

    def fn_clone_selected(self):
        if self.selected_filter is None:
            return
        if not self._fn_confirm_pending_order():
            return

        existing_names = {
            item.get("name", "")
            for item in self.quick_access_controller.fn_load()
        }
        base_name = f"{self.selected_filter.get('name', 'Quick Filter')} (Copy)"
        name = base_name
        suffix = 2
        while name in existing_names:
            name = f"{base_name} {suffix}"
            suffix += 1

        cloned = deepcopy(self.selected_filter)
        cloned["name"] = name
        self.quick_access_controller.fn_insert_after(
            self.selected_filter["id"],
            cloned,
        )
        self.fn_reload()
    
    
    def _fn_delete_filter(
            self,
            quick_filter: dict,
        ):
        """
        Delete a quick filter immediately.
        """
        if not self._fn_confirm_pending_order():
            return

        self.quick_access_controller.fn_delete(
            quick_filter["id"]
        )

        self.fn_reload()

    def _fn_clone_filter(self, quick_filter: dict):
        """Create an independent copy of a quick filter."""
        if not self._fn_confirm_pending_order():
            return

        existing_names = {
            item.get("name", "")
            for item in self.quick_access_controller.fn_load()
        }
        base_name = f"{quick_filter.get('name', 'Quick Filter')} (Copy)"
        name = base_name
        suffix = 2
        while name in existing_names:
            name = f"{base_name} {suffix}"
            suffix += 1

        cloned = deepcopy(quick_filter)
        cloned.pop("id", None)
        cloned.pop("enabled", None)
        cloned["name"] = name

        self.quick_access_controller.fn_add(cloned)
        self.fn_reload()

    def _fn_edit_filter(
            self,
            quick_filter: dict,
        ):
        """
        Edit one quick filter.
        """
        if not self._fn_confirm_pending_order():
            return

        dialog = QuickFilterDialog(

            quick_filter=quick_filter,

            parent=self

        )

        if not dialog.exec():

            return

        updated_filter = dialog.fn_get_data()

        self.quick_access_controller.fn_update(
        updated_filter
        )

        self.fn_reload()

    def fn_set_enabled(self):

        self.fn_enable_buttons(True)

    def fn_set_disabled(self):

        self.fn_enable_buttons(False)

    def fn_clear_active_selection(self) -> None:
        self.selected_filter = None
        self._fn_refresh_button_states()
    
    def fn_enable_buttons(
            self,
            enabled: bool
        ):
        """
        Enable or disable all quick access buttons.
        """
        self._buttons_enabled = enabled

        for button in self.buttons:

            button.fn_enable(enabled)
    
    def fn_refresh_theme(self):

        self.edit_search.fn_refresh_theme()
        fn_apply_scrollbar_style(self.scroll_area)
        self.btn_add.fn_refresh_theme()
        self.btn_import.fn_refresh_theme()
        self.btn_export.fn_refresh_theme()
        self.btn_save_order.fn_refresh_theme()
        for button in (self.btn_add, self.btn_import, self.btn_export, self.btn_save_order):
            button.setMinimumWidth(button.sizeHint().width() + 16)
        self.scroll_area.fn_refresh_theme()
        self.lbl_order_status.setStyleSheet(f"color: {ThemeManager.fn_colors().TEXT};")

        self._fn_refresh_button_states()



