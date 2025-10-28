import logging
import json
import time
from utils import mcast_receiver, mcast_sender, is_greater_than


class Proposer:
    def __init__(self, config, id):
        self.config = config
        self.id = id
        self.r = mcast_receiver(config["proposers"])
        self.s = mcast_sender()
        
        # Synod state
        self.c_rnd = None
        self.c_val = None
        self.promises = {}  # {acceptor_id: (v_rnd, v_val)}
        self.quorum_size = 2  # Majority of 3 acceptors
        
        self.round_number = 0

    def run(self):
        logging.info(f"-> proposer {self.id}")
        
        # Get value from client
        msg, _ = self.r.recvfrom(2**16)
        try:
            value = str(json.loads(msg.decode()))
        except:
            value = msg.decode().strip()
        
        logging.debug(f"Proposer {self.id}: proposing value {value}")
        self.propose(value)

    def propose(self, value):
        """Phase 1A: Send PREPARE"""
        self.round_number += 1
        self.c_rnd = (self.round_number, self.id)
        self.c_val = value
        self.promises = {}
        
        prepare_msg = {"type": "prepare", "c_rnd": list(self.c_rnd)}
        
        logging.debug(f"Phase 1A: PREPARE c-rnd={self.c_rnd}")
        self.s.sendto(json.dumps(prepare_msg).encode(), self.config["acceptors"])
        
        # Wait for promises
        self.wait_promises()

    def wait_promises(self):
        """Wait for Phase 1B promises from quorum"""
        while len(self.promises) < self.quorum_size:
            msg, _ = self.r.recvfrom(2**16)
            data = json.loads(msg.decode())
            
            if data.get("type") == "promise" and tuple(data["rnd"]) == self.c_rnd:
                acceptor_id = data["acceptor_id"]
                v_rnd = tuple(data["v_rnd"]) if data["v_rnd"] else None
                v_val = data["v_val"]
                
                self.promises[acceptor_id] = (v_rnd, v_val)
                logging.debug(f"Phase 1B: PROMISE from acceptor {acceptor_id}")
        
        logging.debug(f"Quorum reached: {len(self.promises)} promises")
        self.send_accept()

    def send_accept(self):
        """Phase 2A: Send ACCEPT"""
        # Find highest v_rnd with a value
        max_v_rnd = None
        for v_rnd, v_val in self.promises.values():
            if v_rnd and (not max_v_rnd or is_greater_than(v_rnd, max_v_rnd)):
                max_v_rnd = v_rnd
                self.c_val = v_val
        
        accept_msg = {"type": "accept", "c_rnd": list(self.c_rnd), "c_val": self.c_val}
        
        logging.debug(f"Phase 2A: ACCEPT c-rnd={self.c_rnd} c-val={self.c_val}")
        self.s.sendto(json.dumps(accept_msg).encode(), self.config["acceptors"])
        
        # Done
        time.sleep(1)


