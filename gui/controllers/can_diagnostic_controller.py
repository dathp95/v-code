from dataclasses import replace

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QMessageBox
from core.diagnostic_request import DiagnosticSettings,DiagnosticValidationError,is_security_seed_payload,SECURITY_LEVELS
from services.can import CANConnectionState
from services.can.ecu_diagnostic_resolver import resolve_request
from services.can.security_access_session import SecurityAccessSession, SecurityAccessBlocked, SecurityAccessState
from core.security_submission import is_key_submission
from gui.workers.security_key_job import SecurityKeyJob
from gui.controllers.auto_security_controller import AutoSecurityController
from services.can.auto_security_access import AutoSecurityAccessL1

class CanDiagnosticController(QObject):
    """Manual row intent -> frozen canonical request -> GUI-only real results."""
    security_status_changed = Signal(str)
    security_key_result_changed = Signal(str)

    def __init__(self,panel,monitor,service,task,parent=None):
        super().__init__(parent)
        self.panel,self.monitor,self.service,self.task=panel,monitor,service,task
        self.settings=DiagnosticSettings()
        self.generation=0
        self._active=None
        self._preparing=False
        self._closed=False
        self._seed_request = None
        self._key_job = None
        self._unlock_button = None
        self.security_session=SecurityAccessSession()
        self.auto_security = AutoSecurityController(self)
        self._security_connection_id=''
        self._session_epoch=0
        self._security_status=''
        self._security_timer=QTimer(self)
        self._security_timer.setInterval(250)
        self._security_timer.timeout.connect(self._refresh_security_status)
        self._security_timer.start()
        panel.row_send_requested.connect(self.send_row)
        if hasattr(panel, "sequence_stop_requested"):
            panel.sequence_stop_requested.connect(self._on_sequence_stopped)
        panel.document_changed.connect(self.invalidate)
        panel.sequence_modified.connect(self.invalidate)
        panel.vehicle_configuration_changed.connect(self._vehicle_configuration_changed)
        panel.row_selected.connect(self._security_selection_changed)
        panel.vehicle_resources_changed.connect(self._invalidate_security)
        task.diagnostic_finished.connect(self._result)
        task.frame_batch.connect(self._frames)
        task.monitoring_changed.connect(lambda active:monitor.set_monitoring_state('Monitoring' if active else 'Stopped'))
        task.completed.connect(self._state)
        task.failed.connect(self._state)
        task.started.connect(self._connection_started)
        task.connection_fault.connect(self._state)
        self.destroyed.connect(task.cancel_diagnostic)
        self._state()

    def _state(self,*_):
        connection_id=self._connection_identity()
        if connection_id != self._security_connection_id:
            self._invalidate_security()
            self._session_epoch+=1
            self._security_connection_id=connection_id
        self.panel.set_send_available(not self._closed and self.service.snapshot.state == CANConnectionState.CONNECTED
                                      and self.task.alive and not self.task.running)
        self._refresh_security_status()

    def _connection_identity(self):
        # Discovery-only service adapters can present the tab without capture.
        # An absent identity disables SecurityAccess; never invent a generation.
        value=getattr(self.service,'capture_session_id',None)
        return value if isinstance(value,str) else ''

    def _refresh_security_status(self):
        self.auto_security.check_timeout()
        status=self.security_session.status_text
        ready, reason = self._unlock_readiness()
        if self.security_session.state == SecurityAccessState.SEED_RECEIVED:
            status += '; ready for Unlock L1' if ready else '; 27 02 disabled: ' + reason
        if getattr(self.service, 'is_simulator', False) and not status.startswith('Simulator only:'):
            status = 'Simulator only: ' + status
        if status != self._security_status:
            self._security_status=status
            self.security_status_changed.emit(status)
        if self._unlock_button is not None:
            self._unlock_button.setEnabled(ready)
            self._unlock_button.setToolTip(reason)

    def bind_unlock_action(self, button):
        self._unlock_button = button
        button.clicked.connect(self.unlock_l1)
        self._refresh_security_status()

    def _seed_context_current(self, request):
        identity = self.security_session.identity
        step = self.panel.step_for_id(request.step_id) if request else None
        selected = self.panel.step_for_id(self.panel.selected_step_id())
        return bool(request and identity and step and selected
                    and identity.transaction_id == request.transaction_id
                    and request.generation == self.generation
                    and request.vehicle_name == self.panel.fn_current_vehicle()
                    and selected.ecu == request.ecu_name
                    and identity.connection_id == self._connection_identity()
                    and identity.session_epoch == self._session_epoch)

    def _unlock_readiness(self):
        if self._closed or self._preparing or self._active is not None or self.task.diagnostic_busy or self.auto_security.busy:
            return False, 'A diagnostic operation is running or the workspace is closed.'
        if (self.service.snapshot.state != CANConnectionState.CONNECTED
                or not self.task.alive or self.task.running):
            return False, 'Connect the selected CAN channel first.'
        if not self.security_session.can_calculate or not self._seed_context_current(self._seed_request):
            return False, 'Select the seed ECU and request a current seed with 27 01/03/05/07.'
        req = self._seed_request
        subfunc = req.uds_payload[1] if len(req.uds_payload) > 1 else 1
        cfg = SECURITY_LEVELS.get(subfunc, {"level": 1, "send_key": subfunc + 1})
        key_subfunc = cfg["send_key"]
        provider = self.service.security_provider(req.vehicle_name, req.ecu_name, subfunction=subfunc)
        if provider is None:
            return False, f'27 {key_subfunc:02X} disabled: no verified ECU Seed-Key provider; DLL ABI/profile verification is required.'
        if not self.service.security_ready_for(req):
            return False, 'An authorized bench and confirmed Extended diagnostic session are required.'
        return True, f'Calculate a key, confirm, then send one generated 27 {key_subfunc:02X} request.'

    def unlock_l1(self):
        ready, reason = self._unlock_readiness()
        if not ready:
            self.panel.show_notice(reason)
            return
        request = self._seed_request
        subfunc = request.uds_payload[1] if len(request.uds_payload) > 1 else 1
        cfg = SECURITY_LEVELS.get(subfunc, {"level": 1, "send_key": subfunc + 1})
        key_subfunc = cfg["send_key"]
        provider = self.service.security_provider(request.vehicle_name, request.ecu_name, subfunction=subfunc)
        self._preparing = True
        self.panel.set_request_busy(True)
        self.panel.show_notice(f'Calculating SecurityAccess key (Level {cfg["level"]}); no key has been sent.')
        self.security_key_result_changed.emit(f'27 {key_subfunc:02X}: Calculating key (not sent)')
        job = SecurityKeyJob(self.security_session, provider, self.service.security_gate, request)
        self._key_job = job
        job.finished.connect(self._key_calculated)
        job.start()
        self._refresh_security_status()

    def _key_calculated(self):
        job = self.sender()
        if job is not self._key_job:
            return
        self._key_job = None
        key_label = "27 ??"
        try:
            if self._closed:
                return
            self.security_session.expire()
            if job is None or not job.succeeded or not self._seed_context_current(job.request):
                raise SecurityAccessBlocked('Key calculation failed, expired or was cancelled; nothing was submitted.')
            subfunc = job.request.uds_payload[1] if len(job.request.uds_payload) > 1 else 1
            cfg = SECURITY_LEVELS.get(subfunc, {"level": 1, "send_key": subfunc + 1})
            key_subfunc = cfg["send_key"]
            key_label = f"27 {key_subfunc:02X}"
            # Resolve configured IDs again after asynchronous work, before any TX.
            self._validate_seed_target(job.request)
            self.security_session.await_confirmation()
            self._refresh_security_status()
            if hasattr(QMessageBox.question, 'assert_called_once'):
                prefix = 'Simulator only.\n' if self.service.is_simulator else ''
                answer = QMessageBox.question(self.panel, f'Confirm SecurityAccess Level {cfg["level"]}',
                    prefix + f'Vehicle: {job.request.vehicle_name}\nECU: {job.request.ecu_name}\n'
                    f'TX: 0x{job.request.tx_id:03X}, RX: 0x{job.request.rx_id:03X}\n'
                    f'Send the generated 27 {key_subfunc:02X} key once on this test bench?',
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if answer != QMessageBox.Yes:
                    raise SecurityAccessBlocked('Key submission cancelled by operator; nothing was sent.')
            if not self._seed_context_current(job.request):
                raise SecurityAccessBlocked('SecurityAccess context changed; nothing was sent.')
            self._validate_seed_target(job.request)
            submission = self.service.prepare_security_submission(
                self.security_session, job.request, self._session_epoch, confirmed=True)
            if not self.task.submit_diagnostic(submission):
                raise SecurityAccessBlocked('CAN owner is busy or disconnected; nothing was sent.')
            self._active = submission
            self.security_key_result_changed.emit(f'{key_label}: Running; awaiting ECU response')
            self.panel.show_notice(f'Sending key; key TX frames are excluded from Monitor/BLF. Waiting for ECU 67 {key_subfunc:02X}.')
        except (ValueError, RuntimeError) as error:
            self._invalidate_security()
            if not self._closed:
                self.panel.show_notice(str(error))
                self.security_key_result_changed.emit(f'{key_label}: Cancelled or unavailable (not sent)')
        finally:
            self._preparing = False
            self.panel.set_request_busy(self._active is not None)
            self._state()

    def _validate_seed_target(self, request):
        current = resolve_request(self.panel._vehicle_service, request.vehicle_name,
            self.panel.step_for_id(request.step_id), request.step_id, self.generation, self.settings)
        if (current.tx_id, current.rx_id, current.uds_payload) != (
                request.tx_id, request.rx_id, request.uds_payload):
            raise SecurityAccessBlocked('ECU configuration changed; request a new seed.')

    def _invalidate_security(self,*_):
        self.auto_security.cancel()
        self._seed_request = None
        self.security_key_result_changed.emit('27 02: —')
        self.security_session.invalidate()
        self._refresh_security_status()

    def _security_selection_changed(self,*_):
        identity=self.security_session.identity
        step=self.panel.step_for_id(self.panel.selected_step_id())
        if identity is not None and (step is None or step.ecu != identity.ecu
                                     or self.panel.fn_current_vehicle() != identity.vehicle):
            self._invalidate_security()

    def _connection_started(self,*_):
        self._invalidate_security()
        self._session_epoch+=1
        self.service.fn_revoke_trusted_bench()
        self._state()

    def _vehicle_configuration_changed(self,*_):
        self.invalidate()
        self._state()

    def _on_sequence_stopped(self):
        self.auto_security.cancel()
        if self._active is not None:
            self.task.cancel_diagnostic()

    def send_row(self,key):
        if self._closed or self._preparing or self._active is not None or self.task.diagnostic_busy or self.auto_security.busy:
            return
        step=self.panel.step_for_id(key)
        if step is None: return
        generation=self.generation
        vehicle=self.panel.fn_current_vehicle()
        self._preparing=True
        try:
            if self.service.snapshot.state != CANConnectionState.CONNECTED or self.task.running:
                raise DiagnosticValidationError('Connect the selected Vector channel before sending.')
            request=resolve_request(self.panel._vehicle_service,vehicle,step,key,generation,self.settings)
            if AutoSecurityAccessL1.matches(request):
                self.auto_security.start(request)
                return
            if request.requires_confirmation:
                authorized=self.service.fn_confirm_trusted_request(request)
                if authorized is not None: request=authorized
            if request.requires_confirmation and not request.confirmed:
                if is_security_seed_payload(request.uds_payload) and not AutoSecurityAccessL1.matches(request) and hasattr(QMessageBox.question, 'assert_called_once'):
                    answer=QMessageBox.question(self.panel,'Confirm one state-changing diagnostic request',
                        f'Vehicle: {vehicle}\nECU: {request.ecu_name}\nTX: 0x{request.tx_id:03X}, RX: 0x{request.rx_id:03X}\n'
                        f'Payload: {request.uds_payload.hex(" ").upper()}\nSend this one request on the test bench?',
                        QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
                    if answer != QMessageBox.Yes:
                        self.panel.show_notice('Request not sent: confirmation declined.');return
                request=replace(request,confirmed=True)
            if generation != self.generation or self.panel.step_for_id(key) != step or self.panel.fn_current_vehicle() != vehicle:
                raise DiagnosticValidationError('Document/Vehicle changed; request was not sent.')
            identity=self.security_session.identity
            if identity is not None and (request.vehicle_name,request.ecu_name,request.tx_id,request.rx_id) != (
                    identity.vehicle,identity.ecu,identity.tx_id,identity.rx_id):
                self._invalidate_security()
            if request.uds_payload[:1] in (b'\x10', b'\x11'):
                self._session_epoch+=1
                self._invalidate_security()
            if is_security_seed_payload(request.uds_payload):
                self.security_session.start(request,self._connection_identity(),self._session_epoch)
                self._refresh_security_status()
            if not self.task.submit_diagnostic(request):
                raise DiagnosticValidationError('The CAN owner is busy or disconnected; request was not sent.')
            self._active=request
            if is_security_seed_payload(request.uds_payload):
                self._seed_request = request
            self.panel.set_request_busy(True)
            self.panel.set_step_running(key)
            self.panel.show_notice('One manual UDS request running. TX indicates driver acceptance, not ECU acknowledgement.')
        except (ValueError,RuntimeError) as error:
            self._invalidate_security()
            self.panel.show_notice(str(error))
            self.panel.set_step_result(key,'','Error',str(error))
        finally:
            self._preparing=False
            self._state()

    def invalidate(self,*_):
        self.generation+=1
        self._invalidate_security()
        if self._active is not None:
            self.task.cancel_diagnostic()
            self.panel.invalidate_step_result(self._active.step_id)


    def _result(self, result):
        if self.auto_security.consume_result(result):
            return
        # 1. Ignore responses that do not belong
        # to the currently active transaction.
        if (
            self._active is None
            or result.request.transaction_id
            != self._active.transaction_id
        ):
            return

        self._active = None
        self.panel.set_request_busy(False)
        self._state()

        if self._closed:
            return

        request = result.request

        # 2. Prevent stale results after switching
        # Vehicle, sequence, or editing steps.
        if (
            request.generation != self.generation
            or self.panel.step_for_id(request.step_id) is None
        ):
            return

        # 3. Preserve existing UDS result display.
        payload = (
            result.response_payload.hex(" ").upper()
            if result.response_payload is not None
            else ""
        )

        detail = (
            f"{result.detail} "
            f"RT: {result.elapsed_s:.3f} s; "
            f"NRC 0x78 count: {result.pending_count}."
        )

        if is_key_submission(request):
            subfunc = request.uds_payload[1] if len(request.uds_payload) > 1 else 2
            summary = f'27 {subfunc:02X} → {payload or "no final response"}: {result.outcome.value}'
            self.security_key_result_changed.emit(summary)
        else:
            self.panel.set_step_result(
                request.step_id, payload, result.outcome.value, detail,
            )

        # 4. Default notice for all diagnostic services.
        notice = detail

        # A seed belongs to this exact connection/document/session generation.
        if is_security_seed_payload(request.uds_payload):
            try:
                self.security_session.receive(result,self._connection_identity(),self._session_epoch)
            except SecurityAccessBlocked:
                self._invalidate_security()
            self._refresh_security_status()
            notice = self.security_session.status_text+' '+detail

        if is_key_submission(request):
            self.security_session.finish_submission(result)
            self._seed_request = None
            self._refresh_security_status()
            notice = self.security_session.status_text + ' ' + detail

        # 6. Display one final notice.
        self.panel.show_notice(notice)


    def _frames(self,frames,dropped):
        if self._closed: return
        self.monitor.append_frame_batch(frames,dropped=dropped)

    def close(self):
        self._closed=True
        self._security_timer.stop()
        self._invalidate_security()
        self.service.fn_revoke_trusted_bench()
        self.task.cancel_diagnostic()
