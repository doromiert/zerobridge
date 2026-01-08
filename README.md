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
- **Universal Compatibility:** Support for NixOS (Flakes/Home Manager) and Arch Linux (AUR).

---

## Architecture

ZeroBridge consists of three main components:

1.  **Daemon (PC):** A Python service (`zb-daemon`) that manages the PipeWire audio graph, handles the UDP handshake, and launches `scrcpy` (video/control) and `gstreamer` (audio tx/rx).
2.  **Receiver (Phone):** A Python script running in **Termux** that receives the audio stream, sends the microphone audio (via Scrcpy's backchannel), and maintains a heartbeat with the PC.
3.  **GNOME Extension:** A UI for toggling features and updating the target phone IP.

---

## Installation

### A. Arch Linux (AUR)

If you are on Arch (or a derivative like CachyOS), you can install the core tools via the AUR:

```bash
yay -S zbridge
```

_Note: The GNOME Extension is packaged separately as `gnome-shell-extension-zbridge`._

### B. NixOS / Home Manager

1. **Add to `flake.nix` inputs:**

```nix
inputs.zbridge.url = "github:doromiert/zbridge";
```

2. **Configure Home Manager:**

```nix
{ inputs, ... }: {
  imports = [ inputs.zbridge.homeManagerModules.default ];
  services.zbridge.enable = true;
  services.zbridge.installExtension = true;
}
```

---

## Setup & Usage

### Step 1: Initial Pairing (USB)

1.  Connect your Android phone via USB.
2.  Ensure **USB Debugging** is active in Developer Options.
3.  Deploy the Python receiver to Termux:

    ```bash
    zb-installer <PHONE_IP>
    ```

### Step 2: Configuration (Wireless)

Once installed, you can disconnect the USB cable. Use the GNOME extension or the CLI:

```bash
# Set Phone IP
zb-config -i 192.168.1.45

# Toggle Features
zb-config -m on      # Use Phone as Mic (Monitor)
zb-config -d on      # Stream PC Audio to Phone (Desktop)
zb-config -c front   # Use Front Camera
zb-config -o flip90  # Set Camera Orientation

# Manage Daemon
zb-config -t         # Toggle Daemon (Start/Stop)
zb-config -k         # Kill all streams and stop service
```

### Step 3: Verify Audio

Open `pavucontrol` or GNOME Sound Settings:

- **Input:** Select **"ZeroBridge_Microphone"**.
- **Output:** Select **"ZeroBridge_To_Phone"** to hear PC audio on your device.

---

## Troubleshooting

1. **Audio Loops / Feedback:** The daemon includes anti-feedback rules. Ensure `zb-daemon` is active: `systemctl --user status zbridge`.
2. **Phone Not Connecting:** - Ensure UDP ports **5000-5002** are open in your firewall.
   - Run `zb-debug-phone <IP>` to see remote logs.
3. **GNOME Extension:** Ensure you have installed `v4l2loopback-dkms` if you plan to use the camera as a virtual webcam.

---

## License

MIT

```

```
