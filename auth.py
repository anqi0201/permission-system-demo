"""
Authentication dependencies — session-token auth with role- and
permission-based route guards, built on FastAPI's Depends system.
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from .database import get_db
from .config import SESSION_EXPIRE_HOURS

security = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def create_session(conn, user_id: int) -> str:
    token = secrets.token_hex(32)
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=SESSION_EXPIRE_HOURS)).isoformat()
    conn.execute(
        "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
        (token, user_id, expires_at),
    )
    conn.commit()
    return token


def delete_session(conn, token: str):
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    token = credentials.credentials
    conn = get_db()
    row = conn.execute(
        """SELECT s.token, s.expires_at, u.* FROM sessions s
           JOIN users u ON s.user_id = u.id
           WHERE s.token = ? AND u.status = 'active'""",
        (token,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")

    expires_at = datetime.fromisoformat(row["expires_at"])
    if datetime.now(timezone.utc) > expires_at:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")

    return dict(row)


def require_role(*roles):
    """Dependency factory: restrict a route to a set of roles."""
    def checker(user=Depends(get_current_user)):
        if user["role"] not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user
    return checker


def require_permission(field: str):
    """Dependency factory: restrict a route by a boolean permission flag
    on the user record (e.g. perm_sales_data, perm_logs). Admin always
    passes regardless of the flag's value."""
    def checker(user=Depends(get_current_user)):
        if user["role"] == "admin":
            return user
        if not user.get(field):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this resource")
        return user
    return checker
