# Multi-Paxos Implementation (IP Multicast)

The system assumes an asynchronous network with crash failures and uses IP multicast for all roles.

## Roles and Responsibilities
- Clients: submit user values to proposers
- Proposers: coordinate rounds, batch client requests, and skip 1A with proactive prepares.
- Acceptors: maintain accepted instance history, respond to prepares, and multicast accepts to learners and proposers.
- Learners: collect 2B votes, detect quorums, deliver ordered values, and catch up missing instances.

## Message Types
- `client`: client → proposers; payload `(value, msg_num, client_id)`.
- `1A`: proposer → acceptors; payload `(c_rnd, proposer_id)`.
- `1B`: acceptor → proposers; payload `(rnd, max_inst, proposer_id)` where `max_inst` is highest instance the acceptor knows.
- `2A`: proposer → acceptors; payload `(c_rnd, c_val, proposer_id, instance_id)`.
- `2B` to learners and proposers: acceptor → learners; payload `(v_rnd, v_val, instance_id)`.
- Catchup: `QueryLastInstance` / `LastInstanceResponse` and `Catchup` / `CatchupResponse` between learners and acceptors.

## Proposer (batched Multi-Paxos)
- Batching: incoming client tuples are queued; `_create_batch` pulls up to `batch_size`. A batch is the value proposed for one instance.
- Instance numbering: `instance_seq` tracks the global sequence; 1B replies provide `max_inst` to pick `next_instance = max(local, max_inst+1)`.
- Proactive prepare optimization: if a quorum of 1B is acquired before a value arrives, the proposer records `proactive_instance_seq` and later skips a new 1A, going straight to 2A for the stored instance.
- Flow:
  1. On first value (or after consensus), send 1A unless a proactive quorum exists.
  2. Upon majority 1B, if a value exists, send 2A with chosen instance id; else mark proactive quorum and wait for value.
  3. On majority 2B (matching `c_rnd` and proposer id), advance `instance_seq`, clear current value, and immediately send another 1A (proactive) whether or not a new batch is queued.
- Majority size: `⌊n/2⌋ + 1` acceptors.

## Acceptor
- State: `rnd` (promise) and `accepted_history` keyed by `instance_id` storing `(v_rnd, v_val)`.
- 1A handling: if `c_rnd` is higher, update `rnd` and reply with `1B` carrying only `max_inst` to reduce traffic.
- 2A handling: if `c_rnd >= rnd`, record acceptance and multicast 2B to both learners and proposers.
- Catchup support: respond to `Catchup` with the accepted value for that instance; respond to `QueryLastInstance` with highest known instance id.

## Learner
- Quorum tracking: per-instance map from `(v_rnd, v_val)` to vote counts; quorum is majority of acceptors.
- Delivery buffer: `instance_buffer` where keys are instance id; `global_next_seq` is the next required instance for total order delivery.
- Catchup and gap recovery:
  - On start, send `QueryLastInstance` to acceptors.
  - On receiving `LastInstanceResponse`, request catchup for missing instances in range.
  - `request_catchup` batches `Catchup` requests with rate limiting; `retry_missing_catchup` periodically resends outstanding gaps.
  - `CatchupResponse` inserts missing instance values, triggers in-order drain of `instance_buffer`.
- Decision handling: also accepts `Decision` messages containing `(v_val, instance_id)` and uses the same in-order delivery path.


## Key Optimizations
- Proactive prepares: proposers keep a ready quorum so that when a value arrives they can jump directly to 2A.
- Reduced 1B payload: acceptors send only `max_inst`, not the full history.
- Dual 2B multicast: acceptors send 2B to learners (learning shortcut) and proposers (flow control and pipelining).
- Catchup: learners continuously detect gaps and rate-limit batched catchup requests.
- Batching of client requests: proposer batches up to `batch_size` requests as one Paxos value to increase throughput.


## Difficulties and Resolutions
- Implementing Synod by vibe code was confusing; following the reference slides step by step clarified the protocol and made the basic Paxos flow work.
- Understanding Multi-Paxos needed a discussion with colleagues; in the end a proposer-side queue of client messages and pop batches as they are proposed, while acceptors clear their `v_val` after each acceptance to prepare for the next instance.
- Running the same experiment parameters on different laptops produced divergent results (not all values learned); some machines required larger sleep (`-s`) delays.

