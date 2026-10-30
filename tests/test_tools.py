import json

import pytest

from app.agents.agents import load_api_tools
from app.mock_api.mock_api import mock_request
from app.tools.tools import ToolDispatcher


@pytest.fixture
def dispatcher():
    return ToolDispatcher(mock_request, load_api_tools())


def run(dispatcher, tool, **args):
    return dispatcher.run(tool, json.dumps(args))


def test_there_are_six_tools(dispatcher):
    assert [s["function"]["name"] for s in dispatcher.schemas()] == [
        "list_employees", "get_employee", "list_vendors", "list_vendor_invoices", "get_vendor_invoice", "get_transaction",
    ]


def test_active_employee_count_is_by_status(dispatcher):
    assert run(dispatcher, "list_employees", status=["ONBOARDED"])["output"]["count"] == 16


def test_new_york_is_the_state_not_just_the_city(dispatcher):
    assert run(dispatcher, "list_employees", state="NY")["output"]["count"] == 6  # includes Brooklyn
    assert run(dispatcher, "list_employees", city="New York")["output"]["count"] == 4


def test_name_filter_matches_first_or_last_name(dispatcher):
    assert run(dispatcher, "list_employees", name="priya")["output"]["count"] == 1
    assert run(dispatcher, "list_employees", name="Priya Raghunathan")["output"]["count"] == 1


def test_counts_by_status_are_computed_in_code(dispatcher):
    assert run(dispatcher, "list_employees")["output"]["count_by_status"] == {
        "ONBOARDED": 16, "PENDING_ONBOARDING": 3, "DISMISSED": 2,
    }
    assert run(dispatcher, "list_vendor_invoices", vendor_name="Orrery")["output"]["count_by_status"] == {
        "OVERDUE": 2, "PENDING_APPROVAL": 1, "PAID": 1,
    }


def test_overdue_bills(dispatcher):
    assert run(dispatcher, "list_vendor_invoices", status=["OVERDUE"])["output"]["count"] == 5


def test_amount_owed_to_a_vendor_is_summed_in_code(dispatcher):
    output = run(dispatcher, "list_vendor_invoices", vendor_name="Orrery",
                 status=["OVERDUE", "PENDING_APPROVAL", "SCHEDULED"])["output"]
    assert output["count"] == 3
    assert output["total_by_currency"] == {"USD": 3480.0}


def test_filters_that_match_nothing_are_not_an_error(dispatcher):
    result = run(dispatcher, "list_vendors", name="does not exist")
    assert result["ok"] and result["output"] == {"count": 0, "items": []}


def test_detail_endpoint_and_its_source(dispatcher):
    employee_id = run(dispatcher, "list_employees", name="Marisol")["output"]["items"][0]["employee_id"]
    result = run(dispatcher, "get_employee", employee_id=employee_id)
    assert result["ok"] and result["endpoint"] == f"GET /employer/current/employee/{employee_id}"
    assert "onboarding" in result["output"]


def test_errors_come_back_as_results(dispatcher):
    assert run(dispatcher, "get_transaction", transaction_id="txn-nope") == {
        "endpoint": "GET /transactions/txn-nope", "ok": False, "output": {"error": "404 Not found"},
    }
    assert not run(dispatcher, "get_transaction")["ok"]  # missing argument
    assert not run(dispatcher, "delete_everything")["ok"]  # unknown tool
    assert not dispatcher.run("list_vendors", "{not json")["ok"]
