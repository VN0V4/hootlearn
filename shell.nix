# NixOS: `nix-shell` gives you Python with tkinter, and a .venv with the dependencies.
{ pkgs ? import <nixpkgs> { } }:
pkgs.mkShell {
  packages = [ (pkgs.python3.withPackages (ps: [ ps.tkinter ])) pkgs.git ];
  shellHook = ''
    if [ ! -d .venv ]; then
      python3 -m venv --system-site-packages .venv
      .venv/bin/pip install -q -r requirements.txt
    fi
    source .venv/bin/activate
  '';
}
