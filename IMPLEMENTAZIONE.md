# Arloc: documento di implementazione

Riferimento: [IDEA.md](IDEA.md). Questo documento descrive *come* costruire Arloc. Le decisioni qui raccolte sono state concordate con l'autore; se una cambia, va aggiornata qui e annotata in [CHANGELOG.md](CHANGELOG.md).

---

## 1. Panoramica

Arloc prende tre cose:
- una foto di **sfondo**, cioè una scrivania con gli attrezzi del kit fotografata dall'alto;
- la foto di un **mosaico**, reale o disegnato;
- le **misure reali** dello sfondo e del mosaico.

Con queste produce un'immagine in cui il mosaico è appoggiato sulla scrivania con la grandezza giusta, in prospettiva e con un'ombra credibile.

### Scelta di fondo: motore ibrido

I modelli Claude **non generano e non modificano immagini**: le capiscono, ma non le producono. Per questo la composizione la fa **il software in locale** (OpenCV + Pillow), in modo preciso e ripetibile. **Claude** si occupa della parte "intelligente":

| Compito | Chi lo fa |
|---|---|
| Ritaglio e raddrizzamento del mosaico | Software (OpenCV) |
| Ricerca dell'area verde nello sfondo | Software (OpenCV) |
| Scala, prospettiva, posizionamento | Software (omografia) |
| Ombra, spessore, adattamento di luce e colore | Software |
| Lettura delle istruzioni in testo libero ("ombra morbida verso destra, ruota di 5°") | **Claude** → parametri JSON |
| Suggerimento della direzione della luce guardando lo sfondo (opzionale) | **Claude** (vision) |

Perché è la scelta giusta:
- **Il mosaico resta identico**: nessuna tessera viene inventata o alterata. Per un prodotto in vendita è un requisito fondamentale.
- **Costa pochissimo** (vedi §6) e il risultato è prevedibile.
- **Funziona anche senza internet e senza chiave API**: le istruzioni si danno con i cursori.

L'armonizzazione con un modello generativo esterno (es. Gemini Image, FLUX Kontext) resta in [ROADMAP.md](ROADMAP.md) come idea per il futuro, da valutare solo se le ombre "classiche" non bastano.

### Flusso

```
Sfondo ──► trova l'area (verde o 4 punti) ─┐
                                           ├─► calcola la scala ─► compone ─► esporta con il preset
Mosaico ─► trova angoli + raddrizza ───────┘          ▲
                                                      │
Istruzioni (testo) ─► Claude ─► ComposeParams ────────┘   (in alternativa: i cursori)
```

---

## 2. Stack

| Componente | Scelta | Motivo |
|---|---|---|
| Linguaggio | Python 3.12 | Ecosistema imaging maturo |
| Interfaccia | PySide6 (Qt 6) | Nativa su Windows, macOS e Linux, aspetto moderno |
| Imaging | `opencv-python-headless`, `Pillow`, `numpy` | Omografia, maschere, inpaint, I/O (anche WEBP) |
| Batch | `pandas` + `openpyxl` | Lettura di CSV e XLSX |
| AI | `anthropic` (SDK ufficiale) | Istruzioni → parametri, analisi della luce |
| Segreti | `keyring` | Chiave API nel portachiavi del sistema |
| Percorsi di configurazione | `platformdirs` | Cartelle utente corrette su ogni sistema |
| Pacchetti | `uv` | Ambiente riproducibile e veloce |
| Distribuzione | PyInstaller (+ appimagetool su Linux) | Un eseguibile per sistema operativo |

---

## 3. Struttura del progetto

