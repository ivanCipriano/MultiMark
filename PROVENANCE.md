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
| 2026-11-21 | wm-bench (ramo `posthoc-multimark`) | `3e47f61` | `tests/fixtures/tiny/humanevalplus.jsonl`, `mbppplus.jsonl`, `mbpp_original.jsonl` | dati, non codice: `HumanEval/0..4` (`prompt + canonical_solution`), `Mbpp/2, 3, 4, 6, 7` (`canonical_solution`), MBPP `task_id` 1–10 (`code`) | `tests/fixtures/tiny_functions.jsonl` | solo i campi `source`, `task_id`, `code`; a capo di MBPP resi LF. Licenze: HumanEval MIT, EvalPlus Apache-2.0, MBPP CC BY 4.0 (README della fixture) |
