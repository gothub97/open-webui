import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Request, Response, Query, Body, Path, status, HTTPException
from fastapi.responses import JSONResponse

from backend.open_webui.models.scim_schemas import (
    SCIMUser,
    SCIMListResponse,
    SCIMPatchRequest,
    USER_SCHEMA_URN,
    # SCIMError, # No longer needed here if exceptions handle all SCIM error formatting
)
from backend.open_webui.utils.scim_utils import user_to_scim_user, scim_user_to_db_dict, get_scim_base_url
from backend.open_webui.utils.scim_auth import verify_scim_request
from backend.open_webui.utils.scim_exceptions import (
    SCIMNotFoundError,
    SCIMConflictError,
    SCIMBadRequestError,
    SCIMNotImplementedError,
    SCIMInternalServerError, # Added for robust error handling
)
from backend.open_webui.models.users import Users, UserModel # Assuming UserModel is the Pydantic model for a user row
from backend.open_webui.models.auths import Auths
from backend.open_webui.utils.auth import get_password_hash

router = APIRouter(
    prefix="/Users",
    tags=["SCIM Users"],
    dependencies=[Depends(verify_scim_request)]
)

# get_scim_base_url is now imported from scim_utils

@router.get("", response_model=SCIMListResponse, response_model_exclude_none=True)
async def get_users(
    request: Request,
    startIndex: Optional[int] = Query(1, ge=1, description="1-based index for pagination."),
    count: Optional[int] = Query(100, ge=0, description="Number of resources to return."),
    filter: Optional[str] = Query(None, description="Filter expression for searching users."),
    sortBy: Optional[str] = Query(None, description="Attribute to sort by."),
    sortOrder: Optional[str] = Query(None, description="Sort order ('ascending' or 'descending')."),
    attributes: Optional[str] = Query(None, description="Comma-separated list of attributes to include."),
    excludedAttributes: Optional[str] = Query(None, description="Comma-separated list of attributes to exclude.")
) -> SCIMListResponse:
    
    base_scim_url = get_scim_base_url(request)

    if sortBy or sortOrder:
        raise SCIMNotImplementedError("Sorting is not implemented for users.")
    if attributes or excludedAttributes:
        raise SCIMNotImplementedError("Attribute projection is not implemented for users.")

    user_models: List[UserModel] = []
    total_results = 0

    # Basic filter parsing: userName eq "value"
    filter_email = None
    if filter:
        parts = filter.split(" ")
        if len(parts) == 3 and parts[0].lower() == "username" and parts[1].lower() == "eq":
            filter_email = parts[2].strip('"')
        else:
            raise SCIMNotImplementedError(f"Filter syntax not supported: {filter}")

    # Fetching users:
    # This part needs to interact with Users model methods that ideally support pagination and filtering.
    # For V1, let's assume simpler methods and do some post-filtering/pagination if necessary.
    
    all_db_users = Users.get_users() # This fetches all users, not ideal for production

    if filter_email:
        user_models = [u for u in all_db_users if u.email == filter_email]
    else:
        user_models = all_db_users
    
    total_results = len(user_models)

    # Apply pagination
    # SCIM startIndex is 1-based
    start_index_0_based = startIndex - 1
    end_index_0_based = start_index_0_based + count
    paginated_user_models = user_models[start_index_0_based:end_index_0_based]

    scim_user_resources = [user_to_scim_user(user_model, base_scim_url) for user_model in paginated_user_models]

    return SCIMListResponse(
        schemas=[LIST_RESPONSE_URN],
        totalResults=total_results,
        startIndex=startIndex,
        itemsPerPage=len(scim_user_resources),
        Resources=[user for user in scim_user_resources if isinstance(user, SCIMUser)] # Ensure correct type
    )

