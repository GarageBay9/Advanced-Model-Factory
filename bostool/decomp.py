import sys, re
from cob import read_cob
from ops import *

class DecompError(Exception): pass

def _strip_outer(e):
    """Remove one pair of parentheses that encloses the whole expression."""
    while e.startswith('(') and e.endswith(')'):
        d=0
        for k,ch in enumerate(e):
            d+= (ch=='(') - (ch==')')
            if d==0 and k!=len(e)-1: return e
        e=e[1:-1]
    return e

def _literal(e, kind):
    """Render a bare integer as [linear] or <angle> only when the decimal text converts back exactly."""
    if not re.fullmatch(r'-?\d+', e): return e
    v=int(e)
    for d in range(7):
        if kind=='lin': x=v/LINEAR_SCALE; s=f'{x:.{d}f}'; ok=int(round(float(s)*LINEAR_SCALE))==v; br=('[',']')
        else: x=v*360/65536; s=f'{x:.{d}f}'; ok=int(float(s)*65536/360)==v; br=('<','>')
        if ok: return br[0]+s+br[1]
    return e

# Parameter names for engine-called callbacks (Decompiler.cfg [COMMON_FUNC]). The COB stores no parameter count;
# parameters are simply the first locals. Unknown scripts are emitted with no parameters.
SIGNATURES={'RequestState':['requestedstate'],'SetSpeed':['the_speed'],'SetDirection':['dir'],
            'Killed':['severity','corpsetype'],'HitByWeapon':['anglex','anglez'],'RockUnit':['anglex','anglez'],
            'SweetSpot':['piecenum'],'AimFromPrimary':['piecenum'],'QueryPrimary':['piecenum'],
            'AimPrimary':['heading','pitch'],'SetMaxReloadTime':['time'],'TargetHeading':['heading']}

def decode(words, base=0, blobs=()):
    """Turn the word stream into instructions: (addr, opcode, imms).
    Jump targets in the stream are global word indices; rebase them to the script."""
    out=[]; i=0
    while i<len(words):
        g=base+i
        blob=next(((s,e) for s,e in blobs if s<=g<e),None)
        if blob: i+=blob[1]-g; continue          # skip text blocks such as the COBBLER signature
        w=words[i]
        if (w & 0xF0000000)!=0x10000000:
            raise DecompError(f'expected opcode at word {i}, got {w:#x}')
        if w not in IMM: raise DecompError(f'unsupported opcode {w:#010x} at word {i}')
        n=IMM[w]
        imms=list(words[i+1:i+1+n])
        if w in (JF,JMP): imms=[imms[0]-base]
        out.append((i,w,imms)); i+=1+n
    return out

