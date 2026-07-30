"""Tests for S1 seed resolution: NCBI Taxonomy and PubChem/ChEBI lookups.

No network: every upstream is an ``httpx.MockTransport`` serving payloads trimmed
from real API responses (see the fixture docstrings for provenance). The live
acceptance check — `Yarrowia lipolytica` → 4952 with three synonyms, `hesperetin`
→ CID 72281 in `Flavonoids & Polyphenols` — is recorded in
docs/DATASHEET_FEATURE_PLAN.md §8.1 and re-run by hand, not here.
"""

from __future__ import annotations

import json

import httpx
import pytest

from pipelines.discovery.http import DiscoveryLookupError, HttpSettings, get_json
from pipelines.discovery.product import (
    ProductSeed,
    fetch_product,
    resolve_product,
    search_products,
)
from pipelines.discovery.product_classes import CLASS_TOKENS, classify_terms
from pipelines.discovery.taxonomy import (
    OrganismSeed,
    fetch_organism,
    organism_search_terms,
    parse_taxon_xml,
    resolve_organism,
    search_organisms,
)
from pipelines.extraction.default_template import STANDARD_PRODUCT_CLASSES

# Trimmed from a real efetch db=taxonomy id=4952 response. The authority,
# type-material and misspelling entries are kept deliberately: filtering them is
# the behaviour under test.
TAXON_XML = """<?xml version="1.0"?>
<TaxaSet>
  <Taxon>
    <TaxId>4952</TaxId>
    <ScientificName>Yarrowia lipolytica</ScientificName>
    <OtherNames>
      <Synonym>Candida lipolytica</Synonym>
      <Synonym>Endomycopsis lipolytica</Synonym>
      <Synonym>Mycotorula lipolytica</Synonym>
      <Name>
        <ClassCDE>authority</ClassCDE>
        <DispName>Yarrowia lipolytica (Wick., Kurtzman &amp; Herman) Van der Walt &amp; Arx, 1980</DispName>
      </Name>
      <Name>
        <ClassCDE>type material</ClassCDE>
        <DispName>ATCC 18942</DispName>
      </Name>
      <Name>
        <ClassCDE>misspelling</ClassCDE>
        <DispName>Yallowia lipolitica</DispName>
      </Name>
    </OtherNames>
    <Rank>species</Rank>
    <Lineage>cellular organisms; Eukaryota; Fungi; Dikarya; Ascomycota; Saccharomycotina; Dipodascales; Yarrowia</Lineage>
  </Taxon>
</TaxaSet>
"""

EMPTY_TAXON_XML = '<?xml version="1.0"?><TaxaSet></TaxaSet>'

# Trimmed from PubChem /compound/cid/72281/synonyms/JSON — the registry codes are
# what `_clean_synonyms` must drop.
PUBCHEM_SYNONYMS = [
    "hesperetin",
    "Hesperitin",
    "520-33-2",
    "3',5,7-Trihydroxy-4'-methoxyflavanone",
    "(-)-hesperetin",
    "Eriodictyol 4'-monomethyl ether",
    "NSC-57654",
    "Q9Q3D557F1",
    "DTXSID4022319",
    "CHEBI:28230",
]
PUBCHEM_PROPERTIES = {
    "CID": 72281,
    "MolecularFormula": "C16H14O6",
    "MolecularWeight": "302.28",
    "InChIKey": "AIONOLUJZLIMTK-AWEZNQCLSA-N",
    "IUPACName": "(2S)-5,7-dihydroxy-2-(3-hydroxy-4-methoxyphenyl)-2,3-dihydrochromen-4-one",
}


def transport_from(routes: dict[str, object], *, calls: list[str] | None = None) -> httpx.Client:
    """Client whose responses are chosen by the first matching path fragment."""

    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        for fragment, payload in routes.items():
            if fragment in str(request.url):
                if isinstance(payload, httpx.Response):
                    return payload
                if isinstance(payload, str):
                    return httpx.Response(200, text=payload)
                return httpx.Response(200, json=payload)
        return httpx.Response(404, text=f"no route for {request.url}")

    return httpx.Client(transport=httpx.MockTransport(handler))


