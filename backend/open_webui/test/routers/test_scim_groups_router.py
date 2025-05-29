import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, ANY
import uuid
from typing import List

from backend.open_webui.main import app
from backend.open_webui.models.users import UserModel
from backend.open_webui.models.groups import GroupModel, GroupForm
from backend.open_webui.models.scim_schemas import (
    GROUP_SCHEMA_URN,
    LIST_RESPONSE_URN,
    ERROR_URN,
    SCIMGroup,
    SCIMMember,
    SCIMMeta,
    SCIMPatchOp
)
from backend.open_webui.config import ENABLE_SCIM, SCIM_TOKEN

# Test SCIM Token (same as in users test, can be shared via conftest.py later)
VALID_SCIM_TOKEN = "test_scim_token_12345"
INVALID_SCIM_TOKEN = "invalid_scim_token_67890"
HEADERS = {"Authorization": f"Bearer {VALID_SCIM_TOKEN}"}
INVALID_HEADERS = {"Authorization": f"Bearer {INVALID_SCIM_TOKEN}"}
NO_AUTH_HEADERS = {}


@pytest.fixture(scope="module")
def client():
    # Patch SCIM configuration for the test session
    with patch.object(ENABLE_SCIM, 'value', True), \
         patch.object(SCIM_TOKEN, 'value', VALID_SCIM_TOKEN):
        test_app_client = TestClient(app)
        yield test_app_client

# --- Mock Data ---
def create_mock_user_model(id: str, email: str, name: str, role: str = "user") -> UserModel:
    return UserModel(
        id=id, email=email, name=name, role=role, profile_image_url="/static/favicon.png",
        created_at=1670000000.0, updated_at=1670000000.0, settings={}, api_key=None,
        last_active_at=None, info=None, organization_id=None, pending_email=None,
        referral_code=None, company=None, website=None, phone_number=None
    )

def create_mock_group_model(id: str, name: str, user_ids: List[str], created_at=None, updated_at=None) -> GroupModel:
    return GroupModel(
        id=id, name=name, user_ids=user_ids,
        created_at=created_at or 1670000000.0,
        updated_at=updated_at or 1670000000.0,
        description="", # Add other fields if your GroupModel has them
        user_id="" # Owner user_id, assuming it exists
    )

mock_user_id1 = str(uuid.uuid4())
mock_user_id2 = str(uuid.uuid4())
mock_admin_user_id = str(uuid.uuid4())

mock_user1 = create_mock_user_model(id=mock_user_id1, email="member1@example.com", name="Member One")
mock_user2 = create_mock_user_model(id=mock_user_id2, email="member2@example.com", name="Member Two")
mock_admin_user = create_mock_user_model(id=mock_admin_user_id, email="admin@example.com", name="Admin User", role="admin")


mock_group1_id = str(uuid.uuid4())
mock_group1_name = "Group One"
mock_group1 = create_mock_group_model(id=mock_group1_id, name=mock_group1_name, user_ids=[mock_user_id1])

mock_group2_id = str(uuid.uuid4())
mock_group2_name = "Group Two"
mock_group2 = create_mock_group_model(id=mock_group2_id, name=mock_group2_name, user_ids=[mock_user_id1, mock_user_id2])


# --- Test Cases ---

# Authentication Tests (Basic check, more exhaustive ones in user tests)
def test_get_groups_no_token(client):
    response = client.get("/scim/v2/Groups", headers=NO_AUTH_HEADERS)
    assert response.status_code == 401
    data = response.json()
    assert data["schemas"] == [ERROR_URN]