```
arloc/
  pyproject.toml
  arloc/
    __main__.py          # avvio: senza argomenti apre la GUI, con argomenti usa la CLI (sviluppo e test)
    app.py               # crea QApplication e MainWindow
    core/                # NESSUNA dipendenza da Qt
      models.py          # dataclass: ComposeParams, Job, Quad, OutputPreset
      detect.py          # find_green_area(), find_mosaic_corners()
      geometry.py        # order_quad(), px_per_cm(), placement_quad()
      compose.py         # compose(job) -> immagine PIL
      effects.py         # ombre, spessore, adattamento colore, inpaint del verde residuo
      instructions.py    # parse_instructions(), suggest_light() via Claude, con cache
      presets.py         # Shopify / Etsy / Custom + export
      batch.py           # read_batch(), run_batch() -> report
      settings.py        # impostazioni utente + keyring
    ui/
      main_window.py     # schede "Singola" e "Batch"
      steps_panel.py     # pannello a passi (sinistra)
      canvas.py          # anteprima con punti trascinabili (QGraphicsView)
      batch_view.py      # tabella delle righe + avanzamento
      settings_dialog.py # chiave API, cartella di output predefinita
      style.qss          # tema
      resources/         # icone
  templates/
    modello_batch.csv
    modello_batch.xlsx
  tests/                 # pochi test mirati (§10)
  packaging/             # spec PyInstaller, icone, script AppImage
```

Regola d'oro: **tutta la logica sta in `core/`**. Interfaccia, batch e CLI chiamano la stessa funzione `compose(job)`. In questo modo ogni cosa che funziona da riga di comando funziona anche nella GUI.

---

## 4. Sfondi: specifiche e ricerca dell'area

### 4.1 Come preparare uno sfondo (da riportare nel README)

- Foto scattata **il più possibile dall'alto**, con buona luce e senza oggetti dove andrà il mosaico.
- **Opzione A, rettangolo verde**: con un qualsiasi programma di grafica si disegna un quadrilatero **pieno** di verde puro `#00FF00` (RGB 0,255,0), senza sfumature né trasparenze, nel punto in cui andrà il mosaico. Se la foto è in prospettiva, il quadrilatero segue la prospettiva del piano.
  - Il quadrilatero deve essere **uguale o più piccolo** del mosaico reale. Il verde che resta scoperto viene ricostruito in automatico, ma su legno e venature il risultato è meno pulito.
  - Il file va salvato in **PNG** (o JPG qualità ≥ 95); un JPG molto compresso sporca i bordi del verde.
- **Opzione B, 4 punti**: lo sfondo resta pulito. Nell'interfaccia si cliccano i 4 angoli; nel batch si scrivono le coordinate nel CSV.

### 4.2 Ricerca del verde (`detect.find_green_area`)

1. Conversione in HSV. Maschera: H ∈ [50,70] (scala OpenCV 0–180), S > 150, V > 150. I valori sono tarabili.
2. Apertura e chiusura morfologica per togliere rumore e buchi.
3. Contorno più grande; se l'area è < 0,5% dell'immagine → "nessuna area verde".
4. `cv2.approxPolyDP` fino a ottenere 4 vertici. In fallback si usa `cv2.minAreaRect`.
5. `geometry.order_quad()` ordina i vertici in alto-sx, alto-dx, basso-dx, basso-sx.
6. La funzione restituisce `Quad` e anche la **maschera del verde**, che serve dopo per il riempimento.

Priorità: area dal CSV o dai click se presente, altrimenti verde, altrimenti errore ("Indica l'area").

---

## 5. Mosaico: ritaglio, scala e composizione

### 5.1 Ritaglio automatico (`detect.find_mosaic_corners`)

Le foto d'esempio (`examples/mosaici/RIFERIMENTO_*`) hanno nastro e supporto bianco intorno al mosaico.

1. Riduzione a ~1200 px per velocità, bilateral filter.
2. Stima del colore del bordo (mediana di una cornice del 3% sui lati) e segmentazione per differenza dal bordo in LAB + soglia di Otsu. In alternativa Canny + chiusura.
3. Contorno più grande → quadrilatero (come in §4.2).
4. Se la ricerca fallisce o l'area è < 20% → si usano gli angoli dell'immagine intera (caso "immagine già ritagliata" o "disegno").
5. Nell'interfaccia i 4 punti proposti sono **trascinabili**; il batch usa sempre quelli automatici.
6. Raddrizzamento: `warpPerspective` verso un rettangolo con rapporto `larghezza_mosaico_cm / altezza_mosaico_cm`, alla risoluzione nativa massima.

I PNG con trasparenza (es. `M21.png`) mantengono il canale alpha come maschera.

### 5.2 Scala

```
px_per_cm   = larghezza_sfondo_px / larghezza_sfondo_cm
mosaico_px  = (larghezza_mosaico_cm × px_per_cm, altezza_mosaico_cm × px_per_cm)
```

