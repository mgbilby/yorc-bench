//! yorc-rs side of the yorc-rs / yorc-zig comparison (yorc-bench).
//!
//! ```text
//! orcid-libs-bench [--root DIR] [--iters N] [--dump-iters N] [--warmup N]
//!                  [--only W,W,...] [--dump PATH | PATH]
//! orcid-libs-bench --emit OUT_DIR [--root DIR] [--dump PATH | PATH]
//! orcid-libs-bench --reread DIR --emit OUT_DIR
//! ```
//!
//! Benchmark mode prints one JSON line per workload on stdout:
//! `{"impl","workload","iterations","bytes","total_ns","ns_per_op","mb_per_s"}`.
//! Emit mode writes the cross-check tree that `./compare.sh` diffs
//! against the Zig program's. Both programs implement the same workloads on
//! the same inputs; keep them in step (zig/src/main.zig).
//! Since 2026-10-18 emit mode also writes, for yorc-rs's opt-in sections
//! (`rows::Extra`, `rows::changes`; layout and format: CROSSCHECK.md,
//! "Bench files for group ids, timeline and changes"): `<stem>.group_ids.tsv`
//! and `<stem>.timeline.tsv` next to each XML input's `.rows.tsv`;
//! `json_samples/write_samples/peer-review-group-id.group_ids.tsv`;
//! `group_id/` (the group-id XML inputs: `.sha256`, `.xml`, `.json`,
//! `.json.xml`, `.group_ids.tsv`); `changes/<old>_<new>.changes.tsv`; and
//! `dump/sample.tsv` (the stems of a reservoir sample of the dump, n = 5,
//! seed 42).
//! Re-read mode (Rust only) reads every `.xml` and `.json` file below DIR
//! with yorc-rs and writes its rows: the three-way check uses it to read
//! what the other implementations wrote (./compare.sh).
//!
//! Single-threaded; timing is `std::time::Instant` around N iterations after
//! a warm-up, with no harness crate, so the two sides measure the same thing.

use std::fs;
use std::hint::black_box;
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::time::Instant;

use yorc::dump::{Reservoir, Slot};
use yorc::rows::{CHANGE_COLUMNS, Cell, Change, Column, Extra, Row, Section, Tables};
use yorc::{dump, hash, id, json, rows, xml};

const IMPL: &str = "rust";
const FIXTURE: &str = "yorc-rs/tests/data/0000-0003-0100-6634.xml";
const SAMPLES: &str = "yorc-rs/reference/orcid-model/record_3.0/samples";
const DUMP: &str = "yorc-zig/testdata/dump/orcid_test_summaries.tgz";
/// The group-id inputs (`group_id/`): ORCID's XML sample and a two-record
/// page (yorc-duckdb's orcid_api_messages.test).
const GROUP_ID_XML: [&str; 2] = [
    "yorc-rs/reference/orcid-model/group-id-3.0/samples/group-id-3.0.xml",
    "yorc-rs/tests/data/group-id-records.xml",
];
/// ORCID's group-id JSON write sample: the `group_ids_read` input, and
/// `json_samples/write_samples/<stem>.group_ids.tsv`.
const GROUP_ID_JSON: &str =
    "yorc-rs/reference/orcid-model/record_3.0/samples/write_samples/peer-review-group-id.json";
/// Two snapshots of ORCID's record sample (yorc-duckdb's orcid_changes tests).
const CHANGES_OLD: &str = "yorc-rs/tests/data/changes/old.xml";
const CHANGES_NEW: &str = "yorc-rs/tests/data/changes/new.xml";
/// `dump_sample` and `dump/sample.tsv`: reservoir size and seed.
const SAMPLE_N: usize = 5;
const SAMPLE_SEED: u64 = 42;
const N_IDS: usize = 10_000;
const ERROR_TEXT: &str = "error\n";

/// Workloads in output order, with their default iteration counts. The
/// first eight are the original set (keep them first and unchanged, so runs
/// stay comparable); the last four were appended on 2026-10-18.
const WORKLOADS: [(&str, u64); 12] = [
    ("id_normalize", 200),
    ("xml_read_record", 30),
    ("xml_write_record", 30),
    ("json_write_record", 30),
    ("json_read_record", 30),
    ("rows_record", 30),
    ("sha256", 300),
    ("dump_stream", 20),
    ("group_ids_read", 10_000),
    ("timeline_record", 30),
    ("changes_record", 30),
    ("dump_sample", 20),
];

const USAGE: &str = "usage: orcid-libs-bench [--root DIR] [--iters N] [--dump-iters N] [--warmup N] \
[--only W,W] [--dump PATH | PATH]\n       orcid-libs-bench --emit OUT_DIR [--root DIR] [--dump PATH | PATH]\n       \
orcid-libs-bench --reread DIR --emit OUT_DIR";

