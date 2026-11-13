# P0 — Esempi di riconoscimento dei siti

Report di esempi della fase P0 (`PIPELINE_metodo.md` §1 regola 12). P0 implementa solo il
**riconoscimento** dei siti; `phi`, maschera, parola di codice, inserimento e rilettura arrivano in
P1. Per ognuno dei tre file:

1. il codice di partenza (righe numerate);
2. la tabella dei siti strutturali trovati, con `fid`, canale, rango, posizione e forma letta;
3. la tabella delle variabili del canale dei nomi;
4. la riga dell'inventario;
5. alcuni nodi vicini che **non** sono siti, con la condizione di §3.3.1 o la regola di non
   interferenza che li esclude.

**Come sono fatte le tabelle.** Siti, variabili e inventario sono prodotti dalla libreria
(configurazione di base di `multimark`: `canonical="kind"`, `guards=True`, parametri esclusi dai
nomi). L'ultima colonna, «mcss», riporta la forma letta con `canonical="paper"`: `=` se coincide.
Ogni affermazione delle tabelle «non siti» è verificata in `tests/test_report_p0_examples.py`: se il
codice cambia comportamento, il test fallisce e il report va rigenerato.

**Promemoria.**
- `kind`: `Constant` 0, `Name` 1, `Attribute` 2, `Subscript` 3, `Call` 4, `BinOp`/`UnaryOp` 5,
  altro 6. Nei canali 2 e 3 la forma 0 ha l'operando di `kind` minore a sinistra.
- «Puro» = non contiene `Call`, `Await`, `Yield`, `NamedExpr`, comprehension.
- `fid = (nome, n_params)`, con `self` contato fra i parametri; il nome della classe non entra.
- Rango: indice del sito fra quelli dello stesso canale nella stessa funzione, in ordine di visita.
- Le tabelle dei siti sono nell'ordine di §3.9: funzione, poi canale 1..8, poi rango (non in ordine
  di riga).

---

## Esempio 1 — Funzione corta (HumanEval/3, `below_zero`, prompt + soluzione canonica)

```text
 1  from typing import List
 2
 3
 4  def below_zero(operations: List[int]) -> bool:
 5      """ You're given a list of deposit and withdrawal operations on a bank account that starts with
 6      zero balance. Your task is to detect if at any point the balance of account falls below zero, and
 7      at that point function should return True. Otherwise it should return False.
 8      >>> below_zero([1, 2, 3])
 9      False
10      >>> below_zero([1, 2, -4, 5])
11      True
12      """
13      balance = 0
14
15      for op in operations:
16          balance += op
17          if balance < 0:
18              return True
19
20      return False
```

**Siti strutturali**

| # | fid | canale | rango | riga:col | nodo | forma letta | mcss |
|---|---|---|---|---|---|---|---|
| 1 | `('below_zero', 1)` | 2 `compare_dir` | 0 | 17:11 | `balance < 0` | 1: kind minore a destra (`Name` 1 a sinistra, `Constant` 0 a destra) | = |

**Canale dei nomi**

| fid | rango | variabile | primo binding (riga) |
|---|---|---|---|
| `('below_zero', 1)` | 0 | `balance` | 13 |
| `('below_zero', 1)` | 1 | `op` | 15 |

**Inventario:** `n_sites_structural=1`, `n_vars=2`, `n_sites_total=3`, `n_bits_v1=5`,
`n_functions=1`, `n_duplicate_fids=0`, `loc=8`.
Con il profilo `mcss` (`--canonical paper --include-params`) anche il parametro `operations` è una
variabile sito: `n_bits_v1 = 1 + 2·3 = 7`.

**Nodi vicini che non sono siti**

| riga | nodo | canale candidato | perché non è un sito |
|---|---|---|---|
| 16 | `balance += op` | 1 `aug_assign` | Con `op ∈ {+, -}` l'operando `e` deve essere una costante numerica (§3.3.1 riga 1); qui `e = op` è un `Name`. Il motivo è semantico: con tipi non numerici `x = x + e` e `x += e` non sono equivalenti (aliasing delle liste). Con `--no-guards` diventerebbe un sito (forma 1). |
| 13 | `balance = 0` | 1, 6 | Non è della forma `x = x op e` e non contiene un `BinOp`: nessun canale ha un pattern che lo copra. |
| 15–18 | `for op in operations: …` | 4 `list_comp` | Manca l'istruzione `L = []` subito prima, e il corpo ha due istruzioni invece di un solo `L.append(expr)`. |
| 4 | parametro `operations` | nomi | Condizione (b) di §3.6.1: i parametri sono esclusi nella base di `multimark` (`names.include_params=false`). In `mcss` è un sito (MD8). |
| 5–12 | docstring, compresi `below_zero([1, 2, -4, 5])` e `-4` | tutti | §3.1: la docstring è un `Expr(Constant(str))`; un nodo dentro una stringa non è mai un sito. |
| 1 | `from typing import List` | nomi | Fuori dalle funzioni (`MODULE`) non ci sono siti dei nomi, e un `import` non è un binding di variabile. |

