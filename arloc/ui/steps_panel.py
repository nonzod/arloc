"""Pannello sinistro: i quattro passi numerati."""
from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout,
                               QLabel, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QSlider,
                               QSpinBox, QToolButton, QVBoxLayout, QWidget)

from arloc.core.models import ComposeParams, OutputPreset

PANEL_WIDTH = 340

LABELS = {
    "rotazione_gradi": ("Rotazione", "°", 0),
    "offset_x_cm": ("Spostamento a destra", " cm", 1),
    "offset_y_cm": ("Spostamento in basso", " cm", 1),
    "ombra_direzione_gradi": ("Direzione dell'ombra", "°", 0),
    "ombra_distanza_cm": ("Distanza dell'ombra", " cm", 1),
    "ombra_morbidezza": ("Morbidezza dell'ombra", "", 2),
    "ombra_opacita": ("Intensità dell'ombra", "", 2),
    "spessore_mm": ("Spessore del mosaico", " mm", 1),
    "luminosita": ("Luminosità", "", 2),
    "temperatura": ("Temperatura colore (freddo / caldo)", "", 2),
    "armonizzazione": ("Armonizzazione con lo sfondo", "", 2),
    "grana": ("Grana fotografica", "", 2),
}

_FALLBACK_PRESETS = {
    "shopify": OutputPreset("shopify", 2048, 2048, "jpg", 90),
    "etsy": OutputPreset("etsy", 2700, 2025, "jpg", 90),
}


class Card(QFrame):
    def __init__(self, number: int, title: str, optional: bool = False):
        super().__init__()
        self.setObjectName("Card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 16)
        lay.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(8)
        self.badge = QLabel(str(number))
        self.badge.setObjectName("Badge")
        self.badge.setFixedSize(24, 24)
        self.badge.setAlignment(Qt.AlignCenter)
        t = QLabel(title)
        t.setObjectName("CardTitle")
        head.addWidget(self.badge)
        head.addWidget(t)
        if optional:
            o = QLabel("facoltativo")
            o.setObjectName("Muted")
            head.addWidget(o)
        head.addStretch(1)
        lay.addLayout(head)
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        lay.addLayout(self.body)

    def set_done(self, done: bool):
        self.badge.setText("✓" if done else self.badge.property("num"))
        self.badge.setProperty("done", done)
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)


def _number_card(n, title, optional=False):
    c = Card(n, title, optional)
    c.badge.setProperty("num", str(n))
    return c


class FocusOutText(QPlainTextEdit):
    focusLost = Signal()

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.focusLost.emit()


def _spin(maximum=1000.0) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setDecimals(1)
    s.setRange(0, maximum)
    s.setSingleStep(1)
    s.setSuffix(" cm")
    s.setSpecialValueText("– cm")  # corto: i campi Misure sono stretti; cosa manca lo dice il testo sopra GENERA
    s.setAlignment(Qt.AlignRight)
    s.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
    s.setMinimumWidth(56)
    return s


def _row(label: str, *widgets) -> QHBoxLayout:
    r = QHBoxLayout()
    r.setSpacing(8)
    l = QLabel(label)
    l.setFixedWidth(104)
    r.addWidget(l)
    for w in widgets:
        r.addWidget(w, 1)
    return r


