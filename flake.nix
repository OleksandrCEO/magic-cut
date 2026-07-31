{
  description = "magic-cut — transcript-driven cutting of silence and hesitation sounds";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-26.05";
  };

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs {
        inherit system;
        config.allowUnfree = true;
        overlays = [
          # faster-whisper runs on CTranslate2 — build it with CUDA, same as the MagType env.
          (final: prev: {
            ctranslate2 = prev.ctranslate2.override {
              withCUDA = true;
              withCuDNN = true;
            };
          })
        ];
      };

      # CUDA runtime libraries needed at load time by CTranslate2.
      runtimeLibs = with pkgs; [
        stdenv.cc.cc.lib
        zlib
        cudaPackages.cudatoolkit
        cudaPackages.cudnn
        cudaPackages.libcublas
      ];

      # Transcription needs faster-whisper; everything downstream is stdlib only.
      pythonEnv = pkgs.python3.withPackages (ps: with ps; [ faster-whisper ]);
    in
    {
      packages.${system}.default = pkgs.callPackage ./package.nix { inherit pythonEnv runtimeLibs; };

      devShells.${system}.default = pkgs.mkShell {
        buildInputs = [ pythonEnv pkgs.ffmpeg ];

        LD_LIBRARY_PATH = "${pkgs.lib.makeLibraryPath runtimeLibs}:/run/opengl-driver/lib";

        shellHook = ''
          echo "✂️  magic-cut dev environment (faster-whisper + CUDA)"
        '';
      };

      nixosModules.default = { config, lib, pkgs, ... }: {
        options.services.magcut.enable = lib.mkEnableOption "magic-cut video tools";
        config = lib.mkIf config.services.magcut.enable {
          environment.systemPackages = [ self.packages.${pkgs.stdenv.hostPlatform.system}.default ];
        };
      };
    };
}
