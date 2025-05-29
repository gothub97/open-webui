from pydantic import BaseModel, Field, HttpUrl
from typing import List, Optional, Union, Any
from datetime import datetime

# Default SCIM URNs
USER_SCHEMA_URN = "urn:ietf:params:scim:schemas:core:2.0:User"
GROUP_SCHEMA_URN = "urn:ietf:params:scim:schemas:core:2.0:Group"
LIST_RESPONSE_URN = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
PATCH_OP_URN = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
ERROR_URN = "urn:ietf:params:scim:api:messages:2.0:Error"

class SCIMMeta(BaseModel):
    resourceType: str
    created: Optional[datetime] = None
    lastModified: Optional[datetime] = None
    location: Optional[HttpUrl] = None
    version: Optional[str] = None  # ETag

class SCIMName(BaseModel):
    formatted: Optional[str] = None
    familyName: Optional[str] = None
    givenName: Optional[str] = None
    middleName: Optional[str] = None
    honorificPrefix: Optional[str] = None
    honorificSuffix: Optional[str] = None

class SCIMMultiValuedAttribute(BaseModel): # Base for email, phone, etc.
    value: Optional[str] = None
    display: Optional[str] = None
    type: Optional[str] = None
    primary: Optional[bool] = False

class SCIMEmail(SCIMMultiValuedAttribute):
    pass

class SCIMPhoneNumber(SCIMMultiValuedAttribute):
    pass

class SCIMAddress(BaseModel):
    type: Optional[str] = None
    streetAddress: Optional[str] = None
    locality: Optional[str] = None
    region: Optional[str] = None
    postalCode: Optional[str] = None
    country: Optional[str] = None
    formatted: Optional[str] = None
    primary: Optional[bool] = False

class SCIMGroupMember(BaseModel):
    value: str  # User ID
    ref: Optional[HttpUrl] = Field(None, alias="$ref")
    type: Optional[str] = None
    display: Optional[str] = None

class SCIMUser(BaseModel):
    schemas: List[str] = Field(default_factory=lambda: [USER_SCHEMA_URN])
    id: str
    externalId: Optional[str] = None
    userName: str
    name: Optional[SCIMName] = None
    displayName: Optional[str] = None
    nickName: Optional[str] = None
    profileUrl: Optional[HttpUrl] = None
    title: Optional[str] = None
    userType: Optional[str] = None
    preferredLanguage: Optional[str] = None
    locale: Optional[str] = None
    timezone: Optional[str] = None
    active: Optional[bool] = False
    password: Optional[str] = None # Write-only
    
    emails: Optional[List[SCIMEmail]] = None
    phoneNumbers: Optional[List[SCIMPhoneNumber]] = None
    addresses: Optional[List[SCIMAddress]] = None
    
    groups: Optional[List[SCIMGroupMember]] = None # Read-only for client, populated by server
    
    meta: SCIMMeta

    class Config:
        allow_population_by_field_name = True

class SCIMGroup(BaseModel):
    schemas: List[str] = Field(default_factory=lambda: [GROUP_SCHEMA_URN])
    id: str
    externalId: Optional[str] = None
    displayName: str
    members: Optional[List[SCIMGroupMember]] = None
    meta: SCIMMeta

    class Config:
        allow_population_by_field_name = True

class SCIMListResponse(BaseModel):
    schemas: List[str] = Field(default_factory=lambda: [LIST_RESPONSE_URN])
    totalResults: int
    startIndex: int
    itemsPerPage: int
    Resources: List[Union[SCIMUser, SCIMGroup]] = Field(default_factory=list)

class SCIMPatchOp(BaseModel):
    op: str = Field(..., pattern="^(add|replace|remove)$") # Using ... to mark it as required
    path: Optional[str] = None
    value: Optional[Any] = None # Can be a single value, object, or array of objects/values

class SCIMPatchRequest(BaseModel):
    schemas: List[str] = Field(default_factory=lambda: [PATCH_OP_URN])
    Operations: List[SCIMPatchOp]

class SCIMError(BaseModel):
    schemas: List[str] = Field(default_factory=lambda: [ERROR_URN])
    detail: Optional[str] = None
    status: Optional[str] = None # String representation of HTTP status code
    scimType: Optional[str] = None # e.g., uniqueness, tooMany, invalidSyntax, etc.
