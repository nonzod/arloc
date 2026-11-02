"""Utilità condivise dalla UI: conversioni immagine, lavori in background, errori."""
from __future__ import annotations

import logging
import traceback
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEvent, QObject, QRunnable, QThreadPool, QTimer, Signal, Slot
from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QLineEdit, QPlainTextEdit, QTextEdit
from PySide6.QtGui import QImage, QPixmap

from arloc.core.models import ArlocError

log = logging.getLogger("arloc.ui")

_alive: set = set()


def to_qimage(img: np.ndarray) -> QImage:
    """BGR/BGRA uint8 (numpy) -> QImage (copia indipendente)."""
    img = np.ascontiguousarray(img)
    h, w = img.shape[:2]
    if img.ndim == 2:
        q = QImage(img.data, w, h, w, QImage.Format_Grayscale8)
    elif img.shape[2] == 4:
        q = QImage(img.data, w, h, w * 4, QImage.Format_ARGB32)
        # BGRA in memoria == ARGB32 little endian
    else:
        q = QImage(img.data, w, h, w * 3, QImage.Format_BGR888)
    return q.copy()


def to_pixmap(img: np.ndarray) -> QPixmap:
    return QPixmap.fromImage(to_qimage(img))


def friendly_error(exc: BaseException) -> str:
    if isinstance(exc, ArlocError):
        return str(exc)
    log.error("Errore inatteso: %s", "".join(traceback.format_exception(exc)))
    return ("Qualcosa non ha funzionato. Controlla le immagini e i dati inseriti e riprova. "
            "Se il problema continua, riavvia Arloc.")


class _Task(QObject, QRunnable):
    done = Signal(object)
    failed = Signal(object)

    def __init__(self, fn, on_done, on_fail):
        QObject.__init__(self)
        QRunnable.__init__(self)
        self.setAutoDelete(False)
        self._fn, self._on_done, self._on_fail = fn, on_done, on_fail
        self.done.connect(self._finish_ok)
        self.failed.connect(self._finish_ko)

    def run(self):
        try:
            res = self._fn()
        except BaseException as e:  # noqa: BLE001
            self.failed.emit(e)
        else:
            self.done.emit(res)

    @Slot(object)
    def _finish_ok(self, res):
        _alive.discard(self)
        if self._on_done:
            self._on_done(res)

    @Slot(object)
    def _finish_ko(self, exc):
        _alive.discard(self)
        if self._on_fail:
            self._on_fail(exc)
        else:
            log.error("Lavoro fallito: %s", exc)


def run_async(fn, on_done=None, on_fail=None) -> None:
    """Esegue fn() in un thread; i callback girano nel thread della UI."""
    t = _Task(fn, on_done, on_fail)
    _alive.add(t)
    QThreadPool.globalInstance().start(t)


def load_app_settings():
    try:
        from arloc.core.settings import load_settings
        return load_settings()
    except Exception:  # noqa: BLE001
        return None


def style_path() -> Path:
    return Path(__file__).with_name("style.qss")


class _PlaceholderFilter(QObject):
    """Nasconde il segnaposto quando il campo prende il focus e lo rimette se resta vuoto."""

    _KEY = "_arloc_ph"

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.FocusIn:
            self._hide(obj)
        elif t == QEvent.FocusOut:
            self._show(obj)
        return False

    @staticmethod
    def _owner(obj):
        # il campo interno di uno spinbox appartiene allo spinbox
        p = obj.parent()
        if isinstance(obj, QLineEdit) and isinstance(p, QAbstractSpinBox):
            return p
        return obj

    def _hide(self, obj):
        w = self._owner(obj)
        if isinstance(w, QAbstractSpinBox):
            empty = bool(w.specialValueText()) and w.value() == w.minimum()
            if empty:
                w.setProperty(self._KEY, w.specialValueText())
                w.setSpecialValueText("")
            # rimandato: il click del mouse arriva dopo il FocusIn e sposterebbe il cursore.
            # Campo "vuoto" → niente "0,0" da cancellare; valore presente → selezionato, si sovrascrive.
            QTimer.singleShot(0, (lambda: w.lineEdit().setText("")) if empty else w.selectAll)
        elif isinstance(w, (QLineEdit, QPlainTextEdit, QTextEdit)) and w.placeholderText():
            w.setProperty(self._KEY, w.placeholderText())
            w.setPlaceholderText("")

    def _show(self, obj):
        w = self._owner(obj)
        saved = w.property(self._KEY)
        if not saved:
            return
        w.setProperty(self._KEY, None)
        if isinstance(w, QAbstractSpinBox):
            w.setSpecialValueText(saved)
        else:
            w.setPlaceholderText(saved)


_ph_filter: _PlaceholderFilter | None = None


def install_placeholder_behavior() -> None:
    """Attiva (una sola volta) la scomparsa dei segnaposto al focus su tutti i campi dell'app."""
    global _ph_filter
    app = QApplication.instance()
    if app is not None and _ph_filter is None:
        _ph_filter = _PlaceholderFilter(app)
        app.installEventFilter(_ph_filter)
