#!/usr/bin/env python3
"""yorc-duckdb leg of the yorc-bench benchmarks (README.md).

    python3 -I duckdb/bench.py [--root DIR] [--duckdb BIN] [--rust-emit DIR]
        [--iters N] [--dump-iters N] [--warmup N] [--min-time S] [--only W,W] [--dump PATH]

Times yorc-duckdb in the duckdb CLI that `make release` builds
(yorc-duckdb/build/release/duckdb, the extension linked in) on the inputs of
the Rust, Zig and Java bench programs, under their workload names wherever
SQL has a counterpart, and prints the same JSON lines on stdout
({"impl":"duckdb","workload",...}), so that summarize.py gives DuckDB a
column. Rewritten 2026-10-19 after the first 4-way run, whose sha256,
dump_stream, dump_sample and xml_read_record figures, and those of every
lateral workload, were not measuring the work (see "Why the first run was
wrong" below and README.md, "DuckDB leg"). This version ran on 2026-10-19
for those four workloads, with plausible numbers; the full run is pending.

How it times: one duckdb process runs one generated script with `.timer on`,
SET threads = 1 and the common_subplan optimizer disabled. Each workload is
ONE statement that does all N iterations inside DuckDB, after one untimed
warm-up statement of the same shape (min(N, --warmup) iterations). The time
is the shell's `Run Time (s): real` of that statement: wall clock, planning
and execution, millisecond resolution. So that the resolution does not
dominate, the iteration count is calibrated: a statement that took less than
--min-time (default 0.2 s) is run again, in a new process, with N scaled up
to reach it (at most 4 rounds; --min-time 0 keeps N as given). Process
start-up, extension loading and input staging are not timed.

How each iteration is made to do the work (the three ways the first run
went wrong, and what is done here instead):

  1. Identical UNION ALL branches were computed once. DuckDB 1.4+ has a
     common-subplan optimizer that turns repeated identical subplans into one
     materialised CTE, so `orcid_<s>(file) UNION ALL orcid_<s>(file) ...`
     (N copies) parsed the file once and divided by N. Now no two
     iterations have the same input: file workloads read a glob over N
     distinct symlinks to the input (one scan, N documents), and string
     workloads give branch i its own variable bench_doc_<i> = the document
     plus i+1 trailing spaces (insignificant whitespace after the root
     element: the parse is the same, and the per-op byte count stays the
     document's). The optimizer is also disabled (SET disabled_optimizers),
     which saves it serialising 1.3 MB constants to compare plans.
  2. A lateral join over a VARCHAR column is decorrelated by DuckDB into a
     duplicate-eliminated (DELIM) join: the table function runs once per
     DISTINCT input, and its rows are joined back to the N input rows on the
     1.3 MB string itself. With one distinct document per statement, the old
     `copies(...)` laterals parsed once and then timed hash-join key copies
     and compares (about the speed of memcpy). Large documents are therefore
     never passed through a lateral join here: they go in as constant
     arguments (`orcid_<s>_xml(getvariable('bench_doc_<i>'))`, run by a
     table scan, no join). Only group_ids_read (a 154-byte document, where
     the join is cheap) stays lateral, and its input is made distinct per
     row by also correlating on the range value.
  3. A function over a constant vector is evaluated once per vector, not
     per row. sha256 therefore hashes branch i's own variable, one SHA-256
     per branch, and id_normalize keeps its cross join below 1808 iterations
     (10,000 = 4 * 2048 + 1808: the iD vectors stay flat; see
     PhysicalCrossProduct, which turns the side with the smaller chunk into
     constants).

Every statement also consumes every column the table functions produce:
`bit_xor(hash(sec_))` hashes the struct of the whole row (sec_ is the table
function's alias), so projection pushdown cannot drop a column (the file
readers write only the projected columns). The section readers parse the
whole document and compute source_hash whatever is projected; the hash is
just a sink, its value is not checked. The row count is checked (> 0).

The workloads and what each times per iteration (README.md, "DuckDB leg"):

  id_normalize        orcid_normalize over the 10,000 generated iDs (Rust's
                      --emit ids.tsv when --rust-emit is given, else the same
                      generator ported here)
  xml_read_record     the 14 shared sections, orcid_<s>(file): 14 file reads,
                      parses and SHA-256s of the fixture
  rows_record         the same from the document in memory, orcid_<s>_xml
  json_read_record    the same over the fixture's JSON (Rust's --emit
                      fixture/<stem>.json), orcid_<s>_json; skipped without it
  sha256              DuckDB's own sha256() over the fixture's bytes (mbedtls
                      3.6's portable C SHA-256, as vendored by DuckDB)
  dump_stream         every .xml member of the dump decompressed and parsed:
                      orcid_person(dump, members := '*.xml')
  dump_sample         orcid_dump_sample(dump, 5, 42), the kept members not read
  timeline_record     orcid_timeline_xml over the fixture
  changes_record      orcid_changes_xml(fixture, fixture with "Edited: "
                      inserted as the Rust and Zig programs do)
  group_ids_read      orcid_group_ids_json over the group-id JSON write sample
  xml_write_record, json_write_record
                      n/a: yorc-duckdb writes item documents only, from rows;
                      it has no record writer

Exit status: 0, 1 if a workload's statement failed, 2 on a setup error.
"""

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile

