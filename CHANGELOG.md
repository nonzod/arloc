# Changelog

Tutte le modifiche rilevanti del progetto sono annotate in questo file.
Formato: [Keep a Changelog](https://keepachangelog.com/it/1.1.0/), versioni secondo [Semantic Versioning](https://semver.org/lang/it/).

## [Unreleased]

### Aggiunto
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

### Corretto
- L'avviso "mosaico più piccolo dell'area" compare solo se l'area è un rettangolo verde.
- Impostazioni: i campi del Formato Custom non si sovrappongono più (il dialogo prende l'altezza necessaria invece del limite di 2/3 dello schermo di `adjustSize`).
- Campi in cm: segnaposto corto "– cm" (prima "da inserire" veniva tagliato).
- Dipendenza `httpx2` dichiarata esplicitamente (usata per OpenRouter).
