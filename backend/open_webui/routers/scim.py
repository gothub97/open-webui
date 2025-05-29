from fastapi import FastAPI, APIRouter, Depends, HTTPException, Request, Response, status
from typing import List, Optional, Dict, Any
import uuid
import hmac

from backend.open_webui.models.scim import (
    SCIMUser,
    SCIMListResponseUser,
    SCIMName,
    SCIMEmail,
    SCIMMeta,
    to_scim_user,
    from_scim_user,
    SCIMGroup,
    SCIMListResponseGroup,
    to_scim_group,
    from_scim_group,
    SCIMMember, # Needed for PATCH operations on members
)
from backend.open_webui.models.users import UserModel, Users
from backend.open_webui.models.groups import GroupModel, Groups, GroupForm
from backend.open_webui.models.auths import Auths
from backend.open_webui.utils.auth import get_password_hash
from backend.open_webui.config import ENABLE_SCIM, SCIM_TOKEN

router = APIRouter(prefix="/scim/v2", tags=["scim"])

# Placeholder for SCIM authentication dependency (to be implemented later)
async def verify_scim_token(request: Request):
    if not ENABLE_SCIM.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="SCIM is not enabled")
    
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    
    scheme, _, credentials = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication scheme")
    
    # Ensure SCIM_TOKEN.value is a string before encoding
    scim_token_str = SCIM_TOKEN.value if isinstance(SCIM_TOKEN.value, str) else str(SCIM_TOKEN.value)

    if not hmac.compare_digest(scim_token_str.encode('utf-8'), credentials.encode('utf-8')):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return True


# SCIM uses 1-based indexing for startIndex
# FastAPI pagination typically uses 0-based offset
# Default count as per SCIM spec is often 100 if not specified by client

@router.get("/Users", response_model=SCIMListResponseUser, dependencies=[Depends(verify_scim_token)])
async def get_users(startIndex: Optional[int] = 1, count: Optional[int] = 100):
    # SCIM startIndex is 1-based, adjust for 0-based offset if your DB layer needs it
    # Assuming Users.get_users() handles limit and offset directly (or adapt as needed)
    # For now, let's assume it takes limit and offset, and we fetch all then slice.
    # This is not efficient for large datasets but simplifies the initial implementation.
    
    all_users_models = Users.get_users()
    if not all_users_models:
        return SCIMListResponseUser(
            totalResults=0,
            startIndex=startIndex,
            itemsPerPage=0,
            Resources=[],
        )

    total_results = len(all_users_models)

    # Adjust for 1-based startIndex
    start_index_0_based = (startIndex - 1) if startIndex > 0 else 0
    
    # Slice the users for pagination
    paginated_user_models = all_users_models[start_index_0_based : start_index_0_based + count]
    
    scim_users = [to_scim_user(user_model) for user_model in paginated_user_models]
    
    return SCIMListResponseUser(
        totalResults=total_results,
        startIndex=startIndex,
        itemsPerPage=len(scim_users),
        Resources=scim_users,
    )

@router.post("/Users", response_model=SCIMUser, status_code=status.HTTP_201_CREATED, dependencies=[Depends(verify_scim_token)])
async def create_user(scim_user_payload: SCIMUser):
    user_data = from_scim_user(scim_user_payload)
    
    existing_user = Users.get_user_by_email(user_data["email"])
    if existing_user:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User with this email already exists")

    # Generate a random password
    random_password = uuid.uuid4().hex
    hashed_password = get_password_hash(random_password)

    # Create user using Auths.insert_new_auth
    # This function should handle creating entries in both 'auths' and 'users' tables.
    # It typically requires id, email, name, password_hash, role.
    # We will let the DB assign the ID.
    
    # The from_scim_user function might not return all fields needed by insert_new_auth,
    # or might return them with different keys. We need to ensure the payload is correct.
    # Auths.insert_new_auth expects: id, email, name, password_hash, role
    
    auth_payload = {
        "id": scim_user_payload.id if scim_user_payload.id else str(uuid.uuid4()), # SCIM id can be provided by client
        "email": user_data["email"],
        "name": user_data.get("name"), # name can be optional
        "hashed_password": hashed_password,
        "role": user_data.get("role", "user"), # Default to 'user' if not specified
        "profile_image_url": f"/static/favicon.png", # Default profile image
    }

    created_auth = Auths.insert_new_auth(
        auth_payload["id"],
        auth_payload["email"],
        auth_payload["name"],
        auth_payload["hashed_password"],
        auth_payload["role"],
        auth_payload["profile_image_url"]
    )

    if not created_auth:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create user")

    # Fetch the newly created user model to return it
    new_user_model = Users.get_user_by_id(auth_payload["id"])
    if not new_user_model:
        # This case should ideally not happen if insert_new_auth was successful
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve created user")
        
    return to_scim_user(new_user_model)


