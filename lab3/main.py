import argparse
import os
import subprocess
import sys
import time

# --- Logger ---
from logger import setup_logger

COLOR_MAGENTA = "\033[95m"
log = setup_logger("MAIN", COLOR_MAGENTA)

# --- Network Configuration ---
SERVER_NS = "server_ns"
CLIENT_NS = "client_ns"
SERVER_IP = "10.0.0.2"
CLIENT_IP = "10.0.0.1"
PORT = "8080"
TEST_FILE = "emulation_test.txt"
FILE_SIZE_BYTES = 10 * 1024  # 10 KB test file


def run_cmd(cmd, check=True, silent=False):
    """Executes a shell command."""
    if not silent:
        log.info(f"Executing: {cmd}")
    result = subprocess.run(cmd, shell=True, text=True, capture_output=silent)
    if check and result.returncode != 0:
        log.error(f"Command failed: {result.stderr}")
        sys.exit(1)
    return result


def setup_network():
    """Creates namespaces and connects them via a veth pair."""
    log.info("=== Setting up Network Namespaces & VETH Pair ===")
    teardown_network(silent=True)  # Clean up previous state if any

    commands = [
        f"ip netns add {SERVER_NS}",
        f"ip netns add {CLIENT_NS}",
        "ip link add veth_s type veth peer name veth_c",
        f"ip link set veth_s netns {SERVER_NS}",
        f"ip link set veth_c netns {CLIENT_NS}",
        f"ip netns exec {SERVER_NS} ip addr add {SERVER_IP}/24 dev veth_s",
        f"ip netns exec {CLIENT_NS} ip addr add {CLIENT_IP}/24 dev veth_c",
        f"ip netns exec {SERVER_NS} ip link set veth_s up",
        f"ip netns exec {CLIENT_NS} ip link set veth_c up",
        f"ip netns exec {SERVER_NS} ip link set lo up",
        f"ip netns exec {CLIENT_NS} ip link set lo up",
    ]
    for cmd in commands:
        run_cmd(cmd)


def teardown_network(silent=False):
    """Deletes namespaces (which automatically destroys the veth pair)."""
    if not silent:
        log.info("=== Tearing Down Network Setup ===")
    run_cmd(f"ip netns del {SERVER_NS}", check=False, silent=silent)
    run_cmd(f"ip netns del {CLIENT_NS}", check=False, silent=silent)


def run_scenario(scenario_name, tc_command, port, filename, segment_size):
    """Runs a specific test scenario by applying tc rules, starting server, and running client."""
    text = f"SCENARIO: {scenario_name}"
    bar_length = max(55, len(text) + 4)
    log.info("=" * bar_length)
    log.info(text.center(bar_length))
    log.info("=" * bar_length)

    run_cmd(f"ip netns exec {SERVER_NS} tc qdisc del dev veth_s root", check=False, silent=True)
    run_cmd(f"ip netns exec {SERVER_NS} {tc_command}")

    server_cmd = ["ip", "netns", "exec", SERVER_NS, sys.executable, "-u", "server.py", str(port)]
    log.info(f"Starting Server: {' '.join(server_cmd)}")
    server_proc = subprocess.Popen(server_cmd, stdout=sys.stdout, stderr=sys.stderr)

    time.sleep(1)  # Give server a moment to bind

    client_cmd = f"ip netns exec {CLIENT_NS} {sys.executable} client.py {SERVER_IP} {port} {filename} --segment-size {segment_size}"
    log.info(f"Starting Client: {client_cmd}")

    start_time = time.time()
    subprocess.run(client_cmd, shell=True)
    end_time = time.time()

    duration = end_time - start_time
    log.info(f"[RESULT] Transfer completed in {duration:.2f} seconds.")

    server_proc.terminate()
    server_proc.wait()
    run_cmd(f"ip netns exec {SERVER_NS} pkill -9 -f server.py", check=False, silent=True)


def main():
    parser = argparse.ArgumentParser(description="Lab 3 Network Emulation Orchestrator")
    parser.add_argument("filename", help="Name of the file in the data/ directory to transfer")
    parser.add_argument(
        "port", type=int, nargs="?", default=8080, help="Port to use for the server (default: 8080)"
    )
    parser.add_argument(
        "--segment-size",
        type=int,
        default=512,
        help="Maximum UDP payload size in bytes (default: 512)",
    )
    args = parser.parse_args()

    if os.geteuid() != 0:
        log.error("This script requires root privileges to configure network namespaces.")
        log.error("Please run it using: sudo -E uv run main.py")
        sys.exit(1)

    # Check if the file actually exists
    filepath = os.path.join("data", args.filename)
    if not os.path.isfile(filepath):
        log.error(
            f"File '{filepath}' does not exist. Please place your file in the 'data/' directory."
        )
        sys.exit(1)

    # --- Netem Emulation Variables ---
    # Delay Parameters
    delay_base = "100ms"
    delay_jitter = "20ms"
    delay_dist = "normal"

    # Packet Loss Parameters
    loss_percent = "10%"

    try:
        setup_network()

        # --- Scenario 1: Delay ---
        delay_rule = f"tc qdisc add dev veth_s root netem delay {delay_base} {delay_jitter} distribution {delay_dist}"
        run_scenario(
            scenario_name=f"DELAY ({delay_base} base, {delay_jitter} jitter)",
            tc_command=delay_rule,
            port=args.port,
            filename=args.filename,
            segment_size=args.segment_size,
        )

        # --- Scenario 2: Packet Loss ---
        loss_rule = f"tc qdisc add dev veth_s root netem loss {loss_percent}"
        run_scenario(
            scenario_name=f"PACKET LOSS ({loss_percent} Packet Loss)",
            tc_command=loss_rule,
            port=args.port,
            filename=args.filename,
            segment_size=args.segment_size,
        )
    finally:
        teardown_network()


if __name__ == "__main__":
    main()
