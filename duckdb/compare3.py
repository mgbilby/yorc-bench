#!/usr/bin/env python3
"""Three-way cross-check of yorc-rs, yorc-zig and yorc-duckdb (README.md).

    python3 -I duckdb/compare3.py stage  ROOT WORK [--dump PATH]
    python3 -I duckdb/compare3.py report ROOT WORK [--impls rust,zig,duckdb]
                                                    [--diff N] [--diff-lines L] [--known-gaps]

compare.sh runs these in order; they are not meant to be run by hand, but
can be, on a tree kept with compare.sh --keep.

stage    copies what the three implementations wrote into WORK/reread-in for
         `orcid-libs-bench --reread` (yorc-rs reads all of it), with a
         `<file>.kind` next to each JSON file, and extracts the dump's .xml
         members there.
report   compares WORK/{rust,zig,duckdb} and WORK/reread-out, prints one line
         per artefact class and, with --diff N, N examples per class.

Classes (an entry is one file per implementation; `-` = no such capability):

  rows                  <dir>/<stem>.rows.tsv and dump/members.tsv, byte for byte
  dump member rows      the rows of each dump member (Rust: --reread of the extracted member)
  json-read rows        rows of a JSON document: ORCID's JSON samples, and the JSON the
                        Rust and the Zig program wrote. Rust: json::from_str(kind);
                        Zig: its JSON read written as XML (json_samples/*.xml,
                        *.json.xml), re-read by yorc-rs; DuckDB: orcid_<s>(file).
                        source_hash is blanked (the documents differ).
  written XML bytes     write_samples/<stem>.xml, byte for byte: yorc-duckdb writes in
                        crosswalk mode (SET orcid_crosswalk = true, emit.py), whose bytes are
                        yorc-rs's document writers', as yorc-zig's are
  written JSON bytes    write_samples/<stem>.json, byte for byte (the same)
  written XML semantic  each write_samples/<stem>.xml re-read by yorc-rs, rows compared
  written JSON semantic each write_samples/<stem>.json re-read by yorc-rs (kind of the sample)
  group_ids rows        <dir>/<stem>.group_ids.tsv for every XML input (fixture, read and write
                        samples), json_samples/write_samples/peer-review-group-id.group_ids.tsv and
                        group_id/group-id-3.0.group_ids.tsv (ORCID's group-id JSON and XML
                        samples): orcid_group_ids's 12 columns, byte for byte
  timeline rows         <dir>/<stem>.timeline.tsv for every XML input: orcid_timeline's 13 columns
  changes rows          changes/<pair>.changes.tsv for each snapshot pair in CHANGES_PAIRS:
                        orcid_changes's 9 columns
                        (the three formats: CROSSCHECK.md, "Bench files for group ids,
                        timeline and changes"). Until the Rust and Zig programs write them, these
                        classes report missing R / missing Z without failing (PENDING_OK)
  rust/zig only         every other file of the Rust and Zig trees (the two-way contract)

Buckets: all same; known Z gap; R=Z!=D; R=D!=Z; Z=D!=R; all differ (two
implementations: "differ"); missing R / Z / D (an implementation that has the
capability wrote no file; such an entry is counted in no other bucket).

Known Zig gaps. When yorc-rs and yorc-duckdb add sections or columns that
yorc-zig does not have yet, list them in ZIG_PENDING_SECTIONS /
ZIG_PENDING_COLUMNS and KNOWN_ZIG_GAPS below. An entry whose Zig file
equals the Rust file seen through yorc-zig's layout (those sections and
columns removed; for dump/members.tsv, the rows of those sections not
counted) is then counted as "known Z gap", which does not fail the check;
the other two must still agree, and a Zig difference outside the gap is
still a difference. The report prints a note about them; --known-gaps lists
the gaps and every entry counted so. Remove an item once yorc-zig has it.
There are none now: yorc-zig caught up with the 2026-10-18 layout
(search_results, errors, research_resource_hosts and the 21 appended
columns; CROSSCHECK.md, "Pending: Zig", closed).

With java in --impls (compare.sh --only ...,java), a second table takes
ORCID's Java orcid-model (java, WORK/java) as the reference for
reading. stage copies what Java wrote into WORK/reread-in/java/, so that
yorc-rs re-reads it; each class then compares every other
implementation's own result with what Java produced:

  J rows via XML        the record and samples: Java reads and writes XML, yorc-rs re-reads
                        it; against each implementation's direct rows
  J rows via JSON       Java's JSON of the same documents, re-read by yorc-rs (kind of the
                        source root); against Rust's JSON re-read (jsonread/rust), Zig's JSON
                        through its XML (zigproxy/zig) and DuckDB's read of Rust's JSON. Both
                        sides then carry the JSON timestamp form (epoch ms, UTC, .mmmZ)
  J rows via JSON->XML  Java's JSON read back by Java and written as XML; as above
  J json-read rows      ORCID's JSON samples read by Java, written as XML; against the
                        json-read rows of the three-way table
  J dump member rows    each dump member re-serialised by Java; against Rust's and DuckDB's
  J members             dump/members.tsv, first three columns (stem, SHA-256, iD)
  J sha256              <stem>.sha256 (java.security.MessageDigest; not a library feature)
  J accepts written documents
                        each write sample as each implementation wrote it (XML and JSON), read
                        by ORCID's classes and checked with ORCID's XSD (java --reread):
                        `read: ok, xsd: ok|rejected|none` or `read: error`; Java's own
                        document is the reference
  J reads written JSON  the same for every JSON document the Rust and Zig programs wrote, and
                        the JSON DuckDB wrote (crosswalk mode; the write samples only: DuckDB has
                        no record writer, so its other entries are n/a, not missing)
  J written XML bytes   (info) the write samples as Java's JAXB writes them (tabs, Jackson's
                        `"key" : value`: a format of its own, not the crosswalk contract)
  J written JSON bytes  (info) the same, Jackson

source_hash is blanked in every rows class. Buckets of the Java table, per
entry: same (every compared implementation equals Java); X!=J for each one
that differs (an entry may count in several); missing J / missing X.

Exit status (report): 0 when every entry of a compared class is the same or
a known Zig gap, 1 otherwise (the informational classes never fail: Java's
JAXB and Jackson bytes), 2 on a usage error.
"""

