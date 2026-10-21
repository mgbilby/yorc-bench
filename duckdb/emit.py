#!/usr/bin/env python3
"""yorc-duckdb side of the three-way cross-check (README.md).

    python3 -I duckdb/emit.py --emit OUT [--root DIR] [--duckdb BIN]
        [--dump PATH] [--rust-tree DIR] [--zig-tree DIR] [--threads N]

Runs the duckdb CLI that `make release` builds in yorc-duckdb
(yorc-duckdb/build/release/duckdb, the extension linked in) on harness.sql
plus statements generated here, and writes the tree that
./compare.sh compares with the trees of the Rust and Zig programs'
--emit mode. Only what yorc-duckdb can do is written, in the same layout
and the same TSV format (`# section<TAB>count`, the column names, one line
per row; `\\N` for NULL, `true`/`false`, `\\\\ \\t \\n \\r` escaped):

  fixture/<stem>.rows.tsv, read_samples/<stem>.rows.tsv, write_samples/<stem>.rows.tsv
      orcid_<section>(file) for the 14 sections of yorc-rs's rows
      (Section::ALL: the 11 record sections, search_results, errors,
      research_resource_hosts), with yorc-rs's column list (rows.rs); a
      column DuckDB does not have is written as <missing column>. yorc-zig
      prints the same 14 sections and columns.
  json_samples/{read,write}_samples/<stem>.rows.tsv
      ORCID's JSON samples read with orcid_<section>(file).
  json_read/{rust,zig}/{fixture,read_samples,write_samples}/<stem>.rows.tsv
      the JSON the Rust and Zig programs wrote (--rust-tree, --zig-tree), read.
  write_samples/<stem>.{xml,json}
      each write sample read with the
      section readers, assembled into the writer's STRUCT (external ids,
      contributors, resource items and research-resource hosts as LIST(STRUCT)
      fields, in document order) and written with orcid_<writer>_to_xml /
      _to_json (orcid_bulk_works_to_* for bulk:bulk) in crosswalk mode
      (`SET orcid_crosswalk = true` in harness.sql, and `true` as the writers'
      second argument): exactly the bytes yorc-rs's document writers emit,
      so compare3.py compares them byte for byte with the Rust and Zig files;
      `error` when the writer refuses (or when the build has no crosswalk mode).
  write_samples/<stem>.messages.txt
      why a writer refused the input, when one did (not compared).
  fixture/<stem>.group_ids.tsv, read_samples/<stem>.group_ids.tsv, write_samples/<stem>.group_ids.tsv,
  json_samples/write_samples/peer-review-group-id.group_ids.tsv, group_id/group-id-3.0.group_ids.tsv
      orcid_group_ids(file): one section in the rows format (`# group_ids<TAB>count`,
      then the 12 column names and the rows if any)
  fixture/<stem>.timeline.tsv, read_samples/<stem>.timeline.tsv, write_samples/<stem>.timeline.tsv
      orcid_timeline(file), the same way (13 columns)
  changes/<pair>.changes.tsv
      orcid_changes(old, new) for each pair of compare3.CHANGES_PAIRS (9 columns)
      (these three: CROSSCHECK.md, "Bench files for group ids,
      timeline and changes"; the Rust and Zig programs are adding them)
  dump/members.tsv
      `stem<TAB>sha256<TAB>iD<TAB>total rows` per .xml member of the dump, as
      the Rust and Zig programs write it; iD is the first `orcid` of the
      member's rows (`-` without rows).
  dumprows/<member path>.rows.tsv
      the rows of every dump member (compare.sh re-reads the extracted
      members with yorc-rs for the other side).

Not compared, listed for reference: extra/<key>.tsv (the 5 sections only
DuckDB has: timeline, summary, summary_items, notifications, group_ids),
columns.tsv (each section's columns: shared,
DuckDB-only or missing, with both types), json_root.tsv (JSON documents that
DuckDB read only with json_root), errors.tsv (statements that failed, with
DuckDB's message), version.txt, _sql/ (the script and DuckDB's stderr).

Exit status: 0 when the tree is written (failures of single documents are
in the tree), 2 on a setup error (no duckdb binary, the script did not run).
"""

import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = "yorc-rs/tests/data/0000-0003-0100-6634.xml"
SAMPLES = "yorc-rs/reference/orcid-model/record_3.0/samples"
DUMP = "yorc-zig/testdata/dump/orcid_test_summaries.tgz"
DUCKDB = "yorc-duckdb/build/release/duckdb"
ERROR_TEXT = "error\n"
MAX_RERUNS = 300

