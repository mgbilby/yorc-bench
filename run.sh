#!/usr/bin/env bash
# Build, cross-check and benchmark yorc-rs (Rust) against yorc-zig (Zig),
# and optionally against ORCID's own Java orcid-model (--java) and
# yorc-duckdb (--duckdb).
#
#   run.sh [-k REPS] [--iters N] [--dump-iters N] [--warmup N] [--only W,W]
#          [--dump PATH] [--cpu native|baseline] [--no-zig-own] [-o RESULTS.jsonl]
#          [--no-build] [--no-check] [--build-only] [--duckdb] [--java]
#          [--populate [--no-push]]
#
#   -k REPS        runs of each program (default 5); they alternate which goes first
#   --iters N      iterations of every workload but dump_stream (default: per workload)
#   --dump-iters N iterations of dump_stream (default 20; use 1-3 for a large archive)
#   --warmup N     untimed iterations before each workload (default 2; dump_stream: at most 1)
#   --only W,W     only these workloads (names: see README.md): id_normalize,
#                  xml_read_record, xml_write_record, json_write_record,
#                  json_read_record, rows_record, sha256, dump_stream,
#                  group_ids_read, timeline_record, changes_record, dump_sample
#   --dump PATH    .tar.gz for dump_stream and the cross-check
#                  [yorc-zig/testdata/dump/orcid_test_summaries.tgz]
#   --cpu MODE     native (default): Rust gets -C target-cpu=native, Zig its
#                  default native target; baseline: neither
#   --no-zig-own   only the headline Zig build. By default the Zig program is built
#                  twice: linked with libc (malloc, the Rust program's allocator;
#                  impl "zig", the headline comparison) and with Zig's own default
#                  allocator (impl "zig-own", reported next to it). --libc is
#                  accepted and ignored.
#   --no-build     use the binaries already built
#   --no-check     skip the cross-check (compare.sh)
#   --build-only   build both programs and stop
#   --duckdb       also run the three-way cross-check with yorc-duckdb
#                  (compare.sh; needs `make release` in yorc-duckdb first),
#                  and benchmark yorc-duckdb (duckdb/bench.py: the duckdb CLI,
#                  one thread, the same inputs and workload names where SQL
#                  has a counterpart; xml_write_record and json_write_record
#                  are n/a) in the alternating runs. Its iD list and fixture
#                  JSON come from one untimed `orcid-libs-bench --emit`.
#                  Reported in the notes; it does not change the exit status.
#                  The gate stays the two-way check (compare.sh --only rust,zig).
#   --java         also build (mvn -q package) and benchmark ORCID's Java
#                  yorc-rs (java), in the alternating runs, and
#                  run the cross-check with java (compare.sh --only rust,zig[,duckdb],java).
#                  Reported in the notes; it does not change the exit status.
#                  Java runs with JAVA_OPTS (below); its timing excludes JVM
#                  startup, and each workload first warms up for --warmup N runs
#                  and at least 3 s (the program's --warmup-ms) for the JIT.
#   --populate     publish the run when it is done (implies --duckdb --java):
#                  populate.sh commits results/<run>.jsonl and .txt, rewrites
#                  RESULTS.md and pushes to yorc-bench. It works in a clone of
#                  yorc-bench and refuses a partial or failed run (populate.sh -h).
#   --no-push      with --populate: commit, but do not push
#
# Environment: ZIG (default: zig on PATH; Zig 0.18.0-dev.131+41f885830 exactly;
# an optional site.sh next to this script may set it), CARGO (default: cargo),
# DUCKDB (default: yorc-duckdb/build/release/duckdb), MVN (default: mvn),
# JAVA (default: java, JDK 21), JAVA_OPTS (default: -Xms2g -Xmx2g
# -XX:+UseParallelGC -XX:+AlwaysPreTouch -XX:-UsePerfData -Duser.timezone=UTC
# -Dfile.encoding=UTF-8: a fixed 2 GiB heap, touched at startup, and the
# throughput (parallel) collector).
# Exit status: 0, or 1 if the cross-check found differences (the benchmarks
# still run), 2 on a setup or build error.
set -uo pipefail

here=$(cd "$(dirname "$0")" && pwd)
# The inputs are read below $root: the nearest directory, from here up, that
# holds yorc-rs/ and yorc-zig/ (the checkout of these scripts, or one above it).
root=$here
until [[ -f $root/yorc-rs/Cargo.toml && -f $root/yorc-zig/build.zig.zon ]]; do
  [[ $root == / ]] && { echo "no yorc-rs/ and yorc-zig/ in $here or above (git submodule update --init --recursive?)" >&2; exit 2; }
  root=$(dirname "$root")
