from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


from app import models  # noqa: F401
