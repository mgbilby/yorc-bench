package yorc.bench.orcid;

import static java.nio.charset.StandardCharsets.UTF_8;

import java.io.BufferedInputStream;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.EOFException;
import java.io.IOException;
import java.io.InputStream;
import java.io.PrintStream;
import java.net.URL;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.TimeZone;
import java.util.stream.Stream;
import java.util.zip.GZIPInputStream;

import javax.xml.XMLConstants;
import javax.xml.stream.XMLInputFactory;
import javax.xml.stream.XMLStreamConstants;
import javax.xml.stream.XMLStreamReader;
import javax.xml.transform.stream.StreamSource;
import javax.xml.validation.Schema;
import javax.xml.validation.SchemaFactory;
import javax.xml.validation.Validator;

import org.orcid.jaxb.model.record.bulk.BulkElement;
import org.orcid.jaxb.model.v3.release.error.OrcidError;
import org.orcid.jaxb.model.v3.release.groupid.GroupIdRecord;
import org.orcid.jaxb.model.v3.release.record.Address;
import org.orcid.jaxb.model.v3.release.record.Addresses;
import org.orcid.jaxb.model.v3.release.record.Biography;
import org.orcid.jaxb.model.v3.release.record.CreditName;
import org.orcid.jaxb.model.v3.release.record.Distinction;
import org.orcid.jaxb.model.v3.release.record.Education;
import org.orcid.jaxb.model.v3.release.record.Email;
import org.orcid.jaxb.model.v3.release.record.Emails;
import org.orcid.jaxb.model.v3.release.record.Employment;
import org.orcid.jaxb.model.v3.release.record.Funding;
import org.orcid.jaxb.model.v3.release.record.History;
import org.orcid.jaxb.model.v3.release.record.InvitedPosition;
import org.orcid.jaxb.model.v3.release.record.Keyword;
import org.orcid.jaxb.model.v3.release.record.Keywords;
import org.orcid.jaxb.model.v3.release.record.Membership;
import org.orcid.jaxb.model.v3.release.record.Name;
import org.orcid.jaxb.model.v3.release.record.OtherName;
import org.orcid.jaxb.model.v3.release.record.OtherNames;
import org.orcid.jaxb.model.v3.release.record.PeerReview;
import org.orcid.jaxb.model.v3.release.record.Person;
import org.orcid.jaxb.model.v3.release.record.PersonExternalIdentifier;
import org.orcid.jaxb.model.v3.release.record.PersonExternalIdentifiers;
import org.orcid.jaxb.model.v3.release.record.PersonalDetails;
import org.orcid.jaxb.model.v3.release.record.Preferences;
import org.orcid.jaxb.model.v3.release.record.Qualification;
import org.orcid.jaxb.model.v3.release.record.Record;
import org.orcid.jaxb.model.v3.release.record.ResearchResource;
import org.orcid.jaxb.model.v3.release.record.ResearcherUrl;
import org.orcid.jaxb.model.v3.release.record.ResearcherUrls;
import org.orcid.jaxb.model.v3.release.record.Service;
import org.orcid.jaxb.model.v3.release.record.Work;
import org.orcid.jaxb.model.v3.release.record.WorkBulk;
import org.orcid.jaxb.model.v3.release.record.summary.ActivitiesSummary;
import org.orcid.jaxb.model.v3.release.record.summary.DistinctionSummary;
import org.orcid.jaxb.model.v3.release.record.summary.Distinctions;
import org.orcid.jaxb.model.v3.release.record.summary.EducationSummary;
import org.orcid.jaxb.model.v3.release.record.summary.Educations;
import org.orcid.jaxb.model.v3.release.record.summary.EmploymentSummary;
import org.orcid.jaxb.model.v3.release.record.summary.Employments;
import org.orcid.jaxb.model.v3.release.record.summary.FundingSummary;
import org.orcid.jaxb.model.v3.release.record.summary.Fundings;
import org.orcid.jaxb.model.v3.release.record.summary.InvitedPositionSummary;
import org.orcid.jaxb.model.v3.release.record.summary.InvitedPositions;
import org.orcid.jaxb.model.v3.release.record.summary.MembershipSummary;
import org.orcid.jaxb.model.v3.release.record.summary.Memberships;
import org.orcid.jaxb.model.v3.release.record.summary.PeerReviewSummary;
import org.orcid.jaxb.model.v3.release.record.summary.PeerReviews;
import org.orcid.jaxb.model.v3.release.record.summary.QualificationSummary;
import org.orcid.jaxb.model.v3.release.record.summary.Qualifications;
import org.orcid.jaxb.model.v3.release.record.summary.ResearchResources;
import org.orcid.jaxb.model.v3.release.record.summary.ServiceSummary;
import org.orcid.jaxb.model.v3.release.record.summary.Services;
import org.orcid.jaxb.model.v3.release.record.summary.WorkSummary;
import org.orcid.jaxb.model.v3.release.record.summary.Works;
import org.orcid.jaxb.model.v3.release.search.Search;
import org.orcid.jaxb.model.v3.release.search.expanded.ExpandedSearch;
import org.xml.sax.ErrorHandler;
import org.xml.sax.SAXParseException;

import com.fasterxml.jackson.databind.AnnotationIntrospector;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.databind.introspect.JacksonAnnotationIntrospector;
import com.fasterxml.jackson.module.jakarta.xmlbind.JakartaXmlBindAnnotationIntrospector;

import jakarta.xml.bind.JAXBContext;
import jakarta.xml.bind.JAXBElement;
import jakarta.xml.bind.JAXBException;
import jakarta.xml.bind.Marshaller;
import jakarta.xml.bind.Unmarshaller;
import jakarta.xml.bind.util.JAXBSource;

