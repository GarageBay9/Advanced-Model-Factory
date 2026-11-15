# ---- 3DO viewport (OpenGL, embedded in Tk through pyopengltk) ----
# Needs: pip install PyOpenGL pyopengltk   (fixed-function GL; depth buffer; GL does the lighting).
# One GL context draws every pane: each pane is a glViewport/scissor rectangle with its own camera.
# Camera controls follow 3ds Max viewports: middle-drag pans, wheel zooms, alt+middle-drag orbits the
# model (or the selected part), left-click picks a face (click empty space to deselect), alt+W toggles
# the active pane between the quad layout and a single pane.
# Colours: palette index 0-255 (TApalette.dat). Textured quads take their texture from the texture sources; other faces are grey.
# Three-point faces are magenta when that highlight is on (see 3DO notes).
try:
    import tkinter as _vtk
    from tkinter import ttk as _vttk
except ImportError:
    _vtk=_vttk=None
try:
    from pyopengltk import OpenGLFrame as _OGLBase
    from OpenGL import GL as _GL
    import ctypes as _ctypes
except Exception as _gl_err:      # keep the rest of the program usable without GL
    _OGLBase=None; _GL=None; _GL_ERR=str(_gl_err)

import math as _math
import json as _json
import os as _os
import contextlib as _contextlib

VIEW_NAMES=['3D','Top','Bottom','Front','Back','Left','Right']
ORTHO_DIRS={                       # camera looks along d, with screen-up u (right-handed)
    'Front':((0.0,0.0,1.0),(0.0,1.0,0.0)),
    'Back':((0.0,0.0,-1.0),(0.0,1.0,0.0)),
    'Left':((1.0,0.0,0.0),(0.0,1.0,0.0)),
    'Right':((-1.0,0.0,0.0),(0.0,1.0,0.0)),
    'Top':((0.0,-1.0,0.0),(0.0,0.0,1.0)),
    'Bottom':((0.0,1.0,0.0),(0.0,0.0,1.0)),
}
RENDER_MODES=('wireframe','shaded','textured')
PANE_DEFAULT_VIEWS=['Top','Front','Left','3D']       # top-left, top-right, bottom-left, bottom-right
PERSP_TAN=_math.tan(_math.radians(20.0))             # 40 degree vertical field of view
ORBIT_MIN=0.25; ORBIT_MAX=3.0                         # orbit distance limits, in units of the model radius R
VIEW_KEYS=(('z','frame_selection'),('Z','undo_view'))  # frame selection; undo view change (shift+z)
WHEEL_GROUP_S=0.6                                     # wheel steps closer than this share one view-undo step
VIEW_NEUTRAL=(0.59,0.59,0.59)
VIEW_TRI3=(1.0,0.25,1.0)
VIEW_BG=(0.17,0.17,0.18,1.0)
VIEW_LIGHT=(0.35,0.8,0.5,0.0)
OUTLINE_DEFAULT='#b4f5b4'           # pale green
GRID_CELL_DEFAULT=4.0               # TA units per grid cell
GRID_MAJOR_EVERY=5                  # every 5th line is drawn heavier
# Backdrops. 'dark' is the shaded dark background; 'grid' is a light backdrop with a ground grid.
# Contrast ratios (WCAG) for the grid lines and wire colours are checked in test_3do_panes.py:
# minor grid 1.30:1, major grid 1.99:1, wireframe 12:1 on the light backdrop; wireframe 9.9:1 on dark.
BACKDROPS={
    'dark':dict(bg=(0.17,0.17,0.18),wire=(0.85,0.85,0.85),border=(1.0,1.0,1.0,0.35)),
    'grid':dict(bg=(0.875,0.886,0.902),wire=(0.13,0.14,0.16),border=(0.0,0.0,0.0,0.45),
                minor=(0.761,0.784,0.812),major=(0.604,0.635,0.675)),
}
BACKDROP_LABELS={'dark':'Dark (shaded)','grid':'Light grid'}

# ---- manipulator gizmos (W move, R rotate) and undo ----
VIEW_AXES=(((1.0,0.0,0.0),(0.0,1.0,0.0),(0.0,0.0,1.0)),       # X: ring basis u,w with u x w = axis
      ((0.0,1.0,0.0),(0.0,0.0,1.0),(1.0,0.0,0.0)),       # Y
      ((0.0,0.0,1.0),(1.0,0.0,0.0),(0.0,1.0,0.0)))       # Z
AXIS_COLOURS=((0.95,0.25,0.25),(0.25,0.85,0.30),(0.30,0.50,1.00))
GIZMO_ACTIVE=(1.0,0.9,0.2)
GIZMO_SIZE=0.35                    # arm length and ring radius, in model radii
GIZMO_HIT_PX=8.0
RING_N=72
# Q W E R map to select, move, rotate, scale in standard 3D modelling navigation. Scale is not built yet, so R is unbound.
TOOL_KEYS=(('q','select'),('w','move'),('e','rotate'))
RETAIL_MISS_COLOUR=209     # 03 §2.4.1 item 4: a texture name that resolves nowhere is rewritten to flat 0xd1
FACE_KEYS=(('c','spin_face_edge'),('v','flip_face_normal'),('b','assign_selected_texture'),       # quad edge spin, normal flip (method names)
           ('F7','rotate_texture_back'),('F8','rotate_texture_fwd'))  # texture 90 degree turns, as in 3DOBuilder
MAX_UNDO=200

def _pt_seg_hit(p,a,b):
    """(distance from p to segment ab, fraction along ab of the closest point)."""
    ax,ay=a; bx,by=b; px,py=p
    dx,dy=bx-ax,by-ay; l2=dx*dx+dy*dy
    t=0.0 if l2<=1e-12 else max(0.0,min(1.0,((px-ax)*dx+(py-ay)*dy)/l2))
    return _math.hypot(px-(ax+t*dx),py-(ay+t*dy)), t

def _pt_seg_dist(p,a,b):
    return _pt_seg_hit(p,a,b)[0]

def _ring_point(O,L,u,w,theta):
    c=_math.cos(theta)*L; s=_math.sin(theta)*L
    return (O[0]+c*u[0]+s*w[0],O[1]+c*u[1]+s*w[1],O[2]+c*u[2]+s*w[2])

# ---- small linear algebra (row-major 4x4 lists) ----
def _ident():
    return [[1.0 if i==j else 0.0 for j in range(4)] for i in range(4)]
def _mm(A,B):
    return [[sum(A[i][k]*B[k][j] for k in range(4)) for j in range(4)] for i in range(4)]
def _tr(x,y,z):
    M=_ident(); M[0][3]=x; M[1][3]=y; M[2][3]=z; return M
def _rx(a):
    c,s=_math.cos(a),_math.sin(a); M=_ident(); M[1][1]=c; M[1][2]=-s; M[2][1]=s; M[2][2]=c; return M
def _ry(a):
    c,s=_math.cos(a),_math.sin(a); M=_ident(); M[0][0]=c; M[0][2]=s; M[2][0]=-s; M[2][2]=c; return M
def _frustum(l,r,b,t,n,f):
    M=[[0.0]*4 for _ in range(4)]
    M[0][0]=2*n/(r-l); M[0][2]=(r+l)/(r-l)
    M[1][1]=2*n/(t-b); M[1][2]=(t+b)/(t-b)
    M[2][2]=-(f+n)/(f-n); M[2][3]=-2*f*n/(f-n); M[3][2]=-1.0
    return M
def _ortho(l,r,b,t,n,f):
    M=_ident()
    M[0][0]=2/(r-l); M[0][3]=-(r+l)/(r-l)
    M[1][1]=2/(t-b); M[1][3]=-(t+b)/(t-b)
    M[2][2]=-2/(f-n); M[2][3]=-(f+n)/(f-n)
    return M
def _sub(a,b): return (a[0]-b[0],a[1]-b[1],a[2]-b[2])
def _add(a,b): return (a[0]+b[0],a[1]+b[1],a[2]+b[2])
def _smul(a,k): return (a[0]*k,a[1]*k,a[2]*k)
def _vdot(a,b): return a[0]*b[0]+a[1]*b[1]+a[2]*b[2]
def _cross(a,b): return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
def _unit(a):
    l=_math.sqrt(_vdot(a,a)) or 1.0
    return (a[0]/l,a[1]/l,a[2]/l)
def _lookat(eye,target,up):
    f=_unit(_sub(target,eye)); s=_unit(_cross(f,up)); u=_cross(s,f)
    M=_ident()
    M[0][0],M[0][1],M[0][2]=s; M[1][0],M[1][1],M[1][2]=u; M[2][0],M[2][1],M[2][2]=(-f[0],-f[1],-f[2])
    M[0][3]=-_vdot(s,eye); M[1][3]=-_vdot(u,eye); M[2][3]=_vdot(f,eye)
    return M
def _inv(M):
    A=[list(M[i])+[1.0 if i==j else 0.0 for j in range(4)] for i in range(4)]
    for c in range(4):
        p=max(range(c,4),key=lambda r: abs(A[r][c]))
        if abs(A[p][c])<1e-12: raise ValueError('singular matrix')
        A[c],A[p]=A[p],A[c]
        pv=A[c][c]; A[c]=[v/pv for v in A[c]]
        for r in range(4):
            if r!=c and A[r][c]!=0.0:
                f=A[r][c]; A[r]=[A[r][k]-f*A[c][k] for k in range(8)]
    return [row[4:] for row in A]
def _gl_flat(M):
    """Column-major flat list, as glLoadMatrixf expects."""
    return [M[r][c] for c in range(4) for r in range(4)]

def _hex_to_rgb(h):
    h=h.lstrip('#')
    return tuple(int(h[i:i+2],16)/255.0 for i in (0,2,4))

def _ray_tri(o,d,a,b,c):
    """Moller-Trumbore: distance along the ray to triangle abc, or None."""
    e1=_sub(b,a); e2=_sub(c,a); p=_cross(d,e2); det=_vdot(e1,p)
    if abs(det)<1e-12: return None
    inv=1.0/det; tv=_sub(o,a)
    u=_vdot(tv,p)*inv
    if u<0.0 or u>1.0: return None
    q=_cross(tv,e1); v=_vdot(d,q)*inv
    if v<0.0 or u+v>1.0: return None
    t=_vdot(e2,q)*inv
    return t if t>1e-9 else None

def build_mesh(model,keep,palette,hl3,missing=()):
    """Fan-triangulate the kept faces. Returns (nverts, pos, nrm, col, picks, faces) where
    picks is [(piece, poly_index, (a,b,c))] and faces maps (id(piece), poly_index) -> world polygon vertices."""
    pos=[];nrm=[];col=[];picks=[];faces={}
    for piece,pi,vs,color,tex in model.flat_faces(keep):
        nidx=len(vs)
        faces[(id(piece),pi)]=vs
        if nidx==3 and hl3: rgb=VIEW_TRI3
        elif palette and not tex and 0<=color<=255: rgb=tuple(v/255.0 for v in palette[color])
        elif palette and tex and tex.lower() in missing: rgb=tuple(v/255.0 for v in palette[RETAIL_MISS_COLOUR])
        else: rgb=VIEW_NEUTRAL
        for k in range(1,nidx-1):
            a,b,c=vs[0],vs[k],vs[k+1]
            n=_unit(_cross(_sub(b,a),_sub(c,a)))
            picks.append((piece,pi,(a,b,c)))
            for v in (a,b,c):
                pos.extend(v); nrm.extend(n); col.extend(rgb)
    return len(picks)*3,pos,nrm,col,picks,faces

def _corner_uv(w,h):
    """Texel-centre UVs for the four quad corners (retail: 0->(0,0), 1->(1,0), 2->(1,1), 3->(0,1) in texel terms)."""
    l=0.5/w; r=(w-0.5)/w; t=0.5/h; b=(h-0.5)/h
    return [(l,t),(r,t),(r,b),(l,b)]

def texture_batches(model,keep,lib,palette):
    """Textured quads grouped by texture name. Retail maps textures on quads only, so three-point faces
    that name a texture are drawn plain and counted; a quad whose texture no source holds is drawn plain and
    its name is recorded. Returns (batches, stats): batches maps lower name -> dict(name, w, h, rows, pos, uv, n)."""
    batches={}
    stats={'quads':0,'tri_tex':0,'missing':set(),'no_palette':palette is None}
    if palette is None: 
        for _,_,vs,_,tex in model.flat_faces(keep):
            if tex and len(vs)==3: stats['tri_tex']+=1
        return batches,stats
    for piece,pi,vs,color,tex in model.flat_faces(keep):
        if not tex: continue
        if len(vs)==3: stats['tri_tex']+=1; continue
        if len(vs)!=4: continue
        info=lib.texture(tex) if lib is not None else None
        if info is None: stats['missing'].add(tex); continue
        w,h,rows=info
        if w<=0 or h<=0: stats['missing'].add(tex); continue
        key=tex.lower()
        b=batches.setdefault(key,{'name':tex,'w':w,'h':h,'rows':rows,'pos':[],'uv':[],'n':0})
        uv=_corner_uv(w,h)
        for k in (0,1,2,0,2,3):
            b['pos'].extend(vs[k]); b['uv'].extend(uv[k]); b['n']+=1
        stats['quads']+=1
    return batches,stats

def count_tri3(model):
    """Faces with exactly three indexes, split by texture (textured vs untextured)."""
    textured=untextured=0
    for p,_ in model.pieces():
        for poly in p.polys:
            if len(poly.idx)==3:
                if poly.tex: textured+=1
                else: untextured+=1
    return textured,untextured

