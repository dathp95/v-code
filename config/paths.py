from pathlib import Path
import sys

if getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent

OUTPUT_DIR = PROJECT_ROOT / "output"

LOG_ANALYZER_REPORT_DIR = OUTPUT_DIR / "Report_LogAnalyzer"
CODING_VALUE_REPORT_DIR = OUTPUT_DIR / "Report_CodingValue"
Q_CURRENT_REPORT_DIR = OUTPUT_DIR / "Report_QCurrent"
CAN_INTERFACE_LOG_DIR = OUTPUT_DIR / "CAN_Interface_Logs"
CAN_INTERFACE_REPORT_DIR = OUTPUT_DIR / "Report_CANInterface"

CONFIG_DIR = PROJECT_ROOT / "config"
Q_CURRENT_DATABASE_DIR = CONFIG_DIR / "database_qcurrent"
Q_CURRENT_CONFIG_FILE = CONFIG_DIR / "q_current_config.json"
CODING_VALUE_WORKSPACES_FILE = CONFIG_DIR / "coding_value_workspaces.json"
CODING_VALUE_WORKSPACE_SNAPSHOTS_DIR = CONFIG_DIR / "coding_value_workspace_snapshots"
EXPORT_CODING_FILES_DIR = CONFIG_DIR / "export_coding_files"
DIAGNOSTIC_SEQUENCES_DIR = CONFIG_DIR / "diagnostic_sequences"

VEHICLES_DIR = CONFIG_DIR / "vehicles"

QUICK_FILTER_FILE = CONFIG_DIR / "quick_filters.json"
SHORTCUTS_FILE = PROJECT_ROOT / "shortcuts" / "shortcuts.json"
DISPLAY_NAMES_FILE = CONFIG_DIR / "display_names.json"
UDS_SERVICES_FILE = CONFIG_DIR / "uds_services.json"
UDS_USER_FILE = CONFIG_DIR / "uds_user.json"
RELEASE_FEATURES_FILE = CONFIG_DIR / "release_features.json"

if getattr(sys, "frozen", False):
    RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))
else:
    RESOURCE_ROOT = PROJECT_ROOT

RESOURCE_DIR = RESOURCE_ROOT / "gui" / "resources"
ICON_DIR = RESOURCE_DIR / "icons"
IMAGE_DIR = RESOURCE_DIR / "images"
