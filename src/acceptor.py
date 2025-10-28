import logging
import json
from utils import mcast_receiver, mcast_sender, is_greater_than


class Acceptor:
    def __init__(self, config, id):
        self.config = config
        self.id = id
        self.r = mcast_receiver(config["acceptors"])
        self.s = mcast_sender()
        
        # Synod state
        self.rnd = (0, 0)
        self.v_rnd = (0, 0)
        self.v_val = None

    def run(self):
        logging.info(f"-> acceptor {self.id}")
        while True:
            msg, _ = self.r.recvfrom(2**16)
            data = json.loads(msg.decode())
            msg_type = data.get("type")
            
            if msg_type == "prepare":
                self.handle_prepare(data)
            elif msg_type == "accept":
                self.handle_accept(data)

    def handle_prepare(self, data):
        """Phase 1B: Respond to PREPARE if c_rnd > rnd"""
        c_rnd = tuple(data["c_rnd"])
        
        if is_greater_than(c_rnd, self.rnd):
            self.rnd = c_rnd
            
            promise_msg = {
                "type": "promise",
                "rnd": list(c_rnd),
                "acceptor_id": self.id,
                "v_rnd": list(self.v_rnd) if self.v_rnd != (0, 0) else None,
                "v_val": self.v_val
            }
            
            logging.debug(f"Phase 1B: PROMISE rnd={c_rnd}")
            self.s.sendto(json.dumps(promise_msg).encode(), self.config["proposers"])

    def handle_accept(self, data):
        """Phase 2B: Accept if c_rnd >= rnd"""
        c_rnd = tuple(data["c_rnd"])
        c_val = data["c_val"]
        
        if not is_greater_than(self.rnd, c_rnd):
            self.rnd = c_rnd
            self.v_rnd = c_rnd
            self.v_val = c_val
            
            accepted_msg = {
                "type": "accepted",
                "v_rnd": list(c_rnd),
                "acceptor_id": self.id,
                "v_val": c_val
            }
            
            logging.debug(f"Phase 2B: ACCEPTED v-rnd={c_rnd} v-val={c_val}")
            self.s.sendto(json.dumps(accepted_msg).encode(), self.config["learners"])