struct Args {
    root: PathBuf,
    emit: Option<PathBuf>,
    reread: Option<PathBuf>,
    dump: Option<PathBuf>,
    iters: Option<u64>,
    dump_iters: Option<u64>,
    warmup: u64,
    only: Option<Vec<String>>,
}

fn value(it: &mut impl Iterator<Item = String>, flag: &str) -> Result<String, String> {
    it.next().ok_or_else(|| format!("{flag} needs a value"))
}

fn number(s: &str, flag: &str) -> Result<u64, String> {
    s.parse::<u64>()
        .map_err(|_| format!("{flag}: not a number: {s}"))
}

fn parse_args() -> Result<Args, String> {
    let mut a = Args {
        root: PathBuf::from("."),
        emit: None,
        reread: None,
        dump: None,
        iters: None,
        dump_iters: None,
        warmup: 2,
        only: None,
    };
    let mut it = std::env::args().skip(1);
    while let Some(arg) = it.next() {
        match arg.as_str() {
            "-h" | "--help" => return Err(String::new()),
            "--root" => a.root = PathBuf::from(value(&mut it, &arg)?),
            "--emit" => a.emit = Some(PathBuf::from(value(&mut it, &arg)?)),
            "--reread" => a.reread = Some(PathBuf::from(value(&mut it, &arg)?)),
            "--dump" => a.dump = Some(PathBuf::from(value(&mut it, &arg)?)),
            "--iters" => a.iters = Some(number(&value(&mut it, &arg)?, &arg)?),
            "--dump-iters" => a.dump_iters = Some(number(&value(&mut it, &arg)?, &arg)?),
            "--warmup" => a.warmup = number(&value(&mut it, &arg)?, &arg)?,
            "--only" => {
                let v = value(&mut it, &arg)?;
                a.only = Some(v.split(',').map(str::to_string).collect());
            }
            s if s.starts_with('-') => return Err(format!("unknown argument: {s}")),
            _ => a.dump = Some(PathBuf::from(arg)),
        }
    }
    if a.reread.is_some() && a.emit.is_none() {
        return Err("--reread needs --emit OUT_DIR".to_string());
    }
    if let Some(only) = &a.only {
        for w in only {
            if !WORKLOADS.iter().any(|(n, _)| n == w) {
                return Err(format!("unknown workload: {w}"));
            }
        }
    }
    Ok(a)
}

fn main() -> ExitCode {
    let args = match parse_args() {
        Ok(a) => a,
        Err(e) => {
            if !e.is_empty() {
                eprintln!("orcid-libs-bench: {e}");
            }
            eprintln!("{USAGE}");
            return ExitCode::from(2);
        }
    };
    let result = match (&args.reread, &args.emit) {
        (Some(src), Some(dir)) => reread(src, dir),
        (None, Some(dir)) => emit(&args, dir),
        _ => run(&args),
    };
    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("orcid-libs-bench: {e}");
            ExitCode::FAILURE
        }
    }
}

/// An yorc-rs error as an `io::Error`, with context.
fn lib<T>(r: yorc::Result<T>, what: &str) -> io::Result<T> {
    r.map_err(|e| io::Error::other(format!("{what}: {e}")))
}

fn read(path: &Path) -> io::Result<Vec<u8>> {
    fs::read(path).map_err(|e| io::Error::new(e.kind(), format!("{}: {e}", path.display())))
}

/// Inside a timed loop: report and stop instead of returning a value that
/// would make a failing workload look fast.
fn fail(what: &str, e: &dyn std::fmt::Display) -> ! {
    eprintln!("orcid-libs-bench: {what}: {e}");
    std::process::exit(1)
}

// ------------------------------------------------------------------ inputs

/// SplitMix64, used only to generate the iD list (same constants as Zig).
struct SplitMix(u64);

impl SplitMix {
    fn next(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }
}

fn text(b: &[u8]) -> String {
    b.iter().map(|&c| char::from(c)).collect()
}

fn hyphenate(d: &[u8; 16]) -> String {
    let mut s = String::with_capacity(19);
    for (i, &c) in d.iter().enumerate() {
        if i > 0 && i % 4 == 0 {
            s.push('-');
        }
        s.push(char::from(c));
    }
    s
}

