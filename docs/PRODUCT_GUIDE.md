# Niural product guide — Employees and Niural Pay

Background reading for the support agent exercise.

Niural is an HR and financial operations platform. Employers use it to hire and manage
workers, run payroll, pay their vendors and bill their customers. This guide covers the two
areas the exercise dataset models: the **Employees** tab, and **Niural Pay**.

Read it to understand what the product actually does, what each status means, and what a
customer is likely to be asking about. Examples use a fictional employer, **Bramblewood
Robotics**, matching the dataset.

> **On the dataset.** The JSON in `data/` is a simplified extract — fewer fields, fewer
> statuses, and its own field names. Where this guide and `API_DOCUMENTATION.md` disagree,
> **the API documentation is authoritative for the data you will be coding against.** This
> guide is here so you understand the product the data describes.

---

## How the app is organised

The top bar carries the organisation switcher (company name and an entity badge such as
**HQ**), the wallet balance, an **Ask Emma** assistant, search, settings and support.

Sections hang off the top bar:

- **People** — Employees, Contracts, Org chart, Hire, Benefits; then *Tracking*
  (Timesheets, Time off, Policies) and *Reimburse* (Expense).
- **More ▾** — Payments, **Niural Pay**, Niural Insights, Integrations.

Pages live at `/{organization-id}/{section}/{page}`, so the employee list is at
`/{org}/people/employees` and bills at `/{org}/niural-pay/bills`.

---

# Part 1 — Employees

**People → Employees**

## The employee list

Employees are split across five tabs. This is the single most important thing to understand
before answering any question about headcount: **each tab is a separate population, and a
count only ever refers to the tab you are looking at.**

| Tab | Who is in it |
|---|---|
| **Active** | Onboarding complete, on payroll, payable |
| **Onboarding** | Hired, but setup is unfinished — **not yet payable** |
| **Dismissed** | Offboarded; excluded from payroll after their final pay date |
| **Offboarding** | Departure in progress |
| **Draft** | Started in the system, not submitted |

So "how many employees do we have?" is ambiguous on its own. Someone with 40 people in
Active and 12 in Onboarding has 52 records but 40 payable staff.

**Columns:** Name · Type · Job title · Compensation type · Payroll schedule · Reporting
manager · Hire date.

- **Type** — `W-2 employee`. Contractors are *not* here; they live under **People →
  Contracts**. A question about paying a contractor is a different area of the product.
- **Compensation type** — `Salary`, `Hourly`, or `Salary with overtime`.
- **Payroll schedule** — `Default`, or a named schedule such as `Bi-weekly - Hourly Team`.
- **Reporting manager** — a name, or `-` when unassigned.

Above the table sit **Search** (focus with `/`) and **Filter**; top right are **Bulk Upload
History**, **Import from ATS** and **+ Add employee**.

Note the list does **not** show department or work location. Both live on the individual
record, so narrowing by either means opening people or using Filter.

## The employee record

Click a name to open it. The header shows the person, a **status badge** (for example an
amber *Onboarding*), their type and hire date.

**Banners** appear above the header when something is outstanding, and they are usually the
real answer to "why isn't this person set up yet":

- *"Having trouble with account activation? Resend the invitation link…"* — the person has
  never activated their account.
- *"The deadline for submitting Form I-9 was <date>…"* with **Upload manually**.

**Tabs:** Personal · Work · Taxes · Benefits · Time off · Pay · Documents.

**Personal** holds personal details, **Emergency contacts** and **Custom data**.

**Work** is where most staffing questions are answered:

| Section | Contains |
|---|---|
| **Pay schedule** | Payroll schedule name, Work week start day, Paid through date |
| **Employment details** | Employment type (e.g. Full Time), Job title, Hire date |
| **Compensation details** | Compensation type, Annual salary |
| **Organization position** | Reporting manager, Direct reports |
| **Department & team** | Department, Team, and their primary/secondary managers |
| **Work location** | Workplace (e.g. Home), Work address |

Unset fields show `--`. Department and team are often blank; that is normal, not an error.

## Onboarding and Form I-9

Onboarding is a checklist, not a single flag. Someone stays in the **Onboarding** tab until
every step is done, and the step that most often holds things up is **Form I-9 Section 2** —
which is the *employer's* responsibility, not the employee's:

> Section 2 must be completed within 3 business days of the employee's first day of work.

The dashboard carries a **Form I-9 tracker** listing everyone outstanding. So when a
customer asks why a new hire cannot be paid, or why someone is missing from a payroll run,
check their status and their onboarding steps before anything else.

## How to hire an employee

**People → Hire** (or **Employees → + Add employee**).

### Step 1 — choose the worker type

1. Under **Who would you like to hire?**, pick one:
   - **Employee** — on your payroll, with benefits and tax withholding.
   - **Contractor** — self-employed, manages their own taxes and benefits.
   - **EOR employee** — hired through Niural's Employer of Record service, with Niural
     handling compliance.
