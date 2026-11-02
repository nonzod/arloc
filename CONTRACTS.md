# Contratti tra moduli (per lo sviluppo parallelo)

Tipi condivisi: `arloc/core/models.py` (non modificare in modo incompatibile).
Immagini = numpy BGR uint8 (BGRA se con alpha). Messaggi utente in italiano, errori utente = `ArlocError`.

## Agente CORE (immagini)
- `arloc/core/imageio.py`
  - `load_image(path) -> np.ndarray` — legge JPG/PNG/WEBP, applica orientamento EXIF, mantiene alpha se presente. Solleva `ArlocError` se non leggibile. Supporta percorsi con spazi/unicode (usa `np.fromfile`+`cv2.imdecode` o Pillow).
  - `save_image(img, path, formato, qualita) -> Path` — sRGB, senza EXIF.
- `arloc/core/detect.py`
  - `find_green_area(img) -> tuple[Quad, np.ndarray] | None` — quad + maschera uint8 (255 = verde).
  - `find_mosaic_corners(img) -> Quad` — fallback: angoli dell'immagine intera.
  - `texture_mask(small, factor=0.6) -> np.ndarray` — zona con "grana" (fughe), 255 = mosaico.
- `arloc/core/cutout.py` (scontorno)
  - `cutout_mosaic(img, quad: Quad | None = None) -> np.ndarray` — maschera uint8 (255 = mosaico, bordo leggermente sfumato) alla risoluzione di `img`. Alpha del PNG se significativo, altrimenti GrabCut su copia ~1000 px, inizializzato da `quad` (se dato) e dalla texture. Senza buchi interni.
  - `quad_from_mask(mask) -> Quad | None`, `quad_coverage(mask, quad) -> float`, `use_shape(mode, mask, quad, img=None) -> bool` (`mode`: `auto` | `rettangolo` | `forma`; auto = forma se copertura < 92% o PNG con alpha).
- `arloc/core/geometry.py`
  - `order_quad(pts) -> Quad`, `parse_area(text) -> Quad` (formato `"x1,y1;x2,y2;x3,y3;x4,y4"`, ordine qualsiasi; ArlocError se invalido),
  - `px_per_cm(bg_width_px, bg_width_cm) -> float`, `placement_quad(area, mosaic_w_px, mosaic_h_px, params, px_per_cm) -> Quad`.
- `arloc/core/effects.py` — ombre, spessore, armonizzazione, grana, inpaint verde residuo.
- `arloc/core/compose.py`
  - `compose(job: Job, preview_max: int | None = None) -> ComposeResult` — se `preview_max` è dato, lavora su copia ridotta (lato lungo ≤ preview_max) per l'anteprima veloce. NON chiama Claude: usa `job.params` così com'è.
  - Scontorno: `Job.scontorno` (`"auto"` default | `"rettangolo"` | `"forma"`) e `Job.mosaico_maschera` (uint8 0/255, anche a risoluzione ridotta; None = calcolata con `cutout_mosaic`). In modalità forma immagine e maschera sono raddrizzate con la stessa omografia del quad e la maschera è l'alpha (ombra e spessore ne derivano). Le misure in cm si riferiscono al rettangolo del quad. Se `mosaico_quad` è None, in auto/forma il quad deriva dalla maschera (`quad_from_mask`).
  - `rectify_mosaic(img, quad, w_cm, h_cm) -> np.ndarray` (usata anche dalla UI per mostrare il ritaglio).
- `arloc/core/presets.py`
  - `SHOPIFY`, `ETSY` (OutputPreset), `parse_preset(text) -> OutputPreset` (`"shopify"`, `"etsy"`, `"custom 1600x1200 png"`), 
  - `apply_preset(result: ComposeResult, preset) -> np.ndarray`, `export(result, preset, path_senza_estensione) -> Path`.
- CLI: `arloc/cli.py` con `main(argv) -> int`, sottocomando `compose` (vedi IMPLEMENTAZIONE.md §11 M1). Il sottocomando `batch` lo registra l'agente BATCH chiamando `arloc.core.batch`.

## Agente BATCH + CLAUDE + SETTINGS
- `arloc/core/settings.py`
  - `Settings` dataclass: `output_dir: str`, `custom_preset: OutputPreset`, `default_preset: str`, `model_instructions="claude-haiku-5-5"`, `model_light="claude-sonnet-5-5"`, `last_dirs: dict`, `provider="anthropic"|"openrouter"`, `openrouter_model_instructions="anthropic/claude-haiku-5.5"`, `openrouter_model_light="anthropic/claude-sonnet-5.5"`.
  - `load_settings() -> Settings`, `save_settings(s)` (JSON in platformdirs user_config_dir("arloc")), `get_api_key() -> str|None`, `set_api_key(key|None)` (keyring, fallback env `ANTHROPIC_API_KEY`), `get_openrouter_key()`/`set_openrouter_key(key|None)` (keyring, fallback env `OPENROUTER_API_KEY`), `cache_dir() -> Path`.
- `arloc/core/instructions.py`
  - `parse_instructions(text, current: ComposeParams, settings=None) -> tuple[ComposeParams, str | None]` — secondo valore = avviso utente o None. Mai eccezioni verso il chiamante.
  - `suggest_light(bg_img_or_path, settings=None) -> tuple[dict | None, str | None]` — dict con chiavi ombra_*.
  - `verify_api_key(key, provider=None) -> tuple[bool, str]` (provider di default da `Settings`).
- `arloc/core/batch.py`
  - `BatchRow` dataclass: `index:int, raw:dict, job: Job|None, error: str|None, status: str ("in attesa"|"ok"|"errore"|"saltata"), output: Path|None`.
  - `read_batch(path, default_preset: OutputPreset) -> list[BatchRow]` (colonna facoltativa `scontorno`: auto|rettangolo|forma; CSV `,`/`;`, XLSX, decimali con virgola, percorsi relativi al file).
  - `run_batch(rows, out_dir, progress=None, should_stop=None, use_claude=True) -> Path` (report CSV). `progress(i, total, row)`.
  - `write_template(path)` — copia/genera il modello.
- Packaging: `packaging/arloc.spec`, `.github/workflows/build.yml`, `templates/modello_batch.csv|xlsx`.

## Agente UI
- `arloc/app.py` `run() -> int`, `arloc/ui/*` come in IMPLEMENTAZIONE.md §9. Usa solo le funzioni sopra. Lavori pesanti in `QThread`.
- `arloc/__main__.py`: `main()` — senza argomenti `app.run()`, altrimenti `cli.main(sys.argv[1:])`.