/// The deterministic iD list: canonical, URL, hyphenless, spaced and
/// lowercase-`x` forms, and one in eight invalid (wrong check character, or
/// too short).
fn gen_ids(n: usize) -> Vec<String> {
    let mut rng = SplitMix(42);
    let mut out = Vec::with_capacity(n);
    for i in 0..n {
        let mut r = rng.next();
        let mut d = [b'0'; 16];
        for c in d.iter_mut().take(15).skip(3) {
            *c = b'0' + (r % 10) as u8;
            r /= 10;
        }
        d[15] = id::check_char(&d[..15]).unwrap_or(b'0');
        let canon = hyphenate(&d);
        let plain = text(&d);
        let s = match i % 8 {
            0 => canon,
            1 => format!("https://orcid.org/{canon}"),
            2 => format!("http://orcid.org/{canon}"),
            3 => format!("orcid.org/{plain}"),
            4 => plain,
            5 => format!(" {} ", canon.replace('-', " ")),
            6 => plain.to_ascii_lowercase(),
            _ => {
                let mut bad = d;
                bad[15] = match bad[15] {
                    b'X' => b'0',
                    b'9' => b'X',
                    c => c + 1,
                };
                if i % 16 == 15 {
                    text(&bad[..15])
                } else {
                    hyphenate(&bad)
                }
            }
        };
        out.push(s);
    }
    out
}

/// Files with extension `ext` in `dir`, sorted by name.
fn files(dir: &Path, ext: &str) -> io::Result<Vec<PathBuf>> {
    let mut v = Vec::new();
    let entries =
        fs::read_dir(dir).map_err(|e| io::Error::new(e.kind(), format!("{}: {e}", dir.display())))?;
    for e in entries {
        let p = e?.path();
        if p.is_file() && p.extension().is_some_and(|x| x == ext) {
            v.push(p);
        }
    }
    v.sort();
    Ok(v)
}

fn stem(p: &Path) -> String {
    p.file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("?")
        .to_string()
}

fn dump_path(args: &Args) -> PathBuf {
    match &args.dump {
        Some(p) => p.clone(),
        None => args.root.join(DUMP),
    }
}

fn find(hay: &[u8], needle: &[u8], from: usize) -> Option<usize> {
    hay.get(from..)?
        .windows(needle.len())
        .position(|w| w == needle)
        .map(|i| from + i)
}

/// The `changes_record` copy of the fixture, made the same way by both
/// programs: `Edited: ` inserted right after the first `<common:title>` that
/// follows the first `<work:work-summary` (the title of the record's first
/// work summary).
fn edited_fixture(fixture: &[u8]) -> io::Result<Vec<u8>> {
    const TAG: &[u8] = b"<common:title>";
    let at = find(fixture, b"<work:work-summary", 0)
        .and_then(|i| find(fixture, TAG, i))
        .ok_or_else(|| io::Error::other("fixture: no work summary title"))?
        + TAG.len();
    let mut out = Vec::with_capacity(fixture.len() + 8);
    out.extend_from_slice(&fixture[..at]);
    out.extend_from_slice(b"Edited: ");
    out.extend_from_slice(&fixture[at..]);
    Ok(out)
}

// --------------------------------------------------------------- benchmarks

fn report(
    out: &mut impl Write,
    name: &str,
    iters: u64,
    bytes: u64,
    total_ns: u128,
) -> io::Result<()> {
    let ns_per_op = if iters == 0 { 0 } else { total_ns / u128::from(iters) };
    let mb_per_s = if total_ns == 0 {
        0.0
    } else {
        bytes as f64 * iters as f64 * 1e3 / total_ns as f64
    };
    writeln!(
        out,
        "{{\"impl\":\"{IMPL}\",\"workload\":\"{name}\",\"iterations\":{iters},\"bytes\":{bytes},\
\"total_ns\":{total_ns},\"ns_per_op\":{ns_per_op},\"mb_per_s\":{mb_per_s:.2}}}"
    )?;
    out.flush()
}

fn bench<F: FnMut() -> usize>(
    out: &mut impl Write,
    name: &str,
    iters: u64,
    warmup: u64,
    bytes: u64,
    mut f: F,
) -> io::Result<()> {
    for _ in 0..warmup {
        black_box(f());
    }
    let start = Instant::now();
    for _ in 0..iters {
        black_box(f());
    }
    let total = start.elapsed().as_nanos();
    report(out, name, iters, bytes, total)
}

/// One pass over a dump: parse every `.xml` member. Returns the member count
/// and their total size.
fn stream_dump(path: &Path) -> (usize, u64) {
    let mut archive = match dump::open(path) {
        Ok(a) => a,
        Err(e) => fail(&path.display().to_string(), &e),
    };
    let records = match dump::records(&mut archive) {
        Ok(r) => r,
        Err(e) => fail(&path.display().to_string(), &e),
    };
    let mut n = 0;
    let mut bytes = 0u64;
    for m in records {
        let m = match m {
            Ok(m) => m,
            Err(e) => fail(&path.display().to_string(), &e),
        };
        match m.parse() {
            Ok(doc) => {
                black_box(&doc);
            }
            Err(e) => fail(&m.stem, &e),
        }
        n += 1;
        bytes += m.bytes.len() as u64;
    }
    (n, bytes)
}

