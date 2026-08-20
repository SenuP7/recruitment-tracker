from django.contrib.auth.models import Group, User
from django.test import Client, TestCase
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile

from io import BytesIO

from docx import Document

from .matching import (
    extract_text,
    find_skills_in_text,
    score_cv_against_role,
)

from candidates.models import Candidate

from .models import (
    CandidateCV,
    CVMatchResult,
    RoleKeywordProfile,
    Skill,
    Synonym,
)


class CVMatchingTests(TestCase):

    def setUp(self):
        # ---------------------------------------------------------
        # CREATE SKILLS
        # ---------------------------------------------------------

        self.candidate = Candidate.objects.create(
            first_name="Test",
            last_name="Candidate",
            email="test@example.com",
            phone="0712345678",
        )

        self.python = Skill.objects.create(
            name="Python"
        )

        self.javascript = Skill.objects.create(
            name="JavaScript"
        )

        self.django = Skill.objects.create(
            name="Django"
        )

        self.aws = Skill.objects.create(
            name="AWS"
        )

        # ---------------------------------------------------------
        # CREATE SYNONYMS
        # ---------------------------------------------------------

        Synonym.objects.create(
            skill=self.python,
            term="Py",
        )

        Synonym.objects.create(
            skill=self.javascript,
            term="JS",
        )

        Synonym.objects.create(
            skill=self.javascript,
            term="ECMAScript",
        )

        # ---------------------------------------------------------
        # CREATE ROLE PROFILE
        # ---------------------------------------------------------

        self.role = RoleKeywordProfile.objects.create(
            role_name="Software Engineer"
        )

        # Required skills
        self.role.required_skills.add(
            self.python,
            self.javascript,
            self.django,
        )

        # Nice-to-have skills
        self.role.nice_to_have_skills.add(
            self.aws,
        )

    # -------------------------------------------------------------
    # HELPER
    # -------------------------------------------------------------

    def create_cv(self, text):
        """
        Create a CV database record containing already-extracted text.

        No real file is uploaded because the tests do not need
        external storage.
        """
        return CandidateCV.objects.create(
            candidate=self.candidate,
            file="test_cv.pdf",
            extracted_text=text,
    )

    # -------------------------------------------------------------
    # SYNONYM MATCHING
    # -------------------------------------------------------------

    def test_synonym_matching(self):
        """
        JS should be recognised as JavaScript.
        Py should be recognised as Python.
        """

        text = (
            "Experienced with JS and Py development."
        )

        found = find_skills_in_text(text)

        self.assertIn(
            self.javascript,
            found,
        )

        self.assertIn(
            self.python,
            found,
        )

    # -------------------------------------------------------------
    # DIRECT SKILL MATCHING
    # -------------------------------------------------------------

    def test_direct_skill_matching(self):
        """
        Canonical skill names should be detected directly.
        """

        text = (
            "Experienced Python, Django and AWS developer."
        )

        found = find_skills_in_text(text)

        self.assertIn(
            self.python,
            found,
        )

        self.assertIn(
            self.django,
            found,
        )

        self.assertIn(
            self.aws,
            found,
        )

    # -------------------------------------------------------------
    # ZERO MATCH
    # -------------------------------------------------------------

    def test_zero_match(self):
        """
        A CV containing none of the required skills
        should receive a zero score.
        """

        cv = self.create_cv(
            "Experienced graphic designer with "
            "Photoshop and Illustrator skills."
        )

        result = score_cv_against_role(
            cv,
            self.role,
        )

        self.assertAlmostEqual(
            result.score,
            0.0,
            places=2,
        )

        self.assertEqual(
            result.matched_required.count(),
            0,
        )

        self.assertEqual(
            result.missing_required.count(),
            3,
        )

    # -------------------------------------------------------------
    # FULL REQUIRED MATCH
    # -------------------------------------------------------------

    def test_full_required_match(self):
        """
        A CV containing all required skills should receive
        the full required-skills portion of the score.

        Required skills are worth 80%, so the expected
        score is 0.8.
        """

        cv = self.create_cv(
            "Experienced Python, Django and JavaScript developer."
        )

        result = score_cv_against_role(
            cv,
            self.role,
        )

        self.assertAlmostEqual(
            result.score,
            0.8,
            places=2,
        )

        self.assertEqual(
            result.matched_required.count(),
            3,
        )

        self.assertEqual(
            result.missing_required.count(),
            0,
        )

    # -------------------------------------------------------------
    # REQUIRED + NICE-TO-HAVE MATCH
    # -------------------------------------------------------------

    def test_required_and_nice_to_have_match(self):
        """
        A CV containing all required skills and the
        nice-to-have AWS skill should receive 100%.

        The database stores 100% as 1.0.
        """

        cv = self.create_cv(
            "Experienced Python, Django, JavaScript "
            "and AWS developer."
        )

        result = score_cv_against_role(
            cv,
            self.role,
        )

        self.assertAlmostEqual(
            result.score,
            1.0,
            places=2,
        )

        self.assertEqual(
            result.matched_required.count(),
            3,
        )

        self.assertEqual(
            result.matched_nice_to_have.count(),
            1,
        )

    # -------------------------------------------------------------
    # PARTIAL REQUIRED MATCH
    # -------------------------------------------------------------

    def test_partial_required_match(self):
        """
        Two out of three required skills should produce
        approximately 53.33%.

        The database stores this as approximately 0.5333.
        """

        cv = self.create_cv(
            "Experienced Python and Django developer."
        )

        result = score_cv_against_role(
            cv,
            self.role,
        )

        self.assertAlmostEqual(
            result.score,
            0.5333,
            places=3,
        )

        self.assertEqual(
            result.matched_required.count(),
            2,
        )

        self.assertEqual(
            result.missing_required.count(),
            1,
        )

    # -------------------------------------------------------------
    # RESULT IS STORED
    # -------------------------------------------------------------

    def test_result_is_stored(self):
        """
        Matching should create a CVMatchResult record
        for the CV and role profile.
        """

        cv = self.create_cv(
            "Experienced Python and Django developer."
        )

        result = score_cv_against_role(
            cv,
            self.role,
        )

        self.assertTrue(
            CVMatchResult.objects.filter(
                cv=cv,
                role_profile=self.role,
            ).exists()
        )

        self.assertAlmostEqual(
            result.score,
            0.5333,
            places=3,
        )

    # -------------------------------------------------------------
    # DOCX TEXT EXTRACTION
    # -------------------------------------------------------------

    def test_docx_text_extraction(self):
        """
        Verify that the existing DOCX extraction logic
        correctly extracts text from a CV.
        """

        document = Document()

        document.add_paragraph(
            "Experienced Python and Django developer."
        )

        buffer = BytesIO()

        document.save(buffer)

        buffer.seek(0)

        uploaded_file = SimpleUploadedFile(
            "test_cv.docx",
            buffer.read(),
            content_type=(
                "application/vnd.openxmlformats-officedocument"
                ".wordprocessingml.document"
            ),
        )

        # Create the database record first.
        # Using an empty file value prevents the test from
        # attempting an actual S3 upload.
        cv = CandidateCV.objects.create(
        candidate=self.candidate,
        file="test_cv.docx",
        extracted_text="",
        )

        # Attach the temporary DOCX only in memory.
        cv.file = uploaded_file

        extracted = extract_text(cv)

        self.assertIn(
            "Experienced Python and Django developer.",
            extracted,
    )


