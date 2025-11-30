import logging
from utils import mcast_receiver, mcast_sender
import pickle


class Acceptor:
    def __init__(self, config, id):
        self.config = config
        self.id = id
        # Per-instance promised round: instance_id -> rnd
        self.promised = {} #instance_id is (client_id, msg_num) 
        # Per-instance accepted values: instance_id -> (v_rnd, v_val)
        self.accepted = {}
        self.r = mcast_receiver(config["acceptors"]) # socket to receive from proposers
        self.s = mcast_sender() # socket to send to proposers

    def run(self):
        logging.info(f"-> acceptor {self.id}")
        while True:
            msg, addr = self.r.recvfrom(2**16) 
            msg = pickle.loads(msg)
            logging.debug(f"Received {msg} from {addr}")

            # msg format: 1A(c_rnd, instance_id) at first and then 2A(c_rnd, instance_id, c_val)
            match msg[0]:
                case "1A":
                    c_rnd, instance_id = msg[1:]
                    c_rnd = int(c_rnd)
                    
                    # Get current promised round for this instance
                    current_rnd = self.promised.get(instance_id, 0)
                    
                    if current_rnd < c_rnd: # if the proposer round is higher than the acceptor round
                        self.promised[instance_id] = c_rnd
                        # Get accepted value for this instance (if any)
                        v_rnd, v_val = self.accepted.get(instance_id, (0, None))
                        msg_1B = pickle.dumps(["1B", c_rnd, instance_id, v_rnd, v_val])
                        self.s.sendto(msg_1B, self.config["proposers"])
                        logging.debug(f"Instance {instance_id}: Sending 1B rnd={c_rnd} v_rnd={v_rnd}")
                        
                case "2A":
                    c_rnd, instance_id, c_val = msg[1:]
                    current_rnd = self.promised.get(instance_id, 0)
                    
                    if c_rnd >= current_rnd:
                        self.promised[instance_id] = c_rnd
                        self.accepted[instance_id] = (c_rnd, c_val)
                        msg_2B = pickle.dumps(["2B", c_rnd, instance_id, c_val])
                        self.s.sendto(msg_2B, self.config["proposers"])
                        logging.debug(f"Instance {instance_id}: Sending 2B rnd={c_rnd} val={c_val}")
                        
                case _:
                    logging.error(f"Unknown message: {msg}")
                    break



            
            #self.s.sendto(msg, self.config["learners"])