/// One pass over a dump: a seeded reservoir sample ([`Reservoir`]) of its
/// records, picking only (no member is read). Eligible, as yorc-duckdb's
/// `orcid_dump_sample`: a regular file whose name is longer than 4
/// characters and ends in `.xml` (any case), with a stem that normalises to
/// a valid iD. Returns the picked stems in slot order and the number of
/// eligible members seen.
fn sample_dump(path: &Path, n: usize, seed: u64) -> (Vec<String>, u64) {
    let what = path.display().to_string();
    let mut archive = match dump::open(path) {
        Ok(a) => a,
        Err(e) => fail(&what, &e),
    };
    let entries = match archive.entries() {
        Ok(e) => e,
        Err(e) => fail(&what, &e),
    };
    let mut r = Reservoir::new(n, seed);
    for entry in entries {
        let entry = match entry {
            Ok(e) => e,
            Err(e) => fail(&what, &e),
        };
        if !entry.header().entry_type().is_file() {
            continue;
        }
        let member = match entry.path() {
            Ok(p) => p.into_owned(),
            Err(e) => fail(&what, &e),
        };
        let Some(stem) = dump::xml_entry_stem(&member) else {
            continue;
        };
        if id::normalize(stem).is_none() {
            continue;
        }
        let slot = r.offer();
        if slot != Slot::Skip {
            r.put(slot, stem.to_string());
        }
    }
    let seen = r.seen();
    (r.into_items(), seen)
}

fn run(args: &Args) -> io::Result<()> {
    let want = |name: &str| match &args.only {
        Some(only) => only.iter().any(|w| w == name),
        None => true,
    };
    let fixture = read(&args.root.join(FIXTURE))?;
    let doc = lib(xml::from_slice(&fixture), FIXTURE)?;
    let xml_text = lib(xml::to_string(&doc.root), "write XML")?;
    let json_text = lib(json::to_string(&doc.root), "write JSON")?;
    let source_hash = hash::sha256_hex(&fixture);
    let ids = gen_ids(N_IDS);
    let dump = dump_path(args);
    let group_id_json = read(&args.root.join(GROUP_ID_JSON))?;
    let group_id_hash = hash::sha256_hex(&group_id_json);
    let edited = edited_fixture(&fixture)?;
    let edited_doc = lib(xml::from_slice(&edited), "edited fixture")?;
    eprintln!(
        "{IMPL}: fixture {} B, XML out {} B, JSON out {} B, {} iDs",
        fixture.len(),
        xml_text.len(),
        json_text.len(),
        ids.len()
    );

    let stdout = io::stdout();
    let mut out = stdout.lock();
    let w = args.warmup;
    for (name, default_iters) in WORKLOADS {
        if !want(name) {
            continue;
        }
        let iters = if name == "dump_stream" || name == "dump_sample" {
            args.dump_iters.unwrap_or(default_iters)
        } else {
            args.iters.unwrap_or(default_iters)
        };
        match name {
            "id_normalize" => {
                let bytes = ids.iter().map(|s| s.len() as u64).sum();
                bench(&mut out, name, iters, w, bytes, || {
                    let mut n = 0;
                    for s in &ids {
                        if let Some(c) = id::normalize(black_box(s)) {
                            n += c.len();
                        }
                    }
                    n
                })?;
            }
            "xml_read_record" => {
                bench(&mut out, name, iters, w, fixture.len() as u64, || {
                    match xml::from_slice(black_box(&fixture)) {
                        Ok(d) => usize::from(d.orcid().is_some()),
                        Err(e) => fail(name, &e),
                    }
                })?;
            }
            "xml_write_record" => {
                bench(&mut out, name, iters, w, xml_text.len() as u64, || {
                    match xml::to_string(black_box(&doc.root)) {
                        Ok(s) => s.len(),
                        Err(e) => fail(name, &e),
                    }
                })?;
            }
            "json_write_record" => {
                bench(&mut out, name, iters, w, json_text.len() as u64, || {
                    match json::to_string(black_box(&doc.root)) {
                        Ok(s) => s.len(),
                        Err(e) => fail(name, &e),
                    }
                })?;
            }
            "json_read_record" => {
                bench(&mut out, name, iters, w, json_text.len() as u64, || {
                    match json::from_str("record", black_box(&json_text)) {
                        Ok(d) => usize::from(d.orcid().is_some()),
                        Err(e) => fail(name, &e),
                    }
                })?;
            }
            "rows_record" => {
                bench(&mut out, name, iters, w, fixture.len() as u64, || {
                    let t = Tables::from_document(black_box(&doc), Some(&source_hash));
                    Section::ALL.iter().map(|&s| t.get(s).len()).sum()
                })?;
            }
            "sha256" => {
                bench(&mut out, name, iters, w, fixture.len() as u64, || {
                    hash::sha256_hex(black_box(&fixture)).len()
                })?;
            }
            "dump_stream" => {
                // One untimed pass checks the archive and measures its size.
                let (members, bytes) = stream_dump(&dump);
                eprintln!(
                    "{IMPL}: dump {}: {members} XML members, {bytes} B uncompressed",
                    dump.display()
                );
                let warm = w.min(1);
                bench(&mut out, name, iters, warm, bytes, || stream_dump(&dump).0)?;
            }
            "group_ids_read" => {
                bench(&mut out, name, iters, w, group_id_json.len() as u64, || {
                    match json::from_slice("group-id-record", black_box(&group_id_json)) {
                        Ok(d) => rows::group_ids(&d, Some(&group_id_hash)).len(),
                        Err(e) => fail(name, &e),
                    }
                })?;
            }
            "timeline_record" => {
                bench(&mut out, name, iters, w, fixture.len() as u64, || {
                    rows::timeline(black_box(&doc), Some(&source_hash)).len()
                })?;
            }
            "changes_record" => {
                let bytes = (fixture.len() + edited.len()) as u64;
                bench(&mut out, name, iters, w, bytes, || {
                    rows::changes(Some(black_box(&doc)), Some(black_box(&edited_doc))).len()
                })?;
            }
            "dump_sample" => {
                // One untimed pass measures the archive (as for dump_stream).
                let (members, bytes) = stream_dump(&dump);
                eprintln!(
                    "{IMPL}: dump {}: {members} XML members, {bytes} B uncompressed; \
sample of {SAMPLE_N}, seed {SAMPLE_SEED}",
                    dump.display()
                );
                let warm = w.min(1);
                bench(&mut out, name, iters, warm, bytes, || {
                    sample_dump(&dump, SAMPLE_N, SAMPLE_SEED).0.len()
                })?;
            }
            _ => unreachable!("workload list and match disagree: {name}"),
        }
    }
    Ok(())
}

