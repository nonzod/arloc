# Contratti tra moduli (per lo sviluppo parallelo)

Tipi condivisi: `arloc/core/models.py` (non modificare in modo incompatibile).
Immagini = numpy BGR uint8 (BGRA se con alpha). Messaggi utente in italiano, errori utente = `ArlocError`.

## Agente CORE (immagini)
- `arloc/core/imageio.py`
  - `load_image(path) -> np.ndarray` — legge JPG/PNG/WEBP, applica orientamento EXIF, mantiene alpha se presente. Solleva `ArlocError` se non leggibile. Supporta percorsi con spazi/unicode (usa `np.fromfile`+`cv2.imdecode` o Pillow).
  - `save_image(img, path, formato, qualita) -> Path` — sRGB, senza EXIF.
  - `load_image_cached(path) -> np.ndarray` — come `load_image` ma in cache (percorso + data di modifica), array in **sola lettura**. `file_key(path)` = identità del file.
  - `downscale(img, long_side, interpolation=INTER_AREA) -> (img, scala)`, `encode_jpeg(img, long_side, quality) -> bytes`.
- `arloc/core/detect.py`
  - `find_green_area(img) -> tuple[Quad, np.ndarray] | None` — quad + maschera uint8 (255 = verde).
  - `find_mosaic_corners(img) -> Quad` — fallback: angoli dell'immagine intera.
  - `texture_mask(small, factor=0.6) -> np.ndarray` — zona con "grana" (fughe), 255 = mosaico.
- `arloc/core/cutout.py` (scontorno)
  - `cutout_mosaic(img, quad: Quad | None = None) -> np.ndarray` — maschera uint8 (255 = mosaico, bordo leggermente sfumato) alla risoluzione di `img`. Alpha del PNG se significativo, altrimenti GrabCut su copia ~1000 px, inizializzato da `quad` (se dato) e dalla texture. Senza buchi interni.
  - `quad_from_mask(mask) -> Quad | None`, `quad_coverage(mask, quad) -> float`, `use_shape(mode, mask, quad, img=None) -> bool` (`mode`: `auto` | `rettangolo` | `forma`; auto = forma se copertura < 92% o PNG con alpha).
- `arloc/core/geometry.py`
  - `order_quad(pts) -> Quad`, `parse_area(text) -> Quad` (formato `"x1,y1;x2,y2;x3,y3;x4,y4"`, ordine qualsiasi; ArlocError se invalido),
  - `auto_mosaic_size(area, mosaic_quad, riempimento) -> (w_px, h_px, px_per_cm)` (misure automatiche), `px_per_cm(bg_width_px, bg_width_cm) -> float`, `placement_quad(area, mosaic_w_px, mosaic_h_px, params, px_per_cm) -> Quad`.
- `arloc/core/effects.py` — ombre, spessore, armonizzazione, grana, inpaint verde residuo. `grain_sigma(bg, alpha)`; `add_grain(..., sigma=None)`. `compose` applica gli effetti solo sul riquadro del mosaico (+ margine).
- `arloc/core/compose.py`
  - `compose(job: Job, preview_max: int | None = None) -> ComposeResult` — se `preview_max` è dato, lavora su copia ridotta (lato lungo ≤ preview_max) per l'anteprima veloce. NON chiama Claude: usa `job.params` così com'è.
  - Scontorno: `Job.scontorno` (`"auto"` default | `"rettangolo"` | `"forma"`) e `Job.mosaico_maschera` (uint8 0/255, anche a risoluzione ridotta; None = calcolata con `cutout_mosaic`). In modalità forma immagine e maschera sono raddrizzate con la stessa omografia del quad e la maschera è l'alpha (ombra e spessore ne derivano). Le misure in cm si riferiscono al rettangolo del quad. Se `mosaico_quad` è None, in auto/forma il quad deriva dalla maschera (`quad_from_mask`).
  - Misure: `Job.misure` = `"reali"` (default; servono `larghezza_sfondo_cm`, `larghezza_mosaico_cm`, `altezza_mosaico_cm`, altrimenti `ArlocError`) | `"automatiche"` (cm ignorati/0; serve comunque un'area; il mosaico è scalato per entrare nell'area, proporzioni del suo quad, `ComposeParams.riempimento` 0,5-1,0). Nessun avviso di dimensione in automatico.
  - `rectify_mosaic(img, quad, w_cm, h_cm) -> np.ndarray` (usata anche dalla UI per mostrare il ritaglio).
- `arloc/core/presets.py`
  - `SHOPIFY`, `ETSY` (OutputPreset), `parse_preset(text) -> OutputPreset` (`"shopify"`, `"etsy"`, `"custom 1600x1200 png"`), 
  - `apply_preset(result: ComposeResult, preset) -> np.ndarray`, `export(result, preset, path_senza_estensione) -> Path`.
- CLI: `arloc/cli.py` con `main(argv) -> int`, sottocomando `compose` (vedi IMPLEMENTAZIONE.md §11 M1). Il sottocomando `batch` lo registra l'agente BATCH chiamando `arloc.core.batch`.