**Lettura.** È il caso tipico del codice corto: **un solo sito strutturale** e due variabili,
3 voti contro `B = 32`. Lo stato all'inserimento sarà `PARTIAL` (§3.9). È la misura che
l'inventario di P0 deve quantificare su L1.

---

## Esempio 2 — Due funzioni e una classe

```text
 1  class Stats:
 2      def __init__(self, values=None):
 3          if values is None:
 4              values = []
 5          self.values = values
 6          self.total = 0
 7
 8      def add(self, value):
 9          self.values.append(value)
10          self.total = self.total + value
11          return self
12
13
14  def mean(values):
15      if len(values) == 0:
16          return None
17      return sum(values) / len(values)
18
19
20  def summary(values, digits=2):
21      stats = Stats(values)
22      scaled = []
23      for item in values:
24          scaled.append(item * 2)
25      avg = mean(values)
26      label = "empty" if avg is None else "ok"
27      spread = max(values) - min(values) if values else 0
28      count = len(values)
29      count -= 1
30      ratio = 100 * count
31      return {"label": label, "avg": round(avg, digits), "ratio": ratio, "spread": spread}
```

Unità di funzione (§3.2), in ordine di visita: `('__init__', 2)`, `('add', 2)`, `('mean', 1)`,
`('summary', 2)`. I metodi sono unità a sé; il corpo della classe fuori dai metodi è `MODULE`.

**Siti strutturali**

| # | fid | canale | rango | riga:col | nodo | forma letta | mcss |
|---|---|---|---|---|---|---|---|
| 1 | `('__init__', 2)` | 7 `empty_coll` | 0 | 4:21 | `[]` | 0: letterale | = |
| 2 | `('__init__', 2)` | 8 `none_check` | 0 | 3:11 | `values is None` | 0: `is` / `is not` | = |
| 3 | `('mean', 1)` | 3 `equality_dir` | 0 | 15:7 | `len(values) == 0` | 1: kind minore a destra (`Call` 4 a sinistra, `Constant` 0 a destra) | = |
| 4 | `('summary', 2)` | 1 `aug_assign` | 0 | 29:4 | `count -= 1` | 1: `x op= e` | = |
| 5 | `('summary', 2)` | 4 `list_comp` | 0 | 22:4 | `scaled = []` (+ righe 23–24) | 0: `L = []` + ciclo con `append` | = |
| 6 | `('summary', 2)` | 5 `ternary` | 0 | 26:4 | `label = "empty" if avg is None else "ok"` | 1: `x = a if t else b` | = |
| 7 | `('summary', 2)` | 6 `operand_order` | 0 | 24:22 | `item * 2` | 0: costante a destra | = |
| 8 | `('summary', 2)` | 6 `operand_order` | 1 | 30:12 | `100 * count` | 1: costante a sinistra | = |
| 9 | `('summary', 2)` | 8 `none_check` | 0 | 26:23 | `avg is None` | 0: `is` / `is not` | = |

Note:
- **#7** sta dentro `expr` del sito `list_comp` #5: non appartiene a quel sito (cambiare la forma
  del ciclo sposta `item * 2` intatto), quindi resta un sito 6 in entrambe le forme.
- **#9** è il `test` del ternario #6: anche lui resta identico nelle due forme del ternario.
- In `equality_dir` il pareggio non si presenta: `kind` diversi, e `mcss` legge la stessa forma.

**Canale dei nomi**

| fid | rango | variabile | primo binding (riga) |
|---|---|---|---|
| `('summary', 2)` | 0 | `stats` | 21 |
| `('summary', 2)` | 1 | `scaled` | 22 |
| `('summary', 2)` | 2 | `avg` | 25 |
| `('summary', 2)` | 3 | `label` | 26 |
| `('summary', 2)` | 4 | `spread` | 27 |
| `('summary', 2)` | 5 | `count` | 28 |
| `('summary', 2)` | 6 | `ratio` | 30 |