@router.post("", status_code=status.HTTP_201_CREATED, response_model=SCIMUser, response_model_exclude_none=True)
async def create_user(
    request: Request,
    scim_user_payload: SCIMUser # Pydantic automatically validates the incoming payload against SCIMUser
) -> Response: # Return type is Response to set Location header
    
    base_scim_url = get_scim_base_url(request)

    if not scim_user_payload.userName:
        raise SCIMBadRequestError("userName is a required field.")

    existing_user = Users.get_user_by_email(scim_user_payload.userName)
    if existing_user:
        raise SCIMConflictError(f"User with userName '{scim_user_payload.userName}' already exists.")

    user_data_for_db = scim_user_to_db_dict(scim_user_payload)
    
    # Generate a new ID for the user if not provided (though usually server generates it for POST)
    user_id = scim_user_payload.id if scim_user_payload.id else str(uuid.uuid4())
    user_data_for_db["id"] = user_id # Ensure ID is in the dict for insert_new_auth

    # Generate a secure random password
    # SCIM spec says password MAY be provided. If not, server should generate one or reject.
    # We'll generate one if not provided or if the provided one is empty.
    if scim_user_payload.password:
        password_to_hash = scim_user_payload.password
    else:
        password_to_hash = uuid.uuid4().hex
        
    hashed_password = get_password_hash(password_to_hash)

    # Default profile image, role can be derived from 'active' in scim_user_to_db_dict
    profile_image_url = "/static/favicon.png" # TODO: Make configurable or derive differently

    try:
        # Auths.insert_new_auth should create user in 'users' and 'auths' tables
        created_auth_user = Auths.insert_new_auth(
            id=user_data_for_db["id"],
            email=user_data_for_db["email"],
            name=user_data_for_db.get("name"), # name can be optional
            hashed_password=hashed_password,
            role=user_data_for_db.get("role", "user"), # Default to 'user'
            profile_image_url=profile_image_url
        )
        if not created_auth_user: # insert_new_auth might return None or raise an error on failure
            raise SCIMInternalServerError("Failed to create user due to an internal error (auth creation failed).")
            
    except Exception as e: # Catch specific DB errors if possible
        # Log the exception e
        raise SCIMInternalServerError(f"Failed to create user: {str(e)}")

    # Fetch the newly created user model to ensure all fields are current
    new_user_model = Users.get_user_by_id(user_data_for_db["id"])
    if not new_user_model:
        # This case should ideally not happen if insert_new_auth was successful and transaction committed
        raise SCIMInternalServerError("Failed to retrieve created user immediately after creation.")
        
    final_scim_user = user_to_scim_user(new_user_model, base_scim_url)
    
    # Construct Location header
    location_url = f"{base_scim_url}/Users/{new_user_model.id}"
    
    return JSONResponse(
        content=final_scim_user.model_dump(exclude_none=True),
        status_code=status.HTTP_201_CREATED,
        headers={"Location": location_url}
    )


@router.get("/{user_id}", response_model=SCIMUser, response_model_exclude_none=True)
async def get_user_by_id(
    request: Request,
    user_id: str = Path(..., description="ID of the user to retrieve."),
    attributes: Optional[str] = Query(None, description="Comma-separated list of attributes to include."),
    excludedAttributes: Optional[str] = Query(None, description="Comma-separated list of attributes to exclude.")
) -> SCIMUser:
    base_scim_url = get_scim_base_url(request)

    if attributes or excludedAttributes:
        raise SCIMNotImplementedError("Attribute projection is not implemented for fetching a single user.")

    user_model = Users.get_user_by_id(user_id)
    if not user_model:
        raise SCIMNotFoundError(f"User with ID '{user_id}' not found.")
    
    return user_to_scim_user(user_model, base_scim_url)


@router.put("/{user_id}", response_model=SCIMUser, response_model_exclude_none=True)
async def replace_user(
    request: Request,
    scim_user_payload: SCIMUser,
    user_id: str = Path(..., description="ID of the user to replace.")
) -> SCIMUser:
    base_scim_url = get_scim_base_url(request)

    if scim_user_payload.id and scim_user_payload.id != user_id:
        raise SCIMBadRequestError("User ID in payload must match user ID in path if provided.")

    user_model = Users.get_user_by_id(user_id)
    if not user_model:
        raise SCIMNotFoundError(f"User with ID '{user_id}' not found.")

    # For PUT, the userName (email) can change. If it does, check for conflicts.
    if scim_user_payload.userName != user_model.email:
        existing_user_with_new_email = Users.get_user_by_email(scim_user_payload.userName)
        if existing_user_with_new_email and existing_user_with_new_email.id != user_id:
            raise SCIMConflictError(f"Another user with userName '{scim_user_payload.userName}' already exists.")

    update_data_db = scim_user_to_db_dict(scim_user_payload)
    # Remove ID from update_data_db as update_user_by_id takes it separately
    update_data_db.pop("id", None) 

    updated_user = Users.update_user_by_id(user_id, update_data_db)
    if not updated_user:
        # This could mean the update failed or returned None. Re-fetch to be sure.
        updated_user = Users.get_user_by_id(user_id)
        if not updated_user:
            raise SCIMInternalServerError("Failed to update user or retrieve after update.")

    # Handle password update if provided in PUT
    if scim_user_payload.password:
        hashed_password = get_password_hash(scim_user_payload.password)
        # Assuming Auths.update_user_password_by_id updates password in 'auths' table
        # This method needs to exist in Auths model.
        if not Auths.update_user_password_by_id(user_id, hashed_password):
             # Log this failure, but SCIM user resource might have updated other fields.
             # Depending on strictness, could raise error or just log.
            print(f"Warning: Failed to update password for user {user_id} during PUT operation.")


    return user_to_scim_user(updated_user, base_scim_url)