FIXTURE = "yorc-rs/tests/data/0000-0003-0100-6634.xml"
GROUP_ID_JSON = "yorc-rs/reference/orcid-model/record_3.0/samples/write_samples/peer-review-group-id.json"
DUMP = "yorc-zig/testdata/dump/orcid_test_summaries.tgz"
DUCKDB = "yorc-duckdb/build/release/duckdb"
N_IDS = 10000

# The 14 sections of yorc-rs's rows (Section::ALL), as emit.py.
SECTIONS = ("works", "fundings", "affiliations", "peer_reviews", "research_resources", "research_resource_items",
            "contributors", "external_ids", "person", "person_items", "history", "search_results", "errors",
            "research_resource_hosts")

# In output order, with the default iteration counts of the Rust and Zig
# programs (the starting point of the calibration).
WORKLOADS = (
    ("id_normalize", 200),
    ("xml_read_record", 30),
    ("xml_write_record", 30),
    ("json_write_record", 30),
    ("json_read_record", 30),
    ("rows_record", 30),
    ("sha256", 300),
    ("dump_stream", 20),
    ("group_ids_read", 10000),
    ("timeline_record", 30),
    ("changes_record", 30),
    ("dump_sample", 20),
)
NOT_AVAILABLE = {
    "xml_write_record": "yorc-duckdb has no record writer (item documents only, from rows)",
    "json_write_record": "yorc-duckdb has no record writer (item documents only, from rows)",
}
DUMP_WORKLOADS = ("dump_stream", "dump_sample")
# Workloads whose iterations are per-branch variables holding a copy of a
# 1.3 MB document (memory: about 1.3 MB per iteration and variable).
VARIABLE_WORKLOADS = ("rows_record", "json_read_record", "sha256", "timeline_record", "changes_record")
# Upper bounds of the calibrated iteration count.
MAX_ITERS = {
    "id_normalize": 1024,  # < 1808, see point 3 of the module docstring
    "xml_read_record": 2000, "dump_stream": 2000, "dump_sample": 2000,  # symlinks
    "group_ids_read": 1000000,
}
MAX_VARIABLE_ITERS = 400
MAX_ROUNDS = 4

MARK = "@@bench "
STMT = "@@stmt "
TIME_RE = re.compile(r"^Run Time \(s\): real ([0-9]+(?:\.[0-9]+)?)\b")

# The changes_record edit of rust/src/main.rs (edited_fixture) and
# the Zig program: "Edited: " inserted right after the first <common:title>
# that follows the first <work:work-summary.
EDIT_AFTER = (b"<work:work-summary", b"<common:title>")
EDIT_TEXT = b"Edited: "


