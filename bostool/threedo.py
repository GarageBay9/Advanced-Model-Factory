# ---- 3DO model reader (Total Annihilation .3do, little-endian, no GUI dependency) ----
# Layout follows Servo's Piece3do::read / SERVOstructures.h (and the repo's research/formats/3do.md):
#   piece header (13 longs, 52 bytes): version, nverts, nprims, flag, x, y, z (offset from parent),
#   name offset, always-0, vertex-array offset, primitive-array offset, sibling offset, child offset.
#   vertex: 3 longs.  primitive: 8 longs (color, nindexes, 0, index-array offset, texture-name offset, 3 unknown).
#   index array: uint16 values.  Position units: raw / 65536 (16.16 fixed point; matches the retail engine and the ARMAP pad check; Servo and the Cavedog Unitviewer use 163840, a 2.5x viewer scale).
import struct as _struct

TA_ALONG=1.0/65536.0
_PIECE_HDR=_struct.Struct('<13l')
_VERT=_struct.Struct('<3l')
_PRIM=_struct.Struct('<8l')

class ThreeDOError(Exception): pass

class Poly3D:
    # pad and unk keep the header fields the reader does not interpret, so a write reproduces them
    __slots__=('color','idx','tex','pad','unk')
    def __init__(self,color,idx,tex,pad=0,unk=(0,0,0)):
        self.color=color; self.idx=idx; self.tex=tex; self.pad=pad; self.unk=tuple(unk)

class Piece3D:
    def __init__(self,name,offset,version=1,flag=0):
        self.name=name; self.offset=offset          # offset from parent origin (TA units, already scaled)
        self.version=version; self.flag=flag
        self.verts=[]; self.polys=[]; self.children=[]
        self.pend=None      # pending rotation: unit quaternion (w,x,y,z) in the parent's frame, about this origin; None = none

def _walk(p,depth=0):
    yield p,depth
    for c in p.children:
        yield from _walk(c,depth+1)

def read_3do(path,max_pieces=4096):
    """Parse a .3do file into a tree of Piece3D. Raises ThreeDOError on malformed input (never silently truncates)."""
    with open(path,'rb') as f: data=f.read()
    n=len(data)
    if n<_PIECE_HDR.size: raise ThreeDOError('file too short for a 3DO header')
    seen=set()

    def cstr(off,maxlen=32):
        if off<=0 or off>=n: return ''
        return data[off:off+maxlen].split(b'\0',1)[0].decode('latin1')

    def need(off,size,what):
        if off<0 or off+size>n: raise ThreeDOError(f'{what} at {off} runs past end of file ({n} bytes)')

    def read_one(off):
        need(off,_PIECE_HDR.size,'piece header')
        (ver,nv,npr,flag,x,y,z,oname,_z0,overt,oprim,osib,ochild)=_PIECE_HDR.unpack_from(data,off)
        p=Piece3D(cstr(oname),tuple(v*TA_ALONG for v in (x,y,z)),ver,flag)
        if nv<0 or npr<0: raise ThreeDOError(f'negative count in piece at {off}')
        need(overt,nv*_VERT.size,'vertex array')
        for i in range(nv):
            vx,vy,vz=_VERT.unpack_from(data,overt+i*_VERT.size)
            p.verts.append((vx*TA_ALONG,vy*TA_ALONG,vz*TA_ALONG))
        need(oprim,npr*_PRIM.size,'primitive array')
        for i in range(npr):
            (color,nidx,pad,oidx,otex,u1,u2,u3)=_PRIM.unpack_from(data,oprim+i*_PRIM.size)
            if nidx<0: raise ThreeDOError(f'negative index count in piece {p.name!r}')
            need(oidx,nidx*2,'vertex index array')
            idx=list(_struct.unpack_from(f'<{nidx}H',data,oidx)) if nidx else []
            if any(k>=nv for k in idx): raise ThreeDOError(f'face in piece {p.name!r} references a vertex past {nv}')
            p.polys.append(Poly3D(color,idx,cstr(otex),pad,(u1,u2,u3)))
        return p,osib,ochild

    def chain(off,depth):
        out=[]
        while True:
            if off in seen:           # cycle guard for malformed sibling/child links
                break
            seen.add(off)
            if len(seen)>max_pieces: raise ThreeDOError(f'more than {max_pieces} pieces; file looks malformed')
            p,osib,ochild=read_one(off)
            if ochild and depth<64: p.children=chain(ochild,depth+1)
            out.append(p)
            if not osib: break
            off=osib
        return out

    roots=chain(0,0)
    if not roots: raise ThreeDOError('no root piece')
    model=Model3DO(path,roots[0])
    model.extra_roots=roots[1:]
    return model

