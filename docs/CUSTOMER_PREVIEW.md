# Customer subscription preview

This additive release preserves the owner dashboard, owner login, scanner, paper ledger and broker safeguards. Customer routes are disabled unless CUSTOMER_PREVIEW_ENABLED=true. No new Render resources are needed.

## Scope

- /customer-admin: owner creates one-use invitations after signing in to the existing owner dashboard. Invitation links expire in 24 hours. Keep them private; they contain an enrollment capability in a URL fragment, which the customer page removes from browser history after reading it.
- /customers: invite-only registration, authenticator enrollment, password plus TOTP login, customer preferences, test checkout and subscription access.
- Independent customer sessions, customer-specific records and preferences. Customer accounts cannot use owner APIs or issue invitations.
- Local billing simulator: server-owned $0 checkout, successful/declined outcome tests, duplicate completion protection, calendar-month access, cancellation at period end and expiry checks.
- CUSTOMER_BILLING_SIMULATOR_ENABLED=true is required for simulated checkout completion. There is no real payment provider connection, card form, transaction or automatic renewal. Real customer payments cannot be enabled by changing these flags.

## Owner walkthrough

1. Sign in to the existing owner dashboard with your existing password and authenticator code.
2. Open /customer-admin in the same browser and create an invitation.
3. Open the private invitation link in a separate browser profile for testing.
4. Choose a customer username and new password (at least 14 characters). Add the displayed key to an authenticator as Tradeomatic Customer. Verify with its current code. Use the next code to sign in.
5. Change customer preferences; verify a second customer retains independent defaults.
6. Start the $0 checkout and simulate a decline. Access must remain inactive.
7. Start another checkout and simulate success. Access should become active for a calendar month.
8. Cancel renewal; access remains until the displayed expiry. This does not issue a refund or contact a provider.
9. Sign out. No private session endpoint should remain accessible.

## Data and security

Records use additive kinds: customers, customer_enrollment, customer_invitations, customer_sessions, customer_settings, customer_subscriptions, customer_checkouts, customer_audit and customer_limits. No owner rows are overwritten or migrated. Database transactions serialize invitation redemption and checkout completion. Passwords use Argon2; authenticator secrets use the existing persistent encryption key. Do not rotate that key to deploy this release. Cookies are HTTP-only, Secure in production and SameSite Strict; state changes require CSRF verification. Authenticator codes cannot be reused at login. Enrollment and sign-in have per-peer limits; a production gateway/distributed abuse-control review remains necessary before broad registration.

The preview has no customer signal stream, journal, broker connection, order approval or trade execution. Customer preferences do not affect the owner account. Only a protected placeholder workspace verifies subscription access. No owner trade or position data is copied to customers.

## Release gates before accepting paying customers

Select monthly prices and payment provider, integrate a real provider's sandbox hosted checkout and signed/idempotent billing webhooks, test renewals/failures/refunds, add email verification and account recovery, implement customer research/paper workflows and notification isolation, validate licensed market data and distribution permissions, perform security/load/backup testing, and approve live billing separately. Website/domain integration remains a later step; VillageSquareStories.com is unchanged.

## Rollback

Disable CUSTOMER_PREVIEW_ENABLED and CUSTOMER_BILLING_SIMULATOR_ENABLED to hide the preview. Preserve customer records and the encryption key. Owner functionality does not depend on preview flags. Do not delete the database or reset owner authentication.
