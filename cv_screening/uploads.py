"""Shared CV upload rules.

Staff uploads (cv_screening.views) and candidate uploads (portal.views) must
accept exactly the same files, so the limits live here rather than being
written out twice.
"""

MAX_CV_BYTES = 5 * 1024 * 1024
ALLOWED_CV_EXTENSIONS = (".pdf", ".docx")

TOO_LARGE_MESSAGE = "CV file is too large. The maximum allowed size is 5 MB."
WRONG_TYPE_MESSAGE = "Unsupported file type. Please upload a PDF or DOCX file."
MISSING_MESSAGE = "Please select a CV file."


def validate_cv_file(uploaded_file):
    """Returns an error message, or None when the file is acceptable."""
    if not uploaded_file:
        return MISSING_MESSAGE
    if uploaded_file.size > MAX_CV_BYTES:
        return TOO_LARGE_MESSAGE
    if not uploaded_file.name.lower().endswith(ALLOWED_CV_EXTENSIONS):
        return WRONG_TYPE_MESSAGE
    return None
