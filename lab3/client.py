import argparse
import os
import random
import socket
import struct
import sys
from enum import Enum, auto

# --- Packet Definitions ---
# Header format: ! I I B H
# ! = Network byte order (Big-Endian)
# I = Connection ID (4 bytes, uint32)
# I = Sequence Number (4 bytes, uint32)
# B = Message Type (1 byte, uint8)
# H = Payload Length (2 bytes, uint16)
HEADER_FORMAT = "!IIBH"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

OUTPUT_DIR = "out"


class MsgType(Enum):
    REQUEST = 1
    DATA = 2
    ACK = 3
    ERROR = 4


class ClientState(Enum):
    INIT = auto()
    SEND_REQUEST = auto()
    WAIT_FOR_DATA = auto()
    DONE = auto()
    ERROR = auto()


class RDTClient:
    def __init__(self, server_ip, server_port, filename, segment_size):
        self.server_addr = (server_ip, server_port)
        self.filename: str = filename
        self.segment_size = segment_size

        # Connection ID setup
        self.conn_id = random.randint(1, 0xFFFFFFFF)
        self.expected_seq = 0

        # Socket setup
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(
            2.0
        )  # 2 second timeout for retransmissions (since there's no congestion control implemented)

        self.state = ClientState.INIT
        self.output_file = None

    def pack_message(self, msg_type: MsgType, seq_num: int, payload: bytes = b"") -> bytes:
        """Helper to create a binary packet according to the protocol spec."""
        header = struct.pack(HEADER_FORMAT, self.conn_id, seq_num, msg_type.value, len(payload))
        return header + payload

    def unpack_message(self, packet: bytes):
        """Helper to parse an incoming binary packet."""
        if len(packet) < HEADER_SIZE:
            raise ValueError("[Error] Packet too small to contain header")

        header = packet[:HEADER_SIZE]
        conn_id, seq_num, msg_type_val, payload_len = struct.unpack(HEADER_FORMAT, header)
        payload = packet[HEADER_SIZE : HEADER_SIZE + payload_len]

        return conn_id, seq_num, MsgType(msg_type_val), payload

    def run(self):
        """Main state machine loop."""
        try:
            print(f"Starting transfer for '{self.filename}' with Connection ID: {self.conn_id}")
            while self.state not in (ClientState.DONE, ClientState.ERROR):
                if self.state == ClientState.INIT:
                    self._state_init()
                elif self.state == ClientState.SEND_REQUEST:
                    self._state_send_request()
                elif self.state == ClientState.WAIT_FOR_DATA:
                    self._state_wait_for_data()
        finally:
            if self.output_file and not self.output_file.closed:
                self.output_file.close()
            self.sock.close()

    # --- State Handlers ---
    def _state_init(self):
        """Open the file and prepare for transfer."""
        try:
            os.makedirs(OUTPUT_DIR, exist_ok=True)

            # Append connection ID to the filename: e.g., out/12345678_test.txt
            out_filepath = os.path.join(OUTPUT_DIR, f"{self.conn_id}_{self.filename}")

            self.output_file = open(out_filepath, "wb")
            print(f"[INFO] Saving file to: {out_filepath}")
            self.state = ClientState.SEND_REQUEST

        except IOError as e:
            print(f"[Error] Opening file for writing: {e}")
            self.state = ClientState.ERROR

    def _state_send_request(self):
        """Send the REQUEST Packet."""
        # Embed the segment size into the payload: e.g., "512|test.txt"
        request_payload = f"{self.segment_size}|{self.filename}"

        packet = self.pack_message(MsgType.REQUEST, 0, request_payload.encode("utf-8"))
        self.sock.sendto(packet, self.server_addr)
        print(f"Sent REQUEST for {self.filename} (Negotiating segment size: {self.segment_size})")
        self.state = ClientState.WAIT_FOR_DATA

    def _state_wait_for_data(self):
        """Receive DATA, Stop-and-Wait, Handle ACKs and End of Transfer."""
        try:
            packet, addr = self.sock.recvfrom(HEADER_SIZE + self.segment_size)
        except socket.timeout:
            # Timeout triggered. Retransmit last message.
            if self.expected_seq == 0:
                print("[Timeout] waiting for first data packet. Retransmitting REQUEST...")
                self.state = ClientState.SEND_REQUEST
            else:
                print(
                    f"[Timeout] waiting for DATA {self.expected_seq}. Retransmitting ACK {self.expected_seq - 1}..."
                )
                ack_pkt = self.pack_message(MsgType.ACK, self.expected_seq - 1)
                self.sock.sendto(ack_pkt, self.server_addr)
            return

        try:
            conn_id, seq_num, msg_type, payload = self.unpack_message(packet)
        except (ValueError, struct.error) as e:
            print(f"[Error] Malformed packet received: {e}")
            return

        if conn_id != self.conn_id:
            print(f"[Ignored] packet with mismatched Connection ID: {conn_id}")
            return

        if msg_type == MsgType.ERROR:
            print(f"[Error] Server reported an error: {payload.decode('utf-8', errors='replace')}")
            self.state = ClientState.ERROR
            return

        if msg_type == MsgType.DATA:
            if seq_num == self.expected_seq:
                # Write the payload data to the output file
                self.output_file.write(payload)
                print(f"[INFO] Received DATA {seq_num} ({len(payload)} bytes). Sending ACK.")

                # Handle confirmations (Send ACK)
                ack_pkt = self.pack_message(MsgType.ACK, seq_num)
                self.sock.sendto(ack_pkt, self.server_addr)

                # Increment expected sequence for stop-and-wait
                self.expected_seq += 1

                # Detect the End of the Transfer
                if len(payload) < self.segment_size:
                    print("[INFO] Final packet received. Transfer complete.")
                    self.state = ClientState.DONE

            elif seq_num < self.expected_seq:
                # Received an older packet (ACK was likely lost). Re-ACK it.
                print(f"[WARNING] Received duplicate DATA {seq_num}. Resending ACK.")
                ack_pkt = self.pack_message(MsgType.ACK, seq_num)
                self.sock.sendto(ack_pkt, self.server_addr)
            else:
                print(
                    f"[WARNING] Out of order packet {seq_num} (expected {self.expected_seq}). Ignored."
                )


def main():
    # Parse Runtime Parameters
    parser = argparse.ArgumentParser(description="Reliable UDP File Transfer Client")
    parser.add_argument("server_ip", help="Server IP address (e.g., 127.0.0.1)")
    parser.add_argument("server_port", type=int, help="Server UDP port")
    parser.add_argument("filename", help="Name of the file to retrieve")
    parser.add_argument(
        "--segment-size",
        type=int,
        default=512,
        help="Maximum UDP payload size in bytes (default: 512)",
    )

    args = parser.parse_args()

    # Initialize and run the state machine
    client = RDTClient(
        server_ip=args.server_ip,
        server_port=args.server_port,
        filename=args.filename,
        segment_size=args.segment_size,
    )
    client.run()


if __name__ == "__main__":
    main()
