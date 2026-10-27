# Security reporting and operational boundaries

Do not open a public issue containing secrets, real account details, exploitation
instructions against a financial institution or undisclosed vulnerability details.

Use GitHub's private vulnerability reporting for this repository, where available:
https://github.com/mhatipog/iso20022-payment-quality/security/advisories/new

The maintainers can review a minimal, synthetic reproduction and coordinate
a correction. This is experimental open-source code and does not promise a
particular disclosure response time or guarantee any banking certification.

**Never run an unapproved payment transaction to test this library.** The parser
accepts only bounded XML; avoid sending raw transactions to external observability,
CI logs or example data. Production authorization, encryption, audit, retention,
and regulatory controls belong to the deploying organization.
