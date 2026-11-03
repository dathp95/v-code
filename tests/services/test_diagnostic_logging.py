"""Deterministic tests for diagnostic anomaly logging and logging service."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.diagnostic_request import (
    DiagnosticRequest,
    DiagnosticSettings,
    DiagnosticOutcome,
    DiagnosticResult,
)


class TestDiagnosticLogging(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.log_dir = Path(self.tmpdir.name) / "CAN_Interface_Logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.app_log = self.log_dir / "vcode_app.log"
        self.failure_log = self.log_dir / "diagnostic_failures.log"

    def tearDown(self):
        import logging
        for h in list(logging.getLogger().handlers):
            h.close()
            logging.getLogger().removeHandler(h)
        self.tmpdir.cleanup()

    def test_init_logging_creates_handlers_and_files(self):
        from services.logging_service import init_logging
        with patch("services.logging_service.CAN_INTERFACE_LOG_DIR", self.log_dir), \
             patch("services.logging_service.APP_LOG_FILE", self.app_log), \
             patch("services.logging_service.DIAGNOSTIC_FAILURE_LOG_FILE", self.failure_log):
            init_logging()
            import logging
            log = logging.getLogger("vcode.test")
            log.info("Test logging message")
            for h in logging.getLogger().handlers:
                h.flush()

        self.assertTrue(self.app_log.exists(), "Expected vcode_app.log to be created")
        content = self.app_log.read_text(encoding="utf-8")
        self.assertIn("Test logging message", content)

    def test_log_diagnostic_failure_on_silent_ecu_timeout(self):
        """When ECU is silent on 27 01 timeout, log diagnoses Extended Session 10 03 requirement."""
        from services.logging_service import log_diagnostic_failure
        req = DiagnosticRequest(
            transaction_id="tx_test_timeout_1",
            step_id="step_1",
            generation=1,
            vehicle_name="VF5NP",
            ecu_name="EDS",
            tx_id=0x69B,
            rx_id=0x61B,
            uds_payload=b"\x27\x01",
            expected=b"\x67\x01",
            settings=DiagnosticSettings(p2_s=1.0, p2_star_s=2.0, total_s=5.0),
            confirmed=True,
        )
        res = DiagnosticResult(
            request=req,
            outcome=DiagnosticOutcome.TIMEOUT,
            detail="No final ECU response within P2.",
            elapsed_s=1.002,
        )
        telemetry = {
            "tx_count": 1,
            "rx_target_count": 0,
            "rx_total_count": 145,
            "channel": 0,
            "bitrate": 500000,
        }

        with patch("services.logging_service.CAN_INTERFACE_LOG_DIR", self.log_dir), \
             patch("services.logging_service.DIAGNOSTIC_FAILURE_LOG_FILE", self.failure_log):
            log_diagnostic_failure(res, telemetry)

        self.assertTrue(self.failure_log.exists())
        content = self.failure_log.read_text(encoding="utf-8")
        self.assertIn("DIAGNOSTIC ANOMALY REPORT", content)
        self.assertIn("VF5NP", content)
        self.assertIn("EDS", content)
        self.assertIn("0x69B", content)
        self.assertIn("0x61B", content)
        self.assertIn("TIMEOUT", content)
        self.assertIn("10 03", content, "Expected log to suggest checking Extended Session 10 03")
        self.assertIn("145", content, "Expected total bus frames to be noted")

    def test_log_diagnostic_failure_on_nrc_7e(self):
        """When ECU returns NRC 0x7E, log identifies subfunction not supported in active session."""
        from services.logging_service import log_diagnostic_failure
        req = DiagnosticRequest(
            transaction_id="tx_nrc_7e",
            step_id="step_1",
            generation=1,
            vehicle_name="VF5NP",
            ecu_name="BCM",
            tx_id=0x681,
            rx_id=0x601,
            uds_payload=b"\x27\x01",
            expected=b"\x67\x01",
            settings=DiagnosticSettings(p2_s=1.0, p2_star_s=2.0, total_s=5.0),
            confirmed=True,
        )
        res = DiagnosticResult(
            request=req,
            outcome=DiagnosticOutcome.FAILED,
            response_payload=b"\x7F\x27\x7E",
            detail="ECU terminal negative response NRC 0x7E",
            elapsed_s=0.015,
            nrc=0x7E,
        )
        telemetry = {
            "tx_count": 1,
            "rx_target_count": 1,
            "rx_total_count": 10,
            "channel": 0,
        }

        with patch("services.logging_service.CAN_INTERFACE_LOG_DIR", self.log_dir), \
             patch("services.logging_service.DIAGNOSTIC_FAILURE_LOG_FILE", self.failure_log):
            log_diagnostic_failure(res, telemetry)

        content = self.failure_log.read_text(encoding="utf-8")
        self.assertIn("NRC 0x7E", content)
        self.assertIn("subFunctionNotSupportedInActiveSession", content)
        self.assertIn("10 03", content)

    def test_log_masks_raw_key_and_seed_bytes(self):
        """Security rule: Raw seed and key bytes must NEVER be logged in plain text."""
        from services.logging_service import log_diagnostic_failure, mask_diagnostic_payload
        # Fake 16-byte key payload
        key_payload = b"\x27\x02" + bytes([0xAA] * 16)
        masked_req = mask_diagnostic_payload(0x27, 0x02, key_payload)
        self.assertNotIn("AA AA AA", masked_req)
        self.assertIn("KEY MATERIAL MASKED", masked_req)

        # Fake 16-byte seed response
        seed_response = b"\x67\x01" + bytes([0xBB] * 16)
        masked_resp = mask_diagnostic_payload(0x67, 0x01, seed_response)
        self.assertNotIn("BB BB BB", masked_resp)
        self.assertIn("SEED MATERIAL MASKED", masked_resp)


if __name__ == "__main__":
    unittest.main()
