"""
Multi-Paxos entry point.

Starts a Paxos node with the specified role (client, proposer, acceptor, learner).
"""

import argparse
import logging

from client import Client
from proposer import Proposer
from acceptor import Acceptor
from learner import Learner
from utils import load_config


def main():
    parser = argparse.ArgumentParser(description="Multi-Paxos Consensus")
    parser.add_argument("-r", "--role", required=True,
                        choices=["client", "proposer", "acceptor", "learner"],
                        help="Role of the process")
    parser.add_argument("-p", "--pid", required=True, type=int,
                        help="Process ID")
    parser.add_argument("-d", "--debug", action="store_true",
                        help="Enable debug output")
    parser.add_argument("-b", "--batch-size", type=int, default=1,
                        help="Batch size for proposers (default: 1)")
    args = parser.parse_args()

    config = load_config()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format=f"[{args.role[0].upper()}{args.pid}:%(levelname)s] %(message)s",
    )

    if args.role == "client":
        node = Client(config, args.pid)
    elif args.role == "proposer":
        node = Proposer(config, args.pid, args.batch_size)
    elif args.role == "acceptor":
        node = Acceptor(config, args.pid)
    elif args.role == "learner":
        node = Learner(config, args.pid)

    node.run()


if __name__ == "__main__":
    main()
