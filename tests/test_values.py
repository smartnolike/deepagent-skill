"""Runtime-generated values for credential-related test inputs.

Keeping these values non-literal makes it explicit that tests never contain a
reusable credential and avoids triggering secret scanners on test fixtures.
"""

from secrets import token_urlsafe


TEST_API_KEY = token_urlsafe(32)
TEST_AUTH_TOKEN = token_urlsafe(32)
TEST_PASSWORD = token_urlsafe(32)
TEST_SECRET = token_urlsafe(32)


def new_test_secret_reference() -> str:
    """Create a valid-looking, non-reusable Secret Manager version reference."""
    return "/".join(("projects", token_urlsafe(12), "secrets", token_urlsafe(12), "versions", "1"))


TEST_SECRET_REFERENCE = new_test_secret_reference()
