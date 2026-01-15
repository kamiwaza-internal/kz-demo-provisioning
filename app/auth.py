import secrets
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from itsdangerous import URLSafeTimedSerializer, BadSignature
from app.config import settings

security = HTTPBasic()


def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    """
    Verify HTTP Basic Auth credentials.

    Returns:
        Username if valid

    Raises:
        HTTPException: If credentials are invalid
    """
    correct_username = secrets.compare_digest(
        credentials.username.encode("utf8"),
        settings.app_admin_user.encode("utf8")
    )
    correct_password = secrets.compare_digest(
        credentials.password.encode("utf8"),
        settings.app_admin_pass.encode("utf8")
    )

    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    return credentials.username


class CSRFProtection:
    """Simple CSRF protection using signed tokens"""

    def __init__(self):
        self.serializer = URLSafeTimedSerializer(settings.secret_key)

    def generate_token(self, session_data: str = "csrf") -> str:
        """Generate a CSRF token"""
        return self.serializer.dumps(session_data, salt="csrf-token")

    def verify_token(self, token: str, max_age: int = 3600) -> bool:
        """
        Verify a CSRF token.

        Args:
            token: Token to verify
            max_age: Maximum age in seconds (default 1 hour)

        Returns:
            True if valid, False otherwise
        """
        try:
            self.serializer.loads(token, salt="csrf-token", max_age=max_age)
            return True
        except BadSignature:
            return False
        except Exception:
            return False


csrf_protection = CSRFProtection()


async def verify_csrf_token(request: Request):
    """
    Verify CSRF token for POST/PUT/DELETE requests.

    Raises:
        HTTPException: If token is missing or invalid
    """
    if request.method in ["POST", "PUT", "DELETE"]:
        # Check form data first, then headers
        form = await request.form()
        token = form.get("csrf_token")

        if not token:
            token = request.headers.get("X-CSRF-Token")

        if not token:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CSRF token missing"
            )

        if not csrf_protection.verify_token(token):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid CSRF token"
            )
