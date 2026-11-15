"""BOS preprocessor: #include (case-insensitive lookup, both quote styles), object #define/#undef,
#ifdef/#ifndef/#if/#elif/#else/#endif with proper nesting. Directive names are case-insensitive."""
import os, re

class PPError(Exception): pass

IDENT=re.compile(r'[A-Za-z_][A-Za-z0-9_]*(?:-[A-Za-z_][A-Za-z0-9_]*)*')

class Preprocessor:
    def __init__(self, incdirs=(), defines=None):
        self.incdirs=list(incdirs)
        self.defs=dict(defines or {})
        self.out=[]
        self.origin=[]   # parallel to out: (file, line) each output line came from
        self.stack=[]     # each: {'parent':bool,'taken':bool,'active':bool}
        self.depth=0

    def active(self):
        return not self.stack or self.stack[-1]['active']

    def find(self, name, cur_dir):
        # Windows-style and *nix-style separators are equivalent: '\\' is read as '/'.
        want=name.replace('\\','/')
        for d in [cur_dir]+self.incdirs:
            p=os.path.join(d,want)
            if os.path.isfile(p): return p
            # case-insensitive fallback: match each path component against the directory listing.
            # '.' and '..' are followed as real directories, not looked up by name.
            cur=d; ok=True
            for part in want.split('/'):
                if part in ('','.'): continue
                if part=='..':
                    cur=os.path.dirname(cur); continue
                if not os.path.isdir(cur): ok=False; break
                hits=[e for e in os.listdir(cur) if e.lower()==part.lower()]
                if not hits: ok=False; break
                cur=os.path.join(cur,hits[0])
            if ok and os.path.isfile(cur): return cur
        raise PPError(f'include not found: {name} (searched from {cur_dir} and the include folders)')

    def expand(self, text):
        code, sep, comment = text.partition('//')
        for _ in range(20):
            new=IDENT.sub(lambda m: self.defs.get(m.group(0), m.group(0)), code)
            if new==code: break
            code=new
        return code+sep+comment

    def eval_if(self, expr):
        e=re.sub(r'defined\s*\(\s*(\w+)\s*\)', lambda m: '1' if m.group(1) in self.defs else '0', expr)
        e=re.sub(r'defined\s+(\w+)', lambda m: '1' if m.group(1) in self.defs else '0', e)
        for _ in range(20):
            new=IDENT.sub(lambda m: self.defs.get(m.group(0), '0'), e)
            if new==e: break
            e=new
        e=e.replace('&&',' and ').replace('||',' or ')
        e=re.sub(r'!(?!=)', ' not ', e)
        try:
            return bool(eval(e, {'__builtins__':{}}, {}))
        except Exception as ex:
            raise PPError(f'bad #if expression {expr!r}: {ex}')

    def process(self, path):
        self.depth+=1
        if self.depth>32: raise PPError('include nesting too deep')
        cur_dir=os.path.dirname(os.path.abspath(path))
        text=open(path,'rb').read().decode('latin1')
        absp=os.path.abspath(path)
        for lineno,ln in enumerate(text.replace('\r\n','\n').replace('\r','\n').split('\n'),1):
            s=ln.strip()
            if s.startswith('#'):
                m=re.match(r'#\s*(\w+)\s*(.*)$', s)
                d=m.group(1).lower(); rest=m.group(2).strip()
                if d in ('if','ifdef','ifndef'):
                    parent=self.active()
                    if d=='if': val=parent and self.eval_if(rest)
                    elif d=='ifdef': val=parent and rest.split()[0] in self.defs
                    else: val=parent and rest.split()[0] not in self.defs
                    self.stack.append({'parent':parent,'taken':val,'active':val})
                elif d=='elif':
                    top=self.stack[-1]
                    val=top['parent'] and not top['taken'] and self.eval_if(rest)
                    top['active']=val; top['taken']=top['taken'] or val
                elif d=='else':
                    top=self.stack[-1]
                    top['active']=top['parent'] and not top['taken']; top['taken']=True
                elif d=='endif':
                    if not self.stack: raise PPError('#endif without #if')
                    self.stack.pop()
                elif not self.active():
                    pass
                elif d=='define':
                    parts=rest.split(None,1)
                    if not parts: raise PPError('#define without a name')
                    if '(' in parts[0]: raise PPError(f'function-like macros are not supported: {parts[0]}')
                    value=parts[1] if len(parts)>1 else ''
                    value=re.sub(r'/\*.*?\*/', ' ', value).split('//')[0]
                    self.defs[parts[0]]=value.strip()
                elif d=='undef':
                    self.defs.pop(rest.split()[0],None)
                elif d=='include':
                    inc=re.match(r'["<](.+?)[">]', rest)
                    if not inc: raise PPError(f'bad #include: {rest}')
                    self.emit('', absp, lineno)
                    self.process(self.find(inc.group(1), cur_dir))
                    self.depth-=0
                    self.emit('', absp, lineno)
                    continue
                else:
                    raise PPError(f'unknown directive #{d}')
                self.emit('', absp, lineno)
            else:
                self.emit(self.expand(ln) if self.active() else '', absp, lineno)
        self.depth-=1

    def emit(self, text, path, lineno):
        self.out.append(text); self.origin.append((path, lineno))

def preprocess_with_map(path, incdirs=()):
    """Returns (expanded text, origin) where origin[i] = (file, line) for expanded line i+1."""
    pp=Preprocessor(incdirs)
    pp.process(path)
    if pp.stack: raise PPError('unterminated #if')
    return '\n'.join(pp.out), list(pp.origin)

def preprocess_file(path, incdirs=()):
    return preprocess_with_map(path, incdirs)[0]
