"""Summarise yorc-bench JSON lines into a (Java,) Rust, Zig (and DuckDB) table.

    python3 -I summarize.py RESULTS.jsonl [--markdown]

Reads the lines the bench programs print ({"impl","workload","iterations",
"bytes","total_ns","ns_per_op","mb_per_s"}), takes the median ns/op of each
(impl, workload) over the repetitions, and prints one row per workload:
the ns/op of each implementation, Java first when the file has Java lines
(impl "java", run.sh --java: ORCID's orcid-model), then Rust, then Zig; the
ratios Rust/Java, Zig/Java and Zig/Rust (Zig/Rust alone without Java; below
1: the first is faster); MB/s; and the repetition counts. With DuckDB lines
(impl "duckdb", run.sh --duckdb: yorc-duckdb in SQL), a DuckDB column comes
last, with the ratios DuckDB/Java and DuckDB/Rust. "-" marks a workload an
implementation does not run (Java: id_normalize, rows_record, timeline_record,
changes_record, dump_sample, no such feature in ORCID's library; DuckDB:
xml_write_record, json_write_record, no record writer). A last row gives the average of each ratio
column (geometric mean over the workloads that have it). Lines that are not
JSON objects with these keys are ignored.
"""

import json
import statistics
import sys

ORDER = [
    "id_normalize",
    "xml_read_record",
    "xml_write_record",
    "json_write_record",
    "json_read_record",
    "rows_record",
    "sha256",
    "dump_stream",
    # appended on 2026-10-18 (the Rust and Zig programs; group_ids_read also Java)
    "group_ids_read",
    "timeline_record",
    "changes_record",
    "dump_sample",
]


def load(path):
    runs = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                r = json.loads(line)
                key = (r["impl"], r["workload"])
                ns = float(r["total_ns"]) / max(int(r["iterations"]), 1)
                mb = float(r["mb_per_s"])
            except (ValueError, KeyError, TypeError):
                continue
            runs.setdefault(key, []).append((ns, mb))
    return runs


def fmt_ns(ns):
    return "-" if ns is None else f"{ns:,.0f}"


def main(argv):
    if len(argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    markdown = "--markdown" in argv[2:]
    runs = load(argv[1])
    workloads = [w for w in ORDER if any(k[1] == w for k in runs)]
    workloads += sorted({k[1] for k in runs} - set(workloads))

    java = any(k[0] == "java" for k in runs)
    duckdb = any(k[0] == "duckdb" for k in runs)
    zig_own = any(k[0] == "zig-own" for k in runs)
    impls = ((("java",) if java else ()) + ("rust", "zig") + (("zig-own",) if zig_own else ())
             + (("duckdb",) if duckdb else ()))
    # "zig" links libc (malloc, as the Rust program); "zig-own" is the same code
    # on Zig's own default allocator (run.sh; README.md "Allocators")
    label = {"java": "Java", "rust": "Rust", "zig": "Zig", "zig-own": "ZigOwn", "duckdb": "DuckDB"}
    initial = {"java": "J", "rust": "R", "zig": "Z", "zig-own": "O", "duckdb": "D"}
    # the pairwise ratios, numerator/denominator: below 1, the numerator is faster
    pairs = [("rust", "java"), ("zig", "java"), ("zig", "rust")] if java else [("zig", "rust")]
    if zig_own:
        pairs += [("zig-own", "zig")]
    if duckdb:
        pairs += ([("duckdb", "java")] if java else []) + [("duckdb", "rust")]
    head = (["workload"] + [f"{label[i]} ns/op" for i in impls]
            + [f"{label[a]}/{label[b]}" for a, b in pairs]
            + [f"{label[i]} MB/s" for i in impls]
            + ["reps " + "/".join(initial[i] for i in impls)])  # J/R/Z/D
    rows = []
    ratios = {p: [] for p in pairs}
    for w in workloads:
        cell = {}
        for impl in impls:
            v = runs.get((impl, w), [])
            ns = statistics.median(x[0] for x in v) if v else None
            mb = statistics.median(x[1] for x in v) if v else None
            cell[impl] = (ns, mb, len(v))
        row = [w] + [fmt_ns(cell[i][0]) for i in impls]
        for a, b in pairs:
            na, nb = cell[a][0], cell[b][0]
            if na and nb:
                ratios[(a, b)].append(na / nb)
                row.append(f"{na / nb:.2f}")
            else:
                row.append("-")
        row += ["-" if cell[i][1] is None or cell[i][1] == 0 else f"{cell[i][1]:.1f}" for i in impls]
        row.append("/".join(str(cell[i][2]) for i in impls))
        rows.append(row)
    # summary: the average of each ratio column over the workloads it has (geometric mean,
    # the average that treats 2x faster and 2x slower alike)
    summary = (["average"] + [""] * len(impls)
               + [f"{statistics.geometric_mean(ratios[p]):.2f}" if ratios[p] else "-" for p in pairs]
               + [""] * len(impls) + [""])

    if markdown:
        print("| " + " | ".join(head) + " |")
        print("|---" + "|---:" * (len(head) - 1) + "|")
        for r in rows:
            print("| " + " | ".join(r) + " |")
        print("| **" + summary[0] + "** | " + " | ".join(f"**{x}**" if x else "" for x in summary[1:]) + " |")
    else:
        width = [max(len(str(x)) for x in col) for col in zip(head, summary, *rows)]
        line = lambda r: "  ".join(str(x).ljust(width[j]) if j == 0 else str(x).rjust(width[j]) for j, x in enumerate(r))
        rule = "  ".join("-" * n for n in width)
        print(line(head))
        print(rule)
        for r in rows:
            print(line(r))
        print(rule)
        print(line(summary).rstrip())
    print("\nmedian over repetitions. A/B is A's time over B's: below 1, A is faster (Zig/Rust 0.5: Zig takes"
          " half Rust's time). average: geometric mean of the column over the workloads it has. MB/s counts the"
          " workload's input (output for the writers; uncompressed members for dump_stream).")
    if java:
        print("Java: ORCID's orcid-model 4.0.2 (JAXB, Jackson),"
              " steady state after JIT warm-up, JVM startup excluded; sha256 is the JDK's MessageDigest"
              " (see README.md).")
    if duckdb:
        print("DuckDB: yorc-duckdb in its duckdb CLI (run.sh --duckdb, duckdb/bench.py), one thread, each workload"
              " one SQL statement over all its iterations: SQL planning and execution included, process start-up"
              " excluded; the workloads are the closest SQL counterparts (README.md, \"DuckDB leg\").")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
