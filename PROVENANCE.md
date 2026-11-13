# Provenienza del codice ripreso da altri repository

Ogni file, classe o funzione presa da un altro repository (le trasformazioni di Zottarelli nella
versione irrobustita da Simone, `PIPELINE_metodo.md` §2 P8) va annotata qui **al momento
dell'import**. In testa al file copiato va il commento:

```python
# Origine: <repo>@<commit>:<file>::<classe>; modifiche: …
```

Nella tesi la fonte si cita nel capitolo 4.

| Data | Repository | Commit | File d'origine | Classe / funzione | File qui | Modifiche fatte |
|---|---|---|---|---|---|---|
| 2026-11-13 | wm-bench (ramo `posthoc-multimark`) | `843f569` | `packages/bench-contracts/bench_contracts/seeds.py` | `derive_seed` | `multimark/prf.py::derive_seed` | nessuna (copia identica, con docstring nostra): serve alle esche del registro (§3.10.1), che devono coincidere con quelle del benchmark senza dipendere da esso |

