import uuid
import logging
from typing import Dict

from fastapi import HTTPException, Request, Response, status
from starlette.responses import RedirectResponse
from onelogin.saml2.auth import OneLogin_Saml2_Auth

from open_webui.models.auths import Auths
from open_webui.models.users import Users
from open_webui.config import (
    DEFAULT_USER_ROLE,
    JWT_EXPIRES_IN,
    ENABLE_SAML,
    SAML_ENTITY_ID,
    SAML_CALLBACK_URL,
    SAML_IDP_ENTITY_ID,
    SAML_IDP_SSO_URL,
    SAML_IDP_CERT,
    SAML_SP_CERT,
    SAML_SP_KEY,
)
from open_webui.utils.auth import get_password_hash, create_token
from open_webui.utils.misc import parse_duration
from open_webui.env import WEBUI_AUTH_COOKIE_SAME_SITE, WEBUI_AUTH_COOKIE_SECURE

log = logging.getLogger(__name__)


class SAMLManager:
    def __init__(self, app):
        self.app = app

    def _saml_settings(self) -> Dict:
        return {
            "strict": True,
            "debug": False,
            "sp": {
                "entityId": SAML_ENTITY_ID.value,
                "assertionConsumerService": {
                    "url": SAML_CALLBACK_URL.value,
                    "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
                },
                "x509cert": SAML_SP_CERT.value,
                "privateKey": SAML_SP_KEY.value,
            },
            "idp": {
                "entityId": SAML_IDP_ENTITY_ID.value,
                "singleSignOnService": {
                    "url": SAML_IDP_SSO_URL.value,
                    "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
                },
                "x509cert": SAML_IDP_CERT.value,
            },
        }

    async def _prepare_request(self, request: Request) -> Dict:
        post_data = {}
        if request.method == "POST":
            form = await request.form()
            post_data = dict(form)
        return {
            "https": "on" if request.url.scheme == "https" else "off",
            "http_host": request.url.hostname,
            "server_port": request.url.port
            or (443 if request.url.scheme == "https" else 80),
            "script_name": request.url.path,
            "get_data": dict(request.query_params),
            "post_data": post_data,
        }

    async def handle_login(self, request: Request) -> RedirectResponse:
        if not ENABLE_SAML.value:
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        auth = OneLogin_Saml2_Auth(
            await self._prepare_request(request), self._saml_settings()
        )
        login_url = auth.login(return_to=None, stay=True)
        return RedirectResponse(login_url)

    async def handle_acs(self, request: Request, response: Response):
        if not ENABLE_SAML.value:
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        auth = OneLogin_Saml2_Auth(
            await self._prepare_request(request), self._saml_settings()
        )
        auth.process_response()
        errors = auth.get_errors()
        if errors:
            log.error(f"SAML errors: {errors}")
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid SAML response")

        if not auth.is_authenticated():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Authentication failed")

        email = auth.get_nameid()
        if not email:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Email not provided")

        email = email.lower()
        user = Users.get_user_by_email(email)
        if not user:
            role = "admin" if Users.get_num_users() == 0 else DEFAULT_USER_ROLE
            user = Auths.insert_new_auth(
                email=email,
                password=get_password_hash(str(uuid.uuid4())),
                name=email,
                role=role,
            )
            if not user:
                raise HTTPException(500, "Failed to create user")

        jwt_token = create_token(
            data={"id": user.id},
            expires_delta=parse_duration(
                JWT_EXPIRES_IN.value
                if hasattr(JWT_EXPIRES_IN, "value")
                else JWT_EXPIRES_IN
            ),
        )

        response = RedirectResponse(
            url=f"{self.app.state.config.WEBUI_URL or request.base_url}auth#token={jwt_token}"
        )
        response.set_cookie(
            key="token",
            value=jwt_token,
            httponly=True,
            samesite=WEBUI_AUTH_COOKIE_SAME_SITE,
            secure=WEBUI_AUTH_COOKIE_SECURE,
        )
        return response
