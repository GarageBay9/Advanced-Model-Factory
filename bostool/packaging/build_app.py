# Builds Advanced Model Factory as one self-contained app for the operating system it runs on:
#   Linux    -> dist/AMF            (single executable)
#   Windows  -> dist/AMF.exe        (single executable)
#   macOS    -> dist/AMF.app        (application bundle)
# PyInstaller cannot cross-compile, so run this on each platform you ship to. The bundle includes Python, Tk, PyOpenGL
# and pyopengltk, so the people who run it need nothing installed.
#
# Usage (from the bostool folder):  python3 packaging/build_app.py
# Needs: pip install -r requirements.txt pyinstaller   (run this with the python that has those installed)
import os, sys, subprocess, shutil
HERE=os.path.dirname(os.path.abspath(__file__))
SRC=os.path.dirname(HERE)
OUT=os.path.join(HERE,'dist')

def need(modname):
    try: __import__(modname)
    except ImportError: raise SystemExit(f'missing {modname}: pip install -r requirements.txt pyinstaller')

def main():
    for m in ('OpenGL','pyopengltk','tkinter','PyInstaller'): need(m)
    subprocess.run([sys.executable,os.path.join(SRC,'build_bostool.py')],cwd=SRC,check=True)   # fresh amf.py
    cmd=[sys.executable,'-m','PyInstaller','--noconfirm','--onefile','--name','AMF',
         '--collect-submodules','OpenGL','--hidden-import','pyopengltk',
         '--distpath',OUT,'--workpath',os.path.join(HERE,'build'),'--specpath',os.path.join(HERE,'build')]
    if sys.platform=='darwin': cmd.append('--windowed')          # produces AMF.app on macOS
    cmd.append(os.path.join(SRC,'amf.py'))
    subprocess.run(cmd,cwd=SRC,check=True)
    print('built for',sys.platform,'into',OUT)

if __name__=='__main__':
    main()
