# ---- piece editing: create, duplicate, mirror, pivot placement, and import of OBJ, DXF and LWO meshes ----
# Each function edits the model in place and raises ThreeDOError with a plain reason. The viewer calls them and records
# one undo step after each. Geometry is stored in the piece's own frame (its pivot is the origin), so an import places
# the mesh's coordinates relative to the pivot, scaled by the chosen factor.
import struct as _pstruct

def piece_names(model):
    return {p.name for p,_ in model.pieces()}

def unique_piece_name(used,base):
    """A name no other part uses, at most the 3DO's name length. Adds _2, _3 ... when needed, and records the name."""
    base=(base or '').strip() or 'part'
    base=base[:_MAX_NAME]
    name=base; n=2
    while name in used:
        suffix=f'_{n}'; name=base[:_MAX_NAME-len(suffix)]+suffix; n+=1
    used.add(name); return name

def _require_in_model(model,piece):
    if piece is None: raise ThreeDOError('select a part first')
    if locate(model,piece) is None: raise ThreeDOError('the part is not in this model')

def create_piece(model,parent,name):
    """A new empty part (no geometry) under parent, at the parent's pivot. Returns the part."""
    parent=parent or model.root
    _require_in_model(model,parent)
    p=Piece3D(unique_piece_name(piece_names(model),name),(0.0,0.0,0.0))
    parent.children.append(p)
    return p

def duplicate_piece(model,piece):
    """A copy of a part and everything under it, placed right after the original, with unique names. Returns the copy."""
    _require_in_model(model,piece)
    if piece is model.root: raise ThreeDOError('the base part cannot be duplicated')
    dup=copy_piece_tree(piece)
    used=piece_names(model)
    for p in _all_pieces([dup]): p.name=unique_piece_name(used,p.name)
    if any(r is piece for r in model.extra_roots):
        i=[k for k,r in enumerate(model.extra_roots) if r is piece][0]
        model.extra_roots.insert(i+1,dup)
    else:
        par=_parent_of(model,piece)
        i=[k for k,c in enumerate(par.children) if c is piece][0]
        par.children.insert(i+1,dup)
    return dup

def mirror_piece(model,piece,axis):
    """Mirrors a part and everything under it across the plane through its pivot, perpendicular to axis (0, 1 or 2 for
    X, Y or Z). Vertices flip, corner order is reversed so faces keep facing the same way, and every child's offset flips.
    Parts with a pending rotation under them must be committed first, because a mirrored rotation is not a rotation."""
    _require_in_model(model,piece)
    if axis not in (0,1,2): raise ThreeDOError('mirror axis must be X, Y or Z')
    sub=_all_pieces([piece])
    if any(p.pend is not None for p in sub):
        raise ThreeDOError('commit the pending rotations under this part first (Part menu), then mirror')
    for p in sub:
        p.verts=[tuple(-v[i] if i==axis else v[i] for i in range(3)) for v in p.verts]
        for poly in p.polys: poly.idx=type(poly.idx)(reversed(poly.idx))
    for p in sub[1:]:
        p.offset=tuple(-p.offset[i] if i==axis else p.offset[i] for i in range(3))

def piece_geometry_centre(model,piece):
    """The average of the part's vertex positions in world space: the centre of its mesh. Raises for a part with no geometry."""
    _require_in_model(model,piece)
    if not piece.verts: raise ThreeDOError('this part has no geometry, so it has no mesh centre')
    _,origin,Ap=locate(model,piece)
    pts=[tuple(origin[i]+m_apply(Ap,v)[i] for i in range(3)) for v in piece.verts]
    return tuple(sum(p[i] for p in pts)/float(len(pts)) for i in range(3))

# ---- importers. Each returns (points, polygons): points are (x,y,z) floats, polygons are lists of 0-based point indices ----
def _fan(polys):
    """Faces of more than four corners become fans of triangles (the 3DO shape stays three or four corners)."""
    out=[]
    for idx in polys:
        if len(idx)<3: continue
        if len(idx)<=4: out.append(list(idx))
        else:
            for k in range(1,len(idx)-1): out.append([idx[0],idx[k],idx[k+1]])
    return out

def _check_indices(polys,npts,what):
    for idx in polys:
        for k in idx:
            if not (0<=k<npts): raise ThreeDOError(f'{what}: a face refers to point {k + 1}, but there are only {npts} points')

