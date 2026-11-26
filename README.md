# Tuition.com EdTech Platform

Tuition.com is a Django 4.2 educational marketplace for students and teachers.

## PowerShell setup

```powershell
cd C:\Users\ADMIN\Desktop\dinuworld
python -m pip install django pillow
python manage.py makemigrations
python manage.py migrate
python manage.py seed_demo
python manage.py createsuperuser
python manage.py runserver
```

Open `http://127.0.0.1:8000/`.

Demo accounts use `fiction_student_1` or `fiction_teacher_1` with password `Demo12345!`.

The demo-data command is for local development only. Do not run `seed_demo` against a production database.

## Teacher enquiries, materials, and bookings

Teachers can read submitted enquiries from the dashboard inbox. Enquiries and demo-booking requests create in-app notifications; email delivery uses Django's configured email backend. The default local backend prints email to the console. For SMTP, set `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, and `DEFAULT_FROM_EMAIL` in the environment.

Teachers can publish study materials as either an uploaded file (up to 25 MB) or an external URL. Students can browse active materials from the Study Materials page. Demo requests are accepted only for future times inside a teacher's saved availability, and overlapping pending or confirmed sessions are rejected.

## Course payments (Razorpay)

Paid course enrollment uses Razorpay Checkout and is disabled until credentials are configured. Start with Razorpay **test-mode** credentials; do not put secrets in source code:

```powershell
$env:RAZORPAY_KEY_ID = "rzp_test_..."
$env:RAZORPAY_KEY_SECRET = "..."
$env:RAZORPAY_WEBHOOK_SECRET = "..."
python manage.py migrate
python manage.py runserver
```

In the Razorpay dashboard, configure a webhook for `payment.captured` at `https://<your-domain>/payments/razorpay/webhook/` using the same webhook secret. Keep live credentials and webhook configuration in the deployment environment. Course access is granted only after server-side signature verification and confirmation that Razorpay reports the payment as captured. Free courses do not require payment credentials.

Run the app tests with:

```powershell
python manage.py test config.edtech.tests
```

## Included

- Student and teacher registration
- Role-based dashboards
- Advanced tutor search and combined filters
- Subject and course pages
- Course enrollment
- Free demo booking
- Favorite teachers
- Study-material library
- Teacher professional profiles with subject specialties, career history, certifications, skills, and portfolio
- Shareable public teacher pages with student reviews and teaching enquiries
- Teacher enquiry inbox with in-app and email notifications
- Teacher-managed study materials and availability windows
- Availability-checked free demo requests with overlap protection
- Razorpay course checkout with captured-payment verification and idempotent webhooks
- Teacher dashboard metrics for profile views, enquiries, student connections, and profile completion
- Profile editing and image uploads
- Django admin management
- Fictional demo data command
- Responsive premium light/dark theme
