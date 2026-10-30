# Niural mock API — endpoint reference

Six read-only endpoints covering the **Employees** tab and **Niural Pay**. Fixtures for
each live in `./data`, keyed by `"METHOD /path"`.

All data is invented. Response shapes follow the real platform's conventions so that work
built against this mock transfers to the real API.

---

## Conventions

**Envelope.** Every response wraps its payload:

```json
{ "message": "Success", "data": <object or array> }
```

**Authentication.** Requests carry the signed-in user's token. The mock accepts any
non-empty value.

```
Authorization: <token>
```

**List vs detail.** List endpoints return a *summary* of each record. Fields like an
employee's compensation and onboarding checklist, or an invoice's approval chain, appear
only on the by-id endpoint. Expect to call the list first to resolve a name to an id, then
the detail endpoint.

**Fixture layout.** Detail endpoints are stored as a `_records` map keyed by id:

```json
{
  "GET /vendor-invoices/{invoice_id}": {
    "_records": { "vinv-2041": { "message": "Success", "data": { ... } } }
  }
}
```

A mock server looks up the path parameter in `_records` and returns the matching value,
or a 404 when absent. Keys beginning with `_` are fixture scaffolding, not API fields.

**Dates** are `YYYY-MM-DD`. The dataset is built as though today is **2026-09-28**.

---

## 1. List employees

```
GET /employer/{employer_id}/employees
```

Every worker on the employer's roster — 21 records. Returns an array.

| Field | Type | Notes |
|---|---|---|
| `employee_id` | string | `emp-#####` |
| `first_name`, `last_name` | string | |
| `work_email` | string | |
| `job_title` | string | |
| `department` | string | Engineering, Sales, Finance, Product, People, Support, Operations, Design, Marketing |
| `employment_type` | enum | `EMPLOYEE`, `US_1099_CONTRACTOR` |
| `status` | enum | `ONBOARDED`, `PENDING_ONBOARDING`, `DISMISSED` |
| `start_date` | date | May be in the future for a new hire |
| `work_location` | object | `{ city, state, country_iso2 }` — `state` is null outside the US |
| `manager_name` | string \| null | null for people with no manager |

`status` is what most questions turn on: only `ONBOARDED` workers are payable.
`PENDING_ONBOARDING` means hired with paperwork outstanding; `DISMISSED` means offboarded.

**Fixture:** `data/employees.json`

## 2. Get employee

```
GET /employer/{employer_id}/employee/{employee_id}
```

One worker, with everything from the summary plus:

| Field | Type | Notes |
|---|---|---|
| `compensation` | object | `{ amount, currency, frequency }` — `ANNUAL` for employees, `HOURLY` for contractors |
| `manager` | object \| null | `{ employee_id, name, job_title }` |
| `payroll_eligible` | boolean | True only when `status` is `ONBOARDED` |
| `onboarding` | object | `{ complete, completed_steps, total_steps, steps[] }` |
| `onboarding.steps[]` | array | `{ name, status, completed_date }`; a pending step also carries `blocked_on` and `note` |
| `dismissal` | object \| null | `{ dismissal_date, final_pay_date, reason }` when dismissed |

A pending onboarding step names who it is `blocked_on` — `EMPLOYER` or `EMPLOYEE` — which
is usually the actual answer to "why isn't this person set up yet".

**Fixture:** `data/employees.json` → `_records`

## 3. List vendors

```
GET /vendors
```

Vendors set up in Niural Pay — 8 records. Returns an array.

| Field | Type | Notes |
|---|---|---|
| `vendor_id` | string | `ven-####` |
| `name`, `email` | string | |
| `status` | enum | `ACTIVE` |
| `default_currency` | string | |
| `payment_method` | enum | `ACH`, `WIRE` |
| `payment_terms_days` | integer | Net terms |
| `address` | object | `{ city, country_iso2 }` |

**Fixture:** `data/vendors.json`

## 4. List vendor invoices

```
GET /vendor-invoices
```

Bills owed to vendors — 25 records spanning several months. Returns an array.

| Field | Type | Notes |
|---|---|---|
| `invoice_id` | string | `vinv-####` |
| `invoice_number` | string | `INV-####` — the number people actually quote |
| `vendor_id`, `vendor_name` | string | |
| `amount`, `currency` | number, string | |
| `status` | enum | `PAID`, `OVERDUE`, `PENDING_APPROVAL`, `SCHEDULED` |
| `issue_date`, `due_date` | date | |
| `paid_date` | date \| null | Set if and only if `status` is `PAID` |

Status meanings, which the dataset holds to consistently:

- **`PAID`** — settled; `paid_date` present.
- **`OVERDUE`** — `due_date` has passed and nothing was paid.
- **`PENDING_APPROVAL`** — waiting on an internal approver, not on money.
- **`SCHEDULED`** — approved, dated to pay in the future.

**Fixture:** `data/vendor_invoices.json`

## 5. Get vendor invoice

```
GET /vendor-invoices/{invoice_id}
```

One bill, with everything from the summary plus:

| Field | Type | Notes |
|---|---|---|
| `line_items` | array | `{ description, amount }` |
| `approvals` | array | `{ step, approver_name, role, status, acted_date }` in order |
| `awaiting_approval_from` | string \| null | The first approver still pending; null once fully approved |
| `payment_terms_days` | integer | Copied from the vendor |

`awaiting_approval_from` is the short answer to "why hasn't this been paid yet" when a bill
is sitting in `PENDING_APPROVAL`.

**Fixture:** `data/vendor_invoices.json` → `_records`

## 6. Get payment status

```
GET /transactions/{transaction_id}
```

One outbound payment.

| Field | Type | Notes |
|---|---|---|
| `transaction_id` | string | `txn-#####` |
| `reference` | string | The invoice number or payroll run this paid |
| `transaction_type` | enum | `ACH`, `WIRE` |
| `amount`, `currency` | number, string | |
| `status` | enum | `SETTLED`, `PENDING`, `FAILED` |
| `created_date` | datetime | |
| `settlement_date` | date \| null | Set once settled |
| `expected_settlement_date` | date | Present while pending |
| `failure_reason` | string \| null | e.g. `INSUFFICIENT_FUNDS` |
| `failure_detail` | string | Plain-English explanation, present on failures |
| `payment_method` | object | `{ institution_name, account_last_4 }` |

**Fixture:** `data/payments.json` → `_records`

---

## Deliberate gaps

The dataset does not cover payroll runs, wallets, contracts, timesheets, time off, tax
documents or reference data. Questions in those areas should be answered from the help
articles, or declined — there is no endpoint for them here, by design.