def parse_obj(text):
    pts=[]; polys=[]
    for raw in text.splitlines():
        parts=raw.split('#')[0].split()
        if not parts: continue
        if parts[0]=='v':
            if len(parts)<4: raise ThreeDOError('OBJ: a vertex line has fewer than three numbers')
            pts.append(tuple(float(x) for x in parts[1:4]))
        elif parts[0]=='f':
            idx=[]
            for tok in parts[1:]:
                k=int(tok.split('/')[0])
                idx.append(k-1 if k>0 else len(pts)+k)     # OBJ counts from 1; negative counts back from the last point
            polys.append(idx)
    polys=_fan(polys)
    _check_indices(polys,len(pts),'OBJ')
    return pts,polys

def _dxf_entities(text):
    lines=text.splitlines()
    ents=[]; cur=None
    for i in range(0,len(lines)-1,2):
        code=lines[i].strip(); val=lines[i+1].strip()
        if code=='0':
            if cur is not None: ents.append(cur)
            cur=[val,[]]
        elif cur is not None: cur[1].append((code,val))
    if cur is not None: ents.append(cur)
    return ents

def parse_dxf(text):
    """3DFACE entities and POLYFACE meshes (POLYLINE with the mesh flag, VERTEX records and faces). Shared corners are joined."""
    ents=_dxf_entities(text)
    pts=[]; polys=[]; index={}
    def vid(x,y,z):
        key=(round(x,6),round(y,6),round(z,6))
        if key not in index: index[key]=len(pts); pts.append(key)
        return index[key]
    k=0
    while k<len(ents):
        typ,codes=ents[k]; k+=1
        d=dict(codes)
        if typ=='3DFACE':
            corners=[]
            for i in range(4):
                if f'{10+i}' in d and f'{20+i}' in d:
                    corners.append(vid(float(d[f'{10+i}']),float(d[f'{20+i}']),float(d.get(f'{30+i}','0'))))
            out=[]
            for c in corners:                       # a triangle repeats its last corner: drop the repeat
                if not out or out[-1]!=c: out.append(c)
            if len(out)>1 and out[-1]==out[0]: out.pop()
            if len(out)>=3: polys.append(out)
        elif typ=='POLYLINE':
            # the polyface mesh's VERTEX records come first, then the face records; SEQEND closes the group
            verts=[]; faces=[]
            while k<len(ents) and ents[k][0]!='SEQEND':
                t,cs=ents[k]; k+=1
                if t!='VERTEX': continue
                dv=dict(cs)
                if '10' in dv and '20' in dv:
                    verts.append(vid(float(dv['10']),float(dv['20']),float(dv.get('30','0'))))
                else:
                    faces.append([abs(int(dv[c])) for c in ('71','72','73','74') if c in dv and int(dv[c])!=0])
            if k<len(ents): k+=1                    # SEQEND
            if int(d.get('70','0')) & 64:
                for f in faces:
                    if f and all(1<=i<=len(verts) for i in f): polys.append([verts[i-1] for i in f])
    polys=_fan(polys)
    _check_indices(polys,len(pts),'DXF')
    return pts,polys

def parse_lwo(data):
    """LightWave objects: LWOB (the format this program writes) and LWO2. Layers are read in order; surfaces are not used."""
    if len(data)<12 or data[:4]!=b'FORM' or data[8:12] not in (b'LWOB',b'LWO2'):
        raise ThreeDOError('not a LightWave object (expected a FORM with LWOB or LWO2)')
    kind=data[8:12]
    pts=[]; polys=[]; layer_base=0
    end=min(len(data),8+_pstruct.unpack('>I',data[4:8])[0])
    pos=12
    while pos+8<=end:
        cid=data[pos:pos+4]; size=_pstruct.unpack('>I',data[pos+4:pos+8])[0]
        body=data[pos+8:pos+8+size]
        if len(body)<size: raise ThreeDOError('LightWave: a chunk runs past the end of the file')
        if cid==b'PNTS':
            layer_base=len(pts)
            pts+=[_pstruct.unpack('>3f',body[i:i+12]) for i in range(0,len(body)-11,12)]
        elif cid==b'POLS':
            j=0
            if kind==b'LWO2':
                if body[:4]!=b'FACE': pos+=8+size+(size&1); continue      # curves, patches and the rest are not meshes
                j=4
            while j+2<=len(body):
                n=_pstruct.unpack('>H',body[j:j+2])[0]&0x3ff; j+=2
                if j+2*n>len(body): raise ThreeDOError('LightWave: a face runs past the end of its chunk')
                idx=[layer_base+_pstruct.unpack('>H',body[j+2*q:j+2*q+2])[0] for q in range(n)]
                j+=2*n
                if kind==b'LWOB': j+=2                                       # LWOB stores a surface number after each face
                polys.append(idx)
        pos+=8+size+(size&1)
    polys=_fan(polys)
    _check_indices(polys,len(pts),'LightWave')
    return [tuple(float(c) for c in p) for p in pts],polys

