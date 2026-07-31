{ lib, stdenv, makeWrapper, writeTextDir, symlinkJoin, ffmpeg, python3, coreutils, gnugrep, gnused }:

# Packages the kdenlive add-on as the `magcut` command plus a KDE service menu
# (right-click a .kdenlive project → "Вирізати тишу").
#
# The transcript pipeline (magcut/transcribe.py, magcut/regions.py) is NOT wrapped here:
# transcription needs faster-whisper + CUDA, which lives in the devShell (`nix develop`).
# A unified CLI covering both is the next step.

let
  runtimeDeps = [
    ffmpeg      # silencedetect
    python3     # the engine — stdlib only
    coreutils   # mktemp, readlink, dirname, head
    gnugrep     # parse silencedetect output / project resource
    gnused      # extract the resource path
  ];

  magcut = stdenv.mkDerivation {
    pname = "magcut";
    version = "1.1.0";
    src = ./.;

    nativeBuildInputs = [ makeWrapper ];

    installPhase = ''
      mkdir -p $out/bin $out/share/magcut
      cp -r kdenlive magcut $out/share/magcut/
      chmod +x $out/share/magcut/kdenlive/cut-silences.sh

      makeWrapper $out/share/magcut/kdenlive/cut-silences.sh $out/bin/magcut \
        --prefix PATH : ${lib.makeBinPath runtimeDeps}
    '';

    meta = {
      description = "Transcript-driven cutting of silence and hesitation sounds";
      homepage = "https://github.com/OleksandrCEO/magic-cut";
      platforms = lib.platforms.linux;
    };
  };

  serviceMenu = writeTextDir "share/kio/servicemenus/magic-cut.desktop" ''
    [Desktop Entry]
    Type=Service
    MimeType=application/x-kdenlive;
    Actions=cut-silence;
    X-KDE-Submenu=MagWer Video Toolbox
    Icon=audio-volume-muted

    [Desktop Action cut-silence]
    Name=Вирізати тишу
    Icon=audio-volume-muted
    Exec=konsole --hold -e magcut %f
  '';
in
symlinkJoin {
  name = "magcut";
  paths = [ magcut serviceMenu ];
}
