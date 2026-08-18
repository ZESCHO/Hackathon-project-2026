"""
Understanding and grounded answering for the Secure Agentic-AI platform.

Two responsibilities:

1. understand_request  - classify a message and collect the fields a
                         service request needs before it can be filed.
2. answer_question     - answer institutional questions using ONLY
                         verified snippets retrieved from the knowledge
                         base, with citations, or decline.

The agent must never state institutional policy from its own memory.
"""

import re
import time
import json
from datetime import datetime

from app.ollama_client import ask_model, ask_model_verbose, ModelUnavailable
from app import trace
from app.rag.retriever import (
    search,
    format_context,
    get_index,
    STOPWORDS
)


# Categories the platform can act on, plus the two non-action cases.
SERVICE_CATEGORIES = [
    "certificate",
    "maintenance",
    "laboratory",
    "grievance"
]

ALL_CATEGORIES = SERVICE_CATEGORIES + ["information", "unknown"]


# The platform converses in English only. A message in another language
# is declined rather than half-understood, because a misread service
# request becomes a real institutional action.
UNSUPPORTED_LANGUAGE_MESSAGE = (
    "Sorry, I can only understand English at the moment. "
    "Please rewrite your request in English."
)


# The model's own confidence word, as a starting score. It is only a
# starting point: a model asked how sure it is tends to say "high".
CONFIDENCE_SCORES = {
    "high": 0.9,
    "medium": 0.6,
    "low": 0.3
}

# Below this the platform will not file anything. It asks the user to
# restate instead, because a misread request becomes a real
# institutional action that someone then has to undo.
CONFIDENCE_FLOOR = 0.55

# Each value the model invented and the grounding checks threw away is
# evidence it did not understand the message, whatever it claims about
# its own confidence.
FABRICATION_PENALTY = 0.25

# A request whose details all had to be recovered by the second pass
# was not clearly stated the first time.
RETRY_PENALTY = 0.1


# Words that stand in for the thing the user has not named.
VAGUE_MARKERS = {
    "something", "someone", "somebody", "somewhere", "anything",
    "stuff", "thing", "things", "issue", "issues", "problem",
    "problems", "matter", "situation"
}

# Concrete things a real service request tends to mention. Any one of
# these, or any digit, means the user named something specific enough
# to act on.
CONCRETE_NOUNS = {
    "block", "room", "hostel", "floor", "building", "wing", "lab",
    "labs", "laboratory", "library", "canteen", "mess", "gate",
    "classroom", "class", "hall", "office", "washroom", "toilet",
    "ac", "fan", "light", "lights", "socket", "switch", "tap",
    "water", "pipe", "sink", "drain", "projector", "computer",
    "wifi", "internet", "network", "door", "window", "chair",
    "desk", "table", "bench", "board", "certificate", "bonafide",
    "transfer", "character", "marksheet", "scholarship", "fee",
    "fees", "exam", "attendance", "warden", "senior", "seniors",
    "faculty", "professor", "teacher", "ragging", "harassment"
}


def _has_concrete_anchor(text):
    """
    Whether the message names anything specific enough to act on.

    "something happened and I am not happy" names nothing: there is no
    place, object or person in it, so there is nothing to file against.
    A digit, or any concrete campus noun, is enough.
    """

    lowered = (text or "").lower()

    if any(character.isdigit() for character in lowered):
        return True

    words = set(re.findall(r"[a-z]+", lowered))

    return bool(words & CONCRETE_NOUNS)


def _is_vague(text):
    """
    A message that leans on placeholder words and names nothing.
    """

    words = set(re.findall(r"[a-z]+", (text or "").lower()))

    return bool(words & VAGUE_MARKERS) and not _has_concrete_anchor(text)


REQUIRED_FIELDS = {
    "certificate": ["certificate_type", "purpose"],
    "maintenance": ["location", "room", "description"],
    "laboratory": [
        "laboratory_name",
        "booking_date",
        "booking_time",
        "purpose"
    ],
    "grievance": ["subject", "description"]
}


# Fields whose value is drawn from a known set. These are resolved by
# matching the transcript against the knowledge base instead of relying
# on the model, which is both more reliable and auditable.
CLOSED_VOCABULARY_FIELDS = {
    "certificate": "certificate_type",
    "laboratory": "laboratory_name"
}


