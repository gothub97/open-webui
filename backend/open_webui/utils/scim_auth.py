import hmac
from fastapi import Request, HTTPException, status

from backend.open_webui.config import ENABLE_SCIM, SCIM_TOKEN

async def verify_scim_request(request: Request) -> bool:
    """
    FastAPI dependency to verify SCIM requests.
    Checks if SCIM is enabled and validates the Bearer token.
    """

    # Check if SCIM is enabled via app.state.config if available, otherwise direct import
    # For this structure, direct import is used as specified.
    if not ENABLE_SCIM.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="SCIM is not enabled"
        )

    # Get Authorization Header
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated: Missing Authorization header",
        )

    # Verify Scheme and Credentials Format
    scheme, _, credentials = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication scheme or missing token",
        )

    # Verify Token
    scim_token_from_config = SCIM_TOKEN.value
    
    # Ensure the token from config is a string and not empty
    if not scim_token_from_config or not isinstance(scim_token_from_config, str):
        # Log this issue for the admin, as it's a server-side misconfiguration
        # log.error("SCIM token is not configured properly on the server.") # Assuming log is available
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SCIM token is not configured on the server", # Avoid leaking too much info to client
        )

    # Securely compare the provided token with the configured token
    # Both tokens must be encoded to bytes for hmac.compare_digest
    is_valid = hmac.compare_digest(
        scim_token_from_config.encode('utf-8'), 
        credentials.encode('utf-8')
    )

    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Invalid SCIM token"
        )

    return True
