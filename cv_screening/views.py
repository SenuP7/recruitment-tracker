from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from .matching import extract_text, score_cv_against_role
from .models import CandidateCV, RoleKeywordProfile


@login_required
def upload_cv(request, role_profile_id):

    role_profile = get_object_or_404(
        RoleKeywordProfile,
        id=role_profile_id
    )

    if request.method == "POST":

        candidate = request.POST.get("candidate")
        uploaded_file = request.FILES.get("cv_file")

        cv = CandidateCV.objects.create(
            candidate_id=candidate,
            file=uploaded_file,
        )

        extract_text(cv)

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
        }
    )