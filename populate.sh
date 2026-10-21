#!/usr/bin/env bash
# Publish a benchmark run to the yorc-bench repository: commit its raw lines
# and notes (results/<run>.jsonl, .txt), regenerate RESULTS.md (the latest
# run's table and the list of every published run) and push.
#
#   ./populate.sh [--no-push] results/<run>.jsonl
#   ./run.sh --duckdb --java --populate [--no-push]   # the same, after a run
#
#   --no-push   commit, but leave the push to you (git push)
#
# It works in a clone of yorc-bench only, and refuses a run that cannot back
# published numbers:
#   - a partial run (--only), fewer than 3 repetitions, or a run without the
#     Java and DuckDB legs;
#   - a cross-check that found differences, or was skipped;
#   - a run made on code other than this commit: the notes must name this
#     yorc-bench commit with a clean tree, and the submodule commits checked
#     out now, unmodified;
#   - a clone that is behind its upstream branch (pull first), and an
#     author identity that is a coding agent's.
# Commits use your git identity and signing settings (user.name, user.email,
# commit.gpgsign). The host name is not published; the CPU, OS and
# BENCH_LABEL are.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
die() { echo "populate: $*" >&2; exit 1; }

push=1; run=""
while [[ $# -gt 0 ]]; do
  case $1 in
    --no-push) push=0; shift ;;
    -h|--help) sed -n '2,23p' "$0"; exit 0 ;;
    -*) die "unknown option $1" ;;
    *) [[ -z $run ]] || die "one run at a time"; run=$1; shift ;;
  esac
done
[[ -n $run ]] || die "usage: ./populate.sh [--no-push] results/<run>.jsonl"
[[ -f $run ]] || die "no such file: $run"
run=$(cd "$(dirname "$run")" && pwd)/$(basename "$run")
notes=${run%.jsonl}.txt
[[ $run == "$here/results/"*.jsonl ]] || die "the run must be in $here/results/"
[[ -f $notes ]] || die "no notes file next to it: $notes"
name=$(basename "$run" .jsonl)

g() { git -C "$here" "$@"; }

# ---- the repository
[[ $(g rev-parse --show-toplevel 2>/dev/null) == "$here" ]] ||
  die "$here is not the root of a git clone (populate works in a clone of yorc-bench)"
for s in yorc-rs yorc-zig yorc-duckdb; do
  [[ $(g config -f .gitmodules --get "submodule.$s.path" 2>/dev/null) == "$s" ]] ||
    die "no $s submodule: populate works in a clone of yorc-bench"
done
origin=$(g remote get-url origin 2>/dev/null) || die "no remote 'origin'"
[[ $origin =~ yorc-bench(\.git)?/?$ ]] || die "origin is $origin, not yorc-bench"
branch=$(g symbolic-ref --short -q HEAD) || die "detached HEAD: check out a branch"

name_a=$(g config user.name || true); email_a=$(g config user.email || true)
[[ -n $name_a && -n $email_a ]] || die "set git user.name and user.email"
if [[ "$name_a $email_a" =~ [Cc]laude|[Aa]nthropic ]]; then
  die "git identity '$name_a <$email_a>' is a coding agent's; publish under your own"
fi

# ---- the run's notes (run.sh writes "key: value" lines)
field() { sed -n "s/^$1: *//p" "$notes" | head -n 1; }
args=$(field args)
[[ $args != *--only* ]] || die "a partial run (--only) is not published"
reps=$(sed -n 's/^-k \([0-9][0-9]*\).*/\1/p' <<<"$args")
[[ -n $reps && $reps -ge 3 ]] || die "at least 3 repetitions (-k 3) are needed; the notes say: $args"
for impl in rust zig java duckdb; do
  grep -q "\"impl\":\"$impl\"" "$run" || die "the run has no $impl lines (run with --duckdb --java)"
done
[[ $(field cross-check) == identical ]] || die "cross-check: $(field cross-check)"
three_way_v=$(field three-way)
[[ $three_way_v == "no differences"* || ( $(field 'java check') == "differences"* && $(field cross-check) == identical ) ]] || die "four-way check: $three_way_v"

head_now=$(g rev-parse --short=12 HEAD)
bench_at=$(field yorc-bench)
[[ $bench_at == "$head_now clean" ]] ||
  die "the run was made at yorc-bench '$bench_at'; this clone is at $head_now (re-run here)"
