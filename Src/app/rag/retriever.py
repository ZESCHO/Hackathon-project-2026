"""
Lexical retriever over the verified institutional knowledge base.

The agent is never allowed to answer a policy question from its own
memory. It must retrieve verified snippets from knowledge_base/*.json
and answer only from those. If nothing relevant is retrieved, the
caller is expected to say "I don't know" rather than fabricate.

Implementation is BM25 over a very small corpus, using only the
standard library so the platform has no extra dependencies.
"""

import os
import re
import json
import math


# =========================================================
# CORPUS LOCATION
# =========================================================

BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )
)

KNOWLEDGE_BASE_DIR = os.path.join(
    BASE_DIR,
    "knowledge_base"
)


# Maps a knowledge base file onto the service category it describes,
# so retrieval can be narrowed once the agent knows the category.
FILE_TO_CATEGORY = {
    "certificates": "certificate",
    "maintenance": "maintenance",
    "laboratories": "laboratory",
    "grievance": "grievance"
}


# =========================================================
# TOKENIZATION
# =========================================================

STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "do", "does", "did", "doing", "have", "has", "had", "having",
    "i", "me", "my", "we", "our", "you", "your", "it", "its", "they",
    "them", "their", "this", "that", "these", "those",
    "and", "or", "but", "if", "then", "than", "so", "because",
    "of", "to", "in", "on", "at", "for", "with", "from", "by", "about",
    "as", "into", "over", "under", "up", "down", "out",
    "can", "could", "will", "would", "shall", "should", "may", "might",
    "must", "need", "want", "get", "got",
    "what", "when", "where", "which", "who", "whom", "why", "how",
    "there", "here", "some", "any", "all", "no", "not", "very",
    "please", "hello", "hi", "thanks", "thank"
}


# Unicode aware: the knowledge base carries aliases in Devanagari,
# Tamil and Bengali, and questions arrive in those scripts too.
TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)


def _stem(token):
    """
    Very small suffix stripper.

    A real stemmer is overkill for a 16 document corpus; this only
    needs to make "bookings"/"booking" and "certificates"/"certificate"
    land on the same term.
    """

    for suffix in ("ing", "ies", "es", "ed", "s"):

        if len(token) > len(suffix) + 2 and token.endswith(suffix):

            if suffix == "ies":
                return token[: -len(suffix)] + "y"

            return token[: -len(suffix)]

    return token


def tokenize(text):
    """
    Lowercase, split into words, drop stopwords, stem.
    """

    tokens = TOKEN_PATTERN.findall((text or "").lower())

    return [
        _stem(token)
        for token in tokens
        if token not in STOPWORDS and len(token) > 1
    ]


# =========================================================
# CORPUS LOADING
# =========================================================

_INDEX = None


def _load_documents():
    """
    Read every knowledge base file into a flat list of documents.
    """

    documents = []

    if not os.path.isdir(KNOWLEDGE_BASE_DIR):
        return documents

    for filename in sorted(os.listdir(KNOWLEDGE_BASE_DIR)):

        if not filename.endswith(".json"):
            continue

        path = os.path.join(KNOWLEDGE_BASE_DIR, filename)

        try:
            with open(path, "r", encoding="utf-8") as handle:
                entries = json.load(handle)

        except (OSError, json.JSONDecodeError) as error:
            print("KNOWLEDGE BASE ERROR:", filename, error)
            continue

        if not isinstance(entries, list):
            continue

        stem = filename.rsplit(".", 1)[0]
        category = FILE_TO_CATEGORY.get(stem, stem)

        for entry in entries:

            if not isinstance(entry, dict):
                continue

            content = (entry.get("content") or "").strip()

            if not content:
                continue

            raw_aliases = entry.get("aliases") or []

            # Aliases may be a flat list (the snippet names one thing)
            # or a mapping of canonical name -> aliases (it names
            # several, as the restricted laboratories snippet does).
            if isinstance(raw_aliases, dict):
                alias_map = {
                    str(name): [str(a).strip() for a in values if str(a).strip()]
                    for name, values in raw_aliases.items()
                }
                raw_aliases = [a for values in alias_map.values() for a in values]
            else:
                alias_map = {}

            documents.append({
                "id": entry.get("id") or f"{stem}-{len(documents)}",
                "title": (entry.get("title") or "").strip(),
                "content": content,
                # Other names for the same thing, including translations
                # and transliterations. Indexed so a question asked in
                # another language still reaches the right snippet.
                "aliases": [
                    str(alias).strip()
                    for alias in raw_aliases
                    if str(alias).strip()
                ],
                # Present only when the snippet names several things.
                "alias_map": alias_map,
                "category": category,
                "source": filename
            })

    return documents


