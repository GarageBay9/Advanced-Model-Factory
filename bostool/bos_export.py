# ---- BOS export: stages A, B and C (design: BOS_EXPORT_DESIGN.md, sections 3, 7 and 11) ----
# A: rotations. B: offsets. C: accel/decel ramps at key ticks.
# Samples each keyed track once per tick, simplifies each axis to straight segments, adds the ramps, splits turns
# at half a turn, schedules every segment with a speed that finishes it inside its time, and emits BOS text.
# bos_verify reads that text back with the engine's rules. Two errors are reported: the schedule error against the
# intended path (must be small), and the fidelity error against the keyed motion (the ramps change it on purpose).
import math as _bxm

BX_ANGLE_UNITS=65536
BX_TICKS_PER_SECOND=30
BX_DEFAULT_TOL_DEG=0.5
BX_DEFAULT_TOL_POS=0.02      # 3DO units
BX_MAX_SEG=0x7fff            # no rotation turn is longer than this many raw units
BX_RAMP_TICKS=6              # each ramp lasts up to this many ticks, never more than half the segment
BX_RAMP_STEPS=4              # a ramp is written as this many stepped sub-segments at most
BX_LOOP_POLICIES=('report','enforce','ignore')

class BosExportError(Exception): pass

# ---- unit conversions ----
def bx_shortest(d):
    """Signed difference of two 16-bit angles, in [-32768, 32767]: the arc the engine takes."""
    return ((int(d)+32768)&0xffff)-32768

def bx_raw(deg):
    """Degrees -> the 16-bit angle unit the engine stores."""
    return int(round(deg*BX_ANGLE_UNITS/360.0)) & 0xffff

def bx_pos_raw(units):
    """3DO units -> the 16.16 value the engine stores."""
    return int(round(units*BX_ANGLE_UNITS))

def bx_literal(raw):
    """Angle text, written so the compiler's int(x*65536/360) returns exactly raw. The +0.25 puts the value in the
    middle of its bucket so float error cannot drop it to raw-1."""
    return '%.6f' % ((int(raw)+0.25)*360.0/BX_ANGLE_UNITS)

def bx_compile_value(text):
    """What the compiler makes of an angle <literal> (compile.to_fixed_angle): truncation toward zero."""
    return int(float(text)*BX_ANGLE_UNITS/360)

def bx_linear_literal(raw):
    """Move text, written so the compiler's round(x*LINEAR_SCALE) returns exactly raw, whatever the build's scale."""
    return '%.6f' % ((int(raw)+0.25)/LINEAR_SCALE)

def bx_compile_linear(text):
    """What the compiler makes of a [linear] literal (compile.to_fixed_linear)."""
    return int(round(float(text)*LINEAR_SCALE))

def bx_ms_for_ticks(n):
    """Milliseconds for n ticks: ceil(100*n/3), so the engine's trunc(30*ms/1000) gives back n."""
    return (100*int(n)+2)//3

# ---- stage 1: sample ----
def bx_piece_map(roots):
    """{piece key: piece}."""
    return {piece_key(path):p for path,p in _roots_paths(roots)}

def bx_key_ticks(tr, s):
    """{relative tick: interpolation} for every key of a track, rotation and offset alike."""
    out={}
    for kind in ('rot','pos'):
        for k in tr.get(kind,[]):
            out.setdefault(int(k['t'])-s,k.get('i','smooth'))
            if k.get('i')=='instant': out[int(k['t'])-s]='instant'
    return out

def bx_sample(anim, roots, ticks):
    """One value per tick for every animated track, per axis.
    rotation: engine degrees: {pk: {'kind':'rot', 'x':[..], 'y':[..], 'z':[..]}}
    offset:   engine offset relative to rest (engine_offset of the key delta): {pk: {'kind':'pos', ...}}"""
    pmap=bx_piece_map(roots)
    out={}
    for pk,tr in anim['tracks'].items():
        if pk not in pmap:
            raise BosExportError(f'track {pk} has no part in the model')
        rec={}
        if tr.get('rot'):
            r={'x':[], 'y':[], 'z':[]}
            for t in ticks:
                q=eval_rot(tr['rot'],t)
                if q is None: raise BosExportError(f'part {pk} has no rotation at tick {t}')
                ex,ey,ez=engine_angles(q_to_euler(q))
                r['x'].append(ex); r['y'].append(ey); r['z'].append(ez)
            rec['rot']=r
        if tr.get('pos'):
            r={'x':[], 'y':[], 'z':[]}
            for t in ticks:
                d=eval_pos(tr['pos'],t)
                if d is None: raise BosExportError(f'part {pk} has no offset at tick {t}')
                ed=engine_offset(tuple(d))           # relative to rest, in the engine's sign convention
                for i,a in enumerate('xyz'): r[a].append(ed[i])
            rec['pos']=r
        out[pk]=rec
    return out

