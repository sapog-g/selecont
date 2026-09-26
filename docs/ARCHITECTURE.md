# Architecture and privacy

selecont is currently a closed, single-instance research prototype. Its architecture is intentionally compact: one FastAPI process, one SQLite database and one private media directory. This makes the access model inspectable and keeps the demo reproducible.

## Trust boundary

The HTTP adapter authenticates a server-side session before it calls the domain layer. Routes do not accept a trusted `actor_id` or `viewer_id` from forms, query parameters or URLs. The current user always comes from the validated session.

The domain store is an internal component. Its identity arguments are trusted only because the HTTP adapter has already authenticated the request.

## Data model

- An author owns one system Public context and up to 20 private circles.
- A follower can belong to at most one private circle for each author.
- Every context has its own profile variant.
- A post is stored once and connected to one or more explicitly selected audiences.
- Comments belong to a specific post-and-audience pair.
- A reaction belongs to a post and user, so the visible count is shared across audiences.
- Media metadata records the owner and attachment; the original client filename is never used as a storage path.

SQLite constraints repeat the most important ownership rules so that invalid cross-author relationships are rejected below the service layer as well.

## Request path

```text
HTTP request
  → session lookup
  → CSRF check for mutations
  → current membership and ownership lookup
  → domain operation
  → audience-filtered response
```

Private profile variants, posts, discussions and media are re-authorized on each request. A previously received URL is not a permanent capability.

## Authentication

- Passwords are hashed with Argon2id.
- The browser receives an opaque HttpOnly session token.
- Only a SHA-256 digest of that token is stored in SQLite.
- Mutating forms require a CSRF token.
- Login errors do not reveal whether a username exists.
- Login attempts are limited for both client and account.

Local HTTP runs without the cookie `Secure` flag. Any HTTPS deployment must set `SELECONT_COOKIE_SECURE=1` and a persistent random `SELECONT_SECRET_KEY` of at least 32 bytes.

## Media handling

Uploads are decoded as images rather than trusted by extension. Static JPEG, PNG and WebP files are accepted up to 10 MB and 20 megapixels. The image is oriented, copied into a new pixel buffer and encoded as WebP without EXIF, XMP, ICC or text metadata.

Media lives outside public static files. Every download checks current access and returns `private, no-store`. Random storage keys prevent client filenames from affecting paths, while per-owner and per-instance quotas bound disk use.

## Revocation

After membership is removed, subsequent requests to private content fail. Open private pages carry a short-lived proof and recheck access in the background; the demo clears private DOM within its tested polling interval.

Revocation cannot erase bytes that a recipient has already seen, copied or captured. The prototype makes this boundary explicit rather than claiming perfect recall of delivered content.

## Deliberate limits

SQLite and polling are appropriate for one controlled demo instance. Before serving real users, the project needs public registration and recovery, moderation and abuse processes, privacy documentation, observability, backups, a scalable push channel and a production database plan.