import difflib
import os
import re
import shutil
import sys
import tarfile

SAMPLES = "yorc-rs/reference/orcid-model/record_3.0/samples"
FIXTURE = "yorc-rs/tests/data/0000-0003-0100-6634.xml"
ERROR = b"error\n"
DIRS = ("fixture", "read_samples", "write_samples")
IMPLS = ("rust", "zig", "duckdb")
JAVA = "java"  # the reference table; never part of IMPLS (the three-way buckets)

COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
ROOT_RE = re.compile(r"<(?![?!/])(?:[A-Za-z_][\w.-]*:)?([A-Za-z_][\w.-]*)")

# What yorc-zig does not produce yet: sections, columns per section, and one
# line per gap for the report. Empty since yorc-zig caught up with the
# 2026-10-18 layout (CROSSCHECK.md, "Pending: Zig", closed).
ZIG_PENDING_SECTIONS = ()
ZIG_PENDING_COLUMNS = {}
KNOWN_ZIG_GAPS = ()

# The classes of the bench files the Rust and Zig programs are adding
# (2026-10-18): an implementation that wrote none of a class's files is
# reported as missing without failing the check; once it writes one, every
# entry counts. Remove a class from here when both programs have it.
PENDING_OK = ("group_ids rows", "timeline rows", "changes rows")

# Snapshot pairs of the changes class: (name, old, new), paths below ROOT.
# test/data/changes/new.xml is old.xml (ORCID's record-3.0 read sample) with a
# given name, a work title and an employment role title revised, a keyword
# added and the funding removed (yorc-duckdb audit/PROVENANCE.md).
CHANGES_PAIRS = (
    ("old_new", "yorc-duckdb/test/data/changes/old.xml", "yorc-duckdb/test/data/changes/new.xml"),
)
GROUP_ID_JSON = "json_samples/write_samples/peer-review-group-id"
GROUP_ID_XML = "group_id/group-id-3.0"  # ORCID's group-id-3.0/samples/group-id-3.0.xml

# A value of an implementation that does not have the capability for one
# entry of a class it otherwise has (counted in no bucket).
NA = b"\0n/a\0"

JSON_SAMPLE_KINDS = (
    ("record-full", "record"), ("address", "address"), ("bulk-", "bulk"), ("distinction", "distinction"),
    ("education", "education"), ("employment", "employment"), ("external-identifier", "external-identifier"),
    ("funding", "funding"), ("invited-position", "invited-position"), ("keywords", "keyword"),
    ("membership", "membership"), ("other-names", "other-name"), ("peer-review-group-id", ""),
    ("peer-review", "peer-review"), ("qualification", "qualification"), ("research-resource", "research-resource"),
    ("researcher-url", "researcher-url"), ("service", "service"), ("work", "work"),
)


def json_sample_kind(name):
    for prefix, kind in JSON_SAMPLE_KINDS:
        if name.startswith(prefix):
            return kind or None
    return None