`larghezza_sfondo_cm` è la larghezza reale dell'**intera foto** (es. "la scrivania inquadrata misura 120 cm"). È un'approssimazione valida per foto dall'alto. Se l'area indicata differisce di oltre il 15% dalla grandezza calcolata del mosaico, l'interfaccia mostra un avviso non bloccante ("Il mosaico risulterà più grande/piccolo dell'area segnata").

### 5.3 Posizionamento in prospettiva (`geometry.placement_quad`)

1. Dall'area `Q` si stima il rettangolo del piano `R` (larghezza = media dei lati alto/basso, altezza = media dei lati sinistro/destro).
2. Si calcola l'omografia `H: R → Q`.
3. Nel piano si costruisce il rettangolo del mosaico `mosaico_px`, centrato in `R`, con lo spostamento e la rotazione di `ComposeParams`.
4. I suoi 4 angoli vengono proiettati con `H`, e si ottiene il quadrilatero di destinazione.
5. `cv2.getPerspectiveTransform(mosaico_raddrizzato → destinazione)` + `warpPerspective` (INTER_LANCZOS4), con una maschera alpha antialiasata (bordo sfumato di 1 px).

Così un'unica logica gestisce sia le foto dall'alto (H ≈ similitudine) sia quelle leggermente inclinate.

### 5.4 Effetti (`effects.py`), applicati in quest'ordine

1. **Riempimento del verde residuo**: maschera verde − maschera del mosaico, dilatata di 3 px → `cv2.inpaint` (TELEA). Sui bordi del mosaico si applica un despill (riduzione del canale G in eccesso).
2. **Ombra proiettata**: maschera alpha spostata di `ombra_distanza` lungo `ombra_direzione`, sfocata (gaussiana, raggio da `ombra_morbidezza`), applicata in moltiplicazione sullo sfondo con `ombra_opacita`.
3. **Ombra di contatto**: maschera appena dilatata, poco sfocata, opacità ~0,35. Toglie l'effetto "adesivo".
4. **Spessore** (opzionale, `spessore_mm` > 0): un bordo più scuro di qualche px sul lato opposto alla luce simula lo spessore delle tessere.
5. **Adattamento luce e colore**: si confrontano media e deviazione di L, a, b (LAB) del mosaico con un anello di sfondo intorno all'area, e il mosaico viene spostato verso quei valori con intensità `armonizzazione` (predefinita 0,3, così il colore originale resta riconoscibile). Poi si applicano `luminosita` e `temperatura` manuali.
6. **Grana** (opzionale): rumore leggero uguale a quello stimato sullo sfondo, perché il mosaico non sembri "troppo pulito".

---

## 6. Parametri e integrazione con Claude

### 6.1 `ComposeParams`

| Campo | Tipo / intervallo | Default | Significato |
|---|---|---|---|
| `rotazione_gradi` | -180…180 | 0 | Rotazione extra nel piano |
| `offset_x_cm`, `offset_y_cm` | float | 0 | Spostamento dal centro dell'area |
| `ombra_direzione_gradi` | 0…360 (0 = destra, 90 = basso) | 135 | Verso dove cade l'ombra |
| `ombra_distanza_cm` | 0…5 | 0,6 | Distanza dell'ombra |
| `ombra_morbidezza` | 0…1 | 0,5 | Sfocatura |
| `ombra_opacita` | 0…1 | 0,45 | Intensità |
| `spessore_mm` | 0…15 | 4 | Spessore simulato |
| `luminosita` | -0,5…0,5 | 0 | Correzione manuale |
| `temperatura` | -0,5…0,5 | 0 | Più freddo/caldo |
| `armonizzazione` | 0…1 | 0,3 | Adattamento alla luce dello sfondo |
| `grana` | 0…1 | 0 | Rumore fotografico |

Nell'interfaccia ogni campo è un cursore, nascosto sotto "Regolazioni avanzate". Le istruzioni in testo libero li compilano da sole.

### 6.2 Istruzioni → parametri (`instructions.parse_instructions`)