class Script:
    def __init__(self, cob, idx, snames=None):
        self.cob=cob; self.idx=idx
        self.snames=snames or {}     # static index -> label (see static_labels)
        self.name, self.words = cob['scripts'][idx]
        self.ins=decode(self.words, cob['starts'][idx], cob.get('blobs',()))
        self.ndecl=sum(1 for _,op,_ in self.ins if op==DECL_LOCAL)
        self.stack=[]; self.loops=[]
    def pieces(self,p):
        if p<0 or p>=len(self.cob['pieces']): raise DecompError(f'piece index {p}')
        return self.cob['pieces'][p]
    def axis(self,a):
        if a<0 or a>2: raise DecompError(f'axis {a}')
        return AXES[a]
    def pop(self):
        if not self.stack: raise DecompError(f'stack underflow in {self.name}')
        return self.stack.pop()
    def pop_n(self,n):
        if len(self.stack)<n: raise DecompError(f'stack underflow in {self.name}')
        vals=self.stack[len(self.stack)-n:] if n else []
        del self.stack[len(self.stack)-n:]
        return vals
    def expr_for_ins(self, op, imms):
        if op==PUSH_LIT: return str(imms[0])
        if op==PUSH_LOCAL: return self.local_name(imms[0])
        if op==PUSH_STATIC: return self.static_name(imms[0])
        if op==GET:
            p=self.pop()
            return f'get {PORTS[int(p)]}' if p.isdigit() and int(p) in PORTS else f'get({p})'
        if op==GET_ARGS:
            vals=self.pop_n(5); port=vals[0]; args=vals[1:]
            while args and args[-1]=='0': args.pop()
            name=PORTS[int(port)] if port.isdigit() and int(port) in PORTS else f'({port})'
            return f'get {name}({", ".join(args)})'
        if op==RAND:
            a,b=self.pop_n(2)
            return f'rand( {a}, {b} )'
        if op==NOT:
            return f'!({self.pop()})'
        if op==BNOT: return f'~({self.pop()})'
        if op==READ_ONE: return f'engine-read1({self.pop()})'
        if op==READ_NONE: return 'engine-read0()'
        if op in BINARY:
            a,b=self.pop_n(2)
            return f'({a} {BINARY[op]} {b})'
        raise DecompError('not an expression op')
    def emit_stmt(self, op, imms, ind):
        P=lambda s: '    '*ind+s
        if op==DECL_LOCAL: return []
        if op==POP_LOCAL: return [P(f'{self.local_name(imms[0])} = {_strip_outer(self.pop())};')]
        if op==POP_STATIC: return [P(f'{self.static_name(imms[0])} = {_strip_outer(self.pop())};')]
        if op==RET: return [P(f'return {_strip_outer(self.pop())};')]
        if op==SPIN:
            accel,speed=self.pop_n(2)
            s=f'spin {self.pieces(imms[0])} around {self.axis(imms[1])} speed {speed}'
            if accel!='0': s+=f' accelerate {accel}'
            return [P(s+';')]
        if op==STOP_SPIN:
            return [P(f'stop-spin {self.pieces(imms[0])} around {self.axis(imms[1])} decelerate {self.pop()};')]
        if op==TURN_SPEED:
            speed,ang=[_literal(x,'ang') for x in self.pop_n(2)]  # speed pushed first
            return [P(f'turn {self.pieces(imms[0])} to {self.axis(imms[1])} {ang} speed {speed};')]
        if op==ATTACH_UNIT:
            u,p,_pad=self.pop_n(3)  # third slot is a 0 pad
            return [P(f'attach-unit {u} to {p};')]
        if op==DROP_UNIT:
            return [P(f'drop-unit {self.pop()};')]
        if op==TURN_NOW:
            return [P(f'turn {self.pieces(imms[0])} to {self.axis(imms[1])} {_literal(self.pop(),"ang")} now;')]
        if op==MOVE_NOW:
            return [P(f'move {self.pieces(imms[0])} to {self.axis(imms[1])} {_literal(self.pop(),"lin")} now;')]
        if op==MOVE_SPEED:
            speed,val=[_literal(x,'lin') for x in self.pop_n(2)]  # speed pushed first
            return [P(f'move {self.pieces(imms[0])} to {self.axis(imms[1])} {val} speed {speed};')]
        if op==DISCARD: return [P(f'discard {self.pop()};  // retail: discards the top of stack; not compilable')]
        if op==LEGACY_EFFECT:
            a,b=self.pop_n(2)
            return [P(f'legacy-effect {a}, {b};  // retail no-op on units; operand order not confirmed; not compilable')]
        if op==RESERVED_POPN:
            n=imms[1]
            for _ in range(max(n,0)): self.pop()
            return [P(f'reserved-pop {n};  // retail pops and discards n values; no shipped script uses it; not compilable')]
        simple={SHOW:'show',HIDE:'hide',CACHE:'cache',DONT_CACHE:'dont-cache',
                DONT_SHADOW:'dont-shadow',DONT_SHADE:'dont-shade',SHADE:'shade'}
        if op in simple: return [P(f'{simple[op]} {self.pieces(imms[0])};')]
        if op==EMIT_SFX: return [P(f'emit-sfx {self.pop()} from {self.pieces(imms[0])};')]
        if op==WAIT_TURN: return [P(f'wait-for-turn {self.pieces(imms[0])} around {self.axis(imms[1])};')]
        if op==WAIT_MOVE: return [P(f'wait-for-move {self.pieces(imms[0])} along {self.axis(imms[1])};')]
        if op==SLEEP: return [P(f'sleep {self.pop()};')]
        if op==EXPLODE: return [P(f'explode {self.pieces(imms[0])} type {self.pop()};')]
        if op==SIGNAL: return [P(f'signal {self.pop()};')]
        if op==SIGMASK: return [P(f'set-signal-mask {self.pop()};')]
        if op==SET:
            port,val=self.pop_n(2)
            if port.isdigit() and int(port) in PORTS: pn=PORTS[int(port)]
            else: raise DecompError(f'unknown port {port}')
            return [P(f'set {pn} to {val};')]
        if op in (CALL,START):
            sidx,nargs=imms
            args=self.pop_n(nargs)
            kw='call-script' if op==CALL else 'start-script'
            return [P(f'{kw} {self.cob["names"][sidx]}({", ".join(args)});')]
        raise DecompError(f'no statement form for {op:#010x}')

    def block(self, lo, hi, ind):
        """Structure instructions with address in [lo,hi). Returns list of lines."""
        out=[]; k=self.pos_of(lo)
        while k<len(self.ins) and self.ins[k][0]<hi:
            addr,op,imms=self.ins[k]
            if op in IMM and op in BINARY or op in (PUSH_LIT,PUSH_LOCAL,PUSH_STATIC,GET,GET_ARGS,RAND,NOT,BNOT,READ_ONE,READ_NONE):
                self.stack.append(self.expr_for_ins(op,imms)); k+=1; continue
            if op==JF:
                T=imms[0]; cond=_strip_outer(self.pop())
                # while loop: back-edge JMP just before the exit target
                back=self.ins_at(T-2)
                if back and back[1]==JMP and back[2][0]<=addr:
                    H=back[2][0]
                    self.loops.append((H,T))
                    body=self.block(addr+2,T-2,ind+1)
                    self.loops.pop()
                    out.append('    '*ind+f'while ( {cond} )')
                    out.append('    '*ind+'{'); out+=body; out.append('    '*ind+'}')
                    k=self.pos_of(T); continue
                loopexit=self.loops[-1][1] if self.loops else None
                if back and back[1]==JMP and back[2][0]>T-2 and back[2][0]!=loopexit:
                    E=back[2][0]
                    then=self.block(addr+2,T-2,ind+1)
                    els=self.block(T,E,ind+1)
                    out.append('    '*ind+f'if ( {cond} )'); out.append('    '*ind+'{'); out+=then; out.append('    '*ind+'}')
                    out.append('    '*ind+'else'); out.append('    '*ind+'{'); out+=els; out.append('    '*ind+'}')
                    k=self.pos_of(E); continue
                then=self.block(addr+2,T,ind+1)
                out.append('    '*ind+f'if ( {cond} )'); out.append('    '*ind+'{'); out+=then; out.append('    '*ind+'}')
                k=self.pos_of(T); continue
            if op==JMP:
                T=imms[0]
                if self.loops and T==self.loops[-1][1]: out.append('    '*ind+'break;')
                elif self.loops and T==self.loops[-1][0]: out.append('    '*ind+'continue;')
                else: raise DecompError(f'unstructured jump at {addr} -> {T} in {self.name}')
                k+=1; continue
            if op==RET and addr==self.implicit_ret:
                self.pop(); k+=1; continue      # the compiler regenerates this one
            out+=self.emit_stmt(op,imms,ind); k+=1
        return out
    def static_name(self,i):
        return self.snames.get(i, f'sv{i}')
    def local_name(self,i):
        params=SIGNATURES.get(self.name,[])
        return params[i] if i<len(params) else f'v{i}'
    def pos_of(self,addr):
        for k,(a,_,_) in enumerate(self.ins):
            if a>=addr: return k
        return len(self.ins)
    def ins_at(self,addr):
        for a,op,imms in self.ins:
            if a==addr: return (a,op,imms)
        return None
    def render(self):
        # Every compiled function ends with an implicit 'push 0; return' that the compiler adds itself.
        self.implicit_ret=None
        if len(self.ins)>=2 and self.ins[-1][1]==RET and self.ins[-2][1]==PUSH_LIT and self.ins[-2][2]==[0]:
            self.implicit_ret=self.ins[-1][0]
        body=self.block(0,len(self.words),1)
        if self.stack: raise DecompError(f'leftover stack in {self.name}: {self.stack}')

        params=SIGNATURES.get(self.name,[])
        if self.ndecl < len(params): params=params[:self.ndecl]   # the COB declares fewer; keep its count
        names=params+[f'v{i}' for i in range(len(params),self.ndecl)]
        lines=[f'{self.name}('+', '.join(params)+')','{']
        if len(names)>len(params): lines.append('    var '+', '.join(names[len(params):])+';')
        lines+=body+['}']
        return '\n'.join(lines)

