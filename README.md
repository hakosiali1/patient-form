# Patient Form — self-contained (no EmailJS, no third-party form service)

Everything runs on your own server:
- `templates/index.html` — the form the patient/staff fills out
- `app.py` — a Flask backend that:
  1. Validates the submission
  2. Builds the PDF itself (using `reportlab`, a Python library — no external API)
  3. Emails that PDF to the patient using plain SMTP (`smtplib`, built into Python)
  4. Also streams the PDF back to the browser so staff get an instant local copy

The only thing you still need is an email account to send *from* — that's
true of any real email sending, self-hosted or not. You are not tied to
any specific provider or paid form-service; any SMTP account works
(Gmail, Outlook/Office365, your clinic's own domain mailbox, etc.).

## 1. Install

```bash
cd patient_form
python3 -m venv venv
source venv/bin/activate        # on Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Configure your SMTP account

Set these as environment variables before running the app (or put them
in a `.env` file and load it with `python-dotenv` if you prefer):

```bash
export SMTP_HOST=smtp.gmail.com
export SMTP_PORT=587
export SMTP_USER=you@yourclinic.com
export SMTP_PASS=your-app-password
export FROM_EMAIL=you@yourclinic.com
export FROM_NAME="Your Clinic Name"
export BCC_EMAIL=records@yourclinic.com   # optional — get a copy of every submission
```

### If using Gmail
Gmail blocks plain-password SMTP login. You need an **App Password**:
1. Turn on 2-Step Verification on the Google account: https://myaccount.google.com/security
2. Go to https://myaccount.google.com/apppasswords
3. Generate a password for "Mail" and use that (not your normal Gmail password) as `SMTP_PASS`.

### If using Outlook/Office365
`SMTP_HOST=smtp.office365.com`, `SMTP_PORT=587`, and your normal account
credentials (or an app password if MFA is on).

### If your clinic has its own domain mailbox
Ask whoever manages your email hosting (cPanel, Google Workspace,
Microsoft 365, etc.) for the SMTP hostname/port — the code doesn't
change, only these settings do.

## 3. Run it

```bash
python app.py
```

Open http://localhost:5000 in a browser, fill out the form, and submit.
The backend generates the PDF, emails it to the patient's address, and
also hands a copy back to the browser to download.

## 4. Deploying so it's reachable outside your machine

For real use (not just localhost), run this behind a proper WSGI server,
e.g.:

```bash
pip install gunicorn
gunicorn -w 2 -b 0.0.0.0:8000 app:app
```

...and put it behind your own domain/reverse proxy (nginx, Caddy, etc.)
with HTTPS. That part is standard web hosting, not tied to any
particular vendor.

## Notes

- Passport numbers and other patient data are transmitted to your own
  server and your own SMTP provider only — nothing goes through a
  third-party form-processing SaaS.
- Consider whether this counts as health/personal data under your
  local regulations (e.g. GDPR if handling EU patients) and make sure
  your hosting and email provider are configured accordingly (TLS is
  already enforced via `starttls()` in the code).
