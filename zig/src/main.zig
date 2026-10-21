//! yorc-zig side of the yorc-rs / yorc-zig comparison (yorc-bench).
//!
//!   orcid-libs-bench [--root DIR] [--iters N] [--dump-iters N] [--warmup N]
//!                    [--only W,W,...] [--dump PATH | PATH]
//!   orcid-libs-bench --emit OUT_DIR [--root DIR] [--dump PATH | PATH]
//!
//! Benchmark mode prints one JSON line per workload on stdout:
//! {"impl","workload","iterations","bytes","total_ns","ns_per_op","mb_per_s"}.
//! Emit mode writes the cross-check tree that ./compare.sh diffs
//! against the Rust program's. Both programs implement the same workloads on
//! the same inputs; keep them in step (rust/src/main.rs).
//!
//! Since 2026-10-18 emit mode also writes, for yorc-zig's opt-in sections
//! (`rows.Extra`, `rows.changes`; layout and format: CROSSCHECK.md,
//! "Bench files for group ids, timeline and changes"): `<stem>.group_ids.tsv`
//! and `<stem>.timeline.tsv` next to each XML input's `.rows.tsv`;
//! `json_samples/write_samples/peer-review-group-id.group_ids.tsv`;
//! `group_id/` (the group-id XML inputs: `.sha256`, `.xml`, `.json`,
//! `.json.xml`, `.group_ids.tsv`); `changes/<old>_<new>.changes.tsv`; and
//! `dump/sample.tsv` (the stems of a reservoir sample of the dump, n = 5,
//! seed 42), byte for byte as the Rust program writes them.
//!
//! Single-threaded; timing is the `.awake` (monotonic) std.Io clock around N
//! iterations after a warm-up.
const std = @import("std");
const yorc = @import("yorc");

const Io = std.Io;
const Allocator = std.mem.Allocator;
const model = yorc.model;
const rows = yorc.rows;

// "zig" when libc is linked (init.gpa is malloc, as the Rust program's
// allocator): the headline comparison. "zig-own" on Zig's own default
// allocator, reported next to it (run.sh builds both).
const impl = if (@import("builtin").link_libc) "zig" else "zig-own";
const fixture_rel = "yorc-rs/tests/data/0000-0003-0100-6634.xml";
const samples_rel = "yorc-rs/reference/orcid-model/record_3.0/samples";
const dump_rel = "yorc-zig/testdata/dump/orcid_test_summaries.tgz";
/// The group-id inputs (`group_id/`): ORCID's XML sample and a two-record
/// page (yorc-duckdb's orcid_api_messages.test).
const group_id_xml_rel = [_][]const u8{
    "yorc-rs/reference/orcid-model/group-id-3.0/samples/group-id-3.0.xml",
    "yorc-rs/tests/data/group-id-records.xml",
};
/// ORCID's group-id JSON write sample: the `group_ids_read` input, and
/// `json_samples/write_samples/<stem>.group_ids.tsv`.
const group_id_json_rel = "yorc-rs/reference/orcid-model/record_3.0/samples/write_samples/peer-review-group-id.json";
/// Two snapshots of ORCID's record sample (yorc-duckdb's orcid_changes tests).
const changes_old_rel = "yorc-rs/tests/data/changes/old.xml";
const changes_new_rel = "yorc-rs/tests/data/changes/new.xml";
/// `dump_sample` and `dump/sample.tsv`: reservoir size and seed.
const sample_n = 5;
const sample_seed = 42;
const n_ids = 10_000;
const max_file = 256 << 20;
const max_member = 64 << 20;
const error_text = "error\n";

const Workload = struct { name: []const u8, iters: u64 };

/// Workloads in output order, with their default iteration counts. The
/// first eight are the original set (keep them first and unchanged, so runs
/// stay comparable); the last four were appended on 2026-10-18.
const workloads = [_]Workload{
    .{ .name = "id_normalize", .iters = 200 },
    .{ .name = "xml_read_record", .iters = 30 },
    .{ .name = "xml_write_record", .iters = 30 },
    .{ .name = "json_write_record", .iters = 30 },
    .{ .name = "json_read_record", .iters = 30 },
    .{ .name = "rows_record", .iters = 30 },
    .{ .name = "sha256", .iters = 300 },
    .{ .name = "dump_stream", .iters = 20 },
    .{ .name = "group_ids_read", .iters = 10_000 },
    .{ .name = "timeline_record", .iters = 30 },
    .{ .name = "changes_record", .iters = 30 },
    .{ .name = "dump_sample", .iters = 20 },
};

const usage =
    \\usage: orcid-libs-bench [--root DIR] [--iters N] [--dump-iters N] [--warmup N] [--only W,W] [--dump PATH | PATH]
    \\       orcid-libs-bench --emit OUT_DIR [--root DIR] [--dump PATH | PATH]
    \\
;

const Args = struct {
    root: []const u8 = ".",
    emit: ?[]const u8 = null,
    dump: ?[]const u8 = null,
    iters: ?u64 = null,
    dump_iters: ?u64 = null,
    warmup: u64 = 2,
    only: ?[]const u8 = null,
};

fn eql(a: []const u8, b: []const u8) bool {
    return std.mem.eql(u8, a, b);
}

