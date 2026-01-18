"""
Paxos Learner implementation.

The learner collects Phase 2B votes and delivers values when quorum is reached:
- Tracks votes per instance to detect majority agreement
- Maintains delivery buffer for total order guarantee
- Supports catch-up for missing instances (gap recovery, late join)

Delivery is in-order by consensus instance, with per-client deduplication
within each batch.
"""

import logging
import pickle
import select
import sys
import time

from utils import mcast_receiver, mcast_sender


class Learner:
    def __init__(self, config, node_id):
        self.config = config
        self.id = node_id
        
        # Quorum tracking: {instance_id: {(v_rnd, v_val_tuple): count}}
        self.quorum_2B = {}
        self.majority_acceptors = (config["n"] // 2) + 1
        
        # Instance ordering
        self.global_next_seq = 0  # Next instance to deliver
        self.instance_buffer = {}  # {instance_id: value}
        
        # Client-level deduplication
        self.client_buffer = {}  # {(client_id, msg_num): value}
        self.client_next_seq = {}  # {client_id: next_msg_num}
        
        # Catch-up state
        self.catchup_pending = set()  # Instances awaiting catch-up
        self.catchup_max_instance = -1
        self.last_catchup_request = 0
        
        # Network
        self.r = mcast_receiver(config["learners"])
        self.s = mcast_sender()

    def deliver(self, v_val):
        """
        Deliver a batch of values in client order.
        
        Args:
            v_val: List of tuples [(msg_num, client_id, value), ...]
        """
        # Add all values from batch to client buffer
        for msg_num, client_id, value in v_val:
            if client_id not in self.client_next_seq:
                self.client_next_seq[client_id] = 0
            self.client_buffer[(client_id, msg_num)] = value
        
        # Deliver consecutive values for all known clients
        for client_id in list(self.client_next_seq.keys()):
            while (client_id, self.client_next_seq[client_id]) in self.client_buffer:
                val = self.client_buffer.pop((client_id, self.client_next_seq[client_id]))
                print(val)
                sys.stdout.flush()
                self.client_next_seq[client_id] += 1

    def request_catchup(self, start, end):
        """Request catch-up for missing instances in range [start, end]."""
        logging.debug(f"Requesting catch-up: instances {start} to {end}")
        
        for inst_id in range(start, end + 1):
            if inst_id not in self.instance_buffer:
                self.catchup_pending.add(inst_id)
        
        self.catchup_max_instance = max(self.catchup_max_instance, end)
        
        # Send requests in batches with rate limiting
        batch_size = 200
        requests_sent = 0
        
        for inst_id in range(start, end + 1):
            if inst_id not in self.instance_buffer:
                msg = pickle.dumps(["Catchup", inst_id])
                self.s.sendto(msg, self.config["acceptors"])
                requests_sent += 1
                
                if requests_sent % batch_size == 0:
                    time.sleep(0.005)
        
        self.last_catchup_request = time.time()

    def retry_missing_catchup(self):
        """Retry catch-up for instances still missing."""
        if not self.catchup_pending:
            return
        
        now = time.time()
        if now - self.last_catchup_request < 0.1:
            return
        
        missing = [
            inst_id for inst_id in sorted(self.catchup_pending)
            if inst_id not in self.instance_buffer
        ]
        
        if not missing:
            return
        
        logging.debug(f"Retrying catch-up for {len(missing)} missing instances")
        
        batch_size = 200
        for i, inst_id in enumerate(missing):
            msg = pickle.dumps(["Catchup", inst_id])
            self.s.sendto(msg, self.config["acceptors"])
            
            if (i + 1) % batch_size == 0:
                time.sleep(0.003)
        
        self.last_catchup_request = now

    def _try_deliver_buffered(self):
        """Deliver consecutive instances from the buffer."""
        while self.global_next_seq in self.instance_buffer:
            val = self.instance_buffer.pop(self.global_next_seq)
            self.deliver(val)
            self.global_next_seq += 1

    def _handle_2B(self, msg):
        """Handle Phase 2B (accepted) message from acceptor."""
        v_rnd, v_val, instance_id = msg[1:]
        
        if instance_id < self.global_next_seq:
            return  # Already delivered
        
        # Track votes for this instance
        if instance_id not in self.quorum_2B:
            self.quorum_2B[instance_id] = {}
        
        # Make value hashable for vote counting
        key = (v_rnd, tuple(v_val))
        self.quorum_2B[instance_id][key] = self.quorum_2B[instance_id].get(key, 0) + 1
        
        # Check for quorum
        if self.quorum_2B[instance_id][key] >= self.majority_acceptors:
            if instance_id not in self.instance_buffer:
                self.instance_buffer[instance_id] = v_val
                
                if instance_id == self.global_next_seq:
                    self._try_deliver_buffered()
                else:
                    # Gap detected
                    self.request_catchup(self.global_next_seq, instance_id - 1)
            
            # Clean up quorum tracking
            del self.quorum_2B[instance_id]

    def _handle_decision(self, msg):
        """Handle decision message (alternative to quorum-based learning)."""
        v_val, instance_id = msg[1:]
        
        if instance_id < self.global_next_seq:
            return
        
        self.instance_buffer[instance_id] = v_val
        
        if instance_id == self.global_next_seq:
            self._try_deliver_buffered()
        else:
            self.request_catchup(self.global_next_seq, instance_id - 1)

    def _handle_last_instance_response(self, msg):
        """Handle response to QueryLastInstance."""
        highest_instance_id = msg[1]
        logging.debug(f"LastInstanceResponse: {highest_instance_id} (local: {self.global_next_seq})")
        
        if highest_instance_id >= self.global_next_seq:
            self.request_catchup(self.global_next_seq, highest_instance_id)

    def _handle_catchup_response(self, msg):
        """Handle catch-up response from acceptor."""
        instance_id, v_val = msg[1:]
        
        self.catchup_pending.discard(instance_id)
        
        if instance_id >= self.global_next_seq and instance_id not in self.instance_buffer:
            self.instance_buffer[instance_id] = v_val
            self._try_deliver_buffered()

    def run(self):
        """Main learner loop."""
        logging.debug(f"Learner {self.id} started")
        
        # Query acceptors for latest instance on startup
        query_msg = pickle.dumps(["QueryLastInstance"])
        self.s.sendto(query_msg, self.config["acceptors"])
        last_msg_time = time.time()

        
        while True:
            # Use select with timeout for catch-up retries
            ready = select.select([self.r], [], [], 0.1)
            
            if not ready[0]:
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
                    self._handle_2B(msg)
                case "Decision":
                    self._handle_decision(msg)
                case "LastInstanceResponse":
                    self._handle_last_instance_response(msg)
                case "CatchupResponse":
                    self._handle_catchup_response(msg)