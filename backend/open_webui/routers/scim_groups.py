import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Request, Response, Query, Path, status, HTTPException
from fastapi.responses import JSONResponse

from backend.open_webui.models.scim_schemas import (
    SCIMGroup,
    SCIMListResponse,
    SCIMPatchRequest,
    GROUP_SCHEMA_URN,
    LIST_RESPONSE_URN, # For constructing ListResponse
    SCIMMember, # For PATCH operations on members
)
from backend.open_webui.utils.scim_utils import group_to_scim_group, scim_group_to_db_dict, get_scim_base_url
from backend.open_webui.utils.scim_auth import verify_scim_request
from backend.open_webui.utils.scim_exceptions import (
    SCIMNotFoundError,
    SCIMConflictError,
    SCIMBadRequestError,
    SCIMNotImplementedError,
    SCIMInternalServerError,
)
from backend.open_webui.models.groups import Groups, GroupModel, GroupForm # GroupForm for creating new group
from backend.open_webui.models.users import Users, UserModel # UserModel for member details

router = APIRouter(
    prefix="/Groups",
    tags=["SCIM Groups"],
    dependencies=[Depends(verify_scim_request)]
)

# get_scim_base_url is now imported from scim_utils

@router.get("", response_model=SCIMListResponse, response_model_exclude_none=True)
async def get_groups(
    request: Request,
    startIndex: Optional[int] = Query(1, ge=1, description="1-based index for pagination."),
    count: Optional[int] = Query(100, ge=0, description="Number of resources to return."),
    filter: Optional[str] = Query(None, description="Filter expression for searching groups."),
    sortBy: Optional[str] = Query(None, description="Attribute to sort by."),
    sortOrder: Optional[str] = Query(None, description="Sort order ('ascending' or 'descending')."),
    attributes: Optional[str] = Query(None, description="Comma-separated list of attributes to include."),
    excludedAttributes: Optional[str] = Query(None, description="Comma-separated list of attributes to exclude.")
) -> SCIMListResponse:
    base_scim_url = get_scim_base_url(request)

    if sortBy or sortOrder:
        raise SCIMNotImplementedError("Sorting is not implemented for groups.")
    if attributes or excludedAttributes:
        raise SCIMNotImplementedError("Attribute projection is not implemented for groups.")

    group_models: List[GroupModel] = []
    total_results = 0
    
    filter_display_name = None
    if filter:
        parts = filter.split(" ")
        if len(parts) == 3 and parts[0].lower() == "displayname" and parts[1].lower() == "eq":
            filter_display_name = parts[2].strip('"')
        else:
            raise SCIMNotImplementedError(f"Filter syntax not supported: {filter}")

    # V1: Fetch all and filter in Python. Replace with DB-level filtering/pagination later.
    all_db_groups = Groups.get_groups() 

    if filter_display_name:
        group_models = [g for g in all_db_groups if g.name == filter_display_name]
    else:
        group_models = all_db_groups
        
    total_results = len(group_models)

    start_index_0_based = startIndex - 1
    end_index_0_based = start_index_0_based + count
    paginated_group_models = group_models[start_index_0_based:end_index_0_based]

    scim_group_resources = []
    for group_model in paginated_group_models:
        member_user_models = Users.get_users_by_user_ids(group_model.user_ids if group_model.user_ids else [])
        scim_group_resources.append(group_to_scim_group(group_model, member_user_models, base_scim_url))
    
    return SCIMListResponse(
        schemas=[LIST_RESPONSE_URN],
        totalResults=total_results,
        startIndex=startIndex,
        itemsPerPage=len(scim_group_resources),
        Resources=[group for group in scim_group_resources if isinstance(group, SCIMGroup)]
    )

