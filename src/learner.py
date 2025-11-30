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
        # Buffering for FIFO ordering per client
        self.buffer = {}  # instance_id -> value
        self.next_seq = {}  # client_id -> next expected seq_num

    def run(self):
        logging.debug(f"-> learner {self.id}")
        while True:
            msg, addr = self.r.recvfrom(2**16)
            msg = pickle.loads(msg)
            
            # Decision format: ["Decision", (client_id, seq_num), value]
            instance_id, v_val = msg[1:]
            client_id, seq_num = instance_id
            
            # Avoid duplicate decisions
            if instance_id in self.decided:
                continue
            
            self.decided.add(instance_id)
            logging.debug(f"Decided instance {instance_id}: {v_val}")
            
            # Broadcast decision to proposers so they learn
            self.s.sendto(msg, self.config["proposers"])
            
            # Buffer the decision
            self.buffer[instance_id] = v_val
            
            # Initialize next expected sequence for this client
            if client_id not in self.next_seq:
                self.next_seq[client_id] = 0
            
            # Print all consecutive ready values in FIFO order
            while (client_id, self.next_seq[client_id]) in self.buffer:
                val = self.buffer[(client_id, self.next_seq[client_id])]
                print(val)
                sys.stdout.flush()
                del self.buffer[(client_id, self.next_seq[client_id])]
                self.next_seq[client_id] += 1
