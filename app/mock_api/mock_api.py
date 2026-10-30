"""In-process mock of the Niural API: `mock_request.get("/vendors")` returns the fixture envelope."""
import json
import re
from pathlib import Path

DATA = Path(__file__).parent / "data"


class MockAPIError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"{status} {message}")
        self.status, self.message = status, message


class MockAPI:
    def __init__(self, data_dir: Path = DATA):
        # (compiled path regex, fixture) per "METHOD /path/{param}" key
        self.routes = []
        for f in data_dir.glob("*.json"):
            for key, fixture in json.loads(f.read_text()).items():
                method, template = key.split(" ", 1)
                pattern = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", template)
                self.routes.append((method, re.compile(f"^{pattern}$"), fixture))

    def get(self, path: str) -> dict:
        for method, pattern, fixture in self.routes:
            if method != "GET" or not (m := pattern.match(path)):
                continue
            if "_records" not in fixture:
                return fixture
            # the detail id is always the last path parameter; employer_id is ignored (single employer)
            record = fixture["_records"].get(list(m.groupdict().values())[-1])
            if record is None:
                raise MockAPIError(404, "Not found")
            return record
        raise MockAPIError(404, "Unknown route")


mock_request = MockAPI()
