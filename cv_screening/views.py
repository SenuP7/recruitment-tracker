from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.http import FileResponse

from .matching import extract_text, score_cv_against_role
from .models import CandidateCV, RoleKeywordProfile, CVMatchResult
from candidates.models import Candidate


@login_required
def upload_cv(request, role_profile_id):

    role_profile = get_object_or_404(
        RoleKeywordProfile,
        id=role_profile_id
    )

    candidates = Candidate.objects.all().order_by(
        "first_name",
        "last_name"
    )

    if request.method == "POST":

        candidate_id = request.POST.get("candidate")
        uploaded_file = request.FILES.get("cv_file")

        # Candidate validation
        if not candidate_id:
            return render(
                request,
                "cv_screening/upload_form.html",
                {
                    "role_profile": role_profile,
                    "candidates": candidates,
                    "error": "Please select a candidate.",
                }
            )

        # File validation
        if not uploaded_file:
            return render(
                request,
                "cv_screening/upload_form.html",
                {
                    "role_profile": role_profile,
                    "candidates": candidates,
                    "error": "Please select a CV file.",
                }
            )

        # Maximum 5 MB
        max_size = 5 * 1024 * 1024

        if uploaded_file.size > max_size:
            return render(
                request,
                "cv_screening/upload_form.html",
                {
                    "role_profile": role_profile,
                    "candidates": candidates,
                    "error": "CV file is too large. The maximum allowed size is 5 MB.",
                }
            )

        # File extension validation
        filename = uploaded_file.name.lower()

        if not filename.endswith((".pdf", ".docx")):
            return render(
                request,
                "cv_screening/upload_form.html",
                {
                    "role_profile": role_profile,
                    "candidates": candidates,
                    "error": "Invalid CV format. Please upload a PDF or DOCX file.",
                }
            )

        # Candidate lookup
        candidate = get_object_or_404(
            Candidate,
            id=candidate_id
        )

        # Role validation
        if not role_profile.required_skills.exists():
            return render(
                request,
                "cv_screening/upload_form.html",
                {
                    "role_profile": role_profile,
                    "candidates": candidates,
                    "error": "This role does not have any required skills configured.",
                }
            )

        # Create CV
        cv = CandidateCV.objects.create(
            candidate=candidate,
            file=uploaded_file,
        )

        # Extract CV text
        try:
            extract_text(cv)
        except Exception:
            cv.delete()

            return render(
                request,
                "cv_screening/upload_form.html",
                {
                    "role_profile": role_profile,
                    "candidates": candidates,
                    "error": (
                        "We could not read this CV. "
                        "Please make sure the PDF or DOCX file is valid."
                    ),
                }
            )

        # Make sure text was actually extracted
        if not cv.extracted_text.strip():
            cv.delete()

            return render(
                request,
                "cv_screening/upload_form.html",
                {
                    "role_profile": role_profile,
                    "candidates": candidates,
                    "error": (
                        "No readable text was found in this CV. "
                        "Please upload a text-based PDF or DOCX file."
                    ),
                }
            )

        # Score CV
        result = score_cv_against_role(
            cv,
            role_profile
        )

        return render(
            request,
            "cv_screening/match_result.html",
            {
                "cv": cv,
                "result": result,
            }
        )

    return render(
        request,
        "cv_screening/upload_form.html",
        {
            "role_profile": role_profile,
            "candidates": candidates,
        }
    )

@login_required
def screening_results(request):

    results = CVMatchResult.objects.select_related(
        "cv",
        "cv__candidate",
        "role_profile",
    ).prefetch_related(
        "matched_required",
        "matched_nice_to_have",
        "missing_required",
    ).order_by("-score", "-computed_at")

    return render(
        request,
        "cv_screening/screening_results.html",
        {
            "results": results,
        }
    )


@login_required
def screening_result_detail(request, result_id):

    result = get_object_or_404(
        CVMatchResult.objects.select_related(
            "cv",
            "cv__candidate",
            "role_profile",
        ).prefetch_related(
            "matched_required",
            "matched_nice_to_have",
            "missing_required",
        ),
        id=result_id,
    )

    return render(
        request,
        "cv_screening/match_result.html",
        {
            "cv": result.cv,
            "result": result,
        }
    )

@login_required
def view_cv(request, cv_id):
    cv = get_object_or_404(CandidateCV, id=cv_id)

    response = FileResponse(
        cv.file.open("rb"),
        as_attachment=False,
        filename=cv.file.name.split("/")[-1],
    )

    return response