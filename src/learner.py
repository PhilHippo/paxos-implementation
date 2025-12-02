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
        
        # Buffer for Application level deduplication
        self.client_buffer = {} 
        self.client_next_seq = {} 

        # Buffer for Consensus level ordering
        self.global_next_seq = 0
        self.instance_buffer = {} 

    def deliver(self, v_val, msg_num, client_id):
        if client_id not in self.client_next_seq:
            self.client_next_seq[client_id] = 0
            
        self.client_buffer[(client_id, msg_num)] = v_val

        while (client_id, self.client_next_seq[client_id]) in self.client_buffer:
            val = self.client_buffer[(client_id, self.client_next_seq[client_id])]
            print(val)
            del self.client_buffer[(client_id, self.client_next_seq[client_id])]
            self.client_next_seq[client_id] += 1
            sys.stdout.flush()

    def request_catchup(self, start, end):
        """Helper to batch request missing instances"""
        logging.debug(f"Bootstrapping/Catching up from {start} to {end}")
        for missing_id in range(start, end + 1):
            if missing_id not in self.instance_buffer:
                catchup_msg = pickle.dumps(["Catchup", missing_id])
                self.s.sendto(catchup_msg, self.config["acceptors"])

    def run(self):
        logging.debug(f"-> learner {self.id}")
        
        # 1. On startup: Ask acceptors what the latest instance is
        logging.debug("Querying acceptors for latest instance ID...")
        query_msg = pickle.dumps(["QueryLastInstance"])
        self.s.sendto(query_msg, self.config["acceptors"])

        while True:
            msg, addr = self.r.recvfrom(2**16)
            msg = pickle.loads(msg)

            match msg[0]:
                case "Decision":
                    v_val, instance_id, msg_num, client_id = msg[1:]

                    if instance_id < self.global_next_seq:
                        continue

                    self.instance_buffer[instance_id] = (v_val, msg_num, client_id)

                    if instance_id == self.global_next_seq:
                        while self.global_next_seq in self.instance_buffer:
                            val, mn, cid = self.instance_buffer[self.global_next_seq]
                            self.deliver(val, mn, cid)
                            del self.instance_buffer[self.global_next_seq]
                            self.global_next_seq += 1
                    else:
                        # Standard gap detection (during normal operation)
                        self.request_catchup(self.global_next_seq, instance_id - 1)

                case "LastInstanceResponse":
                    # 2. Receive info about the highest instance existing in the cluster
                    highest_instance_id = msg[1]
                    logging.debug(f"Received LastInstanceResponse: {highest_instance_id} (My seq: {self.global_next_seq})")
                    if highest_instance_id >= self.global_next_seq:
                        # Trigger catchup for everything we are missing since startup
                        self.request_catchup(self.global_next_seq, highest_instance_id)

                case "CatchupResponse":
                    instance_id, v_val, msg_num, client_id = msg[1:]
                    
                    if instance_id >= self.global_next_seq and instance_id not in self.instance_buffer:
                        self.instance_buffer[instance_id] = (v_val, msg_num, client_id)
                        
                        while self.global_next_seq in self.instance_buffer:
                            val, mn, cid = self.instance_buffer[self.global_next_seq]
                            self.deliver(val, mn, cid)
                            del self.instance_buffer[self.global_next_seq]
                            self.global_next_seq += 1