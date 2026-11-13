# multimark

Watermark multi-bit post-hoc per codice Python (**MultiMark**, nome provvisorio) e
reimplementazione di Multi-Channel Spread-Spectrum (**MCSS**, arXiv 2607.06009v1) come profilo
dello stesso pacchetto. È il submodule `third_party/multimark` del benchmark `wm-bench`; adapter,
shim e configurazioni del benchmark stanno lì, non qui.

La specifica vincolante è [`PIPELINE_metodo.md`](PIPELINE_metodo.md); le regole di lavoro sono in
[`CLAUDE.md`](CLAUDE.md); le differenze di `mcss` dal paper in
[`docs/mcss_deviations.md`](docs/mcss_deviations.md); il codice ripreso da altri repository in
[`PROVENANCE.md`](PROVENANCE.md).

## Stato

| Fase | Contenuto | Stato |
|---|---|---|
| P0 | scheletro, riconoscimento dei siti (8 canali strutturali + nomi), inventario | fatto |
| P1 | scrittura LibCST, legame, maschera, codice compatto, inserimento e rilevazione | da fare |
| P3 | proponente neurale dei nomi (`names_neural.py`) | da fare |

## Installazione

Python ≥ 3.9. Dipendenza obbligatoria: `libcst`. `torch` e `transformers` solo con l'extra
`[neural]`.

```bash
pip install -e .            # libreria
pip install -e ".[dev]"     # più pytest, hypothesis, ruff, mypy
```

## Moduli

| Modulo | Contenuto |
|---|---|
| `multimark/_astindex.py` | visita in pre-ordine, unità di funzione e `fid` (§3.2), predicati `kind`/puro |
| `multimark/channels.py` | gli 8 canali: riconoscimento e lettura (P0), scrittura (P1) |
| `multimark/sites.py` | ricerca dei siti, sovrapposizioni, rango (§3.3–3.4) |
| `multimark/names.py` | canale dei nomi: quali variabili sono siti (P0); varianti e proponenti (P1) |
| `multimark/inventory.py`, `multimark/cli/inventory.py` | inventario dei siti per campione e per dataset |
| `multimark/config.py` | opzioni di §3.11 e profili `multimark_base()` / `mcss_profile()` |
| `multimark/{prf,codec,linking,embed,detect}.py` | firme di §3 (P1) |

## Inventario dei siti

Input: un JSONL con un oggetto per riga e il codice in un campo (default `code`).

```bash
python -m multimark.cli.inventory --input codes.jsonl --output rows.csv \
    --summary summary.txt --summary-json summary.json --id-field sample_id --label "L1 dev"
```

Opzioni: `--canonical {kind,paper}` (forme canoniche di `multimark` o di `mcss`), `--no-guards`
(senza le condizioni semantiche dei canali, §4.2 punto 6), `--include-params` (parametri nel canale
dei nomi, §7 punto C). Colonne per campione: `n_sites_total` (strutturali + `n_vars`),
`n_sites_structural`, `n_sites_<canale>` per gli 8 canali, `n_vars`, `n_bits_v1` (strutturali +
2·`n_vars`, capacità di `mcss`), `n_functions`, `n_duplicate_fids`, `loc`. Il riepilogo riporta
media, mediana, P25, P75, la frazione di campioni con `n_sites_total ≥ 32`, `≥ 20`, `≥ 13` e la
frazione di campioni con almeno un `fid` duplicato.

## Sviluppo

```bash
pytest
ruff check . && ruff format --check .
mypy            # configurato con python_version = 3.9 (serve mypy < 1.16)
```
