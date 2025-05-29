from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, HttpUrl
from typing import List, Optional

# SCIM URN for ServiceProviderConfig
SERVICE_PROVIDER_CONFIG_URN = "urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"

class SCIMAuthenticationScheme(BaseModel):
    type: str
    name: str
    description: str
    specUri: Optional[HttpUrl] = None
    documentationUri: Optional[HttpUrl] = None
    primary: Optional[bool] = False

class SCIMServiceProviderConfigSupport(BaseModel):
    supported: bool
    maxOperations: Optional[int] = None # For bulk
    maxPayloadSize: Optional[int] = None # For bulk
    maxResults: Optional[int] = None # For filter

class SCIMServiceProviderConfig(BaseModel):
    schemas: List[str] = Field(default_factory=lambda: [SERVICE_PROVIDER_CONFIG_URN])
    documentationUri: Optional[HttpUrl] = None
    patch: SCIMServiceProviderConfigSupport
    bulk: SCIMServiceProviderConfigSupport
    filter: SCIMServiceProviderConfigSupport
    changePassword: SCIMServiceProviderConfigSupport
    sort: SCIMServiceProviderConfigSupport
    etag: SCIMServiceProviderConfigSupport
    authenticationSchemes: List[SCIMAuthenticationScheme]
    # As per RFC 7643, meta for ServiceProviderConfig is optional and typically not versioned with ETag.
    # Location is the URI of the ServiceProviderConfig endpoint itself.
    meta: dict = Field(default_factory=lambda: {"resourceType": "ServiceProviderConfig"})


router = APIRouter(
    prefix="/ServiceProviderConfig", 
    tags=["SCIM Service Provider Config"]
)

@router.get("", response_model=SCIMServiceProviderConfig, response_model_exclude_none=True)
async def get_service_provider_config(request: Request) -> SCIMServiceProviderConfig:
    
    # Construct the full location URL for the meta field
    # request.url gives the full URL of the current request
    location_url = str(request.url) 

    # Alternatively, if you need to ensure it's just the path and query if behind a proxy:
    # location_path = request.url.path
    # if request.url.query:
    #     location_path += f"?{request.url.query}"
    # For ServiceProviderConfig, the full URL is common for meta.location.

    service_provider_config = SCIMServiceProviderConfig(
        documentationUri=HttpUrl("https://open-webui.com/docs/api/scim", scheme="https") if not str(request.url).startswith("http://localhost") else None, # Example documentation URI
        patch=SCIMServiceProviderConfigSupport(supported=True),
        bulk=SCIMServiceProviderConfigSupport(supported=False, maxOperations=0, maxPayloadSize=0), # Not implemented
        filter=SCIMServiceProviderConfigSupport(supported=True, maxResults=100), # Basic filtering supported
        changePassword=SCIMServiceProviderConfigSupport(supported=False), # Not implemented via SCIM
        sort=SCIMServiceProviderConfigSupport(supported=False), # Not implemented
        etag=SCIMServiceProviderConfigSupport(supported=False), # Not implemented
        authenticationSchemes=[
            SCIMAuthenticationScheme(
                type="oauthbearertoken", # Standard type for bearer tokens
                name="Bearer Token",
                description="Authentication using a static Bearer Token (SCIM_TOKEN).",
                primary=True
            )
        ],
        meta={
            "resourceType": "ServiceProviderConfig",
            "location": location_url # Location of this endpoint
        }
    )
    return service_provider_config
