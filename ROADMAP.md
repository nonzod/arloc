# Roadmap

Dettagli tecnici di ogni milestone in [IMPLEMENTAZIONE.md](IMPLEMENTAZIONE.md) §11.

## M0: Progettazione
- [x] Idea (IDEA.md)
- [x] Documento di implementazione
- [x] README, AGENTS, ROADMAP, CHANGELOG

## M1: Core di composizione + CLI
- [x] Scheletro progetto (`uv`, `pyproject.toml`, struttura cartelle)
- [x] Ricerca dell'area verde
- [x] Ritaglio automatico del mosaico e raddrizzamento
- [x] Scala reale (px/cm) e posizionamento in prospettiva
- [x] Misure automatiche: il mosaico riempie l'area senza misure in cm (UI, CLI, batch)
- [x] Ombra proiettata, ombra di contatto, spessore
- [x] Adattamento luce/colore, riempimento del verde residuo
- [x] Preset Shopify / Etsy / Custom ed export
- [x] CLI `compose`, verifica visiva su `examples/`

## M2: Interfaccia manuale
- [x] Finestra principale con pannello a passi e anteprima
- [x] Punti trascinabili (area sfondo e angoli mosaico)
- [x] Regolazioni avanzate con anteprima veloce
- [x] Salvataggio e memoria delle ultime scelte
- [x] Tema e stile
- [ ] Prova manuale con mouse: trascinamento maniglie, 4 clic area, Prima/Dopo, Salva

## M2b: Scontorno del mosaico
- [x] Maschera automatica (GrabCut + grana delle fughe), alpha dei PNG, modalità auto/rettangolo/forma
- [x] Composizione con la maschera come alpha (ombra e spessore seguono la forma)
- [x] Colonna batch `scontorno`, opzione CLI `--scontorno`
- [x] Vista Mosaico: velo, pennello Aggiungi/Togli, Annulla, Ripristina automatico
- [ ] Prova manuale del pennello con il mouse su schermo reale

## M3: Batch
- [x] Lettura CSV/XLSX (separatori, decimali, percorsi relativi)
- [x] Esecuzione in background con avanzamento e interruzione
- [x] Report finale
- [x] Modelli `templates/modello_batch.csv|xlsx` e "Scarica modello"

## M4: Claude
- [x] Impostazioni: chiave API nel portachiavi + verifica
- [x] Istruzioni → parametri (Haiku 5.5, output strutturato, cache)
- [x] Suggerimento della luce dallo sfondo (Sonnet 5.5, cache per sfondo)
- [x] Comportamento senza chiave o rete
- [x] OpenRouter come servizio alternativo (selettore nelle Impostazioni, chiave separata)
- [ ] Prova con chiave API reale, Anthropic e OpenRouter (finora solo test simulati)

## M4b: Verifica modelli e ritocco AI (sperimentale)
- [x] "Verifica" controlla anche i modelli configurati (esistenza, tipo di modello, suggerimenti)
- [x] Ritocco AI finale con modello generativo di immagini (OpenRouter), con protezione del mosaico, interruttore UI, batch `ritocco_ai`, CLI `--ritocco-ai`
- [ ] Prova con chiave OpenRouter reale: formato della risposta (`message.images`), costo effettivo e qualità del ritocco

## M5: Distribuzione
- [x] Build PyInstaller Linux verificato (GUI, CLI compose, batch dall'eseguibile; ~500 MB, ~200 MB compresso)
- [x] Icona dell'app (`packaging/make_icon.py`)
- [ ] Build PyInstaller Windows / macOS (spec pronto, mai eseguito su quei sistemi)
- [ ] GitHub Actions su tag `v*` — workflow scritto, mai eseguito
- [ ] Prova su macchine pulite

## M6: Refactoring e velocità
- [x] Servizi AI dietro un'unica interfaccia (`core/ai.py`), errori tradotti in un solo punto, client riusati
- [x] Cache su disco unica (`core/cache.py`), un file per risposta e limite di dimensione
- [x] Sequenza istruzioni → composizione → ritocco in un solo punto (`core/pipeline.py`) per GUI, batch e CLI
- [x] Anteprima più veloce: sfondo, mosaico e verde in memoria, effetti solo sulla zona del mosaico, anello di armonizzazione con `distanceTransform`
- [ ] Prova manuale della GUI con mouse dopo il refactoring (cursori, Suggerisci luce, Genera con ritocco AI)

## Da migliorare
- [ ] Ombra più marcata / meno effetto "incollato" (tarare i default su più sfondi)
- [ ] Ritaglio automatico: a volte taglia ~1% di tessere sul bordo
- [ ] Scontorno: su M11 include un po' di intonaco scuro a sinistra; sul vetro S108 la cornice dorata a destra può restare fuori (si corregge col pennello)

## Idee future
- Dividere `ui/main_window.py` (quasi 900 righe) in controller e vista
- Raddrizzare il mosaico direttamente alla dimensione finale (oggi ~20 ms in anteprima: guadagno piccolo, da rivalutare con mosaici molto grandi)
- Batch API di Anthropic per i batch lunghi (−50 % sul costo, risultati non immediati)
- Installer Windows (Inno Setup) e firma dell'app macOS
- Più mosaici nella stessa immagine
- Altri preset (Amazon, Instagram)