// --------------------------------------------------------------- cross-check

fn put(dir: &Path, name: &str, data: &[u8]) -> io::Result<()> {
    fs::write(dir.join(name), data)
}

fn put_result(dir: &Path, name: &str, r: yorc::Result<String>) -> io::Result<()> {
    match r {
        Ok(s) => put(dir, name, s.as_bytes()),
        Err(_) => put(dir, name, ERROR_TEXT.as_bytes()),
    }
}

/// TSV escaping: backslash, tab, LF and CR.
fn push_escaped(s: &mut String, v: &str) {
    for c in v.chars() {
        match c {
            '\\' => s.push_str("\\\\"),
            '\t' => s.push_str("\\t"),
            '\n' => s.push_str("\\n"),
            '\r' => s.push_str("\\r"),
            c => s.push(c),
        }
    }
}

/// One table: `# name<TAB>rows`, then (if any rows) the column names and one
/// line per row. NULL is `\N`, booleans `true`/`false`.
fn push_table(s: &mut String, name: &str, columns: &[Column], rows: &[Row]) {
    s.push_str(&format!("# {name}\t{}\n", rows.len()));
    if rows.is_empty() {
        return;
    }
    let cols: Vec<&str> = columns.iter().map(|c| c.name).collect();
    s.push_str(&cols.join("\t"));
    s.push('\n');
    for row in rows {
        for (i, c) in row.iter().enumerate() {
            if i > 0 {
                s.push('\t');
            }
            match c {
                Cell::Null => s.push_str("\\N"),
                Cell::Varchar(v) => push_escaped(s, v),
                Cell::Integer(v) => s.push_str(&v.to_string()),
                Cell::Boolean(v) => s.push_str(if *v { "true" } else { "false" }),
                _ => s.push_str("<unknown cell>"),
            }
        }
        s.push('\n');
    }
}

/// Every section, in `Section::ALL` order (one [`push_table`] each).
fn rows_tsv(t: &Tables) -> String {
    let mut s = String::new();
    for &sec in Section::ALL {
        push_table(&mut s, sec.name(), sec.columns(), t.get(sec));
    }
    s
}