done
reps=5
iters=""; dump_iters=""; warmup=""; only=""; dump=""; cpu=native; zig_own=1
out=""; build=1; check=1; build_only=0; duckdb=0; java=0; populate=0; push=1
while [[ $# -gt 0 ]]; do
  case $1 in
    -k) reps=$2; shift 2 ;;
    --iters) iters=$2; shift 2 ;;
    --dump-iters) dump_iters=$2; shift 2 ;;
    --warmup) warmup=$2; shift 2 ;;
    --only) only=$2; shift 2 ;;
    --dump) dump=$(cd "$(dirname "$2")" && pwd)/$(basename "$2"); shift 2 ;;
    --cpu) cpu=$2; shift 2 ;;
    --libc) shift ;;  # kept for old command lines: Zig links libc by default now
    --no-zig-own) zig_own=0; shift ;;
    -o) out=$2; shift 2 ;;
    --no-build) build=0; shift ;;
    --no-check) check=0; shift ;;
    --build-only) build_only=1; shift ;;
    --duckdb) duckdb=1; shift ;;
    --java) java=1; shift ;;
    --populate) populate=1; duckdb=1; java=1; shift ;;
    --no-push) push=0; shift ;;
    -h|--help) sed -n '2,62p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ $cpu == native || $cpu == baseline ]] || { echo "--cpu: native or baseline" >&2; exit 2; }
if [[ $populate -eq 1 ]]; then
  # populate.sh checks the rest; fail early on what would make it refuse the run
  [[ -z $only && $check -eq 1 && $build_only -eq 0 && $reps -ge 3 ]] ||
    { echo "--populate needs a full, checked run: no --only, --no-check or --build-only, -k 3 or more" >&2; exit 2; }
fi

CARGO=${CARGO:-cargo}
# Settings of this checkout, if it has any (site.sh, next to this script, may
# set ZIG and ZIG_HINT; the published repository has none).
# shellcheck source=/dev/null
[[ -f $here/site.sh ]] && . "$here/site.sh"
ZIG_VERSION=0.18.0-dev.131+41f885830  # minimum_zig_version of yorc-zig and zig/build.zig.zon
ZIG=${ZIG:-zig}
RUST_BENCH=$here/rust/target/release/orcid-libs-bench
ZIG_BENCH=$here/zig/zig-out/bin/orcid-libs-bench
ZIG_OWN_BENCH=$here/zig/zig-out-own/bin/orcid-libs-bench
JAVA_JAR=$here/java/target/orcid-libs-bench-java.jar
# The Java baseline is JDK 21 (java/FINDINGS.md). When JAVA_HOME is unset, use
# Ubuntu's JDK 21 if it is installed, so that Maven (which runs on JAVA_HOME or
# the default java, possibly a newer JRE) and the timed runs both use it.
if [[ -z ${JAVA_HOME:-} && -x /usr/lib/jvm/java-21-openjdk-amd64/bin/javac ]]; then
  export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
fi
DUCKDB=${DUCKDB:-$root/yorc-duckdb/build/release/duckdb}
MVN=${MVN:-mvn}
JAVA=${JAVA:-${JAVA_HOME:+$JAVA_HOME/bin/}java}
JAVA_OPTS=${JAVA_OPTS:--Xms2g -Xmx2g -XX:+UseParallelGC -XX:+AlwaysPreTouch -XX:-UsePerfData -Duser.timezone=UTC -Dfile.encoding=UTF-8}
export RUST_BENCH ZIG_BENCH JAVA_JAR JAVA

if [[ $build -eq 1 ]]; then
  command -v "$ZIG" >/dev/null || {
    echo "no Zig at '$ZIG': put Zig $ZIG_VERSION on PATH or set ZIG${ZIG_HINT:+ ($ZIG_HINT)}" >&2; exit 2; }
  zig_found=$("$ZIG" version 2>/dev/null)
  [[ $zig_found == "$ZIG_VERSION" ]] || echo "warning: $ZIG is Zig '$zig_found', not $ZIG_VERSION" >&2
  # Same dependency versions as yorc-rs's own tests: seed the lock file
  # from yorc-rs's; cargo adds this package to it.
  [[ -f $here/rust/Cargo.lock ]] || cp "$root/yorc-rs/Cargo.lock" "$here/rust/Cargo.lock"
  rustflags=${RUSTFLAGS:-}
  [[ $cpu == native ]] && rustflags="$rustflags -C target-cpu=native"
  echo "== cargo build --release (RUSTFLAGS='${rustflags# }')" >&2
  (cd "$here/rust" && RUSTFLAGS="${rustflags# }" "$CARGO" build --release) || exit 2
  zig_args=(-Doptimize=ReleaseFast)
  [[ $cpu == baseline ]] && zig_args+=(-Dcpu=baseline)
  echo "== $ZIG build ${zig_args[*]} -Dlibc=true" >&2
  (cd "$here/zig" && "$ZIG" build "${zig_args[@]}" -Dlibc=true) || exit 2
  if [[ $zig_own -eq 1 ]]; then
    echo "== $ZIG build ${zig_args[*]} -p zig-out-own (Zig's own allocator)" >&2
    (cd "$here/zig" && "$ZIG" build "${zig_args[@]}" -p zig-out-own) || exit 2
  fi
  if [[ $java -eq 1 ]]; then
    echo "== $MVN -q -f java/pom.xml package" >&2
    "$MVN" -q -f "$here/java/pom.xml" package || exit 2
  fi
