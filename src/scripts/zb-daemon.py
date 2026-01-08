#!/usr/bin/env python3
# ==============================================================================
# ZBridge Daemon (Python Rewrite)
# Role: Robust State Machine, Audio Graph Manager & Handshake Host
# ==============================================================================

import socket
import time
import subprocess
import os
import signal
import sys
import json
import threading
import logging
import argparse
from logging.handlers import SysLogHandler

# --- Configuration ---
CONFIG_DIR = os.path.expanduser("~/.config/zbridge")
CONFIG_FILE = os.path.join(CONFIG_DIR, "state.conf")
READY_FLAG = "/tmp/zbridge_ready"
CONFIG_PID_FILE = "/tmp/zbridge_config_pid"
LOG_TAG = "zbridge-daemon"

UDP_PORT_LISTEN = 5001
UDP_PORT_SEND = 5002

# Globals
running = True
current_state = "DISCONNECTED"
phone_ip = ""
last_heartbeat = 0
gst_process = None
scrcpy_process = None
lock = threading.Lock()

# Args
args = None

# Setup Logging
logger = logging.getLogger(LOG_TAG)
logger.setLevel(logging.INFO)
syslog = SysLogHandler(address='/dev/log')
formatter = logging.Formatter('%(name)s: [%(levelname)s] %(message)s')
syslog.setFormatter(formatter)
logger.addHandler(syslog)
console = logging.StreamHandler()
console.setFormatter(formatter)
logger.addHandler(console)

def log(msg):
    logger.info(msg)

def error(msg):
    logger.error(msg)

# --- Helpers ---

