import sys
import logging
from utils import mcast_receiver, mcast_sender
import pickle
import select
import time

class Learner:
    def __init__(self, config, id):
        self.config = config
        self.id = id
        self.r = mcast_receiver(config["learners"])
        self.s = mcast_sender()
        
        # Buffer for Application level deduplication
        self.client_buffer = {} 
        self.client_next_seq = {} 

        # Buffer for Consensus level ordering
        self.global_next_seq = 0
        self.instance_buffer = {}
        
        # Track 2B messages to detect quorum (optimization)
        # {instance_id: {(v_rnd, v_val): count}}
        self.quorum_2B = {}
        self.majority_acceptors = (config["n"] // 2) + 1
        
        # Catchup tracking
        self.catchup_pending = set()  # instances we're waiting for
        self.catchup_max_instance = -1  # highest instance we know about
        self.last_catchup_request = 0  # timestamp of last catchup request 

    def deliver(self, v_val):
        """
        Deliver a batch of values.
        v_val is a list of tuples: [(msg_num, client_id, value), ...]
        """
        # Track which clients are affected by this batch
        affected_clients = set()
        
        # First, add all values from the batch to the buffer
        for msg_num, client_id, value in v_val:
            if client_id not in self.client_next_seq:
                self.client_next_seq[client_id] = 0
            self.client_buffer[(client_id, msg_num)] = value
            affected_clients.add(client_id)
        
        # Then, try to deliver consecutive values for all clients
        # Check all clients (not just affected ones) because this batch might
        # complete a sequence that was waiting for values from a previous batch
        for client_id in self.client_next_seq:
            while (client_id, self.client_next_seq[client_id]) in self.client_buffer:
                val = self.client_buffer[(client_id, self.client_next_seq[client_id])]
                print(val)
                del self.client_buffer[(client_id, self.client_next_seq[client_id])]
                self.client_next_seq[client_id] += 1
                sys.stdout.flush()

    def request_catchup(self, start, end):
        """Helper to batch request missing instances with rate limiting"""
        logging.debug(f"Bootstrapping/Catching up from {start} to {end}")
        
        # Add to pending set
        for missing_id in range(start, end + 1):
            if missing_id not in self.instance_buffer:
                self.catchup_pending.add(missing_id)
        
        # Update max instance
        self.catchup_max_instance = max(self.catchup_max_instance, end)
        
        # Send requests in batches with minimal delays
        batch_size = 200
        requests_sent = 0
        for missing_id in range(start, end + 1):
            if missing_id not in self.instance_buffer:
                catchup_msg = pickle.dumps(["Catchup", missing_id])
                self.s.sendto(catchup_msg, self.config["acceptors"])
                requests_sent += 1
                
                # Add tiny delay every batch_size requests
                if requests_sent % batch_size == 0:
                    time.sleep(0.005)
        
        self.last_catchup_request = time.time()
    
    def retry_missing_catchup(self):
        """Retry catchup for instances still missing"""
        if not self.catchup_pending:
            return
        
        now = time.time()
        # Retry more frequently for large catchups
        if now - self.last_catchup_request < 0.1:
            return
        
        missing = []
        for inst_id in sorted(self.catchup_pending):
            if inst_id not in self.instance_buffer:
                missing.append(inst_id)
        
        if missing:
            logging.debug(f"Retrying catchup for {len(missing)} missing instances")
            # Send retry requests in larger batches
            batch_size = 200
            for i, inst_id in enumerate(missing):
                catchup_msg = pickle.dumps(["Catchup", inst_id])
                self.s.sendto(catchup_msg, self.config["acceptors"])
                
                if (i + 1) % batch_size == 0:
                    time.sleep(0.003)
            
            self.last_catchup_request = now

    def run(self):
        logging.debug(f"-> learner {self.id}")
        
        # 1. On startup: Ask acceptors what the latest instance is
        logging.debug("Querying acceptors for latest instance ID...")
        query_msg = pickle.dumps(["QueryLastInstance"])
        self.s.sendto(query_msg, self.config["acceptors"])
        last_msg_time = time.time()
        
        while True:
            # Use select with shorter timeout for more aggressive retry
            ready = select.select([self.r], [], [], 0.1)
            
            if not ready[0]:
                # Timeout - retry missing catchup
                self.retry_missing_catchup()
                
                # If we have not received anything for 0.5s, re-query latest instance to trigger catchup
                now = time.time()
                if now - last_msg_time >= 0.5:
                    self.s.sendto(query_msg, self.config["acceptors"])
                    last_msg_time = now
                continue
            
            msg, addr = self.r.recvfrom(2**16)
            msg = pickle.loads(msg)
            last_msg_time = time.time()

            match msg[0]:
                case "2B":
                    # Optimization: Receive 2B directly from acceptors
                    v_rnd, v_val, instance_id = msg[1:]
                    
                    if instance_id < self.global_next_seq:
                        continue
                    
                    # Track votes for this instance
                    if instance_id not in self.quorum_2B:
                        self.quorum_2B[instance_id] = {}
                    
                    # Convert v_val (list) to tuple to make it hashable
                    key = (v_rnd, tuple(v_val))
                    if key not in self.quorum_2B[instance_id]:
                        self.quorum_2B[instance_id][key] = 0
                    self.quorum_2B[instance_id][key] += 1
                    
                    # Check if we have a quorum (majority) for this value
                    if self.quorum_2B[instance_id][key] >= self.majority_acceptors:
                        if instance_id not in self.instance_buffer:
                            self.instance_buffer[instance_id] = v_val
                            
                            if instance_id == self.global_next_seq:
                                while self.global_next_seq in self.instance_buffer:
                                    val = self.instance_buffer[self.global_next_seq]
                                    self.deliver(val)
                                    del self.instance_buffer[self.global_next_seq]
                                    self.global_next_seq += 1
                            else:
                                # Gap detection
                                self.request_catchup(self.global_next_seq, instance_id - 1)
                        
                        # Clean up quorum tracking for this instance
                        del self.quorum_2B[instance_id]
                
                case "Decision":
                    v_val, instance_id = msg[1:]

                    if instance_id < self.global_next_seq:
                        continue

                    self.instance_buffer[instance_id] = v_val

                    if instance_id == self.global_next_seq:
                        while self.global_next_seq in self.instance_buffer:
                            val = self.instance_buffer[self.global_next_seq]
                            self.deliver(val)
                            del self.instance_buffer[self.global_next_seq]
                            self.global_next_seq += 1
                    else:
                        # Standard gap detection (during normal operation)
                        self.request_catchup(self.global_next_seq, instance_id - 1)

                case "LastInstanceResponse":
                    # 2. Receive info about the highest instance existing in the cluster
                    highest_instance_id = msg[1]
                    logging.debug(f"Received LastInstanceResponse: {highest_instance_id} (My seq: {self.global_next_seq})")
                    if highest_instance_id >= self.global_next_seq:
                        # Trigger catchup for everything we are missing since startup
                        self.request_catchup(self.global_next_seq, highest_instance_id)

                case "CatchupResponse":
                    instance_id, v_val = msg[1:]
                    
                    # Remove from pending
                    self.catchup_pending.discard(instance_id)
                    
                    if instance_id >= self.global_next_seq and instance_id not in self.instance_buffer:
                        self.instance_buffer[instance_id] = v_val
                        
                        while self.global_next_seq in self.instance_buffer:
                            val = self.instance_buffer[self.global_next_seq]
                            self.deliver(val)
                            del self.instance_buffer[self.global_next_seq]
                            self.global_next_seq += 1
