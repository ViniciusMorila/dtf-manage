"""In-memory test doubles. Never access the user's credential store."""
from dtf_manager.services.session_storage import SessionStorageError


class FakeSessionStorage:
    def __init__(self, token=None):
        self.token = token
        self.saved = []
        self.deletions = 0
        self.fail_save = False
        self.fail_load = False
        self.fail_delete = False
        self.lock_available = True
        self.lock_released = False

    def acquire_session_lock(self):
        return self.lock_available

    def release_session_lock(self):
        self.lock_released = True

    def load_refresh_token(self):
        if self.fail_load:
            raise SessionStorageError("Fake storage read error")
        return self.token

    def save_refresh_token(self, token):
        if self.fail_save:
            raise SessionStorageError("Fake storage write error")
        self.token = token
        self.saved.append(token)

    def delete_refresh_token(self):
        if self.fail_delete:
            raise SessionStorageError("Fake storage delete error")
        self.token = None
        self.deletions += 1
