from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ("edtech", "0003_paymenttransaction_paymentwebhookevent"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="booking",
            name="unique_teacher_booking_slot",
        ),
        migrations.AddConstraint(
            model_name="booking",
            constraint=models.UniqueConstraint(
                fields=("teacher", "starts_at"),
                condition=Q(("status__in", ["pending", "confirmed"])),
                name="unique_active_teacher_booking_slot",
            ),
        ),
    ]
