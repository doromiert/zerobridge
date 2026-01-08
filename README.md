
# ZeroBridge (zb)

**ZeroBridge** is a bidirectional Android-Linux audio/video bridge. It turns your Android device into a high-quality wireless microphone, camera, and secondary display for your Linux desktop, using `pipewire`, `scrcpy`, and `gstreamer`.

It features a robust **Python-based daemon** with self-healing audio routing, persistent IP caching, and a "Dual Advertising" handshake protocol that ensures instant reconnections even after network drops or server restarts.

## Features

- **Virtual Microphone:** Use your phone's mic as a native Linux input source (`zmic`).
- **Audio Monitor:** Listen to your phone's mic on your PC headphones in real-time.
- **Desktop Audio Bridge:** Stream your PC's desktop audio _to_ your phone (wireless headphones adapter).
- **Camera Integration:** Use your phone as a webcam (via `v4l2loopback`).
- **Robust Networking:**
  - **Auto-Discovery:** PC scans for the phone; Phone caches the PC's IP.
  - **Dual Advertising:** Both sides aggressively advertise their presence when disconnected.
  - **Self-Healing:** Automatically repairs Broken PipeWire links or crashed GStreamer streams.
- **NixOS / Home Manager Native:** Deploys easily via Flakes.

---

## Architecture

ZeroBridge consists of three main components:

1.  **Daemon (PC):** A Python service (`zb-daemon`) that manages the PipeWire audio graph, handles the UDP handshake, and launches `scrcpy` (video/control) and `gstreamer` (audio tx/rx).
2.  **Receiver (Phone):** A Python script running in **Termux** that receives the audio stream, sends the microphone audio (via Scrcpy's backchannel), and maintains a heartbeat with the PC.
3.  **GNOME Extension:** A UI for toggling features and updating the target phone IP.

### The Handshake Protocol (UDP 5001/5002)

1.  **Disconnected:**
    - **PC:** Broadcasts `SYNC:<PC_IP>` to the last known Phone IP every second.
    - **Phone:** Broadcasts `READY` to the cached PC IP every second.
2.  **Connection:**
    - When either side receives the other's packet, they update their target IP.
    - The PC sends an `ACK` packet.
3.  **Connected:**
    - The Phone stops broadcasting and switches to a 10s Heartbeat.
    - The PC starts the GStreamer audio stream and Scrcpy video session.

---

## Installation

### Prerequisites

- **Linux Desktop:** PipeWire, WirePlumber, Wayland/X11.
- **Android Device:** Developer Options > USB Debugging enabled.
- **Nix:** Flakes enabled.

### 1. Add to `flake.nix`

Add ZeroBridge to your system flake inputs:

```nix
inputs = {
  nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";

  # Add ZeroBridge Input
  zbridge.url = "github:doromiert/zerobridge";
  zbridge.inputs.nixpkgs.follows = "nixpkgs";
};
```

### 2. Configure Home Manager

Import the module in your Home Manager configuration:

```nix
{ inputs, pkgs, ... }:
{
  imports = [
    inputs.zbridge.homeManagerModules.default
  ];

  services.zbridge = {
    enable = true;
    installExtension = true; # Auto-installs GNOME Shell extension
  };
}
```

Apply your configuration (`home-manager switch` or `nixos-rebuild switch`).

---

## Setup & Usage

### Step 1: Initial Pairing (USB)

1.  Connect your Android phone to your PC via USB.
2.  Ensure **USB Debugging** is active.
3.  Run the installer to deploy the Python receiver to Termux:

    ```bash
    zb-installer <PHONE_IP>
    # Example: zb-installer 192.168.1.45
    ```

    _This will install Python/GStreamer in Termux, set up the scripts, and start the service._

### Step 2: Configuration (Wireless)

You can now disconnect the USB cable. Use the GNOME extension or the CLI to control the bridge.

**CLI Control:**

```bash
# Update Target Phone IP
zb-config set PHONE_IP "192.168.1.45"

# Toggle Features
zb-config set MONITOR "on"      # Listen to phone mic on PC
zb-config set DESKTOP "on"      # Stream PC audio to Phone
zb-config set CAM_FACING "back" # Use back camera
```

### Step 3: Verify Audio

Open your OS Sound Settings (e.g., `pavucontrol`):

- **Input Devices:** You should see **"ZeroBridge_Microphone"**. Select this as your default input.
- **Output Devices:** If `DESKTOP="on"`, change your output device to **"ZeroBridge_To_Phone"** to hear PC audio on your phone.

---

## Troubleshooting

**1. Audio Loops / Feedback**

- The daemon includes anti-feedback rules. If you hear an echo, ensure `zb-daemon` is running (`systemctl --user status zbridge`).
- Trigger a graph reload: `zb-config reload`.

**2. Phone Not Connecting**

- Check Firewall: Ensure UDP ports **5000-5002** are open on your PC.
- Check Phone IP: Run `zb-config set PHONE_IP <NEW_IP>`.
- Debug Mode: Run `zb-debug-phone <IP>` to see the phone's logs in real-time.

**3. Resetting State**

- Restart the service:
  ```bash
  systemctl --user restart zbridge
  ```

---

## License

MIT License
\*/
