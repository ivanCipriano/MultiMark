# P0-bis — Canali candidati: esempi di riconoscimento

Passo P0-bis, prima di P1. `multimark/candidates.py` conta, **sull'`ast` e senza trasformare
nulla**, 23 pattern (lettere a–w della richiesta di Ivan) che potrebbero diventare canali. Nessuno
di questi pattern è un canale: il conteggio serve a scegliere quali studiare. Le tabelle qui sotto
sono prodotte dalla libreria (`candidate_hits`) e verificate da
`tests/test_report_p0bis_examples.py`.

## Pattern e forme

| | nome | forma 0 | forma 1 (forma 2) | fonte | nella stima prudente |
|---|---|---|---|---|---|
| a | `else_return` | `if c: return X` / `else: return Y` | `if c: return X` / `return Y` | T16 | f0, f1 |
| b | `range_len` | `for i in range(len(a))` con `a[i]` nel corpo | `for i, x in enumerate(a)` | T38 | f0, f1 |
| c | `square` | `x * x` (`x` puro) | `x ** 2` | T7 | f0, f1 |
| d | `not_eq` | `not a == b` | `a != b` | | f0, f1 |
| e | `len_test` | `len(a) == 0` / `len(a) > 0` | `a` / `not a` in una condizione | | f0 |
| f | `slice_bound` | `a[0:n]` / `a[i:len(a)]` | `a[:n]` / `a[i:]` | T2 | f0, f1 |
| g | `str_method` | `s.split(...)`, `s.join(...)`, `s.strip(...)` ecc. | `str.split(s, ...)` ecc. | T39 | f1 |
| h | `bool_return` | `if c: return True` / `else: return False` | `return bool(c)` (`return <Compare/BoolOp/not>`) | | f0, f1 |
| i | `elif` | `elif` / `else: if` (stesso `ast`) | — | T9 | — |
| j | `nested_if` | `if a: if b:` senza `else` | `if a and b:` senza `else` | T17 | f0, f1 |
| k | `range_zero` | `range(0, n)` | `range(n)` | | f0, f1 |
| l | `or_eq` | `a == b or a == c` | `a in (b, c)` | T6 | f0, f1 |
| m | `identity_comp` | `[x for x in a]` | `list(a)` | T31 | f0, f1 |
| n | `sorted_rev` | `sorted(a)[::-1]` | `sorted(a, reverse=True)` | | f0, f1 |
| o | `str_build` | f-string | `'...'.format(...)` (concatenazione `+` con `str()`) | | f0, f1, f2 |
| p | `bool_cmp` | `a == True`, `a == False`, `a is True`, `a is False` | `a` / `not a` in una condizione (= e.f1) | | — |
| q | `while_break` | `while True:` con un solo `if …: break` in testa | `while not cond:` | | f0, f1 |
| r | `const_pow` | `c1 ** c2` fra costanti (`10**3`) | — | | — |
| s | `get_none` | `d.get(k, None)` | `d.get(k)` | | f0, f1 |
| t | `return_none` | `return None` | `return` | | f0, f1 |
| u | `aug_inc` | `x = x ± c` | `x ±= c` | già `aug_assign` | — |
| v | `max_ternary` | `max(a, b)` | `a if a > b else b` (o `b if a < b else a`) | | f0, f1 |
| w | `empty_str` | `s == ""` | `not s` / `s` in condizione (= e.f1) (`len(s) == 0`, sottoinsieme di e.f0) | | — |

Nella tabella, «stima prudente» indica le forme che si possono trasformare nell'altra senza
conoscere i tipi. Sono quelle sommate ai siti attuali nella stima di capacità della CLI; la CLI
stampa anche la variante «tutte le forme». Le scelte di questa colonna sono nostre: TODO(ivan),
confermarle.

**Limiti dovuti alla lettura sull'`ast`** (il codice si legge solo con `ast`, senza spazi, a capo
o commenti):
- **i**: `elif b:` e `else:` + `if b:` producono lo stesso `ast` (`orelse = [If]`). Si conta
  l'occorrenza con un solo contatore, ma non può essere un canale.
- **r**: `0.5`/`.5` e `1e3`/`1000.0` producono lo stesso `Constant`. Si conta solo `10**3`, la cui
  altra forma (`1000`) non si riconosce come forma: non è un canale.
- **e.f1, p.f1, w.f1**: sono lo stesso contatore (test di verità `a` / `not a` in un `if`,
  `while`, espressione condizionale o `assert`).
