#!/usr/bin/env bash
# ==============================================================================
# ZBridge Controller (zb-config.sh)
# Role: Client / State Writer with Blocking Confirmation
# ==============================================================================

CONFIG_DIR="$HOME/.config/zbridge"
CONFIG_FILE="$CONFIG_DIR/state.conf"
SERVICE_NAME="zbridge"

mkdir -p "$CONFIG_DIR"
[[ ! -f "$CONFIG_FILE" ]] && touch "$CONFIG_FILE"

# --- Confirmation Mechanism ---
CONFIRMED=false
trap 'CONFIRMED=true' SIGUSR2

# --- Helpers ---

get_config() {
    local key="$1"
    grep "^$key=" "$CONFIG_FILE" | cut -d'=' -f2 | tr -d '"'
}

set_config() {
    local key="$1"
    local value="$2"
    if grep -q "^$key=" "$CONFIG_FILE"; then
        sed -i "s/^$key=.*/$key=\"$value\"/" "$CONFIG_FILE"
    else
        echo "$key=\"$value\"" >> "$CONFIG_FILE"
    fi
}

send_signal_and_wait() {
    if ! systemctl --user is-active --quiet "$SERVICE_NAME"; then
        echo "[!] Daemon is NOT running. Start it with -t or systemctl."
        return 1
    fi

    echo -n "[*] Updating Daemon... "
    systemctl --user kill -s USR1 "$SERVICE_NAME"
    
    # Block for confirmation (Up to 60s)
    local timeout=60
    while [[ "$CONFIRMED" == "false" && $timeout -gt 0 ]]; do
        sleep 1
        ((timeout--))
    done

    if [[ "$CONFIRMED" == "true" ]]; then
        echo "Done."
    else
        echo "Timed out waiting for Daemon response."
    fi
}

toggle_setting() {
    local key="$1"
    local input_arg="$2"
    local current=$(get_config "$key")
    [[ -z "$current" ]] && current="off"

    local target=""
    if [[ "$input_arg" == "toggle" ]]; then
        [[ "$current" == "on" ]] && target="off" || target="on"
    else
        target="$input_arg"
    fi

    if [[ "$current" == "$target" ]]; then
        echo "[*] $key is already $target."
    else
        echo "[*] Setting $key to $target"
        set_config "$key" "$target"
        send_signal_and_wait
    fi
}

show_status() {
    echo ":: ZeroBridge State ::"
    echo "   IP: $(get_config PHONE_IP)"
    echo "   Cam: $(get_config CAM_FACING)"
    
    # [FIX] Robust detection for nodes created by pw-loopback
    # pw-loopback creates 'input.Name' and 'output.Name'. We check for the output node.
    local mon_conf=$(get_config MONITOR)
    local mon_act=$(pw-dump Node | jq -r '.[] | select(.info.props["node.name"] | strings | contains("ZBridge_Monitor")) | .id' | head -n 1)
    echo -n "   Monitor: [${mon_conf:-off}] "
    [[ -n "$mon_act" && "$mon_act" != "null" ]] && echo -e "\033[32m[ACTIVE]\033[0m" || echo -e "\033[31m[INACTIVE]\033[0m"

    local dsk_conf=$(get_config DESKTOP)
    local dsk_act=$(pw-dump Node | jq -r '.[] | select(.info.props["node.name"] | strings | contains("ZBridge_Desktop")) | .id' | head -n 1)
    echo -n "   Desktop: [${dsk_conf:-off}] "
    [[ -n "$dsk_act" && "$dsk_act" != "null" ]] && echo -e "\033[32m[ACTIVE]\033[0m" || echo -e "\033[31m[INACTIVE]\033[0m"

    local active=$(systemctl --user is-active "$SERVICE_NAME")
    echo "   Daemon: $active"
}

# --- Main ---

if [[ $# -eq 0 ]]; then show_status; exit 0; fi

while getopts "i:c:m:d:tkh" opt; do
    case $opt in
        i) set_config "PHONE_IP" "$OPTARG"; send_signal_and_wait ;;
        c) set_config "CAM_FACING" "$OPTARG"; send_signal_and_wait ;;
        m) toggle_setting "MONITOR" "$OPTARG" ;;
        d) toggle_setting "DESKTOP" "$OPTARG" ;;
        t)
            if systemctl --user is-active --quiet "$SERVICE_NAME"; then
                echo "[*] Stopping Service..."
                systemctl --user stop "$SERVICE_NAME"
            else
                echo "[*] Starting Service..."
                systemctl --user start "$SERVICE_NAME"
            fi
            ;;
        k)
            echo "[!] KILL SWITCH."
            systemctl --user stop "$SERVICE_NAME"
            pkill -f "zb-daemon.sh"
            pkill -f "scrcpy"
            pkill -f "pw-loopback.*ZBridge"
            ;;
        h) echo "Usage: zb-config [-i IP] [-c front/back/none] [-m on/off/toggle] [-d on/off/toggle] [-t] [-k]" ;;
    esac
done