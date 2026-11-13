# Reimplementazione di MCSS (`mcss`): deviazioni dal paper

Paper: Choi, Gao, Duan, *Multi-Channel Spread-Spectrum* (arXiv 2607.06009v1; pagine del PDF).
Il profilo `mcss` è lo stesso pacchetto `multimark` con gli interruttori di
`PIPELINE_metodo.md` §3.11 (`multimark.config.mcss_profile`). Ogni deviazione si scrive qui **nel
momento in cui si decide** (`PIPELINE_metodo.md` §1 punto 7); il benchmark la riprende in
`docs/audit/mcss.md` §«Deviazioni dal paper» (P2).

## Deviazioni dal paper

Formato: ID, fase in cui è stata decisa, riferimento al paper, deviazione, motivo, stato.

### Già fissate dalla pipeline (`PIPELINE_metodo.md` §4.2, §3.8)

| ID | Fase | Paper | Deviazione | Stato |
|---|---|---|---|---|
| MD1 | P0 (spec) | p. 8, «ast.unparse» | Lettura sull'`ast`, scrittura con LibCST al posto di `ast.unparse`: commenti e formattazione restano; il pool è identico perché la lettura è la stessa. | scrittura in P1 |
| MD2 | P0 (spec) | p. 5, punti su secp256k1 | PRF HMAC-SHA256: il flusso di Fisher-Yates è `prf_int(K, "fy", str(j))`, `j = 0, 1, …`, consumato in ordine (permutazioni dei primi cicli indipendenti da N; §7 punto I). | P1; da riverificare sul codice ufficiale |
| MD3 | P0 | p. 5, «sorted by type» / «ordered by complexity» | Forme canoniche dei canali 2 e 3 con pareggio: `kind` di §3.3.1; a parità di `kind`, ordine lessicografico del testo `ast.unparse` dell'operando (dipende dai nomi). Implementata in `channels.py` (`canonical="paper"`). Il canale 6 non ha pareggi (la forma dipende dalla posizione della costante), quindi è uguale nei due profili. | **implementata (P0)** |
| MD4 | P0 (spec) | p. 5, «context-inferred suffixes» | Suffisso dei nomi di una parola dal tipo del primo binding (`_count`/`_val`, `_str`, `_list`, `_map`, `_flag`, altrimenti `_val`). | P1 |
| MD5 | P0 (spec) | — | Punteggio continuo per la calibrazione (stesso di `multimark` a `N_reg = 1`, senza maschera); `native_decision` = decodifica riuscita e uguale al messaggio atteso. | P1 |
| MD6 | P0 | p. 8, «100% AST validity» | Condizioni semantiche sui canali (§3.3.1), più strette del paper; la perdita di siti si misura con `--no-guards` dell'inventario. Implementate in `channels.py` (`guards=True`). `--no-guards` toglie solo le condizioni semantiche (purezza, operatori e tipo dell'operando di `aug_assign`, `kind` dell'altro operando di `operand_order`, condizioni su `L` e `x` di `list_comp`, ridefinizione di `list`/`dict`); restano le condizioni che definiscono le forme e quelle di non interferenza (perimetro confermato da Ivan, 13 novembre 2026). | **implementata (P0)**; misura in P0 (Ivan) |
| MD7 | P0 (spec) | p. 3, seme SHA-256 non pubblicato | Matrice del codice compatto nostra (stessa costruzione, seme `posthoc-compact-code-v1`). | P1 |
| MD8 | P0 (spec) | p. 2, figura 1 | Parametri delle funzioni inclusi nel canale dei nomi di `mcss` (`names.include_params=true`). | **implementata (P0)** nel riconoscimento |

### Decise durante P0 (13 novembre 2026)

