# Advanced Model Factory (AMF)

AMF is a desktop tool for Total Annihilation unit files. In one window it edits:

- **BOS scripts** (`.bos`) and compiled **COB scripts** (`.cob`): a code editor, decompile and compile, and a test-run
  panel that plays a script's movement against the model.
- **3DO models** (`.3do`, and `.3dox` projects that keep a model with its animation): a 3D viewport with a part tree,
  move and rotate tools, pivots, faces and textures, animation keys, and an export to BOS.

The in-app help (Help menu) is the full how-to and the hotkey list. This file covers running, building and the layout
of the source.

## Running

Start the editor with no arguments, or with a file to open:

```
python3 amf.py
python3 amf.py path/to/model.3do
```

The 3D viewport uses OpenGL. On Linux AMF sets `PYOPENGL_PLATFORM=x11` itself, so no environment setup is needed.

Command-line subcommands are for scripting and are not needed for the editor:

```
python3 amf.py decompile unit.cob -o unit.bos
python3 amf.py compile unit.bos -o unit.cob [-I folder] [--linear-scale 65536|163840]
python3 amf.py check unit.cob ...          # decompile, recompile, compare bytes
```

## Requirements

- Python 3.12 with Tk (`tkinter`).
- For the 3D viewport: `pip install -r requirements.txt` (PyOpenGL 3.1.10 and pyopengltk 0.0.4).

## Packaged app

`packaging/build_app.py` builds one self-contained app with PyInstaller: `dist/AMF.exe` on Windows and `dist/AMF` on Linux.
PyInstaller does not cross-compile, so build on the system you ship to. The Windows app is built by the GitHub workflow
in `packaging/build-apps.yml`; see the build kit's instructions. Install `pyinstaller` with the requirements first.

```
python3 packaging/build_app.py
```

**macOS is not supported at present.** pyopengltk, the package that embeds OpenGL in the window, has no macOS version
(its macOS frame is not implemented, and version 0.0.4 cannot be imported there). The build script still has macOS
branches, so a future macOS port would start from them.

## Building the single-file source

The source is split into modules that are concatenated into one file, `amf.py` (and `bostool.py`, the same program under
the old name):

```
python3 build_bostool.py
```

The modules are joined in this order: `ops.py`, `cob.py`, `pp.py`, `decomp.py`, `compile.py`, `hpi.py`, `gaf.py`,
`threedo.py`, `pieces.py`, `anim.py`, `bos_export.py`, `theme.py`, `viewer3do.py`, `help_text.py`, `bostool_gui.py`,
then `bostool_cli.py`. The modules share one namespace, so a name defined twice silently replaces the earlier one.

| Module | What it holds |
| --- | --- |
| `ops.py`, `cob.py`, `pp.py`, `decomp.py`, `compile.py` | BOS and COB: reading, decompiling, compiling |
| `hpi.py`, `gaf.py` | Archives and textures |
| `threedo.py` | 3DO reading, writing, the part tree, pending rotations, mesh export (OBJ, DXF, LWO, 3DO) |
| `pieces.py` | Part editing outside the window: create, duplicate, mirror, mesh import, base plate |
| `anim.py`, `bos_export.py` | Animation sequences and export to BOS scripts; the test-run playback |
| `viewer3do.py` | The 3D viewport: tools, undo, the Piece, pivot, base plate and transform palette actions |
| `help_text.py` | The help text, the hotkey table and the About box |
| `bostool_gui.py` | The window, menus, dialogs, the transform palette and base plate panel |
| `bostool_cli.py` | The entry point and the subcommands |

## Tests

The GUI tests need a display. On Linux run them under `xvfb-run` with a Python that has Tk:

```
for f in test_*.py; do xvfb-run -a /usr/bin/python3.12 "$f" || echo "FAIL $f"; done
```

Each test file prints `N of M passed` and exits non-zero on failure. The GUI tests load the sample model `../armap_data/ARMAP.3do`, relative to this folder.

## Working on the piece and base plate tools

- Piece edits (`pieces.py`) are plain functions on a model and raise `ThreeDOError` with a reason. The viewer calls them
  through one wrapper that shows the reason, refuses in Animate or during a pivot move, and records one undo step.
- A base plate is the root part's face designated by its selection field (`Piece3D.flag`, header word 0x0C). The rules
  for a usable plate are in `pieces.py` (`base_plate_problem`), with the research they come from cited there.
- The transform palette applies values through the same wrapper. Spinner drags keep the start of the drag and record the
  whole drag as one step when released.

## Notes

- The Rot toolbar label can be clipped on narrow windows.
- Undo restores the selection of the step it returns to. A part removed by an edit is not selected after undo unless it
  was selected before the edit.
- Retail's ground-plate winding and placement are not settled by the research. A base plate keeps the corner order it
  has, and a new plate sits at height zero in the base part's frame.