**Inventario:** `n_sites_structural=9`, `n_vars=7`, `n_sites_total=16`, `n_bits_v1=23`,
`n_functions=4`, `n_duplicate_fids=0`, `loc=26`.
Con il profilo `mcss` si aggiungono i parametri `value` (di `add`) e `digits`: `n_bits_v1 = 27`.

**Nodi vicini che non sono siti**

| riga | nodo | canale candidato | perché non è un sito |
|---|---|---|---|
| 22 | `[]` di `scaled = []` | 7 `empty_coll` | Sovrapposizione (§3.3.2 punto 3): il nodo appartiene già al sito 4 `list_comp` #5, e vince il canale con numero minore. Il `[]` della riga 4 invece è un sito 7, perché lì non c'è un ciclo con `append` dopo. |
| 3–4 | `if values is None: values = []` | 5 `ternary` | Il pattern richiede un `else` con un'assegnazione allo stesso nome; qui `orelse` è vuoto. Il `Compare` e il `[]` interni restano siti (#2, #1). |
| 2, 4, 14, 20 | variabile `values` | nomi | È parametro (condizione (b)); inoltre compare come attributo `self.values` (condizione (e), controllata in tutto il modulo). Per (e) è esclusa anche in `mcss`, dove i parametri sono ammessi. |
| 10 | `self.total = self.total + value` | 1 `aug_assign`, 6 `operand_order` | Canale 1: il bersaglio deve essere un `Name`, qui è un `Attribute`. Canale 6: nessuno dei due operandi è una costante numerica. |
| 23 | variabile `item` | nomi | È il bersaglio del ciclo di un sito `list_comp` in forma 0: per non interferenza non è un binding (MD10). Nella forma comprehension sarebbe la variabile di una comprehension, che (a) esclude: in entrambe le forme non è un sito. |
| 27 | `spread = max(values) - min(values) if values else 0` | 5 `ternary` | Il ramo `a = max(values) - min(values)` non è puro (contiene `Call`), §3.3.1 riga 5. Con `--no-guards` diventerebbe un sito. |
| 17 | `sum(values) / len(values)` | 6 `operand_order` | Il canale 6 ammette solo `+` e `*`, e serve una costante numerica. |
| 31 | `{"label": …}` | 7 `empty_coll` | Il dizionario non è vuoto. |

---

## Esempio 3 — Costrutti che quasi sono siti

```text
 1  def tricky(x, items, flag):
 2      x = x * 2
 3      x = 1 + x
 4      x = x + flag
 5      if flag:
 6          res = x + 1
 7      elif items:
 8          res = 0
 9      else:
10          res = 1
11      out = []
12      for val in items:
13          out.append(val)
14      print(val)
15      pick = x if flag else (1 if items else 2)
16      both = 1 + 2
17      return 0 < x < 10, flag == True, len(items) < len(out), pick, both, res
18
19
20  def shadow(list):
21      return list()
```

**Siti strutturali** (solo tre: il file è costruito per mostrare le esclusioni)

| # | fid | canale | rango | riga:col | nodo | forma letta | mcss |
|---|---|---|---|---|---|---|---|
| 1 | `('tricky', 3)` | 6 `operand_order` | 0 | 2:8 | `x * 2` | 0: costante a destra | = |
| 2 | `('tricky', 3)` | 6 `operand_order` | 1 | 6:14 | `x + 1` | 0: costante a destra | = |
| 3 | `('tricky', 3)` | 7 `empty_coll` | 0 | 11:10 | `[]` | 0: letterale | = |

**Canale dei nomi**

| fid | rango | variabile | primo binding (riga) |
|---|---|---|---|
| `('tricky', 3)` | 0 | `res` | 6 |
| `('tricky', 3)` | 1 | `out` | 11 |
| `('tricky', 3)` | 2 | `val` | 12 |
| `('tricky', 3)` | 3 | `pick` | 15 |
| `('tricky', 3)` | 4 | `both` | 16 |

**Inventario:** `n_sites_structural=3`, `n_vars=5`, `n_sites_total=8`, `n_bits_v1=13`,
`n_functions=2`, `n_duplicate_fids=0`, `loc=19`.
Con `--no-guards` i siti strutturali diventano 5:
- `x = x * 2` e `x = x + flag` diventano `aug_assign`, e il primo assorbe il sito 6 #1;
- `out = []` + ciclo diventa `list_comp`, e assorbe il sito 7 #3;
- si aggiunge il `list()` della riga 21.

