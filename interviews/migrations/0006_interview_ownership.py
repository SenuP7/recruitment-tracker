"""Splits interview ownership from assignment.

`interviewer` is *renamed* rather than dropped and recreated: the column
holds real assignments, and a drop/add pair would silently lose them.
"""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("interviews", "0005_interview_interviewer"),
    ]

    operations = [
        migrations.RenameField(
            model_name="interview",
            old_name="interviewer",
            new_name="assigned_interviewer",
        ),
        migrations.AddField(
            model_name="interview",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="interviews_created",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="interview",
            name="location",
            field=models.CharField(
                blank=True,
                help_text="Where to go, or the room. Shown to the candidate.",
                max_length=200,
            ),
        ),
        migrations.AddField(
            model_name="interview",
            name="meeting_link",
            field=models.URLField(
                blank=True, help_text="Video call link. Shown to the candidate."
            ),
        ),
    ]
