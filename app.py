"""
Patient Form Backend
=====================
Renders the patient form, generates a PDF from the submission on the
server, and emails that PDF to the patient — all with plain Python.
No third-party form/email services (EmailJS, etc.) are used.

You only need SMTP credentials for an email account you control
(Gmail with an App Password, Outlook, your own domain's mail server,
a transactional SMTP relay you already pay for, etc.). Fill those in
via environment variables — see config.py / README.

Run:
    pip install -r requirements.txt
    export SMTP_HOST=smtp.gmail.com
    export SMTP_PORT=587
    export SMTP_USER=you@yourclinic.com
    export SMTP_PASS=your-app-password
    export FROM_EMAIL=you@yourclinic.com
    export FROM_NAME="Your Clinic Name"
    python app.py
"""

import io
import os
import base64
import requests
from dotenv import load_dotenv
load_dotenv()
from datetime import datetime, timezone

from flask import Flask, render_template, request, jsonify
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Flowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

app = Flask(__name__)

# ---------------------------------------------------------------------
# Configuration (read from environment variables — nothing hardcoded)
# ---------------------------------------------------------------------
# Resend (https://resend.com) sends email over their HTTPS API instead
# of raw SMTP — this is what lets it work on Render's free tier, which
# blocks outbound traffic on SMTP ports 25/465/587.
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
FROM_EMAIL = os.environ.get("FROM_EMAIL", "onboarding@resend.dev")
FROM_NAME = os.environ.get("FROM_NAME", "Patient Coordination")
# Optional: also BCC every submission to your own clinic inbox
BCC_EMAIL = os.environ.get("BCC_EMAIL", "")

REQUIRED_FIELDS = [
    "name", "passport", "email", "age", "height", "weight",
    "country", "arrival_code", "departure_code", "treatments",
    "op_types", "arr_date", "op_date", "dep_date",
    "currency", "package_amount",
]

# Colors pulled straight from the HTML form's CSS so the PDF matches it
NAVY = colors.HexColor("#0d1f3c")
DARK_RED = colors.HexColor("#8b0000")
ACCENT_RED = colors.HexColor("#c0392b")
BORDER = colors.HexColor("#c5cdd8")
LABEL_COLOR = colors.HexColor("#444444")
VALUE_COLOR = colors.HexColor("#222222")
READONLY_BG = colors.HexColor("#f4f6f9")
READONLY_TEXT = colors.HexColor("#555555")


# ---------------------------------------------------------------------
# Gradient bar flowable — reproduces the form's
#   linear-gradient(135deg, #0d1f3c 0%, #8b0000 100%)
# header / section-divider look, since reportlab has no native
# gradient-fill flowable.
# ---------------------------------------------------------------------
def _interp(c1, c2, t):
    return colors.Color(
        c1.red + (c2.red - c1.red) * t,
        c1.green + (c2.green - c1.green) * t,
        c1.blue + (c2.blue - c1.blue) * t,
    )


