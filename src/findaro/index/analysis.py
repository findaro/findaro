"""Analyzers. Language-level only (English + romanised Hindi), never domain vocabulary."""

# Indexed-text stopwords: keep small so titles/descriptions stay matchable.
INDEX_STOPWORDS = ["a", "an", "the", "and", "or", "of", "for", "with", "to", "in", "on", "at", "by", "is", "it"]

# Query-only fillers: English request phrasing + common Hinglish function words. These carry intent
# that M2 query understanding will use; for M1 lexical matching they are noise.
QUERY_STOPWORDS = INDEX_STOPWORDS + [
    "show", "me", "i", "want", "need", "looking", "find", "get", "buy", "please", "some", "any", "my",
    "under", "below", "above", "less", "than", "more", "upto", "up", "from", "within", "between",
    "rs", "inr", "rupees", "rupee", "price", "cheap", "best",
    # romanised Hindi
    "ke", "ka", "ki", "ko", "se", "me", "mein", "mai", "andar", "neeche", "niche", "upar", "tak",
    "wala", "wali", "wale", "vala", "vali", "vale", "liye", "lie", "chahiye", "chaiye", "hai", "hain",
    "ho", "aur", "ya", "koi", "kuch", "acha", "accha", "achha", "sasta", "sasti", "saste", "mujhe",
    "dikhao", "dikha", "batao", "jo", "jisme", "ek", "do", "rakhne", "karne", "ne",
]

# Romanised-Hindi spelling normalisation for the phonetic subfield: joota/juta/jootey -> jut,
# kapde/kapdey -> kapde, chappal/chapal -> kapal. Lossy by design; it only boosts recall at low weight.
PHONETIC_RULES = [
    ("ph", "f"),
    ("([bcdgjkpst])h", "$1"),
    ("w", "v"),
    ("z", "j"),
    ("q", "k"),
    ("ck", "k"),
    ("c", "k"),
    ("x", "ks"),
    ("(ey|ay|ai)$", "e"),
    ("[ou]+", "u"),
    ("(ee|ie|iy|y)", "i"),
    ("([a-z])\\1+", "$1"),
]


def analysis_settings() -> dict:
    filters: dict = {
        "findaro_translit": {"type": "icu_transform", "id": "Any-Latin; Latin-ASCII"},
        "findaro_index_stop": {"type": "stop", "stopwords": INDEX_STOPWORDS, "ignore_case": True},
        "findaro_query_stop": {"type": "stop", "stopwords": QUERY_STOPWORDS, "ignore_case": True},
        "findaro_stem": {"type": "stemmer", "language": "minimal_english"},
        "findaro_wdg": {
            "type": "word_delimiter_graph",
            "preserve_original": True,
            "split_on_numerics": True,
            "generate_number_parts": True,
            "generate_word_parts": True,
        },
    }
    phon_filters = []
    for i, (pat, rep) in enumerate(PHONETIC_RULES):
        name = f"findaro_phon_{i}"
        filters[name] = {"type": "pattern_replace", "pattern": pat, "replacement": rep}
        phon_filters.append(name)

    base = ["findaro_translit", "lowercase"]
    return {
        "analysis": {
            "filter": filters,
            "normalizer": {"findaro_lower": {"type": "custom", "filter": ["lowercase", "asciifolding"]}},
            "analyzer": {
                "findaro_text": {
                    "type": "custom", "tokenizer": "icu_tokenizer",
                    "filter": [*base, "findaro_wdg", "findaro_index_stop", "findaro_stem", "flatten_graph"],
                },
                "findaro_text_search": {
                    "type": "custom", "tokenizer": "icu_tokenizer",
                    "filter": [*base, "findaro_query_stop", "findaro_stem"],
                },
                "findaro_phonetic": {
                    "type": "custom", "tokenizer": "icu_tokenizer",
                    "filter": [*base, "findaro_index_stop", "findaro_stem", *phon_filters],
                },
                "findaro_phonetic_search": {
                    "type": "custom", "tokenizer": "icu_tokenizer",
                    "filter": [*base, "findaro_query_stop", "findaro_stem", *phon_filters],
                },
            },
        }
    }