# The 14 sections of yorc-rs's rows module, in Section::ALL order, with
# its column names and types (yorc-rs/src/rows.rs; V VARCHAR, I INTEGER,
# L BIGINT, B BOOLEAN): the 11 record sections, then search_results and
# errors (CROSSCHECK #7) and research_resource_hosts (#9), with the columns
# #10 appended to 9 of them (yorc-duckdb docs/COVERAGE.md, "Columns added on
# 2026-10-18"). yorc-duckdb has the same tables (docs/REFERENCE.md);
# columns.tsv records any difference. yorc-zig has the same 14 sections and
# columns (CROSSCHECK.md, "Pending: Zig", closed).
_SECTIONS = (
    ("works", "orcid:V put_code:L group_index:I display_index:I title:V subtitle:V journal:V type:V pub_year:I "
     "pub_month:I pub_day:I doi:V url:V source_name:V visibility:V created:V last_modified:V source_hash:V "
     "translated_title:V translated_title_language:V short_description:V citation_type:V citation_value:V "
     "language_code:V country:V path:V source_client_id:V source_orcid:V assertion_origin_name:V "
     "assertion_origin_orcid:V assertion_origin_client_id:V item:V"),
    ("fundings", "orcid:V put_code:L group_index:I display_index:I title:V translated_title:V "
     "translated_title_language:V type:V organization_defined_type:V short_description:V amount:V "
     "currency:V start_year:I start_month:I start_day:I end_year:I end_month:I end_day:I org_name:V "
     "org_city:V org_region:V org_country:V org_disambiguated_id:V org_disambiguation_source:V url:V "
     "visibility:V path:V source_name:V source_client_id:V source_orcid:V assertion_origin_name:V "
     "created:V last_modified:V item:V source_hash:V assertion_origin_orcid:V assertion_origin_client_id:V"),
    ("affiliations", "orcid:V affiliation_type:V put_code:L group_index:I display_index:I department:V "
     "role_title:V start_year:I start_month:I start_day:I end_year:I end_month:I end_day:I org_name:V "
     "org_city:V org_region:V org_country:V org_disambiguated_id:V org_disambiguation_source:V url:V "
     "visibility:V path:V source_name:V source_client_id:V source_orcid:V assertion_origin_name:V "
     "created:V last_modified:V item:V source_hash:V assertion_origin_orcid:V assertion_origin_client_id:V"),
    ("peer_reviews", "orcid:V put_code:L group_index:I display_index:I reviewer_role:V review_type:V "
     "review_url:V completion_year:I completion_month:I completion_day:I review_group_id:V subject_type:V "
     "subject_name:V subject_subtitle:V subject_translated_name:V subject_container_name:V subject_url:V "
     "subject_id_type:V subject_id_value:V convening_org_name:V convening_org_city:V "
     "convening_org_region:V convening_org_country:V convening_org_disambiguated_id:V "
     "convening_org_disambiguation_source:V visibility:V path:V source_name:V source_client_id:V "
     "source_orcid:V assertion_origin_name:V created:V last_modified:V item:V source_hash:V "
     "subject_translated_name_language:V assertion_origin_orcid:V assertion_origin_client_id:V"),
    ("research_resources", "orcid:V put_code:L group_index:I display_index:I title:V translated_title:V "
     "translated_title_language:V host_name:V host_city:V host_region:V host_country:V "
     "host_disambiguated_id:V host_disambiguation_source:V start_year:I start_month:I start_day:I "
     "end_year:I end_month:I end_day:I url:V visibility:V path:V source_name:V source_client_id:V "
     "source_orcid:V assertion_origin_name:V created:V last_modified:V item:V source_hash:V "
     "assertion_origin_orcid:V assertion_origin_client_id:V"),
    ("research_resource_items", "orcid:V owner_put_code:L ordinal:I resource_name:V resource_type:V "
     "host_name:V host_city:V host_region:V host_country:V host_disambiguated_id:V "
     "host_disambiguation_source:V url:V source_hash:V"),
    ("contributors", "orcid:V owner:V owner_put_code:L ordinal:I contributor_orcid:V contributor_orcid_uri:V "
     "credit_name:V email:V sequence:V role:V source_hash:V contributor_orcid_host:V"),
    ("external_ids", "orcid:V owner:V owner_put_code:L group_index:I container:V type:V value:V normalized:V "
     "normalized_error:V url:V relationship:V source_hash:V normalized_error_code:V"),
    ("person", "orcid:V given_names:V family_name:V credit_name:V name_visibility:V biography:V "
     "biography_visibility:V last_modified:V name_last_modified:V biography_last_modified:V path:V item:V "
     "source_hash:V orcid_uri:V orcid_host:V"),
    ("person_items", "orcid:V kind:V put_code:L display_index:I value:V url:V type:V relationship:V verified:B "
     "primary:B visibility:V path:V source_name:V source_client_id:V source_orcid:V created:V "
     "last_modified:V source_hash:V assertion_origin_name:V assertion_origin_orcid:V "
     "assertion_origin_client_id:V normalized:V normalized_error:V normalized_error_code:V"),
    ("history", "orcid:V creation_method:V completion_date:V submission_date:V last_modified:V claimed:B "
     "deactivation_date:V verified_email:B verified_primary_email:B visibility:V source_name:V "
     "source_client_id:V source_orcid:V source_hash:V assertion_origin_name:V assertion_origin_orcid:V "
     "assertion_origin_client_id:V"),
    ("search_results", "num_found:L ordinal:I orcid:V orcid_uri:V orcid_host:V given_names:V family_names:V "
     "credit_name:V other_names:V emails:V institution_names:V item:V source_hash:V"),
    ("errors", "orcid:V response_code:I developer_message:V user_message:V error_code:I more_info:V "
     "container:V position:I source_hash:V primary_orcid:V"),
    ("research_resource_hosts", "orcid:V owner_put_code:L ordinal:I host_name:V host_city:V host_region:V "
     "host_country:V host_disambiguated_id:V host_disambiguation_source:V container:V item_ordinal:I "
     "source_hash:V"),
)
TYPES = {"V": "VARCHAR", "I": "INTEGER", "L": "BIGINT", "B": "BOOLEAN"}
SECTIONS = [(name, [c.split(":") for c in cols.split()]) for name, cols in _SECTIONS]
SHARED = [name for name, _ in SECTIONS]
EXTRA = ["timeline", "summary", "summary_items", "notifications", "group_ids"]
# Bench files of single sections (compare3.py: group_ids rows, timeline rows),
# and orcid_changes's columns (yorc-duckdb docs/REFERENCE.md) with the pairs.
BENCH_SECTIONS = ("group_ids", "timeline")
GROUP_ID_JSON = "json_samples/write_samples/peer-review-group-id"
# ORCID's group-id XML sample (group-id-3.0.xsd's sample; yorc-rs vendors the same bytes
# in reference/orcid-model/group-id-3.0/samples since 2026-10-18)
GROUP_ID_XML = ("group_id/group-id-3.0", "yorc-duckdb/reference/orcid-model/group-id-3.0/samples/group-id-3.0.xml")
CHANGES_COLS = ["orcid", "section", "kind", "put_code", "change", "field", "old_value", "new_value", "label"]
CHANGES_PAIRS = (
    ("old_new", "yorc-duckdb/test/data/changes/old.xml", "yorc-duckdb/test/data/changes/new.xml"),
)

