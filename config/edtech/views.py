import base64
import hashlib
import hmac
import json
import logging
import smtplib
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID, uuid4

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.mail import EmailMessage
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import Avg, Q, Sum
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .forms import (
    BookingRequestForm, StudentSettingsForm, StudyMaterialForm, TeacherAchievementForm,
    TeacherAvailabilityForm, TeacherExperienceForm, TeacherPortfolioForm,
    TeacherProfileForm, TeacherSubjectForm,
)
from .models import (
    Booking, ChatConversation, ChatMessage, Course, EducationBoard, Enrollment,
    FavoriteTeacher, Grade, Lesson, LessonProgress,
    Notification, StudyMaterial, Subject, TeacherAchievement, TeacherEnquiry,
    TeacherExperience, TeacherPortfolioItem, TeacherProfile, TeacherProfileView,
    TeacherSkill, TeacherSubject, StudentProfile, UserProfile, Wallet,
    PaymentTransaction, PaymentWebhookEvent,
)

logger = logging.getLogger(__name__)


class PaymentGatewayError(Exception):
    pass


def _notify_user(user, title, message, email_subject, email_body, reply_to=None):
    Notification.objects.create(user=user, title=title, message=message)
    if not user.email:
        logger.warning("Unable to email user %s: no email address is saved.", user.pk)
        return False
    try:
        email = EmailMessage(
            email_subject,
            email_body,
            to=[user.email],
            reply_to=[reply_to] if reply_to else None,
        )
        sent = email.send(fail_silently=False)
    except (OSError, smtplib.SMTPException):
        logger.exception("Email notification failed for user %s.", user.pk)
        return False
    if not sent:
        logger.error("Email backend did not send a notification to user %s.", user.pk)
    return bool(sent)


def home(request):
    return render(request, "edtech/home.html", {
        "subjects": Subject.objects.filter(active=True).order_by("name"),
        "teachers": TeacherProfile.objects.filter(verified=True).select_related("user")[:6],
        "courses": Course.objects.filter(active=True).select_related("subject", "teacher", "teacher__user")[:6],
        "stats": {
            "students": UserProfile.objects.filter(role="student").count(),
            "teachers": TeacherProfile.objects.count(),
            "courses": Course.objects.filter(active=True).count(),
            "classes": Booking.objects.filter(status="completed").count(),
        },
    })


def register(request, role):
    if role not in ("student", "teacher"):
        return redirect("home")
    if request.method == "POST":
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        username = request.POST.get("username", "").strip()
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")
        confirm = request.POST.get("confirm_password", "")
        if not all((first_name, username, email, password)):
            messages.error(request, "Please complete all required fields.")
        elif password != confirm:
            messages.error(request, "Passwords do not match.")
        elif User.objects.filter(username=username).exists():
            messages.error(request, "That username is already taken.")
        elif User.objects.filter(email=email).exists():
            messages.error(request, "That email is already registered.")
        else:
            user = User.objects.create_user(username=username, email=email, password=password,
                                             first_name=first_name, last_name=last_name)
            UserProfile.objects.create(user=user, role=role)
            if role == "teacher":
                profile = TeacherProfile.objects.create(user=user)
                Wallet.objects.create(teacher=profile)
            else:
                StudentProfile.objects.create(user=user)
            login(request, user)
            messages.success(request, "Account created successfully.")
            return redirect("dashboard")
    return render(request, "edtech/register.html", {"role": role})


def user_login(request):
    if request.method == "POST":
        user = authenticate(request, username=request.POST.get("username"),
                            password=request.POST.get("password"))
        if user:
            login(request, user)
            return redirect("dashboard")
        messages.error(request, "Invalid username or password.")
    return render(request, "edtech/login.html")


@login_required
def user_logout(request):
    logout(request)
    return redirect("home")


@login_required
def dashboard(request):
    profile = getattr(request.user, "profile", None)
    teacher = getattr(request.user, "teacher_profile", None)
    role = profile.role if profile else ("teacher" if teacher else "student")
    if role == "teacher":
        if not teacher:
            teacher = TeacherProfile.objects.create(user=request.user)
            Wallet.objects.create(teacher=teacher)
        context = {
            "role": "teacher", "teacher": teacher,
            "courses": teacher.courses.select_related("subject"),
            "bookings": teacher.bookings.select_related("student", "subject").order_by("-starts_at")[:10],
            "earnings": teacher.earnings.aggregate(total=Sum("net_amount"))["total"] or 0,
            "profile_completion": teacher_profile_completion(teacher),
            "profile_views": teacher.profile_views.count(),
            "enquiry_count": teacher.enquiries.count(),
            "enquiries": teacher.enquiries.select_related("sender")[:5],
            "chat_conversations": teacher.chat_conversations.select_related(
                "student", "teacher__user",
            )[:5],
            "student_connections": len(set(
                Enrollment.objects.filter(course__teacher=teacher).values_list("student_id", flat=True)
            ) | set(teacher.bookings.values_list("student_id", flat=True))),
            "notifications": request.user.notifications.order_by("-created_at")[:5],
            "teacher_materials": StudyMaterial.objects.filter(uploaded_by=request.user)
            .select_related("subject", "grade").order_by("-created_at")[:5],
        }
        return render(request, "edtech/teacher_dashboard.html", context)
    enrollments = Enrollment.objects.filter(
        student=request.user, paid=True,
    ).select_related("course", "course__subject", "course__teacher", "course__teacher__user")
    favorites = FavoriteTeacher.objects.filter(student=request.user).select_related("teacher", "teacher__user")
    profile = getattr(request.user, "profile", None)
    preferred_subjects = profile.preferred_subjects.all() if profile else Subject.objects.none()
    enrolled_subjects = Subject.objects.filter(
        courses__enrollments__student=request.user,
        courses__enrollments__paid=True,
    ).distinct()
    bookings = Booking.objects.filter(student=request.user).select_related(
        "teacher", "teacher__user", "subject",
    ).order_by("-starts_at")
    completed_minutes = Booking.objects.filter(
        student=request.user, status="completed",
    ).aggregate(total=Sum("duration_minutes"))["total"] or 0
    upcoming_bookings = Booking.objects.filter(
        student=request.user,
        status__in=("pending", "confirmed"),
        starts_at__gte=timezone.now(),
    ).select_related("teacher", "teacher__user", "subject").order_by("starts_at")[:5]
    saved_teacher_ids = set(favorites.values_list("teacher_id", flat=True))
    context = {
        "role": "student", "enrollments": enrollments, "favorites": favorites,
        "bookings": bookings[:10], "upcoming_bookings": upcoming_bookings,
        "booking_count": bookings.count(), "study_hours": round(completed_minutes / 60, 1),
        "enquiries": TeacherEnquiry.objects.filter(sender=request.user).select_related(
            "teacher", "teacher__user",
        ).order_by("-created_at")[:3],
        "chat_conversations": ChatConversation.objects.filter(
            student=request.user,
        ).select_related("teacher", "teacher__user")[:3],
        "unread_notifications": request.user.notifications.filter(read=False).count(),
        "notifications": request.user.notifications.order_by("-created_at")[:5],
        "materials": StudyMaterial.objects.filter(active=True).select_related(
            "subject", "grade",
        ).order_by("-created_at")[:6],
        "preferred_subjects": preferred_subjects, "enrolled_subjects": enrolled_subjects,
        "saved_teacher_ids": saved_teacher_ids,
    }
    return render(request, "edtech/student_dashboard.html", context)