# ------------------------------------------------------------------ inputs

class SplitMix:
    """SplitMix64, the generator of the bench programs' iD list."""

    def __init__(self, seed):
        self.state = seed

    def next(self):
        m = (1 << 64) - 1
        self.state = (self.state + 0x9E3779B97F4A7C15) & m
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & m
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & m
        return z ^ (z >> 31)


def check_char(digits):
    """ISO 7064 MOD 11-2 over 15 digits (yorc-rs id::check_char)."""
    total = 0
    for c in digits:
        total = (total + int(c)) * 2
    r = (12 - total % 11) % 11
    return "X" if r == 10 else str(r)


def hyphenate(d):
    return "-".join(d[i:i + 4] for i in range(0, 16, 4))


def gen_ids(n):
    """The bench programs' gen_ids (rust/src/main.rs), ported."""
    rng = SplitMix(42)
    out = []
    for i in range(n):
        r = rng.next()
        d = ["0"] * 16
        for j in range(3, 15):
            d[j] = str(r % 10)
            r //= 10
        d[15] = check_char(d[:15])
        plain = "".join(d)
        canon = hyphenate(plain)
        form = i % 8
        if form == 0:
            s = canon
        elif form == 1:
            s = "https://orcid.org/" + canon
        elif form == 2:
            s = "http://orcid.org/" + canon
        elif form == 3:
            s = "orcid.org/" + plain
        elif form == 4:
            s = plain
        elif form == 5:
            s = " " + canon.replace("-", " ") + " "
        elif form == 6:
            s = plain.lower()
        else:
            last = {"X": "0", "9": "X"}.get(d[15]) or str(int(d[15]) + 1)
            bad = plain[:15] + last
            s = bad[:15] if i % 16 == 15 else hyphenate(bad)
        out.append(s)
    return out


def read_ids(path):
    """The first column of the Rust program's ids.tsv (`input<TAB>normalized`)."""
    with open(path, encoding="utf-8") as f:
        return [line.rstrip("\n").rsplit("\t", 1)[0] for line in f if line.strip("\n")]


def edited_fixture(data):
    """rust/src/main.rs edited_fixture, on bytes."""
    i = data.find(EDIT_AFTER[0])
    j = data.find(EDIT_AFTER[1], i) if i >= 0 else -1
    if j < 0:
        raise ValueError("fixture: no work summary title")
    at = j + len(EDIT_AFTER[1])
    return data[:at] + EDIT_TEXT + data[at:]


def q(s):
    return "'" + s.replace("'", "''") + "'"


def archive_ext(path):
    low = path.lower()
    for ext in (".tar.gz", ".tgz", ".tar"):
        if low.endswith(ext):
            return ext
    return ".tgz"


class Links:
    """Directories of N distinct names for one input file (point 1 of the
    module docstring): `<tmp>/<tag>-<n>/f_<i><ext>`, symlinks (hard links or
    copies where symlinks fail). Returns the glob over them."""

    def __init__(self, tmp):
        self.tmp = tmp
        self.made = {}

    def glob(self, tag, target, n, ext):
        key = (tag, n)
        if key not in self.made:
            d = os.path.join(self.tmp, "%s-%d" % (tag, n))
            os.makedirs(d, exist_ok=True)
            for i in range(n):
                p = os.path.join(d, "f_%06d%s" % (i, ext))
                if os.path.lexists(p):
                    continue
                try:
                    os.symlink(target, p)
                except OSError:
                    try:
                        os.link(target, p)
                    except OSError:
                        shutil.copyfile(target, p)
            self.made[key] = os.path.join(d, "f_*" + ext)
        return self.made[key]


# --------------------------------------------------------------- the script

def branch(source):
    """One iteration's (or section's) rows: their count, and a hash over every
    column of every row (the struct of the row, so nothing is projected out)."""
    return "SELECT count(*) AS n, bit_xor(hash(sec_)) AS h FROM %s sec_" % source


