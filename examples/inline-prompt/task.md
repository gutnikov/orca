# Summarize the auth refactor proposal

The current auth middleware stores session tokens in plaintext cookies and
must be migrated to signed, httpOnly cookies. The migration cannot break
existing sessions — older cookies must remain valid until they expire.

Constraints: no new dependencies, must ship before the next release branch
is cut.
