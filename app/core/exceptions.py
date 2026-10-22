from fastapi import status


class AppError(Exception):
    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, message: str = "Erro de aplicação", code: str = "app_error"):
        super().__init__(message)
        self.message = message
        self.code = code


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND

    def __init__(self, message: str = "Recurso não encontrado", code: str = "not_found"):
        super().__init__(message, code)


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT

    def __init__(self, message: str = "Conflito", code: str = "conflict"):
        super().__init__(message, code)


class UnauthorizedError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED

    def __init__(self, message: str = "Não autorizado", code: str = "unauthorized"):
        super().__init__(message, code)


class UploadError(AppError):
    def __init__(self, message: str = "Arquivo inválido", code: str = "upload_error"):
        super().__init__(message, code)
