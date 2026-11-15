# ---- animation: keys, evaluation and the driver pose ----
# A clip is a timeline of keys per part. Rotation keys are quaternions relative to the part's rest pose (rest·Q), and
# position keys are offsets relative to its rest offset, so a child key is local to its parent and a parent's motion is
# inherited by every descendant through the ordinary frame composition. The rest pose is never changed by playback: the
# driver writes the composed pose into the tree, and clearing the driver restores the rest snapshot exactly.
import math as _amath

INTERP=('linear','instant','smooth')
LOOPS=('hold','loop','ping')
DEFAULT_TIMELINE={'start':0,'length':60,'fps':30,'loop':'loop'}     # the span runs start .. start+length; start may be negative

def default_anim():
    return {'timeline':dict(DEFAULT_TIMELINE),'tracks':{}}

def piece_key(path):
    """Stable key for a part: its tree path as dotted indices, e.g. '0.2.1'."""
    return '.'.join(str(i) for i in path)

def normalize_anim(a):
    """Checks and fills an animation block read from a project. Raises ValueError with a plain reason."""
    if a is None: return default_anim()
    if not isinstance(a,dict): raise ValueError('animation data is not an object')
    tl=dict(DEFAULT_TIMELINE); tl.update(a.get('timeline') or {})
    if not isinstance(tl['length'],int) or isinstance(tl['length'],bool) or tl['length']<1:
        raise ValueError('timeline length must be a whole number of frames, at least 1')
    if not isinstance(tl['start'],int) or isinstance(tl['start'],bool): raise ValueError('timeline start must be a whole number of frames')
    if tl['loop'] not in LOOPS: raise ValueError(f'unknown loop mode {tl["loop"]!r}')
    if not isinstance(tl['fps'],(int,float)) or tl['fps']<=0: raise ValueError('timeline fps must be positive')
    tracks={}
    for pk,tr in (a.get('tracks') or {}).items():
        out={'rot':[],'pos':[]}
        for kind in ('rot','pos'):
            n=3 if kind=='pos' else 4
            for k in (tr.get(kind) or []):
                t=k['t']
                if not isinstance(t,int) or isinstance(t,bool): raise ValueError(f'key frame for {pk} is not a whole number')
                if k.get('i','linear') not in INTERP: raise ValueError(f'unknown interpolation {k.get("i")!r} on {pk}')
                v=tuple(float(c) for c in k['v'])
                if len(v)!=n: raise ValueError(f'{kind} key on {pk} needs {n} values')
                if kind=='rot': v=q_norm(v)
                out[kind].append({'t':t,'v':v,'i':k.get('i','linear')})
            out[kind].sort(key=lambda k:k['t'])
            frames=[k['t'] for k in out[kind]]
            if len(frames)!=len(set(frames)): raise ValueError(f'two {kind} keys share a frame on {pk}')
        tracks[str(pk)]=out
    return {'timeline':tl,'tracks':tracks}

def anim_to_json(a):
    """The plain JSON form of an animation block (tuples become lists)."""
    tracks={}
    for pk,tr in a['tracks'].items():
        tracks[pk]={kind:[{'t':k['t'],'v':list(k['v']),'i':k['i']} for k in tr[kind]] for kind in ('rot','pos')}
    return {'timeline':dict(a['timeline']),'tracks':tracks}

# ---- quaternion maths (w,x,y,z), unit quaternions ----
def _dot(a,b): return sum(x*y for x,y in zip(a,b))

def _near(q,ref):
    """q, or -q, whichever lies in the same hemisphere as ref (the shorter arc)."""
    return q if _dot(q,ref)>=0 else tuple(-c for c in q)

def q_slerp(a,b,u):
    d=_dot(a,b)
    if d<0: b=tuple(-c for c in b); d=-d
    if d>0.9995:
        return q_norm(tuple(a[i]+u*(b[i]-a[i]) for i in range(4)))
    th=_amath.acos(min(1.0,d)); s=_amath.sin(th)
    wa=_amath.sin((1-u)*th)/s; wb=_amath.sin(u*th)/s
    return q_norm(tuple(wa*a[i]+wb*b[i] for i in range(4)))

def q_log(q):
    w=max(-1.0,min(1.0,q[0])); v=q[1:]; n=_amath.sqrt(sum(c*c for c in v))
    if n<1e-12: return (0.0,0.0,0.0)
    th=_amath.atan2(n,w)
    return tuple(c*th/n for c in v)

def q_exp(v):
    th=_amath.sqrt(sum(c*c for c in v))
    if th<1e-12: return q_norm((1.0,v[0],v[1],v[2]))
    s=_amath.sin(th)/th
    return (_amath.cos(th),v[0]*s,v[1]*s,v[2]*s)

