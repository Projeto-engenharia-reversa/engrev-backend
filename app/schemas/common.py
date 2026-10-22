from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Message(BaseModel):
    message: str


class Paginated[T](BaseModel):
    items: list[T]
    total: int
    page: int = 1
    size: int = 20