def detect_flavor(cob):
    """Brain always appends an implicit 'push 0; return' even after an explicit return, leaving a
    doubled pair; the retail compiler appends it only when the function does not already end in a return."""
    for k,(_,w) in enumerate(cob['scripts']):
        ins=decode(w, cob['starts'][k], cob.get('blobs',()))
        if len(ins)>=4 and [o for _,o,_ in ins[-4:]]==[PUSH_LIT,RET,PUSH_LIT,RET] and ins[-4][2]==[0] and ins[-2][2]==[0]:
            return 'brain'
    return 'retail'

def static_labels(cob):
    """Function-based labels for static variables. A static referenced by exactly one script is named
    <Script>FunctionVar (then <Script>FunctionVar2, FunctionVar3, ... if that script has several). A static
    used by several scripts, or by none, keeps its neutral name sv<N>. Only the references in the COB are
    used; nothing is guessed from the variable's behaviour."""
    users={}
    for k,(name,w) in enumerate(cob['scripts']):
        for a,op,imms in decode(w, cob['starts'][k], cob.get('blobs',())):
            if op in (PUSH_STATIC,POP_STATIC):
                users.setdefault(imms[0],set()).add(name)
    labels={}; per_script={}
    for i in sorted(users):
        if i>=cob['nstatics'] or len(users[i])!=1: continue
        s=next(iter(users[i])); k=per_script.get(s,0)+1; per_script[s]=k
        labels[i]=f'{s}FunctionVar' if k==1 else f'{s}FunctionVar{k}'
    return labels

def decompile(path, label_functions=False):
    cob=read_cob(path)
    flavor=detect_flavor(cob)
    snames=static_labels(cob) if label_functions else {}
    out=[f'// compiler: {flavor}']
    out.append('piece '+', '.join(cob['pieces'])+';')
    out.append('static-var '+', '.join(snames.get(i,f'sv{i}') for i in range(cob['nstatics']))+';')
    out.append('')
    for i in range(len(cob['scripts'])):
        out.append(Script(cob,i,snames).render())
        out.append('')
    return '\n'.join(out)

if __name__=='__main__':
    print(decompile(sys.argv[1]))
