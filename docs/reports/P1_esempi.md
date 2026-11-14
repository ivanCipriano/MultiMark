# P1 — Esempi di inserimento e rilevazione

Report di esempi della fase P1 (`PIPELINE_metodo.md` §1 regola 12). Per ogni esempio:

1. il codice di partenza;
2. la tabella dei siti: `fid`, canale, rango, riga, forma letta, `phi`, maschera e valore da
   scrivere (`cw[phi] XOR maschera`); per le variabili, il bit del nome attuale e quello richiesto;
3. il messaggio e la parola di codice;
4. il codice marcato, con il diff riga per riga;
5. la rilettura: voti per posizione, concordanza, punteggio, decodifica.

Configurazione di base di `multimark`:
- 14 canali (`channels=extended`), legame per funzione e canale, maschera attiva, forme `kind`;
- nomi V2 con `StaticProposer`, t = 2 (B = 32);
- **[v1.2.2]** matrice del codice compatto `code.matrix=dmin4` (distanza minima 4, §3.8, MD18):
  rispetto alla versione precedente di questo report cambiano i bit di parità della parola di
  codice e quindi la chiave degli esempi;
- registro con `registry_seed = 20261001`.

Messaggio: «gpt4» con l'alfabeto a 6 bit. Chiave K = 20261711, scelta perché ogni sito dei canali
nuovi debba cambiare forma (prima chiave ≥ 20261116 con questa proprietà e con il sito non
scrivibile dell'esempio 3). Tabelle e diff sono prodotti dalla libreria;
`tests/test_report_p1_examples.py` ne verifica i numeri.

**Dove si vede ogni canale nuovo (§3.3.1b)**

| # | canale | esempio | scrittura |
|---|---|---|---|
| 9 | `range_zero` | 2, riga 3 | `range(0, len(values) - width + 1)` → `range(len(values) - width + 1)` |
| 10 | `slice_lower` | 2, riga 11; 3, riga 2 | `samples[0:len(samples)]` → `samples[:len(samples)]`; `evens[:1]` → `evens[0:1]` |
| 11 | `else_return` | 1, riga 14; 3, riga 2 | forma 1 → 0: le istruzioni dopo l'`if` entrano nell'`else` |
| 12 | `nested_if` | 2, riga 17 | `if x is not None: if lo < hi:` → `if x is not None and lo < hi:` |
| 13 | `square` | 2, riga 12 | `sample * sample` → `sample ** 2` |
| 14 | `return_none` | 1, riga 15 | `return None` → `return` |

---

## Esempio 1 — Funzione corta (HumanEval/12 `longest`, prompt + soluzione canonica)

```text
 1  from typing import List, Optional
 2  
 3  
 4  def longest(strings: List[str]) -> Optional[str]:
 5      """ Out of list of strings, return the longest one. Return the first one in case of multiple
 6      strings of the same length. Return None in case the input list is empty.
 7      >>> longest([])
 8  
 9      >>> longest(['a', 'b', 'c'])
10      'a'
11      >>> longest(['a', 'bb', 'ccc'])
12      'ccc'
13      """
14      if not strings:
15          return None
16  
17      maxlen = max(len(x) for x in strings)
18      for s in strings:
19          if len(s) == maxlen:
20              return s
```

| fid | canale | rango | riga | forma letta | `phi` | maschera | da scrivere |
|---|---|---|---|---|---|---|---|
| `('longest', 1)` | equality_dir | 0 | 19 | 1 | 10 | 1 | 0 |
| `('longest', 1)` | else_return | 0 | 14 | 1 | 8 | 1 | 0 |
| `('longest', 1)` | return_none | 0 | 15 | 0 | 13 | 0 | 1 |
| `('longest', 1)` | names (`maxlen`) | 0 | 17 | 0 | 26 | — | 1 |

Messaggio `000110001111010011111000` («gpt4» con l'alfabeto a 6 bit); parola di codice (t = 2, B = 32): `000110001111010011111000 00100100`. Chiave K = 20261711.

Inserimento: stato **PARTIAL**, N = 4 (B = 32), siti saltati 0, variabili rinominate 1, variabili senza candidato 0.

```diff
--- prima
+++ dopo
@@ -14,7 +14,8 @@
     if not strings:
-        return None
+        return
+    else:
 
-    maxlen = max(len(x) for x in strings)
-    for s in strings:
-        if len(s) == maxlen:
-            return s
+        maxlen_count = max(len(x) for x in strings)
+        for s in strings:
+            if maxlen_count == len(s):
+                return s
```

Rilettura (voti per posizione della parola di codice; `·` = nessun voto):

| posizione | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 | 21 | 22 | 23 | 24 | 25 | 26 | 27 | 28 | 29 | 30 | 31 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `cw` | 0 | 0 | 0 | 1 | 1 | 0 | 0 | 0 | 1 | 1 | 1 | 1 | 0 | 1 | 0 | 0 | 1 | 1 | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 1 | 0 | 0 |
| voti | · | · | · | · | · | · | · | · | 1 | · | 1 | · | · | 1 | · | · | · | · | · | · | · | · | · | · | · | · | 1 | · | · | · | · | · |

Concordanza A = 4 su N = 4 voti; punteggio principale (`N_reg = 1`) **1.20** (= −log10 P[Bin(N, 1/2) ≥ A]); `score_nreg16` 1.20, `score_nreg1024` 1.20; decodifica `ambiguous`, cancellazioni 28, `bits_correct` 3/24, messaggio decodificato —.

**Lettura.**
- Quattro siti, tutti scritti; N = 4 contro B = 32, quindi stato `PARTIAL`.
- Il confronto con il messaggio atteso dà A = N = 4, punteggio 4 · log10 2 = 1,20.
- La decodifica aperta non può riuscire: 28 posizioni su 32 non hanno voti.
- È il caso del codice corto di L1: si rileva con l'aggregazione su più campioni (§5.10), non
  sul singolo campione.
- `else_return` in forma 1 → 0 mette in `else` tutte le istruzioni successive, compresa la riga
  vuota che le precedeva; `equality_dir` 1 → 0 scambia i lati del confronto (`maxlen_count ==
  len(s)`).
- La variabile `maxlen` aveva bit 0 e doveva portare 1: il primo candidato valido con bit 1 è
  `maxlen_count` (composizione con un suffisso: il dizionario non ha sinonimi per `maxlen`).

---

## Esempio 2 — Più funzioni (canali 9, 10, 12, 13)

```text
 1  def moving_sums(values, width):
 2      out = []
 3      for i in range(0, len(values) - width + 1):
 4          window = values[i:i + width]
 5          out.append(sum(window))
 6      return out
 7  
 8  
 9  def energy(samples):
10      total = 0.0
11      for sample in samples[0:len(samples)]:
12          total += sample * sample  # potenza istantanea
13      return total
14  
15  
16  def clip(x, lo, hi):
17      if x is not None:
18          if lo < hi:
19              x = max(lo, min(x, hi))
20      return x
```

| fid | canale | rango | riga | forma letta | `phi` | maschera | da scrivere |
|---|---|---|---|---|---|---|---|
| `('moving_sums', 2)` | empty_coll | 0 | 2 | 0 | 2 | 0 | 0 |
| `('moving_sums', 2)` | range_zero | 0 | 3 | 0 | 28 | 1 | 1 |
| `('energy', 1)` | slice_lower | 0 | 11 | 0 | 14 | 1 | 1 |
| `('energy', 1)` | square | 0 | 12 | 0 | 2 | 1 | 1 |
| `('clip', 3)` | none_check | 0 | 17 | 0 | 30 | 0 | 0 |
| `('clip', 3)` | nested_if | 0 | 17 | 0 | 12 | 1 | 1 |
| `('moving_sums', 2)` | names (`out`) | 0 | 2 | 1 | 12 | — | 0 |
| `('moving_sums', 2)` | names (`window`) | 1 | 4 | 1 | 13 | — | 1 |
| `('energy', 1)` | names (`total`) | 0 | 10 | 1 | 20 | — | 1 |
| `('energy', 1)` | names (`sample`) | 1 | 11 | 0 | 21 | — | 0 |

Messaggio `000110001111010011111000` («gpt4» con l'alfabeto a 6 bit); parola di codice (t = 2, B = 32): `000110001111010011111000 00100100`. Chiave K = 20261711.

Inserimento: stato **PARTIAL**, N = 10 (B = 32), siti saltati 0, variabili rinominate 1, variabili senza candidato 0.

```diff
--- prima
+++ dopo
@@ -1,7 +1,7 @@
 def moving_sums(values, width):
-    out = []
-    for i in range(0, len(values) - width + 1):
+    result = []
+    for i in range(len(values) - width + 1):
         window = values[i:i + width]
-        out.append(sum(window))
-    return out
+        result.append(sum(window))
+    return result
 
@@ -10,4 +10,4 @@
     total = 0.0
-    for sample in samples[0:len(samples)]:
-        total += sample * sample  # potenza istantanea
+    for sample in samples[:len(samples)]:
+        total += sample ** 2  # potenza istantanea
     return total
@@ -16,5 +16,4 @@
 def clip(x, lo, hi):
-    if x is not None:
-        if lo < hi:
-            x = max(lo, min(x, hi))
+    if x is not None and lo < hi:
+        x = max(lo, min(x, hi))
     return x
```

Rilettura (voti per posizione della parola di codice; `·` = nessun voto):

| posizione | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 | 21 | 22 | 23 | 24 | 25 | 26 | 27 | 28 | 29 | 30 | 31 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `cw` | 0 | 0 | 0 | 1 | 1 | 0 | 0 | 0 | 1 | 1 | 1 | 1 | 0 | 1 | 0 | 0 | 1 | 1 | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 1 | 0 | 0 |
| voti | · | · | 00 | · | · | · | · | · | · | · | · | · | 00 | 1 | 0 | · | · | · | · | · | 1 | 0 | · | · | · | · | · | · | 0 | · | 0 | · |

Concordanza A = 10 su N = 10 voti; punteggio principale (`N_reg = 1`) **3.01** (= −log10 P[Bin(N, 1/2) ≥ A]); `score_nreg16` 3.01, `score_nreg1024` 3.01; decodifica `ambiguous`, cancellazioni 24, `bits_correct` 6/24, messaggio decodificato —.

**Lettura.**
- Tre funzioni, ognuna col suo legame (`off(f, c)` dipende da nome e numero di parametri):
  estrarre o spostare una funzione non cambia i bit delle altre.
- Tutti i siti strutturali dei canali nuovi cambiano forma.
- `nested_if` 0 → 1 unisce i due test con `and`. Il sito `none_check` (`x is not None`) resta un
  sito a sé, nel test: con questa chiave porta già il bit richiesto e non cambia.
- Il commento in fondo alla riga 12 resta.
- Una sola variabile rinominata, `out` → `result` (dizionario dei sinonimi); `window`, `total` e
  `sample` portano già il bit richiesto.
- A = N = 10, punteggio 3,01. Tutte le esche (16 e 1024) restano sotto o alla pari:
  `score_nreg16` e `score_nreg1024` coincidono col punteggio del messaggio atteso, cioè il
  migliore del registro è il messaggio atteso o un'esca a pari concordanza (vince il messaggio
  atteso).

---

## Esempio 3 — Qualcosa non va: un sito non scrivibile

```text
 1  def first_even(data, flag):
 2      if flag: evens = [v for v in data if v % 2 == 0]; return evens[:1]
 3      result = [w * 2 for w in data]
 4      if flag: picked = [u for u in result]
 5      return result
```

| fid | canale | rango | riga | forma letta | `phi` | maschera | da scrivere |
|---|---|---|---|---|---|---|---|
| `('first_even', 2)` | equality_dir | 0 | 2 | 1 | 7 | 1 | 1 |
| `('first_even', 2)` | list_comp | 0 | 3 | 1 | 9 | 0 | 1 |
| `('first_even', 2)` | list_comp | 1 | 4 | 1 | 10 | 1 | 0 |
| `('first_even', 2)` | operand_order | 0 | 3 | 0 | 16 | 1 | 0 |
| `('first_even', 2)` | slice_lower | 0 | 2 | 1 | 28 | 0 | 0 |
| `('first_even', 2)` | else_return | 0 | 2 | 1 | 21 | 0 | 0 |
| `('first_even', 2)` | names (`evens`) | 0 | 2 | 0 | 7 | — | 0 |
| `('first_even', 2)` | names (`result`) | 1 | 3 | 0 | 8 | — | 1 |
| `('first_even', 2)` | names (`picked`) | 2 | 4 | 1 | 9 | — | 1 |

Messaggio `000110001111010011111000` («gpt4» con l'alfabeto a 6 bit); parola di codice (t = 2, B = 32): `000110001111010011111000 00100100`. Chiave K = 20261711.

Inserimento: stato **PARTIAL**, N = 9 (B = 32), siti saltati 1, variabili rinominate 1, variabili senza candidato 0.

```diff
--- prima
+++ dopo
@@ -1,5 +1,6 @@
 def first_even(data, flag):
-    if flag: evens = [v for v in data if v % 2 == 0]; return evens[:1]
-    result = [w * 2 for w in data]
-    if flag: picked = [u for u in result]
-    return result
+    if flag: evens = [v for v in data if v % 2 == 0]; return evens[0:1]
+    else:
+        output = [w * 2 for w in data]
+        if flag: picked = [u for u in output]
+        return output
```

Rilettura (voti per posizione della parola di codice; `·` = nessun voto):

| posizione | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 | 21 | 22 | 23 | 24 | 25 | 26 | 27 | 28 | 29 | 30 | 31 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `cw` | 0 | 0 | 0 | 1 | 1 | 0 | 0 | 0 | 1 | 1 | 1 | 1 | 0 | 1 | 0 | 0 | 1 | 1 | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 1 | 0 | 0 |
| voti | · | · | · | · | · | · | · | 00 | 1 | 11 | 0 | · | · | · | · | · | 1 | · | · | · | · | 0 | · | · | · | · | · | · | 0 | · | · | · |

Concordanza A = 8 su N = 9 voti; punteggio principale (`N_reg = 1`) **1.71** (= −log10 P[Bin(N, 1/2) ≥ A]); `score_nreg16` 1.71, `score_nreg1024` 2.71; decodifica `ambiguous`, cancellazioni 25, `bits_correct` 5/24, messaggio decodificato —.

**Lettura.**
- **Sito saltato.** La riga 4 `if flag: picked = [u for u in result]` è un sito `list_comp` in
  forma 1. Doveva diventare la forma 0 (ciclo con `append`), ma sta sulla stessa riga dell'`if`
  (`SimpleStatementSuite`): LibCST non può aprire lì un ciclo senza riscrivere l'`if`.
  - Il sito resta com'è e si conta in `skipped_sites = 1`.
  - Alla rilettura è l'unico voto sbagliato: A = 8 su N = 9.
- **Rischio di attribuzione sbagliata a N basso.** Con 9 voti il punteggio del messaggio atteso
  (1,71) è alla pari con la migliore esca del registro a 16, ma sotto quello della migliore esca
  del registro a 1024 (2,71: un'esca concorda con tutti e 9 i voti).
  - Con il registro a 1024, questo campione sarebbe attribuito al messaggio sbagliato.
  - È la misura di `wrong_attribution_rate` (§5.3) e il motivo per cui il punteggio principale è
    quello a `N_reg = 1`.
- `else_return` (riga 2, forma 1 → 0) sposta in `else` anche la riga col sito saltato; il sito
  resta lo stesso (stesso rango, stesso valore).
- `result` → `output` (dizionario dei sinonimi); `evens` e `picked` portano già il bit richiesto.