class Model3DO:
    def __init__(self,path,root):
        self.path=path; self.root=root; self.extra_roots=[]

    def pieces(self):
        """Yield (piece, depth) for every piece in tree order."""
        for r in [self.root]+self.extra_roots:
            yield from _walk(r)

    def origin_of(self,target):
        """World origin of a piece (its pivot, after every ancestor's offset and pending rotation), or None if not in this model."""
        loc=locate(self,target)
        return None if loc is None else loc[1]

    def flat_faces(self,keep=None):
        """Every polygon of the kept pieces, in world space: list of (piece, poly_index, [(x,y,z)...], color, texture).
        Each piece's vertices are local to its origin; origins and pending rotations compose down the tree.
        keep: optional set of id(piece) to include; pieces not in it are skipped (children still count)."""
        out=[]
        def fn(p,A,origin,Ap):
            if keep is None or id(p) in keep:
                vs=[(origin[0]+w[0],origin[1]+w[1],origin[2]+w[2]) for w in (m_apply(Ap,v) for v in p.verts)]
                for pi,poly in enumerate(p.polys):
                    if len(poly.idx)<3: continue
                    out.append((p,pi,[vs[k] for k in poly.idx],poly.color,poly.tex))
        frames([self.root]+self.extra_roots,fn)
        return out

    def flat_triangles(self,keep=None):
        """Fan-triangulated faces: list of (piece_name, color, texture_name, [(x,y,z)*3], face_index_count)."""
        out=[]
        for p,pi,poly_verts,color,tex in self.flat_faces(keep):
            for k in range(1,len(poly_verts)-1):
                out.append((p.name,color,tex,(poly_verts[0],poly_verts[k],poly_verts[k+1]),len(poly_verts)))
        return out

    def bounds(self):
        xs=[];ys=[];zs=[]
        for _,_,_,tri,_ in self.flat_triangles():
            for x,y,z in tri: xs.append(x); ys.append(y); zs.append(z)
        if not xs: return None
        return (min(xs),min(ys),min(zs)),(max(xs),max(ys),max(zs))

    def part_bounds(self,piece):
        """World bounds (lo,hi) of a piece and its descendants, or None if they have no faces."""
        ids={id(p) for p,_ in _walk(piece)}
        pts=[v for _,_,vs,_,_ in self.flat_faces(keep=ids) for v in vs]
        if not pts: return None
        return (tuple(min(q[i] for q in pts) for i in range(3)),tuple(max(q[i] for q in pts) for i in range(3)))

    def summary(self):
        pieces=list(self.pieces())
        npoly=sum(len(p.polys) for p,_ in pieces)
        nvert=sum(len(p.verts) for p,_ in pieces)
        return dict(pieces=len(pieces),verts=nvert,polys=npoly)

# ---- 3DO writer ----
# Mirrors read_3do. Every number goes back as the raw integer it was read from (positions are raw / 65536),
# so parse -> write -> parse reproduces the same tree. Saves are atomic: the bytes are encoded and validated
# before anything touches disk, the previous file is kept as <path>.bak, and the new file is re-read and
# compared with the in-memory tree. A mismatch restores the previous file's bytes.
import os as _os
_ALONG_SCALE=65536.0
_MAX_NAME=31
_MAX_PIECES=4096
_I32=(-2**31,2**31-1)

def _raw(v):
    f=float(v)*_ALONG_SCALE
    if f!=f or f in (float('inf'),float('-inf')): raise ThreeDOError(f'non-finite coordinate {v!r}')
    return int(round(f))

def _al4(n): return (n+3)&~3

def _name_bytes(s,what):
    try: b=s.encode('latin1')
    except UnicodeEncodeError: raise ThreeDOError(f'{what} {s!r} has characters outside Latin-1')
    if len(b)>_MAX_NAME: raise ThreeDOError(f'{what} {s!r} is longer than {_MAX_NAME} characters')
    return b

def _all_pieces(roots):
    out=[]
    def visit(p):
        out.append(p)
        for c in p.children: visit(c)
    for r in roots: visit(r)
    return out

def validate_3do(roots):
    """Raises ThreeDOError for anything the format cannot hold. Returns warnings as (part, face index or None, message)."""
    warnings=[]
    pieces=_all_pieces(roots)
    if not pieces: raise ThreeDOError('the model has no parts')
    if len(pieces)>_MAX_PIECES: raise ThreeDOError(f'{len(pieces)} parts; the format allows {_MAX_PIECES}')
    for p in pieces:
        _name_bytes(p.name,'part name')
        if not p.name: warnings.append((p.name,None,'part has no name'))
        if len(p.verts)>65535: raise ThreeDOError(f'part {p.name!r} has more than 65535 vertices')
        for c in list(p.offset)+[x for v in p.verts for x in v]: _raw(c)
        for pi,poly in enumerate(p.polys):
            if not (_I32[0]<=poly.color<=_I32[1]): raise ThreeDOError(f'part {p.name!r} face {pi}: colour out of range')
            for k in poly.idx:
                if not 0<=k<len(p.verts): raise ThreeDOError(f'part {p.name!r} face {pi} uses vertex {k} of {len(p.verts)}')
            if poly.tex: _name_bytes(poly.tex,'texture name')
            if len(poly.idx)<3: warnings.append((p.name,pi,'face with fewer than three points'))
            elif len(poly.idx)==3: warnings.append((p.name,pi,'three-point face'))
    return warnings

def encode_3do(roots):
    """Serialise a model (roots = [root]+extra_roots) to .3do bytes. Returns (data, warnings)."""
    warnings=validate_3do(roots)
    order=_all_pieces(roots)
    addr=0; hdr={}; nam={}; vtx={}; prm={}; idx={}; txa={}
    for p in order:
        hdr[id(p)]=addr; addr+=52
        nam[id(p)]=addr; addr+=32
        vtx[id(p)]=addr; addr+=12*len(p.verts)
        prm[id(p)]=addr; addr+=32*len(p.polys)
    for p in order:
        for k,poly in enumerate(p.polys):
            idx[(id(p),k)]=addr; addr=_al4(addr+2*len(poly.idx))
            if poly.tex and poly.tex not in txa:
                txa[poly.tex]=addr; addr=_al4(addr+len(poly.tex.encode('latin1'))+1)
    buf=bytearray(addr)
    def emit(lst):
        for i,p in enumerate(lst):
            osib=hdr[id(lst[i+1])] if i+1<len(lst) else 0
            ochild=hdr[id(p.children[0])] if p.children else 0
            pid=id(p)
            _struct.pack_into('<13l',buf,hdr[pid],p.version,len(p.verts),len(p.polys),p.flag,
                              _raw(p.offset[0]),_raw(p.offset[1]),_raw(p.offset[2]),
                              nam[pid],0,vtx[pid],prm[pid],osib,ochild)
            buf[nam[pid]:nam[pid]+32]=p.name.encode('latin1').ljust(32,b'\0')
            for j,v in enumerate(p.verts):
                _struct.pack_into('<3l',buf,vtx[pid]+12*j,_raw(v[0]),_raw(v[1]),_raw(v[2]))
            for k,poly in enumerate(p.polys):
                ia=idx[(pid,k)]
                ta=txa[poly.tex] if poly.tex else 0
                _struct.pack_into('<8l',buf,prm[pid]+32*k,poly.color,len(poly.idx),poly.pad,ia,ta,*poly.unk)
                _struct.pack_into(f'<{len(poly.idx)}H',buf,ia,*poly.idx)
            emit(p.children)
    emit(roots)
    for text,a in txa.items():
        tb=text.encode('latin1'); buf[a:a+len(tb)+1]=tb+b'\0'
    return bytes(buf),warnings

