from django.contrib import admin
from .models import Candidate, CandidateCV, Application

admin.site.register(Candidate)
admin.site.register(CandidateCV)
admin.site.register(Application)