- **u** è già il canale `aug_assign`: lo conto solo per confronto e non entra nella stima.

**Sovrapposizioni.** Alcuni nodi contano per più pattern. Sommare i pattern nella stima dà quindi
un limite superiore:
- `range(len(a))` è sia b.f0 sia k.f1;
- `if c: return True else: return False` è sia a.f0 sia h.f0;
- `a != b` (d.f1) può essere già un sito `equality_dir`. Anche questa è un'interferenza fra canali
  da valutare prima di adottare d.

---

## Esempio 1 — HumanEval/12 `longest` (prompt + soluzione canonica)

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

| riga:col | pattern | forma | nodo | nella stima prudente |
|---|---|---|---|---|
| 14:7 | e `len_test` | f1: `a` / `not a` in una condizione | `not strings` | no |
| 14:7 | p `bool_cmp` | f1 (= e.f1) | `not strings` | no |
| 14:7 | w `empty_str` | f1 (= e.f1) | `not strings` | no |
| 15:8 | t `return_none` | f0: `return None` | `return None` | sì |

Siti attuali: `n_sites_total = 2` (1 strutturale, 1 variabile).

**Lettura.**
- Nella stima prudente entra **un solo** candidato, `return None` ↔ `return`.
- Il test `not strings` potrebbe diventare `len(strings) == 0` solo sapendo che `strings` è una
  sequenza: la firma lo dice (`List[str]`), ma il lettore non usa i tipi.
- `max(len(x) for x in strings)` non è v (un solo argomento).
- `len(s) == maxlen` non è e (confronto con una variabile, non con `0`).

Il codice corto resta povero anche di candidati.

---

## Esempio 2 — Funzione in stile LLM con molti pattern

```text
 1  def summarize(records, key=None):
 2      if len(records) == 0:
 3          return None
 4      names = [r for r in records]
 5      result = []
 6      for i in range(len(names)):
 7          name = names[i].strip()
 8          if name == "" or name == "-":
 9              continue
10          if key is not None:
11              if key in name:
12                  result.append(name[0:10])
13          else:
14              result.append(name.lower())
15      total = 0
16      for i, row in enumerate(records):
17          total += row.get("value", None) or 0
18      label = "Total: " + str(total)
19      return sorted(result)[::-1], label
```

| riga:col | pattern | forma | nodo | nella stima prudente |
|---|---|---|---|---|
| 2:7 | e `len_test` | f0: `len(a) == 0` / `len(a) > 0` | `len(records) == 0` | sì |
| 2:7 | w `empty_str` | f2: `len(s) == 0` (sottoinsieme di e.f0) | `len(records) == 0` | no |
| 3:8 | t `return_none` | f0: `return None` | `return None` | sì |
| 4:12 | m `identity_comp` | f0: `[x for x in a]` | `[r for r in records]` | sì |
| 6:4 | b `range_len` | f0: `for i in range(len(a))` con `a[i]` | `for i in range(len(names)):` | sì |
| 6:13 | k `range_zero` | f1: `range(n)` | `range(len(names))` | sì |
| 7:15 | g `str_method` | f0: `s.strip(...)` ecc. | `names[i].strip()` | no |
| 8:11 | l `or_eq` | f0: `a == b or a == c` | `name == "" or name == "-"` | sì |
| 8:11 | w `empty_str` | f0: `s == ""` | `name == ""` | no |
| 12:30 | f `slice_bound` | f0: `a[0:n]` / `a[i:len(a)]` | `name[0:10]` | sì |
| 14:26 | g `str_method` | f0: `s.lower()` ecc. | `name.lower()` | no |
| 16:4 | b `range_len` | f1: `for i, x in enumerate(a)` | `for i, row in enumerate(records):` | sì |
| 17:17 | s `get_none` | f0: `d.get(k, None)` | `row.get("value", None)` | sì |
| 18:12 | o `str_build` | f2: concatenazione `+` con `str()` | `"Total: " + str(total)` | sì |
| 19:11 | n `sorted_rev` | f0: `sorted(a)[::-1]` | `sorted(result)[::-1]` | sì |

Siti attuali: `n_sites_total = 12` (6 strutturali, 6 variabili).

**Lettura.**
- La stima prudente aggiunge fino a 11 siti, ma è un limite superiore: alla riga 6 b.f0 e k.f1
  sono lo stesso costrutto.