def tree_signature(roots):
    """Everything the file holds, in file order, as plain values. Two trees with equal signatures write identical bytes."""
    sig=[]
    for p in _all_pieces(roots):
        sig.append((p.name,tuple(_raw(c) for c in p.offset),tuple(tuple(_raw(c) for c in v) for v in p.verts),
                    tuple((q.color,tuple(q.idx),q.tex,q.pad,tuple(q.unk)) for q in p.polys),
                    p.version,p.flag,len(p.children)))
    return sig

def state_signature(roots):
    """tree_signature plus each part's pending rotation: the undo and unsaved-change check (pending state is not in the file)."""
    return (tree_signature(roots),tuple(None if p.pend is None else tuple(p.pend) for p in _all_pieces(roots)))

def save_3do(roots,path,backup=True):
    """Atomic, verified save. Returns the warnings from validate_3do. Raises ThreeDOError (file left as it was) on failure."""
    data,warn=encode_3do(roots)
    prior=None
    if _os.path.exists(path):
        with open(path,'rb') as f: prior=f.read()
        if backup:
            with open(path+'.bak','wb') as f: f.write(prior)
    tmp=path+'.tmp'
    try:
        with open(tmp,'wb') as f:
            f.write(data); f.flush(); _os.fsync(f.fileno())
        _os.replace(tmp,path)
    except OSError as e:
        try: _os.remove(tmp)
        except OSError: pass
        raise ThreeDOError(f'could not write {path}: {e}')
    try:
        back=read_3do(path)
        good=tree_signature([back.root]+back.extra_roots)==tree_signature(roots)
        err=None
    except ThreeDOError as e:
        good=False; err=str(e)
    if not good:
        if prior is not None:
            with open(path,'wb') as f: f.write(prior)
        else:
            _os.remove(path)
        raise ThreeDOError('verification after writing failed'+(f' ({err})' if err else '')+'; the previous file was restored')
    return warn

# ---- autosave and file helpers ----
import copy as _copy, uuid as _uuid
AUTOSAVE_DIR=_os.path.join(_os.path.expanduser('~'),'.bostool_autosave')

def new_untitled_id(): return _uuid.uuid4().hex[:8]

def copy_piece_tree(p): return _copy.deepcopy(p)

def autosave_target(path,untitled_id=None):
    """Autosave file for a model: <path>.autosave beside the file, or a per-window file for an untitled model."""
    if path: return path+'.autosave'
    try: _os.makedirs(AUTOSAVE_DIR,exist_ok=True)
    except OSError as e: raise ThreeDOError(f'cannot create {AUTOSAVE_DIR}: {e}')
    return _os.path.join(AUTOSAVE_DIR,f'untitled-{untitled_id or "session"}.3do.autosave')

# ---- .3dox project: the working state beside a model ----
# A project is a .3dox file: pending rotations now; timeline, tracks, clips and driver later. It names the .3do it belongs
# to (its absolute path, 'model') and records a digest of the base tree it was made against ('base'). The .3do is the
# base the engine reads; the project holds everything not yet committed. Every open or save writes a project; a .3do
# opened with no project beside it gets an empty one.
import json as _json, hashlib as _hashlib
PROJECT_FORMAT='bostool-3dox'; PROJECT_VERSION=1

class ProjectError(ThreeDOError):
    """A model or project could not be opened, and nothing was loaded. kind is one of:
    bad_3do, bad_3dox, no_3do, ambiguous, mismatch, unreconcilable. candidates lists the files involved."""
    def __init__(self,kind,message,candidates=None):
        super().__init__(message); self.kind=kind; self.candidates=list(candidates or [])

class Bundle:
    """What opening a model or project produced. note is a human message (a created project, say), or None."""
    def __init__(self,model,model_file,project_file,pending,note=None,seqs=None,active=0,output=None):
        self.model=model; self.model_file=model_file; self.project_file=project_file; self.pending=pending; self.note=note
        self.seqs=seqs      # [{'name','anim'}] with each anim checked (normalize_anim form), or None when there is no project
        self.active=active  # index of the sequence that is selected
        self.output=output  # the animation output file recorded in the project, or None
        self.anim=seqs[active]['anim'] if seqs else None

def sidecar_path(path):
    """unit.3do -> unit.3dox. Any other name (an autosave file, say) gets .3dox appended."""
    base=path[:-4] if path.lower().endswith('.3do') else path
    return base+'.3dox'

def _roots_paths(roots):
    """[(path, piece)] over a list of root pieces; path is (root index, child index, ...)."""
    out=[]
    def visit(p,path):
        out.append((path,p))
        for i,c in enumerate(p.children): visit(c,path+(i,))
    for ri,r in enumerate(roots): visit(r,(ri,))
    return out

def base_signature(roots):
    return _hashlib.sha256(repr(tree_signature(roots)).encode('utf-8')).hexdigest()

def find_projects(model_path):
    """Project files for a .3do: names matching its project name case-insensitively in its folder. More than one is an error."""
    d=_os.path.dirname(_os.path.abspath(model_path)); want=_os.path.basename(sidecar_path(model_path)).lower()
    try: names=_os.listdir(d)
    except OSError: return []
    return [_os.path.join(d,n) for n in sorted(names) if n.lower()==want]