def _known_values(category):
    """
    Collect the recognised values for a category's closed field.

    Each value is returned with the aliases that should resolve to it,
    so a loosely worded request ("my TC", "robotics lab") still lands
    on the canonical name that policy rules are matched against.

    Values come from the knowledge base itself, so adding a new
    certificate type to certificates.json makes it recognisable here
    with no code change.
    """

    suffix = {
        "certificate": "certificate",
        "laboratory": "lab"
    }.get(category)

    if not suffix:
        return []

    values = []

    for document in get_index()["documents"]:

        if document["category"] != category:
            continue

        alias_map = document.get("alias_map") or {}

        # When a snippet names several things, each canonical name gets
        # only its own aliases; otherwise the whole list applies.
        shared_aliases = [] if alias_map else [
            alias.lower()
            for alias in document.get("aliases", [])
        ]

        # Titles name the thing ("Transfer Certificate"); prose mentions
        # specific instances ("Advanced Chemistry Lab, Robotics Lab").
        for phrase in _candidate_phrases(document, suffix):

            if any(phrase == value["name"] for value in values):
                continue

            values.append({
                "name": phrase,
                # The distinguishing word, plus every alias from the
                # knowledge base entry this phrase came from.
                "keys": [phrase.split()[0].lower()] + (
                    [a.lower() for a in alias_map.get(phrase, [])]
                    if alias_map
                    else shared_aliases
                )
            })

    return values


def known_value_names(category):
    """
    Just the canonical names, for prompting and display.
    """

    return [value["name"] for value in _known_values(category)]


_PHRASE_PATTERN = re.compile(
    r"\b((?:[A-Z][\w-]*\s+){1,3}(?:Certificate|Lab|Laboratory))\b"
)


def _candidate_phrases(document, suffix):
    """
    Pull proper-noun phrases naming a certificate or laboratory.
    """

    found = []

    for text in (document["title"], document["content"]):

        for match in _PHRASE_PATTERN.findall(text or ""):

            phrase = match.strip()

            # A sentence-initial article is capitalised, so it gets
            # swept into the phrase ("A Bonafide Certificate").
            phrase = re.sub(
                r"^(?:A|An|The)\s+",
                "",
                phrase
            )

            # "General certificate request rules" is a policy heading,
            # not the name of an issuable certificate.
            if phrase.lower().startswith(("general", "all", "each")):
                continue

            if len(phrase.split()) < 2:
                continue

            if phrase not in found:
                found.append(phrase)

    return found


# Fields whose value must be traceable to something the user actually
# typed. A room number or a block name cannot be inferred, so a value
# that appears nowhere in the conversation was invented.
VERBATIM_FIELDS = {"location", "room"}

# Fields naming a specific thing. The generic head word is not enough:
# "certificate" does not identify a certificate, and "lab" does not
# identify a laboratory. The qualifier has to come from the user.
QUALIFIED_FIELDS = {
    "certificate_type": {"certificate", "certificates"},
    "laboratory_name": {"lab", "labs", "laboratory", "laboratories"}
}

# Fields that may be paraphrased but must still be anchored in
# something the user said, rather than supplied from nowhere.
ANCHORED_FIELDS = {"purpose", "subject"}

# Naming the service back at us is not an answer. "Purpose: certificate"
# tells a clerk nothing, so these words cannot carry an anchored field
# on their own.
GENERIC_TERMS = {
    "certificate", "certificates", "lab", "labs", "laboratory",
    "laboratories", "maintenance", "grievance", "complaint", "booking",
    "book", "request", "requests", "need", "needs", "want", "wants",
    "issue", "problem", "service", "apply", "application", "get"
}

# Fields that require the user to have expressed a time at all.
TEMPORAL_FIELDS = {"booking_date", "booking_time"}

# Any digit, month, weekday or relative day counts as the user having
# expressed a time. Without one, a date in the output was invented.
_TEMPORAL_CUE = re.compile(
    r"\d|"
    r"jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|"
    r"mon|tue|wed|thu|fri|sat|sun|"
    r"today|tomorrow|tonight|morning|afternoon|evening|noon|"
    r"next|this|week|weekend|day after",
    re.IGNORECASE
)

# Fields the platform will ask for but will not block a request on.
OPTIONAL_FIELDS = {
    "maintenance": ["urgency", "available_time"],
    "laboratory": [],
    "certificate": [],
    "grievance": ["urgency"]
}


FIELD_DESCRIPTIONS = {
    "certificate_type": "which certificate is wanted",
    "purpose": "why they need it / what it is for",
    "location": "building or block name",
    "room": "room or door number",
    "description": "what the problem or request is",
    "laboratory_name": "which laboratory",
    "booking_date": "the date, as DD Mon YYYY",
    "booking_time": "the time, as 24-hour HH:MM",
    "subject": "a short title for the grievance",
    "urgency": "how urgent they say it is (low, medium or high)",
    "available_time": "when they are free for a visit"
}


# What the user sees when asked for a field.
FIELD_PROMPTS = {
    "certificate_type": "certificate type",
    "purpose": "purpose",
    "location": "building or block",
    "room": "room number",
    "description": "what is wrong",
    "laboratory_name": "laboratory",
    "booking_date": "date",
    "booking_time": "time",
    "subject": "subject",
    "urgency": "urgency - low / medium / high (optional)",
    "available_time": "best time to visit (optional)"
}