fi
[[ $build_only -eq 1 ]] && exit 0
zig_bins=("$ZIG_BENCH"); [[ $zig_own -eq 1 ]] && zig_bins+=("$ZIG_OWN_BENCH")
for b in "$RUST_BENCH" "${zig_bins[@]}"; do
  [[ -x $b ]] || { echo "missing binary: $b (run without --no-build)" >&2; exit 2; }
done
if [[ $java -eq 1 && ! -f $JAVA_JAR ]]; then
  echo "missing jar: $JAVA_JAR (run without --no-build)" >&2; exit 2
fi
if [[ $duckdb -eq 1 && ! -x $DUCKDB ]]; then
  echo "missing duckdb CLI: $DUCKDB (run \`make release\` in yorc-duckdb, or set DUCKDB)" >&2; exit 2
fi

# The harness commit, and whether its tree (results/ aside) differs from it:
# populate.sh publishes only a run made on a clean, committed tree.
bench_at=unknown
if bench_head=$(git -C "$here" rev-parse --short=12 HEAD 2>/dev/null); then
  if [[ -z $(git -C "$here" status --porcelain --untracked-files=no --ignore-submodules=all -- . ':(exclude)results' ':(exclude)RESULTS.md') ]]; then
    bench_at="$bench_head clean"
  else
    bench_at="$bench_head modified"
  fi
fi

status=0
check_result="skipped"
cargs=()
[[ -n $dump ]] && cargs=(--dump "$dump")
if [[ $check -eq 1 ]]; then
  echo "== cross-check" >&2
  if "$here/compare.sh" --only rust,zig "${cargs[@]}"; then
    check_result="identical"
  else
    rc=$?
    [[ $rc -eq 2 ]] && exit 2
    check_result="DIFFERENCES (see compare.sh output)"
    status=1
    echo "cross-check found differences; benchmarking anyway" >&2
  fi
fi
three_way="not run (--duckdb)"
java_check="not run (--java)"
if [[ $duckdb -eq 1 || $java -eq 1 ]]; then
  impls=rust,zig
  [[ $duckdb -eq 1 ]] && impls+=,duckdb
  [[ $java -eq 1 ]] && impls+=,java
  echo "== cross-check over $impls" >&2
  if "$here/compare.sh" --only "$impls" "${cargs[@]}"; then
    ext="no differences"
  else
    rc=$?
    if [[ $rc -eq 2 ]]; then ext="setup error (see above)"; else ext="differences (see compare.sh output)"; fi
  fi
  [[ $duckdb -eq 1 ]] && three_way="$ext (compare.sh --only $impls)"
  [[ $java -eq 1 ]] && java_check="$ext (compare.sh --only $impls)"
fi

mkdir -p "$here/results"
if [[ -z $out ]]; then
  # date and time only: no host name in file names (the notes record the host)
  out=$here/results/$(date +%F-%H%M%S).jsonl
fi
notes=${out%.jsonl}.txt
: >"$out"

bargs=(--root "$root")
[[ -n $iters ]] && bargs+=(--iters "$iters")
[[ -n $dump_iters ]] && bargs+=(--dump-iters "$dump_iters")
[[ -n $warmup ]] && bargs+=(--warmup "$warmup")
[[ -n $only ]] && bargs+=(--only "$only")
[[ -n $dump ]] && bargs+=(--dump "$dump")

