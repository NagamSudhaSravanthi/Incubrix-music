"""One error type for the whole service. The API turns it into {"error": {code, message, retryable, details}}."""


class EngineError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False, details: dict | None = None, http_status: int = 422):
        super().__init__(message)
        self.code, self.message, self.retryable = code, message, retryable
        self.details, self.http_status = details or {}, http_status

    def to_dict(self):
        return {"error": {"code": self.code, "message": self.message, "retryable": self.retryable, "details": self.details}}
