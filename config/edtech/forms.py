from datetime import timedelta

from django import forms
from django.contrib.auth.models import User
from django.utils import timezone

from .models import (
    Booking, EducationBoard, Grade, StudentProfile, StudyMaterial, Subject,
    TeacherAchievement, TeacherAvailability, TeacherExperience,
    TeacherPortfolioItem, TeacherSubject, UserProfile,
)


class TeacherProfileForm(forms.Form):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField()
    phone = forms.CharField(max_length=20, required=False)
    profile_picture = forms.ImageField(required=False)
    headline = forms.CharField(max_length=180, required=False)
    biography = forms.CharField(required=False, widget=forms.Textarea)
    qualifications = forms.CharField(max_length=250, required=False)
    college = forms.CharField(max_length=180, required=False)
    location = forms.CharField(max_length=150, required=False)
    cover_image = forms.ImageField(required=False)
    experience_years = forms.IntegerField(min_value=0, required=False, initial=0)
    hourly_fee = forms.DecimalField(min_value=0, max_digits=8, decimal_places=2, required=False)

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = self.cleaned_data["email"]
        if User.objects.filter(email__iexact=email).exclude(pk=self.user.pk).exists():
            raise forms.ValidationError("That email address is already registered.")
        return email

    def save(self, user, profile, teacher):
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.email = self.cleaned_data["email"]
        user.save()
        profile.phone = self.cleaned_data["phone"]
        if self.cleaned_data.get("profile_picture"):
            profile.profile_picture = self.cleaned_data["profile_picture"]
        profile.save()
        teacher.headline = self.cleaned_data["headline"]
        teacher.biography = self.cleaned_data["biography"]
        teacher.qualifications = self.cleaned_data["qualifications"]
        teacher.college = self.cleaned_data["college"]
        teacher.location = self.cleaned_data["location"]
        teacher.experience_years = self.cleaned_data.get("experience_years") or 0
        if self.cleaned_data.get("hourly_fee") is not None:
            teacher.hourly_fee = self.cleaned_data["hourly_fee"]
        if self.cleaned_data.get("cover_image"):
            teacher.cover_image = self.cleaned_data["cover_image"]
        teacher.save()


