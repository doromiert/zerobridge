{
  lib,
  stdenv,
  makeWrapper,
  android-tools,
  scrcpy,
  pipewire,
  gstreamer,
  gst-plugins-base,
  gst-plugins-good,
  gst-plugins-bad,
  gst-plugins-ugly,
  pulseaudio,
  procps,
  systemd,
  util-linux,
  bash,
  coreutils,
  gnugrep,
  which,
  gawk,
  iproute2,
  toybox,
  jq,
  uutils-findutils,
  libnotify,
  python3, # Add Python3
}:

stdenv.mkDerivation {
  pname = "zbridge-core";
  version = "1.0.0";

  src = ../src/scripts;

  nativeBuildInputs = [ makeWrapper ];

  installPhase = ''
    mkdir -p $out/bin
    cp zb-config.sh $out/bin/zb-config

    # Install Python Daemon as 'zb-daemon'
    cp zb_daemon.py $out/bin/zb-daemon

    cp zb-installer.sh $out/bin/zb-installer
    cp zb-debug-phone.sh $out/bin/zb-debug-phone

    chmod +x $out/bin/*
  '';

  fixupPhase = ''
    # Wrapped path now includes python3
    for script in zb-config zb-daemon zb-installer zb-debug-phone; do
      wrapProgram $out/bin/$script \
        --prefix PATH : ${
          lib.makeBinPath [
            python3
            bash
            coreutils
            gnugrep
            iproute2
            uutils-findutils
            gawk
            jq
            libnotify
            which
            android-tools
            scrcpy
            pipewire
            gstreamer
            pulseaudio
            procps
            systemd
            toybox
            util-linux
          ]
        } \
        --prefix GST_PLUGIN_SYSTEM_PATH_1_0 : "${
          lib.makeSearchPathOutput "lib" "lib/gstreamer-1.0" [
            gstreamer
            gst-plugins-base
            gst-plugins-good
            gst-plugins-bad
            gst-plugins-ugly
          ]
        }"
    done
  '';

  meta = with lib; {
    description = "Backend scripts for ZeroBridge (Python Version)";
    license = licenses.mit;
    platforms = platforms.linux;
  };
}