def _timed_call(purpose, prompt, temperature=0.2):
    """
    Call the model and record the exchange in the trace log.
    """

    started = time.time()

    answer, thinking = ask_model_verbose(prompt, temperature=temperature)

    trace.model_call(
        purpose,
        thinking,
        answer,
        seconds=time.time() - started
    )

    return answer, thinking


def _extract_fields(category, transcript, missing):
    """
    Second pass that extracts only the fields still outstanding.

    The classification prompt asks the model to do many things at once
    and it reliably drops values under that load. Asking one small,
    explicit question per gap recovers them.
    """

    if not missing:
        return {}, 0

    today = datetime.now()

    wanted = "\n".join(
        f"- {field}: {FIELD_DESCRIPTIONS.get(field, field)}"
        for field in missing
    )

    prompt = f"""
Extract information from a campus service message.

Today's date is {today.strftime("%d %b %Y")} ({today.strftime("%A")}).
Resolve "tomorrow", "next Monday" and similar into a real date.

Message:
{transcript}

Extract ONLY these fields:
{wanted}

Rules:
- Use the user's own words where possible.
- If a field genuinely is not stated, use an empty string.
- Never invent a value.

Return ONLY a JSON object with exactly these keys:
{json.dumps({field: "" for field in missing})}
"""

    try:
        raw, thinking = _timed_call(
            f"extract missing fields: {', '.join(missing)}",
            prompt,
            temperature=0.1
        )
        data = _extract_json(raw)

    except (ModelUnavailable, ValueError, json.JSONDecodeError) as error:
        print("FIELD EXTRACTION ERROR:", error)
        trace.note("EXTRACTION FAILED", str(error))
        return {}, 0

    if not isinstance(data, dict):
        return {}, 0

    extracted = {}

    rejected = 0

    for field in missing:

        value = str(data.get(field, "")).strip()

        if not value:
            continue

        if not _is_grounded_value(field, value, transcript):
            trace.rejected(
                field, value,
                "not present in what the user typed (invented or "
                "copied from a prompt example)"
            )
            rejected += 1
            continue

        if not _is_plausible_value(field, value, transcript):
            trace.rejected(
                field, value,
                "echoes the whole message back instead of answering"
            )
            rejected += 1
            continue

        extracted[field] = value

    return extracted, rejected


def _normalize_text(text):
    return " ".join(text.lower().split())


def _tokens(text):
    """
    Word tokens of a string, lowercased.
    """

    return re.findall(r"[\w']+", _normalize_text(text))


def _is_grounded_value(field, value, transcript):
    """
    Check that a field's value really came from the user.

    The model will happily fill a field it was never given, copying a
    value out of a worked example in the prompt ("room 204", "bank
    loan") or inventing a plausible one. Filing that creates a real
    ticket for the wrong room, or a certificate for a purpose the
    student never stated, so each kind of field is checked against
    what was actually typed.

    Rules are deliberately different per field, because "how much may
    this be reworded?" genuinely differs:

      location / room     nothing may be added; every token must appear
      certificate_type /
      laboratory_name     the qualifier must come from the user, though
                          a knowledge base alias may resolve it
      booking_date / time the user must have expressed a time at all
      purpose / subject   may be reworded, but must share a real word
      description         free; the complaint is the message itself
    """

    value_text = _normalize_text(value)

    if not value_text:
        return False

    transcript_tokens = set(_tokens(transcript))

    haystack = _normalize_text(transcript)

    # ---- must be reproduced exactly ----

    if field in VERBATIM_FIELDS:

        if value_text in haystack:
            return True

        # Token matching, not substring: block names are often a single
        # letter, and "B block" would otherwise match the "b" inside
        # "broken". "A block" and "B block" differ by one character and
        # confusing them sends someone to the wrong building.
        value_tokens = _tokens(value_text)

        return bool(value_tokens) and all(
            token in transcript_tokens for token in value_tokens
        )

    # ---- must name something the user named ----

    if field in QUALIFIED_FIELDS:

        # A knowledge base alias counts: "my TC" legitimately resolves
        # to "Transfer Certificate" without those words being typed.
        category = (
            "certificate"
            if field == "certificate_type"
            else "laboratory"
        )

        for known in _known_values(category):

            if _normalize_text(known["name"]) != value_text:
                continue

            if any(key and key in haystack for key in known["keys"]):
                return True

        generic = QUALIFIED_FIELDS[field]

        qualifier = [
            token
            for token in _tokens(value_text)
            if token not in generic
        ]

        # "certificate" alone identifies nothing.
        return bool(qualifier) and all(
            token in transcript_tokens for token in qualifier
        )

    # ---- the user must have mentioned a time at all ----

    if field in TEMPORAL_FIELDS:
        return bool(_TEMPORAL_CUE.search(transcript or ""))

    # ---- may be reworded, must still be anchored ----

    if field in ANCHORED_FIELDS:

        content = [
            token
            for token in _tokens(value_text)
            if token not in STOPWORDS
            and token not in GENERIC_TERMS
            and len(token) > 2
        ]

        # Everything left was the name of the service itself, which
        # answers nothing.
        if not content:
            return False

        return any(token in transcript_tokens for token in content)

    return True


