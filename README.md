# yorc-bench: yorc-rs, yorc-zig and yorc-duckdb compared

Benchmarks and a four-way parity check of three implementations of the
[ORCID](https://orcid.org/) message schema v3.0, against ORCID's own Java
library:

- **[yorc-rs](https://github.com/mgbilby/yorc-rs)**: the Rust crate (crate `yorc-rs`, imported as `yorc`).
- **[yorc-zig](https://github.com/mgbilby/yorc-zig)**: the Zig library (module `yorc`, plus `yorc_client`).
- **[yorc-duckdb](https://github.com/mgbilby/yorc-duckdb)**: the C++ DuckDB extension `yorc` (SQL table functions, writers and `COPY` formats).
- **ORCID orcid-model (Java)**, the established baseline: `org.orcid:orcid-model:4.0.2` from Maven Central, the JAXB classes of the v3.0 message schema that ORCID's servers use, with XML through JAXB and JSON through Jackson set up as ORCID's API sets it up. It is built in `java/` and joins the benchmarks (`run.sh --java`) and the cross-check (`compare.sh --only ...,java`), where it is the reference for reading. See [Java baseline](#java-baseline-orcids-orcid-model) and [java/FINDINGS.md](java/FINDINGS.md).

The yorc packages and this harness are independent open-source projects, not
affiliated with, endorsed by or sponsored by ORCID, Inc.; ORCID's orcid-model
is used unmodified from Maven Central as the baseline.

Everything that produced the published numbers is here: the four driver
programs, the cross-check, the summary script, and the three packages
themselves, checked out next to the harness as `yorc-rs/`, `yorc-zig/` and
`yorc-duckdb/` (git submodules, pinned to the commits measured). The
benchmark tables in each package's BENCHMARKS.md name the run in
`results/` they come from, so anyone can check them against the raw lines
and re-run the same commands on their own machine.

## Getting it

```sh
git clone --recursive https://github.com/mgbilby/yorc-bench
cd yorc-bench
```

In a clone made without `--recursive`, run `git submodule update --init
--recursive`. The recursion fetches yorc-duckdb's own submodules (DuckDB
and extension-ci-tools), which only `make release` in yorc-duckdb needs.

Prerequisites:

| for | needs |
|---|---|
| the Rust program | Rust 1.87 or later (yorc-rs's MSRV), with cargo |
| the Zig program | Zig **0.18.0-dev.131+41f885830** exactly (yorc-zig's `minimum_zig_version`, a development snapshot), as `zig` on `PATH` or in `ZIG` |
| `--java` | JDK 21 and Maven 3.6.3 or later ([Prerequisites and commands](#prerequisites-and-commands)); Maven downloads orcid-model and its dependencies on the first build |
| `--duckdb`, the three- and four-way checks | a C++17 toolchain, CMake and make (ninja optional) for `make release` in yorc-duckdb, which builds DuckDB v1.5.6 with the extension linked in |
| the summary and the DuckDB leg | Python 3.8 or later (standard library only, run with `python3 -I`) |

## Running it

```sh
# Build the Rust and Zig programs, run the two-way cross-check, then
# benchmark them on the fixtures (5 repetitions, the order rotating).
./run.sh

# All four implementations, as in the published runs. Build yorc-duckdb's CLI
# once first (and after changes to yorc-duckdb); it takes a while.
(cd yorc-duckdb && GEN=ninja make release)
./run.sh --duckdb --java

# The four-way parity check on its own (the programs built above).
./compare.sh --only rust,zig,duckdb,java

# A run's table again, as Markdown (the tables of the BENCHMARKS.md files).
python3 -I summarize.py results/<run>.jsonl --markdown
```

Each run writes `results/<date>-<HHMMSS>.jsonl` (the raw lines) and a
`.txt` next to it (toolchains, commits of the three packages, arguments,
the cross-check results, then the summary table). `./run.sh -h` lists
every option; the most used are below.

Larger inputs: `--dump PATH` streams any `.tar.gz` of ORCID XML records, for
example an ORCID Public Data File summaries archive, in `dump_stream` and in
the cross-check. The corpus figures (PARITY.md, yorc-rs's BENCHMARKS.md)
come from the 10,000-record sample of the ORCID Public Data File used on the
maintainer's machine (not distributed); with `--dump` you can make the same
measurement on a sample of your own.

```sh
./compare.sh --only rust,zig --dump PATH
./run.sh --no-build --no-check --only dump_stream --dump PATH --dump-iters 3 -k 3
# One whole Public Data File: hours. Zig reads single-member gzip only, as ORCID ships them.
./run.sh --no-build --no-check --only dump_stream -k 1 --dump-iters 1 \
  --dump ORCID_2025_10_summaries.tar.gz
```

## Published numbers

**[RESULTS.md](RESULTS.md)** shows the latest published run: its table, the
machine, the toolchains, the commits of the three packages and the
cross-check results, and a list of every published run. The packages'
BENCHMARKS.md pages link to it.

A run is published with `./run.sh --duckdb --java --populate` (or
`./populate.sh results/<run>.jsonl` after the fact). populate.sh commits
both files of the run and rewrites RESULTS.md, then pushes:

- `results/<run>.jsonl`: every line every program printed, every repetition.
  `python3 -I summarize.py results/<run>.jsonl --markdown` prints the table
  RESULTS.md shows (median over the repetitions).
- `results/<run>.txt`: the machine (CPU, OS, `BENCH_LABEL`; not the host
  name, which stays out of RESULTS.md), the toolchains, the commits of the
  harness and the three packages, the build flags, the `run.sh` arguments
  and the cross-check results.

It refuses a run that cannot back published numbers: a partial run
(`--only`), fewer than 3 repetitions, a run without the Java and DuckDB
legs, a cross-check that found differences, a run made on code other than
the checked-out commits (harness and submodules, unmodified), and a clone
behind its upstream. `./populate.sh -h` lists the checks; `--no-push`
commits without pushing.

To reproduce a run, check out the yorc-bench commit that added it (its
submodules are the code measured), build as above and run `run.sh` with
the arguments in the notes. Compare the ratios, not the absolute times:
those depend on the machine ([Reading the results](#reading-the-results)).

## What is here

It has five parts:

- **[PARITY.md](PARITY.md)** compares the features of the three, area by area. It is for users choosing between them.
- **A two-way cross-check** (`compare.sh --only rust,zig`) runs both libraries on the same inputs and diffs every output byte for byte. Byte identity is their contract.
- **A three-way cross-check** (`compare.sh`, the default) adds yorc-duckdb. It compares rows, JSON reads, and written documents (as bytes and as what yorc-rs reads back from them), class by class. With `java` in `--only` it becomes the four-way check, with ORCID's classes as the reference for reading.
- **[CROSSCHECK.md](CROSSCHECK.md)**, a static review of the three codebases. It lists every rule that differs, which side the XSDs support, and the ranked changes each implementation should take from the others.
- **Benchmarks** (`run.sh`) time the same workloads on the same inputs in two small programs (Rust and Zig), and print a comparison table. With `--java`, a third program times the ones ORCID's Java library can do. With `--duckdb`, `duckdb/bench.py` times yorc-duckdb in its duckdb CLI on the same inputs, under the same names wherever SQL has a counterpart ([DuckDB leg](#duckdb-leg-yorc-duckdb-in-sql)).

| file | what |
|---|---|
| `PARITY.md` | Feature comparison: Rust, Zig, DuckDB, parity status, and what verifies it. |
| `CROSSCHECK.md` | Static cross-review of the three: every differing rule, which is right per the XSDs, ranked recommendations. |
| `rust/` | The Rust program: a standalone Cargo project (its own empty `[workspace]`, edition 2024, MSRV 1.87). It depends on `yorc-rs` by path with `features = ["full"]`. Its `--reread DIR` mode reads what the other implementations wrote. |
| `zig/` | The Zig program: `build.zig` and `build.zig.zon`, with `yorc-zig` as a path dependency. It builds ReleaseFast by default. |
| `java/` | The Java program: a Maven project (`pom.xml`, Java 21, pinned versions, one shaded jar `target/orcid-libs-bench-java.jar`) over ORCID's `org.orcid:orcid-model:4.0.2`. Same CLI and JSON lines as the other two; `--emit DIR` writes the part of the tree Java can produce; `--reread DIR --emit OUT` reads what the others wrote with ORCID's classes and XSDs. [java/FINDINGS.md](java/FINDINGS.md) lists what it shows for the three implementations. |
| `duckdb/` | The yorc-duckdb leg: `harness.sql` (setup), `emit.py` (generates the SQL per document, runs the duckdb CLI and writes the tree), `compare3.py` (staging for `--reread`, the three-way report) and `bench.py` (the DuckDB benchmarks, JSON lines like the programs'). Python 3, standard library only, run with `python3 -I`. |
| `compare.sh` | Cross-check. Two-way: runs both programs with `--emit DIR` and compares the two output trees. Three-way: adds the duckdb leg and yorc-rs's re-read, then reports per artefact class. |
| `run.sh` | Builds both programs, runs the two-way cross-check (and the three-way one with `--duckdb`), runs the benchmarks K times, and prints the summary. |
| `summarize.py` | Builds the table from the JSON lines (`python3 -I`): Java (when there are Java lines), Rust, Zig, DuckDB (when there are DuckDB lines), the ratios Rust/Java, Zig/Java, Zig/Rust, DuckDB/Java and DuckDB/Rust, and an `average` row (geometric means). |
| `results/` | One `.jsonl` (raw lines) and one `.txt` (notes) per run. Gitignored, except the published runs and the [README](results/README.md). |

The programs were built and run against yorc-rs, yorc-zig and yorc-duckdb
0.1.0: the benchmark runs of 2026-10-19 and the four-way parity check
(PARITY.md, "Status of the checks").

## Running parts by hand

```sh
(cd rust && RUSTFLAGS="-C target-cpu=native" cargo build --release)
(cd zig && "${ZIG:-zig}" build -Doptimize=ReleaseFast)
rust/target/release/orcid-libs-bench --root . --only xml_read_record --iters 100
zig/zig-out/bin/orcid-libs-bench     --root . --only xml_read_record --iters 100
zig/zig-out/bin/orcid-libs-bench     --root . --emit /tmp/zig-out
./compare.sh --diff 3 --keep /tmp/cc3        # 3 examples per class; keep the trees
./compare.sh --only rust,zig,java --diff 3   # the Java table without DuckDB
```

The options of `run.sh` (all are listed by `./run.sh -h`):

| option | effect |
|---|---|
| `-k REPS` | Number of runs of each program (default 5). The order alternates between runs: Rust first in odd runs, Zig first in even runs. |
| `--iters N` | Iterations of every workload except `dump_stream`. The default depends on the workload (see below). |
| `--dump-iters N` | Iterations of `dump_stream` (default 20). Use 1 to 3 for a large archive. |
| `--warmup N` | Untimed iterations before each workload (default 2; at most 1 for `dump_stream`). |
| `--only W,W` | Only these workloads. |
| `--dump PATH` | The `.tar.gz` used by `dump_stream` and the cross-check. |
| `--cpu native\|baseline` | `native` (the default) builds Rust with `-C target-cpu=native` and Zig for its default native target. `baseline` uses neither. |
| `--no-zig-own` | Build and run only the headline Zig program (linked with libc, malloc). By default a second build on Zig's own allocator runs too, as `zig-own` (see caveats, "Same allocator for the headline"). `--libc` is accepted and ignored. |
| `-o FILE` | Where the raw lines go (default: `results/<date>-<HHMMSS>.jsonl`; no host name in the file name, the notes record it). |
| `--no-build`, `--no-check`, `--build-only` | Skip a stage, or stop after the build. |
| `--duckdb` | After the two-way check, also run the three-way check (needs `make release` in yorc-duckdb), and benchmark yorc-duckdb in every repetition (`duckdb/bench.py`; the order rotates over all the programs). Its iD list and the fixture's JSON come from one untimed `orcid-libs-bench --emit`. The check's result goes into the notes file; it does not change the exit status. `DUCKDB` overrides the CLI. |
| `--java` | Also build the Java program (`mvn -q package`), run it in every repetition (the order then rotates over the three: Rust, Zig, Java first in turn), and run the cross-check with Java (`compare.sh --only rust,zig[,duckdb],java`). The result goes into the notes file; it does not change the exit status. JVM flags: `JAVA_OPTS` (see "Java baseline"). |

Set `BENCH_LABEL="<cpu>, <ram>, <os>"` to record a machine description in
the notes file. `ZIG`, `CARGO`, `MVN` and `JAVA` override the tools.

Both programs take the same arguments:
`[--root DIR] [--iters N] [--dump-iters N] [--warmup N] [--only W,W] [--dump PATH | PATH]`,
or `--emit DIR [--root DIR] [--dump PATH]`. `--root` is the directory
that holds `yorc-rs/`, `yorc-zig/` and `yorc-duckdb/` (default `.`), and the
inputs are read relative to it. The Rust program also has `--reread DIR --emit OUT` (see the three-way check below).

## What is measured

The two programs run the same workloads on the same inputs, single-threaded,
in the same order. They print one JSON line per workload:

```json
{"impl":"rust","workload":"xml_read_record","iterations":30,"bytes":1324198,"total_ns":123456789,"ns_per_op":4115226,"mb_per_s":321.78}
```

- `total_ns` covers the `iterations` timed runs, after the warm-up runs.
  Rust measures it with `std::time::Instant`; Zig with `std.Io.Timestamp.now(io, .awake)`, the monotonic clock.
- `ns_per_op` is `total_ns / iterations`, rounded down.
- `mb_per_s` is `bytes × iterations / total_ns`, in 10⁶ bytes per second. It is `0.00` when `bytes` is 0.

Neither side uses a benchmark harness, so both measure the same thing. Each
result goes through `std::hint::black_box` (Rust) or
`std.mem.doNotOptimizeAway` (Zig).

| workload | one operation | `bytes` | default iterations |
|---|---|---|---:|
| `id_normalize` | Normalise 10,000 generated iDs. The list cycles through canonical, `https://`/`http://`/`orcid.org/` URL, hyphenless, space-separated and lowercase-`x` forms; one in eight is invalid (wrong check character, or too short). Both programs generate the same list with SplitMix64, seed 42. | total input length | 200 |
| `xml_read_record` | Parse the 1.3 MB real record `yorc-rs/tests/data/0000-0003-0100-6634.xml` into the model, then free it. | input size | 30 |
| `xml_write_record` | Write that model back as ORCID XML. | output size | 30 |
| `json_write_record` | Write it as ORCID JSON. | output size | 30 |
| `json_read_record` | Parse that JSON back (kind `record`). | JSON size | 30 |
| `rows_record` | Flatten the parsed record into the 11 section tables (`source_hash` precomputed). | input size | 30 |
| `sha256` | SHA-256 hex of the record. | input size | 300 |
| `dump_stream` | Open a `.tar.gz`, stream every `.xml` member and parse each one. The default input is `yorc-zig/testdata/dump/orcid_test_summaries.tgz` (8 entries). An untimed pass first checks the archive and measures it. | uncompressed member bytes | 20 |
| `group_ids_read` | Read ORCID's JSON write sample `peer-review-group-id.json`, a peer-review group-id record (Rust and Zig: and make its `group_ids` row). | input size | 10,000 (Java: 1,000) |
| `timeline_record` | The record's timeline (dated created and modified events, yorc-duckdb's `orcid_timeline` columns). | input size | 30 |
| `changes_record` | Diff the record against an in-memory copy with one work edited (yorc-duckdb's `orcid_changes` columns). | input size | 30 |
| `dump_sample` | Draw the seeded reservoir sample n = 5, seed 42 over the dump fixture (`dump::reservoir`); kept members are not read. | uncompressed member bytes | 20 |

The last four were added on 2026-10-18, after the first eight, in the
order of `summarize.py`. The DuckDB leg starts from the same defaults and
then calibrates N (see [DuckDB leg](#duckdb-leg-yorc-duckdb-in-sql)).

### Which workload times which feature

The rows of PARITY.md's "At a glance" table, and the workloads that time them:

- ORCID iD check and normalisation: `id_normalize`.
- XML read: `xml_read_record`. XML write: `xml_write_record`.
- JSON read: `json_read_record`. JSON write: `json_write_record`.
- Flat row tables: `rows_record` (DuckDB: also `xml_read_record`, which reads rows; it has no model).
- SHA-256 `source_hash`: `sha256`.
- Public Data File dumps read in place: `dump_stream`.
- Reproducible reservoir sample: `dump_sample`.
- Record timeline and snapshot diff: `timeline_record`, `changes_record`.
- Group-id records: `group_ids_read`.
- No workload (not timed): the object model as such, our JSON readable by
  ORCID's library (a check, not a speed), XSD validation, the clients,
  OAuth and rate limits (network-bound), writes, dependencies, licence.

Rust streams with `dump::open` and `dump::records`, and parses each member
with `DumpRecord::parse`. Zig uses `dump.FileArchive`, `nextXml` and `read`, then `xml.parse`.

## Cross-check (`compare.sh`)

`compare.sh` has two modes. `--only rust,zig` is the two-way check
described in this section: the contract of the two libraries, and the gate
`run.sh` uses. The default, `--only rust,zig,duckdb`, is the three-way check
of the next section.

```sh
./compare.sh --only rust,zig                  # fixtures: exit 0 if every file is identical
./compare.sh --only rust,zig --diff 20        # show the start of each diff
./compare.sh --only rust,zig --keep /tmp/cc   # keep both trees in /tmp/cc/{rust,zig}
./compare.sh --only rust,zig --dump PATH  # any .tar.gz of ORCID XML records
```

Both programs run with `--emit DIR`. Each writes the same tree, and
`compare.sh` compares the two trees file by file. It reports identical files,
differing files (with the first differing byte and line) and files that only
one side wrote.

| path | content |
|---|---|
| `ids.tsv` | `input<TAB>canonical` (or `-`) for the 10,000 generated iDs. |
| `fixture/`, `read_samples/`, `write_samples/` | One set of files per XML input: the real record, and ORCID's 53 read and 21 write samples (`yorc-rs/reference/orcid-model/record_3.0/samples/`, identical to `yorc-zig/testdata/record_3.0/samples/`). |
| `<stem>.sha256` | `hash::sha256_hex` of the input. |
| `<stem>.xml` | The input parsed, then written back as XML (`error` if the read or the write fails). |
| `<stem>.rows.tsv` | The section rows, in a fixed format: `# section<TAB>count`, then the column names and one line per row; `\N` for NULL, `true`/`false`, and `\\ \t \n \r` escaped. |
| `<stem>.json`, `<stem>.json.xml` | When the root has a JSON kind: the model written as JSON, and that JSON read back and written as XML. |
| `json_samples/{read,write}_samples/<stem>.{xml,json}` | ORCID's JSON samples read with the kind from their file name (the table of `yorc-rs/tests/json_roundtrip.rs`), then written as XML and as JSON. |
| `dump/members.tsv` | One line per `.xml` member of the dump: `stem<TAB>sha256<TAB>iD<TAB>total rows`. |

**Byte-identical output is a contract of both libraries.** Both promise exact,
deterministic writes and the same rows. So a differing file is a bug in one library (or in
one of the two programs here), never an accepted difference. Fix it and add a
test to the library at fault.

The one documented exception is JSON numbers that are not integers.
yorc-zig keeps their source text, while serde reformats them as `f64`
(yorc-zig/PARITY.md, json). ORCID's samples have none.

## Three-way cross-check (`compare.sh` with yorc-duckdb)

```sh
(cd yorc-duckdb && GEN=ninja make release)    # once: build/release/duckdb, the extension linked in
./run.sh --build-only                 # the Rust and Zig programs
./compare.sh                          # report; exit 0 only if no compared class differs
./compare.sh --diff 5                 # 5 example entries per class, with their diff
./compare.sh --diff 5 --diff-lines 80 --keep /tmp/cc3
./compare.sh --only rust,duckdb       # without Zig
./compare.sh --dump PATH
./run.sh --duckdb                     # benchmarks, plus the three-way report in the notes
```

The DuckDB leg needs `make release` in yorc-duckdb first. It uses that
build's `duckdb` CLI (`DUCKDB=...` overrides the path) and only DuckDB core
functions: the build links no `json` extension, so nothing is downloaded.
It also needs `python3` (3.8 or later, standard library only).

`compare.sh` runs these steps, all in one temporary directory (`--keep DIR`
keeps it):

1. The Rust and Zig programs run `--emit` into `rust/` and `zig/`, as in the two-way check.
2. `duckdb/emit.py` runs the duckdb CLI on `duckdb/harness.sql` plus the
   statements it generates, and writes `duckdb/` (the layout is below).
3. `duckdb/compare3.py stage` copies what each side wrote into `reread-in/`.
   Each JSON file gets a `<file>.kind` next to it: the XML root's local
   name, which is yorc-rs's JSON kind. The dump's `.xml` members are
   extracted there too.
5. `orcid-libs-bench --reread reread-in --emit reread-out` reads every
   `.xml` and `.json` file below `reread-in/` with yorc-rs. It writes
   each one's rows to `reread-out/<path>.rows.tsv` (the `--emit` format,
   `source_hash` = the SHA-256 of the file), or `error`.
6. `duckdb/compare3.py report` compares and prints the table.

The duckdb tree mirrors the Rust and Zig trees wherever yorc-duckdb has
the capability:

| path | content |
|---|---|
| `fixture/`, `read_samples/`, `write_samples/<stem>.rows.tsv` | `orcid_<section>(file)` for the 14 sections of yorc-rs's `Section::ALL` (the 11 record sections, `search_results`, `errors`, `research_resource_hosts`, with the columns appended on 2026-10-18). The format is exactly the `--emit` format: yorc-rs's column list and order (`rows.rs`), `\N`, `true`/`false`, integers in decimal, `\\ \t \n \r` escaped. Each line is built in SQL (`CAST(... AS VARCHAR)` plus the four escapes). A column this build lacks is written as `<missing column>`. |
| `json_samples/{read,write}_samples/<stem>.rows.tsv` | ORCID's JSON samples, read. |
| `json_read/{rust,zig}/<dir>/<stem>.rows.tsv` | The JSON the Rust and Zig programs wrote, read. |
| `write_samples/<stem>.{xml,json}` | Each XML write sample, read with the section readers and assembled into the writer's STRUCT: external ids, contributors, resource items and research-resource hosts (`orcid_research_resource_hosts`, by `container` and `item_ordinal`) as `LIST(STRUCT)` fields, in document order. The bulk works and a research resource's proposal and items are split by counting elements in the document, as yorc-duckdb's `test/sql/orcid_write.test` does. It is then written with `orcid_<writer>_to_xml(rec, true)` / `_to_json(rec, true)` (`orcid_bulk_works_to_*` for `bulk:bulk`) in crosswalk mode (`SET orcid_crosswalk = true` in `harness.sql` as well): yorc-rs's document bytes, so these files compare byte for byte. `error` when a writer refuses, or when the build has no crosswalk mode. |
| `<same>.verdict.txt`, `<same>.messages.txt` | `create: ok` when both writers accept, else `create: rejected`; the writers' messages. |
| `dump/members.tsv` | As the programs write it: `stem`, SHA-256, iD (the first `orcid` of the member's rows, `-` without rows), total rows. |
| `dumprows/<member path>.rows.tsv` | Every dump member's rows. |
| `<input>.group_ids.tsv`, `<input>.timeline.tsv`, `changes/old_new.changes.tsv` | `orcid_group_ids` and `orcid_timeline` of every XML input (and `group_ids` of the group-id samples), `orcid_changes` of the snapshot pair: one section each in the rows format (CROSSCHECK.md, "Bench files for group ids, timeline and changes"). |
| `extra/<key>.tsv` | The 5 sections only DuckDB has (`timeline`, `summary`, `summary_items`, `notifications`, `group_ids`), in the same format. Listed in the report, not compared. (`search_results` and `errors` moved to the compared sections when yorc-rs gained them, CROSSCHECK #7.) |
| `columns.tsv` | Every column of every section: shared, DuckDB-only or missing, with yorc-rs's and DuckDB's types (from `DESCRIBE`). |
| `json_root.tsv`, `errors.tsv`, `version.txt`, `_sql/` | JSON documents DuckDB read only with `json_root`; failed statements with DuckDB's message; DuckDB and extension versions; the generated script and DuckDB's stderr. The script can be re-run by hand: `yorc-duckdb/build/release/duckdb -batch -no-init < _sql/script.sql`. |

JSON documents are read without `json_root` first, as a user would.
DuckDB infers the document element. When that fails (an affiliation
without `path`, or `{"content": ...}`), the read is retried with
`json_root` = the kind, and the document is listed in `json_root.tsv`.

The report has one line per artefact class. Each entry of a class is one
file per implementation:

| class | entries | Rust | Zig | DuckDB | compared |
|---|---|---|---|---|---|
| rows | the record, 53 read and 21 write samples; `dump/members.tsv` | `--emit` | `--emit` | `orcid_<s>(file)` | bytes |
| dump member rows | every `.xml` member of the dump | `--reread` of the extracted member | - (no such mode) | the archive reader | bytes |
| json-read rows | ORCID's JSON samples (the 27 with a kind); the JSON the Rust and Zig programs wrote | `json::from_str(kind)` (`--reread`) | its JSON read, written as XML (`json_samples/*.xml`, `*.json.xml`), re-read by yorc-rs | `orcid_<s>(file)` | rows, `source_hash` blanked |
| written XML bytes | the 21 XML write samples | `xml::to_string` | the same | `orcid_<w>_to_xml(rec, true)`: crosswalk mode | bytes |
| written JSON bytes | the same | `json::to_string` | the same | `orcid_<w>_to_json(rec, true)` | bytes |
| written XML semantic | the same | what each wrote, re-read by yorc-rs | the same | the same | rows, `source_hash` blanked |
| written JSON semantic | the same | what each wrote, re-read by yorc-rs (kind of the sample) | the same | the same | rows, `source_hash` blanked |
| group_ids rows | `<dir>/<stem>.group_ids.tsv` for every XML input, plus ORCID's group-id JSON and XML samples | `--emit` (being added) | `--emit` (being added) | `orcid_group_ids(file)` | bytes |
| timeline rows | `<dir>/<stem>.timeline.tsv` for every XML input | `--emit` (being added) | `--emit` (being added) | `orcid_timeline(file)` | bytes |
| changes rows | `changes/old_new.changes.tsv` (yorc-duckdb's `test/data/changes` pair) | `--emit` (being added) | `--emit` (being added) | `orcid_changes(old, new)` | bytes |
| rust/zig only | every other file of the two trees (`ids.tsv`, `*.sha256`, record writes, `*.json.xml`, `json_samples/`) | | | - | bytes (the two-way contract) |

The three classes added on 2026-10-18 have the format in
[CROSSCHECK.md](CROSSCHECK.md), "Bench files for group ids, timeline and
changes". Until the Rust and Zig programs write their files, they show
`missing R` / `missing Z` and do not fail the check (`PENDING_OK` in
`compare3.py`).

The columns of the table:

- **same**: all the implementations of the class wrote identical files.
- **known Z gap**: Rust and DuckDB agree, and Zig's file equals theirs seen through yorc-zig's current layout, without the sections and columns listed in `ZIG_PENDING_SECTIONS` / `ZIG_PENDING_COLUMNS` of `compare3.py`. Both are empty now: yorc-zig has the 2026-10-18 layout ([CROSSCHECK.md](CROSSCHECK.md), "Pending: Zig", closed), so this bucket should stay at 0 until yorc-rs and yorc-duckdb get ahead again. These entries do not fail the check; any other Zig difference does. The report prints a note with their count; `python3 -I duckdb/compare3.py report ROOT WORK --known-gaps` (on a tree kept with `--keep WORK`) lists the gaps and every entry counted so. For `dump/members.tsv` it needs yorc-rs's re-read of the members (always there with DuckDB or Java in `--only`). The Java table has the same column for "J rows via XML". Remove a gap from `ZIG_PENDING_SECTIONS` / `ZIG_PENDING_COLUMNS` in `compare3.py` once yorc-zig has it.
- **R=Z!=D**, **R=D!=Z**, **Z=D!=R**: two of them agree.
- **all differ**: no two agree. With two implementations, this column counts the entries where they differ.
- **missing R / Z / D**: that implementation has the capability but wrote no file. Such an entry counts in no other column.
- **-**: the implementation has no such capability.

The byte classes are real checks for all three (CROSSCHECK #5, decided
2026-10-18). yorc-duckdb keeps its own layout by default (tabs, JSON in
schema order), but the DuckDB leg runs in crosswalk mode, which emits
exactly what yorc-rs's document writers emit for documents without
ORCID's read-only fields, which ORCID's write samples are. yorc-zig
already matches yorc-rs byte for byte. A byte difference is
therefore a bug in one of the writers, or in the DuckDB leg's assembly of
the input. The semantic level (what yorc-rs reads back from each
document) is still compared too, so a byte difference can be told apart
from a lost value. `--diff N` prints N example entries per class, each
with a `diff -u` of the two sides that differ.

Exit status: 0 when every entry of a compared class is the same (or a
known Zig gap), 1 otherwise, 2 on a setup error. Several limits of the check are listed in
CROSSCHECK.md §11, among them: rows cannot show a second host, and the
item of an external id is found by counting elements.

## Java baseline (ORCID's orcid-model)

`java/` runs ORCID's own Java library, the established implementation of
the v3.0 message schema, through the same CLI as the Rust and Zig programs.
It is the baseline for speed and the reference for reading correctness.

### What it depends on, and why this version

| artefact | version | evidence |
|---|---|---|
| `org.orcid:orcid-model` | **4.0.2** | The vendored XSDs (`yorc-duckdb/reference/orcid-model`, `yorc-rs/reference/orcid-model`) come from ORCID/orcid-model commit `9592e2d3bde21a1edf703f26f8bc304448f886fb` (PROVENANCE.md). That commit (2026-09-29, the head of `master` when this was written) has `<version>4.0.2</version>` in its `pom.xml`. Maven Central's `maven-metadata.xml` lists 4.0.2 as latest and release, last updated 2026-09-29. Its published POM is byte-identical to the commit's `pom.xml`, and every file under `record_3.0/`, `common_3.0/`, `summary_3.0/`, `notification_3.0/` and `group-id-3.0/` in the published jar is byte-identical to the vendored copy. ORCID-Source (ORCID's registry and API) pins the same version in its parent POM's `dependencyManagement`. |
| Jackson (`jackson-bom`) | 2.15.4 | `jackson.version` in both yorc-rs's and ORCID-Source's POMs. The BOM also aligns the older Jackson modules yorc-rs pulls in (swagger, `jackson-dataformat-csv` 2.5.1). |
| `jackson-module-jakarta-xmlbind-annotations` | 2.15.4 | The JAXB introspector of ORCID's JSON provider (`JacksonXmlBindJsonProvider`, `jackson-jakarta-rs-json-provider` 2.15.4 in ORCID-Source). |
| `jakarta.xml.bind-api` / `jaxb-runtime` | 3.0.1 / 3.0.2 | orcid-model 4.0.2's own dependencies. |

It is the 3.0 model: the classes are `org.orcid.jaxb.model.v3.release.*`
(`record`, `record.summary`, `common`, `error`, `search`, `groupid`,
`notification`, `client`). The jar also carries the 1.2 message, 2.0 and 2.1
models and their XSDs. Licence: the ORCID MIT-style licence (MIT, plus a
clause on ORCID's name and marks; `LICENSE` in the repository and
`yorc-duckdb/reference/orcid-model/LICENSE`). The POM declares "MIT License".

### How it is configured

The program is written to behave like ORCID's API, not like a fresh JAXB/Jackson setup:

- **XML**: one `JAXBContext` per root class, `JAXB_FORMATTED_OUTPUT = true`
  (ORCID-Source `orcid-api-common` `OrcidMarshallerContextResolver`). The
  class is picked from the document element (namespace and local name). One
  context over every class is not possible: several classes share a root
  element name (`title` four times; `research-resource` for the full and the
  summary form).
- **JSON**: ORCID registers `OrcidJacksonJaxbJsonProvider` (application/json)
  and `OrcidJacksonJaxbJsonProviderPretty` (application/vnd.orcid+json,
  application/orcid+json), both `extends JacksonXmlBindJsonProvider`. That
  provider builds `new ObjectMapper()` with
  `AnnotationIntrospector.pair(new JacksonAnnotationIntrospector(), new JakartaXmlBindAnnotationIntrospector())`
  (its `DEFAULT_ANNOTATIONS`, Jackson first). ORCID's `configureAll()` then sets
  `ACCEPT_SINGLE_VALUE_AS_ARRAY = true` and `INDENT_OUTPUT` (true for the
  Pretty provider). `Main.orcidMapper()` builds exactly that, with
  `INDENT_OUTPUT = true` (vnd.orcid+json). Everything else is Jackson's
  default: nulls are written, `FAIL_ON_UNKNOWN_PROPERTIES` is on,
  `XMLGregorianCalendar` is written as epoch milliseconds, keys follow the
  JAXB `propOrder`, and the default pretty printer writes `"key" : value`
  with two-space indentation. yorc-rs's own test `OrcidTranslator`
  (`ObjectMapper` + `JaxbAnnotationModule` + `INDENT_OUTPUT`) is close, but
  makes JAXB the primary introspector. The API's provider is the one used here.
- **XSD check**: ORCID's API checks documents against the XSD of their
  class: `JAXBSource` plus a `javax.xml.validation.Validator`
  (`JSONInputValidator` for JSON, a schema-validating `Unmarshaller` in
  `OrcidValidationJaxbContextResolver` for XML). The schemas are loaded from
  the jar by URL, so that relative imports resolve. The business rules
  (put-code on create, a title, ...) are in ORCID-Source's orcid-core
  (`ActivityValidator`), not in the model jar, and are not run.
- The JVM default time zone is set to UTC in `main`, as in `run.sh`'s
  `JAVA_OPTS`. Jackson reads timestamps in UTC anyway. This fixes how an
  `xs:dateTime` without an offset becomes epoch milliseconds.

### Workloads

| workload | Java | how |
|---|---|---|
| `id_normalize` | **n/a** | The model jar has no ORCID iD utility. `OrcidIdBase` is a bean (`uri`, `path`, `host`; `getPath()` falls back to the end of `uri`). None is hand-rolled. |
| `xml_read_record` | yes | `JAXBContext(Record).createUnmarshaller().unmarshal(...)`, one unmarshaller per operation (ORCID creates one per request). |
| `xml_write_record` | yes | A formatted marshaller per operation, into a `ByteArrayOutputStream`. |
| `json_write_record` | yes | `mapper.writeValueAsBytes(record)`. |
| `json_read_record` | yes | `mapper.readValue(json, Record.class)` on Java's own JSON of the record. |
| `rows_record` | **n/a** | ORCID's library has no rows or flattening. |
| `sha256` | yes, JDK | `java.security.MessageDigest` (SHA-256) and `HexFormat`: not an yorc-rs feature, timed only to keep the table complete. |
| `group_ids_read` | yes | `mapper.readValue(json, GroupIdRecord.class)` on ORCID's JSON write sample `peer-review-group-id.json` (2026-10-18). |
| `timeline_record`, `changes_record`, `dump_sample` | **n/a** | The model has the dates but no timeline, no diff, and no dump reader or sampler. |
| `dump_stream` | yes | `GZIPInputStream` (it reads concatenated members, like Rust's `MultiGzDecoder`) and a minimal tar reader in `Main.Tar` (ustar prefix, GNU long names, pax `path`/`size`, base-256 sizes), unmarshalling each `.xml` member with the `Record` context. The model jar has no dump reader. |

The JSON lines are the same as the other programs' (`"impl":"java"`).
Absent workloads print nothing. `summarize.py` shows `-` for them.

### JVM caveats

- **Startup is excluded.** The timing (`System.nanoTime`) is inside the
  process, around the timed iterations only. JVM start, class loading and
  the first `JAXBContext` (hundreds of milliseconds) are not counted.
- **JIT warm-up.** Each workload runs untimed first: at least `--warmup N`
  times (run.sh's value, default 2; `dump_stream` at most 1) and for at
  least `--warmup-ms` (default 3000 ms). Then a `System.gc()`, then the
  timed iterations. The numbers are therefore steady-state (C2-compiled)
  numbers. With small `--iters` they still include GC pauses.
- **GC and heap.** `run.sh` uses `JAVA_OPTS` = `-Xms2g -Xmx2g
  -XX:+UseParallelGC -XX:+AlwaysPreTouch -XX:-UsePerfData
  -Duser.timezone=UTC -Dfile.encoding=UTF-8`: a fixed 2 GiB heap, touched
  at startup, and the parallel (throughput) collector, which suits a
  single-threaded batch benchmark. G1, the JVM default, trades throughput
  for pause times. Set `JAVA_OPTS` to compare. The collector runs on other
  threads, so "single-threaded" holds for the workload code, not for the
  JVM.
- **Allocation.** JAXB and Jackson allocate a full object tree per document,
  like Rust. The JVM's allocator and GC are part of what is measured, as the
  allocators are for Rust and Zig.
- `JAVA_TOOL_OPTIONS`, if set on the host, applies too (the JVM prints
  "Picked up ..." on stderr).

### Cross-check: what Java writes, and the Java table

`--emit DIR` writes, below `java/` in compare.sh's work directory:

| path | content |
|---|---|
| `fixture/`, `read_samples/`, `write_samples/<stem>.xml` | The input unmarshalled and marshalled back (`error` when it does not read). |
| `<stem>.json`, `<stem>.json.xml` | Jackson's JSON of it, and that JSON read back by Java and marshalled. Written for every root, not only those with a Rust JSON kind. |
| `<stem>.sha256` | SHA-256 of the input (MessageDigest). |
| `write_samples/<stem>.xsd.txt` | ORCID's XSD check: `xsd: ok`, or one `xsd: <message>` line per error (not compared). |
| `json_samples/{read,write}_samples/<stem>.{xml,json}` | ORCID's JSON samples read with the class of their kind (the Rust table, plus `peer-review-group-id` → `GroupIdRecord`), marshalled and re-written. |
| `dump/members.tsv` | `stem<TAB>sha256<TAB>iD` (no row count: Java has no rows). |
| `dumpxml/<member path>` | Each `.xml` member of the dump, re-serialised. |

Not written: `ids.tsv` and `*.rows.tsv` (no such features).

`compare.sh` then stages Java's documents into `reread-in/java/`, so that
yorc-rs's `--reread` turns them into rows. It also runs
`orcid-libs-bench-java.jar --reread reread-in --emit java-reread`, which
reads every staged document of every implementation with ORCID's classes
and records `read: ok, xsd: ok|rejected|none` or `read: error`.
`compare3.py report` prints a second table, with Java as the reference:

| class | Java | compared with |
|---|---|---|
| J rows via XML | the record and samples, read and written by Java, re-read by yorc-rs | each implementation's own rows of the input |
| J rows via JSON | Java's JSON of the same, re-read by yorc-rs | Rust's JSON re-read, Zig's JSON through its XML, DuckDB's read of Rust's JSON (both sides then carry the JSON timestamp form) |
| J rows via JSON->XML | Java's JSON read back by Java, marshalled | as above |
| J json-read rows | ORCID's JSON samples read by Java, marshalled | the three-way json-read rows |
| J dump member rows | each member re-serialised by Java | Rust's `--reread` of the member; DuckDB's archive reader |
| J members | `dump/members.tsv`, first three columns | the same columns |
| J sha256 | `<stem>.sha256` | Rust, Zig |
| J accepts written documents | ORCID's read and XSD check of Java's own write | the same of each implementation's written write samples (XML and JSON) |
| J reads written JSON | ORCID's read of Java's own JSON | the same of every JSON the Rust and Zig programs wrote, and of DuckDB's written JSON (crosswalk mode; the 21 write samples, since DuckDB has no record writer: its other entries are n/a, counted nowhere) |
| J written XML / JSON bytes (info) | Java's bytes | each implementation's bytes |

Columns: `same` (every compared implementation equals Java), `R!=J`,
`Z!=J`, `D!=J` (an entry can count for several), `missing J / R / Z / D`.
`source_hash` is blanked. The classes not marked `(info)` count for the exit
status when java is in `--only`. `--diff N` shows N examples per class,
each a `diff -u` of Java against the implementation that differs.

The byte classes differ by design. JAXB writes `<?xml ... standalone="yes"?>`,
declares all 28 namespaces of the record package on the root, in its own
order, whether used or not, and indents with four spaces. Jackson writes
`null` members, JAXB `propOrder` key order, `"key" : value` and `[ {`, and
no final newline. yorc-rs and yorc-zig declare only the
namespaces used, indent with two spaces, end with a newline, and write sorted
JSON keys without nulls. yorc-duckdb indents with tabs.

What to expect, from running Java's `--emit` on the fixtures (findings in
[java/FINDINGS.md](java/FINDINGS.md)):

- All 75 XML inputs, all 27 JSON samples with a kind, the group-id sample
  and the three dump members read without error.
- The written XML of the 21 write samples and of the 1.3 MB record has the
  same element tree, attributes and text as the input.
- Java's own JSON round trip changes only timestamps, to UTC with
  milliseconds (`2001-12-31T12:00:00` → `2001-12-31T12:00:00.000Z`,
  `...-06:00` → `...Z`), which is also what yorc-rs's JSON reader produces.
- ORCID's classes drop a few things on read: `visibility` on `history` and
  on a work's `country` (no such field), the pre-3.0
  `activities:group/peer-review:summary` of read sample `peer-reviews-3.0`
  (as Rust and Zig do; DuckDB keeps it), and an
  `external-id-relationship` whose text has surrounding white space
  (read sample `research-resources-3.0`; JAXB's enum adapter does not trim).
- XSD check: every write sample passes. Read sample `work-3.0.xml` fails it
  (empty `journal-title`).

### Prerequisites and commands

JDK 21 (LTS) and Maven 3.6.3 or later (the enforcer plugin checks both).
Maven downloads the dependencies from Maven Central on the first build.

```sh
# Linux (Debian/Ubuntu)
sudo apt-get install -y openjdk-21-jdk-headless maven
# Fedora/RHEL
sudo dnf install -y java-21-openjdk-devel maven
# Any Linux, no root: Temurin 21 and Maven from the archives
#   https://adoptium.net/temurin/releases/?version=21  (tar.gz, set JAVA_HOME and PATH)
#   https://maven.apache.org/download.cgi              (apache-maven-3.9.x-bin.tar.gz)
# or with SDKMAN: sdk list java (pick a 21.x Temurin), sdk install java <that id>, sdk install maven
java -version && mvn -v          # 21.x; Maven 3.6.3+ running on JDK 21

mvn -q -f java/pom.xml package            # target/orcid-libs-bench-java.jar
J="java -Xms2g -Xmx2g -XX:+UseParallelGC -Duser.timezone=UTC -jar java/target/orcid-libs-bench-java.jar"
$J --root . --only xml_read_record --iters 100
$J --root . --emit /tmp/java-out
$J --reread /tmp/java-out --emit /tmp/java-accept    # JSON needs <file>.kind (compare3.py stage writes them)
```

## DuckDB leg (yorc-duckdb in SQL)

`run.sh --duckdb` runs `duckdb/bench.py` in each repetition, next to the
other programs. It needs `make release` in yorc-duckdb, and `DUCKDB`
overrides the CLI. To run only the DuckDB leg by hand (the Rust binary
provides the iD list and the fixture's JSON):

```sh
rust/target/release/orcid-libs-bench --emit /tmp/rust-emit --root .
python3 -I duckdb/bench.py --root . --rust-emit /tmp/rust-emit \
    [--only W,W] [--iters N] [--dump-iters N] [--warmup N] [--min-time S]
```

`run.sh` has no switch that skips Rust and Zig. `run.sh --duckdb --no-build
--only W,W -k 1` still runs both programs, and it still runs the three-way
cross-check even with `--no-check`.

**How it times.** Each round is one duckdb process with `SET threads = 1`
and the `common_subplan` optimizer disabled. Each workload runs as one SQL
statement that does all N iterations, after one untimed warm-up statement
of the same shape. `total_ns` is the shell's `.timer` value for that
statement: wall-clock time for planning plus execution, at millisecond
resolution. A `.print @@stmt` marker comes before each statement. A time
counts only if the statement's own result line comes between the marker
and the `Run Time` line, so a failed statement is reported as a failure
and never picks up another statement's time. If a statement takes less
than `--min-time` (default 0.2 s), the script raises N to about 1.25 times
the target and runs it again in a new process (at most 4 rounds). N starts
at `--iters`/`--dump-iters` or the program's default. `iterations` is the
N that was finally timed. Not timed: process start-up, extension loading
and input staging (temp tables, variables, symlinks).

**Making every iteration do the work.** Each statement ends in
`count(*)` plus `bit_xor(hash(sec_))`, where `sec_` is the table
function's alias, so the hash covers the struct of the whole row.
Projection pushdown therefore cannot drop a column, and the row count must
be > 0. No two iterations get the same input:

- File inputs go through a glob over N distinct symlinks to the file, so
  one scan reads N documents.
- In-memory documents are passed as constant arguments. Iteration i reads
  `getvariable('bench_doc_<i>')`, which holds the document plus i+1
  trailing spaces. Whitespace after the root element is insignificant, and
  the byte count stays the document's.
- A large document never goes through a lateral join (see the caveat
  below for why).

| workload | DuckDB, per iteration | bytes | what it cannot match |
|---|---|---|---|
| `id_normalize` | `orcid_normalize` over the 10,000 iDs (`bench_ids` × `range(N)`, N ≤ 1024 so the iD vectors stay flat) | sum of the iD lengths | none (`sum(length(...))` = Rust's count) |
| `xml_read_record` | the 14 sections, `orcid_<s>('<links>/f_*.xml')` | fixture | Rust/Zig parse once into a model, in memory. DuckDB reads the file and parses it 14 times (once per section), with one SHA-256 for `source_hash` each time |
| `xml_write_record`, `json_write_record` | **n/a** | | yorc-duckdb has no record writer |
| `json_read_record` | the 14 sections, `orcid_<s>_json(getvariable('bench_json_<i>'), json_root := 'record')` | the JSON (`--rust-emit`) | 14 parses and 14 hashes, as above; skipped without `--rust-emit` |
| `rows_record` | the 14 sections, `orcid_<s>_xml(getvariable('bench_doc_<i>'))` | fixture | Rust/Zig build rows from a parsed document, with the hash computed beforehand. DuckDB has no parsed document, so this is 14 parses and 14 hashes, the same as `xml_read_record` minus the file reads |
| `sha256` | DuckDB's built-in `sha256(getvariable('bench_doc_<i>'))`, one per `UNION ALL` branch | fixture | DuckDB's function is mbedtls 3.6's portable C SHA-256 (no SHA-NI), and it first copies the value into a `std::string`. yorc-duckdb's own `source_hash` uses a separate portable implementation (`src/core/sha256.cpp`) |
| `dump_stream` | `orcid_person('<links>/f_*.tgz', members := '*.xml')`: N archives, every `.xml` member decompressed and parsed | uncompressed `.xml` members | DuckDB also hashes each member (`source_hash`) and makes its person row; Rust and Zig only parse |
| `dump_sample` | `orcid_dump_sample('<links>/f_*.tgz', 5, 42)`, every column except `xml`, so no member is read | uncompressed `.xml` members | one reservoir over N archives (N passes over the tar stream) rather than N reservoirs |
| `timeline_record` | `orcid_timeline_xml(getvariable('bench_doc_<i>'))` | fixture | Rust/Zig start from a parsed document and a precomputed hash. DuckDB parses and hashes |
| `changes_record` | `orcid_changes_xml(bench_doc_<i>, bench_edit_<i>)` | fixture + edited fixture (as Rust/Zig) | `edited` is the fixture with `Edited: ` inserted after the first work summary's `<common:title>`, the same edit the programs make. DuckDB parses both snapshots once per diffed section (8 sections × 2) |
| `group_ids_read` | `bench_gid g, range(N) it, orcid_group_ids_json(CASE WHEN it.range >= 0 THEN g.doc END)` | the 154-byte JSON | the lateral join's hash aggregate and hash join (both on small keys) are in the time |

## Reading the results

`run.sh` ends with a table like this (median over the repetitions):

```text
workload                Rust ns/op   Zig ns/op  Zig/Rust  Rust MB/s  Zig MB/s  reps R/Z
xml_read_record          4,115,226   ...
```

`Zig/Rust` below 1 means Zig is faster; above 1 means Rust is faster. With
Java lines (`run.sh --java`), Java comes first (`Java ns/op`, then Rust, then
Zig) and the ratios are `Rust/Java`, `Zig/Java` and `Zig/Rust`: each is the
first one's time over the second's, so below 1 the first is faster. A last
`average` row gives each ratio column's geometric mean over the workloads it
has (the workloads Java does not run are left out of the Java columns). With
DuckDB lines (`run.sh --duckdb`), a `DuckDB ns/op` column comes last, with
the ratios `DuckDB/Java` and `DuckDB/Rust`, also averaged. Compare
ratios within one run on one machine. Absolute numbers from different machines
or builds are not comparable. The `.txt` notes file next to the `.jsonl`
records the toolchains and commits measured.

## Caveats

- **Same allocator for the headline.** Since 2026-10-19 the headline Zig
  numbers (impl `zig`) come from the Zig program linked with libc, so that
  `std.process.Init.gpa` is malloc, the same system allocator the Rust
  program uses: the comparison is then between the two libraries' code. The
  same Zig code on Zig's own default allocator (`std.heap.smp_allocator`) is
  reported next to it as `zig-own`, with the ratio `ZigOwn/Zig`
  (`--no-zig-own` skips it). Measured 2026-10-19 on the maintainer's machine (median of 3): on
  malloc Zig/Rust averages 0.52 over the 12 workloads, on its own allocator
  0.75; the own allocator costs 1.3x to 3.2x on the allocation-heavy
  workloads (rows 3.2x, timeline 2.4x, changes 2.3x, XML write 1.7x, dump
  stream 1.5x, XML read 1.3x) and nothing elsewhere. The cause is how
  `smp_allocator` serves large blocks (straight from the OS, not reused), so
  every iteration faults in fresh pages; glibc reuses the freed block. Zig
  programs choose their allocator, so this is a property of the program, not
  of yorc-zig: see yorc-zig's README, "Performance". Runs before 2026-10-19
  labelled `zig` used Zig's own allocator.
- **Allocation patterns differ by design.** `id::normalize` returns a
  `String` in Rust and a `[19]u8` value in Zig. A Zig `Document` owns one arena, while the Rust model is a
  tree of individually allocated `String`s and `Vec`s. Zig's dump reader
  reuses one member buffer; `dump::records` allocates a `Vec` per member.
  These differences are part of what is measured.
- **Optimisation levels.** Zig ReleaseFast compiles the whole program as one
  unit, without safety checks. Rust uses `--release` with `lto = "fat"` and
  `codegen-units = 1` (see `rust/Cargo.toml`). A Rust release build keeps
  slice bounds checks (integer overflow checks are off). ReleaseFast removes
  every safety check.
- **CPU target.** `zig build` targets the native CPU by default, and Rust
  targets baseline x86-64. `run.sh` therefore builds Rust with
  `-C target-cpu=native` by default; `--cpu baseline` builds both for the
  baseline. SHA-256 is the most sensitive workload: Zig selects SHA-NI at
  compile time from the target, while `sha2` detects it at run time.
- **XML and JSON implementations differ.** yorc-rs reads XML with
  quick-xml and JSON with serde_json. yorc-zig has its own scanner and uses
  `std.json`. JSON writing is the library's own code on both sides.
- **Single-threaded.** Each workload runs on one thread. Neither library
  parallelises a parse, and `run.sh` runs one program at a time. The DuckDB
  leg sets `threads = 1` (yorc-duckdb parallelises across files and archive
  members otherwise).
- **Cold vs warm cache.** Inputs are read into memory before timing, except
  for `dump_stream`, which reads the archive from disk on every iteration.
  After the untimed pass it is normally in the page cache, so the numbers
  are warm-cache numbers: decompression and parsing, not disk. For cold
  numbers, drop the page cache before a single-iteration run (Linux:
  `sync; echo 3 | sudo tee /proc/sys/vm/drop_caches`).
- **Fixture sizes.** The record is a single 1.3 MB document with 382 works.
  The default dump is 8 small entries, so `dump_stream` on it mostly measures
  setup (gzip window, tar and buffers). Use a larger archive (`--dump`)
  for throughput. In the 10,000-record sample behind the corpus figures,
  the 9,999 records other than the fixture are much smaller, so
  per-document overhead dominates there.
- **Gzip members.** Rust, Java and DuckDB read concatenated gzip members,
  and yorc-zig does since 2026-10-18 (CROSSCHECK #6). The corpus sample
  and ORCID's dumps have a single member each.
- **DuckDB's numbers include SQL execution.** The DuckDB leg
  (`duckdb/bench.py`) times one SQL statement per workload in the duckdb
  CLI. Planning, table-function calls, vectors and the aggregate over the
  result are in the time; process start-up, extension loading and staging
  the inputs are not. The workloads are the closest SQL counterparts, not
  the same operations. Every section read parses the whole document and
  hashes it once: see [DuckDB leg](#duckdb-leg-yorc-duckdb-in-sql).
  Read DuckDB's column as "what a SQL user pays", not as one library
  against another.
- **The first DuckDB run (4-way, `run.sh --duckdb --java`) is invalid for
  most workloads.** It was made by `bench.py` before 2026-10-19. Two
  DuckDB optimizations removed most of the work, and the 1 ms timer
  dominated what was left:
  - **Identical `UNION ALL` branches were computed once.** DuckDB 1.4+
    (here 1.5.6) has a common-subplan optimizer, and it materialized N
    identical `orcid_<s>(file)`, `orcid_person(dump)` and
    `orcid_dump_sample(dump, 5, 42)` branches as a single CTE. As a result,
    `xml_read_record` (3,966,667 ns), `dump_stream` (600,000 ns, an
    impossible 2.3 GB/s) and `dump_sample` (150,000 ns, 9.1 GB/s) each did
    one iteration's work divided by N. The last two were also only 12 and
    3 timer ticks.
  - **The lateral joins parsed only once per statement.** DuckDB
    decorrelates a lateral join over a VARCHAR column into a
    duplicate-eliminated join. The `_xml`/`_json`/changes/timeline function
    therefore ran once per distinct document (once per statement), and its
    rows were then hash-joined back to the N copies on the 1.3 MB string.
    That makes the `rows_record`, `json_read_record`, `timeline_record` and
    `changes_record` figures mostly key copies and compares.
  - **`sha256` was a difference of two such scans.** That difference
    (226,667 ns, "5.8 GB/s") measured the join on the 1.3 MB key, at about
    memcpy speed, not SHA-256.
  - **`group_ids_read`** (1,000 ns over 1,000 iterations) was a single
    timer tick.
  - **`id_normalize`** was a real measurement.
  - **Not the causes:** projection pushdown (the readers parse and hash
    whatever columns are projected), file caching, and the `.timer`
    parsing (it matched the right lines, though fragile).
  Discard those figures. The current script gives each iteration distinct
  inputs and no lateral join over large documents, disables
  `common_subplan`, and calibrates N to at least 0.2 s per statement.
- **Noise.** `-k 5` and the alternating order damp frequency scaling and
  thermal effects, but do not remove them. On a laptop, use AC power and an
  idle machine.
