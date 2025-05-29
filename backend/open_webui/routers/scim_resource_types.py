from fastapi import APIRouter, Request, Path
from pydantic import BaseModel, Field, HttpUrl
from typing import List, Optional

from backend.open_webui.models.scim_schemas import (
    USER_SCHEMA_URN, 
    GROUP_SCHEMA_URN, 
    LIST_RESPONSE_URN
)
from backend.open_webui.utils.scim_utils import get_scim_base_url
from backend.open_webui.utils.scim_exceptions import SCIMNotFoundError

# URN for ResourceType schema itself
RESOURCE_TYPE_SCHEMA_URN = "urn:ietf:params:scim:schemas:core:2.0:ResourceType"

class SCIMResourceTypeSchemaExtension(BaseModel):
    schema_str: str = Field(..., alias="schema")
    required: bool

class SCIMResourceTypeMeta(BaseModel):
    resourceType: str = "ResourceType"
    location: HttpUrl

class SCIMResourceType(BaseModel):
    schemas: List[str] = Field(default_factory=lambda: [RESOURCE_TYPE_SCHEMA_URN])
    id: str  # e.g., "User" or "Group"
    name: str
    description: Optional[str] = None
    endpoint: str  # Relative path from SCIM base, e.g., "/Users"
    schema_str: str = Field(..., alias="schema")  # Main schema URN
    schemaExtensions: Optional[List[SCIMResourceTypeSchemaExtension]] = None
    meta: SCIMResourceTypeMeta

    class Config:
        allow_population_by_field_name = True


class SCIMListResponseForResourceTypes(BaseModel):
    schemas: List[str] = Field(default_factory=lambda: [LIST_RESPONSE_URN])
    totalResults: int
    startIndex: int
    itemsPerPage: int
    Resources: List[SCIMResourceType] = Field(default_factory=list)


router = APIRouter(
    prefix="/ResourceTypes", 
    tags=["SCIM Resource Types"]
)

def _get_user_resource_type(base_scim_url: str) -> SCIMResourceType:
    return SCIMResourceType(
        schemas=[RESOURCE_TYPE_SCHEMA_URN],
        id="User",
        name="User",
        description="User Account",
        endpoint="/Users",
        schema=USER_SCHEMA_URN, # Pydantic will use alias 'schema_str' for field name
        meta=SCIMResourceTypeMeta(
            location=HttpUrl(f"{base_scim_url}/ResourceTypes/User", scheme="http") if base_scim_url.startswith("http:") else HttpUrl(f"{base_scim_url}/ResourceTypes/User", scheme="https")
        )
    )

def _get_group_resource_type(base_scim_url: str) -> SCIMResourceType:
    return SCIMResourceType(
        schemas=[RESOURCE_TYPE_SCHEMA_URN],
        id="Group",
        name="Group",
        description="Group",
        endpoint="/Groups",
        schema=GROUP_SCHEMA_URN,
        meta=SCIMResourceTypeMeta(
            location=HttpUrl(f"{base_scim_url}/ResourceTypes/Group", scheme="http") if base_scim_url.startswith("http:") else HttpUrl(f"{base_scim_url}/ResourceTypes/Group", scheme="https")
        )
    )

@router.get("", response_model=SCIMListResponseForResourceTypes, response_model_exclude_none=True)
async def get_resource_types(request: Request) -> SCIMListResponseForResourceTypes:
    base_scim_url = get_scim_base_url(request)
    
    user_resource_type = _get_user_resource_type(base_scim_url)
    group_resource_type = _get_group_resource_type(base_scim_url)
    
    resources = [user_resource_type, group_resource_type]
    
    return SCIMListResponseForResourceTypes(
        totalResults=len(resources),
        startIndex=1,
        itemsPerPage=len(resources),
        Resources=resources
    )

@router.get("/{type_name}", response_model=SCIMResourceType, response_model_exclude_none=True)
async def get_resource_type_by_name(request: Request, type_name: str = Path(..., description="Name of the ResourceType (User or Group)")) -> SCIMResourceType:
    base_scim_url = get_scim_base_url(request)
    
    if type_name.lower() == "user":
        return _get_user_resource_type(base_scim_url)
    elif type_name.lower() == "group":
        return _get_group_resource_type(base_scim_url)
    else:
        raise SCIMNotFoundError(f"ResourceType '{type_name}' not found.")