**Nodi vicini che non sono siti**

| riga | nodo | canale candidato | perché non è un sito |
|---|---|---|---|
| 2 | `x = x * 2` (istruzione) | 1 `aug_assign` | `*` è escluso sempre (aliasing e tipi: `l = l * 2` crea una lista nuova, `l *= 2` modifica quella condivisa). Il `BinOp` interno invece **è** sito 6 (#1): `x = 2 * x` non sarebbe sito 1 per lo stesso motivo, quindi non c'è interferenza. |
| 3 | `x = 1 + x` | 1, 6 | Canale 1: `x` non è l'operando sinistro. Canale 6: escluso dalla **regola di non interferenza** (MD10). La forma 0 sarebbe `x = x + 1`, che è un sito 1: scrivere il sito 6 creerebbe un sito di un altro canale. |
| 4 | `x = x + flag` | 1, 6 | Canale 1: con `+` serve una costante numerica. Canale 6: nessuna costante. |
| 5–10 | `if flag: … elif items: … else: …` | 5 `ternary` | L'`If` esterno ha come `orelse` un altro `If`, non un'assegnazione. L'`If` interno (righe 7–10) ha la forma giusta ma è l'unico elemento dell'`orelse` di un `If` (posizione di `elif`), escluso per non interferenza (MD10). La regola vale in entrambe le forme: in forma 0 è un `elif`; in forma 1 `res = 0 if items else 1` sarebbe l'unica istruzione dell'`else`. Così il sito non compare né scompare cambiando forma. Il `x + 1` della riga 6 resta sito 6 (#2). |
| 11–14 | `out = []` + `for val in items: out.append(val)` | 4 `list_comp` | `val` ha un riferimento **fuori dal sito** (`print(val)`, riga 14): MD12. In forma comprehension `val` non sarebbe più definita dopo. Il `[]` allora non appartiene a nessun sito 4 e torna sito 7 (#3); `val` torna binding ordinario, quindi variabile sito. |
| 15 | `pick = x if flag else (1 if items else 2)` | 5 `ternary` | Un ramo è un `IfExp` (MD10). In forma 0 il ramo diventerebbe l'istruzione `pick = 1 if items else 2`, a sua volta candidata ternario (sarebbe un sito se fosse nel ramo `if`, qui cade in posizione di `elif`). Per tenere il pool uguale nelle due forme, un ramo `IfExp` esclude sempre il sito. L'`IfExp` interno non è valore diretto di un'assegnazione, quindi non è un sito. |
| 16 | `1 + 2` | 6 `operand_order` | Serve **esattamente una** costante numerica; qui sono due. |
| 17 | `0 < x < 10` | 2 `compare_dir` | Due operatori: il canale 2 vuole un solo operatore. |
| 17 | `flag == True` | 3 `equality_dir`, 8 `none_check` | Il canale 3 esclude i confronti con `None`, `True`, `False`; il canale 8 riguarda solo `None`. |
| 17 | `len(items) < len(out)` | 2 `compare_dir` | Stesso `kind` (4 e 4): senza forma canonica in `kind` (2D). E comunque entrambi gli operandi non sono puri (al più uno ammesso); per questo non è un sito nemmeno in `mcss`. |
| 21 | `list()` | 7 `empty_coll` | `list` è ridefinito nel modulo (qui è il parametro di `shadow`): `list()` e `[]` non sono più equivalenti. |
| 1 | variabili `x`, `items`, `flag` | nomi | `x`: nome di una lettera (condizione (c)) e parametro. `items`, `flag`: parametri (condizione (b)). In `mcss` `items` e `flag` sono siti, e lo è anche `list` di `shadow`. |

---

## Cosa si vede

- Sul codice corto i siti strutturali sono pochi. L'esempio 1, che è una soluzione reale di
  HumanEval, ne ha uno solo: la capacità viene soprattutto dalle variabili. È il motivo per cui la
  base usa il confronto con il registro (§3.10) e misura la curva per numero di siti.
- In questi tre file `kind` e `paper` leggono le stesse forme. Le differenze fra i due profili
  compaiono solo con operandi dello stesso `kind` (es. `a < b`, sito solo in `mcss`) e nel canale
  dei nomi (parametri).
- Le regole di non interferenza (MD10, MD12) agiscono su costrutti comuni. `x = 1 + x`, gli
  `elif` e le variabili di ciclo lette dopo compaiono anche nel codice generato: l'inventario con e
  senza `--no-guards` misura quanti siti costano.
