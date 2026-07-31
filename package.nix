{ lib, stdenv, makeWrapper, ffmpeg, coreutils, gnugrep, gnused,
  libnotify, systemd, pythonEnv, runtimeLibs }:

# Packages the `magcut` command. No KDE service menu is shipped on purpose: two .desktop files
# sharing one X-KDE-Submenu get merged by KDE into a single menu with duplicated entries, and the
# submenu icon then comes from whichever file wins. The menu belongs to the consuming config,
# next to the other tools of the same toolbox.
#
# pythonEnv carries faster-whisper, runtimeLibs the CUDA libraries it loads at runtime — both
# come from flake.nix. On the same nixpkgs these are the very store paths MagType already pulls
# in, so the transcription half costs practically no extra disk.

let
  runtimeDeps = [
    pythonEnv   # the engine (stdlib) + faster-whisper for --fillers
    ffmpeg      # silencedetect, rendering
    libnotify   # notify-send when a render finishes
    systemd     # systemd-inhibit: keep the machine awake through a long render
    coreutils   # mktemp, readlink, dirname, head
    gnugrep     # parse silencedetect output / project resource
    gnused      # extract the resource path
  ];
in
stdenv.mkDerivation {
  pname = "magcut";
  version = "2.0.0";
  src = ./.;

  nativeBuildInputs = [ makeWrapper ];

  installPhase = ''
    mkdir -p $out/bin $out/share/magcut
    cp -r kdenlive magcut $out/share/magcut/
    chmod +x $out/share/magcut/kdenlive/cut-silences.sh

    makeWrapper ${pythonEnv}/bin/python3 $out/bin/magcut \
      --add-flags "$out/share/magcut/magcut/cli.py" \
      --prefix PATH : ${lib.makeBinPath runtimeDeps} \
      --prefix PYTHONPATH : "$out/share/magcut" \
      --prefix LD_LIBRARY_PATH : "${lib.makeLibraryPath runtimeLibs}:/run/opengl-driver/lib"
  '';

  meta = {
    description = "Transcript-driven cutting of silence and hesitation sounds";
    homepage = "https://github.com/OleksandrCEO/magic-cut";
    platforms = lib.platforms.linux;
    mainProgram = "magcut";
  };
}
