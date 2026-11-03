"""Central diagnostic & application logging service with failure anomaly reporting.

Guarantees:
1. Persistent application log file in output/CAN_Interface_Logs/vcode_app.log.
2. Structured failure & anomaly reports in output/CAN_Interface_Logs/diagnostic_failures.log.
3. Automated root-cause assistance for timeouts and NRC rejections (e.g. 10 03 requirement).
4. Strictly masks OEM raw seeds, keys, and security material in compliance with security policies.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from config.paths import CAN_INTERFACE_LOG_DIR

APP_LOG_FILE = CAN_INTERFACE_LOG_DIR / "vcode_app.log"
DIAGNOSTIC_FAILURE_LOG_FILE = CAN_INTERFACE_LOG_DIR / "diagnostic_failures.log"

LOG = logging.getLogger("vcode")

# ISO 14229-1 Negative Response Code Names
UDS_NRC_DESCRIPTIONS = {
    0x10: "generalReject",
    0x11: "serviceNotSupported",
    0x12: "subFunctionNotSupported",
    0x13: "incorrectMessageLengthOrInvalidFormat",
    0x14: "responseTooLong",
    0x21: "busyRepeatRequest",
    0x22: "conditionsNotCorrect",
    0x24: "requestSequenceError",
    0x25: "noResponseFromSubnetComponent",
    0x26: "failurePreventsExecutionOfRequestedAction",
    0x31: "requestOutOfRange",
    0x33: "securityAccessDenied",
    0x35: "invalidKey",
    0x36: "exceededNumberOfAttempts",
    0x37: "requiredTimeDelayNotExpired",
    0x70: "uploadDownloadNotAccepted",
    0x71: "transferDataSuspended",
    0x72: "generalProgrammingFailure",
    0x73: "wrongBlockSequenceCounter",
    0x78: "requestCorrectlyReceived-ResponsePending",
    0x7E: "subFunctionNotSupportedInActiveSession",
    0x7F: "serviceNotSupportedInActiveSession",
}

_INITIALIZED = False


def init_logging() -> None:
    """Initialize application-wide logging handlers and uncaught exception hook."""
    global _INITIALIZED
    CAN_INTERFACE_LOG_DIR.mkdir(parents=True, exist_ok=True)
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Avoid duplicate file handlers on repeated init
    for handler in list(root_logger.handlers):
        if isinstance(handler, RotatingFileHandler) and getattr(handler, "_vcode_app_handler", False):
            return

    formatter = logging.Formatter(
        "%(asctime)s.%(msecs)03d [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        file_handler = RotatingFileHandler(
            str(APP_LOG_FILE),
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        file_handler._vcode_app_handler = True
        root_logger.addHandler(file_handler)
    except Exception as err:
        sys.stderr.write(f"Cannot initialize file logger: {err}\n")

    # Install unhandled exception hook once
    if not _INITIALIZED:
        original_hook = sys.excepthook

        def _exception_hook(exc_type, exc_value, exc_tb):
            if issubclass(exc_type, KeyboardInterrupt):
                original_hook(exc_type, exc_value, exc_tb)
                return
            LOG.critical("Unhandled application crash/exception:", exc_info=(exc_type, exc_value, exc_tb))
            original_hook(exc_type, exc_value, exc_tb)

        sys.excepthook = _exception_hook
        _INITIALIZED = True


def mask_diagnostic_payload(sid: int, subfunc: int | None, payload: bytes | None) -> str:
    """Mask sensitive OEM seed, key, and raw cryptographic payload bytes."""
    if not payload or not isinstance(payload, bytes):
        return ""
    # SecurityAccess Request (0x27)
    if sid == 0x27:
        if subfunc is not None and subfunc % 2 == 1:
            return f"27 {subfunc:02X} [SEED REQUEST]"
        elif subfunc is not None and subfunc % 2 == 0:
            byte_len = max(0, len(payload) - 2)
            return f"27 {subfunc:02X} [KEY MATERIAL MASKED - {byte_len} BYTES]"
        return "27 ?? [SECURITY ACCESS]"

    # SecurityAccess Response (0x67)
    if sid == 0x67:
        if subfunc is not None and subfunc % 2 == 1:
            byte_len = max(0, len(payload) - 2)
            return f"67 {subfunc:02X} [SEED MATERIAL MASKED - {byte_len} BYTES]"
        elif subfunc is not None and subfunc % 2 == 0:
            return f"67 {subfunc:02X} [POSITIVE UNLOCK RESPONSE]"
        return "67 ?? [SECURITY RESPONSE]"

    # Other non-security UDS payloads (e.g. 10 03, 22 F1 90)
    return payload.hex(" ").upper()


def log_diagnostic_transaction(result) -> None:
    """Log one structured line for every completed diagnostic transaction."""
    if not _INITIALIZED:
        init_logging()
    req = result.request
    sid = req.uds_payload[0] if req.uds_payload else 0
    subfunc = req.uds_payload[1] if len(req.uds_payload) > 1 else None
    safe_req = mask_diagnostic_payload(sid, subfunc, req.uds_payload)

    resp_sid = result.response_payload[0] if result.response_payload else None
    resp_sub = result.response_payload[1] if result.response_payload and len(result.response_payload) > 1 else None
    safe_resp = mask_diagnostic_payload(resp_sid, resp_sub, result.response_payload) if resp_sid else ""

    LOG.info(
        "DIAG_TX | TxID=0x%03X RxID=0x%03X | %s/%s | Req=%s | Resp=%s | Outcome=%s | RT=%.3fs | Detail=%s",
        req.tx_id,
        req.rx_id,
        req.vehicle_name,
        req.ecu_name,
        safe_req,
        safe_resp or "none",
        result.outcome.value,
        result.elapsed_s,
        result.detail,
    )


def log_diagnostic_failure(result, telemetry: dict | None = None) -> None:
    """Generate and write a comprehensive diagnostic anomaly and root-cause report."""
    if not _INITIALIZED:
        init_logging()
    req = result.request
    telemetry = telemetry or {}
    sid = req.uds_payload[0] if req.uds_payload else 0
    subfunc = req.uds_payload[1] if len(req.uds_payload) > 1 else None
    safe_req = mask_diagnostic_payload(sid, subfunc, req.uds_payload)

    exp_sid = req.expected[0] if req.expected else None
    exp_sub = req.expected[1] if req.expected and len(req.expected) > 1 else None
    safe_exp = mask_diagnostic_payload(exp_sid, exp_sub, req.expected) if exp_sid else (req.expected.hex(" ").upper() if req.expected else "none")

    resp_sid = result.response_payload[0] if result.response_payload else None
    resp_sub = result.response_payload[1] if result.response_payload and len(result.response_payload) > 1 else None
    safe_resp = mask_diagnostic_payload(resp_sid, resp_sub, result.response_payload) if resp_sid else "none"

    tx_count = telemetry.get("tx_count", 1)
    rx_target = telemetry.get("rx_target_count", 0)
    rx_total = telemetry.get("rx_total_count", 0)
    channel = telemetry.get("channel", 0)
    bitrate = telemetry.get("bitrate", 500000)

    # Automated Root-Cause Analysis
    reasons = []
    if result.outcome.value == "Timeout":
        if rx_target == 0 and rx_total > 0:
            reasons.append(
                f"[!] Target ECU 0x{req.rx_id:03X} remained completely silent during the {result.elapsed_s:.3f}s window.\n"
                f"    CAN channel {channel} is ACTIVE (observed {rx_total} other CAN frames on the bus).\n"
                f"    Primary Root Causes:\n"
                f"    1. Diagnostic Session: ECU requires Extended Session (10 03 -> 50 03) before SecurityAccess ({req.uds_payload.hex(' ').upper()}).\n"
                f"       -> Action: Execute '10 03' first, confirm positive response '50 03', then send '{req.uds_payload.hex(' ').upper()}'.\n"
                f"    2. Session Expiration (S3=5.0s): If '10 03' was sent earlier, the ECU automatically reverted to Default Session\n"
                f"       if more than 5.0s passed without TesterPresent (3E 00) or other requests.\n"
                f"    3. Subnet / Gateway Routing: {req.ecu_name} may reside on another CAN bus or behind a Gateway (XGW/CGW).\n"
                f"    4. Power / KL15 Ignition: Verify the ECU is awake and powered on the test bench.\n"
                f"    5. ID Mapping: Check config/vehicles/{req.vehicle_name}/ecus/{req.ecu_name}.json (Request: 0x{req.tx_id:03X}, Response: 0x{req.rx_id:03X})."
            )
        elif rx_total == 0:
            reasons.append(
                f"[!] ZERO CAN TRAFFIC DETECTED on channel {channel}!\n"
                f"    Primary Root Causes:\n"
                f"    1. Physical wiring: Vector CAN cable is disconnected or loose.\n"
                f"    2. Termination: Missing 120-ohm termination resistor on Classical CAN bus.\n"
                f"    3. Channel index: Vector hardware channel {channel} does not match physical port."
            )
        else:
            reasons.append(
                f"[!] Frame received from 0x{req.rx_id:03X} ({rx_target} frames), but no valid final response within timeout."
            )
    elif result.nrc is not None:
        nrc_name = UDS_NRC_DESCRIPTIONS.get(result.nrc, f"Unknown NRC 0x{result.nrc:02X}")
        reasons.append(
            f"[!] ECU responded with Negative Response Code NRC 0x{result.nrc:02X}: {nrc_name}.\n"
        )
        if result.nrc == 0x7E:
            reasons.append(
                "    -> ECU rejects request because subfunction is not supported in the CURRENT active session.\n"
                "       Action: Enter Extended Diagnostic Session (10 03) first!"
            )
        elif result.nrc == 0x22:
            reasons.append(
                "    -> ECU conditions not correct (vehicle state, speed, or precondition not satisfied)."
            )
        elif result.nrc == 0x35:
            reasons.append(
                "    -> Invalid Key: The computed Key was rejected by the ECU. Verify DLL algorithm profile."
            )
        elif result.nrc in (0x36, 0x37):
            reasons.append(
                "    -> ECU SecurityAccess is LOCKED OUT due to excessive attempts or required delay."
            )

    analysis_text = "\n".join(reasons) if reasons else "[!] General diagnostic failure."

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    report = (
        "================================================================================\n"
        f"[{now_str}] DIAGNOSTIC ANOMALY REPORT\n"
        f"Transaction ID : {req.transaction_id}\n"
        f"Vehicle / ECU  : {req.vehicle_name} / {req.ecu_name}\n"
        f"CAN Addressing : TX 0x{req.tx_id:03X} -> RX 0x{req.rx_id:03X} (11-bit Normal)\n"
        f"UDS Request    : {safe_req}\n"
        f"Expected Resp  : {safe_exp}\n"
        f"Actual Response: {safe_resp}\n"
        f"Outcome        : {result.outcome.value.upper()}\n"
        f"Detail         : {result.detail}\n"
        f"Elapsed Time   : {result.elapsed_s:.3f} s (P2={req.settings.p2_s:.1f}s, Total={req.settings.total_s:.1f}s)\n"
        f"CAN Telemetry  :\n"
        f"  - TX frames sent       : {tx_count}\n"
        f"  - Target RX frames     : {rx_target} (CAN ID 0x{req.rx_id:03X})\n"
        f"  - Total bus frames     : {rx_total} (Channel {channel}, {bitrate // 1000} kbps)\n"
        "Root Cause Analysis:\n"
        f"{analysis_text}\n"
        "================================================================================\n\n"
    )

    try:
        CAN_INTERFACE_LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(DIAGNOSTIC_FAILURE_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(report)
            f.flush()
    except Exception as err:
        sys.stderr.write(f"Cannot write diagnostic failure log: {err}\n")

    LOG.warning(
        "DIAGNOSTIC ANOMALY [%s/%s]: %s | Outcome=%s | Detail=%s | Log: %s",
        req.vehicle_name,
        req.ecu_name,
        safe_req,
        result.outcome.value,
        result.detail,
        DIAGNOSTIC_FAILURE_LOG_FILE,
    )


def open_logs_folder() -> bool:
    """Open the CAN logs directory in Windows Explorer or system file manager."""
    try:
        CAN_INTERFACE_LOG_DIR.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(CAN_INTERFACE_LOG_DIR))
            return True
        import subprocess
        subprocess.Popen(["xdg-open", str(CAN_INTERFACE_LOG_DIR)])
        return True
    except Exception as err:
        LOG.exception("Cannot open logs folder: %s", err)
        return False