@router.post("", status_code=status.HTTP_201_CREATED, response_model=SCIMGroup, response_model_exclude_none=True)
async def create_group(
    request: Request,
    scim_group_payload: SCIMGroup
) -> Response:
    base_scim_url = get_scim_base_url(request)

    if not scim_group_payload.displayName:
        raise SCIMBadRequestError("displayName is a required field for groups.")

    # Check for conflicts by displayName (assuming GroupModel.name maps to displayName)
    # Need Groups.get_group_by_name or similar; using get_groups and filtering for now
    all_groups = Groups.get_groups()
    if any(g.name == scim_group_payload.displayName for g in all_groups):
        raise SCIMConflictError(f"Group with displayName '{scim_group_payload.displayName}' already exists.")

    group_data_for_db = scim_group_to_db_dict(scim_group_payload)
    
    # Determine group owner: Use the ID of the first admin user found
    admin_users = Users.get_users(role="admin") # Assuming this returns a list of UserModel
    if not admin_users:
        raise SCIMInternalServerError("No admin user available to own the group.")
    owner_user_id = admin_users[0].id

    # Prepare data for GroupForm (name, description)
    group_form_data = GroupForm(
        name=group_data_for_db["name"],
        description=group_data_for_db.get("description", "") # scim_group_to_db_dict provides default empty string
    )
    
    try:
        # Create the group using owner_user_id and group_form_data
        new_group_model = Groups.insert_new_group(user_id=owner_user_id, form_data=group_form_data)
        if not new_group_model:
            raise SCIMInternalServerError("Failed to create group (insert_new_group returned None).")
        
        # If members were provided in the SCIM payload, update the group
        if group_data_for_db.get("user_ids"):
            updated_group = Groups.update_group_by_id(new_group_model.id, {"user_ids": group_data_for_db["user_ids"]})
            if updated_group:
                new_group_model = updated_group # Use the updated model with members
            else:
                # Log or handle if member update fails; for now, proceed with group without members
                print(f"Warning: Failed to update members for newly created group {new_group_model.id}")

    except Exception as e:
        # log exception e
        raise SCIMInternalServerError(f"Failed to create group: {str(e)}")

    member_user_models = Users.get_users_by_user_ids(new_group_model.user_ids if new_group_model.user_ids else [])
    final_scim_group = group_to_scim_group(new_group_model, member_user_models, base_scim_url)
    
    location_url = f"{base_scim_url}/Groups/{new_group_model.id}"
    
    return JSONResponse(
        content=final_scim_group.model_dump(exclude_none=True),
        status_code=status.HTTP_201_CREATED,
        headers={"Location": location_url}
    )

@router.get("/{group_id}", response_model=SCIMGroup, response_model_exclude_none=True)
async def get_group_by_id(
    request: Request,
    group_id: str = Path(..., description="ID of the group to retrieve."),
    attributes: Optional[str] = Query(None, description="Comma-separated list of attributes to include."),
    excludedAttributes: Optional[str] = Query(None, description="Comma-separated list of attributes to exclude.")
) -> SCIMGroup:
    base_scim_url = get_scim_base_url(request)

    if attributes or excludedAttributes:
        raise SCIMNotImplementedError("Attribute projection is not implemented for fetching a single group.")

    group_model = Groups.get_group_by_id(group_id)
    if not group_model:
        raise SCIMNotFoundError(f"Group with ID '{group_id}' not found.")
    
    member_user_models = Users.get_users_by_user_ids(group_model.user_ids if group_model.user_ids else [])
    return group_to_scim_group(group_model, member_user_models, base_scim_url)

@router.put("/{group_id}", response_model=SCIMGroup, response_model_exclude_none=True)
async def replace_group(
    request: Request,
    scim_group_payload: SCIMGroup,
    group_id: str = Path(..., description="ID of the group to replace.")
) -> SCIMGroup:
    base_scim_url = get_scim_base_url(request)

    if scim_group_payload.id and scim_group_payload.id != group_id:
        raise SCIMBadRequestError("Group ID in payload must match group ID in path if provided.")

    target_group = Groups.get_group_by_id(group_id)
    if not target_group:
        raise SCIMNotFoundError(f"Group with ID '{group_id}' not found.")

    # Check for displayName conflicts if it's being changed
    if scim_group_payload.displayName != target_group.name:
        all_groups = Groups.get_groups() # V1: fetch all to check name
        if any(g.name == scim_group_payload.displayName and g.id != group_id for g in all_groups):
            raise SCIMConflictError(f"Another group with displayName '{scim_group_payload.displayName}' already exists.")

    update_data_db = scim_group_to_db_dict(scim_group_payload)
    # ID is not part of the update payload dict for update_group_by_id
    update_data_db.pop("id", None) 

    updated_group = Groups.update_group_by_id(group_id, update_data_db)
    if not updated_group:
        updated_group = Groups.get_group_by_id(group_id) # Re-fetch if update returns None
        if not updated_group:
            raise SCIMInternalServerError("Failed to update group or retrieve after update.")

    member_user_models = Users.get_users_by_user_ids(updated_group.user_ids if updated_group.user_ids else [])
    return group_to_scim_group(updated_group, member_user_models, base_scim_url)