# Kind of an ORCID JSON sample from its file name: the table of the Rust and
# Zig programs (yorc-rs/tests/json_roundtrip.rs); "" = not a record document.
JSON_SAMPLE_KINDS = (
    ("record-full", "record"), ("address", "address"), ("bulk-", "bulk"), ("distinction", "distinction"),
    ("education", "education"), ("employment", "employment"), ("external-identifier", "external-identifier"),
    ("funding", "funding"), ("invited-position", "invited-position"), ("keywords", "keyword"),
    ("membership", "membership"), ("other-names", "other-name"), ("peer-review-group-id", ""),
    ("peer-review", "peer-review"), ("qualification", "qualification"), ("research-resource", "research-resource"),
    ("researcher-url", "researcher-url"), ("service", "service"), ("work", "work"),
)

AFFILIATIONS = ("distinction", "education", "employment", "invited-position", "membership", "qualification", "service")
PERSON_ITEMS = ("address", "keyword", "other-name", "researcher-url", "external-identifier")
BIG = 1 << 62

COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
ROOT_RE = re.compile(r"<(?![?!/])(?:[A-Za-z_][\w.-]*:)?([A-Za-z_][\w.-]*)")
WORK_RE = re.compile(r"<(?:[\w.-]+:)?work(?=[\s/>])")
ITEM_RE = re.compile(r"<(?:[\w.-]+:)?resource-item(?=[\s/>])")
EXT_RE = re.compile(r"<(?:[\w.-]+:)?external-id(?=[\s/>])")
CON_RE = re.compile(r"<(?:[\w.-]+:)?contributor(?=[\s/>])")


def json_sample_kind(name):
    for prefix, kind in JSON_SAMPLE_KINDS:
        if name.startswith(prefix):
            return kind or None
    return None


def root_name(path):
    """Local name of the document element of an XML file (None if unreadable)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = COMMENT_RE.sub("", f.read(1 << 16))
    except OSError:
        return None
    m = ROOT_RE.search(text)
    return m.group(1) if m else None


def writer_of(root):
    """(writer, items section, list fields) of a write document's root."""
    if root == "work":
        return "work", "works", ("external_ids", "contributors")
    if root == "bulk":
        return "bulk_works", "works", ("external_ids", "contributors")
    if root == "funding":
        return "funding", "fundings", ("external_ids", "contributors")
    if root in AFFILIATIONS:
        return "affiliation", "affiliations", ("external_ids",)
    if root == "peer-review":
        return "peer_review", "peer_reviews", ("external_ids",)
    if root == "research-resource":
        return "research_resource", "research_resources", ("external_ids", "resource_items")
    if root in PERSON_ITEMS:
        return "person_item", "person_items", ()
    if root == "group-id-record":
        return "group_id", "group_ids", ()
    return None


