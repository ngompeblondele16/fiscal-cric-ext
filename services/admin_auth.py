"""Authentification admin — compte unique, OTP reset mot de passe."""
import hashlib
import secrets
from datetime import datetime, timedelta

from werkzeug.security import check_password_hash, generate_password_hash

from config import ADMIN_EMAIL, ADMIN_PASS, ADMIN_RECOVERY_CODE, ADMIN_USER
from models import AdminAccount, PasswordResetToken
from services.email_service import send_password_reset_code

OTP_LENGTH = 6
OTP_TTL_MINUTES = 15
MAX_RESET_REQUESTS_PER_HOUR = 3


def recovery_code_configured():
    return bool((ADMIN_RECOVERY_CODE or '').strip())


def _normalize_email(value):
    return (value or '').strip().lower()


def ensure_admin_account(db):
    """Crée ou met à jour le compte admin depuis les variables d'environnement."""
    admin = db.query(AdminAccount).order_by(AdminAccount.id).first()
    email = _normalize_email(ADMIN_EMAIL) or f'{ADMIN_USER}@local.invalid'

    if admin is None:
        admin = AdminAccount(
            username=ADMIN_USER,
            email=email,
            password_hash=generate_password_hash(ADMIN_PASS),
        )
        db.add(admin)
        db.commit()
        return admin

    changed = False
    if admin.username != ADMIN_USER:
        admin.username = ADMIN_USER
        changed = True
    if _normalize_email(admin.email) != email and ADMIN_EMAIL:
        admin.email = email
        changed = True
    if changed:
        admin.updated_at = datetime.utcnow()
        db.commit()
    return admin


def get_admin_account(db):
    return db.query(AdminAccount).order_by(AdminAccount.id).first()


def verify_admin_credentials(db, username, password):
    admin = get_admin_account(db)
    if not admin:
        admin = ensure_admin_account(db)
    if (username or '').strip() != admin.username:
        return None
    if not check_password_hash(admin.password_hash, password or ''):
        return None
    return admin


def _hash_otp(code):
    return hashlib.sha256(code.encode('utf-8')).hexdigest()


def _generate_otp():
    return ''.join(secrets.choice('0123456789') for _ in range(OTP_LENGTH))


def _recent_reset_count(db, admin_id, since):
    return db.query(PasswordResetToken).filter(
        PasswordResetToken.admin_id == admin_id,
        PasswordResetToken.created_at >= since,
    ).count()


def request_password_reset(db, email_input, request_ip=None):
    """
    Demande de reset. Retourne un dict status:
    - sent: True si email parti (ou message générique affiché côté route)
    - error: code interne optionnel
    """
    admin = ensure_admin_account(db)
    email = _normalize_email(email_input)

    if not email:
        return {'ok': False, 'error': 'missing_email'}

    if email != _normalize_email(admin.email):
        # Ne pas révéler si l'email existe — comportement identique côté UI.
        return {'ok': True, 'masked': True}

    since = datetime.utcnow() - timedelta(hours=1)
    if _recent_reset_count(db, admin.id, since) >= MAX_RESET_REQUESTS_PER_HOUR:
        return {'ok': False, 'error': 'rate_limit'}

    code = _generate_otp()
    token = PasswordResetToken(
        admin_id=admin.id,
        code_hash=_hash_otp(code),
        expires_at=datetime.utcnow() + timedelta(minutes=OTP_TTL_MINUTES),
        request_ip=(request_ip or '')[:64] or None,
    )
    db.add(token)
    db.commit()

    sent = send_password_reset_code(admin.email, code, OTP_TTL_MINUTES)
    if not sent:
        db.delete(token)
        db.commit()
        return {'ok': False, 'error': 'email_failed'}

    return {'ok': True, 'token_id': token.id}


def reset_password_with_code(db, email_input, code, new_password):
    admin = get_admin_account(db)
    if not admin:
        return {'ok': False, 'error': 'no_admin'}

    if _normalize_email(email_input) != _normalize_email(admin.email):
        return {'ok': False, 'error': 'invalid'}

    if not code or len(code.strip()) != OTP_LENGTH:
        return {'ok': False, 'error': 'invalid_code'}

    if not new_password or len(new_password) < 8:
        return {'ok': False, 'error': 'weak_password'}

    now = datetime.utcnow()
    token = (
        db.query(PasswordResetToken)
        .filter(
            PasswordResetToken.admin_id == admin.id,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at >= now,
        )
        .order_by(PasswordResetToken.created_at.desc())
        .first()
    )
    if not token:
        return {'ok': False, 'error': 'expired'}

    if token.code_hash != _hash_otp(code.strip()):
        return {'ok': False, 'error': 'invalid_code'}

    admin.password_hash = generate_password_hash(new_password)
    admin.updated_at = now
    token.used_at = now

    # Invalider les autres tokens actifs
    db.query(PasswordResetToken).filter(
        PasswordResetToken.admin_id == admin.id,
        PasswordResetToken.used_at.is_(None),
        PasswordResetToken.id != token.id,
    ).update({'used_at': now}, synchronize_session=False)

    db.commit()
    return {'ok': True}


def reset_password_with_recovery_code(db, recovery_code, new_password):
    """Réinitialisation via code de secours (sans SMTP)."""
    if not recovery_code_configured():
        return {'ok': False, 'error': 'not_configured'}

    if not new_password or len(new_password) < 8:
        return {'ok': False, 'error': 'weak_password'}

    if not secrets.compare_digest(
        (recovery_code or '').strip(),
        ADMIN_RECOVERY_CODE.strip(),
    ):
        return {'ok': False, 'error': 'invalid_recovery'}

    admin = ensure_admin_account(db)
    admin.password_hash = generate_password_hash(new_password)
    admin.updated_at = datetime.utcnow()
    db.commit()
    return {'ok': True}
