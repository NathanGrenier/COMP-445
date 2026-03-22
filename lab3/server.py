import argparse
import os
import socket
import struct
import time
from enum import Enum, auto

# --- Logger ---
from logger import setup_logger

COLOR_GREEN = "\033[92m"
log = setup_logger("SERVER", COLOR_GREEN)

# --- Packet Definitions ---
# Header format: ! I I B H
# ! = Network byte order (Big-Endian)
# I = Connection ID (4 bytes, uint32)
# I = Sequence Number (4 bytes, uint32)
# B = Message Type (1 byte, uint8)
# H = Payload Length (2 bytes, uint16)
HEADER_FORMAT = "!IIBH"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
DATA_DIR = "data"
MAX_UDP_PAYLOAD = 65507

# --- Protocol Settings ---
ACK_TIMEOUT_SEC = 1.0
TIME_WAIT_RECV_TIMEOUT_SEC = 1.0
TIME_WAIT_DURATION_SEC = 4.0


class MsgType(Enum):
    REQUEST = 1
    DATA = 2
    ACK = 3
    ERROR = 4


class ServerState(Enum):
    LISTEN = auto()
    SEND_DATA = auto()
    WAIT_ACK = auto()
    TIME_WAIT = auto()


class RDTServer:
    def __init__(self, port, segment_size):
        self.port = port
        self.segment_size = segment_size

        # Socket setup
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("", self.port))

        # State machine variables
        self.state = ServerState.LISTEN
        self.client_addr = None
        self.conn_id = None
        self.file_obj = None
        self.seq_num = 0
        self.current_chunk = b""
        self.last_packet = b""
        self.time_wait_start = 0

    def pack_message(
        self, conn_id: int, seq_num: int, msg_type: MsgType, payload: bytes = b""
    ) -> bytes:
        """Helper to create a binary packet according to the protocol spec."""
        header = struct.pack(HEADER_FORMAT, conn_id, seq_num, msg_type.value, len(payload))
        return header + payload

    def unpack_message(self, packet: bytes):
        """Helper to parse an incoming binary packet."""
        if len(packet) < HEADER_SIZE:
            raise ValueError("Packet too small")

        header = packet[:HEADER_SIZE]
        conn_id, seq_num, msg_type_val, payload_len = struct.unpack(HEADER_FORMAT, header)
        payload = packet[HEADER_SIZE : HEADER_SIZE + payload_len]
        return conn_id, seq_num, MsgType(msg_type_val), payload

    def run(self):
        """Main state machine loop."""
        log.info(f"Listening on port {self.port} (Segment Size: {self.segment_size} bytes)")
        try:
            while True:
                if self.state == ServerState.LISTEN:
                    self._state_listen()
                elif self.state == ServerState.SEND_DATA:
                    self._state_send_data()
                elif self.state == ServerState.WAIT_ACK:
                    self._state_wait_ack()
                elif self.state == ServerState.TIME_WAIT:
                    self._state_time_wait()
        except KeyboardInterrupt:
            log.info("Server shutting down.")
        finally:
            if self.file_obj and not self.file_obj.closed:
                self.file_obj.close()
            self.sock.close()

    # --- State Handlers ---
    def _state_listen(self):
        """Listen and Handle REQUEST Packets."""
        self.sock.settimeout(None)  # Block indefinitely while waiting for a client
        try:
            # Use MAX_UDP_PAYLOAD here because we haven't negotiated the segment size yet
            packet, addr = self.sock.recvfrom(MAX_UDP_PAYLOAD)
            conn_id, seq_num, msg_type, payload = self.unpack_message(packet)

            if msg_type == MsgType.REQUEST:
                raw_request = payload.decode("utf-8")

                # Dynamic segment size negotiation
                if "|" in raw_request:
                    seg_str, filename = raw_request.split("|", 1)
                    self.segment_size = int(seg_str)
                    log.info(f"Client negotiated segment size: {self.segment_size} bytes")
                else:
                    filename = raw_request
                    log.info(
                        f"Standard client detected. Using default segment size: {self.segment_size} bytes"
                    )

                log.info(f"Received REQUEST for '{filename}' from {addr}")

                # Prevent directory traversal by only taking the base filename
                safe_filename = os.path.basename(filename)
                filepath = os.path.join(DATA_DIR, safe_filename)

                if os.path.isfile(filepath):
                    # Setup server-side state for this transfer
                    self.conn_id = conn_id
                    self.client_addr = addr
                    self.file_obj = open(filepath, "rb")
                    self.seq_num = 0

                    # Segment the File (Read first chunk)
                    self.current_chunk = self.file_obj.read(self.segment_size)
                    self.state = ServerState.SEND_DATA
                else:
                    log.error(f"File '{filepath}' not found. Sending ERROR packet.")
                    err_pkt = self.pack_message(conn_id, 0, MsgType.ERROR, b"File not found")
                    self.sock.sendto(err_pkt, addr)

        except (ValueError, struct.error) as e:
            log.warning(f"Malformed packet received in LISTEN: {e}")

    def _state_send_data(self):
        """Send Data Using Stop-and-Wait."""
        self.last_packet = self.pack_message(
            self.conn_id, self.seq_num, MsgType.DATA, self.current_chunk
        )
        self.sock.sendto(self.last_packet, self.client_addr)
        log.info(f"Sent DATA {self.seq_num} ({len(self.current_chunk)} bytes)")
        self.state = ServerState.WAIT_ACK

    def _state_wait_ack(self):
        """Handle timeouts, confirmations, and retransmissions."""
        self.sock.settimeout(
            ACK_TIMEOUT_SEC
        )  # No congestion control, so we use a fixed timeout for ACKs
        try:
            packet, addr = self.sock.recvfrom(HEADER_SIZE + self.segment_size)
            conn_id, seq_num, msg_type, payload = self.unpack_message(packet)

            # Ignore packets from other clients/connections
            if addr != self.client_addr or conn_id != self.conn_id:
                return

            if msg_type == MsgType.ACK:
                if seq_num == self.seq_num:
                    log.info(f"Received ACK {seq_num}")
                    # Check if this was the final packet
                    if len(self.current_chunk) < self.segment_size:
                        log.info("Final packet acknowledged. Entering TIME_WAIT.")
                        self.file_obj.close()
                        self.time_wait_start = time.time()
                        self.state = ServerState.TIME_WAIT
                    else:
                        # Move to the next sequence and read the next chunk
                        self.seq_num += 1
                        self.current_chunk = self.file_obj.read(self.segment_size)
                        self.state = ServerState.SEND_DATA

            elif msg_type == MsgType.REQUEST:
                # The client's timeout triggered because it missed our first DATA packet
                log.warning("Received duplicate REQUEST. Retransmitting first DATA packet.")
                self.sock.sendto(self.last_packet, self.client_addr)

        except socket.timeout:
            log.warning(f"Timeout: No ACK received for DATA {self.seq_num}. Retransmitting...")
            self.sock.sendto(self.last_packet, self.client_addr)
        except (ValueError, struct.error):
            log.warning("Malformed packet received in WAIT_ACK. Ignored.")

    def _state_time_wait(self):
        """Handle End of Connection."""
        # Keep transfer state for a short time to handle any straggling packets (e.g., duplicate ACKs or REQUESTs)
        self.sock.settimeout(TIME_WAIT_RECV_TIMEOUT_SEC)
        if time.time() - self.time_wait_start > TIME_WAIT_DURATION_SEC:
            log.info("Connection state discarded. Returning to LISTEN.")
            self.state = ServerState.LISTEN
            return

        try:
            packet, addr = self.sock.recvfrom(HEADER_SIZE + self.segment_size)
            conn_id, seq_num, msg_type, payload = self.unpack_message(packet)

            if conn_id == self.conn_id:
                # Re-send the final DATA packet if a duplicate ACK or REQUEST arrives
                if msg_type in (MsgType.ACK, MsgType.REQUEST):
                    log.warning(
                        "Stray packet received during TIME_WAIT. Retransmitting final DATA."
                    )
                    self.sock.sendto(self.last_packet, self.client_addr)
            elif msg_type == MsgType.REQUEST:
                # Edge case: A completely new client request came in while we were waiting
                # For this simple lab, we just drop the TIME_WAIT state and serve the new client.
                log.info("New connection request received during TIME_WAIT. Resetting to LISTEN.")
                self.state = ServerState.LISTEN

        except socket.timeout:
            pass  # Loop again until 5 seconds passes
        except (ValueError, struct.error):
            log.warning("Malformed packet received in TIME_WAIT. Ignored.")


def main():
    parser = argparse.ArgumentParser(description="Reliable UDP File Transfer Server")
    parser.add_argument("port", type=int, help="UDP port to listen on")
    parser.add_argument("--segment-size", type=int, default=512, help="Maximum UDP payload size")
    args = parser.parse_args()

    server = RDTServer(port=args.port, segment_size=args.segment_size)
    server.run()


if __name__ == "__main__":
    main()