def _conj(q): return (q[0],-q[1],-q[2],-q[3])

def _tangent(qs,i):
    """Spherical-cubic control quaternion at key i, from its neighbours (ends reuse the key itself)."""
    q=qs[i]
    prev=_near(qs[i-1],q) if i>0 else q
    nxt=_near(qs[i+1],q) if i+1<len(qs) else q
    qi=_conj(q)
    a=q_log(q_mul(qi,nxt)); b=q_log(q_mul(qi,prev))
    return q_mul(q,q_exp(tuple(-(a[k]+b[k])/4.0 for k in range(3))))

def q_squad(q0,q1,s0,s1,u):
    return q_slerp(q_slerp(q0,q1,u),q_slerp(s0,s1,u),2.0*u*(1.0-u))

def _catmull(p0,p1,p2,p3,u):
    return tuple(0.5*((2*p1[i])+(-p0[i]+p2[i])*u+(2*p0[i]-5*p1[i]+4*p2[i]-p3[i])*u*u+(-p0[i]+3*p1[i]-3*p2[i]+p3[i])*u*u*u)
                 for i in range(len(p1)))

# ---- evaluation ----
def span(tl):
    """(first, last) frame of a timeline."""
    s=int(tl.get('start',0)); return s, s+int(tl['length'])

def wrap_time(t,tl):
    """Maps a frame onto the span by the loop mode. hold clamps, loop repeats, ping runs forward then back."""
    s=float(tl.get('start',0)); L=float(tl['length']); u=float(t)-s
    if tl['loop']=='hold': u=min(max(u,0.0),L)
    elif tl['loop']=='loop': u=u%L
    else:
        m=u%(2*L); u=m if m<=L else 2*L-m
    return s+u

def _seg(keys,t):
    i=0
    for j in range(len(keys)-1):
        if keys[j]['t']<=t: i=j
    return i

def eval_rot(keys,t):
    """Rotation key track at frame t: a unit quaternion relative to rest, or None when the track has no keys."""
    if not keys: return None
    if t<=keys[0]['t']: return keys[0]['v']
    if t>=keys[-1]['t']: return keys[-1]['v']
    i=_seg(keys,t); a=keys[i]; b=keys[i+1]
    if a['i']=='instant': return a['v']
    u=(t-a['t'])/float(b['t']-a['t'])
    if a['i']=='linear': return q_slerp(a['v'],b['v'],u)
    qs=[k['v'] for k in keys]
    return q_squad(a['v'],b['v'],_tangent(qs,i),_tangent(qs,i+1),u)

def eval_pos(keys,t):
    """Position key track at frame t: an offset relative to rest, or None when the track has no keys."""
    if not keys: return None
    if t<=keys[0]['t']: return keys[0]['v']
    if t>=keys[-1]['t']: return keys[-1]['v']
    i=_seg(keys,t); a=keys[i]; b=keys[i+1]
    if a['i']=='instant': return a['v']
    u=(t-a['t'])/float(b['t']-a['t'])
    if a['i']=='linear': return tuple(a['v'][k]+u*(b['v'][k]-a['v'][k]) for k in range(3))
    vs=[k['v'] for k in keys]
    p0=vs[i-1] if i>0 else vs[i]
    p3=vs[i+2] if i+2<len(vs) else vs[i+1]
    return _catmull(p0,vs[i],vs[i+1],p3,u)

def evaluate(anim,t):
    """Pose at frame t (already wrapped): {piece key: (rotation quaternion or None, offset or None)}."""
    out={}
    for pk,tr in anim['tracks'].items():
        q=eval_rot(tr['rot'],t); d=eval_pos(tr['pos'],t)
        if q is not None or d is not None: out[pk]=(q,d)
    return out

# ---- the rest snapshot and the driver pose, applied to a tree ----
def snapshot_pose(roots):
    """{piece key: (pending rotation or None, offset)} for every part: the rest pose of a tree."""
    return {piece_key(pth): (p.pend,tuple(p.offset)) for pth,p in _roots_paths(roots)}

def restore_pose(roots,snap):
    for pth,p in _roots_paths(roots):
        r=snap.get(piece_key(pth))
        if r is not None: p.pend,p.offset=r[0],tuple(r[1])

def apply_pose(roots,rest,pose):
    """Writes rest·pose into the tree. Geometry is not touched; only each part's pending rotation and offset."""
    for pth,p in _roots_paths(roots):
        k=piece_key(pth); r=rest.get(k)
        if r is None: continue
        rp,ro=r
        q,d=pose.get(k,(None,None))
        p.pend=rp if q is None else q_norm(q_mul(rp or _QI,q))
        p.offset=tuple(ro) if d is None else tuple(ro[i]+d[i] for i in range(3))