def splits(root, text, lists):
    """(list, item k, first, last): which rows of a list field (1-based, in
    document order) belong to which item. The readers cannot tell them apart
    in a bulk (no put-codes) or in a research resource (proposal and items
    share the owner), so they are counted in the document text, as
    yorc-duckdb's own test/sql/orcid_write.test does by hand. Item 0 is a
    research resource's proposal."""
    out = []
    if root not in ("bulk", "research-resource"):
        for name in ("external_ids", "contributors"):
            if name in lists:
                out.append((name, 1, 1, BIG))
        return out
    body = COMMENT_RE.sub("", text)
    if root == "bulk":
        segments = list(enumerate(WORK_RE.split(body)[1:], 1))
    else:
        segments = list(enumerate(ITEM_RE.split(body)))
    e = c = 0
    for k, seg in segments:
        ne, nc = len(EXT_RE.findall(seg)), len(CON_RE.findall(seg))
        if "external_ids" in lists and ne:
            out.append(("external_ids", k, e + 1, e + ne))
        if "contributors" in lists and nc:
            out.append(("contributors", k, c + 1, c + nc))
        e += ne
        c += nc
    return out


def q(s):
    return "NULL" if s is None else "'" + s.replace("'", "''") + "'"


def ident(name):
    return '"' + name.replace('"', '""') + '"'


def enc(col):
    """SQL for one cell in the --emit TSV format: \\N for NULL, the value
    cast to VARCHAR (integers in decimal, booleans true/false) with
    backslash, TAB, LF and CR escaped, as both bench programs write them."""
    c = "x." + ident(col)
    return ("CASE WHEN %s IS NULL THEN '\\N' ELSE replace(replace(replace(replace(CAST(%s AS VARCHAR), "
            "'\\', '\\\\'), chr(9), '\\t'), chr(10), '\\n'), chr(13), '\\r') END" % (c, c))


def line_expr(cols, present):
    """The TSV line of a row: `cols` in order; a column DuckDB lacks is
    written as <missing column>. cols None: the whole row cast to text."""
    if cols is None:
        return "replace(replace(CAST(x AS VARCHAR), chr(9), '\\t'), chr(10), '\\n')"
    parts = [enc(c) if (present is None or c in present) else "'<missing column>'" for c in cols]
    return " || chr(9) || ".join(parts) if parts else "''"


def rows_tsv(by_section, sections):
    """`# section<TAB>count`, then (if any rows) the column names and the lines."""
    out = []
    for name, cols in sections:
        lines = by_section.get(name, [])
        out.append("# %s\t%d\n" % (name, len(lines)))
        if not lines:
            continue
        out.append("\t".join(cols) + "\n")
        for line in lines:
            out.append(line + "\n")
    return "".join(out)


def member_path(member):
    """An archive member path as a relative path ('' if it would escape)."""
    parts = [p for p in member.replace("\\", "/").split("/") if p not in ("", ".")]
    if ".." in parts:
        return ""
    return "/".join(parts)


def xml_stem(name):
    return name[:-4] if len(name) > 4 and name[-4:].lower() == ".xml" else name


