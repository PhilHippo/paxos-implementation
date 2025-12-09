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
        self.r = mcast_receiver(config["proposers"])
        self.s = mcast_sender()
        self.value = None
        self.queue = deque()
        
        # Global Sequence Number for Total Order
        self.instance_seq = 0

        # number of acceptors
        self.majority_acceptors = math.ceil(self.config["n"]/2)
        
        # Proactive prepare optimization: track if we have quorum but no value
        self.has_proactive_quorum = False
        self.proactive_instance_seq = None

    def send_1A(self, msg_num=None, client_id=None):
        self.c_rnd += 1
        # reset quorums
        self.quorum_1B = []
        self.quorum_2B = []
        self.has_proactive_quorum = False
        self.proactive_instance_seq = None

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

            match msg[0]:
                case "client":
                    value, msg_num, client_id = msg[1:]
                    logging.debug(f"Queue: {self.queue}")

                    if not self.queue:
                        self.value = value
                        self.queue.append((msg_num, client_id, value))
                        
                        # Optimization: if we already have a proactive quorum, skip 1A and go directly to 2A
                        if self.has_proactive_quorum and self.proactive_instance_seq is not None:
                            # Use the instance_seq from the proactive prepare
                            self.instance_seq = self.proactive_instance_seq
                            c_val = self.value
                            msg_2A = pickle.dumps(["2A", self.c_rnd, c_val, self.id, self.instance_seq, msg_num, client_id])
                            self.s.sendto(msg_2A, self.config["acceptors"])
                            logging.debug(f"Sending {pickle.loads(msg_2A)} to acceptors (proactive optimization)")
                            # Reset proactive state
                            self.has_proactive_quorum = False
                            self.proactive_instance_seq = None
                        else:
                            self.send_1A(msg_num, client_id)
                    else:
                        self.queue.append((msg_num, client_id, value))
                        
                case "1B":
                    # Now receives only max_inst instead of full accepted_history
                    rnd, max_inst, id_a, msg_num, client_id = msg[1:]
                    
                    if rnd == self.c_rnd:
                        # Collect max_inst from each acceptor
                        self.quorum_1B.append(max_inst)
                        logging.debug(f"SIZE quorum_1B  {len(self.quorum_1B)}")
                        
                        if len(self.quorum_1B) == self.majority_acceptors:
                            # 1. Discovery: Find the highest instance ID used by the cluster
                            max_inst_global = max(self.quorum_1B)
                            
                            # 2. Update local sequence to be next available slot
                            next_instance = max(self.instance_seq, max_inst_global + 1)
                            
                            # 3. Check if we have a value to propose
                            if self.value is not None:
                                # We have a value, proceed with 2A
                                self.instance_seq = next_instance
                                logging.debug(f"Proposing in instance: {self.instance_seq}")
                                c_val = self.value
                                msg_2A = pickle.dumps(["2A", self.c_rnd, c_val, self.id, self.instance_seq, msg_num, client_id])
                                self.s.sendto(msg_2A, self.config["acceptors"])
                                logging.debug(f"Sending {pickle.loads(msg_2A)} to acceptors")
                            else:
                                # Optimization: We have quorum but no value yet - store for later
                                self.has_proactive_quorum = True
                                self.proactive_instance_seq = next_instance
                                logging.debug(f"Proactive quorum ready for instance {next_instance}, waiting for value")

                case "2B":
                    # Optimization: 2B messages go to both learners (for learning) and proposers (for flow control)
                    v_rnd, v_val, id, msg_num, client_id = msg[1:]
                    if v_rnd == self.c_rnd and self.id == id:
                        self.quorum_2B.append((v_rnd, v_val))
                        logging.debug(f"SIZE quorum_2B {len(self.quorum_2B)}")
                        if len(self.quorum_2B) == self.majority_acceptors:
                            # Consensus reached - proposer can proceed to next value
                            logging.debug(f"Consensus reached for instance {self.instance_seq}")
                            
                            # Increment for next request
                            self.instance_seq += 1

                            logging.debug(f"popping queue: {self.queue[0]}")
                            self.queue.popleft()
                            
                            # Optimization: Send proactive 1A for next instance even if queue is empty
                            if self.queue:
                                msg_num, client_id, value = self.queue[0]
                                self.value = value
                                self.send_1A(msg_num, client_id)
                            else:
                                # No value in queue, but send proactive 1A to prepare for future values
                                self.value = None
                                self.send_1A(None, None)
                                logging.debug("Sent proactive 1A (no value in queue)")
                    
                case _:
                    logging.error(f"Unknown message: {msg}")
                    break