# ---- stage 2: simplify ----
def bx_unwrap(vals):
    """Makes an angle series continuous in degrees, so the simplifier never sees a false 360-degree jump."""
    out=[float(vals[0])]
    for v in vals[1:]:
        prev=out[-1]
        out.append(prev+((v-prev+180.0)%360.0-180.0))
    return out

def bx_simplify(ticks, vals, tol):
    """Ramer-Douglas-Peucker on (tick, value): the breakpoint indexes whose straight chords stay within tol."""
    n=len(vals)
    if n==0: return []
    if n==1: return [0]
    keep={0,n-1}; stack=[(0,n-1)]
    while stack:
        i,j=stack.pop()
        if j<=i+1: continue
        t0,v0,t1,v1=ticks[i],vals[i],ticks[j],vals[j]
        best=i+1; bd=-1.0
        for k in range(i+1,j):
            f=(ticks[k]-t0)/float(t1-t0)
            dist=abs(vals[k]-(v0+(v1-v0)*f))
            if dist>bd: bd=dist; best=k
        if bd>tol:
            keep.add(best); stack.append((i,best)); stack.append((best,j))
    return sorted(keep)

# ---- stage 3: ramps (accel/decel as stepped speeds, only at key ticks) ----
def bx_ramp_lengths(T, ra_on, rb_on):
    """Ramp lengths in ticks at the start and end of a segment of T ticks."""
    R=min(BX_RAMP_TICKS, T//2)
    return (R if ra_on else 0), (R if rb_on else 0)

def bx_ramp_h(u, T, ra, rb):
    """Fraction of the way along a segment at tick offset u, for a trapezoid velocity profile with ramps of ra and rb
    ticks at its ends. Continuous, reaches 0 and 1 at the ends, and its velocity is continuous where a ramp is."""
    if T<=0: return 1.0
    a=ra/float(T); b=rb/float(T)
    vp=1.0/(1.0-a/2.0-b/2.0)
    x=u/float(T)
    if a>0 and x<a: return vp*x*x/(2.0*a)
    if x<=1.0-b or b==0: return vp*(a/2.0+(x-a))
    w=x-(1.0-b)
    return vp*(a/2.0+(1.0-a-b)+(w-w*w/(2.0*b)))

def bx_expand(ticks, vals, idx, ramp_start, ramp_end):
    """Turns the breakpoints into a point list with the ramp profile on the chosen segment ends.
    ramp_start(i)/ramp_end(i): whether breakpoint i is a key where a ramp applies. Returns (ticks, values)."""
    if not idx: return [], []
    out_t=[ticks[idx[0]]]; out_v=[vals[idx[0]]]
    for a,b in zip(idx, idx[1:]):
        t0,t1=ticks[a],ticks[b]; v0,v1=vals[a],vals[b]
        T=t1-t0
        ra,rb=bx_ramp_lengths(T, ramp_start(a), ramp_end(b))
        samples={t1}
        if ra>0:
            N=min(ra,BX_RAMP_STEPS)
            for k in range(1,N+1): samples.add(t0+int(round(ra*k/float(N))))
        if rb>0:
            N=min(rb,BX_RAMP_STEPS)
            for k in range(0,N): samples.add(t1-int(round(rb*(N-k)/float(N))))
        for t in sorted(samples):
            if t<=t0 or t>t1: continue
            h=bx_ramp_h(t-t0,T,ra,rb)
            out_t.append(t); out_v.append(v0+(v1-v0)*h)
    return out_t, out_v

def bx_interp(ticks, vals, t):
    """Value of the piecewise-linear path (ticks, vals) at tick t."""
    if t<=ticks[0]: return vals[0]
    if t>=ticks[-1]: return vals[-1]
    lo,hi=0,len(ticks)-1
    while hi-lo>1:
        mid=(lo+hi)//2
        if ticks[mid]<=t: lo=mid
        else: hi=mid
    f=(t-ticks[lo])/float(ticks[hi]-ticks[lo])
    return vals[lo]+(vals[hi]-vals[lo])*f

# ---- stage 4: schedule ----
def bx_schedule(ticks, vals, kind):
    """Commands for one axis over a point list. Rotation: each segment is split so no turn exceeds half a turn, and
    the wrap is the engine's shortest arc. Offset: no wrap. Each command is (tick, target raw, speed raw or None).
    The step per tick is s = ceil(|delta|/T) and the speed is 30*s, so the engine's trunc(speed/30) gives s per tick."""
    cmds=[]
    for t0,t1,v0,v1 in ((ticks[i],ticks[i+1],vals[i],vals[i+1]) for i in range(len(ticks)-1)):
        T=t1-t0
        if kind=='rot':
            total=int(round((v1-v0)*BX_ANGLE_UNITS/360.0))
            n=min(max(1,-(-abs(total)//BX_MAX_SEG)), T)
        else:
            n=1
        for k in range(n):
            ks=t0+int(round(T*k/float(n))); ke=t0+int(round(T*(k+1)/float(n)))
            vs=v0+(v1-v0)*k/float(n); ve=v0+(v1-v0)*(k+1)/float(n)
            Ts=ke-ks
            if kind=='rot':
                tgt=bx_raw(ve); cur=bx_raw(vs)
                d=bx_shortest(tgt-cur)
            else:
                tgt=bx_pos_raw(ve); cur=bx_pos_raw(vs)
                d=tgt-cur
            if d==0: continue
            s=-(-abs(d)//Ts)
            cmds.append((ks, tgt, 30*s))
    return cmds

def bx_piece_names(roots):
    """{piece key: piece name} for the tree."""
    names={}
    for path,p in _roots_paths(roots):
        names[piece_key(path)]=p.name
    return names

# ---- the export ----
def bos_export_clip(anim, roots, source='', clip_name='Clip', tol_deg=BX_DEFAULT_TOL_DEG, tol_pos=BX_DEFAULT_TOL_POS,
                    loop_policy='report', ramps=True):
    """Exports one clip as BOS text. Returns (text, report, replay_input). The report holds the seam check, the
    segment counts and the fidelity of the intended path against the keyed motion. replay_input is what bos_verify
    checks the text against."""
    if loop_policy not in BX_LOOP_POLICIES:
        raise ValueError(f'loop policy must be one of {BX_LOOP_POLICIES}')
    tl=anim['timeline']
    s,e=span(tl)
    ticks=list(range(s,e+1))
    rel=[t-s for t in ticks]
    L=rel[-1]
    samples=bx_sample(anim, roots, ticks)
    names=bx_piece_names(roots)
    keyticks={pk:bx_key_ticks(tr,s) for pk,tr in anim['tracks'].items()}
    looped=(tl.get('loop')=='loop')
    seams=[]
    for pk,rec in samples.items():
        for kind,axes in rec.items():
            for a in 'xyz':
                v=axes[a]
                if looped and loop_policy!='ignore':
                    same=(bx_raw(v[-1])==bx_raw(v[0])) if kind=='rot' else (bx_pos_raw(v[-1])==bx_pos_raw(v[0]))
                    if not same:
                        seams.append({'piece':names.get(pk,pk),'kind':kind,'axis':a,'policy':loop_policy})
                        if loop_policy=='enforce': v[-1]=v[0]
    body=[]; cmd_list=[]; rep_pieces={}; replay_input={}; fidelity={}
    for pk,rec in samples.items():
        name=names.get(pk,pk)
        if name in rep_pieces:
            raise BosExportError(f'two parts share the name {name}; BOS needs unique piece names')
        rep_pieces[name]={}; replay_input[name]={}; fidelity[name]={}
        for kind,axes in rec.items():
            rep_pieces[name][kind]={}; replay_input[name][kind]={}; fidelity[name][kind]={}
            tol=tol_deg if kind=='rot' else tol_pos
            for a in 'xyz':
                v=bx_unwrap(axes[a]) if kind=='rot' else list(axes[a])
                idx=bx_simplify(rel,v,tol)
                def ramp_ok(i, pk=pk):
                    # a ramp applies only where a key sits, and an 'instant' key has none
                    if not ramps: return False
                    return keyticks[pk].get(rel[i]) not in (None,'instant')
                pt, pv = bx_expand(rel, v, idx, lambda i: ramp_ok(i), lambda i: ramp_ok(i))
                if kind=='rot': intended=[bx_raw(bx_interp(pt,pv,t)) for t in rel]
                else: intended=[bx_pos_raw(bx_interp(pt,pv,t)) for t in rel]
                replay_input[name][kind][a]=intended
                # fidelity: intended path against the keyed motion, in the axis's own unit
                worst=(0.0,0)
                for t in rel:
                    iv=bx_interp(pt,pv,t); kv=v[t]
                    if kind=='rot': diff=abs(((iv-kv)+180.0)%360.0-180.0)
                    else: diff=abs(iv-kv)
                    if diff>worst[0]: worst=(diff,t)
                fidelity[name][kind][a]=(round(worst[0],4),worst[1])
                rep_pieces[name][kind][a]={'breakpoints':len(idx),'points':len(pt)}
                for tick,tgt,spd in bx_schedule(pt,pv,kind):
                    cmd_list.append((tick,name,kind,a,tgt,spd))
                cmd_list.append((0,name,kind,a,intended[0],None))
    cmd_list.sort(key=lambda c:(c[0], 0 if c[5] is None else 1))
    groups=[]
    for tick,name,kind,a,tgt,spd in cmd_list:
        item=(name,kind,a,tgt,spd)
        if groups and groups[-1][0]==tick: groups[-1][1].append(item)
        else: groups.append((tick,[item]))
    last=0
    for tick,items in groups:
        if tick>last:
            body.append(f'    sleep {bx_ms_for_ticks(tick-last)};')
            last=tick
        for name,kind,a,tgt,spd in items:
            if kind=='rot':
                if spd is None: body.append(f'    turn {name} to {a}-axis <{bx_literal(tgt)}> now;')
                else: body.append(f'    turn {name} to {a}-axis <{bx_literal(tgt)}> speed <{bx_literal(spd)}>;')
            else:
                if spd is None: body.append(f'    move {name} to {a}-axis [{bx_linear_literal(tgt)}] now;')
                else: body.append(f'    move {name} to {a}-axis [{bx_linear_literal(tgt)}] speed [{bx_linear_literal(spd)}];')
    if L>last:
        body.append(f'    sleep {bx_ms_for_ticks(L-last)};')
    kinds=[k for pk in samples for k in samples[pk]]
    header=[
        f'// BOS export: clip "{clip_name}"',
        f'// source: {source or "(unnamed)"}; span {s}..{e} at {BX_TICKS_PER_SECOND} ticks per second',
        f'// rotation tolerance {tol_deg} deg; offset tolerance {tol_pos} units; loop: {tl.get("loop")}; seam policy: {loop_policy}',
        f'// accel/decel ramps: {"on" if ramps else "off"}; seam mismatches: {len(seams)}',
    ]
    fn=''.join(c if (c.isalnum() or c=='_') else '_' for c in clip_name) or 'Clip'
    text='\n'.join(header+[f'{fn}()','{']+body+['}',''])
    report={'seams':seams,'pieces':rep_pieces,'fidelity':fidelity,'ticks':L,'tol_deg':tol_deg,'tol_pos':tol_pos,
            'loop_policy':loop_policy,'ramps':ramps}
    return text, report, replay_input

# ---- the replayer: reads the emitted text back with the engine's rules ----
_BX_RE=None
def _bx_regex():
    global _BX_RE
    if _BX_RE is None:
        import re as _bxre
        _BX_RE={
            'turn_now':_bxre.compile(r'^\s*turn (\S+) to (x|y|z)-axis <([-0-9.]+)> now;\s*$'),
            'turn_spd':_bxre.compile(r'^\s*turn (\S+) to (x|y|z)-axis <([-0-9.]+)> speed <([-0-9.]+)>;\s*$'),
            'move_now':_bxre.compile(r'^\s*move (\S+) to (x|y|z)-axis \[([-0-9.]+)\] now;\s*$'),
            'move_spd':_bxre.compile(r'^\s*move (\S+) to (x|y|z)-axis \[([-0-9.]+)\] speed \[([-0-9.]+)\];\s*$'),
            'sleep':_bxre.compile(r'^\s*sleep (\d+);\s*$'),
        }
    return _BX_RE

def bos_verify(text, replay_input):
    """Reads the emitted BOS back and compares each axis with the intended path, tick by tick.
    Returns {piece: {'rot': {axis: (max error, tick)}, 'pos': {axis: (max error, tick)}}}.
    Rotation errors are in degrees, offset errors in 3DO units. Ticks are relative to the span start."""
    rx=_bx_regex()
    state={}
    L=0
    for name,kinds in replay_input.items():
        for kind,axes in kinds.items():
            for a,row in axes.items():
                state[(name,kind,a)]={'cur':None,'tgt':None,'step':0}
                L=max(L,len(row)-1)
    worst={}
    def target_at(name,kind,a,t):
        row=replay_input[name][kind][a]
        return row[min(t,len(row)-1)]
    def physics():
        for (name,kind,a),st in state.items():
            if st['cur'] is None or st['tgt'] is None or st['cur']==st['tgt']: continue
            if kind=='rot':
                diff=bx_shortest(st['tgt']-st['cur'])
                if abs(diff)<=st['step']: st['cur']=st['tgt']
                else: st['cur']=(st['cur']+(st['step'] if diff>0 else -st['step']))&0xffff
            else:
                diff=st['tgt']-st['cur']
                if abs(diff)<=st['step']: st['cur']=st['tgt']
                else: st['cur']=st['cur']+(st['step'] if diff>0 else -st['step'])
    def compare(t):
        for (name,kind,a),st in state.items():
            if st['cur'] is None: continue
            target=target_at(name,kind,a,t)
            if kind=='rot':
                err=abs(bx_shortest(st['cur']-target))*360.0/BX_ANGLE_UNITS
            else:
                err=abs(st['cur']-target)/float(BX_ANGLE_UNITS)
            cur=worst.get((name,kind,a))
            if cur is None or err>cur[0]: worst[(name,kind,a)]=(err,t)
    tick=0
    for raw in text.splitlines():
        m=rx['turn_now'].match(raw)
        if m:
            st=state[(m.group(1),'rot',m.group(2))]
            st['cur']=bx_compile_value(m.group(3))&0xffff; st['tgt']=st['cur']; st['step']=0; continue
        m=rx['turn_spd'].match(raw)
        if m:
            st=state[(m.group(1),'rot',m.group(2))]
            st['tgt']=bx_compile_value(m.group(3))&0xffff; st['step']=bx_compile_value(m.group(4))//BX_TICKS_PER_SECOND; continue
        m=rx['move_now'].match(raw)
        if m:
            st=state[(m.group(1),'pos',m.group(2))]
            st['cur']=bx_compile_linear(m.group(3)); st['tgt']=st['cur']; st['step']=0; continue
        m=rx['move_spd'].match(raw)
        if m:
            st=state[(m.group(1),'pos',m.group(2))]
            st['tgt']=bx_compile_linear(m.group(3)); st['step']=bx_compile_linear(m.group(4))//BX_TICKS_PER_SECOND; continue
        m=rx['sleep'].match(raw)
        if m:
            for _ in range((BX_TICKS_PER_SECOND*int(m.group(1)))//1000):
                compare(tick); physics(); tick+=1
            continue
    compare(tick)
    out={}
    for (name,kind,a),(err,t) in worst.items():
        out.setdefault(name,{}).setdefault(kind,{})[a]=(round(err,4),t)
    return out

# ---- test run: the replay as frames, for the test-run panel ----
def bx_functions(text):
    """{name: body lines} for each NAME() { ... } block in a BOS text."""
    import re as _bxre
    head=_bxre.compile(r'^\s*(\w+)\s*\(\s*\)\s*$')
    lines=text.splitlines(); out={}; i=0
    while i<len(lines):
        m=head.match(lines[i])
        if not m:
            i+=1; continue
        j=i+1
        while j<len(lines) and lines[j].strip()!='{': j+=1
        body=[]; depth=1; k=j+1
        while k<len(lines):
            s=lines[k].strip()
            if s.endswith('{'): depth+=1
            if s=='}':
                depth-=1
                if depth==0: break
            body.append(lines[k]); k+=1
        out[m.group(1)]=body
        i=k+1
    return out

def bx_play(text, function=None, max_ticks=900, statics=None, game=None):
    """Plays one function (or the whole text) the way the engine runs it, one tick at a time. Every piece starts at
    rest (zero). Commands: turn and move (now, or at a speed; the target is <degrees> or a bare raw engine value),
    sleep, wait-for-turn/move, call-script (inline, the caller waits), start-script (a parallel task). Integer
    variables are evaluated: static-vars persist in `statics` (pass the same dict to keep them between runs), locals
    live with their script. while and if run when their condition evaluates; a condition that needs state the playback
    does not have (a game call such as get, a parameter) is skipped and listed. Signals and masks have no motion and
    are listed as ignored. Returns (frames, notes): one frame per tick, {piece name: {'rot': {axis: raw},
    'pos': {axis: raw}}}; rotation raws are 16-bit angles, offsets are 16.16."""
    import re as _bxre, ast as _bxast
    rx=_bx_regex()
    funcs=bx_functions(text)
    if function is not None and function not in funcs:
        raise BosExportError(f'no function named {function}')
    if statics is None: statics={}
    game=dict(game or {})                     # game values the test sets (get HEALTH, get BUILD_PERCENT_LEFT, ...)
    notes={'skipped':set(),'ignored':set(),'unplayed':set(),'unknown_call':set(),'busy_loop':False,'capped':0,'depth':False}
    state={}
    ycount=[0]
    def slot(name,kind,a):
        return state.setdefault((name,kind,a),{'cur':0,'tgt':None,'step':0,'kind':kind})
    def frame():
        f={}
        for (name,kind,a),st in state.items():
            f.setdefault(name,{'rot':{},'pos':{}})[kind][a]=st['cur']
        return f
    def physics():
        for st in state.values():
            if st['tgt'] is None or st['cur']==st['tgt']: continue
            if st['kind']=='rot':
                diff=bx_shortest(st['tgt']-st['cur'])
                if abs(diff)<=st['step']: st['cur']=st['tgt']
                else: st['cur']=(st['cur']+(st['step'] if diff>0 else -st['step']))&0xffff
            else:
                diff=st['tgt']-st['cur']
                if abs(diff)<=st['step']: st['cur']=st['tgt']
                else: st['cur']=st['cur']+(st['step'] if diff>0 else -st['step'])
    def finished(key):
        st=state.get(key)
        return st is None or st['tgt'] is None or st['cur']==st['tgt']

    # ---- values: <deg> is an angle, a bare number is already a raw engine value ----
    VAL=r'(<-?[0-9.]+>|-?[0-9]+|\[-?[0-9.]+\])'
    def angle_raw(tok):
        return (bx_compile_value(tok[1:-1]) if tok.startswith('<') else int(tok))&0xffff
    def linear_raw(tok):
        if tok.startswith('['): return bx_compile_linear(tok[1:-1])
        return int(tok)
    c_turn_now=_bxre.compile(r'^turn (\S+) to (x|y|z)-axis '+VAL+r' now$')
    c_turn_spd=_bxre.compile(r'^turn (\S+) to (x|y|z)-axis '+VAL+r' speed '+VAL+r'$')
    c_move_now=_bxre.compile(r'^move (\S+) to (x|y|z)-axis '+VAL+r' now$')
    c_move_spd=_bxre.compile(r'^move (\S+) to (x|y|z)-axis '+VAL+r' speed '+VAL+r'$')
    c_sleep=_bxre.compile(r'^sleep (\d+)$')
    c_sleep_expr=_bxre.compile(r'^sleep\s+(.+)$')
    c_wait=_bxre.compile(r'^wait-for-(turn|move)\s+(\S+)\s+(?:to|around|along)\s+(x|y|z)-axis$')
    c_call=_bxre.compile(r'^(call|start)-script\s+(\w+)\s*\(')
    c_assign=_bxre.compile(r'^([A-Za-z_][\w\-]*)\s*=(?!=)\s*(.+)$')
    head_while=_bxre.compile(r'^while\s*\((.*)\)\s*\{?\s*$')
    head_if=_bxre.compile(r'^if\s*\((.*)\)\s*\{?\s*$')

    # ---- integer expressions: names come from the statics (sv...) and the script's locals ----
    class _Unknown(Exception): pass
    def to_py(expr):
        e=_bxre.sub(r'\bget\s+(\w+)',lambda m:'g_'+m.group(1),expr.strip())
        e=e.replace('&&',' and ').replace('||',' or ')
        e=_bxre.sub(r'!(?!=)','not ',e)
        return e.strip()
    def evaluate(expr,env):
        src=to_py(expr)
        try: tree=_bxast.parse(src,mode='eval')
        except SyntaxError: raise _Unknown(expr)
        env=dict(env)
        for k,v in game.items(): env.setdefault('g_'+k,v)
        for node in _bxast.walk(tree):             # a static that was never set is 0, as it is in the engine
            if isinstance(node,_bxast.Name) and node.id not in env and node.id.startswith('sv'): env[node.id]=0
        for node in _bxast.walk(tree):
            if not isinstance(node,(_bxast.Expression,_bxast.BinOp,_bxast.UnaryOp,_bxast.BoolOp,_bxast.Compare,
                                    _bxast.Name,_bxast.Constant,_bxast.Load,_bxast.operator,_bxast.unaryop,
                                    _bxast.boolop,_bxast.cmpop)):
                raise _Unknown(expr)
            if isinstance(node,_bxast.Name) and node.id not in env: raise _Unknown(expr)
        vals={k:v for k,v in env.items()}
        for node in _bxast.walk(tree):
            if isinstance(node,_bxast.Name) and vals.get(node.id) is None: raise _Unknown(expr)
        try: return int(eval(compile(tree,'<bos>','eval'),{'__builtins__':{}},vals))
        except Exception: raise _Unknown(expr)

    def run_nodes(nodes,local,depth=0):
        for node in nodes:
            if node[0]=='cmd':
                t=node[1]
                m=c_turn_now.match(t)
                if m:
                    st=slot(m.group(1),'rot',m.group(2)); st['cur']=angle_raw(m.group(3)); st['tgt']=st['cur']; st['step']=0
                    continue
                m=c_turn_spd.match(t)
                if m:
                    st=slot(m.group(1),'rot',m.group(2)); st['tgt']=angle_raw(m.group(3))
                    st['step']=angle_raw(m.group(4))//BX_TICKS_PER_SECOND
                    continue
                m=c_move_now.match(t)
                if m:
                    st=slot(m.group(1),'pos',m.group(2)); st['cur']=linear_raw(m.group(3)); st['tgt']=st['cur']; st['step']=0
                    continue
                m=c_move_spd.match(t)
                if m:
                    st=slot(m.group(1),'pos',m.group(2)); st['tgt']=linear_raw(m.group(3))
                    st['step']=linear_raw(m.group(4))//BX_TICKS_PER_SECOND
                    continue
                m=c_sleep.match(t)
                if m:
                    ycount[0]+=1; yield ('sleep',(BX_TICKS_PER_SECOND*int(m.group(1)))//1000); continue
                m=c_sleep_expr.match(t)               # sleep v1; a duration held in a variable
                if m:
                    try: ms=evaluate(m.group(1),{**statics,**local})
                    except _Unknown: notes['skipped'].add('sleep '+m.group(1)); continue
                    ycount[0]+=1; yield ('sleep',(BX_TICKS_PER_SECOND*max(0,ms))//1000); continue
                m=c_wait.match(t)
                if m:
                    ycount[0]+=1; yield ('wait',(m.group(2),'rot' if m.group(1)=='turn' else 'pos',m.group(3))); continue
                m=c_call.match(t)
                if m:
                    target=m.group(2)
                    if target not in funcs: notes['unknown_call'].add(target); continue
                    if m.group(1)=='call':
                        if depth>=32: notes['depth']=True; continue
                        yield from run_nodes(body_of(target),{},depth+1)
                    else:
                        spawned.append(target)
                    continue
                m=c_assign.match(t)
                if m:
                    name=m.group(1); store=statics if name.startswith('sv') else local
                    try: store[name]=evaluate(m.group(2),{**statics,**local})
                    except _Unknown: store[name]=None
                    continue
                word=t.split()[0] if t.split() else ''
                if word in ('spin','stop-spin'): notes['unplayed'].add(word)     # motion, not played yet
                elif word in ('var','static-var'): pass                           # declarations
                elif word: notes['ignored'].add(word)                            # no motion of its own
            elif node[0]=='while':
                if node[1].strip().upper()=='TRUE' or node[1].strip()=='1':
                    cond=True
                else:
                    try: cond=bool(evaluate(node[1],{**statics,**local}))
                    except _Unknown: notes['skipped'].add('while ('+node[1]+')'); continue
                if cond:
                    while True:
                        y0=ycount[0]
                        yield from run_nodes(node[2],local,depth)
                        if ycount[0]==y0:          # an iteration with no sleep or wait would spin forever; stop it
                            notes['busy_loop']=True; break
                        if not (node[1].strip().upper()=='TRUE' or node[1].strip()=='1'):
                            try:
                                if not evaluate(node[1],{**statics,**local}): break
                            except _Unknown: break
            else:
                try: v=bool(evaluate(node[1],{**statics,**local}))
                except _Unknown:
                    notes['skipped'].add('if ('+node[1]+')'); continue
                branch=node[2] if v else (node[3] or [])
                yield from run_nodes(branch,local,depth)

    # ---- the body as nested nodes: ('cmd', text) | ('while', cond, body) | ('if', cond, body, else_body) ----
    def parse(lines,i,in_block):
        nodes=[]
        while i<len(lines):
            s_=lines[i].strip(); i+=1
            if not s_ or s_.startswith('//'): continue
            if s_.startswith('}'):
                if in_block: return nodes,i,s_
                continue
            m=head_while.match(s_)
            if m:
                if not s_.endswith('{') and i<len(lines) and lines[i].strip()=='{': i+=1
                body,i,_=parse(lines,i,True)
                nodes.append(('while',m.group(1).strip(),body)); continue
            m=head_if.match(s_)
            if m:
                if not s_.endswith('{') and i<len(lines) and lines[i].strip()=='{': i+=1
                body,i,closer=parse(lines,i,True)
                else_body=None
                if closer.startswith('} else'):
                    if not closer.endswith('{') and i<len(lines) and lines[i].strip()=='{': i+=1
                    else_body,i,_=parse(lines,i,True)
                nodes.append(('if',m.group(1).strip(),body,else_body)); continue
            nodes.append(('cmd',s_.rstrip(';').strip()))
        return nodes,i,''
    body_cache={}
    def body_of(name):
        if name not in body_cache:
            body_cache[name]=parse(funcs[name],0,False)[0]
        return body_cache[name]
    spawned=[]

    tasks=[]
    def start(name):
        tasks.append({'gen':run_nodes(body_of(name),{}),'sleep':0,'wait':None,'name':name})
    for nm in ([function] if function else list(funcs)[:1]): start(nm)
    tick=0; frames=[]
    while tasks and tick<max_ticks:
        frames.append(frame())                       # a tick shows the state its commands start from
        for task in list(tasks):
            if task['sleep']>0: task['sleep']-=1; continue
            if task['wait'] is not None:
                if not finished(task['wait']): continue
                task['wait']=None
            while True:
                try: y=next(task['gen'])
                except StopIteration: tasks.remove(task); break
                if y[0]=='sleep':
                    task['sleep']=max(0,y[1]-1); break
                if not finished(y[1]):
                    task['wait']=y[1]; break
        while spawned: start(spawned.pop(0))
        physics(); tick+=1
    frames.append(frame())                           # the last state, after the final motion
    notes['capped']=len(tasks)
    notes['statics']=statics
    notes['game_unset']=[]
    for k in ('skipped','ignored','unplayed','unknown_call'): notes[k]=sorted(notes[k])
    return frames, notes

def bx_run(text, function=None, max_ticks=900):
    """The frames of bx_play, without the notes."""
    return bx_play(text,function,max_ticks)[0]
