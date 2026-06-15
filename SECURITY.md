# Security Policy

This is a solo-maintained research repository. We take security seriously within the limits of a small, non-commercial project, and we welcome good-faith reports.

## Supported scope

- Active security maintenance focuses on the current **`main`** branch.
- Preserved historical branches, archive tags, old unmerged pull requests, and superseded experimental material are retained for historical reference and are **not** actively supported.
- Historical releases are **not** guaranteed to receive security fixes.
- Reports concerning current code, workflows, dependencies, build processes, or active policy controls on `main` are welcome.

This repository contains research and experimental components. Their presence does not imply that every experiment is a production-supported product.

## Reporting a vulnerability

Please report suspected vulnerabilities **privately** through GitHub's built-in channel:

- Go to this repository's **Security** tab (Advisories) and choose **Report a vulnerability** to open a private security advisory. This routes the report directly and confidentially to the maintainer.

Please **do not**:

- disclose vulnerability details in a public issue, pull request, or discussion; or
- send reports to the maintainer's personal email.

When reporting, please include where possible:

- the affected component or file path;
- steps to reproduce;
- the likely impact;
- relevant environment or version information; and
- a suggested mitigation, if you have one.

Please minimize the use of sensitive data and avoid destructive testing while investigating.

## Response expectations

This is a solo-maintained research repository, so please set expectations accordingly:

- acknowledgement, investigation, and remediation timing **cannot be guaranteed**;
- reports will be assessed as capacity permits;
- coordinated disclosure is appreciated;
- there is **no** bug-bounty or compensation program; and
- this policy does **not** create any service-level agreement.

We will not promise a fixed response time.

## Current security controls

The following controls are currently active on this repository:

- **Continuous integration** verification on pull requests (Python and, where applicable, Node).
- **Agent-Safety / OPA** policy validation (Open Policy Agent format, check, and tests) as a required check.
- **GitHub secret scanning.**
- **GitHub secret-scanning push protection.**
- **GitHub private vulnerability reporting** (the private "Report a vulnerability" route described above).

The following are **not** currently in place and should not be assumed:

- CodeQL / static application security testing;
- OpenSSF Scorecard;
- Dependabot pull-request automation;
- container image scanning;
- SBOM or build provenance; and
- automated release-time security validation.

## Good-faith research

We welcome good-faith security research. When investigating, please:

- avoid privacy violations;
- avoid service disruption or destructive activity;
- access only the information necessary to demonstrate the issue; and
- allow a reasonable period for assessment before any public disclosure.

## Non-goals

This policy:

- does **not** authorize testing of third-party systems or services;
- does **not** create a service-level agreement;
- does **not** establish a bug-bounty or compensation program; and
- does **not** imply production support for historical or experimental material.
