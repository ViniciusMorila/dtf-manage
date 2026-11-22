"""Lazy, cached thumbnails for the art-stock list (a folder can hold hundreds of images).

request(path) returns immediately: the picture comes from the memory cache if it is there,
otherwise a small worker reads it scaled down (QImageReader decodes straight to the target size,
never the full image) and `ready(path)` is emitted on the interface thread. Nothing blocks the
window. Files that cannot be read are remembered in `failed` so they are not tried again.

Also here: the background job that looks for identical files (low priority, started after the
list is on screen)."""
from collections import OrderedDict

from PySide6.QtCore import QObject, QRunnable, QSize, QThread, QThreadPool, Qt, Signal
from PySide6.QtGui import QImage, QImageReader, QPixmap


class _Signals(QObject):
    loaded = Signal(str, QImage)
    failed = Signal(str)


class _LoadJob(QRunnable):
    def __init__(self, path: str, size: int, signals: _Signals):
        super().__init__()
        self.path, self.size, self.signals = path, size, signals

    def run(self) -> None:
        reader = QImageReader(self.path)
        reader.setAutoTransform(True)
        original = reader.size()
        if original.isValid() and (original.width() > self.size or original.height() > self.size):
            reader.setScaledSize(original.scaled(QSize(self.size, self.size),
                                                 Qt.AspectRatioMode.KeepAspectRatio))
        image = reader.read()
        if image.isNull():
            self.signals.failed.emit(self.path)
        else:
            self.signals.loaded.emit(self.path, image)


class ThumbnailCache(QObject):
    ready = Signal(str)                    # a thumbnail (or its failure) is now known

    def __init__(self, size: int = 44, capacity: int = 800, threads: int = 2, parent=None):
        super().__init__(parent)
        self.size, self.capacity = size, capacity
        self._pixmaps: OrderedDict[str, QPixmap] = OrderedDict()
        self._failed: set[str] = set()
        self._pending: set[str] = set()
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(threads)
        self._signals = _Signals(self)
        self._signals.loaded.connect(self._on_loaded)
        self._signals.failed.connect(self._on_failed)
        self.requests = 0                  # how many files were actually sent to the workers

    def pixmap(self, path: str) -> QPixmap | None:
        pixmap = self._pixmaps.get(path)
        if pixmap is not None:
            self._pixmaps.move_to_end(path)
        return pixmap

    def has_failed(self, path: str) -> bool:
        return path in self._failed

    def request(self, path: str) -> None:
        """Starts loading `path` unless it is cached, failed or already on its way."""
        if path in self._pixmaps or path in self._failed or path in self._pending:
            return
        self._pending.add(path)
        self.requests += 1
        self._pool.start(_LoadJob(path, self.size, self._signals))

    def wait(self) -> None:
        """Blocks until the workers are idle (tests and shutdown)."""
        self._pool.waitForDone()

    def _on_loaded(self, path: str, image: QImage) -> None:
        self._pending.discard(path)
        self._pixmaps[path] = QPixmap.fromImage(image)
        while len(self._pixmaps) > self.capacity:
            self._pixmaps.popitem(last=False)
        self.ready.emit(path)

    def _on_failed(self, path: str) -> None:
        self._pending.discard(path)
        self._failed.add(path)
        self.ready.emit(path)


class _IdenticalSignals(QObject):
    done = Signal(list)


class _IdenticalJob(QRunnable):
    def __init__(self, files, cached, save, signals):
        super().__init__()
        self.files, self.cached, self.save, self.signals = files, cached, save, signals

    def run(self) -> None:
        from dtf_manager.services.art_duplicates import find_identical
        QThread.currentThread().setPriority(QThread.Priority.LowestPriority)
        try:
            groups = find_identical(self.files, self.cached, self.save)
        except Exception:                  # a warning only: never worth an error on screen
            groups = []
        self.signals.done.emit(groups)


class IdenticalFilesScanner(QObject):
    """Looks for files with identical content in the background, at the lowest priority."""
    found = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._signals = _IdenticalSignals(self)
        self._signals.done.connect(self.found)

    def start(self, files, cached, save) -> None:
        self._pool.start(_IdenticalJob(list(files), dict(cached), save, self._signals), -1)

    def wait(self) -> None:
        self._pool.waitForDone()
