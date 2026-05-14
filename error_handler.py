"""
Centralized error handling with logging and user-friendly messages.
"""
import json
import logging
from datetime import datetime
from typing import Optional
from enum import Enum

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='[%(asctime)s] [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler('story_generator.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


class ErrorSeverity(str, Enum):
    """Error severity levels for UI display."""
    INFO = "info"        # Informational message
    WARNING = "warning"  # Warning but can proceed
    ERROR = "error"      # Error, action failed
    CRITICAL = "critical"  # Critical error, full stop


class AppError(Exception):
    """Base application error with user-friendly message."""

    def __init__(
        self,
        message: str,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        details: Optional[str] = None,
        error_code: Optional[str] = None,
        user_action: Optional[str] = None
    ):
        self.message = message  # User-facing message
        self.severity = severity
        self.details = details  # Technical details for logs
        self.error_code = error_code or self.__class__.__name__
        self.user_action = user_action  # What user should do
        self.timestamp = datetime.now().isoformat()

        # Log the error
        self._log_error()

        super().__init__(self.message)

    def _log_error(self):
        """Log error with full details."""
        log_msg = f"{self.error_code}: {self.message}"
        if self.details:
            log_msg += f" | Details: {self.details}"

        if self.severity == ErrorSeverity.CRITICAL:
            logger.critical(log_msg)
        elif self.severity == ErrorSeverity.ERROR:
            logger.error(log_msg)
        elif self.severity == ErrorSeverity.WARNING:
            logger.warning(log_msg)
        else:
            logger.info(log_msg)

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict for API response."""
        return {
            "error": {
                "code": self.error_code,
                "message": self.message,
                "severity": self.severity,
                "details": self.details,
                "userAction": self.user_action,
                "timestamp": self.timestamp
            }
        }


class ValidationError(AppError):
    """Validation error (bad input)."""
    def __init__(self, message: str, details: Optional[str] = None):
        super().__init__(
            message=message,
            severity=ErrorSeverity.ERROR,
            details=details,
            error_code="VALIDATION_ERROR",
            user_action="Check your input and try again"
        )


class RateLimitError(AppError):
    """Rate limit exceeded."""
    def __init__(self, message: str, retry_after: Optional[int] = None):
        user_action = f"Please wait {retry_after} seconds and try again" if retry_after else "Please wait and try again"
        super().__init__(
            message=message,
            severity=ErrorSeverity.WARNING,
            error_code="RATE_LIMIT_ERROR",
            user_action=user_action
        )


class APIError(AppError):
    """External API error (Groq, Gemini, etc)."""
    def __init__(self, provider: str, message: str, status_code: Optional[int] = None):
        details = f"Provider: {provider}"
        if status_code:
            details += f" | Status: {status_code}"

        super().__init__(
            message=f"{provider} API error: {message}",
            severity=ErrorSeverity.ERROR if status_code != 429 else ErrorSeverity.WARNING,
            details=details,
            error_code="API_ERROR",
            user_action="Please try again in a moment"
        )


class DatabaseError(AppError):
    """Database operation error."""
    def __init__(self, message: str, operation: Optional[str] = None):
        details = f"Operation: {operation}" if operation else None
        super().__init__(
            message=f"Database error: {message}",
            severity=ErrorSeverity.CRITICAL,
            details=details,
            error_code="DATABASE_ERROR",
            user_action="Please contact support if this persists"
        )


class FileError(AppError):
    """File operation error."""
    def __init__(self, message: str, filename: Optional[str] = None):
        details = f"File: {filename}" if filename else None
        super().__init__(
            message=f"File error: {message}",
            severity=ErrorSeverity.ERROR,
            details=details,
            error_code="FILE_ERROR",
            user_action="Please check the file and try again"
        )


class GenerationError(AppError):
    """Generation/processing error."""
    def __init__(self, message: str, phase: Optional[str] = None, user_action: Optional[str] = None):
        details = f"Phase: {phase}" if phase else None
        super().__init__(
            message=f"Generation failed: {message}",
            severity=ErrorSeverity.ERROR,
            details=details,
            error_code="GENERATION_ERROR",
            user_action=user_action or "Please check your input and try again"
        )


def log_info(component: str, message: str, **kwargs):
    """Log informational message."""
    extra = " | " + " | ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
    logger.info(f"[{component}] {message}{extra}")


def log_warning(component: str, message: str, **kwargs):
    """Log warning message."""
    extra = " | " + " | ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
    logger.warning(f"[{component}] {message}{extra}")


def log_error(component: str, message: str, exception: Optional[Exception] = None, **kwargs):
    """Log error message with optional exception."""
    extra = " | " + " | ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
    if exception:
        logger.error(f"[{component}] {message}{extra}", exc_info=exception)
    else:
        logger.error(f"[{component}] {message}{extra}")


def log_debug(component: str, message: str, **kwargs):
    """Log debug message."""
    extra = " | " + " | ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
    logger.debug(f"[{component}] {message}{extra}")


def create_error_response(error: AppError, status_code: int = 400) -> tuple[dict, int]:
    """Create FastAPI error response from AppError."""
    return error.to_dict(), status_code


def format_error_for_sse(error: AppError) -> str:
    """Format error for Server-Sent Events stream."""
    return json.dumps({
        "type": "error",
        "error": {
            "code": error.error_code,
            "message": error.message,
            "severity": error.severity,
            "userAction": error.user_action,
            "details": error.details,
            "timestamp": error.timestamp
        }
    })
