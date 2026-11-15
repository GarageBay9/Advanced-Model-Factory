"""BOS -> TA v4 COB compiler. Input is preprocessed BOS text (see pp.py).
Keywords, variables, pieces, ports and script names are matched case-insensitively; the names written
into the COB keep the case used at their definition. Jump targets are global word indices."""
import re, struct
from ops import *

class CompileError(Exception): pass

TOKEN=re.compile(r'''
   (?P<ws>\s+|//[^\n]*|/\*.*?\*/)
 | (?P<num>\d+(?:\.\d+)?)
 | (?P<ident>[A-Za-z_][A-Za-z0-9_]*(?:-[A-Za-z_][A-Za-z0-9_]*)*)
 | (?P<op>==|!=|<=|>=|&&|\|\||[-+*/<>=!|?(){}\[\];,])
''', re.X|re.S)

class Toks(list):
    """Token list with a parallel .lines list (1-based line of each token)."""
    lines=None

def tokenize(src):
    out=Toks(); lines=[]; pos=0; line=1
    while pos<len(src):
        m=TOKEN.match(src,pos)
        if not m:
            raise CompileError(f'line {line}: bad character {src[pos]!r}')
        tok_start=m.start(); pos=m.end()
        if m.lastgroup=='ws':
            line+=m.group(0).count('\n'); continue
        out.append((m.lastgroup, m.group(m.lastgroup))); lines.append(line)
        line+=m.group(0).count('\n')
    out.append(('eof','')); lines.append(line)
    out.lines=lines
    return out

PREC={'*':50,'/':50,'+':40,'-':40,'<':30,'<=':30,'>':30,'>=':30,'==':30,'!=':30,'|':20,'?':20,'&&':10,'||':10}
BIN_OP={'+':0x10031000,'-':0x10032000,'*':0x10033000,'/':0x10034000,'<':0x10051000,'<=':0x10052000,
        '>':0x10053000,'>=':0x10054000,'==':0x10055000,'!=':0x10056000,'|':0x10036000,
        '&&':0x10057000,'||':0x10058000,'?':0x10035000}
AXIS={'x-axis':0,'y-axis':1,'z-axis':2}
SIMPLE_PIECE={'show':SHOW,'hide':HIDE,'cache':CACHE,'dont-cache':DONT_CACHE,
              'dont-shadow':DONT_SHADOW,'dont-shade':DONT_SHADE,'shade':SHADE}
PORT_BY_NAME={v:k for k,v in PORTS.items()}

class Ctx:
    def __init__(self, pieces, scripts, statics):
        self.pieces={n.lower():i for i,n in enumerate(pieces)}
        self.scripts={n.lower():i for i,n in enumerate(scripts)}
        self.statics={n.lower():i for i,n in enumerate(statics)}
    def piece(self,n):
        if n.lower() not in self.pieces: raise CompileError(f"unknown piece '{n}': not declared in the BOS and not in the unit's piece list. Check the unit's 3DO model before adding it.")
        return self.pieces[n.lower()]
    def script(self,n):
        if n.lower() not in self.scripts: raise CompileError(f'unknown script {n}')
        return self.scripts[n.lower()]
    def port(self,n):
        if n.upper() in PORT_BY_NAME: return PORT_BY_NAME[n.upper()]
        raise CompileError(f'unknown unit value {n}')

def to_fixed_linear(x): return int(round(float(x)*LINEAR_SCALE))  # 65536 default; 163840 for sources written at 2.5x (see the Build menu note)
def to_fixed_angle(x):  return int(float(x)*65536/360)  # retail truncates