{
  echo "date:        $(date -u +%FT%TZ)"
  echo "host:        ($(uname -srm))"
  if [[ -r /proc/cpuinfo ]]; then
    echo "cpu:         $(grep -m1 'model name' /proc/cpuinfo | sed 's/.*: //') ($(nproc) threads)"
  else
    echo "cpu:         $(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo unknown)"
  fi
  echo "rustc:       $(rustc -V 2>/dev/null || echo unknown)"
  echo "zig:         $("$ZIG" version 2>/dev/null || echo unknown)"
  if [[ $java -eq 1 ]]; then
    echo "java:        $("$JAVA" -version 2>&1 | grep -v '^Picked up' | head -1)"
    echo "java opts:   $JAVA_OPTS"
    echo "java model:  org.orcid:orcid-model:4.0.2 (Jackson 2.15.4, jaxb-runtime 3.0.2; java/pom.xml)"
  fi
  # The last commit of each package (a submodule's HEAD, or the last commit touching its directory).
  echo "yorc-rs:     $(git -C "$root/yorc-rs" log -1 --format='%h %cs' -- . 2>/dev/null || echo unknown)"
  echo "yorc-zig:    $(git -C "$root/yorc-zig" log -1 --format='%h %cs' -- . 2>/dev/null || echo unknown)"
  echo "yorc-duckdb: $(git -C "$root/yorc-duckdb" log -1 --format='%h %cs' -- . 2>/dev/null || echo unknown)"
  echo "yorc-bench:  $bench_at"
  echo "build:       cpu=$cpu zig=libc malloc (headline), zig-own=$zig_own (rust: release, lto=fat, codegen-units=1; zig: ReleaseFast)"
  if [[ $duckdb -eq 1 ]]; then
    echo "duckdb:      $("$DUCKDB" --version 2>/dev/null | head -n 1) (${DUCKDB/$HOME/\$HOME}; yorc-duckdb $(git -C "$root/yorc-duckdb" log -1 --format='%h %cs' -- . 2>/dev/null || echo unknown))"
  fi
  echo "args:        -k $reps ${bargs[*]/$HOME/\$HOME}"
  echo "cross-check: $check_result"
  echo "three-way:   $three_way"
  echo "java check:  $java_check"
  echo "label:       ${BENCH_LABEL:-}"
} >"$notes"

if [[ $duckdb -eq 1 ]]; then
  # The DuckDB leg's inputs that SQL cannot make: the iD list (ids.tsv) and the
  # fixture's JSON, from one untimed run of the Rust program's --emit.
  duckdb_emit=$(mktemp -d "${TMPDIR:-/tmp}/orcid-libs-duckdb-emit.XXXXXX")
  trap 'rm -rf "$duckdb_emit"' EXIT
  "$RUST_BENCH" --emit "$duckdb_emit" --root "$root" >/dev/null || { echo "rust --emit failed (duckdb inputs)" >&2; exit 2; }
fi

for ((r = 1; r <= reps; r++)); do
  # Rotate which program goes first: rust zig [java] [duckdb], then the next first, ...
  all=(rust zig)
  [[ $zig_own -eq 1 ]] && all+=(zig-own)
  [[ $java -eq 1 ]] && all+=(java)
  [[ $duckdb -eq 1 ]] && all+=(duckdb)
  s=$(( (r - 1) % ${#all[@]} ))
  order=("${all[@]:s}" "${all[@]:0:s}")
  for impl in "${order[@]}"; do
    echo "== rep $r/$reps: $impl" >&2
    if [[ $impl == duckdb ]]; then
      python3 -I "$here/duckdb/bench.py" --duckdb "$DUCKDB" --rust-emit "$duckdb_emit" "${bargs[@]}" >>"$out" \
        || { echo "duckdb failed (rep $r)" >&2; exit 2; }
      continue
    fi
    if [[ $impl == java ]]; then
      # shellcheck disable=SC2086 # JAVA_OPTS is a list of JVM flags
      "$JAVA" $JAVA_OPTS -jar "$JAVA_JAR" "${bargs[@]}" >>"$out" || { echo "java failed (rep $r)" >&2; exit 2; }
      continue
    fi
    bin=RUST_BENCH; [[ $impl == zig ]] && bin=ZIG_BENCH; [[ $impl == zig-own ]] && bin=ZIG_OWN_BENCH
    "${!bin}" "${bargs[@]}" >>"$out" || { echo "$impl failed (rep $r)" >&2; exit 2; }
  done
done

echo >&2
echo "raw results: $out" >&2
echo "notes:       $notes" >&2
echo
python3 -I "$here/summarize.py" "$out" | tee -a "$notes"
echo "cross-check: $check_result"
[[ $java -eq 1 ]] && echo "java check:  $java_check"
if [[ $populate -eq 1 ]]; then
  [[ $status -eq 0 ]] || { echo "not published: the cross-check found differences" >&2; exit "$status"; }
  pargs=(); [[ $push -eq 0 ]] && pargs+=(--no-push)
  "$here/populate.sh" "${pargs[@]}" "$out" || exit 1
fi
exit $status
