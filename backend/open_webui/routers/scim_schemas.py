from fastapi import APIRouter, Request, Path
from pydantic import BaseModel, Field, HttpUrl
from typing import List, Dict, Any, Optional, Union

from backend.open_webui.models.scim_schemas import (
    SCIMUser, 
    SCIMGroup, 
    USER_SCHEMA_URN, 
    GROUP_SCHEMA_URN, 
    LIST_RESPONSE_URN
)
from backend.open_webui.utils.scim_utils import get_scim_base_url
from backend.open_webui.utils.scim_exceptions import SCIMNotFoundError

# Attempt Pydantic v2 import, fallback to v1 style if necessary
try:
    from pydantic.json_schema import model_json_schema 
    PYDANTIC_V2 = True
except ImportError:
    PYDANTIC_V2 = False

# SCIM Schema URN
SCHEMA_SCHEMA_URN = "urn:ietf:params:scim:schemas:core:2.0:Schema"

class SCIMSchemaAttribute(BaseModel):
    name: str
    type: str  # "string", "complex", "boolean", "decimal", "integer", "dateTime", "reference"
    multiValued: bool = False
    description: Optional[str] = None
    required: bool = False
    caseExact: bool = False
    mutability: str = "readWrite"  # "readOnly", "readWrite", "immutable", "writeOnly"
    returned: str = "default"  # "always", "never", "default", "request"
    uniqueness: str = "none"  # "none", "server", "global"
    subAttributes: Optional[List['SCIMSchemaAttribute']] = None # For complex types
    referenceTypes: Optional[List[str]] = None # For reference types

class SCIMSchemaMeta(BaseModel):
    resourceType: str = "Schema"
    location: HttpUrl

class SCIMSchemaDefinition(BaseModel):
    schemas: List[str] = Field(default_factory=lambda: [SCHEMA_SCHEMA_URN])
    id: str  # Schema URN (e.g., USER_SCHEMA_URN)
    name: str
    description: Optional[str] = None
    attributes: List[SCIMSchemaAttribute]
    meta: SCIMSchemaMeta


class SCIMListResponseForSchemas(BaseModel):
    schemas: List[str] = Field(default_factory=lambda: [LIST_RESPONSE_URN])
    totalResults: int
    startIndex: int
    itemsPerPage: int
    Resources: List[SCIMSchemaDefinition] = Field(default_factory=list)


def pydantic_type_to_scim_type(pydantic_type: str, pydantic_format: Optional[str] = None) -> str:
    """Converts Pydantic property types to SCIM attribute types."""
    if pydantic_type == "string":
        if pydantic_format == "date-time":
            return "dateTime"
        return "string"
    elif pydantic_type == "integer":
        return "integer"
    elif pydantic_type == "number":
        return "decimal"
    elif pydantic_type == "boolean":
        return "boolean"
    elif pydantic_type == "array" or pydantic_type == "object": # Array of simple types or complex objects
        return "complex" # SCIM uses 'complex' for objects and arrays of objects/values. MultiValued handles array aspect.
    # Add more mappings as needed, e.g. for reference types if they can be inferred
    return "string" # Default fallback

