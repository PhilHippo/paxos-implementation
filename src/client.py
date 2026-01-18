"""
Paxos Client implementation.

The client reads values from stdin and submits them to proposers.
Optionally measures end-to-end latency by listening for learned values.
"""

import logging
import pickle
import sys
import time

from utils import mcast_sender, mcast_receiver


class Client:
    def __init__(self, config, node_id):
        self.config = config
        self.id = node_id
        self.msg_num = 0
        
        # Network
        self.s = mcast_sender()
        self.r = mcast_receiver(config["learners"])
        
        # Latency measurement
        self.measuring = True
        self.output_file = f"logs/latency_client{self.id}"

    def run(self):
        """Read values from stdin and submit to proposers."""
        logging.debug(f"Client {self.id} started")
        
        for line in sys.stdin:
            value = line.strip()
            msg = pickle.dumps(["client", value, self.msg_num, self.id])
            
            if self.measuring:
                start_time = time.perf_counter()
            
            self.s.sendto(msg, self.config["proposers"])
            logging.debug(f"Sent value: {value}, msg_num={self.msg_num}")
            self.msg_num += 1
            
            if self.measuring:
                # Wait for the value to be learned
                response, addr = self.r.recvfrom(2**16)
                
                end_time = time.perf_counter()
                latency_us = (end_time - start_time) * 1_000_000
                
                with open(self.output_file, "a") as f:
                    f.write(f"{latency_us:.6f}\n")
                
                print(pickle.loads(response))
                sys.stdout.flush()
        
        logging.debug("Client finished")
