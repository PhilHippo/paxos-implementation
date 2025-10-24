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
        """Handle ACCEPTED message from acceptor"""
        instance = data["instance"]
        proposal_id = tuple(data["proposal_id"])
        acceptor_id = data["acceptor_id"]
        value = data["value"]
        
        logging.debug(f"Received ACCEPTED from acceptor {acceptor_id} for instance {instance} proposal {proposal_id} with value {value}")
        
        # Skip if we've already learned this instance
        if instance in self.learned_values:
            return
        
        # Track this acceptance
        if instance not in self.accepted_proposals:
            self.accepted_proposals[instance] = {}
        if proposal_id not in self.accepted_proposals[instance]:
            self.accepted_proposals[instance][proposal_id] = {}
        
        self.accepted_proposals[instance][proposal_id][acceptor_id] = value
        
        # Check if we have a quorum for this proposal
        if len(self.accepted_proposals[instance][proposal_id]) >= self.quorum_size:
            # Value is learned!
            # Check that all acceptors in quorum agreed on same value
            values = list(self.accepted_proposals[instance][proposal_id].values())
            if len(set(values)) == 1:  # All same value
                learned_value = values[0]
                
                # Mark as learned and output
                self.learned_values[instance] = learned_value
                logging.debug(f"LEARNED value: {learned_value} for instance {instance} (proposal {proposal_id})")
                print(learned_value)
                sys.stdout.flush()
            else:
                logging.warning(f"Quorum reached for instance {instance} but acceptors have different values!")

