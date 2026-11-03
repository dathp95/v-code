"""Bounded I/O pump, child of the existing native connection owner worker."""
import logging
import time
import hashlib
import secrets
from collections import deque

from PySide6.QtCore import QObject,QTimer,Qt,Signal,Slot
from core.diagnostic_request import DiagnosticResult,DiagnosticOutcome as Outcome,DiagnosticCancelled,is_security_seed_payload
from services.can.can_connection import CANIoError
from core.security_submission import is_key_submission

LOG=logging.getLogger(__name__)


class CanDiagnosticSession(QObject):
    finished=Signal(object)
    raw_frames=Signal(object)
    connection_fault=Signal(object)
    monitoring_changed=Signal(bool)
    capture_failed=Signal(str)

    def __init__(self,service,parent):
        super().__init__(parent)
        self.service=service
        self.request=None
        self.client=None
        self.cancelled=None
        self._frames=[]
        self._private_tx = deque(maxlen=4096)
        self._private_fingerprints = deque(maxlen=4096)
        self._private_seed_streams = {}
        self._capture_salt = secrets.token_bytes(16)
        self._leased=False
        self.monitoring=False
        self.capture_sink=None
        self.timer=QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.setInterval(2)
        self.timer.timeout.connect(self._pump)

    def start_monitoring(self):
        self.monitoring=True
        self.timer.start()
        self.monitoring_changed.emit(True)

    def stop_monitoring(self):
        self.timer.stop()
        self.monitoring=False
        self.cancel()
        self._publish()
        self.monitoring_changed.emit(False)

    def _capture(self,frame):
        self._rx_total_count = getattr(self, '_rx_total_count', 0) + 1
        if self.request is not None and frame.can_id == self.request.rx_id and frame.direction == 'RX':
            self._rx_target_count = getattr(self, '_rx_target_count', 0) + 1
        if self.capture_sink is not None: self.capture_sink(frame)
        self._frames.append(frame)

    def _frame_fingerprint(self, frame):
        # Driver echo correlation expires after 1 s. A bounded, salted in-memory
        # digest also protects delayed copies without retaining any raw key bytes.
        digest = hashlib.blake2s(frame.data, key=self._capture_salt, digest_size=16).digest()
        return (frame.session_id, frame.can_id, frame.dlc, digest)

    def start(self,request,cancelled):
        if self.request is not None:
            self.finished.emit(DiagnosticResult(request,Outcome.ERROR,detail='A diagnostic request is already running.'))
            return
        if cancelled is not None and cancelled.is_set():
            self.finished.emit(DiagnosticResult(request,Outcome.CANCELLED,detail='Diagnostic request cancelled before start.'))
            return
        self.request=request
        self._tx_count = 0
        self._rx_target_count = 0
        self._rx_total_count = 0
        if (is_security_seed_payload(request.uds_payload)
                and getattr(self.service, 'is_auto_request', lambda _: False)(request)):
            session_id = self.service.capture_session_id
            # Bound metadata to the active connection; no seed bytes are retained.
            self._private_seed_streams = {key: value for key, value in self._private_seed_streams.items()
                                          if key[0] == session_id}
            self._private_seed_streams[(session_id, request.rx_id)] = True
        self.cancelled=cancelled
        try:
            # Import lazily: missing optional transport dependency never breaks
            # discovery/connection or application startup, and sends no frame.
            from services.can.diagnostic_client import DiagnosticClient
            self._client_class=DiagnosticClient
            self.service.fn_begin_diagnostic(request)
            self._leased=True
            self.started=time.monotonic()
            if not self.monitoring: self.start_monitoring()
            if self.timer.isActive():
                self.timer.stop()
            self._execute_diagnostic()
        except Exception as error:
            LOG.exception('Cannot start diagnostic transport')
            message='can-isotp 2.0.7 is required; install requirements.txt.' if isinstance(error,ImportError) else str(error)
            self._finish(DiagnosticResult(request,Outcome.ERROR,detail=message))

    def _send(self,can_id,data):
        self._tx_count = getattr(self, '_tx_count', 0) + 1
        frame=self.service.fn_send_diagnostic_frame(can_id,data)
        self._capture(frame)

    def _publish(self):
        if self._frames:
            self.raw_frames.emit(tuple(self._frames))
            self._frames.clear()

    def _execute_diagnostic(self):
        try:
            if self.cancelled.is_set():
                self.cancel()
                return

            # Drain old driver queue before transmitting; cooperative and bounded,
            # so Disconnect is still serviced even with a saturated CAN channel.
            if self.client is None:
                drain_start = time.monotonic()
                while self.client is None:
                    if self.cancelled.is_set():
                        self.cancel()
                        return
                    if time.monotonic() - drain_start >= min(2.0, self.request.settings.total_s):
                        self._finish(DiagnosticResult(self.request, Outcome.ERROR,
                                                      detail='RX backlog did not clear; no request was sent. Retry after the channel recovers.'))
                        return
                    for _ in range(32):
                        frame = self.service.fn_receive_diagnostic_frame(timeout=0.0)
                        if frame is None:
                            self.client = self._client_class(self.request, self._send, self.cancelled)
                            break
                        self._capture(frame)

            self.client.poll()  # Send the request before handling its response.

            # Rapid initial drain for immediate responses or loopback
            for _ in range(32):
                if self.client.result is not None:
                    break
                if self.cancelled.is_set():
                    self.cancel()
                    return
                frame = self.service.fn_receive_diagnostic_frame(timeout=0.0)
                if frame is None:
                    break
                self._capture(frame)
                self.client.feed(frame)
                self.client.poll()

            if self.client.result is not None:
                self._finish(self.client.result)
                return

            last_publish = time.monotonic()
            while (self.request is not None
                   and self.client is not None
                   and self.client.result is None):
                if self.cancelled.is_set():
                    self.cancel()
                    return

                now = time.monotonic()
                if now - self.started >= self.request.settings.total_s:
                    result = self.client.finish(Outcome.TIMEOUT, detail='Maximum transaction duration exceeded.')
                    self._finish(result)
                    return

                # Determine wait timeout based on ISO-TP activity:
                # When actively transmitting (e.g. waiting for Flow Control or spacing CFs)
                # or receiving (waiting for Consecutive Frames): use tight 1ms wait on hardware event.
                # When waiting for ECU UDS response (idle wait): use 5ms wait.
                is_active = (self.client.engine.transmitting or self.client.engine.receiving)
                rx_timeout = 0.001 if is_active else 0.005

                frame = self.service.fn_receive_diagnostic_frame(timeout=rx_timeout)
                if frame is not None:
                    self._capture(frame)
                    self.client.feed(frame)
                    self.client.poll()

                    # Drain companion burst frames
                    for _ in range(32):
                        if self.client.result is not None or self.cancelled.is_set():
                            break
                        companion = self.service.fn_receive_diagnostic_frame(timeout=0.0)
                        if companion is None:
                            break
                        self._capture(companion)
                        self.client.feed(companion)
                        self.client.poll()
                else:
                    self.client.poll()

                # If transmitting multi-frame and STmin=0, stream out outgoing CFs immediately
                while (self.client.result is None
                       and self.client.engine.transmitting
                       and not self.cancelled.is_set()):
                    prev_tx = len(self._frames)
                    self.client.poll()
                    if len(self._frames) == prev_tx:
                        break

                if self.client.result is not None:
                    self._finish(self.client.result)
                    return

                # Cooperative UI batch publish (~25ms)
                if time.monotonic() - last_publish >= 0.025:
                    self._publish()
                    last_publish = time.monotonic()

        except DiagnosticCancelled:
            self.cancel()  # Expired authorization is not a capture/BLF failure.
        except CANIoError as error:
            self.capture_failed.emit(f'CAN capture stopped unexpectedly: {error}')
            LOG.exception('Native diagnostic I/O failed')
            result = (self.client.finish(Outcome.ERROR, detail=str(error)) if self.client else
                      DiagnosticResult(self.request, Outcome.ERROR, detail=str(error)) if self.request else None)
            self.timer.stop()
            self.monitoring = False
            self.monitoring_changed.emit(False)
            self._release()
            try:
                self.service.fn_transport_failed(error)
            except Exception:
                LOG.exception('Cleanup following diagnostic I/O error failed')
            self.connection_fault.emit(self.service.snapshot)
            if result is not None:
                self.finished.emit(result)
        except Exception as error:
            self.capture_failed.emit(f'CAN acquisition/processing failed: {error}')
            LOG.exception('Diagnostic processing failed')
            if self.request is not None:
                result = (self.client.finish(Outcome.ERROR, detail=str(error)) if self.client else
                          DiagnosticResult(self.request, Outcome.ERROR, detail=str(error)))
                self._finish(result)
            else:
                self.timer.stop()
                self.monitoring = False
                self.monitoring_changed.emit(False)
                self.connection_fault.emit(self.service.snapshot)
        finally:
            self._publish()
            if self.monitoring and not self.timer.isActive():
                self.timer.start()

    @Slot()
    def _pump(self):
        if not self.monitoring: return
        try:
            if self.request is None:
                for _ in range(32):
                    frame=self.service.fn_receive_capture_frame()
                    if frame is None: break
                    self._capture(frame)
                return
            self._execute_diagnostic()
        finally:
            self._publish()

    def _release(self):
        if self._leased:
            self.service.fn_end_diagnostic(self.request.transaction_id)
            self._leased=False
        self.request=None
        self.client=None
        self._publish()

    def _finish(self,result):
        tx_count = getattr(self, '_tx_count', 0)
        rx_target = getattr(self, '_rx_target_count', 0)
        rx_total = getattr(self, '_rx_total_count', 0)
        cfg = getattr(self.service.snapshot, 'config', None)
        telemetry = {
            'tx_count': tx_count,
            'rx_target_count': rx_target,
            'rx_total_count': rx_total,
            'channel': getattr(cfg, 'channel', 0) if cfg else 0,
            'bitrate': getattr(cfg, 'bitrate', 500000) if cfg else 500000,
        }

        # Enrich timeout detail if target ECU was silent
        if result.outcome == Outcome.TIMEOUT and rx_target == 0 and self.request is not None:
            if '0 frames received' not in result.detail:
                from dataclasses import replace
                hint = f"(0 frames received on 0x{self.request.rx_id:03X}; {rx_total} bus frames observed). Check 10 03 session or power."
                result = replace(result, detail=f"{result.detail} {hint}")

        try:
            from services.logging_service import log_diagnostic_transaction, log_diagnostic_failure
            log_diagnostic_transaction(result)
            if result.outcome not in (Outcome.PASSED, Outcome.NOT_EVALUATED):
                log_diagnostic_failure(result, telemetry)
        except Exception:
            LOG.exception('Diagnostic logging failed')

        completed=getattr(self.service,'fn_diagnostic_completed',None)
        if callable(completed): completed(result)
        self._release()
        self.finished.emit(result)

    def cancel(self):
        if self.request is None: return
        result=self.client.cancel() if self.client else DiagnosticResult(self.request,Outcome.CANCELLED,detail='Diagnostic request cancelled before TX.')
        self._finish(result)
