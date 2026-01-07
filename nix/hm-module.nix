flake:
{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.services.zbridge;
  # Use the packages defined in the flake
  zbridgeCore = flake.packages.${pkgs.system}.core;
  zbridgeExt = flake.packages.${pkgs.system}.extension;
in
{
  options.services.zbridge = {
    enable = lib.mkEnableOption "ZeroBridge Service";

    installExtension = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Whether to install the GNOME extension automatically.";
    };
  };

  config = lib.mkIf cfg.enable {
    # 1. Install the CLI tools
    home.packages = [ zbridgeCore ] ++ (lib.optional cfg.installExtension zbridgeExt);

    # 2. Define the Systemd User Service
    systemd.user.services.zbridge = {
      Unit = {
        Description = "ZeroBridge Background Daemon";
        After = [
          "pipewire.service"
          "network.target"
        ];
      };

      Service = {
        ExecStart = "${zbridgeCore}/bin/zb-daemon";
        Restart = "always";
        RestartSec = "5";
        # Ensure the script sees the wrapper path
        Environment = "PATH=${zbridgeCore}/bin:/usr/bin:/bin";
      };

      Install = {
        WantedBy = [ "default.target" ];
      };
    };
  };
}
