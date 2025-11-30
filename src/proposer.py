import logging
from utils import mcast_receiver, mcast_sender
import pickle

class Proposer:
    def __init__(self, config, id):
        self.config = config
        self.id = id
        self.c_rnd = 0
        # Per-instance state: instance_id -> {value, quorum_1B, quorum_2B, round}
        self.instances = {}
        # Track decided instances: instance_id -> decided_value
        self.decided = {}
        self.r = mcast_receiver(config["proposers"]) #socket to receive from clients and acceptors
        self.s = mcast_sender() #socket to send to acceptors and learners
        # number of acceptors is >= n/2 + 1
        self.majority_acceptors = int(self.config["n"] // 2 + 1)

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
                    client_id, seq_num, value = msg[1:]
                    instance_id = (client_id, seq_num)
                    
                    # if the client instance is already decided, ignore
                    if instance_id in self.decided:
                        logging.debug(f"Instance {instance_id} already decided, so ignoring")
                        continue
                    
                    # if the client instance is already in progress, ignore
                    if instance_id in self.instances:
                        logging.debug(f"Instance {instance_id} already in progress, so ignoring")
                        continue
                    
                    # Start new instance
                    self.c_rnd += 1
                    self.instances[instance_id] = {
                        'value': value,
                        'quorum_1B': [],
                        'quorum_2B': [],
                        'round': self.c_rnd
                    }
                    
                    msg_1A = pickle.dumps(["1A", self.c_rnd, instance_id])
                    self.s.sendto(msg_1A, self.config["acceptors"])
                    logging.debug(f"Instance {instance_id}: Sending 1A round={self.c_rnd}")
                    
                case "1B":
                    rnd, instance_id, v_rnd, v_val = msg[1:]
                    
                    if instance_id not in self.instances: # check if instance is known
                        continue
                    
                    inst = self.instances[instance_id]
                    if rnd == inst['round']: # check if round of acceptor matches proposer c_rnd
                        inst['quorum_1B'].append((v_rnd, v_val))
                        
                        if len(inst['quorum_1B']) == self.majority_acceptors:
                            k, V = max(inst['quorum_1B'], key=lambda x: x[0])
                            c_val = inst['value'] if k == 0 else V
                            
                            msg_2A = pickle.dumps(["2A", inst['round'], instance_id, c_val])
                            self.s.sendto(msg_2A, self.config["acceptors"])
                            logging.debug(f"Instance {instance_id}: Sending 2A round={inst['round']} value={c_val}")

                case "2B":
                    v_rnd, instance_id, v_val = msg[1:]
                    
                    if instance_id in self.decided or instance_id not in self.instances:
                        continue
                    
                    inst = self.instances[instance_id]
                    if v_rnd == inst['round']:
                        inst['quorum_2B'].append((v_rnd, v_val))
                        
                        if len(inst['quorum_2B']) == self.majority_acceptors: # majority reached, not >= becauase we don't want duplicate decisions
                            msg_3 = pickle.dumps(["Decision", instance_id, v_val])
                            self.s.sendto(msg_3, self.config["learners"])
                            logging.debug(f"Instance {instance_id}: Decision value={v_val}")
                            self.decided[instance_id] = v_val
                            del self.instances[instance_id]
                
                case "Decision":
                    # Learn decisions from other proposers via learners
                    instance_id, v_val = msg[1:]
                    if instance_id not in self.decided:
                        self.decided[instance_id] = v_val
                        if instance_id in self.instances:
                            del self.instances[instance_id]
                        logging.debug(f"Learned decision for instance {instance_id}: {v_val}")
                            
                case _:
                    logging.error(f"Unknown message: {msg}")
                    break

            
            
    