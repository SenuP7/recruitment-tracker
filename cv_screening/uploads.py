"""Shared CV upload rules.

Staff uploads (cv_screening.views) and candidate uploads (portal.views) must
accept exactly the same files, so the limits live here rather than being
written out twice.
"""

MAX_CV_BYTES = 5 * 1024 * 1024
ALLOWED_CV_EXTENSIONS = (".pdf", ".docx")

# What the file actually starts with, not what it's called. A .pdf that is
# really something else gets past an extension check, and is then handed to a
# parser and stored under a name the browser will trust.
FILE_SIGNATURES = {
    ".pdf": (b"%PDF-",),
    ".docx": (b"PK\x03\x04", b"PK\x05\x06"),  # a zip container: entry, or empty
}

TOO_LARGE_MESSAGE = "CV file is too large. The maximum allowed size is 5 MB."
WRONG_TYPE_MESSAGE = "Unsupported file type. Please upload a PDF or DOCX file."
MISSING_MESSAGE = "Please select a CV file."
CONTENT_MISMATCH_MESSAGE = (
    "That file doesn't look like a real PDF or Word document. Please export it again and retry."
)


def validate_cv_file(uploaded_file):
    """Returns an error message, or None when the file is acceptable."""
    if not uploaded_file:
        return MISSING_MESSAGE
    if uploaded_file.size > MAX_CV_BYTES:
        return TOO_LARGE_MESSAGE
    name = uploaded_file.name.lower()
    extension = next((ext for ext in ALLOWED_CV_EXTENSIONS if name.endswith(ext)), None)
    if extension is None:
        return WRONG_TYPE_MESSAGE
    if not _looks_like(uploaded_file, FILE_SIGNATURES[extension]):
        return CONTENT_MISMATCH_MESSAGE
    return None


def _looks_like(uploaded_file, signatures):
    try:
        uploaded_file.seek(0)
        head = uploaded_file.read(8)
    except Exception:
        return False
    finally:
        try:
            uploaded_file.seek(0)
        except Exception:
            pass
    return any(head.startswith(signature) for signature in signatures)


UNREADABLE_MESSAGE = (
    "We stored your file, but we couldn't read any text from it, so it won't be "
    "scored automatically. A scanned or image-only document does this. If you can, "
    "upload a text-based PDF or Word file."
)


def score_cv_safely(cv, role_profile):
    """Scores a CV without letting a malformed file take the request down.

    PyPDF2 raises on truncated, encrypted or image-only PDFs, and python-docx
    raises on a zip that isn't really a document. Neither is a server error:
    the file is stored either way and a recruiter can still open it.

    Returns (result, error_message).
    """
    import logging

    from .matching import score_cv_against_role

    logger = logging.getLogger(__name__)

    if role_profile is None:
        return None, None
    try:
        return score_cv_against_role(cv, role_profile), None
    except Exception as error:
        logger.warning("Could not score CV %s: %s: %s", cv.pk, type(error).__name__, error)
        return None, UNREADABLE_MESSAGE
