# Paxos Implementation Guide - Milestone 1

## Overview

This guide explains the implementation of **Milestone 1: Synod Algorithm** for the Paxos consensus protocol. The implementation provides a fault-tolerant atomic broadcast service that can handle message loss and crash failures while guaranteeing safety properties (total order, agreement, and integrity).

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Key Design Decisions](#key-design-decisions)
3. [Implementation Details](#implementation-details)
4. [Message Flow](#message-flow)
5. [Testing and Validation](#testing-and-validation)
6. [Troubleshooting](#troubleshooting)

---

## Architecture Overview

The system consists of four main components that communicate via IP multicast:

```
Clients → Proposers → Acceptors → Learners
           ↑____________↓
           (Promise/Accept loop)
```

### Component Roles

- **Clients**: Generate values to be decided upon
- **Proposers**: Orchestrate the consensus protocol (Phase 1 and 2)
- **Acceptors**: Vote on proposals (fixed at 3 acceptors)
- **Learners**: Detect when consensus is reached and output decided values

---

## Key Design Decisions

### 1. Multi-Instance Paxos

While Milestone 1 focuses on the Synod algorithm (single-value consensus), the implementation supports **multiple independent Paxos instances**. Each client value is assigned to a new instance, allowing the system to decide on a sequence of values.

**Why?** This design bridges Milestone 1 and Milestone 2, making the transition to Multi-Paxos straightforward.

```python
# Each instance has independent state
self.promised_id = {}    # {instance: (count, proposer_id)}
self.accepted_id = {}    # {instance: (count, proposer_id)}
self.accepted_value = {}  # {instance: value}
```

### 2. Proposal ID Structure

Proposal IDs are tuples: `(count, proposer_id)`

- **count**: Incremented on each retry (primary comparison key)
- **proposer_id**: Process ID used as tiebreaker

```python
def is_greater_than(p1, p2):
    """
    Compare proposal IDs: (count1, pid1) vs (count2, pid2)
    Returns True if p1 > p2
    """
    count1, pid1 = p1
    count2, pid2 = p2
    
    if count1 > count2:
        return True
    elif count1 == count2:
        return pid1 > pid2
    else:
        return False
```

**Why?** This ensures total ordering of proposals and prevents ties between concurrent proposers.

### 3. Fixed Acceptor Count

The system uses exactly **3 acceptors** with a quorum size of **2** (majority).

```python
self.n_acceptors = 3
self.quorum_size = (self.n_acceptors // 2) + 1  # = 2
```

**Why?** As specified in the requirements, this provides fault tolerance (can tolerate 1 acceptor failure) while keeping the system manageable.

### 4. Timeout and Retry Mechanism

Proposers use a **1-second timeout** when waiting for promises. If a quorum is not reached, they retry with an incremented proposal count.

```python
timeout_remaining = self.timeout  # 1.0 seconds
ready, _, _ = select.select([self.r], [], [], timeout_remaining)
if not ready:
    # Timeout: retry with higher proposal number
    self.handle_timeout(instance)
```

**Why?** Prevents proposers from blocking indefinitely if messages are lost or acceptors crash.

---

## Implementation Details

### Proposer (`src/proposer.py`)

**State Management:**
```python
self.instance_num = 0           # Current instance counter
self.proposal_count = {}        # {instance: count}
self.current_value = {}         # {instance: value}
self.promises_received = {}     # {instance: {acceptor_id: (accepted_id, value)}}
self.phase = {}                 # {instance: 'prepare' or 'accept'}
self.pending_values = []        # Queue of client values
```

**Key Methods:**

1. **`run()`**: Main event loop
   - Checks if a new instance can be started
   - Receives and processes messages (client values, promises, accepted notifications)
   - Queues client values when busy

2. **`propose(instance, value)`**: Initiates Phase 1a
   - Increments proposal count for the instance
   - Sends `PREPARE` message to all acceptors
   - Calls `wait_for_phase1b()` with timeout

3. **`wait_for_phase1b(instance)`**: Waits for promises with timeout
   - Uses `select.select()` for non-blocking I/O
   - Handles incoming messages during wait
   - Triggers timeout if quorum not reached

4. **`handle_promise(data)`**: Processes Phase 1b promises
   - Validates proposal ID matches current proposal
   - Stores promise from acceptor
   - Triggers Phase 2 when quorum reached

5. **`start_phase2(instance)`**: Initiates Phase 2a
   - Selects value to propose:
     - If any acceptor previously accepted a value, use the one with highest proposal_id
     - Otherwise, use client's value
   - Sends `ACCEPT` message to all acceptors

6. **`handle_timeout(instance)`**: Retry logic
   - Resets phase
   - Calls `propose()` again with incremented count

**Message Format Examples:**
```json
// PREPARE (Phase 1a)
{
  "type": "prepare",
  "instance": 1,
  "proposal_id": [1, 1]  // [count, proposer_id]
}

// ACCEPT (Phase 2a)
{
  "type": "accept",
  "instance": 1,
  "proposal_id": [1, 1],
  "value": "42"
}
```

---

### Acceptor (`src/acceptor.py`)

**State Management:**
```python
self.promised_id = {}      # {instance: (count, proposer_id)}
self.accepted_id = {}      # {instance: (count, proposer_id)}
self.accepted_value = {}   # {instance: value}
```

**Key Methods:**

1. **`handle_prepare(data)`**: Processes Phase 1a
   - Extracts instance and proposal_id
   - Compares with promised_id for this instance
   - If proposal_id is higher:
     - Updates promised_id
     - Sends `PROMISE` back to proposers with any previously accepted value
   - Otherwise: silently ignores (or logs rejection)

2. **`handle_accept(data)`**: Processes Phase 2a
   - Checks if proposal_id >= promised_id
   - If acceptable:
     - Updates promised_id, accepted_id, accepted_value
     - Sends `ACCEPTED` to learners
   - Otherwise: rejects

**Message Format Examples:**
```json
// PROMISE (Phase 1b)
{
  "type": "promise",
  "instance": 1,
  "proposal_id": [1, 1],
  "acceptor_id": 1,
  "accepted_id": null,      // or [count, pid] if previously accepted
  "accepted_value": null    // or the value
}

// ACCEPTED (Phase 2b)
{
  "type": "accepted",
  "instance": 1,
  "proposal_id": [1, 1],
  "acceptor_id": 1,
  "value": "42"
}
```

---

### Learner (`src/learner.py`)

**State Management:**
```python
self.n_acceptors = 3
self.quorum_size = 2
self.accepted_proposals = {}  # {instance: {proposal_id: {acceptor_id: value}}}
self.learned_values = {}      # {instance: value}
```

**Key Methods:**

1. **`handle_accepted(data)`**: Processes Phase 2b
   - Extracts instance, proposal_id, acceptor_id, value
   - Skips if instance already learned
   - Tracks acceptance in nested dictionary
   - Checks for quorum:
     - If >= 2 acceptors accepted same (instance, proposal_id, value)
     - Marks as learned
     - Outputs value to stdout (required for tests)

**Output Format:**
```
42
17
99
```
(One value per line, no other output)

---

### Utility Functions (`src/utils.py`)

**`is_greater_than(p1, p2)`**
- Compares two proposal IDs
- Primary: compare counts
- Tiebreaker: compare proposer IDs
- Returns boolean

**Existing utilities:**
- `load_config()`: Reads JSON config with multicast addresses
- `mcast_receiver()`: Creates multicast socket for receiving
- `mcast_sender()`: Creates UDP socket for sending

---

## Message Flow

### Complete Protocol Flow for One Value

```
Client                Proposer 1              Acceptor 1,2,3           Learner 1,2
  |                       |                         |                      |
  |--value="42"---------->|                         |                      |
  |                       |                         |                      |
  |                    [Start instance 1]           |                      |
  |                       |                         |                      |
  |                       |--PREPARE(1,[1,1])------>|                      |
  |                       |                         |                      |
  |                       |<--PROMISE(1,[1,1],...)--|                      |
  |                       |<--PROMISE(1,[1,1],...)--|                      |
  |                       |  [Quorum reached]       |                      |
  |                       |                         |                      |
  |                       |--ACCEPT(1,[1,1],"42")-->|                      |
  |                       |                         |                      |
  |                       |                         |--ACCEPTED(1,[1,1],"42")-->|
  |                       |                         |--ACCEPTED(1,[1,1],"42")-->|
  |                       |                         |  [Quorum reached]    |
  |                       |                         |                      |
  |                       |                         |                  [Output: 42]
```

### Handling Concurrent Proposers

When multiple proposers compete for the same instance:

```
Proposer 1                  Acceptor                  Proposer 2
    |                          |                          |
    |--PREPARE(1,[1,1])------->|                          |
    |                          |<--PREPARE(1,[1,2])-------|
    |                          |                          |
    |<--PROMISE(1,[1,2],...)---|--PROMISE(1,[1,2],...)-->|
    |  [Rejected: lower ID]    |  [Accepted: higher ID]  |
    |                          |                          |
    |  [Timeout & Retry]       |                          |
    |--PREPARE(1,[2,1])------->|<--ACCEPT(1,[1,2],"X")---|
    |                          |                          |
    |<--PROMISE(1,[2,1],"X")---|                          |
    |  [Must use value "X"]    |                          |
    |--ACCEPT(1,[2,1],"X")---->|                          |
```

**Key Point:** Paxos guarantees that once a value is accepted by a quorum, all future proposals for that instance will propose the same value.

---

## Testing and Validation

### Basic Test (No Message Loss)

```bash
cd /path/to/paxos-implementation-1
scripts/run.sh -n 100
scripts/check.sh
```

**Expected Output:**
```
Test 1 - Learners learned the same set of values in total order
  > OK
Test 2 - Values learned were actually proposed
  > OK
Test 3 - Learners learned every value that was sent by some client
  > OK
```

### Test with Message Loss

```bash
# 10% message loss, longer sleep time to allow retries
sudo scripts/run.sh -n 20 --loss 0.1 -s 4
scripts/check.sh
```

**Note:** With message loss, some values may not be decided due to timeouts. The key property is **safety**: all learners that do learn a value agree on it.

### Debug Mode

```bash
scripts/run.sh -n 10 -d
```

This enables detailed logging. Check logs in `logs/` directory:
- `logs/proposer1.log`, `logs/proposer2.log`
- `logs/acceptor1.log`, `logs/acceptor2.log`, `logs/acceptor3.log`
- `logs/learner1.log`, `logs/learner2.log`

### Cleanup After Message Loss Tests

If you interrupt a test with message loss:
```bash
sudo scripts/cleanup.sh
```

This removes iptables rules that simulate packet drops.

---

## Troubleshooting

### Problem: No values learned

**Symptoms:**
- Learners output nothing
- `check.sh` reports missing values

**Possible Causes:**
1. **Timeout too short**: Increase sleep time with `-s` flag
2. **High message loss**: Reduce `--loss` percentage
3. **Proposer not starting instances**: Check if proposers are receiving client values

**Debug Steps:**
```bash
# Run with debug mode
scripts/run.sh -n 5 -d

# Check proposer logs
cat logs/proposer1.log | grep "Received value from client"
cat logs/proposer1.log | grep "Quorum reached"

# Check acceptor logs
cat logs/acceptor1.log | grep "Accepted proposal"

# Check learner logs
cat logs/learner1.log | grep "LEARNED"
```

### Problem: Learners learn different values

**Symptoms:**
- Test 1 fails: "Learners learned different values"

**This should NOT happen** - it violates Paxos safety. If it does:
1. Check `is_greater_than()` logic
2. Verify acceptors are checking `promised_id` correctly
3. Ensure proposal IDs are unique per proposer

### Problem: Duplicated values learned

**Symptoms:**
- Same value appears multiple times in learner output

**Cause:** Instance numbers not incrementing properly, or learner not tracking learned instances.

**Fix:** Check that:
- Proposer increments `instance_num` for each new value
- Learner checks `if instance in self.learned_values` before processing

### Problem: Process hangs during shutdown

**Symptoms:**
- `run.sh` takes long to complete
- Processes don't respond to `pkill`

**Solution:**
- Close the terminal and open a new one
- Manually kill: `pkill -9 -f "python3 src/main.py"`

### Problem: Multicast not working

**Symptoms:**
- No messages received by any component
- Logs show only startup messages

**Solution:**
```bash
# Check multicast is enabled
ifconfig eth0 | grep MULTICAST

# Enable if needed
sudo ifconfig eth0 multicast
```

---

## Performance Characteristics

### Latency per Value (No Message Loss)

- **Phase 1 (Prepare/Promise)**: ~1-5ms
- **Phase 2 (Accept/Accepted)**: ~1-5ms
- **Total**: ~2-10ms per value

### Throughput

- **Without loss**: ~100-500 values/second (depends on system)
- **With 10% loss**: Significantly reduced due to timeouts and retries

### Message Complexity

For each decided value:
- **Prepare**: 1 multicast to 3 acceptors
- **Promise**: 3 messages to proposers
- **Accept**: 1 multicast to 3 acceptors
- **Accepted**: 3 messages to learners

**Total**: ~8 messages per value (in the best case)

---

## Next Steps: Milestone 2 (Multi-Paxos)

The current implementation already supports multiple instances, making it a good foundation for Multi-Paxos optimizations:

1. **Leader Election**: Designate one proposer as leader to avoid conflicts
2. **Skip Phase 1**: Leader can skip Phase 1 for subsequent instances after being elected
3. **Batching**: Combine multiple client values into one Paxos instance
4. **Catchup Mechanism**: Allow late learners to learn previously decided values

---

## Code Structure Summary

```
src/
├── __init__.py          # Empty module marker
├── main.py              # Entry point, parses arguments and starts roles
├── client.py            # Sends values to proposers
├── proposer.py          # Implements Paxos proposer role
├── acceptor.py          # Implements Paxos acceptor role
├── learner.py           # Implements Paxos learner role
└── utils.py             # Helper functions (multicast, is_greater_than)

scripts/
├── run.sh               # Main test runner
├── check.sh             # Validates learned values
└── cleanup.sh           # Removes iptables rules

logs/                    # Created during runs
├── config.json          # Generated multicast configuration
├── values1.log          # Client 1's proposed values
├── values2.log          # Client 2's proposed values
├── proposer*.log        # Proposer logs
├── acceptor*.log        # Acceptor logs
└── learner*.log         # Learner logs (contain decided values)
```

---

## References

- **Paxos Made Simple** by Leslie Lamport
- **Paxos Made Moderately Complex** by Robbert van Renesse and Deniz Altinbuken
- Original project specification: `project.pdf`

---

## Contact & Support

For questions or issues with this implementation, refer to:
- Course materials
- Project PDF specification
- This implementation guide

**Last Updated:** October 23, 2025
