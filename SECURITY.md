# Security and trust boundaries

This package validates packet correlation and persists a local execution ledger. Authenticated native tools, registered participants, human task authority and domain-specific checks remain the operator's responsibility.

The ledger lock is local. Duplicate suppression and receipt reconciliation do not guarantee exactly-once effects across external services. Interrupted executions and uncertain sends require direct receipt checks; existing locks are never removed automatically.

Saved source-page JSON is untrusted input, not authentication. Missing history, truncation, unfinished output and backlogs beyond the collector's six-page cap hold dependent work. OS restart and offline recovery require deployment-specific acceptance tests.

Local skill discovery does not install a bot skill or grant additional permissions. Keep routes, ledgers, credentials, logs, screenshots and personal task evidence outside the repository.

Verify the private state directory before use. New POSIX files/locks request `0600`; replacements retain existing file mode. Windows new files inherit the directory ACL, while existing ledger replacement uses `ReplaceFileW` without ACL-ignore flags. Mode bits do not certify DACL privacy, and the package does not configure or audit directory ACLs or preserve arbitrary POSIX ACLs. Write failures retain an execution hold and recovery evidence rather than authorizing a retry.

Invalid existing state holds work. The helper does not repair missing suppression indexes, reclaim an interrupted owner, reset an uncertain send, or replace an immutable partial/uncertain domain result. Such changes require evidence-backed operator recovery outside the ordinary helper actions.

When reporting a problem, use a minimal synthetic reproduction. Share no credentials, private thread identifiers, personal records or runtime ledger contents in a public issue.
