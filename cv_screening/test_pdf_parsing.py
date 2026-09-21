"""PDF text extraction, pinned against the library it depends on.

`PyPDF2` was discontinued at 3.0.1 and carries a published denial-of-service:
a crafted PDF sends `extract_text()` into an infinite loop, pinning a CPU core
until the worker is killed. `score_cv_safely()` is no defence against it --
that catches exceptions, and a loop never raises one. On a single-instance
deployment a handful of such uploads is the whole site.

CVs arrive from people outside the organisation (the public careers form and
the candidate portal both reach this code), so the parser is the most exposed
dependency in the project. These tests fail if the discontinued library comes
back, and fail if extraction quietly stops working when it is upgraded.
"""

import io

from django.test import SimpleTestCase

from .matching import extract_text


def build_pdf(body_text):
    """A minimal but genuinely valid single-page PDF containing `body_text`.

    Built by hand rather than committed as a fixture so the test exercises a
    real parse -- a stored binary would drift out of sight and prove less.
    """
    content = b"BT /F1 14 Tf 72 720 Td (" + body_text.encode("ascii") + b") Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>stream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    buffer = io.BytesIO()
    buffer.write(b"%PDF-1.4\n")
    offsets = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(buffer.tell())
        buffer.write(str(number).encode() + b" 0 obj\n" + obj + b"\nendobj\n")

    xref_offset = buffer.tell()
    buffer.write(b"xref\n0 " + str(len(objects) + 1).encode() + b"\n")
    buffer.write(b"0000000000 65535 f \n")
    for offset in offsets:
        buffer.write(str(offset).zfill(10).encode() + b" 00000 n \n")
    buffer.write(
        b"trailer\n<< /Size "
        + str(len(objects) + 1).encode()
        + b" /Root 1 0 R >>\nstartxref\n"
        + str(xref_offset).encode()
        + b"\n%%EOF\n"
    )
    return buffer.getvalue()


class StubCV:
    """Stands in for a CandidateCV without touching the database.

    `extract_text` only needs `.file.name` and a readable file object, and
    saves the text back to the record. Nothing here needs a real row.
    """

    class _File:
        def __init__(self, name, data):
            self.name = name
            # One buffer, not one per call: a parser seeks around the file and
            # would lose its position against a fresh stream each time.
            self._buffer = io.BytesIO(data)

        def __getattr__(self, attr):
            return getattr(self._buffer, attr)

    def __init__(self, name, data):
        self.file = self._File(name, data)
        self.extracted_text = ""
        self.saved_fields = None

    def save(self, update_fields=None):
        self.saved_fields = update_fields


class PdfLibraryTests(SimpleTestCase):
    """The discontinued library must not come back."""

    def test_the_maintained_library_is_what_is_imported(self):
        from cv_screening import matching

        self.assertEqual(matching.PdfReader.__module__.split(".")[0], "pypdf")

    def test_pypdf2_is_not_installed_at_all(self):
        # Belt and braces: the import above could pass while something else
        # still pulls in the vulnerable package.
        with self.assertRaises(ImportError):
            __import__("PyPDF2")


class PdfExtractionTests(SimpleTestCase):
    """Swapping the parser must not quietly break scoring."""

    def test_it_pulls_the_text_out_of_a_real_pdf(self):
        cv = StubCV("cv.pdf", build_pdf("Kubernetes AWS Docker PostgreSQL"))

        text = extract_text(cv)

        for skill in ("Kubernetes", "AWS", "Docker", "PostgreSQL"):
            self.assertIn(skill, text)

    def test_it_writes_the_text_back_to_the_record(self):
        cv = StubCV("cv.pdf", build_pdf("Terraform"))

        extract_text(cv)

        self.assertIn("Terraform", cv.extracted_text)
        self.assertEqual(cv.saved_fields, ["extracted_text"])

    def test_a_file_that_is_not_a_pdf_raises_rather_than_returning_nothing(self):
        # score_cv_safely() turns this into "we couldn't read it"; silently
        # returning empty text would score every such CV at zero instead.
        cv = StubCV("cv.pdf", b"this is not a pdf at all")

        with self.assertRaises(Exception):
            extract_text(cv)

    def test_an_unsupported_extension_is_refused(self):
        cv = StubCV("cv.txt", b"plain text")

        with self.assertRaises(ValueError):
            extract_text(cv)
