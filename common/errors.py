from typing import Dict, Any, Optional, Type, List
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from sqlalchemy.exc import SQLAlchemyError
import logging

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base class for application errors"""
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code: str = "server_error"
    message: str = "An unexpected error occurred"
    
    def __init__(
        self, 
        message: Optional[str] = None, 
        details: Optional[Dict[str, Any]] = None
    ):
        self.message = message or self.message
        self.details = details or {}
        super().__init__(self.message)


class NotFoundError(AppError):
    """Error raised when a resource is not found"""
    status_code = status.HTTP_404_NOT_FOUND
    error_code = "not_found"
    message = "Resource not found"


class ValidationError(AppError):
    """Error raised when input validation fails"""
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    error_code = "validation_error"
    message = "Validation error"


class AuthenticationError(AppError):
    """Error raised when authentication fails"""
    status_code = status.HTTP_401_UNAUTHORIZED
    error_code = "authentication_error"
    message = "Authentication failed"


class AuthorizationError(AppError):
    """Error raised when authorization fails"""
    status_code = status.HTTP_403_FORBIDDEN
    error_code = "authorization_error"
    message = "Not authorized to access this resource"


class ConflictError(AppError):
    """Error raised when there is a conflict"""
    status_code = status.HTTP_409_CONFLICT
    error_code = "conflict_error"
    message = "Resource conflict"


class DatabaseError(AppError):
    """Error raised when a database operation fails"""
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code = "database_error"
    message = "Database operation failed"


class ServiceError(AppError):
    """Error raised when a service operation fails"""
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code = "service_error"
    message = "Service operation failed"


class BadRequestError(AppError):
    """Error raised when a request is invalid"""
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "bad_request"
    message = "Bad request"


class BusinessError(AppError):
    """Error raised when a business rule is violated"""
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "business_error"
    message = "Business rule violated"


def register_error_handlers(app: FastAPI) -> None:
    """Register error handlers for FastAPI application"""
    
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        """Handle application errors"""
        logger.error(
            f"AppError: {exc.error_code} - {exc.message}",
            extra={"details": exc.details, "path": request.url.path}
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.error_code,
                "message": exc.message,
                **({"details": exc.details} if exc.details else {})
            }
        )
    
    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Handle validation errors"""
        errors = {}
        for error in exc.errors():
            loc = ".".join(str(x) for x in error["loc"] if x != "body")
            errors[loc] = error["msg"]
        
        logger.warning(
            "Validation error",
            extra={"errors": errors, "path": request.url.path}
        )
        
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": "validation_error",
                "message": "Validation error",
                "details": errors
            }
        )
    
    @app.exception_handler(SQLAlchemyError)
    async def sqlalchemy_error_handler(
        request: Request, exc: SQLAlchemyError
    ) -> JSONResponse:
        """Handle SQLAlchemy errors"""
        logger.error(
            f"Database error: {str(exc)}",
            exc_info=True,
            extra={"path": request.url.path}
        )
        
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "database_error",
                "message": "A database error occurred"
            }
        )
    
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        """Handle unhandled exceptions"""
        logger.error(
            f"Unhandled exception: {str(exc)}",
            exc_info=True,
            extra={"path": request.url.path}
        )
        
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "server_error",
                "message": "An unexpected error occurred"
            }
        )