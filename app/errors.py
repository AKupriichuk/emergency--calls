class ApiError(Exception):
    def __init__(self, status_code: int, message: str, field: str | None = None):
        self.status_code = status_code
        self.message = message
        self.field = field
        super().__init__(message)
