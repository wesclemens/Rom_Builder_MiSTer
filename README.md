# Arcade ROM Builder MiSTer
This is a simple GUI/CLI that downloads the rom definitions from [MiSTer-devel](https://github.com/MiSTer-devel) GitHub and allows you to create the ROM file with out having to checkout or download the `build_rom.ini`, batch or shell script and any extra files that maybe needed.

![Main Window](/main.png)

## Usage
1. Place script anywhere and run `python Rom_Builder_MiSTer.py`.
2. Click on `Refresh Definitions` to download rom definitions from GitHub.
3. Click on `Select ROM to convert` and select ROM zip file and save location.

## TODO
- This is an Alpha release and interface may change as need.
- Add IPS to support Arkanoid.
- Package release in exe for Windows and app for MacOS
- Add CLI options to take `build_rom.ini` for local builds
- Add RBF embeding.
