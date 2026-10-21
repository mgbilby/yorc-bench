# yorc-rs, yorc-zig and yorc-duckdb: cross-review

This is a static review of the three ORCID v3.0 implementations of the yorc family.
It is based on reading the code and documentation only; nothing was built or
run to write it. Status notes dated 2026-10-18 mark the items since done in
yorc-rs (#4, #7), in yorc-rs and yorc-duckdb together (#2 in
yorc-rs only, #9, #10), in yorc-duckdb (#1, #3, #5, #8, #12, #14, #15, #17, #18), in yorc-rs and yorc-zig together (#16) and in
yorc-zig (#7, #9, #10, closing "Pending: Zig" after §9). All three have
since been built and tested, and the four-way cross-check has run on them
(PARITY.md, "Status of the checks"); the dated notes below keep their dates.

**2026-10-18, later: Member API write support was removed from all three
packages** (Member API and Sandbox access are out of scope for the public packages): payload validation (yorc-rs `validate`,
yorc-zig `orcid.validate`, yorc-duckdb `orcid_validate_*`), the payload
writers (`payload_to_string`, `payloadToOwned`, `Payload::to_root`),
yorc-duckdb's COPY TO `orcid_xml` / `orcid_json`, and the clients' write
methods. So recommendations #1 and #2 and §7 are historical, the bench's
`validation` and `J XSD validation` classes and the probes are gone, and
"Pending: Zig" item 4 (payloads) no longer applies. The document writers
(`to_string`, `toOwned`, yorc-duckdb's `orcid_<writer>_to_*` and crosswalk
mode) stay. The three implementations are:

- **Rust**: yorc-rs (`yorc-rs/`).
- **Zig**: yorc-zig (`yorc-zig/`).
- **DuckDB**: yorc-duckdb (`yorc-duckdb/`, C++17, DuckDB v1.5.6).

It lists every capability or rule found to differ, says which behaviour
the XSDs (`reference/orcid-model/`) and ORCID's samples support, and
recommends a change and where to make it.

The three-way cross-check (`compare.sh`, README.md) tests many of these
claims on real inputs. A "cc:" in a row names the artefact class that shows
the difference. The classes are listed in README.md, "Three-way cross-check".

Rust and Zig agree byte for byte on everything the two-way check covers
(PARITY.md, 2026-10-17). So in the tables below, Zig is "= Rust" unless a
row says otherwise. Two areas were being edited while this was written:
yorc-zig's JSON reader and rows, and yorc-rs's XML writer. Re-check
those rows against the current code.

## Recommended changes, ranked by user value

"Safe now" means the change is additive or a plain bug fix: no published
behaviour changes for correct input. "Decision" means the maintainer must
choose, because the change alters published output or an API contract.

| # | change | where | why it matters | |
|---|---|---|---|---|
| 1 | Add the XSD rules that DuckDB's writers lack: `maxLength`, the closed vocabularies (work, funding, citation and peer-review types and roles, relationship, contributor sequence and role, visibility), the `orcid-path` / `orcid-uri` / `group-id` / `email` patterns, and the ISO country and currency shape. Do it as a new `orcid_validate_<writer>(rec [, mode])` table or scalar function that returns yorc-rs's violation text (`work/title: required`), so that the writers stay as they are. | DuckDB | Today `orcid_work_to_xml` writes documents that ORCID's API refuses with a 400: an unknown work type, an over-long title, a malformed contributor iD. yorc-rs and yorc-zig catch all of these before sending. cc: validation (the `probe-work-unknown-type`, `-title-1001-chars`, `-bad-contributor-orcid`, `employment-lowercase-country` and `other-name-256-chars` probes). | safe now (a new function); making the writers themselves reject is a decision. **Done in yorc-duckdb**: `orcid_validate_<writer>(rec [, mode])` and `orcid_validate_bulk_works(list [, mode])` (`src/core/validate.cpp`), `VARCHAR[]` in yorc-rs's paths and texts; the writers are unchanged |
| 2 | `payload_to_string` (XML and JSON) writes every read-only field the model holds: `source`, `created-date`, `last-modified-date`, `@path` and `@display-index`. It should omit them, or `validate` should report them in payload mode. | Rust, Zig | A payload built from an item read from a record carries ORCID's own metadata back to ORCID. yorc-duckdb drops these fields by design (REFERENCE.md, "Read-only and derived fields are not written"), and none of ORCID's write samples carries one. ORCID sets them itself. `to_string` / `toOwned` (full documents) should keep writing everything. | decision (changes `payload_to_string` output). **Decided and done in yorc-rs (2026-10-18)**: `xml::payload_to_string` and `json::payload_to_string` write `Payload::to_root()`, which drops the item's `source`, `created-date`, `last-modified-date`, `@path` and `@display-index`, the `external-id-normalized` / `-normalized-error` and item metadata of its external ids, and a work's `country/@visibility` (yorc-duckdb's list); `@put-code` and `@visibility` stay; `to_string` / `document_to_string` unchanged; validation unchanged. **Zig: pending** |
| 3 | The XML readers should check UTF-8 (`invalid UTF-8 at byte n`, as the JSON parser and the writers already do). | DuckDB | Today only the JSON parser (`src/core/json.cpp`) and the writers (`AppendXmlEscaped`, `src/core/xml.cpp`) check UTF-8. The XML reader copies bytes into `VARCHAR` columns unchecked, as far as can be read, so a corrupt member can put invalid UTF-8 into a DuckDB table. yorc-rs fails with `Error::Utf8`; yorc-zig checks UTF-8 in its scanner. | safe now (bug fix). **Done in yorc-duckdb**: `ExtractSection` checks the bytes (one pass, ASCII fast path) and raises `orcid: malformed XML in ...: invalid UTF-8 at byte <n>`; `orcid_documents` refuses such text too; character references to no Unicode character stay literal |
| 4 | Give `dump::records` / `read_entry` an optional member size limit, like DuckDB's `max_member_bytes` (default 64 MiB) and Zig's `Archive.read(member, limit)`. | Rust | `read_entry` reads a member to its end and only caps the *initial capacity* at 64 MiB (`src/dump/mod.rs`). A crafted or corrupt archive (a gzip bomb) can make it allocate without bound. | **done in yorc-rs (2026-10-18)**: `dump::Limits { max_member_bytes }` (default 64 MiB), `records_with`, `read_entry_with`; `records` and `read_entry` apply the default. The header is checked before allocating and the read is capped. |
| 5 | Make the writers byte-compatible. DuckDB would indent with two spaces instead of a tab (XML), and either DuckDB sorts JSON keys or Rust/Zig write them in XSD order. Attribute order (`put-code`, `visibility`), namespace order (alphabetical by prefix: `xml::Ns` order is alphabetical) and the XML declaration already agree. | DuckDB (XML indentation); JSON order: either side | For ORCID's write samples, which have no read-only fields, the only XML byte difference left would then be the indentation. With it gone, all three would be byte-identical, and the cross-check could assert it (cc: written XML bytes, written JSON bytes). | decision (changes published output, and would need DuckDB's own test expectations updated). **Decided and done in yorc-duckdb (2026-10-18)**: yorc-duckdb keeps its own layout by default; a crosswalk switch, off by default, makes every writer emit exactly yorc-rs's `payload_to_string` bytes, the contract yorc-rs and yorc-zig share: `SET orcid_crosswalk = true`, a trailing `BOOLEAN` argument on every writer scalar (`orcid_work_to_xml(rec, true)`; it wins over the setting) and COPY's `CROSSWALK true` option (`src/core/crosswalk.cpp`, a separate emitter over the writers' tree). Besides the indentation it sorts JSON keys, writes `{"external-id": []}` for an empty always-written container (`req_ext_ids`), DEL unescaped (serde_json) and put-code as an i64. Tests: `test/sql/orcid_crosswalk.test` and `core_test.cpp` against bytes derived from yorc-rs's rules for the 21 XML write samples (`test/data/crosswalk/`). The bench's DuckDB leg writes in crosswalk mode, and the written XML / JSON bytes classes are real checks now |
| 6 | Read concatenated gzip members. | Zig | flate2's `MultiGzDecoder` (Rust) and DuckDB's `GZipFileSystem` (concatenated files, `duckdb/src/common/gzip_file_system.cpp`) read every member; yorc-zig stops after the first (yorc-zig/PARITY.md). ORCID ships single-member archives, but `cat a.gz b.gz` and some recompressors do not. cc: rows (`dump/members.tsv`) on such an archive. | safe now |
| 7 | Rows for the API messages the models already parse: `errors` (standalone and per bulk entry, including the locked/deprecated iD fallbacks and `primary_orcid`) and `search_results`, with DuckDB's columns. | Rust, Zig | The models read `Root::Error`, `Search`, `ExpandedSearch` and bulk errors, but `rows` stops at the 11 record sections. DuckDB users get these tables (REFERENCE.md); library users rebuild them by hand. `Section` is `#[non_exhaustive]` and `Section::ALL` is a slice, so adding sections is not a breaking change. | **Rust done (2026-10-18)**: `Section::SearchResults`, `Section::Errors`, 13 sections, 267 columns. **Zig done (2026-10-18)**: `Section.search_results`, `Section.errors`, the same values (yorc-zig's `tests/rows_test.zig`). |
| 8 | The writer for fundings should reject a contributor `sequence` (funding-3.0.xsd's contributor attributes have none) instead of dropping it silently. | DuckDB | `Contributors("funding", false)` in `src/core/writer.cpp` leaves out the `sequence` leaf, while `sequence` stays an accepted field (it is a column of `orcid_contributors`), so a value is lost without an error. yorc-rs reports `TooMany { max: 0 }` and refuses the write (`Error::Unwritable`). | safe now (a missing error). **Done in yorc-duckdb**: the funding writer raises `funding: cannot write 'contributors[<n>].sequence' (funding/contributors/contributor[<n>]/contributor-attributes/contributor-sequence): a funding contributor has no contributor-sequence (funding-3.0.xsd)`, yorc-rs's reason text; `orcid_validate_funding` reports `...: 1 occurrences, at most 0` |
| 9 | Keep more than one research-resource host. The model holds 1 to 10 (`research-resource-3.0.xsd`, `hosts`: `maxOccurs="10"`); the DuckDB tables and writer keep the first. | DuckDB (columns, writer); Rust/Zig rows mirror DuckDB | `research-resource-3.0.json` has two proposal hosts. DuckDB's `orcid_research_resource_to_*` writes back only one (REFERENCE.md, "one host each"); yorc-rs writes both. This harness cannot see it: the semantic level compares rows, which hold the first host on all three sides. | decision (a new column or list field in all three). **Decided and done in yorc-duckdb and yorc-rs (2026-10-18)**: a new section `research_resource_hosts` (12 columns, last in both section lists), one row per host of a proposal or of a resource item (the XSD allows 10 in each; one table, `container` = `proposal` / `resource-item`, `item_ordinal`); the first-host columns stay. yorc-duckdb's research_resource writer takes `hosts` LIST(STRUCT) fields (proposal and items), writes every host, still takes the flat fields alone, and refuses both when they disagree. **Zig done (2026-10-18)**: `Section.research_resource_hosts`, the same rows (yorc-zig's `tests/rows_test.zig`) |
| 10 | Close the context gaps of COVERAGE.md in the row layout: `assertion_origin_orcid` / `assertion_origin_client_id` outside `works`, `normalized_error` code, the record-level `orcid-identifier/uri` and `/host`, and collection `last-modified-date`. | DuckDB, then Rust and Zig (the rows mirror its layout) | The models of all three read these values, but no row carries them. The assertion origin matters most: member integrations assert affiliations and fundings "on behalf of" an organization. | decision (a change to the table layout in all three). **Decided and done in yorc-duckdb and yorc-rs (2026-10-18)**: 21 columns appended to 9 shared sections (and 6 to DuckDB's `notifications`), after the existing ones: the assertion origin in fundings, affiliations, peer reviews, research resources, person items and history; `normalized`, `normalized_error`, `normalized_error_code` in person items; `normalized_error_code` in external ids; `contributor_orcid_host` (DuckDB now writes it, as Rust and Zig do); the record's `orcid_uri` / `orcid_host` in `person`. Not added: collection `last-modified-date` (§1: no change). Table: yorc-duckdb/docs/COVERAGE.md, "Columns added on 2026-10-18". **Zig done (2026-10-18)**: the same 21 columns (yorc-zig's `src/rows.zig`, `tests/rows_test.zig`) |
| 11 | JSON reading should error, or warn, when no document element can be inferred, instead of yielding no rows. | DuckDB | `InferJsonRoot` returns `""` for shapes it does not know (for example a work without a `title`, or a minimal funding), and REFERENCE.md says such a document "gives no rows". A typo in a document silently loses its rows. Rust and Zig cannot hit this: `json::from_str` takes the kind explicitly. cc: json-read rows. | decision |
| 12 | Convert bare epoch numbers in timestamp members (`"created-date": 1540896558250`, not only `{"value": 1540896558250}`). | DuckDB | yorc-rs's `R::time` takes a bare number or a wrapped one; DuckDB converts only value wrappers in `*-date` members (`FillElement`, `src/core/json_map.cpp`), so a bare number stays its digits. ORCID always wraps, so this is an edge case. | safe now. **Done in yorc-duckdb**: `AddMember` converts a bare integer in a `*-date` member too |
| 13 | A harness extension: `--reread` could also print yorc-rs's canonical model (its JSON), so that the semantic level sees what rows do not carry (the second host, contributor `host`, normalized ids, every `language-code`). | bench (Rust program) | It would make #9 and similar losses visible. | safe now |
| 14 | Read `history/creation-method` from JSON as the XSD value. ORCID's JSON has the Java enum names (`record-full-3.0.json`: `"MEMBER_REFERRED"`); the XML and the rows have the XSD's (`Member-referred`). | DuckDB | Found by the four-way check (`--only rust,zig,duckdb,java`): the `history` row of `record-full-3.0.json` had `MEMBER_REFERRED` in DuckDB, `Member-referred` in Rust, Zig and Java. It is the only enum ORCID's JSON spells differently (yorc-rs json.rs module docs; every enum-valued member of the JSON samples checked). cc: json-read rows. | safe now (bug fix). **Done in yorc-duckdb (2026-10-18)**: `CreationMethodFromJson` in `src/core/json_map.cpp`, as yorc-rs's `creation_method_from_json`: `API` -> `API`, `DIRECT` -> `Direct`, `MEMBER_REFERRED` -> `Member-referred`, `WEBSITE` -> `website`, anything else kept (trimmed match). DuckDB writes no history, so there is no writer side |
| 15 | Read JSON containers in XSD child order. yorc-rs and yorc-zig write sorted keys, so their JSON of `person-3.0` (and of the fixture record) lists `addresses`, `emails`, `external-identifiers`, `keywords`, `other-names`, `researcher-urls`; DuckDB gave `person_items` in that order, Rust and Java in the XSD's (other names, researcher URLs, emails, addresses, keywords, external identifiers), which is also DuckDB's order for the XML. | DuckDB | Found by the four-way check (json-read rows of `read_samples/person-3.0` and the fixture). | safe now (bug fix). **Done in yorc-duckdb (2026-10-18)**: `kChildOrders` / `OrderChildren` in `src/core/json_map.cpp` put the children of `record`, `person`, `personal-details`, `record-summary` and `research-resource` in XSD sequence order (record-3.0, person-3.0, personal-details-3.0, summary-3.0, research-resource-3.0 xsd); children of one name keep their order. Checked and left alone because the XSD order is already alphabetical: `activities-summary`, the activity groups (`external-ids` before the items), `peer-review` (`review-identifiers` before `subject-external-identifier`). FINDINGS.md #3 (DuckDB read 2 more external ids in `read_samples/peer-reviews-3.0`, the pre-3.0 `activities:group/peer-review:summary`): **done in yorc-duckdb (2026-10-18)**, see "item matching" in section 1 |
| 16 | Leave `history/@visibility` out of the JSON writers. ORCID's JSON never has it, and ORCID's Java model reads with `FAIL_ON_UNKNOWN_PROPERTIES`; the XSD declares it, so the XML keeps it. | Rust, Zig (DuckDB writes no history) | Found by the four-way check: 6 JSON documents written by Rust and Zig (3 of the 75 inputs, each by both) did not read in Java ("Unrecognized field visibility" in `history`: `record-3.0`, `history-3.0`, `record-no-city-country-for-professional-activities-3.0`). cc: J reads written JSON. | **Done (2026-10-18)**: yorc-rs `w_history` and yorc-zig `wHistory` no longer write `visibility` (the same bytes in both); the readers still accept the member; the XML -> JSON -> XML round-trip tests strip history visibility from the original before comparing; java/FINDINGS.md #4, #7. Expected: `J reads written JSON` 75/75 same |

| 17 | Draw a reproducible sample of a dump with the libraries' sampler. yorc-rs and yorc-zig share `dump::reservoir` (SplitMix64, Algorithm R, contract vectors); DuckDB had only `USING SAMPLE reservoir(n ROWS) REPEATABLE (seed)`, which samples rows with its own generator. | DuckDB | A sample drawn in SQL could not be reproduced with a library, or the other way round; the walkthroughs' cell 8 picked different records. | **Done in yorc-duckdb (2026-10-18)**: `orcid_dump_sample(archive, n, seed)` (`src/core/reservoir.cpp`): SplitMix64; `below(n)` = high 64 bits of `next() * n` (no rejection); the k-th eligible member is kept while k < n, else `j = below(k + 1)` replaces slot j iff j < n; eligible = a regular file whose last path component is longer than 4 characters, ends in `.xml` (any case) and has a stem that normalises to a valid iD (yorc-rs's walkthrough: `xml_entry_stem` then `OrcidId::parse`; yorc-zig's: `nextXml`, `xmlEntryStem`, `id.normalize`). Rows in slot order, as `into_items()`. Seed 42, n = 1 on the dump fixture: 0000-0003-0100-6634 (as both walkthroughs); n = 5: both records. Note: the private app's `sample` command uses a stricter rule (the stem must match `^[0-9]{4}-[0-9]{4}-[0-9]{4}-[0-9]{3}[0-9X]$`, no check digit, and `._*` names are skipped), so its picks can differ from the libraries' on archives with other names; on ORCID's dumps the two rules agree. Not yet in the cross-check: the bench's `dump_sample` workload times it |
| 18 | Skip the pre-3.0 `activities:group/peer-review:summary` layout (read sample `peer-reviews-3.0.xml`). | DuckDB | Rust, Zig and Java drop the element (it is outside the v3.0 XSDs); DuckDB's suffix matching read the 2 external ids inside it (java/FINDINGS.md #3). | **Done in yorc-duckdb (2026-10-18)**: nothing inside a `group/summary` element is read (`src/core/sections.cpp`); expected: rows of `read_samples/peer-reviews-3.0` all same |
| 19 | Bench files and classes for group ids, the timeline and the snapshot diff, so that the three-way check compares them. | Rust, Zig (DuckDB done) | yorc-rs and yorc-zig are adding group-id records, `timeline` and a diff with yorc-duckdb's columns (2026-10-18, by the other agent). | **Done in the DuckDB leg and compare3.py (2026-10-18)**; the formats are in "Bench files for group ids, timeline and changes" below. Until the Rust and Zig programs write the files, the three classes report missing R / missing Z without failing |

Smaller differences with no recommended change, or only "document it",
are in the tables below.

## 1. Field coverage

| area | Rust | Zig | DuckDB | per the XSDs and samples | recommendation |
|---|---|---|---|---|---|
| schemas covered | Every name of the 27 `record_3.0` XSDs and `common-3.0`, except the 11 in `tests/xsd_uncovered.txt` (checked by `tests/schema_coverage.rs`) | = Rust (the same list: `testdata/xsd_uncovered.txt`, `tests/schema_test.zig`) | 32 XSDs: the record ones plus `summary-3.0`, both notification XSDs and `group-id-3.0`. 106 of 109 data-bearing names have a column (COVERAGE.md) | All are ORCID v3.0 message schemas | none |
| `record-summary` (summary-3.0), notifications, group-id records | not modelled | not modelled | `orcid_summary`, `orcid_summary_items`, `orcid_notifications`, `orcid_group_ids` (and `orcid_group_id_to_*`) | The API serves them | Rust/Zig: add them only if users ask (decision: new model types) |
| `notification` dates (`archived-date`, `read-date`, `sent-date`) | not modelled (xsd_uncovered: "notification_3.0 only") | = Rust | mapped (`notifications.*`) | notification-3.0 only | follows from the row above |
| `approval-date`, `application-orcid`, `application-group-orcid`, `group-orcid-identifier` | not modelled | = Rust | not mapped | Declared in common-3.0, referenced by no vendored type | none: no document carries them |
| `preferences/locale` | `Root::Preferences` (`locale`) | = Rust | not mapped (COVERAGE.md: no section for a standalone `preferences`) | `preferences-3.0.xsd`; a read sample exists | DuckDB: no change (no user value seen) |
| `@transient` (on `external-id-normalized`) | modelled ("every attribute is covered") | = Rust | not mapped (always `true`) | Pattern-restricted to `true` | none |
| context gaps (COVERAGE.md): `assertion-origin-orcid` / `-client-id` only in `works` | rows of every section with a `common:source` (#10, 2026-10-18) | = Rust before #10 (pending) | the same columns (#10) | Every `common:source` has them | done (#10) |
| context gap: `external-id-normalized-error/error-code` | `external_ids.normalized_error_code`, `person_items.normalized_error_code` (#10) | pending | the same (#10) | | done (#10) |
| context gap: a second `hosts/organization` | `research_resource_hosts`: every host (#9); the first-host columns stay | pending | the same section (#9) | `maxOccurs="10"`; `research-resource-3.0.json` has two | done (#9) |
| context gap: record `orcid-identifier/uri`, `/host` | `person.orcid_uri`, `person.orcid_host` (#10) | pending | the same (#10); `summary` and `search_results` as before | | done (#10) |
| context gap: collection `last-modified-date` | in the model; no row | = Rust | not read | | none (`max(last_modified)` gives it) |
| item matching | where the XSDs put an item (rows.rs: "items are found where the schema puts them") | = Rust | local-name path suffixes, anywhere (REFERENCE.md: "Item patterns are local-name suffixes") | The XSDs | Document only. The two agree on schema-valid documents and may differ on documents outside the XSDs. The one such case the check found, read sample `peer-reviews-3.0.xml` (the pre-3.0 `activities:group/peer-review:summary` layout: DuckDB read 2 external ids inside it that Rust, Zig and Java drop), is **closed (2026-10-18)**: yorc-duckdb reads nothing inside a `group/summary` element (java/FINDINGS.md #3). cc: rows (`read_samples/peer-reviews-3.0`), expected all same |

## 2. JSON: the document element

| area | Rust | Zig | DuckDB | per the XSDs and samples | recommendation |
|---|---|---|---|---|---|
| how the kind is known | explicit: `json::from_str(kind, json)`, with the XML root local names (`json::KINDS`) | explicit: `json.parse(gpa, kind, …)` | inferred (`InferJsonRoot`): from `json_root` when given; then `bulk`; then the document's `path`; then the members the document has | ORCID's JSON names no root; the URL does (REFERENCE.md, "JSON documents") | none: both designs fit their APIs |
| affiliation without `path` | any of the 7 kinds, as given | = Rust | an error asking for `json_root := 'employment'` (or another of the seven types) | The same members for all seven types | none. The harness retries with `json_root` = the kind and lists those documents in `json_root.tsv`. |
| `{"content": ...}` (keyword or other name) | as given | = Rust | an error asking for `json_root := 'keyword'` or `'other-name'` | Ambiguous by construction | none (as above) |
| unknown shape | `Root::Unknown` or the kind's empty model | = Rust | no rows, no error | | #11 |
| top-level array | an error (`must be a JSON object`) | = Rust (to check: being edited) | a sequence of documents | ORCID's API returns objects | none (document) |
| collection kinds (`employments`, `works`, …) | explicit kinds | = Rust | `RootFromGroups` and the `path` (`/<iD>/employments`) | | none |

## 3. JSON timestamps (epoch milliseconds)

| area | Rust | Zig | DuckDB | per the XSDs and samples | recommendation |
|---|---|---|---|---|---|
| read: which members | the fields the model holds as timestamps (`R::time`), bare or `{"value"}` | = Rust (`json.millisToDatetime`) | any `{"value": <integer>}` in a member whose name ends in `-date` (`FillElement`); bare integers too since #12 (done in yorc-duckdb) | ORCID wraps every timestamp (`record-full-3.0.json`) | #12 (the bare-number edge) |
| read: text written | `YYYY-MM-DDTHH:MM:SS.mmmZ` (`millis_to_datetime`) | = Rust | the same format (`EpochMillisToIso`, the same Hinnant algorithm) | ORCID's XML: `2018-10-30T10:49:18.250Z` | none. cc: json-read rows (`created`, `last_modified`) |
| read: very large or non-integer numbers | `as_i64`; a float gives no value | keeps the source text | at most 18 characters, digits only; otherwise the number's text | ORCID writes integer ms | none |
| write | `xs:dateTime` text → ms, converted to UTC (`datetime_to_millis`); text that is not an `xs:dateTime` makes the JSON write fail (`Error::Unwritable`) | = Rust | timestamps are never written (they are read-only) | | Rust/Zig: none. Keep in mind that one malformed date makes a whole record unwritable as JSON. |
| offset round trip | `…-06:00` in XML becomes `…Z` (UTC) after JSON | = Rust | the same after a JSON read | | none. cc: json-read rows; the rows class shows the original text. |

## 4. Writers: what is written

| area | Rust | Zig | DuckDB | per the XSDs and samples | recommendation |
|---|---|---|---|---|---|
| purpose | `to_string`: any root as it is (a full document); `payload_to_string`: validate, then the same writer | = Rust | item payloads only, from a `STRUCT` of reader columns (+ `LIST(STRUCT)` children) | | none |
| roots written | every root kind, records included | = Rust | work, bulk of works, funding, the 7 affiliations, peer review, research resource, the 5 person items, group-id record | ORCID's write samples cover the DuckDB set, plus the group id (Member API) | Rust/Zig: a group-id writer only with the model (see §1) |
| `put-code` | written when the model holds it | = Rust | written (an integer is required) | element-summary declares it; needed for an update | none |
| `visibility` | written | = Rust | written (any text) | `bulk-works-3-works-3.0.json` sends it | #1 (the vocabulary check) |
| `source`, `created-date`, `last-modified-date`, `@path`, `@display-index` | `to_string`: written when held; payloads: not written (#2, 2026-10-18) | written in payloads too (#2 pending) | never written | Set by ORCID; no write sample has them | #2 (Rust done) |
| contributor `host` | written when held | = Rust | written (`contributor_orcid_host`, a reader column since #10) | optional in `common:orcid-id`; `work-full-3.0.xml` (write sample) has it | done |
| `external-id-normalized` (`@transient`) | `to_string`: written when held; payloads: not written (#2) | written (#2 pending) | not written | ORCID's own; transient | #2 (Rust done) |
| a work's `country/@visibility` | `to_string`: written when held; payloads: not written (#2) | written (#2 pending) | not written | no write sample has it | #2 (Rust done) |
| research-resource hosts | all hosts | = Rust | all hosts of the `hosts` lists, else the flat first host (#9) | 1..10 | done (#9) |
| work `doi` column | n/a (model) | n/a | becomes a `doi`/`self` external id when `external_ids` is absent | | none (a DuckDB convenience) |
| peer-review subject id | `subject-external-identifier` from the model | = Rust | the `external_ids` item with `container = 'peer-review'` (two are an error) | | none |
| required containers | `review-identifiers`, `resource-items` and proposal/item `external-ids`, always written | = Rust | the same (`ALWAYS`), plus `common:address` in every organization (`<common:address/>` when it is empty) | `address` is required (no `minOccurs`); its children are optional | none: both valid |
| funding contributor `sequence` | `TooMany { max: 0 }`; the write fails (`Unwritable`) | = Rust | silently not written; now an error (#8, done in yorc-duckdb) | `funding-3.0.xsd` has no sequence | #8 |
| fuzzy-date text | year `{:04}`, month and day `{:02}`, no range check in `to_string` | = Rust | year as an integer 1900..2100, month and day as two digits | `common:year` | none (the same bytes in range) |

## 5. Output bytes

| area | Rust | Zig | DuckDB | per the XSDs and samples | recommendation |
|---|---|---|---|---|---|
| XML declaration, final LF | `<?xml version="1.0" encoding="UTF-8"?>` LF … LF | = Rust | the same | | none |
| indentation | two spaces | = Rust | one tab; two spaces in crosswalk mode (#5, done in yorc-duckdb) | ORCID's samples use tabs | #5 (decided: a switch in DuckDB) |
| namespace declarations | every namespace used, on the root, in `xml::Ns` order (alphabetical by prefix) | = Rust | the prefixes used, on the root, `std::set` order (alphabetical) | | none: already equal |
| `xsi:schemaLocation` | not written | = Rust | not written | ORCID's samples have it; it is optional | none |
| attribute order | `put-code`, `path`, `visibility`, `display-index`, … | = Rust | `put-code`, `visibility` | | none (equal for payloads) |
| JSON key order | sorted (serde) | = Rust | XSD sequence order; sorted in crosswalk mode (#5) | Jackson writes model order | #5 (done in yorc-duckdb) |
| JSON layout | serde's pretty print (two spaces, `": "`), final LF; always-written containers hold `[]` when empty (`"external-id": []`) | = Rust | two spaces, final LF; an empty always-written container is `{}`, `{"external-id": []}` in crosswalk mode (#5) | | none |
| JSON numbers | `put-code` as a number; dates' parts as strings | = Rust | `put-code` as a number; dates' parts as strings | `record-full-3.0.json` | none |

## 6. Escaping and character handling

| area | Rust | Zig | DuckDB | per the XSDs and samples | recommendation |
|---|---|---|---|---|---|
| XML text | `&` `<` `>` and CR (`&#13;`) | = Rust | the same | XML 1.0 | none |
| XML attributes | also `"`, TAB, LF (`&#9;`, `&#10;`) | = Rust | the same | attribute-value normalization | none |
| characters XML 1.0 cannot carry | `Error::Unwritable` (`check_chars`), U+FFFE/FFFF included | = Rust | an error (`cannot be written in XML 1.0`), U+FFFE/FFFF included | | none |
| JSON strings | serde: `"` `\` and C0 control characters escaped; DEL and U+2028/2029 written raw | = Rust (serde layout) | the same, but DEL escaped (`\u007f`); raw in crosswalk mode (#5). U+2028 / U+2029 are raw (`AppendJsonString`) | Both are valid JSON | none (a byte difference only for DEL, and none in crosswalk mode) |
| invalid UTF-8, read | `Error::Utf8 { valid_up_to }` (XML and JSON) | checked in the scanner (`utf8.zig`) | JSON: checked; XML: not checked on read; now checked (#3, done in yorc-duckdb) | | #3 |
| XML 1.0 forbidden characters, read | accepted (quick-xml does not check them); the write then fails | rejected (PARITY.md: "checks UTF-8 and XML characters") | accepted (not checked on read) | Not well-formed XML | Rust and DuckDB: decision (leniency is a stated design rule of yorc-rs). A read probe in the harness would show the Rust/Zig difference. |
| malformed attribute (no `=` or no quotes) | skipped (quick-xml) | `MalformedXml` | an error (`attribute without value`, `unquoted attribute value`) | Not well-formed | none (document the leniency): Rust documented (`xml` module docs, 2026-10-18) |
| BOM | stripped (XML and JSON) | = Rust | stripped (format detection, JSON parser) | | none |

## 7. Validation rules

*Historical: the validators were removed on 2026-10-18 (see the note at the
top).*

yorc-rs's `validate` and yorc-zig's `validate.check` implement the same
rules with the same violation text (PARITY.md). DuckDB's writers check while
they write (`src/core/writer.cpp`, `Renderer`). Since #1 (done in
yorc-duckdb) DuckDB also has `orcid_validate_<writer>(rec [, mode])`
(`src/core/validate.cpp`) with yorc-rs's paths and texts: the "no" cells
of the DuckDB column below are "yes (validator)" now; the writers are
unchanged. The harness's validation verdict still uses the writers; switching
it to the validators' lists would make the reasons comparable. cc: validation
(each probe is named in `probes.tsv`).

| rule | Rust | Zig | DuckDB | per the XSDs | recommendation |
|---|---|---|---|---|---|
| required elements (`minOccurs="1"`) | yes | yes | yes (`REQUIRED`) | | none |
| empty or whitespace-only text counts as missing | `Empty` / `Required` | = Rust | blank fields are left out, so a required one fails | `common:non-empty-string` | none |
| `maxLength` (title 1000, other-name 255, url-name 350, …) | yes | yes | no | | #1 |
| fuzzy-date ranges (year 1900..2100, month 1..12, day 1..31; a day needs its month; a date needs its year) | yes | yes | yes | common-3.0 | none |
| translated title needs `language-code`; citation needs both type and value; amount needs `currency-code`; a disambiguated organization needs both its id and its source | yes | yes | yes | | none |
| closed vocabularies (`Other(..)` → `UnknownValue`) | yes (CRediT role URIs accepted) | yes | no | The XSD documentation lists the values ORCID validates | #1 |
| patterns (`orcid-path`, `orcid-uri`, `client-path`, `group-id`, `email`, `locale`) | yes | yes | no | | #1 |
| put-code absent on create, present (> 0) on update | yes (`Mode`) | yes | no mode; `put_code` must be an integer | ORCID API rule | #1 (a `mode` argument) |
| ISO country `[A-Z]{2}` and currency `[A-Z]{3}` shape | yes (ORCID API rule) | yes | no | | #1 |
| bulk: 1..100 works | yes | yes | yes | ORCID API rule | none |
| unknown input fields | n/a (typed model) | n/a | an error (`unknown field 'titel'`) | | none |
| a disambiguated organization required where an organization is (common-3.0.xsd documentation; not enforced by the schema) | no | no | no | documentation only | none (ORCID enforces it server-side) |

## 8. Row columns

| area | Rust | Zig | DuckDB | recommendation |
|---|---|---|---|---|
| 11 sections, 244 columns, names, order and types | `rows.rs`; plus `search_results` and `errors` (#7) and `research_resource_hosts` and the #10 columns: 14 sections, 300 columns | `rows.zig` (11 sections, 244 columns; #7, #9 and #10 not yet) | `src/core/sections.cpp` (19 sections) | Zig: "Pending: Zig". cc: rows (`columns.tsv` lists every column with both types) |
| columns added after the first layout | appended after the existing ones, as yorc-duckdb does (#10) | — | appended (`peer_reviews`' 36th column first, #10 since) | | none: keep appending |
| `peer_reviews.subject_translated_name_language` (the 36th column, after `source_hash`) | yes | yes | yes | none |
| sections only DuckDB has | `search_results`, `errors` (#7, done) | — (#7 pending) | `timeline`, `summary`, `summary_items`, `search_results`, `errors`, `notifications`, `group_ids` (written to `extra/`, not compared) | Zig: #7. bench: compare DuckDB's `search_results` and `errors` too, once Zig has them |
| a non-integer `put-code` | counts as absent | = Rust | NULL ("numbers that are not plain digits are NULL") | none |
| repeated single-valued element | the first non-empty value, per column | = Rust | the first one wins | none (the same on the samples; cc: rows) |

## 9. API messages only DuckDB reads

`orcid_summary` / `orcid_summary_items` (`/summary`), `orcid_search_results`
(search and expanded search), `orcid_errors` (with the locked/deprecated iD
fallback and `primary_orcid`), `orcid_notifications`, `orcid_group_ids`,
plus `orcid_timeline`, `orcid_changes` and `orcid_documents`.

yorc-rs and yorc-zig parse `error`, `search`, `expanded-search` and
bulk errors into the model. yorc-rs now produces DuckDB's
`search_results` and `errors` rows for them (#7); yorc-zig does not yet.
Neither models `record-summary`, notifications or group-id records. See #7
and §1.

## Pending: Zig (after yorc-rs's #4 and #7)

yorc-rs (2026-10-18, 0.1.0 unreleased) added:

- **#7**: `rows::Section::SearchResults` and `rows::Section::Errors`, at the
  end of `Section::ALL` (after `history`), with DuckDB's columns, order and
  types (`search_results`: 13 columns, starting with `num_found`, not
  `orcid`; `errors`: 10, ending with `primary_orcid`). Values:
  `search_results` has one row per `search/result` (`item` = `result`) or
  `expanded-search/expanded-result`, `num_found` on every row, a 1-based
  `ordinal`, and `; `-joined `other_names`, `emails` and `institution_names`.
  `errors` has one row per standalone `error` (`container` NULL,
  `position` 1) or per bulk entry error (`container` = `bulk`, `position` =
  the 1-based entry index among works and errors). `orcid` is the document's
  iD, else the first valid iD after `ORCID ` in `developer-message` and then
  `user-message`. `primary_orcid` is the first valid iD after
  `refer to account:` (DuckDB's `IdAfter`: spaces skipped, the token ends at
  whitespace, trailing `.,;)/` dropped, `orcid_normalize`d).
  `response_code` / `error_code` (INTEGER) and `num_found` (BIGINT) follow
  the digit rule (0..=9 or 18 digits).
  The values are pinned in yorc-rs's `tests/samples.rs` against DuckDB's
  `orcid_api_messages.test`, `orcid_locked_deprecated.test`,
  `orcid_activity_items.test` and `orcid_json.test`.
  **Done in yorc-zig (2026-10-18)**:
  `rows.zig` has both sections with the same rules (`Walker.search`,
  `expandedSearch`, `apiError`, `idAfter`), and `tests/rows_test.zig`
  ports the samples.rs expectations. compare3.py no longer treats them as
  a known Zig gap.
- **#4**: `dump::records` and `read_entry` now refuse a member over 64 MiB
  by default (`dump::Limits`, `records_with`, `read_entry_with`). The bench
  already uses 64 MiB on the Zig side, so the dump class should not change.

### Pending: Zig (after #2, #9 and #10, 2026-10-18)

**Closed (2026-10-18, later).** yorc-zig's
`rows.zig` now has items 1 to 3 below: 14 sections, 300 columns, the names,
order and types of yorc-rs's tables (`schema matches yorc-duckdb`), with
the samples.rs expectations of item 5 ported to `tests/rows_test.zig`
(except `payload_leaves_out_what_orcid_sets`: payloads were removed).
compare3.py's `ZIG_PENDING_SECTIONS`, `ZIG_PENDING_COLUMNS` and
`KNOWN_ZIG_GAPS` are empty. The text below is the specification it
followed.

yorc-rs and yorc-duckdb share the layout below; yorc-zig was not changed
at first. To match, yorc-zig must add exactly this (#7 above comes first: the section order assumes it):

1. **Section order** (`rows.zig`): `works`, `fundings`, `affiliations`,
   `peer_reviews`, `research_resources`, `research_resource_items`,
   `contributors`, `external_ids`, `person`, `person_items`, `history`,
   `search_results`, `errors`, `research_resource_hosts`: 14 sections, 300
   columns. Widths: 32, 37, 32, 38, 32, 13, 12, 13, 15, 24, 17, 13, 10, 12.
2. **Columns appended** (after every existing column, in this order; all
   VARCHAR; paths relative to the item):
   - `fundings` (36, 37), `affiliations` (31, 32), `peer_reviews` (37, 38,
     after `subject_translated_name_language`), `research_resources` (31,
     32): `assertion_origin_orcid` (`source/assertion-origin-orcid/path`),
     `assertion_origin_client_id` (`source/assertion-origin-client-id/path`).
   - `contributors` (12): `contributor_orcid_host` (`contributor-orcid/host`).
   - `external_ids` (13): `normalized_error_code`
     (`external-id-normalized-error/error-code`).
   - `person` (14, 15): `orcid_uri`, `orcid_host`: the record's
     `orcid-identifier/uri` and `/host`, only when the document element is a
     `record` (NULL for a standalone `person` or `personal-details`).
   - `person_items` (19 to 24): `assertion_origin_name`,
     `assertion_origin_orcid`, `assertion_origin_client_id`, `normalized`,
     `normalized_error`, `normalized_error_code` (the last three from a
     person external identifier's `common:external-id`; NULL for the other
     kinds).
   - `history` (15 to 17): `assertion_origin_name`, `assertion_origin_orcid`,
     `assertion_origin_client_id`.
3. **New section `research_resource_hosts`** (item `hosts/organization`,
   one row per host, in document order: the proposal's hosts, then each
   resource item's): `orcid` VARCHAR (the document's iD, no item-path
   fallback: as `research_resource_items`), `owner_put_code` BIGINT (the
   research resource's or summary's put-code), `ordinal` INTEGER (1-based
   position in `hosts`), `host_name`, `host_city`, `host_region`,
   `host_country`, `host_disambiguated_id`, `host_disambiguation_source`
   VARCHAR (as `org_cols("host", ...)` on the one host), `container` VARCHAR
   (`proposal` or `resource-item`), `item_ordinal` INTEGER (the resource
   item's 1-based position; NULL for the proposal), `source_hash` VARCHAR.
   Summaries (`research-resource-summary/proposal/hosts`) give rows too.
   **Done in yorc-zig (2026-10-18)**, with the section order of
   item 1 (`Walker.hosts`; tests in `tests/rows_test.zig`).
4. *(No longer applies: the payload writers were removed on 2026-10-18.)*
   **Payloads (#2)**: the XML and JSON payload writers write a copy without
   the item's `source`, `created-date`, `last-modified-date`, `@path`,
   `@display-index` (`@put-code` and `@visibility` stay), without the
   `external-id-normalized`, `external-id-normalized-error` and item metadata
   of every external id inside the item (`external-ids`,
   `review-identifiers`, `subject-external-identifier`; a person external
   identifier payload keeps its own put-code and visibility), and without a
   work's `country/@visibility` (yorc-rs: `Payload::to_root`). Whole
   documents (`toOwned`, the document writers) keep everything.
5. **Tests**: the expectations of yorc-rs's `tests/samples.rs`
   (`schema_matches_yorc_duckdb`, `record_sample_counts`,
   `research_resource_sample`, `record_full_json_context_columns`,
   `research_resource_json_hosts`, `payload_leaves_out_what_orcid_sets`),
   which are yorc-duckdb's (`orcid_sections.test`, `orcid_json.test`,
   `orcid_api_messages.test`, `orcid_write.test`).

**Until then (no longer: see "Closed" above) the Rust-Zig cross-check differed on rows**: every document
differs in the widths of the 9 sections above (`columns.tsv`, and every
`.rows.tsv` line of those sections), and the Rust side has
`# research_resource_hosts` lines (and rows for every research resource).
Payloads written from read items (with ORCID's metadata) differ in bytes;
written payloads from ORCID's write samples do not (they carry none of the
dropped fields). The bench's DuckDB side was brought up to date with #5 (2026-10-18):
`duckdb/emit.py` lists yorc-rs's 14 sections and 300 columns
(`_SECTIONS`; `EXTRA` keeps the 5 DuckDB-only sections), passes every
research-resource host, and writes in crosswalk mode. `duckdb/compare3.py`
counts a Zig file that differs only by the items above as **known Z gap**
(`KNOWN_ZIG_GAPS`, `ZIG_PENDING_SECTIONS`, `ZIG_PENDING_COLUMNS`; `report
--known-gaps` lists them), which does not fail the check, so the gap shows
as such and not as noise; remove an item there once yorc-zig has it.
`java/FINDINGS.md` item 4 (a work's `country/@visibility`) now also holds
for yorc-rs's payloads.

## 10. Dump reading

| area | Rust | Zig | DuckDB | recommendation |
|---|---|---|---|---|
| containers | `.tar.gz` / `.tgz` (`dump::open` on any path; `is_dump_path`) | `.tar.gz` / `.tgz` | `.tar`, `.tar.gz`, `.tgz`, globs, `https://` and `s3://` (httpfs) | none |
| concatenated gzip members | yes (`MultiGzDecoder`) | yes since 2026-10-18 (a fresh decompressor per member, #6); before: the first member only | yes (DuckDB's `GZipFileSystem`: `MiniZStreamWrapper::Read` restarts inflate at each member end; pinned by `test/data/dump/orcid_test_summaries_2members.tar.gz` in `orcid_dumps.test`, 2026-10-18) | #6 |
| members read | regular files ending in `.xml` (any case) | = Rust (`nextXml`, `xmlEntryStem`) | `members` glob, by default `*.xml` and `*.json` (the harness passes `members := '*.xml'`) | none |
| member size limit | `dump::Limits::max_member_bytes`, 64 MiB by default (`records_with`, `read_entry_with`); a larger member is an `io::Error` for that member, and the walk goes on (#4, done) | a per-call `limit` (the bench: 64 MiB) | `max_member_bytes`, 64 MiB by default; larger fails the scan | none |
| a malformed member | that member fails; the stream goes on | = Rust | the whole scan fails | DuckDB: decision (an `ignore_errors` option). The harness then writes `dump/members.tsv` = `error`. |
| a member's iD | `DumpRecord::orcid()` from the file stem | the stem | `orcid_documents.orcid`: the first valid iD (check digit verified) in the path | none |
| tar extensions | the `tar` crate (GNU and pax) | std tar | GNU long names, pax `path`, ustar prefix (`src/core/tar.cpp`) | none |
| sampling | `dump::reservoir` (SplitMix64, Algorithm R) | = Rust | `orcid_dump_sample(archive, n, seed)`: the same picks (#17) | none |
| other | | | `max_records`; parallel parsing; progress | none |

## Bench files for group ids, timeline and changes

The format the Rust and Zig bench programs' `--emit` should write for the
three classes compare3.py added on 2026-10-18 (`group_ids rows`,
`timeline rows`, `changes rows`). yorc-duckdb's leg (`duckdb/emit.py`)
writes them already; compare3.py compares each file **byte for byte** (no
re-read, `source_hash` not blanked: all sides hash the same input bytes).

**Layout** (paths below the `--emit` directory):

| file | input (below `--root`) | section |
|---|---|---|
| `fixture/<stem>.group_ids.tsv`, `read_samples/<stem>.group_ids.tsv`, `write_samples/<stem>.group_ids.tsv` | every XML input the program reads into rows (the same set as `<stem>.rows.tsv`; most have 0 rows) | `group_ids` |
| `json_samples/write_samples/peer-review-group-id.group_ids.tsv` | `yorc-rs/reference/orcid-model/record_3.0/samples/write_samples/peer-review-group-id.json` (JSON; ORCID's only group-id JSON sample) | `group_ids` |
| `group_id/group-id-3.0.group_ids.tsv` | `yorc-duckdb/reference/orcid-model/group-id-3.0/samples/group-id-3.0.xml` (yorc-rs's `reference/orcid-model/group-id-3.0/samples/group-id-3.0.xml` is the same bytes) | `group_ids` |
| `fixture/<stem>.timeline.tsv`, `read_samples/<stem>.timeline.tsv`, `write_samples/<stem>.timeline.tsv` | every XML input, as above | `timeline` |
| `changes/old_new.changes.tsv` | old `yorc-duckdb/test/data/changes/old.xml`, new `yorc-duckdb/test/data/changes/new.xml` (the same bytes as yorc-rs's `tests/data/changes/`) | `changes` |

When an input does not read (the program writes `error` as its `.xml`), write
no `.group_ids.tsv` / `.timeline.tsv`: compare3.py takes the read error as
the value, as for `.rows.tsv`. A changes pair that does not read: write the
file with the content `error` and a newline.

**Format:** exactly the `.rows.tsv` format, with one section:

- line 1: `# <section>` TAB `<row count>` (`# group_ids`, `# timeline`, `# changes`);
- if the count is not 0: the column names, TAB-separated, then one line per
  row, in table order (the order of yorc-duckdb's table function: document
  order; for the timeline each item's `created` event, then its `modified`
  event when it differs; for changes yorc-duckdb's order, REFERENCE.md:
  section by section, modified and added items in the new snapshot's order,
  then removed ones);
- cells: `\N` for NULL, integers in decimal, text with backslash, TAB, LF and CR
  escaped as `\\`, `\t`, `\n`, `\r`; every line ends with LF (also the last).

**Columns** (yorc-duckdb `docs/REFERENCE.md`; types: V text, I/B integer):

- `group_ids` (12): `put_code` B, `name`, `group_id`, `description`, `type`,
  `source_name`, `source_client_id`, `source_orcid`, `total` I, `page` I,
  `page_size` I, `source_hash`.
- `timeline` (13): `orcid`, `event_at`, `event`, `kind`, `put_code` B,
  `label`, `organization`, `visibility`, `source_name`, `created`,
  `last_modified`, `path`, `source_hash`.
- `changes` (9): `orcid`, `section`, `kind`, `put_code` B, `change`,
  `field`, `old_value`, `new_value`, `label`.

Until the Rust and Zig programs write these files, the three classes report
`missing R` / `missing Z` and do not fail the check (`PENDING_OK` in
compare3.py); as soon as a program writes one file of a class, every entry
of that class counts. Remove the classes from `PENDING_OK` once both have
them.

## 11. What the three-way check cannot see

- **Semantic level means rows.** The written documents are re-read by
  yorc-rs and compared as rows (`source_hash` blanked). A value that no
  row carries is invisible to it: `language-code` of a translated subject
  outside peer reviews, and normalized ids outside `external_ids` and
  `person_items`. Since #9 and #10 (2026-10-18) the second host and the
  contributor `host` have rows (`research_resource_hosts`,
  `contributor_orcid_host`), once the bench prints them (see "Pending: Zig").
  See #13.
- **External ids of bulk and research-resource items.** DuckDB's readers
  cannot tell which item an external id belongs to: a bulk's works have no
  put-code, and a research resource's proposal and items share an owner.
  `duckdb/emit.py` counts `external-id` and `contributor` elements per item
  in the document text, as yorc-duckdb's own `test/sql/orcid_write.test`
  does by hand. A document with comments inside an item, or with
  external ids outside `external-ids`, could be split wrongly. The
  comments of ORCID's samples are stripped first.
- **Only the XML write samples are written by DuckDB.** The JSON write
  samples are read (json-read rows), not written back. So in the Java table's
  `J reads written JSON` (DuckDB added 2026-10-18), DuckDB's entries are the
  21 write samples; the record and the read samples are n/a for it (no
  record writer), not missing.
- **Byte classes see item documents only.** Since #5 the written XML / JSON
  bytes are compared byte for byte (DuckDB in crosswalk mode). They cover
  ORCID's 21 XML write samples, which carry no read-only field, and the Rust
  and Zig sides write them with `to_string`.
  Two crosswalk limits lie outside the samples (yorc-duckdb REFERENCE.md,
  "Crosswalk mode"): DuckDB always writes an organization's `address`, and
  the group-id record has no yorc-rs counterpart.

## 19. A work's `country/@visibility` is left out of written JSON (2026-10-18)

The four-way run after #16 showed Java still rejecting 3 of the 75 JSON
documents yorc-rs and yorc-zig write (`read_samples/work-full-3.0`,
`work-review-3.0`; Java: `Unrecognized field "visibility" (class Country)`).
ORCID's `Country` has only `value`, as `History` has no visibility, so the
JSON writers of yorc-rs and yorc-zig leave the attribute out, like
history/@visibility (#16); XML keeps it and the readers still accept it.
yorc-duckdb does not write it in either layout. The four-way check after
the rebuild gave `J reads written JSON` 74/75 (PARITY.md, "Status of the
checks"), the one left being `work-3.0` (Java's own XSD
check of the empty `journal-title` it keeps, FINDINGS #10a: information).
