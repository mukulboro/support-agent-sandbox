import pytest

from app.mock_api.mock_api import MockAPIError, mock_request


@pytest.mark.parametrize("path,count", [("/employer/e1/employees", 21), ("/vendors", 8), ("/vendor-invoices", 25)])
def test_list_endpoints(path, count):
    res = mock_request.get(path)
    assert res["message"] == "Success" and len(res["data"]) == count


@pytest.mark.parametrize("path,key,value", [
    ("/employer/e1/employee/emp-03100", "employee_id", "emp-03100"),
    ("/vendor-invoices/vinv-2041", "invoice_id", "vinv-2041"),
    ("/transactions/txn-88401", "status", "SETTLED"),
])
def test_detail_endpoints(path, key, value):
    assert mock_request.get(path)["data"][key] == value


@pytest.mark.parametrize("path", ["/transactions/nope", "/payroll", "/vendors/"])
def test_not_found(path):
    with pytest.raises(MockAPIError) as e:
        mock_request.get(path)
    assert e.value.status == 404
