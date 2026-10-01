# Operator sequence

The human registers the exact AZ conversation and local receiver and defines task authority. Verify authenticated local tools can read the source and return a message. An identifier in downloaded JSON is not authentication.

## Source coverage

Fetch at most six native `read_thread` pages per scan, starting newest-first. Save each parsed response privately and annotate `requestedCursor` with the exact argument used (null on the first page). Keep cursor linkage and stable source-item IDs. If an API schema differs from the fixtures, hold processing and adapt/test the collector before relying on it.

The collector assumes pages and turns are newest-first and items within each turn are oldest-first. Verify actual native ordering before using a new tool version. Exit `0` means complete coverage; exit `3` is an explicit hold with preserved JSON candidates/continuation; exit `1` returns a JSON error on stderr; argument usage errors exit `2`. Never advance a boundary or begin an effect after a nonzero exit.

Run the collector against the known boundary. Persist candidates, initial newest item, issues and continuation. On an incomplete scan, do not advance the boundary or start effects. Additional authenticated linked pages can be included only while the total remains within six pages; restart the collector from the first saved page against the unchanged boundary. Never append an unrelated page or discard saved candidates silently. The collector has no standalone resume-state input.

The supplied collector caps a scan at six pages. Beyond that cap, the operator must retain a continuation and complete coverage with a separately reviewed continuation procedure. It intentionally does not claim gap-free automatic processing of arbitrarily large backlogs.

The protocol's requirement to resume from saved state is an operator obligation, not an implemented automatic resume feature. Here `continuation` is a durable hold marker; it cannot be supplied as the collector's first cursor. Keep the known boundary unchanged until the recovery procedure establishes complete coverage.

After complete coverage, validate all envelopes and reconcile every request/cancel/ACK in chronological order before any `begin`. A malformed designated envelope holds the batch. A quoted request or incoming delegated echo is ignored.

## Ledger and effects

Use `event` with both authenticated source and expected-source IDs, the packet file and exact contract hash. The helper queues or reconciles an event under an exclusive lock.

Every state transition validates schema v1, complete canonical operation indexes, alias paths, counts and stored packet/result/ACK/delivery correlation. Invalid existing state is rejected without rewriting ledger bytes. A missing ledger may initialize empty; an existing empty object or incomplete import cannot. Reviewed legacy completion tombstones retain their evidence references and suppress execution, but do not invent a transport result or send permission.

The raw-byte hash of the unchanged `references/protocol.md` is `a6a033b18963df6dfcf6f49428ec6d05545642c807f2da775f05a1002e4a62c2`. Use the README's Python file-byte hashing command. The helper's `hash` action takes a UTF-8 payload file; the separate raw-byte command is clearer for contract verification. The protocol defines no canonical JSON key order: sorted or insertion-ordered serialization is valid when its exact frozen string and hash agree. Serialize once and reuse that identical string rather than reconstructing it.

Use `begin` with stable request ID and execution-owner ID. Only `execute_once` permits starting the authorized task. Every other decision requires reuse or reconciliation. Do not treat a new alias ID as permission to repeat an operation.

The actual task uses its domain tools and skill. Before a send, booking or other effect, verify the exact recipient/object, current state, original authority and any domain-specific conditions. Save direct receipts privately.

Use `finish` to persist the immutable correlated result. Distinguish complete, partial, blocked, uncertain, cancelled and failed. Then use `prepare_send`; only `send_once` permits the native result send. Save its actual receipt through `delivery`. If the tool was interrupted, record uncertain delivery and inspect the exact AZ destination before deciding what occurred.

Before `finish`, reconcile a fresh covered source batch and any recorded cancellation against direct effect receipts. An already completed external effect can still be reported accurately after cancellation; cancellation does not undo it. Suppress work cancelled before execution and describe unresolved partial effects explicitly.

Validate and persist a matching ACK with `event`. Duplicate, unmatched and terminal ACKs produce no reply.

When a valid ACK exists without a delivery claim, `prepare_send` returns `acknowledged_no_send`; it does not fabricate a sent receipt. Existing sending/uncertain claims remain reconciliation holds, and an existing sent receipt is reused.

An operation alias reuses the canonical outcome, not a newly addressed result packet. AZ must acknowledge the persisted result's original request ID, original request hash, operation key and result hash. An ACK addressed to an alias cannot certify receipt of the canonical packet. Alias-specific results would require a separately designed correlated result and delivery record; do not reinterpret an unmatched ACK or resend an already delivered canonical result.

## Interruption

The helper creates an exclusive ledger lock and atomically replaces the state file. An existing lock causes a conservative stop. Establish whether its process and execution owner still exist before any recovery; the helper never removes a pre-existing lock.

Prepare a private state directory before processing. New POSIX leaf directories request `0700`; new temporary files and locks request `0600`; replacement preserves existing POSIX file mode. Existing directory permissions and POSIX ACLs are not changed or certified. On Windows, new files inherit the verified directory ACL. Replacement of an existing ledger uses native `ReplaceFileW` with no ACL-ignore flags; no permissive fallback is used. This preserves the target DACL according to the [Microsoft API contract](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-replacefilew). The ordinary inherited-DACL integration test is narrower than validation of every explicit ACL or filesystem.

A failed ledger write retains the owned lock. Windows replacement uses a same-directory backup; a native failure may retain `.recovery` and `.tmp` evidence, or leave the old file under its recovery name. Inspect all of them before a reviewed repair. A retained recovery file holds subsequent initialization or mutation even when the main ledger is absent. No recovery file is silently used to authorize effects.

`delivery` supports a verified `sending`/`uncertain` transport claim becoming `sent` with the same owner and result hash. Ordinary `finish` accepts only the active executing record: persisted partial/uncertain domain results cannot be replaced through it. A send claim later proved unsent, an incomplete import, unsupported schema, orphan lock or changed domain outcome needs a separately reviewed migration or continued hold. Do not delete delivery state, change an operation key, or resend to evade a hold.

One receiver per route is an operator requirement. The helper enforces persisted ownership per execution/send claim; it does not enforce a global route-owner lease across independent processes or devices.

A saved executing record survives a new Python process. It is not automatically reclaimed. An OS restart may require application-specific owner and source recovery; restart acceptance must be tested separately.

Prefer native recurring heartbeats over shell loops. Keep one receiver and one shared ledger for manual and scheduled processing. Configure quiet unchanged runs and meaningful completion/failure reporting through the supported application scheduling tool.
