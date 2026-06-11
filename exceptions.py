"""Unified error-handling system.

Three flavors of "not normal," all subclassing one base and sharing the same
shape {type, code, message, detail}:
  ValidationError  malformed input (NPI is not 10 digits)        -> 400
  BlockError       business rule forbids it (same NPI, diff name) -> 409
  WarningException possible issue; user can confirm and proceed   -> 200 (with warning)

Code just raises; the formatting is handled by the single unified handler in main.py.
Want to change the response format? Change the handler in one place. Add a new
error type? Add one subclass; the handler stays untouched.
"""


class BaseAppException(Exception):
    type = "error"
    code = "ERROR"
    http_status = 400

    def __init__(self, message: str, detail: dict | None = None):
        self.message = message
        self.detail = detail or {}
        super().__init__(message)

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "code": self.code,
            "message": self.message,
            "detail": self.detail,
        }


class ValidationError(BaseAppException):
    type = "validation"
    http_status = 400

    def __init__(self, message: str, code: str = "VALIDATION_ERROR", detail: dict | None = None):
        self.code = code
        super().__init__(message, detail)


class BlockError(BaseAppException):
    type = "block"
    http_status = 409

    def __init__(self, message: str, code: str = "BLOCK", detail: dict | None = None):
        self.code = code
        super().__init__(message, detail)


class WarningException(BaseAppException):
    type = "warning"
    http_status = 200      # not an error, a heads-up; the client can retry with confirm=true to skip it

    def __init__(self, message: str, code: str = "WARNING", detail: dict | None = None):
        self.code = code
        super().__init__(message, detail)
