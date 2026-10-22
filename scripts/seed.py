import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.db.session import session_scope
from app.helpers.auth import hash_password
from app.models.user import User, UserRole


def seed() -> None:
    email = settings.SEED_ADMIN_EMAIL
    password = settings.SEED_ADMIN_PASSWORD
    with session_scope() as session:
        if session.query(User).filter(User.email == email).first():
            print(f"Usuário {email} já existe.")
            return
        session.add(User(email=email, password_hash=hash_password(password), role=UserRole.ADMIN))
        print(f"Usuário admin criado: {email}")


if __name__ == "__main__":
    seed()
