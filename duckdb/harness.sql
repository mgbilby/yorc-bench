-- yorc-duckdb leg of the yorc-bench cross-check: the fixed setup.
--
-- emit.py (next to this file) runs the duckdb CLI that yorc-duckdb's
-- `make release` builds (yorc-duckdb/build/release/duckdb, the extension
-- linked in) on this file followed by the statements it generates for each
-- document: one INSERT per document into bench_rows (every section; each row
-- already as its TSV line, built in SQL), the writer statements per write
-- sample (in crosswalk mode, below), and COPY statements that hand the
-- tables to emit.py as CSV (the written documents hex-encoded, so their
-- bytes pass unchanged). Only core functions are used: the build links no
-- json extension. The whole generated script is kept in
-- <out>/_sql/script.sql; it can be re-run with
--   yorc-duckdb/build/release/duckdb -batch -no-init < <out>/_sql/script.sql
-- (statements read from stdin do not stop at an error, so one document that
-- fails leaves the others intact; emit.py tells failures by missing rows).

-- One thread and insertion order: rows come in document order, and the
-- sequence below numbers them in that order (REFERENCE.md, "Parallel scans
-- and row order"). emit.py --threads N appends a SET threads = N after this.
SET threads = 1;
SET preserve_insertion_order = true;
SET enable_progress_bar = false;

-- The writers emit yorc-rs's bytes (yorc-duckdb docs/REFERENCE.md,
-- "Crosswalk mode"; CROSSCHECK #5), so that compare3.py compares the written
-- documents byte for byte with the Rust and Zig ones. emit.py also passes
-- `true` as each writer's second argument, so a build without crosswalk mode
-- fails those writes (`error`) instead of writing its default layout.
SET orcid_crosswalk = true;

CREATE SEQUENCE bench_seq;

-- doc: the key emit.py gave the document; section: a section table name, or
-- '#ok' for the one row that marks a statement that ran to the end (an
-- INSERT is atomic, so a document whose read failed has no row at all);
-- line: the row in the --emit TSV format (\N, true/false, \\ \t \n \r);
-- h, orcid: its source_hash and orcid (to group the rows of a dump by member).
CREATE TABLE bench_rows (doc VARCHAR, section VARCHAR, seq BIGINT, line VARCHAR, h VARCHAR, orcid VARCHAR);

-- fmt: 'xml' or 'json'; text: what orcid_<writer>_to_<fmt> returned.
CREATE TABLE bench_written (doc VARCHAR, fmt VARCHAR, seq BIGINT, text VARCHAR);

-- '<key>#setup=<n>' once the writer input of a write sample (n items) is assembled.
CREATE TABLE bench_ok (doc VARCHAR);

-- The columns of every section, as DESCRIBE reports them (emit.py fills it
-- in a first, short run, and generates the row lines from it).
CREATE TABLE bench_columns (section VARCHAR, seq BIGINT, column_name VARCHAR, column_type VARCHAR);
