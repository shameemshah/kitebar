# Security Policy

## What this app touches

- **Kite Connect API key & secret** — stored only in the macOS Keychain
  (service `kitebar`), entered by you at runtime. Never written to
  the repo, config files, or logs.
- **Daily access token** — cached at
  `~/Library/Application Support/KiteBar/access_token.json` with mode
  `0600`, expires ~6 AM IST daily.
- **Local callback server** — binds `127.0.0.1:8000` only while a login is
  in progress; parses only the `request_token` query parameter.
- **API surface** — read-only: `generate_session`, `holdings`, and
  `positions`. No order,
  fund, or profile-mutation endpoints are called anywhere in the code.

## Reporting a vulnerability

Please use GitHub's **private vulnerability reporting** (Security tab →
"Report a vulnerability") rather than a public issue. Include reproduction
steps and impact. You should get a response within a week.

If the issue involves leaked credentials of your own, first regenerate your
API secret at developers.kite.trade and invalidate the session from the
Kite web console.

## Out of scope

- Vulnerabilities in Zerodha/Kite Connect itself (report to
  [Zerodha](https://zerodha.com/contact/))
- Attacks requiring an already-compromised local user account (the Keychain
  and token file are only as safe as your macOS login)
