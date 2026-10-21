# yorc-rs, yorc-zig and yorc-duckdb: feature parity

This page is for choosing between the ORCID v3.0 implementations of the yorc family:

- **yorc-rs**: the Rust crate ([yorc-rs](https://github.com/mgbilby/yorc-rs), `yorc-rs/` here; crate `yorc-rs`, imported as `yorc`, version 0.1.0).
- **yorc-zig**: the Zig library ([yorc-zig](https://github.com/mgbilby/yorc-zig), `yorc-zig/` here; modules `yorc` and `yorc_client`, version 0.1.0).
- **yorc-duckdb**: the DuckDB extension ([yorc-duckdb](https://github.com/mgbilby/yorc-duckdb), `yorc-duckdb/` here; C++17, version 0.1.0, DuckDB v1.5.6). It reads ORCID documents into SQL tables and writes item documents from rows. It is not a library with an object model: compare it by what it reads and writes.

The baseline is ORCID's own Java library, in the "ORCID orcid-model (Java)" column:

- **ORCID orcid-model (Java)**: `org.orcid:orcid-model:4.0.2` (github.com/ORCID/orcid-model at commit 9592e2d, the commit the vendored XSDs come from). These are the JAXB classes of the v3.0 message schema, with XML through JAXB and JSON through Jackson as ORCID's servers configure them. It is a data model and nothing else: no iD utility, no rows, no dump reader, no client, no OAuth, and no validation beyond the XSDs it ships. It is driven from `java/` (README.md, "Java baseline"); [java/FINDINGS.md](java/FINDINGS.md) lists what it shows for the three.

The comparison works area by area. For the item-by-item API mapping
(`snake_case` to `camelCase`, `Result` to error unions, which function
corresponds to which), see
[yorc-zig's PARITY.md](https://github.com/mgbilby/yorc-zig/blob/main/PARITY.md). This page does not repeat
it.

Status (the "status" column compares the two libraries; the DuckDB and Java
columns describe the counterparts and their own differences, and
[CROSSCHECK.md](CROSSCHECK.md) lists every rule that differs among the three
new implementations):

- **same**: same capability and the same observable behaviour on the same input.
- **adapted**: same capability, with a shape that differs; the notes say how.
- **gap**: one side lacks it; the notes say which side.

The "verified by" column says what checks the claim:

- **cc:** followed by a path is the [cross-check](README.md#cross-check-comparesh) (`compare.sh --only rust,zig`). It requires the two output files to be byte-identical.
- **cc3:** followed by a class is the [three-way cross-check](README.md#three-way-cross-check-comparesh-with-yorc-duckdb) (`compare.sh`), in the DuckDB column.
- **cc3j:** followed by a class is the Java table of the cross-check (`compare.sh --only rust,zig,duckdb,java`; README.md, "Java baseline"), in the Java column. Claims in the Java column without it come from reading ORCID's sources (yorc-rs at 9592e2d, ORCID-Source) and from running the Java program's `--emit` on the fixtures.
- **tests** means each library's own test suite only (each tests against the same ORCID samples, but neither is run against the other).
- **docs** means the claim comes from reading the code and documentation only.

The cross-check passed on 2026-10-17: every output is byte-identical (see "Status of the checks" below).

## At a glance

ORCID's Java library first, as the baseline. ✓ supported, – not provided.
The detailed table under "Comparison" below gives the API names and what
checks each claim.

| feature | ORCID orcid-model (Java) | yorc-rs (Rust) | yorc-zig (Zig) | yorc-duckdb (DuckDB CE) | benchmark workload |
|---|:---:|:---:|:---:|:---:|---|
| ORCID iD check and normalisation | – | ✓ | ✓ | ✓ `orcid_valid`, `orcid_normalize` | `id_normalize` |
| v3.0 object model (every record XSD element) | ✓ JAXB classes | ✓ | ✓ | – (rows and STRUCTs, no object model) | – |
| XML read | ✓ JAXB | ✓ | ✓ | ✓ | `xml_read_record` |
| XML write | ✓ JAXB | ✓ | ✓ same bytes as Rust | ✓ same bytes as Rust in crosswalk mode | `xml_write_record` (DuckDB: n/a, no record writer) |
| JSON read (ORCID's JSON) | ✓ Jackson | ✓ | ✓ | ✓ | `json_read_record` |
| JSON write | ✓ Jackson | ✓ | ✓ same bytes as Rust | ✓ same bytes as Rust in crosswalk mode | `json_write_record` (DuckDB: n/a, no record writer) |
| our JSON readable by ORCID's library | n/a | ✓ 74/75 since CROSSCHECK #16 (69/75 before; the 75th is Java's own XSD check of an empty `journal-title`) | ✓ the same | expected ✓ for its 21 written write samples (checked since 2026-10-18; to run) | – |
| flat row tables | – | ✓ 14 sections, 300 columns | ✓ the same | ✓ the same 14, plus 5 DuckDB-only | `rows_record` |
| SHA-256 `source_hash` per document | – (JDK `MessageDigest`) | ✓ | ✓ | ✓ | `sha256` |
| Public Data File dumps (tar / tar.gz) read in place | – | ✓ | ✓ (concatenated gzip members, `Archive.gzip_members`) | ✓ (`.tar`, `.tar.gz`, `.tgz`; concatenated gzip members) | `dump_stream` |
| reproducible reservoir sample | – | ✓ | ✓ same picks as Rust | ✓ same picks as Rust: `orcid_dump_sample` (2026-10-18) | `dump_sample` |
| record timeline | – | ✓ (2026-10-18) | ✓ (2026-10-18) | ✓ `orcid_timeline` | `timeline_record` |
| snapshot diff | – | ✓ (2026-10-18) | ✓ (2026-10-18) | ✓ `orcid_changes` | `changes_record` |
| group-id records | ✓ `GroupIdRecord` | ✓ (2026-10-18) | ✓ (2026-10-18) | ✓ `orcid_group_ids` | `group_ids_read` |
| XSD validation | ✓ ships the XSDs | tests only (xmllint) | – | – | – |
| ORCID Public API read client (`pub.orcid.org` only; no Member API, no Sandbox) | – | ✓ | ✓ | – (offline by design) | – (network-bound) |
| OAuth | – | optional 2-legged `/read-public` token only | the same | – | – |
| neighbourly limits (45 s per orcid.org request, host allowlist) | – | ✓ | ✓ | n/a | – |
| ORCID Member API or Sandbox access, payload validation | – (XSD only) | – (out of scope) | – (out of scope) | – (out of scope) | – |
| runtime dependencies | JAXB, Jackson, Jakarta APIs | feature-gated crates | Zig standard library only | none (C++17) | – |
| licence | ORCID MIT-style | MIT | MIT | MIT | – |
| speed vs Java (geometric mean of time ratios, 7 workloads, 2026-10-19; Rust and Zig on malloc) | 1.00 | 0.67 | 0.46 (0.58 on Zig's own allocator, 2026-10-18) | DuckDB leg re-run 2026-10-19 for sha256, dump_stream, dump_sample and xml_read_record (the first run overstated some workloads); the full run is pending | all of the above |

Access to the ORCID Member API and the ORCID Sandbox is out of scope for the
public packages: yorc-rs and yorc-zig read ORCID's Public API only, and
yorc-duckdb makes no requests to ORCID.

## Comparison

| area | yorc-rs (Rust) | yorc-zig (Zig) | yorc-duckdb (DuckDB) | ORCID orcid-model (Java) | status | verified by | notes |
|---|---|---|---|---|---|---|---|
| iD | `id::normalize` → `Option<String>`, `is_valid`, `check_char`, `OrcidId` (`parse`, `FromStr`, `Display`, `uri`) | `id.normalize` → `?[19]u8` (no allocation), `isValid`, `checkChar`, `OrcidId` (`parse`, `{f}`, `uri` → `[37]u8`) | `orcid_valid`, `orcid_normalize` (SQL scalars). The libraries copy its rules. | None: the model jar has no iD utility. `OrcidIdentifier` / `OrcidIdBase` hold `uri`, `path`, `host`, and `getPath()` falls back to the end of `uri`. No check character, no normalisation. `id_normalize` is n/a. | same | cc: `ids.tsv`; tests | Same rules as yorc-duckdb's `orcid_normalize`: leading whitespace, the `https://`, `http://` and `orcid.org/` prefixes, hyphens and spaces ignored, lowercase `x`. Zig's parse error has no payload. |
| model coverage | Every data-bearing element and attribute of the v3.0 record XSDs; the summary and full forms; bulk, error, search and expanded search. Vocabularies are `#[non_exhaustive]` enums with `Other(String)`. | The same types and fields, in `snake_case`. Vocabularies are `Vocab(E)` (`.known` / `.other`). Adds `model.eql` / `firstDifference` in place of `PartialEq` / `Debug`. | No object model: 18 section tables over 32 XSDs (106 of 109 data-bearing names, docs/COVERAGE.md), including `record-summary`, notifications and group-id records, which neither library models. Unmapped: `approval-date`, `locale`, `@transient`. | JAXB classes `org.orcid.jaxb.model.v3.release.*`: record, activities and their summaries, person, bulk, error, search and expanded search, group-id records, notifications (permission, custom, amended), client summary. The jar also has the 1.2, 2.0 and 2.1 models. No class for `summary_3.0` (`record-summary`), although the XSD ships. Vocabularies are Java enums. No field for `history/@visibility` or a work's `country/@visibility`. | same (adapted shape) | tests (`schema_coverage.rs` / `schema_test.zig`, the same `xsd_uncovered.txt`) | Rust: match `Root`, `BulkItem`, `Cell`, `Section`, ... with a `_ =>` arm. Zig: unions are exhaustive, so a new variant breaks the build. |
| XML read | quick-xml 0.42. Lenient: unknown elements skipped, namespaces matched by local name. | Its own pull scanner over std. Same leniency; checks UTF-8 and XML characters; nesting limit (`Options.max_depth`, 256). | Its own reader (`src/core/xml.cpp`). Items are matched by element-path suffix anywhere, not only where the XSDs put them; nothing inside the pre-3.0 `group/summary` peer-review layout is read (2026-10-18; FINDINGS #3), as in Rust, Zig and Java. A malformed attribute fails the parse (as in Zig). UTF-8 is not checked on read (CROSSCHECK.md #3). cc3: rows. | JAXB (jaxb-runtime 3.0.2), one context per root class. Unknown elements are skipped, as is the pre-3.0 `peer-review:summary` layout. String text is kept verbatim, not trimmed; typed values (dates, integers) are. An enum value that does not match exactly, white space included, is dropped without an error. A schema-validating unmarshal is optional (ORCID's API uses it for payloads). cc3j: J rows via XML. | same reads; adapted parser | cc: `*/*.xml`, `*.rows.tsv`, `dump/members.tsv`; tests | **Gap (Zig):** a malformed attribute (missing `=` or quote) fails the whole parse with `MalformedXml`, where quick-xml skips the attribute. **Gap (Rust):** no configurable nesting limit. |
| XML write | `xml::to_string`, `document_to_string`. ORCID's prefixes; XSD sequence order. | `xml.write` / `toOwned`. Since 2026-10-18 one pass like yorc-rs's: one pre-sized buffer, namespaces as a bit set inserted after the root's name, one `@Vector` escape-and-check scan, no `std.fmt`; `write(*Writer)` adds a discarding dry run for the namespaces. | Item documents only, from a STRUCT of reader columns: `orcid_<w>_to_xml` (work, funding, affiliation, peer_review, research_resource, person_item, group_id), `orcid_bulk_works_to_xml`. By default tab indentation, the same namespace and attribute order. **Crosswalk mode** (`SET orcid_crosswalk = true` or a trailing `true` argument; off by default; CROSSCHECK #5, 2026-10-18) writes exactly yorc-rs's document bytes: two-space indentation, the rest already equal (`src/core/crosswalk.cpp`). Read-only fields (source, dates, path, display index, normalized ids) are never written; every research-resource host of the `hosts` lists. The bench writes in crosswalk mode. cc3: written XML bytes, written XML semantic. | `Marshaller` with `JAXB_FORMATTED_OUTPUT`, as ORCID's API: `standalone="yes"`, all 28 namespaces of the package on the root, four-space indent. Writes any object; no validation on write. cc3j: J written XML bytes (info), J rows via XML. | same bytes | cc: `*/<stem>.xml`, `*.json.xml`, `json_samples/*/*.xml`; tests | Both promise exact, deterministic output. Rust's tests also validate every written document with xmllint against the XSDs; **gap (Zig):** no XSD validation in its tests. Both keep their previous writer as a test oracle and require the same bytes or the same error on samples, the record and injected values (yorc-rs `tests/reference_writer`, yorc-zig `tests/xml_write_legacy.zig`). |
| JSON read / write | serde_json. `json::from_str` / `from_slice` / `from_value`, `to_string`, `to_value`, `kind_of`. | `std.json`. `json.parse`, `fromValue` (`std.json.Value`), `write` / `toOwned`, `Root.kind()`. | Its own parser. Reads infer the document element (`json_root` is needed for an affiliation without `path` and for `{"content"}`); `{"value": ms}` in `*-date` members become ISO text. Writes item documents, timestamps never: by default in XSD key order; in crosswalk mode (as XML) exactly yorc-rs's bytes, with sorted keys, `{"external-id": []}` for an empty always-written container, DEL unescaped (serde_json) and put-code as an i64. cc3: json-read rows, written JSON bytes, written JSON semantic. | Jackson 2.15.4 with the Jakarta XML Bind introspector, configured as ORCID's `JacksonXmlBindJsonProvider`: `propOrder` keys, `null` members, timestamps as epoch milliseconds (read back in UTC), `ACCEPT_SINGLE_VALUE_AS_ARRAY`. Unknown keys fail the read. Reading needs the target class (no kind function). cc3j: J rows via JSON, J json-read rows, J reads written JSON (Rust, Zig, and since 2026-10-18 DuckDB's written write samples). | same bytes; adapted value type | cc: `*/<stem>.json`, `json_samples/*/*.json`; tests | Sorted keys, serde's pretty layout, no nulls. **Gap (Zig):** no `to_value`. Non-integer JSON numbers: Zig keeps the source text, while serde may reformat them as `f64`. |
| validation | removed 2026-10-18 (Member API access is out of scope for the public packages) | removed 2026-10-18 (the same) | removed 2026-10-18 (`orcid_validate_*`; the writers still check what the XSD structure needs) | XSD only (ORCID's own check, `xsd.txt`; not compared) | - | - | - |
| rows | `rows::Tables` (14 sections, 300 columns), `Cell`, `Section::ALL`, `section_rows`, `take`. | `rows.Tables` (`fromDocument`, `fromXml`, `get`, `count`, `cell`), `Section.all`. | The reference: the 14 tables are yorc-duckdb's (`src/core/sections.cpp`), the same 300 columns. More of its own: `timeline`, `summary`, `summary_items`, `notifications`, `group_ids` (`search_results` and `errors` are among the 14). `group_ids`, `timeline` and `orcid_changes` are the reference for the Rust and Zig additions of 2026-10-18. cc3: rows (`columns.tsv`); group_ids rows, timeline rows, changes rows (byte for byte; missing R / Z until the programs write them). | None. `rows_record` is n/a. | same | cc: `*.rows.tsv`, `dump/members.tsv`; tests (`samples.rs` / `rows_test.zig`) | yorc-duckdb's table layout. Zig has `Tables.take` and `rows.sectionRows` since 2026-10-18. |
| timeline and snapshot diff | `rows::Extra::Timeline` / `rows::timeline` (13 columns) and `rows::changes` → `Change` (9 columns, `CHANGE_COLUMNS`, `DIFF_SECTIONS`) (2026-10-18). | `rows.timeline` and `rows.changes` → `Changes` (2026-10-18). | The reference: `orcid_timeline`, `orcid_changes`. | None. | adapted | cc3: timeline, changes (to be run) | Values are compared as model values (padded dates, integers), DuckDB compares document text: `01` vs `1` can differ (CROSSCHECK). |
| group-id records | `model::GroupIdRecord` / `GroupIdRecords`, `Root::GroupIdRecord(s)`, XML and JSON read/write; `rows::group_ids` (12 columns) (2026-10-18). | The same: `model.GroupIdRecord`, `rows.groupIds` (2026-10-18). | The reference: `orcid_group_ids`. | `GroupIdRecord` (JSON via Jackson in the bench). | same | cc3: group_ids (to be run) | |
| hash | `hash::sha256_hex` → `String` (sha2). | `hash.sha256Hex` → `[64]u8` (std.crypto). | `source_hash` column (its own SHA-256) on every row. cc3: rows. | None. The benchmark uses the JDK's `MessageDigest`. cc3j: J sha256. | same | cc: `*.sha256`, `dump/members.tsv` |  |
| dump streaming | `dump::open` (flate2 `MultiGzDecoder` + tar), `dump::records` → `DumpRecord` (path, stem, bytes, `orcid()`, `parse()`), `read_entry`, `xml_entry_stem`, `is_dump_path`. | `dump.FileArchive.open` / `openAt`, `Archive.init` over any `*std.Io.Reader`; `next`, `nextXml`, `read(member, limit)`; `xmlEntryStem`, `isDumpPath`. Concatenated gzip members are read (a fresh `std.compress.flate.Decompress` per member, `Archive.gzip_members`; since 2026-10-18). | `orcid_<section>(archive)` and `orcid_documents`: `.tar`, `.tar.gz`, `.tgz`, globs, `https://`/`s3://` (httpfs). Options `members`, `max_records`, `max_member_bytes` (64 MiB). Concatenated gzip members are read (DuckDB's gzip file system; pinned since 2026-10-18 by a two-member fixture in `orcid_dumps.test`). Parsing runs in parallel. One malformed member fails the scan. cc3: rows (`dump/members.tsv`), dump member rows. | None in the jar (ORCID publishes the dumps). The benchmark uses `GZIPInputStream`, which reads concatenated members, and a minimal tar reader of its own. cc3j: J dump member rows, J members. | adapted | cc: `dump/members.tsv` (member order, bytes, iD, row count) | Zig has no `records`-style iterator: loop over `nextXml` and `read`. The `read` buffer is reused, and its slice is valid until the next call. Concatenated gzip members: Rust, Zig and DuckDB read them, as does the Java benchmark's `GZIPInputStream` (Zig since 2026-10-18, CROSSCHECK.md #6; input after a member that is not gzip fails in Rust and Zig). ORCID's dumps and yorc's corpus are single-member. |
| reservoir sampler | `dump::reservoir`: `SplitMix64`, `Reservoir` (Algorithm R), `Slot`. | `reservoir.SplitMix64`, `Reservoir(T)`, `Slot`. | `orcid_dump_sample(archive, n, seed)` (2026-10-18): the same SplitMix64, `below` and Algorithm R (`src/core/reservoir.cpp`), the walkthroughs' eligibility rule (a regular `.xml` member whose stem is a valid iD), rows in slot order; kept members read only if `xml` is selected. (SQL's own `USING SAMPLE reservoir(n) REPEATABLE (seed)` samples rows, with different picks.) | None. | same picks | tests (the same contract vectors in all three; DuckDB's `orcid_dump_sample.test`: seed 42 on the dump fixture picks 0000-0003-0100-6634, as both walkthroughs) | Benchmarked as `dump_sample`; not in the cross-check. CROSSCHECK #17. |
| Public API client | `blocking::Client` over ureq 3 + rustls, `pub.orcid.org` only (`Access::Public`; `Custom` for mock servers). `record`, `record_raw`, `person`, `works`, `work`, `works_bulk`, `section`; **`search`, `expanded_search`** (one page, up to 1,000 rows). XML reads. Per-call `token: Option<&Token>` (`/read-public` only). `Custom` refuses ORCID's hosts. 60 s request timeout. | `yorc_client.Client` over `std.http.Client` (std TLS), `pub.orcid.org` only (`.public`; `.custom` for mock servers). The same reads, as XML **or JSON** (`Format`), returning a `Document`. One token per client (`Config.token`). | None by design: no network code (README.md, Scope). With httpfs, files and dumps are read over `https://`. | None. The jar depends on httpclient5 and `jakarta.ws.rs-api`, but has no client code. ORCID-Source is the server side. | adapted; gap | tests (`blocking_client.rs` / `client_test.zig`, mock servers) | **Gap (Zig):** no `search` or `expanded_search` (yorc-zig/PARITY.md says neither library has search, which is now out of date); no request timeout setting; no automatic proxy (call `initDefaultProxies` yourself). **Gap (Rust):** no JSON reads. Neither library follows redirects; 301 and 409 are answers. Not benchmarked: both are network-bound. |
| OAuth (optional `/read-public` token) | `read_public_token` (2-legged `client_credentials`, scope `/read-public`), `encode_component`; `Token` with `is_expired` and a redacting `Debug`. No sign-in (3-legged) OAuth, no member-scoped tokens. | `readPublicToken`, `encodeComponent`; `Token` (`expires_in`, `bearer`). The same: no sign-in OAuth, no member-scoped tokens. | None by design. | None. `ScopePathType` (`org.orcid.jaxb.model.message`) lists the scopes. | same; small gap | tests | **Gap (Zig):** no `is_expired`; record the time of issue yourself. Neither library refreshes or revokes tokens. |
| rate limiting / retries | One process-wide `RateLimiter::orcid()` for ORCID's hosts (the Public API and the token endpoint): one request every 45 s, one at a time, the token call and retries included; a faster limiter is clamped, only `Custom` (mock servers) may go faster. GET retried on 5xx and transport errors, at most 3 attempts; POST never; a 429 is not retried and pauses the limiter for `Retry-After`. | The same: one process-wide ORCID limiter (`RateLimiter.global()`, 45 s, serialised), the same retry rules. | None (no client). | None. | same | tests; docs | The same cap on both sides: one request per 45 s to ORCID's hosts (not Public Data File downloads). |
| errors / diagnostics | One `Error` enum with payloads: `Xml { message, position }`, `Utf8 { valid_up_to }`, `Unwritable { path, reason }`, `Json { message }`. `ClientError` for the client. | Error sets without payload, plus an optional `*Diagnostic` (position, message, element path, code point) filled before returning. `client.Failure` (status, body, error-3.0 document, transport or OAuth error). | DuckDB exceptions whose text names the input and the field: `orcid: malformed XML in <file or row>: <reason>`, `orcid_work_to_xml: work: 'title' is required (common:title)`. | `OrcidError` models the error-3.0 document. Failures are `JAXBException` (XML), Jackson's `JsonProcessingException` (JSON), and `SAXParseException` messages (XSD). | adapted | docs | The error *kinds* agree, but the message texts do not. The cross-check therefore records only `error` for a failure, never the message. |
| fuzzing | No fuzz targets in the current tree. yorc-zig/PARITY.md refers to a `fuzz/` (cargo-fuzz) directory that does not exist at 7aa7f3b. | `tests/fuzz_test.zig`: the XML reader plus write-back, the iD normaliser, and the JSON reader for every kind (`zig build test --fuzz`). | `make fuzz`: libFuzzer targets over the core (`test/fuzz/`). | None (JUnit tests). | gap (Rust) | docs |  |
| toolchain | Rust **1.87** (MSRV), edition 2024, stable. | Zig **0.18.0-dev.131+41f885830** exactly (a development snapshot; `minimum_zig_version`). yorc-bench's `run.sh` takes it from `PATH` or `ZIG`. | C++17; built and tested against DuckDB v1.5.6 (it also compiles against the v2.0 pre-release). | Java **21** (enforcer: `requireJavaVersion` 21, Maven 3.6.3). | adapted | docs | A move to the next stable Zig is planned. |
| dependencies | Feature-gated: `quick-xml` (xml), `sha2` (hash), `flate2` + `tar` (dump), `serde_json` (json, blocking), `ureq` with rustls (blocking). Default features: `id`, `model`, `xml`. `#![forbid(unsafe_code)]`. | None beyond the Zig standard library: no C and no TLS library of its own. Two modules: `orcid` (no network code) and `yorc_client`. | None beyond DuckDB: its own XML reader, JSON parser, tar reader and SHA-256. | Compile scope: jakarta.xml.bind-api 3.0.1, jaxb-runtime 3.0.2, Jackson 2.15.4 (core, databind, annotations; dataformat-csv 2.5.1), swagger 2.1.1, commons-lang3, commons-io, commons-collections4, jettison, httpclient5, jakarta.ws.rs-api, jakarta.annotation-api, guava. The shaded benchmark jar is about 15 MB. | adapted | docs |  |
| licence | MIT. NOTICE covers ORCID's schemas and samples (MIT-style) and the CC0 record. | MIT. The same NOTICE terms. | MIT. NOTICE covers the fixture record and ORCID's schemas. | ORCID MIT-style licence (MIT, plus a clause on ORCID's name and marks). Copyright ORCID, Inc. | same | docs | All three say they are independent and not affiliated with, endorsed by or sponsored by ORCID, Inc., and that they do not provide access to the ORCID Sandbox or the ORCID Member API. |
| packaging / publishing | crates.io `yorc-rs` and github.com/mgbilby/yorc-rs. `include` keeps tests and `reference/` out of the crate; docs.rs builds with all features. See yorc-rs's README. | No registry: `zig fetch --save git+https://github.com/mgbilby/yorc-zig#v0.1.0`; `.paths` keeps `testdata/` and `tests/` out of the package. See yorc-zig's README. | A DuckDB community extension (`INSTALL yorc FROM community`); see yorc-duckdb's README. | Maven Central `org.orcid:orcid-model` (4.0.2 matches the vendored XSDs: commit 9592e2d). ORCID-Source pins the same version. | adapted | docs | The benchmark and parity harness is published too: [yorc-bench](https://github.com/mgbilby/yorc-bench). |

None of the three provides access to the ORCID Member API or the ORCID
Sandbox (out of scope for the public packages), payload validation, consent
or retention policy, or an async client.
yorc-duckdb's `orcid_changes` (field-level differences between two
snapshots), `orcid_timeline` and `orcid_group_ids` are getting library
counterparts in yorc-rs and yorc-zig with the same columns (2026-10-18, to
be built); the three-way check compares them (CROSSCHECK.md, "Bench files
for group ids, timeline and changes").

## Status of the checks

| check | state |
|---|---|
| Cross-check (`compare.sh`): the record, 53 read and 21 write samples, the JSON samples, 10,000 iDs, the dump fixture | **Passed** 2026-10-17 (development tree `a927012`, maintainer's machine): `cross-check: identical`. |
| Cross-check on the 10,000-record corpus | **Passed** 2026-10-17 (`compare.sh --dump PATH` on the 10,000-record sample of the ORCID Public Data File used on the maintainer's machine, not distributed; two-way, now `compare.sh --only rust,zig --dump PATH`): `452 identical, 0 differing, 0 only from Rust, 0 only from Zig`. |
| Three-way cross-check (`compare.sh`: Rust, Zig, yorc-duckdb) | **Run** 2026-10-18 (maintainer's machine). Written XML / JSON: 84/84 byte-identical (crosswalk mode). Rows 74/76, JSON-read rows 168/177: the peer-review leniency (FINDINGS #3, since fixed in yorc-duckdb), and two JSON reading differences since fixed (CROSSCHECK #14, #15). Dump rows: `.tgz` not opened, since fixed (71f6b0a). New classes since: group_ids rows, timeline rows, changes rows. The fixes were built; the four-way check below ran on them. |
| Four-way cross-check (`compare.sh --only rust,zig,duckdb,java`) | **Passed** 2026-10-18 (a later run than the two rows above, maintainer's machine): Rust, Zig and yorc-duckdb identical in every compared class (yorc-duckdb's writers in crosswalk mode). ORCID's Java library, the reference reader, read 74 of the 75 JSON documents the others wrote; the 75th is its own XSD check rejecting the empty `journal-title` of read sample `work-3.0.xml`, which yorc reads as absent. 2026-10-19 (`run.sh --duckdb --java`): Rust and Zig identical (597 files), Java 74 of 75 again. |
| Static three-way review | [CROSSCHECK.md](CROSSCHECK.md) (2026-10-18, by reading the code). |
| Java baseline (`compare.sh --only rust,zig,duckdb,java`) | **Run** 2026-10-18 (JDK 21.0.12). Rows 71/75 for Rust and Zig: the 4 are history `visibility`, which ORCID's classes do not model (FINDINGS #4). Java accepts all 42 written documents; it read 69/75 written JSON until history `visibility` was left out of JSON (CROSSCHECK #16); 74/75 in the four-way check above. "J reads written JSON" now also covers DuckDB's 21 written write samples (to run). |

Any differing file in a later two-way run is a bug in one library:
byte-identical output is the intended contract of both. yorc-duckdb keeps
its own layout by default; in crosswalk mode (`SET orcid_crosswalk = true`,
which the bench uses) its written documents share that contract: the same
bytes as yorc-rs's document writers. Its other differences in the
three-way check are findings to weigh against CROSSCHECK.md.

## Benchmarks

Measured 2026-10-18 on the maintainer's machine, `run.sh --java`:
Rust release + fat LTO, Zig ReleaseFast, both `target-cpu=native`, each with
its own allocator; Java ORCID orcid-model 4.0.2 on JDK 21.0.12, steady state
after JIT warm-up. Median of 5 alternating runs. A/B is A's time over B's
(below 1: A is faster); the average is the geometric mean of the column.

| workload | Java ns/op | Rust ns/op | Zig ns/op | Rust/Java | Zig/Java | Zig/Rust |
|---|---:|---:|---:|---:|---:|---:|
| id_normalize | - | 771,477 | 437,704 | - | - | 0.57 |
| xml_read_record | 13,209,334 | 5,832,896 | 4,410,628 | 0.44 | 0.33 | 0.76 |
| xml_write_record | 5,359,538 | 639,028 | 990,721 | 0.12 | 0.18 | 1.55 |
| json_write_record | 4,289,978 | 4,968,867 | 4,146,077 | 1.16 | 0.97 | 0.83 |
| json_read_record | 4,066,491 | 5,472,152 | 2,272,739 | 1.35 | 0.56 | 0.42 |
| rows_record | - | 1,160,007 | 461,379 | - | - | 0.40 |
| sha256 | 3,176,906 | 4,104,680 | 4,003,242 | 1.29 | 1.26 | 0.98 |
| dump_stream (fixture) | 15,827,852 | 6,920,270 | 5,994,862 | 0.44 | 0.38 | 0.87 |
| **average** | | | | **0.60** | **0.50** | **0.73** |

Where each leads: Java beats both only at SHA-256 (the JDK's intrinsic), and
beats Rust at JSON reading and writing; Rust writes XML fastest; Zig leads everything
else. The clearest targets: Rust's JSON reading (slower than both) and Zig's
XML writing (1.55x Rust's time; the allocator is the first suspect, see
README.md caveats). The Java corpus run stopped at the corpus's first error
document; fixed in 5e69ae1, to re-run.

**Since then:** four workloads were appended after the eight above
(`group_ids_read`, `timeline_record`, `changes_record`, `dump_sample`; Java
has `group_ids_read`), and a DuckDB leg (`run.sh --duckdb`,
`duckdb/bench.py`): yorc-duckdb timed in its duckdb CLI on the same inputs,
which gives the table a DuckDB column and the ratios DuckDB/Java and
DuckDB/Rust. DuckDB's times include SQL execution, and its workloads are the
closest SQL counterparts (README.md, "DuckDB leg"); it has no record writer,
so `xml_write_record` and `json_write_record` are n/a for it. The current
tables (2026-10-19: all twelve workloads, Rust and Zig on the same
allocator) are in the BENCHMARKS.md of
[yorc-rs](https://github.com/mgbilby/yorc-rs/blob/main/BENCHMARKS.md),
[yorc-zig](https://github.com/mgbilby/yorc-zig/blob/main/BENCHMARKS.md) and
[yorc-duckdb](https://github.com/mgbilby/yorc-duckdb/blob/main/BENCHMARKS.md),
which name the run in `results/` each comes from (README.md, "Published
numbers").

### Earlier runs


Measured 2026-10-17 on the maintainer's machine, development tree `a927012`,
default `run.sh` build: Rust release + fat LTO, Zig ReleaseFast, both
`target-cpu=native`, each with its own allocator (glibc malloc / Zig
`smp_allocator`). Median of 5 alternating runs (corpus: 3). Raw lines:
the `results/` files of those runs on that machine (not committed).
Zig/Rust below 1 means Zig is faster.

| workload | Rust ns/op | Zig ns/op | Zig/Rust |
|---|---:|---:|---:|
| id_normalize | 710,338 | 490,583 | 0.69 |
| xml_read_record | 5,606,319 | 4,395,009 | 0.78 |
| xml_write_record | 6,932,347 | 2,222,357 | 0.32 |
| json_write_record | 4,924,132 | 4,175,170 | 0.85 |
| json_read_record | 5,366,319 | 7,107,342 | 1.32 |
| validate_work_payloads (workload removed 2026-10-18) | 12,503 | 10,879 | 0.87 |
| rows_record | 1,072,191 | 1,385,860 | 1.29 |
| sha256 | 4,096,271 | 3,984,357 | 0.97 |
| dump_stream (fixture) | 6,877,156 | 5,957,248 | 0.87 |
| dump_stream (corpus) | 2,375,295,938 | 1,760,543,095 | 0.74 |

In MB/s: XML read 236 vs 301, XML write 160 vs 499, JSON write 231 vs 272,
JSON read 212 vs 160, rows 1,235 vs 956, corpus dump stream (449.7 MB of
XML, 10,000 members, parsed) 189 vs 255.

**Update, development tree `991c148` (2026-10-17, same machine and build):** yorc-rs's
one-pass writer brought `xml_write_record` from 6,932,347 to 603,720 ns
(1,835 MB/s; Zig/Rust 3.68, so Rust now leads by 3.7x), with the
cross-check still identical (452 files, fixtures and corpus). xml_read_record
(5.69 ms vs Zig 4.42) and dump_stream (7.32 vs 6.02 ms) were unchanged within
noise. The table above is the first run, kept for comparison.

Where each was ahead in the first run: Zig on XML writing (about 3x: yorc-rs's writer is
the clearest place to optimise), iD normalisation, XML reading and dump
streaming; Rust on JSON reading (serde_json is about 1.3x faster than
yorc-zig's std.json path) and on rows. Validation and SHA-256 are close.

All workloads are single-threaded. Read the caveats in README.md
(allocators, ReleaseFast vs release + LTO, CPU target, cache) before drawing
conclusions.
