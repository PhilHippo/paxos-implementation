import sys
import logging
import time
from utils import mcast_sender, mcast_receiver
import pickle #used to encode and decode lists


class Client:
    def __init__(self, config, id):
        self.config = config
        self.id = id
        self.s = mcast_sender() #initialize socket to send to proposers
        self.r = mcast_receiver(config["learners"]) #initialize socket to receive from learners
        
        self.output_file = f"logs/latency_client{self.id}"
        self.measuring = True
        self.msg_num = 0  # sequence number for FIFO ordering

    def run(self):
        logging.debug(f"-> client {self.id}")
        for value in sys.stdin:
            # Include client_id and seq_num for instance identification by proposers
            value = pickle.dumps(["client", self.id, self.msg_num, value.strip()])
            self.msg_num += 1

            if self.measuring:
                start_time = time.perf_counter() #start time measurement

            logging.debug(f"client: sending {value} to proposers")
            self.s.sendto(value, self.config["proposers"])
            
            if self.measuring:
                msg, addr = self.r.recvfrom(2**16) #wait for response from learners
                
                end_time = time.perf_counter() #end time measurement
                latency = (end_time - start_time) * 1_000_000 # us
                with open(self.output_file, "a") as f:
                    f.write(f"{latency:.6f}\n")
                
                print(pickle.loads(msg))
                sys.stdout.flush()
                
        logging.debug("client done.")