def find_model(project_path,ref):
    """The .3do a project names: the recorded path if it exists, otherwise a same-named .3do beside the project."""
    if ref and _os.path.isfile(ref): return ref
    d=_os.path.dirname(_os.path.abspath(project_path))
    base=_os.path.basename(ref) if ref else _os.path.basename(project_path)[:-1]     # x.3dox -> x.3do
    try: names=_os.listdir(d)
    except OSError: names=[]
    hits=[_os.path.join(d,n) for n in sorted(names) if n.lower()==base.lower() and n.lower().endswith('.3do')]
    if len(hits)>1: raise ProjectError('ambiguous',f'More than one model matches {base}.',hits)
    if hits: return hits[0]
    raise ProjectError('no_3do',f'The model this project refers to ({ref or base}) was not found.',[ref] if ref else [])

def read_project(project_path):
    name=_os.path.basename(project_path)
    try:
        with open(project_path,'r',encoding='utf-8') as f: doc=_json.load(f)
    except (OSError,ValueError) as e:
        raise ProjectError('bad_3dox',f'{name} could not be read: {e}',[project_path])
    if not isinstance(doc,dict) or doc.get('format')!=PROJECT_FORMAT:
        raise ProjectError('bad_3dox',f'{name} is not an Advanced Model Factory project file.',[project_path])
    if doc.get('version')!=PROJECT_VERSION:
        raise ProjectError('bad_3dox',f'{name} is project version {doc.get("version")}; this build reads version {PROJECT_VERSION}.',[project_path])
    return doc

def write_project(project_path,roots,model_path,anim=None,sequences=None,active=0,output=None):
    """Writes the project for a model: pending rotations keyed by part path, bound to the base tree in roots (the tree
    just written to model_path), and the animation sequences: a list of {'name','timeline','tracks'} (JSON form) with
    the selected index. anim, when given without sequences, is written as one sequence. Atomic and verified by
    re-reading. Raises ThreeDOError."""
    name=_os.path.basename(project_path)
    items=[{'path':list(pth),'q':[float(c) for c in p.pend]} for pth,p in _roots_paths(roots) if p.pend is not None]
    if sequences is None:
        a=anim or {}
        sequences=[{'name':'Sequence 1','timeline':a.get('timeline') or dict(DEFAULT_TIMELINE),'tracks':a.get('tracks') or {}}]
    if not sequences or not 0<=active<len(sequences): raise ThreeDOError('the project needs at least one sequence and a valid selection')
    cur=sequences[active]
    doc={'format':PROJECT_FORMAT,'version':PROJECT_VERSION,'model':_os.path.abspath(model_path),
         'base':base_signature(roots),'pending':items,'timeline':cur['timeline'],'tracks':cur['tracks'],
         'clips':[{'name':q['name'],'timeline':q['timeline'],'tracks':q['tracks']} for q in sequences],
         'active':int(active),'output':output,'driver':'base'}
    text=_json.dumps(doc,indent=1,sort_keys=True)
    tmp=project_path+'.tmp'
    try:
        with open(tmp,'w',encoding='utf-8') as f:
            f.write(text); f.flush(); _os.fsync(f.fileno())
        with open(tmp,'r',encoding='utf-8') as f:
            if _json.load(f)!=_json.loads(text): raise ThreeDOError(f'{name} did not verify on re-read')
        _os.replace(tmp,project_path)
    except (OSError,ThreeDOError) as e:
        try: _os.remove(tmp)
        except OSError: pass
        if isinstance(e,ThreeDOError): raise
        raise ThreeDOError(f'could not write {name}: {e}')

def attach_project(roots,project_path,doc):
    """Applies a project's pending rotations to roots (a tree just read from its .3do). All or nothing.
    Returns the number applied. Raises ProjectError: mismatch if the base differs, unreconcilable if entries do not fit."""
    name=_os.path.basename(project_path)
    if doc.get('base')!=base_signature(roots):
        raise ProjectError('mismatch',f'{name} was saved against a different version of its .3do (the base digest does not match). '
                           'Nothing was loaded. Open the .3do the project was made for, or re-save the project from the current model.',[project_path])
    entries=doc.get('pending',[])
    if not isinstance(entries,list): raise ProjectError('unreconcilable',f'{name} has a malformed pending list. Nothing was loaded.',[project_path])
    by_path=dict(_roots_paths(roots)); todo=[]
    for it in entries:
        try:
            pth=tuple(int(i) for i in it['path'])
            qq=tuple(float(c) for c in it['q'])
            if len(qq)!=4: raise ValueError('quaternion needs 4 values')
            q=q_norm(qq)
        except (KeyError,TypeError,ValueError,ThreeDOError):
            raise ProjectError('unreconcilable',f'{name} has a bad pending entry. Nothing was loaded.',[project_path])
        if pth not in by_path:
            raise ProjectError('unreconcilable',f'{name} refers to part {list(pth)}, which the model does not have. Nothing was loaded.',[project_path])
        todo.append((by_path[pth],q))
    for p,q in todo: p.pend=q
    return len(todo)

def _project_seqs(doc,project_file):
    """The animation sequences a project holds: ([{'name','anim'}], selected index), each checked by the animation
    module. A project written before sequences existed has one sequence from its timeline and tracks, or the default.
    Invalid data raises ProjectError (kind bad_3dox)."""
    name=_os.path.basename(project_file)
    def bad(why): return ProjectError('bad_3dox',f'{name} holds animation data that does not check out: {why}',[project_file])
    raw=doc.get('clips')
    try:
        if isinstance(raw,list) and raw:
            seqs=[]; names=set()
            for q in raw:
                if not isinstance(q,dict): raise ValueError('a sequence is not an object')
                nm=str(q.get('name') or '').strip()
                if not nm: raise ValueError('a sequence has no name')
                if nm.lower() in names: raise ValueError(f'two sequences are named {nm!r}')
                names.add(nm.lower())
                seqs.append({'name':nm,'anim':normalize_anim({'timeline':q.get('timeline'),'tracks':q.get('tracks')})})
            active=doc.get('active',0)
            if not isinstance(active,int) or isinstance(active,bool) or not 0<=active<len(seqs):
                raise ValueError('the selected sequence does not exist')
            return seqs,active
        if doc.get('timeline') is None and not doc.get('tracks'):
            return [{'name':'Sequence 1','anim':normalize_anim(None)}],0
        return [{'name':'Sequence 1','anim':normalize_anim({'timeline':doc.get('timeline'),'tracks':doc.get('tracks')})}],0
    except (ValueError,KeyError,TypeError) as e:
        raise bad(e)

