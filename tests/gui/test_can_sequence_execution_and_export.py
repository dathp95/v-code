from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

from openpyxl import load_workbook
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

from core.diagnostic_sequence import DiagnosticStep, DiagnosticTestCase
from core.services.can_diagnostic_report_service import (
    CanDiagnosticReportService,
    CanDiagnosticReportSheet,
    CanDiagnosticReportStep,
    CAN_DIAGNOSTIC_REPORT_HEADERS,
)
from gui.widgets.can_interface.diagnostic_table_panel import CanDiagnosticTablePanel


app = QApplication.instance()
if app is None:
    app = QApplication([])


def _create_sample_test_case(name="Test Sequence 1"):
    steps = [
        DiagnosticStep(
            step=1,
            sequence_name="Diagnostic Session Control",
            ecu="BCM",
            request="10 03",
            delay_ms=50,
            repeat=1,
            expected_response="50 03",
            comment="Enter Extended Session",
        ),
        DiagnosticStep(
            step=2,
            sequence_name="Security Access Seed",
            ecu="BCM",
            request="27 01",
            delay_ms=50,
            repeat=1,
            expected_response="67 01",
            comment="Request Seed",
        ),
        DiagnosticStep(
            step=3,
            sequence_name="Read Data By Identifier",
            ecu="BCM",
            request="22 F1 90",
            delay_ms=50,
            repeat=1,
            expected_response="62 F1 90",
            comment="Read VIN",
        ),
    ]
    return DiagnosticTestCase(
        schema_version=1,
        name=name,
        description="Sample sequence for unit test",
        enabled=True,
        steps=steps,
    )


class TestCanToolbarLayoutAndProperties(unittest.TestCase):
    def setUp(self):
        self.vehicle_service = MagicMock()
        self.vehicle_service.list_vehicles.return_value = ["VF5NP", "LIMO"]
        mock_vehicle = MagicMock()
        mock_vehicle.name = "VF5NP"
        mock_bcm = MagicMock()
        mock_bcm.name = "BCM"
        mock_vcu = MagicMock()
        mock_vcu.name = "VCU"
        mock_vehicle.ecus = [mock_bcm, mock_vcu]
        self.vehicle_service.get_vehicle.return_value = mock_vehicle

        self.panel = CanDiagnosticTablePanel(vehicle_service=self.vehicle_service)
        self.panel.fn_set_vehicle(mock_vehicle)

    def tearDown(self):
        self.panel.stop_sequence()
        self.panel.deleteLater()

    def test_toolbar_button_widths_and_texts(self):
        # RUN, EXPORT, STOP buttons must have width 200px
        self.assertEqual(self.panel.btn_run.maximumWidth(), 200)
        self.assertEqual(self.panel.btn_run.minimumWidth(), 200)
        self.assertEqual(self.panel.btn_export.maximumWidth(), 200)
        self.assertEqual(self.panel.btn_export.minimumWidth(), 200)
        self.assertEqual(self.panel.btn_stop.maximumWidth(), 200)
        self.assertEqual(self.panel.btn_stop.minimumWidth(), 200)

        # Texts
        self.assertEqual(self.panel.btn_run.text(), "RUN")
        self.assertEqual(self.panel.btn_export.text(), "EXPORT")
        self.assertEqual(self.panel.btn_stop.text(), "STOP")
        self.assertEqual(self.panel.btn_add.text(), "+Add Row")
        self.assertEqual(self.panel.btn_delete.text(), "Delete")
        self.assertEqual(self.panel.btn_settings.text(), "Setting")

        # Sequence title should be hidden (removed from toolbar)
        self.assertTrue(self.panel.title.isHidden())

        # STOP and EXPORT should be visible, load should be hidden
        self.assertFalse(self.panel.btn_export.isHidden())
        self.assertFalse(self.panel.btn_stop.isHidden())
        self.assertTrue(self.panel.btn_load.isHidden())

    def test_toolbar_widget_ordering(self):
        # Find toolbar layout
        main_layout = self.panel.layout()
        toolbar = main_layout.itemAt(0).layout()
        self.assertIsNotNone(toolbar)

        widgets = []
        for i in range(toolbar.count()):
            item = toolbar.itemAt(i)
            if item.widget():
                widgets.append(item.widget())

        # Expected order: Vehicle | +Add Row | Delete | RUN | EXPORT | STOP | Setting
        expected_widgets = [
            self.panel.vehicle_selector,
            self.panel.btn_add,
            self.panel.btn_delete,
            self.panel.btn_run,
            self.panel.btn_export,
            self.panel.btn_stop,
            self.panel.btn_settings,
        ]
        self.assertEqual(widgets, expected_widgets)