def total(branches):
    return "SELECT sum(n) AS n, bit_xor(h) AS h FROM (" + " UNION ALL ".join(branches) + ")"


def var(kind, i):
    return "getvariable('bench_%s_%d')" % (kind, i)


def workload_sql(name, n, paths, links):
    """The statement of one run of workload `name` with n iterations: one row
    (n: rows produced, > 0; h: a sink over the columns)."""
    n = max(n, 1)
    if name == "id_normalize":
        # n <= MAX_ITERS["id_normalize"] < 1808: the iD vectors stay flat (point 3)
        return ("SELECT count(*) AS n, sum(length(orcid_normalize(s))) AS h FROM bench_ids, range(%d)" % n)
    if name == "xml_read_record":
        g = q(links.glob("fixture", paths["fixture"], n, ".xml"))
        return total([branch("orcid_%s(%s)" % (s, g)) for s in SECTIONS])
    if name == "rows_record":
        return total([branch("orcid_%s_xml(%s)" % (s, var("doc", i))) for i in range(n) for s in SECTIONS])
    if name == "json_read_record":
        return total([branch("orcid_%s_json(%s, json_root := 'record')" % (s, var("json", i)))
                      for i in range(n) for s in SECTIONS])
    if name == "sha256":
        # branch i: sha256 of its own constant, folded at plan time or run once:
        # either way one SHA-256 of the document per branch, inside the timed statement
        return total(["SELECT 1 AS n, hash(sha256(%s)) AS h" % var("doc", i) for i in range(n)])
    if name == "dump_stream":
        g = q(links.glob("dump", paths["dump"], n, archive_ext(paths["dump"])))
        return branch("orcid_person(%s, members := '*.xml')" % g)
    if name == "dump_sample":
        # one reservoir over the n archives: every member header of every archive is
        # offered (n passes over the tar stream, as n calls of the Rust program's
        # sample_dump); the xml column is not asked for, so no member is read
        g = q(links.glob("dump", paths["dump"], n, archive_ext(paths["dump"])))
        return ("SELECT count(*) AS n, bit_xor(hash(slot, orcid, file, member, name, eligible)) AS h"
                " FROM orcid_dump_sample(%s, 5, 42)" % g)
    if name == "timeline_record":
        return total([branch("orcid_timeline_xml(%s)" % var("doc", i)) for i in range(n)])
    if name == "changes_record":
        return total([branch("orcid_changes_xml(%s, %s)" % (var("doc", i), var("edit", i))) for i in range(n)])
    if name == "group_ids_read":
        # lateral (a 154-byte document): correlating on it.range as well makes the n
        # inputs distinct, so the DELIM join's DISTINCT keeps all n (point 2)
        return branch("bench_gid g, range(%d) it, orcid_group_ids_json(CASE WHEN it.range >= 0 THEN g.doc END)"
                      % n)
    raise ValueError(name)


