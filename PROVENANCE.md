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
| 2026-11-27 | wm-bench (ramo `posthoc-multimark`) | `8f5588a` | `src/bench/attacks/t1/{common,comments,rename,local_edits,snake_case,tooling}.py`, `t2/{refactor,truncate,truncate_k,dilution}.py`, `t3/remark.py`, `t4/minify.py`, `attacks/tools.py` | `identifiers_in`, `reserved_names`, `NameFactory.random`, `statement_sites`, `remove_comments`, `python_candidates`, `module_candidates`, `norm`, `snake_name`, `LocalEditsAttack`, `RenameAttack`, `SnakeCaseAttack`, catalogo AST Python di `RefactorAttack` (`ForToWhilePython`, `IfElseInversion`, `CompoundAssignment`, `CommutativeSwap`, `ComparisonFlip`), `TruncateAttack`, `TruncateKAttack`, `dilute`, `DilutionAttack`, `RemarkAttack` (post-hoc), `FormatAttack.apply_python`, `LintAttack` con `ToolRunner._ruff`, `MinifyAttack.apply_python` | `multimark/cli/demo_attacks.py` (solo dimostratore) | logica ricopiata, non il codice: tree-sitter sostituito da `ast`/`tokenize` (posizioni da `ast`), solo Python, seme fisso `DEMO_SEED`; T1.4 solo nomi `random`; T2.1 senza le regole Ruff; T2.4 con funzione bersaglio scelta; T2.5 con la raccolta `FUNCTION_POOL` (MBPP `task_id` 2, 5, 8, 9 dalla fixture qui sopra, CC BY 4.0); T1.1, T1.2, T4.1 con black 24.10.0, ruff 0.7.4, python-minifier 2.11.3 dell'extra `demo` (versioni di `requirements-bench-core.lock`), ruff un file alla volta; differenze nel docstring di ogni attacco |