@router.get("/Users/{user_id}", response_model=SCIMUser, dependencies=[Depends(verify_scim_token)])
async def get_user(user_id: str):
    user_model = Users.get_user_by_id(user_id)
    if not user_model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return to_scim_user(user_model)


@router.put("/Users/{user_id}", response_model=SCIMUser, dependencies=[Depends(verify_scim_token)])
async def update_user(user_id: str, scim_user_payload: SCIMUser):
    user_model = Users.get_user_by_id(user_id)
    if not user_model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    update_data = from_scim_user(scim_user_payload)

    # Update basic user details
    # Users.update_user_by_id expects a dictionary of fields to update
    # Ensure that we only pass fields that are meant to be updated by SCIM PUT
    
    user_update_payload = {
        "email": update_data["email"], # SCIM userName maps to email
        "name": update_data.get("name"),
        # Role is handled based on 'active' status
    }
    
    # Handle 'active' status change -> role change
    new_role = user_model.role
    if "role" in update_data: # from_scim_user sets role based on active
        if update_data["role"] == "pending" and user_model.role != "pending":
            new_role = "pending"
        elif update_data["role"] == "user" and user_model.role == "pending":
            new_role = "user"
    
    if new_role != user_model.role:
        user_update_payload["role"] = new_role

    updated_user_model = Users.update_user_by_id(user_id, user_update_payload)
    if not updated_user_model:
        # This might happen if the update fails for some reason, or if update_user_by_id returns None on no change
        # For SCIM, even if no change, a 200 OK with the current representation is expected.
        # Fetch the user again to be sure.
        updated_user_model = Users.get_user_by_id(user_id)
        if not updated_user_model:
             raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update or retrieve user after update")

    return to_scim_user(updated_user_model)

# SCIM PATCH request body structure
class SCIMPatchOp(BaseModel):
    op: str
    path: Optional[str] = None
    value: Any = None

class SCIMPatchRequest(BaseModel):
    schemas: List[str] = ["urn:ietf:params:scim:api:messages:2.0:PatchOp"]
    Operations: List[SCIMPatchOp]


@router.patch("/Users/{user_id}", response_model=SCIMUser, dependencies=[Depends(verify_scim_token)])
async def patch_user(user_id: str, patch_request: SCIMPatchRequest):
    user_model = Users.get_user_by_id(user_id)
    if not user_model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    updated = False
    for operation in patch_request.Operations:
        # For now, only support replacing the 'active' attribute
        if operation.op.lower() == "replace" and operation.path == "active":
            if isinstance(operation.value, bool):
                new_active_status = operation.value
                current_role = user_model.role
                new_role = current_role

                if new_active_status is False and current_role != "pending":
                    new_role = "pending"
                elif new_active_status is True and current_role == "pending":
                    new_role = "user"
                
                if new_role != current_role:
                    Users.update_user_by_id(user_id, {"role": new_role})
                    updated = True
            else:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid value type for 'active': {type(operation.value)}")
        elif operation.op.lower() == "add" or operation.op.lower() == "remove":
             # More complex operations like adding/removing emails, group memberships, etc.
             # SCIM path examples: "emails[type eq \"work\"].value", "members"
            raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=f"Operation '{operation.op}' on path '{operation.path}' not implemented")
        else: # Other operations or paths
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported PATCH operation: {operation.op} on path {operation.path}")

    if updated:
        user_model = Users.get_user_by_id(user_id) # Re-fetch the updated model

    return to_scim_user(user_model) # Return current state, 204 if no change, 200 if changed


