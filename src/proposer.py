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
        
        # Proposer state per instance (following Paxos notation)
        self.instance_num = 0  # Current instance number
        self.c_rnd = {}  # {instance: round_number} highest-numbered round started
        self.c_val = {}  # {instance: value} value picked for round c-rnd
        self.promises_received = {}  # {instance: {acceptor_id: (v_rnd, v_val)}}
        self.phase = {}  # {instance: 'prepare' or 'accept'}
        self.n_acceptors = 3  # Fixed number of acceptors
        self.quorum_size = (self.n_acceptors // 2) + 1  # Majority (Qa)
        
        # Lamport logical clock for round numbers
        self.logical_clock = 0
        
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
                        
                        # Handle promise messages
                        if msg_type == "promise":
                            # Get the expected c-rnd for this instance
                            instance = data.get("instance")
                            if instance in self.c_rnd:
                                self.handle_promise(data, self.c_rnd[instance])
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
        """
        Phase 1A: To propose value v:
        - increase c-rnd to an arbitrary unique value
        - send (PHASE 1A, c-rnd) to acceptors
        """
        # Increment logical clock to get unique round number
        self.logical_clock += 1
        
        # Set c-rnd and c-val for this instance
        c_rnd = (self.logical_clock, self.id)
        self.c_rnd[instance] = c_rnd
        self.c_val[instance] = value
        
        self.promises_received[instance] = {}
        self.phase[instance] = 'prepare'
        
        # Phase 1A: Send PREPARE (c-rnd) to acceptors
        prepare_msg = {
            "type": "prepare",
            "instance": instance,
            "c_rnd": list(c_rnd),  # Convert tuple to list for JSON
            "timestamp": self.logical_clock  # LC2(a): piggyback logical clock
        }
        
        logging.debug(f"Phase 1A: Sending PREPARE for instance {instance} with c-rnd {c_rnd}")
        self.s.sendto(json.dumps(prepare_msg).encode(), self.config["acceptors"])
        
        # Wait for promises with timeout
        self.wait_for_phase1b(instance, c_rnd)

    def wait_for_phase1b(self, instance, c_rnd):
        """Wait for Phase 1B promise messages from acceptors"""
        timeout_remaining = self.timeout
        start_wait = time.time()
        
        while timeout_remaining > 0 and len(self.promises_received[instance]) < self.quorum_size:
            ready, _, _ = select.select([self.r], [], [], timeout_remaining)
            
            if not ready:
                # Timeout occurred
                logging.debug(f"Timeout in Phase 1B for instance {instance}, only {len(self.promises_received[instance])} promises received")
                self.handle_timeout(instance)
                return
            
            msg, addr = self.r.recvfrom(2**16)
            
            try:
                data = json.loads(msg.decode())
                
                if isinstance(data, dict):
                    msg_type = data.get("type")
                    
                    if msg_type == "promise":
                        self.handle_promise(data, c_rnd)
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

    def handle_promise(self, data, expected_c_rnd):
        """
        Phase 1B: upon receiving (PHASE 1B, rnd, v-rnd, v-val) from Qa such that c-rnd = rnd
        - k ← largest v-rnd value received
        - V ← set of (v-rnd, v-val) received with v-rnd = k
        - if k = 0 then let c-val be v
        - else c-val ← the only v-val in V
        - send (PHASE 2A, c-rnd, c-val) to acceptors
        """
        instance = data["instance"]
        
        if instance not in self.phase or self.phase[instance] != 'prepare':
            return
        
        # LC2(b): Update logical clock based on received timestamp
        if "timestamp" in data:
            self.logical_clock = max(self.logical_clock, data["timestamp"])
        
        # LC1: Increment before timestamping this receive event
        self.logical_clock += 1
        
        rnd = tuple(data["rnd"])
        acceptor_id = data["acceptor_id"]
        v_rnd = tuple(data["v_rnd"]) if data["v_rnd"] else None
        v_val = data["v_val"]
        
        logging.debug(f"Received PROMISE (Phase 1B) from acceptor {acceptor_id} for instance {instance} rnd {rnd}, v-rnd {v_rnd}, v-val {v_val}")
        
        # Check if this promise is for our current round (c-rnd = rnd)
        if rnd != expected_c_rnd:
            logging.debug(f"Promise for different round, ignoring")
            return
        
        # Store the promise with (v-rnd, v-val)
        self.promises_received[instance][acceptor_id] = (v_rnd, v_val)
        
        # Check if we have a quorum (Qa)
        if len(self.promises_received[instance]) >= self.quorum_size:
            logging.debug(f"Quorum Qa reached with {len(self.promises_received[instance])} promises for instance {instance}")
            self.start_phase2(instance, expected_c_rnd)

    def start_phase2(self, instance, c_rnd):
        """
        Phase 2A: Send ACCEPT message
        - k ← largest v-rnd value received
        - V ← set of (v-rnd, v-val) received with v-rnd = k
        - if k = 0 then let c-val be v (original value)
        - else c-val ← the only v-val in V
        - send (PHASE 2A, c-rnd, c-val) to acceptors
        """
        self.phase[instance] = 'accept'
        
        # Find k = largest v-rnd value received
        k = None
        for acceptor_id, (v_rnd, v_val) in self.promises_received[instance].items():
            if v_rnd is not None:
                if k is None or is_greater_than(v_rnd, k):
                    k = v_rnd
        
        # Build set V of (v-rnd, v-val) with v-rnd = k
        if k is None:
            # k = 0 (no acceptor has voted), use original value
            c_val = self.c_val[instance]
        else:
            # Get the only v-val in V where v-rnd = k
            V = {}
            for acceptor_id, (v_rnd, v_val) in self.promises_received[instance].items():
                if v_rnd == k:
                    V[acceptor_id] = v_val
            
            # c-val ← the only v-val in V
            values = list(V.values())
            c_val = values[0]  # Should all be the same
            self.c_val[instance] = c_val
        
        # LC1: Increment logical clock before sending
        self.logical_clock += 1
        
        # Phase 2A: Send (PHASE 2A, c-rnd, c-val) to acceptors
        accept_msg = {
            "type": "accept",
            "instance": instance,
            "c_rnd": list(c_rnd),  # Convert tuple to list for JSON
            "c_val": c_val,
            "timestamp": self.logical_clock  # LC2(a): piggyback logical clock
        }
        
        logging.debug(f"Phase 2A: Sending ACCEPT for instance {instance} with c-rnd {c_rnd} and c-val {c_val}")
        self.s.sendto(json.dumps(accept_msg).encode(), self.config["acceptors"])
        
        # Proposer's job is done - mark instance as complete
        self.phase[instance] = None

    def handle_timeout(self, instance):
        """Handle timeout by restarting with a higher round number"""
        logging.debug(f"Timeout occurred for instance {instance}, restarting proposal")
        # Reset phase and restart the proposal with incremented round
        self.phase[instance] = None
        if instance in self.c_val:
            self.propose(instance, self.c_val[instance])