# ── HTTP layer ────────────────────────────────────────────────────────────────


def test_retries_a_server_error_then_succeeds() -> None:
    attempts: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) < 3:
            return httpx.Response(503, text="busy")
        return httpx.Response(200, json={"ok": True})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        payload = get_json(
            "https://example.org/x",
            upstream="Test",
            client=client,
            settings=HttpSettings(backoff_base_s=0.0),
        )

    assert payload == {"ok": True}
    assert len(attempts) == 3


def test_a_client_error_is_not_retried() -> None:
    attempts: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(400, text="bad request")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(DiscoveryLookupError) as excinfo:
            get_json(
                "https://example.org/x",
                upstream="Test",
                client=client,
                settings=HttpSettings(backoff_base_s=0.0),
            )

    assert len(attempts) == 1
    assert excinfo.value.upstream == "Test"


def test_a_404_is_an_answer_when_the_caller_allows_it() -> None:
    """PubChem answers an unknown compound with 404. That is 'no such compound',
    not an outage, and must not raise."""
    with httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(404))) as client:
        assert (
            get_json("https://example.org/x", upstream="Test", client=client, allow_404=True)
            is None
        )


def test_an_upstream_outage_is_never_reported_as_an_empty_result() -> None:
    """The distinction the wizard depends on: a 500 must not look like 'not found'."""
    with httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(500))) as client:
        with pytest.raises(DiscoveryLookupError):
            get_json(
                "https://example.org/x",
                upstream="Test",
                client=client,
                settings=HttpSettings(max_attempts=1, backoff_base_s=0.0),
            )


# ── Taxonomy ──────────────────────────────────────────────────────────────────


def test_parses_the_accepted_name_and_only_usable_synonyms() -> None:
    seed = parse_taxon_xml(TAXON_XML)

    assert seed is not None
    assert seed.taxid == 4952
    assert seed.scientific_name == "Yarrowia lipolytica"
    assert seed.rank == "species"
    assert seed.synonyms == (
        "Candida lipolytica",
        "Endomycopsis lipolytica",
        "Mycotorula lipolytica",
    )
    assert seed.lineage[-1] == "Yarrowia"


@pytest.mark.parametrize("noise", ["Yallowia lipolitica", "ATCC 18942", "Van der Walt"])
def test_authority_type_material_and_misspellings_are_not_search_terms(noise: str) -> None:
    """They add no recall to a literature query and would pollute every source."""
    seed = parse_taxon_xml(TAXON_XML)
    assert seed is not None
    assert all(noise not in term for term in seed.search_terms)


def test_an_empty_taxa_set_resolves_to_nothing() -> None:
    """NCBI answers an unknown taxid with a valid empty document, not an error."""
    assert parse_taxon_xml(EMPTY_TAXON_XML) is None


def test_unparseable_xml_is_an_upstream_error() -> None:
    with pytest.raises(DiscoveryLookupError):
        parse_taxon_xml("<TaxaSet><Taxon>")


def test_search_terms_put_the_accepted_name_first_then_curated_extras() -> None:
    """`Saccharomycopsis lipolytica` has no taxid, so NCBI cannot supply it. A
    curator can, and it must land after the authoritative names."""
    seed = parse_taxon_xml(TAXON_XML)
    assert seed is not None

    terms = organism_search_terms(seed, extra_synonyms=["Saccharomycopsis lipolytica"])

    assert terms[0] == "Yarrowia lipolytica"
    assert terms[-1] == "Saccharomycopsis lipolytica"
    assert terms.index("Candida lipolytica") < terms.index("Saccharomycopsis lipolytica")


def test_search_terms_dedupe_case_insensitively() -> None:
    seed = OrganismSeed(
        taxid=1,
        scientific_name="Yarrowia lipolytica",
        synonyms=("yarrowia LIPOLYTICA", "Candida lipolytica"),
    )
    assert seed.search_terms == ("Yarrowia lipolytica", "Candida lipolytica")


