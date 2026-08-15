
"""
RAG package.

Retrieval-Augmented Generation is used to ensure
that the AI retrieves verified institutional
information before answering policy-related questions.
"""

SUPPORTED_DOCUMENT_TYPES = [
    "pdf",
    "txt",
    "docx"
]


def is_supported_document(filename):
    """
    Check whether a document type is supported.
    """

    if "." not in filename:
        return False

    extension = filename.rsplit(".", 1)[1].lower()

    return extension in SUPPORTED_DOCUMENT_TYPES
