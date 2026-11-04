import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, QSignalBlocker, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core.coding_value_workspace import CodingEcuWorkspace
from core.coding_value import CodingValueOption, CodingValueRow
from core.coding_value_workspace_store import CodingWorkspaceState, CodingWorkspaceStore
from gui.tabs.coding_value_tab import CodingValueTab
from gui.themes.theme import ThemeType
from gui.themes.theme_manager import ThemeManager


class CodingWorkspaceReorderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        directory = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2])
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.store = CodingWorkspaceStore(self.root / "workspaces.json")
        self.workspaces = [CodingEcuWorkspace.create(name) for name in ("A", "B", "C", "D")]
        self.store.save(CodingWorkspaceState(tuple(self.workspaces), self.workspaces[1].id))
        self.tab = self.create_tab()
        self.sidebar = self.tab.workspace_sidebar
        self.tab.resize(1100, 720)
        self.tab.show()
        self.app.processEvents()

    def create_tab(self):
        tab = CodingValueTab(workspace_store=self.store)
        self.addCleanup(tab.deleteLater)
        return tab

    def ids(self, workspaces=None):
        return [w.id for w in (self.sidebar.workspaces() if workspaces is None else workspaces)]

    def drop(self, source_index, target_index, accepted=True):
        area = self.sidebar.scroll_area
        buttons = self.sidebar._item_widgets()
        source, target = buttons[source_index], buttons[target_index]
        area.ensureWidgetVisible(target)
        self.app.processEvents()
        point = target.mapTo(area.viewport(), target.rect().topLeft())
        if buttons.index(target) > buttons.index(source):
            point.setY(point.y() + target.height())

        class Enter(QDragEnterEvent):
            def source(self):
                return source

        class Drop(QDropEvent):
            def source(self):
                return source

        mime = area.fn_mime_data(source)
        enter = Enter(point, Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
        area.dragEnterEvent(enter)
        self.assertEqual(enter.isAccepted(), accepted)
        if accepted:
            self.assertFalse(area._indicator.isHidden())
        event = Drop(QPointF(point), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
        area.dropEvent(event)
        self.assertEqual(event.isAccepted(), accepted)
        self.assertTrue(area._indicator.isHidden())
        self.app.processEvents()

    def test_drag_updates_layout_and_model_preserves_uuid_selection_and_backtrack(self):
        original = self.ids()
        active = self.tab.active_coding_value_panel()
        selected = []
        self.sidebar.workspace_selected.connect(selected.append)
        disk = self.store.config_path.read_bytes()
        self.assertFalse(self.sidebar.btn_save_order.isEnabled())
        self.drop(0, -1)
        self.assertEqual(self.ids(), original[1:] + original[:1])
        self.assertEqual([item.workspace.id for item in self.sidebar._item_widgets()], self.ids())
        self.assertIs(self.tab.active_coding_value_panel(), active)
        self.assertIs(self.tab.workspace_stack.currentWidget(), active)
        self.assertEqual(selected, [])
        self.assertTrue(self.sidebar.btn_save_order.isEnabled())
        self.assertEqual(self.store.config_path.read_bytes(), disk)
        self.drop(-1, 0)
        self.assertEqual(self.ids(), original)
        self.assertFalse(self.sidebar.btn_save_order.isEnabled())

    def test_save_order_restores_after_restart_without_saving_snapshots(self):
        active = self.tab.active_coding_value_panel()
        active.txt_coding_value.setPlainText("unsaved payload")
        before = active.create_workspace_snapshot()
        with patch.object(self.store, "save_snapshot") as save_snapshot:
            self.drop(0, -1)
            self.sidebar.btn_save_order.click()
        save_snapshot.assert_not_called()
        self.assertEqual(active.create_workspace_snapshot(), before)
        self.assertFalse(self.sidebar.btn_save_order.isEnabled())
        self.assertEqual(self.sidebar.lbl_order_status.text(), "Order saved.")
        self.assertTrue(self.sidebar._feedback_timer.isActive())
        restarted = self.create_tab()
        self.assertEqual(self.ids(restarted.workspace_sidebar.workspaces()), self.ids())
        self.assertEqual(restarted.workspace_sidebar.active_workspace_id(), self.workspaces[1].id)
        self.assertEqual(list(self.root.rglob("*.json")), [self.store.config_path])

    def test_metadata_actions_preserve_pending_order_without_committing_it(self):
        original = self.ids()
        self.drop(0, -1)
        self.sidebar.rename_workspace(original[1], "Renamed")
        self.assertEqual(self.ids(self.store.load().workspaces), original)
        self.assertEqual(self.store.load().workspaces[1].name, "Renamed")
        self.sidebar.select_workspace(original[2])
        self.assertEqual(self.ids(self.store.load().workspaces), original)
        with patch("gui.widgets.coding_value.ecu_workspace_sidebar.QInputDialog.getText",
                   return_value=("New", True)):
            self.sidebar.btn_add.click()
        added = self.sidebar.active_workspace_id()
        self.assertEqual(self.ids(self.store.load().workspaces), original + [added])
        self.assertEqual(self.ids(), original[1:] + original[:1] + [added])
        self.sidebar.remove_workspace(original[2])
        self.assertEqual(self.ids(self.store.load().workspaces), [original[0], original[1], original[3], added])
        self.assertEqual(self.ids(), [original[1], original[3], original[0], added])
        self.assertTrue(self.sidebar.btn_save_order.isEnabled())
        self.assertEqual(self.sidebar.lbl_order_status.text(), "Order not saved.")
        self.sidebar.btn_save.click()
        self.assertEqual(self.ids(self.store.load().workspaces), [original[0], original[1], original[3], added])
        self.sidebar.btn_save_order.click()
        self.assertEqual(self.ids(self.store.load().workspaces), self.ids())

    def test_search_rejects_drag_but_save_order_uses_complete_list(self):
        original = self.ids()
        self.sidebar.edit_search.setText("B")
        self.drop(0, 1, accepted=False)
        self.assertEqual(self.ids(), original)
        self.sidebar.edit_search.clear()
        self.drop(0, -1)
        self.sidebar.edit_search.setText("B")
        self.sidebar.btn_save_order.click()
        self.assertEqual(self.ids(self.store.load().workspaces), original[1:] + original[:1])

    def test_save_failure_retains_pending_order_and_original_disk(self):
        original = self.store.config_path.read_bytes()
        self.drop(0, -1)
        with patch.object(self.store, "save", side_effect=OSError("disk full")), patch(
            "gui.tabs.coding_value_tab.QMessageBox.warning"
        ) as warning:
            self.sidebar.btn_save_order.click()
        warning.assert_called_once()
        self.assertEqual(self.store.config_path.read_bytes(), original)
        self.assertTrue(self.sidebar.btn_save_order.isEnabled())

    def test_theme_and_context_actions_preserve_pending_order_and_data(self):
        panel = self.tab.active_coding_value_panel()
        self.tab._save_workspace_snapshot(self.sidebar.active_workspace_id())
        snapshot_path = self.store.snapshot_path(self.sidebar.active_workspace_id())
        saved_snapshot = snapshot_path.read_bytes()
        panel.table.set_rows([CodingValueRow(
            parameter="Byte 14 nibble", byte_pos="14", bit_pos="0", bit_length="4",
            raw_value="", decoded_value="", decoded_options=(CodingValueOption("F", "On"),)
        )])
        with QSignalBlocker(panel.table):
            panel.table.item(0, 4).setText("FF")
        panel.table._row_state[0].update(last_raw="FF", original_raw="FF")
        panel.txt_coding_value.setPlainText("unsaved payload")
        self.drop(0, -1)
        ids = self.ids()
        snapshots = {key: panel.create_workspace_snapshot()
                     for key, panel in self.tab._panel_by_workspace_id.items()}
        disk = self.store.config_path.read_bytes()
        original_theme = ThemeManager.fn_theme()
        try:
            with patch("gui.widgets.coding_value.coding_value_table.QMessageBox.warning") as warning:
                for theme in (ThemeType.DARK, ThemeType.LIGHT, ThemeType.DARK, ThemeType.LIGHT):
                    ThemeManager.fn_set_theme(theme)
                    self.tab.fn_refresh_theme()
                warning.assert_not_called()
        finally:
            ThemeManager.fn_set_theme(original_theme)
        self.assertEqual(self.ids(), ids)
        self.assertEqual(self.store.config_path.read_bytes(), disk)
        self.assertEqual(snapshots, {key: panel.create_workspace_snapshot()
                                   for key, panel in self.tab._panel_by_workspace_id.items()})
        self.assertTrue(self.sidebar.btn_save_order.isEnabled())
        self.sidebar.btn_save_order.click()
        self.assertEqual(panel.table.item(0, 4).text(), "FF")
        self.assertEqual(panel.create_workspace_snapshot(), snapshots[self.sidebar.active_workspace_id()])
        self.assertEqual(snapshot_path.read_bytes(), saved_snapshot)
        item = self.sidebar._item_widgets()[0]
        menu = item._create_context_menu()
        self.assertEqual([a.data() for a in menu.actions()],
                         ["add_panel", "clone_panel", None, "save", "save_order", None, "rename", "delete"])
        menu.deleteLater()
        QTest.mouseClick(item, Qt.LeftButton)
        self.assertEqual(self.sidebar.active_workspace_id(), item.workspace.id)

    def test_native_mouse_drag_suppresses_click_and_next_click_works(self):
        source = self.sidebar._item_widgets()[0]
        selected = []
        self.sidebar.workspace_selected.connect(selected.append)
        with patch("gui.widgets.log_analyzer.reorderable_filter_area.QDrag") as drag:
            drag.return_value.exec.side_effect = lambda *_: self.drop(0, -1)
            QTest.mousePress(source, Qt.LeftButton)
            position = QPointF(source.rect().center() + QPoint(0, 20))
            move = QMouseEvent(QEvent.MouseMove, position, position, Qt.NoButton,
                               Qt.LeftButton, Qt.NoModifier)
            QApplication.sendEvent(source, move)
            QTest.mouseRelease(source, Qt.LeftButton)
            drag.return_value.exec.assert_called_once_with(Qt.MoveAction)
        self.assertEqual(selected, [])
        self.assertEqual(self.ids()[-1], source.workspace.id)
        QTest.mouseClick(source, Qt.LeftButton)
        self.assertEqual(selected, [source.workspace.id])

    def test_delete_active_during_pending_order_keeps_fallback_and_saved_order(self):
        original = self.ids()
        self.drop(0, -1)
        self.sidebar.remove_workspace(original[1])
        self.assertEqual(self.sidebar.active_workspace_id(), original[2])
        self.assertEqual(self.ids(self.store.load().workspaces), [original[0], original[2], original[3]])
        self.assertEqual(self.ids(), [original[2], original[3], original[0]])
        self.assertTrue(self.sidebar.btn_save_order.isEnabled())


if __name__ == "__main__":
    unittest.main()
