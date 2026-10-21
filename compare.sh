#!/usr/bin/env bash
# Correctness cross-check of yorc-rs, yorc-zig and yorc-duckdb (README.md).
#
#   compare.sh [--only IMPLS] [--dump PATH] [--keep DIR] [--diff N] [--diff-lines L]
#
# Three-way (the default, --only rust,zig,duckdb): runs the Rust and Zig bench
# programs in --emit mode and duckdb/emit.py (yorc-duckdb's CLI)
# on the same inputs (the real-record fixture, every ORCID read/write sample
# in XML and JSON, every member of a dump), re-reads what each one wrote with yorc-rs
# (orcid-libs-bench --reread), and prints, per artefact class (rows, dump
# member rows, json-read rows, written XML/JSON bytes, written XML/JSON
# semantic, rust/zig only), how many entries are identical in all
# three, which two agree, all differ, or are missing (duckdb/compare3.py).
#
# Two-way (--only rust,zig): the original check. Both programs' --emit trees
# must be byte-identical file by file: any differing file is a bug in one of
# them (or in one of the two bench programs).
#
# With java in IMPLS (e.g. --only rust,zig,duckdb,java), ORCID's own Java
# yorc-rs (java, `mvn -q package` first) also runs --emit, and
# a second table compares every implementation with Java, the reference for
# reading: what Java read and wrote, re-read by yorc-rs, against each
# implementation's own read.
#
#   --only IMPLS  rust,zig (two-way), or rust plus any of zig, duckdb, java
#                 (three-way report over those, plus the Java table) [rust,zig,duckdb]
#   --dump PATH   dump to stream [yorc-zig/testdata/dump/orcid_test_summaries.tgz]
#   --keep DIR    write the trees to DIR and keep them [a temp dir, removed]
#   --diff N      two-way: the first N lines of `diff -u` for each differing file;
#                 three-way: N example entries per class, with their diff [0]
#   --diff-lines L  three-way: diff lines per example [30]
#
# Environment: RUST_BENCH, ZIG_BENCH: the two binaries
#   [rust/target/release/orcid-libs-bench, zig/zig-out/bin/orcid-libs-bench]
#   (build them with ./run.sh --build-only, or by hand: see README.md);
#   DUCKDB: yorc-duckdb's CLI [yorc-duckdb/build/release/duckdb] (`make release`
#   in yorc-duckdb); PYTHON [python3]; JAVA [java], JAVA_JAR
#   [java/target/orcid-libs-bench-java.jar], JAVA_EMIT_OPTS
#   [-Duser.timezone=UTC -Dfile.encoding=UTF-8].
# Exit status: 0 all identical (three-way: no compared class has a difference
# or a missing file; the byte classes are informational), 1 differences,
# 2 usage or setup error.
set -uo pipefail

here=$(cd "$(dirname "$0")" && pwd)
# The inputs are read below $root: the nearest directory, from here up, that
# holds yorc-rs/ and yorc-zig/ (the checkout of these scripts, or one above it).
root=$here
until [[ -f $root/yorc-rs/Cargo.toml && -f $root/yorc-zig/build.zig.zon ]]; do
  [[ $root == / ]] && { echo "no yorc-rs/ and yorc-zig/ in $here or above (git submodule update --init --recursive?)" >&2; exit 2; }
  root=$(dirname "$root")
done
dump=""
keep=""
show=0
lines=30
only=rust,zig,duckdb
while [[ $# -gt 0 ]]; do
  case $1 in
    --only) only=$2; shift 2 ;;
    --dump) dump=$2; shift 2 ;;
    --keep) keep=$2; shift 2 ;;
    --diff) show=$2; shift 2 ;;
    --diff-lines) lines=$2; shift 2 ;;
    -h|--help) sed -n '2,43p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