fn isWorkload(name: []const u8) bool {
    for (workloads) |w| if (eql(w.name, name)) return true;
    return false;
}

fn wanted(only: ?[]const u8, name: []const u8) bool {
    const list = only orelse return true;
    var it = std.mem.splitScalar(u8, list, ',');
    while (it.next()) |w| if (eql(w, name)) return true;
    return false;
}

fn parseArgs(argv: []const [:0]const u8) !Args {
    var a: Args = .{};
    var i: usize = 1;
    while (i < argv.len) : (i += 1) {
        const arg: []const u8 = argv[i];
        if (eql(arg, "-h") or eql(arg, "--help")) return error.Help;
        const flags = [_][]const u8{ "--root", "--emit", "--dump", "--iters", "--dump-iters", "--warmup", "--only" };
        const takes_value = for (flags) |f| {
            if (eql(arg, f)) break true;
        } else false;
        if (!takes_value) {
            if (arg.len > 0 and arg[0] == '-') {
                std.debug.print("orcid-libs-bench: unknown argument: {s}\n", .{arg});
                return error.Usage;
            }
            a.dump = arg;
            continue;
        }
        i += 1;
        if (i >= argv.len) {
            std.debug.print("orcid-libs-bench: {s} needs a value\n", .{arg});
            return error.Usage;
        }
        const v: []const u8 = argv[i];
        if (eql(arg, "--root")) {
            a.root = v;
        } else if (eql(arg, "--emit")) {
            a.emit = v;
        } else if (eql(arg, "--dump")) {
            a.dump = v;
        } else if (eql(arg, "--only")) {
            var it = std.mem.splitScalar(u8, v, ',');
            while (it.next()) |w| {
                if (!isWorkload(w)) {
                    std.debug.print("orcid-libs-bench: unknown workload: {s}\n", .{w});
                    return error.Usage;
                }
            }
            a.only = v;
        } else {
            const n = std.fmt.parseInt(u64, v, 10) catch {
                std.debug.print("orcid-libs-bench: {s}: not a number: {s}\n", .{ arg, v });
                return error.Usage;
            };
            if (eql(arg, "--iters")) {
                a.iters = n;
            } else if (eql(arg, "--dump-iters")) {
                a.dump_iters = n;
            } else {
                a.warmup = n;
            }
        }
    }
    return a;
}

pub fn main(init: std.process.Init) !u8 {
    const gpa = init.gpa;
    const io = init.io;
    const argv = try init.minimal.args.toSlice(init.arena.allocator());
    const args = parseArgs(argv) catch {
        std.debug.print("{s}", .{usage});
        return 2;
    };

    var out_buf: [4096]u8 = undefined;
    var stdout = Io.File.stdout().writerStreaming(io, &out_buf);
    const out = &stdout.interface;
    if (args.emit) |dir| {
        try emit(gpa, io, args, dir);
    } else {
        try run(gpa, io, out, args);
    }
    try out.flush();
    return 0;
}

fn readFile(io: Io, a: Allocator, path: []const u8) ![]u8 {
    return Io.Dir.cwd().readFileAlloc(io, path, a, .limited(max_file)) catch |err| {
        std.debug.print("orcid-libs-bench: {s}: {t}\n", .{ path, err });
        return err;
    };
}

fn lessStr(_: void, x: []const u8, y: []const u8) bool {
    return std.mem.lessThan(u8, x, y);
}

/// Names of the regular files in `path` ending in `ext`, sorted.
fn listFiles(io: Io, a: Allocator, path: []const u8, ext: []const u8) ![]const []const u8 {
    const dir = Io.Dir.cwd().openDir(io, path, .{ .iterate = true }) catch |err| {
        std.debug.print("orcid-libs-bench: {s}: {t}\n", .{ path, err });
        return err;
    };
    defer dir.close(io);
    var names: std.ArrayList([]const u8) = .empty;
    var it = dir.iterate();
    while (try it.next(io)) |e| {
        if (e.kind != .file or !std.mem.endsWith(u8, e.name, ext)) continue;
        try names.append(a, try a.dupe(u8, e.name));
    }
    std.mem.sort([]const u8, names.items, {}, lessStr);
    return names.items;
}

fn stemOf(name: []const u8) []const u8 {
    return if (std.mem.lastIndexOfScalar(u8, name, '.')) |i| name[0..i] else name;
}

fn dumpPath(a: Allocator, args: Args) ![]const u8 {
    return args.dump orelse try std.fs.path.join(a, &.{ args.root, dump_rel });
}

/// The `changes_record` copy of the fixture, made the same way by both
/// programs: `Edited: ` inserted right after the first `<common:title>` that
/// follows the first `<work:work-summary` (the title of the record's first
/// work summary).
fn editedFixture(a: Allocator, fixture: []const u8) ![]const u8 {
    const tag = "<common:title>";
    const summary = std.mem.indexOf(u8, fixture, "<work:work-summary") orelse return error.NoWorkSummaryTitle;
    const title = std.mem.indexOfPos(u8, fixture, summary, tag) orelse return error.NoWorkSummaryTitle;
    const at = title + tag.len;
    return std.mem.concat(a, u8, &.{ fixture[0..at], "Edited: ", fixture[at..] });
}