class StudentSettingsForm(forms.Form):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField()
    phone = forms.CharField(max_length=20, required=False)
    profile_picture = forms.ImageField(required=False)
    grade = forms.ModelChoiceField(queryset=Grade.objects.none(), required=False)
    board = forms.ModelChoiceField(queryset=EducationBoard.objects.none(), required=False)
    preferred_subjects = forms.ModelMultipleChoiceField(
        queryset=Subject.objects.none(), required=False,
    )
    guardian_name = forms.CharField(max_length=100, required=False)
    guardian_phone = forms.CharField(max_length=20, required=False)
    learning_goals = forms.CharField(required=False, widget=forms.Textarea)

    def __init__(self, *args, user, profile, student_profile, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields["grade"].queryset = Grade.objects.order_by("order", "name")
        self.fields["board"].queryset = EducationBoard.objects.order_by("name")
        self.fields["preferred_subjects"].queryset = Subject.objects.filter(active=True).order_by("name")
        if not self.is_bound:
            self.initial.update({
                "first_name": user.first_name,
                "last_name": user.last_name,
                "email": user.email,
                "phone": profile.phone,
                "grade": profile.grade_id,
                "board": profile.board_id,
                "preferred_subjects": profile.preferred_subjects.values_list("pk", flat=True),
                "guardian_name": student_profile.guardian_name,
                "guardian_phone": student_profile.guardian_phone,
                "learning_goals": student_profile.learning_goals,
            })

    def clean_email(self):
        email = self.cleaned_data["email"]
        if User.objects.filter(email__iexact=email).exclude(pk=self.user.pk).exists():
            raise forms.ValidationError("That email address is already registered.")
        return email


class TeacherSubjectForm(forms.ModelForm):
    class Meta:
        model = TeacherSubject
        fields = ["subject", "education_level", "classes", "teaching_mode", "experience_years"]


class TeacherExperienceForm(forms.ModelForm):
    class Meta:
        model = TeacherExperience
        fields = [
            "job_title", "organization", "employment_type", "start_date",
            "end_date", "currently_working", "responsibilities",
        ]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("currently_working"):
            cleaned_data["end_date"] = None
        elif cleaned_data.get("end_date") and cleaned_data.get("start_date") and cleaned_data["end_date"] < cleaned_data["start_date"]:
            self.add_error("end_date", "End date must be on or after the start date.")
        return cleaned_data


class TeacherAchievementForm(forms.ModelForm):
    class Meta:
        model = TeacherAchievement
        fields = [
            "title", "certificate_name", "issuing_organization", "issue_date",
            "certificate_file", "description",
        ]
        widgets = {"issue_date": forms.DateInput(attrs={"type": "date"})}


class TeacherPortfolioForm(forms.ModelForm):
    class Meta:
        model = TeacherPortfolioItem
        fields = ["title", "item_type", "description", "url", "file"]


class StudyMaterialForm(forms.ModelForm):
    class Meta:
        model = StudyMaterial
        fields = ["title", "subject", "grade", "description", "file", "external_url"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["subject"].queryset = Subject.objects.filter(active=True).order_by("name")
        self.fields["grade"].queryset = Grade.objects.order_by("order", "name")

    def clean_file(self):
        uploaded_file = self.cleaned_data.get("file")
        if uploaded_file:
            allowed_extensions = {
                ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx",
                ".csv", ".txt", ".zip", ".jpg", ".jpeg", ".png", ".webp", ".mp4",
            }
            extension = "." + uploaded_file.name.rsplit(".", 1)[-1].lower() if "." in uploaded_file.name else ""
            if extension not in allowed_extensions:
                raise forms.ValidationError("Upload a PDF, office document, image, video, text file, or ZIP.")
            if uploaded_file.size > 25 * 1024 * 1024:
                raise forms.ValidationError("Study material files must be 25 MB or smaller.")
        return uploaded_file

    def clean(self):
        cleaned_data = super().clean()
        has_file = bool(cleaned_data.get("file"))
        has_url = bool(cleaned_data.get("external_url"))
        if has_file == has_url:
            raise forms.ValidationError("Choose exactly one source: upload a file or provide an external link.")
        return cleaned_data


class TeacherAvailabilityForm(forms.ModelForm):
    starts_at = forms.DateTimeField(
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
    )
    ends_at = forms.DateTimeField(
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
    )

    class Meta:
        model = TeacherAvailability
        fields = ["starts_at", "ends_at"]
        widgets = {
            "starts_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "ends_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args, teacher, **kwargs):
        self.teacher = teacher
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        starts_at = cleaned_data.get("starts_at")
        ends_at = cleaned_data.get("ends_at")
        if starts_at and starts_at <= timezone.now():
            self.add_error("starts_at", "Availability must start in the future.")
        if starts_at and ends_at and ends_at <= starts_at:
            self.add_error("ends_at", "End time must be after start time.")
        if starts_at and ends_at and starts_at > timezone.now():
            overlaps = TeacherAvailability.objects.filter(
                teacher=self.teacher, starts_at__lt=ends_at, ends_at__gt=starts_at
            )
            if overlaps.exists():
                raise forms.ValidationError("This time overlaps an availability window you already added.")
        return cleaned_data


class BookingRequestForm(forms.Form):
    starts_at = forms.DateTimeField(
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
    )
    subject = forms.ModelChoiceField(queryset=Subject.objects.none())

    def __init__(self, *args, teacher, **kwargs):
        self.teacher = teacher
        super().__init__(*args, **kwargs)
        self.fields["subject"].queryset = teacher.subjects.filter(active=True).order_by("name")

    def clean_starts_at(self):
        starts_at = self.cleaned_data["starts_at"]
        if starts_at <= timezone.now():
            raise forms.ValidationError("Choose a date and time in the future.")
        duration = timedelta(minutes=60)
        available = self.teacher.availability.filter(
            starts_at__lte=starts_at, ends_at__gte=starts_at + duration
        ).exists()
        if not available:
            raise forms.ValidationError("This time is outside the teacher's available hours.")
        recent_bookings = Booking.objects.filter(
            teacher=self.teacher,
            status__in=("pending", "confirmed"),
            starts_at__lt=starts_at + duration,
        )
        if any(
            booking.starts_at + timedelta(minutes=booking.duration_minutes) > starts_at
            for booking in recent_bookings
        ):
            raise forms.ValidationError("This time overlaps an existing booking.")
        return starts_at