def _is_plausible_value(field, value, transcript):
    """
    Reject an "extracted" value that is really the whole message again.

    Pressed for a field the user never supplied, the model tends to echo
    the request back ("purpose": "I want a character certificate").
    Filing that would defeat the point of asking, so it is discarded and
    the user is asked instead.
    """

    # The complaint or fault report legitimately is the whole message.
    if field == "description":
        return True

    normalized = _normalize_text(value)
    whole = _normalize_text(transcript)

    if normalized == whole:
        return False

    # A short field that swallowed most of the message is an echo.
    if (
        len(value.split()) > 5
        and len(normalized) > 0.6 * len(whole)
    ):
        return False

    return True


def _resolve_closed_vocabulary(category, fields, transcript):
    """
    Fill a closed field by matching the transcript against known values.

    The model regularly returns an empty certificate_type even when the
    user plainly named one. Matching the text against the knowledge
    base, including its aliases, recovers the canonical name without
    inventing anything.
    """

    field = CLOSED_VOCABULARY_FIELDS.get(category)

    if not field:
        return fields

    current = str(fields.get(field, "")).strip()

    # Search the model's own value first so a loose form is snapped to
    # the canonical name that policy checks match on.
    haystack = f"{current}\n{transcript}".lower()

    for value in _known_values(category):

        if any(key and key in haystack for key in value["keys"]):
            fields[field] = value["name"]
            return fields

    return fields


# =========================================================
# JSON EXTRACTION
# =========================================================

def _extract_json(text):
    """
    Pull the first balanced JSON object out of a model response.

    Local models regularly wrap JSON in prose or markdown fences, so
    locating the object is more reliable than trusting the whole reply.
    """

    if not text:
        raise ValueError("Empty model response")

    text = text.strip()

    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text[3:]
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:]

    start = text.find("{")

    if start == -1:
        raise ValueError("No JSON object in model response")

    depth = 0
    in_string = False
    escaped = False

    for position in range(start, len(text)):

        character = text[position]

        if in_string:

            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False

            continue

        if character == '"':
            in_string = True

        elif character == "{":
            depth += 1

        elif character == "}":

            depth -= 1

            if depth == 0:
                # strict=False tolerates raw newlines inside strings.
                # The model emits them for the multi-line clarification
                # prompt, which strict JSON rejects outright.
                return json.loads(
                    text[start:position + 1],
                    strict=False
                )

    raise ValueError("Unterminated JSON object in model response")


# =========================================================
# GROUNDED ANSWERING
# =========================================================

_CITATION_MARKER = re.compile(r"\s*[\[(]\s*[a-z]+-\d+\s*[\])]")


def _strip_citation_markers(text):
    """
    Remove inline "[cert-001]" markers from an answer.
    """

    cleaned = _CITATION_MARKER.sub("", text or "")

    return " ".join(cleaned.split()).strip()


def _unverified_answer(reason):
    """
    The standard refusal used whenever the knowledge base cannot
    support an answer. Declining is always preferred to guessing.

    A fixed string rather than model output: a refusal must say
    exactly what we mean.
    """

    return {
        "answer": (
            "I don't have verified information about that in the "
            "institutional knowledge base, so I can't answer it. "
            "Please contact the relevant campus office to confirm."
        ),
        "sources": [],
        "grounded": False,
        "reason": reason
    }


# Top score below which a lexical result set is considered weak enough
# to be worth a second, expanded retrieval pass.
WEAK_RETRIEVAL_SCORE = 4.0


def _expand_query(question):
    """
    Rewrite a question into the vocabulary a policy document would use.

    Students ask "is anyone going to find out what I complained about";
    the policy says "grievance details are never disclosed". Those share
    almost no words, so pure keyword matching misses the snippet. Asking
    the model for institutional synonyms bridges that gap.
    """

    prompt = (
        "Rewrite this campus service question as a list of 8-12 search "
        "keywords covering the formal institutional words a policy "
        "document would use (synonyms, procedure names, categories). "
        "Output ONLY a comma-separated list.\n\n"
        f"Question: {question}"
    )

    try:
        return ask_model(prompt, temperature=0.1)

    except ModelUnavailable as error:
        print("QUERY EXPANSION UNAVAILABLE:", error)
        return ""


