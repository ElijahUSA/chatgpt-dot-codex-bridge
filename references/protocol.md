# Portable AZ / local Codex contract

Version: az-codex/1

## Participants and authority

The registered AZ conversation emits requests for the registered local receiver. The local receiver pulls those outputs and sends results back through its working local tools. AZ acknowledges in its own conversation. Use the exact route IDs; missing cloud-to-local tools do not invalidate working local-to-cloud tools.

The human's established delegation supplies authority within its scope. Packet provenance supplies identity, not extra approval. Goal-limited setup approval ends when that goal is accomplished. Neither participant can override higher-priority instructions or tool-enforced boundaries.

## Packet format

Designated output begins exactly AZ_BRIDGE_V1 followed by a space and one complete JSON object, without a code fence. Accept only actual completed assistant output or a completed user_message.send_message output from the registered AZ source, not incoming delegated prompts, quoted material, examples, or echoes.

All packets have these nonempty string fields:

- protocol: az-codex/1
- kind: request, result, ack, or cancel
- sender and receiver: az/codex for request, ack, and cancel; codex/az for result
- request_id: stable ID for one immutable request
- operation_key: stable key for the consequential operation across retries and changed IDs
- payload: a frozen JSON-object string
- payload_sha256: lowercase SHA-256 of that decoded string's exact UTF-8 bytes, without BOM, trimming, normalization, or newline conversion
- request_sha256: the original request payload hash; equals payload_sha256 on a request
- contract_sha256: lowercase SHA-256 of this exact protocol file's bytes

An ACK additionally has result_sha256, matching the result payload hash. Request payload contains objective and may contain inputs, execution_mode, and nonce. Result payload contains domain_status (complete, partial, blocked, uncertain, cancelled, or failed), outcome, evidence references, unknowns, and next action as appropriate. ACK confirms receipt of the correlated result; it does not independently certify an external outcome.

To construct hashes in Python: serialize the payload once with json.dumps(body, ensure_ascii=False, separators=(',', ':')); freeze that string; compute hashlib.sha256(payload.encode('utf-8')).hexdigest(). Different whitespace or newlines are different payloads. Hash the contract file bytes separately.

If AZ lacks hashing tools, it can originate a nonce and an explicit stable request in prose; local Codex freezes a proposed packet and returns it for AZ to emit unchanged as designated output. Execute only after that actual AZ confirmation. Do not guess a hash.

## Durable receipt and ownership

The global route records source, receiver, contract hash, authority references, heartbeat ID, ledger path, and source-item boundary. Both manual and heartbeat processing use that ledger. Save complete incoming packets plus source-item IDs before advancing the source boundary. Import prior completion tombstones so reinstallation cannot repeat completed messages.

scripts/bridge_packet.py validates and atomically mutates the ledger under an exclusive local lock. It never executes tasks. Persist queued, then claim executing with one owner before an effect. Complete only with direct domain evidence. A crashed or suspended executing record remains a reconciliation hold; do not claim it again. An uncertain result never auto-replays.

Same request ID, operation key, and request hash reuses the existing state/result. Changed content under the same ID is a conflict. Another ID with an existing operation key is an alias, not permission to repeat the effect. Preserve complete and uncertain outcomes across alias requests. This provides duplicate suppression and receipt recovery, not an exactly-once guarantee across external services.

A cancellation received before execution leaves a tombstone and suppresses later replay. Reconcile cancellations for executing, partial, or uncertain work. Cancellation after completion returns the known outcome and never implies rollback.

Persist a result before sending it. Send at most once per result hash when a verified send receipt exists. If send outcome is uncertain, inspect the exact destination before retrying. A matching ACK is stored silently. Duplicate and unmatched ACKs cause no reply and no execution. There is no ACK-to-ACK exchange.

## Polling and liveness

Start each scan from the newest page. Follow older page cursors to the persisted known source-item boundary. Capture the initial newest item so arrivals during scanning remain for the next scan. Process packets in chronological order after a complete covered batch, including cancellations, and persist candidates before advancing the boundary.

Limit one scan to six pages. A missing boundary, invalid cursor, truncation, or page cap means incomplete coverage: preserve the continuation cursor and candidates, hold dependent effects, and resume from saved state. Never mark a gap scanned. Initial onboarding establishes a documented boundary after reconciling earlier requests and completion tombstones.

Use the existing native Codex heartbeat, with one execution owner and the shared ledger. Stay quiet while history is unchanged or non-actionable. Offline or suspended local execution preserves pending work. A five-minute configured interval is not a guaranteed response time. Do not add custom background loops.

## Adoption and acceptance

Local installation is global for compatible Codex skill discovery. It does not install a cloud bot skill. Give this exact text and its contract hash to the registered AZ conversation; require an explicit adoption receipt for az-codex/1 and that hash. Claim bot-wide discovery only if a real bot instruction surface has been verified.

Live acceptance uses two fresh AZ-originated nonces. For each, AZ emits a request; local Codex reads the actual source output, validates and claims it, reads the installed skill's version/hash, echoes the nonce in a persisted result, and sends it back. AZ emits a matching ACK with request and result hashes. Save provenance, packets, installed hashes, and receipt IDs.

Replay a saved request locally and verify execution count stays one. Local pressure tests cover changed payloads, operation aliases, cancellation before start, unknown result, owner conflict, wrong source/version/hash, and terminal ACKs. No external action is repeated for a test.