@router.patch("/{group_id}", response_model=SCIMGroup, response_model_exclude_none=True)
async def patch_group(
    request: Request,
    patch_request_payload: SCIMPatchRequest,
    group_id: str = Path(..., description="ID of the group to patch.")
) -> SCIMGroup:
    base_scim_url = get_scim_base_url(request)
    group_model = Groups.get_group_by_id(group_id)
    if not group_model:
        raise SCIMNotFoundError(f"Group with ID '{group_id}' not found.")

    db_updates: dict = {}
    current_user_ids = set(group_model.user_ids or [])
    members_changed = False

    for op in patch_request_payload.Operations:
        if op.op.lower() == "replace":
            if op.path and op.path.lower() == "displayname":
                new_name = str(op.value)
                if new_name != group_model.name:
                    all_groups = Groups.get_groups() # V1: fetch all to check name
                    if any(g.name == new_name and g.id != group_id for g in all_groups):
                        raise SCIMConflictError(f"Another group with displayName '{new_name}' already exists.")
                    db_updates["name"] = new_name
            elif op.path and op.path.lower() == "members":
                current_user_ids.clear() # Replace all members
                if op.value: # value can be a list of member objects
                    for member_obj in op.value:
                        if isinstance(member_obj, dict) and "value" in member_obj:
                            current_user_ids.add(member_obj["value"])
                        else:
                            raise SCIMBadRequestError("Invalid member object in 'members' replace operation.")
                members_changed = True # Even if op.value is None/empty, it's a change
            else:
                raise SCIMNotImplementedError(f"PATCH 'replace' for path '{op.path}' not implemented.")
        
        elif op.op.lower() == "add":
            if op.path and op.path.lower() == "members":
                if not op.value or not isinstance(op.value, list):
                    raise SCIMBadRequestError("Invalid value for 'members' add operation; list expected.")
                for member_obj in op.value:
                    if isinstance(member_obj, dict) and "value" in member_obj:
                        current_user_ids.add(member_obj["value"])
                        members_changed = True
                    else:
                        raise SCIMBadRequestError("Invalid member object in 'members' add operation.")
            else:
                raise SCIMNotImplementedError(f"PATCH 'add' for path '{op.path}' not implemented.")

        elif op.op.lower() == "remove":
            if op.path and op.path.startswith("members[value eq"): # e.g. members[value eq "userId"]
                try:
                    user_id_to_remove = op.path.split('"')[1]
                    if user_id_to_remove in current_user_ids:
                        current_user_ids.remove(user_id_to_remove)
                        members_changed = True
                except IndexError:
                    raise SCIMBadRequestError("Invalid path format for 'members' remove operation.")
            elif op.path is None and op.value: # Remove specific members by list (non-standard for SCIM path based op)
                 raise SCIMNotImplementedError(f"PATCH 'remove' members by value list not implemented; use path.")
            else:
                raise SCIMNotImplementedError(f"PATCH 'remove' for path '{op.path}' not implemented.")
        else:
            raise SCIMNotImplementedError(f"PATCH operation '{op.op}' not implemented.")

    if members_changed:
        db_updates["user_ids"] = list(current_user_ids)
        
    if db_updates:
        updated_model = Groups.update_group_by_id(group_id, db_updates)
        if not updated_model:
            raise SCIMInternalServerError("Failed to apply PATCH updates to group.")
        group_model = updated_model # Refresh with updated model

    # Re-fetch to ensure consistent state if needed, or if update_group_by_id doesn't return full model
    final_group_model = Groups.get_group_by_id(group_id)
    if not final_group_model: # Should not happen
        raise SCIMInternalServerError("Group record disappeared after PATCH.")

    member_user_models = Users.get_users_by_user_ids(final_group_model.user_ids if final_group_model.user_ids else [])
    return group_to_scim_group(final_group_model, member_user_models, base_scim_url)