## Agente BATCH + CLAUDE + SETTINGS
- `arloc/core/settings.py`
  - `Settings` dataclass: `output_dir: str`, `custom_preset: OutputPreset`, `default_preset: str`, `model_instructions="claude-haiku-5-5"`, `model_light="claude-sonnet-5-5"`, `last_dirs: dict`, `provider="anthropic"|"openrouter"`, `openrouter_model_instructions="anthropic/claude-haiku-5.5"`, `openrouter_model_light="anthropic/claude-sonnet-5.5"`.
  - `Settings.model(role) -> str` — modello del ruolo (`instructions|light|retouch`) per il servizio scelto.
  - `get_key(provider)`/`set_key(provider, key|None)` (provider `anthropic|openrouter`; gli alias sotto restano).
  - `load_settings() -> Settings`, `save_settings(s)` (JSON in platformdirs user_config_dir("arloc")), `get_api_key() -> str|None`, `set_api_key(key|None)` (keyring, fallback env `ANTHROPIC_API_KEY`), `get_openrouter_key()`/`set_openrouter_key(key|None)` (keyring, fallback env `OPENROUTER_API_KEY`), `cache_dir() -> Path`.
- `arloc/core/ai.py` — servizi AI. `provider_for(settings_or_name)` → oggetto con `name`, `label`, `key()`, `call_json(model, system, text, schema, image_jpeg=None) -> dict`, `verify_key(key, model)`, `check_models(settings, key)`, `to_error(e)`; OpenRouter anche `chat(body, timeout) -> dict`. Errori: `AIError(kind, model)`; `message(err, provider, context)` (context `instructions|light|retouch`) → testo italiano. `openrouter_models()`, `ROLE_NAMES`.
- `arloc/core/cache.py` — `DiskCache(name, max_items=500, suffix=".json")` con `get/put` (JSON) e `get_bytes/put_bytes`; `make_key(*parts)`. Mai eccezioni.
- `arloc/core/pipeline.py` — sequenza completa, mai eccezioni dalle parti AI:
  - `apply_instructions(job, settings=None, use_claude=True) -> (Job, avviso|None)` — copia del job con i parametri aggiornati.
  - `retouch(result, settings=None) -> (ComposeResult, avviso|None)` — ritocco AI su una copia del risultato.
  - `render(job, settings=None, *, use_claude=True, retouch_ai=None, preview_max=None) -> (Job, ComposeResult, avvisi AI)` — `retouch_ai=None` usa `job.ritocco_ai`; niente ritocco in anteprima.
- `arloc/core/instructions.py`
  - `parse_instructions(text, current: ComposeParams, settings=None) -> tuple[ComposeParams, str | None]` — secondo valore = avviso utente o None. Mai eccezioni verso il chiamante.
  - `suggest_light(bg_img_or_path, settings=None) -> tuple[dict | None, str | None]` — dict con chiavi ombra_*.
  - `verify_api_key(key, provider=None) -> tuple[bool, str]` (provider di default da `Settings`).
  - `check_models(settings=None, key=None) -> list[tuple[str, str, str]]` — `(ruolo, livello, messaggio)`, ruolo `instructions|light|retouch`, livello `ok|warn|error`. Senza Qt, mai eccezioni; elenco modelli OpenRouter in cache per la sessione (`openrouter_models()`).
- `arloc/core/harmonize.py` (ritocco AI finale, sperimentale, solo OpenRouter)
  - `harmonize(result: ComposeResult, mosaic_mask_out: np.ndarray | None, settings=None) -> tuple[np.ndarray, str | None]` — immagine finale BGR (originale se scartato o in errore) e avviso italiano. Mai eccezioni. Richiede `result.mosaic_mask` (o `mosaic_mask_out`). `estimate_cost_usd(settings=None) -> float | None`.
  - `ComposeResult.mosaic_mask` (uint8 0/255, dimensioni di `image`, facoltativo, None se assente) e `Job.ritocco_ai: bool = False` (lo applica il chiamante: UI, batch, CLI; compose non lo chiama).
  - Settings: `openrouter_model_retouch="google/gemini-3.1-flash-image"`.
- `arloc/core/batch.py`
  - `BatchRow` dataclass: `index:int, raw:dict, job: Job|None, error: str|None, status: str ("in attesa"|"ok"|"errore"|"saltata"), output: Path|None`.
  - `read_batch(path, default_preset: OutputPreset) -> list[BatchRow]` (colonne cm facoltative: tutte vuote = misure automatiche, parziali = errore di riga; colonna facoltativa `misure`: reali|automatiche; colonna facoltativa `scontorno`: auto|rettangolo|forma; colonna facoltativa `ritocco_ai`: sì|no, vuoto = no; CSV `,`/`;`, XLSX, decimali con virgola, percorsi relativi al file).
  - `run_batch(rows, out_dir, progress=None, should_stop=None, use_claude=True) -> Path` (report CSV). `progress(i, total, row)`.
  - `write_template(path)` — copia/genera il modello.
- Packaging: `packaging/arloc.spec`, `.github/workflows/build.yml`, `templates/modello_batch.csv|xlsx`.

## Agente UI
- `arloc/app.py` `run() -> int`, `arloc/ui/*` come in IMPLEMENTAZIONE.md §9. Usa solo le funzioni sopra. Lavori pesanti in `QThread`.
- `arloc/__main__.py`: `main()` — senza argomenti `app.run()`, altrimenti `cli.main(sys.argv[1:])`.
