"""Auth errors."""


class GoogleOAuthError(ValueError):
    """Only a fixed safe error code may cross the API boundary."""
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)