/// One extra section's rows ([`push_table`]).
fn extra_tsv(extra: Extra, rows: &[Row]) -> String {
    let mut s = String::new();
    push_table(&mut s, extra.name(), extra.columns(), rows);
    s
}

/// A snapshot diff as the table `changes` ([`push_table`]; the columns of
/// yorc-duckdb's orcid_changes).
fn changes_tsv(changes: &[Change]) -> String {
    let rows: Vec<Row> = changes.iter().map(Change::to_row).collect();
    let mut s = String::new();
    push_table(&mut s, "changes", CHANGE_COLUMNS, &rows);
    s
}

/// An XML input: `.sha256`, `.xml` (written back), `.rows.tsv`, and if the
/// root has a JSON kind `.json` and `.json.xml` (JSON read back, XML written).
fn emit_xml_doc(dir: &Path, stem: &str, bytes: &[u8]) -> io::Result<()> {
    let h = hash::sha256_hex(bytes);
    put(dir, &format!("{stem}.sha256"), format!("{h}\n").as_bytes())?;
    let doc = match xml::from_slice(bytes) {
        Ok(d) => d,
        Err(_) => return put(dir, &format!("{stem}.xml"), ERROR_TEXT.as_bytes()),
    };
    put_result(dir, &format!("{stem}.xml"), xml::to_string(&doc.root))?;
    let t = Tables::from_document(&doc, Some(&h));
    put(dir, &format!("{stem}.rows.tsv"), rows_tsv(&t).as_bytes())?;
    let tsv = extra_tsv(Extra::GroupIds, &rows::group_ids(&doc, Some(&h)));
    put(dir, &format!("{stem}.group_ids.tsv"), tsv.as_bytes())?;
    let tsv = extra_tsv(Extra::Timeline, &rows::timeline(&doc, Some(&h)));
    put(dir, &format!("{stem}.timeline.tsv"), tsv.as_bytes())?;
    if let Some(kind) = json::kind_of(&doc.root) {
        match json::to_string(&doc.root) {
            Ok(j) => {
                put(dir, &format!("{stem}.json"), j.as_bytes())?;
                let back = json::from_str(kind, &j).and_then(|d| xml::to_string(&d.root));
                put_result(dir, &format!("{stem}.json.xml"), back)?;
            }
            Err(_) => put(dir, &format!("{stem}.json"), ERROR_TEXT.as_bytes())?,
        }
    }
    Ok(())
}

/// A JSON input: `.xml` and `.json` written from the model read.
fn emit_json_doc(dir: &Path, stem: &str, bytes: &[u8], kind: &str) -> io::Result<()> {
    let doc = match json::from_slice(kind, bytes) {
        Ok(d) => d,
        Err(_) => return put(dir, &format!("{stem}.xml"), ERROR_TEXT.as_bytes()),
    };
    put_result(dir, &format!("{stem}.xml"), xml::to_string(&doc.root))?;
    put_result(dir, &format!("{stem}.json"), json::to_string(&doc.root))
}

/// A group-id XML input: `.sha256`, `.xml` (written back), `.group_ids.tsv`,
/// `.json` and `.json.xml` (JSON read back, XML written).
fn emit_group_id_xml(dir: &Path, stem: &str, bytes: &[u8]) -> io::Result<()> {
    let h = hash::sha256_hex(bytes);
    put(dir, &format!("{stem}.sha256"), format!("{h}\n").as_bytes())?;
    let doc = match xml::from_slice(bytes) {
        Ok(d) => d,
        Err(_) => return put(dir, &format!("{stem}.xml"), ERROR_TEXT.as_bytes()),
    };
    put_result(dir, &format!("{stem}.xml"), xml::to_string(&doc.root))?;
    let tsv = extra_tsv(Extra::GroupIds, &rows::group_ids(&doc, Some(&h)));
    put(dir, &format!("{stem}.group_ids.tsv"), tsv.as_bytes())?;
    if let Some(kind) = json::kind_of(&doc.root) {
        match json::to_string(&doc.root) {
            Ok(j) => {
                put(dir, &format!("{stem}.json"), j.as_bytes())?;
                let back = json::from_str(kind, &j).and_then(|d| xml::to_string(&d.root));
                put_result(dir, &format!("{stem}.json.xml"), back)?;
            }
            Err(_) => put(dir, &format!("{stem}.json"), ERROR_TEXT.as_bytes())?,
        }
    }
    Ok(())
}

/// A side of a changes pair: `Ok(None)` for no snapshot, `Err` for one that
/// did not read.
fn snapshot(x: Option<&Option<yorc::model::Document>>) -> Result<Option<&yorc::model::Document>, ()> {
    match x {
        None => Ok(None),
        Some(Some(d)) => Ok(Some(d)),
        Some(None) => Err(()),
    }
}