def subject_list(request):
    subjects = Subject.objects.filter(active=True).prefetch_related("grades").order_by("category", "name")
    return render(request, "edtech/subject_list.html", {"subjects": subjects})


def subject_detail(request, slug):
    subject = get_object_or_404(Subject, slug=slug, active=True)
    return render(request, "edtech/subject_detail.html", {
        "subject": subject,
        "teachers": subject.teachers.filter(available=True).select_related("user"),
        "courses": subject.courses.filter(active=True).select_related("teacher", "teacher__user"),
        "materials": subject.materials.filter(active=True),
    })


def find_tutor(request):
    teachers = TeacherProfile.objects.select_related("user").prefetch_related("subjects", "grades", "boards")
    query = request.GET.get("q", "").strip()
    subject = request.GET.get("subject")
    grade = request.GET.get("grade")
    board = request.GET.get("board")
    language = request.GET.get("language")
    min_fee = request.GET.get("min_fee")
    max_fee = request.GET.get("max_fee")
    experience = request.GET.get("experience")
    rating = request.GET.get("rating")
    if query:
        teachers = teachers.filter(Q(user__first_name__icontains=query) | Q(user__last_name__icontains=query) |
                                   Q(user__username__icontains=query) | Q(qualifications__icontains=query))
    if subject:
        teachers = teachers.filter(subjects__id=subject)
    if grade:
        teachers = teachers.filter(grades__id=grade)
    if board:
        teachers = teachers.filter(boards__id=board)
    if language:
        teachers = teachers.filter(languages__icontains=language)
    if min_fee:
        teachers = teachers.filter(hourly_fee__gte=min_fee)
    if max_fee:
        teachers = teachers.filter(hourly_fee__lte=max_fee)
    if experience:
        teachers = teachers.filter(experience_years__gte=experience)
    if request.GET.get("verified"):
        teachers = teachers.filter(verified=True)
    if request.GET.get("available"):
        teachers = teachers.filter(available=True)
    if request.GET.get("online"):
        teachers = teachers.filter(online=True)
    if request.GET.get("offline"):
        teachers = teachers.filter(offline=True)
    if request.GET.get("demo"):
        teachers = teachers.filter(free_demo=True)
    if rating:
        teachers = teachers.annotate(avg_rating=Avg("reviews__rating")).filter(avg_rating__gte=rating)
    sort = request.GET.get("sort")
    if sort == "lowest":
        teachers = teachers.order_by("hourly_fee")
    elif sort == "highest":
        teachers = teachers.order_by("-hourly_fee")
    elif sort == "experienced":
        teachers = teachers.order_by("-experience_years")
    elif sort == "recent":
        teachers = teachers.order_by("-id")
    else:
        teachers = teachers.order_by("-verified", "-id")
    page = Paginator(teachers.distinct(), 9).get_page(request.GET.get("page"))
    query_params = request.GET.copy()
    query_params.pop("page", None)
    return render(request, "edtech/find_tutor.html", {
        "page": page, "subjects": Subject.objects.filter(active=True),
        "grades": Grade.objects.all(), "boards": EducationBoard.objects.all(),
        "query_string": query_params.urlencode(),
    })


def teacher_profile_completion(teacher):
    profile = getattr(teacher.user, "profile", None)
    profile_fields = [
        teacher.user.first_name, teacher.user.last_name, teacher.user.email,
        profile.phone if profile else "", teacher.headline, teacher.biography,
        teacher.qualifications, teacher.college, teacher.location,
        teacher.experience_years,
    ]
    sections = [
        bool(value) for value in profile_fields
    ] + [
        profile.profile_picture if profile else "",
        teacher.cover_image,
        teacher.teaching_subjects.exists(),
        teacher.professional_experiences.exists(),
        teacher.achievements.exists(),
        teacher.skills.exists(),
        teacher.portfolio_items.exists(),
    ]
    return round(sum(bool(value) for value in sections) * 100 / len(sections))


def _render_teacher_detail(request, teacher):
    is_favorite = request.user.is_authenticated and FavoriteTeacher.objects.filter(student=request.user, teacher=teacher).exists()
    return render(request, "edtech/teacher_detail.html", {
        "teacher": teacher, "is_favorite": is_favorite,
        "reviews": teacher.reviews.select_related("student").order_by("-created_at"),
    })


