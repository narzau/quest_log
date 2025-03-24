from typing import Optional, Dict, Any, List
from pydantic import BaseModel

# ----- Commands -----

class CreateUserCommand(BaseModel):
    """Command to create a new user"""
    email: str
    username: str
    password: str
    role: str = "USER"
    
class UpdateUserCommand(BaseModel):
    """Command to update a user"""
    user_id: int
    email: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    
class DeleteUserCommand(BaseModel):
    """Command to delete a user"""
    user_id: int
    
class UpdateProgressionCommand(BaseModel):
    """Command to update user progression"""
    user_id: int
    level: Optional[int] = None
    experience: Optional[int] = None
    
class ChangePasswordCommand(BaseModel):
    """Command to change a user's password"""
    user_id: int
    current_password: str
    new_password: str
    
class ResetPasswordCommand(BaseModel):
    """Command to reset a user's password using a token"""
    token: str
    new_password: str
    
class RequestPasswordResetCommand(BaseModel):
    """Command to request a password reset"""
    email: str

# ----- Queries -----

class GetUserQuery(BaseModel):
    """Query to get a user by ID"""
    user_id: int
    
class GetUserByEmailQuery(BaseModel):
    """Query to get a user by email"""
    email: str
    
class GetUserByUsernameQuery(BaseModel):
    """Query to get a user by username"""
    username: str
    
class GetUsersQuery(BaseModel):
    """Query to get a list of users with filtering and pagination"""
    search: Optional[str] = None
    skip: int = 0
    limit: int = 100
    
class AuthenticateUserQuery(BaseModel):
    """Query to authenticate a user"""
    email: str
    password: str
    
class RefreshTokenQuery(BaseModel):
    """Query to refresh an access token"""
    refresh_token: str

# ----- Events -----

class UserCreatedEvent(BaseModel):
    """Event emitted when a user is created"""
    user_id: int
    email: str
    username: str
    role: str
    
class UserUpdatedEvent(BaseModel):
    """Event emitted when a user is updated"""
    user_id: int
    changes: Dict[str, Any]
    
class UserDeletedEvent(BaseModel):
    """Event emitted when a user is deleted"""
    user_id: int
    
class UserProgressionUpdatedEvent(BaseModel):
    """Event emitted when user progression is updated"""
    user_id: int
    level: Optional[int] = None
    experience: Optional[int] = None
    
class UserLoggedInEvent(BaseModel):
    """Event emitted when a user logs in"""
    user_id: int
    
class UserLoggedOutEvent(BaseModel):
    """Event emitted when a user logs out"""
    user_id: int
    
class PasswordChangedEvent(BaseModel):
    """Event emitted when a user changes their password"""
    user_id: int
    
class PasswordResetRequestedEvent(BaseModel):
    """Event emitted when a password reset is requested"""
    user_id: int
    email: str
    
class PasswordResetEvent(BaseModel):
    """Event emitted when a password is reset"""
    user_id: int 