@router.patch("/{user_id}", response_model=SCIMUser, response_model_exclude_none=True)
async def patch_user(
    request: Request,
    patch_request_payload: SCIMPatchRequest,
    user_id: str = Path(..., description="ID of the user to patch.")
) -> SCIMUser:
    base_scim_url = get_scim_base_url(request)
    user_model = Users.get_user_by_id(user_id)
    if not user_model:
        raise SCIMNotFoundError(f"User with ID '{user_id}' not found.")

    # For V1, only implement 'active' field replacement.
    # A more complete implementation would need to handle complex paths and values.
    db_updates = {}
    password_to_update = None

    for op in patch_request_payload.Operations:
        if op.op.lower() == "replace":
            if op.path and op.path.lower() == "active":
                if isinstance(op.value, bool):
                    db_updates["role"] = "user" if op.value else "pending"
                else:
                    raise SCIMBadRequestError("Invalid value for 'active', boolean expected.")
            elif op.path and op.path.lower() == "username": # SCIM userName
                 if isinstance(op.value, str):
                    if op.value != user_model.email: # If email is changing
                        existing_user = Users.get_user_by_email(op.value)
                        if existing_user and existing_user.id != user_id:
                            raise SCIMConflictError(f"userName '{op.value}' is already in use.")
                        db_updates["email"] = op.value
                 else:
                    raise SCIMBadRequestError("Invalid value for 'userName', string expected.")
            # Add more specific path handling here for other fields (e.g., name.familyName)
            # For example:
            # elif op.path and op.path.lower() == "name.formattedname":
            #     db_updates["name"] = str(op.value)
            # elif op.path and op.path.lower() == "password":
            #     password_to_update = str(op.value) # Hash and update separately
            else:
                raise SCIMNotImplementedError(f"PATCH operation for path '{op.path}' with op '{op.op}' is not implemented.")
        else: # add, remove
            raise SCIMNotImplementedError(f"PATCH operation '{op.op}' is not implemented.")

    if db_updates:
        updated_model = Users.update_user_by_id(user_id, db_updates)
        if not updated_model:
            raise SCIMInternalServerError("Failed to apply PATCH updates.")
        user_model = updated_model # Refresh model state

    if password_to_update:
        # This logic for password update would need to be added to Auths model
        # hashed_password = get_password_hash(password_to_update)
        # Auths.update_user_password_by_id(user_id, hashed_password)
        # For now, if password path is used, it will hit SCIMNotImplementedError above.
        pass
        
    # Re-fetch to ensure consistent state after all operations
    final_user_model = Users.get_user_by_id(user_id)
    if not final_user_model: # Should not happen
        raise SCIMInternalServerError("User record disappeared after PATCH.")

    return user_to_scim_user(final_user_model, base_scim_url)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str = Path(..., description="ID of the user to delete.")
) -> Response:
    user_model = Users.get_user_by_id(user_id)
    if not user_model:
        raise SCIMNotFoundError(f"User with ID '{user_id}' not found.")

    # Auths.delete_auth_by_id should handle cascading deletion or related logic for users table
    auth_deleted = Auths.delete_auth_by_id(user_id) 
    if not auth_deleted:
        # If user existed but auth deletion failed, it's an internal issue.
        raise SCIMInternalServerError(f"Failed to delete user '{user_id}'. Auth record could not be deleted.")

    return Response(status_code=status.HTTP_204_NO_CONTENT)

# Note: The DB methods Users.get_users_by_filter_and_pagination, Users.count_users_by_filter,
# and Auths.update_user_password_by_id are assumed to be implemented or adapted in the models.
# For initial implementation, the GET /Users filtering is simplified.
# Full SCIM PATCH is complex and only basic 'active' and 'userName' replacement is sketched out.
# Error handling for DB operations should be more specific where possible.
# Location header for POST should use the final determined base_scim_url.
# The get_scim_base_url helper might need refinement based on deployment specifics (FastAPI root_path).