/**
 * ORCID's Java orcid-model (org.orcid:orcid-model:4.0.2, the JAXB classes of
 * ORCID's v3.0 message schema) as the baseline of the yorc-bench comparison.
 *
 * <pre>
 * java -jar orcid-libs-bench-java.jar [--root DIR] [--iters N] [--dump-iters N] [--warmup N]
 *                                     [--warmup-ms MS] [--only W,W] [--dump PATH | PATH]
 * java -jar orcid-libs-bench-java.jar --emit OUT_DIR [--root DIR] [--dump PATH | PATH]
 * java -jar orcid-libs-bench-java.jar --reread DIR --emit OUT_DIR
 * </pre>
 *
 * Benchmark mode prints the same JSON lines as the Rust and Zig programs
 * (rust/src/main.rs, zig/src/main.zig), for the
 * workloads ORCID's library can do. Emit mode writes the part of the
 * cross-check tree Java can produce (./compare.sh, --only ...,java).
 * Re-read mode reads every .xml and .json file below DIR (what the other
 * implementations wrote, staged by compare3.py) with ORCID's classes, as
 * ORCID's API would: OUT_DIR/&lt;path&gt;.accept.txt says whether it read and
 * whether it passes ORCID's XSD check.
 *
 * XML is JAXB, configured as ORCID's API configures it (ORCID-Source
 * orcid-api-common OrcidMarshallerContextResolver: one JAXBContext per root
 * class, JAXB_FORMATTED_OUTPUT). JSON is Jackson, configured as ORCID's JSON
 * provider (OrcidJacksonJaxbJsonProviderPretty, which extends
 * JacksonXmlBindJsonProvider): see {@link #orcidMapper()}. Validation is the
 * XSD check ORCID's API runs on payloads (JAXBSource + javax.xml.validation,
 * JSONInputValidator / OrcidValidationJaxbContextResolver). There is no iD
 * utility and no rows or dump reader in ORCID's model jar: those are not
 * hand-rolled here.
 */
public final class Main {
    static final String IMPL = "java";
    static final String FIXTURE = "yorc-rs/tests/data/0000-0003-0100-6634.xml";
    static final String SAMPLES = "yorc-rs/reference/orcid-model/record_3.0/samples";
    static final String DUMP = "yorc-zig/testdata/dump/orcid_test_summaries.tgz";
    static final byte[] ERROR = "error\n".getBytes(UTF_8);
    static final String NS = "http://www.orcid.org/ns/";

    /** Workloads in output order, with their default iteration counts (as in Rust and Zig). */
    static final Map<String, Long> WORKLOADS = new LinkedHashMap<>();
    static {
        WORKLOADS.put("id_normalize", 200L);
        WORKLOADS.put("xml_read_record", 30L);
        WORKLOADS.put("xml_write_record", 30L);
        WORKLOADS.put("json_write_record", 30L);
        WORKLOADS.put("json_read_record", 30L);
        WORKLOADS.put("rows_record", 30L);
        WORKLOADS.put("sha256", 300L);
        WORKLOADS.put("dump_stream", 20L);
        // appended on 2026-10-18, as in the Rust and Zig programs
        WORKLOADS.put("group_ids_read", 1000L);
        WORKLOADS.put("timeline_record", 30L);
        WORKLOADS.put("changes_record", 30L);
        WORKLOADS.put("dump_sample", 20L);
    }

    /** The group-id document of group_ids_read: ORCID's JSON write sample, read into GroupIdRecord. */
    static final String GROUP_ID_JSON = SAMPLES + "/write_samples/peer-review-group-id.json";

    /** Workloads ORCID's library has no feature for; never timed. */
    static final Map<String, String> NOT_AVAILABLE = Map.of(
            "id_normalize", "orcid-model has no ORCID iD utility (OrcidIdBase is a bean)",
            "rows_record", "orcid-model has no rows/flattening",
            "timeline_record", "orcid-model has no timeline (it has the dates, not the events)",
            "changes_record", "orcid-model has no snapshot diff",
            "dump_sample", "orcid-model has no dump reader or sampler");

    static final String USAGE = "usage: java -jar orcid-libs-bench-java.jar [--root DIR] [--iters N] [--dump-iters N] "
            + "[--warmup N] [--warmup-ms MS] [--only W,W] [--dump PATH | PATH]\n"
            + "       java -jar orcid-libs-bench-java.jar --emit OUT_DIR [--root DIR] [--dump PATH | PATH]\n"
            + "       java -jar orcid-libs-bench-java.jar --reread DIR --emit OUT_DIR";

    // ------------------------------------------------------------------ args

    static final class Args {
        Path root = Path.of(".");
        Path emit;
        Path reread;
        Path dump;
        Long iters;
        Long dumpIters;
        long warmup = 2;
        long warmupMs = 3000;
        List<String> only;
    }

    static final class UsageException extends Exception {
        private static final long serialVersionUID = 1L;

        UsageException(String m) {
            super(m);
        }
    }

    static String value(String[] argv, int i, String flag) throws UsageException {
        if (i >= argv.length) {
            throw new UsageException(flag + " needs a value");
        }
        return argv[i];
    }

    static long number(String s, String flag) throws UsageException {
        try {
            long n = Long.parseLong(s);
            if (n < 0) {
                throw new NumberFormatException();
            }
            return n;
        } catch (NumberFormatException e) {
            throw new UsageException(flag + ": not a number: " + s);
        }
    }

    static Args parseArgs(String[] argv) throws UsageException {
        Args a = new Args();
        for (int i = 0; i < argv.length; i++) {
            String arg = argv[i];
            switch (arg) {
                case "-h", "--help" -> throw new UsageException("");
                case "--root" -> a.root = Path.of(value(argv, ++i, arg));
                case "--emit" -> a.emit = Path.of(value(argv, ++i, arg));
                case "--reread" -> a.reread = Path.of(value(argv, ++i, arg));
                case "--dump" -> a.dump = Path.of(value(argv, ++i, arg));
                case "--iters" -> a.iters = number(value(argv, ++i, arg), arg);
                case "--dump-iters" -> a.dumpIters = number(value(argv, ++i, arg), arg);
                case "--warmup" -> a.warmup = number(value(argv, ++i, arg), arg);
                case "--warmup-ms" -> a.warmupMs = number(value(argv, ++i, arg), arg);
                case "--only" -> a.only = List.of(value(argv, ++i, arg).split(","));
                default -> {
                    if (arg.startsWith("-")) {
                        throw new UsageException("unknown argument: " + arg);
                    }
                    a.dump = Path.of(arg);
                }
            }
        }
        if (a.reread != null && a.emit == null) {
            throw new UsageException("--reread needs --emit OUT_DIR");
        }
        if (a.only != null) {
            for (String w : a.only) {
                if (!WORKLOADS.containsKey(w)) {
                    throw new UsageException("unknown workload: " + w);
                }
            }
        }
        return a;
    }

