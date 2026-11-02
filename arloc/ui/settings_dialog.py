"""Impostazioni (⚙): servizio AI, chiave API, cartella risultati, formato Custom, modelli."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QGridLayout, QDialog, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QToolButton,
                               QVBoxLayout, QWidget)

from arloc.core.models import OutputPreset
from arloc.ui.common import friendly_error, install_placeholder_behavior, run_async


def _section(text: str) -> QLabel:
    l = QLabel(text)
    l.setObjectName("CardTitle")
    return l


class SettingsDialog(QDialog):
    _verified = Signal(bool, str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        install_placeholder_behavior()
        self.setWindowTitle("Impostazioni")
        self.setMinimumWidth(480)
        self._s = settings
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(12)

        # Servizio AI e chiave API
        lay.addWidget(_section("Servizio AI"))
        self.provider = QComboBox()
        self.provider.addItem("Anthropic (Claude)", "anthropic")
        self.provider.addItem("OpenRouter", "openrouter")
        cur = getattr(settings, "provider", "anthropic")
        self.provider.setCurrentIndex(1 if cur == "openrouter" else 0)
        lay.addWidget(self.provider)
        self.info = QLabel()
        self.info.setObjectName("Muted")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        row = QHBoxLayout()
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self._typed = {}  # chiavi scritte e non ancora salvate, per servizio
        self.key.textEdited.connect(lambda t: self._typed.__setitem__(self._prov(), t))
        self.btn_verify = QPushButton("Verifica")
        self.btn_verify.clicked.connect(self._verify)
        row.addWidget(self.key, 1)
        row.addWidget(self.btn_verify)
        lay.addLayout(row)
        self.lbl_verify = QLabel("")
        self.lbl_verify.setWordWrap(True)
        lay.addWidget(self.lbl_verify)
        self._verified.connect(self._show_verify)

        lay.addWidget(self._hline())
        lay.addWidget(_section("Cartella dei risultati"))
        row = QHBoxLayout()
        self.out = QLineEdit(getattr(settings, "output_dir", "") or "")
        self.out.setPlaceholderText("Ogni volta chiedi dove salvare")
        b = QPushButton("Scegli…")
        b.clicked.connect(self._pick_dir)
        row.addWidget(self.out, 1)
        row.addWidget(b)
        lay.addLayout(row)

        lay.addWidget(self._hline())
        lay.addWidget(_section("Formato Custom"))
        cp = getattr(settings, "custom_preset", None) or OutputPreset("custom", 1600, 1200)
        form = QGridLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(8)
        form.setColumnStretch(1, 1)
        self.cw, self.ch, self.cq = QSpinBox(), QSpinBox(), QSpinBox()
        for s, v, lo, hi, suf in ((self.cw, cp.larghezza, 100, 10000, " px"),
                                  (self.ch, cp.altezza, 100, 10000, " px"),
                                  (self.cq, cp.qualita, 40, 100, " %")):
            s.setRange(lo, hi)
            s.setValue(v)
            s.setSuffix(suf)
        self.cf = QComboBox()
        self.cf.addItems(["JPG", "PNG", "WEBP"])
        self.cf.setCurrentText(cp.formato.upper())
        # con il QSS gli spinbox/combo sottostimano l'altezza (e lo stile non è ancora applicato qui):
        # 34 px = min-height 20 + padding 2×6 + bordo 2×1, come in style.qss
        for w in (self.cw, self.ch, self.cq, self.cf):
            w.setFixedHeight(34)
        form.addWidget(QLabel("Larghezza"), 0, 0)
        form.addWidget(self.cw, 0, 1)
        form.addWidget(QLabel("Altezza"), 1, 0)
        form.addWidget(self.ch, 1, 1)
        form.addWidget(QLabel("Tipo di file"), 2, 0)
        form.addWidget(self.cf, 2, 1)
        form.addWidget(QLabel("Qualità"), 3, 0)
        form.addWidget(self.cq, 3, 1)
        lay.addLayout(form)

        lay.addWidget(self._hline())
        self.btn_adv = QToolButton()
        self.btn_adv.setObjectName("Disclosure")
        self.btn_adv.setText("Modelli avanzati")
        self.btn_adv.setCheckable(True)
        self.btn_adv.setArrowType(Qt.RightArrow)
        self.btn_adv.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        lay.addWidget(self.btn_adv)
        self.adv = QWidget()
        af = QFormLayout(self.adv)
        af.setContentsMargins(0, 0, 0, 0)
        af.setVerticalSpacing(8)
        af.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.m_instr = QLineEdit(getattr(settings, "model_instructions", ""))
        self.m_light = QLineEdit(getattr(settings, "model_light", ""))
        self.o_instr = QLineEdit(getattr(settings, "openrouter_model_instructions", ""))
        self.o_light = QLineEdit(getattr(settings, "openrouter_model_light", ""))
        af.addRow("Modello per le istruzioni", self.m_instr)
        af.addRow("Modello per la luce", self.m_light)
        af.addRow("Modello per le istruzioni", self.o_instr)
        af.addRow("Modello per la luce", self.o_light)
        self._af = af
        self.adv.hide()
        lay.addWidget(self.adv)
        self.btn_adv.toggled.connect(self._toggle_adv)
        self.provider.currentIndexChanged.connect(self._on_provider)
        self._on_provider()

        lay.addStretch(1)
        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("Annulla")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Salva")
        ok.setObjectName("Primary")
        ok.clicked.connect(self._accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)

    def _prov(self) -> str:
        return self.provider.currentData()

    def _on_provider(self, *_):
        p = self._prov()
        orr = p == "openrouter"
        self.info.setText(
            ("Serve per capire le istruzioni scritte a parole e per suggerire la luce. "
             "OpenRouter è un servizio a pagamento che dà accesso a molti modelli AI: "
             "crea la chiave su openrouter.ai. ") if orr else
            ("Serve solo per capire le istruzioni scritte a parole e per suggerire la luce. "))
        self.info.setText(self.info.text() + "Senza chiave Arloc funziona lo stesso, con i cursori.")
        self.key.blockSignals(True)
        self.key.setText(self._typed.get(p, ""))
        self.key.blockSignals(False)
        self.key.setPlaceholderText(
            "Chiave già salvata (scrivine una nuova per sostituirla)" if self._had_key(p)
            else "Incolla qui la chiave di OpenRouter" if orr else "Incolla qui la chiave di Claude")
        self.lbl_verify.setText("")
        for i, vis in enumerate((not orr, not orr, orr, orr)):
            self._af.setRowVisible(i, vis)
        self._fit_height()

    def _stored_key(self, p: str) -> str:
        try:
            from arloc.core import settings as st
            return (st.get_openrouter_key() if p == "openrouter" else st.get_api_key()) or ""
        except Exception:  # noqa: BLE001
            return ""

    def _had_key(self, p: str) -> bool:
        return bool(self._stored_key(p))

    def _hline(self):
        f = QFrame()
        f.setFrameShape(QFrame.HLine)
        f.setObjectName("Separator")
        return f

    def _toggle_adv(self, on):
        self.adv.setVisible(on)
        self.btn_adv.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        self._fit_height()

    def _fit_height(self):
        # adjustSize() limita a 2/3 dello schermo e comprime i campi: usa l'altezza necessaria
        self.layout().activate()
        h = self.layout().totalSizeHint().height()
        scr = self.screen().availableGeometry().height() if self.screen() else h
        self.resize(self.width(), min(h, scr - 40))

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Cartella dei risultati", self.out.text())
        if d:
            self.out.setText(d)

    def _current_key(self):
        p = self._prov()
        if p in self._typed:
            return self._typed[p].strip()
        return self._stored_key(p)

    def _verify(self):
        key = self._current_key()
        prov = self._prov()
        if not key:
            self._show_verify(False, "Inserisci prima la chiave.")
            return
        self.btn_verify.setEnabled(False)
        self.lbl_verify.setText("Controllo in corso…")
        self.lbl_verify.setProperty("state", "")

        def work():
            from arloc.core.instructions import verify_api_key
            return verify_api_key(key, prov)

        run_async(work, lambda r: self._verified.emit(bool(r[0]), str(r[1])),
                  lambda e: self._verified.emit(False, friendly_error(e)))

    def _show_verify(self, ok: bool, msg: str):
        self.btn_verify.setEnabled(True)
        self.lbl_verify.setText(("✓ " if ok else "") + msg)
        self.lbl_verify.setProperty("state", "ok" if ok else "todo")
        self.lbl_verify.style().unpolish(self.lbl_verify)
        self.lbl_verify.style().polish(self.lbl_verify)

    def _accept(self):
        s = self._s
        try:
            if s is not None:
                s.output_dir = self.out.text().strip()
                s.custom_preset = OutputPreset("custom", self.cw.value(), self.ch.value(),
                                               self.cf.currentText().lower(), self.cq.value())
                s.provider = self._prov()
                for attr, w in (("openrouter_model_instructions", self.o_instr),
                                ("openrouter_model_light", self.o_light)):
                    if w.text().strip():
                        setattr(s, attr, w.text().strip())
                if self.m_instr.text().strip():
                    s.model_instructions = self.m_instr.text().strip()
                if self.m_light.text().strip():
                    s.model_light = self.m_light.text().strip()
                from arloc.core.settings import (save_settings, set_api_key, set_openrouter_key)
                save_settings(s)
                for prov, setter in (("anthropic", set_api_key), ("openrouter", set_openrouter_key)):
                    if prov in self._typed:
                        setter(self._typed[prov].strip() or None)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Impostazioni", "Non sono riuscito a salvare le impostazioni.\n"
                                + friendly_error(e))
            return
        self.accept()