def _retrieve(question, category=None):
    """
    Retrieve verified snippets, expanding the query only when needed.

    The fast lexical pass handles literal questions ("fee for a transfer
    certificate") in a single round trip. Only when it looks weak do we
    spend a second model call on synonym expansion.
    """

    hits = search(question, top_k=4, category=category)

    if hits and hits[0]["score"] >= WEAK_RETRIEVAL_SCORE:
        return hits

    expansion = _expand_query(question)

    if not expansion:
        return hits

    expanded_hits = search(
        f"{question} {expansion}",
        top_k=4,
        category=category,
        min_score=0.0
    )

    return expanded_hits or hits


def answer_question(question, category=None):
    """
    Answer an institutional question strictly from verified snippets.

    Returns a dict with the answer text, the snippet ids it was drawn
    from, and a `grounded` flag. When `grounded` is False the platform
    is explicitly saying it does not know.
    """

    hits = _retrieve(question, category=category)

    trace.note(
        "RETRIEVED FROM KNOWLEDGE BASE",
        [f"{hit['id']}  score={hit['score']}  {hit['title']}" for hit in hits]
        or "nothing above the relevance threshold"
    )

    if not hits:
        return _unverified_answer("No relevant knowledge base entry")

    prompt = f"""
You answer questions about institutional services for a campus
service platform.

VERIFIED INFORMATION (the only facts you may use):

{format_context(hits)}

USER QUESTION:
{question}

Rules you must follow:

- Answer using ONLY the verified information above.
- Never add policies, timelines, fees or requirements that do not
  appear above, even if you believe you know them.
- If the verified information does not answer the question, set
  "sufficient" to false and leave "answer" empty.
- Cite the id of every snippet you used, exactly as written in
  square brackets above.
- Keep the answer under 60 words, plain and direct.

Return ONLY this JSON object:

{{
    "sufficient": true or false,
    "answer": "the answer, or empty string if not sufficient",
    "sources": ["ids of the snippets you used"]
}}
"""

    try:
        raw, thinking = _timed_call("answer from verified sources", prompt)
        data = _extract_json(raw)

    except ModelUnavailable as error:
        print("MODEL UNAVAILABLE:", error)
        trace.note("MODEL UNAVAILABLE", str(error))
        return _unverified_answer("Model unavailable")

    except (ValueError, json.JSONDecodeError) as error:
        print("GROUNDED ANSWER PARSE ERROR:", error)
        return _unverified_answer("Unreadable model response")

    if not data.get("sufficient") or not (data.get("answer") or "").strip():
        return _unverified_answer("Knowledge base did not cover the question")

    # Only ids that were actually retrieved may be cited; this stops a
    # model from inventing a source to make an answer look verified.
    retrieved_ids = {hit["id"] for hit in hits}

    cited = [
        source
        for source in data.get("sources", [])
        if source in retrieved_ids
    ]

    if not cited:
        return _unverified_answer("Answer cited no verified source")

    return {
        # Sources are returned separately and shown as their own badge,
        # so inline markers would only clutter the sentence.
        "answer": _strip_citation_markers(data["answer"]),
        "sources": cited,
        "grounded": True,
        "reason": ""
    }


# =========================================================
# REQUEST UNDERSTANDING
# =========================================================

def _not_english_result():
    """
    The reply given to a message that is not in English.

    Nothing is classified and no request is filed. Guessing at a
    half-understood service request is worse than declining, because
    the request becomes a real institutional action.
    """

    return {
        "intent": "unknown",
        "category": "unknown",
        "action": "unknown",
        "confidence": "low",
        "message": UNSUPPORTED_LANGUAGE_MESSAGE,
        "status": "complete",
        "missing": [],
        "clarification_question": "",
        "fields": {},
        "sources": [],
        "grounded": False,
        "is_english": False
    }


# Characters that belong to a writing system other than the Latin one.
_NON_LATIN = re.compile(
    r"[^\x00-\x7FÀ-ɏ -⁯₠-₿]"
)


# High signal words that effectively never appear in an English
# sentence. The model is unreliable on short Latin-script messages
# ("Necesito un certificado"), so these catch the common cases before
# it is asked.
_FOREIGN_TOKENS = {
    # Spanish / Portuguese
    "necesito", "quiero", "quisiera", "certificado", "solicitud",
    "por favor", "gracias", "una", "para", "como", "cuanto", "cuánto",
    "donde", "dónde", "preciso", "obrigado",
    # French
    "veux", "voudrais", "bonjour", "merci", "pour", "avec", "combien",
    "certificat", "demande", "sil vous plait", "s'il",
    # German
    "ich", "bitte", "danke", "brauche", "möchte", "mochte",
    # Romanised Hindi / Urdu
    "mujhe", "chahiye", "kripya", "kaise", "kitna", "hai", "kya",
    "karna", "banwana", "dhanyavad", "shukriya",
}


