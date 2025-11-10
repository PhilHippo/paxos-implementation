import sys
import logging
from utils import mcast_receiver, mcast_sender
import pickle


class Learner:
    def __init__(self, config, id):
        self.config = config
        self.id = id
        self.r = mcast_receiver(config["learners"])

    def run(self):
        logging.debug(f"-> learner {self.id}")
        while True:
            msg, addr = self.r.recvfrom(2**16)
            msg = pickle.loads(msg)
            v_val = msg[1]
            logging.debug(f"Decided on {v_val}")
            print(v_val)
            sys.stdout.flush()
