from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, render
from django.http import FileResponse

from accounts import audit
from accounts.decorators import RECRUITMENT_STAFF_GROUPS, group_required
from .uploads import score_cv_safely, validate_cv_file
from .models import CandidateCV, CVMatchResult

from django.shortcuts import redirect
from candidates.models import Application


@group_required(*RECRUITMENT_STAFF_GROUPS)
def upload_application_cv(request, application_id):

    application = get_object_or_404(
        Application,
        id=application_id
    )

    position = application.position

    role_profile = position.screening_profile

    if not role_profile:
        return render(
            request,
            "cv_screening/error.html",
            {
                "message": "No screening profile assigned to this position."
            }
        )


    if request.method == "POST":

        uploaded_file = request.FILES.get("cv_file")

        # Exactly the rules the candidate portal and the public application
        # form apply (cv_screening/uploads.py). A staff account is trusted to
        # do its job; it is not a reason to let an arbitrary file into
        # storage under a name a browser will act on.
        error = validate_cv_file(uploaded_file)

        if error:
            return render(
                request,
                "cv_screening/application_upload.html",
                {
                    "application": application,
                    "role_profile": role_profile,
                    "error": error,
                }
            )

        cv = CandidateCV.objects.create(
            candidate=application.candidate,
            file=uploaded_file,
        )


        result, unreadable = score_cv_safely(cv, role_profile)

        if unreadable:
            messages.warning(
                request,
                "The file was stored, but no text could be read from it, so there's no "
                "score. It may be a scan or an image-only PDF.",
            )

        # The score never decides the outcome on its own. It used to set
        # "CV Screening Passed"/"Failed" straight away, which emailed the
        # candidate a decision no person had looked at -- a solely automated
        # decision under UK GDPR Art. 22. A recruiter now confirms it via
        # confirm_screening_outcome() below.

        if application.status == "Applied":
            application.status = "CV Screening"
            application.save(update_fields=["status"])

        messages.success(request, "CV uploaded and scored. Confirm the screening outcome when you've reviewed it.")

        return render(
            request,
            "cv_screening/match_result.html",
            {
                "cv": cv,
                "result": result,
                "application": application,
            }
        )


    return render(
        request,
        "cv_screening/application_upload.html",
        {
            "application": application,
            "role_profile": role_profile,
        }
    )

@group_required(*RECRUITMENT_STAFF_GROUPS)
def screening_results(request):

    results = CVMatchResult.objects.select_related(
        "cv",
        "cv__candidate",
        "role_profile",
    ).prefetch_related(
        "matched_required",
        "matched_nice_to_have",
        "missing_required",
    ).order_by("-score")

    scores = [result.score for result in results]
    summary = {
        "total": len(scores),
        "average": round(sum(scores) / len(scores) * 100) if scores else None,
        "strong": sum(1 for score in scores if score >= 0.8),
        "needs_review": sum(1 for score in scores if score < 0.6),
    }

    return render(
        request,
        "cv_screening/screening_results.html",
        {
            "results": results,
            "summary": summary,
        }
    )


@group_required(*RECRUITMENT_STAFF_GROUPS)
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

@group_required(*RECRUITMENT_STAFF_GROUPS)
def view_cv(request, cv_id):
    cv = get_object_or_404(CandidateCV, id=cv_id)

    # Any member of staff may open any CV -- that is deliberate, because
    # recruiters and reviewers work across departments. Accountability comes
    # from the record instead: a CV is the most sensitive thing here, and
    # this was the one way to read one that left no trace.
    audit.record(
        audit.CV_DOWNLOADED,
        actor=request.user,
        request=request,
        target=cv.candidate,
    )

    response = FileResponse(
        cv.file.open("rb"),
        as_attachment=False,
        filename=cv.file.name.split("/")[-1],
    )

    return response

@group_required(*RECRUITMENT_STAFF_GROUPS)
def delete_cv_result(request, result_id):

    result = get_object_or_404(
        CVMatchResult,
        id=result_id
    )

    cv = result.cv

    # Delete uploaded file
    if cv.file:
        cv.file.delete()

    # Delete CV
    cv.delete()

    messages.success(request, "CV screening result deleted successfully.")

    return redirect(
        "cv_screening:screening-results"
    )

@group_required(*RECRUITMENT_STAFF_GROUPS)
def confirm_screening_outcome(request, application_id):
    """A person decides whether a CV passes screening.

    The match score is advice; this view is where the outcome is actually
    set, and it's the only place that writes "CV Screening Passed"/"Failed".
    Requires change_application on top of staff group membership, so
    interviewers who may only read applications can't decide screening.
    """
    if request.method != "POST":
        raise PermissionDenied("Screening outcomes are confirmed by submitting the form.")

    if not request.user.has_perm("candidates.change_application"):
        raise PermissionDenied("You do not have permission to change applications.")

    application = get_object_or_404(Application, id=application_id)
    outcome = request.POST.get("outcome")

    if application.status not in ("Applied", "CV Screening"):
        messages.error(request, "This application's screening outcome has already been decided.")
    elif outcome == "pass":
        application.status = "CV Screening Passed"
        application.save(update_fields=["status"])
        audit.record(audit.SCREENING_DECIDED, request=request, target=application, outcome="passed")
        messages.success(request, "Screening marked as passed.")
    elif outcome == "fail":
        application.status = "CV Screening Failed"
        application.save(update_fields=["status"])
        audit.record(audit.SCREENING_DECIDED, request=request, target=application, outcome="failed")
        messages.success(request, "Screening marked as not passed.")
    else:
        messages.error(request, "Choose whether the CV passed screening.")

    return redirect("application-detail", pk=application.pk)
