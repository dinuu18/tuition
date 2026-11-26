from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("edtech", "0004_active_teacher_booking_slot"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="LessonProgress",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("completed_at", models.DateTimeField(auto_now_add=True)),
                ("lesson", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="student_progress", to="edtech.lesson")),
                ("student", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lesson_progress", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["completed_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="lessonprogress",
            constraint=models.UniqueConstraint(fields=("student", "lesson"), name="unique_student_lesson_progress"),
        ),
    ]