def convert_properties_to_scim_attributes(
    properties: Dict[str, Any], 
    required_list: Optional[List[str]] = None,
    definitions: Optional[Dict[str, Any]] = None # For resolving $ref in Pydantic v2
) -> List[SCIMSchemaAttribute]:
    """
    Basic converter from Pydantic JSON schema properties to SCIM attributes.
    This is a simplified version and might need significant enhancement for full compliance.
    """
    attributes = []
    required_set = set(required_list or [])

    for name, prop_schema in properties.items():
        # Resolve $ref if present (common in Pydantic v2 for nested models)
        if "$ref" in prop_schema and definitions:
            ref_path = prop_schema["$ref"].split('/')
            ref_name = ref_path[-1]
            if ref_name in definitions:
                prop_schema = definitions[ref_name] # Replace with the resolved schema
            else:
                # Could not resolve $ref, skip or handle error
                continue 
        
        # Handle 'anyOf' for optional fields (common in Pydantic v2 for Optional[Type])
        # We take the first non-null type definition.
        if 'anyOf' in prop_schema:
            actual_prop_schema = next((s for s in prop_schema['anyOf'] if s.get('type') != 'null'), None)
            if actual_prop_schema:
                prop_schema = actual_prop_schema
            else: # Only null type, or unhandled structure
                prop_schema = {"type": "string"} # Fallback for unhandled anyOf

        # Handle 'allOf' for combining schemas (e.g. with a $ref)
        if 'allOf' in prop_schema and definitions:
            combined_props = {}
            for item in prop_schema['allOf']:
                if '$ref' in item:
                    ref_path = item["$ref"].split('/')
                    ref_name = ref_path[-1]
                    if ref_name in definitions:
                        # Deep merge properties and requirements if necessary
                        # For simplicity, this example might just use the referenced schema's properties
                        # A true merge would be more complex.
                        resolved_schema = definitions[ref_name]
                        # This is a simplification; true merging is more involved.
                        # We'll assume the $ref is the primary source of type info for now.
                        if 'properties' in resolved_schema : # If it's a complex type itself
                             prop_schema.update(resolved_schema) # Update current prop_schema
                        else: # If it's a simple type with a $ref
                            prop_schema.update({"type": resolved_schema.get("type", "string")})


        pydantic_type = prop_schema.get("type", "string") # Default to string if type not present
        pydantic_format = prop_schema.get("format")
        
        scim_type = pydantic_type_to_scim_type(pydantic_type, pydantic_format)
        multi_valued = pydantic_type == "array"
        
        sub_attributes = None
        if scim_type == "complex" and not multi_valued and "properties" in prop_schema: # Single complex object
            sub_attributes = convert_properties_to_scim_attributes(
                prop_schema["properties"], 
                prop_schema.get("required"),
                definitions # Pass definitions for nested resolution
            )
        elif multi_valued and "items" in prop_schema:
            item_schema = prop_schema["items"]
            # Resolve $ref for items if present
            if "$ref" in item_schema and definitions:
                ref_path = item_schema["$ref"].split('/')
                ref_name = ref_path[-1]
                if ref_name in definitions:
                    item_schema = definitions[ref_name]
            
            if item_schema.get("type") == "object" and "properties" in item_schema:
                 sub_attributes = convert_properties_to_scim_attributes(
                    item_schema["properties"], 
                    item_schema.get("required"),
                    definitions
                )
            # If it's an array of simple types, subAttributes remain None, SCIM type is just 'string' etc.
            # but multiValued is true. The SCIM type should reflect the item type.
            # This part needs refinement for arrays of simple types vs arrays of complex types.
            # For now, if items are objects, they become subAttributes. Otherwise, it's a multi-valued simple type.
            # SCIM usually defines a complex type with sub-attributes for multi-valued attributes like 'emails'.
            # This logic here is simplified. 'emails' in SCIM is a complex multi-valued attribute.

        # Default mutability, returned, uniqueness etc. These can be refined
        # based on conventions or extended Pydantic schema info if available.
        attr = SCIMSchemaAttribute(
            name=name,
            type=scim_type,
            multiValued=multi_valued,
            description=prop_schema.get("description", prop_schema.get("title")), # Use title if desc not present
            required=name in required_set,
            mutability="readWrite", # Default, can be more specific
            # caseExact, returned, uniqueness can be set based on model conventions
        )
        if sub_attributes:
            attr.subAttributes = sub_attributes
        
        attributes.append(attr)
    return attributes

def pydantic_schema_to_scim_schema(
    pydantic_model_cls, 
    schema_urn: str, 
    name: str, 
    description: str, 
    base_scim_url: str
) -> SCIMSchemaDefinition:
    
    if PYDANTIC_V2:
        # For Pydantic v2, model_json_schema includes definitions for nested models in '$defs'
        # We need to pass these definitions to convert_properties_to_scim_attributes
        # The ref_template can be customized if needed, default is usually fine.
        json_schema = model_json_schema(pydantic_model_cls, ref_template="#/$defs/{model}")
        definitions = json_schema.get("$defs", {})
    else: # Pydantic v1
        json_schema = pydantic_model_cls.schema()
        definitions = json_schema.get("definitions", {}) # v1 uses "definitions"

    # The main properties of the model itself
    properties = json_schema.get("properties", {})
    required_list = json_schema.get("required", [])
    
    scim_attributes = convert_properties_to_scim_attributes(properties, required_list, definitions)
    
    return SCIMSchemaDefinition(
        id=schema_urn,
        name=name,
        description=description,
        attributes=scim_attributes,
        meta=SCIMSchemaMeta(
            location=HttpUrl(f"{base_scim_url}/Schemas/{schema_urn}", scheme="http") if base_scim_url.startswith("http:") else HttpUrl(f"{base_scim_url}/Schemas/{schema_urn}", scheme="https")
        )
    )

