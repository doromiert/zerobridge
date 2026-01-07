{
  lib,
  stdenv,
  glib,
  gettext,
  zip,
  jq,
}:

stdenv.mkDerivation rec {
  pname = "zbridge-extension";
  version = "1.0.0";

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

    # Compile schemas if they exist (future proofing)
    if [ -d schemas ]; then
      glib-compile-schemas schemas/
    fi
  '';

  installPhase = ''
    uuid=$(jq -r '.uuid' metadata.json)
    installDir="$out/share/gnome-shell/extensions/$uuid"

    mkdir -p "$installDir"
    cp -r * "$installDir"
  '';

  meta = with lib; {
    description = "GNOME Shell extension for ZeroBridge";
    license = licenses.mit;
    platforms = platforms.linux;
  };
}
