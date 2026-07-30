from django.db import models


class Skill(models.Model):
    """A canonical skill, e.g. 'JavaScript'. This is the taxonomy's anchor term —
    every synonym points back to one of these, so matching always resolves
    to a single canonical skill regardless of the wording used in a CV."""
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class Synonym(models.Model):
    """Alternate wording for a Skill, e.g. 'JS' or 'ECMAScript' -> JavaScript.
    This is the piece that solves the 'different words, same skill' problem
    flagged in the CV Screening Comparison doc, without needing NLP."""
    skill = models.ForeignKey(Skill, related_name="synonyms", on_delete=models.CASCADE)
    term = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return f"{self.term} -> {self.skill.name}"


class RoleKeywordProfile(models.Model):
    """The required/nice-to-have skill list for a given job role.
    Built with the BA, per the Master Plan's step 1 for this card."""
    role_name = models.CharField(max_length=150)
    required_skills = models.ManyToManyField(Skill, related_name="required_for_roles")
    nice_to_have_skills = models.ManyToManyField(
        Skill, related_name="nice_to_have_for_roles", blank=True
    )

    def __str__(self):
        return self.role_name


class CandidateCV(models.Model):
    """One uploaded CV. File itself lives in S3 (see settings_additions.py);
    extracted_text is cached here so re-matching doesn't require re-parsing."""
    candidate_name = models.CharField(max_length=200)
    file = models.FileField(upload_to="cvs/")
    extracted_text = models.TextField(blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.candidate_name


class CVMatchResult(models.Model):
    """Stores the outcome of matching one CV against one role's keyword
    profile — this is the record the dashboard (Card 3) will read from,
    so it should be recomputed whenever the CV or the profile changes."""
    cv = models.ForeignKey(CandidateCV, related_name="match_results", on_delete=models.CASCADE)
    role_profile = models.ForeignKey(RoleKeywordProfile, on_delete=models.CASCADE)
    score = models.FloatField(default=0.0)  # 0.0 - 1.0
    matched_required = models.ManyToManyField(
        Skill, related_name="matched_required_in", blank=True
    )
    matched_nice_to_have = models.ManyToManyField(
        Skill, related_name="matched_nice_to_have_in", blank=True
    )
    missing_required = models.ManyToManyField(
        Skill, related_name="missing_required_in", blank=True
    )
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("cv", "role_profile")

    def __str__(self):
        return f"{self.cv.candidate_name} vs {self.role_profile.role_name}: {self.score:.0%}"