def teacher_detail(request, pk):
    teacher = get_object_or_404(TeacherProfile, pk=pk)
    return redirect("public_teacher_profile", slug=teacher.public_slug)


def public_teacher_profile(request, slug):
    teacher = get_object_or_404(
        TeacherProfile.objects.select_related("user", "user__profile").prefetch_related(
            "subjects", "grades", "boards", "teaching_subjects__subject",
            "professional_experiences", "achievements", "skills", "portfolio_items",
        ),
        public_slug=slug,
    )
    if request.method == "POST":
        if request.user.is_authenticated and request.user == teacher.user:
            messages.error(request, "You cannot send an enquiry to your own profile.")
        else:
            name = request.POST.get("name", "").strip()
            email = request.POST.get("email", "").strip()
            message = request.POST.get("message", "").strip()
            if not name or not email or not message:
                messages.error(request, "Please complete all enquiry fields.")
            else:
                try:
                    validate_email(email)
                except ValidationError:
                    messages.error(request, "Enter a valid email address.")
                else:
                    enquiry = TeacherEnquiry.objects.create(
                        teacher=teacher, sender=request.user if request.user.is_authenticated else None,
                        name=name, email=email, message=message,
                    )
                    email_sent = _notify_user(
                        teacher.user,
                        "New teaching enquiry",
                        f"{enquiry.name}: {enquiry.message}",
                        f"New teaching enquiry from {enquiry.name}",
                        f"You received a teaching enquiry on Tuition.com.\n\n"
                        f"From: {enquiry.name}\nEmail: {enquiry.email}\n\n{enquiry.message}",
                        reply_to=enquiry.email,
                    )
                    if not email_sent:
                        messages.warning(
                            request,
                            "Your enquiry was saved, but the teacher email notification could not be sent.",
                        )
                    else:
                        messages.success(request, "Your teaching enquiry has been sent.")
        return redirect("public_teacher_profile", slug=teacher.public_slug)
    TeacherProfileView.objects.create(teacher=teacher)
    return _render_teacher_detail(request, teacher)


def course_detail(request, pk):
    course = get_object_or_404(Course.objects.select_related("subject", "teacher", "teacher__user"), pk=pk)
    enrollment = Enrollment.objects.filter(student=request.user, course=course).first() if request.user.is_authenticated else None
    is_enrolled = bool(enrollment and enrollment.paid)
    lessons = course.lessons.order_by("order", "pk") if is_enrolled else Lesson.objects.none()
    return render(request, "edtech/course_detail.html", {
        "course": course,
        "enrollment": enrollment,
        "is_enrolled": is_enrolled,
        "lessons": lessons,
        "completed_lesson_ids": set(
            LessonProgress.objects.filter(
                student=request.user, lesson__course=course,
            ).values_list("lesson_id", flat=True)
        ) if request.user.is_authenticated and is_enrolled else set(),
        "display_price": course.discount_price if course.discount_price is not None else course.price,
        "payment_request_key": uuid4(),
    })


@login_required
@require_POST
def complete_lesson(request, pk, lesson_pk):
    profile = get_object_or_404(UserProfile, user=request.user, role="student")
    course = get_object_or_404(Course, pk=pk, active=True)
    enrollment = get_object_or_404(
        Enrollment, student=profile.user, course=course, paid=True,
    )
    lesson = get_object_or_404(Lesson, pk=lesson_pk, course=course)
    with transaction.atomic():
        LessonProgress.objects.get_or_create(student=request.user, lesson=lesson)
        lesson_count = course.lessons.count()
        completed_count = LessonProgress.objects.filter(
            student=request.user, lesson__course=course,
        ).count()
        enrollment.progress = round(completed_count * 100 / lesson_count) if lesson_count else 0
        enrollment.save(update_fields=["progress"])
    messages.success(request, "Lesson marked complete.")
    return redirect("course_detail", pk=course.pk)


