from django.contrib import admin

from .models import (
    Skill,
    Synonym,
    RoleKeywordProfile,
    CandidateCV,
    CVMatchResult,
)


@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(Synonym)
class SynonymAdmin(admin.ModelAdmin):
    list_display = ("term", "skill")
    search_fields = ("term", "skill__name")
    list_filter = ("skill",)


@admin.register(RoleKeywordProfile)
class RoleKeywordProfileAdmin(admin.ModelAdmin):
    list_display = ("role_name",)
    search_fields = ("role_name",)

    filter_horizontal = (
        "required_skills",
        "nice_to_have_skills",
    )


@admin.register(CandidateCV)
class CandidateCVAdmin(admin.ModelAdmin):
    list_display = (
        "candidate",
        "file",
        "uploaded_at",
    )
    list_filter = ("uploaded_at",)
    search_fields = (
        "candidate__first_name",
        "candidate__last_name",
    )


@admin.register(CVMatchResult)
class CVMatchResultAdmin(admin.ModelAdmin):
    list_display = (
        "cv",
        "role_profile",
        "score",
        "computed_at",
    )
    list_filter = (
        "role_profile",
        "computed_at",
    )
    ordering = ("-score",)