class Parser:
    def __init__(self, toks, ctx):
        self.t=toks; self.i=0; self.ctx=ctx; self.L={}
    def peek(self,k=0): return self.t[self.i+k]
    def next(self):
        tok=self.t[self.i]; self.i+=1; return tok
    def accept(self,val):
        k,v=self.peek()
        if v.lower()==val.lower() and k!='num' and k!='eof' or (k=='op' and v==val):
            self.i+=1; return True
        return False
    def expect(self,val):
        if not self.accept(val): raise CompileError(f'expected {val!r}, got {self.peek()[1]!r}')
    def ident(self):
        k,v=self.next()
        if k!='ident': raise CompileError(f'expected identifier, got {v!r}')
        return v

    # ---- expressions: ('lit',n) ('local',i) ('static',i) ('get',port) ('get_expr',e) ('rand',a,b) ('not',e) ('bin',op,a,b)
    def num_signed(self):
        neg=self.accept('-')
        k,v=self.next()
        if k!='num': raise CompileError('expected a number')
        x=float(v) if '.' in v else int(v)
        return -x if neg else x
    def primary(self):
        k,v=self.peek()
        if k=='op' and v=='[':
            self.next(); x=self.num_signed(); self.expect(']'); return ('lit', to_fixed_linear(x))
        if k=='op' and v=='<':
            self.next(); x=self.num_signed(); self.expect('>'); return ('lit', to_fixed_angle(x))
        if k=='op' and v=='(':
            self.next(); e=self.expr(); self.expect(')'); return e
        if k=='op' and v in ('!',):
            self.next(); return ('not', self.primary())
        if k=='op' and v=='-' and self.peek(1)[0]=='num':
            self.next(); return ('lit', -int(float(self.next()[1])))
        if k=='num':
            self.next(); return ('lit', int(float(v)))
        if k=='ident':
            self.next(); lv=v.lower()
            if lv=='not': return ('not', self.primary())
            if lv=='get':
                if self.peek()[1]=='(':
                    self.next(); e=self.expr(); self.expect(')'); return ('get_expr', e)
                port=self.port_token()
                if self.peek()[1]=='(':
                    self.next(); args=[]
                    if self.peek()[1]!=')':
                        args.append(self.expr())
                        while self.accept(','): args.append(self.expr())
                    self.expect(')'); return ('get_args', port, args)
                return ('get', port)
            if lv=='rand':
                self.expect('('); a=self.expr(); self.expect(','); b=self.expr(); self.expect(')')
                return ('rand', a, b)
            if lv=='true': return ('lit',1)
            if lv=='false': return ('lit',0)
            if lv in self.L: return ('local', self.L[lv])
            if lv in self.ctx.statics: return ('static', self.ctx.statics[lv])
            if lv in self.ctx.pieces: return ('lit', self.ctx.pieces[lv])
            raise CompileError(f"unknown name '{v}': not a local, static, piece or constant. If it is a piece, check the unit's 3DO model.")
        raise CompileError(f'unexpected {v!r} in expression')
    def port_token(self):
        # a unit value by name, or a number when a header has already expanded the name (EXPtype.h)
        k,v=self.next()
        if k=='num': return int(float(v))
        if k=='ident': return self.ctx.port(v)
        raise CompileError(f'expected a unit value, got {v!r}')
    def expr(self, minp=0):
        lhs=self.primary()
        while True:
            k,v=self.peek()
            if k=='ident' and v.lower() in ('and','or'): k,v='op',{'and':'&&','or':'||'}[v.lower()]
            if k!='op' or v not in PREC or PREC[v]<minp: break
            self.next()
            lhs=('bin', v, lhs, self.expr(PREC[v]+1))
        return lhs

    def emit_expr(self, e, out):
        t=e[0]
        if t=='lit': out.append(('ins',PUSH_LIT,[e[1]]))
        elif t=='local': out.append(('ins',PUSH_LOCAL,[e[1]]))
        elif t=='static': out.append(('ins',PUSH_STATIC,[e[1]]))
        elif t=='get': out.append(('ins',PUSH_LIT,[e[1]])); out.append(('ins',GET,[]))
        elif t=='get_expr': self.emit_expr(e[1],out); out.append(('ins',GET,[]))
        elif t=='get_args':
            out.append(('ins',PUSH_LIT,[e[1]]))
            for a in e[2]: self.emit_expr(a,out)
            for _ in range(4-len(e[2])): out.append(('ins',PUSH_LIT,[0]))
            out.append(('ins',GET_ARGS,[]))
        elif t=='rand': self.emit_expr(e[1],out); self.emit_expr(e[2],out); out.append(('ins',RAND,[]))
        elif t=='not': self.emit_expr(e[1],out); out.append(('ins',NOT,[]))
        elif t=='bin': self.emit_expr(e[2],out); self.emit_expr(e[3],out); out.append(('ins',BIN_OP[e[1]],[]))
        else: raise CompileError(f'bad expression {e}')

    # ---- statements (parsed into tuples, then emitted)
    def block(self):
        self.expect('{'); stmts=[]
        while not self.accept('}'): stmts.append(self.stmt())
        return stmts
    def axis(self):
        a=self.ident().lower()
        if a not in AXIS: raise CompileError(f'bad axis {a}')
        return AXIS[a]
    def piece(self): return self.ctx.piece(self.ident())
    def stmt(self):
        start=self.i
        try:
            return self._stmt()
        except CompileError as e:
            msg=str(e)
            if msg.startswith('line '): raise
            ln=self.t.lines[start] if getattr(self.t,'lines',None) else None
            raise CompileError(f'line {ln}: {msg}' if ln else msg)
    def _stmt(self):
        k,v=self.peek()
        if k=='ident' and self.peek(1)[1]=='=' and v.lower() not in ('return',):
            name=self.ident(); self.expect('=')
            e=self.expr(); self.expect(';'); return ('assign', name.lower(), e)
        self.next(); kw=v.lower()
        if kw=='return': e=self.expr(); self.expect(';'); return ('return', e)
        if kw=='if':
            self.expect('('); c=self.expr(); self.expect(')'); then=self.block(); els=None
            if self.accept('else'): els=self.block()
            return ('if', c, then, els)
        if kw=='while':
            self.expect('('); c=self.expr(); self.expect(')'); return ('while', c, self.block())
        if kw=='break': self.expect(';'); return ('break',)
        if kw=='continue': self.expect(';'); return ('continue',)
        if kw=='sleep': e=self.expr(); self.expect(';'); return ('sleep', e)
        if kw=='spin':
            p=self.piece(); self.expect('around'); a=self.axis(); self.expect('speed'); s=self.expr()
            acc=('lit',0)
            if self.accept('accelerate'): acc=self.expr()
            self.expect(';'); return ('spin', p, a, acc, s)
        if kw=='stop-spin':
            p=self.piece(); self.expect('around'); a=self.axis()
            if self.accept('decelerate'): d=self.expr()
            else: d=('lit',0)  # bare stop-spin = decelerate 0 (immediate stop); retail COBs encode it this way
            self.expect(';')
            return ('stop-spin', p, a, d)
        if kw in ('turn','move'):
            p=self.piece(); self.expect('to'); a=self.axis(); val=self.expr()
            if self.accept('now'): self.expect(';'); return (kw+'-now', p, a, val)
            self.expect('speed'); sp=self.expr(); self.expect(';'); return (kw+'-speed', p, a, val, sp)
        if kw in SIMPLE_PIECE: p=self.piece(); self.expect(';'); return ('piece-op', SIMPLE_PIECE[kw], p)
        if kw=='emit-sfx': e=self.expr(); self.expect('from'); p=self.piece(); self.expect(';'); return ('emit', e, p)
        if kw=='wait-for-turn': p=self.piece(); self.expect('around'); a=self.axis(); self.expect(';'); return ('wait', WAIT_TURN, p, a)
        if kw=='wait-for-move': p=self.piece(); self.expect('along'); a=self.axis(); self.expect(';'); return ('wait', WAIT_MOVE, p, a)
        if kw=='explode': p=self.piece(); self.expect('type'); e=self.expr(); self.expect(';'); return ('explode', p, e)
        if kw=='attach-unit': u=self.expr(); self.expect('to'); p=self.expr(); self.expect(';'); return ('attach', u, p)
        if kw=='drop-unit': u=self.expr(); self.expect(';'); return ('drop', u)
        if kw=='signal': e=self.expr(); self.expect(';'); return ('signal', e)
        if kw=='set-signal-mask': e=self.expr(); self.expect(';'); return ('sigmask', e)
        if kw=='set':
            port=self.port_token(); self.expect('to'); e=self.expr(); self.expect(';'); return ('set', port, e)
        if kw in ('call-script','start-script'):
            name=self.ident(); self.expect('('); args=[]
            if not self.accept(')'):
                args.append(self.expr())
                while self.accept(','): args.append(self.expr())
                self.expect(')')
            self.expect(';')
            return ('call' if kw=='call-script' else 'start', self.ctx.script(name), args)
        if kw=='play-sound': raise CompileError('play-sound is not supported yet (stub): the argument format is unconfirmed')
        raise CompileError(f'unknown statement starting {v!r}')

    def emit_stmts(self, stmts, out, loops):
        for s in stmts: self.emit_stmt(s, out, loops)
    def emit_stmt(self, s, out, loops):
        t=s[0]
        def E(e): self.emit_expr(e,out)
        def I(op,*imm): out.append(('ins',op,list(imm)))
        if t=='assign':
            E(s[2]); name=s[1]
            if name in self.L: I(POP_LOCAL, self.L[name])
            elif name in self.ctx.statics: I(POP_STATIC, self.ctx.statics[name])
            else: raise CompileError(f'unknown variable {name}')
        elif t=='return': E(s[1]); I(RET)
        elif t=='sleep': E(s[1]); I(SLEEP)
        elif t=='spin': E(s[3]); E(s[4]); I(SPIN,s[1],s[2])
        elif t=='stop-spin': E(s[3]); I(STOP_SPIN,s[1],s[2])
        elif t=='attach': E(s[1]); E(s[2]); I(PUSH_LIT,0); I(ATTACH_UNIT)  # ATTACH takes unit, piece, 0-pad
        elif t=='drop': E(s[1]); I(DROP_UNIT)
        elif t=='turn-now': E(s[3]); I(TURN_NOW,s[1],s[2])
        elif t=='turn-speed': E(s[4]); E(s[3]); I(TURN_SPEED,s[1],s[2])  # retail pushes speed first
        elif t=='move-now': E(s[3]); I(MOVE_NOW,s[1],s[2])
        elif t=='move-speed': E(s[4]); E(s[3]); I(MOVE_SPEED,s[1],s[2])  # retail pushes speed first
        elif t=='piece-op': I(s[1],s[2])
        elif t=='emit': E(s[1]); I(EMIT_SFX,s[2])
        elif t=='wait': I(s[1],s[2],s[3])
        elif t=='explode': E(s[2]); I(EXPLODE,s[1])
        elif t=='signal': E(s[1]); I(SIGNAL)
        elif t=='sigmask': E(s[1]); I(SIGMASK)
        elif t=='set': I(PUSH_LIT,s[1]); E(s[2]); I(SET)
        elif t in ('call','start'):
            for a in s[2]: E(a)
            I(CALL if t=='call' else START, s[1], len(s[2]))
        elif t=='if':
            c,then,els=s[1],s[2],s[3]
            E(c); lelse=object(); lend=object()
            out.append(('jf',lelse))
            self.emit_stmts(then,out,loops)
            if els is not None:
                out.append(('jmp',lend)); out.append(('label',lelse))
                self.emit_stmts(els,out,loops); out.append(('label',lend))
            else:
                out.append(('label',lelse))
        elif t=='while':
            h=object(); ex=object()
            out.append(('label',h)); E(s[1]); out.append(('jf',ex))
            loops.append((h,ex)); self.emit_stmts(s[2],out,loops); loops.pop()
            out.append(('jmp',h)); out.append(('label',ex))
        elif t=='break':
            if not loops: raise CompileError('break outside a loop')
            out.append(('jmp',loops[-1][1]))
        elif t=='continue':
            if not loops: raise CompileError('continue outside a loop')
            out.append(('jmp',loops[-1][0]))
        else: raise CompileError(f'no emitter for {t}')