2. Set **Where is the employee located?**.
3. Under **How would you like to hire this employee?**, pick one:
   - **W-2 employee** — your company is responsible for all HR and compliance.
   - **PEO employee** — Niural handles payroll, compliance and HR. Sales-gated.
   - **Dismissed employee** — for recording someone your entity remains responsible for.

Choosing **W-2 employee** opens a four-step wizard, tracked in the left rail:
**Employee details → Payroll schedule → Configure documents → Review & invite**. A **Bulk
Upload** option is available for adding many people at once.

### Step 2 — Employee details *(step 1 of 4)*

Required fields carry a red asterisk.

1. **Employee identity** — First name\*, Middle name, Last name\*, Personal email\*,
   Work email.
2. **Job details** — Job title\*, Hire date\* (`MM-DD-YYYY`).
3. **Work location & compliance** — Work address\* (e.g. *Works from home*), Work state\*,
   Risk class code. Then **Is this member a statutory employee?** (Yes/No), and **Does this
   employee have any special tax exemption status?** — **Add exemption** opens the exempt-tax
   configuration.
4. **Compensation** — Compensation type\* (*Salaried/Eligible for overtime*, *Salaried/No
   overtime*, or *Hourly*), Annual gross amount\*, Employment status\* (e.g. Full time).
5. **Organization position** — Reporting manager, Direct reports.
6. **Department & team** — select a department and a team.
7. Click **Next**.

### Remaining steps

8. **Payroll schedule** — assign the schedule governing their pay dates.
9. **Configure documents** — choose the onboarding paperwork to send.
10. **Review & invite** — check the summary and send the invitation.

The new hire lands in **Onboarding**, not Active, and is not payable until every step
including I-9 Section 2 is complete.

---

# Part 2 — Niural Pay

**More → Niural Pay**

Left nav: **Overview**; *Accounts Payable* — **Bills**, **Vendors**; *Accounts Receivable* —
**Invoices**, **Customers**; *Configuration* — **Users & Policies**, **Settings**.

> **Vocabulary.** **Bills** are money you owe vendors (accounts payable). **Invoices** under
> Accounts Receivable are money customers owe you. Confusingly, an individual bill's own
> identifiers are still labelled "Invoice ID" and "Invoice number" — so read which list you
> are in before interpreting either.

**Overview** shows four tiles — Total bills, Unpaid bills, Pending approvals, Total
vendors — over a top-vendors chart, a recent-invoices feed and invoices awaiting approval.

## Bills

**Tabs:** All payments · Needs approval · Ready for payment *(with a count)*.

**Filters:** Status · Scheduled pay date · Approvers involved · Vendor · Entity ·
Department, plus **Export** and **Add bill**.

**Columns:** Invoice ID · Invoice number · Invoice date · Scheduled pay date · Vendor ·
Entity · Department · Status · Amount · Preferred currency · Emma's review.

Every bill carries **two identifiers**, and customers quote either:

- **Invoice ID** — Niural's own, prefixed with the organisation, e.g. `BRW-XFEWYVQU`.
- **Invoice number** — whatever the vendor printed on their document, e.g. `HAL-2026-0101`.

**Statuses:** *Ready for payment*, *Payment received*, *Paid*. A bill needing sign-off sits
under **Needs approval**.

**Amount vs Preferred currency.** A bill can be raised in one currency and settled in
another — `AED 17,000.00` against a preferred currency of `USD`. Read both before quoting a
figure.

### Emma's review

A column on every row, showing **Flagged**, **Cleared** or **N/A**. This is Niural's
automated check of the bill against its associated contract, and it is the first thing to
look at when someone asks why a payment is being held up.

## A single bill

**Header:** invoice ID, amount, status, created date, entity and department.

**Actions:** Pay invoice · Void invoice · Record payment · Update pay date · View invoice ·
Duplicate.

**Emma summary** — a written verdict with **Re-analyze**, for example:

> Reviewed 12 fields against Contract "Ironvale supply agreement": 8 match, 2 require
> attention, 2 could not be verified, review before payment.

Below it, the **anomalies detected** in a table of **Niural field · Value in contract ·
Value in bill · Note**, each explaining the discrepancy in plain English — a due date that
falls outside the contract's payment window, payment terms of −6 days where the contract
says Net 45, and so on. This is the most useful screen for "why is this bill flagged?".

**Approval** appears as a named policy and its outcome, e.g. *Employer Self Approval —
Approval Status: Approved*.

**Overview** holds the invoice items (Item, Quantity, Rate, Tax, Amount, with subtotal and
net total), a summary including fees such as an *ACH processing fee*, the selected vendor
and its **associated contract**, full invoice details (issued/invoice/due/scheduled pay
dates, currencies, exchange method), and the payment method details with a masked account
number.

**Activity** is the audit trail, newest first — who did what, and when:

> Rosalind Vane approved the bill. · 09:05 PM
> Rosalind Vane updated payee details and payment methods. · 09:05 PM
> Rosalind Vane created a draft bill #BRW-XFEWYVQU · 09:05 PM

When someone asks what happened to a bill, this is the answer.

## Vendors