def _read_model(path):
    try: return read_3do(path)
    except (ThreeDOError,OSError) as e:
        raise ProjectError('bad_3do',f'{_os.path.basename(path)} could not be read: {e}',[path])

def open_bundle(path,model_path=None):
    """Opens a .3do or a .3dox with its project. model_path names the .3do explicitly (used after the user locates a
    missing one). Raises ProjectError; nothing is returned unless the model and its project both check out.
    A .3do with no project beside it gets a new, empty one."""
    if path.lower().endswith('.3dox'):
        project_file=path; doc=read_project(path)
        model_file=model_path or find_model(path,doc.get('model'))
    else:
        model_file=model_path or path
        hits=find_projects(model_file)
        if len(hits)>1: raise ProjectError('ambiguous',f'More than one project file matches {_os.path.basename(model_file)}.',hits)
        project_file=hits[0] if hits else None
        doc=read_project(project_file) if project_file else None
    m=_read_model(model_file)
    m.path=model_file
    roots=[m.root]+m.extra_roots
    if doc is not None:
        seqs,active=_project_seqs(doc,project_file)   # checked before anything is applied, so bad data halts the load
        n=attach_project(roots,project_file,doc)
        return Bundle(m,model_file,project_file,n,seqs=seqs,active=active,output=doc.get('output'))
    project_file=sidecar_path(model_file)
    try:
        write_project(project_file,roots,model_file)
        return Bundle(m,model_file,project_file,0,f'Created {_os.path.basename(project_file)}')
    except ThreeDOError as e:
        return Bundle(m,model_file,None,0,f'No project file: {e}')

def open_recovery(model_file,autosave_file):
    """Opens an autosave in place of model_file, applying the autosave's own project (written beside it)."""
    m=_read_model(autosave_file)
    m.path=model_file
    roots=[m.root]+m.extra_roots
    ap=sidecar_path(autosave_file)
    if _os.path.exists(ap):
        doc=read_project(ap); seqs,active=_project_seqs(doc,ap)
        n=attach_project(roots,ap,doc)
        return Bundle(m,model_file,sidecar_path(model_file),n,seqs=seqs,active=active,output=doc.get('output'))
    return Bundle(m,model_file,sidecar_path(model_file),0,seqs=[{'name':'Sequence 1','anim':normalize_anim(None)}])

def write_autosave(roots,target):
    """Atomic write of the in-memory model to its autosave file (no .bak, no verification pass)."""
    data,_=encode_3do(roots)
    tmp=target+'.tmp'
    try:
        with open(tmp,'wb') as f:
            f.write(data); f.flush(); _os.fsync(f.fileno())
        _os.replace(tmp,target)
    except OSError as e:
        try: _os.remove(tmp)
        except OSError: pass
        raise ThreeDOError(f'autosave failed: {e}')

def recovery_for(path):
    """The autosave file for path if it is newer than the saved file, otherwise None."""
    if not path: return None
    try:
        t=autosave_target(path)
        if not _os.path.exists(t): return None
        if _os.path.exists(path) and _os.path.getmtime(t)<=_os.path.getmtime(path): return None
        return t
    except (OSError,ThreeDOError): return None

def discard_autosave(path,untitled_id=None):
    """Removes the autosave for a model (after a save, or when the user throws the changes away)."""
    try:
        t=autosave_target(path,untitled_id)
        for f in (t,sidecar_path(t)):
            if _os.path.exists(f): _os.remove(f)
    except (OSError,ThreeDOError): pass

# ---- export: Wavefront OBJ (+MTL), ASCII DXF (3DFACE), LightWave object (LWOB) ----
# Coordinates are world TA units, as the 3D viewport shows them. Pieces with no faces are skipped and counted.
import re as _re
EXPORT_FORMATS={'obj':'Wavefront OBJ','dxf':'AutoCAD DXF (3DFACE)','lwo':'LightWave object (LWOB)','3do':'3DO (one part, with children)'}

def _atomic_write(path,data):
    tmp=path+'.tmp'
    try:
        with open(tmp,'wb') as f:
            f.write(data); f.flush(); _os.fsync(f.fileno())
        _os.replace(tmp,path)
    except OSError as e:
        try: _os.remove(tmp)
        except OSError: pass
        raise ThreeDOError(f'could not write {path}: {e}')

def _export_scope(model,piece):
    """Faces of the whole model (piece None) or of one piece and its children: (faces, skipped) where faces = [(name, [(verts, colour)...])]."""
    roots=[model.root]+model.extra_roots
    if piece is None:
        pieces=_all_pieces(roots); keep=None
    else:
        pieces=_all_pieces([piece]); keep={id(p) for p in pieces}
    groups={}; order=[]
    for p,pi,verts,color,tex in model.flat_faces(keep):
        if id(p) not in groups:
            groups[id(p)]=(p.name,[]); order.append(id(p))
        groups[id(p)][1].append((verts,color))
    faces=[groups[i] for i in order]
    return faces, len(pieces)-len(faces)

def _safe_name(s,used):
    base=_re.sub(r'[^A-Za-z0-9_-]','_',s or '') or 'part'
    name=base; n=2
    while name in used: name=f'{base}_{n}'; n+=1
    used.add(name); return name

