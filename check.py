#!/usr/bin/env python3
"""Re-derive every published number from the raw rows it claims to come from.

Each bounty ships a `report.md` (what was published) and a `raw.csv` (what the
instrument wrote).  This script parses the numbers out of the report's own
markdown tables and recomputes them from the CSV.  A cell that disagrees is a
transcription error or a lie; either way it fails here before a reader finds it.

    python3 check.py            # every bounty
    python3 check.py rubikfs    # one bounty
"""

import csv
import re
import sys

PASS, FAIL = 0, 1


# ---------------------------------------------------------------- plumbing

def rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def num(text):
    """Parse a published cell: '15,833,075' -> 15833075.0, '**0.2850**' -> 0.285.

    Returns None when the cell is not a number (a dash, a word, a range).
    """
    t = text.replace("*", "").replace(",", "").replace("`", "").strip()
    t = t.replace("\u00a0", "").replace("\u202f", "").replace("\u2009", "").replace(" ", "")
    t = t.replace("%", "").replace("×", "")
    try:
        return float(t)
    except ValueError:
        return None


def tables(md_path):
    """Yield (section_heading, header, rows) for every markdown table."""
    section, header, body, in_table = "", None, [], False
    with open(md_path, encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped.startswith("#"):
                if in_table:
                    yield section, header, body
                    header, body, in_table = None, [], False
                section = stripped
                continue
            if stripped.startswith("|"):
                cells = [c.strip() for c in stripped.strip("|").split("|")]
                if set("".join(cells)) <= set("-: "):  # the separator row
                    continue
                if not in_table:
                    header, in_table = cells, True
                else:
                    body.append(cells)
            elif in_table:
                yield section, header, body
                header, body, in_table = None, [], False
    if in_table:
        yield section, header, body


def pick(md_path, first_header, section_contains=None):
    """The one table whose first column header matches, optionally by section."""
    found = [
        (s, h, b)
        for s, h, b in tables(md_path)
        if h and h[0].lower() == first_header.lower()
        and (section_contains is None or section_contains in s)
    ]
    if len(found) != 1:
        raise SystemExit(
            "expected exactly one table starting with %r%s in %s, found %d"
            % (first_header, " under %r" % section_contains if section_contains else "",
               md_path, len(found))
        )
    return found[0]


class Check:
    def __init__(self, name):
        self.name, self.n, self.bad = name, 0, []

    def eq(self, label, published, derived, tol=5e-5):
        self.n += 1
        if published is None or derived is None:
            self.bad.append((label, published, derived))
        elif abs(published - derived) > tol:
            self.bad.append((label, published, derived))

    def report(self):
        status = "PASS" if not self.bad else "FAIL"
        print("%-9s %-3s %3d cells checked, %d disagree" %
              (self.name, status, self.n, len(self.bad)))
        for label, pub, der in self.bad:
            print("    %-44s report=%-14s raw=%s" % (label, pub, der))
        return PASS if not self.bad else FAIL


# ---------------------------------------------------------------- bounties

def check_rubikfs():
    """RubikFS, bounty #4.  Four orders over one packer, two pack sizes."""
    c, raw = Check("rubikfs"), rows("rubikfs/raw.csv")
    agg = {(r["mode"], r["plan"], r["pack_bytes"]): r
           for r in raw if r["tenant"] == ""}
    sizes = {"A": "262144", "B": "1048576"}
    fields = {
        "packs": ("packs", 1),
        "stored": ("stored_bytes", 1),
        "sealed": ("sealed_bytes", 1),
        "sealed (counterfactual)": ("sealed_bytes", 1),
        "vs arrival": ("sealed_vs_arrival", 1e-4),
        "amp": ("read_amp", 1e-4),
        "amp_sum": ("read_amp_sum", 1e-4),
    }
    for table, mode, pack in (("A", "layered", "262144"), ("B", "layered", "1048576"),
                              ("C", "scatter", "262144")):
        _, header, body = pick("rubikfs/report.md", "order", "### %s." % table)
        for row in body:
            plan = row[0].replace("*", "").replace("-", "")  # "co-access" -> "coaccess"
            for col, cell in zip(header[1:], row[1:]):
                if col in fields:
                    fld, tol = fields[col]
                    c.eq("%s/%s/%s" % (table, plan, col), num(cell),
                         float(agg[(mode, plan, pack)][fld]))
                elif col == "runs/groups":
                    runs, groups = (num(x) for x in cell.split("/"))
                    c.eq("%s/%s/runs" % (table, plan), runs,
                         float(agg[(mode, plan, pack)]["coaccess_runs"]))
                    c.eq("%s/%s/groups" % (table, plan), groups,
                         float(agg[(mode, plan, pack)]["coaccess_groups"]))
    # Every order writes the same bytes: the claim the whole report rests on.
    stored = {float(r["stored_bytes"]) for r in agg.values()}
    c.n += 1
    if len(stored) != 1:
        c.bad.append(("stored identical across orders", 1, len(stored)))
    return c.report()



def _pair(cell):
    """'2,594 / 2,582' -> [2594.0, 2582.0]; '—' -> []."""
    return [num(x) for x in cell.split("/") if num(x) is not None]


def _range(cell):
    """'2.94-3.03' -> (2.94, 3.03); '135' -> (135.0, 135.0)."""
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", cell.replace(",", "").replace("*", ""))]
    if not nums:
        return (None, None)
    return (min(nums), max(nums))


def _spread(values):
    return (min(values), max(values))


def check_wsbuffer():
    """WSBuffer, bounty #1.  Pages the media writes, layer on and off.

    The CSV holds two experiments at `every=8` -- one with a 1 MiB buffer window and
    one with 256 KiB -- and in both, `through` rows are indistinguishable by their own
    columns, so rows are paired (through, window) by run inside the block that the
    buffered row's `window` field identifies.
    """
    c, raw = Check("wsbuffer"), rows("wsbuffer/raw.csv")
    cfg, pending = {}, None
    for r in raw:
        if r["mode"] == "through":
            pending = r
            continue
        key = (int(r["every"]), int(r["window"]))
        cfg.setdefault(key, {}).setdefault("through", {})[int(pending["run"])] = pending
        cfg[key].setdefault("window", {})[int(r["run"])] = r
    labels = {"1": (1, 1048576), "8": (8, 1048576), "32": (32, 1048576),
              "8 (256 KiB window)": (8, 262144)}
    _, header, body = pick("wsbuffer/report.md", "every", "### 4.1")
    for row in body:
        key = labels[row[0]]
        mode = row[1]
        mine = cfg[key][mode]
        ref = cfg[key]["through"]
        for col, cell in zip(header[2:], row[2:]):
            if col.startswith("pages (run"):
                for i, want in enumerate(_pair(cell)):
                    c.eq("every=%s/%s/pages/run%d" % (row[0], mode, i + 1), want,
                         float(mine[i + 1]["pages"]))
            elif col == "ratio":
                for i, want in enumerate(_pair(cell)):
                    c.eq("every=%s/%s/ratio/run%d" % (row[0], mode, i + 1), want,
                         float(mine[i + 1]["ratio"]), tol=5e-4)
            elif col.startswith("pages, journal"):
                for i, want in enumerate(_pair(cell)):
                    c.eq("every=%s/%s/ref_pages/run%d" % (row[0], mode, i + 1), want,
                         float(ref[i + 1]["ref_pages"]))
            elif col.startswith("removed"):
                got = _pair(cell)
                if not got:
                    continue
                by_run = [100.0 * (1.0 - float(mine[k]["pages"]) / float(ref[k]["ref_pages"]))
                          for k in sorted(mine)]
                if len(got) == 1:
                    c.eq("every=%s/%s/removed/run1" % (row[0], mode), got[0],
                         by_run[0], tol=0.051)
                else:
                    lo, hi = _spread(by_run)
                    c.eq("every=%s/%s/removed_lo" % (row[0], mode), min(got), lo, tol=0.051)
                    c.eq("every=%s/%s/removed_hi" % (row[0], mode), max(got), hi, tol=0.051)
    # 4.3: the price paid per record, run 1 / run 2.
    _, h43, b43 = pick("wsbuffer/report.md", "every", "### 4.3")
    for row in b43:
        key = labels[row[0]]
        cells = dict(zip(h43, row))
        mine = cfg[key][row[1]]
        for col, cell in cells.items():
            if col.startswith("CPU"):
                for i, want in enumerate(_pair(cell)):
                    r = mine[i + 1]
                    c.eq("every=%s/%s/cpu_per_record/run%d" % (row[0], row[1], i + 1), want,
                         float(r["cpu_us"]) / float(r["records"]), tol=0.061)
            elif col.startswith("p50"):
                # two measurements of the same quantity, published in the order they were
                # written; compared as a pair, since run order is not the claim
                got = sorted(float(mine[k]["p50_us"]) / 1000.0 for k in mine)
                for i, want in enumerate(sorted(_pair(cell))):
                    c.eq("every=%s/%s/p50/%d" % (row[0], row[1], i + 1), want,
                         got[i], tol=0.0051)
            elif col.startswith("records/s"):
                for i, want in enumerate(_pair(cell)):
                    c.eq("every=%s/%s/records_per_s/run%d" % (row[0], row[1], i + 1), want,
                         float(mine[i + 1]["ops_s"]), tol=0.51)
    return c.report()


def check_rask():
    """RASK, bounty #2.  Bytes per extent on one side, lookup latency on the other."""
    c, raw = Check("rask"), rows("rask/raw.csv")
    _, header, body = pick("rask/report.md", "runs", "### B.")
    for row in body:
        runs, leaf = row[0].replace(",", ""), row[1]
        mine = [r for r in raw if r["n_runs"] == runs and r["leaf"] == leaf]
        mine.sort(key=lambda r: int(r["run"]))
        for col, cell in zip(header[2:], row[2:]):
            if col.startswith("B/ext RASK"):
                c.eq("runs=%s/leaf=%s/B_per_ext" % (runs, leaf), num(cell),
                     float(mine[0]["bytes_per_extent"]))
            elif col.startswith("B/ext array"):
                c.eq("runs=%s/leaf=%s/array_B_per_ext" % (runs, leaf), num(cell),
                     float(mine[0]["array_bytes_per_extent"]), tol=5e-3)
            elif col == "ratio":
                c.eq("runs=%s/leaf=%s/bytes_ratio" % (runs, leaf), num(cell),
                     float(mine[0]["bytes_ratio"]), tol=5e-3)
            elif col.startswith("p50 RASK"):
                left, right = cell.split("/")
                lo, hi = _range(left)
                c.eq("runs=%s/leaf=%s/p50_rask_lo" % (runs, leaf), lo,
                     min(float(r["p50_rask_ns"]) for r in mine), tol=0.51)
                c.eq("runs=%s/leaf=%s/p50_rask_hi" % (runs, leaf), hi,
                     max(float(r["p50_rask_ns"]) for r in mine), tol=0.51)
                lo, hi = _range(right)
                c.eq("runs=%s/leaf=%s/p50_array_lo" % (runs, leaf), lo,
                     min(float(r["p50_array_ns"]) for r in mine), tol=0.51)
            elif col.endswith("ratio"):
                which = col.split()[0]  # p50 / p90 / p99
                lo, hi = _range(cell)
                vals = [float(r["%s_ratio" % which]) for r in mine]
                c.eq("runs=%s/leaf=%s/%s_ratio_lo" % (runs, leaf, which), lo,
                     min(vals), tol=5e-3)
                c.eq("runs=%s/leaf=%s/%s_ratio_hi" % (runs, leaf, which), hi,
                     max(vals), tol=5e-3)
    return c.report()


def check_parasync():
    """ParaSync, bounty #7.  Delta against full restore, by change size.

    Each workload carries two tables: the absolute one the bench wrote, and the
    percentages it derived from the full copy of the same checkpoint.  Both are
    checked -- the first against the CSV, the second against the first.
    """
    c, raw = Check("parasync"), rows("parasync/raw.csv")
    seen = {}
    for section, size in (("### 5a.", "2048"), ("### 5b.", "49152")):
        cand = [(h, b) for sec, h, b in tables("parasync/report.md")
                if section in sec and h[0].lower() == "change" and h[1].lower() == "mode"]
        if len(cand) != 1:
            raise SystemExit("expected one absolute table under %r, found %d" % (section, len(cand)))
        header, body = cand[0]
        for row in body:
            change = row[0].replace(" %", "").replace("%", "").strip()
            mine = next(r for r in raw if r["order"] == "spread" and r["size"] == size
                        and r["change_pct"] == change and r["mode"] == row[1])
            seen[(size, change, row[1])] = mine
            for col, cell in zip(header[1:], row[1:]):
                if col in ("objects", "pruned", "packs", "bytes"):
                    c.eq("%s/change=%s/%s/%s" % (size, change, row[1], col),
                         num(cell), float(mine[col]))
                elif col == "shards":
                    c.eq("%s/change=%s/%s/shards" % (size, change, row[1]),
                         num(cell), float(mine["shards"]))
                elif col.startswith("restore"):
                    ms = float(mine["restore_us"]) / 1000.0
                    c.eq("%s/change=%s/%s/restore_ms" % (size, change, row[1]),
                         num(cell), ms, tol=0.051)
        # the derived table: delta as a percent of the full copy of the same checkpoint
        for sec, hdr, bdy in tables("parasync/report.md"):
            if section not in sec:
                continue
            if not (hdr[0].lower() == "change" and hdr[1].lower() == "objects"):
                continue
            for row in bdy:
                change = row[0].replace(" %", "").replace("%", "").strip()
                full = seen[(size, change, "full")]
                delta = seen[(size, change, "delta")]
                for col, cell in zip(hdr[1:], row[1:]):
                    what = "restore" if col.startswith("restore") else col
                    pair = {"objects": "objects", "bytes": "bytes", "restore": "restore_us"}[what]
                    c.eq("%s/change=%s/pct_%s" % (size, change, what), num(cell),
                         100.0 * float(delta[pair]) / float(full[pair]), tol=0.051)
    return c.report()


def check_fspi():
    """FS-PI, bounty #10.  Which detector sees which damage, and what it costs.

    A detection cell is `caught / damaged`: the targets a detector reported over the
    distinct targets the class was injected into.  The raw `faults` column (how many
    individual errors a reader raised) is deliberately not published -- `read-all`
    raises 63 errors for 2 missing packs -- so it is not checked here either.  The ms
    column of 5c is likewise unread: the report declares it indicative only.
    """
    c = Check("fspi")
    # 5a: the shape of each store, and the rows each CSV actually carries.
    layouts = {"A": rows("fspi/raw.csv"), "B": rows("fspi/layout-b.csv")}
    _, h5a, b5a = pick("fspi/report.md", "run", "### 5a")
    for row in b5a:
        cells = dict(zip(h5a, row))
        run = row[0].strip("`").strip()
        mine, clean = layouts[run], [r for r in layouts[run] if r["class"] == "clean"][0]
        c.eq("%s/objects" % run, num(cells["objects"]), float(clean["store_objects"]))
        c.eq("%s/shards" % run, num(cells["shards"]), float(clean["store_shards"]))
        c.eq("%s/packs" % run, num(cells["packs"]), float(clean["store_packs"]))
        c.eq("%s/store_bytes" % run, num(cells["store bytes"]), float(clean["store_bytes"]))
        reach, total = (num(x) for x in cells["reachable"].split("of"))
        c.eq("%s/reachable" % run, reach,
             float(int(clean["reachable_shards"]) + int(clean["reachable_packs"])))
        c.eq("%s/shape_total" % run, total,
             float(int(clean["store_shards"]) + int(clean["store_packs"])))
        c.eq("%s/rows" % run, num(cells["rows"]), float(len(mine)))
    raw = layouts["A"]
    _, header, body = pick("fspi/report.md", "damage", "### 5b")
    detectors = [h.replace("`", "") for h in header[2:]]
    for row in body:
        cls = row[0].replace("`", "")
        mine = [r for r in raw if r["class"] == cls]
        c.eq("%s/objects" % cls, num(row[1]), float(len({r["target"] for r in mine})))
        for det, cell in zip(detectors, row[2:]):
            caught, damaged = (num(x) for x in cell.split("/"))
            sub = [r for r in mine if r["detector"] == det]
            c.eq("%s/%s/caught" % (cls, det), caught,
                 float(sum(1 for r in sub if r["caught"] == "true")))
            c.eq("%s/%s/damaged" % (cls, det), damaged,
                 float(len({r["target"] for r in sub})))
    # 5c: the cost of a store nothing has damaged, in bytes and requests (never in ms).
    _, h5c, b5c = pick("fspi/report.md", "reader", "### 5c")
    clean = {(r["detector"], r["target"]): r for r in raw if r["class"] == "clean"}
    for row in b5c:
        cells = dict(zip(h5c, row))
        r = clean[(row[0].replace("`", "").strip(), "rep1")]
        for col, cell in cells.items():
            if col == "bytes read":
                c.eq("%s/bytes_read" % r["detector"], num(cell), float(r["bytes_read"]))
            elif col == "of store":
                c.eq("%s/of_store_pct" % r["detector"], num(cell),
                     100.0 * int(r["bytes_read"]) / int(r["store_bytes"]), tol=0.051)
            elif col == "requests":
                c.eq("%s/requests" % r["detector"], num(cell), float(r["store_reads"]))
            elif col == "stats":
                c.eq("%s/stats" % r["detector"], num(cell), float(r["store_stats"]))
    return c.report()


BOUNTIES = {"rubikfs": check_rubikfs, "wsbuffer": check_wsbuffer, "rask": check_rask,
            "parasync": check_parasync, "fspi": check_fspi}



def _mutate(md_text, ordinal):
    """Add one to the first number of the ordinal-th table's first data row."""
    lines = md_text.split("\n")
    seen, i = -1, 0
    while i < len(lines):
        if lines[i].startswith("|") and set(lines[i]) <= set("-:| "):
            seen += 1
            if seen == ordinal:
                for j in range(i + 1, len(lines)):
                    if not lines[j].startswith("|"):
                        return None
                    cells = lines[j].split("|")
                    for k, cell in enumerate(cells):
                        if num(cell) is not None:
                            cells[k] = " %s " % ("%.6f" % (num(cell) + 1.0)).rstrip("0").rstrip(".")
                            lines[j] = "|".join(cells)
                            return "\n".join(lines)
                    return None
                return None
        i += 1
    return None


def selftest(name):
    """A checker that cannot fail is not an instrument.

    For every table in the report, add one to its first number in a throwaway copy of
    the tree and require that bounty's check to go red.  A table that stays green is a
    table nobody is checking -- it is listed here rather than left implied.
    """
    import os
    import shutil
    import subprocess
    import tempfile

    here = os.path.dirname(os.path.abspath(__file__))
    text = open(os.path.join(here, name, "report.md"), encoding="utf-8").read()
    sections = [s for s, _, _ in tables(os.path.join(here, name, "report.md"))]
    calls, red = 0, []
    tmp = tempfile.mkdtemp(prefix="evselftest-")
    try:
        dst = os.path.join(tmp, "copy")
        shutil.copytree(here, dst, ignore=shutil.ignore_patterns(".git"))
        for ordinal, section in enumerate(sections):
            mutated = _mutate(text, ordinal)
            if mutated is None:
                continue
            open(os.path.join(dst, name, "report.md"), "w", encoding="utf-8").write(mutated)
            rc = subprocess.run([sys.executable, "check.py", name], cwd=dst,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
            calls += 1
            if rc == 0:
                red.append(section.lstrip("# ").strip())
        bad = [s for s in red if not any(u in s for u in UNCHECKED.get(name, ()))]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("%-9s selftest %d/%d tables go red on a one-unit lie%s" %
          (name, calls - len(red), calls,
           "" if not red else "; unverified: " + " | ".join(red)))
    return PASS if not bad else FAIL


# Tables this checker does not read, and why.  RASK's `2.` is `unsafe.Sizeof` over three
# struct definitions, `A.` comes from `TestDeterministicByteCost` and `C.` from the synthetic
# runner -- none of the three writes a CSV row, so a reader who wants them re-derives them by
# running those tests, not by reading `raw.csv`.
UNCHECKED = {
    "rask": ("Matched baselines", "A. Bytes per extent", "C. Lookup percentiles"),
}


def main(argv):
    if len(argv) > 1 and argv[1] == "--self-test":
        names = argv[2:] or list(BOUNTIES)
        results = [selftest(n) for n in names]
    else:
        names = argv[1:] or list(BOUNTIES)
        results = [BOUNTIES[n]() for n in names]
    return FAIL if any(results) else PASS


if __name__ == "__main__":
    sys.exit(main(sys.argv))
