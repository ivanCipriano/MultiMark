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
| P0 | scheletro, riconoscimento dei siti (8 canali strutturali + nomi), inventario; P0-bis candidati | fatto |
| P1 | canali 9–14, scrittura LibCST, rinomina, legame, maschera, codice compatto, inserimento e rilevazione, autovalidazione | fatto (in attesa della lettura di Ivan) |
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
| `multimark/channels.py` | i 14 canali: riconoscimento e lettura (opzione `channels`: `mcss8`, `extended`) |
| `multimark/rewrite.py` | scrittura con LibCST delle forme dei siti e rinomina delle variabili (`ScopeProvider`) |
| `multimark/layout.py` | posizioni di bit e maschera di ogni sito (legame per funzione, single run, posizionale) |
| `multimark/sites.py` | ricerca dei siti, sovrapposizioni, rango (§3.3–3.4) |
| `multimark/names.py` | canale dei nomi: variabili sito (anche di modulo), norm, stili V1/V1b, V2/V2b, `StaticProposer` (`data/name_synonyms.json`) |
| `multimark/inventory.py`, `multimark/cli/inventory.py` | inventario dei siti per campione e per dataset |
| `multimark/candidates.py`, `multimark/cli/candidates.py` | P0-bis: conteggio dei canali candidati (23 pattern, solo lettura; vedi `docs/reports/P0bis_candidati.md`) |
| `multimark/config.py` | opzioni di §3.11 e profili `multimark_base()` / `mcss_profile()` |
| `multimark/prf.py`, `codec.py`, `linking.py` | PRF, alfabeto a 6 bit, codice compatto e decodifica per cancellazioni, legame e maschera |
| `multimark/embed.py`, `detect.py` | inserimento (§3.9) e rilevazione (§3.10) |
| `multimark/synthetic.py`, `multimark/cli/selftest.py` | frammenti sintetici e autovalidazione di P1 (`docs/milestone_logs/P1_selftest.txt`) |
| `multimark/cli/demo.py`, `multimark/cli/demo_web.py` | dimostratore P7.d: `mark`, `verify`, `show`, `web` (pagina Streamlit) con le configurazioni congelate |

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

## Inserimento e rilevazione

```python
from multimark.config import multimark_base, mcss_profile
from multimark.embed import embed
from multimark.detect import detect

cfg = multimark_base()  # mcss_profile() per la reimplementazione di MCSS
r = embed(code, "0101…(24 bit)", key, cfg)  # r.code, r.status (OK/PARTIAL/FAILED), r.extra
d = detect(r.code, "0101…", key, cfg, registry_seed=global_seed)  # d.score, d.extra
```

## Dimostratore (P7.d)

`python -m multimark.cli.demo` (o `multimark-demo` dopo `pip install -e .`) marca, verifica e mostra
un file Python con una delle tre configurazioni congelate in P6 (`--preset`):

| Preimpostazione | Metodo | `config_hash` | Soglia τ Qwen / DeepSeek |
|---|---|---|---|
| `mcss_main` | `mcss` | `1d3087c73439` | 1,2621 / 1,2621 |
| `multimark_prudent` (default) | `multimark`, opzioni di B | `e52b040770df` | 1,2274 / 1,3359 |
| `multimark_high_capacity` | `multimark`, opzioni di D | `3fed1f1c1e24` | 1,5423 / 1,6105 |

Le soglie sono quelle congelate del punteggio principale (`N_reg = 1`, decisione `score ≥ τ`), per il
modello scelto con `--model {qwen25_coder_7b,deepseek_coder_6p7b}`. La chiave è un intero di 64 bit
(decimale o `0x…`) letto da `--key-file` (fuori dal repository) o dalla variabile d'ambiente
`MULTIMARK_KEY` (`--key-env` per cambiarla); non si passa mai sulla riga di comando. Il messaggio è
di 24 bit: 24 cifre 0/1, `0x` con al più 6 cifre esadecimali o un decimale. Codici di uscita: 0 fatto
(per `verify`: marchio rilevato), 1 inserimento fallito o marchio non rilevato, 2 errore d'uso.

Esempio 1, chiave nuova e marcatura (scrive `esempio.marked.py` accanto all'originale e non
sovrascrive mai un file esistente):

```bash
python -c "import secrets; print(secrets.randbits(64))" > ~/.multimark_key
python -m multimark.cli.demo mark esempio.py --key-file ~/.multimark_key \
    --preset multimark_prudent --message 0xABCDEF
```

Esempio 2, verifica con il messaggio atteso (punteggio, soglia congelata, decisione, messaggio
della decodifica aperta se c'è; senza `--message` solo la decodifica aperta):

```bash
python -m multimark.cli.demo verify esempio.marked.py --key-file ~/.multimark_key \
    --preset multimark_prudent --message 0xABCDEF --model deepseek_coder_6p7b
```

Esempio 3, chiave dalla variabile d'ambiente; siti letti nel file marcato (funzione, canale, rango,
bit; con V1 e con due bit per nome il secondo bit di una variabile ha canale `names_b1`) e diff fra
originale e marcato:

```bash
export MULTIMARK_KEY="$(cat ~/.multimark_key)"
python -m multimark.cli.demo show esempio.py --preset multimark_prudent   # usa esempio.marked.py
```

I file si leggono in `utf-8-sig`, quindi vanno bene anche quelli con BOM (per esempio scritti da
Windows PowerShell con `Out-File -Encoding utf8`).

### Pagina web

`multimark-demo web` avvia in locale la pagina Streamlit `multimark/cli/demo_web.py`
(`streamlit run`, solo su `127.0.0.1`, porta 8765 di default, `--port` per cambiarla, statistiche
d'uso di Streamlit spente). Streamlit è nell'extra `demo` e si importa solo in quel file: la libreria
e wm-bench non ne dipendono; se manca, `multimark-demo web` stampa come installarlo. La pagina non
carica risorse esterne e funziona senza internet. La chiave si legge solo sul server, da
`--key-file` o da `MULTIMARK_KEY`, e non compare mai nella pagina né nello stato della sessione.

```bash
pip install -e ".[demo]"
multimark-demo web --key-file ~/.multimark_key     # poi http://127.0.0.1:8765
```

Su Windows (PowerShell):

```powershell
pip install -e ".[demo]"
multimark-demo web --key-file "$HOME\.multimark_key"
```

Nella barra laterale: preimpostazione, modello della soglia, linguaggio (solo Python) e messaggio
esadecimale (al più 6 cifre). Al centro: caricamento di un file `.py` o area di testo, «Inserisci
marchio» (originale e marcato affiancati con le righe cambiate evidenziate, siti e bit inseriti,
scaricamento del file marcato), area di testo modificabile con il codice marcato e «Verifica»
(rilevato o non rilevato, punteggio contro la soglia congelata, messaggio estratto contro atteso).
Errori di sintassi, codice vuoto o senza siti compaiono come avvisi.

## Sviluppo

```bash
pytest
ruff check . && ruff format --check .
mypy            # configurato con python_version = 3.9 (serve mypy < 1.16)
```