def test_typeahead_appends_a_wildcard_because_ncbi_matches_whole_names() -> None:
    """`Yarrowia lipo` returns nothing from NCBI; `Yarrowia lipo*` returns 4952."""
    calls: list[str] = []
    client = transport_from(
        {
            "esearch": {"esearchresult": {"idlist": ["4952"]}},
            "esummary": {
                "result": {
                    "uids": ["4952"],
                    "4952": {"scientificname": "Yarrowia lipolytica", "rank": "species"},
                }
            },
        },
        calls=calls,
    )

    with client:
        suggestions = search_organisms("Yarrowia lipo", client=client)

    assert [(item.taxid, item.scientific_name) for item in suggestions] == [
        (4952, "Yarrowia lipolytica")
    ]
    assert "Yarrowia+lipo%2A" in calls[0] or "Yarrowia%20lipo*" in calls[0]


def test_typeahead_leaves_an_explicit_wildcard_alone() -> None:
    calls: list[str] = []
    client = transport_from({"esearch": {"esearchresult": {"idlist": []}}}, calls=calls)

    with client:
        assert search_organisms("Yarrow*", client=client) == []

    assert "%2A%2A" not in calls[0] and "**" not in calls[0]


def test_typeahead_keeps_esearch_ranking_not_esummary_key_order() -> None:
    client = transport_from(
        {
            "esearch": {"esearchresult": {"idlist": ["4952", "4951"]}},
            "esummary": {
                "result": {
                    "uids": ["4951", "4952"],
                    "4951": {"scientificname": "Yarrowia", "rank": "genus"},
                    "4952": {"scientificname": "Yarrowia lipolytica", "rank": "species"},
                }
            },
        }
    )

    with client:
        suggestions = search_organisms("Yarrowia", client=client)

    assert [item.taxid for item in suggestions] == [4952, 4951]


def test_empty_query_makes_no_request() -> None:
    calls: list[str] = []
    client = transport_from({"esearch": {}}, calls=calls)

    with client:
        assert search_organisms("   ", client=client) == []

    assert calls == []


def test_resolving_a_taxid_skips_the_search_step() -> None:
    calls: list[str] = []
    client = transport_from({"efetch": TAXON_XML}, calls=calls)

    with client:
        seed = fetch_organism(4952, client=client)

    assert seed is not None and seed.taxid == 4952
    assert len(calls) == 1 and "efetch" in calls[0]


def test_a_synonym_resolves_to_the_accepted_taxon() -> None:
    """So a run keyed on the taxid cannot be split in two by which name was typed."""
    client = transport_from(
        {"esearch": {"esearchresult": {"idlist": ["4952"]}}, "efetch": TAXON_XML}
    )

    with client:
        seed = resolve_organism("candida lipolytica", client=client)

    assert seed is not None
    assert seed.taxid == 4952
    assert seed.scientific_name == "Yarrowia lipolytica"


