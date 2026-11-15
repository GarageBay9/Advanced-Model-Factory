# ---- HPI archive reader (Total Annihilation .hpi/.ufo/.ccx/.gp3; read-only) ----
# Layout and cipher per the repo's research/formats/hpi.md (header, directory tree, SQSH chunks, LZ77/zlib).
# Only the reader is here; nothing is written back to archives.
import zlib as _zlib

class HPIError(Exception): pass

HPI_CHUNK=65536
_HPI_COPYRIGHT_TEMPLATE=b'Copyright 0000 Cavedog Entertainment'

def _hpi_key(k):
    """Working key for the archive cipher, from the stored header key's low byte (0 = cipher disabled)."""
    if k==0: return 0
    return (~(((k>>6)|(k<<2))&0xff))&0xff

def _lz77(data,declared):
    """Retail LZSS variant: 4096-byte window starting at cursor 1, matches of 2-17 bytes, position 0 terminates."""
    window=bytearray(4096); cur=1
    out=bytearray(); i=0; n=len(data)
    tag=0; bit=0
    while True:
        if bit==0:
            if i>=n: raise HPIError('LZ77 stream ends before its terminator')
            tag=data[i]; i+=1
        if ((tag>>bit)&1)==0:
            if i>=n: raise HPIError('LZ77 literal past end of input')
            b=data[i]; i+=1
            out.append(b); window[cur]=b; cur=(cur+1)&0xfff
        else:
            if i+2>n: raise HPIError('LZ77 match past end of input')
            v=data[i]|(data[i+1]<<8); i+=2
            pos=v>>4
            if pos==0: break                      # terminator
            length=(v&0xf)+2
            if len(out)+length>declared: raise HPIError('LZ77 output exceeds the declared size')
            for _ in range(length):
                b=window[pos]; out.append(b); window[cur]=b
                pos=(pos+1)&0xfff; cur=(cur+1)&0xfff
        bit=(bit+1)&7
    return bytes(out)

def _zlib_chunk(data,declared):
    """Inflate a zlib payload. Some packers drop the final block and Adler-32 once all bytes are out (accepted)."""
    d=_zlib.decompressobj()
    try:
        out=d.decompress(data)
    except _zlib.error as e:
        raise HPIError(f'zlib chunk does not inflate: {e}')
    if len(out)!=declared:
        raise HPIError(f'zlib chunk produced {len(out)} bytes, expected {declared}')
    return out

class HPIArchive:
    def __init__(self,path):
        with open(path,'rb') as f: self._d=f.read()
        self.path=path
        d=self._d
        if len(d)<20 or d[0:4]!=b'HAPI' or d[4:8]!=b'\x00\x00\x01\x00':
            raise HPIError(f'{path}: not an HPI archive (bad header)')
        if len(d)<36 or not self._copyright_ok(d[-36:]):
            raise HPIError(f'{path}: missing the Cavedog copyright trailer')
        self._dir_end=int.from_bytes(d[8:12],'little')
        self._key=_hpi_key(d[12])
        self._dir_start=int.from_bytes(d[16:20],'little')
        self.entries={}                      # lower-case path -> (display path, data offset, size, comp)
        self._walk(self._dir_start,'',0,set())

    @staticmethod
    def _copyright_ok(tail):
        # the year is a wildcard: any four bytes at the year position pass
        t=bytearray(tail)
        if len(t)!=36 or t[:10]!=b'Copyright ' : return False
        if t[14:]!=_HPI_COPYRIGHT_TEMPLATE[14:]: return False
        return True

    # ---- cipher ----
    def _dec(self,pos,n):
        """Decrypt n archive bytes starting at absolute position pos (position-dependent XOR cipher)."""
        raw=self._d[pos:pos+n]
        if len(raw)!=n: raise HPIError(f'{self.path}: read at {pos} runs past end of file')
        k=self._key
        if k==0: return bytes(raw)
        return bytes(((pos+i)&0xff ^ k ^ (~c & 0xff)) & 0xff for i,c in enumerate(raw))

    def _u32(self,pos):
        return int.from_bytes(self._dec(pos,4),'little')

    def _cstr(self,pos):
        out=bytearray(); p=pos
        while True:
            b=self._dec(p,1)[0]
            if b==0: break
            out.append(b); p+=1
            if len(out)>512: raise HPIError('name too long')
        return out.decode('latin1')

    # ---- directory ----
    def _walk(self,node,prefix,depth,seen):
        if depth>32 or node in seen: raise HPIError(f'{self.path}: directory loop or nesting too deep')
        seen.add(node)
        count=self._u32(node); eoff=self._u32(node+4)
        if count>65536: raise HPIError('directory entry count implausible')
        for i in range(count):
            e=eoff+9*i
            name=self._cstr(self._u32(e))
            data=self._u32(e+4)
            flag=self._dec(e+8,1)[0]
            full=(prefix+'\\'+name) if prefix else name
            if flag&1:
                self._walk(data,full,depth+1,seen)
            else:
                size=self._u32(data+4); comp=self._dec(data+8,1)[0]
                self.entries[full.lower().replace('/','\\')]=(full,self._u32(data),size,comp)
        seen.discard(node)

    def names(self):
        return sorted(v[0] for v in self.entries.values())

    def read(self,name):
        """Return the decompressed bytes of an archive file. Name is case-insensitive; '/' or '\\' separators."""
        key=name.lower().replace('/','\\').lstrip('\\')
        if key not in self.entries: raise HPIError(f'{self.path}: no entry {name!r}')
        full,off,size,comp=self.entries[key]
        if comp==0:
            return self._dec(off,size)
        if comp not in (1,2): raise HPIError(f'{full}: unknown compression {comp}')
        chunks=(size+HPI_CHUNK-1)//HPI_CHUNK if size else 0
        table=[self._u32(off+4*i) for i in range(chunks)]
        pos=off+4*chunks
        out=bytearray()
        for i,stored in enumerate(table):
            want=min(HPI_CHUNK,size-HPI_CHUNK*i)
            blob=self._dec(pos,stored); pos+=stored
            out+=self._unpack_chunk(blob,full,want)
        if len(out)!=size: raise HPIError(f'{full}: decompressed to {len(out)} bytes, expected {size}')
        return bytes(out)

    def _unpack_chunk(self,blob,full,want):
        if len(blob)<19 or blob[0:4]!=b'SQSH': raise HPIError(f'{full}: chunk header missing SQSH marker')
        method=blob[5]; encoded=blob[6]
        csize=int.from_bytes(blob[7:11],'little'); dsize=int.from_bytes(blob[11:15],'little')
        checksum=int.from_bytes(blob[15:19],'little')
        payload=bytearray(blob[19:19+csize])
        if len(payload)!=csize: raise HPIError(f'{full}: chunk payload truncated')
        if sum(payload)&0xffffffff!=checksum: raise HPIError(f'{full}: chunk checksum mismatch')
        if dsize!=want: raise HPIError(f'{full}: chunk declares {dsize} bytes, expected {want}')
        if encoded:
            payload=bytearray(((payload[x]-x)^x)&0xff for x in range(len(payload)))
        if method==1: return _lz77(bytes(payload),dsize)
        if method==2: return _zlib_chunk(bytes(payload),dsize)
        raise HPIError(f'{full}: unsupported chunk method {method}')
