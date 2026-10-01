# AZ / Codex local-pull bridge

A reusable skill and packet ledger for exchanging delegated tasks between a registered AZ conversation and a human-selected local Codex chat.

"AZ" means the operator's designated assistant conversation. This is an independent integration package; it is not an official OpenAI product or a general bot messaging API.

When cloud-to-local dispatch is unavailable but local Codex can read AZ and send messages back, the local chat pulls designated requests, executes authorized work with the appropriate domain skill, persists its result, and returns it. AZ acknowledges receipt.

This package contains protocol and recovery helpers. It does not provide an OS executor, install a bot, authenticate either participant, or bypass missing application tools.

## Prerequisites

- A local Codex environment exposing authenticated native `read_thread` and `send_message_to_thread` for the exact registered AZ conversation.
- A human-selected local receiver and explicit delegation for the requested task.
- Python 3.11 or newer with its standard library. No third-party Python package is required.
- Compatible skill discovery, verified after installation.
- Optional native thread heartbeat for recurring pulls, configured through supported application tools.

The local-pull route must first be verified in your environment. Application tool names, availability and thread placement can differ. Do not assume a cloud chat can address a local thread merely because the local chat can address the cloud chat.

## Install and configure

1. Copy this directory to your personal agent skill directory as `communicating-with-az`. Keep `SKILL.md`, `scripts`, `references` and `tests` together. Confirm the skill appears in a fresh compatible local session.
2. Prepare a private state directory, then copy `examples/route.example.json` there. On POSIX, restrict its permissions to the operator; on Windows, verify its directory ACL covers new ledger, lock, temporary and evidence files. Replace every placeholder with verified source, receiver, local state paths and human authority references. Keep runtime state outside this repository.
3. Verify SHA-256 of the exact bytes of `references/protocol.md` using the command below. Save that hash in the private route and exchange the complete contract with AZ. Require explicit version/hash adoption in the registered AZ conversation.
4. Reconcile earlier operations and import completion tombstones before establishing an initial source-item boundary. Never replay an earlier uncertain effect.
5. Run `python -m unittest discover -s tests -v`.
6. Verify two distinct benign AZ-originated nonce round trips with correlated terminal ACKs. Save private source provenance and receipt evidence. Replay locally to check that execution and send counts stay one. Do not use real messages, purchases or other external effects as test payloads.

Protocol details: [references/protocol.md](references/protocol.md).
Operator sequence: [docs/operator.md](docs/operator.md).
Verification scope: [docs/testing.md](docs/testing.md).

The repository name is `az-codex-bridge`; the installed skill directory is `communicating-with-az`. Protocol `az-codex/1` uses this raw-file SHA-256:

```text
a6a033b18963df6dfcf6f49428ec6d05545642c807f2da775f05a1002e4a62c2
```

Verify it from the package root on Windows, macOS or Linux:

```text
python -c "import hashlib,pathlib; print(hashlib.sha256(pathlib.Path('references/protocol.md').read_bytes()).hexdigest())"
```

`.gitattributes` pins LF line endings. Preserve the complete protocol bytes, including its existing final newline; an editor change requires renewed hash adoption. The helper's `hash` action hashes a UTF-8 payload string, not the contract file. Freeze each serialized payload once: key order, whitespace and newlines are significant even if two JSON objects have the same meaning.

## Helpers

`scripts/bridge_packet.py` validates frozen payload hashes and manages an atomic, single-owner local ledger. Use `--help` for arguments. Its actions are `hash`, `validate`, `event`, `begin`, `finish`, `prepare_send` and `delivery`. It never executes a delegated task.

`scripts/source_batch.py` collects candidate envelopes from saved native source pages and guards the source-item boundary. Each page is the parsed native `read_thread` response plus `requestedCursor`, copied from the actual tool arguments; the first page uses null. Feed pages in newest-first cursor order. The helper rejects source mismatches and holds incomplete cursor chains, missing boundaries, unfinished emissions and truncated designated packets. It does not authenticate saved JSON or validate packet hashes. Those checks remain separate.

Example collection:

```text
python scripts/source_batch.py --pages PRIVATE_PAGES_JSON --source REGISTERED_SOURCE_ID --boundary KNOWN_SOURCE_ITEM_ID
```

Only a complete covered batch may progress to hash validation, ledger event reconciliation, then an execution claim. Persist candidates before advancing any boundary.

The collector exits `0` for complete coverage, `3` for a hold (the JSON on stdout retains candidates and continuation), and `1` for a file or validation error (JSON on stderr). Argument usage errors exit `2`. A nonzero exit must stop dependent processing. Pages and turns must be newest-first, with items inside each turn oldest-first. Backlogs beyond six pages need operator recovery; the helper has no automatic continuation input.

## Recovery and limitations

An executing record after interruption, an orphaned lock, uncertain delivery, malformed existing ledger or a gap in source history is a reconciliation hold. Inspect the recorded owner, destination and direct receipts; do not delete locks or repeat external effects automatically. Apply every cancellation in a covered batch before starting work. The helper validates retained operation indexes and correlation evidence before authorizing a claim; it does not reconstruct damaged indexes.

Result packets remain immutable. The helper can reconcile an uncertain transport receipt to a verified sent receipt, but cannot replace a persisted partial/uncertain domain result or reset a send claim proved unsent. Those cases and incomplete imports require a reviewed recovery procedure. See the operator guide for the exact supported transitions.

The ledger suppresses duplicates and operation aliases. It cannot guarantee exactly-once effects across external services. ACKs certify result receipt, not completion of the underlying task.

A configured heartbeat interval is not a delivery guarantee. OS restart, machine sleep, offline recovery, application-version changes and bot-wide discovery need their own acceptance checks. Installation in a local skill directory does not install anything in AZ.

## Sharing

Keep private routes, ledgers, logs, receipts, screenshots and incident reports outside the repository. The included fixtures use synthetic data. Review both working files and Git history before publication.

The included code and documentation are released under the [MIT license](LICENSE). Private runtime records are excluded from this package and the publication; the code license grants no right to access or redistribute another operator's private data. Every deployment requires its own verified route, human delegation and acceptance evidence.
