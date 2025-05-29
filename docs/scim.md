# SCIM Provisioning

Open WebUI supports SCIM (System for Cross-domain Identity Management) version 2.0 for automated user and group provisioning. This allows Identity Providers (IdPs) like Azure AD, Okta, etc., to manage user and group identities within Open WebUI.

## Enabling SCIM

To enable SCIM, you need to configure the following environment variables:

*   **`ENABLE_SCIM=True`**: This variable activates the SCIM feature and its endpoints.
*   **`SCIM_TOKEN="your_secure_token_here"`**: This variable sets the Bearer token that IdPs must use to authenticate their requests to the SCIM API. **Important**: This token should be a strong, randomly generated secret, and kept confidential.

These variables are typically set in your `.env` file if running locally, or as environment variables in your Docker container or deployment environment.

```env
# Example .env configuration
ENABLE_SCIM=True
SCIM_TOKEN="a_very_strong_and_secret_random_string_!@#$%^&*"
```

## SCIM Endpoints

The base URL for all SCIM v2 endpoints in Open WebUI is:
`/scim/v2`

For example, if your Open WebUI instance is hosted at `https://open.webui.example.com`, the full SCIM base URL would be `https://open.webui.example.com/scim/v2`.

### Supported Endpoints:

*   **Users**: `/scim/v2/Users`
    *   **Operations**: `GET` (list, get by ID), `POST` (create), `PUT` (replace), `PATCH` (partial update), `DELETE`
*   **Groups**: `/scim/v2/Groups`
    *   **Operations**: `GET` (list, get by ID), `POST` (create), `PUT` (replace), `PATCH` (partial update), `DELETE`
*   **ServiceProviderConfig**: `/scim/v2/ServiceProviderConfig`
    *   Provides information about the SCIM capabilities of Open WebUI (e.g., supported operations, authentication methods).
*   **ResourceTypes**: `/scim/v2/ResourceTypes`
    *   Describes the types of resources available (User and Group) and their SCIM endpoints and schema URNs.
*   **Schemas**: `/scim/v2/Schemas`
    *   Provides the attribute schemas for User and Group resources, detailing their structure, data types, and characteristics.

## Supported Features (from ServiceProviderConfig)

Open WebUI's SCIM implementation currently supports the following:

*   **Patch Operation (`PATCH`)**: Supported for users and groups.
    *   For Users: Supports updating the `active` status and `userName`.
    *   For Groups: Supports updating `displayName` and managing `members` (add, remove, replace).
*   **Filtering (`filter`)**: Basic support is available.
    *   For Users: `userName eq "value"`
    *   For Groups: `displayName eq "value"`
*   **Bulk Operations**: Not supported.
*   **Sorting**: Not supported.
*   **ETag**: Not supported.
*   **Change Password**: Not supported via SCIM (passwords are typically managed by the IdP or set initially by the system).

Refer to the `/scim/v2/ServiceProviderConfig` endpoint for the most up-to-date details on supported features.

## Authentication

*   Requests to the SCIM User (`/scim/v2/Users`) and Group (`/scim/v2/Groups`) endpoints **must** include an `Authorization` header with a Bearer token:
    ```
    Authorization: Bearer <your_SCIM_TOKEN>
    ```
    Replace `<your_SCIM_TOKEN>` with the value you configured for the `SCIM_TOKEN` environment variable.

*   The metadata endpoints (`/ServiceProviderConfig`, `/ResourceTypes`, `/Schemas`) are **unauthenticated** and can be accessed without an Authorization header, as per common SCIM practice.

## Basic IdP Integration Notes

When configuring your Identity Provider (IdP) for SCIM provisioning with Open WebUI, you will typically need the following:

*   **Tenant URL / SCIM Endpoint**: This is the base URL for the SCIM API. For Open WebUI, it will be:
    `https://your-open-webui-instance-url/scim/v2`
    (Replace `https://your-open-webui-instance-url` with the actual URL of your Open WebUI deployment).

*   **Secret Token**: This is the value you set for the `SCIM_TOKEN` environment variable.

*   **Attribute Mappings**: Your IdP will require you to map its internal user and group attributes to the standard SCIM attributes. Common mappings include:
    *   **Users**:
        *   IdP `userPrincipalName` or `email` -> SCIM `userName` (this is the primary identifier for login)
        *   IdP `givenName` -> SCIM `name.givenName`
        *   IdP `surname` or `lastName` -> SCIM `name.familyName`
        *   IdP `displayName` -> SCIM `displayName` or `name.formatted`
        *   IdP user active status -> SCIM `active` (boolean)
    *   **Groups**:
        *   IdP group name -> SCIM `displayName`
        *   IdP group members -> SCIM `members`

    Ensure your IdP is configured to use the correct SCIM attribute names as defined by the `/scim/v2/Schemas` endpoint (e.g., `urn:ietf:params:scim:schemas:core:2.0:User` and `urn:ietf:params:scim:schemas:core:2.0:Group`).

    Refer to your IdP's documentation for specific instructions on configuring SCIM provisioning and attribute mappings.
