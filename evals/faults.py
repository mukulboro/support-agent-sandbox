from app.mock_api.mock_api import MockAPIError


class FaultyAPI:
    """Wraps the mock API and fails every path that starts with one of the given prefixes, to test tool failures."""

    def __init__(self, api, failures: dict[str, int]):
        self.api = api
        self.failures = failures  # path prefix -> http status to fail with

    def get(self, path: str) -> dict:
        for prefix, status in self.failures.items():
            if path.startswith(prefix):
                raise MockAPIError(status, "Injected failure")
        return self.api.get(path)
