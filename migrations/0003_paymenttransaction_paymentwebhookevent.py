import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("edtech", "0002_teacherprofile_college_teacherprofile_cover_image_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PaymentTransaction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("request_key", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("provider_order_id", models.CharField(blank=True, max_length=80, null=True, unique=True)),
                ("provider_payment_id", models.CharField(blank=True, max_length=80, null=True, unique=True)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=10)),
                ("currency", models.CharField(default="INR", max_length=3)),
                ("status", models.CharField(choices=[("created", "Created"), ("paid", "Paid"), ("failed", "Failed")], default="created", max_length=10)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("paid_at", models.DateTimeField(blank=True, null=True)),
                ("course", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="payment_transactions", to="edtech.course")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="payment_transactions", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="PaymentWebhookEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_id", models.CharField(max_length=100, unique=True)),
                ("event_type", models.CharField(max_length=100)),
                ("received_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
    ]
