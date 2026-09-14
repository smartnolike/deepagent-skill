"""Runtime-generated values for credential-related test inputs.

Keeping these values non-literal makes it explicit that tests never contain a
reusable credential and avoids triggering secret scanners on test fixtures.
"""

from secrets import token_urlsafe


TEST_API_KEY = token_urlsafe(32)
TEST_AUTH_TOKEN = token_urlsafe(32)
TEST_PASSWORD = token_urlsafe(32)
TEST_SECRET = token_urlsafe(32)
TEST_SECRET_REFERENCE = f"projects/test-project/secrets/test-{token_urlsafe(16)}/versions/1"
