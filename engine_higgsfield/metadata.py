"""Identity constants. Standard library only.

The TUI imports this module, not ``engine.py``, so reading the provider's
display name never pulls in the provider's SDK.
"""

PROVIDER_NAME = "Higgsfield"
PROVIDER_HOMEPAGE = "https://higgsfield.ai"
PLATFORM = "higgsfield"
API_KEY_ENV_VAR = "HIGGSFIELD_API_KEY"
API_KEY_PATTERN = r".+"
