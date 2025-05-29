import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, ANY
import uuid

# Assuming the main FastAPI app instance is in backend.open_webui.main
# We need to ensure SCIM routers are loaded and config is mocked *before* TestClient uses the app
# This might require careful setup or a fixture that configures the app state for SCIM

from backend.open_webui.main import app  # Main FastAPI application
from backend.open_webui.models.users import UserModel
from backend.open_webui.models.auths import AuthsModel # Assuming AuthsModel exists for type hinting if needed
from backend.open_webui.models.scim_schemas import (
    USER_SCHEMA_URN, 
    LIST_RESPONSE_URN, 
    ERROR_URN,
    SCIMUser,
    SCIMName,
    SCIMEmail,
    SCIMMeta,
    SCIMPatchOp
)
from backend.open_webui.config import ENABLE_SCIM, SCIM_TOKEN

# Test SCIM Token
VALID_SCIM_TOKEN = "test_scim_token_12345"
INVALID_SCIM_TOKEN = "invalid_scim_token_67890"
HEADERS = {"Authorization": f"Bearer {VALID_SCIM_TOKEN}"}
INVALID_HEADERS = {"Authorization": f"Bearer {INVALID_SCIM_TOKEN}"}
NO_AUTH_HEADERS = {}

@pytest.fixture(scope="module")
def client():
    # Temporarily set SCIM config for testing
    # This needs to affect the app instance that TestClient uses.
    # A common pattern is to have a factory for the app or modify app.state directly.
    
    # Patch the config singletons directly where they are imported/used by the app
    # This is more robust than trying to modify app.state after TestClient is initialized,
    # as dependencies might have already captured the original values.

    with patch.object(ENABLE_SCIM, 'value', True), \
         patch.object(SCIM_TOKEN, 'value', VALID_SCIM_TOKEN):
        
        # If your app conditionally loads routers based on ENABLE_SCIM.value at import time of main.py,
        # you might need to reload modules or ensure TestClient picks up a fresh app instance.
        # For now, assuming TestClient(app) uses the live app state which should reflect patched values
        # if PersistentConfig objects are truly singletons and their .value is dynamic.
        
        # If routers are added in main.py's lifespan or based on app.state.config.ENABLE_SCIM
        # then we need to ensure this state is set correctly when TestClient initializes the app.
        # FastAPI's TestClient typically creates a fresh app instance or uses the one passed.
        # We will assume that the main.py has already been modified to include the SCIM routers
        # if ENABLE_SCIM.value is True (which we are patching here).
        
        # To be absolutely sure the app reflects these patched values for SCIM router inclusion:
        # One approach is to have a global app fixture that re-imports/re-configures app if needed.
        # For this subtask, we'll rely on the patching affecting the app instance used by TestClient.
        # If main.py uses app.state.config.ENABLE_SCIM to add routers, we need to ensure app.state.config is updated.
        # The PersistentConfig system *should* mean that ENABLE_SCIM.value reflects the patched value.
        
        test_app_client = TestClient(app)
        yield test_app_client


# --- Mock Data ---
def create_mock_user_model(id: str, email: str, name: str, role: str = "user", created_at=None, updated_at=None) -> UserModel:
    return UserModel(
        id=id,
        email=email,
        name=name,
        role=role,
        profile_image_url="/static/favicon.png",
        created_at=created_at or 1670000000.0, # Example timestamp
        updated_at=updated_at or 1670000000.0,
        settings=None, # Or some default dict
        api_key=None,
        last_active_at=None,
        info=None,
        organization_id=None,
        pending_email=None,
        referral_code=None,
        company=None,
        website=None,
        phone_number=None
    )

mock_user1_id = str(uuid.uuid4())
mock_user1_email = "user1@example.com"
mock_user1_name = "User One"
mock_user1 = create_mock_user_model(id=mock_user1_id, email=mock_user1_email, name=mock_user1_name)

mock_user2_id = str(uuid.uuid4())
mock_user2_email = "user2@example.com"
mock_user2_name = "User Two"
mock_user2_active_false_role = "pending" # 'active: false' maps to 'pending'
mock_user2 = create_mock_user_model(id=mock_user2_id, email=mock_user2_email, name=mock_user2_name, role=mock_user2_active_false_role)


# --- Test Cases ---

# Authentication and Authorization Tests
def test_get_users_no_token(client):
    response = client.get("/scim/v2/Users", headers=NO_AUTH_HEADERS)
    assert response.status_code == 401
    data = response.json()
    assert data["schemas"] == [ERROR_URN]
    assert "Not authenticated" in data["detail"] # Or specific detail from scim_auth verify_scim_request