// ================================================================== inputs

/// SplitMix64, used only to generate the iD list (same constants as Rust).
const SplitMix = struct {
    state: u64,

    fn next(s: *SplitMix) u64 {
        s.state +%= 0x9E3779B97F4A7C15;
        var z = s.state;
        z = (z ^ (z >> 30)) *% 0xBF58476D1CE4E5B9;
        z = (z ^ (z >> 27)) *% 0x94D049BB133111EB;
        return z ^ (z >> 31);
    }
};

fn hyphenate(d: [16]u8) [19]u8 {
    var out: [19]u8 = undefined;
    var o: usize = 0;
    for (d, 0..) |c, i| {
        if (i > 0 and i % 4 == 0) {
            out[o] = '-';
            o += 1;
        }
        out[o] = c;
        o += 1;
    }
    return out;
}

/// The deterministic iD list: canonical, URL, hyphenless, spaced and
/// lowercase-`x` forms, and one in eight invalid (wrong check character, or
/// too short).
fn genIds(a: Allocator, n: usize) ![]const []const u8 {
    var rng: SplitMix = .{ .state = 42 };
    const out = try a.alloc([]const u8, n);
    for (out, 0..) |*slot, i| {
        var r = rng.next();
        var d: [16]u8 = @splat('0');
        for (3..15) |k| {
            d[k] = '0' + @as(u8, @intCast(r % 10));
            r /= 10;
        }
        d[15] = yorc.id.checkChar(d[0..15]) orelse '0';
        const canon = hyphenate(d);
        slot.* = switch (i % 8) {
            0 => try a.dupe(u8, canon[0..]),
            1 => try std.fmt.allocPrint(a, "https://orcid.org/{s}", .{canon[0..]}),
            2 => try std.fmt.allocPrint(a, "http://orcid.org/{s}", .{canon[0..]}),
            3 => try std.fmt.allocPrint(a, "orcid.org/{s}", .{d[0..]}),
            4 => try a.dupe(u8, d[0..]),
            5 => blk: {
                var spaced = canon;
                for (&spaced) |*c| {
                    if (c.* == '-') c.* = ' ';
                }
                break :blk try std.fmt.allocPrint(a, " {s} ", .{spaced[0..]});
            },
            6 => blk: {
                const s = try a.dupe(u8, d[0..]);
                for (s) |*c| c.* = std.ascii.toLower(c.*);
                break :blk s;
            },
            else => blk: {
                var bad = d;
                bad[15] = switch (bad[15]) {
                    'X' => '0',
                    '9' => 'X',
                    else => bad[15] + 1,
                };
                if (i % 16 == 15) break :blk try a.dupe(u8, bad[0..15]);
                const h = hyphenate(bad);
                break :blk try a.dupe(u8, h[0..]);
            },
        };
    }
    return out;
}

// ============================================================== benchmarks

fn report(out: *Io.Writer, name: []const u8, iters: u64, bytes: u64, total_ns: u64) !void {
    const per_op = if (iters == 0) 0 else total_ns / iters;
    const mb: f64 = if (total_ns == 0) 0 else @as(f64, @floatFromInt(bytes)) * @as(f64, @floatFromInt(iters)) * 1e3 / @as(f64, @floatFromInt(total_ns));
    try out.print(
        "{{\"impl\":\"" ++ impl ++ "\",\"workload\":\"{s}\",\"iterations\":{d},\"bytes\":{d},\"total_ns\":{d},\"ns_per_op\":{d},\"mb_per_s\":{d:.2}}}\n",
        .{ name, iters, bytes, total_ns, per_op, mb },
    );
    try out.flush();
}

/// Runs `ctx.once()` `warmup` times, then `iters` times under the clock.
fn bench(io: Io, out: *Io.Writer, name: []const u8, iters: u64, warmup: u64, bytes: u64, ctx: anytype) !void {
    var i: u64 = 0;
    while (i < warmup) : (i += 1) std.mem.doNotOptimizeAway(try ctx.once());
    const start = Io.Timestamp.now(io, .awake);
    i = 0;
    while (i < iters) : (i += 1) std.mem.doNotOptimizeAway(try ctx.once());
    const total: u64 = @intCast(start.durationTo(Io.Timestamp.now(io, .awake)).toNanoseconds());
    try report(out, name, iters, bytes, total);
}

const IdNormalize = struct {
    ids: []const []const u8,

    fn once(c: @This()) !usize {
        var n: usize = 0;
        for (c.ids) |s| {
            if (yorc.id.normalize(s)) |canon| n += canon.len;
        }
        return n;
    }
};

const XmlRead = struct {
    gpa: Allocator,
    bytes: []const u8,

    fn once(c: @This()) !usize {
        var d = try yorc.xml.parse(c.gpa, c.bytes, .{}, null);
        defer d.deinit();
        return @intFromBool(d.orcid() != null);
    }
};

const XmlWrite = struct {
    gpa: Allocator,
    root: *const model.Root,

    fn once(c: @This()) !usize {
        const s = try yorc.xml.toOwned(c.gpa, c.root, null);
        defer c.gpa.free(s);
        return s.len;
    }
};