def setup_sql(paths, ids, nvars):
    """Untimed: settings, inputs, byte counts. nvars: how many per-iteration
    variables of each kind ({"doc": n, "edit": n, "json": n})."""
    s = [".mode list", ".headers off", "SET threads = 1;", "SET enable_progress_bar = false;",
         "SET preserve_insertion_order = false;",
         # point 1 of the module docstring; checked through the `setting` line
         "SET disabled_optimizers = 'common_subplan';",
         "SELECT '%ssetting', current_setting('disabled_optimizers');" % MARK]
    s.append("CREATE TEMP TABLE bench_ids (s VARCHAR);")
    for k in range(0, len(ids), 1000):
        s.append("INSERT INTO bench_ids VALUES " + ", ".join("(%s)" % q(x) for x in ids[k:k + 1000]) + ";")
    s.append("CREATE TEMP TABLE bench_doc AS SELECT content AS doc FROM read_text(%s);" % q(paths["fixture"]))
    s.append("CREATE TEMP TABLE bench_edit AS SELECT content AS doc FROM read_text(%s);" % q(paths["edited"]))
    if paths.get("json"):
        s.append("CREATE TEMP TABLE bench_json AS SELECT content AS doc FROM read_text(%s);" % q(paths["json"]))
    s.append("CREATE TEMP TABLE bench_gid AS SELECT content AS doc FROM read_text(%s);" % q(paths["group_id"]))
    # iteration i's own copy: the document plus i+1 trailing spaces (point 1)
    for kind, table in (("doc", "bench_doc"), ("edit", "bench_edit"), ("json", "bench_json")):
        for i in range(nvars.get(kind, 0)):
            s.append("SET VARIABLE bench_%s_%d = (SELECT doc || repeat(' ', %d) FROM %s);" % (kind, i, i + 1, table))
    s.append("SELECT '%sbytes fixture', strlen(doc) FROM bench_doc;" % MARK)
    s.append("SELECT '%sbytes edited', strlen(doc) FROM bench_edit;" % MARK)
    if paths.get("json"):
        s.append("SELECT '%sbytes json', strlen(doc) FROM bench_json;" % MARK)
    s.append("SELECT '%sbytes group_id', strlen(doc) FROM bench_gid;" % MARK)
    s.append("SELECT '%sbytes dump', sum(strlen(xml)) FROM orcid_documents(%s, members := '*.xml');"
             % (MARK, q(paths["dump"])))
    s.append("SELECT '%sbytes ids', sum(strlen(s)) FROM bench_ids;" % MARK)
    s.append(".timer on")
    return "\n".join(s) + "\n"


def timed_statement(name, label, n, sql):
    """A `.print` marker (a dot command: no timer line), then the statement,
    whose result line and `Run Time` line follow."""
    return ".print %s%s %s %d\nSELECT '%s%s %s', * FROM (%s);\n" % (STMT, name, label, n, MARK, name, label, sql)


def parse_output(lines):
    """The script's stdout -> (bytes_of, setting, timed).

    bytes_of: {"fixture": int, ...}; setting: the disabled_optimizers value or
    None; timed: {(name, label): {"n": int, "seconds": float or None,
    "rows": int, "value": str}}. A statement's time is the first `Run Time`
    line after its `@@stmt` marker; it counts only if the statement's own
    result line (`@@bench <name> <label>|rows|h`) came in between, so a failed
    statement (the shell still prints its timer line) has seconds None."""
    bytes_of, setting, timed, cur = {}, None, {}, None
    for line in lines:
        if line.startswith(STMT):
            parts = line[len(STMT):].split()
            if len(parts) == 3 and parts[2].isdigit():
                cur = (parts[0], parts[1])
                timed[cur] = {"n": int(parts[2]), "seconds": None, "rows": 0, "value": None}
            else:
                cur = None
        elif line.startswith(MARK + "bytes "):
            what, _, value = line[len(MARK) + 6:].partition("|")
            bytes_of[what] = int(value) if value.strip().isdigit() else 0
        elif line.startswith(MARK + "setting|"):
            setting = line[len(MARK) + 8:]
        elif line.startswith(MARK):
            head, _, value = line[len(MARK):].partition("|")
            key = tuple(head.split(" ", 1))
            if cur is not None and key == cur:
                rows = value.split("|", 1)[0].strip()
                timed[cur]["rows"] = int(rows) if rows.isdigit() else 0
                timed[cur]["value"] = value
        else:
            m = TIME_RE.match(line)
            if m and cur is not None:
                if timed[cur]["value"] is not None:
                    timed[cur]["seconds"] = float(m.group(1))
                cur = None
    return bytes_of, setting, timed


def next_iters(n, seconds, min_time, cap):
    """The iteration count for the next round of a statement that took
    `seconds` (< min_time) with n iterations: scaled to about 1.25 min_time,
    at least doubled when the time was below the timer's resolution."""
    if seconds is None or seconds <= 0.002:
        m = n * 10
    else:
        m = int(math.ceil(n * min_time * 1.25 / seconds))
    return max(n + 1, min(m, cap))


