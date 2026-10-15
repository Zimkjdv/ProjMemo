"""Transport-independent application errors, mapped to HTTP at the boundary."""


class ApplicationError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class FieldValidationError(ApplicationError):
    def __init__(self, fields: dict[str, str]):
        super().__init__(400, next(iter(fields.values())))
        self.fields = fields