def _pal_rgb(palette,c):
    if palette and 0<=c<=255: return tuple(v/255.0 for v in palette[c])
    return (0.7,0.7,0.7)

def _obj_files(faces,path,palette):
    mtl=_os.path.splitext(path)[0]+'.mtl'
    out=['# Advanced Model Factory export; TA units, as the 3D viewport shows them',f'mtllib {_os.path.basename(mtl)}']
    used=set(); nv=0; colours=set()
    for name,polys in faces:
        out.append(f'o {_safe_name(name,used)}')
        for verts,color in polys:
            colours.add(color); out.append(f'usemtl c{color}')
            base=nv
            for x,y,z in verts:
                out.append(f'v {x:.6f} {y:.6f} {z:.6f}'); nv+=1
            out.append('f '+' '.join(str(base+k+1) for k in range(len(verts))))
    mlines=[]
    for c in sorted(colours):
        r,g,b=_pal_rgb(palette,c)
        mlines+=[f'newmtl c{c}',f'Kd {r:.4f} {g:.4f} {b:.4f}','']
    return [(path,('\n'.join(out)+'\n').encode('latin1')),(mtl,('\n'.join(mlines)+'\n').encode('latin1'))]

def _dxf_files(faces,path):
    used={'0'}; layers=[]; ents=[]
    for name,polys in faces:
        layer=_safe_name(name,used); layers.append(layer)
        for verts,_ in polys:
            for k in range(1,len(verts)-1):
                tri=(verts[0],verts[k],verts[k+1],verts[k+1])   # 3DFACE takes four corners; a triangle repeats one
                ents+=['0','3DFACE','8',layer]
                for i,(x,y,z) in enumerate(tri):
                    ents+=[str(10+i),f'{x:.6f}',str(20+i),f'{y:.6f}',str(30+i),f'{z:.6f}']
    lines=['0','SECTION','2','HEADER','9','$ACADVER','1','AC1009','0','ENDSEC',
           '0','SECTION','2','TABLES','0','TABLE','2','LAYER','70',str(len(layers)+1),
           '0','LAYER','2','0','70','0','62','7','6','CONTINUOUS']
    for layer in layers:
        lines+=['0','LAYER','2',layer,'70','0','62','7','6','CONTINUOUS']
    lines+=['0','ENDTAB','0','ENDSEC','0','SECTION','2','ENTITIES']+ents+['0','ENDSEC','0','EOF']
    return [(path,('\n'.join(lines)+'\n').encode('latin1'))]

def _s0(s):
    b=s.encode('latin1')+b'\0'
    return b+(b'\0' if len(b)&1 else b'')

def _lwob_files(faces,path):
    pts=[]; index={}; srfs=[]; srf_index={}; polys=[]
    for name,plist in faces:
        for verts,color in plist:
            sname=f'pal{color}' if 0<=color<=255 else f'col{color}'
            if sname not in srf_index:
                srfs.append(sname); srf_index[sname]=len(srfs)
            idx=[]
            for x,y,z in verts:
                key=(x,y,z)
                if key not in index:
                    index[key]=len(pts); pts.append(key)
                idx.append(index[key])
            if len(idx)>65535: raise ThreeDOError('a face has more than 65535 corners')
            polys.append((idx,srf_index[sname]))
    if len(pts)>65535: raise ThreeDOError(f'{len(pts)} points; LWOB allows 65535 per object')
    def chunk(cid,body):
        return cid+_struct.pack('>I',len(body))+body+(b'\0' if len(body)&1 else b'')
    pnts=b''.join(_struct.pack('>3f',*p) for p in pts)
    srfs_b=b''.join(_s0(s) for s in srfs)
    pols=b''.join(_struct.pack('>H',len(i))+_struct.pack(f'>{len(i)}H',*i)+_struct.pack('>H',s) for i,s in polys)
    body=b'LWOB'+chunk(b'PNTS',pnts)+chunk(b'SRFS',srfs_b)+chunk(b'POLS',pols)
    return [(path,b'FORM'+_struct.pack('>I',len(body))+body)]

def export_3d(model,piece,path,fmt,palette=None):
    """Writes the whole model (piece None) or one piece with its children. fmt is 'obj', 'dxf' or 'lwo'.
    Returns (faces written, pieces skipped for having no faces). Raises ThreeDOError; nothing is left half-written."""
    fmt=(fmt or '').lower()
    if fmt not in EXPORT_FORMATS: raise ThreeDOError(f'unknown export format {fmt!r}')
    if fmt=='3do':
        if piece is None: raise ThreeDOError('the 3DO format writes one part: select a part first')
        faces,skipped=_export_scope(model,piece)
        save_3do([copy_piece_tree(piece)],path)
        return sum(len(p) for _,p in faces), skipped
    faces,skipped=_export_scope(model,piece)
    if not faces: raise ThreeDOError('nothing to export: the chosen scope has no faces')
    if fmt=='obj': files=_obj_files(faces,path,palette)
    elif fmt=='dxf': files=_dxf_files(faces,path)
    else: files=_lwob_files(faces,path)
    for p,data in files: _atomic_write(p,data)
    return sum(len(p) for _,p in faces), skipped

# ---- hierarchy editing ----
# Vertices are local to their piece's origin, so moving an origin or reparenting never touches stored vertex
# positions except where an origin edit has to compensate. Offsets are quantised to the file's 1/65536 grid.
def _q(v): return round(float(v)*65536.0)/65536.0

def _is_within(piece,candidate):
    return any(q is candidate for q in _all_pieces([piece]))

def _parent_of(model,target):
    """Parent of target, or None when target is a top-level root. Raises if target is not in the model."""
    if target is model.root or any(r is target for r in model.extra_roots): return None
    def visit(p):
        for c in p.children:
            if c is target: return p
            q=visit(c)
            if q is not None: return q
        return None
    for r in [model.root]+model.extra_roots:
        q=visit(r)
        if q is not None: return q
    raise ThreeDOError('part is not in this model')

