# ---- bostool CLI ----
import sys as _sys, argparse as _argparse
def _cmd_decompile(a):
    set_linear_scale(a.linear_scale)
    text=decompile(a.cob, a.label_functions)
    if a.o: open(a.o,'w',encoding='utf-8').write(text); print('wrote',a.o)
    else: print(text)
def _cmd_compile(a):
    set_linear_scale(a.linear_scale)
    out=compile_text(preprocess_file(a.bos, a.I or []))
    open(a.o,'wb').write(out); print('wrote',a.o,len(out),'bytes')
def _cmd_check(a):
    ok=True
    for f in a.cob:
        try:
            src=decompile(f); out=compile_text(src)
        except Exception as e:
            print(f'{f}: FAILED ({type(e).__name__}: {e})'); ok=False; continue
        ref=open(f,'rb').read()
        if out==ref: print(f'{f}: identical ({len(ref)} bytes)')
        else:
            ok=False
            a1=read_cob_bytes(out); b1=read_cob_bytes(ref)
            bad=[n for (n,x),(_,y) in zip(a1,b1) if x!=y]
            print(f'{f}: DIFFERS (lengths {len(out)} vs {len(ref)}; scripts differing: {bad or "none"})')
    return 0 if ok else 1
def read_cob_bytes(data):
    import tempfile,os
    fd,p=tempfile.mkstemp(suffix='.cob'); os.write(fd,data); os.close(fd)
    try: c=read_cob(p); return c['scripts']
    finally: os.remove(p)
_SUBCOMMANDS=('decompile','compile','check')
def main(argv=None):
    # No arguments (or a file to open) starts the editor: that is the program. The subcommands are for scripting.
    argv=list(_sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0] not in _SUBCOMMANDS and not argv[0].startswith('-')):
        run_gui(argv[0] if argv else None)
        return 0
    p=_argparse.ArgumentParser(prog='amf',description='Advanced Model Factory: BOS/COB command-line tools. Run with no arguments to open the editor.')
    sub=p.add_subparsers(dest='cmd',required=True)
    d=sub.add_parser('decompile',help='COB -> BOS source'); d.add_argument('cob'); d.add_argument('-o')
    d.add_argument('--label-functions',action='store_true',help='name statics used by one function <Func>FunctionVar'); d.add_argument('--linear-scale',type=int,choices=LINEAR_SCALES,default=65536,help='65536 (default) or 163840'); d.set_defaults(fn=_cmd_decompile)
    c=sub.add_parser('compile',help='BOS source -> COB'); c.add_argument('bos'); c.add_argument('-o',required=True); c.add_argument('-I',action='append'); c.add_argument('--linear-scale',type=int,choices=LINEAR_SCALES,default=65536,help='65536 (default) or 163840'); c.set_defaults(fn=_cmd_compile)
    k=sub.add_parser('check',help='decompile then recompile COB files and compare bytes'); k.add_argument('cob',nargs='+'); k.set_defaults(fn=_cmd_check)
    a=p.parse_args(argv)
    r=a.fn(a)
    return r if isinstance(r,int) else 0
if __name__=='__main__':
    _sys.exit(main())