const JsonWrite = struct {
    gpa: Allocator,
    root: *const model.Root,

    fn once(c: @This()) !usize {
        const s = try yorc.json.toOwned(c.gpa, c.root, null);
        defer c.gpa.free(s);
        return s.len;
    }
};

const JsonRead = struct {
    gpa: Allocator,
    text: []const u8,

    fn once(c: @This()) !usize {
        var d = try yorc.json.parse(c.gpa, "record", c.text, null);
        defer d.deinit();
        return @intFromBool(d.orcid() != null);
    }
};

const RowsRecord = struct {
    gpa: Allocator,
    doc: *const model.Document,
    hash: []const u8,

    fn once(c: @This()) !usize {
        var t = try rows.Tables.fromDocument(c.gpa, c.doc, c.hash);
        defer t.deinit();
        var n: usize = 0;
        for (rows.Section.all) |s| n += t.count(s);
        return n;
    }
};

const Sha256 = struct {
    bytes: []const u8,

    fn once(c: @This()) !usize {
        const h = yorc.hash.sha256Hex(c.bytes);
        return h.len + h[0];
    }
};

const DumpStream = struct {
    gpa: Allocator,
    io: Io,
    path: []const u8,

    fn once(c: @This()) !usize {
        return (try streamDump(c.gpa, c.io, c.path)).members;
    }
};

const GroupIdsRead = struct {
    gpa: Allocator,
    bytes: []const u8,
    hash: []const u8,

    fn once(c: @This()) !usize {
        var d = try yorc.json.parse(c.gpa, "group-id-record", c.bytes, null);
        defer d.deinit();
        var r = try rows.groupIds(c.gpa, &d, c.hash);
        defer r.deinit();
        return r.rows.len;
    }
};

const TimelineRecord = struct {
    gpa: Allocator,
    doc: *const model.Document,
    hash: []const u8,

    fn once(c: @This()) !usize {
        var r = try rows.timeline(c.gpa, c.doc, c.hash);
        defer r.deinit();
        return r.rows.len;
    }
};

const ChangesRecord = struct {
    gpa: Allocator,
    old: *const model.Document,
    new: *const model.Document,

    fn once(c: @This()) !usize {
        var r = try rows.changes(c.gpa, c.old, c.new);
        defer r.deinit();
        return r.items.len;
    }
};

const DumpSample = struct {
    gpa: Allocator,
    io: Io,
    path: []const u8,

    fn once(c: @This()) !usize {
        var s = try sampleDump(c.gpa, c.io, c.path, sample_n, sample_seed);
        defer freeSample(c.gpa, &s);
        return s.items.items.len;
    }
};

/// One pass over a dump: a seeded reservoir sample (`yorc.reservoir`) of its
/// records, picking only (no member is read). Eligible, as yorc-duckdb's
/// `orcid_dump_sample`: a regular file whose name is longer than 4
/// characters and ends in `.xml` (any case), with a stem that normalises to
/// a valid iD. The sample holds copies of the picked stems (free them with
/// `freeSample`), in slot order; `seen` counts the eligible members.
fn sampleDump(gpa: Allocator, io: Io, path: []const u8, n: usize, seed: u64) !yorc.reservoir.Reservoir([]const u8) {
    const fa = yorc.dump.FileArchive.open(gpa, io, path) catch |err| {
        std.debug.print("orcid-libs-bench: {s}: {t}\n", .{ path, err });
        return err;
    };
    defer fa.deinit();
    var r: yorc.reservoir.Reservoir([]const u8) = .init(n, seed);
    errdefer freeSample(gpa, &r);
    while (try fa.archive.nextXml()) |m| {
        const stem = yorc.dump.xmlEntryStem(m.name).?;
        if (yorc.id.normalize(stem) == null) continue;
        const slot = r.offer();
        if (slot == .skip) continue;
        const owned = try gpa.dupe(u8, stem);
        if (try r.put(gpa, slot, owned)) |evicted| gpa.free(evicted);
    }
    return r;
}

fn freeSample(gpa: Allocator, r: *yorc.reservoir.Reservoir([]const u8)) void {
    for (r.items.items) |x| gpa.free(x);
    r.deinit(gpa);
}

const DumpTotals = struct { members: usize, bytes: u64 };

/// One pass over a dump: parse every `.xml` member.
fn streamDump(gpa: Allocator, io: Io, path: []const u8) !DumpTotals {
    const fa = yorc.dump.FileArchive.open(gpa, io, path) catch |err| {
        std.debug.print("orcid-libs-bench: {s}: {t}\n", .{ path, err });
        return err;
    };
    defer fa.deinit();
    var t: DumpTotals = .{ .members = 0, .bytes = 0 };
    while (try fa.archive.nextXml()) |m| {
        const bytes = try fa.archive.read(m, max_member);
        var d = try yorc.xml.parse(gpa, bytes, .{}, null);
        d.deinit();
        t.members += 1;
        t.bytes += bytes.len;
    }
    return t;
}

