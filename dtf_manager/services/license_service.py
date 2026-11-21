"""License validation and activation against the API (never decides locally)."""
from PySide6.QtCore import QObject, Signal

from dtf_manager.models.license import LicenseStatus
from dtf_manager.services.api_failure import ApiFailure


class LicenseService(QObject):
    checked = Signal(object)            # LicenseStatus (HTTP 200)
    failed = Signal(str)                # details in last_failure
    activated = Signal(object, str)     # LicenseStatus, plano_ativado
    activation_failed = Signal(str)

    def __init__(self, client, parent=None, *, machine_id=None):
        super().__init__(parent)
        self.client = client
        self._machine_id = machine_id
        self.last_failure = ApiFailure("server")
        self._generation = 0
        self._activation_generation = 0

    @property
    def machine_id(self):
        if callable(self._machine_id):
            return self._machine_id()
        if self._machine_id is None:
            from dtf_manager.services.machine_id import get_machine_id
            return get_machine_id()
        return self._machine_id

    def cancel(self):
        self._generation += 1
        self._activation_generation += 1

    def check(self, access_token):
        """GET /licencas/status with Bearer and X-Id-Maquina."""
        self._generation += 1
        generation = self._generation
        try:
            machine_id = self.machine_id
        except Exception:
            self.last_failure = ApiFailure("machine_id")
            self.failed.emit("machine_id")
            return

        def completed(result):
            if generation != self._generation:
                return
            if result.error or not 200 <= result.status < 300:
                self.last_failure = ApiFailure.from_result(result)
                self.failed.emit(self.last_failure.kind)
                return
            status = LicenseStatus.from_response(result.data)
            if status is None:
                self.last_failure = ApiFailure("invalid_json")
                self.failed.emit("invalid_json")
                return
            self.checked.emit(status)

        self.client.get("/licencas/status", completed, access_token=access_token,
                        headers={"X-Id-Maquina": machine_id})

    def activate_key(self, key, *, access_token=None, email=None, password=None):
        """POST /licencas/ativar-chave with a Bearer, or with e-mail and password."""
        self._activation_generation += 1
        generation = self._activation_generation
        try:
            machine_id = self.machine_id
        except Exception:
            self.last_failure = ApiFailure("machine_id")
            self.activation_failed.emit("machine_id")
            return
        body = {"chave": key, "id_maquina": machine_id}
        if not access_token:
            body.update({"email": email, "senha": password})

        def completed(result):
            if generation != self._activation_generation:
                return
            if result.error or not 200 <= result.status < 300:
                self.last_failure = ApiFailure.from_result(result)
                self.activation_failed.emit(self.last_failure.kind)
                return
            status = LicenseStatus.from_response(result.data)
            plan = (result.data or {}).get("plano_ativado")
            if status is None:
                self.last_failure = ApiFailure("invalid_json")
                self.activation_failed.emit("invalid_json")
                return
            self.activated.emit(status, plan if isinstance(plan, str) else status.info.plano)

        self.client.post_json("/licencas/ativar-chave", body, completed,
                              access_token=access_token or None)
