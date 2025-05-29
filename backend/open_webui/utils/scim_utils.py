from backend.open_webui.models.users import UserModel
from backend.open_webui.models.groups import GroupModel
from backend.open_webui.models.scim_schemas import (
    SCIMUser,
    SCIMGroup,
    SCIMName,
    SCIMEmail,
    SCIMMeta,
    SCIMGroupMember,
    USER_SCHEMA_URN,
    GROUP_SCHEMA_URN,
)
from datetime import datetime, timezone
from typing import List, Dict, Any
from pydantic import HttpUrl # Used for type hinting, actual URL construction uses f-strings
from fastapi import Request # Added for get_scim_base_url

def user_to_scim_user(user: UserModel, base_url: str) -> SCIMUser:
    given_name = None
    family_name = None
    if user.name:
        name_parts = user.name.split(" ", 1)
        given_name = name_parts[0]
        if len(name_parts) > 1:
            family_name = name_parts[1]

    # Ensure timestamps are handled correctly, converting from float if necessary
    created_dt = None
    if user.created_at is not None:
        if isinstance(user.created_at, (int, float)):
            created_dt = datetime.fromtimestamp(user.created_at, tz=timezone.utc)
        elif isinstance(user.created_at, datetime):
            created_dt = user.created_at.replace(tzinfo=timezone.utc) if user.created_at.tzinfo is None else user.created_at

    last_modified_dt = None
    if user.updated_at is not None:
        if isinstance(user.updated_at, (int, float)):
            last_modified_dt = datetime.fromtimestamp(user.updated_at, tz=timezone.utc)
        elif isinstance(user.updated_at, datetime):
            last_modified_dt = user.updated_at.replace(tzinfo=timezone.utc) if user.updated_at.tzinfo is None else user.updated_at
        # If updated_at is None, SCIM spec suggests it's same as created_at
        elif created_dt:
             last_modified_dt = created_dt


    return SCIMUser(
        schemas=[USER_SCHEMA_URN],
        id=user.id,
        userName=user.email,
        name=SCIMName(
            formatted=user.name,
            givenName=given_name,
            familyName=family_name,
        ),
        displayName=user.name,
        active=(user.role != "pending"),
        emails=[SCIMEmail(value=user.email, primary=True, type="work")],
        meta=SCIMMeta(
            resourceType="User",
            created=created_dt,
            lastModified=last_modified_dt,
            location=HttpUrl(f"{base_url}/Users/{user.id}", scheme="http") if base_url.startswith("http:") else HttpUrl(f"{base_url}/Users/{user.id}", scheme="https")
        ),
        externalId=None, # Assuming UserModel doesn't have externalId
        phoneNumbers=[],
        addresses=[],
        groups=[], # Populated separately if needed, by fetching user's groups
    )

def scim_user_to_db_dict(scim_user: SCIMUser) -> Dict[str, Any]:
    name = None
    if scim_user.name and scim_user.name.formatted:
        name = scim_user.name.formatted
    elif scim_user.displayName:
        name = scim_user.displayName
    elif scim_user.name and scim_user.name.givenName and scim_user.name.familyName:
        name = f"{scim_user.name.givenName} {scim_user.name.familyName}"
    elif scim_user.name and scim_user.name.givenName:
        name = scim_user.name.givenName
    else:
        name = scim_user.userName # Fallback to userName if no other name available

    db_dict = {
        "email": scim_user.userName,
        "name": name,
        "role": "user" if scim_user.active else "pending",
        # ID is usually handled by the caller, either using scim_user.id or generating a new one
    }
    if scim_user.id:
        db_dict["id"] = scim_user.id
    if scim_user.externalId:
        db_dict["external_id"] = scim_user.externalId # Assuming UserModel might have this field

    # profile_image_url is not part of standard SCIM user, handle separately
    return db_dict

def group_to_scim_group(group: GroupModel, members_users: List[UserModel], base_url: str) -> SCIMGroup:
    scim_members = []
    member_map = {user.id: user for user in members_users}

    for user_id in group.user_ids:
        user_model = member_map.get(user_id)
        display_name = user_model.email if user_model else user_id # Fallback to ID if user not found
        scim_members.append(
            SCIMGroupMember(
                value=user_id,
                display=display_name,
                ref=HttpUrl(f"{base_url}/Users/{user_id}", scheme="http") if base_url.startswith("http:") else HttpUrl(f"{base_url}/Users/{user_id}", scheme="https"),
                type="User",
            )
        )
    
    created_dt = None
    if group.created_at is not None:
        if isinstance(group.created_at, (int, float)):
            created_dt = datetime.fromtimestamp(group.created_at, tz=timezone.utc)
        elif isinstance(group.created_at, datetime):
            created_dt = group.created_at.replace(tzinfo=timezone.utc) if group.created_at.tzinfo is None else group.created_at

    last_modified_dt = None
    if group.updated_at is not None:
        if isinstance(group.updated_at, (int, float)):
            last_modified_dt = datetime.fromtimestamp(group.updated_at, tz=timezone.utc)
        elif isinstance(group.updated_at, datetime):
             last_modified_dt = group.updated_at.replace(tzinfo=timezone.utc) if group.updated_at.tzinfo is None else group.updated_at
        elif created_dt: # If updated_at is None, SCIM spec suggests it's same as created_at
            last_modified_dt = created_dt

    return SCIMGroup(
        schemas=[GROUP_SCHEMA_URN],
        id=group.id,
        displayName=group.name,
        members=scim_members,
        meta=SCIMMeta(
            resourceType="Group",
            created=created_dt,
            lastModified=last_modified_dt,
            location=HttpUrl(f"{base_url}/Groups/{group.id}", scheme="http") if base_url.startswith("http:") else HttpUrl(f"{base_url}/Groups/{group.id}", scheme="https")
        ),
        externalId=None, # Assuming GroupModel doesn't have externalId
    )

def scim_group_to_db_dict(scim_group: SCIMGroup) -> Dict[str, Any]:
    db_dict = {
        "name": scim_group.displayName,
        "user_ids": [member.value for member in scim_group.members] if scim_group.members else [],
        "description": "", # GroupModel has description, SCIMGroup does not by default
    }
    if scim_group.id:
        db_dict["id"] = scim_group.id
    if scim_group.externalId: # Assuming GroupModel might have this field
        db_dict["external_id"] = scim_group.externalId
        
    return db_dict

def get_scim_base_url(request: Request) -> str:
    # Construct base URL up to /scim/v2
    url = request.url
    
    # A more robust way if root_path is configured:
    base_path = request.app.root_path
    if not base_path.endswith("/"):
        base_path += "/"
    
    # Assuming the SCIM router is mounted at /scim/v2 relative to the app's root
    scim_v2_path = "scim/v2" 
    
    # Construct the URL using the scheme and netloc from the original request
    return f"{url.scheme}://{url.netloc}{base_path}{scim_v2_path}"
