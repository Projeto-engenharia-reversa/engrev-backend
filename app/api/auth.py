from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, UnauthorizedError
from app.db.session import get_session
from app.helpers.auth import create_access_token, get_current_user, hash_password, verify_password
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserPublic, UserUpdate

router = APIRouter()


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(data: RegisterRequest, session: Session = Depends(get_session)):
    if session.query(User).filter(User.email == data.email).first():
        raise ConflictError("E-mail já cadastrado")
    user = User(email=data.email, password_hash=hash_password(data.password), name=data.name)
    session.add(user)
    session.commit()
    session.refresh(user)
    return TokenResponse(access_token=create_access_token(user), user=UserPublic.model_validate(user))


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, session: Session = Depends(get_session)):
    user = session.query(User).filter(User.email == data.email).first()
    if user is None or not verify_password(data.password, user.password_hash):
        raise UnauthorizedError("Credenciais inválidas")
    return TokenResponse(access_token=create_access_token(user), user=UserPublic.model_validate(user))


@router.get("/me", response_model=UserPublic)
def me(current: User = Depends(get_current_user)):
    return current


@router.patch("/me", response_model=UserPublic)
def update_me(data: UserUpdate, current: User = Depends(get_current_user), session: Session = Depends(get_session)):
    if data.name is not None:
        current.name = data.name
    if data.password:
        current.password_hash = hash_password(data.password)
    session.add(current)
    session.commit()
    session.refresh(current)
    return current