def parse_declarations(toks):
    pieces=[]; statics=[]; funcs=[]
    depth=0
    i=0
    while toks[i][0]!='eof':
        k,v=toks[i]
        if v=='{': depth+=1
        elif v=='}': depth-=1
        elif depth==0 and k=='ident' and v.lower()=='piece':
            j=i+1
            while toks[j][1]!=';':
                if toks[j][0]=='ident': pieces.append(toks[j][1])
                j+=1
            i=j
        elif depth==0 and k=='ident' and v.lower()=='static-var':
            j=i+1
            while toks[j][1]!=';':
                if toks[j][0]=='ident': statics.append(toks[j][1])
                j+=1
            i=j
        elif depth==0 and k=='ident' and toks[i+1][1]=='(':
            funcs.append(v)
        i+=1
    return pieces, statics, funcs

def compile_bos(src):
    """Returns (names, pieces, statics_count, per-script instruction lists, flavor)."""
    m=re.search(r'//\s*compiler:\s*(\w+)', src)
    flavor=m.group(1).lower() if m else 'retail'
    toks=tokenize(src)
    pieces,statics,funcs=parse_declarations(toks)
    ctx=Ctx(pieces, funcs, statics)
    p=Parser(toks, ctx)
    names=[]; code=[]
    while p.peek()[0]!='eof':
        k,v=p.peek()
        if k=='ident' and v.lower() in ('piece','static-var'):
            while p.next()[1]!=';': pass
            continue
        name=p.ident(); names.append(name); p.expect('(')
        params=[]
        if not p.accept(')'):
            params.append(p.ident())
            while p.accept(','): params.append(p.ident())
            p.expect(')')
        p.expect('{')
        varnames=[]
        while p.peek()[0]=='ident' and p.peek()[1].lower()=='var':
            p.next(); varnames.append(p.ident())
            while p.accept(','): varnames.append(p.ident())
            p.expect(';')
        p.L={n.lower():i for i,n in enumerate(params+varnames)}
        stmts=[]
        while not p.accept('}'): stmts.append(p.stmt())
        out=[('ins',DECL_LOCAL,[]) for _ in p.L]
        p.emit_stmts(stmts,out,[])
        if flavor=='brain' or not stmts or stmts[-1][0]!='return':
            out.append(('ins',PUSH_LIT,[0])); out.append(('ins',RET,[]))
        code.append(out)
    return names, pieces, len(statics), code, flavor

