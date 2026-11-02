"""Finestra principale: schede Singola e Batch."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer, Signal
import numpy as np
from PySide6.QtWidgets import (QButtonGroup, QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QMainWindow, QMessageBox, QPushButton, QSlider, QStackedWidget,
                               QVBoxLayout, QWidget)

from arloc.core.models import ArlocError, ComposeResult, Job, Quad
from arloc.ui.batch_view import BatchView
from arloc.ui.canvas import Canvas
from arloc.ui.common import friendly_error, install_placeholder_behavior, load_app_settings, run_async
from arloc.ui.settings_dialog import SettingsDialog
from arloc.ui.steps_panel import StepsPanel

IMG_FILTER = "Immagini (*.jpg *.jpeg *.png *.webp);;Tutti i file (*)"
PREVIEW_MAX = 1200
MASK_MAX = 1400   # lato lungo della maschera di scontorno tenuta in memoria dalla UI
BRUSH_MIN, BRUSH_MAX = 0.01, 0.15   # diametro del pennello / larghezza dell'immagine


def _segment(text: str, checked=False) -> QPushButton:
    b = QPushButton(text)
    b.setCheckable(True)
    b.setChecked(checked)
    b.setProperty("segment", True)
    return b


class MainWindow(QMainWindow):
    _notice_sig = Signal(str, str)

    def __init__(self):
        super().__init__()
        install_placeholder_behavior()
        self.setWindowTitle("Arloc")
        self.resize(1320, 820)
        self.setMinimumSize(1020, 680)
        self.qs = QSettings("Arloc", "Arloc")
        self.settings = load_app_settings()

        # ---- stato
        self.bg_path: Path | None = None
        self.bg_img = None
        self.bg_area: Quad | None = None
        self.bg_area_auto: Quad | None = None
        self.bg_area_user = False
        self.mo_path: Path | None = None
        self.mo_img = None
        self.mo_quad: Quad | None = None
        self.mo_quad_auto: Quad | None = None
        self.mo_quad_user = False
        self.mo_quad_rect: Quad | None = None   # angoli "da rettangolo" (find_mosaic_corners)
        self.mo_mask = None                     # maschera di scontorno (uint8, <= MASK_MAX)
        self.mo_mask_auto = None
        self.mo_mask_user = False               # ritoccata a mano
        self.mo_mask_ver = 0
        self.scontorno = "auto"
        self._mask_seq = 0
        self._mask_busy = False
        self.view = "sfondo"
        self.show_before = False
        self.result_img = None          # immagine mostrata nella vista Risultato
        self.plain_img = None           # stesso risultato senza ritocco AI (None = nessun ritocco applicato)
        self.show_plain = False
        self.has_result = False
        self._full: tuple[str, ComposeResult] | None = None
        self._seq = 0
        self._busy = False

        central = QWidget()
        central.setObjectName("Central")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_topbar())
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        # Scheda Singola
        single = QWidget()
        sl = QHBoxLayout(single)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)
        cp = getattr(self.settings, "custom_preset", None)
        self.panel = StepsPanel(cp)
        sl.addWidget(self.panel)
        sep = QFrame()
        sep.setObjectName("VSeparator")
        sep.setFixedWidth(1)
        sl.addWidget(sep)
        sl.addWidget(self._build_right(), 1)
        self.stack.addWidget(single)

        self.batch = BatchView(self.settings, preset_getter=self._batch_preset)
        self.stack.addWidget(self.batch)

        # ---- timer anteprima
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self._run_preview)
        self._switch_after_preview = False

        # ---- collegamenti
        p = self.panel
        p.chooseBackground.connect(self.choose_background)
        p.chooseMosaic.connect(self.choose_mosaic)
        p.sizesChanged.connect(lambda: self._changed(switch=False))
        p.paramsChanged.connect(lambda: self._changed(switch=True))
        p.instructionsCommitted.connect(self._parse_text)
        p.suggestLight.connect(self._suggest_light)
        p.generate.connect(self.generate)
        p.save.connect(self.save)
        self.canvas.quadEdited.connect(self._quad_edited)
        self._notice_sig.connect(self._notice)
        self._sync_all()
        self._refresh_retouch()

    # ------------------------------------------------------------------ UI
    def _build_topbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("TopBar")
        bar.setFixedHeight(56)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(24, 0, 16, 0)
        title = QLabel("Arloc")
        title.setObjectName("AppTitle")
        lay.addWidget(title)
        lay.addStretch(1)
        self.tab_single = _segment("Singola", True)
        self.tab_batch = _segment("Batch")
        g = QButtonGroup(self)
        g.setExclusive(True)
        g.addButton(self.tab_single)
        g.addButton(self.tab_batch)
        self.tab_single.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        self.tab_batch.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        seg = QHBoxLayout()
        seg.setSpacing(0)
        seg.addWidget(self.tab_single)
        seg.addWidget(self.tab_batch)
        lay.addLayout(seg)
        lay.addStretch(1)
        gear = QPushButton("⚙")
        gear.setObjectName("IconButton")
        gear.setToolTip("Impostazioni")
        gear.setFixedSize(36, 36)
        gear.clicked.connect(self.open_settings)
        lay.addWidget(gear)
        return bar

    def _build_right(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.canvas = Canvas()
        lay.addWidget(self.canvas, 1)
        self.notice = QLabel("")
        self.notice.setObjectName("Notice")
        self.notice.setWordWrap(True)
        self.notice.hide()
        lay.addWidget(self.notice)

        lay.addWidget(self._build_toolbar())

        bar = QFrame()
        bar.setObjectName("ViewBar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 10, 16, 10)
        bl.setSpacing(8)
        l = QLabel("Vista")
        l.setObjectName("Muted")
        bl.addWidget(l)
        self.view_btns = {}
        g = QButtonGroup(self)
        g.setExclusive(True)
        seg = QHBoxLayout()
        seg.setSpacing(0)
        for key, text in (("sfondo", "Sfondo"), ("mosaico", "Mosaico"), ("risultato", "Risultato")):
            b = _segment(text, key == "sfondo")
            g.addButton(b)
            b.clicked.connect(lambda _=False, k=key: self.set_view(k))
            self.view_btns[key] = b
            seg.addWidget(b)
        bl.addLayout(seg)
        self.btn_before = _segment("Mostra prima")
        self.btn_before.setToolTip("Confronta con lo sfondo originale")
        self.btn_before.toggled.connect(self._toggle_before)
        bl.addWidget(self.btn_before)
        self.btn_plain = _segment("Senza ritocco AI")
        self.btn_plain.setToolTip("Confronta con il risultato prima del ritocco AI")
        self.btn_plain.toggled.connect(self._toggle_plain)
        bl.addWidget(self.btn_plain)
        bl.addStretch(1)
        self.btn_reset = QPushButton("Ripristina automatico")
        self.btn_reset.setToolTip("Torna agli angoli e allo scontorno automatici")
        self.btn_reset.clicked.connect(self.reset_auto)
        bl.addWidget(self.btn_reset)
        self.btn_fit = QPushButton("Adatta")
        self.btn_fit.setToolTip("Adatta l'immagine alla finestra (doppio clic sull'anteprima)")
        self.btn_fit.clicked.connect(self.canvas.fit)
        bl.addWidget(self.btn_fit)
        lay.addWidget(bar)
        return w

    def _build_toolbar(self) -> QWidget:
        """Barra della vista Mosaico: scontorno e ritocco con il pennello."""
        self.toolbar = QFrame()
        self.toolbar.setObjectName("ToolBar")
        col = QVBoxLayout(self.toolbar)
        col.setContentsMargins(16, 10, 16, 10)
        col.setSpacing(8)

        def label(text, width=72):
            l = QLabel(text)
            l.setObjectName("Muted")
            l.setFixedWidth(width)
            return l

        def segments(items, current, slot):
            g = QButtonGroup(self)
            g.setExclusive(True)
            box = QHBoxLayout()
            box.setSpacing(0)
            btns = {}
            for key, text in items:
                b = _segment(text, key == current)
                g.addButton(b)
                b.clicked.connect(lambda _=False, k=key: slot(k))
                box.addWidget(b)
                btns[key] = b
            return box, btns

        r1 = QHBoxLayout()
        r1.setSpacing(8)
        r1.addWidget(label("Scontorno"))
        box, self.cut_btns = segments((("auto", "Automatico"), ("rettangolo", "Rettangolo"),
                                       ("forma", "Forma libera")), "auto", self._set_scontorno)
        r1.addLayout(box)
        self.lbl_cut = QLabel("")
        self.lbl_cut.setObjectName("Status")
        r1.addWidget(self.lbl_cut, 1)
        col.addLayout(r1)

        r2 = QHBoxLayout()
        r2.setSpacing(8)
        r2.addWidget(label("Ritocco"))
        box, self.tool_btns = segments((("move", "Sposta"), ("add", "Aggiungi"), ("remove", "Togli")),
                                       "move", self._set_tool)
        self.tool_btns["add"].setToolTip("Dipingi sul mosaico per includere una zona")
        self.tool_btns["remove"].setToolTip("Dipingi per escludere una zona (nastro, supporto…)")
        r2.addLayout(box)
        r2.addSpacing(16)
        r2.addWidget(QLabel("Pennello"))
        self.sl_brush = QSlider(Qt.Horizontal)
        self.sl_brush.setRange(0, 100)
        self.sl_brush.setFixedWidth(140)
        self.sl_brush.setValue(int(round(100 * (0.04 - BRUSH_MIN) / (BRUSH_MAX - BRUSH_MIN))))
        self.sl_brush.valueChanged.connect(self._brush_size)
        r2.addWidget(self.sl_brush)
        r2.addStretch(1)
        self.btn_undo = QPushButton("Annulla")
        self.btn_undo.setToolTip("Annulla l'ultimo tratto di pennello")
        self.btn_undo.setEnabled(False)
        self.btn_undo.clicked.connect(self.canvas.undo)
        r2.addWidget(self.btn_undo)
        col.addLayout(r2)
        self.canvas.maskEdited.connect(self._mask_edited)
        self.canvas.undoChanged.connect(self.btn_undo.setEnabled)
        self._brush_size()
        return self.toolbar

    # ------------------------------------------------------------ avvisi
    def _notice(self, text: str, kind: str = "warn"):
        self.notice.setText(text)
        self.notice.setProperty("kind", kind)
        self.notice.style().unpolish(self.notice)
        self.notice.style().polish(self.notice)
        self.notice.setVisible(bool(text))

    def _error(self, exc_or_text, title="Qualcosa non è andato"):
        text = exc_or_text if isinstance(exc_or_text, str) else friendly_error(exc_or_text)
        self._notice(text, "error")

    # ------------------------------------------------------------ file
    def _dir(self, key: str) -> str:
        return str(self.qs.value(f"last_dir_{key}", str(Path.home())))

    def choose_background(self):
        p, _ = QFileDialog.getOpenFileName(self, "Scegli l'immagine di sfondo", self._dir("bg"),
                                           IMG_FILTER)
        if p:
            self.load_background(p)

    def choose_mosaic(self):
        p, _ = QFileDialog.getOpenFileName(self, "Scegli l'immagine del mosaico", self._dir("mo"),
                                           IMG_FILTER)
        if p:
            self.load_mosaic(p)

    def load_background(self, path, then=None):
        path = Path(path)
        self.qs.setValue("last_dir_bg", str(path.parent))
        self._notice("", "warn")
        self.setCursor(Qt.BusyCursor)

        def work():
            from arloc.core.detect import find_green_area
            from arloc.core.imageio import load_image
            img = load_image(path)
            found = find_green_area(img[:, :, :3] if img.ndim == 3 else img)
            return img, found

        def done(res):
            self.unsetCursor()
            img, found = res
            self.bg_path, self.bg_img = path, img
            self.bg_area_auto = found[0] if found else None
            self.bg_area, self.bg_area_user = self.bg_area_auto, False
            self.has_result = False
            self._full = None
            self.panel.set_bg_file(path.name)
            self.set_view("sfondo")
            self._sync_all()
            if then:
                then()

        def fail(e):
            self.unsetCursor()
            self._error(e)

        run_async(work, done, fail)

    def load_mosaic(self, path, then=None):
        path = Path(path)
        self.qs.setValue("last_dir_mo", str(path.parent))
        self._notice("", "warn")
        self.setCursor(Qt.BusyCursor)

        def work():
            from arloc.core.detect import find_mosaic_corners
            from arloc.core.imageio import load_image
            img = load_image(path)
            return img, find_mosaic_corners(img)

        def done(res):
            self.unsetCursor()
            img, quad = res
            self.mo_path, self.mo_img = path, img
            self.mo_quad_auto = self.mo_quad_rect = quad
            self.mo_quad, self.mo_quad_user = quad, False
            self.mo_mask = self.mo_mask_auto = None
            self.mo_mask_user = False
            self.mo_mask_ver += 1
            self.canvas.clear_undo()
            self._set_tool("move")
            self.has_result = False
            self._full = None
            self.panel.set_mosaic_file(path.name)
            self.set_view("mosaico")
            self._sync_all()
            self._compute_mask()
            if then:
                then()

        def fail(e):
            self.unsetCursor()
            self._error(e)

        run_async(work, done, fail)

    # ------------------------------------------------------------ scontorno
    def _compute_mask(self):
        """Scontorno automatico in background (con gli angoli indicati dall'utente, se ci sono)."""
        if self.mo_img is None:
            return
        self._mask_seq += 1
        seq = self._mask_seq
        img = self.mo_img
        quad = self.mo_quad if self.mo_quad_user else None
        self._mask_busy = True
        self._update_toolbar()

        def work():
            import cv2
            from arloc.core.cutout import cutout_mosaic
            m = cutout_mosaic(img, quad)
            s = min(1.0, MASK_MAX / max(m.shape[:2]))
            return cv2.resize(m, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else m

        def done(m):
            if seq != self._mask_seq:
                return
            self._mask_busy = False
            self.mo_mask_auto = m
            if not self.mo_mask_user:
                self.mo_mask = m
                self.mo_mask_ver += 1
                self.canvas.clear_undo()
            self._after_mask()

        def fail(e):
            if seq == self._mask_seq:
                self._mask_busy = False
                self._update_toolbar()
                self._notice("Non sono riuscito a individuare il contorno del mosaico: "
                             "si usa il rettangolo.", "warn")

        run_async(work, done, fail)

    def _mask_quad(self) -> Quad | None:
        """Quadrilatero che racchiude la maschera, in coordinate dell'immagine originale."""
        from arloc.core.cutout import quad_from_mask
        q = quad_from_mask(self.mo_mask) if self.mo_mask is not None else None
        if q is None:
            return None
        return Quad.from_array(q.as_array() * (self.mo_img.shape[1] / self.mo_mask.shape[1]))

    def _shape_in_use(self) -> bool:
        """True se la composizione userà la forma (non il rettangolo)."""
        if self.mo_mask is None or self.scontorno == "rettangolo":
            return False
        from arloc.core.cutout import use_shape
        q = self.mo_quad if self.mo_quad_user else self._mask_quad()
        if q is None:
            return False
        k = self.mo_mask.shape[1] / self.mo_img.shape[1]
        return use_shape(self.scontorno, self.mo_mask, Quad.from_array(q.as_array() * k), self.mo_img)

    def _auto_quad(self) -> Quad | None:
        q = self._mask_quad() if self.scontorno != "rettangolo" else None
        if q is None:
            return self.mo_quad_rect
        from arloc.core.cutout import inset_quad
        return q if self._shape_in_use() else inset_quad(q)

    def _after_mask(self):
        """Maschera nuova o scontorno cambiato: aggiorna angoli, vista e anteprima."""
        if not self.mo_quad_user:
            self.mo_quad = self.mo_quad_auto = self._auto_quad()
        self._update_toolbar()
        if self.view == "mosaico":
            self._show(fit=False)
        self._changed(switch=False)

    def _update_toolbar(self):
        has = self.mo_mask is not None
        rect = self.scontorno == "rettangolo"
        for b in self.tool_btns.values():
            b.setEnabled(has and not rect)
        self.sl_brush.setEnabled(has and not rect)
        if (not has or rect) and self.canvas._brush:
            self._set_tool("move")
        if self.mo_img is None:
            text = ""
        elif self._mask_busy:
            text = "Calcolo del contorno…"
        elif rect:
            text = "Il mosaico resta un rettangolo."
        elif not has:
            text = ""
        elif self._shape_in_use():
            text = "Uso la forma del mosaico: la zona velata viene esclusa."
        else:
            text = "Il mosaico è rettangolare: uso il rettangolo."
        self.lbl_cut.setText(text)

    def _set_scontorno(self, mode: str):
        self.scontorno = mode
        self.cut_btns[mode].setChecked(True)
        if mode != "rettangolo" and self.mo_mask is None and not self._mask_busy:
            self._compute_mask()
        self._after_mask()

    def _set_tool(self, tool: str):
        self.tool_btns[tool].setChecked(True)
        self.canvas.set_brush(None if tool == "move" else tool)
        self._show_cut_hint()

    def _brush_size(self, *_):
        v = self.sl_brush.value() / 100
        self.canvas.set_brush_size(BRUSH_MIN + v * (BRUSH_MAX - BRUSH_MIN))

    def _mask_edited(self, mask):
        self.mo_mask, self.mo_mask_user = mask, True
        self.mo_mask_ver += 1
        self._update_toolbar()
        self._changed(switch=False)

    def _show_cut_hint(self):
        t = self.canvas._brush
        self.canvas.set_hint({
            "add": "Dipingi per aggiungere zone al mosaico",
            "remove": "Dipingi per togliere zone (nastro, supporto…)"}.get(
                t, "Trascina gli angoli per ritagliare il mosaico"))

    # ------------------------------------------------------------ viste
    def set_view(self, view: str):
        self.view = view
        self.view_btns[view].setChecked(True)
        self._show(fit=True)

    def _toggle_before(self, on):
        self.show_before = on
        self.btn_before.setText("Mostra dopo" if on else "Mostra prima")
        self._show(fit=False)

    def _toggle_plain(self, on):
        self.show_plain = on
        self.btn_plain.setText("Mostra con ritocco AI" if on else "Senza ritocco AI")
        self._show(fit=False)

    def _set_plain(self, plain):
        """plain: risultato senza ritocco AI, oppure None se il ritocco non è stato applicato."""
        self.plain_img = plain
        self.btn_plain.blockSignals(True)
        self.btn_plain.setChecked(False)
        self.btn_plain.setText("Senza ritocco AI")
        self.btn_plain.blockSignals(False)
        self.show_plain = False

    def _show(self, fit=True):
        c = self.canvas
        v = self.view
        self.btn_before.setVisible(v == "risultato")
        self.btn_plain.setVisible(v == "risultato" and self.plain_img is not None)
        self.btn_reset.setVisible(v in ("sfondo", "mosaico"))
        self.toolbar.setVisible(v == "mosaico")
        c.set_mask(None, reset_undo=False)
        if v == "sfondo":
            if self.bg_img is None:
                c.set_image(None)
                c.set_placeholder("Scegli l'immagine di sfondo\ndal passo 1 per iniziare")
                c.set_hint("")
                return
            c.set_image(self.bg_img, fit=fit)
            picking = self.bg_area is None
            c.set_quad(self.bg_area, True, picking)
            c.set_hint("Clicca i 4 angoli dell'area dove va il mosaico" if picking else
                       "Trascina i punti per regolare l'area")
        elif v == "mosaico":
            if self.mo_img is None:
                c.set_image(None)
                c.set_placeholder("Scegli l'immagine del mosaico\ndal passo 2")
                c.set_hint("")
                return
            c.set_image(self.mo_img, fit=fit)
            c.set_quad(self.mo_quad, True)
            veil = self._shape_in_use()
            c.set_mask(self.mo_mask, veil, reset_undo=False)
            c.set_quad_filled(not veil)
            c.set_brush(None if self.tool_btns["move"].isChecked() else
                        ("add" if self.tool_btns["add"].isChecked() else "remove"))
            self._show_cut_hint()
        else:
            c.set_hint("")
            if self.result_img is None or self.bg_img is None:
                c.set_image(None)
                c.set_placeholder("Il risultato comparirà qui dopo GENERA")
                return
            bh, bw = self.bg_img.shape[:2]
            img = (self.bg_img if self.show_before else
                   self.plain_img if (self.show_plain and self.plain_img is not None) else self.result_img)
            c.set_image(img, logical_size=(bw, bh), fit=fit)
            c.set_quad(None, False)

    def _sync_all(self):
        has_area = self.bg_area is not None
        self.panel.set_flags(self.bg_img is not None, has_area, self.mo_img is not None)
        if self.bg_img is None:
            self.panel.set_area_status("", "")
        elif self.bg_area is None:
            self.panel.set_area_status("Area da indicare: clicca i 4 angoli sull'immagine", "todo")
        elif self.bg_area_user:
            self.panel.set_area_status("✓ Area indicata a mano", "ok")
        else:
            self.panel.set_area_status("✓ Area verde trovata", "ok")
        self.panel.set_can_save(self.has_result and not self._busy)
        self._update_toolbar()
        self._show(fit=True)

    def reset_auto(self):
        if self.view == "sfondo" and self.bg_img is not None:
            self.bg_area, self.bg_area_user = self.bg_area_auto, False
            self._sync_all()
            self._changed(switch=False)
        elif self.view == "mosaico" and self.mo_img is not None:
            self.mo_quad_user = self.mo_mask_user = False
            self.mo_mask = self.mo_mask_auto
            self.mo_mask_ver += 1
            self.mo_quad = self.mo_quad_auto = self._auto_quad()
            self.canvas.clear_undo()
            self._set_tool("move")
            self._compute_mask()
            self._sync_all()
            self._changed(switch=False)

    def _quad_edited(self, quad: Quad):
        if self.view == "sfondo":
            self.bg_area, self.bg_area_user = quad, True
            self._sync_all_keep_view()
        elif self.view == "mosaico":
            self.mo_quad, self.mo_quad_user = quad, True
            if self.scontorno != "rettangolo":
                self._compute_mask()
        self._changed(switch=False)

    def _sync_all_keep_view(self):
        self.panel.set_flags(self.bg_img is not None, self.bg_area is not None, self.mo_img is not None)
        self.panel.set_area_status("✓ Area indicata a mano", "ok")
        self.canvas.set_hint("Trascina i punti per regolare l'area")

    # ------------------------------------------------------------ job
    def _ready(self) -> bool:
        return (self.bg_img is not None and self.bg_area is not None and self.mo_img is not None
                and not self.panel.missing())

    def _job(self, params=None, text="") -> Job:
        mw, mh = self.panel.mosaic_size_cm()
        return Job(
            sfondo=self.bg_path, mosaico=self.mo_path,
            larghezza_sfondo_cm=self.panel.bg_width_cm(),
            larghezza_mosaico_cm=mw, altezza_mosaico_cm=mh, misure=self.panel.misure(),
            area=self.bg_area,
            mosaico_quad=self.mo_quad if self.mo_quad_user else None,
            scontorno=self.scontorno,
            mosaico_maschera=self.mo_mask if self.scontorno != "rettangolo" else None,
            istruzioni=text, params=params or self.panel.params(),
            preset=self.panel.preset())

    def _sig(self, params, text) -> str:
        j = self._job(params, text)
        return repr((str(j.sfondo), str(j.mosaico), j.larghezza_sfondo_cm, j.larghezza_mosaico_cm,
                     j.altezza_mosaico_cm, j.misure, j.area, j.mosaico_quad, j.scontorno, self.mo_mask_ver, params.to_dict(), text))

    def _changed(self, switch: bool):
        self._full = None if switch or self.has_result else self._full
        self.panel.update_checks()
        if switch:
            self._switch_after_preview = True
        if self._ready() and (switch or self.has_result):
            self.timer.start()

    def _run_preview(self):
        if not self._ready():
            return
        self._seq += 1
        seq = self._seq
        job = self._job()
        switch = self._switch_after_preview
        self._switch_after_preview = False

        def work():
            from arloc.core.compose import compose
            return compose(job, preview_max=PREVIEW_MAX)

        def done(res: ComposeResult):
            if seq != self._seq:
                return
            self._notice(" ".join(res.warnings), "warn")
            self.result_img = res.image
            self._set_plain(None)
            self.has_result = True
            self._full = None
            self.panel.set_can_save(not self._busy)
            if switch or self.view == "risultato":
                self.view_btns["risultato"].setChecked(True)
                first = self.view != "risultato"
                self.view = "risultato"
                self._show(fit=first)

        def fail(e):
            if seq == self._seq:
                self._error(e)

        run_async(work, done, fail)

    # ------------------------------------------------------------ istruzioni
    def _parse_text(self, text: str):
        if not text:
            return
        params0 = self.panel.params()
        settings = self.settings

        def work():
            from arloc.core.instructions import parse_instructions
            return parse_instructions(text, params0, settings)

        def done(res):
            params, warn = res
            self.panel.set_params(params)
            if warn:
                self._notice(warn, "warn")
            self._changed(switch=True)

        run_async(work, done, lambda e: self._error(e))

    def _suggest_light(self):
        if self.bg_img is None:
            self._notice("Scegli prima l'immagine di sfondo.", "warn")
            return
        bg = self.bg_path
        settings = self.settings
        self.panel.btn_light.setEnabled(False)

        def work():
            from arloc.core.instructions import suggest_light
            return suggest_light(bg, settings)

        def done(res):
            self.panel.btn_light.setEnabled(True)
            d, warn = res
            if d:
                self.panel.set_params(self.panel.params().updated(**d))
                self._changed(switch=True)
            if warn:
                self._notice(warn, "warn")
            elif not d:
                self._notice("Non sono riuscito a stimare la luce: usa i cursori.", "warn")

        def fail(e):
            self.panel.btn_light.setEnabled(True)
            self._error(e)

        run_async(work, done, fail)

    # ------------------------------------------------------------ genera / salva
    def _set_busy(self, busy: bool):
        self._busy = busy
        self.panel.set_busy(busy)
        self.panel.set_can_save(self.has_result and not busy)

    def generate(self):
        if not self._ready() or self._busy:
            return
        self.timer.stop()
        self._seq += 1  # invalida anteprime in corso
        text = self.panel.instructions()
        params0 = self.panel.params()
        settings = self.settings
        retouch = self.panel.retouch_enabled()
        self._notice("", "warn")
        self._set_busy(True)
        job_fn = self._job

        def work():
            from arloc.core.compose import compose
            params = params0
            warn = None
            if text:
                from arloc.core.instructions import parse_instructions
                params, warn = parse_instructions(text, params0, settings)
            return params, warn, compose(job_fn(params, text))

        def done(res):
            params, warn, result = res
            self.panel.set_params(params)
            self.panel.mark_text_parsed(text)
            self._full = (self._sig(params, text), result)
            self.result_img, self.has_result = result.image, True
            self._set_plain(None)
            msgs = ([warn] if warn else []) + list(result.warnings)
            self._notice(" ".join(msgs), "warn")
            self.view_btns["risultato"].setChecked(True)
            self.view = "risultato"
            self.btn_before.setChecked(False)
            self._show(fit=True)
            if retouch:
                self._run_retouch(result, msgs)
            else:
                self._set_busy(False)

        def fail(e):
            self._set_busy(False)
            self._error(e)

        run_async(work, done, fail)

    def _run_retouch(self, result: ComposeResult, msgs: list[str]):
        """Ritocco AI finale in background sul risultato a piena risoluzione."""
        self.panel.set_busy(True, "Ritocco AI in corso…")
        self._notice("Ritocco AI in corso… può richiedere qualche decina di secondi.", "ok")
        settings = self.settings
        seq = self._seq

        def work():
            from arloc.core.harmonize import harmonize
            return harmonize(result, result.mosaic_mask, settings)

        def done(r):
            img, warn = r
            self._set_busy(False)
            if seq != self._seq:
                return
            if warn is None:
                self._set_plain(result.image)
                self.result_img = img
                self._notice(" ".join(msgs), "warn")
                self._show(fit=False)
            else:
                self._notice(" ".join(msgs + [warn]), "warn")

        def fail(e):
            self._set_busy(False)
            self._notice(" ".join(msgs + ["Ritocco AI non riuscito: tenuto il risultato originale."]), "warn")

        run_async(work, done, fail)

    def save(self):
        if not self.has_result or self._busy:
            return
        preset = self.panel.preset()
        out_dir = getattr(self.settings, "output_dir", "") or self._dir("out")
        default = Path(out_dir) / f"{self.mo_path.stem}_{self.bg_path.stem}.{preset.formato}"
        path, _ = QFileDialog.getSaveFileName(
            self, "Salva immagine", str(default),
            f"{preset.formato.upper()} (*.{preset.formato})")
        if not path:
            return
        base = Path(path).with_suffix("")
        self.qs.setValue("last_dir_out", str(base.parent))
        text = self.panel.instructions()
        params = self.panel.params()
        cached = self._full if (self._full and self._full[0] == self._sig(params, text)) else None
        job_fn = self._job
        retouch = self.panel.retouch_enabled()
        settings = self.settings
        self._set_busy(True)
        self.panel.btn_save.setText("Salvo…")

        def work():
            import dataclasses
            from arloc.core.compose import compose
            from arloc.core.presets import export
            res = cached[1] if cached else compose(job_fn(params, text))
            final, warn = res, None
            if retouch:   # il ritocco va prima del preset (la risposta è in cache su disco: nessuna seconda chiamata)
                from arloc.core.harmonize import harmonize
                img, warn = harmonize(res, res.mosaic_mask, settings)
                final = dataclasses.replace(res, image=img, warnings=list(res.warnings))
            return res, export(final, preset, base), warn

        def done(r):
            res, out, warn = r
            self._full = (self._sig(params, text), res)
            self.panel.btn_save.setText("Salva immagine…")
            self._set_busy(False)
            if warn:
                self._notice(f"Immagine salvata: {out}. {warn}", "warn")
            else:
                self._notice(f"Immagine salvata: {out}", "ok")

        def fail(e):
            self.panel.btn_save.setText("Salva immagine…")
            self._set_busy(False)
            self._error(e)

        run_async(work, done, fail)

    # ------------------------------------------------------------ varie
    def _refresh_retouch(self):
        """Abilita il ritocco AI solo con OpenRouter e mostra il costo stimato (dai prezzi pubblici)."""
        ok = getattr(self.settings, "provider", "anthropic") == "openrouter"
        self.panel.set_retouch_available(ok)
        if not ok:
            return
        settings = self.settings

        def work():
            from arloc.core.harmonize import estimate_cost_usd
            return estimate_cost_usd(settings)

        def done(c):
            if c:
                txt = f"circa {c:.2f} $".replace(".", ",")
                self.panel.set_retouch_available(True, txt)

        run_async(work, done, lambda e: None)

    def _batch_preset(self):
        return self.panel.preset()

    def open_settings(self):
        if self.settings is None:
            QMessageBox.information(self, "Impostazioni", "Le impostazioni non sono disponibili.")
            return
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            self._refresh_retouch()
            self.panel.set_custom_preset(self.settings.custom_preset)
            self.batch.set_settings(self.settings)
