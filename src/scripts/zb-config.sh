#!/usr/bin/env bash
# ==============================================================================
# ZBridge Controller (zb-config.sh)
# Role: Client / State Writer with Blocking Confirmation
# ==============================================================================

CONFIG_DIR="$HOME/.config/zbridge"
CONFIG_FILE="$CONFIG_DIR/state.conf"
CONFIG_PID_FILE="/tmp/zbridge_config_pid"
SERVICE_NAME="zbridge"

mkdir -p "$CONFIG_DIR"
[[ ! -f "$CONFIG_FILE" ]] && touch "$CONFIG_FILE"

# --- Confirmation Mechanism ---
CONFIRMED=false
trap 'CONFIRMED=true' SIGUSR2

# --- Helpers ---

is_valid_ip() {
    local ip=$1
    local stat=1
    if [[ $ip =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
        OIFS=$IFS
        IFS='.'
        ip=($ip)
        IFS=$OIFS
        [[ ${ip[0]} -le 255 && ${ip[1]} -le 255 && \
           ${ip[2]} -le 255 && ${ip[3]} -le 255 ]]
        stat=$?
    fi
    return $stat
}

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
    echo "$$" > "$CONFIG_PID_FILE"
    systemctl --user kill -s USR1 "$SERVICE_NAME"
    
    local timeout=50 
    while [[ "$CONFIRMED" == "false" && $timeout -gt 0 ]]; do
        sleep 0.1
        ((timeout--))
    done

    rm -f "$CONFIG_PID_FILE"
    if [[ "$CONFIRMED" == "true" ]]; then
        echo "Done."
    else
        echo -e "\n[!] Timed out waiting for Daemon response."
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
    
    local cam=$(get_config CAM_FACING)
    echo "   Cam: ${cam:-back}"
    
    if ! grep -qi "CAM_FACING=\"none\"" "$CONFIG_FILE"; then
        local orient=$(get_config CAM_ORIENT)
        
        # Resolve default for display if empty
        if [[ -z "$orient" ]]; then
            local df=$(get_config DEF_ORIENT_FRONT)
            local db=$(get_config DEF_ORIENT_BACK)
            # Fallback to hardcoded if not set
            [[ -z "$df" ]] && df="flip90"
            [[ -z "$db" ]] && db="flip270"

            if [[ "$cam" == "front" ]]; then
                orient="$df (Default)"
            else
                orient="$db (Default)"
            fi
        fi
        
        echo "   Camera orientation: $orient"
    fi
    
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

while getopts "i:c:m:d:o:F:B:tkh" opt; do
    case $opt in
        i) 
            if is_valid_ip "$OPTARG"; then
                set_config "PHONE_IP" "$OPTARG"; send_signal_and_wait
            else
                echo "[!] Error: Invalid IP."; exit 1
            fi
            ;;
        c) 
            set_config "CAM_FACING" "$OPTARG"
            # Clear manual orientation so new default applies
            set_config "CAM_ORIENT" ""
            send_signal_and_wait 
            ;;
        o) 
            if grep -qi "CAM_FACING=\"none\"" "$CONFIG_FILE"; then
                echo "[!] Camera is disabled."
            else
                # UPDATE: Added flip0 to regex to support universal flip switch
                if [[ "$OPTARG" =~ ^(0|flip0|90|flip90|180|flip180|270|flip270)$ ]]; then 
                    set_config "CAM_ORIENT" "$OPTARG"; send_signal_and_wait
                else 
                    echo "[!] Invalid orientation."
                fi
            fi
        ;;
        F) # Set Default Front Orientation
            if [[ "$OPTARG" =~ ^(0|flip0|90|flip90|180|flip180|270|flip270)$ ]]; then 
                set_config "DEF_ORIENT_FRONT" "$OPTARG"
                echo "[*] Default Front Orientation set to $OPTARG"
                send_signal_and_wait
            else
                 echo "[!] Invalid orientation."
            fi
            ;;
        B) # Set Default Back Orientation
            if [[ "$OPTARG" =~ ^(0|flip0|90|flip90|180|flip180|270|flip270)$ ]]; then 
                set_config "DEF_ORIENT_BACK" "$OPTARG"
                echo "[*] Default Back Orientation set to $OPTARG"
                send_signal_and_wait
            else
                 echo "[!] Invalid orientation."
            fi
            ;;
        m) toggle_setting "MONITOR" "$OPTARG" ;;
        d) toggle_setting "DESKTOP" "$OPTARG" ;;
        t)
            if systemctl --user is-active --quiet "$SERVICE_NAME"; then
                systemctl --user stop "$SERVICE_NAME"
            else
                systemctl --user start "$SERVICE_NAME"
            fi
            ;;
        k)
            systemctl --user stop "$SERVICE_NAME"
            pkill -f "scrcpy"
            pkill -f "pw-loopback.*ZBridge"
            ;;
        h) echo "Usage: zb-config [-i IP] [-c facing] [-o orient] [-F def_front] [-B def_back] [-m/-d on/off] [-t] [-k]" ;;
    esac
done