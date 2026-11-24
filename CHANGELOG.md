# Changelog

Tutte le modifiche rilevanti del progetto sono annotate in questo file.
Formato: [Keep a Changelog](https://keepachangelog.com/it/1.1.0/), versioni secondo [Semantic Versioning](https://semver.org/lang/it/).

## [Unreleased]

### Aggiunto
- Verifica dei modelli nelle Impostazioni: "Verifica" controlla la chiave e ogni modello configurato per il servizio scelto, con un esito per riga (✓ / ⚠ / ✗) in italiano semplice: modello inesistente (con fino a 3 nomi simili adatti), modello che genera immagini al posto del testo, modello che non legge immagini, risposte strutturate non supportate. OpenRouter: elenco pubblico `/api/v1/models` (in cache per la sessione); Anthropic: `client.models.retrieve`. Funzione core `instructions.check_models(settings, key)`. Anche all'uso, se OpenRouter dice che il modello non esiste o non accetta immagini, il messaggio nomina il modello e dice cosa fare.
- Ritocco AI finale (SPERIMENTALE, spento di default, solo OpenRouter): un modello che riceve e restituisce immagini (default `google/gemini-3.1-flash-image`, campo "Modello per il ritocco" in Modelli avanzati) armonizza luce, ombre e colore attorno al mosaico. Il mosaico è protetto: se l'immagine ricevuta è spostata o deformata si scarta il ritocco, altrimenti dentro la maschera del mosaico si rimettono i pixel originali (correzione di luminosità max ±10%, bordo sfumato). Cache su disco, mai eccezioni. Interruttore nel passo Istruzioni (con costo stimato dai prezzi di OpenRouter), solo su GENERA e Salva, vista "Senza ritocco AI" per il confronto; colonna batch facoltativa `ritocco_ai` (sì/no), opzione CLI `--ritocco-ai`; il ritocco precede il preset. `ComposeResult.mosaic_mask` (nuovo, facoltativo) e `Job.ritocco_ai`.
- Misure automatiche (meno precise, meno lavoro): nessuna misura in cm, il mosaico mantiene le proprie proporzioni e riempie lo spazio dell'area (`Job.misure`, nuova regolazione `riempimento` 0,5-1,0, "Riempimento area"). Selettore "Misure: Automatiche | Reali (cm)" nel passo Mosaico (default Automatiche, scelta ricordata), CLI `--misure auto|reali` con `--sfondo-cm`/`--mosaico-cm` facoltativi, batch con colonne cm vuote = automatiche (errore se compilate solo in parte) e colonna facoltativa `misure`.
- OpenRouter come servizio AI alternativo ad Anthropic (istruzioni a parole e suggerimento luce): selettore "Servizio AI" nelle Impostazioni, chiave separata nel portachiavi (fallback `OPENROUTER_API_KEY`), modelli predefiniti `anthropic/claude-haiku-5.5` e `anthropic/claude-sonnet-5.5`; se il modello non accetta lo schema JSON si riprova senza.
- Campi di input: il segnaposto sparisce quando il campo prende il focus e ritorna se resta vuoto (filtro unico in `arloc/ui/common.py`, vale per tutti i campi, anche "da inserire" degli spinbox); stile input rivisto (focus con bordo d'accento, hover, altezze uniformi, stato disabilitato, segnaposto grigio).
- Scontorno automatico del mosaico (`arloc/core/cutout.py`): maschera con la forma reale (bordi irregolari, mosaici tondi o sagomati, PNG trasparenti) con GrabCut guidato dalla "grana" delle fughe; modalità `auto` / `rettangolo` / `forma` (`Job.scontorno`, `Job.mosaico_maschera`), opzione CLI `--scontorno`, colonna batch facoltativa `scontorno`.
- Vista Mosaico: selettore Scontorno, velo sulla zona esclusa, pennello Aggiungi/Togli con dimensione regolabile, Annulla e Ripristina automatico; il calcolo gira in background.
- Documento di implementazione (`IMPLEMENTAZIONE.md`): motore ibrido (composizione locale + Claude per le istruzioni), area verde o 4 punti, scala reale dalla larghezza dello sfondo, PySide6, preset Shopify/Etsy/Custom.
- `README.md` per l'utente finale, `AGENTS.md`, `ROADMAP.md`.
- Core di composizione (`arloc/core`): caricamento immagini, ricerca area verde, ritaglio automatico del mosaico, scala reale, prospettiva, ombre, spessore, armonizzazione colore, preset Shopify/Etsy/Custom.
- CLI `python -m arloc compose` e `python -m arloc batch`.
- Batch da CSV/XLSX con report; modelli in `templates/` (con area già indicata per gli sfondi d'esempio).
- Integrazione Claude: istruzioni → parametri (Haiku 5.5) e suggerimento luce (Sonnet 5.5), con cache; chiave API nel portachiavi.
- Interfaccia PySide6: passi numerati, anteprima con maniglie, regolazioni avanzate con anteprima veloce, scheda Batch, Impostazioni.
- Packaging: spec PyInstaller e workflow GitHub Actions (non ancora eseguiti).
- `CONTRACTS.md`: firme pubbliche tra i moduli.
- Packaging: icona dell'app (finestra, exe Windows, app macOS, AppImage) generata da `packaging/make_icon.py`; build PyInstaller provato su Linux.

### Modificato
- Anteprima e generazione più veloci (misurati su esempi con maschera già calcolata, come nella GUI: anteprima da 3 a 5 volte più rapida, ~40–130 ms; immagine finale 5000 px da 5,4 s a 1,3 s). Sfondo, mosaico e rettangolo verde restano in memoria tra un'anteprima e l'altra; gli effetti lavorano solo sulla zona del mosaico; l'anello di armonizzazione usa `distanceTransform` invece di una dilatazione con un kernel enorme; l'inpaint del verde lavora solo dove serve. Risultati identici a prima (differenze ≤ 3 livelli su 255; la grana cambia solo la disposizione casuale, non l'intensità).
- Servizi AI riorganizzati: un oggetto per servizio (`core/ai.py`: Anthropic, OpenRouter) con le stesse funzioni, errori dalle eccezioni tipizzate dell'SDK Anthropic (prima dal nome della classe) e messaggi in italiano scritti in un solo punto; client e connessioni riusati tra le chiamate; con OpenRouter, se si sa già che il modello non supporta le risposte strutturate, niente tentativo a vuoto. Il suggerimento luce usa l'immagine già in memoria.
- Cache delle risposte AI unificata (`core/cache.py`): un file per risposta in `istruzioni/`, `luce/`, `ritocco/`, con limite di dimensione (prima un unico JSON che cresceva senza limite). La vecchia cache viene ignorata.
- Sequenza istruzioni → composizione → ritocco AI scritta una volta sola (`core/pipeline.py`) e usata da GUI, batch e CLI. `Settings.model(ruolo)`, `settings.get_key/set_key(servizio)`, `imageio.downscale/encode_jpeg` al posto di codice ripetuto.

### Corretto
- Batch dalla GUI: le istruzioni in testo libero si applicano anche con OpenRouter (prima si controllava solo la chiave Anthropic).
- Impostazioni: il contenuto scorre se lo schermo è basso (con modelli avanzati ed esito della verifica il dialogo non si schiaccia più).
- Pannello dei passi: il selettore Misure non allarga più il pannello oltre i 340 px (prima il bordo destro e i valori dei cursori venivano tagliati).
- L'avviso "mosaico più piccolo dell'area" compare solo se l'area è un rettangolo verde.
- Impostazioni: i campi del Formato Custom non si sovrappongono più (il dialogo prende l'altezza necessaria invece del limite di 2/3 dello schermo di `adjustSize`).
- Campi numerici: al click il campo vuoto non mostra più "0,0" (si scrive subito); un valore già presente viene selezionato e si sovrascrive digitando.
- Campi in cm: segnaposto corto "– cm" (prima "da inserire" veniva tagliato).
- Dipendenza `httpx2` dichiarata esplicitamente (usata per OpenRouter).
