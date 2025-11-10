import logging
from utils import mcast_receiver, mcast_sender
import pickle


class Acceptor:
    def __init__(self, config, id):
        self.config = config
        self.id = id
        self.rnd = 0
        self.v_rnd = 0
        self.v_val = None
        self.r = mcast_receiver(config["acceptors"])
        self.s = mcast_sender()

    def run(self):
        logging.info(f"-> acceptor {self.id}")
        while True:
            msg, addr = self.r.recvfrom(2**16)
            msg = pickle.loads(msg)
            logging.debug(f"Received {msg} from {addr}")

            #msg could be 1A(c_rnd) or 2A(c_rnd, c_val)
            match msg[0]:
                case "1A":
                    c_rnd = int(msg[1])
                    if self.rnd < c_rnd:
                        self.rnd = c_rnd
                        msg_1B = pickle.dumps(["1B", self.rnd, self.v_rnd, self.v_val])
                        self.s.sendto(msg_1B, self.config["proposers"])
                        logging.debug(f"Sending {pickle.loads(msg_1B)} to proposers")
                case "2A":
                    c_rnd, c_val = msg[1:]
                    if c_rnd >= self.rnd:
                        self.v_rnd = c_rnd
                        self.v_val = c_val
                        msg_2B = pickle.dumps(["2B", self.v_rnd, self.v_val])
                        self.s.sendto(msg_2B, self.config["proposers"])
                        logging.debug(f"Sending {pickle.loads(msg_2B)} to proposers")
                case _:
                    logging.error(f"Unknown message: {msg}")
                    break



            
            #self.s.sendto(msg, self.config["learners"])
