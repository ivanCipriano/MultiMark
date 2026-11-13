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
| MD6 | P0 | p. 8, «100% AST validity» | Condizioni semantiche sui canali (§3.3.1), più strette del paper; la perdita di siti si misura con `--no-guards` dell'inventario. Implementate in `channels.py` (`guards=True`). | **implementata (P0)**; misura in P0 (Ivan) |
| MD7 | P0 (spec) | p. 3, seme SHA-256 non pubblicato | Matrice del codice compatto nostra (stessa costruzione, seme `posthoc-compact-code-v1`). | P1 |
| MD8 | P0 (spec) | p. 2, figura 1 | Parametri delle funzioni inclusi nel canale dei nomi di `mcss` (`names.include_params=true`). | **implementata (P0)** nel riconoscimento |

### Decise durante P0 (13 novembre 2026)

| ID | Paper | Deviazione / interpretazione | Motivo | Stato |
|---|---|---|---|---|
| MD9 | p. 5, canali 2 e 3 | Con `canonical="paper"`, se i due operandi hanno stesso `kind` **e** stesso testo `ast.unparse` (es. `a < a`) il nodo non è un sito. | Le due forme coincidono: nessun bit si può scrivere né leggere. | implementata |
| MD10 | — (il paper non tratta l'interferenza fra canali) | Regole di non interferenza (§3.3.2 punto 3) applicate anche a `mcss`: un nodo appartiene al più a un sito (vince il canale con numero minore); `operand_order` escluso se l'altra forma creerebbe un sito `aug_assign` (`x = 1 + x`); `ternary` escluso con rami «aug», rami `IfExp` o in posizione di `elif`; `list()` di `L = list()` seguito da un ciclo con `append` escluso da `empty_coll`; il bersaglio di un ciclo `list_comp` in forma 0 non è binding del canale dei nomi. | Senza queste regole la scrittura di un sito cambierebbe il pool (rango e numero dei siti) e la lettura non tornerebbe. | implementata; da confermare (TODO(ivan)) |
| MD11 | p. 5, canale dei nomi | Variabili ammesse secondo §3.6.1, allineate a T1.4 del benchmark: esclusi `global`/`nonlocal`, argomenti con nome e attributi omonimi (in tutto il modulo), nomi con binding non di variabile nella funzione (`import`, `def`, `class`, `except … as`), funzioni con `locals`/`vars`/`eval`/`exec`, `self`/`cls`, nomi che iniziano per `_`, nomi di una lettera. | Il paper non dà una regola; T1.4 e il metodo devono parlare delle stesse variabili. | implementata |
