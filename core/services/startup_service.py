from config.paths import (
    CODING_VALUE_REPORT_DIR,
    LOG_ANALYZER_REPORT_DIR,
    OUTPUT_DIR,
    Q_CURRENT_DATABASE_DIR,
    Q_CURRENT_REPORT_DIR,
    CAN_INTERFACE_LOG_DIR,
)


def ensure_directories():
    """Create required application directories if they don't exist."""

    for folder in (
        OUTPUT_DIR,
        LOG_ANALYZER_REPORT_DIR,
        CODING_VALUE_REPORT_DIR,
        Q_CURRENT_DATABASE_DIR,
        Q_CURRENT_REPORT_DIR,
        CAN_INTERFACE_LOG_DIR,
    ):
        folder.mkdir(parents=True, exist_ok=True)
