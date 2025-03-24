import logging
from typing import Optional, List, Dict, Any, Callable

from fastapi import Depends, HTTPException, status, Path, Query, Body, Header
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from common.service import VersionedAPIRouter
from common.auth import JWTHandler, oauth2_scheme
from common.errors import NotFoundError, AuthenticationError, ValidationError, ConflictError
from common.documentation import ApiExample

from schemas import (
    UserCreate, 
    UserUpdate, 
    UserResponse, 
    UserLogin, 
    UserList,
    TokenResponse, 
    TokenRefresh,
    UserProgressionUpdate,
    PasswordChange,
    PasswordReset,
    PasswordResetConfirm
)
from service import UserService
from models import UserRole
from config import settings

logger = logging.getLogger(__name__)

# JWT handler
jwt_handler = JWTHandler(
    settings.JWT_SECRET,
    settings.JWT_ALGORITHM,
    settings.ACCESS_TOKEN_EXPIRE_MINUTES,
    settings.REFRESH_TOKEN_EXPIRE_MINUTES
)

def setup_routes(router: VersionedAPIRouter, get_user_service: Callable[[], UserService]):
    """Set up routes for the user service"""
    
    # Authentication dependency
    async def get_current_user(
        token: str = Depends(oauth2_scheme),
        user_service: UserService = Depends(get_user_service),
    ) -> Dict[str, Any]:
        """Verify token and return current user"""
        try:
            # Decode the JWT token
            payload = jwt_handler.decode_token(token)
            
            # Get the user ID from the token
            user_id: int = payload.get("sub")
            if user_id is None:
                raise AuthenticationError("Invalid authentication token")
            
            # Get the user from the database
            user = await user_service.get_user(user_id)
            
            # Return the user as a dictionary
            return {
                "id": user.id,
                "email": user.email,
                "username": user.username,
                "role": user.role,
                "is_active": user.is_active,
                "level": user.level,
                "experience": user.experience,
                "created_at": user.created_at,
                "updated_at": user.updated_at
            }
        except (AuthenticationError, NotFoundError) as e:
            # Handle exceptions
            logger.warning(f"Authentication failed: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except Exception as e:
            # Handle unexpected exceptions
            logger.error(f"Unexpected error during authentication: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected error occurred",
            )

    # Admin role check dependency
    async def admin_required(
        current_user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        """Check if the current user has admin role"""
        if current_user["role"] != UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user

    # Authentication endpoints
    @router.post("/auth/token", tags=["authentication"], 
                 summary="Login and get access token", 
                 description="Authenticate user and return access and refresh tokens")
    async def login_for_access_token(
        form_data: OAuth2PasswordRequestForm = Depends(),
        user_service: UserService = Depends(get_user_service),
    ):
        """Authenticate user and return JWT tokens"""
        try:
            # Authenticate the user
            user, access_token, refresh_token = await user_service.authenticate_user(
                form_data.username, form_data.password
            )
            
            # Return the tokens
            return {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "bearer",
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "username": user.username,
                    "role": user.role,
                    "is_active": user.is_active,
                    "level": user.level,
                    "experience": user.experience,
                    "created_at": user.created_at,
                    "updated_at": user.updated_at
                }
            }
        except AuthenticationError as e:
            # Handle authentication errors
            logger.warning(f"Login failed: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except Exception as e:
            # Handle unexpected errors
            logger.error(f"Unexpected error during login: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected error occurred",
            )

    @router.post("/auth/refresh", tags=["authentication"],
                 summary="Refresh access token",
                 description="Use refresh token to get a new access token")
    async def refresh_access_token(
        refresh_data: TokenRefresh,
        user_service: UserService = Depends(get_user_service),
    ):
        """Refresh access token using refresh token"""
        try:
            # Refresh the token
            access_token, new_refresh_token = await user_service.refresh_token(
                refresh_data.refresh_token
            )
            
            # Decode the access token to get user data
            payload = jwt_handler.decode_token(access_token)
            user_id = payload.get("sub")
            
            # Get the user
            user = await user_service.get_user(user_id)
            
            # Return new tokens
            return {
                "access_token": access_token,
                "refresh_token": new_refresh_token,
                "token_type": "bearer",
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "username": user.username,
                    "role": user.role,
                    "is_active": user.is_active,
                    "level": user.level,
                    "experience": user.experience,
                    "created_at": user.created_at,
                    "updated_at": user.updated_at
                }
            }
        except AuthenticationError as e:
            logger.warning(f"Token refresh failed: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except Exception as e:
            logger.error(f"Unexpected error during token refresh: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected error occurred",
            )

    @router.post("/auth/logout", tags=["authentication"],
                 summary="Logout user",
                 description="Invalidate the refresh token")
    async def logout(
        refresh_data: TokenRefresh,
        user_service: UserService = Depends(get_user_service),
    ):
        """Logout by invalidating refresh token"""
        try:
            # Invalidate the refresh token
            success = await user_service.logout(refresh_data.refresh_token)
            
            if success:
                return {"message": "Successfully logged out"}
            else:
                return {"message": "Logout failed"}
        except Exception as e:
            logger.error(f"Error during logout: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected error occurred",
            )

    # User management endpoints
    @router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED,
                tags=["users"], 
                summary="Create new user",
                description="Register a new user account")
    async def create_user(
        user_data: UserCreate,
        user_service: UserService = Depends(get_user_service),
    ):
        """Create a new user"""
        try:
            # Create the user
            user = await user_service.create_user(user_data)
            
            # Return the user
            return {
                "id": user.id,
                "email": user.email,
                "username": user.username,
                "role": user.role,
                "is_active": user.is_active,
                "level": user.level,
                "experience": user.experience,
                "created_at": user.created_at,
                "updated_at": user.updated_at
            }
        except ConflictError as e:
            logger.warning(f"User creation failed: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(e),
            )
        except ValidationError as e:
            logger.warning(f"User creation failed: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )
        except Exception as e:
            import traceback
            error_traceback = traceback.format_exc()
            logger.error(f"Unexpected error during user creation: {str(e)}\nTraceback: {error_traceback}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An unexpected error occurred: {str(e)}",
            )

    @router.get("/me", response_model=UserResponse, tags=["users"],
               summary="Get current user profile",
               description="Get the profile of the currently authenticated user")
    async def get_current_user_profile(
        current_user: Dict[str, Any] = Depends(get_current_user),
        user_service: UserService = Depends(get_user_service),
    ):
        """Get current user profile"""
        try:
            # Get the user from the database (to ensure we have the latest data)
            user = await user_service.get_user(current_user["id"])
            
            # Return the user
            return {
                "id": user.id,
                "email": user.email,
                "username": user.username,
                "role": user.role,
                "is_active": user.is_active,
                "level": user.level,
                "experience": user.experience,
                "created_at": user.created_at,
                "updated_at": user.updated_at
            }
        except NotFoundError as e:
            logger.warning(f"User not found: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )
        except Exception as e:
            logger.error(f"Unexpected error retrieving user profile: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected error occurred",
            )

    @router.put("/me", response_model=UserResponse, tags=["users"],
               summary="Update current user profile",
               description="Update the profile of the currently authenticated user")
    async def update_current_user_profile(
        user_data: UserUpdate,
        current_user: Dict[str, Any] = Depends(get_current_user),
        user_service: UserService = Depends(get_user_service),
    ):
        """Update current user profile"""
        try:
            # Update the user
            updated_user = await user_service.update_user(current_user["id"], user_data)
            
            # Return the updated user
            return {
                "id": updated_user.id,
                "email": updated_user.email,
                "username": updated_user.username,
                "role": updated_user.role,
                "is_active": updated_user.is_active,
                "level": updated_user.level,
                "experience": updated_user.experience,
                "created_at": updated_user.created_at,
                "updated_at": updated_user.updated_at
            }
        except ConflictError as e:
            logger.warning(f"User update failed: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(e),
            )
        except ValidationError as e:
            logger.warning(f"User update failed: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )
        except NotFoundError as e:
            logger.warning(f"User not found: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )
        except Exception as e:
            logger.error(f"Unexpected error updating user profile: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected error occurred",
            )

    @router.post("/me/password", tags=["users"],
                summary="Change current user password",
                description="Change the password of the currently authenticated user")
    async def change_current_user_password(
        password_data: PasswordChange,
        current_user: Dict[str, Any] = Depends(get_current_user),
        user_service: UserService = Depends(get_user_service),
    ):
        """Change current user password"""
        try:
            # Change the password
            success = await user_service.change_password(
                current_user["id"],
                password_data.current_password,
                password_data.new_password,
            )
            
            if success:
                return {"message": "Password successfully changed"}
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Password change failed",
                )
        except AuthenticationError as e:
            logger.warning(f"Password change failed: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Current password is incorrect",
            )
        except ValidationError as e:
            logger.warning(f"Password change failed: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )
        except Exception as e:
            logger.error(f"Unexpected error during password change: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected error occurred",
            )

    @router.post("/password-reset", tags=["users"],
                summary="Request password reset",
                description="Request a password reset token")
    async def request_password_reset(
        reset_data: PasswordReset,
        user_service: UserService = Depends(get_user_service),
    ):
        """Request password reset"""
        try:
            # Request password reset
            token = await user_service.request_password_reset(reset_data.email)
            
            # In a real application, we would send an email with the token
            # For testing purposes, we'll return it directly
            return {"message": "Password reset requested", "token": token}
        except NotFoundError as e:
            # For security reasons, don't reveal if the email exists or not
            logger.info(f"Password reset requested for non-existent email: {reset_data.email}")
            return {"message": "If your email is registered, a reset link will be sent"}
        except Exception as e:
            logger.error(f"Unexpected error during password reset request: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected error occurred",
            )

    @router.post("/password-reset/confirm", tags=["users"],
                summary="Confirm password reset",
                description="Reset password using the token received via email")
    async def confirm_password_reset(
        reset_data: PasswordResetConfirm,
        user_service: UserService = Depends(get_user_service),
    ):
        """Confirm password reset"""
        try:
            # Reset the password
            success = await user_service.reset_password(
                reset_data.token,
                reset_data.new_password,
            )
            
            if success:
                return {"message": "Password successfully reset"}
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Password reset failed",
                )
        except AuthenticationError as e:
            logger.warning(f"Password reset failed: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )
        except ValidationError as e:
            logger.warning(f"Password reset failed: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )
        except Exception as e:
            logger.error(f"Unexpected error during password reset: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected error occurred",
            )

    @router.put("/me/progression", response_model=UserResponse, tags=["users"],
              summary="Update user progression",
              description="Update the current user's level and experience points")
    async def update_current_user_progression(
        progression_data: UserProgressionUpdate,
        current_user: Dict[str, Any] = Depends(get_current_user),
        user_service: UserService = Depends(get_user_service),
    ):
        """Update current user progression"""
        try:
            # Update progression
            updated_user = await user_service.update_progression(
                current_user["id"],
                progression_data,
            )
            
            # Return the updated user
            return {
                "id": updated_user.id,
                "email": updated_user.email,
                "username": updated_user.username,
                "role": updated_user.role,
                "is_active": updated_user.is_active,
                "level": updated_user.level,
                "experience": updated_user.experience,
                "created_at": updated_user.created_at,
                "updated_at": updated_user.updated_at
            }
        except NotFoundError as e:
            logger.warning(f"User not found: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )
        except ValidationError as e:
            logger.warning(f"Progression update failed: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )
        except Exception as e:
            logger.error(f"Unexpected error updating user progression: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected error occurred",
            )

    # Admin endpoints
    @router.get("/", response_model=UserList, 
              dependencies=[Depends(admin_required)],
              tags=["admin"],
              summary="List all users",
              description="Admin only: List all users with pagination and search")
    async def get_users(
        search: Optional[str] = None,
        skip: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=1000),
        user_service: UserService = Depends(get_user_service),
    ):
        """Get a list of users (admin only)"""
        try:
            # Get users with pagination
            users_list = await user_service.get_users(search, skip, limit)
            
            # Return the list
            return users_list
        except Exception as e:
            logger.error(f"Unexpected error retrieving users list: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected error occurred",
            )

    @router.get("/{user_id}", response_model=UserResponse, 
              dependencies=[Depends(admin_required)],
              tags=["admin"],
              summary="Get user by ID",
              description="Admin only: Get a specific user by ID")
    async def get_user(
        user_id: int = Path(..., ge=1),
        user_service: UserService = Depends(get_user_service),
    ):
        """Get a user by ID (admin only)"""
        try:
            # Get the user
            user = await user_service.get_user(user_id)
            
            # Return the user
            return {
                "id": user.id,
                "email": user.email,
                "username": user.username,
                "role": user.role,
                "is_active": user.is_active,
                "level": user.level,
                "experience": user.experience,
                "created_at": user.created_at,
                "updated_at": user.updated_at
            }
        except NotFoundError as e:
            logger.warning(f"User not found: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )
        except Exception as e:
            logger.error(f"Unexpected error retrieving user: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected error occurred",
            )

    @router.put("/{user_id}", response_model=UserResponse, 
              dependencies=[Depends(admin_required)],
              tags=["admin"],
              summary="Update user by ID",
              description="Admin only: Update a specific user by ID")
    async def update_user(
        user_data: UserUpdate,
        user_id: int = Path(..., ge=1),
        user_service: UserService = Depends(get_user_service),
    ):
        """Update a user by ID (admin only)"""
        try:
            # Update the user
            updated_user = await user_service.update_user(user_id, user_data)
            
            # Return the updated user
            return {
                "id": updated_user.id,
                "email": updated_user.email,
                "username": updated_user.username,
                "role": updated_user.role,
                "is_active": updated_user.is_active,
                "level": updated_user.level,
                "experience": updated_user.experience,
                "created_at": updated_user.created_at,
                "updated_at": updated_user.updated_at
            }
        except ConflictError as e:
            logger.warning(f"User update failed: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(e),
            )
        except ValidationError as e:
            logger.warning(f"User update failed: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )
        except NotFoundError as e:
            logger.warning(f"User not found: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )
        except Exception as e:
            logger.error(f"Unexpected error updating user: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected error occurred",
            )

    @router.delete("/{user_id}", 
                dependencies=[Depends(admin_required)],
                tags=["admin"],
                summary="Delete user by ID",
                description="Admin only: Delete a specific user by ID")
    async def delete_user(
        user_id: int = Path(..., ge=1),
        user_service: UserService = Depends(get_user_service),
    ):
        """Delete a user by ID (admin only)"""
        try:
            # Delete the user
            success = await user_service.delete_user(user_id)
            
            if success:
                return {"message": f"User {user_id} successfully deleted"}
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="User deletion failed",
                )
        except NotFoundError as e:
            logger.warning(f"User not found: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )
        except Exception as e:
            logger.error(f"Unexpected error deleting user: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected error occurred",
            )