from __future__ import annotations

import sys
import signal

# Clean interrupt handling immediately before any heavy imports
signal.signal(signal.SIGINT, signal.SIG_DFL)

from core.services.startup_service import ensure_directories
from PySide6.QtWidgets import QApplication

from gui.windows.splash_screen import VCodeSplashScreen
from gui.themes.icon_manager import IconManager
from license.manager import LicenseManager
from utils.windows_shortcut import ensure_start_menu_shortcut

MainWindow = None


APP_NAME = "V-CODE"
APP_VERSION = "v3.0.6"
APP_AUTHOR = "AES EEIV by DAT TRAN"


def fn_window_title(license_status) -> str:
    if license_status.is_valid and license_status.license is not None:
        return (
            f"{APP_NAME} {APP_VERSION} | "
            f"{APP_AUTHOR} | "
            f"Valid until "
            f"{license_status.license.expire_date.astimezone().strftime('%d/%m/%Y %H:%M:%S')}"
        )

    return (
        f"{APP_NAME} {APP_VERSION} | "
        f"{APP_AUTHOR} | "
        "Limited Mode"
    )


def main() -> int:
    global MainWindow

    ensure_directories()
    from services.logging_service import init_logging
    init_logging()
    ensure_start_menu_shortcut()
   
    app = QApplication(sys.argv)
    app.setWindowIcon(IconManager.app())

    splash = None
    if isinstance(QApplication, type) and isinstance(app, QApplication):
        splash = VCodeSplashScreen()
        splash.show()
        splash.set_progress(10, "Verifying license & system environment...")
        app.processEvents()

    license_status = LicenseManager.get_status()

    if splash is not None:
        splash.set_progress(25, "Loading application modules...")
        app.processEvents()

    if MainWindow is None:
        from gui.windows.main_window import MainWindow as _MainWindow
        MainWindow = _MainWindow

    if splash is not None:
        splash.set_progress(40, "Initializing workspace & UI tabs...")
        app.processEvents()

    kwargs = {"license_status": license_status}
    if splash is not None:
        kwargs["progress_callback"] = splash.set_progress

    window = MainWindow(**kwargs)

    if splash is not None:
        splash.set_progress(100, "Starting V-CODE...")
        app.processEvents()

    window.setWindowTitle(
        fn_window_title(license_status)
    )

    # Show the main window before closing the splash screen.
    window.showMaximized()

    if splash is not None:
        app.processEvents()
        splash.finish(window)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
