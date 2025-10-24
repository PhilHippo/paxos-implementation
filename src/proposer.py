import logging
import json
import select
import time
from utils import mcast_receiver, mcast_sender, is_greater_than


class Proposer:
    def __init__(self, config, id):
        self.config = config
        self.id = id
        self.r = mcast_receiver(config["proposers"])
        self.s = mcast_sender()
        
        # Proposer state per instance
        self.instance_num = 0  # Current instance number
        self.proposal_count = {}  # {instance: count} Counter for proposal numbers per instance
        self.current_value = {}  # {instance: value} Value to propose per instance
        self.promises_received = {}  # {instance: {acceptor_id: (accepted_id, accepted_value)}}
        self.phase = {}  # {instance: 'prepare' or 'accept'}
        self.n_acceptors = 3  # Fixed number of acceptors
        self.quorum_size = (self.n_acceptors // 2) + 1  # Majority
        
        # Timeout settings
        self.timeout = 1.0  # seconds
        
        # Queue for pending client values
        self.pending_values = []

    def run(self):
        logging.info(f"-> proposer {self.id}")
        while True:
            # Check if we should start a new instance
            can_start_new = (self.instance_num == 0 or self.phase.get(self.instance_num) is None)
            
            if len(self.pending_values) > 0 and can_start_new:
                # Process next pending value with new instance
                value = self.pending_values.pop(0)
                self.instance_num += 1
                self.propose(self.instance_num, value)
            else:
                # Wait for incoming message
                msg, addr = self.r.recvfrom(2**16)
                
                try:
                    data = json.loads(msg.decode())
                    
                    # Check if this is a dictionary (Paxos message) or just a value (client message)
                    if isinstance(data, dict):
                        msg_type = data.get("type")
                        
                        # Handle promise and accepted messages
                        if msg_type == "promise":
                            self.handle_promise(data)
                        elif msg_type == "accepted":
                            self.handle_accepted(data)
                        else:
                            logging.debug(f"Unknown message type: {msg_type}")
                    else:
                        # This is a client value (just a number parsed as JSON)
                        value = str(data)
                        logging.debug(f"Received value from client: {value}")
                        self.pending_values.append(value)
                        
                except json.JSONDecodeError:
                    # This is a client value (not JSON formatted at all)
                    value = msg.decode().strip()
                    logging.debug(f"Received value from client: {value}")
                    self.pending_values.append(value)

    def propose(self, instance, value):
        """Start a new proposal for the given value in the given instance"""
        self.current_value[instance] = value
        if instance not in self.proposal_count:
            self.proposal_count[instance] = 0
        self.proposal_count[instance] += 1
        self.promises_received[instance] = {}
        self.phase[instance] = 'prepare'
        
        # Phase 1a: Send PREPARE message
        proposal_id = (self.proposal_count[instance], self.id)
        prepare_msg = {
            "type": "prepare",
            "instance": instance,
            "proposal_id": list(proposal_id)  # Convert tuple to list for JSON
        }
        
        logging.debug(f"Phase 1a: Sending PREPARE for instance {instance} with proposal_id {proposal_id}")
        self.s.sendto(json.dumps(prepare_msg).encode(), self.config["acceptors"])
        
        # Wait for promises with timeout
        self.wait_for_phase1b(instance)

    def wait_for_phase1b(self, instance):
        """Wait for promise messages from acceptors"""
        timeout_remaining = self.timeout
        start_wait = time.time()
        
        while timeout_remaining > 0 and len(self.promises_received[instance]) < self.quorum_size:
            ready, _, _ = select.select([self.r], [], [], timeout_remaining)
            
            if not ready:
                # Timeout occurred
                logging.debug(f"Timeout in Phase 1b for instance {instance}, only {len(self.promises_received[instance])} promises received")
                self.handle_timeout(instance)
                return
            
            msg, addr = self.r.recvfrom(2**16)
            
            try:
                data = json.loads(msg.decode())
                
                if isinstance(data, dict):
                    msg_type = data.get("type")
                    
                    if msg_type == "promise":
                        self.handle_promise(data)
                    elif msg_type == "accepted":
                        # Ignore accepted messages during phase 1b
                        pass
                    else:
                        # Unknown message type
                        pass
                else:
                    # Got a client value (parsed as JSON number), queue it
                    value = str(data)
                    logging.debug(f"Received client value during phase 1b, queuing: {value}")
                    self.pending_values.append(value)
                    
            except json.JSONDecodeError:
                # Got a client value during waiting, queue it
                value = msg.decode().strip()
                logging.debug(f"Received client value during phase 1b, queuing: {value}")
                self.pending_values.append(value)
            
            timeout_remaining = self.timeout - (time.time() - start_wait)

    def handle_promise(self, data):
        """Handle PROMISE message from acceptor"""
        instance = data["instance"]
        
        if instance not in self.phase or self.phase[instance] != 'prepare':
            return
        
        proposal_id = tuple(data["proposal_id"])
        acceptor_id = data["acceptor_id"]
        accepted_id = tuple(data["accepted_id"]) if data["accepted_id"] else None
        accepted_value = data["accepted_value"]
        
        logging.debug(f"Received PROMISE from acceptor {acceptor_id} for instance {instance} proposal {proposal_id}")
        
        # Check if this promise is for our current proposal
        current_proposal = (self.proposal_count[instance], self.id)
        if proposal_id != current_proposal:
            logging.debug(f"Promise for different proposal, ignoring")
            return
        
        # Store the promise
        self.promises_received[instance][acceptor_id] = (accepted_id, accepted_value)
        
        # Check if we have a quorum
        if len(self.promises_received[instance]) >= self.quorum_size:
            logging.debug(f"Quorum reached with {len(self.promises_received[instance])} promises for instance {instance}")
            self.start_phase2(instance)

    def start_phase2(self, instance):
        """Phase 2a: Send ACCEPT message"""
        self.phase[instance] = 'accept'
        
        # Determine value to propose
        # If any acceptor has accepted a value, use the one with highest proposal ID
        max_accepted_id = None
        value_to_propose = self.current_value[instance]
        
        for acceptor_id, (accepted_id, accepted_value) in self.promises_received[instance].items():
            if accepted_id is not None:
                if max_accepted_id is None or is_greater_than(accepted_id, max_accepted_id):
                    max_accepted_id = accepted_id
                    value_to_propose = accepted_value
        
        proposal_id = (self.proposal_count[instance], self.id)
        accept_msg = {
            "type": "accept",
            "instance": instance,
            "proposal_id": list(proposal_id),  # Convert tuple to list for JSON
            "value": value_to_propose
        }
        
        logging.debug(f"Phase 2a: Sending ACCEPT for instance {instance} with proposal_id {proposal_id} and value {value_to_propose}")
        self.s.sendto(json.dumps(accept_msg).encode(), self.config["acceptors"])
        
        # Reset phase (proposer's job is done after sending accept)
        self.phase[instance] = None

    def handle_accepted(self, data):
        """Handle ACCEPTED message from acceptor (optional, for logging)"""
        instance = data["instance"]
        proposal_id = tuple(data["proposal_id"])
        acceptor_id = data["acceptor_id"]
        value = data["value"]
        
        logging.debug(f"Acceptor {acceptor_id} accepted proposal {proposal_id} for instance {instance} with value {value}")

    def handle_timeout(self, instance):
        """Handle timeout by restarting with a higher proposal number"""
        logging.debug(f"Timeout occurred for instance {instance}, restarting proposal")
        # Reset phase and restart the proposal with incremented count
        self.phase[instance] = None
        if instance in self.current_value:
            self.propose(instance, self.current_value[instance])


