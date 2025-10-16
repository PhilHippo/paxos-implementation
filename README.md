# Paxos Atomic Broadcast Implementation

This repository contains an implementation of the Paxos protocol to solve atomic broadcast in an asynchronous system. This project was developed for the Distributed Algorithms course (Autumn 2025) at the Università della Svizzera italiana (USI).

## Project Overview

The goal of this project is to build a fault-tolerant atomic broadcast service using the Paxos consensus algorithm. The implementation is done in stages, starting from the basic Synod algorithm for single-value consensus, extending it to Multi-Paxos for a sequence of values, and finally incorporating performance optimizations.

The system is designed to tolerate crash failures and message loss while always guaranteeing safety (total order, agreement, and integrity).

### Key Concepts
*   **Paxos Protocol:** A family of protocols for solving consensus in a network of unreliable processors.
*   **Atomic Broadcast:** A reliable multicast primitive that ensures all correct processes deliver the same set of messages in the same order.
*   **System Roles:** The implementation is structured around four distinct roles: Clients, Proposers, Acceptors, and Learners, communicating via IP multicast.

### Milestones
1.  **Synod Algorithm:** Implementation of the basic Paxos protocol to agree on a single value.
2.  **Multi-Paxos:** Extension of the Synod algorithm to decide on a sequence of values in total order.
3.  **Optimizations:** Implementation of techniques such as message batching and reduced communication steps to improve performance.

## Implementation Details

This section outlines the design and implementation choices made for each milestone of the project.

### Milestone 1: Synod Algorithm

*   **Design Choices:**
    *   *(Describe the main architectural decisions. How are roles implemented? How is state managed?)*
*   **Data Structures:**
    *   `ProposalID`: *(Explain the structure of proposal numbers, e.g., a tuple of (sequence_number, proposer_id)).*
    *   `Proposer State`: *(List the key variables managed by a proposer, such as `proposal_id`, `proposed_value`, `promises_received`).*
    *   `Acceptor State`: *(List the key variables, like `promised_id`, `accepted_id`, `accepted_value`).*
*   **Message Flow:**
    *   **Phase 1a (Prepare):** Proposer sends a `Prepare(proposal_id)` message to all acceptors.
    *   **Phase 1b (Promise):** Acceptors respond with `Promise(promised_id, accepted_id, accepted_value)` if `proposal_id` is the highest seen.
    *   **Phase 2a (Accept):** After receiving a majority of promises, the proposer sends an `Accept(proposal_id, value)` message.
    *   **Phase 2b (Accepted):** Acceptors accept the proposal and notify learners by sending an `Accepted(proposal_id, accepted_value)` message.
    *   **Decision:** Learners learn a value upon receiving `Accepted` messages from a majority of acceptors.

### Milestone 2: Multi-Paxos

*   **Design Choices:**
    *   *(Explain how you extended the Synod algorithm. How are multiple instances managed? How is the leader elected or handled?)*
    *   *(Describe the mechanism for handling gaps in the learned sequence).*
*   **Data Structures:**
    *   `Learner State`: *(Detail the data structures used to store decided values in order, e.g., a dictionary or a list mapping instance numbers to values).*
    *   `Proposer/Acceptor State`: *(Describe any modifications to support multiple instances, e.g., storing states per instance number).*
*   **Message Flow:**
    *   *(Explain how messages are modified to include an instance number, e.g., `Prepare(instance, proposal_id)`).*
    *   *(Describe the process for a new learner to "catch up" on previously decided values).*

### Milestone 3: Optimizations

*   **Optimization 1: Acceptors Send to Learners Directly**
    *   **Implementation:** *(Explain how you modified the Phase 2b message flow. Acceptors now send `Accepted` messages directly to the Learner multicast group instead of back to the Proposer).*
*   **Optimization 2: Phase 1 Before Value is Known**
    *   **Implementation:** *(Describe how the leader performs Phase 1 for a future instance as soon as the current one is decided, without waiting for a new value from a client).*
*   **Optimization 3: Batching**
    *   **Implementation:** *(Detail how multiple client values are batched into a single Paxos instance. Explain the data structure used for the batch and how learners process it).*

## Running the Implementation

For detailed information on dependencies, environment setup, and how to run the tests and generate plots, please refer to the detailed instructions document.

**➡️ [View Detailed Setup and Running Instructions](instructions.md)**