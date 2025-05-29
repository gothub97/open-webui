import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from backend.open_webui.main import app # Main FastAPI application
from backend.open_webui.models.scim_schemas import (
    USER_SCHEMA_URN, 
    GROUP_SCHEMA_URN, 
    LIST_RESPONSE_URN, 
    ERROR_URN,
    SERVICE_PROVIDER_CONFIG_URN,
    RESOURCE_TYPE_SCHEMA_URN,
    SCHEMA_SCHEMA_URN
)
from backend.open_webui.config import ENABLE_SCIM, SCIM_TOKEN # SCIM_TOKEN not strictly needed for these tests

# Mock base URL for SCIM meta.location fields
MOCK_SCIM_BASE_URL = "http://localhost:8080/scim/v2"

@pytest.fixture(scope="module")
def client():
    # Patch SCIM configuration and the get_scim_base_url utility
    # For metadata endpoints, token is not strictly necessary but ENABLE_SCIM is.
    with patch.object(ENABLE_SCIM, 'value', True), \
         patch.object(SCIM_TOKEN, 'value', "mock_token_for_metadata_if_needed_by_any_shared_dep"), \
         patch('backend.open_webui.utils.scim_utils.get_scim_base_url', return_value=MOCK_SCIM_BASE_URL), \
         patch('backend.open_webui.routers.scim_service_provider_config.get_scim_base_url', return_value=MOCK_SCIM_BASE_URL, create=True,  errors='ignore'), \
         patch('backend.open_webui.routers.scim_resource_types.get_scim_base_url', return_value=MOCK_SCIM_BASE_URL, create=True,  errors='ignore'), \
         patch('backend.open_webui.routers.scim_schemas.get_scim_base_url', return_value=MOCK_SCIM_BASE_URL, create=True, errors='ignore'):
        
        # The patches for get_scim_base_url in each router module are needed because
        # the routers might have imported the function directly, not via a shared context.
        # `create=True` allows patching even if the name doesn't exist (e.g., if it was already refactored out)
        # `errors='ignore'` helps if the path is slightly off or refactored, but can mask issues.
        # More robust would be to ensure all routers use a consistently imported `get_scim_base_url`.
        # For this test, we assume `get_scim_base_url` is used by these routers for `meta.location`.

        test_app_client = TestClient(app)
        yield test_app_client

# --- Test Cases for /ServiceProviderConfig ---
def test_get_service_provider_config(client):
    response = client.get("/scim/v2/ServiceProviderConfig")
    assert response.status_code == 200
    data = response.json()

    assert data["schemas"] == [SERVICE_PROVIDER_CONFIG_URN]
    assert data["patch"]["supported"] == True
    assert data["bulk"]["supported"] == False
    assert data["filter"]["supported"] == True
    assert data["filter"]["maxResults"] == 100
    assert data["changePassword"]["supported"] == False
    assert data["sort"]["supported"] == False
    assert data["etag"]["supported"] == False
    
    assert len(data["authenticationSchemes"]) == 1
    auth_scheme = data["authenticationSchemes"][0]
    assert auth_scheme["type"] == "oauthbearertoken"
    assert auth_scheme["name"] == "Bearer Token"
    assert auth_scheme["primary"] == True
    
    assert data["meta"]["resourceType"] == "ServiceProviderConfig"
    # Location check depends on how get_scim_base_url is mocked/used.
    # If get_scim_base_url in the router is not patched, request.url will be used.
    # For this test, we are not mocking get_scim_base_url inside the router itself,
    # but assuming the router uses the utility from scim_utils which *is* patched.
    # If the router directly constructs URL from request, this check might be more complex.
    # However, the ServiceProviderConfig router constructs location from request.url directly.
    assert "ServiceProviderConfig" in data["meta"]["location"] 


# --- Test Cases for /ResourceTypes ---
def test_get_resource_types(client):
    response = client.get("/scim/v2/ResourceTypes")
    assert response.status_code == 200
    data = response.json()

    assert data["schemas"] == [LIST_RESPONSE_URN]
    assert data["totalResults"] == 2
    assert data["itemsPerPage"] == 2
    assert len(data["Resources"]) == 2

    user_rt = next((r for r in data["Resources"] if r["id"] == "User"), None)
    group_rt = next((r for r in data["Resources"] if r["id"] == "Group"), None)

    assert user_rt is not None
    assert user_rt["name"] == "User"
    assert user_rt["endpoint"] == "/Users"
    assert user_rt["schema"] == USER_SCHEMA_URN
    assert user_rt["meta"]["resourceType"] == "ResourceType"
    assert user_rt["meta"]["location"] == f"{MOCK_SCIM_BASE_URL}/ResourceTypes/User"

    assert group_rt is not None
    assert group_rt["name"] == "Group"
    assert group_rt["endpoint"] == "/Groups"
    assert group_rt["schema"] == GROUP_SCHEMA_URN
    assert group_rt["meta"]["resourceType"] == "ResourceType"
    assert group_rt["meta"]["location"] == f"{MOCK_SCIM_BASE_URL}/ResourceTypes/Group"