fn run(gpa: Allocator, io: Io, out: *Io.Writer, args: Args) !void {
    var arena_state: std.heap.ArenaAllocator = .init(gpa);
    defer arena_state.deinit();
    const a = arena_state.allocator();

    const fixture = try readFile(io, a, try std.fs.path.join(a, &.{ args.root, fixture_rel }));
    var doc = try yorc.xml.parse(gpa, fixture, .{}, null);
    defer doc.deinit();
    const xml_text = try yorc.xml.toOwned(a, &doc.root, null);
    const json_text = try yorc.json.toOwned(a, &doc.root, null);
    const source_hash = yorc.hash.sha256Hex(fixture);
    const ids = try genIds(a, n_ids);
    const dump = try dumpPath(a, args);
    const group_id_json = try readFile(io, a, try std.fs.path.join(a, &.{ args.root, group_id_json_rel }));
    const group_id_hash = yorc.hash.sha256Hex(group_id_json);
    const edited = try editedFixture(a, fixture);
    var edited_doc = try yorc.xml.parse(gpa, edited, .{}, null);
    defer edited_doc.deinit();
    std.debug.print(impl ++ ": fixture {d} B, XML out {d} B, JSON out {d} B, {d} iDs\n", .{
        fixture.len, xml_text.len, json_text.len, ids.len,
    });

    const w = args.warmup;
    for (workloads) |wl| {
        if (!wanted(args.only, wl.name)) continue;
        const name = wl.name;
        const iters = if (eql(name, "dump_stream") or eql(name, "dump_sample")) args.dump_iters orelse wl.iters else args.iters orelse wl.iters;
        if (eql(name, "id_normalize")) {
            var bytes: u64 = 0;
            for (ids) |s| bytes += s.len;
            try bench(io, out, name, iters, w, bytes, IdNormalize{ .ids = ids });
        } else if (eql(name, "xml_read_record")) {
            try bench(io, out, name, iters, w, fixture.len, XmlRead{ .gpa = gpa, .bytes = fixture });
        } else if (eql(name, "xml_write_record")) {
            try bench(io, out, name, iters, w, xml_text.len, XmlWrite{ .gpa = gpa, .root = &doc.root });
        } else if (eql(name, "json_write_record")) {
            try bench(io, out, name, iters, w, json_text.len, JsonWrite{ .gpa = gpa, .root = &doc.root });
        } else if (eql(name, "json_read_record")) {
            try bench(io, out, name, iters, w, json_text.len, JsonRead{ .gpa = gpa, .text = json_text });
        } else if (eql(name, "rows_record")) {
            try bench(io, out, name, iters, w, fixture.len, RowsRecord{ .gpa = gpa, .doc = &doc, .hash = source_hash[0..] });
        } else if (eql(name, "sha256")) {
            try bench(io, out, name, iters, w, fixture.len, Sha256{ .bytes = fixture });
        } else if (eql(name, "dump_stream")) {
            // One untimed pass checks the archive and measures its size.
            const t = try streamDump(gpa, io, dump);
            std.debug.print(impl ++ ": dump {s}: {d} XML members, {d} B uncompressed\n", .{ dump, t.members, t.bytes });
            try bench(io, out, name, iters, @min(w, 1), t.bytes, DumpStream{ .gpa = gpa, .io = io, .path = dump });
        } else if (eql(name, "group_ids_read")) {
            try bench(io, out, name, iters, w, group_id_json.len, GroupIdsRead{ .gpa = gpa, .bytes = group_id_json, .hash = group_id_hash[0..] });
        } else if (eql(name, "timeline_record")) {
            try bench(io, out, name, iters, w, fixture.len, TimelineRecord{ .gpa = gpa, .doc = &doc, .hash = source_hash[0..] });
        } else if (eql(name, "changes_record")) {
            try bench(io, out, name, iters, w, fixture.len + edited.len, ChangesRecord{ .gpa = gpa, .old = &doc, .new = &edited_doc });
        } else if (eql(name, "dump_sample")) {
            // One untimed pass measures the archive (as for dump_stream).
            const t = try streamDump(gpa, io, dump);
            std.debug.print(impl ++ ": dump {s}: {d} XML members, {d} B uncompressed; sample of {d}, seed {d}\n", .{ dump, t.members, t.bytes, sample_n, sample_seed });
            try bench(io, out, name, iters, @min(w, 1), t.bytes, DumpSample{ .gpa = gpa, .io = io, .path = dump });
        } else unreachable;
    }
}

// ============================================================= cross-check

fn put(io: Io, dir: Io.Dir, name: []const u8, data: []const u8) !void {
    try dir.writeFile(io, .{ .sub_path = name, .data = data });
}

fn fileName(a: Allocator, stem: []const u8, suffix: []const u8) ![]const u8 {
    return std.mem.concat(a, u8, &.{ stem, suffix });
}

/// TSV escaping: backslash, tab, LF and CR.
fn writeEscaped(o: *Io.Writer, s: []const u8) !void {
    for (s) |c| switch (c) {
        '\\' => try o.writeAll("\\\\"),
        '\t' => try o.writeAll("\\t"),
        '\n' => try o.writeAll("\\n"),
        '\r' => try o.writeAll("\\r"),
        else => try o.writeByte(c),
    };
}