def read_mesh_file(path):
    """Reads an OBJ, DXF, LWO or LWOB file. Returns (points, polygons) or raises ThreeDOError."""
    low=path.lower()
    try:
        with open(path,'rb') as f: data=f.read()
    except OSError as e: raise ThreeDOError(f'could not read {path}: {e}')
    if low.endswith('.obj'): return parse_obj(data.decode('utf-8','replace'))
    if low.endswith('.dxf'): return parse_dxf(data.decode('latin1'))
    if low.endswith(('.lwo','.lwob')): return parse_lwo(data)
    raise ThreeDOError('unknown mesh type (use OBJ, DXF, LWO or LWOB)')

def _mesh_geometry(pts,polys,colour,scale):
    if not pts or not polys: raise ThreeDOError('the file has no faces to import')
    if not (0<=colour<=255): raise ThreeDOError('colour must be a palette index from 0 to 255')
    if not (scale>0): raise ThreeDOError('scale must be greater than zero')
    if len(pts)>65535: raise ThreeDOError(f'{len(pts)} points: a part holds at most 65535')
    verts=[]
    for p in pts:
        q=tuple(_q(float(c)*scale) for c in p)
        if any(abs(c)*65536.0>=2**31 for c in q): raise ThreeDOError('the mesh is too large for the 3DO grid: lower the scale')
        verts.append(q)
    return verts,[Poly3D(colour,list(idx),None) for idx in polys]

def add_mesh_piece(model,parent,name,pts,polys,colour=0,scale=1.0):
    """A new part under parent, holding the imported mesh with its pivot at the parent's origin. Returns the part."""
    parent=parent or model.root
    _require_in_model(model,parent)
    verts,faces=_mesh_geometry(pts,polys,colour,scale)
    p=Piece3D(unique_piece_name(piece_names(model),name),(0.0,0.0,0.0))
    p.verts=verts; p.polys=faces
    parent.children.append(p)
    return p

def replace_mesh(model,piece,pts,polys,colour=0,scale=1.0):
    """Replaces a part's geometry with the imported mesh. Its name, pivot, children and pending rotation stay."""
    _require_in_model(model,piece)
    verts,faces=_mesh_geometry(pts,polys,colour,scale)
    piece.verts=verts; piece.polys=faces
    return piece

# ---- base plate: the root part's ground plate ----
# The root part's selection field (stored as Piece3D.flag, header word 0x0C) is the index of one of its faces. Retail
# designates that face as the ground plate: a flat quad in X and Z, with four different corners, one height, and a
# width and depth above zero (3do format note, "Selection primitive"). -1 designates none. The corners are kept in the
# stock ring order (+x,+z), (-x,+z), (-x,-z), (+x,-z) that the format note records for shipped unit plates.
# TODO(question): retail's ground-plate winding and whether it must sit at the model's lowest height are not settled by
# the research; a new plate sits at height zero in the root frame, the height retail's footprint bound starts from.

def _plate_problem_pts(pts):
    """Why four corners cannot be the base plate, or None when they can."""
    if len(pts)!=4: return 'the base plate must be a four-corner face'
    if len({tuple(p) for p in pts})!=4: return 'the base plate needs four different corners'
    if len({p[1] for p in pts})!=1: return 'the base plate must lie flat (one height for all four corners)'
    if len({p[0] for p in pts})<2 or len({p[2] for p in pts})<2: return 'the base plate needs a width and a depth above zero'
    return None

def base_plate_problem(root):
    """Why the root's designated base plate is not usable, or None when it is a flat quad."""
    k=root.flag
    if k==-1: return 'no base plate is designated'
    if not (0<=k<len(root.polys)): return f'the designated face {k} is not one of the base part\'s {len(root.polys)} faces'
    idx=list(root.polys[k].idx)
    if len(idx)!=4 or not all(0<=i<len(root.verts) for i in idx): return 'the designated base plate is not a four-corner face'
    return _plate_problem_pts([root.verts[i] for i in idx])

def base_plate_size(root):
    """(width, depth) of the designated base plate in TA units, or None when there is no usable plate."""
    if base_plate_problem(root) is not None: return None
    pts=[root.verts[i] for i in root.polys[root.flag].idx]
    return (max(p[0] for p in pts)-min(p[0] for p in pts), max(p[2] for p in pts)-min(p[2] for p in pts))