RUST_BENCH=${RUST_BENCH:-$here/rust/target/release/orcid-libs-bench}
ZIG_BENCH=${ZIG_BENCH:-$here/zig/zig-out/bin/orcid-libs-bench}
DUCKDB=${DUCKDB:-$root/yorc-duckdb/build/release/duckdb}
PYTHON=${PYTHON:-python3}
# The Java baseline is JDK 21 (java/FINDINGS.md). When JAVA_HOME is unset, use
# Ubuntu's JDK 21 if it is installed, so that Maven (which runs on JAVA_HOME or
# the default java, possibly a newer JRE) and the timed runs both use it.
if [[ -z ${JAVA_HOME:-} && -x /usr/lib/jvm/java-21-openjdk-amd64/bin/javac ]]; then
  export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
fi
JAVA=${JAVA:-${JAVA_HOME:+$JAVA_HOME/bin/}java}
JAVA_JAR=${JAVA_JAR:-$here/java/target/orcid-libs-bench-java.jar}
JAVA_EMIT_OPTS=${JAVA_EMIT_OPTS:--Duser.timezone=UTC -Dfile.encoding=UTF-8}

use_rust=0; use_zig=0; use_duckdb=0; use_java=0
IFS=, read -r -a picked <<<"$only"
for impl in "${picked[@]}"; do
  case $impl in
    rust) use_rust=1 ;;
    zig) use_zig=1 ;;
    duckdb) use_duckdb=1 ;;
    java) use_java=1 ;;
    *) echo "--only: rust, zig, duckdb or java, not '$impl'" >&2; exit 2 ;;
  esac
done
[[ $use_rust -eq 1 ]] || { echo "--only: rust is required (it re-reads the others' output)" >&2; exit 2; }
two_way=0
[[ $use_zig -eq 1 && $use_duckdb -eq 0 && $use_java -eq 0 ]] && two_way=1

[[ -x $RUST_BENCH ]] || { echo "missing binary: $RUST_BENCH (build with ./run.sh --build-only)" >&2; exit 2; }
if [[ $use_zig -eq 1 && ! -x $ZIG_BENCH ]]; then
  echo "missing binary: $ZIG_BENCH (build with ./run.sh --build-only)" >&2; exit 2
fi
if [[ $use_duckdb -eq 1 && ! -x $DUCKDB ]]; then
  echo "missing duckdb CLI: $DUCKDB (run \`make release\` in yorc-duckdb, or set DUCKDB)" >&2; exit 2
fi
if [[ $use_duckdb -eq 1 ]]; then
  # the extension is built for v1.5.6; a DUCKDB left pointing at another shell (2.0) cannot load it
  duckdb_version=$("$DUCKDB" --version 2>/dev/null | head -n 1)
  if [[ $duckdb_version != *v1.5.6* ]]; then
    echo "DUCKDB=$DUCKDB is \"$duckdb_version\", not v1.5.6: unset DUCKDB to use yorc-duckdb/build/release/duckdb" >&2; exit 2
  fi
fi
if [[ $use_java -eq 1 && ! -f $JAVA_JAR ]]; then
  echo "missing jar: $JAVA_JAR (mvn -q -f java/pom.xml package, or ./run.sh --java --build-only)" >&2; exit 2
fi

if [[ -n $keep ]]; then
  work=$keep
  rm -rf "$work/rust" "$work/zig" "$work/duckdb" "$work/java" "$work/java-reread" \
    "$work/reread-in" "$work/reread-out" "$work/rust.list" "$work/zig.list"
else
  work=$(mktemp -d "${TMPDIR:-/tmp}/orcid-libs-compare.XXXXXX")
  trap 'rm -rf "$work"' EXIT
fi
mkdir -p "$work"
work=$(cd "$work" && pwd)

dump_args=()
dump_abs=""
if [[ -n $dump ]]; then
  dump_abs="$(cd "$(dirname "$dump")" && pwd)/$(basename "$dump")"
  dump_args=(--dump "$dump_abs")
fi

emit() { # impl out-dir [extra args...]
  local impl=$1 out=$2; shift 2
  if [[ $impl == java ]]; then
    # shellcheck disable=SC2086 # JAVA_EMIT_OPTS is a list of JVM flags
    if ! "$JAVA" $JAVA_EMIT_OPTS -jar "$JAVA_JAR" --emit "$out" "$@"; then
      echo "java: --emit failed" >&2
      exit 2
    fi
    return
  fi
  local bin=RUST_BENCH; [[ $impl == zig ]] && bin=ZIG_BENCH
  if ! "${!bin}" --emit "$out" "$@"; then
    echo "$impl: --emit failed" >&2
    exit 2
  fi
}