class StepsPanel(QWidget):
    chooseBackground = Signal()
    chooseMosaic = Signal()
    sizesChanged = Signal()
    paramsChanged = Signal()           # dall'utente (cursori)
    instructionsCommitted = Signal(str)
    suggestLight = Signal()
    presetChanged = Signal()
    generate = Signal()
    save = Signal()

    def __init__(self, custom_preset: OutputPreset | None = None, parent=None):
        super().__init__(parent)
        self.setFixedWidth(PANEL_WIDTH)
        self.setObjectName("StepsPanel")
        self._qs = QSettings("Arloc", "Arloc")
        self._defaults = ComposeParams()
        self._sliders: dict[str, tuple[QSlider, QLabel]] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName("ScrollInner")
        col = QVBoxLayout(inner)
        col.setContentsMargins(16, 16, 16, 16)
        col.setSpacing(12)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        # ① Sfondo
        self.c1 = _number_card(1, "Sfondo")
        self.btn_bg = QPushButton("Scegli immagine…")
        self.btn_bg.clicked.connect(self.chooseBackground)
        self.lbl_bg_file = QLabel("Nessuna immagine scelta")
        self.lbl_bg_file.setObjectName("Muted")
        self.lbl_area = QLabel("")
        self.lbl_area.setWordWrap(True)
        self.sp_bg_w = _spin()
        self.sp_bg_w.valueChanged.connect(self._sizes)
        self.c1.body.addWidget(self.btn_bg)
        self.c1.body.addWidget(self.lbl_bg_file)
        self.c1.body.addWidget(self.lbl_area)
        self.c1.body.addLayout(_row("Larghezza reale", self.sp_bg_w))
        col.addWidget(self.c1)

        # ② Mosaico
        self.c2 = _number_card(2, "Mosaico")
        self.btn_mo = QPushButton("Scegli immagine…")
        self.btn_mo.clicked.connect(self.chooseMosaic)
        self.lbl_mo_file = QLabel("Nessuna immagine scelta")
        self.lbl_mo_file.setObjectName("Muted")
        self.sp_mo_w = _spin()
        self.sp_mo_h = _spin()
        for s in (self.sp_mo_w, self.sp_mo_h):
            s.valueChanged.connect(self._sizes)
        x = QLabel("×")
        x.setAlignment(Qt.AlignCenter)
        dims = QHBoxLayout()
        dims.setSpacing(8)
        l = QLabel("Misure")
        l.setFixedWidth(104)
        dims.addWidget(l)
        dims.addWidget(self.sp_mo_w, 1)
        dims.addWidget(x)
        dims.addWidget(self.sp_mo_h, 1)
        self.lbl_mo_hint = QLabel("larghezza × altezza")
        self.lbl_mo_hint.setObjectName("Muted")
        self.c2.body.addWidget(self.btn_mo)
        self.c2.body.addWidget(self.lbl_mo_file)
        self.c2.body.addLayout(dims)
        self.c2.body.addWidget(self.lbl_mo_hint)
        col.addWidget(self.c2)

        # ③ Istruzioni
        self.c3 = _number_card(3, "Istruzioni", optional=True)
        self.txt = FocusOutText()
        self.txt.setPlaceholderText("Ad esempio: ombra morbida verso destra, luce più calda")
        self.txt.setFixedHeight(72)
        self.txt.focusLost.connect(self._commit_text)
        self.txt.textChanged.connect(self._text_changed)
        self.c3.body.addWidget(self.txt)
        self.btn_adv = QToolButton()
        self.btn_adv.setObjectName("Disclosure")
        self.btn_adv.setText("Regolazioni avanzate")
        self.btn_adv.setCheckable(True)
        self.btn_adv.setArrowType(Qt.RightArrow)
        self.btn_adv.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn_adv.toggled.connect(self._toggle_adv)
        self.c3.body.addWidget(self.btn_adv)
        self.adv = QWidget()
        al = QVBoxLayout(self.adv)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(8)
        for name, (lo, hi) in ComposeParams.RANGES.items():
            al.addLayout(self._make_slider(name, lo, hi))
        self.btn_light = QPushButton("Suggerisci luce dallo sfondo")
        self.btn_light.clicked.connect(self.suggestLight)
        self.btn_reset_params = QPushButton("Azzera regolazioni")
        self.btn_reset_params.setProperty("flat", True)
        self.btn_reset_params.clicked.connect(self._reset_params)
        al.addWidget(self.btn_light)
        al.addWidget(self.btn_reset_params)
        self.adv.hide()
        self.c3.body.addWidget(self.adv)
        col.addWidget(self.c3)

        # ④ Formato
        self.c4 = _number_card(4, "Formato")
        row = QHBoxLayout()
        row.setSpacing(8)
        self.grp = QButtonGroup(self)
        self.grp.setExclusive(True)
        self.preset_btns: dict[str, QPushButton] = {}
        for key, text in (("shopify", "Shopify"), ("etsy", "Etsy"), ("custom", "Custom")):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setProperty("segment", True)
            self.grp.addButton(b)
            self.preset_btns[key] = b
            row.addWidget(b)
        self.c4.body.addLayout(row)
        self.lbl_preset = QLabel("")
        self.lbl_preset.setObjectName("Muted")
        self.c4.body.addWidget(self.lbl_preset)
        self.custom_box = QWidget()
        cl = QVBoxLayout(self.custom_box)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(8)
        cp = custom_preset or OutputPreset("custom", 1600, 1200, "jpg", 90)
        self.sp_cw, self.sp_ch = QSpinBox(), QSpinBox()
        for s, v in ((self.sp_cw, cp.larghezza), (self.sp_ch, cp.altezza)):
            s.setRange(100, 10000)
            s.setValue(v)
            s.setSuffix(" px")
            s.setAlignment(Qt.AlignRight)
            s.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            s.valueChanged.connect(self._preset_changed)
        self.cb_fmt = QComboBox()
        self.cb_fmt.addItems(["JPG", "PNG", "WEBP"])
        self.cb_fmt.setCurrentText(cp.formato.upper())
        self.cb_fmt.currentIndexChanged.connect(self._preset_changed)
        cl.addLayout(_row("Larghezza", self.sp_cw))
        cl.addLayout(_row("Altezza", self.sp_ch))
        cl.addLayout(_row("Tipo di file", self.cb_fmt))
        self._custom_quality = cp.qualita
        self.custom_box.hide()
        self.c4.body.addWidget(self.custom_box)
        col.addWidget(self.c4)
        col.addStretch(1)
        for b in self.grp.buttons():
            b.toggled.connect(lambda on: on and self._preset_changed())

        # Piede fisso: GENERA / Salva
        foot = QFrame()
        foot.setObjectName("Footer")
        fl = QVBoxLayout(foot)
        fl.setContentsMargins(16, 12, 16, 16)
        fl.setSpacing(8)
        self.lbl_missing = QLabel("")
        self.lbl_missing.setObjectName("Missing")
        self.lbl_missing.setWordWrap(True)
        self.lbl_missing.setAlignment(Qt.AlignCenter)
        self.btn_gen = QPushButton("GENERA")
        self.btn_gen.setObjectName("Primary")
        self.btn_gen.setMinimumHeight(44)
        self.btn_gen.clicked.connect(self.generate)
        self.btn_save = QPushButton("Salva immagine…")
        self.btn_save.setMinimumHeight(36)
        self.btn_save.clicked.connect(self.save)
        self.btn_save.setEnabled(False)
        fl.addWidget(self.lbl_missing)
        fl.addWidget(self.btn_gen)
        fl.addWidget(self.btn_save)
        outer.addWidget(foot)

        self._last_text = ""
        self.set_params(ComposeParams())
        last = str(self._qs.value("preset", "shopify"))
        self.preset_btns.get(last, self.preset_btns["shopify"]).setChecked(True)
        self.update_checks()

    # ---- sliders
    def _make_slider(self, name, lo, hi):
        label, unit, dec = LABELS.get(name, (name, "", 2))
        lay = QVBoxLayout()
        lay.setSpacing(2)
        top = QHBoxLayout()
        l = QLabel(label)
        v = QLabel("")
        v.setObjectName("Muted")
        v.setAlignment(Qt.AlignRight)
        top.addWidget(l, 1)
        top.addWidget(v)
        s = QSlider(Qt.Horizontal)
        s.setRange(0, 1000)
        s.valueChanged.connect(lambda _=0, n=name: self._slider_moved(n))
        s.setProperty("unit", unit)
        s.setProperty("dec", dec)
        lay.addLayout(top)
        lay.addWidget(s)
        self._sliders[name] = (s, v)
        return lay

    def _slider_value(self, name) -> float:
        lo, hi = ComposeParams.RANGES[name]
        s, _ = self._sliders[name]
        return lo + (hi - lo) * s.value() / 1000.0

    def _show_value(self, name):
        s, v = self._sliders[name]
        val = self._slider_value(name)
        dec = s.property("dec")
        v.setText(f"{val:.{dec}f}".replace(".", ",") + s.property("unit"))

    def _slider_moved(self, name):
        self._show_value(name)
        self.paramsChanged.emit()

    def params(self) -> ComposeParams:
        return ComposeParams(**{n: self._slider_value(n) for n in self._sliders}).clamped()

    def set_params(self, p: ComposeParams):
        d = p.to_dict()
        for n, (s, _) in self._sliders.items():
            lo, hi = ComposeParams.RANGES[n]
            s.blockSignals(True)
            s.setValue(round((d[n] - lo) / (hi - lo) * 1000))
            s.blockSignals(False)
            self._show_value(n)

    def _reset_params(self):
        self.set_params(self._defaults)
        self.paramsChanged.emit()

    def _toggle_adv(self, on):
        self.adv.setVisible(on)
        self.btn_adv.setArrowType(Qt.DownArrow if on else Qt.RightArrow)

    # ---- testo
    def instructions(self) -> str:
        return self.txt.toPlainText().strip()

    def _text_changed(self):
        self.update_checks()

    def _commit_text(self):
        t = self.instructions()
        if t and t != self._last_text:
            self._last_text = t
            self.instructionsCommitted.emit(t)

    def mark_text_parsed(self, text: str):
        self._last_text = text

    # ---- formato
    def _preset_changed(self, *_):
        key = self.preset_key()
        self.custom_box.setVisible(key == "custom")
        p = self.preset()
        if key:
            self._qs.setValue("preset", key)
        self.lbl_preset.setText(
            f"{p.larghezza} × {p.altezza} px, {p.formato.upper()}" if key != "custom" else "")
        self.update_checks()
        self.presetChanged.emit()

    def preset_key(self) -> str | None:
        for k, b in self.preset_btns.items():
            if b.isChecked():
                return k
        return None

    def preset(self) -> OutputPreset:
        key = self.preset_key() or "shopify"
        if key == "custom":
            return OutputPreset("custom", self.sp_cw.value(), self.sp_ch.value(),
                                self.cb_fmt.currentText().lower(), self._custom_quality)
        try:
            from arloc.core import presets
            return presets.SHOPIFY if key == "shopify" else presets.ETSY
        except Exception:  # noqa: BLE001
            return _FALLBACK_PRESETS[key]

    def set_custom_preset(self, cp: OutputPreset):
        self.sp_cw.setValue(cp.larghezza)
        self.sp_ch.setValue(cp.altezza)
        self.cb_fmt.setCurrentText(cp.formato.upper())
        self._custom_quality = cp.qualita

    # ---- stato
    def _sizes(self, *_):
        self.update_checks()
        self.sizesChanged.emit()

    def bg_width_cm(self): return self.sp_bg_w.value()
    def mosaic_size_cm(self): return self.sp_mo_w.value(), self.sp_mo_h.value()

    def set_bg_file(self, name: str | None):
        self.lbl_bg_file.setText(name or "Nessuna immagine scelta")
        self.btn_bg.setText("Cambia immagine…" if name else "Scegli immagine…")
        self.update_checks()

    def set_mosaic_file(self, name: str | None):
        self.lbl_mo_file.setText(name or "Nessuna immagine scelta")
        self.btn_mo.setText("Cambia immagine…" if name else "Scegli immagine…")
        self.update_checks()

    def set_area_status(self, text: str, state: str):
        """state: ok | todo | '' """
        self.lbl_area.setText(text)
        self.lbl_area.setProperty("state", state)
        self.lbl_area.style().unpolish(self.lbl_area)
        self.lbl_area.style().polish(self.lbl_area)

    def set_flags(self, has_bg: bool, has_area: bool, has_mosaic: bool):
        self._has_bg, self._has_area, self._has_mo = has_bg, has_area, has_mosaic
        self.update_checks()

    _has_bg = _has_area = _has_mo = False

    def missing(self) -> list[str]:
        m = []
        if not self._has_bg:
            m.append("l'immagine di sfondo")
        elif not self._has_area:
            m.append("l'area dello sfondo (clicca i 4 angoli)")
        if self.sp_bg_w.value() <= 0:
            m.append("la larghezza dello sfondo")
        if not self._has_mo:
            m.append("l'immagine del mosaico")
        if self.sp_mo_w.value() <= 0 or self.sp_mo_h.value() <= 0:
            m.append("le misure del mosaico")
        if self.preset_key() is None:
            m.append("il formato")
        return m

    def update_checks(self):
        self.c1.set_done(self._has_bg and self._has_area and self.sp_bg_w.value() > 0)
        self.c2.set_done(self._has_mo and self.sp_mo_w.value() > 0 and self.sp_mo_h.value() > 0)
        self.c3.set_done(bool(self.instructions()))
        self.c4.set_done(self.preset_key() is not None)
        m = self.missing()
        self.lbl_missing.setText("Per generare manca: " + ", ".join(m) + "." if m else "")
        self.lbl_missing.setVisible(bool(m))
        self.btn_gen.setEnabled(not m and not getattr(self, "_busy", False))

    def set_busy(self, busy: bool):
        self._busy = busy
        self.btn_gen.setText("Sto lavorando…" if busy else "GENERA")
        self.update_checks()

    def set_can_save(self, ok: bool):
        self.btn_save.setEnabled(ok)