class TestCanSequentialRunner(unittest.TestCase):
    def setUp(self):
        self.vehicle_service = MagicMock()
        self.vehicle_service.list_vehicles.return_value = ["VF5NP"]
        mock_vehicle = MagicMock()
        mock_vehicle.name = "VF5NP"
        mock_bcm = MagicMock()
        mock_bcm.name = "BCM"
        mock_vehicle.ecus = [mock_bcm]
        self.vehicle_service.get_vehicle.return_value = mock_vehicle

        self.panel = CanDiagnosticTablePanel(vehicle_service=self.vehicle_service)
        self.panel.fn_set_vehicle(mock_vehicle)
        self.test_case = _create_sample_test_case()
        self.panel.fn_load_sequence(self.test_case)

    def tearDown(self):
        self.panel.stop_sequence()
        self.panel.deleteLater()

    def test_run_sequence_step_by_step_to_completion(self):
        emitted_keys = []
        self.panel.row_send_requested.connect(emitted_keys.append)

        # 1. Click RUN
        self.panel.run_sequence()

        self.assertTrue(self.panel._is_sequence_running)
        self.assertFalse(self.panel.btn_run.isEnabled())
        self.assertTrue(self.panel.btn_stop.isEnabled())

        # Row 0 sent
        self.assertEqual(len(emitted_keys), 1)
        step0_key = self.panel.step_ids[0]
        self.assertEqual(emitted_keys[0], step0_key)

        # 2. Simulate step 0 completion with Passed
        self.panel.set_step_result(step0_key, "50 03", "Passed", "OK")

        # Delay timer fired manually
        self.panel._sequence_run_timer.timeout.emit()

        # Row 1 sent
        self.assertEqual(len(emitted_keys), 2)
        step1_key = self.panel.step_ids[1]
        self.assertEqual(emitted_keys[1], step1_key)

        # 3. Simulate step 1 completion with Passed
        self.panel.set_step_result(step1_key, "67 01 01 02 03 04", "Passed", "Seed received")
        self.panel._sequence_run_timer.timeout.emit()

        # Row 2 sent
        self.assertEqual(len(emitted_keys), 3)
        step2_key = self.panel.step_ids[2]
        self.assertEqual(emitted_keys[2], step2_key)

        # 4. Simulate step 2 completion with Passed
        self.panel.set_step_result(step2_key, "62 F1 90", "Passed", "VIN read")

        # Sequence should complete and stop automatically
        self.assertFalse(self.panel._is_sequence_running)
        self.assertTrue(self.panel.btn_run.isEnabled())
        self.assertFalse(self.panel.btn_stop.isEnabled())
        self.assertIn("completed", self.panel.notice.text().lower())

    def test_stop_sequence_mid_run(self):
        stop_signals = []
        self.panel.sequence_stop_requested.connect(lambda: stop_signals.append(True))

        self.panel.run_sequence()
        self.assertTrue(self.panel._is_sequence_running)

        # Click STOP
        self.panel.stop_sequence("User stopped")

        self.assertFalse(self.panel._is_sequence_running)
        self.assertTrue(self.panel.btn_run.isEnabled())
        self.assertFalse(self.panel.btn_stop.isEnabled())
        self.assertEqual(len(stop_signals), 1)
        self.assertIn("User stopped", self.panel.notice.text())