class CVScreeningAccessControlTests(TestCase):
    """Regression tests: the Candidate group (and anyone in no recognized
    group) must not be able to reach any CV screening view. Every view in
    cv_screening/views.py used to be gated only by @login_required --
    meaning any authenticated user, including a Candidate-group login,
    could view every candidate's screening results, match details, and
    download any uploaded CV file directly. Fixed via
    accounts.decorators.group_required, the same "recruitment staff only"
    gate used by the dashboard."""

    def setUp(self):
        self.group_candidate, _ = Group.objects.get_or_create(name="Candidate")
        self.group_recruiter, _ = Group.objects.get_or_create(name="Recruiter")

        self.candidate_user = User.objects.create_user(
            "cv_access_candidate", password="pass12345"
        )
        self.candidate_user.groups.add(self.group_candidate)

        self.recruiter_user = User.objects.create_user(
            "cv_access_recruiter", password="pass12345"
        )
        self.recruiter_user.groups.add(self.group_recruiter)

        self.candidate = Candidate.objects.create(
            first_name="Access",
            last_name="Test",
            email="access.test@example.com",
            phone="0710000000",
        )
        self.skill = Skill.objects.create(name="Access Test Skill")
        self.role_profile = RoleKeywordProfile.objects.create(
            role_name="Access Test Role"
        )
        self.role_profile.required_skills.add(self.skill)

        self.cv = CandidateCV.objects.create(
            candidate=self.candidate, file="test_cv.docx"
        )
        self.result = CVMatchResult.objects.create(
            cv=self.cv, role_profile=self.role_profile, score=0.9
        )

    def test_candidate_group_cannot_view_screening_results_list(self):
        client = Client()
        client.login(username="cv_access_candidate", password="pass12345")
        response = client.get(reverse("cv_screening:screening-results"))
        self.assertEqual(response.status_code, 403)

    def test_candidate_group_cannot_view_screening_result_detail(self):
        client = Client()
        client.login(username="cv_access_candidate", password="pass12345")
        response = client.get(
            reverse("cv_screening:screening-result-detail", args=[self.result.id])
        )
        self.assertEqual(response.status_code, 403)

    def test_candidate_group_cannot_download_cv_file(self):
        client = Client()
        client.login(username="cv_access_candidate", password="pass12345")
        response = client.get(reverse("cv_screening:view_cv", args=[self.cv.id]))
        self.assertEqual(response.status_code, 403)

    def test_candidate_group_cannot_delete_screening_result(self):
        client = Client()
        client.login(username="cv_access_candidate", password="pass12345")
        response = client.get(
            reverse("cv_screening:delete-cv-result", args=[self.result.id])
        )
        self.assertEqual(response.status_code, 403)
        # And the result must still exist -- the denial must happen before
        # any deletion logic runs.
        self.assertTrue(CVMatchResult.objects.filter(id=self.result.id).exists())

    def test_candidate_group_cannot_reach_upload_form(self):
        client = Client()
        client.login(username="cv_access_candidate", password="pass12345")
        response = client.get(
            reverse("cv_screening:upload-cv", args=[self.role_profile.id])
        )
        self.assertEqual(response.status_code, 403)

    def test_anonymous_user_redirected_not_denied(self):
        """Anonymous should get the normal login redirect (via the
        decorator's built-in login_required), not a 403 -- 403 is only for
        an authenticated user in the wrong group."""
        client = Client()
        response = client.get(reverse("cv_screening:screening-results"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_recruiter_group_can_still_view_screening_results(self):
        client = Client()
        client.login(username="cv_access_recruiter", password="pass12345")
        response = client.get(reverse("cv_screening:screening-results"))
        self.assertEqual(response.status_code, 200)

    # Note: view_cv's 200-OK path isn't tested here -- it opens the file
    # from S3Boto3Storage (this project's DEFAULT_FILE_STORAGE), which
    # would make an S3 call under test. test_candidate_group_cannot_download_cv_file
    # above proves the denial happens before the view body (and any file
    # I/O) ever runs; test_recruiter_group_can_still_view_screening_results
    # proves the allow-path isn't blocked, on a view with no file I/O.

    def test_superuser_can_still_access_cv_screening(self):
        admin = User.objects.create_superuser("cv_access_admin", password="pass12345")
        client = Client()
        client.login(username="cv_access_admin", password="pass12345")
        response = client.get(reverse("cv_screening:screening-results"))
        self.assertEqual(response.status_code, 200)