def assemble(names, pieces, nstatics, code):
    words=[]; starts=[]
    for out in code:
        base=len(words); starts.append(base)
        labels={}; addr=0
        for it in out:
            if it[0]=='label': labels[id(it[1])]=addr
            elif it[0]=='ins': addr+=1+IMM[it[1]]
            else: addr+=2
        for it in out:
            if it[0]=='label': continue
            if it[0]=='ins':
                words.append(it[1])
                words.extend(x for x in it[2])
            else:
                words.append(JF if it[0]=='jf' else JMP)
                words.append(base+labels[id(it[1])])
    ns=len(names); npc=len(pieces); totw=len(words)
    codeidx_off=44+4*totw
    sname_off=codeidx_off+4*ns
    pname_off=sname_off+4*ns
    names_off=pname_off+4*npc
    blob=b''; sname_offs=[]; pname_offs=[]; cur=names_off
    for n in names:
        sname_offs.append(cur); b=n.encode('latin1')+b'\0'; blob+=b; cur+=len(b)
    for n in pieces:
        pname_offs.append(cur); b=n.encode('latin1')+b'\0'; blob+=b; cur+=len(b)
    hdr=struct.pack('<11I',4,ns,npc,totw,nstatics,0,codeidx_off,sname_off,pname_off,44,names_off)
    body=b''.join(struct.pack('<i',w) for w in words)
    body+=b''.join(struct.pack('<I',s) for s in starts)
    body+=b''.join(struct.pack('<I',o) for o in sname_offs)
    body+=b''.join(struct.pack('<I',o) for o in pname_offs)
    return hdr+body+blob

def compile_text(src):
    names,pieces,nstatics,code,flavor=compile_bos(src)
    return assemble(names,pieces,nstatics,code)
