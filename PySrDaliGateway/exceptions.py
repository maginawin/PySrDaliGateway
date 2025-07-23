"""Custom exceptions for DALI Gateway operations"""

from typing import Optional


class DaliGatewayError(Exception):
    """Base exception for DALI Gateway operations"""

    def __init__(
        self, message: str, gateway_sn: Optional[str] = None,
        error_code: Optional[str] = None
    ):
        super().__init__(message)
        self.gateway_sn = gateway_sn
        self.error_code = error_code


class DaliConnectionError(DaliGatewayError):
    """Raised when MQTT connection to gateway fails"""


class AuthenticationError(DaliGatewayError):
    """Raised when authentication with gateway fails"""


class DiscoveryError(DaliGatewayError):
    """Raised when gateway discovery fails"""


class NetworkError(DaliGatewayError):
    """Raised when network-related errors occur"""


class DaliTimeoutError(DaliGatewayError):
    """Raised when operations timeout"""
