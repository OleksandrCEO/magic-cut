{
  description = "magic-cut / fillers — detect voiced filler sounds (faster-whisper + CUDA). Standalone.";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-26.05";
  };

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs {
        inherit system;
        config.allowUnfree = true;
        # faster-whisper runs on CTranslate2 — build it with CUDA, like the MagType env.
        overlays = [
          (final: prev: {
            ctranslate2 = prev.ctranslate2.override {
              withCUDA = true;
              withCuDNN = true;
            };
          })
        ];
      };

      # CUDA runtime libraries needed at load time.
      runtimeLibs = with pkgs; [
        stdenv.cc.cc.lib
        zlib
        cudaPackages.cudatoolkit
        cudaPackages.cudnn
        cudaPackages.libcublas
      ];

      pythonEnv = pkgs.python3.withPackages (ps: with ps; [
        faster-whisper
      ]);
    in
    {
      devShells.${system}.default = pkgs.mkShell {
        buildInputs = [ pythonEnv pkgs.ffmpeg ];

        LD_LIBRARY_PATH = "${pkgs.lib.makeLibraryPath runtimeLibs}:/run/opengl-driver/lib";

        shellHook = ''
          echo "🔊 magic-cut · filler detector (faster-whisper + CUDA)"
        '';
      };
    };
}
