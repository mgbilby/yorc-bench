# yorc-bench results

`./run.sh` writes two files per run here. They are gitignored by
default, so a run stays local until you decide to keep it.

The published runs are committed here, both files of each run, so that
anyone can check [RESULTS.md](../RESULTS.md) against the raw lines and
re-run the same commands. `../run.sh --duckdb --java --populate` publishes
a run when it is done; `../populate.sh <run>.jsonl` publishes one after the
fact. It commits both files, rewrites RESULTS.md and pushes; it refuses a
partial or failed run, or one made on other code (`../populate.sh -h`).
Once added, the files stay tracked.

| file | what |
|---|---|
| `<YYYY-MM-DD>-<HHMMSS>.jsonl` | One JSON line per workload, per program, per repetition, exactly as the programs print them: `{"impl","workload","iterations","bytes","total_ns","ns_per_op","mb_per_s"}`. The file name carries no host name; the notes record the host. |
| `<YYYY-MM-DD>-<HHMMSS>.txt` | The run's notes: date, host, CPU, `rustc`, `zig` (and `java`, `duckdb`) versions, the last commits of `yorc-rs/`, `yorc-zig/` (and `yorc-duckdb/`), build flags, arguments, the cross-check results and `BENCH_LABEL`. The summary table is appended at the end. |

Re-summarise a file with:

```sh
python3 -I summarize.py results/2026-10-19-153000.jsonl
python3 -I summarize.py results/2026-10-19-153000.jsonl --markdown
```

For each (implementation, workload), `ns_per_op` is the median over the
repetitions, computed from `total_ns / iterations`. `Zig/Rust` is the
ratio of the two medians. Below 1, Zig is faster.