def get_local_ip_for_target(target_ip):
    try:
        # Create a dummy socket to find the route
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((target_ip, 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None

def read_config():
    """Reads bash-style config file for compatibility"""
    config = {}
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            for line in f:
                if '=' in line:
                    key, val = line.strip().split('=', 1)
                    config[key] = val.strip('"')
    return config

def get_node_id(node_name):
    try:
        output = subprocess.check_output(["pw-dump", "Node"], stderr=subprocess.DEVNULL)
        nodes = json.loads(output)
        for node in nodes:
            if node.get("info", {}).get("props", {}).get("node.name") == node_name:
                return str(node["id"])
    except Exception as e:
        pass
    return None

def run_command(cmd_list, bg=False):
    try:
        if bg:
            return subprocess.Popen(cmd_list, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.run(cmd_list, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return None
    except Exception as e:
        error(f"Command failed: {cmd_list} -> {e}")
        return None

def send_notification(title, message):
    """Sends a desktop notification using notify-send"""
    try:
        subprocess.Popen(["notify-send", "-u", "critical", title, message])
    except Exception as e:
        error(f"Failed to send notification: {e}")

def setup_audio_graph():
    # 1. Create nodes if missing
    nodes = ["zbin", "zbout", "zmic"]
    descs = ["ZeroBridge_Phone_Mic", "ZeroBridge_To_Phone", "ZeroBridge_Microphone"]
    types = ["Audio/Sink", "Audio/Sink", "Audio/Source/Virtual"]
    
    for i, node in enumerate(nodes):
        if not get_node_id(node):
            cmd = [
                "pw-cli", "create-node", "adapter",
                "factory.name=support.null-audio-sink",
                f"node.name={node}",
                f"media.class={types[i]}",
                f"node.description={descs[i]}",
                "object.linger=true"
            ]
            run_command(cmd)
    
    # 2. Enforce Routing (Clean up bad links first)
    try:
        # A. Link Phone Mic (zbin) -> Virtual Mic (zmic)
        run_command(["pw-link", "zbin:monitor_FL", "zmic:input_FL"])
        run_command(["pw-link", "zbin:monitor_FR", "zmic:input_FR"])
        
        # B. Link SDL Application (Scrcpy Audio) -> zbin (Phone Input)
        run_command(["pw-link", "SDL Application:output_FL", "zbin:playback_FL"])
        run_command(["pw-link", "SDL Application:output_FR", "zbin:playback_FR"])
        
        # C. Link Desktop Loopback -> zbout (PC Output)
        run_command(["pw-link", "output.ZBridge_Desktop:output_FL", "zbout:playback_FL"])
        run_command(["pw-link", "output.ZBridge_Desktop:output_FR", "zbout:playback_FR"])

        # --- D. CLEANUP / ANTI-FEEDBACK RULES ---
        
        # 1. Disconnect Scrcpy from zbout (Prevents Loop)
        run_command(["pw-link", "-d", "SDL Application:output_FL", "zbout:playback_FL"])
        run_command(["pw-link", "-d", "SDL Application:output_FR", "zbout:playback_FR"])
        
        # 2. Disconnect Monitor Loopback from zbout (Prevents Loop)
        run_command(["pw-link", "-d", "output.ZBridge_Monitor:output_FL", "zbout:playback_FL"])
        run_command(["pw-link", "-d", "output.ZBridge_Monitor:output_FR", "zbout:playback_FR"])

        # 3. Disconnect Virtual Mic from Desktop Capture (Prevents Virtual Mic being broadcasted back to phone)
        run_command(["pw-link", "-d", "zmic:capture_FL", "input.ZBridge_Desktop:input_FL"])
        run_command(["pw-link", "-d", "zmic:capture_FR", "input.ZBridge_Desktop:input_FR"])
        
    except:
        pass

def manage_loopback(name, active, source=None, sink=None):
    is_running = subprocess.run(["pgrep", "-f", f"pw-loopback.*--name {name}"], stdout=subprocess.DEVNULL).returncode == 0
    
    if active == "on" and not is_running:
        log(f"Enabling Loopback: {name}")
        cmd = ["pw-loopback", "--name", name]
        if source and source != "0": cmd.append(f"--capture-props={{ \"node.target\": \"{source}\" }}")
        if sink and sink != "0": cmd.append(f"--playback-props={{ \"node.target\": \"{sink}\" }}")
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif active != "on" and is_running:
        log(f"Disabling Loopback: {name}")
        run_command(["pkill", "-f", f"pw-loopback.*--name {name}"])

def handle_reload(signum, frame):
    log(":: [Daemon] Reload signal received (SIGUSR1). Re-enforcing graph... ::")
    # Immediate graph cleanup when config changes
    setup_audio_graph()
    
    # ACK to zb-config if waiting
    if os.path.exists(CONFIG_PID_FILE):
        try:
            with open(CONFIG_PID_FILE, 'r') as f:
                pid = int(f.read().strip())
            log(f"Sending confirmation (SIGUSR2) to zb-config PID: {pid}")
            os.kill(pid, signal.SIGUSR2)
        except Exception as e:
            error(f"Failed to ACK zb-config: {e}")
        finally:
            # Clean up the PID file so we don't signal stale processes later
            try:
                os.remove(CONFIG_PID_FILE)
            except: pass

# --- Threads ---

def network_listener():
    """Listens for READY/HEARTBEAT from Phone"""
    global current_state, last_heartbeat, phone_ip
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('0.0.0.0', UDP_PORT_LISTEN))
    sock.settimeout(1.0)
    
    log(f"Listening on UDP {UDP_PORT_LISTEN}...")
    
    while running:
        try:
            data, addr = sock.recvfrom(1024)
            msg = data.decode('utf-8').strip()
            
            if "READY" in msg:
                with lock:
                    last_heartbeat = time.time()
                    if current_state != "CONNECTED":
                        log(f"Handshake received from {addr[0]}. Connected.")
                        current_state = "CONNECTED"
                        # Create flag for other scripts
                        with open(READY_FLAG, 'w') as f: f.write("1")
                    
                    # ALWAYS ACK (Silent Heartbeat)
                    if phone_ip.split(':')[0] != addr[0]:
                        pass 
                        
                    # Send ACK back
                    ack_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    ack_sock.sendto(b"ACK", (addr[0], UDP_PORT_SEND))
        except socket.timeout:
            pass
        except Exception as e:
            error(f"Listener Error: {e}")
            time.sleep(1)

def connection_manager():
    """Manages State, Poking, and Processes"""
    global current_state, gst_process, scrcpy_process, phone_ip, last_heartbeat
    
    start_time = time.time()
    startup_notified = False

    while running:
        # 1. Config & Graph Update
        setup_audio_graph()
        cfg = read_config()
        
        new_ip = cfg.get("PHONE_IP", "")
        monitor = cfg.get("MONITOR", "off")
        desktop = cfg.get("DESKTOP", "off")
        cam_facing = cfg.get("CAM_FACING", "back")
        
        # Detect IP Change
        if new_ip != phone_ip:
            log(f"Target IP Changed: {new_ip}")
            phone_ip = new_ip
            current_state = "DISCONNECTED"
            if gst_process: gst_process.terminate(); gst_process = None
            if scrcpy_process: scrcpy_process.terminate(); scrcpy_process = None
            if os.path.exists(READY_FLAG): os.remove(READY_FLAG)

        manage_loopback("ZBridge_Monitor", monitor, "zbin", "0")
        manage_loopback("ZBridge_Desktop", desktop, "0", "zbout")

        # 2. State Logic
        target_ip_clean = phone_ip.split(':')[0]
        
        if not target_ip_clean or target_ip_clean == "127.0.0.1":
            time.sleep(1)
            continue

        # Check Heartbeat Timeout (10s)
        if current_state == "CONNECTED" and (time.time() - last_heartbeat > 10):
            log("Heartbeat timed out. resetting to DISCONNECTED.")
            current_state = "DISCONNECTED"
            if os.path.exists(READY_FLAG): os.remove(READY_FLAG)
            if gst_process: gst_process.terminate(); gst_process = None

        # Actions based on State
        if current_state == "DISCONNECTED":
            
            # Startup Notification Logic (-d flag)
            if args.debug_notify and not startup_notified:
                if time.time() - start_time > 5.0:
                    log("Startup Timeout: No ready response in 5s. Sending Notification.")
                    send_notification("ZeroBridge Connect", "No response from phone.\nRun 'sv restart zreceiver' on device.")
                    startup_notified = True

            # ACTIVE ADVERTISING: Poke the phone
            my_ip = get_local_ip_for_target(target_ip_clean)
            if my_ip:
                msg = f"SYNC:{my_ip}".encode('utf-8')
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    sock.sendto(msg, (target_ip_clean, UDP_PORT_SEND))
                except: pass
            time.sleep(1) # Poke every second

        elif current_state == "CONNECTED":
            # Reset startup notification if we connect
            startup_notified = True 
            
            # Ensure ADB
            if not scrcpy_process or scrcpy_process.poll() is not None:
                subprocess.run(["adb", "connect", phone_ip], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # Start GStreamer if missing
            if gst_process is None or gst_process.poll() is not None:
                zbout_id = get_node_id("zbout")
                if zbout_id:
                    log(f"Starting Stream -> {target_ip_clean}:5000")
                    # BALANCED: frame-size=10 (10ms) - less overhead than 5ms, less latency than 20ms
                    cmd = [
                        "gst-launch-1.0", "-q", "pipewiresrc", f"path={zbout_id}", "!",
                        "audioconvert", "!",
                        "opusenc", "bitrate=96000", "audio-type=voice", "frame-size=10", "!",
                        "rtpopuspay", "!",
                        "udpsink", f"host={target_ip_clean}", "port=5000", "sync=false", "async=false"
                    ]
                    gst_process = subprocess.Popen(cmd)
                else:
                    error("Cannot start stream: 'zbout' node missing.")
            
            # Start Scrcpy if missing
            if scrcpy_process is None or scrcpy_process.poll() is not None:
                log("Starting Scrcpy...")
                env = os.environ.copy()
                env["PULSE_SINK"] = "zbin"
                
                cmd = ["scrcpy", "--serial", target_ip_clean, "--no-window"]
                
                if monitor == "on":
                    cmd += ["--audio-source=mic", "--audio-codec=opus", "--audio-bit-rate=128K"]
                else:
                    cmd += ["--no-audio"]
                
                if cam_facing == "none":
                    cmd += ["--no-video"]
                else:
                    safe_cam = cam_facing if cam_facing in ["front", "back"] else "back"
                    orient = "flip90" if safe_cam == "front" else "flip270"
                    cmd += ["--video-source=camera", f"--camera-facing={safe_cam}", f"--capture-orientation={orient}"]
                    if os.path.exists("/dev/video9"):
                        cmd += ["--v4l2-sink=/dev/video9"]
                
                scrcpy_process = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        time.sleep(0.5)

# --- Main ---

def cleanup_handler(signum, frame):
    global running
    log("Shutting down...")
    running = False
    if gst_process: gst_process.terminate()
    if scrcpy_process: scrcpy_process.terminate()
    if os.path.exists(READY_FLAG): os.remove(READY_FLAG)
    subprocess.run(["pkill", "-f", "pw-loopback.*--name ZBridge_"])
    sys.exit(0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ZeroBridge Daemon")
    parser.add_argument("-d", "--debug-notify", action="store_true", help="Send desktop notification if no handshake in 5s")
    args = parser.parse_args()

    signal.signal(signal.SIGINT, cleanup_handler)
    signal.signal(signal.SIGTERM, cleanup_handler)
    # Register SIGUSR1 for zb-config reloads
    signal.signal(signal.SIGUSR1, handle_reload)
    
    if not os.path.exists(CONFIG_DIR): os.makedirs(CONFIG_DIR)
    
    t = threading.Thread(target=network_listener, daemon=True)
    t.start()
    
    connection_manager()