def _looks_non_english(text):
    """
    Cheap check for a message that is not English.

    Two signals, neither needing a model call: a non-Latin script
    (Devanagari, Tamil, Bengali, Arabic, CJK), or a word that only
    appears in another language. Anything subtler is left to the model,
    which reports it through "is_english".
    """

    stripped = (text or "").strip()

    if not stripped:
        return False

    non_latin = len(_NON_LATIN.findall(stripped))

    # A stray emoji or symbol should not trip this; a real sentence in
    # another script is overwhelmingly non-Latin.
    if non_latin > max(3, len(stripped) * 0.3):
        return True

    lowered = stripped.lower()

    words = set(re.findall(r"[\w']+", lowered))

    if words & _FOREIGN_TOKENS:
        return True

    return any(
        phrase in lowered
        for phrase in _FOREIGN_TOKENS
        if " " in phrase
    )


def _fallback_understanding(message):
    """
    Safe result used when the model cannot be reached or parsed.
    """

    return {
        "intent": "unknown",
        "category": "unknown",
        "action": "unknown",
        "confidence": "low",
        "message": message,
        "status": "needs_clarification",
        "missing": [],
        "clarification_question": "",
        "fields": {},
        "sources": [],
        "grounded": False
    }


def understand_request(user_request, history=None):
    """
    Classify a message and track the fields its service request needs.

    Returns the structured understanding used by the /chat route. For
    questions (category "information") the reply is generated by the
    grounded answering path instead of free text.
    """

    history = history or []

    # A different script needs no model call to recognise.
    if _looks_non_english(user_request):
        return _not_english_result()

    history_text = "\n".join(
        f"{turn['role']}: {turn['content']}"
        for turn in history
    )

    # Everything the user has said, used for deterministic field
    # resolution that must not depend on the model remembering.
    transcript = "\n".join(
        [
            turn["content"]
            for turn in history
            if turn.get("role") == "user"
        ]
        + [user_request]
    )

    # The model has no clock, so relative dates like "tomorrow" cannot
    # be resolved without being told what today is.
    today = datetime.now()

    # Supplying the recognised values keeps these fields canonical
    # however loosely the user phrased them.
    certificate_types = ", ".join(known_value_names("certificate")) or "none"
    laboratory_names = ", ".join(known_value_names("laboratory")) or "none"

    prompt = f"""
You are the understanding module of a Secure Agentic-AI institutional
service platform.

Today's date is {today.strftime("%d %b %Y")} ({today.strftime("%A")}).
Resolve relative dates such as "tomorrow", "next Monday" or "in two
days" into an absolute date in "DD Mon YYYY" form. Resolve times such
as "3pm" into 24-hour "HH:MM" form.

Classify the user's request and return ONLY valid JSON.

Categories:
- certificate   (the user wants to REQUEST a certificate)
- maintenance   (the user wants to REPORT a maintenance problem)
- laboratory    (the user wants to BOOK a laboratory)
- grievance     (the user wants to SUBMIT a grievance)
- information   (the user is ASKING a question about rules, fees,
                 timelines, eligibility or policy - not asking you to
                 file anything)
- unknown       (small talk or anything unrelated to the above)

Intents:
certificate_request, maintenance_report, laboratory_booking,
grievance_submission, information_query, unknown

Distinguishing requests from questions matters. A message that ASKS
about rules, fees, timelines, eligibility or procedure is
"information", never a service request:

- "I need a bonafide certificate for a bank loan"  -> certificate
- "How long does a bonafide certificate take?"     -> information
- "The AC in room 12 of B block is broken"         -> maintenance
- "the lab is dirty"                               -> maintenance
- "the lab projector has stopped working"          -> maintenance
- "I want to book the lab on Friday"               -> laboratory

Naming a laboratory does not make it a booking. A complaint about
something being broken, dirty, leaking or not working is maintenance,
whatever room it happens in. Only a request to RESERVE a laboratory
for a time slot is "laboratory".
- "How fast are AC repairs handled?"               -> information

A question mark, or a phrase like how long / how much / do I need /
is it / what is, is a strong signal for "information".

Conversation so far:
{history_text}

User request:
{user_request}

Required fields per category:
- certificate: certificate_type, purpose
- maintenance: location, room, description
- laboratory: laboratory_name, booking_date, booking_time, purpose
- grievance: subject, description

Optional fields. Capture these into "fields" when the user states
them, but NEVER list them in "missing" and never treat their absence
as incomplete:
- maintenance: urgency, available_time
- grievance: urgency

Extract every required field the user has already given, anywhere in
the conversation, into "fields" using those exact field names. Do not
leave a field out because it was phrased casually. Worked examples:

Copy values ONLY from the user's own message. Never carry a value
over from these examples; they show the shape of the answer, not its
content. If the user did not state something, it goes in "missing".

  message mentions a certificate and why they need it
  -> both certificate_type and purpose are filled, missing: []

  message names a block and a room and the fault
  -> location, room and description filled, missing: []

  message names only the fault, with no place
  -> description filled,
     missing: ["location", "room"]      <- do NOT guess these

  message names a laboratory but no date, time or reason
  -> laboratory_name filled,
     missing: ["booking_date", "booking_time", "purpose"]

Only list a field in "missing" if the user genuinely has not given it,
and only fill a field if the user genuinely did.

Two fields must be reported using their official name, because
institutional policy is matched against these exact names:

- certificate_type must be one of: {certificate_types}
- laboratory_name must be one of these when the user means one of
  them: {laboratory_names}

Every other field keeps the user's own wording.

For categories "information" and "unknown", status must always be
"complete", "missing" must be empty and "fields" must be an empty
object. Never ask a question for clarification in those cases.

Judge completeness using the ENTIRE conversation above, not just the
latest message - information given earlier still counts.

Set "status" to "complete" only if every required field for the
detected category has been provided somewhere in the conversation.
Otherwise set "status" to "needs_clarification" and list the missing
field names in "missing".

Format "clarification_question" as ONLY the missing field names, each
on its own line followed by a colon, with no sentence before or after:

location:
room:

Keep "message" to one short sentence and never repeat what is in
clarification_question.

Report whether the message is written in English in "is_english".
Set it to false for ANY other language, however short the message,
including one written in Latin letters:

- "I need a bonafide certificate"   -> is_english true
- "Necesito un certificado"         -> is_english false
- "Je veux un certificat"           -> is_english false
- "mujhe certificate chahiye"       -> is_english false
- "Ich brauche ein Zertifikat"      -> is_english false

A message can contain an English noun and still not be English.
Always write "message" itself in English.

Return exactly this structure:

{{
    "is_english": true or false,
    "intent": "one of the intents above",
    "category": "one of the categories above",
    "action": "request, report, book, submit, ask, or unknown",
    "confidence": "high, medium, or low",
    "message": "one short sentence describing what you understood",
    "status": "complete or needs_clarification",
    "missing": ["missing required field names, empty if none"],
    "clarification_question": "missing field names as described, else empty",
    "fields": {{"extracted field values you actually have"}}
}}
"""

    try:
        raw, thinking = _timed_call("classify the request", prompt)
        data = _extract_json(raw)

    except ModelUnavailable as error:
        print("MODEL UNAVAILABLE:", error)
        trace.note("MODEL UNAVAILABLE", str(error))
        return _fallback_understanding(
            "The assistant is offline right now, so I can't process "
            "that. Please use the service forms, or try again shortly."
        )

    except (ValueError, json.JSONDecodeError) as error:
        print("UNDERSTANDING PARSE ERROR:", error)
        return _fallback_understanding(
            "I could not understand that clearly. Could you rephrase it?"
        )

    return _normalize(data, user_request, transcript)


