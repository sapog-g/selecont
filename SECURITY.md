# Security policy

selecont is a research prototype. It has meaningful authorization and upload defenses, but it has not completed the operational work required for a public social network.

## Reporting a vulnerability

Please do not publish account, access-control or media vulnerabilities in a public issue. Use GitHub's private vulnerability reporting for this repository when available, or contact the repository owner privately through their GitHub profile.

Include the affected route, the viewer and author roles, reproduction steps and the result you expected. Do not include real personal data.

## Supported version

Only the latest commit on `main` is supported.

## Safe local use

- Use synthetic accounts and non-sensitive images.
- Keep the default bind address at `127.0.0.1` unless a host is deliberately secured.
- Never commit `apps/api/var`, `.env` files, databases, media or secret keys.
- For HTTPS, set `SELECONT_COOKIE_SECURE=1` and a persistent random `SELECONT_SECRET_KEY` of at least 32 bytes.
- Review the production gaps in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) before exposing the service publicly.