def run_round(duckdb, paths, ids, plan, warmup, links):
    """One duckdb process over the workloads in `plan` ({name: n})."""
    nvars = {}
    for name, n in plan.items():
        if name in VARIABLE_WORKLOADS:
            kinds = {"json_read_record": ("json",), "changes_record": ("doc", "edit")}.get(name, ("doc",))
            for kind in kinds:
                nvars[kind] = max(nvars.get(kind, 0), n)
    script = [setup_sql(paths, ids, nvars)]
    for name, n in plan.items():
        w = min(n, warmup if name not in DUMP_WORKLOADS else min(warmup, 1))
        if w > 0:
            script.append(timed_statement(name, "warm", w, workload_sql(name, w, paths, links)))
        script.append(timed_statement(name, "run", n, workload_sql(name, n, paths, links)))
    text = "".join(script)
    with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False, encoding="utf-8") as f:
        f.write(text)
        script_path = f.name
    try:
        with open(script_path, "rb") as f:
            p = subprocess.run([duckdb, "-batch", "-no-init"], stdin=f, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
    finally:
        os.unlink(script_path)
    out = p.stdout.decode("utf-8", "replace").splitlines()
    err = p.stderr.decode("utf-8", "replace").strip()
    return parse_output(out) + (err, p.returncode)


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=".")
    ap.add_argument("--duckdb")
    ap.add_argument("--rust-emit", help="the Rust program's --emit tree: ids.tsv and fixture/<stem>.json")
    ap.add_argument("--iters", type=int, help="starting iteration count (default: per workload)")
    ap.add_argument("--dump-iters", type=int, help="starting iteration count of dump_stream and dump_sample")
    ap.add_argument("--warmup", type=int, default=2)
    ap.add_argument("--min-time", type=float, default=0.2,
                    help="seconds a timed statement must take, else N is raised (0: no calibration)")
    ap.add_argument("--only")
    ap.add_argument("--dump")
    a = ap.parse_args(argv[1:])

    root = os.path.abspath(a.root)
    duckdb = os.path.abspath(a.duckdb) if a.duckdb else os.path.join(root, DUCKDB)
    if not os.access(duckdb, os.X_OK):
        print("bench.py: no duckdb CLI at %s (make release in yorc-duckdb, or --duckdb)" % duckdb, file=sys.stderr)
        return 2
    only = set(a.only.split(",")) if a.only else None
    known = {w for w, _ in WORKLOADS}
    if only and not only <= known:
        print("bench.py: unknown workload(s): %s" % ", ".join(sorted(only - known)), file=sys.stderr)
        return 2
    paths = {"fixture": os.path.join(root, FIXTURE), "group_id": os.path.join(root, GROUP_ID_JSON),
             "dump": os.path.abspath(a.dump) if a.dump else os.path.join(root, DUMP)}
    for what in ("fixture", "group_id", "dump"):
        if not os.path.isfile(paths[what]):
            print("bench.py: missing input %s" % paths[what], file=sys.stderr)
            return 2
    stem = os.path.basename(FIXTURE)[:-4]
    ids = None
    if a.rust_emit:
        jpath = os.path.join(a.rust_emit, "fixture", stem + ".json")
        if os.path.isfile(jpath):
            paths["json"] = os.path.abspath(jpath)
        ipath = os.path.join(a.rust_emit, "ids.tsv")
        if os.path.isfile(ipath):
            ids = read_ids(ipath)
            if ids != gen_ids(len(ids)):
                print("bench.py: note: Rust's ids.tsv differs from the ported generator; using ids.tsv",
                      file=sys.stderr)
    if ids is None:
        ids = gen_ids(N_IDS)

    plan = {}  # name -> starting iterations
    for name, default in WORKLOADS:
        if only and name not in only:
            continue
        if name in NOT_AVAILABLE:
            print("duckdb: %s: n/a (%s)" % (name, NOT_AVAILABLE[name]), file=sys.stderr)
            continue
        if name == "json_read_record" and "json" not in paths:
            print("duckdb: json_read_record: skipped (no --rust-emit tree with fixture/%s.json)" % stem,
                  file=sys.stderr)
            continue
        cap = MAX_VARIABLE_ITERS if name in VARIABLE_WORKLOADS else MAX_ITERS.get(name, 100000)
        plan[name] = max(1, min((a.dump_iters if name in DUMP_WORKLOADS else a.iters) or default, cap))
    if not plan:
        return 0

    tmp = tempfile.mkdtemp(prefix="orcid-duckdb-bench-")
    status = 0
    try:
        with open(paths["fixture"], "rb") as f:
            fixture = f.read()
        paths["edited"] = os.path.join(tmp, "edited.xml")
        with open(paths["edited"], "wb") as f:
            f.write(edited_fixture(fixture))
        links = Links(tmp)

        results, pending, setting_noted = {}, dict(plan), False
        for rnd in range(MAX_ROUNDS):
            if not pending:
                break
            bytes_of, setting, timed, err, rc = run_round(duckdb, paths, ids, pending, max(a.warmup, 0), links)
            if not setting_noted:
                setting_noted = True
                if setting is None or "common_subplan" not in setting:
                    print("duckdb: note: could not disable the common_subplan optimizer (%r); the inputs are "
                          "distinct per iteration anyway, planning may take longer" % setting, file=sys.stderr)
            nxt = {}
            for name, n in pending.items():
                t = timed.get((name, "run"))
                if t is None or t["seconds"] is None or t["rows"] <= 0:
                    print("duckdb: %s: no timing or no rows with %d iterations (see stderr below)" % (name, n),
                          file=sys.stderr)
                    status = 1
                    continue
                cap = MAX_VARIABLE_ITERS if name in VARIABLE_WORKLOADS else MAX_ITERS.get(name, 100000)
                if a.min_time > 0 and t["seconds"] < a.min_time and n < cap and rnd + 1 < MAX_ROUNDS:
                    nxt[name] = next_iters(n, t["seconds"], a.min_time, cap)
                    print("duckdb: %s: %.3f s with %d iterations, under %.3f s; again with %d"
                          % (name, t["seconds"], n, a.min_time, nxt[name]), file=sys.stderr)
                    continue
                if a.min_time > 0 and t["seconds"] < a.min_time:
                    print("duckdb: %s: note: %.3f s with %d iterations (cap or last round), under %.3f s"
                          % (name, t["seconds"], n, a.min_time), file=sys.stderr)
                results[name] = (n, t["seconds"], dict(bytes_of))
            if err and (status or rc != 0):
                print("duckdb stderr: " + err[:2000], file=sys.stderr)
            pending = nxt
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Bytes per iteration, as the Rust and Zig programs count them.
    def size(name, b):
        return {"id_normalize": b.get("ids", 0), "xml_read_record": b.get("fixture", 0),
                "rows_record": b.get("fixture", 0), "json_read_record": b.get("json", 0),
                "sha256": b.get("fixture", 0), "dump_stream": b.get("dump", 0),
                "dump_sample": b.get("dump", 0), "timeline_record": b.get("fixture", 0),
                "changes_record": b.get("fixture", 0) + b.get("edited", 0),
                "group_ids_read": b.get("group_id", 0)}[name]

    for name, _ in WORKLOADS:
        if name not in results:
            continue
        n, seconds, b = results[name]
        total_ns = max(1, int(round(seconds * 1e9)))
        nbytes = size(name, b)
        print(json.dumps({"impl": "duckdb", "workload": name, "iterations": n, "bytes": nbytes,
                          "total_ns": total_ns, "ns_per_op": total_ns // n,
                          "mb_per_s": round(nbytes * n * 1e3 / total_ns, 2)}, separators=(",", ":")))
        sys.stdout.flush()
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv))
