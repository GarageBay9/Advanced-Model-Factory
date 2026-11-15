# ---- GAF reader (read-only; texture entries for the 3DO viewport) ----
# Byte layout per research/formats/gaf.md: 12-byte header, u32 entry offsets, 40-byte entries with 8-byte
# frame references, 24-byte frame headers, raw or per-row RLE pixels, and composed frames whose children
# are placed at (parent.x_offset - child.x_offset, parent.y_offset - child.y_offset) on the parent canvas.
import struct as _gst

class GafError(Exception): pass

_GAF_MAX_DEPTH=4
_GAF_MAX_PIXELS=4096*4096

def _need(d,p,n):
    if p<0 or p+n>len(d): raise GafError(f'read of {n} bytes at {p} runs past the end of the file')

def _u16(d,p): _need(d,p,2); return _gst.unpack_from('<H',d,p)[0]
def _u32(d,p): _need(d,p,4); return _gst.unpack_from('<I',d,p)[0]

def _rle_row(d,start,count,width):
    """One RLE row: the payload count bounds the row's extent, but commands decode until width is covered (gaf.md)."""
    _need(d,start,count)
    row=[None]*width
    x=0; p=start
    while x<width:
        _need(d,p,1)
        c=d[p]; p+=1
        if c&1:                                  # skip: transparent pixels (None)
            x+=min(c>>1,width-x)
        elif c&2:                                # repeat one palette byte
            _need(d,p,1); v=d[p]; p+=1
            n=min((c>>2)+1,width-x)
            row[x:x+n]=[v]*n; x+=n
        else:                                    # literal run; the discarded suffix is not read
            m=min((c>>2)+1,width-x)
            _need(d,p,m)
            row[x:x+m]=list(d[p:p+m]); p+=m; x+=m
    return row

class GafFrame:
    def __init__(self,width,height,x_offset,y_offset,rows):
        self.width=width; self.height=height; self.x_offset=x_offset; self.y_offset=y_offset
        self.rows=rows                           # height lists of width entries; None = transparent

def _gaf_frame(d,hdr,depth=0):
    if depth>_GAF_MAX_DEPTH: raise GafError('composed frames nest too deeply')
    _need(d,hdr,24)
    w,h,xo,yo=_gst.unpack_from('<HHhh',d,hdr)
    comp=d[hdr+9]; nsub=d[hdr+10]                # the executable reads only the low byte of the subframe count
    data=_u32(d,hdr+16)
    if w*h>_GAF_MAX_PIXELS: raise GafError('frame is larger than the reader allows')
    if nsub:
        rows=[[None]*w for _ in range(h)]
        for i in range(nsub):
            child=_gaf_frame(d,_u32(d,data+4*i),depth+1)
            ox=xo-child.x_offset; oy=yo-child.y_offset
            for r,crow in enumerate(child.rows):
                ty=oy+r
                if not 0<=ty<h: continue
                trow=rows[ty]
                for c,v in enumerate(crow):
                    tx=ox+c
                    if v is not None and 0<=tx<w: trow[tx]=v
        return GafFrame(w,h,xo,yo,rows)
    if w==0 or h==0: return GafFrame(w,h,xo,yo,[])
    rows=[]
    if comp==0:
        _need(d,data,w*h)
        for r in range(h): rows.append(list(d[data+r*w:data+(r+1)*w]))   # raw texels; model textures are opaque (03 §5.2), so the key is not applied here
    elif comp==1:
        p=data
        for r in range(h):
            count=_u16(d,p)
            rows.append(_rle_row(d,p+2,count,w))
            p=p+2+count                          # next row starts after the stored payload, whatever was decoded
    else:
        raise GafError(f'unknown frame compression {comp}')
    return GafFrame(w,h,xo,yo,rows)

class GafFile:
    """A parsed GAF. entries: lower-case name -> (display name, entry offset, frame count)."""
    def __init__(self,data,label='gaf'):
        self._d=data; self.label=label
        if len(data)<12: raise GafError(f'{label}: too short to be a GAF')
        count=_u32(data,4)&0xFFFF                # the executable reads the low 16 bits as signed; a count with bit 15 set loads nothing
        if count&0x8000: count=0
        self.entries={}
        for i in range(count):
            off=_u32(data,12+4*i)
            _need(data,off,40)
            nframes=_u16(data,off)
            name=data[off+8:off+40].split(b'\0',1)[0].decode('latin1')
            self.entries.setdefault(name.lower(),(name,off,nframes))
    def names(self):
        return sorted(v[0] for v in self.entries.values())
    def frame0(self,name):
        """First frame of a named entry, decoded. Multi-frame and animated entries use frame 0 for texturing."""
        key=name.lower()
        if key not in self.entries: raise GafError(f'{self.label}: no entry {name!r}')
        _,off,nframes=self.entries[key]
        if nframes==0: raise GafError(f'{self.label}: entry {name!r} has no frames')
        ref=_u32(self._d,off+40)
        return _gaf_frame(self._d,ref)

class TextureLibrary:
    """Texture GAFs from folders (any .gaf found under them) and from HPI archives (textures\\*.GAF).
    The first source that holds a name wins. Problems opening a source are kept in .problems, not raised."""
    def __init__(self,sources):
        self._gafs={}                            # lower name -> GafFile
        self._cache={}                           # lower name -> (w, h, rows) or None
        self.problems=[]
        self._files=[]                           # every GafFile loaded, in source order (the texture archives)
        for src in sources or []:
            try:
                self._add_source(src)
            except Exception as e:
                self.problems.append(f'{src}: {e}')

    def _add_gaf(self,data,label):
        g=GafFile(data,label=label)
        self._files.append(g)
        for key in g.entries: self._gafs.setdefault(key,g)

    def _add_source(self,src):
        import os as _o
        if _o.path.isdir(src):
            for root,_,files in _o.walk(src):
                for f in sorted(files):
                    if f.lower().endswith('.gaf'):
                        p=_o.path.join(root,f)
                        with open(p,'rb') as fh: self._add_gaf(fh.read(),p)
        elif src.lower().endswith('.hpi') or src.lower().endswith('.ufo') or src.lower().endswith('.ccx'):
            arc=HPIArchive(src)
            for n in arc.names():
                low=n.lower().replace('/','\\')
                if low.startswith('textures\\') and low.endswith('.gaf'):
                    self._add_gaf(arc.read(n),f'{src}:{n}')
        else:
            raise GafError('not a folder or an archive')

    def files(self):
        """Every loaded texture archive (GAF), in source order. Each has .label, .names() and .entries (frame counts)."""
        return list(self._files)

    def has(self,name):
        return bool(name) and name.lower() in self._gafs

    def names(self):
        """Display names of every texture the sources hold, sorted case-insensitively."""
        return sorted({g.entries[k][0] for k,g in self._gafs.items()},key=str.lower)

    def texture(self,name):
        """(width, height, rows) of a texture's first frame, or None if no source holds it or it fails to decode."""
        key=(name or '').lower()
        if key in self._cache: return self._cache[key]
        val=None
        g=self._gafs.get(key)
        if g is not None:
            try:
                f=g.frame0(name)
                val=(f.width,f.height,f.rows)
            except GafError as e:
                self.problems.append(f'{name}: {e}')
        self._cache[key]=val
        return val