/// One table: `# name<TAB>rows`, then (if any rows) the column names and one
/// line per row. NULL is `\N`, booleans `true`/`false`.
fn writeTable(o: *Io.Writer, name: []const u8, columns: []const rows.Column, rs: []const rows.Row) !void {
    try o.print("# {s}\t{d}\n", .{ name, rs.len });
    if (rs.len == 0) return;
    for (columns, 0..) |col, i| {
        if (i > 0) try o.writeByte('\t');
        try o.writeAll(col.name);
    }
    try o.writeByte('\n');
    for (rs) |row| {
        for (row, 0..) |cell, i| {
            if (i > 0) try o.writeByte('\t');
            switch (cell) {
                .null => try o.writeAll("\\N"),
                .varchar => |s| try writeEscaped(o, s),
                .integer => |v| try o.print("{d}", .{v}),
                .boolean => |v| try o.writeAll(if (v) "true" else "false"),
            }
        }
        try o.writeByte('\n');
    }
}

/// Every section, in `Section.all` order (one `writeTable` each).
fn rowsTsv(a: Allocator, t: *const rows.Tables) ![]const u8 {
    var buf: Io.Writer.Allocating = .init(a);
    for (rows.Section.all) |sec| try writeTable(&buf.writer, sec.name(), sec.columns(), t.get(sec));
    return buf.written();
}

/// One extra section's rows (`writeTable`).
fn extraTsv(a: Allocator, r: *const rows.ExtraRows) ![]const u8 {
    var buf: Io.Writer.Allocating = .init(a);
    try writeTable(&buf.writer, r.extra.name(), r.extra.columns(), r.rows);
    return buf.written();
}

/// A snapshot diff as the table `changes` (`writeTable`; the columns of
/// yorc-duckdb's orcid_changes).
fn changesTsv(a: Allocator, c: []const rows.Change) ![]const u8 {
    const rs = try a.alloc(rows.Row, c.len);
    for (c, rs) |*ch, *row| {
        const cells = try a.alloc(rows.Cell, rows.change_columns.len);
        cells[0..rows.change_columns.len].* = ch.cells();
        row.* = cells;
    }
    var buf: Io.Writer.Allocating = .init(a);
    try writeTable(&buf.writer, "changes", &rows.change_columns, rs);
    return buf.written();
}

/// JSON read back with `kind`, then XML written; `error\n` on failure.
fn jsonToXml(gpa: Allocator, a: Allocator, kind: []const u8, text: []const u8) []const u8 {
    var d = yorc.json.parse(gpa, kind, text, null) catch return error_text;
    defer d.deinit();
    return yorc.xml.toOwned(a, &d.root, null) catch error_text;
}

/// An XML input: `.sha256`, `.xml` (written back), `.rows.tsv`, and if the
/// root has a JSON kind `.json` and `.json.xml` (JSON read back, XML written).
fn emitXmlDoc(gpa: Allocator, io: Io, dir: Io.Dir, stem: []const u8, bytes: []const u8) !void {
    var arena_state: std.heap.ArenaAllocator = .init(gpa);
    defer arena_state.deinit();
    const a = arena_state.allocator();
    const h = yorc.hash.sha256Hex(bytes);
    try put(io, dir, try fileName(a, stem, ".sha256"), try std.fmt.allocPrint(a, "{s}\n", .{h[0..]}));
    var doc = yorc.xml.parse(gpa, bytes, .{}, null) catch
        return put(io, dir, try fileName(a, stem, ".xml"), error_text);
    defer doc.deinit();
    const xml_out = yorc.xml.toOwned(a, &doc.root, null) catch error_text;
    try put(io, dir, try fileName(a, stem, ".xml"), xml_out);
    var t = try rows.Tables.fromDocument(gpa, &doc, h[0..]);
    defer t.deinit();
    try put(io, dir, try fileName(a, stem, ".rows.tsv"), try rowsTsv(a, &t));
    {
        var g = try rows.groupIds(gpa, &doc, h[0..]);
        defer g.deinit();
        try put(io, dir, try fileName(a, stem, ".group_ids.tsv"), try extraTsv(a, &g));
        var tl = try rows.timeline(gpa, &doc, h[0..]);
        defer tl.deinit();
        try put(io, dir, try fileName(a, stem, ".timeline.tsv"), try extraTsv(a, &tl));
    }
    if (doc.root.kind()) |kind| {
        if (yorc.json.toOwned(a, &doc.root, null)) |j| {
            try put(io, dir, try fileName(a, stem, ".json"), j);
            try put(io, dir, try fileName(a, stem, ".json.xml"), jsonToXml(gpa, a, kind, j));
        } else |_| try put(io, dir, try fileName(a, stem, ".json"), error_text);
    }
}

/// A JSON input: `.xml` and `.json` written from the model read.
fn emitJsonDoc(gpa: Allocator, io: Io, dir: Io.Dir, stem: []const u8, bytes: []const u8, kind: []const u8) !void {
    var arena_state: std.heap.ArenaAllocator = .init(gpa);
    defer arena_state.deinit();
    const a = arena_state.allocator();
    var doc = yorc.json.parse(gpa, kind, bytes, null) catch
        return put(io, dir, try fileName(a, stem, ".xml"), error_text);
    defer doc.deinit();
    try put(io, dir, try fileName(a, stem, ".xml"), yorc.xml.toOwned(a, &doc.root, null) catch error_text);
    try put(io, dir, try fileName(a, stem, ".json"), yorc.json.toOwned(a, &doc.root, null) catch error_text);
}

