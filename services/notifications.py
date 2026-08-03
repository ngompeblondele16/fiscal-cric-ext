"""Notifications applicatives (panneau cloche)."""
from models import Notification


def add_notification(db, message, level='info', source='system'):
    msg = str(message).strip()
    if not msg:
        return None
    notif = Notification(message=msg, level=level, source=source, is_read=False)
    db.add(notif)
    return notif


def get_recent_notifications(db, limit=20):
    return (
        db.query(Notification)
        .order_by(Notification.created_at.desc())
        .limit(limit)
        .all()
    )


def get_unread_count(db):
    return db.query(Notification).filter(Notification.is_read.is_(False)).count()


def mark_all_read(db):
    db.query(Notification).filter(Notification.is_read.is_(False)).update(
        {Notification.is_read: True},
        synchronize_session=False,
    )
