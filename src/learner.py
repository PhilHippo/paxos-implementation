import sys
import logging
import json
from utils import mcast_receiver, mcast_sender


class Learner:
    def __init__(self, config, id):
        self.config = config
        self.id = id
        self.r = mcast_receiver(config["learners"])
        
        # Learner state
        self.n_acceptors = 3  # Fixed number of acceptors
        self.quorum_size = (self.n_acceptors // 2) + 1  # Majority
        self.accepted_proposals = {}  # {instance: {proposal_id: {acceptor_id: value}}}
        self.learned_values = {}  # {instance: value} Learned values per instance
        
        # Lamport logical clock
        self.logical_clock = 0

    def run(self):
        logging.debug(f"-> learner {self.id}")
        while True:
            msg, addr = self.r.recvfrom(2**16)
            
            try:
                data = json.loads(msg.decode())
                msg_type = data.get("type")
                
                if msg_type == "accepted":
                    self.handle_accepted(data)
                else:
                    logging.debug(f"Unknown message type: {msg_type}")
                    
            except json.JSONDecodeError:
                logging.debug(f"Received non-JSON message: {msg.decode()}")

    def handle_accepted(self, data):
        """
        Phase 3: upon receiving (PHASE 2B, v-rnd, v-val) from Qa
        if for all received messages: v-rnd = c-rnd then
            send (DECISION, v-val) to learners
        
        In practice, learners collect ACCEPTED messages and learn when
        a quorum of acceptors have accepted the same (v-rnd, v-val)
        """
        # LC2(b): Update logical clock based on received timestamp
        if "timestamp" in data:
            self.logical_clock = max(self.logical_clock, data["timestamp"])
        
        # LC1: Increment before timestamping this receive event
        self.logical_clock += 1
        
        instance = data["instance"]
        v_rnd = tuple(data["v_rnd"])
        acceptor_id = data["acceptor_id"]
        v_val = data["v_val"]
        
        logging.debug(f"Received ACCEPTED (Phase 2B) from acceptor {acceptor_id} for instance {instance} v-rnd {v_rnd} with v-val {v_val}")
        
        # Skip if we've already learned this instance
        if instance in self.learned_values:
            return
        
        # Track this acceptance
        if instance not in self.accepted_proposals:
            self.accepted_proposals[instance] = {}
        if v_rnd not in self.accepted_proposals[instance]:
            self.accepted_proposals[instance][v_rnd] = {}
        
        self.accepted_proposals[instance][v_rnd][acceptor_id] = v_val
        
        # Check if we have a quorum (Qa) for this v-rnd
        if len(self.accepted_proposals[instance][v_rnd]) >= self.quorum_size:
            # Check that all acceptors in quorum agreed on same v-val
            values = list(self.accepted_proposals[instance][v_rnd].values())
            if len(set(values)) == 1:  # All same value
                learned_value = values[0]
                
                # Mark as learned and output (DECISION)
                self.learned_values[instance] = learned_value
                logging.debug(f"LEARNED (DECISION): v-val {learned_value} for instance {instance} (v-rnd {v_rnd})")
                print(learned_value)
                sys.stdout.flush()
            else:
                logging.warning(f"Quorum Qa reached for instance {instance} but acceptors have different v-val!")

