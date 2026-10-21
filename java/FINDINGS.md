# What ORCID's Java orcid-model shows for yorc-rs, yorc-zig and yorc-duckdb

ORCID's Java library (`org.orcid:orcid-model:4.0.2`, the classes ORCID's
servers use) was run on the yorc packages' inputs through the bench's
`java/` program. The inputs were the 1.3 MB record, ORCID's 53 read and
21 write samples, the 28 JSON samples, the dump fixture, and edited
copies of `work-simple-3.0.xml` and `work-full-3.0.xml`. JAXB and
Jackson were configured as ORCID's API configures them (README.md, "Java
baseline"). This file lists what ORCID's classes accept or produce that
the three yorc implementations do not, and the reverse.

Status. These findings come from running Java's `--emit` and `--reread`
modes (JDK 21.0.12) and from reading ORCID's orcid-model at 9592e2d and ORCID-Source
(2026-10-15). The rows-level comparison with Rust, Zig and DuckDB
(`compare.sh --only rust,zig,duckdb,java`) was run afterwards (PARITY.md,
"Status of the checks"); the items marked *to confirm* were written before
it.

## Reading

1. **White space in text: ORCID keeps it; we trim.** JAXB keeps string text
   verbatim. In read sample `peer-reviews-3.0.xml`,
   `external-id-value` "orcid-generated:011484675699116\n\t\t\t\t" is written
   back by Java, newline and tabs included, to XML and JSON. yorc-rs,
   yorc-zig and yorc-duckdb trim leaf text. The XSD string types allow the
   white space (`string-1000` is `[\s\S]*[^\s\n\r]+[\s\S]*`). Typed values
   are different: JAXB collapses dates. *Suggestion:* none for rows (trimming
   is the rows contract). Document it as a deliberate difference from
   ORCID's model.

2. **An enum value that does not match exactly is dropped without an error.**
   In read sample `research-resources-3.0.xml`, the summary proposals'
   `external-id-relationship` texts are "self\n\t\t\t\t\t\t".
   ORCID's `Relationship.fromValue` compares exactly, so all three are gone
   after reading, with no error. The XSD types `relationship-type` as plain
   `xs:string`, so the document is schema-valid. An unknown value (`poem`
   as work type, `sibling` as relationship) also reads as null. We trim and
   keep `self` (and keep `poem` as `Other`). *Expect* R/Z/D != J for
   `read_samples/research-resources-3.0` in `J rows via XML` (*to confirm*).
   *Suggestion:* none; we are right per the XSD. A document that
   round-trips through ORCID's classes loses data that ours keep.

3. **Pre-3.0 `activities:group/peer-review:summary` (`peer-reviews-3.0.xml`)
   is dropped by ORCID's classes**, as by yorc-rs and yorc-zig.
   yorc-duckdb read the two external ids inside it (suffix matching,
   CROSSCHECK.md "item matching"); the 2026-10-18 cross-check showed them
   (rows of `read_samples/peer-reviews-3.0`: 3 external ids in D, 1 in R, Z
   and J). **Done in yorc-duckdb (2026-10-18):** nothing inside a
   `group/summary` element is read (no v3.0 element is named `summary`;
   `src/core/sections.cpp`, `opaque_depth_`), so the sample gives the group's
   one external id, as the others. Pinned in `test/sql/orcid_sections.test`
   and `test/cpp/core_test.cpp`. *Expect* R = Z = D = J on that sample (to
   re-run).

