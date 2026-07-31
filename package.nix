{ lib, stdenv, makeWrapper, writeTextDir, symlinkJoin, ffmpeg, coreutils, gnugrep, gnused,
  libnotify, pythonEnv, runtimeLibs }:

# Packages the `magcut` command plus KDE service menus (right-click a video or a .kdenlive
# project → "MagWer Video Toolbox").
#
# pythonEnv carries faster-whisper, runtimeLibs the CUDA libraries it loads at runtime — both
# come from flake.nix. On the same nixpkgs these are the very store paths MagType already pulls
# in, so the transcription half costs practically no extra disk.

let
  runtimeDeps = [
    pythonEnv   # the engine (stdlib) + faster-whisper for --fillers
    ffmpeg      # silencedetect, rendering
    libnotify   # notify-send when a render finishes
    coreutils   # mktemp, readlink, dirname, head
    gnugrep     # parse silencedetect output / project resource
    gnused      # extract the resource path
  ];

  magcut = stdenv.mkDerivation {
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
  };

  serviceMenu = writeTextDir "share/kio/servicemenus/magic-cut.desktop" ''
    [Desktop Entry]
    Type=Service
    MimeType=video/mp4;video/x-matroska;video/quicktime;video/webm;application/x-kdenlive;
    Actions=cut-silence;cut-fillers;
    X-KDE-Submenu=MagWer Video Toolbox
    Icon=edit-cut

    [Desktop Action cut-silence]
    Name=Вирізати тишу
    Icon=audio-volume-muted
    Exec=konsole --hold -e magcut %f

    [Desktop Action cut-fillers]
    Name=Вирізати тишу та екання
    Icon=edit-cut
    Exec=konsole --hold -e magcut %f --fillers
  '';
in
symlinkJoin {
  name = "magcut";
  paths = [ magcut serviceMenu ];
}
