"""Test the constants for Dali Center integration."""
from PySrDaliGateway.const import DOMAIN


def test_domain_constant():
    """Test that the DOMAIN constant is correctly defined."""
    assert DOMAIN == "dali_center"
    assert isinstance(DOMAIN, str)