if _OGLBase is not None:
    class _GLView(_OGLBase):
        """Drawing surface only. Input is handled by the owning Viewport3DO (bound from outside).
        initgl runs on every resize, so it only sets state."""
        def initgl(self):
            GL=_GL
            GL.glClearColor(*VIEW_BG)
            GL.glEnable(GL.GL_DEPTH_TEST); GL.glDepthFunc(GL.GL_LEQUAL)
            GL.glEnable(GL.GL_LIGHTING); GL.glEnable(GL.GL_LIGHT0)
            GL.glEnable(GL.GL_COLOR_MATERIAL); GL.glColorMaterial(GL.GL_FRONT_AND_BACK,GL.GL_AMBIENT_AND_DIFFUSE)
            GL.glEnable(GL.GL_NORMALIZE)
            GL.glDisable(GL.GL_CULL_FACE)
            GL.glLightModeli(GL.GL_LIGHT_MODEL_TWO_SIDE,GL.GL_TRUE)
            GL.glLightModelfv(GL.GL_LIGHT_MODEL_AMBIENT,(0.3,0.3,0.3,1.0))

        def redraw(self):
            self.owner._draw_all(self)

class Viewport3DO:
    """Toolbar, piece list, the GL surface with its pane overlays, and the info line. Create under any tk container."""
    project_path=None          # the .3dox project the open model is tied to (None until one is known)
    tex_selected=None          # texture name chosen in the palette or browser; B applies it to the selected face
    _listeners=()              # callbacks run after the info line refreshes (texture palette, and the like)
    def __init__(self,parent,cfg):
        self.cfg=cfg; self.model=None; self.pieces=[]; self.path=None
        self.dirty=False; self.untitled_id=None
        self._mesh=None; self._picks=[]; self._faces={}; self._palette_cache=(None,None)
        self._texlib=None; self._texlib_key=None; self._gltex={}; self._gltex_stale=[]
        self._tex_batches={}; self._tex_stats={'quads':0,'tri_tex':0,'missing':set(),'no_palette':True}; self._tex_palette=None
        self._view=None; self._drag=None; self._combos=[]
        self._gz=None; self._hist=[]; self._hi=-1
        self.seqs=[{'name':'Sequence 1','anim':default_anim()}]; self.seq_i=0; self.anim=self.seqs[0]['anim']
        self.anim_output=None
        self.driver='base'; self.rest=None; self.frame_t=0
        self.autokey=False; self._anim_struct=None; self.refusal=None
        self.R=1.0; self.center=(0.0,0.0,0.0); self._lo=(0.0,0.0,0.0)
        self.panes=[self._new_pane(v) for v in PANE_DEFAULT_VIEWS]
        self.active=0; self.layout='quad'
        self.sel_part=None; self.sel_face=None      # piece object; (piece, poly_index)
        self.hl3_var=_vtk.BooleanVar(value=True)
        self._edge_base=_vttk.Style().lookup('TFrame','background') or '#d9d9d9'
        self.frame=_vtk.Frame(parent,highlightthickness=3,highlightbackground=self._edge_base,highlightcolor=self._edge_base)
        top=_vttk.Frame(self.frame); top.pack(side='top',fill='x',padx=4,pady=2)
        _vttk.Button(top,text='Reset view',command=self.reset_active_view).pack(side='left')
        _vttk.Button(top,text='Quad / single (Alt+W)',command=self.toggle_maximize).pack(side='left',padx=4)
        self.tool_var=_vtk.StringVar(value='select'); self.pivot_var=_vtk.BooleanVar(value=False)
        self._pivot_session=None; self._match_wait=False; self.highlight_pivot=_vtk.BooleanVar(value=False)
        for name,label in (('select','Select (Q)'),('move','Move (W)'),('rotate','Rotate (E)')):
            _vttk.Radiobutton(top,text=label,value=name,variable=self.tool_var,command=self._tool_changed).pack(side='left',padx=2)
        _vttk.Checkbutton(top,text='Pivot only',variable=self.pivot_var,command=self.redraw).pack(side='left',padx=4)
        self.title=_vttk.Label(top,text='No 3DO model loaded',anchor='w'); self.title.pack(side='left',padx=8,fill='x',expand=True)
        body=_vttk.Frame(self.frame); body.pack(side='top',fill='both',expand=True)
        side=_vttk.Frame(body); side.pack(side='left',fill='y')
        _vttk.Label(side,text='Parts  ([x] = shown)').pack(anchor='w',padx=4)
        self.plist=_vtk.Listbox(side,selectmode='browse',exportselection=False,width=22,height=10)
        self.plist.pack(side='left',fill='y',padx=4,pady=2)
        self.plist.bind('<Button-1>',self._on_list_click)
        self.plist.bind('<ButtonRelease-1>',self._drag_release)
        self._drag_src=None
        self.visible=set()
        if _OGLBase is not None:
            self._surface=_vtk.Frame(body)
            self._surface.pack(side='left',fill='both',expand=True)
            self._view=_GLView(self._surface,width=380,height=300)
            self._view.owner=self
            self._view.place(x=0,y=0,relwidth=1,relheight=1)
            for i in range(4):
                cb=_vttk.Combobox(self._surface,values=VIEW_NAMES,state='readonly',width=8)
                cb.bind('<<ComboboxSelected>>',lambda e,i=i: self._combo_chosen(i))
                self._combos.append(cb)
            self._bind_input(self._view)
            self._surface.bind('<Configure>',lambda e: (self._place_combos(),self.redraw()))
        else:
            _vttk.Label(body,text='The 3DO viewport needs OpenGL support (PyOpenGL and pyopengltk).\n\n'
                'Install into a virtual environment (system pip often refuses installs):\n'
                '  python3 -m venv ~/amf-venv\n'
                '  ~/amf-venv/bin/pip install -r requirements.txt\n'
                'then start Advanced Model Factory (AMF) with that environment\'s python.\n\n'
                'On Linux the viewport also needs an X11 display (DISPLAY set).\n\n'
                '(' + _GL_ERR + ')',justify='left',anchor='nw').pack(side='left',fill='both',expand=True,padx=8,pady=8)
        self._pivot_bar=_vttk.Frame(self.frame)          # shown while a pivot move is open
        _vttk.Label(self._pivot_bar,text='Move pivot: drag an axis arrow. Accept keeps the new pivot; Cancel puts it back.').pack(side='left',padx=6)
        _vttk.Button(self._pivot_bar,text='Accept this location',command=self.pivot_accept).pack(side='left',padx=4)
        _vttk.Button(self._pivot_bar,text='Cancel',command=self.pivot_cancel).pack(side='left',padx=4)
        self.info=_vttk.Label(self.frame,text='Open a .3do file (File > Open 3DO model…) to preview it here.',anchor='w')
        self.info.pack(side='bottom',fill='x',padx=4,pady=2)
        self._build_timeline()

    # ---- animation: driver, playhead, keys and the timeline toolbar ----
    # The tree shows the rest pose (base) or rest·pose(frame) (animate). Files, undo records and structure checks always
    # use the rest pose, so an animated frame never leaks into the .3do or the project.
    @_contextlib.contextmanager
    def _base_state(self):
        """Runs the block with the tree at rest, then puts the live pose back."""
        if self.driver!='anim' or self.rest is None or self.model is None:
            yield; return
        live=snapshot_pose(self.roots())
        restore_pose(self.roots(),self.rest)
        try: yield
        finally: restore_pose(self.roots(),live)

    def _structure_sig(self):
        with self._base_state(): return tree_signature(self.roots())

    def _refuse_structure(self):
        """While animating the rest state is fixed. A structural or rest edit is undone and reported. True if undone."""
        if self.driver!='anim' or self.model is None or self._anim_struct is None: return False
        if self._structure_sig()==self._anim_struct: return False
        if self._hi>=0: self._restore(self._hist[self._hi])
        self.refusal="Turn Animate off to change the model's structure or its base pose."
        self._refresh_info()
        return True

    def set_animate(self,on):
        """Turns the animation driver on (the tree shows the clip at the playhead) or off (the rest pose comes back exactly)."""
        if self.model is None: raise ThreeDOError('no 3DO model is open')
        if bool(on)==(self.driver=='anim'): return
        if on:
            self.rest=snapshot_pose(self.roots())
            self._anim_struct=tree_signature(self.roots())     # the tree is at rest right now
            self.driver='anim'
            self.refusal=None
            self._apply_time()
        else:
            restore_pose(self.roots(),self.rest)
            self.rest=None; self._anim_struct=None; self.driver='base'; self.autokey=False; self.autokey_var.set(False)
            self._resync_view()
        self.anim_var.set(self.driver=='anim')
        self._refresh_info()

    def span(self):
        return span(self.anim['timeline'])

    def set_frame(self,t):
        """Moves the playhead (clamped to the span, which may run through negative frames) and shows the clip's pose
        there when animating."""
        s,e=self.span()
        self.frame_t=int(max(s,min(e,int(round(t)))))
        self._apply_time()
        self._refresh_info()

    def _apply_time(self):
        if self.driver!='anim' or self.rest is None or self.model is None: return
        t=wrap_time(self.frame_t,self.anim['timeline'])
        apply_pose(self.roots(),self.rest,evaluate(self.anim,t))
        self._resync_view()

    def set_timeline(self,length=None,loop=None,start=None):
        """Sets the span: start (any whole frame, negative allowed) and length (frames after start)."""
        tl=self.anim['timeline']
        if start is not None: tl['start']=int(start)
        if length is not None:
            if int(length)<1: raise ThreeDOError('timeline length must be at least 1 frame')
            tl['length']=int(length)
        if loop is not None:
            if loop not in LOOPS: raise ThreeDOError(f'unknown loop mode {loop!r}')
            tl['loop']=loop
        s,e=self.span(); self.frame_t=int(max(s,min(e,self.frame_t)))
        self.mark_dirty(); self._commit(); self._apply_time(); self._refresh_info()

    # ---- animation sequences: several named clips in one model; one is worked on at a time ----
    def _seq_json(self):
        return [{'name':q['name'],'timeline':dict(q['anim']['timeline']),'tracks':anim_to_json(q['anim'])['tracks']} for q in self.seqs]

    def _seq_kwargs(self):
        return dict(sequences=self._seq_json(),active=self.seq_i,output=self.anim_output)

    def seq_names(self):
        return [q['name'] for q in self.seqs]

    def _check_name(self,name,skip=None):
        nm=(name or '').strip()
        if not nm: raise ThreeDOError('a sequence needs a name')
        if len(nm)>60: raise ThreeDOError('a sequence name can be at most 60 characters')
        for i,q in enumerate(self.seqs):
            if i!=skip and q['name'].lower()==nm.lower(): raise ThreeDOError(f'a sequence named {q["name"]!r} already exists')
        return nm

    def _select(self,i):
        self.seq_i=i; self.anim=self.seqs[i]['anim']
        s,e=self.span(); self.frame_t=int(max(s,min(e,self.frame_t)))

    def seq_select(self,i):
        if not 0<=i<len(self.seqs): raise ThreeDOError('no such sequence')
        if i==self.seq_i: return
        if self.driver=='anim': self.set_animate(False)      # the rest pose comes back before another sequence is shown
        self._select(i); self._apply_time(); self._sync_timeline(); self._refresh_info()

    def seq_new(self,name):
        nm=self._check_name(name)
        if self.driver=='anim': self.set_animate(False)
        self.seqs.append({'name':nm,'anim':default_anim()})
        self._select(len(self.seqs)-1)
        self.mark_dirty(); self._commit(); self._apply_time(); self._sync_timeline(); self._refresh_info()

    def seq_rename(self,i,name):
        nm=self._check_name(name,skip=i)
        self.seqs[i]['name']=nm
        self.mark_dirty(); self._commit(); self._sync_timeline(); self._refresh_info()

    def seq_delete(self,i):
        """Removes a sequence for good. Undo history for the model is cleared, so nothing can bring it back."""
        if len(self.seqs)<=1: raise ThreeDOError('a model keeps at least one sequence: add another before deleting this one')
        if self.driver=='anim': self.set_animate(False)
        gone=self.seqs.pop(i)
        if self.seq_i==i: new=min(i,len(self.seqs)-1)
        elif self.seq_i>i: new=self.seq_i-1
        else: new=self.seq_i
        self._select(new)
        self._reset_history(); self.mark_dirty(); self._apply_time(); self._sync_timeline(); self._refresh_info()
        return gone['name']

    def seq_save_file(self,path):
        """Writes the selected sequence to a .3dan file of its own."""
        doc=seq_file_doc(self.seqs[self.seq_i]['name'],self.anim)
        try:
            with open(path,'w',encoding='utf-8') as f: _json.dump(doc,f,indent=1,sort_keys=True)
        except OSError as e: raise ThreeDOError(f'could not write {_os.path.basename(path)}: {e}')

    def seq_load_file(self,path):
        """Adds a .3dan sequence to the model and selects it. A name already in use gets a number after it."""
        try:
            with open(path,'r',encoding='utf-8') as f: doc=_json.load(f)
        except (OSError,ValueError) as e: raise ThreeDOError(f'{_os.path.basename(path)} could not be read: {e}')
        try: name,anim=parse_seq_file(doc)
        except ValueError as e: raise ThreeDOError(f'{_os.path.basename(path)}: {e}')
        base=name[:50]; nm=base; k=2
        taken={q['name'].lower() for q in self.seqs}
        while nm.lower() in taken: nm=f'{base} ({k})'; k+=1
        if self.driver=='anim': self.set_animate(False)
        self.seqs.append({'name':nm,'anim':anim})
        self._select(len(self.seqs)-1)
        self.mark_dirty(); self._commit(); self._apply_time(); self._sync_timeline(); self._refresh_info()
        return nm

    def set_output(self,path):
        self.anim_output=path or None
        self.mark_dirty(); self._commit(); self._refresh_info()

    def clip_bos_text(self,loop_policy='report',ramps=True):
        """The selected sequence as BOS text, built in memory: (text, report, read-back data, sequence name). Writes nothing."""
        if self.model is None: raise ThreeDOError('no model is open')
        name=self.seqs[self.seq_i]['name']
        with self._base_state():
            text,rep,rin=bos_export_clip(self.anim,self.roots(),source=_os.path.basename(self.path or ''),
                                         clip_name=name,loop_policy=loop_policy,ramps=ramps)
        return text,rep,rin,name

    def export_bos(self,path=None,loop_policy='report',ramps=True):
        """Writes the selected sequence as BOS text to the output file, reads it back to check it, and returns a summary."""
        out=path or self.anim_output
        if not out: raise ThreeDOError('no animation output file is set (Animation > Animation output file)')
        if self.model is None: raise ThreeDOError('no model is open')
        text,rep,rin,name=self.clip_bos_text(loop_policy,ramps)
        err=bos_verify(text,rin)
        rot=[e for p in err.values() for a,(e,_) in p.get('rot',{}).items()]
        pos=[e for p in err.values() for a,(e,_) in p.get('pos',{}).items()]
        fid=[f for p in rep['fidelity'].values() for k in p.values() for (f,_) in k.values()]
        with open(out,'w',encoding='utf-8') as fh: fh.write(text)
        summary=(f'exported {name} to {_os.path.basename(out)}: seam mismatches {len(rep["seams"])}; '
                 f'read-back error {max(rot,default=0.0):.2f} deg, {max(pos,default=0.0):.3f} units; '
                 f'ramps {"on" if ramps else "off"} (fidelity to keys up to {max(fid,default=0.0):.2f})')
        self.refusal=summary; self._refresh_info()
        return summary

    def _set_key(self,pk,kind,t,v,interp='smooth'):
        tr=self.anim['tracks'].setdefault(pk,{'rot':[],'pos':[]})
        old=[k for k in tr[kind] if k['t']==t]
        if old: interp=old[0]['i']
        v=q_norm(v) if kind=='rot' else tuple(float(c) for c in v)
        keys=[k for k in tr[kind] if k['t']!=t]
        keys.append({'t':int(t),'v':tuple(v),'i':interp}); keys.sort(key=lambda k:k['t'])
        tr[kind]=keys

    def key_part(self,piece):
        """Records the part's displayed pose as keys at the playhead, relative to rest. One undo step."""
        self.key_parts([piece])

    def key_parts(self,pieces):
        """Keys every given part at the playhead, relative to rest. One undo step for the whole group."""
        if self.driver!='anim': raise ThreeDOError('turn Animate on first')
        pieces=[p for p in pieces if p is not None]
        if not pieces: raise ThreeDOError('select a part first')
        todo=[]
        for piece in pieces:
            pk=piece_key(self._piece_path(piece))
            r=self.rest.get(pk)
            if r is None: raise ThreeDOError('the selected part is not in the rest pose')
            todo.append((pk,)+tuple(key_from_display(r[0],r[1],piece.pend,piece.offset)))
        for pk,Q,d in todo:
            self._set_key(pk,'rot',self.frame_t,Q)
            self._set_key(pk,'pos',self.frame_t,d)
        self.mark_dirty(); self._commit(); self._apply_time(); self._refresh_info()

    def add_key_clicked(self):
        """The toolbar's Add Key: animates if needed, then keys the selected parts at the playhead."""
        if self.driver!='anim': self.set_animate(True)
        self.key_parts(self.sel_parts or [self.sel_part])

    def set_key_values(self,pk,t,rot_deg=None,pos=None):
        """Sets the value of an existing key at frame t: rot_deg is (x,y,z) degrees, pos is (x,y,z) offsets. A key is
        never created here: add one with Add Key first."""
        tr=self.anim['tracks'].get(pk)
        if rot_deg is not None:
            hit=[k for k in (tr['rot'] if tr else []) if k['t']==t]
            if not hit: raise ThreeDOError(f'no rotation key at frame {t}; add a key first')
            hit[0]['v']=euler_to_q(tuple(float(c) for c in rot_deg))
        if pos is not None:
            hit=[k for k in (tr['pos'] if tr else []) if k['t']==t]
            if not hit: raise ThreeDOError(f'no position key at frame {t}; add a key first')
            hit[0]['v']=tuple(float(c) for c in pos)
        self.mark_dirty(); self._commit(); self._apply_time(); self._refresh_info()

    def move_key(self,pk,kind,t_old,t_new):
        """Moves a key in time (value and interpolation kept). Rotation values are not edited here."""
        tr=self.anim['tracks'].get(pk)
        if not tr: return
        hit=[k for k in tr[kind] if k['t']==t_old]
        if not hit: return
        k=hit[0]
        if t_new!=t_old and any(o['t']==t_new for o in tr[kind]): raise ThreeDOError('a key already sits on that frame')
        tr[kind]=sorted([o for o in tr[kind] if o is not k]+[{'t':int(t_new),'v':k['v'],'i':k['i']}],key=lambda o:o['t'])
        self.mark_dirty(); self._commit(); self._apply_time(); self._refresh_info()

    def delete_key(self,pk,kind,t):
        tr=self.anim['tracks'].get(pk)
        if not tr: return
        tr[kind]=[k for k in tr[kind] if k['t']!=t]
        self.mark_dirty(); self._commit(); self._apply_time(); self._refresh_info()

    def set_key_interp(self,pk,kind,t,interp):
        if interp not in INTERP: raise ThreeDOError(f'unknown interpolation {interp!r}')
        for k in self.anim['tracks'].get(pk,{}).get(kind,[]):
            if k['t']==t: k['i']=interp
        self.mark_dirty(); self._commit(); self._apply_time(); self._refresh_info()

    def selected_key_frames(self):
        """Key frames of the selected part, or of every part when none is selected."""
        pth=self._piece_path(self.sel_part) if self.sel_part is not None else None
        pk=piece_key(pth) if pth is not None else None
        out=set()
        for k,tr in self.anim['tracks'].items():
            if pk is not None and k!=pk: continue
            for kind in ('rot','pos'):
                out.update(x['t'] for x in tr[kind])
        return sorted(out)

    # ---- timeline toolbar (bottom of the 3D view, toggled from the Animation menu) ----
    def _build_timeline(self):
        # Row 1: the key timeline, which takes all the width the controls leave, then the frame arrows, Key and Auto Key.
        # Row 2: Animate, the frame readout, the span (start, length, end), the loop mode, and at the far right the
        # sequence dropdown with its small New / Rename / Delete.
        bar=_vttk.Frame(self.frame)
        self.tl_bar=bar
        self.anim_var=_vtk.BooleanVar(value=False); self.autokey_var=_vtk.BooleanVar(value=False)
        self.tl_visible=_vtk.BooleanVar(value=False)
        self.seq_var=_vtk.StringVar(value='')
        row=_vttk.Frame(bar); row.pack(fill='x')
        row2=_vttk.Frame(bar); row2.pack(fill='x',pady=(2,0))
        self.tl_canvas=_vtk.Canvas(row,height=44,width=40,bg='#2b2b2b',highlightthickness=0)
        self.tl_canvas.grid(row=0,column=0,sticky='ew',padx=(0,6))
        self.tl_canvas.bind('<Button-1>',self._tl_press); self.tl_canvas.bind('<B1-Motion>',self._tl_scrub)
        self.tl_canvas.bind('<Configure>',lambda e: self._draw_timeline())
        # Delete or BackSpace over the timeline removes the keys under the shuttle (the canvas takes focus on click)
        self.tl_canvas.bind('<Delete>',lambda e: self.delete_keys_clicked()); self.tl_canvas.bind('<BackSpace>',lambda e: self.delete_keys_clicked())
        row.columnconfigure(0,weight=1)            # the timeline takes all the width the other row-one controls leave
        _vttk.Button(row,text='◀',width=2,command=lambda: self.set_frame(self.frame_t-1)).grid(row=0,column=1)
        _vttk.Button(row,text='▶',width=2,command=lambda: self.set_frame(self.frame_t+1)).grid(row=0,column=2,padx=(1,6))
        _vttk.Button(row,text='Key',width=4,command=self._add_key_clicked).grid(row=0,column=3,padx=(0,4))
        _vtk.Checkbutton(row,text='Auto Key',variable=self.autokey_var,indicatoron=False,selectcolor='#c04040',command=self._autokey_clicked).grid(row=0,column=4,padx=(0,4))
        _vttk.Button(row,text='Del Key',width=7,command=self.delete_keys_clicked).grid(row=0,column=5)

        seqgrp=_vttk.Frame(row2); seqgrp.pack(side='right')  # packed first, so it keeps its place at the far right
        _vttk.Button(seqgrp,text='Delete',style='Small.TButton',command=self._seq_delete_clicked).pack(side='right',padx=(1,0))
        _vttk.Button(seqgrp,text='Rename',style='Small.TButton',command=self._seq_rename_clicked).pack(side='right',padx=1)
        _vttk.Button(seqgrp,text='New',style='Small.TButton',command=self._seq_new_clicked).pack(side='right',padx=1)
        self.seq_cb=_vttk.Combobox(seqgrp,textvariable=self.seq_var,state='readonly',width=8)
        self.seq_cb.pack(side='right',padx=(6,2)); self.seq_cb.bind('<<ComboboxSelected>>',lambda e: self._seq_clicked())
        _vtk.Checkbutton(row2,text='Animate',variable=self.anim_var,indicatoron=False,selectcolor='#c04040',command=self._animate_clicked).pack(side='left',padx=2)
        self.tl_frame_lbl=_vttk.Label(row2,text='0',width=3,anchor='e'); self.tl_frame_lbl.pack(side='left',padx=(8,0))
        _vttk.Label(row2,text='Start').pack(side='left',padx=(4,0))
        self.tl_start_var=_vtk.StringVar(value='0')
        sp0=_vttk.Spinbox(row2,from_=-100000,to=100000,width=5,textvariable=self.tl_start_var,command=self._span_changed)
        sp0.pack(side='left',padx=2); sp0.bind('<Return>',lambda e: self._span_changed())
        _vttk.Label(row2,text='Length').pack(side='left')
        self.tl_len_var=_vtk.StringVar(value='60')
        sp=_vttk.Spinbox(row2,from_=1,to=100000,width=4,textvariable=self.tl_len_var,command=self._length_changed)
        sp.pack(side='left',padx=2); sp.bind('<Return>',lambda e: self._length_changed())
        self.tl_end_lbl=_vttk.Label(row2,text='end 60',width=7,anchor='w'); self.tl_end_lbl.pack(side='left')
        self.tl_loop_var=_vtk.StringVar(value='loop')
        cb=_vttk.Combobox(row2,values=LOOPS,textvariable=self.tl_loop_var,state='readonly',width=5)
        cb.pack(side='left',padx=2); cb.bind('<<ComboboxSelected>>',lambda e: self._loop_changed())

        style=_vttk.Style(self.frame)
        style.configure('Small.TButton',font=('TkDefaultFont',7),padding=(2,0))

    def show_timeline(self,on):
        self.tl_visible.set(bool(on))
        if on:
            if not self.tl_bar.winfo_manager():
                self.tl_bar.pack(side='bottom',fill='x',padx=4,pady=2,before=self.info)
        else:
            self.tl_bar.pack_forget()
        self._sync_timeline()

    def _animate_clicked(self):
        try: self.set_animate(self.anim_var.get())
        except ThreeDOError as e: self.refusal=str(e); self.anim_var.set(self.driver=='anim'); self._refresh_info()

    def _autokey_clicked(self):
        on=self.autokey_var.get()
        if on and self.driver!='anim': self.set_animate(True)
        self.autokey=bool(on) and self.driver=='anim'
        self._edge_sync()
        self.autokey_var.set(self.autokey); self._refresh_info()

    def _add_key_clicked(self):
        try: self.add_key_clicked()
        except ThreeDOError as e: self.refusal=str(e); self._refresh_info()

    def _span_changed(self):
        try: self.set_timeline(start=int(self.tl_start_var.get()))
        except (ValueError,ThreeDOError) as e: self.refusal=str(e if isinstance(e,ThreeDOError) else 'the start must be a whole number of frames')
        self._sync_timeline(); self._refresh_info()

    def _length_changed(self):
        try: self.set_timeline(length=int(self.tl_len_var.get()))
        except (ValueError,ThreeDOError) as e: self.refusal=str(e if isinstance(e,ThreeDOError) else 'the length must be a whole number of frames')
        self._sync_timeline(); self._refresh_info()

    def _loop_changed(self):
        self.set_timeline(loop=self.tl_loop_var.get()); self._refresh_info()

    def _tl_scrub(self,e):
        W=max(self.tl_canvas.winfo_width(),40); L=self.anim['timeline']['length']; s,_=self.span()
        self.set_frame(s+(e.x-8)*L/float(W-16))

    def _tl_press(self,e):
        self.tl_canvas.focus_set()                 # so Delete / BackSpace reach the timeline
        self._tl_scrub(e)

    def delete_keys_at(self,frame):
        """Removes every rotation and position key at one frame. Scope: the selected parts, or every part when none is
        selected (the same rule the timeline's diamonds use). One undo step."""
        if self.driver!='anim': raise ThreeDOError('turn Animate on first')
        if self.model is None: raise ThreeDOError('no 3DO model is open')
        group=self.sel_parts
        pieces=[p for p in group if p is not None] or list(self.pieces)
        removed=0
        for piece in pieces:
            tr=self.anim['tracks'].get(piece_key(self._piece_path(piece)))
            if not tr: continue
            for kind in ('rot','pos'):
                before=len(tr[kind]); tr[kind]=[k for k in tr[kind] if k['t']!=frame]
                removed+=before-len(tr[kind])
        scope='the selected parts' if group else 'any part'
        if removed==0: raise ThreeDOError(f'no key at frame {frame} on {scope}')
        self.mark_dirty(); self._commit(); self._apply_time(); self._refresh_info()

    def delete_keys_clicked(self):
        """Del Key and the Delete / BackSpace keys: removes the keys under the shuttle. Clicking a diamond puts the shuttle on it."""
        try: self.delete_keys_at(self.frame_t)
        except ThreeDOError as e: self.refusal=str(e); self._refresh_info()

    def _seq_clicked(self):
        i=self.seq_cb.current()
        try: self.seq_select(i)
        except ThreeDOError as e: self.refusal=str(e)
        self._sync_timeline(); self._refresh_info()

    def _seq_new_clicked(self):
        from tkinter import simpledialog as _vsd
        name=_vsd.askstring('New sequence','Name for the new sequence:',parent=self.frame)
        if name is None: return
        try: self.seq_new(name)
        except ThreeDOError as e: self.refusal=str(e)
        self._sync_timeline(); self._refresh_info()

    def _seq_rename_clicked(self):
        from tkinter import simpledialog as _vsd
        i=self.seq_i
        name=_vsd.askstring('Rename sequence','New name:',initialvalue=self.seqs[i]['name'],parent=self.frame)
        if name is None: return
        try: self.seq_rename(i,name)
        except ThreeDOError as e: self.refusal=str(e)
        self._sync_timeline(); self._refresh_info()

    def _seq_delete_clicked(self):
        """Two steps: a warning that the sequence is gone for good, then the name typed out. Only then is it removed."""
        from tkinter import messagebox as _vmb, simpledialog as _vsd
        i=self.seq_i; name=self.seqs[i]['name']
        if len(self.seqs)<=1:
            self.refusal='a model keeps at least one sequence: add another before deleting this one'
            self._refresh_info(); return
        if not _vmb.askyesno('Delete sequence',
                f'Delete the sequence "{name}"?\n\n'
                'Its keys and timeline will be GONE once this is done. It cannot be undone, and the '
                'undo history for this model is cleared too.',parent=self.frame):
            return
        typed=_vsd.askstring('Delete sequence',f'To confirm, type the name exactly: {name}',parent=self.frame)
        if typed is None: return
        if typed.strip()!=name:
            self.refusal=f'the name did not match, so "{name}" was kept'
            self._refresh_info(); return
        try: gone=self.seq_delete(i); self.refusal=f'"{gone}" was deleted'
        except ThreeDOError as e: self.refusal=str(e)
        self._sync_timeline(); self._refresh_info()

    def _sync_timeline(self):
        if not hasattr(self,'tl_canvas'): return
        self.anim_var.set(self.driver=='anim'); self.autokey_var.set(self.autokey)
        self.tl_frame_lbl.configure(text=str(self.frame_t))
        tl=self.anim['timeline']; s,e=self.span()
        self.tl_start_var.set(str(s)); self.tl_len_var.set(str(tl['length'])); self.tl_loop_var.set(tl['loop'])
        self.tl_end_lbl.configure(text=f'end {e}')
        self.seq_cb.configure(values=self.seq_names()); self.seq_var.set(self.seqs[self.seq_i]['name'])
        self._draw_timeline()

    def _draw_timeline(self):
        if not hasattr(self,'tl_canvas'): return
        c=self.tl_canvas; c.delete('all')
        W=max(c.winfo_width(),40); H=max(c.winfo_height(),30); L=self.anim['timeline']['length']; s,e=self.span()
        x=lambda f: 8+(W-16)*(f-s)/float(L)
        c.create_line(8,H//2,W-8,H//2,fill='#888')
        step=max(1,L//8)
        for f in range(s,e+1,step):
            c.create_line(x(f),H//2-3,x(f),H//2+3,fill='#888')
            c.create_text(x(f),H-3,text=str(f),fill='#aaa',anchor='s',font=('TkDefaultFont',7))
        for f in self.selected_key_frames():
            cx=x(f); c.create_polygon(cx,H//2-7,cx+5,H//2,cx,H//2+7,cx-5,H//2,fill='#e0b040',outline='')
        c.create_line(x(self.frame_t),0,x(self.frame_t),H,fill='#ff5050',width=2)

    def refresh_theme_edge(self):
        """The resting edge colour follows the theme; called after a light/dark switch."""
        self._edge_base=_vttk.Style().lookup('TFrame','background') or self._edge_base
        self._edge_sync()

    def _edge_sync(self):
        """Auto Key shows as a red edge around the 3D view, the way Max frames its viewports."""
        fr=getattr(self,'frame',None)
        if fr is None: return
        col='#e02020' if self.autokey else self._edge_base
        try: fr.configure(highlightbackground=col,highlightcolor=col)
        except _vtk.TclError: pass

    # ---- panes and cameras ----
    def _new_pane(self,view):
        return dict(view=view,yaw=0.6,pitch=-0.35,dist=3.0,scale=1.3,target=(0.0,0.0,0.0),mode='shaded',bg='grid',vhist=[])

    def _fit_pane(self,pane):
        pane['target']=self.center; pane['dist']=3.0*self.R; pane['scale']=1.3*self.R
        pane['yaw']=0.6; pane['pitch']=-0.35

    def _pane_rects(self,W,H):
        """Pane rectangles in GL pixels (origin bottom-left) for the current layout, in pane order."""
        if self.layout=='single':
            return {self.active:(0,0,W,H)}
        w2=W//2; h2=H//2
        return {0:(0,H-h2,w2,h2),1:(w2,H-h2,W-w2,h2),2:(0,0,w2,H-h2),3:(w2,0,W-w2,H-h2)}

    def _pane_at(self,x,y):
        """Pane index under a Tk point (top-left origin), or None."""
        if self._view is None: return None
        W=max(1,self._view.winfo_width()); H=max(1,self._view.winfo_height())
        for i,(gx,gy,w,h) in self._pane_rects(W,H).items():
            tx=gx; ty=H-(gy+h)
            if tx<=x<tx+w and ty<=y<ty+h: return i
        return None

    def _pane_matrices(self,pane,aspect):
        R=self.R; tgt=pane['target']
        if pane['view']=='3D':
            dist=pane['dist']
            V=_mm(_tr(0,0,-dist),_mm(_rx(pane['pitch']),_mm(_ry(pane['yaw']),_tr(-tgt[0],-tgt[1],-tgt[2]))))
            n=max(dist-1.6*R,0.02*R); f=dist+2.0*R
            t=n*PERSP_TAN; r=t*aspect
            return _frustum(-r,r,-t,t,n,f),V
        d,u=ORTHO_DIRS[pane['view']]
        eye=_sub(tgt,_smul(d,3.0*R))
        V=_lookat(eye,tgt,u)
        hh=pane['scale']; hw=hh*aspect
        return _ortho(-hw,hw,-hh,hh,0.1*R,6.0*R),V

    def _half_height_at_target(self,pane):
        return pane['dist']*PERSP_TAN if pane['view']=='3D' else pane['scale']

    def _to_3d(self,pane):
        pane['view']='3D'; pane['dist']=3.0*self.R; pane['yaw']=0.6; pane['pitch']=-0.35

    def _set_pane_view(self,i,name):
        pane=self.panes[i]
        if name==pane['view']: return
        if name=='3D':
            self._to_3d(pane)
        else:
            if pane['view']=='3D': pane['scale']=1.3*self.R
            pane['view']=name
        self._place_combos(); self.redraw()

    # ---- model ----
    def load(self,path,read_from=None):
        """Returns None on success or an error message. read_from opens an autosave in place of path (recovery)."""
        try: self.open_path(path,recovery_from=read_from)
        except ProjectError as e: return str(e)
        return None

    def open_path(self,path,model_path=None,recovery_from=None):
        """Opens a .3do or a .3dox with its project. Raises ProjectError (its kind says why) and leaves the open model alone."""
        b=open_recovery(path,recovery_from) if recovery_from else open_bundle(path,model_path=model_path)
        self.untitled_id=None
        self._adopt(b.model,b.model_file,seqs=b.seqs,active=b.active,output=b.output)
        self.project_path=b.project_file
        self.sidecar_note=b.note or (f'{b.pending} pending rotation{"s" if b.pending!=1 else ""} restored from the project' if b.pending else None)
        self._refresh_info()
        return b

    def _adopt(self,m,path,anim=None,seqs=None,active=0,output=None):
        self.model=m; self.path=path; self.dirty=False; self.sidecar_note=None
        if seqs is None: seqs=[{'name':'Sequence 1','anim':anim if anim is not None else default_anim()}]
        self.seqs=seqs; self.seq_i=min(max(int(active),0),len(seqs)-1); self.anim=self.seqs[self.seq_i]['anim']
        self.anim_output=output
        self.driver='base'; self.rest=None; self.frame_t=0; self._anim_struct=None; self.refusal=None
        self.anim_var.set(False)
        self.pieces=[]; self.plist.delete(0,'end')
        for p,depth in m.pieces():
            self.pieces.append(p)
        self.visible={id(p) for p in self.pieces}
        self.sel_part=None; self.sel_face=None
        b=m.bounds()
        if b:
            self.center=tuple((b[0][i]+b[1][i])/2 for i in range(3)); self._lo=b[0]
            self.R=max(1e-3,_math.sqrt(sum(((b[1][i]-b[0][i])/2)**2 for i in range(3))))
        else:
            self.center=(0.0,0.0,0.0); self.R=1.0
        for pane in self.panes: self._fit_pane(pane)
        self._refresh_list()
        self._update_title()
        self._reset_history()
        self._rebuild(); self._refresh_info(); self._place_combos(); self.redraw()
        return None

    # ---- model file operations (format and file-safety logic lives in threedo.py) ----
    def roots(self):
        return [self.model.root]+self.model.extra_roots

    def _update_title(self):
        self._update_title_label()
        cb=getattr(self,'on_title',None)           # the window title follows the project (set by the doc window)
        if cb: cb()

    def _update_title_label(self):
        if self.model is None:
            self.title.configure(text='No 3DO model loaded'); return
        import os as _o
        name=_o.path.basename(self.path) if self.path else 'untitled.3do'
        self.title.configure(text=name+(' *' if self.dirty else ''))

    def new_model(self):
        """Starts an untitled one-part model (root 'base'). It counts as unsaved until it is saved."""
        self.untitled_id=new_untitled_id()
        self._adopt(Model3DO(None,Piece3D('base',(0.0,0.0,0.0))),None)
        self.dirty=True; self._update_title()

    def mark_dirty(self):
        if self.model is None: return
        self.dirty=True; self._update_title()

    def save(self,path=None):
        """Atomic, verified save (keeps <file>.bak). Returns validation warnings. Raises ThreeDOError; the file is left as it was."""
        if self.model is None: raise ThreeDOError('no 3DO model is open')
        target=path or self.path
        if not target: raise ThreeDOError('this model has no file name yet; use Save As')
        old_path,old_id=self.path,self.untitled_id
        with self._base_state():                 # files always hold the rest pose, never the posed frame
            warn=save_3do(self.roots(),target)     # the .3do is the base: pending rotations are not in it
            proj=self.project_path if (target==self.path and self.project_path) else sidecar_path(target)
            write_project(proj,self.roots(),target,**self._seq_kwargs())   # bound to the base just written
        self.project_path=proj
        self.model.path=target; self.path=target; self.untitled_id=None; self.dirty=False
        self.sidecar_note=None
        discard_autosave(old_path,old_id)
        self._update_title(); self._refresh_info()
        return warn

    def save_project(self,project_path):
        """Writes the open model's project (pending rotations and the rest) to project_path. The .3do on disk must already
        match the open base: a project is bound to the base it was made against."""
        if self.model is None: raise ThreeDOError('no 3DO model is open')
        if not self.path: raise ThreeDOError('save the model as a .3do first (Save As), then save the project')
        try: disk=read_3do(self.path)
        except (ThreeDOError,OSError) as e: raise ThreeDOError(f'cannot check the .3do on disk: {e}')
        with self._base_state():
            if base_signature([disk.root]+disk.extra_roots)!=base_signature(self.roots()):
                raise ThreeDOError('the open model has unsaved changes to its .3do. Save the 3DO model first, then save the project.')
            write_project(project_path,self.roots(),self.path,**self._seq_kwargs())
        self.project_path=project_path; self._update_title()
        self.dirty=False
        discard_autosave(self.path,self.untitled_id)
        self._update_title(); self._refresh_info()
        return project_path

    def finalize_engine(self):
        """Bakes every pending rotation into the geometry and writes the engine .3do; the sidecar is removed.
        Returns the grid rounding error (TA units)."""
        if self.model is None: raise ThreeDOError('no 3DO model is open')
        if not self.path: raise ThreeDOError('this model has no file name yet; use Save As first')
        if self.driver=='anim': raise ThreeDOError('turn Animate off before finalizing: the engine file holds the rest pose')
        err=self.commit_pending(all_parts=True)
        self.save()
        return err

    def export_part(self,piece,path):
        """Writes one part and its children as a standalone .3do. Returns validation warnings."""
        if piece is None: raise ThreeDOError('select a part first')
        out,_err=baked_copy(self.roots())
        m2=Model3DO(None,out[0]); m2.extra_roots=out[1:]
        p2=piece_at_path(m2,self._piece_path(piece))
        if p2 is None: raise ThreeDOError('part is not in this model')
        return save_3do([copy_piece_tree(p2)],path)

    def autosave_now(self):
        """Writes the unsaved model to its autosave file. Returns that file, or None if nothing needed saving."""
        if self.model is None or not self.dirty: return None
        target=autosave_target(self.path,self.untitled_id)
        with self._base_state():
            write_autosave(self.roots(),target)
            write_project(sidecar_path(target),self.roots(),target,**self._seq_kwargs())
        return target

    def export_3d(self,scope,fmt,path):
        """scope 'part' exports the selected part with its children, 'model' the whole model. Returns (faces, skipped)."""
        if self.model is None: raise ThreeDOError('no 3DO model is open')
        piece=None
        if scope=='part':
            if self.sel_part is None: raise ThreeDOError('select a part first')
            piece=self.sel_part
        return export_3d(self.model,piece,path,fmt,palette=self._palette())

    def discard_changes_file(self):
        """Forgets the autosave when the user discards unsaved changes."""
        discard_autosave(self.path,self.untitled_id)

    def _refresh_list(self):
        self.plist.delete(0,'end')
        depth_of={id(p):d for p,d in self.model.pieces()} if self.model else {}
        for p in self.pieces:
            mark='[x]' if id(p) in self.visible else '[ ]'
            pm='*' if p.pend is not None else ' '          # * = has a pending rotation (not yet committed)
            self.plist.insert('end',f"{mark}{pm} {'  '*depth_of.get(id(p),0)}{p.name or '(unnamed)'}")
        if self.sel_part is not None:
            idx=self.pieces.index(self.sel_part)
            self.plist.selection_clear(0,'end'); self.plist.selection_set(idx); self.plist.see(idx)

    def _on_list_click(self,e):
        idx=self.plist.nearest(e.y)
        if idx<0 or idx>=len(self.pieces): return 'break'
        piece=self.pieces[idx]
        if e.x<=28:                            # the [x] column toggles visibility
            if id(piece) in self.visible: self.visible.discard(id(piece))
            else: self.visible.add(id(piece))
            self._rebuild(); self._refresh_list(); self.redraw()
            return 'break'
        self.sel_part=piece; self._drag_src=idx
        self._note_selection()
        if self.sel_face and self.sel_face[0] is not piece: self.sel_face=None
        self._refresh_list(); self.redraw()
        return None

    def _drag_release(self,e):
        """Drag a part onto another part in the list to nest it under that part; drop it on empty space below the list to make it top level."""
        src=self._drag_src; self._drag_src=None
        if src is None or self.model is None or not (0<=src<len(self.pieces)): return
        piece=self.pieces[src]
        last=self.plist.size()-1
        bb=self.plist.bbox(last) if last>=0 else None
        if bb and e.y>bb[1]+bb[3]:
            dst=None
        else:
            di=self.plist.nearest(e.y)
            if di==src or not (0<=di<len(self.pieces)): return
            dst=self.pieces[di]
        try:
            self.reparent_piece(piece,dst)
        except ThreeDOError as ex:
            self.info.configure(text=f'Cannot move {piece.name or "part"}: {ex}')

    def origin_of_piece(self,piece):
        return self.model.origin_of(piece)

    def reparent_piece(self,piece,new_parent):
        reparent(self.model,piece,new_parent)
        self._after_edit()

    # ---- piece editing (Piece menu): one undo step each; refused while Animate is on or a pivot move is open ----
    def _piece_edit_check(self):
        if self.model is None: raise ThreeDOError('no 3DO model is open')
        if self._pivot_session is not None: raise ThreeDOError('accept or cancel the pivot move first')
        if self.driver=='anim': raise ThreeDOError('turn Animate off to add, remove or reshape parts')

    def _need_sel(self):
        if self.sel_part is None: raise ThreeDOError('select a part first')
        return self.sel_part

    def _piece_edit(self,fn):
        """Runs one piece edit and records it. A part the edit creates becomes the selection. A refusal is shown, not raised."""
        try:
            self._piece_edit_check()
            result=fn()
        except ThreeDOError as e:
            self.refusal=str(e); self._refresh_info(); return None
        self.refusal=None
        self._after_edit()
        if isinstance(result,Piece3D): self.sel_part=result
        self._refresh_list(); self.redraw(); self._refresh_info()
        return result

    def create_piece_here(self,name):
        return self._piece_edit(lambda: create_piece(self.model,self.sel_part or self.model.root,name))

    def duplicate_selected(self):
        return self._piece_edit(lambda: duplicate_piece(self.model,self._need_sel()))

    def mirror_selected(self,axis):
        return self._piece_edit(lambda: mirror_piece(self.model,self._need_sel(),axis))

    def import_piece(self,path,replace,scale=1.0,colour=0):
        """Imports an OBJ, DXF or LWO mesh as a new part under the selection (or the base), or over the selected part."""
        def go():
            pts,polys=read_mesh_file(path)
            if replace: return replace_mesh(self.model,self._need_sel(),pts,polys,colour,scale)
            name=_os.path.splitext(_os.path.basename(path))[0]
            return add_mesh_piece(self.model,self.sel_part or self.model.root,name,pts,polys,colour,scale)
        return self._piece_edit(go)

    def center_pivot_mesh(self):
        return self._piece_edit(lambda: set_origin(self.model,self._need_sel(),piece_geometry_centre(self.model,self.sel_part)))

    def center_pivot_world(self):
        return self._piece_edit(lambda: set_origin(self.model,self._need_sel(),(0.0,0.0,0.0)))

    def match_pivot_start(self):
        """Match To Other Piece: the next part clicked gives its pivot to the selected part."""
        try:
            self._piece_edit_check(); self._need_sel()
        except ThreeDOError as e:
            self.refusal=str(e); self._refresh_info(); return
        self._match_wait=True
        self.refusal='click the part whose pivot this part should match (click empty space to cancel)'
        self._refresh_info()

    def pivot_move_start(self):
        """Move Pivot: the gizmo moves only the pivot. Accept keeps the new place; Cancel puts the part back."""
        try:
            self._piece_edit_check(); self._need_sel()
        except ThreeDOError as e:
            self.refusal=str(e); self._refresh_info(); return
        self._pivot_session={'base':copy_roots([self.model.root]+self.model.extra_roots),'path':self._piece_path(self.sel_part)}
        self.pivot_var.set(True); self.tool_var.set('move')
        self._pivot_bar.pack(side='bottom',fill='x',before=self.info)
        self.refusal=None; self._refresh_info(); self.redraw()

    def pivot_accept(self):
        if self._pivot_session is None: return
        self._pivot_end()
        self._after_edit()                          # one undo step for the whole pivot move
        self._refresh_info(); self.redraw()

    def pivot_cancel(self):
        s=self._pivot_session
        if s is None: return
        roots=copy_roots(s['base'])
        self.model.root=roots[0]; self.model.extra_roots=roots[1:]
        self._pivot_end()
        self.sel_part=piece_at_path(self.model,s['path'])
        self._resync_view(); self._refresh_info(); self.redraw()

    def _pivot_end(self):
        self._pivot_session=None; self.pivot_var.set(False)
        self._pivot_bar.pack_forget()

    def _draw_pivot(self):
        """Highlight Pivot: a small cross at the selected part's pivot."""
        if not self.highlight_pivot.get() or self.model is None or self.sel_part is None or self._view is None: return
        O=self.model.origin_of(self.sel_part)
        if O is None: return
        GL=_GL; L=self._gizmo_len()*0.6
        GL.glDisable(GL.GL_LIGHTING); GL.glDisable(GL.GL_DEPTH_TEST); GL.glLineWidth(2.0)
        GL.glColor3f(*GIZMO_ACTIVE)
        for A,_u,_w in VIEW_AXES:
            GL.glBegin(GL.GL_LINES); GL.glVertex3f(*_add(O,_smul(A,-L))); GL.glVertex3f(*_add(O,_smul(A,L))); GL.glEnd()

    # ---- base plate tool: each edit is one undo step and is refused like the other piece edits ----
    def base_plate_create(self,width,depth):
        return self._piece_edit(lambda: create_base_plate(self.model,width,depth))

    def base_plate_designate(self):
        def go():
            piece=self._need_sel()
            face=designate_base_plate(self.model,piece)
            if piece is not self.model.root:          # the quad's part is gone; the base part is the selection now
                self._sel_group=[self.model.root]; self._sel_part=self.model.root
            return face
        return self._piece_edit(go)

    def base_plate_clear(self):
        return self._piece_edit(lambda: clear_base_plate(self.model))

    def base_plate_resize(self,width,depth):
        return self._piece_edit(lambda: set_base_plate_size(self.model,width,depth))

    def base_plate_status(self):
        if self.model is None: return 'Open or create a 3DO model first.'
        root=self.model.root
        size=base_plate_size(root)
        if size is not None:
            return f'Base plate: face {root.flag}, width {size[0]:g} (X) by depth {size[1]:g} (Z) units.'
        return f'No base plate: {base_plate_problem(root)}.'

    # ---- transform palette: numeric values and spinners for Move and Rotate. Every change is one undo step. ----
    _BASIS=((1.0,0.0,0.0),(0.0,1.0,0.0),(0.0,0.0,1.0))
    _spin=None
    xf_absolute=False          # Move mode: True enters world coordinates, False enters offsets along the part's own axes

    def _xf_group(self):
        """The parts a transform moves: the selection, without parts whose selected ancestor already moves them."""
        parts=self.sel_parts or ([self.sel_part] if self.sel_part is not None else [])
        paths=[self._piece_path(p) for p in parts]
        return [p for p,pth in zip(parts,paths) if pth is not None and not any(q!=pth and pth[:len(q)]==q for q in paths)]

    def _xf_check(self):
        self._piece_edit_check()
        if self.tool_var.get() not in ('move','rotate'): raise ThreeDOError('choose Move (W) or Rotate (E) to use the transform values')
        self._need_sel()

    def _xf_local_to_world(self,vals):
        """Offsets written along the selected part's own axes (its pending rotation included) as a world vector."""
        loc=locate(self.model,self.sel_part)
        return m_apply(loc[2],tuple(vals))

    def _xf_do(self,vals,delta):
        """Applies a transform. Move: vals are world coordinates when absolute and not a delta, otherwise an offset.
        Rotate: vals are degrees about the world X, Y and Z axes, in that order, turned pending as the rotate gizmo does."""
        self._xf_check()
        if self.tool_var.get()=='move':
            if self.xf_absolute and not delta:
                o=self.model.origin_of(self.sel_part)
                vec=tuple(vals[i]-o[i] for i in range(3))
            elif self.xf_absolute:
                vec=tuple(vals)
            else:
                vec=self._xf_local_to_world(vals)
            for part in self._xf_group(): translate_part(part,vec,self.model)
        else:
            for part in self._xf_group():
                for k,deg in enumerate(vals):
                    if deg: turn_pending(self.model,part,self._BASIS[k],_math.radians(deg))

    def palette_state(self):
        """What the palette shows: the tool, whether it can be used, and the values (world origin in absolute Move, else zero)."""
        tool=self.tool_var.get()
        ok=self.model is not None and self.sel_part is not None and tool in ('move','rotate') and self.driver!='anim' and self._pivot_session is None
        vals=(0.0,0.0,0.0)
        if ok and tool=='move' and self.xf_absolute:
            vals=tuple(self.model.origin_of(self.sel_part))
        return {'tool':tool,'ok':ok,'absolute':self.xf_absolute,'values':vals}

    def palette_apply(self,vals):
        return self._piece_edit(lambda: self._xf_do(vals,False))

    def palette_nudge(self,axis,amount):
        """One tap on a spinner: moves (or turns) the selection by amount along (about) one axis."""
        def go():
            v=[0.0,0.0,0.0]; v[axis]=amount
            self._xf_do(v,True)
        return self._piece_edit(go)

    def _xf_dir(self,axis):
        """Direction a spinner drag moves along: the world axis, or the part's own axis in offset Move."""
        if self.tool_var.get()=='move' and not self.xf_absolute:
            return self._xf_local_to_world(self._BASIS[axis])
        return self._BASIS[axis]

    def spin_begin(self,axis):
        """Starts a spinner drag. Nothing is recorded until spin_end; the drag moves the selection live from its start."""
        try:
            self._xf_check()
        except ThreeDOError as e:
            self.refusal=str(e); self._refresh_info(); return False
        self.refusal=None
        g=self._gz_begin(kind='spin',axis=axis,pane=0,x=0,y=0,origin=None,dirpx=None)
        g['dir']=self._xf_dir(axis)
        self._spin=g
        return True

    def spin_drag(self,amount):
        """Moves (or turns, in degrees) the dragged selection to the start plus amount, so the drag is exact from its start."""
        g=self._spin
        if g is None or self.model is None: return
        roots=copy_roots(g['base'])
        self.model.root=roots[0]; self.model.extra_roots=roots[1:]
        for path,_O in g['group']:
            part=piece_at_path(self.model,path)
            if part is None: continue
            if self.tool_var.get()=='move':
                translate_part(part,tuple(g['dir'][i]*amount for i in range(3)),self.model)
            else:
                turn_pending(self.model,part,g['dir'],_math.radians(amount))
        piece=piece_at_path(self.model,g['path'])
        self._sel_group=[p for p in (piece_at_path(self.model,path) for path in g['sel']) if p is not None]
        self._sel_part=piece; self.sel_face=None
        keep=set(g['vis'])
        self.visible={id(p) for path,p in piece_paths(self.model) if path in keep}
        self._resync_view(); self._refresh_info()

    def spin_end(self):
        g=self._spin; self._spin=None
        if g is None or self.model is None: return
        if state_signature([self.model.root]+self.model.extra_roots)!=state_signature(g['base']):
            self.mark_dirty()
            self._commit()
        self._resync_view(); self._refresh_info()

    def set_origin_of(self,piece,xyz):
        set_origin(self.model,piece,xyz)
        self._after_edit()

    def commit_pending(self,all_parts=False):
        """Bakes pending rotations into the geometry: the selected part, or every part. Returns the grid rounding error (TA units)."""
        if self.model is None: raise ThreeDOError('no 3DO model is open')
        if self.driver=='anim': raise ThreeDOError('turn Animate off before committing pending rotations')
        roots=[self.model.root]+self.model.extra_roots
        if all_parts:
            if pending_count(roots)==0: return 0.0
            err=commit_all(roots)
        else:
            if self.sel_part is None: raise ThreeDOError('select a part first')
            if self.sel_part.pend is None: return 0.0
            err=commit_pend(self.sel_part)
        self._after_edit()
        return err

    def _after_edit(self):
        """A finished, discrete edit: mark unsaved, refresh, and record one undo step."""
        if self._refuse_structure(): return
        self.refusal=None
        self.mark_dirty()
        self._resync_view(); self._refresh_info()
        self._commit()

    def _resync_view(self):
        self.pieces=[p for p,_ in self.model.pieces()]
        self._rebuild(); self._refresh_list(); self.redraw()

    # ---- undo / redo: whole-model snapshots (models are small; a drag is one step) ----
    def _snapshot(self):
        pp=piece_paths(self.model)
        sel=next((path for path,p in pp if p is self.sel_part),None) if self.sel_part is not None else None
        group=[path for path,p in pp if any(p is q for q in self.sel_parts)]   # the whole Animate selection, not just its primary
        with self._base_state():                 # undo records the rest pose; the live pose comes back from the frame
            roots=copy_roots([self.model.root]+self.model.extra_roots)
        return dict(roots=roots,seqs=[{'name':q['name'],'anim':anim_to_json(q['anim'])} for q in self.seqs],
                    seq=self.seq_i,output=self.anim_output,sel=sel,group=group,
                    vis=[path for path,p in pp if id(p) in self.visible])

    def _commit(self):
        if self.model is None: return
        st=self._snapshot()
        if self._hi>=0:
            prev=self._hist[self._hi]
            if state_signature(prev['roots'])==state_signature(st['roots']) and prev['seqs']==st['seqs'] \
               and prev['seq']==st['seq'] and prev['output']==st['output']: return
        del self._hist[self._hi+1:]
        self._hist.append(st)
        if len(self._hist)>MAX_UNDO: del self._hist[0]
        self._hi=len(self._hist)-1

    def _reset_history(self):
        self._hist=[]; self._hi=-1; self._commit()

    def _restore(self,st):
        roots=copy_roots(st['roots'])
        self.model.root=roots[0]; self.model.extra_roots=roots[1:]
        self.seqs=[{'name':q['name'],'anim':normalize_anim(q['anim'])} for q in st['seqs']]
        self.seq_i=st['seq']; self.anim=self.seqs[self.seq_i]['anim']
        self.anim_output=st['output']
        vis=set(st['vis'])
        self.visible={id(p) for path,p in piece_paths(self.model) if path in vis}
        self.sel_part=piece_at_path(self.model,st['sel']) if st['sel'] else None
        if st.get('group'):                      # put the whole Animate selection back, with the primary last-clicked part
            group=[piece_at_path(self.model,path) for path in st['group']]
            self._sel_group=[p for p in group if p is not None]
            self._sel_part=self.sel_part
        self.sel_face=None
        if self.driver=='anim':                  # the restored base becomes the rest; the frame's pose goes back on it
            self.rest=snapshot_pose(roots); self._anim_struct=self._structure_sig()
            self.pieces=[p for p,_ in self.model.pieces()]
            self._apply_time()
        self._resync_view(); self._refresh_info(); self.mark_dirty()

    def undo(self):
        if self.model is None or self._gz is not None: return
        if self._hi>0:
            self._hi-=1; self._restore(self._hist[self._hi])

    def redo(self):
        if self.model is None or self._gz is not None: return
        if self._hi<len(self._hist)-1:
            self._hi+=1; self._restore(self._hist[self._hi])

    # ---- tools ----
    def set_tool(self,name):
        if name in ('select','move','rotate'):
            self.tool_var.set(name); self._tool_changed()

    def _tool_changed(self):
        if self._gz is not None: self._gizmo_finish()
        self.redraw()

    def _view_key(self,e,fn):
        if e.state & 0x000C: return          # ctrl/alt combinations belong to the window shortcuts
        fn()

    def _face_key(self,e,fn):
        if e.state & 0x000C: return          # alt/ctrl combinations belong to the window shortcuts
        fn()

    def _tool_key(self,e,tool):
        if e.state & 0x000C: return          # alt/ctrl combinations belong to the window shortcuts
        self.set_tool(tool)

    def selected_poly(self):
        if not self.sel_face: return None
        piece,pi=self.sel_face
        if piece is None or not (0<=pi<len(piece.polys)): return None
        return piece.polys[pi]

    def _face_edit(self,fn):
        """Apply fn to the selected polygon, then record one undo step. False when no face is selected."""
        poly=self.selected_poly()
        if poly is None: return False
        fn(poly); self._after_edit()
        return True

    def spin_face_edge(self):
        """Quads only. Shifting the vertex order by one moves the quad's internal edge to the other diagonal.
        For a textured quad the texture turns with its corners, because the format stores no separate UVs."""
        poly=self.selected_poly()
        if poly is None or len(poly.idx)!=4: return False
        return self._face_edit(lambda p: setattr(p,'idx',list(p.idx[1:])+[p.idx[0]]))

    def flip_face_normal(self):
        """Reverse the winding, which flips the face normal. Any polygon."""
        return self._face_edit(lambda p: setattr(p,'idx',list(reversed(p.idx))))

    def _rotate_quad_corners(self,step):
        """Turn a quad's corner order by one corner (90 degrees of texture). The texture follows the corners."""
        poly=self.selected_poly()
        if poly is None or len(poly.idx)!=4: return False
        idx=list(poly.idx)
        new=idx[step:]+idx[:step] if step==1 else idx[-1:]+idx[:-1]
        return self._face_edit(lambda p: setattr(p,'idx',new))

    def rotate_texture_fwd(self):
        """Texture +90 degrees (F8): the corner order moves one place forward."""
        return self._rotate_quad_corners(1)

    def rotate_texture_back(self):
        """Texture -90 degrees (F7): the corner order moves one place backward."""
        return self._rotate_quad_corners(-1)

    def reload_textures(self):
        """Drop the library and GL texture cache, then re-read the configured sources from disk."""
        self._texlib=None; self._texlib_key=None; self._free_textures()
        self._rebuild(); self._refresh_info(); self.redraw()

    def used_textures(self):
        """Lower-case texture names used by any face of the model."""
        out=set()
        if self.model is None: return out
        for p,_ in self.model.pieces():
            for poly in p.polys:
                if poly.tex: out.add(poly.tex.lower())
        return out

    def assign_selected_texture(self):
        """B: applies the currently selected texture to the selected face."""
        if not self.tex_selected: return False
        return self.assign_texture(self.tex_selected)

    def assign_texture(self,name):
        """Set the selected polygon's texture name ('' clears it)."""
        poly=self.selected_poly()
        if poly is None: return False
        if (poly.tex or '')==(name or ''): return True
        return self._face_edit(lambda p: setattr(p,'tex',name or ''))

    def _gizmo_len(self):
        return GIZMO_SIZE*self.R

    def _proj(self,i,p):
        """World point -> Tk pixel in the view (top-left origin), or None if the pane is missing or the point is behind the camera."""
        W=max(1,self._view.winfo_width()); H=max(1,self._view.winfo_height())
        rects=self._pane_rects(W,H)
        if i not in rects: return None
        gx,gy,w,h=rects[i]
        P,V=self._pane_matrices(self.panes[i],w/float(h))
        M=_mm(P,V)
        q=(p[0],p[1],p[2],1.0)
        c=[sum(M[r][k]*q[k] for k in range(4)) for r in range(4)]
        if c[3]<=1e-9: return None
        nx=c[0]/c[3]; ny=c[1]/c[3]
        return (gx+(nx+1.0)*0.5*w, H-gy-(ny+1.0)*0.5*h)

    def _piece_path(self,piece):
        return next((path for path,p in piece_paths(self.model) if p is piece),None)

    def _visible_paths(self):
        return [path for path,p in piece_paths(self.model) if id(p) in self.visible]

    def _gz_begin(self,**kw):
        g=dict(kw)
        g['x0']=g.pop('x'); g['y0']=g.pop('y')
        g['base']=copy_roots([self.model.root]+self.model.extra_roots)
        g['path']=self._piece_path(self.sel_part)
        # every part in the Animate selection moves together; each keeps its own origin for the pivot mode.
        # A part under another selected part moves with that part already, so it is left out here (moving both would
        # move the child twice). g['sel'] keeps the whole selection, so the drag does not drop the children from it.
        paths=[self._piece_path(p) for p in (self.sel_parts or [self.sel_part])]
        g['sel']=paths
        top=[p for p in paths if not any(q!=p and p[:len(q)]==q for q in paths)]
        g['group']=[(pth,self.model.origin_of(piece_at_path(self.model,pth))) for pth in top]
        g['vis']=self._visible_paths()
        g['pivot']=bool(self.pivot_var.get())
        return g

    def _gizmo_try_start(self,i,x,y):
        """Starts a gizmo drag if the press lands on the selected part's arrow (W) or ring (R). Returns True if it did."""
        tool=self.tool_var.get()
        if tool=='select' or self.model is None or self.sel_part is None or self._view is None: return False
        O=self.model.origin_of(self.sel_part)
        if O is None: return False
        L=self._gizmo_len()
        if tool=='move':
            best=None
            s0=self._proj(i,O)
            if s0 is None: return False
            for k,(A,_u,_w) in enumerate(VIEW_AXES):
                s1=self._proj(i,_add(O,_smul(A,L)))
                if s1 is None: continue
                d=_pt_seg_dist((x,y),s0,s1)
                if d<=GIZMO_HIT_PX and (best is None or d<best[0]): best=(d,k)
            if best is None: return False
            k=best[1]; A=VIEW_AXES[k][0]
            s1=self._proj(i,_add(O,A))
            dirpx=(s1[0]-s0[0],s1[1]-s0[1])
            if dirpx[0]*dirpx[0]+dirpx[1]*dirpx[1]<1e-6: return False
            self._gz=self._gz_begin(kind='move',axis=k,pane=i,x=x,y=y,origin=O,dirpx=dirpx)
            return True
        best=None
        for k,(A,u,w) in enumerate(VIEW_AXES):
            pts=[self._proj(i,_ring_point(O,L,u,w,2*_math.pi*j/RING_N)) for j in range(RING_N)]
            for j in range(RING_N):
                a=pts[j]; b=pts[(j+1)%RING_N]
                if a is None or b is None: continue
                d,tf=_pt_seg_hit((x,y),a,b)
                if d<=GIZMO_HIT_PX and (best is None or d<best[0]): best=(d,k,j+tf)
        if best is None: return False
        _,k,jf=best                      # grab angle at the exact point under the cursor, not the segment start
        A,u,w=VIEW_AXES[k]
        th=2*_math.pi*jf/RING_N
        G=_ring_point(O,L,u,w,th)
        T=_add(_smul(u,-_math.sin(th)),_smul(w,_math.cos(th)))
        g0=self._proj(i,G); g1=self._proj(i,_add(G,_smul(T,1e-3*L))); c0=self._proj(i,O)
        if g0 is None or g1 is None or c0 is None: return False
        tp=(g1[0]-g0[0],g1[1]-g0[1]); tl=_math.hypot(tp[0],tp[1])
        if tl<1e-9: return False
        radius=_math.hypot(g0[0]-c0[0],g0[1]-c0[1])
        self._gz=self._gz_begin(kind='rotate',axis=k,pane=i,x=x,y=y,origin=O,tpu=(tp[0]/tl,tp[1]/tl),radius=radius)
        return True

    def _motion1(self,e):
        if self._gz is None or self.model is None: return
        g=self._gz
        mx=e.x-g['x0']; my=e.y-g['y0']
        roots=copy_roots(g['base'])
        self.model.root=roots[0]; self.model.extra_roots=roots[1:]
        A=VIEW_AXES[g['axis']][0]
        if g['kind']=='move':
            dx,dy=g['dirpx']
            t=(mx*dx+my*dy)/(dx*dx+dy*dy)                 # world units along the axis
            for path,O in g['group']:
                part=piece_at_path(self.model,path)
                if part is None: continue
                if g['pivot']: set_origin(self.model,part,_add(O,_smul(A,t)))
                else: translate_part(part,_smul(A,t),self.model)
        else:
            phi=(mx*g['tpu'][0]+my*g['tpu'][1])/max(g['radius'],4.0)   # one radius of mouse travel = one radian
            for path,_O in g['group']:
                part=piece_at_path(self.model,path)
                if part is not None: turn_pending(self.model,part,A,phi)   # pending: geometry is untouched until commit
        piece=piece_at_path(self.model,g['path'])
        # set the group from the fresh copies (the setter would reduce it to the primary part alone)
        self._sel_group=[p for p in (piece_at_path(self.model,path) for path in g['sel']) if p is not None]
        self._sel_part=piece; self.sel_face=None
        keep=set(g['vis'])
        self.visible={id(p) for path,p in piece_paths(self.model) if path in keep}
        self._resync_view()

    def _release1(self,e):
        self._gizmo_finish()

    def _gizmo_finish(self):
        g=self._gz; self._gz=None
        if g is None or self.model is None: return
        if self._pivot_session is not None:     # a pivot move is open: nothing is recorded until it is accepted
            self._resync_view(); self._refresh_info(); return
        if self.driver=='anim':
            if not self._refuse_structure():
                if self.autokey and self.sel_part is not None: self.key_parts(self.sel_parts or [self.sel_part])
            self._resync_view(); self._refresh_info()
            return
        if state_signature([self.model.root]+self.model.extra_roots)!=state_signature(g['base']):
            self.mark_dirty()
            self._commit()
        self._resync_view(); self._refresh_info()

    def _draw_gizmo(self):
        if self._view is None or self.model is None or self.sel_part is None: return
        tool=self.tool_var.get()
        if tool=='select': return
        O=self.model.origin_of(self.sel_part)
        if O is None: return
        GL=_GL; L=self._gizmo_len()
        active=self._gz['axis'] if self._gz is not None else None
        GL.glDisable(GL.GL_LIGHTING); GL.glDisable(GL.GL_DEPTH_TEST); GL.glLineWidth(4.0)   # X red, Y green, Z blue
        for k,(A,u,w) in enumerate(VIEW_AXES):
            GL.glColor3f(*(GIZMO_ACTIVE if active==k else AXIS_COLOURS[k]))
            if tool=='move':
                tip=_add(O,_smul(A,L))
                GL.glBegin(GL.GL_LINES); GL.glVertex3f(*O); GL.glVertex3f(*tip); GL.glEnd()
                GL.glPointSize(10.0); GL.glBegin(GL.GL_POINTS); GL.glVertex3f(*tip); GL.glEnd()
            else:
                GL.glBegin(GL.GL_LINE_LOOP)
                for j in range(RING_N): GL.glVertex3f(*_ring_point(O,L,u,w,2*_math.pi*j/RING_N))
                GL.glEnd()
        GL.glColor3f(1.0,1.0,1.0); GL.glPointSize(6.0)
        GL.glBegin(GL.GL_POINTS); GL.glVertex3f(*O); GL.glEnd()
        GL.glLineWidth(1.0); GL.glPointSize(1.0)
        GL.glEnable(GL.GL_DEPTH_TEST); GL.glEnable(GL.GL_LIGHTING)

    def _part_center(self,piece):
        b=self.model.part_bounds(piece)
        if not b: return self.center
        return tuple((b[0][i]+b[1][i])/2 for i in range(3))

    def _find_palette_path(self):
        """The configured palette, else a TApalette.dat found in a texture source folder (first match)."""
        path=self.cfg.data.get('palette_path') or ''
        if path: return path
        for src in self.cfg.data.get('texture_sources') or []:
            if not _os.path.isdir(src): continue
            for root,dirs,files in _os.walk(src):
                depth=root[len(src):].count(os.sep)
                if depth>=3: dirs[:]=[]
                for f in files:
                    if f.lower()=="tapalette.dat": return _os.path.join(root,f)
        return ''

    def _palette(self):
        path=self._find_palette_path()
        if self._palette_cache[0]!=path:
            pal,err=read_palette(path) if path else (None,'no palette file set (Textures > Set palette file)')
            self._palette_cache=(path,pal)
            self._palette_problem=err
            self._free_textures()
        return self._palette_cache[1]

    def palette_problem(self):
        """Why there is no usable palette, or None when there is one."""
        self._palette()
        return self._palette_problem

    def _rebuild(self):
        """Build the drawable and pickable geometry for the visible parts."""
        if self.model is None:
            self._mesh=None; self._picks=[]; self._faces={}; return
        self._tex_palette=self._palette()
        self._tex_batches,self._tex_stats=texture_batches(self.model,self.visible,self._library(),self._tex_palette)
        missing={m.lower() for m in self._tex_stats['missing']}
        n,pos,nrm,col,picks,faces=build_mesh(self.model,self.visible,self._palette(),self.hl3_var.get(),missing)
        self._picks=picks; self._faces=faces
        if not n:
            self._mesh=None; return
        self._mesh=(n,(_ctypes.c_float*len(pos))(*pos),(_ctypes.c_float*len(nrm))(*nrm),(_ctypes.c_float*len(col))(*col))

    def set_hl3(self):
        self._rebuild(); self.redraw()

    def outline_colour(self):
        return self.cfg.data.get('face_outline') or OUTLINE_DEFAULT

    def set_outline_colour(self,hexcol):
        self.cfg.data['face_outline']=hexcol; self.cfg.save(); self.redraw()

    # ---- input ----
    def _bind_input(self,w):
        w.bind('<ButtonPress-1>',lambda e: self._press(e,1))
        w.bind('<ButtonPress-2>',lambda e: self._press(e,2))
        w.bind('<B2-Motion>',self._motion)
        w.bind('<ButtonRelease-2>',self._release)
        w.bind('<MouseWheel>',lambda e: self._wheel(e,1 if e.delta>0 else -1))
        w.bind('<Button-4>',lambda e: self._wheel(e,1))
        w.bind('<Button-5>',lambda e: self._wheel(e,-1))
        w.bind('<B1-Motion>',self._motion1)
        w.bind('<ButtonRelease-1>',self._release1)
        for key,tool in TOOL_KEYS:
            w.bind(f'<KeyPress-{key}>',lambda e,t=tool: self._tool_key(e,t))
            w.bind(f'<KeyPress-{key.upper()}>',lambda e,t=tool: self._tool_key(e,t))
        for key,name in VIEW_KEYS:
            w.bind(f'<KeyPress-{key}>',lambda e,n=name: self._view_key(e,getattr(self,n)))
        for key,name in FACE_KEYS:
            w.bind(f'<KeyPress-{key}>',lambda e,n=name: self._face_key(e,getattr(self,n)))
            w.bind(f'<KeyPress-{key.upper()}>',lambda e,n=name: self._face_key(e,getattr(self,n)))
        w.bind('<Control-z>',lambda e: self.undo()); w.bind('<Control-y>',lambda e: self.redo())

    def _press(self,e,button):
        i=self._pane_at(e.x,e.y)
        if i is None: return
        self._view.focus_set()
        self._set_active(i)
        if button==1:
            if self._gizmo_try_start(i,e.x,e.y): return
            self._pick(i,e.x,e.y,ctrl=bool(e.state & 0x0004))
        elif button==2:
            pane=self.panes[i]
            if e.state & 0x0008:               # alt: orbit about the selection (if enabled), else about the view target
                self._push_view(i)
                if pane['view']!='3D': self._to_3d(pane)
                if self._orbit_on() and self.sel_part is not None:
                    pane['target']=self._part_center(self.sel_part)
                self._clamp_orbit_distance(pane)
                self._drag=('orbit',i,e.x,e.y)
            else:
                self._push_view(i)
                self._drag=('pan',i,e.x,e.y)
            self._place_combos()

    def _motion(self,e):
        if not self._drag: return
        mode,i,x0,y0=self._drag
        dx=e.x-x0; dy=e.y-y0
        pane=self.panes[i]
        if mode=='orbit':
            pane['yaw']+=dx*0.01
            pane['pitch']=max(-1.5,min(1.5,pane['pitch']+dy*0.01))
        else:
            W=max(1,self._view.winfo_width()); H=max(1,self._view.winfo_height())
            ph=self._pane_rects(W,H)[i][3]
            upp=2.0*self._half_height_at_target(pane)/max(1,ph)     # world units per pixel at the target
            right,up=self._pane_basis(pane)
            t=pane['target']
            t=_add(t,_add(_smul(right,-dx*upp),_smul(up,dy*upp)))
            pane['target']=t
        self._drag=(mode,i,e.x,e.y)
        self.redraw()

    def _release(self,e):
        self._drag=None

    def _wheel(self,e,step):
        i=self._pane_at(e.x,e.y)
        if i is None: return
        pane=self.panes[i]
        k=1.1 if step>0 else 1/1.1
        import time as _tm
        now=_tm.monotonic()
        if now-getattr(self,'_last_wheel',-1e9)>WHEEL_GROUP_S: self._push_view(i)
        self._last_wheel=now
        if pane['view']=='3D': pane['dist']=max(0.05*self.R,pane['dist']/k)
        else: pane['scale']=max(0.05*self.R,pane['scale']/k)
        self.redraw()

    def _pane_basis(self,pane):
        """Screen right and up vectors for a pane, in world space (rows 0 and 1 of the view rotation)."""
        _,V=self._pane_matrices(pane,1.0)
        return (V[0][0],V[0][1],V[0][2]),(V[1][0],V[1][1],V[1][2])

    def _set_active(self,i):
        if i==self.active: return
        self.active=i
        self._place_combos(); self.redraw()

    # ---- selection: sel_part is the primary part; the group holds every part selected in Animate mode ----
    @property
    def sel_part(self): return self._sel_part
    @sel_part.setter
    def sel_part(self,p):
        self._sel_part=p; self._sel_group=[p] if p is not None else []
    @property
    def sel_parts(self): return list(self._sel_group)

    # ---- picking ----
    def _pick(self,i,x,y,ctrl=False):
        gx,gy,w,h=self._pane_rects(max(1,self._view.winfo_width()),max(1,self._view.winfo_height()))[i]
        pane=self.panes[i]
        ox=x-gx
        oy=y-(max(1,self._view.winfo_height())-(gy+h))
        P,V=self._pane_matrices(pane,w/float(h))
        inv=_inv(_mm(P,V))
        nx=2.0*ox/w-1.0; ny=1.0-2.0*oy/h
        def unproj(z):
            v=[sum(inv[r][c]*q for c,q in enumerate((nx,ny,z,1.0))) for r in range(4)]
            return (v[0]/v[3],v[1]/v[3],v[2]/v[3])
        o=unproj(-1.0); far=unproj(1.0)
        d=_unit(_sub(far,o))
        best=None
        for piece,pi,(a,b,c) in self._picks:
            t=_ray_tri(o,d,a,b,c)
            if t is not None and (best is None or t<best[0]): best=(t,piece,pi)
        if self._match_wait:                    # Match To Other Piece: the clicked part's pivot becomes the selected part's
            self._match_wait=False
            if best is None:
                self.refusal='pivot match cancelled: no part under the cursor'; self._refresh_info(); return
            target=best[1]
            self._piece_edit(lambda: set_origin(self.model,self._need_sel(),self.model.origin_of(target)))
            return
        if self.driver=='anim':                 # Animate: the whole part is the selection; ctrl+click adds or removes it
            piece=best[1] if best else None
            if ctrl:
                if piece is not None:
                    g=list(self._sel_group)
                    if piece in g: g.remove(piece)
                    else: g.append(piece)
                    self._sel_group=g; self._sel_part=g[-1] if g else None
            else:
                self._sel_part=piece; self._sel_group=[piece] if piece is not None else []
            self.sel_face=None
        elif best is None:
            self.sel_face=None; self.sel_part=None
        else:
            _,piece,pi=best
            self.sel_face=(piece,pi); self.sel_part=piece
        self._note_selection()
        self._refresh_list(); self.redraw()

    def _note_selection(self):
        """Selection changes are not undo steps of their own. The newest history entry is the state the model is in now,
        so it carries the current selection: an undo then brings back the selection that was active before the change."""
        if self.model is None or self._hi<0 or self._hi>=len(self._hist): return
        pp=piece_paths(self.model); e=self._hist[self._hi]
        e['sel']=next((path for path,p in pp if p is self.sel_part),None) if self.sel_part is not None else None
        e['group']=[path for path,p in pp if any(p is q for q in self.sel_parts)]

    # ---- commands from the menus ----
    def toggle_maximize(self):
        self.layout='single' if self.layout=='quad' else 'quad'
        self._place_combos(); self.redraw()

    def reset_active_view(self):
        self._push_view(self.active)
        self._fit_pane(self.panes[self.active]); self.redraw()

    # ---- camera: orbit pivot, framing, and per-pane view undo ----
    def _orbit_on(self):
        return bool(self.cfg.data.get('orbit_selection',True))

    def set_orbit_selection(self,on):
        self.cfg.data['orbit_selection']=bool(on); self.cfg.save()

    def _pane_forward(self,pane):
        """World-space direction the pane's camera looks along (the view's -z axis, expressed in world space)."""
        _,V=self._pane_matrices(pane,1.0)
        return (-V[2][0],-V[2][1],-V[2][2])

    def _clamp_orbit_distance(self,pane):
        if pane['view']!='3D': return
        pane['dist']=min(max(pane['dist'],ORBIT_MIN*self.R),ORBIT_MAX*self.R)

    def _push_view(self,i):
        """Record the pane's current view so Shift+Z can return to it. Identical consecutive states are not recorded."""
        pane=self.panes[i]
        snap=dict(view=pane['view'],yaw=pane['yaw'],pitch=pane['pitch'],dist=pane['dist'],scale=pane['scale'],target=tuple(pane['target']))
        h=pane['vhist']
        if h and h[-1]==snap: return
        h.append(snap); del h[:-MAX_UNDO]

    def undo_view(self):
        pane=self.panes[self.active]
        if not pane['vhist']: return False
        pane.update(pane['vhist'].pop())
        self._place_combos(); self.redraw()
        return True

    def frame_selection(self):
        """Centre the active pane on the selected part (or the whole model) and fit it, keeping the view direction."""
        b=self.model.part_bounds(self.sel_part) if self.sel_part is not None else self.model.bounds()
        if not b: return False
        i=self.active; pane=self.panes[i]
        c=tuple((b[0][k]+b[1][k])/2 for k in range(3))
        r=max(1e-3,_math.sqrt(sum(((b[1][k]-b[0][k])/2)**2 for k in range(3))))
        self._push_view(i)
        pane['target']=c
        if pane['view']=='3D': pane['dist']=max(r/PERSP_TAN*1.15,0.05*self.R)
        else: pane['scale']=max(r*1.15,0.05*self.R)
        self._place_combos(); self.redraw()
        return True

    def set_active_mode(self,mode):
        self.panes[self.active]['mode']=mode; self.redraw()

    def active_mode(self):
        return self.panes[self.active]['mode']

    def set_active_view(self,name):
        self._set_pane_view(self.active,name)

    def _combo_chosen(self,i):
        self._set_pane_view(i,self._combos[i].get())
        self._set_active(i)

    def _place_combos(self):
        if self._view is None: return
        W=max(1,self._view.winfo_width()); H=max(1,self._view.winfo_height())
        for i,cb in enumerate(self._combos):
            if i not in self._pane_rects(W,H):
                cb.place_forget(); continue
            gx,gy,w,h=self._pane_rects(W,H)[i]
            cb.set(self.panes[i]['view'])
            cb.place(x=gx+6,y=H-(gy+h)+6)

    # ---- drawing ----
    def redraw(self):
        # pyopengltk draws only once its context exists (after the frame is mapped)
        if self._view is None or not self._view.context_created: return
        self._view._display()

    def _draw_all(self,view):
        GL=_GL
        W=max(1,view.winfo_width()); H=max(1,view.winfo_height())
        rects=self._pane_rects(W,H)
        GL.glEnable(GL.GL_SCISSOR_TEST)
        for i,(x,y,w,h) in rects.items():
            pane=self.panes[i]
            GL.glViewport(x,y,w,h); GL.glScissor(x,y,w,h)
            bd=BACKDROPS[pane['bg']]
            GL.glClearColor(*bd['bg'],1.0); GL.glClear(GL.GL_COLOR_BUFFER_BIT|GL.GL_DEPTH_BUFFER_BIT)
            P,V=self._pane_matrices(pane,w/float(h))
            GL.glMatrixMode(GL.GL_PROJECTION); GL.glLoadMatrixf(_gl_flat(P))
            GL.glMatrixMode(GL.GL_MODELVIEW); GL.glLoadMatrixf(_gl_flat(V))
            GL.glLightfv(GL.GL_LIGHT0,GL.GL_POSITION,VIEW_LIGHT)
            if pane['bg']=='grid': self._draw_grid(bd)
            if self._mesh: self._draw_mesh(pane['mode'],bd['wire'])
            self._draw_outline()
            self._draw_gizmo()
            self._draw_pivot()
        GL.glDisable(GL.GL_SCISSOR_TEST)
        GL.glViewport(0,0,W,H)
        GL.glMatrixMode(GL.GL_PROJECTION); GL.glLoadIdentity(); GL.glOrtho(0,W,0,H,-1,1)
        GL.glMatrixMode(GL.GL_MODELVIEW); GL.glLoadIdentity()
        GL.glDisable(GL.GL_LIGHTING); GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glEnable(GL.GL_BLEND); GL.glBlendFunc(GL.GL_SRC_ALPHA,GL.GL_ONE_MINUS_SRC_ALPHA)
        gx,gy,w,h=rects[self.active]
        GL.glColor4f(*BACKDROPS[self.panes[self.active]['bg']]['border']); GL.glLineWidth(2.0)
        GL.glBegin(GL.GL_LINE_LOOP)
        for px,py in ((gx+1,gy+1),(gx+w-1,gy+1),(gx+w-1,gy+h-1),(gx+1,gy+h-1)): GL.glVertex2f(px,py)
        GL.glEnd()
        GL.glDisable(GL.GL_BLEND); GL.glEnable(GL.GL_DEPTH_TEST); GL.glEnable(GL.GL_LIGHTING)

    def _draw_mesh(self,mode,wire):
        GL=_GL
        n,pos,nrm,col=self._mesh
        GL.glEnableClientState(GL.GL_VERTEX_ARRAY); GL.glVertexPointer(3,GL.GL_FLOAT,0,pos)
        if mode=='wireframe':
            GL.glDisable(GL.GL_LIGHTING); GL.glPolygonMode(GL.GL_FRONT_AND_BACK,GL.GL_LINE)
            GL.glColor3f(*wire)
            GL.glDrawArrays(GL.GL_TRIANGLES,0,n)
            GL.glPolygonMode(GL.GL_FRONT_AND_BACK,GL.GL_FILL); GL.glEnable(GL.GL_LIGHTING)
        else:
            # 'textured' draws the shaded base first (untextured faces, and the grey under transparent texels)
            GL.glEnableClientState(GL.GL_NORMAL_ARRAY); GL.glEnableClientState(GL.GL_COLOR_ARRAY)
            GL.glNormalPointer(GL.GL_FLOAT,0,nrm); GL.glColorPointer(3,GL.GL_FLOAT,0,col)
            GL.glDrawArrays(GL.GL_TRIANGLES,0,n)
            GL.glDisableClientState(GL.GL_NORMAL_ARRAY); GL.glDisableClientState(GL.GL_COLOR_ARRAY)
        GL.glDisableClientState(GL.GL_VERTEX_ARRAY)
        if mode=='textured' and self._tex_batches: self._draw_textured()

    def _library(self):
        """Texture library for the configured sources; rebuilt (and GL textures dropped) when the list changes."""
        srcs=tuple(self.cfg.data.get('texture_sources') or ())
        if self._texlib is None or self._texlib_key!=srcs:
            self._texlib=TextureLibrary(list(srcs)); self._texlib_key=srcs; self._free_textures()
        return self._texlib

    def set_texture_sources(self,sources):
        self.cfg.data['texture_sources']=list(sources); self.cfg.save()
        self._rebuild(); self._refresh_info(); self.redraw()

    def _free_textures(self):
        self._gltex_stale.extend(t for t in self._gltex.values() if t); self._gltex={}

    def _gl_texture(self,key,b):
        """Upload one texture as RGBA (palette colour, alpha 0 for transparent texels). Cached per name; 0 = none."""
        if key in self._gltex: return self._gltex[key]
        GL=_GL; w,h,rows=b['w'],b['h'],b['rows']; pal=self._tex_palette
        if w<=0 or h<=0 or pal is None:
            self._gltex[key]=0; return 0
        buf=bytearray(w*h*4)
        for y,row in enumerate(rows):
            for x,v in enumerate(row):
                o=(y*w+x)*4
                if v is None: buf[o:o+4]=b'\x80\x80\x80\xff'    # not produced by raw frames; neutral grey, opaque
                else:
                    r,g,bl=pal[v]; buf[o:o+4]=bytes((r,g,bl,255))
        tid=int(GL.glGenTextures(1))
        GL.glBindTexture(GL.GL_TEXTURE_2D,tid)
        GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT,1)
        GL.glTexImage2D(GL.GL_TEXTURE_2D,0,GL.GL_RGBA,w,h,0,GL.GL_RGBA,GL.GL_UNSIGNED_BYTE,bytes(buf))
        GL.glTexParameteri(GL.GL_TEXTURE_2D,GL.GL_TEXTURE_MIN_FILTER,GL.GL_NEAREST)
        GL.glTexParameteri(GL.GL_TEXTURE_2D,GL.GL_TEXTURE_MAG_FILTER,GL.GL_NEAREST)
        GL.glTexParameteri(GL.GL_TEXTURE_2D,GL.GL_TEXTURE_WRAP_S,GL.GL_CLAMP_TO_EDGE)
        GL.glTexParameteri(GL.GL_TEXTURE_2D,GL.GL_TEXTURE_WRAP_T,GL.GL_CLAMP_TO_EDGE)
        self._gltex[key]=tid
        return tid

    def _draw_textured(self):
        """Textured quads over the shaded mesh. Lighting is off (retail draws texels flat); depth uses LEQUAL so
        the coplanar textured triangles win over the grey base they sit on."""
        GL=_GL
        if self._gltex_stale:
            for t in self._gltex_stale: GL.glDeleteTextures([t])
            self._gltex_stale=[]
        started=False
        for key,b in self._tex_batches.items():
            tid=self._gl_texture(key,b)
            if not tid: continue
            if 'pos_c' not in b:
                b['pos_c']=(_ctypes.c_float*len(b['pos']))(*b['pos'])
                b['uv_c']=(_ctypes.c_float*len(b['uv']))(*b['uv'])
            if not started:
                GL.glEnable(GL.GL_TEXTURE_2D); GL.glDisable(GL.GL_LIGHTING)
                GL.glEnable(GL.GL_ALPHA_TEST); GL.glAlphaFunc(GL.GL_GREATER,0.5)
                GL.glDepthFunc(GL.GL_LEQUAL); GL.glColor3f(1.0,1.0,1.0)
                GL.glEnableClientState(GL.GL_VERTEX_ARRAY); GL.glEnableClientState(GL.GL_TEXTURE_COORD_ARRAY)
                started=True
            GL.glBindTexture(GL.GL_TEXTURE_2D,tid)
            GL.glVertexPointer(3,GL.GL_FLOAT,0,b['pos_c']); GL.glTexCoordPointer(2,GL.GL_FLOAT,0,b['uv_c'])
            GL.glDrawArrays(GL.GL_TRIANGLES,0,b['n'])
        if started:
            GL.glDisableClientState(GL.GL_TEXTURE_COORD_ARRAY); GL.glDisableClientState(GL.GL_VERTEX_ARRAY)
            GL.glBindTexture(GL.GL_TEXTURE_2D,0); GL.glDisable(GL.GL_TEXTURE_2D)
            GL.glDisable(GL.GL_ALPHA_TEST); GL.glDepthFunc(GL.GL_LESS); GL.glEnable(GL.GL_LIGHTING)

    def _tex_note(self):
        st=self._tex_stats; parts=[]
        if st['no_palette']: parts.append('textures off: '+(self.palette_problem() or 'no palette'))
        else: parts.append(f"{st['quads']} textured quads")
        if st['missing']: parts.append(f"{len(st['missing'])} texture names not found")
        if st['tri_tex']: parts.append(f"{st['tri_tex']} textured triangles (drawn plain)")
        return '; '+', '.join(parts)

    def _refresh_info(self):
        self._edge_sync()
        m=self.model
        if m is None: return
        s=m.summary(); b=m.bounds()
        size_txt=f'size {round(b[1][0]-b[0][0],2)} x {round(b[1][1]-b[0][1],2)} x {round(b[1][2]-b[0][2],2)} TA units' if b else 'no geometry'
        t3,u3=count_tri3(m)
        warn=f'; WARNING {t3+u3} three-point faces ({t3} textured, {u3} untextured)' if (t3 or u3) else ''
        n=pending_count([m.root]+m.extra_roots)
        pend=f'; {n} pending rotation{"s" if n!=1 else ""} (not committed)' if n else ''
        note=f'; {self.sidecar_note}' if self.sidecar_note else ''
        anim=(f'; animating, frame {self.frame_t}'+(' (auto key)' if self.autokey else '')) if self.driver=='anim' else ''
        refuse=f'; {self.refusal}' if self.refusal else ''
        self.info.configure(text=f"{s['pieces']} pieces, {s['verts']} vertices, {s['polys']} faces; {size_txt}{warn}{pend}{note}{anim}{refuse}{self._tex_note()}")
        self._sync_timeline()
        self._notify()

    def add_listener(self,cb):
        """cb() runs after every info-line refresh, so panels can follow edits, loads and undo."""
        self._listeners=list(self._listeners)+[cb]

    def _notify(self):
        for cb in self._listeners: cb()

    def _draw_grid(self,bd):
        """Ground grid on the model's lowest plane, in TA units. Drawn without writing depth so the model sits over it."""
        GL=_GL
        cell=float(self.cfg.data.get('grid_cell',GRID_CELL_DEFAULT))
        if cell<=0: return
        cx,_,cz=self.center; y=self._lo[1]-0.01*cell
        half=max(3.0*self.R,4.0*cell)
        x0=_math.floor((cx-half)/cell); x1=_math.ceil((cx+half)/cell)
        z0=_math.floor((cz-half)/cell); z1=_math.ceil((cz+half)/cell)
        GL.glDisable(GL.GL_LIGHTING); GL.glDepthMask(GL.GL_FALSE); GL.glLineWidth(1.0)
        GL.glBegin(GL.GL_LINES)
        for i in range(x0,x1+1):
            GL.glColor3f(*(bd['major'] if i%GRID_MAJOR_EVERY==0 else bd['minor']))
            GL.glVertex3f(i*cell,y,z0*cell); GL.glVertex3f(i*cell,y,z1*cell)
        for k in range(z0,z1+1):
            GL.glColor3f(*(bd['major'] if k%GRID_MAJOR_EVERY==0 else bd['minor']))
            GL.glVertex3f(x0*cell,y,k*cell); GL.glVertex3f(x1*cell,y,k*cell)
        GL.glEnd()
        GL.glDepthMask(GL.GL_TRUE); GL.glEnable(GL.GL_LIGHTING)

    def set_active_bg(self,bg):
        self.panes[self.active]['bg']=bg; self.redraw()

    def active_bg(self):
        return self.panes[self.active]['bg']

    def grid_cell(self):
        return float(self.cfg.data.get('grid_cell',GRID_CELL_DEFAULT))

    def set_grid_cell(self,v):
        self.cfg.data['grid_cell']=float(v); self.cfg.save(); self.redraw()

    def _draw_outline(self):
        """Selection outline: a dark under-stroke, then the chosen colour, so it stays visible on light and dark backdrops.
        A face in base mode; every face of each selected part in Animate mode."""
        if self.driver=='anim' and self._sel_group:
            ids={id(p) for p in self._sel_group}
            loops=[vs for (pid,_),vs in self._faces.items() if pid in ids and vs]
        elif self.sel_face:
            vs=self._faces.get((id(self.sel_face[0]),self.sel_face[1]))
            loops=[vs] if vs else []
        else: return
        if not loops: return
        GL=_GL
        r,g,b=_hex_to_rgb(self.outline_colour())
        GL.glDisable(GL.GL_LIGHTING)
        GL.glEnable(GL.GL_POLYGON_OFFSET_LINE); GL.glPolygonOffset(-1.0,-1.0)
        for width,rgb in ((4.0,(0.05,0.05,0.05)),(2.5,(r,g,b))):
            GL.glLineWidth(width); GL.glColor3f(*rgb)
            for vs in loops:
                GL.glBegin(GL.GL_LINE_LOOP)
                for v in vs: GL.glVertex3f(*v)
                GL.glEnd()
        GL.glDisable(GL.GL_POLYGON_OFFSET_LINE); GL.glEnable(GL.GL_LIGHTING)
