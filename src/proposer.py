import logging
from utils import mcast_receiver, mcast_sender
import math
import pickle
from collections import deque

class Proposer:
    def __init__(self, config, id):
        self.config = config
        self.id = id
        self.c_rnd = 0
        self.quorum_1B = []
        self.quorum_2B = []
        self.skip = False
        self.r = mcast_receiver(config["proposers"])
        self.s = mcast_sender()
        self.value = None
        self.queue = deque()

        # number of acceptors
        self.majority_acceptors = math.ceil(self.config["n"]/2)

    def send_1A(self, msg_num, client_id):
        self.c_rnd += 1
        self.skip = False
        # reset quorums
        self.quorum_1B = []
        self.quorum_2B = []

        msg_1A = pickle.dumps(["1A", self.c_rnd, self.id, msg_num, client_id])
        self.s.sendto(msg_1A, self.config["acceptors"])
        logging.debug(f"Sending {pickle.loads(msg_1A)} to acceptors")

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
                    value, msg_num, client_id = msg[1:]

                    logging.debug(f"Queue: {self.queue}")

                    if not self.queue:
                        self.value = value
                        self.queue.append((msg_num, client_id, value))
                        self.send_1A(msg_num, client_id)
                    else:
                        self.queue.append((msg_num, client_id, value))
                        
                case "1B":
                    rnd, v_rnd, v_val, accepted, id, msg_num, client_id = msg[1:]
                    if rnd == self.c_rnd and self.id == id:
                        if((msg_num, client_id) not in accepted and not self.skip):
                            self.quorum_1B.append((v_rnd, v_val))
                            logging.debug(f"SIZE quorum_1B  {len(self.quorum_1B)}")
                            if len(self.quorum_1B) == self.majority_acceptors:
                                k, V = max(self.quorum_1B, key=lambda x: x[0])
                                if k == 0:
                                    c_val = self.value
                                    msg_2A = pickle.dumps(["2A", self.c_rnd, c_val, self.id, msg_num, client_id])
                                    self.s.sendto(msg_2A, self.config["acceptors"])
                                    logging.debug(f"Sending {pickle.loads(msg_2A)} to acceptors")
                                # else:
                                #     c_val = V
                            
                                # msg_2A = pickle.dumps(["2A", self.c_rnd, c_val])
                                # self.s.sendto(msg_2A, self.config["acceptors"])
                                # logging.debug(f"Sending {pickle.loads(msg_2A)} to acceptors")
                        elif(not self.skip):
                            self.skip = True
                            logging.debug(f"Skipping value {self.value}. Already proposed!")

                case "2B":
                    v_rnd, v_val, id, msg_num, client_id = msg[1:]
                    if v_rnd == self.c_rnd and self.id == id:
                        self.quorum_2B.append((v_rnd, v_val))
                        logging.debug(f"SIZE quorum_2B {len(self.quorum_2B)}")
                        if len(self.quorum_2B) == self.majority_acceptors:
                            msg_3 = pickle.dumps(["Decision", v_val, msg_num, client_id])
                            self.s.sendto(msg_3, self.config["learners"])
                            logging.debug(f"Sending {pickle.loads(msg_3)} to learners")
                            
                            logging.debug(f"popping queue: {self.queue[0]}")
                            self.queue.popleft()
                            if self.queue:
                                msg_num, client_id, value = self.queue[0]
                                self.value = value
                                self.send_1A(msg_num, client_id)
                    
                case _:
                    logging.error(f"Unknown message: {msg}")
                    break
    