def _build_index():
    """
    Build the BM25 statistics for the corpus.
    """

    documents = _load_documents()

    document_frequency = {}

    total_length = 0

    for document in documents:

        # Title terms are worth repeating: they are short and
        # highly descriptive of what the snippet covers. Aliases carry
        # the same weight, so a question in another language scores
        # like the English one.
        terms = (
            tokenize(document["title"]) * 2
            + tokenize(" ".join(document.get("aliases", []))) * 2
            + tokenize(document["content"])
        )

        document["terms"] = terms
        document["length"] = len(terms)

        term_counts = {}

        for term in terms:
            term_counts[term] = term_counts.get(term, 0) + 1

        document["term_counts"] = term_counts

        total_length += len(terms)

        for term in term_counts:
            document_frequency[term] = document_frequency.get(term, 0) + 1

    document_count = len(documents)

    average_length = (
        total_length / document_count
        if document_count
        else 0
    )

    return {
        "documents": documents,
        "document_frequency": document_frequency,
        "document_count": document_count,
        "average_length": average_length
    }


def get_index(force_reload=False):
    """
    Return the cached index, building it on first use.
    """

    global _INDEX

    if _INDEX is None or force_reload:
        _INDEX = _build_index()

    return _INDEX


def reload_knowledge_base():
    """
    Rebuild the index after the knowledge base files change.
    """

    return get_index(force_reload=True)


# =========================================================
# SEARCH
# =========================================================

# BM25 tuning constants.
K1 = 1.5
B = 0.75

# A hit must clear this score before it is treated as relevant.
# Below it, the agent should decline instead of guessing.
MIN_SCORE = 1.2

# Shortest prefix that may link two different surface forms of a word.
PREFIX_LENGTH = 5

# Prefix matches are real but weaker evidence than an exact term match.
PREFIX_WEIGHT = 0.8


def _expand_term(term, index):
    """
    Map one query term onto the vocabulary terms it should match.

    The stemmer is deliberately crude, so irregular forms such as
    "cancel" / "cancelled" / "cancellation" do not collapse onto a
    single stem. Matching on a shared prefix recovers those links
    without pulling in unrelated words.
    """

    vocabulary = index["document_frequency"]

    if term in vocabulary:
        return [(term, 1.0)]

    if len(term) < PREFIX_LENGTH:
        return []

    prefix = term[:PREFIX_LENGTH]

    return [
        (candidate, PREFIX_WEIGHT)
        for candidate in vocabulary
        if candidate.startswith(prefix)
    ]


def search(query, top_k=4, category=None, min_score=MIN_SCORE):
    """
    Retrieve the most relevant verified snippets for a query.

    Args:
        query: the user's natural language text
        top_k: maximum number of snippets to return
        category: optional service category to prefer
        min_score: relevance floor; hits below this are discarded

    Returns:
        A list of dicts with id, title, content, category and score,
        ordered most relevant first. An empty list means the knowledge
        base does not cover the question.
    """

    index = get_index()

    if not index["document_count"]:
        return []

    query_terms = tokenize(query)

    if not query_terms:
        return []

    # Expand each query term against the vocabulary so that
    # "cancel" still reaches "cancelled" and "cancellation".
    expanded_terms = {}

    for term in set(query_terms):

        for candidate, weight in _expand_term(term, index):
            expanded_terms[candidate] = max(
                expanded_terms.get(candidate, 0.0),
                weight
            )

    results = []

    for document in index["documents"]:

        score = 0.0

        for term, weight in expanded_terms.items():

            term_frequency = document["term_counts"].get(term, 0)

            if not term_frequency:
                continue

            document_frequency = index["document_frequency"].get(term, 0)

            idf = math.log(
                1
                + (index["document_count"] - document_frequency + 0.5)
                / (document_frequency + 0.5)
            )

            length_norm = (
                1
                - B
                + B * document["length"] / (index["average_length"] or 1)
            )

            score += weight * idf * (
                term_frequency * (K1 + 1)
                / (term_frequency + K1 * length_norm)
            )

        if score <= 0:
            continue

        # A known category is a strong prior, but not a hard filter:
        # general rules sometimes live in another file.
        if category and document["category"] == category:
            score *= 1.5

        results.append({
            "id": document["id"],
            "title": document["title"],
            "content": document["content"],
            "category": document["category"],
            "score": round(score, 3)
        })

    results.sort(key=lambda hit: hit["score"], reverse=True)

    return [
        hit
        for hit in results[:top_k]
        if hit["score"] >= min_score
    ]


def format_context(hits):
    """
    Render retrieved snippets into a block the model can quote from.

    Each snippet is labelled with its id so the model can cite it and
    a human can trace the answer back to a verified source.
    """

    if not hits:
        return "NO VERIFIED INFORMATION WAS RETRIEVED."

    blocks = []

    for hit in hits:

        blocks.append(
            f"[{hit['id']}] {hit['title']}\n{hit['content']}"
        )

    return "\n\n".join(blocks)
