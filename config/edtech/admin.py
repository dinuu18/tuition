from django.contrib import admin
from . import models

for model in (
    models.Grade, models.EducationBoard, models.Subject, models.UserProfile,
    models.TeacherProfile, models.StudentProfile, models.Course, models.Lesson,
    models.Enrollment, models.LessonProgress, models.TeacherAvailability, models.Booking,
    models.StudyMaterial, models.Review, models.FavoriteTeacher, models.Quiz,
    models.Question, models.QuizAttempt, models.Wallet, models.TeacherEarning,
    models.WithdrawalRequest, models.Notification, models.TeacherSubject,
    models.TeacherExperience, models.TeacherAchievement, models.TeacherSkill,
    models.TeacherPortfolioItem, models.TeacherProfileView, models.TeacherEnquiry,
    models.PaymentTransaction, models.PaymentWebhookEvent,
):
    admin.site.register(model)

# Register your models here.