    public static void main(String[] argv) {
        // Timestamps read from JSON come back in Jackson's default zone (UTC);
        // fix the JVM default as well so that nothing depends on the host.
        TimeZone.setDefault(TimeZone.getTimeZone("UTC"));
        Locale.setDefault(Locale.ROOT);
        Args args;
        try {
            args = parseArgs(argv);
        } catch (UsageException e) {
            if (!e.getMessage().isEmpty()) {
                System.err.println("orcid-libs-bench-java: " + e.getMessage());
            }
            System.err.println(USAGE);
            System.exit(2);
            return;
        }
        try {
            if (args.reread != null) {
                reread(args.reread, args.emit);
            } else if (args.emit != null) {
                emit(args, args.emit);
            } else {
                run(args);
            }
        } catch (Exception e) {
            System.err.println("orcid-libs-bench-java: " + e);
            System.exit(1);
        }
    }

    // ------------------------------------------------------- ORCID's setup

    /**
     * Jackson configured as ORCID's API configures it for JSON.
     *
     * ORCID-Source orcid-api-common registers OrcidJacksonJaxbJsonProvider
     * (application/json) and OrcidJacksonJaxbJsonProviderPretty
     * (application/vnd.orcid+json, application/orcid+json), both
     * {@code extends JacksonXmlBindJsonProvider} with jackson.version 2.15.4.
     * That provider's default constructor builds {@code new ObjectMapper()}
     * with the annotation introspector pair (Jackson first, then
     * Jakarta XML Bind: JacksonXmlBindJsonProvider.DEFAULT_ANNOTATIONS,
     * JsonMapperConfigurator._resolveIntrospectors), and ORCID's
     * configureAll() sets ACCEPT_SINGLE_VALUE_AS_ARRAY = true and
     * INDENT_OUTPUT = true (Pretty) or false. The Pretty variant is used here:
     * vnd.orcid+json is the media type ORCID documents. Everything else is
     * Jackson's default: nulls are written (the XML-bind introspector has no
     * non-nillable inclusion set), FAIL_ON_UNKNOWN_PROPERTIES stays on,
     * WRITE_DATES_AS_TIMESTAMPS stays on (XMLGregorianCalendar as epoch
     * milliseconds), property order is the JAXB propOrder.
     */
    static ObjectMapper orcidMapper() {
        ObjectMapper m = new ObjectMapper();
        m.setAnnotationIntrospector(AnnotationIntrospector.pair(
                new JacksonAnnotationIntrospector(), new JakartaXmlBindAnnotationIntrospector()));
        m.configure(DeserializationFeature.ACCEPT_SINGLE_VALUE_AS_ARRAY, true);
        m.configure(SerializationFeature.INDENT_OUTPUT, true);
        return m;
    }

    static final ObjectMapper JSON = orcidMapper();

    /** One JAXBContext per root class, as ORCID's OrcidMarshallerContextResolver creates them. */
    static final Map<Class<?>, JAXBContext> CONTEXTS = new HashMap<>();

    static JAXBContext context(Class<?> c) throws JAXBException {
        JAXBContext ctx = CONTEXTS.get(c);
        if (ctx == null) {
            ctx = JAXBContext.newInstance(c);
            CONTEXTS.put(c, ctx);
        }
        return ctx;
    }

    static Object unmarshal(Class<?> c, byte[] bytes) throws JAXBException {
        Unmarshaller u = context(c).createUnmarshaller();
        Object o = u.unmarshal(new ByteArrayInputStream(bytes));
        return o instanceof JAXBElement<?> e ? e.getValue() : o;
    }

    static byte[] marshal(Object o) throws JAXBException {
        Marshaller m = context(o.getClass()).createMarshaller();
        m.setProperty(Marshaller.JAXB_FORMATTED_OUTPUT, Boolean.TRUE);
        ByteArrayOutputStream out = new ByteArrayOutputStream(1 << 16);
        m.marshal(o, out);
        return out.toByteArray();
    }

    /** Document roots (namespace + local name) and the class ORCID unmarshals them to. */
    static final Map<String, Class<?>> ROOTS = new HashMap<>();

    static void root(String ns, String local, Class<?> c) {
        ROOTS.put("{" + NS + ns + "}" + local, c);
    }

    static {
        root("record", "record", Record.class);
        root("activities", "activities-summary", ActivitiesSummary.class);
        root("activities", "works", Works.class);
        root("activities", "fundings", Fundings.class);
        root("activities", "educations", Educations.class);
        root("activities", "employments", Employments.class);
        root("activities", "distinctions", Distinctions.class);
        root("activities", "invited-positions", InvitedPositions.class);
        root("activities", "memberships", Memberships.class);
        root("activities", "qualifications", Qualifications.class);
        root("activities", "services", Services.class);
        root("activities", "peer-reviews", PeerReviews.class);
        root("activities", "research-resources", ResearchResources.class);
        root("work", "work", Work.class);
        root("work", "work-summary", WorkSummary.class);
        root("bulk", "bulk", WorkBulk.class);
        root("funding", "funding", Funding.class);
        root("funding", "summary", FundingSummary.class);
        root("education", "education", Education.class);
        root("education", "education-summary", EducationSummary.class);
        root("employment", "employment", Employment.class);
        root("employment", "employment-summary", EmploymentSummary.class);
        root("distinction", "distinction", Distinction.class);
        root("distinction", "distinction-summary", DistinctionSummary.class);
        root("invited-position", "invited-position", InvitedPosition.class);
        root("invited-position", "invited-position-summary", InvitedPositionSummary.class);
        root("membership", "membership", Membership.class);
        root("membership", "membership-summary", MembershipSummary.class);
        root("qualification", "qualification", Qualification.class);
        root("qualification", "qualification-summary", QualificationSummary.class);
        root("service", "service", Service.class);
        root("service", "service-summary", ServiceSummary.class);
        root("peer-review", "peer-review", PeerReview.class);
        root("peer-review", "summary", PeerReviewSummary.class);
        // research-resource is also ResearchResourceSummary's root name; the
        // documents with that root are the full form.
        root("research-resource", "research-resource", ResearchResource.class);
        root("person", "person", Person.class);
        root("personal-details", "personal-details", PersonalDetails.class);
        root("personal-details", "name", Name.class);
        root("personal-details", "biography", Biography.class);
        root("personal-details", "credit-name", CreditName.class);
        root("other-name", "other-names", OtherNames.class);
        root("other-name", "other-name", OtherName.class);
        root("researcher-url", "researcher-urls", ResearcherUrls.class);
        root("researcher-url", "researcher-url", ResearcherUrl.class);
        root("email", "emails", Emails.class);
        root("email", "email", Email.class);
        root("address", "addresses", Addresses.class);
        root("address", "address", Address.class);
        root("keyword", "keywords", Keywords.class);
        root("keyword", "keyword", Keyword.class);
        root("external-identifier", "external-identifiers", PersonExternalIdentifiers.class);
        root("external-identifier", "external-identifier", PersonExternalIdentifier.class);
        root("history", "history", History.class);
        root("preferences", "preferences", Preferences.class);
        root("error", "error", OrcidError.class);
        root("search", "search", Search.class);
        root("expanded-search", "expanded-search", ExpandedSearch.class);
        root("group-id", "group-id-record", GroupIdRecord.class);
    }