for impl in rust zig java; do
  [[ $impl == zig && $use_zig -eq 0 ]] && continue
  [[ $impl == java && $use_java -eq 0 ]] && continue
  emit "$impl" "$work/$impl" --root "$root" "${dump_args[@]}"
done

# ------------------------------------------------------------------ two-way
if [[ $two_way -eq 1 ]]; then
  (cd "$work/rust" && find . -type f | sort) >"$work/rust.list"
  (cd "$work/zig" && find . -type f | sort) >"$work/zig.list"

  same=0
  differ=()
  while IFS= read -r f; do
    if cmp -s "$work/rust/$f" "$work/zig/$f"; then
      same=$((same + 1))
    else
      differ+=("${f#./}")
    fi
  done < <(comm -12 "$work/rust.list" "$work/zig.list")
  mapfile -t only_rust < <(comm -23 "$work/rust.list" "$work/zig.list" | sed 's|^\./||')
  mapfile -t only_zig < <(comm -13 "$work/rust.list" "$work/zig.list" | sed 's|^\./||')

  echo "cross-check: $same identical, ${#differ[@]} differing, ${#only_rust[@]} only from Rust, ${#only_zig[@]} only from Zig"
  for f in "${differ[@]}"; do
    echo "  differ:    $f ($(cmp "$work/rust/$f" "$work/zig/$f" 2>&1 | sed 's|^.*differ: ||; s|^cmp: ||'))"
    if [[ $show -gt 0 ]]; then
      diff -u --label "rust/$f" --label "zig/$f" "$work/rust/$f" "$work/zig/$f" | head -n "$show" | sed 's/^/      /'
    fi
  done
  for f in "${only_rust[@]}"; do echo "  only rust: $f"; done
  for f in "${only_zig[@]}"; do echo "  only zig:  $f"; done
  [[ -n $keep ]] && echo "trees kept in $work/rust and $work/zig"

  [[ ${#differ[@]} -eq 0 && ${#only_rust[@]} -eq 0 && ${#only_zig[@]} -eq 0 ]]
  exit
fi

# ---------------------------------------------------------------- three-way
c3=$here/duckdb/compare3.py
default_dump=$root/yorc-zig/testdata/dump/orcid_test_summaries.tgz

if [[ $use_duckdb -eq 1 ]]; then
  dargs=(--emit "$work/duckdb" --root "$root" --duckdb "$DUCKDB" --rust-tree "$work/rust")
  [[ $use_zig -eq 1 ]] && dargs+=(--zig-tree "$work/zig")
  [[ -n $dump_abs ]] && dargs+=(--dump "$dump_abs")
  "$PYTHON" -I "$here/duckdb/emit.py" "${dargs[@]}" || { echo "duckdb: emit.py failed" >&2; exit 2; }
fi

"$PYTHON" -I "$c3" stage "$root" "$work" --dump "${dump_abs:-$default_dump}" || exit 2
if ! "$RUST_BENCH" --reread "$work/reread-in" --emit "$work/reread-out"; then
  echo "rust: --reread failed" >&2
  exit 2
fi
if [[ $use_java -eq 1 ]]; then
  # What would ORCID's own classes (and its XSD check) make of each document?
  # shellcheck disable=SC2086 # JAVA_EMIT_OPTS is a list of JVM flags
  if ! "$JAVA" $JAVA_EMIT_OPTS -jar "$JAVA_JAR" --reread "$work/reread-in" --emit "$work/java-reread"; then
    echo "java: --reread failed" >&2
    exit 2
  fi
fi

"$PYTHON" -I "$c3" report "$root" "$work" --impls "$only" --diff "$show" --diff-lines "$lines"
status=$?
[[ -n $keep ]] && echo "trees kept in $work (rust, zig, duckdb, java, reread-in, reread-out)"
exit $status