| ID | Paper | Deviazione / interpretazione | Motivo | Stato |
|---|---|---|---|---|
| MD9 | p. 5, canali 2 e 3 | Con `canonical="paper"`, se i due operandi hanno stesso `kind` **e** stesso testo `ast.unparse` (es. `a < a`) il nodo non è un sito. | Le due forme coincidono: nessun bit si può scrivere né leggere. | implementata |
| MD10 | — (il paper non tratta l'interferenza fra canali) | Regole di non interferenza (§3.3.2 punto 3) applicate anche a `mcss`: un nodo appartiene al più a un sito (vince il canale con numero minore); `operand_order` escluso se l'altra forma creerebbe un sito `aug_assign` (`x = 1 + x`); `ternary` escluso con rami «aug», rami `IfExp` o in posizione di `elif`; `list()` di `L = list()` seguito da un ciclo con `append` escluso da `empty_coll`; il bersaglio di un ciclo `list_comp` in forma 0 non è binding del canale dei nomi. | Senza queste regole la scrittura di un sito cambierebbe il pool (rango e numero dei siti) e la lettura non tornerebbe. | implementata; **confermata da Ivan (13 novembre 2026)** |
| MD11 | p. 5, canale dei nomi | Variabili ammesse secondo §3.6.1, allineate a T1.4 del benchmark: esclusi `global`/`nonlocal`, argomenti con nome e attributi omonimi (in tutto il modulo), nomi con binding non di variabile nella funzione (`import`, `def`, `class`, `except … as`), funzioni con `locals`/`vars`/`eval`/`exec`, `self`/`cls`, nomi che iniziano per `_`, nomi di una lettera. | Il paper non dà una regola; T1.4 e il metodo devono parlare delle stesse variabili. | implementata; **confermata da Ivan (13 novembre 2026)** |
| MD12 | p. 5, canale `list_comp` (Tabella 2) | Condizioni su `L` e `x`: «`expr` e `it` puri rispetto a `L`» significa esattamente «`L` non compare in `expr` né in `it`» (nessun requisito di purezza: `range(n)` va bene); `x` non compare in `it`; `x` non ha **nessun** riferimento nella funzione (lettura o `del`, anche in funzioni annidate, in altre comprehension o in cicli esterni) fuori dalle istruzioni del sito; sono ammessi solo altri binding di `x` come bersaglio. | Una lettura «prima» del ciclo dentro un ciclo esterno è una lettura dopo nel tempo, e nella forma comprehension `x` non sarebbe definita: la lettura «non letto dopo il ciclo» in senso testuale non basta. | implementata; **decisa da Ivan (13 novembre 2026)** |
| MD13 | p. 5, pool in ordine di visita (il paper non usa funzioni) | Riguarda il legame per funzione di `multimark` (in `mcss`, con `linking=positional`, i siti si ordinano per posizione e il caso non si pone). Funzioni con lo stesso `fid` (nome, numero di parametri) condividono le chiavi `(fid, canale, rango)`, quindi stessi `phi` e stessa maschera. Per la sola diagnostica (flip rate) ogni sito porta `dup_index`, la posizione della funzione fra quelle con lo stesso `fid` in ordine di file, che non entra né in `phi` né nella maschera. L'inventario misura il caso con `n_duplicate_fids`. | I voti vanno sugli stessi bit con la stessa maschera e non si contraddicono; ogni disambiguazione (nome della classe, ordinale nel file) romperebbe l'invarianza all'estrazione e al riordino. | implementata (`dup_index`, `n_duplicate_fids`); **decisa da Ivan (13 novembre 2026)** |

### Decise durante P1 (PIPELINE v1.2)

| ID | Paper | Deviazione / interpretazione | Motivo | Stato |
|---|---|---|---|---|
| MD14 | p. 5, «each multi-word variable»; Tabella 3, p. 8 | Variabili di **modulo** nel canale dei nomi di `mcss` (`names.module_level=true`): nomi legati nello scope del modulo (fuori da funzioni, `lambda` e corpi di classe), con le regole (c)–(g) di §3.6.1 più (h) non in `global`, non in `__all__`, non nomi di funzioni, classi o `import` del modulo, e (i) nessun `locals`/`vars`/`eval`/`exec`/`globals` nello scope del modulo. | Il paper non limita le variabili alle funzioni, e senza quelle di modulo la Tabella 3 non è spiegabile sulle soluzioni CodeNet, quasi tutte a livello di modulo (esito di P0, `P0_mcss_selftest.txt`). | implementata nel lettore (passo 0 di P1); rinomina in P1 |
| MD15 | — (il paper non tratta le f-string) | I nodi dentro una f-string (`JoinedStr`) non sono mai siti, in tutti i canali. Applica la regola di §3.1 «un nodo dentro una stringa non è mai un sito». | Prima di Python 3.12 le posizioni `ast` dentro le f-string non sono affidabili, e la scrittura con LibCST ritrova i nodi per posizione. Effetto sul pool: trascurabile (confronti o costanti dentro `{...}`). | implementata (P1) |
