"""
Paxos Acceptor implementation.

The acceptor maintains consensus state and responds to proposer requests:
- Phase 1A: Promise not to accept older rounds, reply with max known instance
- Phase 2A: Accept proposal if round is valid, broadcast to learners and proposers

Also supports learner catch-up by responding to instance queries.
"""

import logging
import pickle

from utils import mcast_receiver, mcast_sender


class Acceptor:
    def __init__(self, config, node_id):
        self.config = config
        self.id = node_id
        
        # Paxos state
        self.rnd = 0  # Highest promised round
        self.accepted_history = {}  # {instance_id: (v_rnd, v_val)}
        
        # Network
        self.r = mcast_receiver(config["acceptors"])
        self.s = mcast_sender()

    def _handle_1A(self, msg):
        """Handle Phase 1A (prepare) request from proposer."""
        c_rnd, proposer_id = msg[1:]
        
        if c_rnd <= self.rnd:
            return  # Ignore lower rounds
        
        self.rnd = c_rnd
        
        # Optimization: Only send max_inst instead of full history
        max_inst = max(self.accepted_history.keys()) if self.accepted_history else -1
        
        msg_1B = pickle.dumps(["1B", self.rnd, max_inst, proposer_id])
        self.s.sendto(msg_1B, self.config["proposers"])
        logging.debug(f"Sent 1B: rnd={self.rnd}, max_inst={max_inst}")

    def _handle_2A(self, msg):
        """Handle Phase 2A (accept) request from proposer."""
        c_rnd, c_val, proposer_id, instance_id = msg[1:]
        
        if c_rnd < self.rnd:
            return  # Reject lower rounds
        
        # Accept the value
        self.accepted_history[instance_id] = (c_rnd, c_val)
        
        # Send 2B to learners (for learning)
        msg_2B_learner = pickle.dumps(["2B", c_rnd, c_val, instance_id])
        self.s.sendto(msg_2B_learner, self.config["learners"])
        
        # Send 2B to proposers (for flow control)
        msg_2B_proposer = pickle.dumps(["2B", c_rnd, c_val, proposer_id])
        self.s.sendto(msg_2B_proposer, self.config["proposers"])
        
        logging.debug(f"Accepted instance {instance_id}, sent 2B")

    def _handle_catchup(self, msg):
        """Handle catch-up request from learner."""
        req_instance_id = msg[1]
        
        if req_instance_id not in self.accepted_history:
            return
        
        v_rnd, val = self.accepted_history[req_instance_id]
        resp = pickle.dumps(["CatchupResponse", req_instance_id, val])
        self.s.sendto(resp, self.config["learners"])
        logging.debug(f"Sent CatchupResponse for instance {req_instance_id}")

    def _handle_query_last_instance(self):
        """Handle query for highest known instance from learner."""
        max_inst = max(self.accepted_history.keys()) if self.accepted_history else -1
        
        resp = pickle.dumps(["LastInstanceResponse", max_inst])
        self.s.sendto(resp, self.config["learners"])
        logging.debug(f"Sent LastInstanceResponse: {max_inst}")

    def run(self):
        """Main acceptor loop."""
        logging.info(f"Acceptor {self.id} started")
        
        while True:
            msg, addr = self.r.recvfrom(2**16)
            msg = pickle.loads(msg)
            logging.debug(f"Received: {msg[0]}")

            match msg[0]:
                case "1A":
                    self._handle_1A(msg)
                case "2A":
                    self._handle_2A(msg)
                case "Catchup":
                    self._handle_catchup(msg)
                case "QueryLastInstance":
                    self._handle_query_last_instance()
                case _:
                    logging.warning(f"Unknown message type: {msg[0]}")
