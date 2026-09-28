from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import (
    clear_session_cookie,
    get_current_user,
    get_current_user_optional,
    set_session_cookie,
)
from app.core.security import hash_password, verify_password
from app.db.models import User
from app.db.session import get_db
from app.schemas.auth import (
    LocaleUpdate,
    LoginRequest,
    SetupRequest,
    StatusOut,
    UserOut,
)
from app.services.seed import SUPPORTED_LOCALES, seed_categories

router = APIRouter(tags=["auth"])

APP_VERSION = "0.3.0-M3"


@router.get("/status", response_model=StatusOut)
def get_status(
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> StatusOut:
    has_user = db.query(User).first() is not None
    return StatusOut(
        needs_setup=not has_user,
        authenticated=user is not None,
        allow_registration=settings.allow_registration,
        user=UserOut.model_validate(user) if user else None,
        default_locale=settings.default_locale,
        supported_locales=list(SUPPORTED_LOCALES),
        app_name=settings.app_name,
        version=APP_VERSION,
    )


@router.post("/setup", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def setup(payload: SetupRequest, response: Response, db: Session = Depends(get_db)) -> UserOut:
    if db.query(User).first() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="already_initialized")

    user = _create_user(db, payload)
    set_session_cookie(response, user.id)
    return UserOut.model_validate(user)


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: SetupRequest, response: Response, db: Session = Depends(get_db)) -> UserOut:
    if not settings.allow_registration:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="registration_disabled")
    if db.query(User).filter(User.username == payload.username.strip()).first() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="username_taken")
    user = _create_user(db, payload)
    set_session_cookie(response, user.id)
    return UserOut.model_validate(user)


def _create_user(db: Session, payload: SetupRequest) -> User:
    locale = payload.locale if payload.locale in SUPPORTED_LOCALES else settings.default_locale
    user = User(
        username=payload.username.strip(),
        password_hash=hash_password(payload.password),
        locale=locale,
    )
    db.add(user)
    db.flush()

    seed_categories(db, user.id)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=UserOut)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)) -> UserOut:
    user = db.query(User).filter(User.username == payload.username.strip()).first()
    # Same message for unknown user and wrong password.
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials"
        )

    user.last_login_at = dt.datetime.now(dt.timezone.utc)
    db.commit()
    db.refresh(user)

    set_session_cookie(response, user.id)
    return UserOut.model_validate(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> Response:
    clear_session_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)


@router.patch("/me/locale", response_model=UserOut)
def update_locale(
    payload: LocaleUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UserOut:
    if payload.locale not in SUPPORTED_LOCALES:
        raise HTTPException(status_code=400, detail="unsupported_locale")
    user.locale = payload.locale
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)
