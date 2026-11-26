---
title: "Five optimisations, five bills: what a checker found in my own benchmark tables"
published: true
description: "I re-derived every published number in five pull requests from the CSV that produced it. The first run found an error I had already published."
tags: performance, go, opensource, testing
---

I sent five pull requests to one Go storage engine. Each came with a benchmark report: a table of
bytes, pages, lookups, milliseconds. Each was written by a person reading numbers off a terminal.

Then I wrote a program that refuses to read the report. It parses the numbers *out of the report's
own markdown tables* and recomputes them from the raw CSV that the benchmark wrote. Five
reports, 421 cells.

On its first run it caught me.

## The cell that was wrong

One table published **1.9 %** for how many disk pages a write-buffer removed. The CSV behind that
cell has two repetitions:

| repetition | buffered pages | pages without the buffer | removed |
|---|---:|---:|---:|
| 1 | 2,092 | 2,137 | **2.1 %** |
| 2 | 2,090 | 2,117 | **1.3 %** |

1.9 % is neither. It was — most likely — a figure carried over from an earlier run of the same
benchmark. The report is public. A reviewer reading it had no way to know. The cell now publishes
the pair, because 2.1 % and 1.3 % differ by a factor of 1.6, and a single number erased exactly
the part worth reading: the second repetition was much cheaper than the first, and nothing in the
prose explained why.

That is the argument for the whole exercise, and it is a cheap one to make: reading a table again
tests your reading; recomputing it tests the table.

The checker lives at [alexisromtz-lab/evidence](https://github.com/alexisromtz-lab/evidence). No
dependencies, standard library only:

    python3 check.py
    python3 check.py --self-test

## A checker that cannot fail is decoration

A green result from an instrument that never goes red is worth nothing, so `--self-test` mutates:
it takes every table in a report, adds one to the first number it finds, in a throwaway copy of
the tree, and requires that bounty's run to go red. Thirteen of sixteen tables do. The other three
are listed in the README as *not covered* — they come from unit tests and a synthetic runner that
never write a CSV row, so a different command re-derives them. An absent check is a fact about the
evidence and belongs in the evidence.

## What the five tables actually say

Here is the pattern I did not see until the numbers sat in one place: **every one of these
optimisations buys one unit and bills another, and the two units are not comparable.** Five for
five.

**Write batching removes 2.8 % of the pages and doubles the wait.** At one record per sync, a
buffered writer asks the media for 2,521 pages where the unbuffered path wrote 2,594 — a real
2.8 %. The same change moves the median sync from about 4.0 ms to 7.0 ms. In the regime the layer
is actually for (seventy journal calls inside one round, in a unit test) the same 346,467 bytes
go from 153 pages of calls to 86 pages at the media: 70 calls become 2, and 44 % of the pages
disappear. The lever is page count; the bill is latency; which one you are optimising for is a
decision the benchmark cannot make for you.

**A compact index is 0.47× to 0.81× the bytes and 2.9× to 8.3× the lookup time.** Sparse-range
encoding puts an extent index at 9 to 15 bytes per extent against 18.84 to 20.46 for a sorted
array — a decisive win on the metric the task asked for. Then the same table publishes the p50 of
a lookup: 255–266 ns against 31–32 ns. The index is smaller *because it is doing more work per
probe*. Both columns are in the same table, which is the only reason the claim survives contact
with a reader.

**Better packing order saves bytes the store never stores.** Four orders over the same data, and
the packer writes exactly 15,833,075 bytes in all four, because it does not compress. What the
ordering changes is a counterfactual — the sealed size the data *would* have if it did: 0.8795 of
arrival order for a content-defined order, 0.2850 for one sorted by size. The same table publishes
what a cold start then fetches: 1.3942 over needed for arrival, 2.0991 for content order, 7.9772
for size order. The order that saves 71 % of the phantom bytes costs 5.7× on the real read path.
And the larger lever is not the order at all: the best plan at a 1 MiB pack is 2.5487 against
1.3960 at 256 KiB — 1.83× from pack size alone.

**A delta planner prunes 15 of 22 subtrees and still moves half the bytes.** With equal subtree
hashes, the planner skips whole branches in O(1): 15 of 22 subtrees skipped, 7 objects transferred
out of 22. And the byte count is still 50.5 % of a full copy, because one leaf holds about thirty
inlined file bodies and a plan that copies one leaf copies all thirty. Put the same data in packs
and a 1 % change moves 1.4 % of the bytes. Same algorithm, same pruning, five times less transfer:
the unit of transfer decides what the pruning is worth.

**The control is the one where the cost landed where the design said it would.** A corruption
detector that reads 225,161 bytes — 1.1 % of the store, 7 requests — catches three of seven
damage classes. The reader that catches the rollback of the head must touch all 19,538,121 bytes
(99.7 %) with 9 requests. Neither number was a surprise, and being able to say that is only
possible because the other four were.

## What these numbers are not

- **One machine, one memory-backed store.** No claim about throughput on a real disk appears
  anywhere in the five reports, and the places where a real-device number would be needed say
  `NO_MEDIDO` explicitly.
- **Only one table of milliseconds is checked** — the one whose CSV carries the raw microsecond
  values per run. The other reports mark their timing columns indicative, and neither the checker
  nor this article quotes them as throughput.
- **The five pull requests are unmerged.** A benchmark that nobody has reviewed is a proposal, not
  a result. Three of the five reports contain a refuted hypothesis, printed next to the refutation.

## Steal the habit, not the tool

The tool is forty lines of parsing and three hundred of adapters. What transfers is the rule:

1. The published number is parsed from the published document, never from a list you keep.
2. The raw rows are the only oracle.
3. Every assertion names its cell, so a failure says `every=32/window/removed/run1` and not
   "mismatch".
4. Mutation-test the checker before you trust it.

Reports are cheap to write and expensive to audit by hand, which is why nobody audits them.
Making the audit run in 0.2 seconds is the whole trick.

    git clone https://github.com/alexisromtz-lab/evidence && cd evidence && python3 check.py