def reparent(model,piece,new_parent):
    """Moves piece (with its children) under new_parent, or to the top level when new_parent is None.
    Its world position stays where it was; only its offset changes. The base part cannot be moved."""
    if piece is model.root: raise ThreeDOError('the base part stays at the top of the model')
    loc=locate(model,piece)
    if loc is None: raise ThreeDOError('part is not in this model')
    _,world,_=loc
    absR=m_mul(loc[0],_pend_m(piece))           # the piece's world rotation, kept through the move
    if new_parent is not None:
        if locate(model,new_parent) is None: raise ThreeDOError('the target part is not in this model')
        if _is_within(piece,new_parent): raise ThreeDOError('a part cannot be moved under itself or one of its own children')
    if any(r is piece for r in model.extra_roots):
        model.extra_roots=[r for r in model.extra_roots if r is not piece]
    else:
        par=_parent_of(model,piece)
        par.children=[c for c in par.children if c is not piece]
    if new_parent is None:
        model.extra_roots.append(piece)
        A_new,pw=_I3,(0.0,0.0,0.0)
    else:
        _,pw,A_new=locate(model,new_parent)     # the new parent's own frame is what the offset is written in
        new_parent.children.append(piece)
    dl=m_apply(m_T(A_new),tuple(world[i]-pw[i] for i in range(3)))
    piece.offset=tuple(_q(c) for c in dl)
    rel=m_mul(m_T(A_new),absR)                  # same world orientation, now relative to the new parent
    q=m_to_q(rel)
    piece.pend=None if abs(abs(q[0])-1.0)<1e-9 else q

def set_origin(model,piece,new_origin):
    """Moves a piece's origin (its pivot) to a world position. Its geometry and child parts stay where they are."""
    loc=locate(model,piece)
    if loc is None: raise ThreeDOError('part is not in this model')
    A_par,cur,A_p=loc
    d=[_q(new_origin[i]-cur[i]) for i in range(3)]
    if d==[0.0,0.0,0.0]: return
    dp=m_apply(m_T(A_par),d)        # the piece's offset is written in its parent's frame
    dl=m_apply(m_T(A_p),d)          # vertices and child offsets are written in the piece's own frame
    piece.offset=tuple(_q(piece.offset[i]+dp[i]) for i in range(3))
    piece.verts=[tuple(_q(v[i]-dl[i]) for i in range(3)) for v in piece.verts]
    for c in piece.children:
        c.offset=tuple(_q(c.offset[i]-dl[i]) for i in range(3))

# ---- tree paths, copies and rigid transforms (gizmos and undo) ----
# A 3DO has no rotation field: a part's pose is its offset plus its vertices, so turning a part bakes the turn
# into its vertices and its children's offsets. Everything stays on the 1/65536 grid the writer uses.
import math as _m3
def copy_roots(roots): return _copy.deepcopy(list(roots))

def piece_paths(model):
    """[(path, piece)] for every piece in tree order. A path is (root index, child index, ...); index 0 is the base part."""
    out=[]
    def visit(p,path):
        out.append((path,p))
        for i,c in enumerate(p.children): visit(c,path+(i,))
    for ri,r in enumerate([model.root]+model.extra_roots): visit(r,(ri,))
    return out

def piece_at_path(model,path):
    roots=[model.root]+model.extra_roots
    if not path or path[0]>=len(roots): return None
    p=roots[path[0]]
    for i in path[1:]:
        if i>=len(p.children): return None
        p=p.children[i]
    return p

def translate_part(piece,d,model=None):
    """Moves a part and everything under it: only its own offset changes. d is in world units; given the model, it is
    converted into the parent's frame (needed when an ancestor carries a pending rotation)."""
    if model is not None:
        loc=locate(model,piece)
        if loc is None: raise ThreeDOError('part is not in this model')
        d=m_apply(m_T(loc[0]),d)
    piece.offset=tuple(_q(piece.offset[i]+d[i]) for i in range(3))

def _rot_matrix(axis,angle):
    x,y,z=axis; c=_m3.cos(angle); s=_m3.sin(angle); t=1.0-c
    return ((t*x*x+c,t*x*y-s*z,t*x*z+s*y),(t*x*y+s*z,t*y*y+c,t*y*z-s*x),(t*x*z-s*y,t*y*z+s*x,t*z*z+c))

def _rot_apply(M,v):
    return tuple(_q(M[r][0]*v[0]+M[r][1]*v[1]+M[r][2]*v[2]) for r in range(3))

# ---- pose math: pending rotations are unit quaternions (w,x,y,z); matrices are 3x3 row tuples ----
_I3=((1.0,0.0,0.0),(0.0,1.0,0.0),(0.0,0.0,1.0))
_QI=(1.0,0.0,0.0,0.0)

def q_norm(q):
    n=_m3.sqrt(sum(c*c for c in q))
    if n==0: raise ThreeDOError('zero quaternion')
    return tuple(c/n for c in q)

def q_mul(a,b):
    """Hamilton product: q_mul(a,b) matches the rotation matrix of a times that of b (b turns first)."""
    aw,ax,ay,az=a; bw,bx,by,bz=b
    return (aw*bw-ax*bx-ay*by-az*bz, aw*bx+ax*bw+ay*bz-az*by, aw*by-ax*bz+ay*bw+az*bx, aw*bz+ax*by-ay*bx+az*bw)

def q_axis_angle(axis,angle):
    s=_m3.sin(angle/2.0)
    return (_m3.cos(angle/2.0),axis[0]*s,axis[1]*s,axis[2]*s)

def q_to_m(q):
    w,x,y,z=q_norm(q)
    return ((1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)),
            (2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)),
            (2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)))