    static final XMLInputFactory STAX = XMLInputFactory.newFactory();
    static {
        STAX.setProperty(XMLInputFactory.SUPPORT_DTD, Boolean.FALSE);
        STAX.setProperty(XMLInputFactory.IS_SUPPORTING_EXTERNAL_ENTITIES, Boolean.FALSE);
    }

    /** The class for the document element of an XML document, or null. */
    static Class<?> rootClass(byte[] bytes) {
        try {
            XMLStreamReader r = STAX.createXMLStreamReader(new ByteArrayInputStream(bytes));
            try {
                while (r.hasNext()) {
                    if (r.next() == XMLStreamConstants.START_ELEMENT) {
                        String ns = r.getNamespaceURI();
                        return ROOTS.get("{" + (ns == null ? "" : ns) + "}" + r.getLocalName());
                    }
                }
            } finally {
                r.close();
            }
        } catch (Exception e) {
            return null;
        }
        return null;
    }

    /**
     * The XSD ORCID validates a payload class against (ORCID-Source
     * JSONInputValidator.SCHEMA_LOCATIONS and OrcidValidationJaxbContextResolver
     * SCHEMA_FILENAME_PREFIX_BY_CLASS_V3_0). WorkBulk is not validated by
     * ORCID's resolver (its works go through orcid-core's ActivityValidator);
     * bulk-3.0.xsd, which the jar ships, is used for it here.
     */
    static final Map<Class<?>, String> XSD = new HashMap<>();
    static {
        XSD.put(Work.class, "record_3.0/work-3.0.xsd");
        XSD.put(WorkBulk.class, "record_3.0/bulk-3.0.xsd");
        XSD.put(Funding.class, "record_3.0/funding-3.0.xsd");
        XSD.put(Education.class, "record_3.0/education-3.0.xsd");
        XSD.put(Employment.class, "record_3.0/employment-3.0.xsd");
        XSD.put(Distinction.class, "record_3.0/distinction-3.0.xsd");
        XSD.put(InvitedPosition.class, "record_3.0/invited-position-3.0.xsd");
        XSD.put(Membership.class, "record_3.0/membership-3.0.xsd");
        XSD.put(Qualification.class, "record_3.0/qualification-3.0.xsd");
        XSD.put(Service.class, "record_3.0/service-3.0.xsd");
        XSD.put(PeerReview.class, "record_3.0/peer-review-3.0.xsd");
        XSD.put(ResearchResource.class, "record_3.0/research-resource-3.0.xsd");
        XSD.put(ResearcherUrl.class, "record_3.0/researcher-url-3.0.xsd");
        XSD.put(ResearcherUrls.class, "record_3.0/researcher-url-3.0.xsd");
        XSD.put(OtherName.class, "record_3.0/other-name-3.0.xsd");
        XSD.put(OtherNames.class, "record_3.0/other-name-3.0.xsd");
        XSD.put(PersonExternalIdentifier.class, "record_3.0/person-external-identifier-3.0.xsd");
        XSD.put(PersonExternalIdentifiers.class, "record_3.0/person-external-identifier-3.0.xsd");
        XSD.put(Keyword.class, "record_3.0/keyword-3.0.xsd");
        XSD.put(Keywords.class, "record_3.0/keyword-3.0.xsd");
        XSD.put(Address.class, "record_3.0/address-3.0.xsd");
        XSD.put(Addresses.class, "record_3.0/address-3.0.xsd");
        XSD.put(Email.class, "record_3.0/email-3.0.xsd");
        XSD.put(Name.class, "record_3.0/personal-details-3.0.xsd");
        XSD.put(GroupIdRecord.class, "group-id-3.0/group-id-3.0.xsd");
    }

    static final Map<String, Schema> SCHEMAS = new HashMap<>();

    /** A schema from orcid-model's jar, by its systemId so that relative imports resolve. */
    static Schema schema(String path) throws Exception {
        Schema s = SCHEMAS.get(path);
        if (s == null) {
            URL url = Work.class.getClassLoader().getResource(path);
            if (url == null) {
                throw new IOException("schema not on the classpath: " + path);
            }
            SchemaFactory sf = SchemaFactory.newInstance(XMLConstants.W3C_XML_SCHEMA_NS_URI);
            s = sf.newSchema(new StreamSource(url.toExternalForm()));
            SCHEMAS.put(path, s);
        }
        return s;
    }

    /** Collects every error and fatal error; warnings are ignored. */
    static final class Collect implements ErrorHandler {
        final List<String> errors = new ArrayList<>();

        @Override
        public void warning(SAXParseException e) {
        }

        @Override
        public void error(SAXParseException e) {
            errors.add(e.getMessage());
        }

        @Override
        public void fatalError(SAXParseException e) {
            errors.add(e.getMessage());
        }
    }

    /**
     * ORCID's XSD check of an XML payload: the document itself is validated
     * against the class's XSD, as ORCID's API does by setting the schema on
     * the unmarshaller (OrcidValidationJaxbContextResolver). Returns the
     * messages (empty: valid).
     */
    static List<String> xsdErrorsXml(byte[] document, Schema schema) throws Exception {
        Validator v = schema.newValidator();
        Collect c = new Collect();
        v.setErrorHandler(c);
        try {
            v.validate(new StreamSource(new ByteArrayInputStream(document)));
        } catch (org.xml.sax.SAXException e) {
            if (c.errors.isEmpty()) {
                c.errors.add(String.valueOf(e.getMessage()));
            }
        }
        return c.errors;
    }

