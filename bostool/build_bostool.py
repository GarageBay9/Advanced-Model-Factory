import re
parts=[]
# Set before any OpenGL import: on Linux PyOpenGL must use the X11/GLX platform, or the 3D view fails with
# "EGLPlatform object has no attribute 'GLX'". An environment setting the user already made is respected.
parts.append('''# ---- platform setup (runs before any OpenGL import) ----
import os as _amf_os, sys as _amf_sys
if _amf_sys.platform.startswith('linux'): _amf_os.environ.setdefault('PYOPENGL_PLATFORM','x11')''')
for f in ['ops.py','cob.py','pp.py','decomp.py','compile.py','hpi.py','gaf.py','threedo.py','pieces.py','anim.py','bos_export.py','theme.py','viewer3do.py','help_text.py','bostool_gui.py']:
    keep=[]
    for l in open(f).read().split('\n'):
        if re.match(r"^if __name__\s*==\s*['\"]__main__['\"]",l): break
        if re.match(r'^\s*(from (ops|cob|pp|decomp|compile) import|import (ops|cob|pp|decomp|compile)\b)',l): continue
        keep.append(l)
    parts.append(f'# ---- from {f} ----\n'+'\n'.join(keep))
cli=open('bostool_cli.py').read()
out='\n\n'.join(parts)+'\n\n'+cli
open('bostool.py','w').write(out)
open('amf.py','w').write(out)     # the program's own name for the file users run
print('built bostool.py and amf.py')
