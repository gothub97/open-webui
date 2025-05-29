from fastapi import HTTPException
# SCIMError model is not directly used in this file for constructing responses,
# but good to note its relevance for the handlers that will use these exceptions.
# from backend.open_webui.models.scim_schemas import SCIMError 

class SCIMBadRequestError(HTTPException):
    def __init__(self, detail: str, scim_type: str = "invalidValue"):
        super().__init__(status_code=400, detail=detail)
        self.scim_type = scim_type

class SCIMUnauthorizedError(HTTPException):
    def __init__(self, detail: str = "Authentication failed or is missing.", scim_type: str = "unauthorized"):
        # SCIM spec doesn't explicitly define 'unauthorized' as a scimType, 
        # but it's a common practice. 'invalidCredentials' could also be used.
        super().__init__(status_code=401, detail=detail)
        self.scim_type = scim_type

class SCIMForbiddenError(HTTPException):
    def __init__(self, detail: str = "Operation forbidden.", scim_type: str = "forbidden"):
        super().__init__(status_code=403, detail=detail)
        self.scim_type = scim_type

class SCIMNotFoundError(HTTPException):
    def __init__(self, detail: str, scim_type: str = "notFound"): # Or no default scim_type if always specific
        super().__init__(status_code=404, detail=detail)
        self.scim_type = scim_type

class SCIMConflictError(HTTPException):
    def __init__(self, detail: str, scim_type: str = "uniqueness"): # 'uniqueness' is common for conflicts
        super().__init__(status_code=409, detail=detail)
        self.scim_type = scim_type

class SCIMPreconditionFailedError(HTTPException):
    def __init__(self, detail: str = "Precondition failed (e.g., ETag mismatch).", scim_type: str = "preconditionFailed"):
        super().__init__(status_code=412, detail=detail)
        self.scim_type = scim_type

class SCIMInternalServerError(HTTPException):
    def __init__(self, detail: str = "An internal server error occurred.", scim_type: str = "internalServerError"):
        super().__init__(status_code=500, detail=detail)
        self.scim_type = scim_type

class SCIMNotImplementedError(HTTPException):
    def __init__(self, detail: str = "Feature not implemented.", scim_type: str = "notImplemented"):
        super().__init__(status_code=501, detail=detail)
        self.scim_type = scim_type