class GradientBar(Flowable):
    def __init__(self, width, height, text, font_size=13,
                 left_pad=10, bottom_border=None):
        Flowable.__init__(self)
        self.width = width
        self.height = height
        self.text = text
        self.font_size = font_size
        self.left_pad = left_pad
        # bottom_border = (color, thickness) or None
        self.bottom_border = bottom_border

    def wrap(self, availWidth, availHeight):
        return (self.width, self.height)

    def draw(self):
        c = self.canv
        steps = 80
        seg_w = self.width / steps
        border_h = self.bottom_border[1] if self.bottom_border else 0
        for i in range(steps):
            t = i / (steps - 1)
            c.setFillColor(_interp(NAVY, DARK_RED, t))
            c.rect(i * seg_w, border_h, seg_w + 0.6, self.height - border_h,
                   fill=1, stroke=0)
        if self.bottom_border:
            bcolor, bthick = self.bottom_border
            c.setFillColor(bcolor)
            c.rect(0, 0, self.width, bthick, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", self.font_size)
        c.drawString(self.left_pad, self.height / 2 - self.font_size / 2.8, self.text)


# ---------------------------------------------------------------------
# PDF generation
# ---------------------------------------------------------------------
def build_pdf(data: dict) -> bytes:
    buf = io.BytesIO()
    W = 180 * mm
    HALF = (W - 6) / 2
    THIRD = (W - 4) / 3

    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=15 * mm, bottomMargin=15 * mm,
        leftMargin=15 * mm, rightMargin=15 * mm,
    )
    styles = getSampleStyleSheet()

    label_style = ParagraphStyle(
        "Label", parent=styles["Normal"],
        fontSize=7, fontName="Helvetica-Bold", textColor=LABEL_COLOR,
        spaceBefore=0, spaceAfter=3,
    )
    value_style = ParagraphStyle(
        "Value", parent=styles["Normal"],
        fontSize=9, fontName="Helvetica", textColor=VALUE_COLOR,
    )
    readonly_value_style = ParagraphStyle(
        "ReadonlyValue", parent=value_style, textColor=READONLY_TEXT,
    )

    PAD = [
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]

    def section_bar(title):
        return GradientBar(W, 20, title.upper(), font_size=9, left_pad=8)

    def field(label, value, width, readonly=False):
        val = str(value).strip() if value else ""
        v_style = readonly_value_style if readonly else value_style
        vbox = Table([[Paragraph(val, v_style)]], colWidths=[width])
        vbox.setStyle(TableStyle([
            *PAD,
            ("BOX",           (0, 0), (-1, -1), 1, BORDER),
            ("BACKGROUND",    (0, 0), (-1, -1), READONLY_BG if readonly else colors.white),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        wrap = Table([[Paragraph(label.upper(), label_style)], [vbox]], colWidths=[width])
        wrap.setStyle(TableStyle(PAD))
        return wrap

    def row2(pairs):
        # pairs: list of (label, value) or (label, value, readonly_bool)
        cells = [field(p[0], p[1], HALF, p[2] if len(p) == 3 else False) for p in pairs]
        t = Table([cells], colWidths=[HALF, HALF], spaceBefore=5)
        t.setStyle(TableStyle([*PAD, ("LEFTPADDING", (1, 0), (1, 0), 6)]))
        return t

    def row3(triples):
        cells = [field(p[0], p[1], THIRD, p[2] if len(p) == 3 else False) for p in triples]
        t = Table([cells], colWidths=[THIRD, THIRD, THIRD], spaceBefore=5)
        t.setStyle(TableStyle([*PAD,
            ("LEFTPADDING", (1, 0), (1, 0), 6),
            ("LEFTPADDING", (2, 0), (2, 0), 6),
        ]))
        return t

    def row1(label, value):
        t = Table([[field(label, value, W)]], colWidths=[W], spaceBefore=5)
        t.setStyle(TableStyle(PAD))
        return t

    # Header bar — same navy→red gradient with the red accent line under it
    header = GradientBar(W, 34, "Patient Information Form", font_size=15,
                          left_pad=12, bottom_border=(ACCENT_RED, 3))

    currency = data.get("currency", "")
    elements = [
        header,
        Spacer(1, 4 * mm),
        section_bar("Patient Info"),
        Spacer(1, 1 * mm),
        row2([("Patient's Name",           data.get("name")),
              ("Passport No",              data.get("passport"))]),
        row2([("Patient's Email",          data.get("email")),
              ("Patient's Age",            data.get("age"))]),
        row3([("Height (cm)",              data.get("height")),
              ("Weight (kg)",              data.get("weight")),
              ("Country",                  data.get("country"))]),
        Spacer(1, 4 * mm),
        section_bar("Flight Info"),
        Spacer(1, 1 * mm),
        row2([("Flight Arrival Code",      data.get("arrival_code")),
              ("Flight Departure Code",    data.get("departure_code"))]),
        row3([("ARR Date",                 data.get("arr_date")),
              ("OP Date",                  data.get("op_date")),
              ("DEP Date",                 data.get("dep_date"))]),
        row1("Flight Note",                data.get("flight_note")),
        Spacer(1, 4 * mm),
        section_bar("Treatment Info"),
        Spacer(1, 1 * mm),
        row2([("Type of Treatments (Ctrl+Click for Multiple)", data.get("treatments")),
              ("Diagnostic No",            data.get("diagnostic"))]),
        row1("OP Types (Comma-Separated)", data.get("op_types")),
        Spacer(1, 4 * mm),
        section_bar("Financial Info"),
        Spacer(1, 1 * mm),
        row2([("Currency",                 currency),
              ("Note for Accommodation",   data.get("accommodation_note"))]),
        row3([("Package Amount",           f"{data.get('package_amount', '0')} {currency}"),
              ("Paid Amount",              f"{data.get('paid_amount', '0')} {currency}"),
              ("Remaining Amount",         f"{data.get('remaining_amount', '0')} {currency}", True)]),
    ]

    doc.build(elements)
    return buf.getvalue()


# ---------------------------------------------------------------------
# Email sending via Resend's HTTPS API (not raw SMTP)
# ---------------------------------------------------------------------
RESEND_ENDPOINT = "https://api.resend.com/emails"


def send_email_with_pdf(to_email: str, patient_name: str, pdf_bytes: bytes):
    if not RESEND_API_KEY:
        raise RuntimeError(
            "RESEND_API_KEY is not configured. Set it as an environment "
            "variable before sending email (see resend.com/api-keys)."
        )

    safe_name = "".join(c for c in patient_name if c.isalnum() or c in " _-").strip() or "patient"
    pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")

    payload = {
        "from": f"{FROM_NAME} <{FROM_EMAIL}>",
        "to": [to_email],
        "subject": f"Your Treatment Information — {patient_name}",
        "text": (
            f"Dear {patient_name},\n\n"
            "Please find attached your treatment information document.\n\n"
            "If any of the details are incorrect, please reply to this email "
            "and let us know.\n\n"
            f"Best regards,\n{FROM_NAME}"
        ),
        "attachments": [
            {"filename": f"patient_{safe_name}.pdf", "content": pdf_b64}
        ],
    }
    if BCC_EMAIL:
        payload["bcc"] = [BCC_EMAIL]

    resp = requests.post(
        RESEND_ENDPOINT,
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=15,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Resend API error {resp.status_code}: {resp.text}")


# ---------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/submit", methods=["POST"])
def submit():
    form = request.form
    treatments = request.form.getlist("treatments")  # multi-select

    missing = [f for f in REQUIRED_FIELDS if f != "treatments" and not form.get(f, "").strip()]
    if not treatments:
        missing.append("treatments")
    if missing:
        return jsonify({"error": f"Missing required field(s): {', '.join(missing)}"}), 400

    try:
        package = float(form.get("package_amount") or 0)
        paid = float(form.get("paid_amount") or 0)
        if package != package or paid != paid:
            raise ValueError
    except ValueError:
        return jsonify({"error": "Invalid numeric value for amount fields."}), 400

    data = {
        "name": form.get("name", "").strip(),
        "passport": form.get("passport", "").strip(),
        "email": form.get("email", "").strip(),
        "age": form.get("age", "").strip(),
        "height": form.get("height", "").strip(),
        "weight": form.get("weight", "").strip(),
        "country": form.get("country", "").strip(),
        "arrival_code": form.get("arrival_code", "").strip(),
        "departure_code": form.get("departure_code", "").strip(),
        "treatments": ", ".join(treatments),
        "diagnostic": form.get("diagnostic", "").strip(),
        "op_types": form.get("op_types", "").strip(),
        "arr_date": form.get("arr_date", "").strip(),
        "op_date": form.get("op_date", "").strip(),
        "dep_date": form.get("dep_date", "").strip(),
        "flight_note": form.get("flight_note", "").strip(),
        "currency": form.get("currency", "").strip(),
        "package_amount": form.get("package_amount", "0").strip(),
        "paid_amount": form.get("paid_amount", "0").strip() or "0",
        "remaining_amount": f"{package - paid:.2f}",
        "accommodation_note": form.get("accommodation_note", "").strip(),
        "submitted_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }

    try:
        pdf_bytes = build_pdf(data)
    except Exception as exc:
        return jsonify({"error": f"Could not generate PDF: {exc}"}), 500

    try:
        send_email_with_pdf(data["email"], data["name"], pdf_bytes)
    except Exception as exc:
        return jsonify({"error": f"PDF was created but the email failed to send: {exc}"}), 502

    return jsonify({"success": "Email sent to patient successfully."})


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true", port=5000)
