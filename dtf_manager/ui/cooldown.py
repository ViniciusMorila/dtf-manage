"""Countdown used to keep a button disabled during a server Retry-After."""
from PySide6.QtCore import QObject, QTimer, Signal


class Cooldown(QObject):
    ticked = Signal(int)     # seconds left
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._left = 0
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.tick)

    @property
    def active(self):
        return self._left > 0

    @property
    def left(self):
        return self._left

    def start(self, seconds):
        self._left = max(1, int(seconds))
        self._timer.start()
        self.ticked.emit(self._left)

    def stop(self):
        self._left = 0
        self._timer.stop()

    def tick(self):
        if self._left <= 0:
            return
        self._left -= 1
        if self._left <= 0:
            self._timer.stop()
            self.finished.emit()
        else:
            self.ticked.emit(self._left)
