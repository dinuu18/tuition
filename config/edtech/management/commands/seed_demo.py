from datetime import timedelta
from decimal import Decimal
import random

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from edtech.models import (
    Booking, Course, EducationBoard, Grade, Review, Subject,
    StudentProfile, TeacherProfile, UserProfile, Wallet,
)


class Command(BaseCommand):
    help = "Create idempotent fictional EdTech demonstration data."

    def handle(self, *args, **options):
        subjects_data = [
            ("School Education", ["Mathematics", "English", "Hindi", "Marathi", "Science", "Physics",
                                  "Chemistry", "Biology", "History", "Geography", "Social Science",
                                  "Environmental Studies"]),
            ("Commerce", ["Accountancy", "Economics", "Business Studies", "Statistics"]),
            ("Technology", ["Computer Science", "Information Technology", "Python", "Java",
                            "C Programming", "C++", "Web Development", "Django", "Data Structures",
                            "Artificial Intelligence"]),
            ("Competitive Exams", ["JEE", "NEET", "MHT-CET", "CUET", "Olympiad preparation"]),
        ]
        subjects = []
        for category, names in subjects_data:
            for name in names:
                subject, _ = Subject.objects.get_or_create(name=name, defaults={
                    "category": {"School Education": "School", "Commerce": "Commerce",
                                 "Technology": "Technology", "Competitive Exams": "Competitive"}[category],
                    "description": f"Expert learning resources and tutors for {name}.",
                    "icon": "book-open",
                })
                subjects.append(subject)

        for number in range(1, 13):
            Grade.objects.get_or_create(name=f"Class {number}", defaults={"order": number})
        Grade.objects.get_or_create(name="College", defaults={"order": 13})
        for board in ("CBSE", "ICSE", "State Board", "IB"):
            EducationBoard.objects.get_or_create(name=board)

        for index in range(1, 21):
            username = f"fiction_teacher_{index}"
            user, created = User.objects.get_or_create(username=username, defaults={
                "first_name": f"DemoTeacher", "last_name": str(index),
                "email": f"{username}@example.com",
            })
            if created:
                user.set_password("Demo12345!")
                user.save()
            profile, _ = UserProfile.objects.get_or_create(user=user, defaults={"role": "teacher"})
            teacher, _ = TeacherProfile.objects.get_or_create(user=user, defaults={
                "headline": "Fictional expert teacher for demonstrations",
                "biography": "Experienced fictional educator created only for platform demonstration.",
                "qualifications": "M.Sc. / B.Ed.",
                "experience_years": 3 + (index % 12),
                "hourly_fee": Decimal(350 + (index % 8) * 50),
                "verified": index <= 14,
                "available": True,
                "free_demo": True,
                "languages": "English, Hindi",
            })
            teacher.subjects.add(subjects[(index - 1) % len(subjects)])
            Wallet.objects.get_or_create(teacher=teacher)
            if index <= 20:
                course, _ = Course.objects.get_or_create(
                    title=f"Demo {subjects[(index - 1) % len(subjects)].name} Mastery {index}",
                    defaults={
                        "description": "A fictional demonstration course.",
                        "subject": subjects[(index - 1) % len(subjects)],
                        "teacher": teacher,
                        "price": Decimal(1499),
                        "discount_price": Decimal(999),
                        "duration": "12 weeks",
                        "level": "Beginner",
                        "language": "English",
                    })

        for index in range(1, 31):
            username = f"fiction_student_{index}"
            user, created = User.objects.get_or_create(username=username, defaults={
                "first_name": "DemoStudent", "last_name": str(index),
                "email": f"{username}@example.com",
            })
            if created:
                user.set_password("Demo12345!")
                user.save()
            UserProfile.objects.get_or_create(user=user, defaults={"role": "student"})
            StudentProfile.objects.get_or_create(user=user)

        teachers = list(TeacherProfile.objects.all())
        students = list(User.objects.filter(username__startswith="fiction_student_"))
        for index, student in enumerate(students[:10]):
            teacher = teachers[index % len(teachers)]
            subject = teacher.subjects.first()
            if subject:
                Booking.objects.get_or_create(
                    student=student, teacher=teacher, starts_at=timezone.now() + timedelta(days=index + 1),
                    defaults={"subject": subject, "status": "confirmed", "is_demo": True, "fee": 0})

        for teacher in teachers[:10]:
            for student in students[:2]:
                Review.objects.get_or_create(
                    teacher=teacher, student=student,
                    defaults={"rating": random.randint(4, 5), "comment": "Fictional demonstration review."})

        self.stdout.write(self.style.SUCCESS(
            "Demo data is ready. Login demo users with password Demo12345!"
        ))