@router.delete("/Users/{user_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(verify_scim_token)])
async def delete_user(user_id: str):
    user_model = Users.get_user_by_id(user_id)
    if not user_model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Delete associated auth entry. This should also handle deleting the user from the 'users' table
    # due to database cascade or trigger, or if Auths.delete_auth_by_id handles it.
    auth_deleted = Auths.delete_auth_by_id(user_id)
    
    if not auth_deleted:
        # If the user was found by Users.get_user_by_id, but Auths.delete_auth_by_id fails,
        # it implies an issue with deleting the auth object or the user object itself (if cascaded).
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete user authentication object")
    
    return Response(status_code=status.HTTP_204_NO_CONTENT)


####################################
# SCIM Group Endpoints
####################################

@router.get("/Groups", response_model=SCIMListResponseGroup, dependencies=[Depends(verify_scim_token)])
async def get_groups(startIndex: Optional[int] = 1, count: Optional[int] = 100):
    all_group_models = Groups.get_groups()
    if not all_group_models:
        return SCIMListResponseGroup(
            totalResults=0,
            startIndex=startIndex,
            itemsPerPage=0,
            Resources=[],
        )

    total_results = len(all_group_models)
    start_index_0_based = (startIndex - 1) if startIndex > 0 else 0
    paginated_group_models = all_group_models[start_index_0_based : start_index_0_based + count]

    scim_groups = []
    for group_model in paginated_group_models:
        member_user_models = Users.get_users_by_user_ids(group_model.user_ids) if group_model.user_ids else []
        scim_groups.append(to_scim_group(group_model, member_user_models))
    
    return SCIMListResponseGroup(
        totalResults=total_results,
        startIndex=startIndex,
        itemsPerPage=len(scim_groups),
        Resources=scim_groups,
    )

@router.post("/Groups", response_model=SCIMGroup, status_code=status.HTTP_201_CREATED, dependencies=[Depends(verify_scim_token)])
async def create_group(scim_group_payload: SCIMGroup):
    group_data_from_scim = from_scim_group(scim_group_payload)

    # Find an admin user to be the owner
    admin_users = Users.get_users(role="admin")
    if not admin_users:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="No admin user available to own the group")
    owner_user_id = admin_users[0].id

    group_form_payload = GroupForm(
        name=group_data_from_scim["name"],
        description=group_data_from_scim.get("description") # SCIM Group doesn't have description, this will be None
    )

    # Create the group. `insert_new_group` takes user_id (owner) and GroupForm (name, description)
    new_group_model = Groups.insert_new_group(user_id=owner_user_id, form_data=group_form_payload)
    if not new_group_model:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create group")

    # If SCIM payload included members, update the group with these members
    if "user_ids" in group_data_from_scim and group_data_from_scim["user_ids"]:
        updated_group = Groups.update_group_by_id(new_group_model.id, {"user_ids": group_data_from_scim["user_ids"]})
        if updated_group:
            new_group_model = updated_group # Use the updated model
        else:
            # Log or handle error if member update fails
            print(f"Warning: Failed to update members for newly created group {new_group_model.id}")


    member_user_models = Users.get_users_by_user_ids(new_group_model.user_ids) if new_group_model.user_ids else []
    return to_scim_group(new_group_model, member_user_models)


@router.get("/Groups/{group_id}", response_model=SCIMGroup, dependencies=[Depends(verify_scim_token)])
async def get_group(group_id: str):
    group_model = Groups.get_group_by_id(group_id)
    if not group_model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    
    member_user_models = Users.get_users_by_user_ids(group_model.user_ids) if group_model.user_ids else []
    return to_scim_group(group_model, member_user_models)


@router.put("/Groups/{group_id}", response_model=SCIMGroup, dependencies=[Depends(verify_scim_token)])
async def update_group(group_id: str, scim_group_payload: SCIMGroup):
    group_model = Groups.get_group_by_id(group_id)
    if not group_model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

    update_data = from_scim_group(scim_group_payload)
    
    # `from_scim_group` returns 'name' and 'user_ids'.
    # SCIM Group doesn't have a description field, so we won't update it here unless specifically mapped.
    update_payload = {
        "name": update_data["name"],
        "user_ids": update_data.get("user_ids", []), # Default to empty list if not provided
    }

    updated_group_model = Groups.update_group_by_id(group_id, update_payload)
    if not updated_group_model:
        # Fetch again to ensure we return the current state if update_group_by_id returns None on no change
        updated_group_model = Groups.get_group_by_id(group_id)
        if not updated_group_model:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update or retrieve group after update")

    member_user_models = Users.get_users_by_user_ids(updated_group_model.user_ids) if updated_group_model.user_ids else []
    return to_scim_group(updated_group_model, member_user_models)


