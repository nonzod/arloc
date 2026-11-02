# Arloc

Arloc appoggia la foto di un mosaico su una foto di sfondo, ad esempio una scrivania con gli attrezzi del kit, e crea un'immagine realistica pronta per il tuo negozio online. Il mosaico viene messo alla grandezza giusta, in prospettiva e con la sua ombra.

---

## Installazione

1. Scarica la versione per il tuo computer dalla pagina dei rilasci:
   - **Windows**: `Arloc-windows.zip`. Estrai la cartella e fai doppio clic su `Arloc.exe`.
   - **Mac**: `Arloc-mac.dmg`. Trascina Arloc in Applicazioni. Al **primo avvio** fai clic con il tasto destro sull'icona e scegli **Apri**.
   - **Linux**: `Arloc.AppImage`. Rendilo eseguibile (tasto destro → Proprietà → Permessi) e fai doppio clic.
2. Fatto. Non serve installare altro.

---

## Preparare le foto

### La foto di sfondo
- Scattala **dall'alto**, con una buona luce, lasciando libero lo spazio dove andrà il mosaico.
- Misura quanto è **larga in centimetri** la zona inquadrata (ad esempio la scrivania da un bordo all'altro della foto). Ad Arloc serve per mettere il mosaico alla grandezza giusta.

### Indicare dove va il mosaico
Hai due possibilità:

**A. Rettangolo verde (comodo se usi tante volte lo stesso sfondo)**
Con un programma di grafica disegna un rettangolo **pieno di verde puro** dove andrà il mosaico:
- colore: **#00FF00** (Rosso 0, Verde 255, Blu 0), senza sfumature;
- grande **come il mosaico o poco meno**, mai più grande;
- salva la foto in **PNG**.

Arloc lo trova da solo.

**B. Clic sugli angoli**
Lascia la foto com'è: in Arloc clicchi i 4 angoli della zona direttamente sull'immagine.

### La foto del mosaico
Una foto frontale, il più possibile dritta. Va bene anche se si vedono il nastro o il supporto intorno: Arloc ritaglia il mosaico da solo, e tu puoi correggere il ritaglio trascinando gli angoli.

---

## Creare un'immagine

Segui i passi numerati a sinistra:

1. **Sfondo**: scegli l'immagine e scrivi la sua larghezza reale in cm. Se non c'è il rettangolo verde, clicca i 4 angoli della zona.
2. **Mosaico**: scegli l'immagine e scrivi larghezza e altezza reali in cm. Controlla il ritaglio nella vista "Mosaico".
3. **Istruzioni** (facoltativo): scrivi a parole cosa vuoi, ad esempio:
   - *"ombra morbida verso destra"*
   - *"ruota il mosaico di 10 gradi"*
   - *"luce più calda, ombra più leggera"*

   Oppure apri **Regolazioni avanzate** e usa i cursori.
4. **Formato**: scegli **Shopify**, **Etsy** o **Custom** (scegli tu larghezza, altezza e tipo di file).
5. Premi **GENERA**, guarda il risultato e premi **Salva immagine**.

| Formato | Dimensioni | File |
|---|---|---|
| Shopify | 2048 × 2048 | JPG |
| Etsy | 2700 × 2025 | JPG |
| Custom | a scelta | JPG, PNG o WEBP |

---

## Creare tante immagini insieme (Batch)

1. Apri la scheda **Batch** e premi **Scarica modello** per avere un file Excel già pronto.
2. Compila una riga per ogni immagine da creare:

| Colonna | Cosa scrivere | Esempio |
|---|---|---|
| sfondo | percorso della foto di sfondo | `sfondi/MARMO 1.png` |
| mosaico | percorso della foto del mosaico | `mosaici/M30.jpg` |
| larghezza_sfondo_cm | larghezza reale dello sfondo | `120` |
| larghezza_mosaico_cm | larghezza reale del mosaico | `30` |
| altezza_mosaico_cm | altezza reale del mosaico | `20` |
| area | *(facoltativo)* i 4 angoli in pixel; vuoto se c'è il rettangolo verde | `812,540;1310,540;1310,880;812,880` |
| istruzioni | *(facoltativo)* come nella modalità singola | `ombra verso sinistra` |
| preset | *(facoltativo)* `shopify`, `etsy` oppure `custom 1600x1200 png` | `etsy` |
| nome_output | *(facoltativo)* nome del file da creare | `M30_marmo` |
| scontorno | *(facoltativo)* `auto` (di solito va bene), `rettangolo` oppure `forma` (segue il bordo reale del mosaico) | `forma` |

   I percorsi possono partire dalla cartella in cui si trova il file Excel.
3. Trascina il file in Arloc (oppure **Scegli file…**), scegli la cartella dei risultati e premi **Avvia**.
4. Alla fine trovi le immagini e un file **report** che dice, riga per riga, cosa è andato bene e cosa no.

---

## Istruzioni a parole (facoltativo)

Per capire le istruzioni scritte, Arloc usa l'intelligenza artificiale Claude, direttamente (Anthropic) oppure tramite il servizio OpenRouter. Per attivarla:
1. Apri **⚙ Impostazioni**.
2. Scegli il **Servizio AI** (Anthropic o OpenRouter).
3. Incolla la **chiave API** che ti è stata fornita per quel servizio e premi **Verifica**.

Senza chiave Arloc funziona lo stesso: per le regolazioni usi i cursori.

---

## Problemi frequenti

- **"Non trovo il rettangolo verde"**: controlla che il verde sia proprio #00FF00 e che la foto sia salvata in PNG. In alternativa clicca i 4 angoli.
- **Il mosaico è troppo grande o piccolo**: controlla la larghezza reale dello sfondo e le misure del mosaico.
- **Il ritaglio del mosaico è sbagliato**: nella vista "Mosaico" trascina i 4 angoli nella posizione corretta.
