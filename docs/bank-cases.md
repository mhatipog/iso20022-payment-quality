# Bank documentation compatibility corpus

**Important distinction:** These are published **bank example messages**, not
production transactions obtained from customers. They are externally maintained,
and may include intentionally unrealistic identifiers, dates, or simplified data.
We never redistribute whole example files here; run the opt-in smoke to fetch them
from the publisher's website. These sources verify field shapes and parsing
compatibility, not bank certification.

- [Goldman Sachs SEPA `pain.001.001.09`](https://developer.gs.com/docs/services/transaction-banking/pain001v9-sepact): bank-documented customer credit transfer example. Exercise the exact version and nested group/batch shape.
- [Goldman Sachs EU `camt.053.001.08`](https://developer.gs.com/docs/services/transaction-banking/camt-053-eu-v8-sample): multiple statements, entries, returns, reversal flags, `BOOK` status represented in different forms, bank transaction codes, and end-to-end references. The reference motivated our reversal and status parsing tests.
- [Goldman Sachs structured remittance camt.053](https://developer.gs.com/docs/services/transaction-banking/camt-053-v8-struct-remi): non-IBAN account, structured remittance and fees. Non-IBAN accounts are valid in some markets; do not force them into SEPA-only matching.
- [European Payments Council SCT 2025 rulebook](https://www.europeanpaymentscouncil.eu/what-we-do/epc-payment-schemes/sepa-credit-transfer-sct/sepa-credit-transfer-rulebook-and): a scheme rulebook with application dates; the 2025 rulebook version 1.2 delayed the end date for unstructured addresses.
- [Isabel Belgian file formats](https://support.isabel.eu/en-US/knowledgebase/article/KA-02119): practical evidence that Belgian platforms may support several pain.001 editions concurrently.

Run against upstream published examples (internet required):

```console
python -m pip install -e .
python examples/public_bank_smoke.py
```

For regulated deployments add independently acquired official XSDs, a versioned
EPC/Belgian bank implementation guideline, operational bank exceptions and compliance
approval. Do not interpret a successful sample smoke as evidence of full message
conformance or payment settlement.