router = APIRouter(
    prefix="/Schemas", 
    tags=["SCIM Schemas"]
)

_USER_SCIM_SCHEMA_CACHE = None
_GROUP_SCIM_SCHEMA_CACHE = None

@router.get("", response_model=SCIMListResponseForSchemas, response_model_exclude_none=True)
async def get_schemas(request: Request) -> SCIMListResponseForSchemas:
    global _USER_SCIM_SCHEMA_CACHE, _GROUP_SCIM_SCHEMA_CACHE
    base_scim_url = get_scim_base_url(request)

    if not _USER_SCIM_SCHEMA_CACHE:
        _USER_SCIM_SCHEMA_CACHE = pydantic_schema_to_scim_schema(
            SCIMUser, USER_SCHEMA_URN, "User", "SCIM User Schema", base_scim_url
        )
    # Update location for current request context if base_url can change per request (e.g. different host)
    # For simplicity, assuming base_url from first call is fine for cache, or regenerate meta if needed.
    _USER_SCIM_SCHEMA_CACHE.meta.location = HttpUrl(f"{base_scim_url}/Schemas/{USER_SCHEMA_URN}", scheme="http") if base_scim_url.startswith("http:") else HttpUrl(f"{base_scim_url}/Schemas/{USER_SCHEMA_URN}", scheme="https")


    if not _GROUP_SCIM_SCHEMA_CACHE:
        _GROUP_SCIM_SCHEMA_CACHE = pydantic_schema_to_scim_schema(
            SCIMGroup, GROUP_SCHEMA_URN, "Group", "SCIM Group Schema", base_scim_url
        )
    _GROUP_SCIM_SCHEMA_CACHE.meta.location = HttpUrl(f"{base_scim_url}/Schemas/{GROUP_SCHEMA_URN}", scheme="http") if base_scim_url.startswith("http:") else HttpUrl(f"{base_scim_url}/Schemas/{GROUP_SCHEMA_URN}", scheme="https")
    
    resources = [_USER_SCIM_SCHEMA_CACHE, _GROUP_SCIM_SCHEMA_CACHE]
    
    return SCIMListResponseForSchemas(
        totalResults=len(resources),
        startIndex=1,
        itemsPerPage=len(resources),
        Resources=resources
    )

@router.get("/{schema_id:path}", response_model=SCIMSchemaDefinition, response_model_exclude_none=True)
async def get_schema_by_id(request: Request, schema_id: str = Path(..., description="URN of the schema to retrieve")) -> SCIMSchemaDefinition:
    global _USER_SCIM_SCHEMA_CACHE, _GROUP_SCIM_SCHEMA_CACHE
    base_scim_url = get_scim_base_url(request)
    
    # Ensure schema_id is treated as a full URN
    if schema_id == USER_SCHEMA_URN:
        if not _USER_SCIM_SCHEMA_CACHE:
             _USER_SCIM_SCHEMA_CACHE = pydantic_schema_to_scim_schema(
                SCIMUser, USER_SCHEMA_URN, "User", "SCIM User Schema", base_scim_url
            )
        _USER_SCIM_SCHEMA_CACHE.meta.location = HttpUrl(f"{base_scim_url}/Schemas/{USER_SCHEMA_URN}", scheme="http") if base_scim_url.startswith("http:") else HttpUrl(f"{base_scim_url}/Schemas/{USER_SCHEMA_URN}", scheme="https")
        return _USER_SCIM_SCHEMA_CACHE
    elif schema_id == GROUP_SCHEMA_URN:
        if not _GROUP_SCIM_SCHEMA_CACHE:
            _GROUP_SCIM_SCHEMA_CACHE = pydantic_schema_to_scim_schema(
                SCIMGroup, GROUP_SCHEMA_URN, "Group", "SCIM Group Schema", base_scim_url
            )
        _GROUP_SCIM_SCHEMA_CACHE.meta.location = HttpUrl(f"{base_scim_url}/Schemas/{GROUP_SCHEMA_URN}", scheme="http") if base_scim_url.startswith("http:") else HttpUrl(f"{base_scim_url}/Schemas/{GROUP_SCHEMA_URN}", scheme="https")
        return _GROUP_SCIM_SCHEMA_CACHE
    else:
        raise SCIMNotFoundError(f"Schema with ID '{schema_id}' not found.")
