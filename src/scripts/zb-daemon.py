#!/usr/bin/env python3
# ==============================================================================
# ZBridge Daemon (Python Rewrite)
# Role: Robust State Machine, Audio Graph Manager & Handshake Host
# Updated: Fixed Mic Slider Logic (Strict Loopback Chaining)
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
placeholder_process = None
current_scrcpy_cmd = [] 
session_id = str(int(time.time())) 
lock = threading.Lock()
scrcpy_last_crash = 0

# Track loopback processes to prevent infinite spawning
virtual_sinks = {} 

# Args
args = None

# Setup Logging
logger = logging.getLogger(LOG_TAG)
logger.setLevel(logging.INFO)
try:
    syslog = SysLogHandler(address='/dev/log')
    formatter = logging.Formatter('%(name)s: [%(levelname)s] %(message)s')
    syslog.setFormatter(formatter)
    logger.addHandler(syslog)
except: pass 
console = logging.StreamHandler()
formatter = logging.Formatter('%(name)s: [%(levelname)s] %(message)s')
console.setFormatter(formatter)
logger.addHandler(console)

def log(msg):
    logger.info(msg)

def error(msg):
    logger.error(msg)

# --- Helpers ---

def get_local_ip_for_target(target_ip):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((target_ip, 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None

def read_config():
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
    try:
        subprocess.Popen(["notify-send", "-u", "critical", title, message])
    except Exception as e:
        error(f"Failed to send notification: {e}")

def get_camera_icon_path():
    """Searches for a standard XDG camera-disabled icon."""
    search_paths = [
        "/usr/share/icons/Adwaita/symbolic/status",
        "/usr/share/icons/Adwaita/scalable/status",
        "/usr/share/icons/hicolor/symbolic/status",
        "/usr/share/icons/hicolor/scalable/status",
        "/usr/share/icons/Papirus/symbolic/status"
    ]
    target_names = ["camera-disabled-symbolic.svg", "camera-off-symbolic.svg", "camera-web-off-symbolic.svg"]
    
    for path in search_paths:
        if os.path.isdir(path):
            for name in target_names:
                full_path = os.path.join(path, name)
                if os.path.exists(full_path):
                    return full_path
    return None

def ensure_adb_connection(target_ip):
    """Ensures ADB is connected to the target IP before launching Scrcpy."""
    try:
        # Check current devices
        output = subprocess.check_output(["adb", "devices"], text=True)
        if target_ip in output:
            return True
        
        # Not found, try connecting
        log(f":: [Daemon] ADB not connected to {target_ip}. Connecting...")
        res = subprocess.run(["adb", "connect", target_ip], timeout=5, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if "connected to" in res.stdout:
            log(f":: [Daemon] ADB Connected: {res.stdout.strip()}")
            return True
        else:
            error(f":: [Daemon] ADB Connect Failed: {res.stdout.strip()}")
            return False
    except Exception as e:
        error(f":: [Daemon] ADB Error: {e}")
        return False

def spawn_loopback_sink(node_name, description, target_node):
    """Starts a pw-loopback process acting as a Volume-Controlled Sink."""
    global virtual_sinks

    client_name = f"zbridge_loopback_{node_name}"

    # 1. Check Python Tracker
    if node_name in virtual_sinks:
        proc = virtual_sinks[node_name]
        if proc.poll() is None:
            return # Healthy
        else:
            log(f":: [Daemon] Virtual Sink {node_name} died unexpectedly. Respawning...")
            del virtual_sinks[node_name]

    # 2. Check External (Cleanup/Orphan detection)
    if subprocess.run(["pgrep", "-f", f"pw-loopback.*--name {client_name}"], stdout=subprocess.DEVNULL).returncode == 0:
        subprocess.run(["pkill", "-f", f"pw-loopback.*--name {client_name}"])
        time.sleep(0.2)

    log(f":: [Daemon] Spawning Virtual Sink: {node_name} -> {target_node}")
    
    capture_props = {
        "media.class": "Audio/Sink",
        "node.name": node_name,
        "node.description": description,
        "audio.position": ["FL", "FR"]
    }
    
    playback_props = {
        "node.target": target_node,
        "audio.position": ["FL", "FR"],
        "node.dont-reconnect": True
    }
    
    cmd = [
        "pw-loopback",
        "--name", client_name, 
        "--capture-props", json.dumps(capture_props),
        "--playback-props", json.dumps(playback_props)
    ]
    
    virtual_sinks[node_name] = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def setup_audio_graph():
    # 1. Create Internal VOID nodes
    void_nodes = ["zbout_void", "zbin_void", "zmic"]
    void_descs = ["ZBridge_Out_Internal", "ZBridge_In_Internal", "ZeroBridge_Microphone"]
    # zbout_void/zbin_void are Sinks. zmic is Source.
    void_types = ["Audio/Sink", "Audio/Sink", "Audio/Source/Virtual"]
    
    for i, node in enumerate(void_nodes):
        if not get_node_id(node):
            cmd = [
                "pw-cli", "create-node", "adapter",
                "factory.name=support.null-audio-sink",
                f"node.name={node}",
                f"media.class={void_types[i]}",
                f"node.description={void_descs[i]}",
                "object.linger=true"
            ]
            run_command(cmd)
    
    time.sleep(0.5)

    # 2. Spawn Loopback Sinks
    spawn_loopback_sink("zbout", "ZeroBridge_To_Phone", "zbout_void")
    spawn_loopback_sink("zbin", "ZeroBridge_Phone_Mic", "zbin_void")

    # 3. Enforce Routing
    try:
        # A. Link zbin_void -> zmic
        # CRITICAL FIX: We must link the MONITOR of the intermediate void sink to the INPUT of the virtual mic
        # zbin (Slider) -> [Loopback Process] -> zbin_void (Intermediate Sink) -> [Monitor] -> zmic (Virtual Mic)
        run_command(["pw-link", "zbin_void:monitor_FL", "zmic:input_FL"])
        run_command(["pw-link", "zbin_void:monitor_FR", "zmic:input_FR"])

        # B. Route Scrcpy/SDL to zbin (The User Slider)
        sources = ["SDL Application", "scrcpy"]
        for src in sources:
            # Connect to zbin (Slider)
            run_command(["pw-link", f"{src}:output_FL", "zbin:playback_FL"])
            run_command(["pw-link", f"{src}:output_FR", "zbin:playback_FR"])
            
            # Anti-Feedback: Disconnect from zbout (PC->Phone)
            run_command(["pw-link", "-d", f"{src}:output_FL", "zbout:playback_FL"])
            run_command(["pw-link", "-d", f"{src}:output_FR", "zbout:playback_FR"])

        # C. Loopback Cleanups
        run_command(["pw-link", "-d", "output.ZBridge_Monitor:output_FL", "zbout:playback_FL"])
        run_command(["pw-link", "-d", "output.ZBridge_Monitor:output_FR", "zbout:playback_FR"])
        
        # Ensure zmic doesn't feed back into desktop capture (if using obs etc)
        # Note: zmic is a Source, so it has capture_FL/FR ports
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
    log(":: [Daemon] Reload signal (SIGUSR1). Parsing config... ::")
    if os.path.exists(CONFIG_PID_FILE):
        try:
            with open(CONFIG_PID_FILE, 'r') as f:
                pid = int(f.read().strip())
            os.kill(pid, signal.SIGUSR2)
        except Exception as e:
            error(f"Failed to ACK zb-config: {e}")
        finally:
            try: os.remove(CONFIG_PID_FILE)
            except: pass

# --- Threads ---

def network_listener():
    global current_state, last_heartbeat, phone_ip, session_id
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 262144)
    sock.bind(('0.0.0.0', UDP_PORT_LISTEN))
    sock.settimeout(1.0)
    
    log(f"Listening on UDP {UDP_PORT_LISTEN}...")
    log(f"Current Session ID: {session_id}")
    
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
                        with open(READY_FLAG, 'w') as f: f.write("1")
                    
                    ack_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    ack_msg = f"ACK:{session_id}"
                    ack_sock.sendto(ack_msg.encode('utf-8'), (addr[0], UDP_PORT_SEND))
        except socket.timeout: pass
        except Exception as e:
            error(f"Listener Error: {e}")
            time.sleep(1)

def connection_manager():
    global current_state, gst_process, scrcpy_process, placeholder_process, phone_ip, last_heartbeat, current_scrcpy_cmd, scrcpy_last_crash
    
    start_time = time.time()
    startup_notified = False

    while running:
        setup_audio_graph()
        cfg = read_config()
        
        new_ip = cfg.get("PHONE_IP", "")
        monitor = cfg.get("MONITOR", "off")
        desktop = cfg.get("DESKTOP", "off")
        cam_facing = cfg.get("CAM_FACING", "back")
        cam_orient = cfg.get("CAM_ORIENT", "")
        def_front = cfg.get("DEF_ORIENT_FRONT", "flip90")
        def_back = cfg.get("DEF_ORIENT_BACK", "flip270")
        
        if new_ip != phone_ip:
            log(f"Target IP Changed: {new_ip}")
            phone_ip = new_ip
            current_state = "DISCONNECTED"
            if gst_process: gst_process.terminate(); gst_process = None
            if scrcpy_process: scrcpy_process.terminate(); scrcpy_process = None
            if placeholder_process: placeholder_process.terminate(); placeholder_process = None
            if os.path.exists(READY_FLAG): os.remove(READY_FLAG)

        # Monitor: Listen to zmic (Final Mix) to ensure we hear volume changes
        manage_loopback("ZBridge_Monitor", monitor, "zmic", "0")
        manage_loopback("ZBridge_Desktop", desktop, "0", "zbout")

        target_ip_clean = phone_ip.split(':')[0]
        if not target_ip_clean or target_ip_clean == "127.0.0.1":
            time.sleep(1)
            continue

        if current_state == "CONNECTED" and (time.time() - last_heartbeat > 10):
            log("Heartbeat timed out.")
            current_state = "DISCONNECTED"
            if os.path.exists(READY_FLAG): os.remove(READY_FLAG)
            if gst_process: gst_process.terminate(); gst_process = None
            if scrcpy_process: scrcpy_process.terminate(); scrcpy_process = None
            if placeholder_process: placeholder_process.terminate(); placeholder_process = None

        if current_state == "DISCONNECTED":
            if args.debug_notify and not startup_notified and (time.time() - start_time > 5.0):
                send_notification("ZeroBridge", "No response from phone.")
                startup_notified = True
            
            my_ip = get_local_ip_for_target(target_ip_clean)
            if my_ip:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    sock.sendto(f"SYNC:{my_ip}".encode('utf-8'), (target_ip_clean, UDP_PORT_SEND))
                except: pass
            time.sleep(1)

        elif current_state == "CONNECTED":
            startup_notified = True 
            
            # --- AUDIO STREAM (PC -> Phone) ---
            if desktop == "on":
                if gst_process is None or gst_process.poll() is not None:
                    # Capture from the Internal Void Monitor
                    # This captures the audio AFTER the loopback applied volume
                    zbout_void_id = get_node_id("zbout_void")
                    if zbout_void_id:
                        log(f"Starting Stream -> {target_ip_clean}:5000")
                        cmd = [
                            "gst-launch-1.0", "-q", "pipewiresrc", f"path={zbout_void_id}", "do-timestamp=true", "!",
                            "audioconvert", "!",
                            "opusenc", "bitrate=96000", "audio-type=voice", "frame-size=10",
                            "inband-fec=true", "packet-loss-percentage=10", "!",
                            "rtpopuspay", "!",
                            "udpsink", f"host={target_ip_clean}", "port=5000", "sync=false", "async=false"
                        ]
                        gst_process = subprocess.Popen(cmd)
            elif desktop == "off":
                if gst_process:
                    log(":: [Daemon] Stopping Audio Stream (Desktop disabled)...")
                    gst_process.terminate()
                    gst_process = None
            
            # --- VIDEO / PLACEHOLDER LOGIC ---
            target_cmd = ["scrcpy", "--serial", phone_ip, "--no-window"]
            
            if monitor == "on":
                target_cmd += ["--audio-source=mic", "--audio-codec=opus", "--audio-bit-rate=128K"]
            else:
                target_cmd += ["--no-audio"]
            
            if cam_facing == "none":
                target_cmd += ["--no-video"]
            else:
                target_cmd.append("--camera-fps=30")
                safe_cam = cam_facing if cam_facing in ["front", "back"] else "back"
                final_orient = cam_orient if cam_orient else (def_front if safe_cam == "front" else def_back)
                target_cmd += ["--video-source=camera", f"--camera-facing={safe_cam}", f"--capture-orientation={final_orient}"]
                if os.path.exists("/dev/video9"):
                    target_cmd += ["--v4l2-sink=/dev/video9"]
            
            if scrcpy_process and current_scrcpy_cmd and target_cmd != current_scrcpy_cmd:
                log(":: [Daemon] Scrcpy config changed. Hot-swapping...")
                scrcpy_process.terminate()
                try: scrcpy_process.wait(timeout=2)
                except: scrcpy_process.kill()
                scrcpy_process = None
                log(":: [Daemon] Safety Pause (1.0s) for Camera HAL...")
                time.sleep(1.0) 

            use_placeholder = (cam_facing == "none" and os.path.exists("/dev/video9"))
            if use_placeholder:
                if not placeholder_process or placeholder_process.poll() is not None:
                    log(":: [Daemon] Starting Placeholder Stream (Black Screen + Icon)...")
                    icon_path = get_camera_icon_path()
                    gst_cmd = ["gst-launch-1.0", "videotestsrc", "pattern=black", "!", "video/x-raw,width=1920,height=1080,framerate=30/1"]
                    if icon_path:
                        gst_cmd += ["!", "gdkpixbufoverlay", f"location={icon_path}", "overlay-height=300", "overlay-width=300"]
                    else:
                        gst_cmd += ["!", "textoverlay", "text=CAMERA DISABLED", "valignment=center", "halignment=center", "font-desc=Sans 40"]
                    gst_cmd += ["!", "v4l2sink", "device=/dev/video9"]
                    placeholder_process = subprocess.Popen(gst_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                if placeholder_process:
                    log(":: [Daemon] Stopping Placeholder...")
                    placeholder_process.terminate()
                    try: placeholder_process.wait(timeout=1)
                    except: placeholder_process.kill()
                    placeholder_process = None

            if scrcpy_process and scrcpy_process.poll() is not None:
                scrcpy_last_crash = time.time()
                _, err = scrcpy_process.communicate()
                error(f"Scrcpy CRASHED. Stderr: {err}")
                scrcpy_process = None

            if scrcpy_process is None or scrcpy_process.poll() is not None:
                if time.time() - scrcpy_last_crash < 3.0:
                    pass 
                else:
                    if ensure_adb_connection(phone_ip):
                        log(f"Starting Scrcpy ({cam_facing})...")
                        log(f"CMD: {' '.join(target_cmd)}")
                        env = os.environ.copy()
                        scrcpy_process = subprocess.Popen(target_cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
                        current_scrcpy_cmd = target_cmd

        time.sleep(0.5)

def cleanup_handler(signum, frame):
    global running
    log("Shutting down...")
    running = False
    if gst_process: gst_process.terminate()
    if scrcpy_process: scrcpy_process.terminate()
    if placeholder_process: placeholder_process.terminate()
    if os.path.exists(READY_FLAG): os.remove(READY_FLAG)
    subprocess.run(["pkill", "-f", "pw-loopback.*--name ZBridge_"])
    for name, proc in virtual_sinks.items():
        if proc.poll() is None: proc.terminate()
    subprocess.run(["pkill", "-f", "pw-loopback.*zbridge_loopback_"])
    sys.exit(0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ZeroBridge Daemon")
    parser.add_argument("-d", "--debug-notify", action="store_true", help="Send desktop notification if no handshake in 5s")
    args = parser.parse_args()

    signal.signal(signal.SIGINT, cleanup_handler)
    signal.signal(signal.SIGTERM, cleanup_handler)
    signal.signal(signal.SIGUSR1, handle_reload)
    
    if not os.path.exists(CONFIG_DIR): os.makedirs(CONFIG_DIR)
    
    t = threading.Thread(target=network_listener, daemon=True)
    t.start()
    
    connection_manager()