@router.patch("/Groups/{group_id}", response_model=SCIMGroup, dependencies=[Depends(verify_scim_token)])
async def patch_group(group_id: str, patch_request: SCIMPatchRequest):
    group_model = Groups.get_group_by_id(group_id)
    if not group_model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

    updated = False
    current_user_ids = set(group_model.user_ids or [])

    for operation in patch_request.Operations:
        if operation.path and operation.path.lower() == "displayname":
            if operation.op.lower() == "replace":
                if isinstance(operation.value, str):
                    if group_model.name != operation.value:
                        Groups.update_group_by_id(group_id, {"name": operation.value})
                        updated = True
                else:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid value type for displayName")
            else:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported op '{operation.op}' for displayName")

        elif operation.path and operation.path.lower() == "members":
            if operation.op.lower() == "replace":
                new_member_ids = set()
                if isinstance(operation.value, list):
                    for member_data in operation.value:
                        if isinstance(member_data, dict) and "value" in member_data:
                            new_member_ids.add(member_data["value"])
                        else: # SCIM clients might send SCIMMember like objects or just strings
                            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid member format in replace operation")
                elif operation.value is None: # Replacing with no members
                    pass # new_member_ids is already empty set
                else:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid value for members replace operation")
                
                if current_user_ids != new_member_ids:
                    Groups.update_group_by_id(group_id, {"user_ids": list(new_member_ids)})
                    current_user_ids = new_member_ids # update current state for next operations
                    updated = True

            elif operation.op.lower() == "add":
                if isinstance(operation.value, list):
                    added_something = False
                    for member_data in operation.value:
                        if isinstance(member_data, dict) and "value" in member_data:
                            user_to_add = member_data["value"]
                            if user_to_add not in current_user_ids:
                                current_user_ids.add(user_to_add)
                                added_something = True
                        else:
                            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid member format in add operation")
                    if added_something:
                        Groups.update_group_by_id(group_id, {"user_ids": list(current_user_ids)})
                        updated = True
                else:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid value for members add operation")
            else:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported op '{operation.op}' for members path")
        
        # Handling specific member removal: op: remove, path: members[value eq "userId"]
        elif operation.op.lower() == "remove" and operation.path and "members[value eq" in operation.path.lower():
            try:
                user_to_remove = operation.path.split('"')[1] # Extract userId from path
                if user_to_remove in current_user_ids:
                    current_user_ids.remove(user_to_remove)
                    Groups.update_group_by_id(group_id, {"user_ids": list(current_user_ids)})
                    updated = True
            except IndexError:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid path format for member removal")
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported PATCH operation: op '{operation.op}', path '{operation.path}'")

    if updated:
        # Re-fetch the group model to get the latest state including timestamps
        group_model = Groups.get_group_by_id(group_id)
        if not group_model: # Should not happen if previously existed
             raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Group disappeared after update")


    member_user_models = Users.get_users_by_user_ids(group_model.user_ids) if group_model.user_ids else []
    return to_scim_group(group_model, member_user_models)


@router.delete("/Groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(verify_scim_token)])
async def delete_group(group_id: str):
    group_model = Groups.get_group_by_id(group_id)
    if not group_model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

    deleted = Groups.delete_group_by_id(group_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete group")
    
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# TODO: Refine error handling and edge cases for Group endpoints.
# TODO: Implement more comprehensive PATCH operations for User and Group.
# TODO: Add request validation for SCIM specific fields/formats if not covered by Pydantic models (though Pydantic handles much of this).
# TODO: Ensure logging is adequate.
# TODO: Test with a SCIM client.
# TODO: The verify_scim_token is basic; enhance for production (e.g., secure comparison for token).
# TODO: Pagination in get_users can be optimized by passing limit/offset to the DB layer.
# TODO: For POST /Users, SCIM clients might expect the 'id' to be returned in the 'meta.location' header.
#       And the 'id' in the response body should match the one in the DB.
#       The current insert_new_auth uses the provided ID, which is good.
# TODO: PUT /Users - if email (userName) changes, need to check for conflicts.
#       The current Users.update_user_by_id might not handle email changes or conflicts.
#       This needs careful consideration. For now, assume userName (email) is not changed by PUT,
#       or that the client ensures it's unique. SCIM spec says "service provider NEED NOT \
#       provide direct support for disassociating the old identifier from the resource."
#       but "A service provider MUST ensure that internal references to the resource are \
#       also updated." For email, it's effectively a key.
# TODO: SCIM PATCH can return 204 if no changes were made, or 200 if changes applied.
#       Currently returning 200 with the (potentially unchanged) resource. This is acceptable.

# Example of how to include this router in your main FastAPI app:
# from backend.open_webui.routers import scim
# app.include_router(scim.router)

"""
Notes on Auths.insert_new_auth:
- It takes: id, email, name, hashed_password, role, profile_image_url
- It creates a user in `users` table and an auth entry in `auths` table.
- It seems to handle the creation of both, which is good.

Notes on Users.update_user_by_id:
- It takes: id, and a dict of fields to update.
- Fields can be: name, email, role, profile_image_url, settings.

Notes on Auths.delete_auth_by_id (previously delete_auth_by_user_id):
- Assumed this function deletes the auth entry AND the corresponding user entry in 'users' table,
  either directly or via database cascade. This is critical for proper user deletion.

SCIM Compliance Points:
- ETag for versioning is not implemented.
- Filtering, Sorting, and Complex Attributes for GET /Users are not fully implemented.
- Bulk Operations not implemented.
- Schema endpoint (/Schemas) not implemented.
- ResourceType endpoint (/ResourceTypes) not implemented.
- ServiceProviderConfig endpoint (/ServiceProviderConfig) not implemented.
"""
