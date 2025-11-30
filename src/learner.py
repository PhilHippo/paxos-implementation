import sys
import logging
from utils import mcast_receiver, mcast_sender
import pickle


class Learner:
    def __init__(self, config, id):
        self.config = config
        self.id = id
        self.r = mcast_receiver(config["learners"])
        self.s = mcast_sender()
        # Track decisions to avoid duplicates
        self.decided = set()

    def run(self):
        logging.debug(f"-> learner {self.id}")
        while True:
            msg, addr = self.r.recvfrom(2**16)
            msg = pickle.loads(msg)
            
            # Decision format: ["Decision", (client_id, seq_num), value]
            instance_id, v_val = msg[1:]
            
            # Avoid duplicate decisions
            if instance_id in self.decided:
                continue
            
            self.decided.add(instance_id)
            logging.debug(f"Decided instance {instance_id}: {v_val}")
            
            # Broadcast decision to proposers so they learn
            self.s.sendto(msg, self.config["proposers"])
            
            # Print value (FIFO assumption ensures order)
            print(v_val)
            sys.stdout.flush()