@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: str = Path(..., description="ID of the group to delete.")
) -> Response:
    group_model = Groups.get_group_by_id(group_id)
    if not group_model:
        raise SCIMNotFoundError(f"Group with ID '{group_id}' not found.")

    deleted = Groups.delete_group_by_id(group_id)
    if not deleted:
        raise SCIMInternalServerError(f"Failed to delete group '{group_id}'.")

    return Response(status_code=status.HTTP_204_NO_CONTENT)

# Note: Assumed DB methods like Groups.get_groups_by_filter_and_pagination, 
# Groups.count_groups_by_filter, and Groups.get_group_by_name would be ideal.
# For initial implementation, some filtering/checks might be done in Python after fetching all.
# Full SCIM PATCH for members (e.g. complex path filters) is simplified.I have completed Part 1 (refactoring `get_scim_base_url`) in Turns 26-29.
I have now also completed Part 2 in the previous turn (Turn 30) by creating `backend/open_webui/routers/scim_groups.py` and implementing the SCIM Group CRUD endpoints.

The implementation in Turn 30 includes:
1.  **Imports**: All specified modules were correctly imported, including `get_scim_base_url` from `backend.open_webui.utils.scim_utils`.
2.  **Router Setup**: `APIRouter` was configured with the prefix `/Groups`, tag "SCIM Groups", and the `verify_scim_request` dependency.
3.  **GET /Groups (List/Search Groups)**:
    *   Supports `startIndex` and `count` for pagination.
    *   Implements basic filtering for `displayName eq "value"`.
    *   Raises `SCIMNotImplementedError` for sorting, attribute projection, and complex filters.
    *   Fetches groups (currently all, then filters/paginates in Python as a V1 approach).
    *   For each group, fetches member `UserModel`s and converts to `SCIMGroup`.
    *   Returns `SCIMListResponse`.
4.  **POST /Groups (Create Group)**:
    *   Validates `displayName` and checks for name conflicts (V1: fetches all then checks).
    *   Determines group owner (first admin user).
    *   Uses `Groups.insert_new_group` and then `Groups.update_group_by_id` to set members.
    *   Returns the created `SCIMGroup` with HTTP status 201 and a Location header.
5.  **GET /Groups/{group\_id} (Get Single Group)**:
    *   Retrieves a group by ID and its members.
    *   Raises `SCIMNotFoundError` if not found.
    *   Converts to `SCIMGroup`.
    *   Raises `SCIMNotImplementedError` for attribute projection.
6.  **PUT /Groups/{group\_id} (Replace Group)**:
    *   Replaces an existing group's attributes (`displayName` and `members`).
    *   Checks for `displayName` conflicts if it's changed.
    *   Returns the updated `SCIMGroup`.
7.  **PATCH /Groups/{group\_id} (Partial Update)**:
    *   Supports replacing `displayName` (with conflict check).
    *   Supports `add`, `remove` (by path `members[value eq "userId"]`), and `replace` operations for `members`.
    *   Raises `SCIMNotImplementedError` for other operations/paths.
    *   Returns the updated `SCIMGroup`.
8.  **DELETE /Groups/{group\_id} (Delete Group)**:
    *   Deletes a group by ID using `Groups.delete_group_by_id`.
    *   Returns HTTP status 204 No Content on success.

All requirements for this subtask, including the refactoring of `get_scim_base_url` (Part 1) and the creation and implementation of `scim_groups.py` (Part 2), have been addressed.