def m_to_q(M):
    tr=M[0][0]+M[1][1]+M[2][2]
    if tr>0:
        s=_m3.sqrt(tr+1.0)*2; w=0.25*s; x=(M[2][1]-M[1][2])/s; y=(M[0][2]-M[2][0])/s; z=(M[1][0]-M[0][1])/s
    elif M[0][0]>M[1][1] and M[0][0]>M[2][2]:
        s=_m3.sqrt(1.0+M[0][0]-M[1][1]-M[2][2])*2; w=(M[2][1]-M[1][2])/s; x=0.25*s; y=(M[0][1]+M[1][0])/s; z=(M[0][2]+M[2][0])/s
    elif M[1][1]>M[2][2]:
        s=_m3.sqrt(1.0+M[1][1]-M[0][0]-M[2][2])*2; w=(M[0][2]-M[2][0])/s; x=(M[0][1]+M[1][0])/s; y=0.25*s; z=(M[1][2]+M[2][1])/s
    else:
        s=_m3.sqrt(1.0+M[2][2]-M[0][0]-M[1][1])*2; w=(M[1][0]-M[0][1])/s; x=(M[0][2]+M[2][0])/s; y=(M[1][2]+M[2][1])/s; z=0.25*s
    q=q_norm((w,x,y,z))
    return q if q[0]>=0 else tuple(-c for c in q)

def m_mul(A,B): return tuple(tuple(sum(A[i][k]*B[k][j] for k in range(3)) for j in range(3)) for i in range(3))
def m_T(A): return tuple(tuple(A[j][i] for j in range(3)) for i in range(3))
def m_apply(M,v): return tuple(M[r][0]*v[0]+M[r][1]*v[1]+M[r][2]*v[2] for r in range(3))
def _pend_m(p): return _I3 if p.pend is None else q_to_m(p.pend)

def frames(roots,fn):
    """Walks the trees with world transforms composed down the hierarchy, parents first. Calls
    fn(piece, A_parent, origin, A_piece) for every piece: origin is the world position of the piece's pivot, A_parent
    is the rotation of the frame its offset is written in, and a vertex v of the piece sits at origin + A_piece·v."""
    def visit(p,A,b):
        o=m_apply(A,p.offset)
        origin=(b[0]+o[0],b[1]+o[1],b[2]+o[2])
        Ap=m_mul(A,_pend_m(p))
        fn(p,A,origin,Ap)
        for c in p.children: visit(c,Ap,origin)
    for r in roots: visit(r,_I3,(0.0,0.0,0.0))

def locate(model,target):
    """(A_parent, origin, A_piece) of a piece in world space, or None if it is not in the model."""
    found=[]
    def fn(p,A,origin,Ap):
        if p is target: found.append((A,origin,Ap))
    frames([model.root]+model.extra_roots,fn)
    return found[0] if found else None

def turn_pending(model,piece,axis,angle):
    """Turns a part about its own origin by angle (radians) around a world-space unit axis. The turn is kept as a pending
    rotation on the part, so the geometry is untouched until it is committed. It composes with any pending rotation already there."""
    loc=locate(model,piece)
    if loc is None: raise ThreeDOError('part is not in this model')
    a=m_apply(m_T(loc[0]),axis)                 # the world axis, written in the parent's frame
    piece.pend=q_norm(q_mul(q_axis_angle(a,angle),piece.pend or _QI))

def commit_pend(piece):
    """Bakes one part's pending rotation into its geometry, on the 1/65536 grid. Its vertices turn about its origin and
    its child offsets turn with them; each child's pending rotation is composed with the one just baked, so the world pose
    is unchanged apart from grid rounding. Returns the largest rounding error, in TA units."""
    if piece.pend is None: return 0.0
    M=q_to_m(piece.pend); err=[0.0]
    def snap(v):
        r=m_apply(M,v); out=tuple(_q(c) for c in r)
        err[0]=max([err[0]]+[abs(out[i]-r[i]) for i in range(3)])
        return out
    piece.verts=[snap(v) for v in piece.verts]
    for c in piece.children:
        c.offset=snap(c.offset)
        c.pend=piece.pend if c.pend is None else q_norm(q_mul(piece.pend,c.pend))
    piece.pend=None
    return err[0]

def commit_all(roots):
    """Commits every pending rotation in the trees, parents first. Returns the largest rounding error, in TA units."""
    err=0.0
    for r in roots:
        for p,_ in _walk(r):
            err=max(err,commit_pend(p))
    return err

def pending_count(roots):
    return sum(1 for r in roots for p,_ in _walk(r) if p.pend is not None)

def baked_copy(roots):
    """A deep copy of the trees with every pending rotation baked in: what a .3do file can hold. Returns (roots, rounding error)."""
    out=_copy.deepcopy(list(roots))
    return out,commit_all(out)

def rotate_about_origin(piece,axis,angle):
    """Turns a part and everything under it about the part's own origin (the pivot). The origin stays where it is;
    vertices and child offsets are rotated, which keeps the subtree rigid. axis must be a unit vector."""
    M=_rot_matrix(axis,angle)
    def visit(p,pivot):
        p.verts=[_rot_apply(M,v) for v in p.verts]
        if not pivot: p.offset=_rot_apply(M,p.offset)
        for c in p.children: visit(c,False)
    visit(piece,True)

def read_palette(path):
    """Read a 256-entry RGB palette (768 bytes). Returns (palette, None) or (None, reason).
    A palette whose values all fit in 6 bits (VGA style) is scaled to 8 bits."""
    try:
        with open(path,'rb') as f: b=f.read()
    except OSError as e:
        return None,f'cannot read {path}: {e.strerror or e}'
    if len(b)!=768:
        return None,f'{path} is {len(b)} bytes; a palette needs exactly 768 (256 RGB triplets)'
    vals=list(b)
    if max(vals)<=63:
        vals=[v*255//63 for v in vals]
    return [(vals[3*i],vals[3*i+1],vals[3*i+2]) for i in range(256)],None

def load_palette(path):
    """Palette list of 256 (r,g,b) tuples, or None (see read_palette for the reason)."""
    return read_palette(path)[0] if path else None
