
import hashlib
import hmac
import json
from decimal import Decimal
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.contrib.auth.models import User
from django.utils import timezone

from .models import (
    Booking, ChatConversation, ChatMessage, Course, Enrollment, FavoriteTeacher,
    Lesson, LessonProgress, Notification,
    PaymentTransaction, StudyMaterial,
    Subject, TeacherAchievement, TeacherAvailability, TeacherEnquiry,
    TeacherExperience, TeacherPortfolioItem, TeacherProfile, TeacherSkill,
    TeacherSubject, UserProfile, StudentProfile, Grade,
)


class EdTechSmokeTests(TestCase):
    def setUp(self):
        self.subject = Subject.objects.create(name="Mathematics", category="School", active=True)

    def test_home_page(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Learn Today")
        self.assertContains(response, '<body class="dark">')
        self.assertContains(response, "Switch to light theme")

    def test_student_registration_and_dashboard(self):
        response = self.client.post(reverse("register", args=["student"]), {
            "first_name": "Test", "last_name": "Student", "username": "student1",
            "email": "student@example.com", "password": "StrongPass123!",
            "confirm_password": "StrongPass123!",
        })
        self.assertRedirects(response, reverse("dashboard"))
        self.assertTrue(UserProfile.objects.filter(user__username="student1", role="student").exists())

    def test_subject_detail(self):
        response = self.client.get(reverse("subject_detail", args=[self.subject.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mathematics")

    def test_homepage_and_subject_list_show_all_active_subjects(self):
        subjects = [
            Subject.objects.create(name=f"Dynamic Subject {index}", category="School")
            for index in range(10)
        ]

        homepage_response = self.client.get(reverse("home"))
        list_response = self.client.get(reverse("subject_list"))

        self.assertContains(homepage_response, subjects[-1].name)
        self.assertContains(list_response, subjects[-1].name)
        self.assertContains(homepage_response, "Explore Learning")
        self.assertContains(homepage_response, "Popular Subjects")

    def test_teacher_can_add_and_remove_manual_subjects(self):
        user = User.objects.create_user("manual-subject-teacher", password="StrongPass123!")
        UserProfile.objects.create(user=user, role="teacher")
        teacher = TeacherProfile.objects.create(user=user)
        self.client.force_login(user)

        response = self.client.post(reverse("edit_profile"), {
            "action": "add_manual_subject",
            "subject_name": "   ",
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enter a subject name.")
        self.assertFalse(Subject.objects.filter(name__iexact="").exists())

        self.client.post(reverse("edit_profile"), {
            "action": "add_manual_subject",
            "subject_name": "mAtHeMaTiCs",
        })
        self.assertEqual(Subject.objects.filter(name__iexact="mathematics").count(), 1)
        self.assertIn(self.subject, teacher.subjects.all())

        self.client.post(reverse("edit_profile"), {
            "action": "add_manual_subject",
            "subject_name": "Biology",
        })
        subject = Subject.objects.get(name="Biology")
        self.assertIn(subject, teacher.subjects.all())
        self.assertContains(self.client.get(reverse("home")), "Biology")
        self.assertContains(self.client.get(reverse("edit_profile")), "Add Subject")

        duplicate_response = self.client.post(reverse("edit_profile"), {
            "action": "add_manual_subject",
            "subject_name": "bIoLoGy",
        }, follow=True)
        self.assertEqual(Subject.objects.filter(name__iexact="biology").count(), 1)
        self.assertContains(duplicate_response, "already in My Subjects")

        course = Course.objects.create(
            title="Biology foundations",
            description="An introductory biology course.",
            subject=subject,
            teacher=teacher,
            price=100,
        )
        detail_response = self.client.get(reverse("subject_detail", args=[subject.slug]))
        self.assertContains(detail_response, user.username)
        self.assertContains(detail_response, course.title)

        remove_response = self.client.post(reverse("edit_profile"), {
            "action": "remove_manual_subject",
            "subject_id": subject.pk,
        })
        self.assertRedirects(remove_response, reverse("edit_profile"))
        self.assertFalse(teacher.subjects.filter(pk=subject.pk).exists())
        self.assertTrue(Subject.objects.filter(pk=subject.pk).exists())
        self.assertTrue(Course.objects.filter(pk=course.pk).exists())

    def test_find_tutor_filter(self):
        user = User.objects.create_user("teacher1", password="StrongPass123!")
        UserProfile.objects.create(user=user, role="teacher")
        teacher = TeacherProfile.objects.create(user=user, hourly_fee=500)
        teacher.subjects.add(self.subject)
        response = self.client.get(reverse("find_tutor"), {"subject": self.subject.pk})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "teacher1")

    def test_teacher_registration_lands_on_teacher_dashboard(self):
        response = self.client.post(reverse("register", args=["teacher"]), {
            "first_name": "Tara", "last_name": "Teacher", "username": "tara-teaches",
            "email": "tara@example.com", "password": "StrongPass123!",
            "confirm_password": "StrongPass123!",
        }, follow=True)
        teacher = TeacherProfile.objects.get(user__username="tara-teaches")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Profile completion")
        self.assertContains(response, teacher.public_slug)
        self.assertRedirects(response, reverse("dashboard"))

    def test_unauthenticated_dashboard_redirects_to_login(self):
        response = self.client.get(reverse("dashboard"))

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('dashboard')}",
        )

    def test_teacher_login_creates_session_and_opens_teacher_dashboard(self):
        teacher_user = User.objects.create_user(
            "teacher-login", password="StrongPass123!", first_name="Terry",
        )
        UserProfile.objects.create(user=teacher_user, role="teacher")
        TeacherProfile.objects.create(user=teacher_user)

        login_response = self.client.post(reverse("login"), {
            "username": "teacher-login",
            "password": "StrongPass123!",
        })

        self.assertRedirects(login_response, reverse("dashboard"))
        self.assertEqual(
            int(self.client.session["_auth_user_id"]),
            teacher_user.pk,
        )
        dashboard_response = self.client.get(reverse("dashboard"))

        self.assertEqual(dashboard_response.status_code, 200)
        self.assertTemplateUsed(dashboard_response, "edtech/teacher_dashboard.html")
        self.assertContains(dashboard_response, "Teacher workspace")

    def test_teacher_can_add_and_remove_subject_profile_item(self):
        user = User.objects.create_user("teacher2", password="StrongPass123!")
        UserProfile.objects.create(user=user, role="teacher")
        TeacherProfile.objects.create(user=user)
        self.client.force_login(user)
        edit_response = self.client.get(reverse("edit_profile"))
        self.assertEqual(edit_response.status_code, 200)
        self.assertContains(edit_response, "Build your teacher profile")
        self.client.post(reverse("edit_profile"), {
            "action": "save_profile", "first_name": "Terry", "last_name": "Educator",
            "email": "teacher2@example.com", "phone": "555-0104",
            "headline": "Science and mathematics educator", "biography": "Learning comes first.",
            "qualifications": "M.Sc. and B.Ed.", "college": "Teaching University",
            "location": "North City", "experience_years": "8", "hourly_fee": "600.00",
        })
        user.refresh_from_db()
        self.assertEqual(user.first_name, "Terry")
        self.assertEqual(user.profile.phone, "555-0104")
        self.assertEqual(user.teacher_profile.college, "Teaching University")
        self.assertEqual(user.teacher_profile.experience_years, 8)
        response = self.client.post(reverse("edit_profile"), {
            "action": "add_subject", "subject": self.subject.pk,
            "education_level": "School", "classes": "Class 8-10",
            "teaching_mode": "Both", "experience_years": 4,
        })
        item = TeacherSubject.objects.get(teacher__user=user)
        self.assertRedirects(response, reverse("edit_profile"))
        self.assertIn(self.subject, user.teacher_profile.subjects.all())
        response = self.client.post(reverse("edit_profile"), {
            "action": "update_subject", "item_id": item.pk, "subject": self.subject.pk,
            "education_level": "School", "classes": "Class 6-10",
            "teaching_mode": "Online", "experience_years": 5,
        })
        item.refresh_from_db()
        self.assertEqual(item.classes, "Class 6-10")
        response = self.client.post(reverse("edit_profile"), {
            "action": "delete_subject", "item_id": item.pk, "subject_id": self.subject.pk,
        })
        self.assertRedirects(response, reverse("edit_profile"))
        self.assertFalse(TeacherSubject.objects.filter(pk=item.pk).exists())
        self.assertFalse(user.teacher_profile.subjects.filter(pk=self.subject.pk).exists())

    def test_public_teacher_profile_tracks_views_and_accepts_enquiry(self):
        user = User.objects.create_user("teacher3", password="StrongPass123!", first_name="Tess")
        UserProfile.objects.create(user=user, role="teacher")
        teacher = TeacherProfile.objects.create(user=user, headline="Science educator")
        profile_url = reverse("public_teacher_profile", args=[teacher.public_slug])
        response = self.client.get(profile_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(teacher.profile_views.count(), 1)
        response = self.client.post(profile_url, {
            "name": "A student", "email": "student@example.com", "message": "I need science lessons.",
        })
        self.assertRedirects(response, profile_url)
        self.assertTrue(TeacherEnquiry.objects.filter(teacher=teacher, email="student@example.com").exists())

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_teacher_receives_enquiry_message_in_dashboard_and_email(self):
        teacher_user = User.objects.create_user(
            "teacher-inbox", password="StrongPass123!", email="teacher@example.com",
        )
        UserProfile.objects.create(user=teacher_user, role="teacher")
        teacher = TeacherProfile.objects.create(user=teacher_user)
        profile_url = reverse("public_teacher_profile", args=[teacher.public_slug])
        response = self.client.post(profile_url, {
            "name": "Student One",
            "email": "student@example.com",
            "message": "Please help me prepare for my exam.",
        })
        self.assertRedirects(response, profile_url)
        self.assertTrue(Notification.objects.filter(
            user=teacher_user, message__contains="Please help me prepare for my exam."
        ).exists())
        self.assertEqual(len(mail.outbox), 1)

        self.client.force_login(teacher_user)
        dashboard = self.client.get(reverse("dashboard"))
        inbox = self.client.get(reverse("teacher_enquiries"))
        self.assertContains(dashboard, "Please help me prepare for my exam.")
        self.assertContains(inbox, "Student One")
        self.assertContains(inbox, "student@example.com")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_teacher_reply_is_notified_and_visible_to_its_student(self):
        teacher_user = User.objects.create_user(
            "reply-teacher", password="StrongPass123!", email="teacher@example.com",
            first_name="Terry",
        )
        UserProfile.objects.create(user=teacher_user, role="teacher")
        teacher = TeacherProfile.objects.create(user=teacher_user)
        student = User.objects.create_user(
            "reply-student", password="StrongPass123!", email="student@example.com",
        )
        UserProfile.objects.create(user=student, role="student")
        other_student = User.objects.create_user("other-student", password="StrongPass123!")
        enquiry = TeacherEnquiry.objects.create(
            teacher=teacher, sender=student, name="Student", email=student.email,
            message="Can you help me with algebra?",
        )
        TeacherEnquiry.objects.create(
            teacher=teacher, sender=other_student, name="Other Student",
            email="other@example.com", message="This enquiry is private.",
        )

        self.client.force_login(teacher_user)
        response = self.client.post(reverse("teacher_enquiries"), {
            "enquiry_id": enquiry.pk,
            "reply_message": "Yes, I can help you with algebra.",
        })

        self.assertRedirects(response, reverse("teacher_enquiries"))
        enquiry.refresh_from_db()
        self.assertEqual(enquiry.reply_message, "Yes, I can help you with algebra.")
        self.assertIsNotNone(enquiry.replied_at)
        self.assertTrue(Notification.objects.filter(
            user=student, title="A teacher replied to your enquiry",
        ).exists())
        self.assertEqual(len(mail.outbox), 1)

        self.client.force_login(student)
        dashboard = self.client.get(reverse("dashboard"))
        self.assertContains(dashboard, "Can you help me with algebra?")
        self.assertContains(dashboard, "Yes, I can help you with algebra.")
        self.assertNotContains(dashboard, "This enquiry is private.")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_teacher_cannot_reply_to_another_teachers_enquiry_or_overwrite_reply(self):
        owner_user = User.objects.create_user("enquiry-owner", password="StrongPass123!")
        UserProfile.objects.create(user=owner_user, role="teacher")
        owner = TeacherProfile.objects.create(user=owner_user)
        other_user = User.objects.create_user("other-enquiry-teacher", password="StrongPass123!")
        UserProfile.objects.create(user=other_user, role="teacher")
        TeacherProfile.objects.create(user=other_user)
        enquiry = TeacherEnquiry.objects.create(
            teacher=owner, name="Student", email="student@example.com", message="Please help.",
        )

        self.client.force_login(other_user)
        forbidden_response = self.client.post(reverse("teacher_enquiries"), {
            "enquiry_id": enquiry.pk, "reply_message": "Unauthorized reply.",
        })
        self.assertEqual(forbidden_response.status_code, 404)

        self.client.force_login(owner_user)
        self.client.post(reverse("teacher_enquiries"), {
            "enquiry_id": enquiry.pk, "reply_message": "First reply.",
        })
        self.client.post(reverse("teacher_enquiries"), {
            "enquiry_id": enquiry.pk, "reply_message": "Changed reply.",
        })
        enquiry.refresh_from_db()
        self.assertEqual(enquiry.reply_message, "First reply.")

    def test_enquiry_inbox_is_private_to_the_teacher(self):
        teacher_user = User.objects.create_user("private-teacher", password="StrongPass123!")
        UserProfile.objects.create(user=teacher_user, role="teacher")
        teacher = TeacherProfile.objects.create(user=teacher_user)
        student = User.objects.create_user("private-student", password="StrongPass123!")
        self.client.force_login(student)

        response = self.client.get(reverse("teacher_enquiries"))

        self.assertEqual(response.status_code, 404)
        self.assertFalse(teacher.enquiries.exists())

    def test_teacher_can_publish_external_study_material(self):
        teacher_user = User.objects.create_user("teacher-materials", password="StrongPass123!")
        UserProfile.objects.create(user=teacher_user, role="teacher")
        TeacherProfile.objects.create(user=teacher_user)
        self.client.force_login(teacher_user)
        response = self.client.post(reverse("teacher_materials"), {
            "action": "add_material",
            "title": "Algebra revision notes",
            "subject": self.subject.pk,
            "description": "A concise revision guide.",
            "external_url": "https://example.com/algebra",
        })
        self.assertRedirects(response, reverse("teacher_materials"))
        material = StudyMaterial.objects.get(uploaded_by=teacher_user)
        self.assertEqual(material.external_url, "https://example.com/algebra")
        library = self.client.get(reverse("material_list"))
        self.assertContains(library, "Open external resource")
        self.assertContains(library, "https://example.com/algebra")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_demo_booking_must_fit_teacher_availability_and_sends_notifications(self):
        teacher_user = User.objects.create_user(
            "teacher-booking", password="StrongPass123!", email="teacher@example.com",
        )
        UserProfile.objects.create(user=teacher_user, role="teacher")
        teacher = TeacherProfile.objects.create(user=teacher_user)
        teacher.subjects.add(self.subject)
        start = (timezone.now() + timedelta(days=3)).replace(second=0, microsecond=0)
        end = start + timedelta(hours=2)
        TeacherAvailability.objects.create(teacher=teacher, starts_at=start, ends_at=end)

        student = User.objects.create_user(
            "student-booking", password="StrongPass123!", email="student@example.com",
        )
        self.client.force_login(student)
        book_url = reverse("book_demo", args=[teacher.pk])
        unavailable = self.client.post(book_url, {
            "subject": self.subject.pk,
            "starts_at": timezone.localtime(end + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
        })
        self.assertEqual(unavailable.status_code, 200)
        self.assertFalse(teacher.bookings.exists())

        booked = self.client.post(book_url, {
            "subject": self.subject.pk,
            "starts_at": timezone.localtime(start + timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M"),
        })
        self.assertRedirects(booked, reverse("dashboard"))
        self.assertEqual(teacher.bookings.count(), 1)
        self.assertEqual(Notification.objects.filter(user=teacher_user).count(), 1)
        self.assertEqual(len(mail.outbox), 2)

    def test_cancelled_booking_slot_can_be_requested_again(self):
        teacher_user = User.objects.create_user("teacher-cancelled", password="StrongPass123!")
        UserProfile.objects.create(user=teacher_user, role="teacher")
        teacher = TeacherProfile.objects.create(user=teacher_user)
        teacher.subjects.add(self.subject)
        student = User.objects.create_user("student-cancelled", password="StrongPass123!")
        start = (timezone.now() + timedelta(days=4)).replace(second=0, microsecond=0)
        TeacherAvailability.objects.create(
            teacher=teacher, starts_at=start, ends_at=start + timedelta(hours=2),
        )
        Booking.objects.create(
            student=student, teacher=teacher, subject=self.subject,
            starts_at=start, status="cancelled", is_demo=True,
        )
        self.client.force_login(student)

        response = self.client.post(reverse("book_demo", args=[teacher.pk]), {
            "subject": self.subject.pk,
            "starts_at": timezone.localtime(start).strftime("%Y-%m-%dT%H:%M"),
        })

        self.assertRedirects(response, reverse("dashboard"))
        self.assertTrue(teacher.bookings.filter(starts_at=start, status="pending").exists())

    def test_pending_booking_blocks_overlapping_demo_request(self):
        teacher_user = User.objects.create_user("teacher-overlap", password="StrongPass123!")
        UserProfile.objects.create(user=teacher_user, role="teacher")
        teacher = TeacherProfile.objects.create(user=teacher_user)
        teacher.subjects.add(self.subject)
        student = User.objects.create_user("student-overlap", password="StrongPass123!")
        start = (timezone.now() + timedelta(days=5)).replace(second=0, microsecond=0)
        TeacherAvailability.objects.create(
            teacher=teacher, starts_at=start, ends_at=start + timedelta(hours=2),
        )
        Booking.objects.create(
            student=student, teacher=teacher, subject=self.subject,
            starts_at=start, status="pending", is_demo=True,
        )
        self.client.force_login(student)

        response = self.client.post(reverse("book_demo", args=[teacher.pk]), {
            "subject": self.subject.pk,
            "starts_at": timezone.localtime(start + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M"),
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "overlaps an existing booking")
        self.assertEqual(teacher.bookings.count(), 1)

    def test_teacher_can_manage_experience_achievements_skills_and_portfolio(self):
        user = User.objects.create_user("teacher4", password="StrongPass123!", first_name="Tina")
        UserProfile.objects.create(user=user, role="teacher")
        teacher = TeacherProfile.objects.create(user=user, experience_years=6)
        self.client.force_login(user)

        self.client.post(reverse("edit_profile"), {
            "action": "add_experience", "job_title": "Science Teacher",
            "organization": "North School", "employment_type": "Full-time",
            "start_date": "2021-06-01", "currently_working": "on",
            "responsibilities": "Plan and teach science lessons.",
        })
        self.client.post(reverse("edit_profile"), {
            "action": "add_achievement", "title": "Teaching Excellence Award",
            "certificate_name": "Excellence Certificate", "issuing_organization": "North School",
            "issue_date": "2024-05-01", "description": "Recognized for mentoring.",
        })
        self.client.post(reverse("edit_profile"), {
            "action": "add_skill", "skill_name": "Student mentoring",
        })
        self.client.post(reverse("edit_profile"), {
            "action": "add_portfolio", "title": "Demo lecture",
            "item_type": "Lecture", "description": "An introduction to science.",
            "url": "https://example.com/lecture",
        })

        self.assertTrue(TeacherExperience.objects.filter(teacher=teacher, currently_working=True).exists())
        self.assertTrue(TeacherAchievement.objects.filter(teacher=teacher, title="Teaching Excellence Award").exists())
        self.assertTrue(TeacherSkill.objects.filter(teacher=teacher, name="Student mentoring").exists())
        self.assertTrue(TeacherPortfolioItem.objects.filter(teacher=teacher, title="Demo lecture").exists())
        response = self.client.get(reverse("public_teacher_profile", args=[teacher.public_slug]))
        self.assertContains(response, "Teaching Excellence Award")
        self.assertContains(response, "Student mentoring")
        self.assertContains(response, "Demo lecture")


class DashboardAuthenticationTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            "dashboard-teacher", password="StrongPass123!", first_name="Terry",
        )
        self.teacher_profile = UserProfile.objects.create(
            user=self.teacher, role="teacher",
        )
        TeacherProfile.objects.create(user=self.teacher)
        self.student = User.objects.create_user(
            "dashboard-student", password="StrongPass123!", first_name="Sasha",
        )
        UserProfile.objects.create(user=self.student, role="student")
        StudentProfile.objects.create(user=self.student)

    def test_anonymous_dashboard_redirects_to_login(self):
        response = self.client.get(reverse("dashboard"))

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('dashboard')}",
            fetch_redirect_response=False,
        )

    def test_teacher_login_creates_session_and_renders_teacher_dashboard(self):
        response = self.client.post(reverse("login"), {
            "username": "dashboard-teacher",
            "password": "StrongPass123!",
        })

        self.assertRedirects(response, reverse("dashboard"))
        self.assertIn("_auth_user_id", self.client.session)

        dashboard = self.client.get(reverse("dashboard"))
        self.assertEqual(dashboard.status_code, 200)
        self.assertTemplateUsed(dashboard, "edtech/teacher_dashboard.html")
        self.assertContains(dashboard, "Teacher workspace")
        self.assertContains(dashboard, "Student chats")

    def test_teacher_profile_without_user_profile_still_uses_teacher_dashboard(self):
        legacy_teacher = User.objects.create_user(
            "legacy-dashboard-teacher", password="StrongPass123!",
        )
        TeacherProfile.objects.create(user=legacy_teacher)
        self.client.force_login(legacy_teacher)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "edtech/teacher_dashboard.html")

    def test_student_login_still_renders_student_dashboard(self):
        response = self.client.post(reverse("login"), {
            "username": "dashboard-student",
            "password": "StrongPass123!",
        })

        self.assertRedirects(response, reverse("dashboard"))
        dashboard = self.client.get(reverse("dashboard"))
        self.assertEqual(dashboard.status_code, 200)
        self.assertTemplateUsed(dashboard, "edtech/student_dashboard.html")
        self.assertContains(dashboard, "Chats with teachers")

    def test_invalid_login_does_not_create_authenticated_session(self):
        response = self.client.post(reverse("login"), {
            "username": "dashboard-teacher",
            "password": "incorrect",
        })

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(response, "Invalid username or password.")


class StudentFeatureTests(TestCase):
    def setUp(self):
        self.subject = Subject.objects.create(name="Student Mathematics", category="School")
        self.student = User.objects.create_user(
            "feature-student", password="StrongPass123!", email="feature@example.com",
            first_name="Sam",
        )
        self.user_profile = UserProfile.objects.create(user=self.student, role="student")
        self.student_profile = StudentProfile.objects.create(user=self.student)
        self.teacher_user = User.objects.create_user(
            "feature-teacher", password="StrongPass123!", first_name="Taylor",
        )
        UserProfile.objects.create(user=self.teacher_user, role="teacher")
        self.teacher = TeacherProfile.objects.create(user=self.teacher_user)
        self.teacher.subjects.add(self.subject)
        self.client.force_login(self.student)

    def test_student_settings_save_learning_preferences_and_guardian_details(self):
        grade = Grade.objects.create(name="Grade 8", order=8)

        response = self.client.post(reverse("edit_profile"), {
            "first_name": "Samantha",
            "last_name": "Learner",
            "email": "sam.new@example.com",
            "phone": "555-0177",
            "grade": grade.pk,
            "board": "",
            "preferred_subjects": [self.subject.pk],
            "guardian_name": "Jordan Learner",
            "guardian_phone": "555-0199",
            "learning_goals": "Build confidence in algebra.",
        })

        self.assertRedirects(response, reverse("edit_profile"))
        self.student.refresh_from_db()
        self.user_profile.refresh_from_db()
        self.student_profile.refresh_from_db()
        self.assertEqual(self.student.first_name, "Samantha")
        self.assertEqual(self.student.email, "sam.new@example.com")
        self.assertEqual(self.user_profile.grade, grade)
        self.assertQuerySetEqual(
            self.user_profile.preferred_subjects.all(), [self.subject],
        )
        self.assertEqual(self.student_profile.guardian_name, "Jordan Learner")
        self.assertEqual(self.student_profile.learning_goals, "Build confidence in algebra.")

    def test_favorite_toggle_requires_post_and_student_role(self):
        favorite_url = reverse("favorite_teacher", args=[self.teacher.pk])

        self.assertEqual(self.client.get(favorite_url).status_code, 405)
        self.client.post(favorite_url)
        self.assertTrue(FavoriteTeacher.objects.filter(
            student=self.student, teacher=self.teacher,
        ).exists())
        self.client.post(favorite_url)
        self.assertFalse(FavoriteTeacher.objects.filter(
            student=self.student, teacher=self.teacher,
        ).exists())

        self.client.force_login(self.teacher_user)
        self.assertEqual(self.client.post(favorite_url).status_code, 404)

    def test_student_teachers_lists_saved_and_connected_teachers(self):
        FavoriteTeacher.objects.create(student=self.student, teacher=self.teacher)

        response = self.client.get(reverse("student_teachers"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Taylor")
        self.assertContains(response, "Saved teachers")
        self.assertContains(response, "Chat")

    def test_student_and_teacher_can_chat_only_in_their_conversation(self):
        FavoriteTeacher.objects.create(student=self.student, teacher=self.teacher)

        start_response = self.client.post(reverse("start_chat", args=[self.teacher.pk]))
        conversation = ChatConversation.objects.get(student=self.student, teacher=self.teacher)
        self.assertRedirects(
            start_response,
            reverse("chat_conversation", args=[conversation.pk]),
        )

        student_message = self.client.post(
            reverse("chat_conversation", args=[conversation.pk]),
            {"body": "Hello, I need help with algebra."},
        )
        self.assertRedirects(student_message, reverse("chat_conversation", args=[conversation.pk]))
        self.assertTrue(ChatMessage.objects.filter(
            conversation=conversation, sender=self.student,
            body="Hello, I need help with algebra.",
        ).exists())
        self.assertTrue(Notification.objects.filter(
            user=self.teacher_user, title__contains="Sam",
        ).exists())

        self.client.force_login(self.teacher_user)
        teacher_inbox = self.client.get(reverse("chat_inbox"))
        self.assertContains(teacher_inbox, "Sam")
        teacher_message = self.client.post(
            reverse("chat_conversation", args=[conversation.pk]),
            {"body": "I can help with that."},
        )
        self.assertRedirects(teacher_message, reverse("chat_conversation", args=[conversation.pk]))
        self.assertTrue(ChatMessage.objects.filter(
            conversation=conversation, sender=self.teacher_user,
            body="I can help with that.",
        ).exists())

        self.client.force_login(self.student)
        self.assertContains(
            self.client.get(reverse("chat_conversation", args=[conversation.pk])),
            "I can help with that.",
        )

    def test_student_cannot_start_chat_without_a_teacher_connection(self):
        response = self.client.post(reverse("start_chat", args=[self.teacher.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertFalse(ChatConversation.objects.exists())

    def test_chat_conversation_is_private_to_its_student_and_teacher(self):
        FavoriteTeacher.objects.create(student=self.student, teacher=self.teacher)
        self.client.post(reverse("start_chat", args=[self.teacher.pk]))
        conversation = ChatConversation.objects.get(student=self.student, teacher=self.teacher)
        url = reverse("chat_conversation", args=[conversation.pk])
        other_student = User.objects.create_user("unrelated-chat-student", password="StrongPass123!")
        other_teacher_user = User.objects.create_user("unrelated-chat-teacher", password="StrongPass123!")
        UserProfile.objects.create(user=other_teacher_user, role="teacher")
        TeacherProfile.objects.create(user=other_teacher_user)

        self.client.force_login(other_student)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, {"body": "Private message"}).status_code, 404)

        self.client.force_login(other_teacher_user)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_student_can_cancel_only_their_own_future_booking(self):
        start = timezone.now() + timedelta(days=2)
        booking = Booking.objects.create(
            student=self.student, teacher=self.teacher, subject=self.subject,
            starts_at=start, status="pending", is_demo=True,
        )
        other_student = User.objects.create_user("other-student", password="StrongPass123!")
        other_booking = Booking.objects.create(
            student=other_student, teacher=self.teacher, subject=self.subject,
            starts_at=start + timedelta(days=1), status="confirmed", is_demo=True,
        )

        response = self.client.post(
            reverse("cancel_student_booking", args=[booking.pk]),
        )
        self.assertRedirects(response, reverse("student_bookings"))
        booking.refresh_from_db()
        self.assertEqual(booking.status, "cancelled")
        self.assertTrue(Notification.objects.filter(
            user=self.teacher_user, message__contains="cancelled the class",
        ).exists())

        self.assertEqual(self.client.post(
            reverse("cancel_student_booking", args=[other_booking.pk]),
        ).status_code, 404)
        other_booking.refresh_from_db()
        self.assertEqual(other_booking.status, "confirmed")

    def test_student_can_mark_only_their_own_notifications_read(self):
        own_notification = Notification.objects.create(
            user=self.student, title="Booking update", message="Your class is confirmed.",
        )
        private_notification = Notification.objects.create(
            user=self.teacher_user, title="Private", message="Teacher-only information.",
        )

        response = self.client.get(reverse("student_notifications"))
        self.assertContains(response, "Your class is confirmed.")
        self.assertNotContains(response, "Teacher-only information.")
        self.client.post(reverse("student_notifications"), {
            "action": "mark_read", "notification_id": private_notification.pk,
        })
        self.client.post(reverse("student_notifications"), {
            "action": "mark_read", "notification_id": own_notification.pk,
        })

        own_notification.refresh_from_db()
        private_notification.refresh_from_db()
        self.assertTrue(own_notification.read)
        self.assertFalse(private_notification.read)

    def test_course_progress_updates_only_for_enrolled_student(self):
        course = Course.objects.create(
            title="Progress Algebra", description="Learn algebra.", subject=self.subject,
            teacher=self.teacher, price=Decimal("100.00"),
        )
        first_lesson = Lesson.objects.create(course=course, title="Expressions", order=1)
        second_lesson = Lesson.objects.create(course=course, title="Equations", order=2)
        Enrollment.objects.create(student=self.student, course=course, paid=True)
        completion_url = reverse(
            "complete_lesson", args=[course.pk, first_lesson.pk],
        )

        response = self.client.post(completion_url)

        self.assertRedirects(response, reverse("course_detail", args=[course.pk]))
        enrollment = Enrollment.objects.get(student=self.student, course=course)
        self.assertEqual(enrollment.progress, 50)
        self.assertEqual(LessonProgress.objects.filter(
            student=self.student, lesson=first_lesson,
        ).count(), 1)

        self.client.post(completion_url)
        self.client.post(reverse(
            "complete_lesson", args=[course.pk, second_lesson.pk],
        ))
        enrollment.refresh_from_db()
        self.assertEqual(enrollment.progress, 100)
        self.assertEqual(LessonProgress.objects.filter(
            student=self.student, lesson__course=course,
        ).count(), 2)

        unauthorized = User.objects.create_user("not-enrolled", password="StrongPass123!")
        UserProfile.objects.create(user=unauthorized, role="student")
        self.client.force_login(unauthorized)
        self.assertEqual(self.client.post(completion_url).status_code, 404)

    def test_dashboard_study_hours_come_from_completed_bookings(self):
        Booking.objects.create(
            student=self.student, teacher=self.teacher, subject=self.subject,
            starts_at=timezone.now() - timedelta(days=1), status="completed",
            duration_minutes=90,
        )
        Booking.objects.create(
            student=self.student, teacher=self.teacher, subject=self.subject,
            starts_at=timezone.now() + timedelta(days=1), status="pending",
            duration_minutes=60,
        )

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "1.5h")
        self.assertContains(response, "Upcoming classes")
        self.assertNotContains(response, "<strong>0h</strong>", html=False)


class CoursePaymentTests(TestCase):
    def setUp(self):
        self.subject = Subject.objects.create(name="Payment Mathematics", category="School")
        self.teacher_user = User.objects.create_user("payment-teacher", password="StrongPass123!")
        UserProfile.objects.create(user=self.teacher_user, role="teacher")
        self.teacher = TeacherProfile.objects.create(user=self.teacher_user)
        self.course = Course.objects.create(
            title="Payment Algebra",
            description="An algebra course.",
            subject=self.subject,
            teacher=self.teacher,
            price=Decimal("1250.00"),
        )
        self.student = User.objects.create_user(
            "payment-student", password="StrongPass123!", email="student@example.com",
        )
        self.client.force_login(self.student)

    @override_settings(RAZORPAY_KEY_ID="rzp_test_id", RAZORPAY_KEY_SECRET="test-secret")
    @patch("config.edtech.views._razorpay_request")
    def test_checkout_creates_order_and_renders_secure_checkout(self, razorpay_request):
        razorpay_request.return_value = {"id": "order_test_123"}
        request_key = uuid4()

        response = self.client.post(
            reverse("enroll_course", args=[self.course.pk]),
            {"request_key": str(request_key)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "edtech/payment_checkout.html")
        self.assertContains(response, "checkout.razorpay.com/v1/checkout.js")
        payment = PaymentTransaction.objects.get(request_key=request_key)
        self.assertEqual(payment.user, self.student)
        self.assertEqual(payment.course, self.course)
        self.assertEqual(payment.amount, Decimal("1250.00"))
        self.assertEqual(payment.provider_order_id, "order_test_123")
        self.assertEqual(payment.status, "created")
        self.assertEqual(razorpay_request.call_args.args[:2], ("POST", "/orders"))
        self.assertEqual(razorpay_request.call_args.args[2]["amount"], 125000)

    def test_zero_discount_price_is_enrolled_without_payment(self):
        self.course.discount_price = Decimal("0.00")
        self.course.save(update_fields=["discount_price"])

        response = self.client.post(reverse("enroll_course", args=[self.course.pk]))

        self.assertRedirects(response, reverse("course_detail", args=[self.course.pk]))
        self.assertTrue(Enrollment.objects.get(student=self.student, course=self.course).paid)
        self.assertFalse(PaymentTransaction.objects.filter(course=self.course).exists())

    @override_settings(RAZORPAY_KEY_ID="rzp_test_id", RAZORPAY_KEY_SECRET="test-secret")
    @patch("config.edtech.views._razorpay_request")
    def test_retry_uses_the_transaction_amount_snapshot(self, razorpay_request):
        request_key = uuid4()
        PaymentTransaction.objects.create(
            user=self.student,
            course=self.course,
            request_key=request_key,
            amount=Decimal("1000.00"),
        )
        self.course.price = Decimal("1500.00")
        self.course.save(update_fields=["price"])
        razorpay_request.return_value = {"id": "order_snapshot_123"}

        response = self.client.post(
            reverse("enroll_course", args=[self.course.pk]),
            {"request_key": str(request_key)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(razorpay_request.call_args.args[2]["amount"], 100000)
        self.assertEqual(response.context["payment"].amount, Decimal("1000.00"))

    @override_settings(RAZORPAY_KEY_ID="rzp_test_id", RAZORPAY_KEY_SECRET="test-secret")
    @patch("config.edtech.views._razorpay_request")
    def test_verified_captured_payment_grants_course_access(self, razorpay_request):
        payment = PaymentTransaction.objects.create(
            user=self.student,
            course=self.course,
            request_key=uuid4(),
            provider_order_id="order_test_456",
            amount=Decimal("1250.00"),
        )
        payment_id = "pay_test_456"
        signature = hmac.new(
            b"test-secret",
            f"{payment.provider_order_id}|{payment_id}".encode(),
            hashlib.sha256,
        ).hexdigest()
        razorpay_request.return_value = {
            "order_id": payment.provider_order_id,
            "amount": 125000,
            "currency": "INR",
            "status": "captured",
        }
        payload = {
            "transaction_id": str(payment.pk),
            "razorpay_order_id": payment.provider_order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": signature,
        }

        response = self.client.post(
            reverse("verify_payment"),
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "paid")
        payment.refresh_from_db()
        self.assertEqual(payment.status, "paid")
        self.assertEqual(payment.provider_payment_id, payment_id)
        self.assertTrue(Enrollment.objects.get(student=self.student, course=self.course).paid)

    @override_settings(RAZORPAY_WEBHOOK_SECRET="webhook-secret")
    def test_signed_payment_webhook_is_idempotent(self):
        payment = PaymentTransaction.objects.create(
            user=self.student,
            course=self.course,
            request_key=uuid4(),
            provider_order_id="order_webhook_123",
            amount=Decimal("1250.00"),
        )
        event = {
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_webhook_123",
                        "order_id": payment.provider_order_id,
                        "amount": 125000,
                        "currency": "INR",
                        "status": "captured",
                    }
                }
            },
        }
        body = json.dumps(event).encode()
        signature = hmac.new(b"webhook-secret", body, hashlib.sha256).hexdigest()

        response = self.client.post(
            reverse("razorpay_webhook"),
            data=body,
            content_type="application/json",
            HTTP_X_RAZORPAY_SIGNATURE=signature,
        )
        duplicate = self.client.post(
            reverse("razorpay_webhook"),
            data=body,
            content_type="application/json",
            HTTP_X_RAZORPAY_SIGNATURE=signature,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "processed")
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(duplicate.json()["status"], "duplicate")
        payment.refresh_from_db()
        self.assertEqual(payment.status, "paid")
        self.assertTrue(Enrollment.objects.get(student=self.student, course=self.course).paid)

    @override_settings(RAZORPAY_KEY_ID="rzp_test_id", RAZORPAY_KEY_SECRET="test-secret")
    @patch("config.edtech.views._razorpay_request")
    def test_payment_signature_or_provider_capture_is_required(self, razorpay_request):
        payment = PaymentTransaction.objects.create(
            user=self.student,
            course=self.course,
            request_key=uuid4(),
            provider_order_id="order_invalid_123",
            amount=Decimal("1250.00"),
        )
        razorpay_request.return_value = {
            "order_id": payment.provider_order_id,
            "amount": 125000,
            "currency": "INR",
            "status": "authorized",
        }
        payload = {
            "transaction_id": str(payment.pk),
            "razorpay_order_id": payment.provider_order_id,
            "razorpay_payment_id": "pay_invalid_123",
            "razorpay_signature": "invalid",
        }

        response = self.client.post(
            reverse("verify_payment"),
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Enrollment.objects.filter(student=self.student, course=self.course).exists())
        payment.refresh_from_db()
        self.assertEqual(payment.status, "created")

        payload["razorpay_signature"] = hmac.new(
            b"test-secret",
            f"{payment.provider_order_id}|{payload['razorpay_payment_id']}".encode(),
            hashlib.sha256,
        ).hexdigest()
        response = self.client.post(
            reverse("verify_payment"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertFalse(Enrollment.objects.filter(student=self.student, course=self.course).exists())