    /**
     * ORCID's XSD check of a payload read from JSON (JSONInputValidator):
     * the model is marshalled through a JAXBSource and checked against the
     * class's XSD. Values the model could not hold (an unknown enum value,
     * for one) are already gone at that point. Returns the messages (empty: valid).
     */
    static List<String> xsdErrors(Object payload, Schema schema) throws Exception {
        Validator v = schema.newValidator();
        Collect c = new Collect();
        v.setErrorHandler(c);
        try {
            v.validate(new JAXBSource(context(payload.getClass()), payload));
        } catch (org.xml.sax.SAXException e) {
            if (c.errors.isEmpty()) {
                c.errors.add(String.valueOf(e.getMessage()));
            }
        }
        return c.errors;
    }

    // ---------------------------------------------------------------- inputs

    static byte[] read(Path p) throws IOException {
        try {
            return Files.readAllBytes(p);
        } catch (IOException e) {
            throw new IOException(p + ": " + e.getMessage(), e);
        }
    }

    /** Files with extension {@code ext} in {@code dir}, sorted by name (byte order, as Rust and Zig). */
    static List<Path> files(Path dir, String ext) throws IOException {
        List<Path> out = new ArrayList<>();
        try (Stream<Path> s = Files.list(dir)) {
            s.filter(p -> Files.isRegularFile(p) && p.getFileName().toString().endsWith("." + ext)).forEach(out::add);
        }
        out.sort((x, y) -> compareBytes(x.getFileName().toString(), y.getFileName().toString()));
        return out;
    }

    static int compareBytes(String a, String b) {
        byte[] x = a.getBytes(UTF_8);
        byte[] y = b.getBytes(UTF_8);
        return java.util.Arrays.compareUnsigned(x, y);
    }

    static String stem(Path p) {
        String n = p.getFileName().toString();
        int dot = n.lastIndexOf('.');
        return dot > 0 ? n.substring(0, dot) : n;
    }

    static Path dumpPath(Args a) {
        return a.dump != null ? a.dump : a.root.resolve(DUMP);
    }

