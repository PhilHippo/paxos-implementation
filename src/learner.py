import logging
from utils import mcast_receiver, mcast_sender
import math
import pickle
from collections import deque

class Proposer:
    def __init__(self, config, id, batch_size=1):
        self.config = config
        self.id = id
        self.batch_size = batch_size
        self.c_rnd = 0
        self.quorum_1B = []
        self.quorum_2B = []
        self.r = mcast_receiver(config["proposers"])
        self.s = mcast_sender()
        self.value = None
        self.queue = deque()
        
        # Global Sequence Number, needed for batching total order
        self.consensus_instance = 0

        self.majority_acceptors = math.floor(self.config["n"]/2) + 1
        
        # Optimization to anticipate phase 1A quorum
        self.has_proactive_quorum = False
        self.proactive_consensus_instance_ = None

    def send_1A(self, msg_num=None, client_id=None):
        self.c_rnd += 1
        self.quorum_1B = []
        self.quorum_2B = []
        self.has_proactive_quorum = False
        self.proactive_consensus_instance_ = None

        # For batching, we don't send msg_num/client_id in 1A (they're in the batch value)
        msg_1A = pickle.dumps(["1A", self.c_rnd, self.id])
        self.s.sendto(msg_1A, self.config["acceptors"])
        logging.debug(f"Sending {pickle.loads(msg_1A)} to acceptors")

    def _create_batch(self):
        """Create a batch of up to batch_size values from the queue"""
        batch = []
        for _ in range(min(self.batch_size, len(self.queue))):
            batch.append(self.queue.popleft())
        return batch

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

                    # Always add to queue
                    self.queue.append((msg_num, client_id, value))

                    # If no value is being proposed, start a new proposal with a batch
                    if self.value is None:
                        # Create a batch from the queue
                        batch = self._create_batch()
                        self.value = batch
                        
                        # Optimization: if we already have a proactive quorum, skip 1A and go directly to 2A
                        if self.has_proactive_quorum and self.proactive_consensus_instance_ is not None:
                            # Use the instance_seq from the proactive prepare
                            self.consensus_instance = self.proactive_consensus_instance_ 
                            c_val = self.value
                            msg_2A = pickle.dumps(["2A", self.c_rnd, c_val, self.id, self.consensus_instance])
                            self.s.sendto(msg_2A, self.config["acceptors"])
                            logging.debug(f"Sending {pickle.loads(msg_2A)} to acceptors (proactive optimization)")
                            # Reset proactive state
                            self.has_proactive_quorum = False
                            self.proactive_consensus_instance_ = None
                        else:
                            self.send_1A()
                        
                case "1B":
                    rnd, max_inst, id_a = msg[1:]
                    
                    if rnd == self.c_rnd:
                        # Collect max_inst from each acceptor
                        self.quorum_1B.append(max_inst)
                        logging.debug(f"SIZE quorum_1B  {len(self.quorum_1B)}")
                        
                        if len(self.quorum_1B) == self.majority_acceptors:
                            # 1. Discovery: Find the highest instance ID used by the cluster
                            max_inst_global = max(self.quorum_1B)
                            
                            # 2. Update local sequence to be next available slot
                            next_instance = max(self.consensus_instance, max_inst_global + 1)
                            
                            # 3. Check if we have a value to propose
                            if self.value is not None:
                                # We have a value (batch), proceed with 2A
                                self.consensus_instance = next_instance
                                logging.debug(f"Proposing batch in instance: {self.consensus_instance}")
                                c_val = self.value
                                msg_2A = pickle.dumps(["2A", self.c_rnd, c_val, self.id, self.consensus_instance])
                                self.s.sendto(msg_2A, self.config["acceptors"])
                                logging.debug(f"Sending {pickle.loads(msg_2A)} to acceptors")
                            else:
                                self.has_proactive_quorum = True
                                self.proactive_consensus_instance_ = next_instance
                                logging.debug(f"Proactive quorum ready for instance {next_instance}, waiting for value")

                case "2B":
                    # Optimization: 2B messages go to both learners (for learning) and proposers (for flow control)
                    v_rnd, v_val, id = msg[1:]
                    if v_rnd == self.c_rnd and self.id == id:
                        self.quorum_2B.append((v_rnd, v_val))
                        logging.debug(f"SIZE quorum_2B {len(self.quorum_2B)}")
                        if len(self.quorum_2B) == self.majority_acceptors:
                            # Consensus reached - proposer can proceed to next value
                            logging.debug(f"Consensus reached for instance {self.consensus_instance}")
                            
                            # Increment for next request
                            self.consensus_instance += 1

                            # Clear current value
                            self.value = None
                            
                            # Optimization: Send proactive 1A for next instance even if queue is empty
                            if self.queue:
                                # Create next batch
                                batch = self._create_batch()
                                self.value = batch
                                self.send_1A()
                            else:
                                # No value in queue, but send proactive 1A to prepare for future values
                                self.send_1A()
                                logging.debug("Sent proactive 1A (no value in queue)")
                    
                case _:
                    logging.error(f"Unknown message: {msg}")
                    break
