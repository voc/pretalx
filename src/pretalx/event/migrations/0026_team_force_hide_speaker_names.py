# Generated by Django 3.2.4 on 2021-08-29 21:37

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("event", "0025_event_featured_sessions_text"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="force_hide_speaker_names",
            field=models.BooleanField(default=False),
        ),
    ]