# ---- per-axis rotation: Euler angles in degrees, in the viewer's own frame ----
# The viewer uses standard right-hand rotations, the same ones the gizmo draws. The composed rotation is
# R = Ry(y)·Rx(x)·Rz(z): z is applied to the vertex first, then x, then y. This matches the order the retail engine uses.
# Angles are shown and typed in this frame. The engine's own angles are produced only at export (engine_angles below).
def _mat_mul(A,B):
    return tuple(tuple(sum(A[i][k]*B[k][j] for k in range(3)) for j in range(3)) for i in range(3))

def _std_ry(t):
    """Standard right-hand rotation about Y, as q_to_m writes it."""
    c,s_=_amath.cos(t),_amath.sin(t)
    return ((c,0.0,s_),(0.0,1.0,0.0),(-s_,0.0,c))

def q_to_euler(q):
    """Unit quaternion -> (x,y,z) degrees with R = Ry·Rx·Rz. At x = ±90 the other two are not separable; z is given the rest."""
    M=q_to_m(q)
    # R = Ry(y)·Rx(x)·Rz(z) in standard form: the engine-form formulas below are for the mirrored Y, so y is negated here
    sc=max(-1.0,min(1.0,-M[1][2]))
    x_ang=_amath.asin(sc)
    if abs(sc)<0.9999999:
        yb=_amath.atan2(M[0][2],M[2][2])
        z_ang=_amath.atan2(M[1][0],M[1][1])
    else:
        z_ang=0.0
        yb=_amath.atan2(-M[2][0],M[0][0])
    return (_amath.degrees(x_ang),_amath.degrees(yb),_amath.degrees(z_ang))

def euler_to_q(deg):
    """(x,y,z) degrees -> unit quaternion, R = Ry·Rx·Rz in the viewer's frame."""
    cx,cy,cz=(_amath.radians(c)/2.0 for c in deg)
    qx=(_amath.cos(cx),_amath.sin(cx),0.0,0.0)
    qy=(_amath.cos(cy),0.0,_amath.sin(cy),0.0)
    qz=(_amath.cos(cz),0.0,0.0,_amath.sin(cz))
    return q_norm(q_mul(qy,q_mul(qx,qz)))

# Set once the half-turn on load is confirmed in the retail binary. True: the engine negates X and Z of every
# vertex and parent offset on load, which makes every engine angle the negation of the viewer's (see engine_angles).
# False: the engine uses the file's frame, and only Y changes sign.
ENGINE_HALF_TURN=True

def engine_angles(deg):
    """Viewer (x,y,z) degrees -> the engine's (x,y,z) angles for a turn command.
    The engine's Y turns the opposite way from the standard rotation. With the half-turn on load, the composed
    rotation is conjugated by a half-turn about Y, which negates every angle; without it, only Y changes sign."""
    x,y,z=deg
    if ENGINE_HALF_TURN: return (-x,-y,-z)
    return (x,-y,z)

def engine_offset(d):
    """Viewer (x,y,z) offset <-> the engine's move value for it. The map is its own inverse. With the half-turn on load
    the engine negates X and Z of parent offsets, the same as it does for vertices, so those two flip; Y does not.
    A BOS move's value is relative to the part's rest position, so the rest offset is not part of it."""
    x,y,z=d
    if ENGINE_HALF_TURN: return (-x,y,-z)
    return (x,y,z)

# ---- sequence files (.3dan): one named sequence, saved and loaded on its own ----
SEQ_FORMAT='bostool-3dan'; SEQ_VERSION=1

def seq_file_doc(name,anim):
    return {'format':SEQ_FORMAT,'version':SEQ_VERSION,'name':name,'timeline':dict(anim['timeline']),
            'tracks':anim_to_json(anim)['tracks']}

def parse_seq_file(doc):
    """(name, checked animation block) from a .3dan document. Raises ValueError with a plain reason."""
    if not isinstance(doc,dict) or doc.get('format')!=SEQ_FORMAT: raise ValueError('not an Advanced Model Factory sequence file')
    if doc.get('version')!=SEQ_VERSION: raise ValueError(f'sequence file version {doc.get("version")} is not supported')
    name=str(doc.get('name') or '').strip() or 'Sequence'
    return name, normalize_anim({'timeline':doc.get('timeline'),'tracks':doc.get('tracks')})

def key_from_display(rest_pend,rest_off,cur_pend,cur_off):
    """The rest-relative key that reproduces the current displayed pose of one part."""
    Q=q_norm(q_mul(_conj(rest_pend or _QI),cur_pend or _QI))
    d=tuple(cur_off[i]-rest_off[i] for i in range(3))
    return Q,d

