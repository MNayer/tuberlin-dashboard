import os
import smtplib
from email.message import EmailMessage


def send_email(to: str, subject: str, body: str) -> bool:
    host = os.environ.get('SMTP_HOST', '').strip()
    sender = os.environ.get('SMTP_FROM', 'no-reply@tu-berlin.de')

    if not host:
        print(f"[mail] SMTP not configured. Would send to {to}:\n--- {subject} ---\n{body}\n---")
        return True

    port = int(os.environ.get('SMTP_PORT', '587'))
    user = os.environ.get('SMTP_USER', '').strip()
    password = os.environ.get('SMTP_PASSWORD', '')
    use_tls = os.environ.get('SMTP_USE_TLS', 'true').lower() in ('1', 'true', 'yes')

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = to
    msg.set_content(body)

    try:
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            smtp.ehlo()
            if use_tls:
                smtp.starttls()
                smtp.ehlo()
            if user:
                smtp.login(user, password)
            smtp.send_message(msg)
        return True
    except Exception as e:
        print(f"[mail] failed to send to {to}: {e}")
        return False
