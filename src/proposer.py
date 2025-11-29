import logging
from utils import mcast_receiver, mcast_sender
import math
import pickle

class Proposer:
    def __init__(self, config, id):
        self.config = config
        self.id = id
        self.c_rnd = 0
        self.quorum_1B = []
        self.quorum_2B = []
        self.r = mcast_receiver(config["proposers"]) #socket to receive from clients and acceptors
        self.s = mcast_sender() #socket to send to acceptors and learners
        self.value = None

        # number of acceptors is >= n/2 + 1
        self.majority_acceptors = int(self.config["n"] / 2 + 1)

    def run(self):
        logging.info(f"-> proposer {self.id}")
        logging.info(f"{self.config['n']}")
        while True:
            msg, addr = self.r.recvfrom(2**16)
            msg = pickle.loads(msg)
            logging.debug(f"Received {msg} from {addr}")

            # switch case for msg
            match msg[0]:
                case "client":
                    self.c_rnd += 1
                    # reset quorums
                    self.quorum_1B = []
                    self.quorum_2B = []

                    msg_1A = pickle.dumps(["1A", self.c_rnd])
                    self.value = msg[1]
                    self.s.sendto(msg_1A, self.config["acceptors"])
                    logging.debug(f"Sending {pickle.loads(msg_1A)} to acceptors")
                case "1B":
                    rnd, v_rnd, v_val = msg[1:]
                    if rnd == self.c_rnd:
                        self.quorum_1B.append((v_rnd, v_val))
                        if len(self.quorum_1B) == self.majority_acceptors:
                            k, V = max(self.quorum_1B, key=lambda x: x[0])
                            if k == 0:
                                c_val = self.value
                            else:
                                c_val = V
                        
                            msg_2A = pickle.dumps(["2A", self.c_rnd, c_val])
                            self.s.sendto(msg_2A, self.config["acceptors"])
                            logging.debug(f"Sending {pickle.loads(msg_2A)} to acceptors")

                case "2B":
                    v_rnd, v_val = msg[1:]
                    if v_rnd == self.c_rnd:
                        self.quorum_2B.append((v_rnd, v_val))
                        if len(self.quorum_2B) == self.majority_acceptors:
                            msg_3 = pickle.dumps(["Decision", v_val])
                            self.s.sendto(msg_3, self.config["learners"])
                            logging.debug(f"Sending {pickle.loads(msg_3)} to learners")
                case _:
                    logging.error(f"Unknown message: {msg}")
                    break

            
            
    