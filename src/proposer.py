"""
Paxos Proposer implementation.

The proposer coordinates consensus rounds by:
1. Sending Phase 1A (prepare) messages to acceptors
2. Collecting Phase 1B (promise) responses to form a quorum
3. Sending Phase 2A (accept) messages with the proposed value
4. Waiting for Phase 2B (accepted) responses before proceeding

Optimizations:
- Request batching: Multiple client values are batched into single instances
- Proactive prepares: Pre-acquire quorum to skip Phase 1A on next request
"""

import logging
import math
import pickle
from collections import deque

from utils import mcast_receiver, mcast_sender


class Proposer:
    def __init__(self, config, node_id, batch_size=1):
        self.config = config
        self.id = node_id
        self.batch_size = batch_size
        
        # Paxos state
        self.c_rnd = 0  # Current round number
        self.quorum_1B = []  # Phase 1B responses
        self.quorum_2B = []  # Phase 2B responses
        self.value = None  # Current batch being proposed
        
        # Client request queue
        self.queue = deque()
        
        # Instance tracking
        self.consensus_instance = 0
        self.majority_acceptors = math.floor(config["n"] / 2) + 1
        
        # Proactive prepare optimization
        self.has_proactive_quorum = False
        self.proactive_instance = None
        
        # Network
        self.r = mcast_receiver(config["proposers"])
        self.s = mcast_sender()

    def send_1A(self):
        """Send Phase 1A (prepare) message to all acceptors."""
        self.c_rnd += 1
        self.quorum_1B = []
        self.quorum_2B = []
        self.has_proactive_quorum = False
        self.proactive_instance = None

        msg_1A = pickle.dumps(["1A", self.c_rnd, self.id])
        self.s.sendto(msg_1A, self.config["acceptors"])
        logging.debug(f"Sent 1A: round={self.c_rnd}")

    def _create_batch(self):
        """Create a batch of up to batch_size values from the queue."""
        batch = []
        for _ in range(min(self.batch_size, len(self.queue))):
            batch.append(self.queue.popleft())
        return batch

    def _handle_client_message(self, msg):
        """Handle incoming client request."""
        value, msg_num, client_id = msg[1:]
        
        # Add to queue
        self.queue.append((msg_num, client_id, value))
        logging.debug(f"Queued client request: msg_num={msg_num}, client={client_id}")

        # If no value is being proposed, start a new proposal
        if self.value is None:
            batch = self._create_batch()
            self.value = batch
            
            # Optimization: skip 1A if we have a proactive quorum
            if self.has_proactive_quorum and self.proactive_instance is not None:
                self.consensus_instance = self.proactive_instance
                msg_2A = pickle.dumps(["2A", self.c_rnd, self.value, self.id, self.consensus_instance])
                self.s.sendto(msg_2A, self.config["acceptors"])
                logging.debug(f"Sent 2A (proactive): instance={self.consensus_instance}")
                self.has_proactive_quorum = False
                self.proactive_instance = None
            else:
                self.send_1A()

    def _handle_1B(self, msg):
        """Handle Phase 1B (promise) response from acceptor."""
        rnd, max_inst, proposer_id = msg[1:]
        
        if rnd != self.c_rnd:
            return
        
        self.quorum_1B.append(max_inst)
        logging.debug(f"Received 1B: quorum_size={len(self.quorum_1B)}")
        
        if len(self.quorum_1B) == self.majority_acceptors:
            # Compute next available instance slot
            max_inst_global = max(self.quorum_1B)
            next_instance = max(self.consensus_instance, max_inst_global + 1)
            
            if self.value is not None:
                # We have a value, proceed with 2A
                self.consensus_instance = next_instance
                msg_2A = pickle.dumps(["2A", self.c_rnd, self.value, self.id, self.consensus_instance])
                self.s.sendto(msg_2A, self.config["acceptors"])
                logging.debug(f"Sent 2A: instance={self.consensus_instance}")
            else:
                # No value yet, store proactive quorum
                self.has_proactive_quorum = True
                self.proactive_instance = next_instance
                logging.debug(f"Proactive quorum ready for instance {next_instance}")

    def _handle_2B(self, msg):
        """Handle Phase 2B (accepted) response from acceptor."""
        v_rnd, v_val, proposer_id = msg[1:]
        
        if v_rnd != self.c_rnd or proposer_id != self.id:
            return
        
        self.quorum_2B.append((v_rnd, v_val))
        logging.debug(f"Received 2B: quorum_size={len(self.quorum_2B)}")
        
        if len(self.quorum_2B) == self.majority_acceptors:
            # Consensus reached
            logging.debug(f"Consensus reached for instance {self.consensus_instance}")
            
            self.consensus_instance += 1
            self.value = None
            
            # Start next round (proactive or with queued value)
            if self.queue:
                batch = self._create_batch()
                self.value = batch
            
            self.send_1A()

    def run(self):
        """Main proposer loop."""
        logging.info(f"Proposer {self.id} started (acceptors={self.config['n']})")
        
        while True:
            msg, addr = self.r.recvfrom(2**16)
            msg = pickle.loads(msg)
            logging.debug(f"Received: {msg[0]}")

            match msg[0]:
                case "client":
                    self._handle_client_message(msg)
                case "1B":
                    self._handle_1B(msg)
                case "2B":
                    self._handle_2B(msg)
                case _:
                    logging.warning(f"Unknown message type: {msg[0]}")
