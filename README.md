<p align="center">
  <img src="brand/png/selecont-wordmark-dark.png" width="360" alt="selecont">
</p>

<p align="center"><strong>One profile. Different contexts.</strong></p>

<p align="center"><sub>Working research prototype · FastAPI · Python 3.11 · 95 automated tests</sub></p>

<p align="center">
  <a href="output/pdf/selecont-pitch-3min-ru.pdf">3-minute pitch · RU</a>
  ·
  <a href="output/pdf/selecont-pitch-3min-en.pdf">EN</a>
  ·
  <a href="deck/pitch-3min/">interactive source</a>
  <br>
  <a href="deck/presentation/exports/selecont-itmo-2026-ru-v3.pdf">Pitch deck · RU</a>
  ·
  <a href="deck/presentation/exports/selecont-itmo-2026-en-v3.pdf">EN</a>
</p>

![selecont pitch deck cover](docs/media/selecont-cover.png)

selecont is a social product prototype for sharing different sides of one life with different groups of people. An author keeps one account, creates circles such as Friends or Family, and chooses the right context for each profile, post and conversation.

**Один профиль — разные контексты.** Пользователь сам решает, какую сторону своей жизни показать друзьям, семье или коллегам, не создавая отдельные аккаунты.

## Why it exists

The same photo can feel natural for friends, too personal for colleagues and meaningful for family. Existing social products often force a choice between showing it to everyone, maintaining several accounts or leaving it unpublished.

selecont connects three layers under one identity:

- **Profile:** a different photo and bio for each circle.
- **Post:** one publication can be shared with several selected circles.
- **Discussion:** each circle gets its own comment thread under the same post.

## What works today

The repository contains a closed local web demo with real server-side access rules:

- public and circle-specific profile variants;
- followers and author-managed circles;
- posts for one or several explicitly selected audiences;
- optional JPEG, PNG or WebP uploads with metadata removal;
- isolated multi-level discussions and comment tombstones;
- one shared like counter with author-only attribution;
- read-only audience preview;
- access revocation for profiles, posts, discussions and media;
- independent sessions for anonymous users, followers and the author.

The current implementation is a **research prototype**, not a production social network. Public registration, account recovery, moderation and a hosted product environment are intentionally outside the current scope.

## Run the demo

Requirements: macOS or Linux, Python 3.11+, and a terminal.

```bash
git clone https://github.com/sapog-g/selecont.git
cd selecont
sh apps/api/scripts/start-demo.sh
```

The script creates an isolated environment, installs locked dependencies, asks for one local demo password and seeds four test accounts. Then open [http://127.0.0.1:8000/demo-guide](http://127.0.0.1:8000/demo-guide).

The detailed operator guide is in [apps/api/README.md](apps/api/README.md).

## Verify it

```bash
apps/api/.venv/bin/python -m unittest discover -s apps/api/tests -v
apps/api/.venv/bin/python -m pip check
```

The current suite contains **95 tests** covering session boundaries, authorization, CSRF, migrations, upload validation, quotas, audience isolation, nested replies, tombstones, reactions and access revocation.

## Architecture

```text
Browser
  └── FastAPI HTTP adapter
        ├── authenticated server sessions
        ├── CSRF and authorization boundaries
        └── domain services
              ├── SQLite v7
              └── private media storage
```

The demo deliberately uses one Python service and one SQLite database so that the access model remains easy to inspect. Identity is established by the HTTP session; client-provided identity arguments are never trusted. Private media is served only after a fresh authorization check.

Read [Architecture and privacy](docs/ARCHITECTURE.md) for the design boundaries and [Product specification](docs/PRODUCT-SPEC.md) for the product rules.

## Repository map

| Path | Purpose |
|---|---|
| `apps/api/` | FastAPI application, domain core, migrations and tests |
| `deck/pitch-3min/` | 13-frame animated pitch in Russian and English |
| `deck/presentation/` | Final bilingual pitch deck and its animated web version |
| `output/pdf/` | Send-ready Russian and English PDF exports of the short pitch |
| `brand/` | Approved selecont wordmark and symbol assets |
| `docs/` | Public product and technical documentation |
| `.github/workflows/` | Test and GitHub Pages automation |

## Project status

The product hypothesis, access model, local demo and final pitch deck are ready for review. The next stage is user discovery: finding first participants, watching them configure contexts and measuring whether they return to use them again.

## Security

This repository contains demo code and synthetic accounts only. Do not use real private photos or personal data in the local seed. See [SECURITY.md](SECURITY.md) before reporting a vulnerability or exposing the service publicly.

## Author

**George Sapogovsky** · founder and developer · ITMO University

## Rights

No reuse license has been granted. © 2026 George Sapogovsky. All rights reserved.
