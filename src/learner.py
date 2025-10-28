import sys
import logging
import json
from utils import mcast_receiver


class Learner:
    def __init__(self, config, id):
        self.config = config
        self.id = id
        self.r = mcast_receiver(config["learners"])
        
        # Synod state
        self.quorum_size = 2  # Majority of 3 acceptors
        self.accepted = {}  # {v_rnd: {acceptor_id: v_val}}
        self.learned = False

    def run(self):
        logging.debug(f"-> learner {self.id}")
        while not self.learned:
            msg, _ = self.r.recvfrom(2**16)
            data = json.loads(msg.decode())
            
            if data.get("type") == "accepted":
                self.handle_accepted(data)

    def handle_accepted(self, data):
        """Learn when quorum accepts same (v_rnd, v_val)"""
        v_rnd = tuple(data["v_rnd"])
        acceptor_id = data["acceptor_id"]
        v_val = data["v_val"]
        
        if v_rnd not in self.accepted:
            self.accepted[v_rnd] = {}
        
        self.accepted[v_rnd][acceptor_id] = v_val
        
        # Check for quorum
        if len(self.accepted[v_rnd]) >= self.quorum_size:
            values = list(self.accepted[v_rnd].values())
            if len(set(values)) == 1:
                logging.debug(f"LEARNED: {values[0]}")
                print(values[0])
                sys.stdout.flush()
                self.learned = True

