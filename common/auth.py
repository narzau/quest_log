import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Union

from jose import jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

logger = logging.getLogger(__name__)

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class JWTHandler:
    """JWT token handling utilities"""
    
    def __init__(
        self, 
        secret_key: str,
        algorithm: str = "HS256",
        access_token_expire_minutes: int = 30,
        refresh_token_expire_minutes: int = 10080,  # 7 days
    ):
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.access_token_expire_minutes = access_token_expire_minutes
        self.refresh_token_expire_minutes = refresh_token_expire_minutes
    
    def create_access_token(
        self, 
        subject: Union[str, int], 
        expires_delta: Optional[timedelta] = None,
        data: Optional[Dict[str, Any]] = None
    ) -> str:
        """Create JWT access token"""
        if expires_delta is None:
            expires_delta = timedelta(minutes=self.access_token_expire_minutes)
            
        to_encode = {}
        if data:
            to_encode.update(data)
        
        expire = datetime.utcnow() + expires_delta
        to_encode.update({
            "exp": expire,
            "sub": str(subject),
            "type": "access"
        })
        
        return jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
    
    def create_refresh_token(
        self, 
        subject: Union[str, int], 
        expires_delta: Optional[timedelta] = None
    ) -> str:
        """Create JWT refresh token"""
        if expires_delta is None:
            expires_delta = timedelta(minutes=self.refresh_token_expire_minutes)
            
        expire = datetime.utcnow() + expires_delta
        to_encode = {
            "exp": expire,
            "sub": str(subject),
            "type": "refresh"
        }
        
        return jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
    
    def verify_token(self, token: str) -> Dict[str, Any]:
        """Verify JWT token"""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            return payload
        except Exception as e:
            logger.error(f"Token verification failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against hashed password"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash password"""
    return pwd_context.hash(password)


# OAuth2 scheme for FastAPI
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")


def create_auth_dependency(
    jwt_handler: JWTHandler,
    oauth2_scheme: OAuth2PasswordBearer = oauth2_scheme,
):
    """Create dependency for authentication"""
    
    async def get_current_user(token: str = Depends(oauth2_scheme)):
        """Verify access token and return current user"""
        try:
            payload = jwt_handler.verify_token(token)
            
            # Check token type
            if payload.get("type") != "access":
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token type",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            
            user_id = int(payload.get("sub"))
            if user_id is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid authentication credentials",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            
            return {
                "id": user_id,
                **{k: v for k, v in payload.items() if k not in ["exp", "sub", "type"]}
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
    
    return get_current_user