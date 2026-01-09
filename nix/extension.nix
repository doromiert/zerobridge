{
  lib,
  stdenv,
  glib,
  gettext,
  zip,
  jq,
}:

stdenv.mkDerivation {
  pname = "zbridge-extension";
  version = "2"; # Updated to match new metadata

  src = ../src/extension;

  nativeBuildInputs = [
    glib
    gettext
    zip
    jq
  ];

  buildPhase = ''
    # Validate UUID matches metadata
    uuid=$(jq -r '.uuid' metadata.json)
    if [ "$uuid" = "null" ]; then
      echo "Error: UUID not found in metadata.json"
      exit 1
    fi

  '';

  installPhase = ''
    uuid=$(jq -r '.uuid' metadata.json)
    installDir="$out/share/gnome-shell/extensions/$uuid"

    mkdir -p "$installDir"

    # This copies everything, including the 'schemas/gschemas.compiled' file generated above
    cp -r * "$installDir"
  '';

  meta = with lib; {
    description = "GNOME Shell extension for ZeroBridge";
    license = licenses.mit;
    platforms = platforms.linux;
  };
}
