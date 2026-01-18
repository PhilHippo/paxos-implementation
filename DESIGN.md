# Multi-Paxos Design Document

This document describes the design decisions and implementation details of the Multi-Paxos consensus system.

## System Model

The system assumes:
- **Asynchronous network**: No timing guarantees on message delivery
- **Crash failures**: Nodes may fail by crashing (no Byzantine faults)
- **IP Multicast**: All communication uses UDP multicast groups

## Roles and Responsibilities

### Clients
- Submit user values to proposers via multicast
- Optionally measure end-to-end latency by listening for learned values

### Proposers
- Coordinate Paxos rounds (Phase 1A and Phase 2A)
- Batch multiple client requests into single consensus instances
- Implement proactive prepare optimization to reduce latency

### Acceptors
- Maintain promise state (`rnd`) and accepted history per instance
- Respond to prepare requests (1A → 1B)
- Accept proposals and multicast accepts to learners and proposers (2A → 2B)
- Support catch-up queries from learners

### Learners
- Collect 2B votes and detect quorums (majority of acceptors)
- Maintain delivery buffer for total order guarantee
- Perform catch-up recovery for missing instances

## Message Types

| Message | Direction | Payload |
|---------|-----------|---------|
| `client` | Client → Proposers | `(value, msg_num, client_id)` |
| `1A` | Proposer → Acceptors | `(c_rnd, proposer_id)` |
| `1B` | Acceptor → Proposers | `(rnd, max_inst, proposer_id)` |
| `2A` | Proposer → Acceptors | `(c_rnd, c_val, proposer_id, instance_id)` |
| `2B` | Acceptor → Learners/Proposers | `(v_rnd, v_val, instance_id)` |
| `QueryLastInstance` | Learner → Acceptors | - |
| `LastInstanceResponse` | Acceptor → Learners | `(highest_instance_id)` |
| `Catchup` | Learner → Acceptors | `(instance_id)` |
| `CatchupResponse` | Acceptor → Learners | `(instance_id, value)` |

## Protocol Flow

### Normal Operation

```
Client          Proposer        Acceptor        Learner
   |                |               |               |
   |---[client]---->|               |               |
   |                |----[1A]------>|               |
   |                |<---[1B]-------|               |
   |                |----[2A]------>|               |
   |                |<---[2B]-------|---[2B]------->|
   |                |               |               |
```

### With Proactive Prepare (Optimization)

```
Client          Proposer        Acceptor        Learner
   |                |               |               |
   |                |----[1A]------>|  (proactive)  |
   |                |<---[1B]-------|               |
   |---[client]---->|               |               |
   |                |----[2A]------>|  (skip 1A!)   |
   |                |<---[2B]-------|---[2B]------->|
```

## Key Optimizations

### 1. Request Batching

Proposers accumulate client requests and propose them as a single batch value:

- Configurable batch size via `-b` flag
- Reduces number of consensus instances needed
- Batch is the atomic unit for each Paxos instance

### 2. Proactive Prepares

After completing a consensus round, proposers immediately send a new 1A:

- If a quorum responds before the next client request arrives, the proposer can skip 1A
- Reduces latency from 4 message delays to 2 for subsequent requests
- Stores `proactive_instance_seq` to track the reserved instance slot

### 3. Reduced 1B Payload

Traditional Paxos sends full accepted history in 1B. Our optimization:

- Acceptors only send `max_inst` (highest known instance ID)
- Proposers use this to compute next available slot: `max(local, max_inst + 1)`
- Significantly reduces 1B message size

### 4. Dual 2B Multicast

Acceptors send 2B to both learners and proposers:

- **Learners**: Learn values directly (saves one message hop)
- **Proposers**: Flow control - know when to proceed to next request

## Learner Catch-up Mechanism

### Bootstrap Recovery

1. On startup, learner sends `QueryLastInstance` to acceptors
2. Receives `LastInstanceResponse` with highest known instance
3. Requests catch-up for all instances from 0 to highest

### Gap Detection

During normal operation, if learner receives instance N but expects instance M (where M < N):

1. Buffer instance N
2. Request catch-up for instances M to N-1
3. Deliver values in order once gaps are filled

### Rate-Limited Retries

- Batch catch-up requests in groups of 200
- Small delays between batches to prevent network flooding
- Periodic retry (every 100ms) for outstanding requests

## Quorum Requirements

- **Majority**: `⌊n/2⌋ + 1` acceptors (where n = total acceptors)
- Same quorum size used for both Phase 1 and Phase 2
- Ensures any two quorums have at least one common member

## Total Order Delivery

Learners guarantee total order delivery using:

1. **Instance buffer**: Maps instance_id → value
2. **Global sequence**: Tracks next expected instance for delivery
3. **In-order drain**: Only delivers when consecutive instances are available

```python
while global_next_seq in instance_buffer:
    deliver(instance_buffer[global_next_seq])
    del instance_buffer[global_next_seq]
    global_next_seq += 1
```

## Client-Level Deduplication

Within each batch, values are tagged with `(msg_num, client_id)`:

- Learners maintain per-client sequence numbers
- Values delivered in client-order within total consensus order
- Handles cases where same value appears in multiple batches
