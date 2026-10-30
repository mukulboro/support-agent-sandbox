import json

from app.mock_api.mock_api import MockAPI, MockAPIError

EMPLOYER = "current"  # the mock serves a single employer and ignores this id


class ToolDispatcher:
    """Runs the model's tool calls against the API. Filtering, counting and summing happen here, not in the LLM."""

    def __init__(self, api: MockAPI, definitions: list[dict]):
        self.api = api
        self.definitions = definitions  # from api_tools.yaml

    def schemas(self) -> list[dict]:
        """The tool definitions in the format OpenAI expects."""
        return [
            {
                "type": "function",
                "function": {"name": d["name"], "description": d["description"].strip(), "parameters": d["parameters"]},
            }
            for d in self.definitions
        ]

    def run(self, name: str, arguments: str) -> dict:
        """Returns {"endpoint": "GET /path" or None, "ok": bool, "output": dict}. Never raises."""
        try:
            args = json.loads(arguments or "{}")
        except ValueError:
            return self.failed(None, "arguments were not valid JSON")

        try:
            match name:
                case "list_employees":
                    return self.fetch_list(f"/employer/{EMPLOYER}/employees", args, {
                        "status": lambda e, wanted: e["status"] in wanted,
                        "employment_type": lambda e, wanted: e["employment_type"] == wanted,
                        "department": lambda e, wanted: e["department"].lower() == wanted.lower(),
                        "state": lambda e, wanted: e["work_location"]["state"] == wanted.upper(),
                        "city": lambda e, wanted: wanted.lower() in e["work_location"]["city"].lower(),
                        "name": lambda e, wanted: wanted.lower() in f"{e['first_name']} {e['last_name']}".lower(),
                    })
                case "get_employee":
                    return self.fetch_one(f"/employer/{EMPLOYER}/employee/{args['employee_id']}")
                case "list_vendors":
                    return self.fetch_list("/vendors", args, {
                        "name": lambda v, wanted: wanted.lower() in v["name"].lower(),
                    })
                case "list_vendor_invoices":
                    return self.fetch_list("/vendor-invoices", args, {
                        "status": lambda i, wanted: i["status"] in wanted,
                        "vendor_name": lambda i, wanted: wanted.lower() in i["vendor_name"].lower(),
                        "invoice_number": lambda i, wanted: i["invoice_number"].lower() == wanted.lower(),
                    })
                case "get_vendor_invoice":
                    return self.fetch_one(f"/vendor-invoices/{args['invoice_id']}")
                case "get_transaction":
                    return self.fetch_one(f"/transactions/{args['transaction_id']}")
                case _:
                    return self.failed(None, f"unknown tool {name}")
        except KeyError as missing:  # a required argument was left out
            return self.failed(None, f"missing argument {missing}")

    def fetch_one(self, path: str) -> dict:
        """Detail endpoints: return the record as is."""
        try:
            data = self.api.get(path)["data"]
        except MockAPIError as error:
            return self.failed(f"GET {path}", f"{error.status} {error.message}")
        return {"endpoint": f"GET {path}", "ok": True, "output": data}

    def fetch_list(self, path: str, args: dict, filters: dict) -> dict:
        """List endpoints: apply the filters the model asked for, then add a count and totals."""
        try:
            items = self.api.get(path)["data"]
        except MockAPIError as error:
            return self.failed(f"GET {path}", f"{error.status} {error.message}")

        for name, wanted in args.items():
            if name in filters:
                items = [item for item in items if filters[name](item, wanted)]

        output = {"count": len(items), "items": items}
        if items and all("status" in item for item in items):
            by_status: dict[str, int] = {}
            for item in items:
                by_status[item["status"]] = by_status.get(item["status"], 0) + 1
            output["count_by_status"] = by_status
        if items and all("amount" in item for item in items):
            totals = {}
            for item in items:
                totals[item["currency"]] = round(totals.get(item["currency"], 0) + item["amount"], 2)
            output["total_by_currency"] = totals
        return {"endpoint": f"GET {path}", "ok": True, "output": output}

    def failed(self, endpoint: str | None, message: str) -> dict:
        return {"endpoint": endpoint, "ok": False, "output": {"error": message}}