/// A group-id XML input: `.sha256`, `.xml` (written back), `.group_ids.tsv`,
/// `.json` and `.json.xml` (JSON read back, XML written).
fn emitGroupIdXml(gpa: Allocator, io: Io, dir: Io.Dir, stem: []const u8, bytes: []const u8) !void {
    var arena_state: std.heap.ArenaAllocator = .init(gpa);
    defer arena_state.deinit();
    const a = arena_state.allocator();
    const h = yorc.hash.sha256Hex(bytes);
    try put(io, dir, try fileName(a, stem, ".sha256"), try std.fmt.allocPrint(a, "{s}\n", .{h[0..]}));
    var doc = yorc.xml.parse(gpa, bytes, .{}, null) catch
        return put(io, dir, try fileName(a, stem, ".xml"), error_text);
    defer doc.deinit();
    try put(io, dir, try fileName(a, stem, ".xml"), yorc.xml.toOwned(a, &doc.root, null) catch error_text);
    var g = try rows.groupIds(gpa, &doc, h[0..]);
    defer g.deinit();
    try put(io, dir, try fileName(a, stem, ".group_ids.tsv"), try extraTsv(a, &g));
    if (doc.root.kind()) |kind| {
        if (yorc.json.toOwned(a, &doc.root, null)) |j| {
            try put(io, dir, try fileName(a, stem, ".json"), j);
            try put(io, dir, try fileName(a, stem, ".json.xml"), jsonToXml(gpa, a, kind, j));
        } else |_| try put(io, dir, try fileName(a, stem, ".json"), error_text);
    }
}

/// The group-id JSON sample: `.group_ids.tsv` only (`source_hash` = SHA-256
/// of the JSON bytes; nothing if it does not read).
fn emitGroupIdJson(gpa: Allocator, io: Io, dir: Io.Dir, stem: []const u8, bytes: []const u8) !void {
    var arena_state: std.heap.ArenaAllocator = .init(gpa);
    defer arena_state.deinit();
    const a = arena_state.allocator();
    var doc = yorc.json.parse(gpa, "group-id-record", bytes, null) catch return;
    defer doc.deinit();
    const h = yorc.hash.sha256Hex(bytes);
    var g = try rows.groupIds(gpa, &doc, h[0..]);
    defer g.deinit();
    try put(io, dir, try fileName(a, stem, ".group_ids.tsv"), try extraTsv(a, &g));
}

/// One changes pair: `<name>.changes.tsv`; a side that does not read makes
/// the file `error`.
fn emitChanges(gpa: Allocator, io: Io, dir: Io.Dir, name: []const u8, old: ?[]const u8, new: []const u8) !void {
    var arena_state: std.heap.ArenaAllocator = .init(gpa);
    defer arena_state.deinit();
    const a = arena_state.allocator();
    const file = try fileName(a, name, ".changes.tsv");
    var old_doc: ?yorc.Document = null;
    defer if (old_doc) |*d| d.deinit();
    if (old) |bytes| {
        old_doc = yorc.xml.parse(gpa, bytes, .{}, null) catch return put(io, dir, file, error_text);
    }
    var new_doc = yorc.xml.parse(gpa, new, .{}, null) catch return put(io, dir, file, error_text);
    defer new_doc.deinit();
    var c = try rows.changes(gpa, if (old_doc) |*d| d else null, &new_doc);
    defer c.deinit();
    try put(io, dir, file, try changesTsv(a, c.items));
}

/// Document kind of an ORCID JSON sample, from its file name (the table of
/// yorc-rs's tests/json_roundtrip.rs); null to skip the file.
fn jsonSampleKind(name: []const u8) ?[]const u8 {
    const kinds = [_]struct { []const u8, []const u8 }{
        .{ "record-full", "record" },
        .{ "address", "address" },
        .{ "bulk-", "bulk" },
        .{ "distinction", "distinction" },
        .{ "education", "education" },
        .{ "employment", "employment" },
        .{ "external-identifier", "external-identifier" },
        .{ "funding", "funding" },
        .{ "invited-position", "invited-position" },
        .{ "keywords", "keyword" },
        .{ "membership", "membership" },
        .{ "other-names", "other-name" },
        .{ "peer-review-group-id", "" },
        .{ "peer-review", "peer-review" },
        .{ "qualification", "qualification" },
        .{ "research-resource", "research-resource" },
        .{ "researcher-url", "researcher-url" },
        .{ "service", "service" },
        .{ "work", "work" },
    };
    for (kinds) |k| {
        if (std.mem.startsWith(u8, name, k[0])) return if (k[1].len == 0) null else k[1];
    }
    return null;
}

fn openOut(io: Io, path: []const u8) !Io.Dir {
    try Io.Dir.cwd().createDirPath(io, path);
    return Io.Dir.cwd().openDir(io, path, .{});
}

