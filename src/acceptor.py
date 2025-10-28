import logging
import json
from utils import mcast_receiver, mcast_sender, is_greater_than


class Acceptor:
    def __init__(self, config, id):
        self.config = config
        self.id = id
        self.r = mcast_receiver(config["acceptors"])
        self.s = mcast_sender()
        
        # Acceptor state per instance (following Paxos notation)
        self.rnd = {}  # {instance: round} highest-numbered round participated in, initially 0
        self.v_rnd = {}  # {instance: round} highest-numbered round cast a vote, initially 0
        self.v_val = {}  # {instance: value} value voted in round v-rnd, initially null
        
        # Lamport logical clock
        self.logical_clock = 0

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
        """
        Phase 1B: upon receiving (PHASE 1A, c-rnd) from proposer
        if c-rnd > rnd then
            rnd ← c-rnd
            send (PHASE 1B, rnd, v-rnd, v-val) to proposer
        """
        # LC2(b): Update logical clock based on received timestamp
        if "timestamp" in data:
            self.logical_clock = max(self.logical_clock, data["timestamp"])
        
        # LC1: Increment before timestamping this receive event
        self.logical_clock += 1
        
        instance = data["instance"]
        c_rnd = tuple(data["c_rnd"])
        
        logging.debug(f"Received PREPARE (Phase 1A) for instance {instance} with c-rnd {c_rnd}")
        
        # Get current rnd for this instance (default 0 means no round yet)
        current_rnd = self.rnd.get(instance, (0, 0))
        
        # Check if c-rnd > rnd
        if is_greater_than(c_rnd, current_rnd):
            # Update rnd ← c-rnd
            self.rnd[instance] = c_rnd
            
            # LC1: Increment before sending
            self.logical_clock += 1
            
            # Phase 1B: Send (PHASE 1B, rnd, v-rnd, v-val) to proposer
            promise_msg = {
                "type": "promise",
                "instance": instance,
                "rnd": list(c_rnd),
                "acceptor_id": self.id,
                "v_rnd": list(self.v_rnd[instance]) if instance in self.v_rnd else None,
                "v_val": self.v_val.get(instance),
                "timestamp": self.logical_clock  # LC2(a): piggyback logical clock
            }
            
            logging.debug(f"Sending PROMISE (Phase 1B) for instance {instance} rnd {c_rnd}, v-rnd {self.v_rnd.get(instance)}, v-val {self.v_val.get(instance)}")
            self.s.sendto(json.dumps(promise_msg).encode(), self.config["proposers"])
        else:
            logging.debug(f"Rejecting PREPARE for instance {instance} (c-rnd {c_rnd} not > rnd {current_rnd})")

    def handle_accept(self, data):
        """
        Phase 2B: upon receiving (PHASE 2A, c-rnd, c-val) from proposer
        if c-rnd >= rnd then
            v-rnd ← c-rnd
            v-val ← c-val
            send (PHASE 2B, v-rnd, v-val) to proposer
        """
        # LC2(b): Update logical clock based on received timestamp
        if "timestamp" in data:
            self.logical_clock = max(self.logical_clock, data["timestamp"])
        
        # LC1: Increment before timestamping this receive event
        self.logical_clock += 1
        
        instance = data["instance"]
        c_rnd = tuple(data["c_rnd"])
        c_val = data["c_val"]
        
        logging.debug(f"Received ACCEPT (Phase 2A) for instance {instance} with c-rnd {c_rnd} and c-val {c_val}")
        
        # Get current rnd for this instance (default 0 means no round yet)
        current_rnd = self.rnd.get(instance, (0, 0))
        
        # Check if c-rnd >= rnd (accept if not strictly less than)
        if not is_greater_than(current_rnd, c_rnd):
            # Accept the proposal: v-rnd ← c-rnd, v-val ← c-val
            self.rnd[instance] = c_rnd
            self.v_rnd[instance] = c_rnd
            self.v_val[instance] = c_val
            
            # LC1: Increment before sending
            self.logical_clock += 1
            
            # Phase 2B: Send (PHASE 2B, v-rnd, v-val) to learners
            # Note: Original algorithm sends to proposer, but Multi-Paxos sends to learners
            accepted_msg = {
                "type": "accepted",
                "instance": instance,
                "v_rnd": list(c_rnd),
                "acceptor_id": self.id,
                "v_val": c_val,
                "timestamp": self.logical_clock  # LC2(a): piggyback logical clock
            }
            
            logging.debug(f"Accepted c-rnd {c_rnd} for instance {instance} with c-val {c_val}, sending to learners")
            self.s.sendto(json.dumps(accepted_msg).encode(), self.config["learners"])
        else:
            logging.debug(f"Rejecting ACCEPT for instance {instance} (c-rnd {c_rnd} not >= rnd {current_rnd})")

