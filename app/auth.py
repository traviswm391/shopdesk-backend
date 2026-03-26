"""
Supabase JWT authentication for ShopDesk AI backend.

Uses Supabase's admin auth API to verify tokens — works with both
legacy HS256 and the newer ECC signing keys automatically.

The frontend uses Supabase Auth and passes the access token as:
    Authorization: Bearer <token>
"""

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.database import supabase

security = HTTPBearer(auto_error=False)


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> str:
    """
    Verify Supabase Bearer token via the Supabase admin auth API.
    Returns the user's UUID, or raises 401.
    """
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Provide Authorization: Bearer <token>",
        )

    try:
        response = supabase.auth.get_user(credentials.credentials)
        user_id = response.user.id if response.user else None
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token: missing user ID.")

    return user_id
