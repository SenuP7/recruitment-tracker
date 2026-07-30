from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .matching import extract_text, score_cv_against_role
from .models import CandidateCV, RoleKeywordProfile


@login_required
def upload_cv(request, role_profile_id):
    """Handles a CV upload for a specific role, then immediately runs
    extraction + matching so the recruiter sees a score without a
    separate step. RBAC note: swap this to check request.user's
    role/department once Card 6 (login gateway) is in place."""
    role_profile = get_object_or_404(RoleKeywordProfile, id=role_profile_id)

    if request.method == "POST":
        candidate_name = request.POST.get("candidate_name")
        uploaded_file = request.FILES.get("cv_file")

        cv = CandidateCV.objects.create(
            candidate_name=candidate_name,
            file=uploaded_file,
        )
        extract_text(cv)
        result = score_cv_against_role(cv, role_profile)

        return render(request, "cv_screening/match_result.html", {
            "cv": cv,
            "result": result,
        })

    return render(request, "cv_screening/upload_form.html", {
        "role_profile": role_profile,
    })
