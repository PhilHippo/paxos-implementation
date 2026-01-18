"""
Multicast communication utilities for Paxos.

Provides functions to create UDP multicast sockets for sending and receiving
messages across all Paxos roles.
"""

import json
import os
import socket
import struct


def load_config(path=""):
    """
    Load the Paxos configuration from a JSON file.
    
    Args:
        path: Path to config file. Defaults to logs/config.json relative to src/.
    
    Returns:
        Dictionary with multicast addresses for each role and acceptor count.
    """
    if path == "":
        script_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(script_dir, "..", "logs", "config.json")

    with open(path, "r") as f:
        config = {}
        for key, value in json.load(f).items():
            if key == "n":
                config[key] = int(value)
            else:
                config[key] = (value["ip"], int(value["port"]))
        return config


def mcast_receiver(hostport):
    """
    Create a multicast socket for receiving messages.
    
    Args:
        hostport: Tuple of (multicast_ip, port) to listen on.
    
    Returns:
        Socket configured to receive multicast messages.
    """
    recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    recv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    recv_sock.bind(hostport)

    mcast_group = struct.pack("4sl", socket.inet_aton(hostport[0]), socket.INADDR_ANY)
    recv_sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mcast_group)
    return recv_sock


def mcast_sender(ttl=1):
    """
    Create a UDP socket for sending multicast messages.
    
    Args:
        ttl: Time-to-live for multicast packets (default: 1, local network only).
    
    Returns:
        Socket configured for sending multicast messages.
    """
    send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    send_sock.setsockopt(
        socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, struct.pack("b", ttl)
    )
    return send_sock