dirty=$(g status --porcelain --untracked-files=no --ignore-submodules=all -- . ':(exclude)results' ':(exclude)RESULTS.md')
[[ -z $dirty ]] || die "uncommitted changes in the harness:"$'\n'"$dirty"
while read -r line; do
  case $line in
    [-+U]*) die "submodule not at the pinned commit (git submodule update --init --recursive): $line" ;;
  esac
done < <(g submodule status)
for s in yorc-rs yorc-zig yorc-duckdb; do
  [[ -z $(git -C "$here/$s" status --porcelain --untracked-files=no) ]] ||
    die "$s has uncommitted changes: the numbers would not match its commit"
  at=$(field "$s" | cut -d' ' -f1)
  sha=$(git -C "$here/$s" rev-parse HEAD)
  [[ -n $at && $sha == "$at"* ]] || die "the run measured $s at '$at'; it is at ${sha:0:12} now (re-run)"
done

upstream=$(g rev-parse --abbrev-ref -q '@{upstream}' 2>/dev/null || true)
if [[ -n $upstream ]]; then
  g fetch -q "${upstream%%/*}" || die "git fetch failed"
  g merge-base --is-ancestor "$upstream" HEAD || die "$branch is behind $upstream: git pull --ff-only, then re-run the benchmark"
fi

# ---- RESULTS.md
os=$(field host | sed -n 's/.*(\(.*\))$/\1/p')
summary=$(python3 -I "$here/summarize.py" "$run" --markdown)
tmp=$(mktemp); trap 'rm -f "$tmp"' EXIT
{
  echo "# Published results"
  echo
  echo "<!-- Written by populate.sh from results/; edits here are overwritten. -->"
  echo
  echo "The latest published run is \`$name\`: raw lines in"
  echo "[results/$name.jsonl](results/$name.jsonl), notes in"
  echo "[results/$name.txt](results/$name.txt). To check the table, run"
  echo "\`python3 -I summarize.py results/$name.jsonl --markdown\`; to reproduce it,"
  echo "check out the commit that added the run and follow [README.md](README.md)."
  echo
  echo "| | |"
  echo "|---|---|"
  echo "| date | $(field date) |"
  echo "| machine | $(field label) |"
  echo "| CPU | $(field cpu) |"
  echo "| OS | $os |"
  echo "| rustc | $(field rustc) |"
  echo "| zig | $(field zig) |"
  echo "| java | $(field java) |"
  echo "| duckdb | $(field duckdb | sed 's/ (.*//') |"
  echo "| yorc-bench | \`${head_now}\` |"
  for s in yorc-rs yorc-zig yorc-duckdb; do
    echo "| $s | \`$(git -C "$here/$s" rev-parse --short=12 HEAD)\` |"
  done
  echo "| arguments | \`run.sh $(field args | sed 's/ *--root [^ ]*//; s/  */ /g; s/ *$//')\` |"
  echo "| cross-checks | Rust/Zig: $(field cross-check); four-way: $(field three-way | sed 's/ (.*//') |"
  echo
  echo "$summary"
  echo
  echo "## Every published run"
  echo
  echo "| run | date | machine | CPU |"
  echo "|---|---|---|---|"
  # the runs committed so far, and this one; newest first
  { g ls-files 'results/*.jsonl'; echo "results/$name.jsonl"; } | sort -u -r | while read -r f; do
    n=${f%.jsonl}.txt
    [[ -f $here/$n ]] || continue
    d=$(sed -n 's/^date: *//p' "$here/$n" | head -n 1)
    l=$(sed -n 's/^label: *//p' "$here/$n" | head -n 1)
    c=$(sed -n 's/^cpu: *//p' "$here/$n" | head -n 1)
    echo "| [$(basename "$f" .jsonl)]($f) | $d | $l | $c |"
  done
} >"$tmp"
cp "$tmp" "$here/RESULTS.md"

# ---- commit and push
g add -f "results/$name.jsonl" "results/$name.txt" RESULTS.md
if g diff --cached --quiet; then
  echo "populate: $name is already published; nothing to commit" >&2
else
  g commit -q -m "results: $name" -m "$(field label)
$(field cpu)
Measured at yorc-bench $head_now; four-way check: $(field three-way | sed 's/ (.*//')."
  echo "populate: committed $(g rev-parse --short HEAD) (results: $name)" >&2
fi
if [[ $push -eq 1 ]]; then
  g push -q origin "$branch" || die "push failed; fix it and run: git -C $here push origin $branch"
  echo "populate: pushed to $origin ($branch)" >&2
else
  echo "populate: not pushed (--no-push); run: git -C $here push origin $branch" >&2
fi