class TestCanDiagnosticExcelExport(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.service = CanDiagnosticReportService(report_root=self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_default_report_path_structure(self):
        path = self.service.default_report_path()
        today = datetime.now().strftime("%d-%m-%Y")
        self.assertEqual(path.parent.name, today)
        self.assertTrue(path.name.startswith("EEIV_report_Diagnostic_"))
        self.assertTrue(path.name.endswith(".xlsx"))

    def test_export_report_multi_sheet(self):
        sheet1_steps = [
            CanDiagnosticReportStep(
                step="1",
                sequence_name="Diag Session",
                ecu="BCM",
                payload="10 03",
                delay_ms="100",
                repeat="1",
                expected_response="50 03",
                receive_message="50 03",
                results="Passed",
                comment="OK",
            ),
            CanDiagnosticReportStep(
                step="2",
                sequence_name="Security Seed",
                ecu="BCM",
                payload="27 01",
                delay_ms="100",
                repeat="1",
                expected_response="67 01",
                receive_message="",
                results="Timeout",
                comment="Failed to respond",
            ),
        ]
        sheet2_steps = [
            CanDiagnosticReportStep(
                step="1",
                sequence_name="Read VIN",
                ecu="VCU",
                payload="22 F1 90",
                delay_ms="50",
                repeat="1",
                expected_response="62 F1 90",
                receive_message="62 F1 90 56 46",
                results="Passed",
                comment="VIN match",
            )
        ]

        sheets = [
            CanDiagnosticReportSheet(title="BCM Diag", rows=sheet1_steps),
            CanDiagnosticReportSheet(title="VCU Diag", rows=sheet2_steps),
        ]

        out_file = Path(self.temp_dir) / "test_export.xlsx"
        result_path = self.service.export_report(sheets, out_file)

        self.assertTrue(result_path.is_file())

        wb = load_workbook(result_path)
        self.assertEqual(wb.sheetnames, ["BCM Diag", "VCU Diag"])

        # Check sheet 1
        ws1 = wb["BCM Diag"]
        self.assertEqual(ws1["A1"].value, "Generated by V-CODE EEIV Diagnostic")
        headers = [cell.value for cell in ws1[2]]
        self.assertEqual(headers, list(CAN_DIAGNOSTIC_REPORT_HEADERS))
        self.assertEqual(ws1.cell(row=3, column=1).value, "1")
        self.assertEqual(ws1.cell(row=3, column=4).value, "10 03")
        self.assertEqual(ws1.cell(row=3, column=9).value, "Passed")

        # Row 4 has "Timeout" -> check cell value
        self.assertEqual(ws1.cell(row=4, column=9).value, "Timeout")

        # Check sheet 2
        ws2 = wb["VCU Diag"]
        self.assertEqual(ws2["A1"].value, "Generated by V-CODE EEIV Diagnostic")
        self.assertEqual(ws2.cell(row=3, column=3).value, "VCU")
        self.assertEqual(ws2.cell(row=3, column=9).value, "Passed")

    @unittest.mock.patch("gui.widgets.can_interface.diagnostic_table_panel.QMessageBox.information")
    def test_panel_export_diagnostic_report(self, mock_info):
        panel = CanDiagnosticTablePanel()
        case = _create_sample_test_case("Sample Diag")
        panel.fn_load_sequence(case)

        # Set some runtime results on panel
        step0_key = panel.step_ids[0]
        panel.set_step_result(step0_key, "50 03", "Passed", "Extended OK")

        out_file = Path(self.temp_dir) / "panel_export.xlsx"
        panel.export_diagnostic_report(out_file)

        self.assertTrue(out_file.is_file())
        wb = load_workbook(out_file)
        self.assertEqual(wb.sheetnames, ["Sample Diag"])
        ws = wb["Sample Diag"]
        self.assertEqual(ws.cell(row=3, column=8).value, "50 03")
        self.assertEqual(ws.cell(row=3, column=9).value, "Passed")
        panel.deleteLater()

    @unittest.mock.patch("gui.widgets.can_interface.diagnostic_table_panel.QMessageBox.information")
    def test_can_interface_tab_export_integration(self, mock_info):
        from gui.tabs.can_interface_tab import CANInterfaceTab

        vehicle_service = MagicMock()
        vehicle_service.list_vehicles.return_value = ["VF5NP"]
        mock_vehicle = MagicMock()
        mock_vehicle.name = "VF5NP"
        mock_bcm = MagicMock()
        mock_bcm.name = "BCM"
        mock_vehicle.ecus = [mock_bcm]
        vehicle_service.get_vehicle.return_value = mock_vehicle

        tab = CANInterfaceTab(vehicle_service=vehicle_service)

        case1 = _create_sample_test_case("Seq1")
        case2 = _create_sample_test_case("Seq2")

        # Mock workspace controller and sidebar checked_ids
        tab.sequence_list.checked_ids = MagicMock(return_value=["/path/to/seq1.json", "/path/to/seq2.json"])
        tab.workspace_controller._case_for_source = MagicMock(side_effect=lambda p: case1 if "seq1" in p else case2)
        tab.sequence_table.fn_load_sequence(case1)

        out_file = Path(self.temp_dir) / "multi_export.xlsx"
        tab.sequence_table.export_diagnostic_report(out_file)

        self.assertTrue(out_file.is_file())
        wb = load_workbook(out_file)
        self.assertEqual(wb.sheetnames, ["Seq1", "Seq2"])
        tab.deleteLater()


if __name__ == "__main__":
    unittest.main()
