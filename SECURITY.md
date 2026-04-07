# Security Policy — Horizon Orchestra

**This is proprietary software owned exclusively by Ashton Fritz.**
Unauthorized access, disclosure, or use is strictly prohibited.

## Reporting a Vulnerability

If you discover a security vulnerability in this codebase:

1. **Do NOT** open a public GitHub issue.
2. **Do NOT** disclose the vulnerability publicly.
3. Email the owner directly: **ashtonfritz3@gmail.com**
   - Subject: `[SECURITY] Horizon Orchestra Vulnerability`
   - Include: description, reproduction steps, potential impact, suggested fix

You will receive a response within 48 hours. Please allow up to 90 days for a
fix to be developed and deployed before any public disclosure.

## Security Architecture

Horizon Orchestra implements defense-in-depth across every layer:

| Layer | Technology |
|---|---|
| Input sanitization | AdversarialFilter, WAFRules, prompt injection defense |
| Runtime isolation | 4-OS sandbox (seccomp-BPF, namespaces, cgroups, OverlayFS) |
| Error recovery | Circuit breakers, adaptive retry, recovery graph |
| Red team | 503 attack payloads, mutation engine, chaos orchestration |
| Secrets | Environment variables only — never committed |
| Auth | JWT with rotation, bcrypt cost 12, refresh token rotation |
| Transport | TLS 1.3 required, HSTS, certificate pinning |
| Audit | Structured audit log for every action |

## Data Handling

- No user data is ever logged in plaintext
- API keys and credentials are stored only in environment variables
- Memory store (SQLite / PostgreSQL) is encrypted at rest
- All cloud storage (S3, DynamoDB) is encrypted with KMS

## Proprietary Notice

All code, algorithms, architectures, and techniques in this repository are
trade secrets of Ashton Fritz. Any unauthorized disclosure violates:
- The Defend Trade Secrets Act (DTSA)
- The Computer Fraud and Abuse Act (CFAA)
- Applicable state trade secret statutes