def _check_plate_size(width,depth):
    if not (width>0 and depth>0): raise ThreeDOError('width and depth must be greater than zero')
    if max(abs(width),abs(depth))*65536.0>=2**31/2: raise ThreeDOError('the base plate is too large for the 3DO grid')

def create_base_plate(model,width,depth):
    """A new flat base plate on the base part, centred on its pivot at height zero, designated as the plate. A plate that
    was designated before stays in the model as ordinary faces. Returns the new face."""
    _check_plate_size(width,depth)
    root=model.root
    hw=_q(width/2.0); hd=_q(depth/2.0)
    base=len(root.verts)
    root.verts=list(root.verts)+[(hw,0.0,hd),(-hw,0.0,hd),(-hw,0.0,-hd),(hw,0.0,-hd)]
    face=Poly3D(0,[base,base+1,base+2,base+3],None)
    root.polys=list(root.polys)+[face]
    root.flag=len(root.polys)-1
    return face

def designate_base_plate(model,piece):
    """Designates a flat quad as the base plate. On the base part, the quad must be one of its own faces (exactly one flat
    quad must be there). Any other part must be a childless part with a single flat quad: that quad is moved into the base
    part, in the base part's frame, and the part it came from is removed. Undo puts it back. Returns the designated face."""
    _require_in_model(model,piece)
    root=model.root
    if piece is root:
        found=[i for i,p in enumerate(root.polys) if len(p.idx)==4 and _plate_problem_pts([root.verts[k] for k in p.idx]) is None]
        if not found: raise ThreeDOError('the base part has no flat four-corner face to use as the base plate')
        if len(found)>1: raise ThreeDOError('the base part has more than one flat quad: move the one you want into its own part, then designate that part')
        root.flag=found[0]
        return root.polys[found[0]]
    if piece.children: raise ThreeDOError('a part with children cannot become the base plate: move its children away first')
    if len(piece.polys)!=1 or len(piece.polys[0].idx)!=4: raise ThreeDOError('the part must hold exactly one four-corner face to become the base plate')
    if root.pend is not None: raise ThreeDOError('commit the base part\'s pending rotation first, then designate')
    loc=locate(model,piece); origin_root=model.origin_of(root)
    _,origin,Ap=loc
    src=piece.polys[0]
    pts=[]
    for k in src.idx:
        w=tuple(origin[i]+m_apply(Ap,piece.verts[k])[i] for i in range(3))
        pts.append(tuple(_q(w[i]-origin_root[i]) for i in range(3)))
    problem=_plate_problem_pts(pts)
    if problem is not None: raise ThreeDOError(problem)
    base=len(root.verts)
    root.verts=list(root.verts)+pts
    root.polys=list(root.polys)+[Poly3D(src.color,[base,base+1,base+2,base+3],src.tex)]
    root.flag=len(root.polys)-1
    if any(r is piece for r in model.extra_roots):
        model.extra_roots=[r for r in model.extra_roots if r is not piece]
    else:
        par=_parent_of(model,piece)
        par.children=[c for c in par.children if c is not piece]
    return root.polys[-1]

def clear_base_plate(model):
    """Stops designating a base plate. The faces stay."""
    model.root.flag=-1

def set_base_plate_size(model,width,depth):
    """Sets the designated base plate's width (X) and depth (Z), keeping its centre and height. Corners the plate shares
    with other faces are not moved in place: new corners are added for the plate, so the other faces keep their shape."""
    _check_plate_size(width,depth)
    root=model.root
    problem=base_plate_problem(root)
    if problem is not None: raise ThreeDOError(problem)
    face=root.polys[root.flag]
    pts=[root.verts[i] for i in face.idx]
    cx=(max(p[0] for p in pts)+min(p[0] for p in pts))/2.0
    cz=(max(p[2] for p in pts)+min(p[2] for p in pts))/2.0
    hw=width/2.0; hd=depth/2.0
    shared=any(k in face.idx for j,q in enumerate(root.polys) if j!=root.flag for k in q.idx)
    new=[]
    for i,p in zip(face.idx,pts):
        sx=1 if p[0]>cx else -1; sz=1 if p[2]>cz else -1
        new.append((_q(cx+sx*hw),p[1],_q(cz+sz*hd)))
    if shared:
        base=len(root.verts)
        root.verts=list(root.verts)+new
        face.idx=[base,base+1,base+2,base+3]
    else:
        for i,q in zip(face.idx,new): root.verts[i]=q
