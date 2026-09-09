# Changelogs for imgbb
> Created and Maintained by @erbanku and fellow AI agents

## 09/10/2026

- Dropped `--no-index` and pinned `dify-plugin>=0.10.2,<0.11.0` so Marketplace pre-check can install a current SDK.
- Replaced hex mock `auth_token` in tests so Marketplace package-secrets check does not treat fixtures as credentials.

## 09/09/2026

- Marketplace README (setup, screenshots, collapsed details), required manifest `privacy` / `repo` / `contact`, and a package-safe `.gitignore`.
