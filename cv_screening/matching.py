"""
Implements Master Plan Card 2, build steps 2-4:
  - CV upload + text extraction (PDF/DOCX)
  - synonym-expanded keyword matching
  - match score + matched keywords stored against the candidate record

Deliberately NOT using NLP/embeddings here — see CV Screening Comparison
doc, Approach 3 (Keyword + Synonym Taxonomy) is the sprint's chosen MVP.
"""

import re

import docx
from PyPDF2 import PdfReader

from .models import CandidateCV, CVMatchResult, RoleKeywordProfile, Skill, Synonym


def extract_text(cv: CandidateCV) -> str:
    """Pulls raw text out of an uploaded PDF or DOCX CV."""
    name = cv.file.name.lower()
    file_obj = cv.file  # django-storages exposes this as a file-like object

    if name.endswith(".pdf"):
        reader = PdfReader(file_obj)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    elif name.endswith(".docx"):
        document = docx.Document(file_obj)
        text = "\n".join(p.text for p in document.paragraphs)
    else:
        raise ValueError(f"Unsupported CV file type: {cv.file.name}")

    cv.extracted_text = text
    cv.save(update_fields=["extracted_text"])
    return text


def _build_term_to_skill_map() -> dict[str, Skill]:
    """Expands every skill + its synonyms into a flat lookup table,
    e.g. {'js': <Skill: JavaScript>, 'javascript': <Skill: JavaScript>, ...}
    Lowercased, so matching is case-insensitive."""
    lookup = {}
    for skill in Skill.objects.all():
        lookup[skill.name.lower()] = skill
    for synonym in Synonym.objects.select_related("skill").all():
        lookup[synonym.term.lower()] = synonym.skill
    return lookup


def find_skills_in_text(text: str) -> set[Skill]:
    """Returns the set of canonical Skills found anywhere in the CV text,
    matching both the skill name itself and any of its synonyms."""
    text_lower = text.lower()
    lookup = _build_term_to_skill_map()
    found = set()

    for term, skill in lookup.items():
        # word-boundary match so "JS" doesn't match inside "JSON" etc.
        pattern = r"\b" + re.escape(term) + r"\b"
        if re.search(pattern, text_lower):
            found.add(skill)

    return found


def score_cv_against_role(cv: CandidateCV, role_profile: RoleKeywordProfile) -> CVMatchResult:
    """Runs the full pipeline for one CV against one role and stores the result.
    Score weighting: required skills matter more than nice-to-have, matching
    the 'weighted' idea from Approach 2 without abandoning the synonym taxonomy."""
    text = cv.extracted_text or extract_text(cv)
    found_skills = find_skills_in_text(text)

    required = set(role_profile.required_skills.all())
    nice_to_have = set(role_profile.nice_to_have_skills.all())

    matched_required = found_skills & required
    matched_nice = found_skills & nice_to_have
    missing_required = required - found_skills

    # Required skills worth 80% of the score, nice-to-have worth 20%.
    required_score = len(matched_required) / len(required) if required else 1.0
    nice_score = len(matched_nice) / len(nice_to_have) if nice_to_have else 1.0
    final_score = (0.8 * required_score) + (0.2 * nice_score)

    result, _ = CVMatchResult.objects.update_or_create(
        cv=cv,
        role_profile=role_profile,
        defaults={"score": final_score},
    )
    result.matched_required.set(matched_required)
    result.matched_nice_to_have.set(matched_nice)
    result.missing_required.set(missing_required)
    return result