def put(out, rel, text):
    path = os.path.join(out, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(text.encode("utf-8") if isinstance(text, str) else text)


def listing(d, ext):
    try:
        return sorted(n for n in os.listdir(d) if n.endswith(ext) and os.path.isfile(os.path.join(d, n)))
    except OSError:
        return []


class Script:
    """The generated statements, grouped so that one can be re-run for its error."""

    def __init__(self, setup):
        self.setup = setup
        self.parts = []
        self.groups = {}

    def add(self, sql, group=None):
        self.parts.append(sql)
        if group is not None:
            self.groups.setdefault(group, []).append(sql)

    def text(self):
        return self.setup + "".join(self.parts)


class Layout:
    """Which columns each section has in this build of yorc-duckdb."""

    def __init__(self, columns):
        self.columns = columns  # section -> [(name, type)] from DESCRIBE

    def shared(self, section):
        cols = [c for c, _ in dict(SECTIONS)[section]]
        have = self.columns.get(section)
        return cols, ({c for c, _ in have} if have else None)

    def extra(self, section):
        have = self.columns.get(section)
        return ([c for c, _ in have], None) if have else (None, None)


def rows_statement(layout, key, path, sections, json_root=None, members=None):
    """One INSERT: a '#ok' row, then every row of `sections` as its TSV line."""
    opts = ", json_root := %s" % q(json_root)
    if members is not None:
        opts += ", members := %s" % q(members)
    parts = ["SELECT %s, '#ok', nextval('bench_seq'), NULL, NULL, NULL" % q(key)]
    for s in sections:
        cols, present = layout.shared(s) if s in SHARED else layout.extra(s)
        hcol = "CAST(x.source_hash AS VARCHAR)" if present is None or "source_hash" in present else "NULL"
        ocol = "CAST(x.orcid AS VARCHAR)" if s in SHARED and (present is None or "orcid" in present) else "NULL"
        parts.append("SELECT %s, %s, nextval('bench_seq'), %s, %s, %s FROM orcid_%s(%s%s) x"
                     % (q(key), q(s), line_expr(cols, present), hcol if s in SHARED else "NULL", ocol, s,
                        q(path), opts))
    return "INSERT INTO bench_rows\n  " + "\n  UNION ALL ".join(parts) + ";\n"


def write_statements(n, key, path, root, text):
    """Statements that read a write document and write it back (None: no writer)."""
    w = writer_of(root)
    if w is None:
        return None
    writer, items, lists = w
    t = "bench_w%d" % n
    p = q(path)
    s = ["CREATE TABLE %s_i AS SELECT nextval('bench_seq') AS seq, x AS rec FROM orcid_%s(%s) x;\n" % (t, items, p)]
    sources = (("external_ids", "e", "external_ids"), ("contributors", "c", "contributors"),
               ("resource_items", "r", "research_resource_items"))
    for field, short, section in sources:
        if field in lists:
            s.append("CREATE TABLE %s_%s AS SELECT nextval('bench_seq') AS seq, x AS rec FROM orcid_%s(%s) x;\n"
                     % (t, short, section, p))
    split = splits(root, text, lists) or [("none", -1, 1, 0)]
    s.append("CREATE TABLE %s_s (field VARCHAR, k INTEGER, lo BIGINT, hi BIGINT);\n" % t)
    s.append("INSERT INTO %s_s VALUES %s;\n" % (t, ", ".join("(%s, %d, %d, %d)" % (q(a), k, lo, hi)
                                                         for a, k, lo, hi in split)))
    for field, short, _ in sources[:2]:
        if field in lists:
            s.append("CREATE TABLE %s_l%s AS SELECT s.k, list(x.rec ORDER BY x.seq) AS l\n"
                     "  FROM (SELECT seq, rec, row_number() OVER (ORDER BY seq) AS r FROM %s_%s) x\n"
                     "  JOIN %s_s s ON s.field = %s AND x.r BETWEEN s.lo AND s.hi GROUP BY s.k;\n"
                     % (t, short, t, short, t, q(field)))
    s.append("CREATE TABLE %s_it AS SELECT row_number() OVER (ORDER BY seq) AS k, rec FROM %s_i;\n" % (t, t))
    if writer == "research_resource":
        # every host (CROSSCHECK #9), told apart by container and item_ordinal;
        # the flat first-host fields agree with the lists (the readers derive them)
        s.append("CREATE TABLE %s_h AS SELECT nextval('bench_seq') AS seq, x AS rec\n"
                 "  FROM orcid_research_resource_hosts(%s) x;\n" % (t, p))
        s.append("CREATE TABLE %s_ri AS SELECT r.k, struct_insert(r.rec, external_ids := le.l,\n"
                 "    hosts := (SELECT list(h.rec ORDER BY h.seq) FROM %s_h h\n"
                 "              WHERE h.rec.container = 'resource-item' AND h.rec.item_ordinal = r.k)) AS rec\n"
                 "  FROM (SELECT row_number() OVER (ORDER BY seq) AS k, rec FROM %s_r) r LEFT JOIN %s_le le USING (k);\n"
                 % (t, t, t, t))
        s.append("CREATE TABLE %s_rec AS SELECT it.k, struct_insert(it.rec,\n"
                 "    external_ids := (SELECT l FROM %s_le WHERE k = 0),\n"
                 "    hosts := (SELECT list(rec ORDER BY seq) FROM %s_h WHERE rec.container = 'proposal'),\n"
                 "    resource_items := (SELECT list(rec ORDER BY k) FROM %s_ri)) AS rec\n"
                 "  FROM %s_it it;\n" % (t, t, t, t, t))
    elif lists:
        short = {"external_ids": "e", "contributors": "c"}
        fields = ", ".join("%s := l%s.l" % (f, short[f]) for f in lists)
        joins = " ".join("LEFT JOIN %s_l%s l%s USING (k)" % (t, short[f], short[f]) for f in lists)
        s.append("CREATE TABLE %s_rec AS SELECT it.k, struct_insert(it.rec, %s) AS rec FROM %s_it it %s;\n"
                 % (t, fields, t, joins))
    else:
        s.append("CREATE TABLE %s_rec AS SELECT k, rec FROM %s_it;\n" % (t, t))
    s.append("INSERT INTO bench_ok SELECT %s || CAST(count(*) AS VARCHAR) FROM %s_rec;\n" % (q(key + "#setup="), t))
    writes = {}
    for fmt in ("xml", "json"):
        # crosswalk mode (yorc-rs's bytes): the argument, so that a build
        # without it fails loudly instead of writing its default layout
        if writer == "bulk_works":
            expr = "orcid_bulk_works_to_%s(list(rec ORDER BY k), true)" % fmt
        else:
            expr = "orcid_%s_to_%s(rec, true)" % (writer, fmt)
        writes[fmt] = ("INSERT INTO bench_written SELECT %s, '%s', nextval('bench_seq'), %s FROM %s_rec;\n"
                       % (q(key), fmt, expr, t))
    return "".join(s), writes


def run_duckdb(duckdb, script):
    p = subprocess.run([duckdb, "-batch", "-no-init"], input=script.encode("utf-8"),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def one_line(msg):
    msg = " | ".join(line.strip() for line in msg.strip().splitlines() if line.strip())
    return msg or "failed (no message)"


def read_csv(path):
    """Rows of a CSV file DuckDB's COPY wrote (empty if there is none)."""
    csv.field_size_limit(min(sys.maxsize, 2 ** 31 - 1))  # a hex-encoded bulk of works is large
    try:
        with open(path, encoding="utf-8", newline="") as f:
            return list(csv.reader(f))
    except OSError:
        return []


def copy_csv(select, path):
    return "COPY (%s) TO %s (FORMAT csv, HEADER false);\n" % (select, q(path))


def unhex(s):
    return bytes.fromhex(s).decode("utf-8") if s else None


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--emit", required=True, help="output tree")
    ap.add_argument("--root", default=".", help="the directory holding yorc-rs/, yorc-zig/ and yorc-duckdb/ [.]")
    ap.add_argument("--duckdb", help="duckdb CLI with orcid linked in [ROOT/%s]" % DUCKDB)
    ap.add_argument("--dump", help="dump to read [ROOT/%s]" % DUMP)
    ap.add_argument("--rust-tree", help="the Rust program's --emit tree (its JSON is read)")
    ap.add_argument("--zig-tree", help="the Zig program's --emit tree (its JSON is read)")
    ap.add_argument("--threads", type=int, default=1, help="DuckDB threads [1]")
    a = ap.parse_args(argv[1:])

    root = os.path.abspath(a.root)
    out = os.path.abspath(a.emit)
    duckdb = os.path.abspath(a.duckdb) if a.duckdb else os.path.join(root, DUCKDB)
    if not os.access(duckdb, os.X_OK):
        print("emit.py: no duckdb CLI at %s: build it with `make release` in yorc-duckdb (or pass --duckdb)"
              % duckdb, file=sys.stderr)
        return 2
    dump = os.path.abspath(a.dump) if a.dump else os.path.join(root, DUMP)
    samples = os.path.join(root, SAMPLES)
    os.makedirs(out, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="orcid-duckdb-leg.")
    try:
        return emit(a, root, out, duckdb, dump, samples, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def inventory(duckdb, setup, tmp, out):
    """section -> [(column, type)], from DESCRIBE in a first short run."""
    path = os.path.join(tmp, "columns.csv")
    sql = setup
    for s in SHARED + EXTRA:
        sql += ("INSERT INTO bench_columns SELECT %s, nextval('bench_seq'), column_name, column_type\n"
                "  FROM (DESCRIBE SELECT * FROM orcid_%s_xml(NULL));\n" % (q(s), s))
    sql += copy_csv("SELECT section, column_name, column_type FROM bench_columns ORDER BY seq", path)
    _, _, err = run_duckdb(duckdb, sql)
    put(out, "_sql/columns.sql", sql)
    put(out, "_sql/columns.stderr.txt", err)
    columns = {}
    for section, name, ty in (r for r in read_csv(path) if len(r) == 3):
        columns.setdefault(section, []).append((name, ty))
    return columns


def emit(a, root, out, duckdb, dump, samples, tmp):
    with open(os.path.join(HERE, "harness.sql"), encoding="utf-8") as f:
        setup = f.read()
    if a.threads != 1:
        setup += "SET threads = %d;\n" % a.threads
    columns = inventory(duckdb, setup, tmp, out)
    if not columns:
        print("emit.py: DESCRIBE gave no columns (see %s); assuming yorc-rs's"
              % os.path.join(out, "_sql/columns.stderr.txt"), file=sys.stderr)
    layout = Layout(columns)
    sc = Script(setup)

    # Documents read into rows: (key, path, json kind or "" for none, extras?)
    docs = [("fixture/" + os.path.basename(FIXTURE)[:-4], os.path.join(root, FIXTURE), "", True)]
    for d in ("read_samples", "write_samples"):
        for name in listing(os.path.join(samples, d), ".xml"):
            docs.append(("%s/%s" % (d, name[:-4]), os.path.join(samples, d, name), "", True))
    for d in ("read_samples", "write_samples"):
        for name in listing(os.path.join(samples, d), ".json"):
            kind = json_sample_kind(name) or ""
            docs.append(("json_samples/%s/%s" % (d, name[:-5]), os.path.join(samples, d, name), kind, True))
    docs.append((GROUP_ID_XML[0], os.path.join(root, GROUP_ID_XML[1]), "", True))
    for impl, tree in (("rust", a.rust_tree), ("zig", a.zig_tree)):
        if not tree:
            continue
        for d in ("fixture", "read_samples", "write_samples"):
            for name in listing(os.path.join(tree, d), ".json"):
                stem = name[:-5]
                src = os.path.join(root, FIXTURE) if d == "fixture" else os.path.join(samples, d, stem + ".xml")
                kind = root_name(src) or ""
                docs.append(("json_read/%s/%s/%s" % (impl, d, stem), os.path.abspath(os.path.join(tree, d, name)),
                             kind, False))

    for key, path, kind, extras in docs:
        sc.add(rows_statement(layout, key, path, SHARED), group=key)
        if kind:
            sc.add(rows_statement(layout, key + "#json_root", path, SHARED, json_root=kind), group=key + "#json_root")
        if extras:
            sc.add(rows_statement(layout, key + "!extra", path, EXTRA), group=key + "!extra")
            if kind:
                sc.add(rows_statement(layout, key + "!extra#json_root", path, EXTRA, json_root=kind),
                       group=key + "!extra#json_root")

    # Write documents: the XML write samples.
    writes = []
    inputs = [("write_samples", os.path.join(samples, "write_samples"))]
    n = 0
    for d, src in inputs:
        for name in listing(src, ".xml"):
            path = os.path.join(src, name)
            key = "%s/%s" % (d, name[:-4])
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
            n += 1
            st = write_statements(n, key, path, root_name(path), text)
            if st is None:
                continue
            setup_sql, w = st
            sc.add(setup_sql, group=key + "#setup")
            for fmt in ("xml", "json"):
                sc.add(w[fmt], group=key + "#" + fmt)
            writes.append(key)

    for pair, old_rel, new_rel in CHANGES_PAIRS:
        key = "changes/" + pair
        sc.add("INSERT INTO bench_rows\n  SELECT %s, '#ok', nextval('bench_seq'), NULL, NULL, NULL\n"
               "  UNION ALL SELECT %s, 'changes', nextval('bench_seq'), %s, NULL, NULL FROM orcid_changes(%s, %s) x;\n"
               % (q(key), q(key), line_expr(CHANGES_COLS, None), q(os.path.join(root, old_rel)),
                  q(os.path.join(root, new_rel))), group=key)

    have_dump = os.path.isfile(dump)
    if have_dump:
        sc.add("CREATE TABLE bench_dump AS SELECT nextval('bench_seq') AS seq, member, name, sha256(xml) AS h\n"
               "  FROM orcid_documents(%s, members := '*.xml');\n" % q(dump), group="dump#documents")
        sc.add(rows_statement(layout, "dump", dump, SHARED, members="*.xml"), group="dump")

    files = {k: os.path.join(tmp, k + ".csv") for k in ("rows", "written", "ok", "dump", "version")}
    sc.add(copy_csv("SELECT doc, section, line, h, orcid FROM bench_rows ORDER BY seq", files["rows"]))
    sc.add(copy_csv("SELECT doc, fmt, hex(text) FROM bench_written ORDER BY seq", files["written"]))
    sc.add(copy_csv("SELECT doc FROM bench_ok", files["ok"]))
    if have_dump:
        sc.add(copy_csv("SELECT member, name, h FROM bench_dump ORDER BY seq", files["dump"]))
    sc.add(copy_csv("SELECT version(), (SELECT extension_version FROM duckdb_extensions() "
                    "WHERE extension_name = 'yorc')", files["version"]))

    script = sc.text()
    put(out, "_sql/script.sql", script)
    print("duckdb: running %s (%d statements)" % (duckdb, len(sc.parts)), file=sys.stderr)
    rc, _, err = run_duckdb(duckdb, script)
    put(out, "_sql/stderr.txt", err)
    if not os.path.exists(files["rows"]):
        print("emit.py: the script did not run to its end (exit %d); see %s"
              % (rc, os.path.join(out, "_sql/stderr.txt")), file=sys.stderr)
        return 2

    # ------------------------------------------------------------ the results
    rows = {}
    for rec in read_csv(files["rows"]):
        if len(rec) != 5:
            continue
        doc_key, section, line, h, orcid = rec
        doc = rows.setdefault(doc_key, {"ok": False, "sections": {}, "rows": []})
        if section == "#ok":
            doc["ok"] = True
            continue
        doc["sections"].setdefault(section, []).append(line)
        doc["rows"].append((section, line, h, orcid))
    written = {}
    for rec in read_csv(files["written"]):
        if len(rec) == 3:
            written.setdefault((rec[0], rec[1]), []).append(unhex(rec[2]))
    items = {}  # write key -> number of items its writer input has
    for rec in read_csv(files["ok"]):
        key, _, count = (rec[0] if rec else "").rpartition("#setup=")
        if key and count.isdigit():
            items[key] = int(count)

    errors = []
    reruns = [0]

    def message(groups):
        if reruns[0] >= MAX_RERUNS:
            return "failed (message not collected: more than %d failures)" % MAX_RERUNS
        reruns[0] += 1
        sql = "".join("".join(sc.groups.get(g, [])) for g in groups)
        return one_line(run_duckdb(duckdb, setup + sql)[2])

    def doc_rows(key):
        """(lines by section, whether json_root was needed); (None, None) after a failure."""
        d = rows.get(key)
        if d and d["ok"]:
            return d["sections"], False
        d2 = rows.get(key + "#json_root")
        if d2 and d2["ok"]:
            return d2["sections"], True
        return None, None

    shared_cols = [(s, [c for c, _ in cols]) for s, cols in SECTIONS]
    json_root_used = []
    for key, path, kind, extras in docs:
        secs, used_root = doc_rows(key)
        if secs is None:
            errors.append((key, message([key, key + "#json_root"])))
            put(out, key + ".rows.tsv", ERROR_TEXT)
        else:
            if used_root:
                json_root_used.append((key, kind))
            put(out, key + ".rows.tsv", rows_tsv(secs, shared_cols))
        if extras:
            esecs, _ = doc_rows(key + "!extra")
            if esecs is None:
                errors.append((key + " (extra sections)", message([key + "!extra", key + "!extra#json_root"])))
                put(out, "extra/" + key + ".tsv", ERROR_TEXT)
            else:
                put(out, "extra/" + key + ".tsv",
                    rows_tsv(esecs, [(s, layout.extra(s)[0] or ["row"]) for s in EXTRA]))
            # the bench files of group ids and timeline (compare3.py): every XML
            # input, and the group-id JSON sample for group_ids
            top = key.split("/", 1)[0]
            for s in BENCH_SECTIONS:
                if top in ("fixture", "read_samples", "write_samples") or (
                        s == "group_ids" and key in (GROUP_ID_JSON, GROUP_ID_XML[0])):
                    text = ERROR_TEXT if esecs is None else rows_tsv(esecs, [(s, layout.extra(s)[0] or ["row"])])
                    put(out, "%s.%s.tsv" % (key, s), text)

    for pair, _, _ in CHANGES_PAIRS:
        key = "changes/" + pair
        d = rows.get(key)
        if d is None or not d["ok"]:
            errors.append((key, message([key])))
            put(out, key + ".changes.tsv", ERROR_TEXT)
        else:
            put(out, key + ".changes.tsv", rows_tsv(d["sections"], [("changes", CHANGES_COLS)]))

    for key in writes:
        texts = {}
        msgs = []
        n_items = items.get(key)
        for fmt in ("xml", "json"):
            got = written.get((key, fmt), [])
            if n_items and len(got) == 1 and got[0] is not None:
                texts[fmt] = got[0]
                continue
            if n_items is None:
                why = message([key + "#setup"])
            elif n_items == 0:
                why = "the readers found no item to write"
            elif not got:
                why = message([key + "#setup", key + "#" + fmt])
            elif len(got) > 1:
                why = "%d items read where the writer takes one" % len(got)
            else:
                why = "the writer returned NULL"
            msgs.append("%s: %s" % (fmt, why))
            texts[fmt] = ERROR_TEXT
        put(out, key + ".xml", texts["xml"])
        put(out, key + ".json", texts["json"])
        if msgs:
            put(out, key + ".messages.txt", "".join(m + "\n" for m in msgs))
            if n_items is None:
                errors.append((key + " (writer input)", msgs[0]))

    if have_dump:
        members = [r for r in read_csv(files["dump"]) if len(r) == 3]
        d = rows.get("dump")
        if d is None or not d["ok"] or not os.path.exists(files["dump"]):
            errors.append(("dump", message(["dump#documents", "dump"])))
            put(out, "dump/members.tsv", ERROR_TEXT)
        else:
            by_hash = {}
            for section, line, h, orcid in d["rows"]:
                m = by_hash.setdefault(h, {"sections": {}, "orcid": {}})
                m["sections"].setdefault(section, []).append(line)
                if orcid and section not in m["orcid"]:
                    m["orcid"][section] = orcid
            lines = []
            for member, name, h in members:
                m = by_hash.get(h, {"sections": {}, "orcid": {}})
                total = sum(len(v) for v in m["sections"].values())
                orcid = next((m["orcid"][s] for s in SHARED if s in m["orcid"]), "-")
                lines.append("%s\t%s\t%s\t%d\n" % (xml_stem(name), h, orcid, total))
                rel = member_path(member or name)
                if rel:
                    put(out, "dumprows/" + rel + ".rows.tsv", rows_tsv(m["sections"], shared_cols))
            put(out, "dump/members.tsv", "".join(lines))

    # ------------------------------------------------------------ the reports
    lines = ["section\tcolumn\tstatus\tyorc_type\tduckdb_type\n"]
    for s, cols in SECTIONS:
        have = dict(columns.get(s, []))
        for c, t in cols:
            lines.append("%s\t%s\t%s\t%s\t%s\n" % (s, c, "shared" if c in have else "missing in duckdb",
                                                     TYPES[t], have.get(c, "-")))
        names = {c for c, _ in cols}
        for c, t in columns.get(s, []):
            if c not in names:
                lines.append("%s\t%s\tduckdb only\t-\t%s\n" % (s, c, t))
    for s in EXTRA:
        for c, t in columns.get(s, []):
            lines.append("%s\t%s\tduckdb only (section)\t-\t%s\n" % (s, c, t))
    put(out, "columns.tsv", "".join(lines))
    put(out, "json_root.tsv", "".join("%s\t%s\n" % kv for kv in json_root_used))
    put(out, "errors.tsv", "".join("%s\t%s\n" % (k, m.replace("\t", " ")) for k, m in errors))
    v = read_csv(files["version"])
    put(out, "version.txt", ("duckdb %s, orcid %s\n" % tuple(v[0][:2])) if v and len(v[0]) >= 2 else "unknown\n")
    print("duckdb: wrote %s (%d documents read, %d written, %d failed statements)"
          % (out, len(docs), len(writes), len(errors)), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
