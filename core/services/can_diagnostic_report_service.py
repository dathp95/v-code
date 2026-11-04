from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Sequence

from openpyxl import Workbook
from openpyxl.utils import get_column_letter

from config.paths import CAN_INTERFACE_REPORT_DIR
from core.excel_styles import (
    HEADER_ALIGNMENT,
    HEADER_FILL,
    HEADER_FONT,
    THIN_BORDER,
    WARNING_FILL,
)


CAN_DIAGNOSTIC_REPORT_HEADERS: tuple[str, ...] = (
    "Step",
    "Test sequence name",
    "ECU",
    "Payload (HEX)",
    "Delay (ms)",
    "Repeat",
    "Expected Response (HEX)",
    "Receive Message (HEX)",
    "Results",
    "Comment",
)


@dataclass(frozen=True)
class CanDiagnosticReportStep:
    step: str
    sequence_name: str
    ecu: str
    payload: str
    delay_ms: str
    repeat: str
    expected_response: str
    receive_message: str
    results: str
    comment: str

    def values_for_headers(self, headers: Sequence[str]) -> list[str]:
        mapping = {
            "Step": self.step,
            "Test sequence name": self.sequence_name,
            "ECU": self.ecu,
            "Payload (HEX)": self.payload,
            "Delay (ms)": self.delay_ms,
            "Repeat": self.repeat,
            "Expected Response (HEX)": self.expected_response,
            "Receive Message (HEX)": self.receive_message,
            "Results": self.results,
            "Comment": self.comment,
        }
        return [mapping.get(header, "") for header in headers]


@dataclass(frozen=True)
class CanDiagnosticReportSheet:
    title: str
    rows: Sequence[CanDiagnosticReportStep]


def safe_excel_sheet_name(name: str) -> str:
    safe_name = str(name or "")
    invalid_chars = r'[]:*?/\\'
    for char in invalid_chars:
        safe_name = safe_name.replace(char, "_")
    return safe_name[:31].strip() or "Sequence"


def _format_diagnostic_export_sheet(sheet) -> None:
    # Row 2: Headers
    for cell in sheet[2]:
        cell.font = HEADER_FONT
        cell.alignment = HEADER_ALIGNMENT
        cell.fill = HEADER_FILL
        cell.border = THIN_BORDER

    # Column index of Results (1-based)
    results_col_idx = None
    for idx, cell in enumerate(sheet[2], start=1):
        if cell.value == "Results":
            results_col_idx = idx
            break

    # Row 3+: Data
    for row in sheet.iter_rows(
        min_row=3,
        max_row=sheet.max_row,
        min_col=1,
        max_col=sheet.max_column,
    ):
        is_warning = False
        if results_col_idx is not None and results_col_idx <= len(row):
            res_val = str(row[results_col_idx - 1].value or "").strip().lower()
            if res_val in ("failed", "mismatch", "timeout", "error", "no-m"):
                is_warning = True

        for cell in row:
            cell.border = THIN_BORDER
            if is_warning:
                cell.fill = WARNING_FILL

    sheet.freeze_panes = "A3"

    if sheet.max_column > 0:
        max_col_letter = get_column_letter(sheet.max_column)
        sheet.auto_filter.ref = f"A2:{max_col_letter}{sheet.max_row}"

    # Auto-adjust column widths with reasonable defaults
    column_widths = {
        1: 8,   # Step
        2: 24,  # Test sequence name
        3: 14,  # ECU
        4: 24,  # Payload (HEX)
        5: 12,  # Delay (ms)
        6: 10,  # Repeat
        7: 24,  # Expected Response (HEX)
        8: 24,  # Receive Message (HEX)
        9: 14,  # Results
        10: 25, # Comment
    }
    for col_idx, width in column_widths.items():
        col_letter = get_column_letter(col_idx)
        sheet.column_dimensions[col_letter].width = width


class CanDiagnosticReportService:
    def __init__(
        self,
        report_root: str | Path | None = None,
        now_provider=datetime.now,
    ):
        self.report_root = (
            Path(report_root)
            if report_root is not None
            else CAN_INTERFACE_REPORT_DIR
        )
        self._now_provider = now_provider

    def report_folder(self) -> Path:
        today = self._now_provider().strftime("%d-%m-%Y")
        report_folder = self.report_root / today
        report_folder.mkdir(parents=True, exist_ok=True)
        return report_folder

    def default_report_path(self) -> Path:
        now = self._now_provider()
        return self.report_folder() / (
            f"EEIV_report_Diagnostic_{now.strftime('%Y%m%d_%H%M%S')}.xlsx"
        )

    def export_report(
        self,
        sheets: Sequence[CanDiagnosticReportSheet],
        output_file: str | Path,
    ) -> Path:
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        workbook = Workbook()
        default_sheet = workbook.active

        sheets_to_process = list(sheets)
        if not sheets_to_process:
            sheets_to_process = [CanDiagnosticReportSheet(title="Sequence", rows=[])]

        used_titles: set[str] = set()
        headers = list(CAN_DIAGNOSTIC_REPORT_HEADERS)

        for index, sheet_data in enumerate(sheets_to_process):
            raw_title = sheet_data.title or f"Sequence_{index + 1}"
            title = safe_excel_sheet_name(raw_title)

            # Avoid sheet name collisions
            base_title = title
            suffix = 1
            while title.lower() in used_titles:
                title = f"{base_title[:28]}_{suffix}"
                suffix += 1
            used_titles.add(title.lower())

            if index == 0:
                ws = default_sheet
                ws.title = title
            else:
                ws = workbook.create_sheet(title=title)

            # Row 1: Header banner
            ws.merge_cells(
                start_row=1,
                start_column=1,
                end_row=1,
                end_column=len(headers),
            )
            ws["A1"] = "Generated by V-CODE EEIV Diagnostic"
            ws["A1"].alignment = HEADER_ALIGNMENT
            ws["A1"].font = HEADER_FONT

            # Row 2: Column Headers
            ws.append(headers)

            # Row 3+: Data rows
            for step_row in sheet_data.rows:
                ws.append(step_row.values_for_headers(headers))

            _format_diagnostic_export_sheet(ws)

        workbook.save(output_path)
        return output_path

