import logging

from sqlalchemy.orm import Session

from app.core.config import settings, _INSECURE_ADMIN_DEFAULTS
from app.core.security import get_password_hash
from app.models.user import User, UserRole

_logger = logging.getLogger(__name__)


def ensure_admin_user(db: Session) -> None:
    """Create or promote the admin user.

    Skips auto-creation when ADMIN_PASSWORD is still the insecure default
    in non-development environments to avoid deploying with known credentials.
    """
    admin = db.query(User).filter(User.email == settings.admin_email).first()
    if admin:
        if admin.role != UserRole.ADMIN:
            admin.role = UserRole.ADMIN
            db.add(admin)
            db.commit()
        return

    # Don't auto-create admin with insecure defaults outside dev
    if settings.app_env != "development" and settings.admin_password in _INSECURE_ADMIN_DEFAULTS:
        _logger.warning(
            "Skipping admin auto-creation: ADMIN_PASSWORD is an insecure default. "
            "Set ADMIN_PASSWORD in .env to create the admin account."
        )
        return

    admin = User(
        email=settings.admin_email,
        full_name="System Admin",
        hashed_password=get_password_hash(settings.admin_password),
        role=UserRole.ADMIN,
    )
    db.add(admin)
    db.commit()
    _logger.info("Admin user created: %s", settings.admin_email)