4. **Attributes ORCID's classes do not model:** `history/@visibility` and a
   work's `country/@visibility` (declared by the XSDs; no field in
   `History`/`Country`). yorc-rs models both: we keep more than ORCID.
   *Suggestion:* none. If they become row columns, note that ORCID never
   returns them.
   **2026-10-18:** ORCID's JSON has no
   `visibility` member in `history`, and Jackson refuses it (#7), so
   yorc-rs's and yorc-zig's JSON writers no longer write it: history
   visibility is XML-only (CROSSCHECK.md #16). The JSON readers still accept
   it. yorc-duckdb writes no history.

5. **Everything else reads as ORCID reads it.** All 75 XML inputs, the 27
   JSON samples with a kind, the group-id sample and the 3 dump members read
   without an error. For the 21 write samples and the record, Java's written
   XML has the same element tree, attributes and text as the input. That is
   the precondition for using Java as the reference.

## JSON

6. **Timestamps.** ORCID writes epoch milliseconds. Read back, they become
   UTC with milliseconds (`2001-12-31T12:00:00` → `...12:00:00.000Z`,
   `...13:22:53.471-06:00` → `...19:22:53.471Z`), exactly what yorc-rs's
   `millis_to_datetime` produces. Caveat (from reading): ORCID converts an
   offset-less `xs:dateTime` in the JVM's default time zone. yorc-rs's
   `datetime_to_millis` treats it as UTC, which matches only on a UTC server.
   *Suggestion:* note this assumption in yorc-rs's and yorc-zig's JSON docs.

7. **Shape.** ORCID writes `null` members, keys in propOrder, and the bulk
   as `{"bulk":[{"work":{...}}]}`. yorc-rs sorts keys and omits nulls.
   yorc-rs's reader names every key Java wrote for these inputs, except
   `group-id`/`description` of the group-id record. The risk is the other
   way: **ORCID's mapper has `FAIL_ON_UNKNOWN_PROPERTIES` on**, so one key
   unknown to ORCID's classes fails the whole payload (e.g. `{"address": ...}`
   read as `Address`: "Unrecognized field"). The classes `J reads written
   JSON` and `J accepts written documents` check every JSON document Rust,
   Zig and DuckDB write (*to confirm*). *Suggestion:* test that each JSON
   writer's key set is within ORCID's samples' key set.
   **Found by the four-way check:** 6 JSON documents Rust and Zig
   wrote failed to read in Java, all for `"visibility"` inside `history`
   (`record-3.0`, `history-3.0`, `record-no-city-country-for-professional-activities-3.0`,
   by Rust and by Zig). **2026-10-18:** the JSON
   writers leave `history/@visibility` out (#4; CROSSCHECK.md #16), so
   `J reads written JSON` should be all same, 75/75.

8. **Group-id records:** ORCID's `GroupIdRecord` reads
   `peer-review-group-id.json`. DuckDB has `orcid_group_ids`; since
   2026-10-18 Rust and Zig model, read and write group-id
   records and give the same `group_ids` rows. Known gap #7 is closed.

## Writing (bytes, informational)

9. ORCID's marshaller writes `standalone="yes"`, declares all 28 namespaces
   of the record package on the root, used or not, and indents with four
   spaces. Ours declare only the namespaces used and indent with two spaces
   or tabs. The forms are namespace-equivalent. Nothing to change.

## Validation

*Historical (2026-10-18): the payload validation of yorc-rs, yorc-zig
and yorc-duckdb compared below was removed with Member API write support
(Member API access is out of scope for the public packages); the `validation` and `J XSD
validation` classes and the probes are gone from the cross-check.*

10. **ORCID's model-level validation is the XSD, and the XSD does not hold
    ORCID's vocabularies.** Raw document validated as ORCID's API does it:

    | edit | ORCID XSD | Rust/Zig create mode |
    |---|---|---|
    | no title | rejected | rejected |
    | year 1850 / month 13 | rejected | rejected |
    | 1001-char title | rejected (maxLength) | rejected |
    | contributor path `0000-0001-5109-37` | rejected (pattern) | rejected |
    | empty `<work:journal-title/>` | rejected (non-blank pattern) | accepted (empty = absent) |
    | type `poem` | **accepted** (no enumeration) | rejected |
    | relationship `sibling` / padded `self` | **accepted** (`xs:string`) | rejected / accepted (trimmed) |
    | put-code on create | **accepted** (API rule) | rejected |

    The vocabulary, put-code and mode rules live in ORCID-Source's orcid-core
    (`ActivityValidator`, `ExternalIDValidator`), not in the jar. On the
    JSON path ORCID validates the model after Jackson's read, so an unknown
    vocabulary value is already null: `"type": "poem"` is reported as a
    missing type. *Suggestions:* (a) Rust/Zig: optionally reject a present
    but empty element where the XSD's non-blank pattern applies, instead of
    reading it as absent. (b) yorc-duckdb: its writers lack the XSD's length
    and pattern rules (CROSSCHECK.md §7); see `J XSD validation (info)`.

11. Bulk: ORCID's API skips the XSD for `bulk:bulk` and checks works with
    orcid-core's rules. The Java program uses `bulk-3.0.xsd`, which is
    stricter than ORCID's API.

## Not available in ORCID's library

No iD normaliser, rows, dump reader, reservoir sampler, HTTP client or OAuth
code in the model jar (it depends on httpclient5 and `jakarta.ws.rs-api` but
does not use them). Where yorc has these, only ORCID's documentation can
serve as a reference.
