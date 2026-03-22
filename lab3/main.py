import argparse
import csv
import json
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

# --- Directories ---
METRICS_DIR = "metrics"


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


def run_scenario(scenario, port, filename):
    """Runs a specific test scenario by applying tc rules, starting server, and running client."""
    text = f"SCENARIO: {scenario['name']}"
    bar_length = max(55, len(text) + 4)
    log.info("=" * bar_length)
    log.info(text.center(bar_length))
    log.info("=" * bar_length)

    # Cleanup old metric files
    for metric_file in [f"{METRICS_DIR}/client_metrics.json", f"{METRICS_DIR}/server_metrics.json"]:
        if os.path.exists(metric_file):
            os.remove(metric_file)

    tc_rule = f"tc qdisc add dev veth_s root netem delay {scenario['delay']} {scenario['jitter']} loss {scenario['loss']}"
    run_cmd(f"ip netns exec {SERVER_NS} tc qdisc del dev veth_s root", check=False, silent=True)
    run_cmd(f"ip netns exec {SERVER_NS} {tc_rule}")

    server_cmd = ["ip", "netns", "exec", SERVER_NS, sys.executable, "-u", "server.py", str(port)]
    server_proc = subprocess.Popen(server_cmd, stdout=sys.stdout, stderr=sys.stderr)

    time.sleep(1)  # Give server a moment to bind

    client_cmd = f"ip netns exec {CLIENT_NS} {sys.executable} client.py {SERVER_IP} {port} {filename} --segment-size {scenario['seg']}"
    subprocess.run(client_cmd, shell=True, stdout=sys.stdout, stderr=sys.stderr)

    # Allow server to write its TIME_WAIT metrics and terminate
    time.sleep(2)
    server_proc.terminate()
    server_proc.wait()
    run_cmd(f"ip netns exec {SERVER_NS} pkill -9 -f server.py", check=False, silent=True)

    # Read gathered metrics
    c_metrics, s_metrics = {}, {}
    try:
        with open(f"{METRICS_DIR}/client_metrics.json", "r") as f:
            c_metrics = json.load(f)
        with open(f"{METRICS_DIR}/server_metrics.json", "r") as f:
            s_metrics = json.load(f)
    except Exception as e:
        log.error(f"Failed to read metrics: {e}")

    transfer_time = c_metrics.get("end_time", 0) - c_metrics.get("start_time", 0)
    bytes_recv = c_metrics.get("bytes_received", 0)
    throughput_kbps = (bytes_recv / transfer_time / 1024) if transfer_time > 0 else 0

    return {
        "Name": scenario["name"],
        "Delay": scenario["delay"],
        "Jitter": scenario["jitter"],
        "Loss": scenario["loss"],
        "SegSize": scenario["seg"],
        "Success": c_metrics.get("status") == "DONE",
        "TransferTime (s)": round(transfer_time, 3),
        "Throughput (KB/s)": round(throughput_kbps, 2),
        "Retransmissions": s_metrics.get("retransmissions", 0),
        "Timeouts (Client)": c_metrics.get("timeouts", 0),
        "Anomalies (Dup Data/ACKs)": c_metrics.get("duplicate_data", 0)
        + s_metrics.get("duplicate_acks", 0),
    }


def main():
    parser = argparse.ArgumentParser(description="Lab 3 Network Emulation Orchestrator")
    parser.add_argument("filename", help="File to transfer")
    parser.add_argument("port", type=int, nargs="?", default=8080)
    parser.add_argument(
        "--mode",
        choices=["single", "batch"],
        default="single",
        help="Run a single basic test or a batch of scenarios (default: single)",
    )
    args = parser.parse_args()

    if os.geteuid() != 0:
        log.error("Run with sudo! Ex: sudo -E .venv/bin/python main.py test.txt")
        sys.exit(1)

    os.makedirs(METRICS_DIR, exist_ok=True)

    # Define Parameter Sets based on mode
    if args.mode == "single":
        scenarios = [
            {"name": "Standard Delay", "delay": "50ms", "jitter": "10ms", "loss": "0%", "seg": 512},
            {"name": "Standard Loss", "delay": "0ms", "jitter": "0ms", "loss": "15%", "seg": 512},
        ]
    else:
        scenarios = [
            {"name": "Ideal Network", "delay": "0ms", "jitter": "0ms", "loss": "0%", "seg": 512},
            {"name": "Low Delay", "delay": "50ms", "jitter": "10ms", "loss": "0%", "seg": 512},
            {"name": "Medium Delay", "delay": "200ms", "jitter": "40ms", "loss": "0%", "seg": 512},
            {"name": "High Delay", "delay": "500ms", "jitter": "100ms", "loss": "0%", "seg": 512},
            {
                "name": "Extreme Delay",
                "delay": "1500ms",
                "jitter": "300ms",
                "loss": "0%",
                "seg": 512,
            },
            {"name": "Low Loss", "delay": "0ms", "jitter": "0ms", "loss": "2%", "seg": 512},
            {"name": "Medium Loss", "delay": "0ms", "jitter": "0ms", "loss": "10%", "seg": 512},
            {"name": "High Loss", "delay": "0ms", "jitter": "0ms", "loss": "25%", "seg": 512},
            {"name": "Extreme Loss", "delay": "0ms", "jitter": "0ms", "loss": "50%", "seg": 512},
            {
                "name": "Mixed Degraded",
                "delay": "100ms",
                "jitter": "20ms",
                "loss": "5%",
                "seg": 512,
            },
        ]

    csv_path = f"{METRICS_DIR}/experiment_results.csv"

    try:
        setup_network()
        results = []
        for sc in scenarios:
            res = run_scenario(sc, args.port, args.filename)
            results.append(res)
            log.info(f"Result: {res}")

        # Export aggregated metrics to CSV
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)

        log.info(f"Experiments finished. Metrics exported to {csv_path}")

    finally:
        teardown_network()


if __name__ == "__main__":
    main()