# GET /Groups
@patch('backend.open_webui.routers.scim_groups.Users')
@patch('backend.open_webui.routers.scim_groups.Groups')
def test_get_groups_empty(MockGroups, MockUsers, client):
    MockGroups.get_groups.return_value = []
    response = client.get("/scim/v2/Groups", headers=HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data["schemas"] == [LIST_RESPONSE_URN]
    assert data["totalResults"] == 0
    assert data["Resources"] == []

@patch('backend.open_webui.routers.scim_groups.Users')
@patch('backend.open_webui.routers.scim_groups.Groups')
def test_get_groups_list_with_pagination(MockGroups, MockUsers, client):
    MockGroups.get_groups.return_value = [mock_group1, mock_group2]
    MockUsers.get_users_by_user_ids.side_effect = lambda ids: [u for u in [mock_user1, mock_user2] if u.id in ids]

    response = client.get("/scim/v2/Groups?startIndex=1&count=1", headers=HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data["totalResults"] == 2
    assert data["itemsPerPage"] == 1
    assert len(data["Resources"]) == 1
    assert data["Resources"][0]["displayName"] == mock_group1_name

    response = client.get("/scim/v2/Groups?startIndex=2&count=1", headers=HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data["totalResults"] == 2
    assert data["itemsPerPage"] == 1
    assert len(data["Resources"]) == 1
    assert data["Resources"][0]["displayName"] == mock_group2_name

@patch('backend.open_webui.routers.scim_groups.Users')
@patch('backend.open_webui.routers.scim_groups.Groups')
def test_get_groups_filter_displayname(MockGroups, MockUsers, client):
    MockGroups.get_groups.return_value = [mock_group1, mock_group2]
    MockUsers.get_users_by_user_ids.return_value = [mock_user1] # For mock_group1

    response = client.get(f'/scim/v2/Groups?filter=displayName eq "{mock_group1_name}"', headers=HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data["totalResults"] == 1
    assert len(data["Resources"]) == 1
    assert data["Resources"][0]["displayName"] == mock_group1_name

# POST /Groups
@patch('backend.open_webui.routers.scim_groups.Users')
@patch('backend.open_webui.routers.scim_groups.Groups')
def test_create_group_success(MockGroups, MockUsers, client):
    new_group_id = str(uuid.uuid4())
    new_group_name = "New Test Group"
    
    MockUsers.get_users.return_value = [mock_admin_user] # For owner assignment
    MockGroups.get_groups.return_value = [] # No existing group with this name
    
    # Mock for insert_new_group
    created_group_model = create_mock_group_model(id=new_group_id, name=new_group_name, user_ids=[mock_user_id1])
    MockGroups.insert_new_group.return_value = created_group_model
    
    # Mock for subsequent update_group_by_id if members are in payload
    MockGroups.update_group_by_id.return_value = created_group_model 
    MockUsers.get_users_by_user_ids.return_value = [mock_user1]


    scim_payload = {
        "schemas": [GROUP_SCHEMA_URN],
        "displayName": new_group_name,
        "members": [{"value": mock_user_id1, "display": "Member One"}]
    }

    response = client.post("/scim/v2/Groups", headers=HEADERS, json=scim_payload)
    assert response.status_code == 201
    data = response.json()
    assert data["displayName"] == new_group_name
    assert data["id"] == new_group_id
    assert len(data["members"]) == 1
    assert data["members"][0]["value"] == mock_user_id1
    assert response.headers["Location"].endswith(f"/scim/v2/Groups/{new_group_id}")

    MockGroups.insert_new_group.assert_called_once_with(user_id=mock_admin_user_id, form_data=ANY)
    # Check that GroupForm was called with correct name
    form_data_arg = MockGroups.insert_new_group.call_args[1]['form_data']
    assert isinstance(form_data_arg, GroupForm)
    assert form_data_arg.name == new_group_name
    MockGroups.update_group_by_id.assert_called_once_with(new_group_id, {"user_ids": [mock_user_id1]})


@patch('backend.open_webui.routers.scim_groups.Users')
@patch('backend.open_webui.routers.scim_groups.Groups')
def test_create_group_no_admin_owner(MockGroups, MockUsers, client):
    MockUsers.get_users.return_value = [] # No admin user
    MockGroups.get_groups.return_value = [] 

    scim_payload = {"schemas": [GROUP_SCHEMA_URN], "displayName": "NoOwnerGroup"}
    response = client.post("/scim/v2/Groups", headers=HEADERS, json=scim_payload)
    assert response.status_code == 500
    data = response.json()
    assert data["schemas"] == [ERROR_URN]
    assert data["scimType"] == "internalServerError"
    assert "No admin user available" in data["detail"]

@patch('backend.open_webui.routers.scim_groups.Groups')
def test_create_group_conflict(MockGroups, client):
    MockGroups.get_groups.return_value = [mock_group1] # Group with this name exists
    
    scim_payload = {"schemas": [GROUP_SCHEMA_URN], "displayName": mock_group1_name}
    response = client.post("/scim/v2/Groups", headers=HEADERS, json=scim_payload)
    assert response.status_code == 409
    data = response.json()
    assert data["schemas"] == [ERROR_URN]
    assert data["scimType"] == "uniqueness"


# GET /Groups/{id}
@patch('backend.open_webui.routers.scim_groups.Users')
@patch('backend.open_webui.routers.scim_groups.Groups')
def test_get_group_by_id_found(MockGroups, MockUsers, client):
    MockGroups.get_group_by_id.return_value = mock_group1
    MockUsers.get_users_by_user_ids.return_value = [mock_user1]

    response = client.get(f"/scim/v2/Groups/{mock_group1_id}", headers=HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == mock_group1_id
    assert data["displayName"] == mock_group1_name
    assert len(data["members"]) == 1
    assert data["members"][0]["value"] == mock_user_id1

@patch('backend.open_webui.routers.scim_groups.Groups')
def test_get_group_by_id_not_found(MockGroups, client):
    MockGroups.get_group_by_id.return_value = None
    non_existent_id = str(uuid.uuid4())
    response = client.get(f"/scim/v2/Groups/{non_existent_id}", headers=HEADERS)
    assert response.status_code == 404

# PUT /Groups/{id}
@patch('backend.open_webui.routers.scim_groups.Users')
@patch('backend.open_webui.routers.scim_groups.Groups')
def test_replace_group_success(MockGroups, MockUsers, client):
    updated_group_name = "Group One Updated"
    updated_member_ids = [mock_user_id2]
    
    # Initial get_group_by_id
    MockGroups.get_group_by_id.return_value = mock_group1
    # get_groups for name conflict check (assume no conflict)
    MockGroups.get_groups.return_value = [mock_group1, mock_group2] 
    # update_group_by_id
    updated_group_model = create_mock_group_model(id=mock_group1_id, name=updated_group_name, user_ids=updated_member_ids)
    MockGroups.update_group_by_id.return_value = updated_group_model
    # Users for member details
    MockUsers.get_users_by_user_ids.return_value = [mock_user2]


    scim_payload_put = {
        "schemas": [GROUP_SCHEMA_URN],
        "id": mock_group1_id,
        "displayName": updated_group_name,
        "members": [{"value": mock_user_id2}]
    }
    response = client.put(f"/scim/v2/Groups/{mock_group1_id}", headers=HEADERS, json=scim_payload_put)
    assert response.status_code == 200
    data = response.json()
    assert data["displayName"] == updated_group_name
    assert len(data["members"]) == 1
    assert data["members"][0]["value"] == mock_user_id2
    MockGroups.update_group_by_id.assert_called_once_with(mock_group1_id, {"name": updated_group_name, "user_ids": updated_member_ids})


# PATCH /Groups/{id}
@patch('backend.open_webui.routers.scim_groups.Users')
@patch('backend.open_webui.routers.scim_groups.Groups')
def test_patch_group_replace_members(MockGroups, MockUsers, client):
    # Initial group has mock_user_id1. Patch will replace with mock_user_id2.
    patched_group_model = create_mock_group_model(id=mock_group1_id, name=mock_group1_name, user_ids=[mock_user_id2])
    
    MockGroups.get_group_by_id.side_effect = [mock_group1, patched_group_model] # Before and after update
    MockGroups.update_group_by_id.return_value = patched_group_model
    MockUsers.get_users_by_user_ids.return_value = [mock_user2] # For final response construction

    patch_payload = {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
        "Operations": [{"op": "replace", "path": "members", "value": [{"value": mock_user_id2}]}]
    }
    response = client.patch(f"/scim/v2/Groups/{mock_group1_id}", headers=HEADERS, json=patch_payload)
    assert response.status_code == 200
    data = response.json()
    assert len(data["members"]) == 1
    assert data["members"][0]["value"] == mock_user_id2
    MockGroups.update_group_by_id.assert_called_once_with(mock_group1_id, {"user_ids": [mock_user_id2]})

@patch('backend.open_webui.routers.scim_groups.Users')
@patch('backend.open_webui.routers.scim_groups.Groups')
def test_patch_group_add_member(MockGroups, MockUsers, client):
    # Initial group has mock_user_id1. Add mock_user_id2.
    group_with_added_member = create_mock_group_model(id=mock_group1_id, name=mock_group1_name, user_ids=[mock_user_id1, mock_user_id2])

    MockGroups.get_group_by_id.side_effect = [mock_group1, group_with_added_member]
    MockGroups.update_group_by_id.return_value = group_with_added_member
    MockUsers.get_users_by_user_ids.return_value = [mock_user1, mock_user2]

    patch_payload = {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
        "Operations": [{"op": "add", "path": "members", "value": [{"value": mock_user_id2}]}]
    }
    response = client.patch(f"/scim/v2/Groups/{mock_group1_id}", headers=HEADERS, json=patch_payload)
    assert response.status_code == 200
    data = response.json()
    assert len(data["members"]) == 2
    member_ids_returned = {m["value"] for m in data["members"]}
    assert mock_user_id1 in member_ids_returned
    assert mock_user_id2 in member_ids_returned
    MockGroups.update_group_by_id.assert_called_once_with(mock_group1_id, {"user_ids": list(member_ids_returned)})


@patch('backend.open_webui.routers.scim_groups.Users')
@patch('backend.open_webui.routers.scim_groups.Groups')
def test_patch_group_remove_member(MockGroups, MockUsers, client):
    # Initial group has mock_user_id1 and mock_user_id2. Remove mock_user_id1.
    group_with_removed_member = create_mock_group_model(id=mock_group2_id, name=mock_group2_name, user_ids=[mock_user_id2])

    MockGroups.get_group_by_id.side_effect = [mock_group2, group_with_removed_member]
    MockGroups.update_group_by_id.return_value = group_with_removed_member
    MockUsers.get_users_by_user_ids.return_value = [mock_user2]

    patch_payload = {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
        "Operations": [{"op": "remove", "path": f'members[value eq "{mock_user_id1}"]'}]
    }
    response = client.patch(f"/scim/v2/Groups/{mock_group2_id}", headers=HEADERS, json=patch_payload)
    assert response.status_code == 200
    data = response.json()
    assert len(data["members"]) == 1
    assert data["members"][0]["value"] == mock_user_id2
    MockGroups.update_group_by_id.assert_called_once_with(mock_group2_id, {"user_ids": [mock_user_id2]})


# DELETE /Groups/{id}
@patch('backend.open_webui.routers.scim_groups.Groups')
def test_delete_group_success(MockGroups, client):
    MockGroups.get_group_by_id.return_value = mock_group1
    MockGroups.delete_group_by_id.return_value = True

    response = client.delete(f"/scim/v2/Groups/{mock_group1_id}", headers=HEADERS)
    assert response.status_code == 204
    MockGroups.delete_group_by_id.assert_called_once_with(mock_group1_id)

@patch('backend.open_webui.routers.scim_groups.Groups')
def test_delete_group_not_found(MockGroups, client):
    MockGroups.get_group_by_id.return_value = None
    non_existent_id = str(uuid.uuid4())
    response = client.delete(f"/scim/v2/Groups/{non_existent_id}", headers=HEADERS)
    assert response.status_code == 404

# TODO: Add more tests for:
# - PUT: displayName conflict
# - PATCH: displayName update, more complex member operations, error cases for values/paths
# - Error response structure for all relevant 4xx/5xx errors.
# - Pagination edge cases for GET /Groups.
# - What happens if Users.get_users_by_user_ids returns fewer users than in group.user_ids.This is a good start for the SCIM Group endpoint tests. I've created the file `backend/open_webui/test/routers/test_scim_groups_router.py` with the structure and initial tests you've outlined.

The key elements are:
-   **`client` fixture**: This sets up the `TestClient` and crucially patches `ENABLE_SCIM` and `SCIM_TOKEN` for the duration of the test module. This ensures the app loads the SCIM routes and that authentication can be tested.
-   **Mock Data**: Helper functions `create_mock_user_model` and `create_mock_group_model` are defined to generate consistent test data.
-   **Authentication Tests**: Basic checks for no token are included. More extensive auth tests (invalid token, SCIM disabled) are assumed to be in `test_scim_users_router.py` and would apply similarly if the `client` fixture is robust.
-   **Endpoint Tests**:
    -   **GET /Groups**: Covers empty list, basic pagination, and `displayName` filtering.
    -   **POST /Groups**: Covers successful creation, conflict on `displayName`, and the case where no admin user is found to be an owner.
    -   **GET /Groups/{id}**: Covers finding a group and not finding a group.
    -   **PUT /Groups/{id}**: Covers successful replacement of group details.
    -   **PATCH /Groups/{id}**: Covers replacing all members, adding a member, and removing a specific member by path.
    -   **DELETE /Groups/{id}**: Covers successful deletion and not finding a group.
-   **Mocking**: Uses `@patch` extensively for `Groups` and `Users` model methods.
-   **Error Handling**: Checks for correct HTTP status codes and, where appropriate, the SCIM error schema (`schemas: [ERROR_URN]`, `scimType`).

This forms a solid foundation for testing the SCIM Group functionality. More detailed tests for edge cases in PATCH operations, advanced filtering (if implemented), and specific error conditions can be added incrementally.

I will now submit this as completed.