    static String sha256Hex(byte[] b) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(b));
    }

    // ------------------------------------------------------------------ tar

    /** One member of a tar stream: its path (pax / GNU long names applied), type and size. */
    record TarEntry(String path, byte type, long size) {
        boolean isFile() {
            return type == '0' || type == 0;
        }
    }

    /**
     * A minimal tar reader over a decompressed stream: ustar (with prefix),
     * GNU long names ('L'), pax extended headers ('x', path and size), and
     * base-256 sizes. Global pax headers ('g') and long link names ('K') are
     * skipped. Enough for ORCID's dumps and yorc's archives.
     */
    static final class Tar {
        final InputStream in;
        long remaining; // data bytes of the current entry not read yet
        long padding;   // padding after them

        Tar(InputStream in) {
            this.in = in;
        }

        void readFully(byte[] b, int off, int len) throws IOException {
            while (len > 0) {
                int n = in.read(b, off, len);
                if (n < 0) {
                    throw new EOFException("truncated tar stream");
                }
                off += n;
                len -= n;
            }
        }

        void skip(long n) throws IOException {
            byte[] buf = new byte[8192];
            while (n > 0) {
                int k = (int) Math.min(buf.length, n);
                readFully(buf, 0, k);
                n -= k;
            }
        }

        static String cstr(byte[] h, int off, int len) {
            int end = off;
            while (end < off + len && h[end] != 0) {
                end++;
            }
            return new String(h, off, end - off, UTF_8);
        }

        static long size(byte[] h) throws IOException {
            if ((h[124] & 0x80) != 0) { // base-256
                long v = 0;
                for (int i = 125; i < 136; i++) {
                    v = (v << 8) | (h[i] & 0xff);
                }
                return v;
            }
            String s = cstr(h, 124, 12).trim();
            if (s.isEmpty()) {
                return 0;
            }
            try {
                return Long.parseLong(s, 8);
            } catch (NumberFormatException e) {
                throw new IOException("bad tar size field: " + s);
            }
        }

        byte[] data(long size) throws IOException {
            if (size > Integer.MAX_VALUE - 16) {
                throw new IOException("tar member too large: " + size);
            }
            byte[] b = new byte[(int) size];
            readFully(b, 0, b.length);
            return b;
        }

        /** The next header, or null at the end of the archive. Skips what the previous entry left. */
        TarEntry next() throws IOException {
            skip(remaining + padding);
            remaining = 0;
            padding = 0;
            String longName = null;
            String paxPath = null;
            long paxSize = -1;
            byte[] h = new byte[512];
            while (true) {
                int got = 0;
                while (got < 512) {
                    int n = in.read(h, got, 512 - got);
                    if (n < 0) {
                        if (got == 0) {
                            return null;
                        }
                        throw new EOFException("truncated tar header");
                    }
                    got += n;
                }
                boolean zero = true;
                for (byte x : h) {
                    if (x != 0) {
                        zero = false;
                        break;
                    }
                }
                if (zero) {
                    return null;
                }
                long size = size(h);
                long pad = (512 - (size % 512)) % 512;
                byte type = h[156];
                if (type == 'L') {
                    longName = cstr(data(size), 0, (int) size);
                    skip(pad);
                    continue;
                }
                if (type == 'x') {
                    String pax = new String(data(size), UTF_8);
                    skip(pad);
                    int i = 0;
                    while (i < pax.length()) {
                        int sp = pax.indexOf(' ', i);
                        if (sp < 0) {
                            break;
                        }
                        int len = Integer.parseInt(pax.substring(i, sp));
                        String rec = pax.substring(sp + 1, i + len - 1); // without the trailing \n
                        int eq = rec.indexOf('=');
                        if (eq > 0) {
                            String k = rec.substring(0, eq);
                            String v = rec.substring(eq + 1);
                            if (k.equals("path")) {
                                paxPath = v;
                            } else if (k.equals("size")) {
                                paxSize = Long.parseLong(v);
                            }
                        }
                        i += len;
                    }
                    continue;
                }
                if (type == 'g' || type == 'K') {
                    skip(size + pad);
                    continue;
                }
                String name = cstr(h, 0, 100);
                // POSIX ustar ("ustar\0" "00") has a prefix; GNU ("ustar  \0") uses those bytes otherwise.
                if (h[257] == 'u' && h[258] == 's' && h[259] == 't' && h[260] == 'a' && h[261] == 'r' && h[262] == 0) {
                    String prefix = cstr(h, 345, 155);
                    if (!prefix.isEmpty()) {
                        name = prefix + "/" + name;
                    }
                }
                if (longName != null) {
                    name = longName;
                }
                if (paxPath != null) {
                    name = paxPath;
                }
                if (paxSize >= 0) {
                    size = paxSize;
                    pad = (512 - (size % 512)) % 512;
                }
                remaining = size;
                padding = pad;
                return new TarEntry(name, type, size);
            }
        }

        /** The data of the current entry. */
        byte[] read(TarEntry e) throws IOException {
            byte[] b = data(e.size());
            remaining = 0;
            return b;
        }
    }

    static InputStream openDump(Path p) throws IOException {
        // GZIPInputStream reads concatenated gzip members, as Rust's MultiGzDecoder does.
        return new BufferedInputStream(new GZIPInputStream(Files.newInputStream(p), 1 << 16), 1 << 16);
    }

    /** The stem of a member path ending in .xml (case-insensitive), or null: Rust's xml_entry_stem. */
    static String xmlStem(String path) {
        String name = path.substring(path.lastIndexOf('/') + 1);
        if (name.length() > 4 && name.substring(name.length() - 4).equalsIgnoreCase(".xml")) {
            return name.substring(0, name.length() - 4);
        }
        return null;
    }

    /** A member path without empty and "." parts; "" if it has "..": compare3.py's member_path. */
    static String memberPath(String path) {
        List<String> parts = new ArrayList<>();
        for (String p : path.replace('\\', '/').split("/")) {
            if (p.isEmpty() || p.equals(".")) {
                continue;
            }
            if (p.equals("..")) {
                return "";
            }
            parts.add(p);
        }
        return String.join("/", parts);
    }

    // ------------------------------------------------------------ benchmarks

    static volatile long sink;

    static void consume(long v) {
        sink ^= v;
    }

    @FunctionalInterface
    interface Op {
        long run() throws Exception;
    }

    static void report(PrintStream out, String name, long iters, long bytes, long totalNs) {
        long nsPerOp = iters == 0 ? 0 : totalNs / iters;
        double mb = totalNs == 0 ? 0.0 : (double) bytes * (double) iters * 1e3 / (double) totalNs;
        out.println(String.format(Locale.ROOT,
                "{\"impl\":\"%s\",\"workload\":\"%s\",\"iterations\":%d,\"bytes\":%d,\"total_ns\":%d,"
                        + "\"ns_per_op\":%d,\"mb_per_s\":%.2f}",
                IMPL, name, iters, bytes, totalNs, nsPerOp, mb));
        out.flush();
    }

    /**
     * Warm-up (at least {@code warmIters} untimed runs and at least
     * {@code warmMs} of them, for the JIT), a full GC, then {@code iters}
     * timed runs with System.nanoTime.
     */
    static void bench(PrintStream out, String name, long iters, long warmIters, long warmMs, long bytes, Op op) {
        try {
            long t0 = System.nanoTime();
            long deadline = t0 + warmMs * 1_000_000L;
            long n = 0;
            while (n < warmIters || System.nanoTime() < deadline) {
                consume(op.run());
                n++;
            }
            long warmNs = System.nanoTime() - t0;
            System.gc();
            long start = System.nanoTime();
            for (long i = 0; i < iters; i++) {
                consume(op.run());
            }
            long total = System.nanoTime() - start;
            System.err.printf(Locale.ROOT, "%s: %s: %d warm-up runs in %d ms%n", IMPL, name, n, warmNs / 1_000_000L);
            report(out, name, iters, bytes, total);
        } catch (Exception e) {
            System.err.println("orcid-libs-bench-java: " + name + ": " + e);
            System.exit(1);
        }
    }

    record DumpTotals(long members, long bytes) {
    }

    /** One pass over a dump: unmarshal every .xml member (a record or an error document). */
    static DumpTotals streamDump(Path path, JAXBContext ctx) throws Exception {
        long n = 0;
        long bytes = 0;
        Unmarshaller u = ctx.createUnmarshaller();
        try (InputStream in = openDump(path)) {
            Tar tar = new Tar(in);
            TarEntry e;
            while ((e = tar.next()) != null) {
                if (!e.isFile() || xmlStem(e.path()) == null) {
                    continue;
                }
                byte[] b = tar.read(e);
                Object o = u.unmarshal(new ByteArrayInputStream(b));
                consume(o.hashCode() == 0 ? 1 : 0);
                n++;
                bytes += b.length;
            }
        }
        return new DumpTotals(n, bytes);
    }

    static void run(Args args) throws Exception {
        byte[] fixture = read(args.root.resolve(FIXTURE));
        JAXBContext recordCtx = context(Record.class);
        // dump members are records or, for locked and deprecated iDs, error documents
        // (the corpus has both); Rust and Zig read either root
        JAXBContext dumpCtx = JAXBContext.newInstance(Record.class, OrcidError.class);
        Record doc = (Record) unmarshal(Record.class, fixture);
        byte[] xmlText = marshal(doc);
        byte[] jsonText = JSON.writeValueAsBytes(doc);
        byte[] groupId = read(args.root.resolve(GROUP_ID_JSON));
        Path dump = dumpPath(args);
        System.err.printf(Locale.ROOT, "%s: fixture %d B, XML out %d B, JSON out %d B%n",
                IMPL, fixture.length, xmlText.length, jsonText.length);

        PrintStream out = System.out;
        long w = args.warmup;
        long wm = args.warmupMs;
        for (Map.Entry<String, Long> wl : WORKLOADS.entrySet()) {
            String name = wl.getKey();
            if (args.only != null && !args.only.contains(name)) {
                continue;
            }
            if (NOT_AVAILABLE.containsKey(name)) {
                System.err.printf("%s: %s: n/a (%s)%n", IMPL, name, NOT_AVAILABLE.get(name));
                continue;
            }
            long iters = name.equals("dump_stream")
                    ? (args.dumpIters != null ? args.dumpIters : wl.getValue())
                    : (args.iters != null ? args.iters : wl.getValue());
            switch (name) {
                case "xml_read_record" -> bench(out, name, iters, w, wm, fixture.length, () -> {
                    Unmarshaller u = recordCtx.createUnmarshaller();
                    Record r = (Record) u.unmarshal(new ByteArrayInputStream(fixture));
                    return r.getOrcidIdentifier() != null ? 1 : 0;
                });
                case "xml_write_record" -> bench(out, name, iters, w, wm, xmlText.length, () -> {
                    Marshaller m = recordCtx.createMarshaller();
                    m.setProperty(Marshaller.JAXB_FORMATTED_OUTPUT, Boolean.TRUE);
                    ByteArrayOutputStream o = new ByteArrayOutputStream(xmlText.length + 1024);
                    m.marshal(doc, o);
                    return o.size();
                });
                case "json_write_record" -> bench(out, name, iters, w, wm, jsonText.length,
                        () -> JSON.writeValueAsBytes(doc).length);
                case "json_read_record" -> bench(out, name, iters, w, wm, jsonText.length, () -> {
                    Record r = JSON.readValue(jsonText, Record.class);
                    return r.getOrcidIdentifier() != null ? 1 : 0;
                });
                case "sha256" -> bench(out, name, iters, w, wm, fixture.length, () -> {
                    // Not an orcid-model feature: java.security.MessageDigest, to keep the table complete.
                    return sha256Hex(fixture).length();
                });
                case "dump_stream" -> {
                    DumpTotals t = streamDump(dump, dumpCtx);
                    System.err.printf(Locale.ROOT, "%s: dump %s: %d XML members, %d B uncompressed%n",
                            IMPL, dump, t.members(), t.bytes());
                    bench(out, name, iters, Math.min(w, 1), wm, t.bytes(), () -> streamDump(dump, dumpCtx).members());
                }
                case "group_ids_read" -> bench(out, name, iters, w, wm, groupId.length, () -> {
                    // Jackson, as ORCID's API reads a group-id record (JacksonXmlBindJsonProvider)
                    GroupIdRecord g = JSON.readValue(groupId, GroupIdRecord.class);
                    return g.getGroupId() != null ? 1 : 0;
                });
                default -> throw new IllegalStateException("workload list and switch disagree: " + name);
            }
        }
    }

    // ----------------------------------------------------------------- emit

    static void put(Path dir, String name, byte[] data) throws IOException {
        Files.createDirectories(dir);
        Files.write(dir.resolve(name), data);
    }

    /**
     * An XML input: {@code .sha256}, {@code .xml} (unmarshalled, marshalled
     * back), {@code .json} (Jackson), {@code .json.xml} (that JSON read back,
     * marshalled), and for write samples {@code .xsd.txt} (ORCID's XSD
     * check of the document: {@code xsd: ok}, or one {@code xsd: message}
     * line per error).
     */
    static void emitXmlDoc(Path dir, String stem, byte[] bytes, boolean payload) throws Exception {
        put(dir, stem + ".sha256", (sha256Hex(bytes) + "\n").getBytes(UTF_8));
        Class<?> c = rootClass(bytes);
        Object doc;
        try {
            if (c == null) {
                throw new IllegalArgumentException("no orcid-model class for this document element");
            }
            doc = unmarshal(c, bytes);
        } catch (Exception e) {
            put(dir, stem + ".xml", ERROR);
            if (payload) {
                put(dir, stem + ".xsd.txt", ("xsd: unreadable: " + oneLine(e) + "\n").getBytes(UTF_8));
            }
            return;
        }
        try {
            put(dir, stem + ".xml", marshal(doc));
        } catch (Exception e) {
            put(dir, stem + ".xml", ERROR);
        }
        try {
            byte[] j = JSON.writeValueAsBytes(doc);
            put(dir, stem + ".json", j);
            try {
                put(dir, stem + ".json.xml", marshal(JSON.readValue(j, c)));
            } catch (Exception e) {
                put(dir, stem + ".json.xml", ERROR);
            }
        } catch (Exception e) {
            put(dir, stem + ".json", ERROR);
        }
        if (payload) {
            String xsd = XSD.get(c);
            StringBuilder s = new StringBuilder();
            if (xsd == null) {
                s.append("xsd: no schema for ").append(c.getSimpleName()).append('\n');
            } else {
                List<String> errs = xsdErrorsXml(bytes, schema(xsd));
                if (errs.isEmpty()) {
                    s.append("xsd: ok\n");
                }
                for (String m : errs) {
                    s.append("xsd: ").append(m.replace('\n', ' ')).append('\n');
                }
            }
            put(dir, stem + ".xsd.txt", s.toString().getBytes(UTF_8));
        }
    }

    static String oneLine(Exception e) {
        Throwable t = e;
        while (t.getCause() != null && t.getMessage() == null) {
            t = t.getCause();
        }
        return String.valueOf(t.getMessage() != null ? t.getMessage() : t).replace('\n', ' ');
    }

    /** A JSON input: read with the class of its kind, then marshalled ({@code .xml}) and written as JSON. */
    static void emitJsonDoc(Path dir, String stem, byte[] bytes, Class<?> c) throws Exception {
        Object doc;
        try {
            doc = JSON.readValue(bytes, c);
        } catch (Exception e) {
            put(dir, stem + ".xml", ERROR);
            return;
        }
        try {
            put(dir, stem + ".xml", marshal(doc));
        } catch (Exception e) {
            put(dir, stem + ".xml", ERROR);
        }
        try {
            put(dir, stem + ".json", JSON.writeValueAsBytes(doc));
        } catch (Exception e) {
            put(dir, stem + ".json", ERROR);
        }
    }

    /**
     * The class of an ORCID JSON sample, from its file name: the table of
     * yorc-rs's tests/json_roundtrip.rs (rust json_sample_kind),
     * plus peer-review-group-id, which ORCID's GroupIdRecord reads.
     */
    static Class<?> jsonSampleClass(String name) {
        String[][] kinds = {
            {"record-full", "record"}, {"address", "address"}, {"bulk-", "bulk"},
            {"distinction", "distinction"}, {"education", "education"}, {"employment", "employment"},
            {"external-identifier", "external-identifier"}, {"funding", "funding"},
            {"invited-position", "invited-position"}, {"keywords", "keyword"}, {"membership", "membership"},
            {"other-names", "other-name"}, {"peer-review-group-id", "group-id-record"},
            {"peer-review", "peer-review"}, {"qualification", "qualification"},
            {"research-resource", "research-resource"}, {"researcher-url", "researcher-url"},
            {"service", "service"}, {"work", "work"},
        };
        for (String[] k : kinds) {
            if (name.startsWith(k[0])) {
                return KIND_CLASS.get(k[1]);
            }
        }
        return null;
    }

    static final Map<String, Class<?>> KIND_CLASS = new HashMap<>();
    static {
        for (Map.Entry<String, Class<?>> e : ROOTS.entrySet()) {
            String local = e.getKey().substring(e.getKey().indexOf('}') + 1);
            if (!Set.of("summary").contains(local)) {
                KIND_CLASS.putIfAbsent(local, e.getValue());
            }
        }
    }

    static void emit(Args args, Path out) throws Exception {
        Files.createDirectories(out);
        // ids.tsv: n/a (no iD utility in orcid-model); rows: n/a.

        Path fx = args.root.resolve(FIXTURE);
        emitXmlDoc(out.resolve("fixture"), stem(fx), read(fx), false);

        for (String set : List.of("read_samples", "write_samples")) {
            Path src = args.root.resolve(SAMPLES).resolve(set);
            Path d = out.resolve(set);
            Files.createDirectories(d);
            for (Path f : files(src, "xml")) {
                emitXmlDoc(d, stem(f), read(f), set.equals("write_samples"));
            }
            Path jd = out.resolve("json_samples").resolve(set);
            Files.createDirectories(jd);
            for (Path f : files(src, "json")) {
                Class<?> c = jsonSampleClass(f.getFileName().toString());
                if (c != null) {
                    emitJsonDoc(jd, stem(f), read(f), c);
                }
            }
        }

        // The dump: members.tsv (stem, SHA-256, iD; no row count, Java has no
        // rows) and every .xml member re-serialised under dumpxml/<member path>.
        Path dd = out.resolve("dump");
        Files.createDirectories(dd);
        Path dx = out.resolve("dumpxml");
        Path path = dumpPath(args);
        StringBuilder s = new StringBuilder();
        try (InputStream in = openDump(path)) {
            Tar tar = new Tar(in);
            TarEntry e;
            while ((e = tar.next()) != null) {
                String st = e.isFile() ? xmlStem(e.path()) : null;
                if (st == null) {
                    continue;
                }
                byte[] b = tar.read(e);
                String h = sha256Hex(b);
                String rel = memberPath(e.path());
                Class<?> c = rootClass(b);
                Object doc = null;
                try {
                    if (c != null) {
                        doc = unmarshal(c, b);
                    }
                } catch (Exception x) {
                    doc = null;
                }
                if (doc == null) {
                    s.append(st).append('\t').append(h).append("\terror\n");
                    if (!rel.isEmpty()) {
                        put(dx.resolve(rel).getParent(), dx.resolve(rel).getFileName().toString(), ERROR);
                    }
                    continue;
                }
                String orcid = "-";
                if (doc instanceof Record r && r.getOrcidIdentifier() != null && r.getOrcidIdentifier().getPath() != null) {
                    orcid = r.getOrcidIdentifier().getPath();
                }
                s.append(st).append('\t').append(h).append('\t').append(orcid).append('\n');
                if (!rel.isEmpty()) {
                    byte[] x;
                    try {
                        x = marshal(doc);
                    } catch (Exception ex) {
                        x = ERROR;
                    }
                    put(dx.resolve(rel).getParent(), dx.resolve(rel).getFileName().toString(), x);
                }
            }
        }
        put(dd, "members.tsv", s.toString().getBytes(UTF_8));
        System.err.println(IMPL + ": wrote " + out);
    }

    // --------------------------------------------------------------- re-read

    /**
     * {@code --reread SRC --emit OUT}: every .xml file below SRC (class from
     * its document element) and .json file (class from the first line of
     * {@code <file>.kind}, which compare3.py writes, else from an ORCID sample
     * name) is read with ORCID's classes. OUT/&lt;path&gt;.accept.txt gets one
     * line: {@code read: ok, xsd: ok}, {@code read: ok, xsd: rejected: ...},
     * {@code read: ok, xsd: none} (no payload schema for the class), or
     * {@code read: error: ...}. The XSD check is ORCID's payload check: the
     * XML document itself ({@link #xsdErrorsXml}), or for JSON the model
     * Jackson read ({@link #xsdErrors}, JSONInputValidator).
     */
    static void reread(Path src, Path out) throws Exception {
        List<Path> paths = new ArrayList<>();
        try (Stream<Path> s = Files.walk(src)) {
            s.filter(Files::isRegularFile).filter(p -> {
                String n = p.getFileName().toString();
                return n.endsWith(".xml") || n.endsWith(".json");
            }).forEach(paths::add);
        }
        paths.sort((x, y) -> compareBytes(src.relativize(x).toString(), src.relativize(y).toString()));
        int failed = 0;
        for (Path p : paths) {
            Path rel = src.relativize(p);
            Path dest = out.resolve(rel.toString() + ".accept.txt");
            String line;
            try {
                byte[] b = read(p);
                Object doc;
                String n = p.getFileName().toString();
                boolean json = n.endsWith(".json");
                if (json) {
                    Class<?> c = null;
                    Path kindFile = p.resolveSibling(n + ".kind");
                    if (Files.isRegularFile(kindFile)) {
                        String kind = Files.readString(kindFile, UTF_8).trim();
                        c = KIND_CLASS.get(kind);
                    } else {
                        c = jsonSampleClass(n);
                    }
                    if (c == null) {
                        throw new IllegalArgumentException("no orcid-model class for this JSON kind");
                    }
                    doc = JSON.readValue(b, c);
                } else {
                    Class<?> c = rootClass(b);
                    if (c == null) {
                        throw new IllegalArgumentException("no orcid-model class for this document element");
                    }
                    doc = unmarshal(c, b);
                }
                String xsd = XSD.get(doc.getClass());
                if (xsd == null) {
                    line = "read: ok, xsd: none";
                } else {
                    List<String> errs = json ? xsdErrors(doc, schema(xsd)) : xsdErrorsXml(b, schema(xsd));
                    line = errs.isEmpty() ? "read: ok, xsd: ok" : "read: ok, xsd: rejected: " + String.join(" | ", errs);
                }
            } catch (Exception e) {
                failed++;
                line = "read: error: " + oneLine(e);
            }
            put(dest.getParent(), dest.getFileName().toString(), (line.replace('\n', ' ') + "\n").getBytes(UTF_8));
        }
        System.err.printf(Locale.ROOT, "%s: re-read %d documents below %s (%d did not read) into %s%n",
                IMPL, paths.size(), src, failed, out);
    }
}