def test_resolution_retries_with_a_wildcard_before_giving_up() -> None:
    calls: list[str] = []
    responses = iter(
        [
            httpx.Response(200, json={"esearchresult": {"idlist": []}}),
            httpx.Response(200, json={"esearchresult": {"idlist": ["4952"]}}),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "efetch" in str(request.url):
            return httpx.Response(200, text=TAXON_XML)
        return next(responses)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        seed = resolve_organism("Yarrowia lipo", client=client)

    assert seed is not None and seed.taxid == 4952
    assert len(calls) == 3  # exact esearch, wildcard esearch, efetch


def test_a_numeric_query_is_treated_as_a_taxid() -> None:
    calls: list[str] = []
    client = transport_from({"efetch": TAXON_XML}, calls=calls)

    with client:
        seed = resolve_organism("4952", client=client)

    assert seed is not None and seed.taxid == 4952
    assert all("esearch" not in call for call in calls)


# ── Product classes ───────────────────────────────────────────────────────────


def test_every_class_in_the_table_is_in_the_controlled_vocabulary() -> None:
    """A name that drifts from the template vocabulary would produce datasheet rows
    the extraction schema rejects."""
    for class_name, _tokens in CLASS_TOKENS:
        assert class_name in STANDARD_PRODUCT_CLASSES


@pytest.mark.parametrize(
    ("terms", "expected"),
    [
        # The S1 acceptance case: the class is spelled out in a synonym.
        (["hesperetin", "3',5,7-Trihydroxy-4'-methoxyflavanone"], "Flavonoids & Polyphenols"),
        (["lupeol", "a pentacyclic triterpenoid"], "Terpenoids & Sterols"),
        (["erythritol"], "Sugar Alcohols (Polyols)"),
        (["citric acid"], "Organic Acids"),
        (["beta-carotene"], "Carotenoids & Apocarotenoids"),
        (["lipase B"], "Enzymes & Recombinant Proteins"),
        (["polyhydroxybutyrate"], "Biopolymers & Biosurfactants"),
        (["vanillin"], "Phenolic & Aromatic / Flavor Compounds"),
        (["L-lysine"], "Amino Acids & Derivatives"),
        (["inosine"], "Nucleosides & Secondary Metabolites"),
    ],
)
def test_classifies_representative_compounds(terms: list[str], expected: str) -> None:
    match = classify_terms(terms)
    assert match is not None
    assert match.product_class == expected


@pytest.mark.parametrize(
    ("terms", "expected", "why"),
    [
        (["farnesene"], "Terpenoids & Sterols", "a sesquiterpene that is also a jet-fuel precursor"),
        (["riboflavin"], "Vitamins & Cofactors", "a vitamin that is also a pigment"),
        (["oleic acid"], "Lipids & Fatty Acids", "a fatty acid, and every fatty acid says 'acid'"),
        (["astaxanthin"], "Carotenoids & Apocarotenoids", "a carotenoid that is also a pigment"),
        (["glycerol"], "Sugar Alcohols (Polyols)", "a polyol, not a sugar"),
    ],
)
def test_ambiguous_compounds_resolve_the_way_a_curator_would(
    terms: list[str], expected: str, why: str
) -> None:
    """These are the reason the table is ordered rather than a plain dict."""
    match = classify_terms(terms)
    assert match is not None, why
    assert match.product_class == expected, why


def test_an_unmatched_compound_is_unclassified_rather_than_guessed() -> None:
    """A wrong class assigned silently propagates into the datasheet as if curated."""
    assert classify_terms(["zorblaxine"]) is None
    assert classify_terms([]) is None


def test_the_matched_token_is_reported_as_evidence() -> None:
    match = classify_terms(["3',5,7-Trihydroxy-4'-methoxyflavanone"])
    assert match is not None
    assert match.matched_token == "flavanone"


def test_token_matching_respects_word_boundaries() -> None:
    """Substring matching would classify anything containing 'indigo' or 'nad'."""
    assert classify_terms(["indigoberry extract"]) is None


# ── Product lookup ────────────────────────────────────────────────────────────


def product_client(calls: list[str] | None = None) -> httpx.Client:
    return transport_from(
        {
            "/cids/JSON": {"IdentifierList": {"CID": [72281]}},
            "/property/": {"PropertyTable": {"Properties": [PUBCHEM_PROPERTIES]}},
            "/synonyms/JSON": {
                "InformationList": {"Information": [{"CID": 72281, "Synonym": PUBCHEM_SYNONYMS}]}
            },
            "ols4": {
                "response": {
                    "docs": [
                        {
                            "obo_id": "CHEBI:28230",
                            "label": "hesperetin",
                            "description": ["A <b>trihydroxyflavanone</b> having ..."],
                        }
                    ]
                }
            },
            "autocomplete": {"dictionary_terms": {"compound": ["hesperetin", "hesperidin"]}},
        },
        calls=calls,
    )


def test_resolves_a_compound_to_cid_synonyms_and_class() -> None:
    client = product_client()

    with client:
        seed = resolve_product("hesperetin", client=client)

    assert seed is not None
    assert seed.cid == 72281
    assert seed.preferred_name == "hesperetin"
    assert seed.molecular_formula == "C16H14O6"
    assert seed.product_class == "Flavonoids & Polyphenols"
    assert seed.product_class_evidence == "flavanone"


def test_registry_codes_are_dropped_from_the_synonym_set() -> None:
    """CAS numbers and vendor catalogue codes are not names a paper would use."""
    client = product_client()

    with client:
        seed = fetch_product(72281, client=client)

    assert seed is not None
    assert "520-33-2" not in seed.synonyms
    assert "DTXSID4022319" not in seed.synonyms
    assert "NSC-57654" not in seed.synonyms
    assert "3',5,7-Trihydroxy-4'-methoxyflavanone" in seed.synonyms


def test_the_chebi_id_comes_free_from_the_pubchem_synonym_list() -> None:
    client = product_client()

    with client:
        seed = fetch_product(72281, enrich_with_chebi=False, client=client)

    assert seed is not None
    assert seed.chebi_id == "CHEBI:28230"
    assert seed.chebi_label is None  # enrichment was off


def test_chebi_markup_is_stripped_from_the_definition() -> None:
    client = product_client()

    with client:
        seed = fetch_product(72281, client=client)

    assert seed is not None
    assert seed.chebi_definition is not None
    assert "<b>" not in seed.chebi_definition
    assert "trihydroxyflavanone" in seed.chebi_definition


def test_a_chebi_outage_does_not_stop_a_product_resolving() -> None:
    """Enrichment is optional; PubChem alone is enough to seed a run."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "ols4" in url:
            return httpx.Response(500, text="down")
        if "/property/" in url:
            return httpx.Response(200, json={"PropertyTable": {"Properties": [PUBCHEM_PROPERTIES]}})
        if "/synonyms/JSON" in url:
            return httpx.Response(
                200,
                json={"InformationList": {"Information": [{"Synonym": PUBCHEM_SYNONYMS}]}},
            )
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        seed = fetch_product(
            72281, client=client, settings=HttpSettings(max_attempts=1, backoff_base_s=0.0)
        )

    assert seed is not None
    assert seed.product_class == "Flavonoids & Polyphenols"
    assert seed.chebi_id == "CHEBI:28230"  # still found in the synonym list
    assert seed.chebi_label is None


def test_an_unknown_compound_name_resolves_to_nothing() -> None:
    with httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(404))) as client:
        assert resolve_product("zorblaxine", client=client) is None


def test_a_numeric_query_is_treated_as_a_cid() -> None:
    calls: list[str] = []
    client = product_client(calls)

    with client:
        seed = resolve_product("72281", client=client)

    assert seed is not None and seed.cid == 72281
    assert all("/cids/JSON" not in call for call in calls)


def test_product_typeahead_returns_names() -> None:
    client = product_client()

    with client:
        suggestions = search_products("hespe", client=client)

    assert [item.name for item in suggestions] == ["hesperetin", "hesperidin"]


def test_a_name_with_a_slash_is_encoded_into_the_path() -> None:
    """PubChem takes the name as a path segment, so `1,2-propanediol/water` must not
    open a new path segment."""
    calls: list[str] = []
    client = transport_from({"pug": {"IdentifierList": {"CID": [1]}}}, calls=calls)

    with client:
        search_products("a/b", client=client)

    assert "a/b/json" not in calls[0]


def test_product_search_terms_order_name_label_then_synonyms() -> None:
    seed = ProductSeed(
        cid=1,
        preferred_name="hesperetin",
        synonyms=("Hesperitin", "hesperetin"),
        chebi_label="hesperetin",
    )
    assert seed.search_terms == ("hesperetin", "Hesperitin")


def test_json_payloads_used_by_these_tests_are_valid() -> None:
    """Guards against a fixture edit that silently breaks every assertion above."""
    assert json.loads(json.dumps(PUBCHEM_PROPERTIES))["CID"] == 72281