/// The group-id JSON sample: `.group_ids.tsv` only (`source_hash` = SHA-256
/// of the JSON bytes; nothing if it does not read).
fn emit_group_id_json(dir: &Path, stem: &str, bytes: &[u8]) -> io::Result<()> {
    let Ok(doc) = json::from_slice("group-id-record", bytes) else {
        return Ok(());
    };
    let h = hash::sha256_hex(bytes);
    let tsv = extra_tsv(Extra::GroupIds, &rows::group_ids(&doc, Some(&h)));
    put(dir, &format!("{stem}.group_ids.tsv"), tsv.as_bytes())
}

/// Document kind of an ORCID JSON sample, from its file name (the table of
/// yorc-rs's tests/json_roundtrip.rs); `None` to skip the file.
fn json_sample_kind(name: &str) -> Option<&'static str> {
    const KINDS: [(&str, &str); 19] = [
        ("record-full", "record"),
        ("address", "address"),
        ("bulk-", "bulk"),
        ("distinction", "distinction"),
        ("education", "education"),
        ("employment", "employment"),
        ("external-identifier", "external-identifier"),
        ("funding", "funding"),
        ("invited-position", "invited-position"),
        ("keywords", "keyword"),
        ("membership", "membership"),
        ("other-names", "other-name"),
        ("peer-review-group-id", ""),
        ("peer-review", "peer-review"),
        ("qualification", "qualification"),
        ("research-resource", "research-resource"),
        ("researcher-url", "researcher-url"),
        ("service", "service"),
        ("work", "work"),
    ];
    let (_, k) = KINDS.iter().find(|(p, _)| name.starts_with(p))?;
    if k.is_empty() { None } else { Some(*k) }
}

fn emit(args: &Args, out: &Path) -> io::Result<()> {
    fs::create_dir_all(out)?;

    let mut s = String::new();
    for i in gen_ids(N_IDS) {
        s.push_str(&i);
        s.push('\t');
        match id::normalize(&i) {
            Some(c) => s.push_str(&c),
            None => s.push('-'),
        }
        s.push('\n');
    }
    put(out, "ids.tsv", s.as_bytes())?;

    let d = out.join("fixture");
    fs::create_dir_all(&d)?;
    let fx = args.root.join(FIXTURE);
    emit_xml_doc(&d, &stem(&fx), &read(&fx)?)?;

    for set in ["read_samples", "write_samples"] {
        let src = args.root.join(SAMPLES).join(set);
        let d = out.join(set);
        fs::create_dir_all(&d)?;
        for f in files(&src, "xml")? {
            emit_xml_doc(&d, &stem(&f), &read(&f)?)?;
        }
        let d = out.join("json_samples").join(set);
        fs::create_dir_all(&d)?;
        for f in files(&src, "json")? {
            let name = f.file_name().and_then(|n| n.to_str()).unwrap_or_default();
            if let Some(kind) = json_sample_kind(name) {
                emit_json_doc(&d, &stem(&f), &read(&f)?, kind)?;
            }
        }
    }

    let f = args.root.join(GROUP_ID_JSON);
    let d = out.join("json_samples").join("write_samples");
    emit_group_id_json(&d, &stem(&f), &read(&f)?)?;
    let d = out.join("group_id");
    fs::create_dir_all(&d)?;
    for rel in GROUP_ID_XML {
        let f = args.root.join(rel);
        emit_group_id_xml(&d, &stem(&f), &read(&f)?)?;
    }

    let d = out.join("changes");
    fs::create_dir_all(&d)?;
    let parse = |bytes: &[u8]| xml::from_slice(bytes).ok();
    let old = parse(&read(&args.root.join(CHANGES_OLD))?);
    let new = parse(&read(&args.root.join(CHANGES_NEW))?);
    let fixture = read(&args.root.join(FIXTURE))?;
    let fixture_doc = parse(&fixture);
    let edited_doc = parse(&edited_fixture(&fixture)?);
    // (name, old, new); a side that does not read makes the file `error`
    for (name, a, b) in [
        ("old_new", Some(&old), Some(&new)),
        ("new_old", Some(&new), Some(&old)),
        ("none_new", None, Some(&new)),
        ("fixture_edited", Some(&fixture_doc), Some(&edited_doc)),
    ] {
        let file = format!("{name}.changes.tsv");
        match (snapshot(a), snapshot(b)) {
            (Ok(a), Ok(b)) => put(&d, &file, changes_tsv(&rows::changes(a, b)).as_bytes())?,
            _ => put(&d, &file, ERROR_TEXT.as_bytes())?,
        }
    }

    let d = out.join("dump");
    fs::create_dir_all(&d)?;
    let path = dump_path(args);
    let mut archive = dump::open(&path)
        .map_err(|e| io::Error::new(e.kind(), format!("{}: {e}", path.display())))?;
    let mut s = String::new();
    for m in dump::records(&mut archive)? {
        let m = m?;
        let h = hash::sha256_hex(&m.bytes);
        match xml::from_slice(&m.bytes) {
            Ok(doc) => {
                let t = Tables::from_document(&doc, Some(&h));
                let n: usize = Section::ALL.iter().map(|&sec| t.get(sec).len()).sum();
                s.push_str(&format!(
                    "{}\t{h}\t{}\t{n}\n",
                    m.stem,
                    doc.orcid().unwrap_or("-")
                ));
            }
            Err(_) => s.push_str(&format!("{}\t{h}\terror\t-\n", m.stem)),
        }
    }
    put(&d, "members.tsv", s.as_bytes())?;
    let (sample, seen) = sample_dump(&path, SAMPLE_N, SAMPLE_SEED);
    let mut s = format!("# sample\tn={SAMPLE_N}\tseed={SAMPLE_SEED}\tseen={seen}\n");
    for stem in &sample {
        s.push_str(stem);
        s.push('\n');
    }
    put(&d, "sample.tsv", s.as_bytes())?;
    eprintln!("{IMPL}: wrote {}", out.display());
    Ok(())
}

