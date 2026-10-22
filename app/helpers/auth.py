from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import NotFoundError, UnauthorizedError
from app.db.session import get_session
from app.models.analysis_run import AnalysisRun
from app.models.project import Project
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_access_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "role": user.role.value,
        "exp": datetime.now(UTC) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError:
        raise UnauthorizedError("Token inválido ou expirado")


def get_current_user(token: str = Depends(oauth2_scheme), session: Session = Depends(get_session)) -> User:
    payload = decode_access_token(token)
    user = session.get(User, int(payload.get("sub", 0)))
    if user is None or not user.is_active:
        raise UnauthorizedError("Usuário não encontrado ou inativo")
    return user


def get_owned_project(session: Session, project_id: int, user_id: int) -> Project:
    project = session.get(Project, project_id)
    if project is None or project.owner_id != user_id:
        raise NotFoundError("Projeto não encontrado")
    return project


def get_owned_run(session: Session, run_id: int, user_id: int) -> AnalysisRun:
    run = session.get(AnalysisRun, run_id)
    if run is None or run.user_id != user_id:
        raise NotFoundError("Execução não encontrada")
    return run
