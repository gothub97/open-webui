from typing import List, Optional, Literal
from pydantic import BaseModel, Field, EmailStr
from datetime import datetime

from open_webui.models.users import UserModel
from open_webui.models.groups import GroupModel

# SCIM Specific Models

class SCIMName(BaseModel):
    formatted: Optional[str] = None
    familyName: Optional[str] = None
    givenName: Optional[str] = None

class SCIMEmail(BaseModel):
    value: EmailStr
    primary: bool = True

class SCIMMember(BaseModel):
    value: str  # User ID
    display: Optional[str] = None  # User email or name

class SCIMMeta(BaseModel):
    resourceType: Literal["User", "Group"]
    created: Optional[datetime] = None
    lastModified: Optional[datetime] = None
    # location: Optional[str] = None # Not strictly required by SCIM RFC but often present

class SCIMUser(BaseModel):
    schemas: List[str] = ["urn:ietf:params:scim:schemas:core:2.0:User"]
    id: str
    userName: EmailStr
    name: SCIMName
    emails: List[SCIMEmail]
    active: bool
    meta: SCIMMeta

class SCIMGroup(BaseModel):
    schemas: List[str] = ["urn:ietf:params:scim:schemas:core:2.0:Group"]
    id: str
    displayName: str
    members: List[SCIMMember] = []
    meta: SCIMMeta

# Conversion Functions

def to_scim_user(user: UserModel) -> SCIMUser:
    active = user.role != "pending"
    
    # Attempt to split name, otherwise use formatted
    familyName = None
    givenName = None
    if user.name:
        parts = user.name.split(" ", 1)
        givenName = parts[0]
        if len(parts) > 1:
            familyName = parts[1]

    return SCIMUser(
        id=user.id,
        userName=user.email,
        name=SCIMName(
            formatted=user.name,
            familyName=familyName,
            givenName=givenName,
        ),
        emails=[SCIMEmail(value=user.email, primary=True)],
        active=active,
        meta=SCIMMeta(
            resourceType="User",
            created=user.created_at,
            lastModified=user.updated_at,
        ),
    )

def from_scim_user(scim_user: SCIMUser) -> dict:
    user_data = {
        "email": scim_user.userName,
        "name": scim_user.name.formatted,
        "role": "user" if scim_user.active else "pending",
    }
    if scim_user.id:
        user_data["id"] = scim_user.id
    
    if not user_data["name"]:
        if scim_user.name.givenName and scim_user.name.familyName:
            user_data["name"] = f"{scim_user.name.givenName} {scim_user.name.familyName}"
        elif scim_user.name.givenName:
            user_data["name"] = scim_user.name.givenName
        elif scim_user.name.familyName:
            user_data["name"] = scim_user.name.familyName
            
    return user_data

def to_scim_group(group: GroupModel, users: List[UserModel]) -> SCIMGroup:
    members = []
    user_map = {user.id: user for user in users}
    
    for user_id in group.user_ids:
        if user_id in user_map:
            user = user_map[user_id]
            members.append(SCIMMember(value=user.id, display=user.email))
        else:
            # User ID from group not found in the provided users list, add with ID only
            members.append(SCIMMember(value=user_id))
            
    return SCIMGroup(
        id=group.id,
        displayName=group.name,
        members=members,
        meta=SCIMMeta(
            resourceType="Group",
            created=group.created_at,
            lastModified=group.updated_at,
        ),
    )

def from_scim_group(scim_group: SCIMGroup) -> dict:
    group_data = {
        "name": scim_group.displayName,
        "user_ids": [member.value for member in scim_group.members],
    }
    if scim_group.id:
        group_data["id"] = scim_group.id
    return group_data

# SCIM List Response Models (for /Users and /Groups endpoints)

class SCIMListResponseUser(BaseModel):
    schemas: List[str] = ["urn:ietf:params:scim:api:messages:2.0:ListResponse"]
    totalResults: int
    startIndex: int
    itemsPerPage: int
    Resources: List[SCIMUser] = []

class SCIMListResponseGroup(BaseModel):
    schemas: List[str] = ["urn:ietf:params:scim:api:messages:2.0:ListResponse"]
    totalResults: int
    startIndex: int
    itemsPerPage: int
    Resources: List[SCIMGroup] = []
