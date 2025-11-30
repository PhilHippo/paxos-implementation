import sys
import logging
from utils import mcast_receiver, mcast_sender
import pickle

class Learner:
    def __init__(self, config, id):
        self.config = config
        self.id = id
        self.r = mcast_receiver(config["learners"])
        self.buffer = {} # buffer[(client_id, msg_num)] = v_val
        self.next_seq = {} # next_seq[client_id] = int

    def run(self):
        logging.debug(f"-> learner {self.id}")
        while True:
            msg, addr = self.r.recvfrom(2**16)
            msg = pickle.loads(msg)

            v_val = msg[1]
            msg_num = msg[2]
            client_id = msg[3]

            if client_id not in self.next_seq:
                self.next_seq[client_id] = 0
            
            self.buffer[(client_id, msg_num)] = v_val

            while (client_id, self.next_seq[client_id]) in self.buffer:
                
                v_val = self.buffer[(client_id, self.next_seq[client_id])]
                print(v_val)
                logging.debug(f"Decided on {v_val}")

                del self.buffer[(client_id, self.next_seq[client_id])]
                self.next_seq[client_id] += 1
                sys.stdout.flush()