@login_required
@require_POST
def enroll_course(request, pk):
    course = get_object_or_404(Course, pk=pk, active=True)
    existing = Enrollment.objects.filter(student=request.user, course=course, paid=True).exists()
    if existing:
        messages.info(request, "You are already enrolled in this course.")
        return redirect("course_detail", pk=course.pk)
    price = course.discount_price if course.discount_price is not None else course.price
    if price < 0:
        messages.error(request, "This course is not available for enrollment.")
        return redirect("course_detail", pk=course.pk)
    if price == 0:
        Enrollment.objects.update_or_create(
            student=request.user, course=course, defaults={"paid": True}
        )
        messages.success(request, "You are enrolled in this free course.")
        return redirect("course_detail", pk=course.pk)

    try:
        request_key = UUID(request.POST.get("request_key", ""))
    except (ValueError, AttributeError):
        messages.error(request, "The checkout session expired. Please try again.")
        return redirect("course_detail", pk=course.pk)
    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        messages.error(request, "Online payments are not configured yet. Please contact support.")
        return redirect("course_detail", pk=course.pk)

    payment, _ = PaymentTransaction.objects.get_or_create(
        request_key=request_key,
        defaults={"user": request.user, "course": course, "amount": price},
    )
    if (
        payment.user_id != request.user.pk
        or payment.course_id != course.pk
        or payment.status == "paid"
    ):
        messages.error(request, "This checkout request is no longer valid.")
        return redirect("course_detail", pk=course.pk)
    if not payment.provider_order_id:
        try:
            order_data = _razorpay_request("POST", "/orders", {
                "amount": int((payment.amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
                "currency": "INR",
                "receipt": request_key.hex,
                "notes": {"payment_transaction_id": str(payment.pk)},
            })
            provider_order_id = order_data.get("id")
            if not provider_order_id:
                raise PaymentGatewayError("Payment provider returned no order identifier.")
            payment.provider_order_id = provider_order_id
            payment.status = "created"
            payment.save(update_fields=["provider_order_id", "status"])
        except PaymentGatewayError:
            payment.status = "failed"
            payment.save(update_fields=["status"])
            logger.exception("Could not create Razorpay order for transaction %s.", payment.pk)
            messages.error(request, "We could not start checkout. Please try again shortly.")
            return redirect("course_detail", pk=course.pk)
    elif payment.status == "failed":
        payment.status = "created"
        payment.save(update_fields=["status"])
    return render(request, "edtech/payment_checkout.html", {
        "course": course,
        "payment": payment,
        "checkout_data": {
            "options": {
                "key": settings.RAZORPAY_KEY_ID,
                "amount": int((payment.amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
                "currency": payment.currency,
                "name": "Tuition.com",
                "description": course.title,
                "order_id": payment.provider_order_id,
                "prefill": {
                    "name": request.user.get_full_name() or request.user.username,
                    "email": request.user.email,
                },
                "theme": {"color": "#0066FF"},
            },
            "verify_url": reverse("verify_payment"),
            "transaction_id": str(payment.pk),
        },
    })


def _razorpay_request(method, path, payload=None):
    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        raise PaymentGatewayError("Razorpay credentials are not configured.")
    credentials = f"{settings.RAZORPAY_KEY_ID}:{settings.RAZORPAY_KEY_SECRET}".encode()
    authorization = base64.b64encode(credentials).decode("ascii")
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"https://api.razorpay.com/v1{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Basic {authorization}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            response_data = json.loads(response.read().decode("utf-8"))
            if not isinstance(response_data, dict):
                raise PaymentGatewayError("Razorpay returned an invalid response.")
            return response_data
    except urllib.error.HTTPError as error:
        logger.error("Razorpay API returned HTTP %s.", error.code)
        raise PaymentGatewayError("Razorpay rejected the payment request.") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        logger.exception("Could not reach Razorpay.")
        raise PaymentGatewayError("Razorpay is temporarily unavailable.") from error
    except json.JSONDecodeError as error:
        logger.exception("Razorpay returned an invalid response.")
        raise PaymentGatewayError("Razorpay returned an invalid response.") from error


def _complete_course_payment(payment, provider_payment_id):
    with transaction.atomic():
        payment = PaymentTransaction.objects.select_for_update().get(pk=payment.pk)
        if payment.status == "paid":
            if payment.provider_payment_id != provider_payment_id:
                raise PaymentGatewayError("This order was already completed with a different payment.")
            return payment
        payment.status = "paid"
        payment.provider_payment_id = provider_payment_id
        payment.paid_at = timezone.now()
        payment.save(update_fields=["status", "provider_payment_id", "paid_at"])
        Enrollment.objects.update_or_create(
            student=payment.user,
            course=payment.course,
            defaults={"paid": True},
        )
        return payment


@login_required
@require_POST
def verify_payment(request):
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid payment response."}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({"error": "Invalid payment response."}, status=400)
    transaction_id = data.get("transaction_id")
    order_id = data.get("razorpay_order_id")
    payment_id = data.get("razorpay_payment_id")
    signature = data.get("razorpay_signature")
    if not all(isinstance(value, str) and value for value in (transaction_id, order_id, payment_id, signature)):
        return JsonResponse({"error": "Payment response is incomplete."}, status=400)
    if not transaction_id.isascii() or not transaction_id.isdigit():
        return JsonResponse({"error": "Payment transaction identifier is invalid."}, status=400)
    payment = get_object_or_404(PaymentTransaction, pk=transaction_id, user=request.user)
    if not payment.provider_order_id or not hmac.compare_digest(payment.provider_order_id, order_id):
        return JsonResponse({"error": "Payment order does not match this checkout."}, status=400)
    signature_payload = f"{order_id}|{payment_id}".encode("utf-8")
    expected_signature = hmac.new(
        settings.RAZORPAY_KEY_SECRET.encode("utf-8"), signature_payload, hashlib.sha256
    ).hexdigest()
    if not settings.RAZORPAY_KEY_SECRET or not hmac.compare_digest(expected_signature, signature):
        return JsonResponse({"error": "Payment signature is invalid."}, status=400)
    try:
        provider_payment = _razorpay_request(
            "GET", f"/payments/{urllib.parse.quote(payment_id, safe='')}"
        )
    except PaymentGatewayError:
        return JsonResponse({
            "error": "Payment was received but could not yet be verified. Please contact support if it remains pending."
        }, status=503)
    expected_amount = int((payment.amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if (
        provider_payment.get("order_id") != order_id
        or provider_payment.get("amount") != expected_amount
        or provider_payment.get("currency") != payment.currency
        or provider_payment.get("status") != "captured"
    ):
        return JsonResponse({
            "error": "Payment is not captured yet. Your access will be updated after confirmation."
        }, status=409)
    try:
        _complete_course_payment(payment, payment_id)
    except PaymentGatewayError as error:
        return JsonResponse({"error": str(error)}, status=409)
    return JsonResponse({
        "status": "paid",
        "redirect_url": reverse("course_detail", args=[payment.course_id]),
    })


@csrf_exempt
@require_POST
def razorpay_webhook(request):
    webhook_secret = settings.RAZORPAY_WEBHOOK_SECRET
    signature = request.headers.get("X-Razorpay-Signature", "")
    if not webhook_secret or not signature:
        return JsonResponse({"error": "Webhook verification is not configured."}, status=400)
    expected_signature = hmac.new(
        webhook_secret.encode("utf-8"), request.body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected_signature, signature):
        return JsonResponse({"error": "Invalid webhook signature."}, status=400)
    try:
        event_data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid webhook payload."}, status=400)
    if not isinstance(event_data, dict):
        return JsonResponse({"error": "Invalid webhook payload."}, status=400)
    event_type = event_data.get("event")
    if event_type != "payment.captured":
        return JsonResponse({"status": "ignored"})
    try:
        provider_payment = event_data["payload"]["payment"]["entity"]
        order_id = provider_payment["order_id"]
        payment_id = provider_payment["id"]
        amount = provider_payment["amount"]
        currency = provider_payment["currency"]
    except (KeyError, TypeError):
        return JsonResponse({"error": "Captured payment details are incomplete."}, status=400)
    if (
        not isinstance(order_id, str)
        or not order_id
        or not isinstance(payment_id, str)
        or not payment_id
        or provider_payment.get("status") != "captured"
        or type(amount) is not int
        or not isinstance(currency, str)
    ):
        return JsonResponse({"error": "Captured payment details are invalid."}, status=400)
    payment = PaymentTransaction.objects.filter(provider_order_id=order_id).first()
    if payment is None:
        logger.warning("Razorpay webhook references unknown order %s.", order_id)
        return JsonResponse({"error": "Unknown payment order."}, status=404)
    expected_amount = int((payment.amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if amount != expected_amount or currency != payment.currency:
        logger.error("Razorpay webhook amount does not match transaction %s.", payment.pk)
        return JsonResponse({"error": "Payment amount or currency does not match."}, status=400)
    event_id = hashlib.sha256(request.body).hexdigest()
    with transaction.atomic():
        event, created = PaymentWebhookEvent.objects.get_or_create(
            event_id=event_id, defaults={"event_type": event_type}
        )
        if not created:
            return JsonResponse({"status": "duplicate"})
        try:
            _complete_course_payment(payment, payment_id)
        except PaymentGatewayError as error:
            return JsonResponse({"error": str(error)}, status=409)
    return JsonResponse({"status": "processed"})


@login_required
def book_demo(request, pk):
    teacher = get_object_or_404(TeacherProfile, pk=pk)
    if request.user == teacher.user:
        messages.error(request, "You cannot book a lesson with yourself.")
        return redirect("public_teacher_profile", slug=teacher.public_slug)
    form = BookingRequestForm(request.POST or None, teacher=teacher)
    if request.method == "POST":
        if form.is_valid():
            try:
                with transaction.atomic():
                    booking = Booking.objects.create(
                        student=request.user, teacher=teacher,
                        subject=form.cleaned_data["subject"],
                        starts_at=form.cleaned_data["starts_at"],
                        duration_minutes=60, is_demo=True, fee=0,
                    )
            except IntegrityError:
                form.add_error("starts_at", "That time was just booked. Please choose another.")
            else:
                local_start = timezone.localtime(booking.starts_at).strftime("%A, %d %B at %I:%M %p")
                teacher_message = (
                    f"{request.user.get_full_name() or request.user.username} requested a free demo for "
                    f"{booking.subject.name} on {local_start}."
                )
                student_message = (
                    f"Your free demo request with {teacher} for {booking.subject.name} "
                    f"on {local_start} is pending confirmation."
                )
                teacher_email_sent = _notify_user(
                    teacher.user, "New free demo request", teacher_message,
                    "New free demo request",
                    f"{teacher_message}\n\nSign in to Tuition.com to manage this request.",
                    reply_to=request.user.email,
                )
                student_email_sent = _notify_user(
                    request.user, "Demo request received", student_message,
                    "Your free demo request was received",
                    f"{student_message}\n\nThe teacher will confirm the session.",
                )
                if not teacher_email_sent or not student_email_sent:
                    messages.warning(
                        request,
                        "Your booking request was saved, but an email notification could not be sent.",
                    )
                else:
                    messages.success(request, "Free demo request submitted.")
                return redirect("dashboard")
    availability = teacher.availability.filter(ends_at__gt=timezone.now()).order_by("starts_at")
    return render(request, "edtech/book_demo.html", {
        "teacher": teacher, "form": form, "availability": availability,
    })


@login_required
@require_POST
def favorite_teacher(request, pk):
    get_object_or_404(UserProfile, user=request.user, role="student")
    teacher = get_object_or_404(TeacherProfile, pk=pk)
    favorite = FavoriteTeacher.objects.filter(student=request.user, teacher=teacher)
    if favorite.exists():
        favorite.delete()
        messages.success(request, "Teacher removed from favorites.")
    else:
        FavoriteTeacher.objects.create(student=request.user, teacher=teacher)
        messages.success(request, "Teacher saved.")
    next_url = request.POST.get("next", "")
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect("student_teachers")


@login_required
def student_teachers(request):
    get_object_or_404(UserProfile, user=request.user, role="student")
    favorites = FavoriteTeacher.objects.filter(
        student=request.user,
    ).select_related("teacher", "teacher__user").order_by("teacher__user__first_name")
    connected_teachers = TeacherProfile.objects.filter(
        Q(bookings__student=request.user)
        | Q(courses__enrollments__student=request.user, courses__enrollments__paid=True)
    ).select_related("user").distinct().order_by("user__first_name")
    return render(request, "edtech/student_teachers.html", {
        "favorites": favorites,
        "connected_teachers": connected_teachers,
    })


@login_required
@require_POST
def start_chat(request, teacher_id):
    get_object_or_404(UserProfile, user=request.user, role="student")
    teacher = get_object_or_404(TeacherProfile, pk=teacher_id)
    is_connected = (
        FavoriteTeacher.objects.filter(student=request.user, teacher=teacher).exists()
        or Booking.objects.filter(student=request.user, teacher=teacher).exists()
        or Enrollment.objects.filter(
            student=request.user, course__teacher=teacher, paid=True,
        ).exists()
    )
    if not is_connected:
        raise Http404
    conversation, _ = ChatConversation.objects.get_or_create(
        student=request.user, teacher=teacher,
    )
    return redirect("chat_conversation", conversation_id=conversation.pk)


@login_required
def chat_inbox(request):
    teacher = getattr(request.user, "teacher_profile", None)
    if teacher:
        conversations = teacher.chat_conversations.select_related(
            "student", "teacher__user",
        )
        role = "teacher"
    else:
        get_object_or_404(UserProfile, user=request.user, role="student")
        conversations = ChatConversation.objects.filter(
            student=request.user,
        ).select_related("student", "teacher", "teacher__user")
        role = "student"
    return render(request, "edtech/chat_inbox.html", {
        "conversations": conversations,
        "role": role,
    })


@login_required
def chat_conversation(request, conversation_id):
    conversation = get_object_or_404(
        ChatConversation.objects.select_related("student", "teacher", "teacher__user"),
        Q(student=request.user) | Q(teacher__user=request.user),
        pk=conversation_id,
    )
    role = "teacher" if conversation.teacher.user_id == request.user.pk else "student"
    if request.method == "POST":
        body = request.POST.get("body", "").strip()
        if not body:
            messages.error(request, "Write a message before sending it.")
        elif len(body) > 4000:
            messages.error(request, "Messages must be 4,000 characters or fewer.")
        else:
            ChatMessage.objects.create(
                conversation=conversation,
                sender=request.user,
                body=body,
            )
            conversation.save(update_fields=["updated_at"])
            recipient = conversation.student if role == "teacher" else conversation.teacher.user
            sender_name = request.user.get_full_name() or request.user.username
            Notification.objects.create(
                user=recipient,
                title=f"New message from {sender_name}",
                message=f"{sender_name} sent you a chat message.",
            )
            messages.success(request, "Your message has been sent.")
        return redirect("chat_conversation", conversation_id=conversation.pk)

    return render(request, "edtech/chat_conversation.html", {
        "conversation": conversation,
        "conversation_messages": conversation.messages.select_related("sender"),
        "role": role,
        "other_participant": (
            conversation.student if role == "teacher" else conversation.teacher.user
        ),
    })


@login_required
def student_bookings(request):
    get_object_or_404(UserProfile, user=request.user, role="student")
    bookings = Booking.objects.filter(
        student=request.user,
    ).select_related("teacher", "teacher__user", "subject").order_by("-starts_at")
    return render(request, "edtech/student_bookings.html", {
        "bookings": bookings, "now": timezone.now(),
    })


@login_required
@require_POST
def cancel_student_booking(request, pk):
    get_object_or_404(UserProfile, user=request.user, role="student")
    with transaction.atomic():
        booking = get_object_or_404(
            Booking.objects.select_for_update().select_related("teacher", "teacher__user"),
            pk=pk, student=request.user,
        )
        if booking.status not in ("pending", "confirmed") or booking.starts_at <= timezone.now():
            messages.error(request, "This booking can no longer be cancelled online.")
            return redirect("student_bookings")
        booking.status = "cancelled"
        booking.save(update_fields=["status"])
    Notification.objects.create(
        user=booking.teacher.user,
        title="Student cancelled a class",
        message=f"{request.user.get_full_name() or request.user.username} cancelled the class scheduled for {timezone.localtime(booking.starts_at):%d %b %Y at %I:%M %p}.",
    )
    messages.success(request, "Your booking was cancelled.")
    return redirect("student_bookings")


@login_required
def student_notifications(request):
    get_object_or_404(UserProfile, user=request.user, role="student")
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "mark_all_read":
            request.user.notifications.filter(read=False).update(read=True)
            messages.success(request, "All notifications marked as read.")
        elif action == "mark_read":
            updated = request.user.notifications.filter(
                pk=request.POST.get("notification_id"), read=False,
            ).update(read=True)
            if updated:
                messages.success(request, "Notification marked as read.")
            else:
                messages.info(request, "That notification is already read or unavailable.")
        else:
            messages.error(request, "Choose a valid notification action.")
        return redirect("student_notifications")
    notifications = Paginator(
        request.user.notifications.order_by("-created_at"), 15,
    ).get_page(request.GET.get("page"))
    return render(request, "edtech/student_notifications.html", {
        "notifications": notifications,
    })


def material_list(request):
    materials = StudyMaterial.objects.filter(active=True).select_related("subject", "grade")
    subject = request.GET.get("subject")
    query = request.GET.get("q")
    if subject:
        materials = materials.filter(subject_id=subject)
    if query:
        materials = materials.filter(Q(title__icontains=query) | Q(description__icontains=query))
    return render(request, "edtech/material_list.html", {
        "materials": materials, "subjects": Subject.objects.filter(active=True)
    })


@login_required
def teacher_enquiries(request):
    teacher = get_object_or_404(TeacherProfile, user=request.user)
    if request.method == "POST":
        enquiry = get_object_or_404(
            TeacherEnquiry.objects.select_related("sender"),
            pk=request.POST.get("enquiry_id"),
            teacher=teacher,
        )
        reply_message = request.POST.get("reply_message", "").strip()
        if not reply_message:
            messages.error(request, "Write a reply before sending it.")
        elif enquiry.reply_message:
            messages.error(request, "A reply has already been sent for this enquiry.")
        else:
            enquiry.reply_message = reply_message
            enquiry.replied_at = timezone.now()
            enquiry.save(update_fields=["reply_message", "replied_at"])

            teacher_name = teacher.user.get_full_name() or teacher.user.username
            email_body = (
                f"Hello {enquiry.name},\n\n"
                f"{teacher_name} replied to your teaching enquiry:\n\n"
                f"{reply_message}\n\n"
                f"Your original enquiry:\n{enquiry.message}\n"
            )
            reply_to = [request.user.email] if request.user.email else None
            if enquiry.sender_id:
                email_sent = _notify_user(
                    enquiry.sender,
                    "A teacher replied to your enquiry",
                    f"{teacher_name} replied to your teaching enquiry.",
                    "Reply to your teaching enquiry on Tuition.com",
                    email_body,
                    reply_to=request.user.email or None,
                )
            else:
                try:
                    email_sent = bool(EmailMessage(
                        "Reply to your teaching enquiry on Tuition.com",
                        email_body,
                        to=[enquiry.email],
                        reply_to=reply_to,
                    ).send(fail_silently=False))
                except (OSError, smtplib.SMTPException):
                    logger.exception("Email reply failed for enquiry %s.", enquiry.pk)
                    email_sent = False
                if not email_sent:
                    logger.error("Email backend did not send a reply for enquiry %s.", enquiry.pk)

            if email_sent:
                messages.success(request, "Your reply has been sent.")
            elif enquiry.sender_id:
                messages.warning(
                    request,
                    "Your reply was saved and is visible in the student's dashboard, but the email could not be sent.",
                )
            else:
                messages.warning(
                    request,
                    "Your reply was saved, but the email could not be sent.",
                )
        return redirect("teacher_enquiries")

    enquiries = Paginator(
        teacher.enquiries.select_related("sender").order_by("-created_at"), 10
    ).get_page(request.GET.get("page"))
    return render(request, "edtech/teacher_enquiries.html", {
        "teacher": teacher, "enquiries": enquiries,
    })


@login_required
def teacher_materials(request):
    get_object_or_404(TeacherProfile, user=request.user)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add_material":
            form = StudyMaterialForm(request.POST, request.FILES)
            if form.is_valid():
                material = form.save(commit=False)
                material.uploaded_by = request.user
                material.save()
                messages.success(request, "Study material added.")
                return redirect("teacher_materials")
            errors = "; ".join(
                error for field_errors in form.errors.values() for error in field_errors
            )
            messages.error(request, f"Could not add study material: {errors}")
        elif action == "delete_material":
            material = get_object_or_404(
                StudyMaterial, pk=request.POST.get("item_id"), uploaded_by=request.user
            )
            if material.file:
                material.file.delete(save=False)
            material.delete()
            messages.success(request, "Study material removed.")
            return redirect("teacher_materials")
        else:
            form = StudyMaterialForm()
            messages.error(request, "Choose a valid study material action.")
    else:
        form = StudyMaterialForm()
    materials = StudyMaterial.objects.filter(uploaded_by=request.user).select_related(
        "subject", "grade"
    ).order_by("-created_at")
    return render(request, "edtech/teacher_materials.html", {
        "form": form, "materials": materials,
    })


@login_required
def teacher_availability(request):
    teacher = get_object_or_404(TeacherProfile, user=request.user)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add_availability":
            form = TeacherAvailabilityForm(request.POST, teacher=teacher)
            if form.is_valid():
                availability = form.save(commit=False)
                availability.teacher = teacher
                availability.save()
                messages.success(request, "Availability window saved.")
                return redirect("teacher_availability")
            errors = "; ".join(
                error for field_errors in form.errors.values() for error in field_errors
            )
            messages.error(request, f"Could not save availability: {errors}")
        elif action == "delete_availability":
            availability = get_object_or_404(
                teacher.availability, pk=request.POST.get("item_id")
            )
            availability.delete()
            messages.success(request, "Availability window removed.")
            return redirect("teacher_availability")
        else:
            form = TeacherAvailabilityForm(teacher=teacher)
            messages.error(request, "Choose a valid availability action.")
    else:
        form = TeacherAvailabilityForm(teacher=teacher)
    return render(request, "edtech/teacher_availability.html", {
        "teacher": teacher,
        "form": form,
        "availability": teacher.availability.filter(ends_at__gt=timezone.now()).order_by("starts_at"),
    })


@login_required
def edit_profile(request):
    profile = getattr(request.user, "profile", None)
    if hasattr(request.user, "teacher_profile"):
        return _manage_teacher_profile(request, request.user.teacher_profile, profile)
    if not profile or profile.role != "student":
        return redirect("dashboard")
    student_profile, _ = StudentProfile.objects.get_or_create(user=request.user)
    form = StudentSettingsForm(
        request.POST or None,
        request.FILES or None,
        user=request.user,
        profile=profile,
        student_profile=student_profile,
    )
    if request.method == "POST":
        if form.is_valid():
            request.user.first_name = form.cleaned_data["first_name"]
            request.user.last_name = form.cleaned_data["last_name"]
            request.user.email = form.cleaned_data["email"]
            request.user.save(update_fields=["first_name", "last_name", "email"])
            profile.phone = form.cleaned_data["phone"]
            profile.grade = form.cleaned_data["grade"]
            profile.board = form.cleaned_data["board"]
            if form.cleaned_data.get("profile_picture"):
                profile.profile_picture = form.cleaned_data["profile_picture"]
            profile.save()
            profile.preferred_subjects.set(form.cleaned_data["preferred_subjects"])
            student_profile.guardian_name = form.cleaned_data["guardian_name"]
            student_profile.guardian_phone = form.cleaned_data["guardian_phone"]
            student_profile.learning_goals = form.cleaned_data["learning_goals"]
            student_profile.save()
            messages.success(request, "Student profile updated.")
            return redirect("edit_profile")
        messages.error(request, "Please correct the highlighted profile fields.")
    return render(request, "edtech/edit_profile.html", {
        "profile": profile, "student_profile": student_profile, "form": form,
    })


def _manage_teacher_profile(request, teacher, profile):
    if profile is None:
        profile = UserProfile.objects.create(user=request.user, role="teacher")
    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "save_profile":
            form = TeacherProfileForm(request.POST, request.FILES, user=request.user)
            if form.is_valid():
                form.save(request.user, profile, teacher)
                messages.success(request, "Professional profile updated.")
            else:
                errors = "; ".join(
                    error for field_errors in form.errors.values() for error in field_errors
                )
                messages.error(request, f"Please correct the profile fields: {errors}")
        elif action in ("add_subject", "update_subject"):
            item = None
            if action == "update_subject":
                item = get_object_or_404(TeacherSubject, pk=request.POST.get("item_id"), teacher=teacher)
            form = TeacherSubjectForm(request.POST, instance=item)
            if form.is_valid():
                subject_item = form.save(commit=False)
                subject_item.teacher = teacher
                try:
                    subject_item.save()
                except IntegrityError:
                    messages.error(request, "That subject and education level are already in your profile.")
                else:
                    teacher.subjects.add(subject_item.subject)
                    messages.success(request, "Teaching subject saved.")
            else:
                messages.error(request, "Please complete the subject details.")
        elif action == "add_manual_subject":
            subject_name = request.POST.get("subject_name", "").strip()
            if not subject_name:
                messages.error(request, "Enter a subject name.")
            elif len(subject_name) > 100:
                messages.error(request, "Subject names must be 100 characters or fewer.")
            else:
                subject = Subject.objects.filter(name__iexact=subject_name).first()
                if subject and not subject.active:
                    messages.error(request, "A subject with that name exists but is unavailable.")
                elif subject and teacher.subjects.filter(pk=subject.pk).exists():
                    messages.error(request, "That subject is already in My Subjects.")
                else:
                    if subject is None:
                        base_slug = slugify(subject_name) or "subject"
                        subject_slug = base_slug
                        suffix = 2
                        while Subject.objects.filter(slug=subject_slug).exists():
                            subject_slug = f"{base_slug}-{suffix}"
                            suffix += 1
                        subject = Subject.objects.create(
                            name=subject_name,
                            slug=subject_slug,
                            category="School",
                        )
                    teacher.subjects.add(subject)
                    messages.success(request, f"{subject.name} added to My Subjects.")
        elif action == "remove_manual_subject":
            subject = teacher.subjects.filter(pk=request.POST.get("subject_id")).first()
            if subject:
                teacher.teaching_subjects.filter(subject=subject).delete()
                teacher.subjects.remove(subject)
                messages.success(request, f"{subject.name} removed from My Subjects.")
            else:
                messages.error(request, "That subject is not in My Subjects.")
        elif action in ("add_experience", "update_experience"):
            item = None
            if action == "update_experience":
                item = get_object_or_404(TeacherExperience, pk=request.POST.get("item_id"), teacher=teacher)
            form = TeacherExperienceForm(request.POST, instance=item)
            if form.is_valid():
                experience = form.save(commit=False)
                experience.teacher = teacher
                experience.save()
                messages.success(request, "Professional experience saved.")
            else:
                messages.error(request, "Please check the experience dates and required fields.")
        elif action in ("add_achievement", "update_achievement"):
            item = None
            if action == "update_achievement":
                item = get_object_or_404(TeacherAchievement, pk=request.POST.get("item_id"), teacher=teacher)
            form = TeacherAchievementForm(request.POST, request.FILES, instance=item)
            if form.is_valid():
                achievement = form.save(commit=False)
                achievement.teacher = teacher
                achievement.save()
                messages.success(request, "Achievement saved.")
            else:
                messages.error(request, "Please complete the achievement details.")
        elif action in ("add_portfolio", "update_portfolio"):
            item = None
            if action == "update_portfolio":
                item = get_object_or_404(TeacherPortfolioItem, pk=request.POST.get("item_id"), teacher=teacher)
            form = TeacherPortfolioForm(request.POST, request.FILES, instance=item)
            if form.is_valid():
                portfolio_item = form.save(commit=False)
                portfolio_item.teacher = teacher
                portfolio_item.save()
                messages.success(request, "Portfolio item saved.")
            else:
                messages.error(request, "Please complete the portfolio details.")
        elif action == "add_skill":
            skill_name = request.POST.get("skill_name", "").strip()
            if not skill_name or len(skill_name) > 60:
                messages.error(request, "Enter a skill name of 60 characters or fewer.")
            else:
                _, created = TeacherSkill.objects.get_or_create(teacher=teacher, name=skill_name)
                messages.success(request, "Skill added." if created else "That skill is already listed.")
        elif action.startswith("delete_"):
            model_map = {
                "delete_subject": TeacherSubject,
                "delete_experience": TeacherExperience,
                "delete_achievement": TeacherAchievement,
                "delete_portfolio": TeacherPortfolioItem,
                "delete_skill": TeacherSkill,
            }
            model = model_map.get(action)
            if model:
                deleted, _ = model.objects.filter(pk=request.POST.get("item_id"), teacher=teacher).delete()
                if deleted:
                    if action == "delete_subject":
                        still_teaches = teacher.teaching_subjects.filter(subject_id=request.POST.get("subject_id")).exists()
                        if not still_teaches:
                            teacher.subjects.remove(request.POST.get("subject_id"))
                    messages.success(request, "Profile item removed.")
                else:
                    messages.error(request, "That profile item could not be found.")
        return redirect("edit_profile")
    return render(request, "edtech/teacher_profile_manage.html", {
        "profile": profile,
        "teacher": teacher,
        "completion": teacher_profile_completion(teacher),
        "subject_form": TeacherSubjectForm(),
        "manual_subjects": teacher.subjects.order_by("name"),
        "experience_form": TeacherExperienceForm(),
        "achievement_form": TeacherAchievementForm(),
        "portfolio_form": TeacherPortfolioForm(),
        "subject_items": teacher.teaching_subjects.select_related("subject"),
        "experiences": teacher.professional_experiences.all(),
        "achievements": teacher.achievements.all(),
        "skills": teacher.skills.all(),
        "portfolio_items": teacher.portfolio_items.all(),
    })
