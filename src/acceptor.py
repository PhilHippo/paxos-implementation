import logging
import json
from utils import mcast_receiver, mcast_sender, is_greater_than


class Acceptor:
    def __init__(self, config, id):
        self.config = config
        self.id = id
        self.r = mcast_receiver(config["acceptors"])
        self.s = mcast_sender()
        
        # Acceptor state per instance
        self.promised_id = {}  # {instance: (count, proposer_id)} Highest proposal ID promised
        self.accepted_id = {}  # {instance: (count, proposer_id)} Highest proposal ID accepted
        self.accepted_value = {}  # {instance: value} Value of the accepted proposal

    def run(self):
        logging.info(f"-> acceptor {self.id}")
        while True:
            msg, addr = self.r.recvfrom(2**16)
            
            try:
                data = json.loads(msg.decode())
                msg_type = data.get("type")
                
                if msg_type == "prepare":
                    self.handle_prepare(data)
                elif msg_type == "accept":
                    self.handle_accept(data)
                else:
                    logging.debug(f"Unknown message type: {msg_type}")
                    
            except json.JSONDecodeError:
                logging.debug(f"Received non-JSON message: {msg.decode()}")

    def handle_prepare(self, data):
        """Handle PREPARE message (Phase 1a)"""
        instance = data["instance"]
        proposal_id = tuple(data["proposal_id"])
        
        logging.debug(f"Received PREPARE for instance {instance} with proposal_id {proposal_id}")
        
        # Check if we should promise
        if instance not in self.promised_id or is_greater_than(proposal_id, self.promised_id[instance]):
            # Update promised_id
            self.promised_id[instance] = proposal_id
            
            # Phase 1b: Send PROMISE back to proposer
            promise_msg = {
                "type": "promise",
                "instance": instance,
                "proposal_id": list(proposal_id),
                "acceptor_id": self.id,
                "accepted_id": list(self.accepted_id[instance]) if instance in self.accepted_id else None,
                "accepted_value": self.accepted_value.get(instance)
            }
            
            logging.debug(f"Sending PROMISE for instance {instance} proposal_id {proposal_id}")
            self.s.sendto(json.dumps(promise_msg).encode(), self.config["proposers"])
        else:
            logging.debug(f"Rejecting PREPARE for instance {instance} (already promised to {self.promised_id[instance]})")

    def handle_accept(self, data):
        """Handle ACCEPT message (Phase 2a)"""
        instance = data["instance"]
        proposal_id = tuple(data["proposal_id"])
        value = data["value"]
        
        logging.debug(f"Received ACCEPT for instance {instance} with proposal_id {proposal_id} and value {value}")
        
        # Check if we should accept
        # Accept if proposal_id >= promised_id (we promised not to accept lower)
        if instance not in self.promised_id or not is_greater_than(self.promised_id[instance], proposal_id):
            # Accept the proposal
            self.promised_id[instance] = proposal_id
            self.accepted_id[instance] = proposal_id
            self.accepted_value[instance] = value
            
            # Phase 2b: Send ACCEPTED to learners
            accepted_msg = {
                "type": "accepted",
                "instance": instance,
                "proposal_id": list(proposal_id),
                "acceptor_id": self.id,
                "value": value
            }
            
            logging.debug(f"Accepted proposal {proposal_id} for instance {instance} with value {value}, sending to learners")
            self.s.sendto(json.dumps(accepted_msg).encode(), self.config["learners"])
        else:
            logging.debug(f"Rejecting ACCEPT for instance {instance} (promised to higher proposal {self.promised_id[instance]})")

