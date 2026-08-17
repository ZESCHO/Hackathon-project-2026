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
import json
from datetime import datetime

from app.ollama_client import ask_model, ModelUnavailable
from app.rag.retriever import search, format_context, get_index
from app.i18n import translate, normalize, language_name, field_label


# Categories the platform can act on, plus the two non-action cases.
SERVICE_CATEGORIES = [
    "certificate",
    "maintenance",
    "laboratory",
    "grievance"
]

ALL_CATEGORIES = SERVICE_CATEGORIES + ["information", "unknown"]


# The model is instructed by language name rather than ISO code, which
# it follows far more reliably.
LANGUAGE_PROMPT_NAMES = {
    "en": "English",
    "hi": "Hindi",
    "ta": "Tamil",
    "bn": "Bengali",
    "es": "Spanish",
    "fr": "French"
}


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
    so a request written in another language still lands on the
    canonical English name that policy rules are matched against.

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


FIELD_DESCRIPTIONS = {
    "certificate_type": "which certificate is wanted",
    "purpose": "why they need it / what it is for",
    "location": "building or block name",
    "room": "room or door number",
    "description": "what the problem or request is",
    "laboratory_name": "which laboratory",
    "booking_date": "the date, as DD Mon YYYY",
    "booking_time": "the time, as 24-hour HH:MM",
    "subject": "a short title for the grievance"
}


def _extract_fields(category, transcript, missing):
    """
    Second pass that extracts only the fields still outstanding.

    The classification prompt asks the model to do many things at once
    and it reliably drops values under that load. Asking one small,
    explicit question per gap recovers them.
    """

    if not missing:
        return {}

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
        data = _extract_json(ask_model(prompt, temperature=0.1))

    except (ModelUnavailable, ValueError, json.JSONDecodeError) as error:
        print("FIELD EXTRACTION ERROR:", error)
        return {}

    if not isinstance(data, dict):
        return {}

    extracted = {}

    for field in missing:

        value = str(data.get(field, "")).strip()

        if value and _is_plausible_value(field, value, transcript):
            extracted[field] = value

    return extracted


def _normalize_text(text):
    return " ".join(text.lower().split())


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

    The model regularly returns an empty or non-English
    certificate_type even when the user plainly named one. Matching the
    text against the knowledge base, including its multilingual
    aliases, recovers the canonical name without inventing anything.
    """

    field = CLOSED_VOCABULARY_FIELDS.get(category)

    if not field:
        return fields

    current = str(fields.get(field, "")).strip()

    # Search the model's own value first so a loose or translated form
    # is snapped to the canonical name that policy checks match on.
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


def _unverified_answer(reason, language="en"):
    """
    The standard refusal used whenever the knowledge base cannot
    support an answer. Declining is always preferred to guessing.

    This is a fixed translated string rather than model output: a
    refusal must say exactly what we mean in every language.
    """

    return {
        "answer": translate("chat.unverified", language),
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


def answer_question(question, category=None, language="en"):
    """
    Answer an institutional question strictly from verified snippets.

    Returns a dict with the answer text, the snippet ids it was drawn
    from, and a `grounded` flag. When `grounded` is False the platform
    is explicitly saying it does not know.

    The answer is written in the user's language, but it is still drawn
    only from the English knowledge base: translation happens at the
    point of writing, never by inventing content in another language.
    """

    hits = _retrieve(question, category=category)

    if not hits:
        return _unverified_answer(
            "No relevant knowledge base entry",
            language=language
        )

    # The model is told the language by name, not by ISO code.
    target_language = LANGUAGE_PROMPT_NAMES.get(
        normalize(language),
        "English"
    )

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
- Write "answer" in {target_language}. Translate the verified facts
  into that language; do not add anything that is not stated above.

Return ONLY this JSON object:

{{
    "sufficient": true or false,
    "answer": "the answer, or empty string if not sufficient",
    "sources": ["ids of the snippets you used"]
}}
"""

    try:
        data = _extract_json(ask_model(prompt))

    except ModelUnavailable as error:
        print("MODEL UNAVAILABLE:", error)
        return _unverified_answer("Model unavailable", language)

    except (ValueError, json.JSONDecodeError) as error:
        print("GROUNDED ANSWER PARSE ERROR:", error)
        return _unverified_answer("Unreadable model response", language)

    if not data.get("sufficient") or not (data.get("answer") or "").strip():
        return _unverified_answer("Knowledge base did not cover the question", language)

    # Only ids that were actually retrieved may be cited; this stops a
    # model from inventing a source to make an answer look verified.
    retrieved_ids = {hit["id"] for hit in hits}

    cited = [
        source
        for source in data.get("sources", [])
        if source in retrieved_ids
    ]

    if not cited:
        return _unverified_answer("Answer cited no verified source", language)

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