def root_name(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = COMMENT_RE.sub("", f.read(1 << 16))
    except OSError:
        return None
    m = ROOT_RE.search(text)
    return m.group(1) if m else None


def listing(d, ext):
    try:
        return sorted(n for n in os.listdir(d) if n.endswith(ext) and os.path.isfile(os.path.join(d, n)))
    except OSError:
        return []


def get(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def put(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


# ------------------------------------------------------------------- stage

def member_path(member):
    parts = [p for p in member.replace("\\", "/").split("/") if p not in ("", ".")]
    return "" if ".." in parts else "/".join(parts)


def _copy(src, dst, kind=None):
    data = get(src)
    if data is None:
        return False
    put(dst, data)
    if kind:
        put(dst + ".kind", (kind + "\n").encode())
    return True


def source_xml(root, d, stem):
    return os.path.join(root, FIXTURE) if d == "fixture" else os.path.join(root, SAMPLES, d, stem + ".xml")


def cmd_stage(root, work, dump):
    rin = os.path.join(work, "reread-in")
    if os.path.exists(rin):
        shutil.rmtree(rin)
    os.makedirs(rin)
    have = {i: os.path.isdir(os.path.join(work, i)) for i in IMPLS}
    n = 0
    # ORCID's JSON samples: Rust reads them directly; Zig through its XML.
    for d in ("read_samples", "write_samples"):
        for name in listing(os.path.join(root, SAMPLES, d), ".json"):
            kind = json_sample_kind(name)
            if not kind:
                continue
            stem = name[:-5]
            n += _copy(os.path.join(root, SAMPLES, d, name), os.path.join(rin, "jsonread/orcid", d, name), kind)
            if have["zig"]:
                n += _copy(os.path.join(work, "zig/json_samples", d, stem + ".xml"),
                           os.path.join(rin, "jsonread/zigproxy/orcid", d, stem + ".xml"))
    # The JSON the Rust and Zig programs wrote.
    for origin in ("rust", "zig"):
        if not have[origin]:
            continue
        for d in DIRS:
            for name in listing(os.path.join(work, origin, d), ".json"):
                stem = name[:-5]
                kind = root_name(source_xml(root, d, stem))
                n += _copy(os.path.join(work, origin, d, name), os.path.join(rin, "jsonread", origin, d, name), kind)
                if not have["zig"]:
                    continue
                same = origin == "zig" or get(os.path.join(work, "rust", d, name)) == get(
                    os.path.join(work, "zig", d, name))
                if same:
                    n += _copy(os.path.join(work, "zig", d, stem + ".json.xml"),
                               os.path.join(rin, "jsonread/zigproxy", origin, d, stem + ".xml"))
    # What each wrote for the write samples.
    for impl in IMPLS:
        if not have[impl]:
            continue
        for name in listing(os.path.join(root, SAMPLES, "write_samples"), ".xml"):
            stem = name[:-4]
            kind = root_name(os.path.join(root, SAMPLES, "write_samples", name))
            base = os.path.join(work, impl, "write_samples", stem)
            dst = os.path.join(rin, "semantic", impl, "write_samples", stem)
            n += _copy(base + ".xml", dst + ".xml")
            n += _copy(base + ".json", dst + ".json", kind)
    # What Java (ORCID's orcid-model) wrote.
    if os.path.isdir(os.path.join(work, JAVA)):
        n += stage_java(root, work, rin)
    # The dump's .xml members, as the Rust dump reader picks them.
    if dump and os.path.isfile(dump) and (have["duckdb"] or os.path.isdir(os.path.join(work, JAVA))):
        with tarfile.open(dump, "r:*") as tf:
            for m in tf:
                if not m.isfile():
                    continue
                rel = member_path(m.name)
                base = rel.rsplit("/", 1)[-1]
                if not rel or len(base) <= 4 or base[-4:].lower() != ".xml":
                    continue
                f = tf.extractfile(m)
                if f is not None:
                    put(os.path.join(rin, "dumprows", rel), f.read())
                    n += 1
    print("stage: %d files in %s" % (n, rin), file=sys.stderr)
    return 0


def stage_java(root, work, rin):
    """Java's tree into reread-in/java/: xml/, json/ (with .kind), jsonxml/, jsonsamples/, dump/."""
    jt = os.path.join(work, JAVA)
    dst = os.path.join(rin, JAVA)
    n = 0
    for d in DIRS:
        for name in listing(os.path.join(jt, d), ".xml"):
            if name.endswith(".json.xml"):
                stem = name[:-len(".json.xml")]
                n += _copy(os.path.join(jt, d, name), os.path.join(dst, "jsonxml", d, stem + ".xml"))
            else:
                n += _copy(os.path.join(jt, d, name), os.path.join(dst, "xml", d, name))
        for name in listing(os.path.join(jt, d), ".json"):
            stem = name[:-5]
            kind = root_name(source_xml(root, d, stem))
            n += _copy(os.path.join(jt, d, name), os.path.join(dst, "json", d, name), kind)
    for d in ("read_samples", "write_samples"):
        for name in listing(os.path.join(jt, "json_samples", d), ".xml"):
            n += _copy(os.path.join(jt, "json_samples", d, name), os.path.join(dst, "jsonsamples", d, name))
    for rel in rel_files(os.path.join(jt, "dumpxml")):
        n += _copy(os.path.join(jt, "dumpxml", rel), os.path.join(dst, "dump", rel))
    return n


# ------------------------------------------------------------------ report

def blank_hash(data):
    """The rows TSV with every source_hash value replaced by <hash>."""
    if data is None or data == ERROR:
        return data
    out = []
    remaining = 0
    header = False
    idx = None
    for line in data.decode("utf-8", "replace").split("\n"):
        if header:
            cols = line.split("\t")
            idx = cols.index("source_hash") if "source_hash" in cols else None
            header = False
        elif remaining > 0:
            if idx is not None:
                f = line.split("\t")
                if idx < len(f):
                    f[idx] = "<hash>"
                line = "\t".join(f)
            remaining -= 1
        elif line.startswith("# "):
            parts = line[2:].split("\t")
            remaining = int(parts[1]) if len(parts) == 2 and parts[1].isdigit() else 0
            header = remaining > 0
        out.append(line)
    return "\n".join(out).encode("utf-8")


def zig_rows_view(data):
    """A rows TSV (Rust's or DuckDB's) as yorc-zig writes it today: without
    ZIG_PENDING_SECTIONS and without the ZIG_PENDING_COLUMNS of each section."""
    if data is None or data == ERROR:
        return data
    lines = data.decode("utf-8", "replace").split("\n")
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        parts = line[2:].split("\t") if line.startswith("# ") else []
        if len(parts) != 2 or not parts[1].isdigit():
            out.append(line)
            i += 1
            continue
        name, n = parts[0], int(parts[1])
        header = lines[i + 1].split("\t") if n > 0 and i + 1 < len(lines) else []
        rows = lines[i + 2:i + 2 + n] if n > 0 else []
        i += 1 + (n + 1 if n > 0 else 0)
        if name in ZIG_PENDING_SECTIONS:
            continue
        out.append(line)
        if n > 0:
            drop = ZIG_PENDING_COLUMNS.get(name, ())
            keep = [j for j, c in enumerate(header) if c not in drop]
            out.append("\t".join(header[j] for j in keep))
            for row in rows:
                f = row.split("\t")
                out.append("\t".join(f[j] for j in keep if j < len(f)))
    return "\n".join(out).encode("utf-8")


def pending_rows(data):
    """Rows of ZIG_PENDING_SECTIONS in a rows TSV."""
    n = 0
    for line in (data or b"").decode("utf-8", "replace").split("\n"):
        parts = line[2:].split("\t") if line.startswith("# ") else []
        if len(parts) == 2 and parts[0] in ZIG_PENDING_SECTIONS and parts[1].isdigit():
            n += int(parts[1])
    return n


def zig_members_view(rows_dir):
    """dump/members.tsv as yorc-zig writes it today: each member's row count
    without its rows in ZIG_PENDING_SECTIONS, counted in yorc-rs's re-read
    of the extracted members (reread-out/dumprows). None without them."""
    pending = {}
    for rel in rel_files(rows_dir):
        if rel.endswith(".rows.tsv"):
            base = rel.rsplit("/", 1)[-1][:-len(".rows.tsv")]
            stem = base[:-4] if base[-4:].lower() == ".xml" else base
            pending[stem] = pending.get(stem, 0) + pending_rows(get(os.path.join(rows_dir, rel)))
    if not pending:
        return None

    def view(data):
        if data is None or data == ERROR:
            return data
        out = []
        for line in data.decode("utf-8", "replace").split("\n"):
            f = line.split("\t")
            if len(f) == 4 and f[3].isdigit() and f[0] in pending:
                f[3] = str(int(f[3]) - pending[f[0]])
            out.append("\t".join(f))
        return "\n".join(out).encode("utf-8")
    return view


class Klass:
    def __init__(self, name, impls, informational=False):
        self.name = name
        self.impls = impls  # the implementations with this capability
        self.informational = informational
        self.entries = []  # (key, {impl: bytes or None}, {impl: detail bytes})
        self.zig_views = {}  # key -> what yorc-zig is expected to write, from the Rust (or Java) value

    def add(self, key, values, details=None, zig_view=None):
        if all(v is None or v is NA for v in values.values()):
            return  # nobody wrote it: not an entry
        self.entries.append((key, values, details or {}))
        if zig_view is not None:
            self.zig_views[key] = zig_view

    def zig_gap(self, key, v, ref="rust"):
        """True when Zig differs from `ref` only by a known Zig gap."""
        view = self.zig_views.get(key)
        z, r = v.get("zig"), v.get(ref)
        return view is not None and z is not None and r is not None and z != r and view(r) == z


def bucket(impls, v):
    missing = [i for i in impls if v.get(i) is None]
    if missing:
        return "missing " + ",".join(missing)
    if len(impls) == 1:
        return "same"
    if len(impls) == 2:
        return "same" if v[impls[0]] == v[impls[1]] else "all differ"
    r, z, d = v["rust"], v["zig"], v["duckdb"]
    if r == z == d:
        return "same"
    if r == z:
        return "R=Z!=D"
    if r == d:
        return "R=D!=Z"
    if z == d:
        return "Z=D!=R"
    return "all differ"


def bucket_of(k, key, v):
    """bucket(), with a Zig value that differs only by a known gap taken as Rust's."""
    if "zig" in k.impls and k.zig_gap(key, v):
        b = bucket(k.impls, dict(v, zig=v["rust"]))
        return "known Z gap" if b == "same" else b
    return bucket(k.impls, v)


def rel_files(top):
    out = []
    for dirpath, _, names in os.walk(top):
        for n in names:
            out.append(os.path.relpath(os.path.join(dirpath, n), top).replace(os.sep, "/"))
    return sorted(out)


def build(root, work, impls):
    W = lambda *p: os.path.join(work, *p)
    R = lambda *p: os.path.join(work, "reread-out", *p)
    on = lambda i: i in impls and os.path.isdir(W(i))
    pick = lambda cap: tuple(i for i in cap if i in impls)
    classes = []
    claimed = set()  # rust/zig tree files a class above already compares

    def tree_val(impl, rel):
        if not on(impl):
            return None
        return get(W(impl, rel))

    # rows
    k = Klass("rows", pick(IMPLS))
    members_view = zig_members_view(R("dumprows"))
    for d in DIRS:
        stems = set()
        for i in k.impls:
            stems |= {n[:-9] for n in listing(W(i, d), ".rows.tsv")}
        for stem in sorted(stems):
            vals = {}
            for i in k.impls:
                v = tree_val(i, "%s/%s.rows.tsv" % (d, stem))
                if v is None and i != "duckdb" and tree_val(i, "%s/%s.xml" % (d, stem)) == ERROR:
                    v = ERROR  # the Rust and Zig programs write no rows when the read fails
                vals[i] = v
            k.add("%s/%s" % (d, stem), vals, zig_view=zig_rows_view)
            claimed.add("%s/%s.rows.tsv" % (d, stem))
    k.add("dump/members.tsv", {i: tree_val(i, "dump/members.tsv") for i in k.impls}, zig_view=members_view)
    claimed.add("dump/members.tsv")
    classes.append(k)

    # dump member rows
    k = Klass("dump member rows", pick(("rust", "duckdb")))
    keys = set(rel_files(W("duckdb", "dumprows"))) if on("duckdb") else set()
    keys |= set(rel_files(R("dumprows")))
    for rel in sorted(keys):
        k.add(rel[:-9], {"rust": get(R("dumprows", rel)), "duckdb": tree_val("duckdb", "dumprows/" + rel)})
    classes.append(k)

    # json-read rows
    k = Klass("json-read rows", pick(IMPLS))
    for d in ("read_samples", "write_samples"):
        for name in listing(R("jsonread/orcid", d), ".json.rows.tsv"):
            stem = name[:-len(".json.rows.tsv")]
            k.add("orcid/%s/%s" % (d, stem), {
                "rust": blank_hash(get(R("jsonread/orcid", d, name))),
                "zig": blank_hash(get(R("jsonread/zigproxy/orcid", d, stem + ".xml.rows.tsv"))) if on("zig") else None,
                "duckdb": blank_hash(tree_val("duckdb", "json_samples/%s/%s.rows.tsv" % (d, stem))),
            })
    for origin in ("rust", "zig"):
        for d in DIRS:
            for name in listing(R("jsonread", origin, d), ".json.rows.tsv"):
                stem = name[:-len(".json.rows.tsv")]
                k.add("%s/%s/%s" % (origin, d, stem), {
                    "rust": blank_hash(get(R("jsonread", origin, d, name))),
                    "zig": blank_hash(get(R("jsonread/zigproxy", origin, d, stem + ".xml.rows.tsv"))) if on("zig") else None,
                    "duckdb": blank_hash(tree_val("duckdb", "json_read/%s/%s/%s.rows.tsv" % (origin, d, stem))),
                })
    classes.append(k)

    # written documents
    stems = [n[:-4] for n in listing(os.path.join(root, SAMPLES, "write_samples"), ".xml")]
    for fmt in ("xml", "json"):
        # DuckDB writes in crosswalk mode: yorc-rs's bytes (CROSSCHECK #5)
        k = Klass("written %s bytes" % fmt.upper(), pick(IMPLS))
        for stem in stems:
            rel = "write_samples/%s.%s" % (stem, fmt)
            k.add(rel, {i: tree_val(i, rel) for i in k.impls})
            claimed.add(rel)
        classes.append(k)
    for fmt in ("xml", "json"):
        k = Klass("written %s semantic" % fmt.upper(), pick(IMPLS))
        for stem in stems:
            k.add("write_samples/%s.%s" % (stem, fmt), {
                i: blank_hash(get(R("semantic", i, "write_samples", "%s.%s.rows.tsv" % (stem, fmt))))
                if on(i) else None for i in k.impls})
        classes.append(k)

    # group ids, timeline, changes: one TSV per input, byte for byte (no re-read)
    xml_inputs = [("fixture", os.path.basename(FIXTURE)[:-4])]
    for d in ("read_samples", "write_samples"):
        xml_inputs += [(d, n[:-4]) for n in listing(os.path.join(root, SAMPLES, d), ".xml")]

    def bench_file(i, key, suffix):
        v = tree_val(i, key + suffix)
        if v is None and i != "duckdb" and tree_val(i, key + ".xml") == ERROR:
            v = ERROR  # the Rust and Zig programs write nothing more when the read fails
        return v

    for name, suffix, extra_keys in (("group_ids rows", ".group_ids.tsv", [GROUP_ID_JSON, GROUP_ID_XML]),
                                     ("timeline rows", ".timeline.tsv", [])):
        k = Klass(name, pick(IMPLS))
        for key in ["%s/%s" % ds for ds in xml_inputs] + extra_keys:
            k.add(key, {i: bench_file(i, key, suffix) for i in k.impls})
            claimed.add(key + suffix)
        classes.append(k)
    k = Klass("changes rows", pick(IMPLS))
    for pair, _, _ in CHANGES_PAIRS:
        rel = "changes/%s.changes.tsv" % pair
        k.add(rel, {i: tree_val(i, rel) for i in k.impls})
        claimed.add(rel)
    classes.append(k)

    # rust/zig only: every other file of the two trees, byte for byte
    k = Klass("rust/zig only", pick(("rust", "zig")))
    files = set()
    for i in k.impls:
        if on(i):
            files |= set(rel_files(W(i)))
    for rel in sorted(files - claimed):
        k.add(rel, {i: tree_val(i, rel) for i in k.impls})
    classes.append(k)
    return classes


def first_columns(data, n):
    """The first n tab-separated columns of every line (members.tsv without the row count)."""
    if data is None:
        return None
    lines = data.decode("utf-8", "replace").splitlines()
    return "".join("\t".join(line.split("\t")[:n]) + "\n" for line in lines).encode("utf-8")


def build_java(root, work, impls):
    """The classes of the Java reference table (see the module docstring)."""
    W = lambda *p: os.path.join(work, *p)
    R = lambda *p: os.path.join(work, "reread-out", *p)
    on = lambda i: i in impls and os.path.isdir(W(i))
    others = lambda cap: tuple(i for i in cap if i in impls)
    classes = []

    def direct(i, d, stem):
        """An implementation's own rows of an input, source_hash blanked."""
        if not on(i):
            return None
        v = get(W(i, d, stem + ".rows.tsv"))
        if v is None and i != "duckdb" and get(W(i, d, stem + ".xml")) == ERROR:
            v = ERROR
        return blank_hash(v)

    inputs = []  # (dir, stem) of every XML input
    inputs.append(("fixture", os.path.basename(FIXTURE)[:-4]))
    for d in ("read_samples", "write_samples"):
        inputs += [(d, n[:-4]) for n in listing(os.path.join(root, SAMPLES, d), ".xml")]

    k = Klass("J rows via XML", others(IMPLS))
    for d, stem in inputs:
        vals = {i: direct(i, d, stem) for i in k.impls}
        vals[JAVA] = blank_hash(get(R(JAVA, "xml", d, stem + ".xml.rows.tsv")))
        k.add("%s/%s" % (d, stem), vals, zig_view=zig_rows_view)
    classes.append(k)

    # The JSON paths: compared with each implementation's own JSON path.
    def json_side(i, d, stem):
        if not on(i):
            return None
        if i == "rust":
            return blank_hash(get(R("jsonread", "rust", d, stem + ".json.rows.tsv")))
        if i == "zig":
            return blank_hash(get(R("jsonread/zigproxy", "zig", d, stem + ".xml.rows.tsv")))
        return blank_hash(get(W("duckdb", "json_read", "rust", d, stem + ".rows.tsv")))

    for name, sub, suffix in (("J rows via JSON", "json", ".json.rows.tsv"),
                              ("J rows via JSON->XML", "jsonxml", ".xml.rows.tsv")):
        k = Klass(name, others(IMPLS))
        for d, stem in inputs:
            j = get(R(JAVA, sub, d, stem + suffix))
            if j is None:
                continue  # Java wrote no such document (it did not read the input)
            vals = {i: json_side(i, d, stem) for i in k.impls}
            vals[JAVA] = blank_hash(j)
            k.add("%s/%s" % (d, stem), vals)
        classes.append(k)

    k = Klass("J json-read rows", others(IMPLS))
    for d in ("read_samples", "write_samples"):
        for name in listing(R("jsonread/orcid", d), ".json.rows.tsv"):
            stem = name[:-len(".json.rows.tsv")]
            k.add("orcid/%s/%s" % (d, stem), {
                "rust": blank_hash(get(R("jsonread/orcid", d, name))) if on("rust") else None,
                "zig": blank_hash(get(R("jsonread/zigproxy/orcid", d, stem + ".xml.rows.tsv"))) if on("zig") else None,
                "duckdb": blank_hash(get(W("duckdb", "json_samples", d, stem + ".rows.tsv"))) if on("duckdb") else None,
                JAVA: blank_hash(get(R(JAVA, "jsonsamples", d, stem + ".xml.rows.tsv"))),
            })
    classes.append(k)

    k = Klass("J dump member rows", others(("rust", "duckdb")))
    keys = set(rel_files(R(JAVA, "dump"))) | set(rel_files(R("dumprows")))
    for rel in sorted(keys):
        vals = {"rust": blank_hash(get(R("dumprows", rel))) if on("rust") else None,
                "duckdb": blank_hash(get(W("duckdb", "dumprows", rel))) if on("duckdb") else None,
                JAVA: blank_hash(get(R(JAVA, "dump", rel)))}
        k.add(rel[:-len(".rows.tsv")], {i: vals[i] for i in k.impls + (JAVA,)})
    classes.append(k)

    k = Klass("J members (stem, sha256, iD)", others(IMPLS))
    vals = {i: first_columns(get(W(i, "dump", "members.tsv")), 3) if on(i) else None for i in k.impls}
    vals[JAVA] = first_columns(get(W(JAVA, "dump", "members.tsv")), 3)
    k.add("dump/members.tsv", vals)
    classes.append(k)

    k = Klass("J sha256", others(("rust", "zig")))
    for d, stem in inputs:
        rel = "%s/%s.sha256" % (d, stem)
        vals = {i: get(W(i, rel)) if on(i) else None for i in k.impls}
        vals[JAVA] = get(W(JAVA, rel))
        k.add(rel, vals)
    classes.append(k)

    stems = [n[:-4] for n in listing(os.path.join(root, SAMPLES, "write_samples"), ".xml")]

    # Would ORCID's classes read each written document, and pass ORCID's XSD
    # check? (java --reread over reread-in: WORK/java-reread/<path>.accept.txt)
    A = lambda *p: os.path.join(work, "java-reread", *p)

    def accept(path):
        data = get(path)
        if data is None:
            return None, None
        line = data.decode("utf-8", "replace").strip()
        short = re.sub(r"^(read: ok, xsd: rejected|read: error).*$", r"\1", line)
        return (short + "\n").encode(), data

    k = Klass("J accepts written documents", others(IMPLS))
    for stem in stems:
        for fmt, sub in (("xml", "xml"), ("json", "json")):
            vals, det = {}, {}
            for i in k.impls:
                vals[i], det[i] = accept(A("semantic", i, "write_samples", "%s.%s.accept.txt" % (stem, fmt))) \
                    if on(i) else (None, None)
            vals[JAVA], det[JAVA] = accept(A(JAVA, sub, "write_samples", "%s.%s.accept.txt" % (stem, fmt)))
            k.add("write_samples/%s.%s" % (stem, fmt), vals, det)
    classes.append(k)

    k = Klass("J reads written JSON", others(IMPLS))
    for d, stem in inputs:
        vals, det = {}, {}
        for i in k.impls:
            if i == "duckdb":
                # DuckDB writes JSON for the write samples only (no record writer);
                # compare.sh stages it in semantic/duckdb for java --reread
                if d != "write_samples":
                    vals[i], det[i] = NA, None
                elif on(i):
                    vals[i], det[i] = accept(A("semantic", i, d, stem + ".json.accept.txt"))
                else:
                    vals[i], det[i] = None, None
                continue
            vals[i], det[i] = accept(A("jsonread", i, d, stem + ".json.accept.txt")) if on(i) else (None, None)
        vals[JAVA], det[JAVA] = accept(A(JAVA, "json", d, stem + ".json.accept.txt"))
        k.add("%s/%s.json" % (d, stem), vals, det)
    classes.append(k)

    for fmt in ("xml", "json"):
        k = Klass("J written %s bytes" % fmt.upper(), others(IMPLS), informational=True)
        for stem in stems:
            rel = "write_samples/%s.%s" % (stem, fmt)
            vals = {i: get(W(i, rel)) if on(i) else None for i in k.impls}
            vals[JAVA] = get(W(JAVA, rel))
            k.add(rel, vals)
        classes.append(k)

    return classes


JCOLS = ("same", "R!=J", "Z!=J", "D!=J", "known Z gap", "missing J", "missing R", "missing Z", "missing D")
PASSING = ("same", "known Z gap")


def java_buckets(k, key, v):
    """The Java-table buckets of one entry: a list (an entry may differ from several)."""
    if v.get(JAVA) is None:
        return ["missing J"]
    out = []
    for i in k.impls:
        if v.get(i) is NA:
            continue
        if v.get(i) is None:
            out.append("missing " + SHORT[i])
        elif v[i] != v[JAVA]:
            out.append("known Z gap" if i == "zig" and k.zig_gap(key, v, ref=JAVA) else SHORT[i] + "!=J")
    if out == ["known Z gap"]:
        return out
    return [b for b in out if b != "known Z gap"] or ["same"]


def report_java(classes, work, ndiff, nlines):
    """Print the Java table (and examples); True if a compared class has a difference."""
    head = ("class", "impls", "entries") + JCOLS
    table = []
    failed = False
    for k in classes:
        t = dict.fromkeys(JCOLS, 0)
        passing = 0
        for key, v, _ in k.entries:
            bs = java_buckets(k, key, v)
            for b in bs:
                t[b] += 1
            passing += all(b in PASSING for b in bs)
        cells = [k.name + (" (info)" if k.informational else ""), "".join(SHORT[i] for i in k.impls) + "+J",
                 str(len(k.entries))]
        for c in JCOLS:
            if c == "known Z gap":
                letter = "Z"
            else:
                letter = c[0] if c.endswith("!=J") else c[-1]
            absent = c != "same" and letter != "J" and letter not in [SHORT[i] for i in k.impls]
            cells.append("-" if absent else str(t[c]))
        table.append(cells)
        if not k.informational and len(k.entries) != passing:
            failed = True
    width = [max(len(r[j]) for r in [list(head)] + table) for j in range(len(head))]
    print("\nJava (ORCID orcid-model) as the reference for reading:")
    for n, r in enumerate([list(head)] + table):
        print("  " + "  ".join(x.ljust(width[j]) if j < 2 else x.rjust(width[j]) for j, x in enumerate(r)))
        if n == 0:
            print("  " + "  ".join("-" * w for w in width))
    print("  X!=J: implementation X differs from what Java read (an entry can count for several X);")
    print("  known Z gap: Zig differs from Java only by what yorc-zig does not produce yet (does not fail).")
    report_java_examples(classes, ndiff, nlines)
    return failed


def report_java_examples(classes, ndiff, nlines):
    """With --diff N: N example entries per Java-table class, with a diff against Java."""
    if ndiff > 0:
        for k in classes:
            shown = 0
            ranked = sorted(k.entries, key=lambda e: java_buckets(k, e[0], e[1])[0].startswith("missing"))
            for key, v, det in ranked:
                b = java_buckets(k, key, v)
                if all(x in PASSING for x in b):
                    continue
                if shown == 0:
                    print("\n%s (vs Java):" % k.name)
                shown += 1
                if shown > ndiff:
                    print("  ... more")
                    break
                print("  [%s] %s" % (", ".join(b), key))
                src = det if det else v
                for i in k.impls:
                    if SHORT[i] + "!=J" in b:
                        show_diff("java/" + key, src.get(JAVA), i + "/" + key, src.get(i), nlines)


COLS = ("same", "known Z gap", "R=Z!=D", "R=D!=Z", "Z=D!=R", "all differ", "missing R", "missing Z", "missing D")
SHORT = {"rust": "R", "zig": "Z", "duckdb": "D", JAVA: "J"}


def absent_impls(k):
    """For a PENDING_OK class: the implementations that wrote none of its files."""
    if k.name not in PENDING_OK:
        return set()
    return {i for i in k.impls if all(v.get(i) is None for _, v, _ in k.entries)}


def tolerated(k, key, v):
    """True when an entry only lacks the files of implementations that do not have the class yet."""
    absent = absent_impls(k)
    b = bucket_of(k, key, v)
    if not absent or not b.startswith("missing "):
        return False
    if not set(b[len("missing "):].split(",")) <= absent:
        return False
    present = [v[i] for i in k.impls if i not in absent]
    return all(x == present[0] for x in present)


def tally(k):
    t = dict.fromkeys(COLS, 0)
    for key, v, _ in k.entries:
        b = bucket_of(k, key, v)
        if b.startswith("missing "):
            for i in b[len("missing "):].split(","):
                t["missing " + SHORT[i]] += 1
        else:
            t[b] += 1
    return t


def show_diff(a_name, a, b_name, b, lines):
    a = (a or b"").decode("utf-8", "replace").splitlines(True)
    b = (b or b"").decode("utf-8", "replace").splitlines(True)
    d = list(difflib.unified_diff(a, b, a_name, b_name, n=1))
    for line in d[:lines]:
        print("      " + line.rstrip("\n"))
    if len(d) > lines:
        print("      ... (%d more diff lines)" % (len(d) - lines))


def cmd_report(root, work, impls, ndiff, nlines, known_gaps=False):
    classes = build(root, work, impls)
    head = ("class", "impls", "entries") + COLS
    table = []
    failed = False
    for k in classes:
        t = tally(k)
        cells = [k.name + (" (info)" if k.informational else ""), "".join(SHORT[i] for i in k.impls),
                 str(len(k.entries))]
        for c in COLS:
            pair = c in ("R=Z!=D", "R=D!=Z", "Z=D!=R")
            missing_impl = c.startswith("missing ") and c[-1] not in [SHORT[i] for i in k.impls]
            no_gap = c == "known Z gap" and "zig" not in k.impls
            cells.append("-" if (pair and len(k.impls) < 3) or missing_impl or no_gap else str(t[c]))
        table.append(cells)
        ok = sum(1 for key, v, _ in k.entries if bucket_of(k, key, v) in ("same", "known Z gap") or tolerated(k, key, v))
        if not k.informational and len(k.entries) != ok:
            failed = True
    width = [max(len(r[j]) for r in [list(head)] + table) for j in range(len(head))]
    print("cross-check (%s):" % ", ".join(impls))
    for n, r in enumerate([list(head)] + table):
        print("  " + "  ".join(x.ljust(width[j]) if j < 2 else x.rjust(width[j]) for j, x in enumerate(r)))
        if n == 0:
            print("  " + "  ".join("-" * w for w in width))
    if any(k.informational for k in classes):
        print("  (info) classes compare bytes of formats that differ by design; they never fail the check.")
    print("  written XML / JSON bytes: byte for byte, yorc-duckdb in crosswalk mode (yorc-rs's document bytes).")
    for k in classes:
        absent = absent_impls(k)
        if absent:
            print("  %s: no files from %s yet (to be built); its missing entries do not fail the check."
                  % (k.name, ", ".join(SHORT[i] for i in k.impls if i in absent)))
    gaps = sum(tally(k)["known Z gap"] for k in classes)
    if "zig" in impls and (KNOWN_ZIG_GAPS or gaps):
        print("  known Z gap: %d entries differ only by what yorc-zig does not produce yet (KNOWN_ZIG_GAPS "
              "in compare3.py); they do not fail the check%s."
              % (gaps, "" if known_gaps else "; --known-gaps lists them"))
    if known_gaps:
        print("\nKnown Zig gaps (expected to differ until yorc-zig catches up):")
        for g in KNOWN_ZIG_GAPS:
            print("  - " + g)
        for k in classes:
            keys = [key for key, v, _ in k.entries if bucket_of(k, key, v) == "known Z gap"]
            if keys:
                shown = ", ".join(keys[:8]) + (", ..." if len(keys) > 8 else "")
                print("  %s: %d entries: %s" % (k.name, len(keys), shown))

    d = os.path.join(work, "duckdb")
    if os.path.isdir(d):
        extra = rel_files(os.path.join(d, "extra"))
        nonempty = {}
        for rel in extra:
            for line in (get(os.path.join(d, "extra", rel)) or b"").decode("utf-8", "replace").splitlines():
                if line.startswith("# ") and not line.endswith("\t0"):
                    s = line[2:].split("\t")[0]
                    nonempty[s] = nonempty.get(s, 0) + 1
        cols = (get(os.path.join(d, "columns.tsv")) or b"").decode("utf-8", "replace").splitlines()[1:]
        status = {}
        for line in cols:
            f = line.split("\t")
            if len(f) >= 3:
                status[f[2]] = status.get(f[2], 0) + 1
        jr = len((get(os.path.join(d, "json_root.tsv")) or b"").splitlines())
        errs = len((get(os.path.join(d, "errors.tsv")) or b"").splitlines())
        print("duckdb only, not compared: %d extra-section files (%s); columns.tsv: %s; "
              "%d JSON documents read only with json_root (json_root.tsv); %d failed statements (errors.tsv); %s"
              % (len(extra), ", ".join("%s in %d" % kv for kv in sorted(nonempty.items())) or "no rows",
                 ", ".join("%d %s" % (v, s) for s, v in sorted(status.items())) or "missing",
                 jr, errs, (get(os.path.join(d, "version.txt")) or b"version unknown\n").decode().strip()))

    java_failed = False
    java_classes = []
    if JAVA in impls and os.path.isdir(os.path.join(work, JAVA)):
        java_classes = build_java(root, work, impls)
        java_failed = report_java(java_classes, work, 0, nlines)

    if ndiff > 0:
        for k in classes:
            shown = 0
            ranked = sorted(k.entries, key=lambda e: bucket_of(k, e[0], e[1]).startswith("missing"))
            for key, v, det in ranked:
                b = bucket_of(k, key, v)
                if b in ("same", "known Z gap"):
                    continue
                if shown == 0:
                    print("\n%s:" % k.name)
                shown += 1
                if shown > ndiff:
                    print("  ... more")
                    break
                print("  [%s] %s" % (b, key))
                if b.startswith("missing"):
                    continue
                src = det if det else v
                if b == "R=Z!=D":
                    pairs = [("rust", "duckdb")]
                elif b == "R=D!=Z":
                    pairs = [("rust", "zig")]
                elif b == "Z=D!=R":
                    pairs = [("zig", "rust")]
                elif len(k.impls) == 2:
                    pairs = [(k.impls[0], k.impls[1])]
                else:
                    pairs = [("rust", "zig"), ("rust", "duckdb")]
                for x, y in pairs:
                    show_diff(x + "/" + key, src.get(x), y + "/" + key, src.get(y), nlines)
        if java_classes:
            report_java_examples(java_classes, ndiff, nlines)
    return 1 if failed or java_failed else 0


def main(argv):
    if len(argv) < 4 or argv[1] not in ("stage", "report"):
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    cmd, root, work = argv[1], os.path.abspath(argv[2]), os.path.abspath(argv[3])
    opts = argv[4:]

    def opt(name, default):
        if name in opts:
            i = opts.index(name)
            if i + 1 < len(opts):
                return opts[i + 1]
        return default

    if cmd == "stage":
        dump = opt("--dump", None)
        return cmd_stage(root, work, os.path.abspath(dump) if dump else None)
    impls = tuple(i for i in opt("--impls", "rust,zig,duckdb").split(",") if i in IMPLS or i == JAVA)
    try:
        ndiff, nlines = int(opt("--diff", "0")), int(opt("--diff-lines", "30"))
    except ValueError:
        print("compare3.py: --diff and --diff-lines take numbers", file=sys.stderr)
        return 2
    return cmd_report(root, work, impls, ndiff, nlines, known_gaps="--known-gaps" in opts)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
