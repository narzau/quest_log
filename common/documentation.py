import logging
from typing import Any, Dict, List, Optional, Sequence, Type, Union, cast

from fastapi import FastAPI, Depends
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ApiExample:
    """Container for API examples that can be attached to endpoints"""
    
    def __init__(
        self,
        request_example: Optional[Dict[str, Any]] = None,
        response_example: Optional[Dict[str, Any]] = None,
        summary: Optional[str] = None,
        description: Optional[str] = None,
    ):
        self.request_example = request_example
        self.response_example = response_example
        self.summary = summary
        self.description = description


class APIDocumentation:
    """
    Enhanced API documentation generator for FastAPI applications
    
    Provides improved OpenAPI schema with:
    - Custom examples for requests and responses
    - Better organization with tags
    - Extended descriptions
    - Security scheme documentation
    """
    
    def __init__(
        self,
        app: FastAPI,
        title: str,
        description: str,
        version: str,
        terms_of_service: Optional[str] = None,
        contact: Optional[Dict[str, str]] = None,
        license_info: Optional[Dict[str, str]] = None,
    ):
        self.app = app
        self.title = title
        self.description = description
        self.version = version
        self.terms_of_service = terms_of_service
        self.contact = contact
        self.license_info = license_info
        self.examples: Dict[str, Dict[str, ApiExample]] = {}
        self.tag_descriptions: Dict[str, str] = {}
        
        # Override the default OpenAPI schema generator
        self._setup_custom_openapi()
    
    def _setup_custom_openapi(self):
        """Replace the default OpenAPI schema generator with our enhanced version"""
        
        def custom_openapi():
            if self.app.openapi_schema:
                return self.app.openapi_schema
            
            openapi_schema = get_openapi(
                title=self.title,
                version=self.version,
                description=self.description,
                routes=self.app.routes,
            )
            
            # Add terms of service, contact, and license info
            if self.terms_of_service:
                openapi_schema["info"]["termsOfService"] = self.terms_of_service
            
            if self.contact:
                openapi_schema["info"]["contact"] = self.contact
            
            if self.license_info:
                openapi_schema["info"]["license"] = self.license_info
            
            # Add tag descriptions
            if self.tag_descriptions:
                openapi_schema["tags"] = [
                    {"name": name, "description": desc}
                    for name, desc in self.tag_descriptions.items()
                ]
            
            # Add examples to paths
            for path, path_item in openapi_schema.get("paths", {}).items():
                for method, operation in path_item.items():
                    operation_id = operation.get("operationId")
                    if operation_id in self.examples:
                        for content_type, example in self.examples[operation_id].items():
                            # Add request examples
                            if example.request_example and "requestBody" in operation:
                                for media_type in operation["requestBody"].get("content", {}).values():
                                    if "examples" not in media_type:
                                        media_type["examples"] = {}
                                    
                                    media_type["examples"][content_type] = {
                                        "summary": example.summary or "Example request",
                                        "description": example.description or "",
                                        "value": example.request_example,
                                    }
                            
                            # Add response examples
                            if example.response_example:
                                for status_code, response in operation.get("responses", {}).items():
                                    for media_type in response.get("content", {}).values():
                                        if "examples" not in media_type:
                                            media_type["examples"] = {}
                                        
                                        media_type["examples"][content_type] = {
                                            "summary": example.summary or "Example response",
                                            "description": example.description or "",
                                            "value": example.response_example,
                                        }
            
            self.app.openapi_schema = openapi_schema
            return self.app.openapi_schema
        
        # Replace the app's openapi function
        self.app.openapi = custom_openapi
    
    def add_example(
        self,
        path: str,
        method: str,
        content_type: str,
        example: ApiExample,
    ):
        """
        Add an example for a specific endpoint
        
        Args:
            path: API path e.g. "/users/{user_id}"
            method: HTTP method in lowercase e.g. "get", "post"
            content_type: Content type identifier e.g. "default", "error"
            example: ApiExample object with request/response examples
        """
        # Generate a unique operation ID based on path and method
        operation_id = f"{method.lower()}_{path}"
        
        # Normalize operation ID
        operation_id = operation_id.replace("/", "_").replace("{", "").replace("}", "").replace("-", "_")
        
        if operation_id not in self.examples:
            self.examples[operation_id] = {}
        
        self.examples[operation_id][content_type] = example
    
    def add_tag_description(self, tag: str, description: str):
        """
        Add a description for a tag
        
        Args:
            tag: Tag name
            description: Tag description
        """
        self.tag_descriptions[tag] = description


def setup_documentation(
    app: FastAPI,
    title: str,
    description: str,
    version: str,
    terms_of_service: Optional[str] = None,
    contact: Optional[Dict[str, str]] = None,
    license_info: Optional[Dict[str, str]] = None,
) -> APIDocumentation:
    """
    Set up enhanced API documentation for a FastAPI application
    
    Args:
        app: FastAPI application
        title: API title
        description: API description
        version: API version
        terms_of_service: URL to terms of service
        contact: Contact information dict with keys like "name", "url", "email"
        license_info: License information dict with keys like "name", "url"
    
    Returns:
        APIDocumentation instance that can be used to add examples and tag descriptions
    """
    return APIDocumentation(
        app=app,
        title=title,
        description=description,
        version=version,
        terms_of_service=terms_of_service,
        contact=contact,
        license_info=license_info,
    )


def example_response(
    status_code: int,
    content: Optional[Type[BaseModel]] = None,
    description: Optional[str] = None,
    examples: Optional[Dict[str, Dict[str, Union[str, Dict[str, Any]]]]] = None,
):
    """
    Create a response example for OpenAPI documentation
    
    Args:
        status_code: HTTP status code
        content: Pydantic model for response
        description: Response description
        examples: Dictionary of examples in OpenAPI format
    
    Returns:
        Dictionary suitable for FastAPI response documentation
    """
    response_dict = {"model": content} if content else {}
    
    if description:
        response_dict["description"] = description
    
    if examples:
        response_dict["examples"] = examples
    
    return {status_code: response_dict}


def document_endpoint(
    summary: str,
    description: str,
    response_description: str,
    tags: List[str],
    responses: Optional[Dict[int, Dict[str, Any]]] = None,
    deprecated: bool = False,
    operation_id: Optional[str] = None,
):
    """
    Create a dictionary of FastAPI parameters for well-documented endpoints
    
    Usage:
        @app.get("/users/{user_id}", **document_endpoint(
            summary="Get user details",
            description="Retrieve detailed information about a user by their ID",
            response_description="User details retrieved successfully",
            tags=["Users"],
            responses={404: {"description": "User not found"}}
        ))
        async def get_user(user_id: int):
            ...
    
    Args:
        summary: Short summary of what the endpoint does
        description: Detailed description of the endpoint
        response_description: Description of successful response
        tags: List of tags for categorizing the endpoint
        responses: Dictionary of possible responses other than the default 200
        deprecated: Whether the endpoint is deprecated
        operation_id: Unique identifier for the operation
    
    Returns:
        Dictionary of parameters for a FastAPI endpoint
    """
    result = {
        "summary": summary,
        "description": description,
        "response_description": response_description,
        "tags": tags,
        "deprecated": deprecated,
    }
    
    if responses:
        result["responses"] = responses
    
    if operation_id:
        result["operation_id"] = operation_id
    
    return result 