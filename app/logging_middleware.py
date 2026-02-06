import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware that logs HTTP requests in a structured JSON format.
    
    Logs include:
    - message: HTTP request details (client IP, method, path, status code)
    - attributes: log level
    - tags: project, environment, service, deployment, replica IDs from environment variables
    - timestamp: ISO 8601 timestamp with timezone
    """
    
    def __init__(self, app: ASGIApp):
        super().__init__(app)
        # Read tags from environment variables
        self.tags = {
            "project": os.getenv("PROJECT_ID", ""),
            "environment": os.getenv("ENVIRONMENT_ID", ""),
            "service": os.getenv("SERVICE_ID", ""),
            "deployment": os.getenv("DEPLOYMENT_ID", ""),
            "replica": os.getenv("REPLICA_ID", ""),
        }
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process the request and log it in structured format.
        """
        # Get client IP address
        client_ip = request.client.host if request.client else "unknown"
        client_port = request.client.port if request.client else 0
        
        # Process the request
        response = await call_next(request)
        
        # Map status codes to phrases
        status_phrases = {
            200: "OK",
            201: "Created",
            204: "No Content",
            400: "Bad Request",
            401: "Unauthorized",
            403: "Forbidden",
            404: "Not Found",
            500: "Internal Server Error",
            502: "Bad Gateway",
            503: "Service Unavailable",
        }
        status_phrase = status_phrases.get(response.status_code, "")
        
        # Build the log message
        message = f"INFO:     {client_ip}:{client_port} - \"{request.method} {request.url.path} HTTP/1.1\" {response.status_code} {status_phrase}"
        
        # Create structured log entry
        log_entry = {
            "message": message,
            "attributes": {
                "level": "info"
            },
            "tags": self.tags,
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        }
        
        # Log as JSON
        logger.info(json.dumps(log_entry))
        
        return response