- **Non** contano:
  - `if key is not None: if key in name:` (righe 10–11) non è j, perché l'`if` esterno ha un
    `else`;
  - `total += row.get(...) or 0` non è u, perché l'operando non è una costante numerica;
  - `for i, row in enumerate(records)` è b.f1 anche se `i` non si usa.
- Due casi da guardare per la semantica:
  - n.f0 → n.f1 (`sorted(result)[::-1]` e `sorted(result, reverse=True)`) mette in ordine diverso
    gli elementi uguali. Con stringhe uguali non si vede, con chiavi o oggetti sì;
  - l.f0 → l.f1 valuta `name` una volta sola invece di due.

---

## Esempio 3 — Quasi-pattern che non contano

```text
 1  def check(a, b, x, items):
 2      if a:
 3          return True
 4      else:
 5          return False
 6
 7
 8  def near_misses(a, b, x, items):
 9      if a > 0:
10          pass
11      elif b:
12          pass
13      scale = 1e3
14      cube = x ** 3
15      rev = items[::-1]
16      top = max(items)
17      x += b
18      while True:
19          x = x - 1
20          if x < 0:
21              break
22      either = a == 1 or b == 1
23      return a, scale, cube, rev, top, either
```

| riga:col | pattern | forma | nodo | nella stima prudente |
|---|---|---|---|---|
| 2:4 | a `else_return` | f0: `if c: return X` / `else: return Y` | `if a:` | sì |
| 2:4 | h `bool_return` | f0: `if c: return True` / `else: return False` | `if a:` | sì |
| 2:7 | e `len_test` | f1: `a` / `not a` in una condizione | `a` | no |
| 2:7 | p `bool_cmp` | f1 (= e.f1) | `a` | no |
| 2:7 | w `empty_str` | f1 (= e.f1) | `a` | no |
| 9:4 | i `elif` | f0: `elif` / `else: if` (stesso `ast`) | `if a > 0:` | no |
| 11:9 | e `len_test` | f1: `a` / `not a` in una condizione | `b` | no |
| 11:9 | p `bool_cmp` | f1 (= e.f1) | `b` | no |
| 11:9 | w `empty_str` | f1 (= e.f1) | `b` | no |
| 19:8 | u `aug_inc` | f0: `x = x ± c` | `x = x - 1` | no (già `aug_assign`) |

Siti attuali: `n_sites_total = 10` (5 strutturali, 5 variabili).

**Cosa non conta e perché**

| riga | nodo | pattern vicino | perché non conta |
|---|---|---|---|
| 2–5 | `if a: return True else: return False` | a, h | **Conta due volte** (a.f0 e h.f0): è l'esempio di sovrapposizione che rende la stima un limite superiore. |
| 9–12 | `elif b:` | i | Conta, ma l'`ast` è identico a `else:` + `if b:`: non può essere un canale. |
| 13 | `1e3` | r | È un `Constant(1000.0)` come `1000.0`: la scrittura non è visibile sull'`ast`. |
| 14 | `x ** 3` | c | c.f1 vuole esponente `2`. |
| 15 | `items[::-1]` | n | n.f0 vuole `sorted(...)[::-1]`. |
| 16 | `max(items)` | v | v.f0 vuole due argomenti. |
| 17 | `x += b` | u | u vuole una costante numerica (come `aug_assign`). |
| 18–21 | `while True:` … `if x < 0: break` | q | L'`if … break` non è la **prima** istruzione del ciclo: la trasformazione in `while not (x < 0):` cambierebbe il numero di decrementi. |
| 22 | `a == 1 or b == 1` | l | Gli operandi sinistri sono diversi (`a`, `b`). |

---

## Come si lancia (per Ivan, sul cluster)

Gli stessi JSONL dell'inventario, un file per gruppo:

```bash
python -m multimark.cli.candidates \
    --input canonical=<l1_dev_canonical.jsonl> \
    --input qwen=<l1_dev_qwen.jsonl> \
    --input deepseek=<l1_dev_deepseek.jsonl> \
    --summary P0bis_candidates.txt --summary-json P0bis_candidates.json
```

La classifica dei pattern si calcola sui gruppi di `--estimate-groups` presi insieme (default:
tutti). Per ogni gruppo la stima dà la frazione di campioni con `n_sites_total + siti aggiunti`
`≥ 8` e `≥ 13`: con i siti attuali (`k = 0`) e con i primi 3, 5 e 8 pattern, nelle varianti
«prudente» e «tutte le forme».
