"""Map a resolved compound onto the controlled `Standard Product Class` vocabulary.

The 17 classes come from the curated Excel (see
``pipelines/extraction/default_template.STANDARD_PRODUCT_CLASSES``); this module
decides which one a looked-up compound belongs to, from its names alone —
PubChem synonyms, the IUPAC name, and the ChEBI definition when available.
Chemical class is almost always spelled out in one of those (`...methoxyflavanone`,
`trihydroxyflavanone`), so a token table gets there without a model call.

Two properties matter more than coverage:

1. **Order is significant.** Many compounds match several tables. `farnesene` is a
   sesquiterpene that is also a jet-fuel precursor; `riboflavin` is a vitamin that
   is also a pigment; every fatty acid contains the word "acid". The list is
   ordered most-specific-first and the first match wins, so these resolve the way
   a curator would resolve them.
2. **No guessing.** An unmatched compound returns ``None`` rather than a
   best-effort class. The wizard shows it as unclassified and the admin picks —
   a wrong class silently assigned is worse than an empty one, because it
   propagates into the datasheet as if it were curated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pipelines.extraction.default_template import STANDARD_PRODUCT_CLASSES

# Ordered most-specific-first: the first class whose token appears wins.
# Tokens are matched on word boundaries against the lowercased name haystack, so
# short tokens are safe but must still be unambiguous words.
CLASS_TOKENS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Carotenoids & Apocarotenoids",
        (
            "carotenoid", "carotene", "apocarotenoid", "lycopene", "astaxanthin",
            "zeaxanthin", "canthaxanthin", "canthaxanthine", "beta-ionone", "bixin",
            "crocin", "lutein", "torulene", "retinal", "retinol",
        ),
    ),
    (
        "Flavonoids & Polyphenols",
        (
            "flavonoid", "flavanone", "flavanonol", "flavone", "flavonol", "flavan",
            "isoflavone", "isoflavonoid", "anthocyanin", "anthocyanidin", "catechin",
            "polyphenol", "stilbene", "stilbenoid", "chalcone", "naringenin",
            "hesperetin", "hesperidin", "quercetin", "kaempferol", "resveratrol",
            "apigenin", "luteolin", "genistein", "eriodictyol", "pinocembrin",
        ),
    ),
    (
        "Terpenoids & Sterols",
        (
            "terpene", "terpenoid", "monoterpene", "sesquiterpene", "diterpene",
            "triterpene", "triterpenoid", "sterol", "stanol", "squalene", "limonene",
            "linalool", "geraniol", "nerolidol", "bisabolene", "farnesene", "farnesol",
            "lupeol", "betulin", "betulinic", "amyrin", "ergosterol", "campesterol",
            "sitosterol", "cholesterol", "taxadiene", "santalene", "patchoulol",
            "valencene", "nootkatone", "artemisinic", "ginsenoside", "glycyrrhizin",
        ),
    ),
    (
        "Polyketides",
        (
            "polyketide", "macrolide", "erythromycin", "tetracycline", "lovastatin",
            "actinorhodin", "6-methylsalicylic", "triacetic acid lactone", "aflatoxin",
        ),
    ),
    (
        "Biopolymers & Biosurfactants",
        (
            "polyhydroxyalkanoate", "polyhydroxybutyrate", "polyhydroxyvalerate",
            "hyaluronic", "hyaluronan", "chitin", "chitosan", "exopolysaccharide",
            "biosurfactant", "sophorolipid", "rhamnolipid", "mannosylerythritol",
            "surfactin", "levan", "pullulan", "curdlan", "xanthan", "polylactic",
            "polyamide", "cellulose acetate",
        ),
    ),
    (
        "Vitamins & Cofactors",
        (
            "vitamin", "riboflavin", "thiamine", "thiamin", "cobalamin", "tocopherol",
            "tocotrienol", "ascorbic", "ascorbate", "folate", "folic", "biotin",
            "pantothenate", "pantothenic", "pyridoxine", "pyridoxal", "niacin",
            "nicotinamide", "menaquinone", "phylloquinone", "ubiquinone",
            "coenzyme q10", "coenzyme a", "glutathione", "s-adenosyl",
        ),
    ),
    (
        "Enzymes & Recombinant Proteins",
        (
            "enzyme", "lipase", "protease", "peptidase", "cellulase", "amylase",
            "xylanase", "laccase", "phytase", "pectinase", "invertase", "catalase",
            "chymosin", "insulin", "interleukin", "interferon", "albumin", "antibody",
            "nanobody", "recombinant protein", "single-cell protein",
        ),
    ),
    (
        "Sugar Alcohols (Polyols)",
        (
            "sugar alcohol", "polyol", "erythritol", "xylitol", "mannitol", "sorbitol",
            "arabitol", "arabinitol", "glycerol", "ribitol", "threitol", "maltitol",
            "isomalt", "inositol",
        ),
    ),
    (
        "Sugars & Oligosaccharides",
        (
            "oligosaccharide", "polysaccharide", "monosaccharide", "disaccharide",
            "sucrose", "glucose", "fructose", "galactose", "xylose", "arabinose",
            "mannose", "rhamnose", "maltose", "cellobiose", "trehalose", "lactose",
            "raffinose", "inulin", "starch",
        ),
    ),
    (
        "Amino Acids & Derivatives",
        (
            "amino acid", "lysine", "glutamate", "glutamic", "glutamine", "arginine",
            "threonine", "tryptophan", "tyrosine", "phenylalanine", "methionine",
            "cysteine", "histidine", "isoleucine", "leucine", "valine", "proline",
            "serine", "asparagine", "aspartate", "ectoine", "ectoin", "betaine",
            "carnitine", "creatine", "taurine",
        ),
    ),
    (
        "Nucleosides & Secondary Metabolites",
        (
            "nucleoside", "nucleotide", "inosine", "adenosine", "guanosine", "cytidine",
            "uridine", "thymidine", "xanthosine", "alkaloid", "indole alkaloid",
            "benzylisoquinoline", "reticuline", "strictosidine", "vinblastine",
            "morphinan", "caffeine", "theobromine", "penicillin", "cephalosporin",
        ),
    ),
    (
        "Pigments (Non-carotenoid)",
        (
            "melanin", "prodigiosin", "violacein", "betalain", "betanin", "indigoidine",
            "indigo", "phycocyanin", "phycoerythrin", "monascus pigment", "azaphilone",
            "anthraquinone", "pigment", "dye",
        ),
    ),
    (
        "Lipids & Fatty Acids",
        (
            "fatty acid", "fatty alcohol", "fatty aldehyde", "fatty acid ethyl ester",
            "lipid", "triacylglycerol", "triglyceride", "diacylglycerol",
            "monoacylglycerol", "phospholipid", "sphingolipid", "glycolipid",
            "wax ester", "oleic", "palmitic", "palmitoleic", "stearic", "linoleic",
            "linolenic", "myristic", "lauric", "arachidonic", "ricinoleic",
            "docosahexaenoic", "eicosapentaenoic", "omega-3", "omega-6",
            "single cell oil", "cocoa butter",
        ),
    ),
    (
        "Phenolic & Aromatic / Flavor Compounds",
        (
            "vanillin", "vanillic", "guaiacol", "eugenol", "phenylethanol",
            "phenylethyl alcohol", "benzaldehyde", "benzyl alcohol", "coumaric",
            "coumarin", "ferulic", "caffeic", "cinnamic", "cinnamaldehyde",
            "gallic", "salicylic", "protocatechuic", "shikimic", "tyrosol",
            "hydroxytyrosol", "raspberry ketone", "phenolic", "aroma", "flavour",
            "flavor",
        ),
    ),
    (
        "Organic Acids",
        (
            "citric", "citrate", "succinic", "succinate", "itaconic", "itaconate",
            "malic", "malate", "fumaric", "fumarate", "lactic", "lactate", "acetic",
            "acetate", "propionic", "butyric", "pyruvic", "pyruvate", "oxalic",
            "alpha-ketoglutaric", "2-oxoglutaric", "ketoglutarate", "adipic",
            "muconic", "levulinic", "glucaric", "gluconic", "malonic", "organic acid",
        ),
    ),
    (
        "Biomass, Biofuels & Hydrocarbons",
        (
            "biodiesel", "biofuel", "biomass", "biogas", "jet fuel", "kerosene",
            "alkane", "alkene", "hydrocarbon", "isoprene", "ethanol", "butanol",
            "isobutanol", "isopentanol", "methane", "hydrogen", "syngas", "bio-oil",
        ),
    ),
)

_CLASS_ORDER = tuple(name for name, _ in CLASS_TOKENS)

# Trailing boundary only, deliberately. Chemical names compose by prefixing —
# `4'-methoxyflavanone`, `phospholipid`, `dihydroxyflavone` — so requiring a
# boundary *before* the token would miss exactly the cases the classifier exists
# for. The trailing boundary is what still keeps `indigoberry` out of the pigment
# class and `nadph` out of the cofactor class.
_TOKEN_PATTERNS: dict[str, tuple[tuple[str, re.Pattern[str]], ...]] = {
    class_name: tuple(
        (token, re.compile(rf"{re.escape(token)}(?![a-z0-9])")) for token in tokens
    )
    for class_name, tokens in CLASS_TOKENS
}


@dataclass(frozen=True)
class ProductClassMatch:
    """Which class, and the token that decided it — shown in the UI as the reason."""

    product_class: str
    matched_token: str


def classify_terms(terms: list[str] | tuple[str, ...]) -> ProductClassMatch | None:
    """Classify from a bag of names. First matching class in table order wins."""
    haystack = " | ".join(term.casefold() for term in terms if term)
    if not haystack:
        return None

    for class_name in _CLASS_ORDER:
        for token, pattern in _TOKEN_PATTERNS[class_name]:
            if pattern.search(haystack):
                return ProductClassMatch(product_class=class_name, matched_token=token)
    return None


def _assert_classes_are_in_the_controlled_vocabulary() -> None:
    """Guard against a typo in this table drifting from the template vocabulary.

    A class name here that the template does not accept would produce datasheet
    rows the extraction schema rejects, so it is worth failing at import.
    """
    unknown = [name for name in _CLASS_ORDER if name not in STANDARD_PRODUCT_CLASSES]
    if unknown:
        raise ValueError(
            "product class table names are not in STANDARD_PRODUCT_CLASSES: " + ", ".join(unknown)
        )


_assert_classes_are_in_the_controlled_vocabulary()