- **Modello**: `claude-haiku-5-5`, con `output_config.effort = "low"` (il compito è semplice).
- **Output strutturato**: `output_config.format` con lo JSON Schema di `ComposeParams` (con l'SDK Python si usa `client.messages.parse()` e la validazione è automatica). Tutti i campi sono opzionali: Claude restituisce **solo quelli citati**, e gli altri restano ai valori correnti.
- **Prompt di sistema** (fisso, quindi cache-friendly): spiega i campi in italiano, con esempi ("ombra a sinistra" → `ombra_direzione_gradi: 180`; "ombra più netta" → `ombra_morbidezza: 0.2`). Ai valori fuori intervallo viene applicato il clamp lato client.
- **Cache locale**: chiave = hash(istruzioni normalizzate + versione dello schema), salvata su file JSON nella cartella cache utente. Nel batch, cento righe con le stesse istruzioni fanno una sola chiamata.
- **Servizio**: `Settings.provider` = `anthropic` (SDK) oppure `openrouter` (`POST https://openrouter.ai/api/v1/chat/completions` con `httpx`, già installato con l'SDK; modelli `openrouter_model_instructions|light`, default `anthropic/claude-haiku-5.5` e `anthropic/claude-sonnet-5.5`, slug verificati sull'elenco pubblico `/api/v1/models`). Output con `response_format` json_schema strict; se il modello lo rifiuta si riprova una volta senza e il JSON si estrae dal testo. Chiave in keyring con nome separato (fallback `OPENROUTER_API_KEY`); la cache include servizio e modello. `verify_api_key` per OpenRouter usa `GET /api/v1/key`.
- **Errori**: se manca la chiave, se c'è un errore di rete o una risposta non valida → si prosegue con i parametri correnti e si mostra un avviso discreto. **La generazione non si blocca mai per Claude.**

### 6.3 Suggerimento della luce (opzionale, `instructions.suggest_light`)

- Pulsante "Suggerisci luce dallo sfondo" e, nel batch, una volta per ogni sfondo diverso, con cache per hash dell'immagine.
- **Modello**: `claude-sonnet-5-5` (migliore per le immagini). Lo sfondo viene ridotto a 1024 px sul lato lungo e inviato come immagine base64.
- **Output strutturato**: `ombra_direzione_gradi`, `ombra_morbidezza`, `ombra_opacita`, stimati dalle ombre degli attrezzi già presenti nella foto.

### 6.4 Costi stimati (prezzi API del listino Anthropic, ottobre 2026)

| Chiamata | Token indicativi | Costo per chiamata |
|---|---|---|
| Istruzioni, Haiku 5.5 ($0,10 / $0,50 per milione) | ~1.500 in / ~300 out | ≈ $0,0003 |
| Luce, Sonnet 5.5 ($2 / $10 per milione) | ~2.000 in / ~400 out | ≈ $0,008 |

Anche con migliaia di immagini al mese, e grazie alla cache, la spesa resta di pochi dollari: molto sotto i **100 $/mese** disponibili. I modelli si possono cambiare nelle impostazioni avanzate (es. `claude-opus-5-5` se servisse più qualità sulla luce). Prima di implementare, verificare con l'SDK la sintassi corrente di `output_config` e degli ID dei modelli.

---

## 7. Modalità batch

### 7.1 Formato del file (CSV o XLSX)

| Colonna | Obbligatoria | Esempio | Note |
|---|---|---|---|
| `sfondo` | sì | `sfondi/MARMO 1.png` | Relativo alla cartella del file batch, oppure assoluto |
| `mosaico` | sì | `mosaici/M30.jpg` | Come sopra |
| `larghezza_sfondo_cm` | sì | `120` | Larghezza reale dell'intera foto di sfondo |
| `larghezza_mosaico_cm` | sì | `30` | |
| `altezza_mosaico_cm` | sì | `20` | |
| `area` | no | `812,540;1310,540;1310,880;812,880` | Vuota = cerca il rettangolo verde. Punti in pixel, ordine qualsiasi |
| `istruzioni` | no | `ombra morbida verso destra` | Testo libero |
| `preset` | no | `shopify` · `etsy` · `custom 1600x1200 png` | Vuoto = preset scelto nell'interfaccia |
| `nome_output` | no | `M30_marmo1` | Vuoto = `<mosaico>_<sfondo>` |
| `scontorno` | no | `auto` · `rettangolo` · `forma` | Vuoto = `auto`: usa la forma reale del mosaico (bordi irregolari, tondo, PNG trasparente) solo se si discosta dal rettangolo, altrimenti il rettangolo |

- I CSV vengono letti con rilevamento automatico del separatore (`,` o `;`, quello usato dall'Excel italiano). Le virgole decimali sono accettate (`30,5`).
- Intestazioni case-insensitive; spazi e accenti normalizzati.

### 7.2 Esecuzione (`batch.run_batch`)

1. Validazione di tutte le righe **prima** di iniziare: file mancanti, numeri non validi. Gli errori vengono mostrati in tabella e le righe non valide saltate.
2. L'elaborazione avviene in un `QThread` (o pool di processi con `concurrent.futures`, max = CPU−1), con avanzamento per riga e pulsante "Interrompi".
3. Una riga che fallisce **non ferma** le altre.
4. Alla fine, nella cartella di output viene scritto `report_AAAAMMGG_HHMM.csv` con le colonne originali + `stato` + `errore` + `file_generato`.
5. Pulsante "Apri cartella risultati".

Da CLI (sviluppo): `python -m arloc batch percorso/file.xlsx --out risultati/`.

---

## 8. Preset di output (`presets.py`)

| Preset | Dimensioni | Formato | Note |
|---|---|---|---|
| Shopify | 2048 × 2048 | JPG, qualità 90, sRGB | Quadrato, consigliato da Shopify |
| Etsy | 2700 × 2025 | JPG, qualità 90, sRGB | 4:3, lato corto ≥ 2000 px |
| Custom | L × A a scelta | JPG / PNG / WEBP | Definito dall'utente, salvato nelle impostazioni |

Adattamento: **ritaglio "cover" centrato sul mosaico**, così il soggetto resta al centro, con clamp ai bordi dell'immagine. Se lo sfondo è più piccolo del preset si ingrandisce con Lanczos e si mostra un avviso. I metadati EXIF vengono rimossi e il profilo è convertito in sRGB.

---

## 9. Interfaccia

Principi: **un solo percorso evidente**, passi numerati, niente gergo tecnico, opzioni avanzate nascoste.

```
┌────────────────────────────────────────────────────────────────────────┐
│  Arloc                                [ Singola | Batch ]      ⚙       │
├──────────────────────────┬─────────────────────────────────────────────┤
│ ① Sfondo                 │                                             │
│   [ Scegli immagine… ]   │                                             │
│   Area: ✓ verde trovata  │          ANTEPRIMA GRANDE                   │
│   Larghezza reale [120]cm│   (sfondo con area evidenziata, punti       │
│                          │    trascinabili; dopo "Genera" mostra il    │
│ ② Mosaico                │    risultato, con un interruttore           │
│   [ Scegli immagine… ]   │    Prima/Dopo)                              │
│   Misure [30] × [20] cm  │                                             │
│                          │                                             │
│ ③ Istruzioni (opz.)      │                                             │
│   [ testo libero…      ] │                                             │
│   ▸ Regolazioni avanzate │                                             │
│                          │                                             │
│ ④ Formato                │                                             │
│   (Shopify)(Etsy)(Custom)│                                             │
│                          ├─────────────────────────────────────────────┤
│   [     GENERA      ]    │  Vista: [Sfondo] [Mosaico] [Risultato]  🔍  │
│   [ Salva immagine… ]    │                                             │
└──────────────────────────┴─────────────────────────────────────────────┘
```

- **Pannello sinistro** largo ~340 px, fisso. Ogni passo è una "card" con un segno di spunta quando è completo. "Genera" resta disabilitato finché i passi 1, 2 e 4 non sono completi, e un testo dice cosa manca.
- **Anteprima**: `QGraphicsView` con zoom (rotella) e pan. In vista "Sfondo" si cliccano o trascinano i 4 punti dell'area (se non c'è il verde); in vista "Mosaico" i 4 angoli del ritaglio. Il pulsante "Ripristina automatico" annulla le modifiche.
- **Anteprima veloce**: le regolazioni dei cursori ricompongono su una versione ridotta (~1200 px) con un debounce di 200 ms; "Genera" e "Salva" lavorano a piena risoluzione.
- **Scheda Batch**: area di drop / "Scegli file…", tabella (riga, sfondo, mosaico, stato con icona), barra di avanzamento, "Avvia" / "Interrompi" / "Apri cartella risultati" e "Scarica modello" (copia di `templates/modello_batch.xlsx`).
- **Impostazioni (⚙)**: chiave API Claude (campo password + "Verifica"), cartella di output predefinita, preset Custom, modelli avanzati.
- **Tema**: chiaro, neutro (grigi caldi), un solo colore d'accento per l'azione principale, font di sistema, spaziatura a griglia di 8 px, angoli arrotondati di 8 px. Tutto in `style.qss`.
- Si ricordano le ultime cartelle e l'ultimo preset (QSettings).
- I messaggi di errore sono in italiano semplice e dicono cosa fare ("Non trovo il rettangolo verde: clicca i 4 angoli dell'area sull'immagine").

---

## 10. Test, packaging e rilascio

### Test (pochi e mirati)
- `test_detect.py`: area verde trovata su un'immagine sintetica, anche ruotata o in prospettiva.
- `test_geometry.py`: `order_quad`, `px_per_cm`, `placement_quad` (un quadrato in un'area identica produce gli stessi punti).
- `test_batch.py`: parsing di CSV con `;` e virgole decimali, percorsi relativi, colonna `area`.
- La verifica principale è **umana**: `python -m arloc compose` sugli esempi di `examples/` e controllo visivo.

### Packaging
- PyInstaller in modalità `onedir` (avvio più veloce di `onefile`), icona e nome "Arloc".
- **Windows**: cartella zip con `Arloc.exe`; in seguito un installer Inno Setup.
- **macOS**: `Arloc.app` in `.dmg`. Senza firma, al primo avvio serve tasto destro → Apri (va spiegato nel README).
- **Linux**: AppImage.
- CI con GitHub Actions: matrice `windows-latest`, `macos-latest`, `ubuntu-22.04`, eseguita al push di un tag `v*`; gli artefatti vengono allegati alla release.

---

## 11. Milestone

| # | Obiettivo | Risultato verificabile |
|---|---|---|
| M1 | Core di composizione + CLI | `python -m arloc compose --sfondo … --mosaico … --sfondo-cm 120 --mosaico-cm 30x20 --out x.jpg` produce un'immagine credibile con gli esempi |
| M2 | Interfaccia manuale | Dall'app si genera e salva una composizione, con correzione dei punti e cursori |
| M3 | Batch | Un XLSX di 10 righe genera 10 immagini + report, anche con righe sbagliate |
| M4 | Claude | Le istruzioni in testo libero modificano l'ombra; il suggerimento della luce funziona; tutto funziona anche senza chiave |
| M5 | Distribuzione | Eseguibili per i 3 sistemi, che si avviano su una macchina pulita |

## 12. Rischi e note

- **Scala approssimata** se la foto non è proprio dall'alto: si accetta, con l'avviso del §5.2 e la possibilità di correggere a mano.
- **Ritaglio automatico** difficile se il mosaico ha lo stesso colore del bordo: per questo c'è la correzione manuale.
- **Verde nel mosaico stesso**: la maschera verde si applica solo allo sfondo, mai al mosaico.
- **File molto grandi** (> 40 MP): l'anteprima lavora sempre su una copia ridotta.

## Scontorno del mosaico
`core/cutout.py`: `cutout_mosaic(img, quad=None)` lavora su una copia di ~1000 px: GrabCut inizializzato dalla zona con "grana" (`detect.texture_mask`, ripulita da strisce sottili come le venature del pavimento) e dalla cornice dell'immagine come sfondo certo; poi pulizia morfologica, componente più grande, riempimento dei buchi interni e bordo sfumato, riportati a piena risoluzione. Con alpha significativo si usa l'alpha. Modalità `auto` (forma se la maschera copre meno del 92% del quadrilatero o c'è alpha), `rettangolo`, `forma`. In composizione l'immagine e la maschera sono raddrizzate con la stessa omografia e la maschera diventa l'alpha; le misure in cm restano riferite al rettangolo del quadrilatero (per le forme tonde, il rettangolo che le racchiude).
