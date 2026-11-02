# AGENTS.md

Istruzioni per gli agenti AI (e gli sviluppatori) che lavorano su Arloc.

## Progetto
Arloc è un'app desktop multipiattaforma (Windows, macOS, Linux) che compone la foto di un mosaico su una foto di sfondo, in scala reale, con prospettiva e ombre. Ha una modalità singola (GUI) e una batch (CSV/XLSX). Gli utenti finali **non sono esperti**.

- Idea originale: `IDEA.md`
- Specifica tecnica: `IMPLEMENTAZIONE.md`. **È la fonte di verità**: leggila prima di lavorare.
- Firme pubbliche tra i moduli: `CONTRACTS.md` (tipi condivisi in `arloc/core/models.py`)
- Guida per l'utente: `README.md` (solo per utenti finali, **niente dettagli tecnici**)

## Stack
Python 3.12 · PySide6 · OpenCV (headless) · Pillow · numpy · pandas + openpyxl · anthropic · keyring · platformdirs · uv · PyInstaller

## Struttura
- `arloc/core/`: tutta la logica, **senza import da Qt**. GUI, batch e CLI usano `compose(job)`.
- `arloc/ui/`: solo interfaccia (PySide6), stile in `style.qss`.
- `templates/`: modelli batch per l'utente.
- `examples/`: sfondi e mosaici di prova per le verifiche manuali.

## Comandi
```bash
uv sync                                   # installa le dipendenze
uv run python -m arloc                    # avvia la GUI
uv run python -m arloc compose --help     # composizione da riga di comando
uv run python -m arloc batch file.xlsx --out risultati/
uv run pytest                             # test
```

## Regole di lavoro
- **Semplicità prima di tutto.** Niente astrazioni premature e niente dipendenze superflue. Conta avere qualcosa che funziona e che una persona può provare.
- **Pochi test mirati** (rilevamento, geometria, parsing batch). La verifica principale è visiva, sugli esempi di `examples/`.
- **Interfaccia e messaggi solo in italiano**, semplici, che dicano cosa fare.
- **La generazione non deve mai bloccarsi per colpa di Claude**: senza chiave o rete si usano i parametri correnti.
- Gli ID dei modelli Claude stanno in un solo punto (`core/settings.py`).
- Non committare chiavi API né immagini generate.

## Aggiornamento continuo di ROADMAP e CHANGELOG (obbligatorio)
A ogni modifica significativa, **nello stesso commit**:
1. **`ROADMAP.md`**: spunta (`[x]`) le voci completate, aggiungi quelle nuove nella milestone giusta e sposta in "Idee future" quello che viene rimandato.
2. **`CHANGELOG.md`**: aggiungi una riga sotto `## [Unreleased]` nella sezione adatta (`Aggiunto`, `Modificato`, `Corretto`, `Rimosso`), formato [Keep a Changelog](https://keepachangelog.com/it/1.1.0/). A ogni rilascio rinomina `[Unreleased]` nella versione con la data (`## [0.1.0] - AAAA-MM-GG`) e aprine uno nuovo.
3. Se cambia una decisione tecnica, aggiorna anche `IMPLEMENTAZIONE.md`.
4. Se cambia qualcosa che l'utente vede, aggiorna anche `README.md`.
