"""Scheda Batch: tabella di lavori da file CSV/XLSX."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMessageBox, QProgressBar, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget, QAbstractItemView)

from arloc.core.models import ArlocError
from arloc.ui.common import friendly_error, run_async

STATUS_TEXT = {"in attesa": "○  In attesa", "ok": "✓  Fatta", "errore": "✕  Errore",
               "saltata": "–  Saltata"}
STATUS_COLOR = {"in attesa": "#7A746B", "ok": "#1F7A6D", "errore": "#B3382C", "saltata": "#7A746B"}


class DropZone(QFrame):
    fileDropped = Signal(str)
    browse = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(8)
        lay.setAlignment(Qt.AlignCenter)
        self.title = QLabel("Trascina qui il file con l'elenco dei lavori")
        self.title.setObjectName("DropTitle")
        self.title.setAlignment(Qt.AlignCenter)
        sub = QLabel("File CSV o Excel (.xlsx). Non ne hai uno? Scarica il modello e compilalo.")
        sub.setObjectName("Muted")
        sub.setAlignment(Qt.AlignCenter)
        self.btn = QPushButton("Scegli file…")
        self.btn.clicked.connect(self.browse)
        self.btn_tpl = QPushButton("Scarica modello")
        self.btn_tpl.setProperty("flat", True)
        row = QHBoxLayout()
        row.setAlignment(Qt.AlignCenter)
        row.addWidget(self.btn)
        row.addWidget(self.btn_tpl)
        lay.addWidget(self.title)
        lay.addWidget(sub)
        lay.addLayout(row)

    def _hl(self, on):
        self.setProperty("hover", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._hl(True)

    def dragLeaveEvent(self, e):
        self._hl(False)

    def dropEvent(self, e):
        self._hl(False)
        urls = e.mimeData().urls()
        if urls:
            self.fileDropped.emit(urls[0].toLocalFile())


class BatchView(QWidget):
    _progress = Signal(int, int)

    def __init__(self, settings=None, preset_getter=None, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._preset_getter = preset_getter
        self._qs = QSettings("Arloc", "Arloc")
        self._rows = []
        self._stop = False
        self._running = False
        self._report: Path | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(16)

        self.drop = DropZone()
        self.drop.fileDropped.connect(self.load_file)
        self.drop.browse.connect(self._browse)
        self.drop.btn_tpl.clicked.connect(self._template)
        lay.addWidget(self.drop)

        self.lbl_file = QLabel("")
        self.lbl_file.setObjectName("Muted")
        lay.addWidget(self.lbl_file)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Riga", "Sfondo", "Mosaico", "Stato"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        h.setSectionResizeMode(2, QHeaderView.Stretch)
        h.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        lay.addWidget(self.table, 1)

        out = QHBoxLayout()
        out.setSpacing(8)
        l = QLabel("Cartella risultati")
        self.out = QLineEdit(getattr(settings, "output_dir", "") or str(Path.home() / "Arloc risultati"))
        b = QPushButton("Scegli…")
        b.clicked.connect(self._pick_out)
        out.addWidget(l)
        out.addWidget(self.out, 1)
        out.addWidget(b)
        lay.addLayout(out)

        self.bar = QProgressBar()
        self.bar.setTextVisible(True)
        self.bar.setFormat("%v di %m")
        self.bar.setFixedHeight(12)
        self.bar.hide()
        lay.addWidget(self.bar)
        self.lbl_state = QLabel("")
        lay.addWidget(self.lbl_state)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        self.btn_start = QPushButton("Avvia")
        self.btn_start.setObjectName("Primary")
        self.btn_start.setMinimumHeight(40)
        self.btn_start.setEnabled(False)
        self.btn_start.clicked.connect(self.start)
        self.btn_stop = QPushButton("Interrompi")
        self.btn_stop.setMinimumHeight(40)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_clicked)
        self.btn_open = QPushButton("Apri cartella risultati")
        self.btn_open.setMinimumHeight(40)
        self.btn_open.clicked.connect(self._open_out)
        btns.addWidget(self.btn_start)
        btns.addWidget(self.btn_stop)
        btns.addStretch(1)
        btns.addWidget(self.btn_open)
        lay.addLayout(btns)
        self._progress.connect(self._on_progress)

    def set_settings(self, s):
        self._settings = s

    # ---- file
    def _start_dir(self) -> str:
        return str(self._qs.value("last_dir_batch", str(Path.home())))

    def _browse(self):
        p, _ = QFileDialog.getOpenFileName(self, "Scegli il file dei lavori", self._start_dir(),
                                           "Elenco lavori (*.csv *.xlsx *.xls)")
        if p:
            self.load_file(p)

    def _template(self):
        p, _ = QFileDialog.getSaveFileName(self, "Salva il modello", str(Path(self._start_dir()) /
                                           "modello_batch.xlsx"), "Excel (*.xlsx);;CSV (*.csv)")
        if not p:
            return
        try:
            from arloc.core.batch import write_template
            write_template(p)
            self.lbl_state.setText(f"Modello salvato: {p}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Modello", friendly_error(e))

    def load_file(self, path: str):
        p = Path(path)
        if p.suffix.lower() not in (".csv", ".xlsx", ".xls"):
            QMessageBox.information(self, "File non valido",
                                    "Scegli un file CSV o Excel (.xlsx) con l'elenco dei lavori.")
            return
        self._qs.setValue("last_dir_batch", str(p.parent))
        try:
            from arloc.core.batch import read_batch
            preset = self._preset_getter() if self._preset_getter else None
            self._rows = read_batch(p, preset)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Non riesco a leggere il file", friendly_error(e))
            return
        self.lbl_file.setText(f"{p.name}: {len(self._rows)} lavori")
        self._fill()
        self.btn_start.setEnabled(bool(self._rows))
        self.bar.hide()
        self.lbl_state.setText("")

    def _fill(self):
        self.table.setRowCount(len(self._rows))
        for i, r in enumerate(self._rows):
            raw = r.raw or {}
            bg = r.job.sfondo.name if r.job else str(self._pick(raw, "sfondo"))
            mo = r.job.mosaico.name if r.job else str(self._pick(raw, "mosaico"))
            vals = [str(r.index), bg, mo, STATUS_TEXT.get(r.status, r.status)]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c == 3:
                    it.setForeground(QColor(STATUS_COLOR.get(r.status, "#000")))
                    if r.error:
                        it.setText(f"{v}: {r.error}")
                        it.setToolTip(r.error)
                self.table.setItem(i, c, it)

    @staticmethod
    def _pick(raw: dict, key: str):
        for k, v in raw.items():
            if key in str(k).lower():
                return v
        return ""

    # ---- esecuzione
    def _pick_out(self):
        d = QFileDialog.getExistingDirectory(self, "Cartella dei risultati", self.out.text())
        if d:
            self.out.setText(d)

    def _use_claude(self) -> bool:
        try:
            from arloc.core.settings import get_api_key
            return bool(get_api_key())
        except Exception:  # noqa: BLE001
            return False

    def start(self):
        if self._running or not self._rows:
            return
        out = self.out.text().strip()
        if not out:
            QMessageBox.information(self, "Cartella risultati", "Scegli dove salvare le immagini.")
            return
        for r in self._rows:
            if r.status != "saltata":
                r.status = "in attesa" if r.job else r.status
        self._running, self._stop = True, False
        self._set_running(True)
        self.bar.setRange(0, len(self._rows))
        self.bar.setValue(0)
        self.bar.show()
        self.lbl_state.setText("Sto creando le immagini…")
        rows, use_claude = self._rows, self._use_claude()

        def work():
            from arloc.core.batch import run_batch
            Path(out).mkdir(parents=True, exist_ok=True)
            return run_batch(rows, out, progress=lambda i, t, r: self._progress.emit(i, t),
                             should_stop=lambda: self._stop, use_claude=use_claude)

        run_async(work, self._finished, self._failed)

    def _on_progress(self, i, total):
        self.bar.setMaximum(max(1, total))
        self.bar.setValue(min(i, total))
        self._fill()

    def _stop_clicked(self):
        self._stop = True
        self.btn_stop.setEnabled(False)
        self.lbl_state.setText("Mi fermo alla fine dell'immagine in corso…")

    def _finished(self, report):
        self._report = Path(report) if report else None
        self._running = False
        self._set_running(False)
        self._fill()
        ok = sum(1 for r in self._rows if r.status == "ok")
        bad = sum(1 for r in self._rows if r.status == "errore")
        txt = f"Finito: {ok} immagini create"
        if bad:
            txt += f", {bad} con problemi (passa il mouse sulla riga per i dettagli)"
        if self._stop:
            txt = "Interrotto. " + txt
        self.lbl_state.setText(txt + ".")
        self.bar.setValue(self.bar.maximum())

    def _failed(self, exc):
        self._running = False
        self._set_running(False)
        self._fill()
        self.lbl_state.setText("")
        QMessageBox.warning(self, "Batch interrotto", friendly_error(exc))

    def _set_running(self, on):
        self.btn_start.setEnabled(not on)
        self.btn_stop.setEnabled(on)
        self.drop.setEnabled(not on)

    def _open_out(self):
        d = Path(self.out.text().strip())
        if d.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))
        else:
            QMessageBox.information(self, "Cartella risultati",
                                    "La cartella non esiste ancora: verrà creata al primo avvio.")
