# Verification scope

Run `python -m unittest discover -s tests -v`. Tests use temporary directories, synthetic packets, native-page-shaped fixtures and mocked failures. They perform no browser actions, network calls, SMS, bookings or purchases.

Coverage includes exact UTF-8 hashing; wrong source/version/hash; immutable IDs; operation aliases and cancellation; one owner; uncertain outcomes; terminal ACKs; result/send receipt reuse; fresh CLI processes; an existing lock; failed atomic replacement; source boundaries, cursor gaps, caps, unfinished emissions, truncated packets and request/cancel reconciliation before an effect claim.

State-validation regressions reject damaged schemas/indexes/aliases and bad result correlation without modifying retained bytes. Compatibility fixtures include cancellation before a request, cancellation addressed to an alias, interrupted uncertain state without a result, object receipts and a reviewed packetless legacy completion tombstone. Cancellation of a previously unseen alias suppresses its canonical queued operation.

File tests request restrictive creation, retain a lock on write failure and check no Windows fallback on an ACL merge error. POSIX-only tests check mode preservation under a permissive umask. Windows-only integration compares DACL grants, propagation flags and protection before and after native replacement on a synthetic ordinary file. Inherited-ACE metadata may be normalized; byte-identical descriptors and future parent-ACL changes are not certified. The test does not certify arbitrary explicit DACLs or private-directory setup. Platform-specific skips must be reported, not counted as passing platform evidence.

For a small synthetic CLI walkthrough, run the fresh-process replay test alone:

```text
python -m unittest discover -s tests -p test_cli_recovery.py -k new_process_replay -v
```

It creates temporary packet/ledger files, queues a request, begins it once, persists a synthetic result, claims sending once, records a synthetic receipt and checks replay suppression. No native message is sent. Use this as a mechanics check; it does not replace live nonce acceptance.

Release regressions pin the adopted raw contract bytes, require exact canonical ACK correlation after operation aliases, preserve cancellation across a later alias, verify multi-turn/item chronology, and require nonzero CLI status on incomplete coverage with retained JSON evidence. The tested CLI exit contract is complete `0`, hold `3`, file/validation error `1`, and argument usage error `2`.

The CLI replay test starts separate Python processes for ledger operations and verifies execution count one and send-attempt count one. This is process recovery evidence, not an operating-system restart test.

The source collector is tested against synthetic fixtures matching an observed native response shape. Its input is a saved authenticated response plus the actual requested cursor. It does not authenticate a file, call native tools, execute a task, or handle arbitrary application schemas. Independently verify schema/provenance and contract hashes in every installation.

Live acceptance is separate: two distinct AZ-originated benign requests, persisted results, verified native send receipts, terminal ACKs and duplicate replay. Save that evidence privately; do not copy live conversation IDs or logs into public fixtures.

Untested deployment conditions include power loss, OS restart, prolonged offline operation, application-version changes, high-volume backlogs beyond the page cap, cross-device shared filesystem locking, malicious filesystem alteration, and bot-wide skill discovery. External effects cannot be made exactly-once by this local ledger alone.