**Columns:** Vendor name · Created date · Type · Country · Status · KYB status.
**Filters:** Type · Country · Status · KYB status, plus **Export** and **Add vendor**.

**KYB status** — **Verified** or **Not verified** — is Know-Your-Business verification. It
is separate from the vendor being *Active*, and an unverified vendor is a common reason a
payment cannot proceed.

## How to add a vendor

**Niural Pay → Vendors → Add vendor** (or **+ Add new vendor** from inside the Add bill
form, which returns you to the bill afterwards).

1. **General information** — Vendor type\* (**Individual** or **Business**), Vendor
   country\*, Vendor name\* (the *legal registered* name), Entity\*, Department.
2. **Contact information** — Contact number\*, Email address\*.
3. **Tax & compliance details** — EIN, and a **Tax document** upload. Required if you will
   generate 1099 documents for this vendor.
4. **Vendor agreement** — **Upload contract** (PDF, DOC or DOCX). This is the contract
   Niural later compares each bill against, which is what produces the anomaly findings.
5. **KYB verification** — tick **Mark this vendor as KYB verified** once the check has
   actually been run.
6. **Home or business address** and **Mailing address**.
7. Click **Create vendor**.

## How to add a bill

**Niural Pay → Bills → Add bill.** A template selector sits next to the title.

The fastest route is the **Upload vendor invoice** panel on the right: drop in the vendor's
document (JPEG, PNG or PDF, up to 10MB) and Niural extracts the vendor, amount, dates and
other details automatically. Then check the fields rather than typing them.

To fill it in manually:

1. **Choose the vendor you want to pay\***, or **+ Add new vendor**.
2. Pick the **Contract** to bill against. This enables the anomaly check, so set it where a
   contract exists.
3. **Entity and department**.
4. **Invoice details** — Invoice number\* (the vendor's own), Invoice date\*, Invoice
   currency\*, Due date.
5. **Line items** — Item, Quantity, Rate, Tax %, Discount %, Amount. **Add new item** for
   more rows; totals calculate as you go.
6. Add **Notes** (500 characters) and any **Additional attachments**.
7. Click **Next: Review details**, check the summary, and confirm.

The bill then appears with its own Invoice ID alongside the vendor's number. If an approval
policy applies it lands under **Needs approval**; otherwise it moves toward **Ready for
payment**. Paying is a separate step — open the bill and use **Pay invoice**.

## Accounts receivable — Invoices

**Niural Pay → Invoices.** Two tabs: **Invoices** and **Schedules** (recurring runs).

**Columns:** Invoice ID · Invoice title · Customer name · Invoice date · Due date · Status ·
Amount · Entity · Department · Emma's review.

Statuses differ from Bills — *Email not sent*, *Voided*. An overdue invoice shows its
lateness inline beneath the due date, e.g. `-7 days`. **Emma's review** here uses *Flagged*
and **Unlinked**, where Unlinked means the invoice has no contract attached, so there is
nothing to check it against.

## How to create a customer invoice

**Niural Pay → Invoices → Create invoice.**

1. **Customer\***.
2. **Invoice title\*** — what it is for; this shows in the list.
3. **Contract** — link one if it exists, otherwise the invoice shows as *Unlinked*.
4. **Entity and department**.
5. **Invoice details** — Reference number, Currency\*, Invoice code, Invoice date\*,
   Payment term\* (e.g. *One Week*), Payment due\*.
6. **Line level fields** — Item, Quantity, Rate, Discount %, Tax rate, Amount.
7. Add **Notes** and an **Additional attachment** if needed.
8. Check Subtotal, **Additional discount %**, Tax amount and Net amount.
9. Answer **Is this a recurring invoice?** — **Yes** puts it on a schedule, visible under
   the **Schedules** tab.
10. Click **Create invoice**.

Creating an invoice does not send it. It sits at *Email not sent* until you send it to the
customer.

---

# Part 3 — Transactions

**More → Payments → History → Transactions**

The record of money that actually moved, which is **not** the same as a bill's status. A
bill can read *Ready for payment* while no transaction exists yet.

**Columns:** Created at · Statements · Payment method · Status · Amount.
**Filters:** Payment method · Status · Payment for, plus **Export**.

- **Statements** describes what was paid — *Payroll payment - Aug 24, 2026 · 1 Payroll*, or
  *Invoice payment - Aug 05, 2026 · 1 Invoice*.
- **Payment method** — `Bank transfer`, `Niural wallet`, or `Wire transfer`.
- **Status** — `Paid` or `Processing`.

The sibling history pages are **Invoice History** and **Payroll History**.

---

## Scope of this guide

Covered: the Employees list and record, hiring, Niural Pay (Bills, Vendors, Accounts
Receivable invoices) and the Transactions history.

Not covered, and out of scope for the exercise: payroll runs, the Niural wallet, contracts,
timesheets, time off, benefits, tax documents, and the employee Taxes / Benefits / Time off /
Pay / Documents tabs. Questions in those areas should be answered from the help articles, or
declined — the dataset has no endpoint for them.