def _normalize(data, user_request, transcript=""):
    """
    Validate the model's classification and attach grounded content.
    """

    category = str(data.get("category", "unknown")).lower().strip()

    if category not in ALL_CATEGORIES:
        category = "unknown"

    fields = data.get("fields")

    if not isinstance(fields, dict):
        fields = {}

    missing = data.get("missing")

    if not isinstance(missing, list):
        missing = []

    status = str(data.get("status", "complete")).lower().strip()

    # Latin-script languages only the model can tell apart.
    if data.get("is_english") is False:
        return _not_english_result()

    result = {
        "is_english": True,
        "intent": str(data.get("intent", "unknown")),
        "category": category,
        "action": str(data.get("action", "unknown")),
        "confidence": str(data.get("confidence", "low")).lower(),
        "message": str(data.get("message", "")).strip(),
        "status": status,
        "missing": [str(item) for item in missing],
        "clarification_question": str(
            data.get("clarification_question", "")
        ).strip(),
        "fields": fields,
        "sources": [],
        "grounded": False
    }

    # ----------------------------------------------------
    # QUESTIONS ARE ANSWERED FROM VERIFIED SOURCES ONLY
    # ----------------------------------------------------

    if category == "information":

        grounded = answer_question(user_request)

        result["message"] = grounded["answer"]
        result["sources"] = grounded["sources"]
        result["grounded"] = grounded["grounded"]
        result["status"] = "complete"
        result["missing"] = []
        result["fields"] = {}
        result["clarification_question"] = ""

        return result

    # ----------------------------------------------------
    # NON-ACTION MESSAGES NEVER ASK FOR FIELDS
    # ----------------------------------------------------

    if category == "unknown":

        result["status"] = "complete"
        result["missing"] = []
        result["fields"] = {}
        result["clarification_question"] = ""

        return result

    # ----------------------------------------------------
    # SERVICE REQUESTS: TRUST THE FIELDS, NOT THE CLAIM
    # ----------------------------------------------------

    # The classification prompt carries worked examples, and the model
    # will copy a value straight out of one ("room 204") when the user
    # gave none. Drop anything not traceable to what they typed BEFORE
    # completeness is judged, or the request is filed against a room
    # nobody mentioned.
    fabricated = 0

    for field in list(fields):

        value = str(fields.get(field, "")).strip()

        if value and not _is_grounded_value(field, value, transcript):
            trace.rejected(
                field, value,
                "not present in what the user typed (invented or "
                "copied from a prompt example)"
            )
            fields.pop(field)
            fabricated += 1

    fields = _resolve_closed_vocabulary(category, fields, transcript)

    # A grievance's description is the complaint itself. Reusing the
    # student's own words is not invention, and saves asking them to
    # retype what they just wrote.
    if category == "grievance" and not str(
        fields.get("description", "")
    ).strip():

        if len(user_request.strip()) >= 20:
            fields["description"] = user_request.strip()

    # The model sometimes reports "complete" while a required field is
    # still absent, which would file an incomplete request. Recompute
    # completeness from the extracted values instead.
    required = REQUIRED_FIELDS.get(category, [])

    def outstanding():
        return [
            field
            for field in required
            if not str(fields.get(field, "")).strip()
        ]

    # One focused retry before giving up and asking the user for
    # something they may already have told us. Optional fields ride
    # along on the same call: we offer them in the question, so
    # discarding an answer the user did give would be rude.
    needed_retry = False

    if outstanding():

        wanted = outstanding() + [
            field
            for field in OPTIONAL_FIELDS.get(category, [])
            if not str(fields.get(field, "")).strip()
        ]

        recovered, retry_rejected = _extract_fields(
            category, transcript, wanted
        )

        fields.update(recovered)

        fabricated += retry_rejected

        needed_retry = bool(recovered)

    result["fields"] = fields

    # ------------------------------------------------
    # HOW SURE ARE WE, REALLY
    # ------------------------------------------------

    score = CONFIDENCE_SCORES.get(result["confidence"], 0.3)

    score -= FABRICATION_PENALTY * fabricated

    if needed_retry:
        score -= RETRY_PENALTY

    # A model asked how sure it is will usually say "high", so its own
    # word cannot be the only signal. This one is checked against the
    # text itself and gives the same answer every time.
    vague = _is_vague(transcript)

    if vague:
        score = min(score, 0.4)

    score = max(0.0, min(1.0, round(score, 2)))

    result["confidence_score"] = score
    result["uncertain"] = score < CONFIDENCE_FLOOR

    trace.note(
        "CONFIDENCE",
        f"model said {result['confidence']}, "
        f"{fabricated} invented value(s) rejected, "
        f"retry needed: {needed_retry}, "
        f"names nothing specific: {vague} -> score {score} "
        f"({'UNCERTAIN' if result['uncertain'] else 'confident'})"
    )

    actually_missing = outstanding()

    result["missing"] = actually_missing

    trace.note("FIELDS ACCEPTED", fields)

    # ------------------------------------------------
    # TOO UNSURE TO ACT
    # ------------------------------------------------

    # Filing on a shaky reading creates a real ticket, booking or
    # grievance that a human then has to find and undo. Asking costs
    # one more message.
    if result["uncertain"]:

        result["status"] = "needs_clarification"
        result["missing"] = actually_missing

        result["clarification_question"] = (
            "I'm not confident I understood that correctly, so I "
            "haven't filed anything yet.\n\n"
            "Could you restate it with the specifics? For a "
            f"{category} request that means:\n\n"
            + "\n".join(
                f"{FIELD_PROMPTS.get(field, field)}:"
                for field in REQUIRED_FIELDS.get(category, [])
            )
        )

        trace.decision_note(
            f"WITHHELD - confidence {result['confidence_score']} is "
            f"below the {CONFIDENCE_FLOOR} floor; asked the user to "
            f"restate rather than filing"
        )

        return result

    if actually_missing:

        result["status"] = "needs_clarification"

        # Always derived from the recomputed list: the model's own
        # question routinely disagrees with what is actually missing.
        # Optional fields are offered alongside, but never block filing.
        wanted = actually_missing + [
            field
            for field in OPTIONAL_FIELDS.get(category, [])
            if not str(fields.get(field, "")).strip()
        ]

        result["clarification_question"] = (
            "Could you provide the following details listed below:\n\n"
            + "\n".join(
                f"{FIELD_PROMPTS.get(field, field)}:"
                for field in wanted
            )
        )

    else:
        result["status"] = "complete"
        result["clarification_question"] = ""

    return result