def test_get_resource_type_user(client):
    response = client.get("/scim/v2/ResourceTypes/User")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "User"
    assert data["schema"] == USER_SCHEMA_URN
    assert data["meta"]["location"] == f"{MOCK_SCIM_BASE_URL}/ResourceTypes/User"

def test_get_resource_type_group(client):
    response = client.get("/scim/v2/ResourceTypes/Group")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "Group"
    assert data["schema"] == GROUP_SCHEMA_URN
    assert data["meta"]["location"] == f"{MOCK_SCIM_BASE_URL}/ResourceTypes/Group"

def test_get_resource_type_invalid(client):
    response = client.get("/scim/v2/ResourceTypes/InvalidType")
    assert response.status_code == 404
    data = response.json()
    assert data["schemas"] == [ERROR_URN]
    assert data["scimType"] == "notFound"


# --- Test Cases for /Schemas ---
def test_get_schemas(client):
    response = client.get("/scim/v2/Schemas")
    assert response.status_code == 200
    data = response.json()

    assert data["schemas"] == [LIST_RESPONSE_URN]
    assert data["totalResults"] == 2 # User and Group schemas
    assert data["itemsPerPage"] == 2
    assert len(data["Resources"]) == 2

    user_schema = next((s for s in data["Resources"] if s["id"] == USER_SCHEMA_URN), None)
    group_schema = next((s for s in data["Resources"] if s["id"] == GROUP_SCHEMA_URN), None)

    assert user_schema is not None
    assert user_schema["name"] == "User"
    assert user_schema["meta"]["resourceType"] == "Schema"
    assert user_schema["meta"]["location"] == f"{MOCK_SCIM_BASE_URL}/Schemas/{USER_SCHEMA_URN}"
    assert any(attr["name"] == "userName" for attr in user_schema["attributes"])

    assert group_schema is not None
    assert group_schema["name"] == "Group"
    assert group_schema["meta"]["resourceType"] == "Schema"
    assert group_schema["meta"]["location"] == f"{MOCK_SCIM_BASE_URL}/Schemas/{GROUP_SCHEMA_URN}"
    assert any(attr["name"] == "displayName" for attr in group_schema["attributes"])


def test_get_schema_user(client):
    response = client.get(f"/scim/v2/Schemas/{USER_SCHEMA_URN}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == USER_SCHEMA_URN
    assert data["name"] == "User"
    assert data["meta"]["location"] == f"{MOCK_SCIM_BASE_URL}/Schemas/{USER_SCHEMA_URN}"
    # Check a few key attributes
    assert any(attr["name"] == "userName" and attr["required"] == True for attr in data["attributes"])
    assert any(attr["name"] == "emails" and attr["multiValued"] == True for attr in data["attributes"])
    name_attr = next((attr for attr in data["attributes"] if attr["name"] == "name"), None)
    assert name_attr is not None
    assert name_attr["type"] == "complex"
    assert any(sub_attr["name"] == "familyName" for sub_attr in name_attr["subAttributes"])


def test_get_schema_group(client):
    response = client.get(f"/scim/v2/Schemas/{GROUP_SCHEMA_URN}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == GROUP_SCHEMA_URN
    assert data["name"] == "Group"
    assert data["meta"]["location"] == f"{MOCK_SCIM_BASE_URL}/Schemas/{GROUP_SCHEMA_URN}"
    assert any(attr["name"] == "displayName" and attr["required"] == True for attr in data["attributes"])
    assert any(attr["name"] == "members" and attr["multiValued"] == True for attr in data["attributes"])

def test_get_schema_invalid(client):
    invalid_urn = "urn:ietf:params:scim:schemas:core:2.0:Invalid"
    response = client.get(f"/scim/v2/Schemas/{invalid_urn}")
    assert response.status_code == 404
    data = response.json()
    assert data["schemas"] == [ERROR_URN]
    assert data["scimType"] == "notFound"

# General Checks: Content-Type
# FastAPI TestClient usually handles content-type correctly based on response model.
# For explicit check, one might inspect response.headers['content-type'].
# The custom SCIM exception handlers set "application/scim+json".
# Successful responses from these metadata endpoints will be "application/json" by default
# from JSONResponse unless explicitly changed in the router. This is generally fine.

def test_error_content_type(client):
    response = client.get("/scim/v2/ResourceTypes/InvalidType") # Known 404
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/scim+json"

def test_success_content_type_service_provider_config(client):
    response = client.get("/scim/v2/ServiceProviderConfig")
    assert response.status_code == 200
    assert "application/json" in response.headers["content-type"] # Default for JSONResponse

def test_success_content_type_resource_types(client):
    response = client.get("/scim/v2/ResourceTypes")
    assert response.status_code == 200
    assert "application/json" in response.headers["content-type"]

def test_success_content_type_schemas(client):
    response = client.get("/scim/v2/Schemas")
    assert response.status_code == 200
    assert "application/json" in response.headers["content-type"]