def _fallback_understanding(key, language="en"):
    """
    Safe result used when the model cannot be reached or parsed.
    """

    language = normalize(language)

    return {
        "language": language,
        "intent": "unknown",
        "category": "unknown",
        "action": "unknown",
        "confidence": "low",
        "message": translate(key, language),
        "status": "needs_clarification",
        "missing": [],
        "clarification_question": "",
        "fields": {},
        "sources": [],
        "grounded": False
    }


def understand_request(user_request, history=None, language=None):
    """
    Classify a message and track the fields its service request needs.

    Returns the structured understanding used by the /chat route. For
    questions (category "information") the reply is generated by the
    grounded answering path instead of free text.
    """

    history = history or []

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
    # regardless of the language the user wrote in.
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

Distinguishing requests from questions matters, and it matters in
every language. A message that ASKS about rules, fees, timelines,
eligibility or procedure is "information", never a service request,
no matter what it is about or what language it is written in:

- "I need a bonafide certificate for a bank loan"  -> certificate
- "How long does a bonafide certificate take?"     -> information
- "The AC in room 204 is broken"                   -> maintenance
- "How fast are AC repairs handled?"               -> information
- "¿Hay que pagar por el certificado de traslado?" -> information
- "Necesito un certificado de traslado"            -> certificate
- "बोनाफाइड सर्टिफिकेट में कितने दिन लगते हैं?"          -> information
- "मुझे बोनाफाइड सर्टिफिकेट चाहिए"                     -> certificate
- "Combien de temps faut-il pour un certificat ?"  -> information
- "எனக்கு ஒரு சான்றிதழ் வேண்டும்"                    -> certificate

A question mark, or a word meaning how long / how much / do I need /
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

Extract every required field the user has already given, anywhere in
the conversation, into "fields" using those exact field names. Do not
leave a field out because it was phrased casually. Worked examples:

"I need a bonafide certificate for a bank loan"
-> fields: {{"certificate_type": "Bonafide Certificate",
            "purpose": "Bank loan"}}, missing: []

"The AC in room 204 of B block is broken"
-> fields: {{"location": "B block", "room": "204",
            "description": "AC is broken"}}, missing: []

"I want to book the robotics lab tomorrow"
-> fields: {{"laboratory_name": "Robotics Lab"}},
   missing: ["booking_date", "booking_time", "purpose"]

Only list a field in "missing" if the user genuinely has not given it.

Two fields must be reported using their official English name, even
when the user writes in another language, because institutional policy
is matched against these exact names:

- certificate_type must be one of: {certificate_types}
- laboratory_name must be one of these when the user means one of
  them: {laboratory_names}

Every other field keeps the user's own wording and language.

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

Detect the language the user wrote in and return its ISO 639-1 code
in "language" (for example en, hi, ta, bn, es, fr). Romanised text
still counts as its own language: "mujhe certificate chahiye" is hi.
Write "message" in that same language.

Return exactly this structure:

{{
    "language": "ISO 639-1 code of the user's language",
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
        data = _extract_json(ask_model(prompt))

    except ModelUnavailable as error:
        print("MODEL UNAVAILABLE:", error)
        return _fallback_understanding("chat.offline", language)

    except (ValueError, json.JSONDecodeError) as error:
        print("UNDERSTANDING PARSE ERROR:", error)
        return _fallback_understanding("chat.unclear", language)

    return _normalize(data, user_request, transcript, language)


def _normalize(data, user_request, transcript="", language=None):
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

    # An explicit choice in the interface always wins over detection.
    effective_language = normalize(
        language or data.get("language")
    )

    result = {
        "language": effective_language,
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

        grounded = answer_question(
            user_request,
            language=effective_language
        )

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
    # something they may already have told us.
    if outstanding():
        fields.update(
            _extract_fields(category, transcript, outstanding())
        )

    result["fields"] = fields

    actually_missing = outstanding()

    result["missing"] = actually_missing

    if actually_missing:

        result["status"] = "needs_clarification"

        # Always derived from the recomputed list: the model's own
        # question routinely disagrees with what is actually missing.
        # Labels are translated; the field keys stay canonical.
        result["clarification_question"] = "\n".join(
            f"{field_label(field, effective_language)}:"
            for field in actually_missing
        )

    else:
        result["status"] = "complete"
        result["clarification_question"] = ""

    return result