// ------------------------------------------------------------------ re-read

/// Every `.xml` and `.json` file below `dir`, depth first, sorted by name.
fn walk(dir: &Path, out: &mut Vec<PathBuf>) -> io::Result<()> {
    let entries =
        fs::read_dir(dir).map_err(|e| io::Error::new(e.kind(), format!("{}: {e}", dir.display())))?;
    let mut paths = Vec::new();
    for e in entries {
        paths.push(e?.path());
    }
    paths.sort();
    for p in paths {
        if p.is_dir() {
            walk(&p, out)?;
        } else if p.is_file() && p.extension().is_some_and(|x| x == "xml" || x == "json") {
            out.push(p);
        }
    }
    Ok(())
}

/// Document kind of a JSON file: the first line of `<file>.kind` when there
/// is one (compare.sh writes them), else the kind of an ORCID sample name.
fn reread_kind(path: &Path) -> Option<String> {
    let mut side = path.as_os_str().to_owned();
    side.push(".kind");
    if let Ok(s) = fs::read_to_string(PathBuf::from(side)) {
        let kind = s.trim();
        if !kind.is_empty() {
            return Some(kind.to_string());
        }
    }
    let name = path.file_name().and_then(|n| n.to_str())?;
    json_sample_kind(name).map(str::to_string)
}

/// `--reread SRC --emit OUT`: each `.xml` (XML) and `.json` (JSON, with the
/// kind of [`reread_kind`]) file below SRC is read with yorc-rs and its
/// rows written to `OUT/<path below SRC>.rows.tsv`, in the `--emit` format
/// with `source_hash` = SHA-256 of the file; `error` if it does not read.
fn reread(src: &Path, out: &Path) -> io::Result<()> {
    let mut paths = Vec::new();
    walk(src, &mut paths)?;
    let mut failed = 0usize;
    for p in &paths {
        let rel = p.strip_prefix(src).map_err(io::Error::other)?;
        let mut name = rel.as_os_str().to_owned();
        name.push(".rows.tsv");
        let dest = out.join(PathBuf::from(name));
        if let Some(dir) = dest.parent() {
            fs::create_dir_all(dir)?;
        }
        let bytes = read(p)?;
        let doc = if p.extension().is_some_and(|x| x == "json") {
            match reread_kind(p) {
                Some(kind) => json::from_slice(&kind, &bytes),
                None => {
                    eprintln!("{IMPL}: {}: no document kind (no .kind file)", p.display());
                    failed += 1;
                    fs::write(&dest, ERROR_TEXT)?;
                    continue;
                }
            }
        } else {
            xml::from_slice(&bytes)
        };
        match doc {
            Ok(doc) => {
                let h = hash::sha256_hex(&bytes);
                let t = Tables::from_document(&doc, Some(&h));
                fs::write(&dest, rows_tsv(&t))?;
            }
            Err(_) => {
                failed += 1;
                fs::write(&dest, ERROR_TEXT)?;
            }
        }
    }
    eprintln!(
        "{IMPL}: re-read {} documents below {} ({failed} did not read) into {}",
        paths.len(),
        src.display(),
        out.display()
    );
    Ok(())
}
