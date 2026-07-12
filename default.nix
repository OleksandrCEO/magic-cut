{ pkgs ? import <nixpkgs> { } }:

# Packages the silence cutter as the `magcut` command and installs a KDE
# service menu so you can right-click a .kdenlive project → "Вирізати тишу".
# The command wraps cut-silences.sh (single source of truth) with its runtime
# deps on PATH; no nix-shell needed at call time.

let
  runtimeDeps = with pkgs; [
    ffmpeg      # silencedetect
    python3     # silence_cut.py engine (stdlib only)
    coreutils   # mktemp, readlink, dirname, head
    gnugrep     # parse silencedetect output / project resource
    gnused      # extract the resource path
  ];

  # The wrapped command.
  magcut = pkgs.stdenv.mkDerivation {
    pname = "magcut";
    version = "1.0.0";
    src = ./.;

    nativeBuildInputs = [ pkgs.makeWrapper ];

    installPhase = ''
      mkdir -p $out/bin $out/share/magcut
      cp cut-silences.sh silence_cut.py $out/share/magcut/
      chmod +x $out/share/magcut/cut-silences.sh

      makeWrapper $out/share/magcut/cut-silences.sh $out/bin/magcut \
        --prefix PATH : ${pkgs.lib.makeBinPath runtimeDeps}
    '';
  };

  # KDE right-click entry for kdenlive project files.
  serviceMenu = pkgs.writeTextDir "share/kio/servicemenus/magic-cut.desktop" ''
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
# One package that provides both the `magcut` binary and the service menu.
pkgs.symlinkJoin {
  name = "magcut";
  paths = [ magcut serviceMenu ];
}
