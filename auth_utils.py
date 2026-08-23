from typing import Any, Mapping, Optional


def is_valid_activation_key(
    value: Optional[str], expected_activation_key: Optional[str]
) -> bool:
    """Return whether a supplied activation key matches the configured key."""
    return value is not None and value == expected_activation_key


def is_valid_activation_request(
    payload: Any, expected_activation_key: Optional[str]
) -> bool:
    """Validate an activation key carried in a JSON-like request payload."""
    if not isinstance(payload, Mapping):
        return False
    return is_valid_activation_key(payload.get("activationKey"), expected_activation_key)
