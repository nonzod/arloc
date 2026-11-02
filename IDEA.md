# Arloc

Autore: Nicola Tomassoni <io@nicolatomassoni.it>

## Descrizione

Il progetto ha come scopo quello di creare un semplice software per fare inpaint con lo scopo di posizionare foto di mosaici reale e/o disegnati su immagini usate come sfondo.
Il caso d'uso è posizionare il disegno di un mosaico su una scrivania composta con gli attrezzi per la realizzazione, viene fornita l'immagine del mosaico, l'immagine di sfondo, le dimensioni del mosaico ed eventuali istruzioni per correggere ombre e prospettiva del mosaico.

Dovremmo avere due modalità di funzionamento, uno manuale, cioè via interfaccia viene caricata la foto di sfondo, la foto del mosaico, le dimensioni e le istruzioni, si clicca su "genera" e veiene generata la composizione.
L'altra modalità è batch, in un file csv o excel sono presenti, per ogni riga, i riferimenti all'immagine sfondo, del mosaico, dimensioni e istruzioni aggiuntive.

## Cosa definire

Il modello da usare, abbiamo 100$ al mese di API Claude da usare e valutare se è necessario usare un altro modello vision più performante.
Per essere più precisi vorrei definire nell'immagine di sfondo l'area dove inserire il mosaico, in pratica fare inpaint, quindi definire le specifiche sulla creazione dell'immagine di sfondo, deve vere un'area bianca/rossa/verde sul punto dove fare inpaint?

## Requisiti

Il software deve girare su windows, su linux e su mac.
Deve essere molto semplice e utilizzabile da personale assolutamente non esperto.
Avere dei preset di output al momento Shopify, Etsy e Custom (viene definita w, h e formato).
Mantenere il progetto molto semplice e scalabile, non esagerare con i test del codice diamo priorità ad avere qualcosa di funzionante e testabile da umani.
UI chiara, moderna e ordinata, non posizionare elementi a caso ma studiarne la composizione migliore.

## Altre informazioni

Generare README.md a solo uso umano per l'utente finale, niente dettagli sul codice o sviluppo.
In examples/ ci sono esempi di sfondi e foto di mosaici.
Generare un AGENTS.md con le informazioni base e le indicazioni relative all'aggiornamento continuo del file ROADMAP e CHANGELOG per segnare l'andamento dello sviluppo.
