"""Reader for Total Annihilation v4 COB files (word-stream layout)."""
import struct
AXES=['x-axis','y-axis','z-axis']
def read_cob(path):
    d=open(path,'rb').read()
    if len(d)<44: raise ValueError('corrupt COB: file shorter than the 44-byte header')
    h=struct.unpack_from('<11I',d,0)
    ver,ns,npc,totw,nstat=h[0],h[1],h[2],h[3],h[4]
    if ver!=4: raise ValueError(f'not a v4 COB (version field is {ver})')
    cbase=h[9]; nbase=h[10]; cidx=h[6]; sname=h[7]; pname=h[8]
    # Every table must lie inside the file; otherwise the COB is corrupt or from another version.
    for label,off,size in (('script index',cidx,4*ns),('script names',sname,4*ns),('piece names',pname,4*npc),
                           ('code',cbase,4*totw)):
        if off+size>len(d): raise ValueError(f'corrupt COB: {label} table runs past the end of the file')
    def nm(o):
        end=d.find(b'\0',o)
        if o>=len(d) or end<0: raise ValueError('corrupt COB: unterminated name string')
        return d[o:end].decode('latin1')
    names=[nm(struct.unpack_from('<I',d,sname+4*i)[0]) for i in range(ns)]
    pieces=[nm(struct.unpack_from('<I',d,pname+4*i)[0]) for i in range(npc)]
    starts=[struct.unpack_from('<I',d,cidx+4*i)[0] for i in range(ns)]
    ends=starts[1:]+[totw]
    words=[struct.unpack_from('<i',d,cbase+4*k)[0] for k in range(totw)]
    # Community-tool (COBBLER) builds write a 146-byte text signature into the code block, after a
    # script's final return, and the word stream runs on past it. The block still counts in the word
    # indices (script starts and jump targets), so it is recorded as a span to skip, not removed.
    blobs=[]
    key=b'Build by COBBLER'
    p=d.find(key,cbase)
    while p>=0:
        q=d.find(b'erhnam )',p)
        if q<0: break
        rel=(q+len(b'erhnam )'))-cbase
        rel=(rel+3)//4*4                 # round up to a word boundary
        blobs.append(((p-cbase)//4,(cbase+rel-cbase)//4))
        p=d.find(key,cbase+rel)
    scripts=[(names[i], words[starts[i]:ends[i]]) for i in range(ns)]
    return dict(names=names,pieces=pieces,nstatics=nstat,scripts=scripts,starts=starts,totw=totw,raw=d,blobs=blobs)
if __name__=='__main__':
    import sys
    c=read_cob(sys.argv[1])
    print(c['names'],c['pieces'],c['nstatics'],c['totw'])
    print([len(w) for _,w in c['scripts']])
