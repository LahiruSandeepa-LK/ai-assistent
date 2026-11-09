# 16 — Keycloak authentication & user onboarding

## Two login models
| User type | Mechanism | Role granted |
|-----------|-----------|--------------|
| Public user | SSO via identity brokering (Authorization Code + PKCE, `kc_idp_hint=corporate-sso`) | **Viewer** (read-only) via first-broker-login role mapper |
| Analyst | Username / password (OIDC Resource-Owner Password grant, `ai-assistant-admin` client) | **Analyst** |
| Administrator | Username / password (same client) | **Administrator** |

The realm is provisioned **as code** in `infra/keycloak/abc-bank-realm.json` and auto-imported by
the `keycloak` service (`start-dev --import-realm`). The API only validates tokens
(`libs/authz/identity.py`); the UIs acquire them (`libs/authclient/keycloak_client.py`).

## Onboarding a new user
### Public (SSO) users — zero-touch
1. Configure the brokered IdP once: replace the `REPLACE_WITH_*` values in the realm's
   `corporate-sso` identity provider with your corporate OIDC client id/secret and endpoints
   (or set them in the Keycloak admin console → Identity Providers).
2. A new employee who exists in the corporate IdP simply clicks **Continue with SSO**. Keycloak
   brokers the login and the `sso-users-get-viewer` mapper assigns **Viewer** automatically. No
   manual step in Keycloak.
3. To widen the default, change the mapper or the realm default role — not application code (the
   PEP/RBAC matrix keys off the three role names only).

### Staff (admin / analyst) — admin-provisioned
1. In the Keycloak admin console (realm **abc-bank**) → Users → Add user.
2. Set a password (Credentials tab) and assign the realm role **Analyst** or **Administrator**
   (Role mapping tab).
3. The user signs in with username/password in the UI. Scripted alternative: `kcadm.sh` or the
   Admin REST API for bulk onboarding; or extend the realm import `users` array.

Seeded demo users: `admin / Admin#12345` (Administrator), `analyst / Analyst#12345` (Analyst).

## Role → privilege mapping
Roles map to the RBAC matrix in `libs/authz/rbac.py` and are enforced by the PEP on every tool
and retrieval. If your IdP uses different role names, set `KEYCLOAK_ROLE_MAP` (e.g.
`kc-reader:Viewer,kc-analyst:Analyst,kc-admin:Administrator`) — no code change.

## Issuer / networking
Browser (SSO redirect) and containers (token/JWKS) both use `http://host.docker.internal:8080`,
pinned as Keycloak's issuer via `KC_HOSTNAME_URL`, so the `iss` claim matches on both sides. On a
Linux host add `127.0.0.1 host.docker.internal` to `/etc/hosts` for the browser redirect.
