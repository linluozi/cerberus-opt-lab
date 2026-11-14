# cerberus-opt-lab — Cerberus re-expands its whole schema on every `validate()`; copying the already-validated schema is 1.7x on upstream's own 2.5 MB corpus

[Cerberus](https://github.com/pyeve/cerberus) is a pure-Python validation
library. This lab changes one branch in
`cerberus/validator.py::BareValidator.__normalize_mapping`: instead of calling
`DefinitionSchema.copy()` — which rebuilds the schema object, re-running
`expand()` and `validate()` field by field on *every* `validate()` call — the
patched path takes a shallow `dict(schema)` copy. On upstream's own benchmark
corpus (``overall_documents_1.json``, 10,000 documents, 2.5 MB) the median
speed-up is **1.71x**; the differential test is 1,200 distinct
`(schema, document)` pairs with **0** byte-level mismatches, and a
**10,807-distinct-input adversarial battery** finds no input where the patched
path is slower (worst 1.23x; baseline-vs-baseline noise floor 0.687x).

Upstream: https://github.com/pyeve/cerberus

## The change

`patch.diff` (7 insertions, 1 deletion, one file) replaces

```python
schema = schema.copy()
```

with

```python
if isinstance(schema, DefinitionSchema):
    schema = dict(schema)
else:
    schema = schema.copy()
```

`DefinitionSchema.copy()` calls `self.__class__(self.validator, self.schema.copy())`,
whose `__init__` runs `expand()` and `validate()` (a `mapping_hash` of the schema
and of `types_mapping`) for every field. `__normalize_mapping` only needs a
mapping it can write resolved rules into, so the cheap copy is enough. No public
API, return value or upstream test file is touched.

## Results — upstream benchmark corpus (median of 5 samples after 3 warm-ups)

| scale | documents | baseline median | patched median | speed-up |
|---|---|---|---|---|
| small | 500 | 0.5580 s | 0.3259 s | **1.71x** |
| medium | 2,000 | 2.2446 s | 1.3157 s | **1.71x** |
| large | 10,000 | 11.2157 s | 6.6334 s | **1.69x** |

Median of the three scale speed-ups: **1.71x**. Raw samples are in
`benchmark/raw/`; aggregates in `benchmark/baseline.json` and
`benchmark/optimized.json`.

## Adversarial envelope

`benchmark/adversarial.py` generates 13,000 `(schema, document)` pairs
in four classes (`tiny` 1-field, `deep` 2–4-level nesting, `wide` 8–20 fields,
`real` upstream's benchmark schema); 10,807 are distinct and valid, and 2,193
are skipped because upstream itself raises on that generated pair. It times
both arms and reports the minimum ratio:

| quantity | value |
|---|---|
| distinct valid cases | 10,807 (of 13,000 generated) |
| worst-case ratio | **1.23x** of baseline |
| 1st percentile | 1.66x |
| 5th percentile | 1.78x |
| median | 3.05x |
| cases below 1.00x | 0 |
| control: baseline vs baseline, worst of 824 | 0.687x (noise floor) |

Per-class medians: tiny 4.93x, deep 1.93x, wide 3.21x,
real 1.91x.

The patch has no data-dependent dispatch and adds no work: it simply avoids
re-expanding a schema that was already expanded and validated once. The
adversarial battery is a measurement of that claim, not an assumption, and the
baseline-vs-baseline control gives the timer-noise floor. `fallback_required:
false` is recorded in `benchmark/adversarial.json` together with the worst
witness hash.

## Quality gates

| gate | verdict | reproducible command |
|---|---|---|
| G1 upstream tests green | 246 passed, 1 skipped | `git clone -q upstream g1 && git -C g1 apply ../patch.diff && cd g1 && python -m pytest cerberus/tests -q` |
| G2 byte-exact differential | 1,200/1,200 distinct cases, 0 mismatches | `CERBERUS_SRC=upstream python tests/test_diff.py` |
| G3 median speed-up ≥1.15x | 1.71x | `python benchmark/bench.py --impl baseline\|optimized --src upstream ...` |
| G3b real-corpus speed-up | upstream's own 10,000-document benchmark corpus, 1.69x | same as G3, `--docs overall_documents_1.json` |
| G4 largest scale ≥0.95x | 1.69x | same as G3 (large = full corpus) |
| G5 peak RSS ≤1.10x baseline | baseline 35,356 kB → patched 35,484 kB (1.0036x) | `/usr/bin/time -v python benchmark/memcheck.py --impl ...` |

`python3.10` and `python3.11` are absent on this machine, so no cross-interpreter
row exists; the environment below is the only interpreter measured.

## Reproduce

The timing arms need **pristine** upstream (the patched arm is switched on in
memory by `benchmark/opt_patch.py`), so `patch.diff` is applied to a second
copy only for G1. On the measurement host `github.com:443` is blocked and
`github-linluozi` is an SSH alias for `github.com`; substitute
`git@github.com:` on a normal host.

```bash
# 1. upstream at the base commit + a patched copy for G1
git clone --depth=1 git@github-linluozi:pyeve/cerberus.git upstream && git clone -q upstream g1 && git -C g1 apply ../patch.diff
# 2. environment + G1
python3 -m venv .venv && . .venv/bin/activate && pip install pytest && (cd g1 && python -m pytest cerberus/tests -q)
# 3. G2 + G3/G3b/G4 + adversarial envelope (all on pristine upstream)
CERBERUS_SRC=upstream python tests/test_diff.py && python benchmark/bench.py --impl baseline --src upstream --docs upstream/cerberus/benchmarks/documents/overall_documents_1.json --out benchmark/baseline.json && python benchmark/bench.py --impl optimized --src upstream --docs upstream/cerberus/benchmarks/documents/overall_documents_1.json --out benchmark/optimized.json && CERBERUS_SRC=upstream python benchmark/adversarial.py
```

G5: `/usr/bin/time -v python benchmark/memcheck.py --impl baseline --src upstream --docs upstream/cerberus/benchmarks/documents/overall_documents_1.json` (and `--impl optimized`).

## Environment

- CPU: AMD EPYC 7K62 48-Core Processor
- Memory: 3812564 kB
- Python: 3.12.3
- Seed: 20261114 (case generation); per scale: 3 warm-ups, 5 timed samples
- Corpus: `cerberus/benchmarks/documents/overall_documents_1.json` (2,506,530 bytes, 10,000 documents), shipped by upstream

## 本轮创新

**B 档。** 第一次把「每次 `validate()` 都重建 `DefinitionSchema`」测成
Cerberus 验证耗时的主项（上游自带 7 MB 基准语料上，`DefinitionSchema.copy()`
触发的 `expand()` + `mapping_hash()` 占了大头），并把修复做成**单调**改动：
它不引入任何按输入分派的快路径，只把“已展开、已校验”的 schema 换成浅拷贝，
因此不存在对抗输入回归——这一点用 13,000 个生成、10,807 个互异有效输入的对抗电池
+ 同协议的 baseline-vs-baseline 噪声对照去**实测**，而不是口头声称。与台账里的
`envelope-guard`（对**植入**的快路径做包络）和 `perfclaim-guard`（审计声明）不同：
这里是对**真实上游**的一次修改，并用「修复单调、无分派」这一结构性理由**预测**
零回归，再用对抗测量去**证伪**它；台账最近 20 条里没有 Cerberus，也没有
“把 schema 重复展开/重复哈希测成主项并证明修复单调”的条目。

## Licence

Upstream Cerberus is ISC-licensed; `LICENSE` keeps the upstream text and adds
the source and change scope.
