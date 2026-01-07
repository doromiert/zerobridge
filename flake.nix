{
  description = "ZeroBridge: Android-Linux Audio/Video Bridge";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
  };

  outputs =
    { self, nixpkgs }:
    let
      supportedSystems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = nixpkgs.lib.genAttrs supportedSystems;
      pkgsFor = system: nixpkgs.legacyPackages.${system};
    in
    {
      packages = forAllSystems (
        system:
        let
          pkgs = pkgsFor system;
        in
        {
          core = pkgs.callPackage ./nix/backend.nix {
            inherit (pkgs.gst_all_1)
              gstreamer
              gst-plugins-base
              gst-plugins-good
              gst-plugins-bad
              gst-plugins-ugly
              ;
          };

          extension = pkgs.callPackage ./nix/extension.nix { };

          default = self.packages.${system}.core;
        }
      );

      homeManagerModules.default = import ./nix/hm-module.nix self;
    };
}
