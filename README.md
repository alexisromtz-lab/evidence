# evidence

Every benchmark number in my `hanzoai/vfs` pull requests, re-derived from the raw CSV that
produced it, by a program instead of by trust.

The claim a benchmark report makes is usually *"here is a table"*. The claim this repository
makes is narrower and cheaper to check: **no published cell disagrees with the rows it claims to
come from, and the checker is proven able to fail.**

    python3 check.py              # all five bounties
    python3 check.py parasync     # one
    python3 check.py --self-test  # mutate a cell, require red

No dependencies beyond the standard library. `check.py` parses the numbers out of each
`report.md`'s own markdown tables — never from a hand-copied list — and recomputes each one from
`raw.csv`. A transcription error therefore produces a false FAIL, never a false PASS.

## What is here

| bounty | PR | one headline number | cells |
|---|---|---|---:|
| #1 WSBuffer | [#101](https://github.com/hanzoai/vfs/pull/101) | a buffered write removes **2.8 %** of the pages the media writes at `every=1`, and **2.4 %–2.8 %** with a 256 KiB window | 68 |
| #2 RASK | [#100](https://github.com/hanzoai/vfs/pull/100) | **0.47×–0.81×** the index bytes of the sorted-array baseline, at **2.94×–8.31×** its p50 lookup | 72 |
| #4 RubikFS | [#104](https://github.com/hanzoai/vfs/pull/104) | the packer never compresses: `stored = 15,833,075 B` under all four orders, and a 1 MiB pack costs **2.5487** read amplification against `1.3960` at 256 KiB | 63 |
| #7 ParaSync | [#102](https://github.com/hanzoai/vfs/pull/102) | a 1 % change over inlined files still moves **50.5 %** of the bytes; over packs, **1.4 %** | 107 |
| #10 FS-PI | [#103](https://github.com/hanzoai/vfs/pull/103) | the default reader catches **3 of 7** damage classes; only a full read sees `head-rollback` | 111 |

421 cells. `python3 check.py` exits 0.

## The checker earned its keep on the first run

`docs/wsbuffer.md` §4.1 published **1.9 %** for the `every=32` row. Neither repetition says that:
the CSV has `2,092` against `2,137` (**2.1 %**) and `2,090` against `2,117` (**1.3 %**). The cell
now publishes the pair, because collapsing it hid a factor of 1.6 between two runs
(`cd57e87`, pushed to `#101`). That is the whole argument for this repository: the error was
mine, it was already public, and only a program that recomputes rather than rereads caught it.

A checker that cannot fail is decoration, so `--self-test` adds one to the first number of every
table in turn, in a throwaway copy, and requires that bounty's run to go red:

    rubikfs   3/3 tables go red on a one-unit lie
    wsbuffer  2/2
    rask      1/4  (three tables are not in the CSV; see below)
    parasync  4/4
    fspi      3/3

## What this repository does not cover

Stated here rather than left implied, because an absent check is a fact about the evidence:

- **RASK §2, §4A, §4C.** `§2` is `unsafe.Sizeof` over three struct definitions; `§4A` comes from
  `TestDeterministicByteCost`; `§4C` from the synthetic runner. None of the three writes a CSV
  row. They are re-derived by running those tests, not by reading `raw.csv`.
- **WSBuffer §4.2** (153 → 86 pages) comes from `TestScrapJournalHoldsTheSameVolume`, a unit
  test, not from the bench CSV.
- **Every millisecond figure except WSBuffer's §4.3.** `raw.csv` carries `p50_us` for WSBuffer, so
  those are checked. The FS-PI report declares its ms column indicative only — an in-memory store
  on a busy laptop — and nothing here quotes it.
- **The bytes a store never stores.** All of this is a local, deterministic measurement over a
  memory-backed `Volume` on one machine. No figure here is a claim about throughput on a real
  disk, and the reports say so where it matters.

## Provenance

Each `report.md` is verbatim from its pull request branch; each `raw.csv` is the file the
benchmark wrote, as committed on that branch. `fspi/layout-b.csv` is the second layout of the
same store, published because the layout is not reproducible and the pattern is the claim.
