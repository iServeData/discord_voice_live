# Security

## Reporting a problem

Please don't open a public issue for a security problem. Use GitHub's **Report a vulnerability**
(Security tab → Advisories) on this repository. Include what you found and how to reproduce it.

## What it protects

- **Members' privacy**: only head counts and timestamps are published, never names, avatars or IDs of people.
- **The webhook URL**: anyone with it can post to the channel. It lives only in `announce.env` (root, mode 600),
  is never logged or printed (`--check` reports "set" or "MISSING"), and the example contains a placeholder.
- **Mentions**: every post and edit sets `allowed_mentions`, so only the configured opt-in role can be pinged,
  and only on the first post.
- **The server**: both jobs run sandboxed with no capabilities; the collector writes one folder, the announcer
  only its own state.

## If a webhook URL leaks

Delete the webhook in Discord (Edit Channel → Integrations → Webhooks), create a new one, put it in
`announce.env`. No restart is needed; the next run uses it.

## Supported versions

Only the latest release gets fixes.
