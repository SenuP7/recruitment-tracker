from django.contrib import admin
from .models import Candidate, Application


admin.site.register(Candidate)
admin.site.register(Application)