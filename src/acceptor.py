import logging
from utils import mcast_receiver, mcast_sender
import pickle


class Acceptor:
    def __init__(self, config, id):
        self.config = config
        self.id = id
        self.rnd = 0
        # History: {instance_id: (v_rnd, v_val, msg_num, client_id)}
        self.accepted_history = {} 
        self.r = mcast_receiver(config["acceptors"])
        self.s = mcast_sender()

    def run(self):
        logging.info(f"-> acceptor {self.id}")
        while True:
            msg, addr = self.r.recvfrom(2**16)
            msg = pickle.loads(msg)
            logging.debug(f"Received {msg} from {addr}")

            match msg[0]:
                case "1A":
                    c_rnd, id_p, msg_num, client_id = msg[1:]
                    if self.rnd < c_rnd:
                        self.rnd = c_rnd
                        msg_1B = pickle.dumps(["1B", self.rnd, self.accepted_history, id_p, msg_num, client_id])
                        self.s.sendto(msg_1B, self.config["proposers"])
                        logging.debug(f"Sending {pickle.loads(msg_1B)} to proposers")

                case "2A":
                    c_rnd, c_val, id_p, instance_id, msg_num, client_id = msg[1:]
                    if c_rnd >= self.rnd:
                        self.accepted_history[instance_id] = (c_rnd, c_val, msg_num, client_id)
                        msg_2B = pickle.dumps(["2B", c_rnd, c_val, id_p, msg_num, client_id])
                        self.s.sendto(msg_2B, self.config["proposers"])
                        logging.debug(f"Sending {pickle.loads(msg_2B)} to proposers")

                case "Catchup":
                    req_instance_id = msg[1]
                    if req_instance_id in self.accepted_history:
                        v_rnd, val, m_num, c_id = self.accepted_history[req_instance_id]
                        resp = pickle.dumps(["CatchupResponse", req_instance_id, val, m_num, c_id])
                       
                        self.s.sendto(resp, self.config["learners"])
                        logging.debug(f"Sent CatchupResponse for inst {req_instance_id} to learners")

                case "QueryLastInstance":
                    max_inst = -1
                    if self.accepted_history:
                        max_inst = max(self.accepted_history.keys())
                    
                    resp = pickle.dumps(["LastInstanceResponse", max_inst])
                    # FIX: Send to Learners Multicast Group
                    self.s.sendto(resp, self.config["learners"])
                    logging.debug(f"Sent LastInstanceResponse ({max_inst}) to learners")

                case _:
                    logging.error(f"Unknown message: {msg}")
                    break