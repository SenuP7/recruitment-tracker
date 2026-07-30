from django.contrib import admin
from .models import Skill, Synonym, RoleKeywordProfile, CandidateCV, CVMatchResult

admin.site.register(Skill)
admin.site.register(Synonym)
admin.site.register(RoleKeywordProfile)
admin.site.register(CandidateCV)
admin.site.register(CVMatchResult)