fn emit(gpa: Allocator, io: Io, args: Args, out_path: []const u8) !void {
    var arena_state: std.heap.ArenaAllocator = .init(gpa);
    defer arena_state.deinit();
    const a = arena_state.allocator();
    const out = try openOut(io, out_path);
    defer out.close(io);

    {
        var buf: Io.Writer.Allocating = .init(a);
        const o = &buf.writer;
        for (try genIds(a, n_ids)) |s| {
            if (yorc.id.normalize(s)) |c| {
                try o.print("{s}\t{s}\n", .{ s, c[0..] });
            } else try o.print("{s}\t-\n", .{s});
        }
        try put(io, out, "ids.tsv", buf.written());
    }

    {
        const d = try openOut(io, try std.fs.path.join(a, &.{ out_path, "fixture" }));
        defer d.close(io);
        const bytes = try readFile(io, a, try std.fs.path.join(a, &.{ args.root, fixture_rel }));
        try emitXmlDoc(gpa, io, d, stemOf(std.fs.path.basename(fixture_rel)), bytes);
    }

    for ([_][]const u8{ "read_samples", "write_samples" }) |set| {
        const src = try std.fs.path.join(a, &.{ args.root, samples_rel, set });
        const d = try openOut(io, try std.fs.path.join(a, &.{ out_path, set }));
        defer d.close(io);
        for (try listFiles(io, a, src, ".xml")) |name| {
            const bytes = try readFile(io, gpa, try std.fs.path.join(a, &.{ src, name }));
            defer gpa.free(bytes);
            try emitXmlDoc(gpa, io, d, stemOf(name), bytes);
        }
        const j = try openOut(io, try std.fs.path.join(a, &.{ out_path, "json_samples", set }));
        defer j.close(io);
        for (try listFiles(io, a, src, ".json")) |name| {
            const kind = jsonSampleKind(name) orelse continue;
            const bytes = try readFile(io, gpa, try std.fs.path.join(a, &.{ src, name }));
            defer gpa.free(bytes);
            try emitJsonDoc(gpa, io, j, stemOf(name), bytes, kind);
        }
    }

    {
        const j = try openOut(io, try std.fs.path.join(a, &.{ out_path, "json_samples", "write_samples" }));
        defer j.close(io);
        const bytes = try readFile(io, a, try std.fs.path.join(a, &.{ args.root, group_id_json_rel }));
        try emitGroupIdJson(gpa, io, j, stemOf(std.fs.path.basename(group_id_json_rel)), bytes);
        const d = try openOut(io, try std.fs.path.join(a, &.{ out_path, "group_id" }));
        defer d.close(io);
        for (group_id_xml_rel) |rel| {
            const x = try readFile(io, a, try std.fs.path.join(a, &.{ args.root, rel }));
            try emitGroupIdXml(gpa, io, d, stemOf(std.fs.path.basename(rel)), x);
        }
    }

    {
        const d = try openOut(io, try std.fs.path.join(a, &.{ out_path, "changes" }));
        defer d.close(io);
        const old = try readFile(io, a, try std.fs.path.join(a, &.{ args.root, changes_old_rel }));
        const new = try readFile(io, a, try std.fs.path.join(a, &.{ args.root, changes_new_rel }));
        const fixture = try readFile(io, a, try std.fs.path.join(a, &.{ args.root, fixture_rel }));
        const edited = try editedFixture(a, fixture);
        try emitChanges(gpa, io, d, "old_new", old, new);
        try emitChanges(gpa, io, d, "new_old", new, old);
        try emitChanges(gpa, io, d, "none_new", null, new);
        try emitChanges(gpa, io, d, "fixture_edited", fixture, edited);
    }

    {
        const d = try openOut(io, try std.fs.path.join(a, &.{ out_path, "dump" }));
        defer d.close(io);
        const path = try dumpPath(a, args);
        const fa = yorc.dump.FileArchive.open(gpa, io, path) catch |err| {
            std.debug.print("orcid-libs-bench: {s}: {t}\n", .{ path, err });
            return err;
        };
        defer fa.deinit();
        var buf: Io.Writer.Allocating = .init(gpa);
        defer buf.deinit();
        const o = &buf.writer;
        while (try fa.archive.nextXml()) |m| {
            const stem = yorc.dump.xmlEntryStem(m.name).?;
            const bytes = try fa.archive.read(m, max_member);
            const h = yorc.hash.sha256Hex(bytes);
            if (yorc.xml.parse(gpa, bytes, .{}, null)) |parsed| {
                var doc = parsed;
                defer doc.deinit();
                var t = try rows.Tables.fromDocument(gpa, &doc, h[0..]);
                defer t.deinit();
                var n: usize = 0;
                for (rows.Section.all) |s| n += t.count(s);
                try o.print("{s}\t{s}\t{s}\t{d}\n", .{ stem, h[0..], doc.orcid() orelse "-", n });
            } else |_| try o.print("{s}\t{s}\terror\t-\n", .{ stem, h[0..] });
        }
        try put(io, d, "members.tsv", buf.written());

        var sample = try sampleDump(gpa, io, path, sample_n, sample_seed);
        defer freeSample(gpa, &sample);
        var sb: Io.Writer.Allocating = .init(a);
        try sb.writer.print("# sample\tn={d}\tseed={d}\tseen={d}\n", .{ sample_n, sample_seed, sample.seen });
        for (sample.slice()) |stem| try sb.writer.print("{s}\n", .{stem});
        try put(io, d, "sample.tsv", sb.written());
    }
    std.debug.print(impl ++ ": wrote {s}\n", .{out_path});
}