def test_get_users_invalid_token(client):
    response = client.get("/scim/v2/Users", headers=INVALID_HEADERS)
    assert response.status_code == 401
    data = response.json()
    assert data["schemas"] == [ERROR_URN]
    assert "Invalid token" in data["detail"]

def test_get_users_scim_disabled(client):
    with patch.object(ENABLE_SCIM, 'value', False):
        response = client.get("/scim/v2/Users", headers=HEADERS)
    assert response.status_code == 403 # Forbidden
    data = response.json()
    assert data["schemas"] == [ERROR_URN]
    assert "SCIM is not enabled" in data["detail"]


# GET /Users
@patch('backend.open_webui.routers.scim_users.Users')
def test_get_users_empty(MockUsers, client):
    MockUsers.get_users.return_value = []
    
    response = client.get("/scim/v2/Users", headers=HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data["schemas"] == [LIST_RESPONSE_URN]
    assert data["totalResults"] == 0
    assert data["startIndex"] == 1
    assert data["itemsPerPage"] == 0
    assert data["Resources"] == []

@patch('backend.open_webui.routers.scim_users.Users')
def test_get_users_list_with_pagination(MockUsers, client):
    MockUsers.get_users.return_value = [mock_user1, mock_user2]
    
    # Test with default count (100), expecting 2 results
    response = client.get("/scim/v2/Users?startIndex=1&count=5", headers=HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data["totalResults"] == 2
    assert data["startIndex"] == 1
    assert data["itemsPerPage"] == 2
    assert len(data["Resources"]) == 2
    assert data["Resources"][0]["userName"] == mock_user1_email
    assert data["Resources"][1]["userName"] == mock_user2_email

    # Test pagination: get first user
    response = client.get("/scim/v2/Users?startIndex=1&count=1", headers=HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data["totalResults"] == 2
    assert data["itemsPerPage"] == 1
    assert len(data["Resources"]) == 1
    assert data["Resources"][0]["userName"] == mock_user1_email

    # Test pagination: get second user
    response = client.get("/scim/v2/Users?startIndex=2&count=1", headers=HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data["totalResults"] == 2
    assert data["itemsPerPage"] == 1
    assert len(data["Resources"]) == 1
    assert data["Resources"][0]["userName"] == mock_user2_email

@patch('backend.open_webui.routers.scim_users.Users')
def test_get_users_filter_username(MockUsers, client):
    MockUsers.get_users.return_value = [mock_user1, mock_user2] # Mock all users
    
    # The router's current filter implementation is basic and Python-side after fetching all
    response = client.get(f'/scim/v2/Users?filter=userName eq "{mock_user1_email}"', headers=HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data["totalResults"] == 1
    assert len(data["Resources"]) == 1
    assert data["Resources"][0]["userName"] == mock_user1_email

    response = client.get(f'/scim/v2/Users?filter=userName eq "nonexistent@example.com"', headers=HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data["totalResults"] == 0
    assert len(data["Resources"]) == 0

@patch('backend.open_webui.routers.scim_users.Users')
def test_get_users_unsupported_filter(MockUsers, client):
    MockUsers.get_users.return_value = [mock_user1]
    response = client.get(f'/scim/v2/Users?filter=displayName eq "Some Name"', headers=HEADERS)
    assert response.status_code == 501 # SCIMNotImplementedError
    data = response.json()
    assert data["schemas"] == [ERROR_URN]
    assert data["scimType"] == "notImplemented"


# POST /Users
@patch('backend.open_webui.routers.scim_users.Auths')
@patch('backend.open_webui.routers.scim_users.Users')
def test_create_user_success(MockUsers, MockAuths, client):
    new_user_id = str(uuid.uuid4())
    new_user_email = "newuser@example.com"
    new_user_name_given = "New"
    new_user_name_family = "User"
    new_user_name_formatted = f"{new_user_name_given} {new_user_name_family}"

    MockUsers.get_user_by_email.return_value = None # No existing user
    
    # Mock what Auths.insert_new_auth returns (usually the user object or True/False)
    # For this test, let's assume it returns a representation of the auth entry, or we mock the subsequent Users.get_user_by_id
    mock_created_user_model = create_mock_user_model(id=new_user_id, email=new_user_email, name=new_user_name_formatted)
    MockAuths.insert_new_auth.return_value = True # Or some representation of the created auth
    MockUsers.get_user_by_id.return_value = mock_created_user_model

    scim_payload = {
        "schemas": [USER_SCHEMA_URN],
        "userName": new_user_email,
        "name": {
            "givenName": new_user_name_given,
            "familyName": new_user_name_family,
            "formatted": new_user_name_formatted
        },
        "active": True,
        "emails": [{"value": new_user_email, "primary": True, "type": "work"}]
    }

    response = client.post("/scim/v2/Users", headers=HEADERS, json=scim_payload)
    
    assert response.status_code == 201
    data = response.json()
    assert data["userName"] == new_user_email
    assert data["id"] == new_user_id # If ID is taken from payload (if provided) or generated and returned
    assert data["active"] == True
    assert data["name"]["formatted"] == new_user_name_formatted
    assert response.headers["Location"].endswith(f"/scim/v2/Users/{new_user_id}")

    MockAuths.insert_new_auth.assert_called_once_with(
        id=ANY, # ID could be generated by router if not in payload
        email=new_user_email,
        name=new_user_name_formatted,
        hashed_password=ANY, # Password is auto-generated
        role="user", # Derived from active: True
        profile_image_url=ANY
    )

@patch('backend.open_webui.routers.scim_users.Users')
def test_create_user_conflict(MockUsers, client):
    MockUsers.get_user_by_email.return_value = mock_user1 # User already exists
    
    scim_payload = {
        "schemas": [USER_SCHEMA_URN],
        "userName": mock_user1_email, # Existing email
        "name": {"formatted": mock_user1_name},
        "active": True
    }
    response = client.post("/scim/v2/Users", headers=HEADERS, json=scim_payload)
    assert response.status_code == 409 # Conflict
    data = response.json()
    assert data["schemas"] == [ERROR_URN]
    assert data["scimType"] == "uniqueness"

def test_create_user_missing_username(client):
    scim_payload = { "schemas": [USER_SCHEMA_URN], "name": {"formatted": "Test User"} }
    response = client.post("/scim/v2/Users", headers=HEADERS, json=scim_payload)
    # Pydantic validation should catch this if userName is not Optional in SCIMUser schema
    # If SCIMUser model allows optional userName, then the router logic should catch it
    assert response.status_code == 400 # Bad Request (or 422 if Pydantic validation error not caught by custom handler)
    # The custom handler might catch FastAPI's RequestValidationError and reformat it.
    # For now, assuming a SCIMBadRequestError is raised from endpoint logic.
    data = response.json()
    assert data["schemas"] == [ERROR_URN]
    assert "userName is a required field" in data["detail"] # Or Pydantic's validation message


# GET /Users/{id}
@patch('backend.open_webui.routers.scim_users.Users')
def test_get_user_by_id_found(MockUsers, client):
    MockUsers.get_user_by_id.return_value = mock_user1
    
    response = client.get(f"/scim/v2/Users/{mock_user1_id}", headers=HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == mock_user1_id
    assert data["userName"] == mock_user1_email

@patch('backend.open_webui.routers.scim_users.Users')
def test_get_user_by_id_not_found(MockUsers, client):
    MockUsers.get_user_by_id.return_value = None
    non_existent_id = str(uuid.uuid4())
    response = client.get(f"/scim/v2/Users/{non_existent_id}", headers=HEADERS)
    assert response.status_code == 404
    data = response.json()
    assert data["schemas"] == [ERROR_URN]
    assert data["scimType"] == "notFound"


# PUT /Users/{id}
@patch('backend.open_webui.routers.scim_users.Auths') # For potential password updates
@patch('backend.open_webui.routers.scim_users.Users')
def test_replace_user_success(MockUsers, MockAuths, client):
    updated_name = "User One Updated"
    updated_email = "user1_updated@example.com"

    # Original user state
    MockUsers.get_user_by_id.side_effect = [
        mock_user1, # First call for initial check
        create_mock_user_model(id=mock_user1_id, email=updated_email, name=updated_name, role=mock_user1.role) # Call after update
    ]
    # Mock for email conflict check (if email changes)
    MockUsers.get_user_by_email.return_value = None 
    # Mock for update operation
    MockUsers.update_user_by_id.return_value = create_mock_user_model(
        id=mock_user1_id, email=updated_email, name=updated_name, role=mock_user1.role
    )
    # Mock for password update (if implemented and tested)
    MockAuths.update_user_password_by_id.return_value = True


    scim_payload_put = {
        "schemas": [USER_SCHEMA_URN],
        "id": mock_user1_id,
        "userName": updated_email,
        "name": {"formatted": updated_name, "givenName": "User", "familyName": "One Updated"},
        "active": True, # Assuming role "user"
        "emails": [{"value": updated_email, "primary": True}]
    }

    response = client.put(f"/scim/v2/Users/{mock_user1_id}", headers=HEADERS, json=scim_payload_put)
    assert response.status_code == 200
    data = response.json()
    assert data["userName"] == updated_email
    assert data["name"]["formatted"] == updated_name
    assert data["active"] == True

    MockUsers.update_user_by_id.assert_called_once_with(
        mock_user1_id, 
        {"email": updated_email, "name": updated_name, "role": "user"} # Role derived from active: True
    )

@patch('backend.open_webui.routers.scim_users.Users')
def test_replace_user_not_found(MockUsers, client):
    MockUsers.get_user_by_id.return_value = None
    non_existent_id = str(uuid.uuid4())
    scim_payload_put = {"schemas": [USER_SCHEMA_URN], "userName": "test@example.com", "active": True}
    response = client.put(f"/scim/v2/Users/{non_existent_id}", headers=HEADERS, json=scim_payload_put)
    assert response.status_code == 404

# PATCH /Users/{id}
@patch('backend.open_webui.routers.scim_users.Users')
def test_patch_user_active_status(MockUsers, client):
    # Initial state: user is active (role='user')
    # After patch: user becomes inactive (role='pending')
    initial_user = create_mock_user_model(id=mock_user1_id, email=mock_user1_email, name=mock_user1_name, role="user")
    patched_user_model = create_mock_user_model(id=mock_user1_id, email=mock_user1_email, name=mock_user1_name, role="pending")

    MockUsers.get_user_by_id.side_effect = [initial_user, patched_user_model] # First call, then call after update
    MockUsers.update_user_by_id.return_value = patched_user_model

    patch_payload = {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
        "Operations": [{"op": "replace", "path": "active", "value": False}]
    }
    response = client.patch(f"/scim/v2/Users/{mock_user1_id}", headers=HEADERS, json=patch_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["active"] == False # Reflects updated state
    MockUsers.update_user_by_id.assert_called_once_with(mock_user1_id, {"role": "pending"})


@patch('backend.open_webui.routers.scim_users.Users')
def test_patch_user_unsupported_op(MockUsers, client):
    MockUsers.get_user_by_id.return_value = mock_user1
    patch_payload = {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
        "Operations": [{"op": "add", "path": "displayName", "value": "New Name"}] # 'add' for displayName might not be fully supported
    }
    response = client.patch(f"/scim/v2/Users/{mock_user1_id}", headers=HEADERS, json=patch_payload)
    assert response.status_code == 501 # Not Implemented for 'add' op
    data = response.json()
    assert data["scimType"] == "notImplemented"

# DELETE /Users/{id}
@patch('backend.open_webui.routers.scim_users.Auths')
@patch('backend.open_webui.routers.scim_users.Users')
def test_delete_user_success(MockUsers, MockAuths, client):
    MockUsers.get_user_by_id.return_value = mock_user1
    MockAuths.delete_auth_by_id.return_value = True # Assume successful deletion

    response = client.delete(f"/scim/v2/Users/{mock_user1_id}", headers=HEADERS)
    assert response.status_code == 204
    MockAuths.delete_auth_by_id.assert_called_once_with(mock_user1_id)

@patch('backend.open_webui.routers.scim_users.Users')
def test_delete_user_not_found(MockUsers, client):
    MockUsers.get_user_by_id.return_value = None
    non_existent_id = str(uuid.uuid4())
    response = client.delete(f"/scim/v2/Users/{non_existent_id}", headers=HEADERS)
    assert response.status_code == 404

@patch('backend.open_webui.routers.scim_users.Auths')
@patch('backend.open_webui.routers.scim_users.Users')
def test_delete_user_auth_deletion_fails(MockUsers, MockAuths, client):
    MockUsers.get_user_by_id.return_value = mock_user1
    MockAuths.delete_auth_by_id.return_value = False # Simulate failure

    response = client.delete(f"/scim/v2/Users/{mock_user1_id}", headers=HEADERS)
    assert response.status_code == 500 # Internal Server Error
    data = response.json()
    assert data["scimType"] == "internalServerError"
    assert "Auth record could not be deleted" in data["detail"]

# TODO: Add more tests for:
# - PUT: userName conflict, other updatable fields
# - PATCH: more operations (replace userName with conflict), different paths, error cases for value types
# - Error response structure for all relevant 4xx/5xx errors to ensure SCIMError format.
# - Test SCIMListResponse for pagination edge cases (e.g., startIndex out of bounds, count=0)
# - Test cases where Users.update_user_by_id or Auths.insert_new_auth return None/False unexpectedly.
