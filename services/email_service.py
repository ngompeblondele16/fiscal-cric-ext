"""Envoi d'e-mails transactionnels (OTP mot de passe oublié)."""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config import (
    ADMIN_EMAIL,
    MAIL_FROM,
    SMTP_ENABLED,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USE_TLS,
    SMTP_USER,
)

logger = logging.getLogger(__name__)


def email_configured():
    return SMTP_ENABLED and bool(SMTP_HOST and MAIL_FROM and ADMIN_EMAIL)


def send_password_reset_code(to_email, code, expires_minutes=15):
    """Envoie le code OTP à l'adresse admin. Retourne True si envoi réussi."""
    if not email_configured():
        logger.error('SMTP non configuré — impossible d envoyer le code OTP')
        return False

    subject = 'TaxStats AI — Code de réinitialisation'
    text_body = (
        f'Votre code de réinitialisation TaxStats AI est : {code}\n\n'
        f'Ce code expire dans {expires_minutes} minutes.\n'
        f'Si vous n\'avez pas demandé cette réinitialisation, ignorez ce message.\n'
    )
    html_body = f"""
    <div style="font-family:Inter,Arial,sans-serif;max-width:480px;margin:0 auto;padding:24px;">
      <h2 style="color:#1e40af;margin:0 0 12px;">TaxStats AI</h2>
      <p style="color:#444653;">Voici votre code de réinitialisation :</p>
      <p style="font-size:32px;font-weight:700;letter-spacing:8px;color:#191c1e;
                background:#f8f9fb;border-radius:12px;padding:16px;text-align:center;">
        {code}
      </p>
      <p style="color:#757684;font-size:14px;">
        Ce code expire dans <strong>{expires_minutes} minutes</strong>.
      </p>
      <p style="color:#757684;font-size:13px;">
        Si vous n'avez pas demandé cette réinitialisation, ignorez ce message.
      </p>
    </div>
    """

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = MAIL_FROM
    msg['To'] = to_email
    msg.attach(MIMEText(text_body, 'plain', 'utf-8'))
    msg.attach(MIMEText(html_body, 'html', 'utf-8'))

    try:
        if SMTP_USE_TLS:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                if SMTP_USER and SMTP_PASSWORD:
                    server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(MAIL_FROM, [to_email], msg.as_string())
        else:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as server:
                if SMTP_USER and SMTP_PASSWORD:
                    server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(MAIL_FROM, [to_email], msg.as_string())
        return True
    except Exception:
        logger.exception('Echec envoi email OTP vers %s', to_email)
        return False
