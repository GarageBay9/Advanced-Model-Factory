# ---- GUI (tkinter) ----
try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, simpledialog
    from tkinter import font as tkfont
except ImportError:   # the CLI still works without tkinter
    tk=ttk=filedialog=messagebox=simpledialog=tkfont=None

UI_SIZE_DEFAULT=14
_CODE_FONT=None
UI_SIZE_MIN,UI_SIZE_MAX=8,28
def apply_ui_size(n):
    """Set the size of every named Tk UI font (menus, default widgets) and the shared code font."""
    n=max(UI_SIZE_MIN,min(UI_SIZE_MAX,int(n)))
    for nm in ('TkDefaultFont','TkTextFont','TkMenuFont','TkHeadingFont','TkFixedFont','TkCaptionFont','TkSmallCaptionFont','TkIconFont','TkTooltipFont'):
        try: tkfont.nametofont(nm).configure(size=n)
        except Exception: pass
    global _CODE_FONT
    try: tkfont.nametofont('BostoolCode').configure(size=n)
    except Exception: _CODE_FONT=tkfont.Font(name='BostoolCode',family='Courier',size=n)  # keep a reference: Tk deletes the named font when this object is collected
    return n
import json, tempfile, re as _re, os as _os, time as _time

CONFIG_PATH=_os.path.join(_os.path.expanduser('~'),'.amf_config.json')
_OLD_CONFIG_PATH=_os.path.join(_os.path.expanduser('~'),'.bostool_config.json')   # settings from the old name are carried over once
if not _os.path.exists(CONFIG_PATH) and _os.path.exists(_OLD_CONFIG_PATH):
    try:
        import shutil as _shutil; _shutil.copy(_OLD_CONFIG_PATH,CONFIG_PATH)
    except OSError: pass
MAX_RECENT=10
BOS_KEYWORDS=set('''piece static-var var if else while return call-script start-script signal set-signal-mask
sleep move turn spin stop-spin show hide cache dont-cache dont-shade dont-shadow emit-sfx explode set get rand
wait-for-turn wait-for-move attach-unit drop-unit from to speed accelerate decelerate around along type now
NOT AND OR TRUE FALSE'''.split())
BOS_KEYWORDS_LOWER={k.lower() for k in BOS_KEYWORDS}
_TOK=_re.compile(r'(//[^\n]*)|(#\s*\w+)|([A-Za-z_][A-Za-z0-9_\-]*)|(\d+(?:\.\d+)?)')
_OPNAMES={v:k for k,v in list(globals().items()) if isinstance(v,int) and k.isupper() and (v & 0xF0000000)==0x10000000}

class Config:
    """Settings persisted in ~/.bostool_config.json: recent files, per-source output and include folders, global options."""
    def __init__(self):
        self.data={'recent':[],'global_incdirs':[],'case_check':True,'label_functions':False,'linear_scale':65536,'sources':{}}
        try:
            with open(CONFIG_PATH) as f: self.data.update(json.load(f))
        except Exception: pass
    def save(self):
        try:
            with open(CONFIG_PATH,'w') as f: json.dump(self.data,f,indent=1)
        except Exception: pass
    def source(self,path):
        return self.data['sources'].setdefault(path,{'out_dir':None,'out_name':None,'incdirs':[]})
    def add_recent(self,p):
        self.data['recent']=([p]+[x for x in self.data['recent'] if x!=p])[:MAX_RECENT]; self.save()

DECOMPILE_TIMEOUT=60   # seconds before a decompile is abandoned

def _decompile_worker(path,label,conn):
    try:
        conn.send(('ok',decompile(path,label)))
    except BaseException as e:          # reported back, never raised into the IDE
        conn.send(('err',f'{type(e).__name__}: {e}'))
    finally:
        conn.close()

def run_decompile(data,label):
    """Decompile COB bytes. Returns (text, error). A crash or hang is reported as an error; the IDE keeps running.
    On platforms without fork the decompile runs in-process and only Python exceptions are caught."""
    tmp=tempfile.NamedTemporaryFile(suffix='.cob',delete=False); tmp.write(data); tmp.close()
    try:
        import multiprocessing as _mp
        if 'fork' not in _mp.get_all_start_methods():
            try: return decompile(tmp.name,label), None
            except Exception as e: return None, f'{type(e).__name__}: {e}'
        ctx=_mp.get_context('fork')
        rx,tx=ctx.Pipe(duplex=False)
        p=ctx.Process(target=_decompile_worker,args=(tmp.name,label,tx)); p.start(); tx.close()
        try:
            if not rx.poll(DECOMPILE_TIMEOUT):
                p.terminate(); p.join()
                return None, f'the decompiler did not finish within {DECOMPILE_TIMEOUT} seconds and was stopped'
            kind,payload=rx.recv()
        except EOFError:
            p.join()
            return None, f'the decompiler stopped unexpectedly (exit code {p.exitcode})'
        p.join()
        return (payload,None) if kind=='ok' else (None,payload)
    finally:
        _os.remove(tmp.name)

def _png(w,h,rgb):
    """Minimal PNG encoder (8-bit RGB, no filtering) for Tk's PhotoImage."""
    import zlib, struct
    def chunk(tag,data):
        return struct.pack('>I',len(data))+tag+data+struct.pack('>I',zlib.crc32(tag+data)&0xffffffff)
    raw=b''.join(b'\x00'+bytes(rgb[y*w*3:(y+1)*w*3]) for y in range(h))
    return (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,8,2,0,0,0))
            +chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b''))

def _texture_photo(rows,w,h,palette,maxside=160):
    """Texture as a Tk image, scaled by a whole factor. Transparent texels show as a grey check."""
    import base64
    buf=bytearray()
    for y,row in enumerate(rows):
        for x,v in enumerate(row):
            if palette is None:
                buf+=bytes((0x80,0x80,0x80))           # no palette: neutral grey, not transparency
            elif v is None:
                g=0x9a if ((x//4)+(y//4))%2==0 else 0x6a   # transparent texel: check
                buf+=bytes((g,g,g))
            else:
                buf+=bytes(palette[v])
    img=tk.PhotoImage(data=base64.b64encode(_png(w,h,bytes(buf))).decode('ascii'),format='png')
    k=max(1,maxside//max(w,h))
    return img.zoom(k) if k>1 else img

THUMB_ROW=58

def _thumb_photo(rows,w,h,palette,side=44):
    """A texture as a small Tk image: scaled down by a whole factor when large, up when small."""
    img=_texture_photo(rows,w,h,palette,maxside=1)
    big=max(w,h,1)
    if big>side: return img.subsample(-(-big//side))
    k=max(1,side//big)
    return img.zoom(k) if k>1 else img

class TexturePanel(ttk.Frame):
    """Docked texture palette beside the 3D view. Pick an archive (marked ● where the model uses it), then a texture
    (rows marked ● are used on the model). B, or the button, applies the selected texture to the selected face."""
    def __init__(self,parent,viewer):
        super().__init__(parent,width=280)
        from tkinter import font as _tkfont
        self.viewer=viewer; self._lib=None; self._files=[]; self._labels=[]; self._idx=0
        self._rows=[]; self._thumbs={}; self._used=set(); self._photo_pal=None; self._queued=False; self._region=None
        base=_tkfont.nametofont('TkDefaultFont')
        self._bold=_tkfont.Font(family=base.actual('family'),size=base.actual('size'),weight='bold')
        top=ttk.Frame(self); top.pack(fill='x',padx=6,pady=(6,2))
        ttk.Label(top,text='Texture archive').pack(anchor='w')
        self.arch=ttk.Combobox(top,state='readonly'); self.arch.pack(fill='x')
        self.arch.bind('<<ComboboxSelected>>',lambda e: self._pick_archive())
        ttk.Label(top,text='● = used on this model',foreground='#666').pack(anchor='w')
        mid=ttk.Frame(self); mid.pack(fill='both',expand=True,padx=6,pady=4)
        self.canvas=theme_track(tk.Canvas(mid,width=262,background='white',highlightthickness=0),'field')
        sb=ttk.Scrollbar(mid,orient='vertical',command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=lambda a,b: (sb.set(a,b),self._queue()))
        sb.pack(side='right',fill='y'); self.canvas.pack(side='left',fill='both',expand=True)
        self.canvas.bind('<Button-1>',self._click)
        self.canvas.bind('<Configure>',lambda e: self._queue())
        self.canvas.bind('<MouseWheel>',lambda e: self.canvas.yview_scroll(-1 if e.delta>0 else 1,'units'))
        self.canvas.bind('<Button-4>',lambda e: self.canvas.yview_scroll(-1,'units'))
        self.canvas.bind('<Button-5>',lambda e: self.canvas.yview_scroll(1,'units'))
        self.info=ttk.Label(self,text='',anchor='w',wraplength=250,justify='left'); self.info.pack(fill='x',padx=6)
        ttk.Button(self,text='Apply to selected face (B)',command=self._apply).pack(fill='x',padx=6,pady=4)
        self.status=ttk.Label(self,text='',anchor='w',wraplength=250,justify='left'); self.status.pack(fill='x',padx=6,pady=(0,6))
        viewer.add_listener(self.refresh)
        self.refresh()

    @staticmethod
    def _short(label):
        return label.replace('\\','/').split('/')[-1].split(':')[-1] or label

    def refresh(self):
        """Follows the library (rebuilt when sources change) and the model's textures (in-use marks)."""
        lib=self.viewer._library()
        if lib is not self._lib:
            self._lib=lib; self._files=lib.files(); self._thumbs={}
            if self._idx>=len(self._files): self._idx=0
        self._used=self.viewer.used_textures()
        marks=[]
        for f in self._files:
            used=any(k in self._used for k in f.entries)
            marks.append(('● ' if used else '   ')+self._short(f.label))
        self.arch['values']=marks
        if marks: self.arch.current(self._idx)
        else: self.arch.set('')
        self._rows=self._rows_for(self._idx) if self._files else []
        self._draw(); self._show_info()

    def _rows_for(self,idx):
        if not self._files: return []
        f=self._files[idx]
        return sorted(((k,v[0],v[2]) for k,v in f.entries.items()),key=lambda r: r[1].lower())

    def _pick_archive(self):
        i=self.arch.current()
        if i<0: return
        self._idx=i; self._rows=self._rows_for(i)
        self.canvas.yview_moveto(0); self._draw(); self._show_info()

    def _thumb(self,idx,key,name):
        pal=self.viewer._palette()
        ck=(idx,key,id(pal))
        if ck not in self._thumbs:
            try:
                fr=self._files[idx].frame0(name)
                self._thumbs[ck]=_thumb_photo(fr.rows,fr.width,fr.height,pal)
            except Exception:
                self._thumbs[ck]=None
        return self._thumbs[ck]

    def _queue(self):
        """Redraws once, after the pending events; scroll and configure callbacks arrive in bursts."""
        if not self._queued:
            self._queued=True; self.after_idle(self._run_queued)

    def _run_queued(self):
        self._queued=False; self._draw()

    def _draw(self):
        c=self.canvas; c.delete('all')
        W=max(c.winfo_width(),200); H=max(c.winfo_height(),1)
        total=max(1,len(self._rows))*THUMB_ROW
        region=(0,0,W,total)
        if region!=self._region:                       # only when it changes: setting it fires the scroll callback
            self._region=region; c.configure(scrollregion=region)
        top=c.canvasy(0); first=max(0,int(top//THUMB_ROW)); last=min(len(self._rows),int((top+H)//THUMB_ROW)+1)
        sel=(self.viewer.tex_selected or '').lower()
        for i in range(first,last):
            key,name,nframes=self._rows[i]
            y=i*THUMB_ROW; used=key in self._used
            if key==sel: c.create_rectangle(1,y+1,W-2,y+THUMB_ROW-1,fill='#dbeafe',outline='#2b6cb0',width=2)
            elif used: c.create_rectangle(1,y+1,W-2,y+THUMB_ROW-1,fill='#fff4cc',outline='')
            ph=self._thumb(self._idx,key,name)
            if ph is not None: c.create_image(6,y+7,image=ph,anchor='nw')
            else: c.create_rectangle(6,y+7,50,y+51,outline='#999')
            c.create_text(58,y+8,text=('● ' if used else '')+name,anchor='nw',font=self._bold)
            try:
                fr=self._files[self._idx].frame0(name); size=f'{fr.width} x {fr.height}'
            except Exception: size='?'
            frames=f'{nframes} frame{"s" if nframes!=1 else ""}'+(' (animated)' if nframes>1 else '')
            c.create_text(58,y+26,text=f'{size}   {frames}',anchor='nw',fill='#333')
        if not self._rows:
            c.create_text(12,12,text='No textures. Add a folder or archive under Textures > Texture libraries.',anchor='nw',width=W-24,fill='#666')

    def _click(self,e):
        i=int(self.canvas.canvasy(e.y)//THUMB_ROW)
        if 0<=i<len(self._rows):
            self.viewer.tex_selected=self._rows[i][1]
            self._draw(); self._show_info()

    def _show_info(self):
        name=self.viewer.tex_selected
        if not name:
            self.info.configure(text='No texture selected.'); self.status.configure(text=''); return
        lib=self._lib; t=lib.texture(name) if lib is not None else None
        nf=None
        for f in self._files:
            e=f.entries.get(name.lower())
            if e: nf=e[2]; break
        dims=f'{t[0]} x {t[1]}' if t else 'unreadable'
        frames=f'{nf} frame{"s" if nf!=1 else ""}'+(' (animated)' if nf and nf>1 else '') if nf else ''
        self.info.configure(text=f'{name}\n{dims}   {frames}')
        pal=self.viewer._palette()
        self.status.configure(text='' if pal else 'No palette: '+(self.viewer.palette_problem() or 'set TApalette.dat under Textures'))

    def _apply(self):
        if not self.viewer.tex_selected:
            self.status.configure(text='Pick a texture first.'); return
        if self.viewer.assign_selected_texture():
            self.status.configure(text=f'Applied {self.viewer.tex_selected} to the selected face.')
        else:
            self.status.configure(text='Select a quad face in the 3D view first.')
        self._draw(); self._show_info()

class TextureBrowser:
    """Browse every texture the library holds, preview one, and assign it to the selected face."""
    def __init__(self,parent,viewer):
        self.viewer=viewer; self.photo=None
        self.top=tk.Toplevel(parent); self.top.title('Texture browser'); self.top.geometry('620x440')
        left=ttk.Frame(self.top); left.pack(side='left',fill='both',expand=True,padx=6,pady=6)
        self.filter_var=tk.StringVar()
        ttk.Entry(left,textvariable=self.filter_var).pack(fill='x')
        sb=ttk.Scrollbar(left); sb.pack(side='right',fill='y')
        self.lb=tk.Listbox(left,font='BostoolCode',yscrollcommand=sb.set,exportselection=False)
        self.lb.pack(side='left',fill='both',expand=True); sb.config(command=self.lb.yview)
        right=ttk.Frame(self.top); right.pack(side='right',fill='both',padx=6,pady=6)
        self.preview=ttk.Label(right,text='(select a texture)',anchor='center',width=24); self.preview.pack(fill='x')
        self.info=ttk.Label(right,text='',anchor='w',wraplength=220,justify='left'); self.info.pack(fill='x',pady=4)
        self.sel=ttk.Label(right,text='',anchor='w',wraplength=220,justify='left'); self.sel.pack(fill='x',pady=4)
        ttk.Button(right,text='Assign to selected face',command=self._assign).pack(fill='x',pady=2)
        ttk.Button(right,text='Clear texture on face',command=self._clear).pack(fill='x',pady=2)
        ttk.Label(right,text='Rotate texture on face').pack(fill='x',pady=(8,0))
        rot=ttk.Frame(right); rot.pack(fill='x')
        ttk.Button(rot,text='-90° (F7)',command=lambda: self._rotate(self.viewer.rotate_texture_back)).pack(side='left',fill='x',expand=True)
        ttk.Button(rot,text='+90° (F8)',command=lambda: self._rotate(self.viewer.rotate_texture_fwd)).pack(side='left',fill='x',expand=True)
        ttk.Button(right,text='Refresh face info',command=self._update_sel).pack(fill='x',pady=2)
        ttk.Button(right,text='Close',command=self.top.destroy).pack(fill='x',pady=(12,2))
        self.status=ttk.Label(self.top,text='',anchor='w'); self.status.pack(side='bottom',fill='x',padx=6)
        self.filter_var.trace_add('write',lambda *a: self._fill())
        self.lb.bind('<<ListboxSelect>>',lambda e: self._show())
        self._fill(); self._update_sel()

    def _fill(self):
        q=self.filter_var.get().strip().lower()
        self.names=[n for n in self.viewer._library().names() if not q or q in n.lower()]
        self.lb.delete(0,'end')
        for n in self.names: self.lb.insert('end',n)
        if not self.names:
            self.status.configure(text='No textures found. Add a folder or archive under View > 3D View > Texture libraries.')

    def _current(self):
        sel=self.lb.curselection()
        return self.names[sel[0]] if sel else None

    def _show(self):
        name=self._current()
        if not name: return
        self.viewer.tex_selected=name           # the browser's pick is the current texture for B
        t=self.viewer._library().texture(name)
        if t is None:
            self.preview.configure(image='',text='(no image)'); self.photo=None; return
        w,h,rows=t
        pal=self.viewer._palette()
        self.photo=_texture_photo(rows,w,h,pal)
        self.preview.configure(image=self.photo,text='')
        note='' if pal else ' (no palette: '+(self.viewer.palette_problem() or 'none')+')'
        self.info.configure(text=f'{name}  {w} x {h}'+note)

    def _rotate(self,fn):
        if fn(): self.status.configure(text='Texture rotated')
        else: self.status.configure(text='Select a quad face in the 3D view first.')
        self._update_sel()

    def _update_sel(self):
        poly=self.viewer.selected_poly()
        if poly is None: self.sel.configure(text='No face selected.')
        else: self.sel.configure(text=f"Selected face texture: {poly.tex or '(none)'}")

    def _assign(self):
        name=self._current()
        if not name: self.status.configure(text='Pick a texture first.'); return
        self._apply(name,f'Assigned {name}')

    def _clear(self):
        self._apply('','Texture cleared')

    def _apply(self,name,msg):
        if self.viewer.assign_texture(name): self.status.configure(text=msg)
        else: self.status.configure(text='Select a face in the 3D view first.')
        self._update_sel()

class Spinner(tk.Canvas):
    """Up and down arrows for one axis. A tap moves one step (the top half is up, the bottom half down). Holding the
    button and dragging vertically moves the value by the drag: up is more, down is less, as in 3ds Max spinners."""
    TAP_PX=3
    def __init__(self,master,on_tap,on_drag_start,on_drag,on_drag_end):
        super().__init__(master,width=20,height=28,highlightthickness=0,bd=0,cursor='sb_v_double_arrow')
        self.on_tap=on_tap; self.on_drag_start=on_drag_start; self.on_drag=on_drag; self.on_drag_end=on_drag_end
        self._y0=0; self._dir=1; self._active=False
        self.create_polygon(10,3,17,11,3,11,fill='#9a9a9a',outline='',tags='up')
        self.create_polygon(3,17,17,17,10,25,fill='#9a9a9a',outline='',tags='down')
        self.bind('<ButtonPress-1>',self._press); self.bind('<B1-Motion>',self._motion); self.bind('<ButtonRelease-1>',self._release)
    def _press(self,e):
        self._y0=e.y; self._dir=1 if e.y<self.winfo_height()/2 else -1; self._active=False
    def _motion(self,e):
        dy=self._y0-e.y                                   # positive when the mouse has moved up since the press
        if not self._active and abs(dy)>=self.TAP_PX: self._active=bool(self.on_drag_start())
        if self._active: self.on_drag(dy)
    def _release(self,e):
        if self._active: self.on_drag_end()
        else: self.on_tap(self._dir)
        self._active=False

class TransformPalette(tk.Toplevel):
    """Popup transform palette: exact values for the selected part's Move (world coordinates, or offsets along the part's own
    axes) or Rotate (degrees about world X, Y and Z), with spinners beside each axis. Each entry, tap or drag is one undo step.
    Rotate values are turns from the part's current pose, so the palette shows zero there and each apply turns the part."""
    MOVE_STEP=0.5; ROT_STEP=5.0          # one tap on a spinner
    MOVE_PER_PX=0.1; ROT_PER_PX=1.0      # one pixel of vertical drag on a spinner

    def __init__(self,master,viewer):
        super().__init__(master)
        self.title('Transform palette'); self.transient(master); self.resizable(False,False); self.viewer=viewer
        self._shown=['0','0','0']; self._exact=(0.0,0.0,0.0)
        self.mode_lbl=tk.Label(self,anchor='w',font=('TkDefaultFont',10,'bold')); self.mode_lbl.pack(fill='x',padx=8,pady=(8,2))
        self.space_bar=tk.Frame(self); self.space_bar.pack(fill='x',padx=8,pady=(0,4))
        self.space=tk.StringVar(value='world' if viewer.xf_absolute else 'local')
        ttk.Radiobutton(self.space_bar,text='World coordinates (absolute)',value='world',variable=self.space,command=self._space_changed).pack(side='left')
        ttk.Radiobutton(self.space_bar,text='Offset from current (local)',value='local',variable=self.space,command=self._space_changed).pack(side='left',padx=(8,0))
        grid=tk.Frame(self); grid.pack(padx=8,pady=4)
        self.entries=[]; self.vars=[]
        for k,name in enumerate(('X','Y','Z')):
            tk.Label(grid,text=name,width=3).grid(row=k,column=0,sticky='e')
            var=tk.StringVar(value='0'); self.vars.append(var)
            e=ttk.Entry(grid,textvariable=var,width=14); e.grid(row=k,column=1,padx=4,pady=2)
            e.bind('<Return>',lambda ev: self.apply()); self.entries.append(e)
            Spinner(grid,on_tap=lambda d,k=k: self._tap(k,d),on_drag_start=lambda k=k: self.viewer.spin_begin(k),
                    on_drag=lambda dy,k=k: self._drag(dy),on_drag_end=self.viewer.spin_end).grid(row=k,column=2,padx=4)
        bar=tk.Frame(self); bar.pack(fill='x',padx=8,pady=(4,2))
        ttk.Button(bar,text='Apply',command=self.apply).pack(side='left')
        ttk.Button(bar,text='Zero entries',command=self.zero).pack(side='left',padx=4)
        ttk.Button(bar,text='Close',command=self.close).pack(side='right')
        self.status=tk.Label(self,anchor='w',justify='left',wraplength=340); self.status.pack(fill='x',padx=8,pady=(2,8))
        viewer.add_listener(self.refresh)
        self.protocol('WM_DELETE_WINDOW',self.close)
        self.refresh()

    def _units(self):
        return 'degrees' if self.viewer.tool_var.get()=='rotate' else 'units'

    def refresh(self):
        try:
            if not self.winfo_exists(): return
        except tk.TclError: return
        st=self.viewer.palette_state()
        if st['tool']=='rotate': self.mode_lbl.configure(text='Rotate (degrees about world X, Y, Z)')
        elif st['tool']=='move': self.mode_lbl.configure(text='Move')
        else: self.mode_lbl.configure(text='Choose Move (W) or Rotate (E) in the 3D view')
        if st['tool']=='move': self.space_bar.pack(fill='x',padx=8,pady=(0,4),after=self.mode_lbl)
        else: self.space_bar.pack_forget()
        self._exact=st['values']
        for k,var in enumerate(self.vars):
            if st['absolute'] and st['tool']=='move':
                txt=f'{st["values"][k]:.4f}'.rstrip('0').rstrip('.') or '0'
                if self.focus_get()!=self.entries[k]: var.set(txt)
                self._shown[k]=txt
            else:
                if self.focus_get()!=self.entries[k]: var.set('0')
                self._shown[k]='0'
        msg=self.viewer.refusal or ('' if st['ok'] else 'Select a part to transform.')
        self.status.configure(text=msg)

    def _space_changed(self):
        self.viewer.xf_absolute=(self.space.get()=='world')
        self.viewer._refresh_info()

    def _read(self,k):
        """Entry text as a number. In absolute Move an unchanged entry keeps the part's exact coordinate."""
        txt=self.vars[k].get().strip()
        if self.viewer.palette_state()['absolute'] and self.viewer.tool_var.get()=='move' and txt==self._shown[k]:
            return self._exact[k]
        if txt=='': return 0.0
        return float(txt.replace(',','.'))

    def apply(self):
        try:
            vals=[self._read(k) for k in range(3)]
        except ValueError:
            self.viewer.refusal='type a number for each axis (decimals use a point)'; self.viewer._refresh_info(); return
        self.viewer.palette_apply(vals)
        self.refresh()

    def zero(self):
        for var in self.vars: var.set('0')

    def _tap(self,k,direction):
        step=self.MOVE_STEP if self.viewer.tool_var.get()=='move' else self.ROT_STEP
        self.viewer.palette_nudge(k,direction*step)

    def _drag(self,dy):
        per=self.MOVE_PER_PX if self.viewer.tool_var.get()=='move' else self.ROT_PER_PX
        self.viewer.spin_drag(round(dy*per,2))

    def close(self):
        self.viewer._listeners=[cb for cb in self.viewer._listeners if cb!=self.refresh]
        self.destroy()

class BasePlatePanel(tk.Toplevel):
    """Popout base plate tool. The base plate is the flat quad the base part designates for the ground (3do format note,
    'Selection primitive'). Create one from a width and depth, designate a flat quad part, clear the designation, or set the
    width (X) and depth (Z) of the designated plate. Each action is one undo step."""
    def __init__(self,master,viewer):
        super().__init__(master)
        self.title('Base plate tool'); self.transient(master); self.resizable(False,False); self.viewer=viewer
        self.status=tk.Label(self,anchor='w',justify='left',wraplength=380); self.status.pack(fill='x',padx=8,pady=(8,4))
        self.w_var=tk.StringVar(value='10'); self.d_var=tk.StringVar(value='10')
        def row(parent,label,var):
            f=tk.Frame(parent); f.pack(fill='x',pady=2)
            tk.Label(f,text=label,width=8,anchor='w').pack(side='left')
            ttk.Entry(f,textvariable=var,width=10).pack(side='left')
        sec=tk.LabelFrame(self,text='Create a new base plate'); sec.pack(fill='x',padx=8,pady=4)
        row(sec,'Width (X)',self.w_var); row(sec,'Depth (Z)',self.d_var)
        tk.Label(sec,text='Centred on the base part\'s pivot at height zero. It becomes the designated plate.',
                 justify='left',wraplength=360).pack(anchor='w',padx=2)
        ttk.Button(sec,text='Create base plate',command=self.create).pack(anchor='w',pady=4)
        sec2=tk.LabelFrame(self,text='Designate an existing quad'); sec2.pack(fill='x',padx=8,pady=4)
        tk.Label(sec2,text='Select a part that holds one flat four-corner face and designate it. On the base part, the quad\n'
                           'must be one of its faces. Another part\'s quad is moved into the base part and that part is removed.',
                 justify='left',wraplength=360).pack(anchor='w',padx=2)
        bf=tk.Frame(sec2); bf.pack(anchor='w',pady=4)
        ttk.Button(bf,text='Designate selected part',command=self.designate).pack(side='left')
        ttk.Button(bf,text='Clear designation',command=self.clear).pack(side='left',padx=4)
        sec3=tk.LabelFrame(self,text='Dimensions of the designated plate'); sec3.pack(fill='x',padx=8,pady=4)
        self.dw_var=tk.StringVar(value=''); self.dd_var=tk.StringVar(value='')
        row(sec3,'Width (X)',self.dw_var); row(sec3,'Depth (Z)',self.dd_var)
        ttk.Button(sec3,text='Apply dimensions',command=self.resize).pack(anchor='w',pady=4)
        ttk.Button(self,text='Close',command=self.close).pack(side='right',padx=8,pady=(0,8))
        viewer.add_listener(self.refresh)
        self.protocol('WM_DELETE_WINDOW',self.close)
        self.refresh()

    def _num(self,var,what):
        try:
            v=float(var.get().strip().replace(',','.'))
        except ValueError:
            raise ValueError(f'{what} must be a number')
        if not v>0: raise ValueError(f'{what} must be greater than zero')
        return v

    def refresh(self):
        try:
            if not self.winfo_exists(): return
        except tk.TclError: return
        msg=self.viewer.base_plate_status()
        if self.viewer.refusal: msg+='\n'+self.viewer.refusal
        self.status.configure(text=msg)
        size=base_plate_size(self.viewer.model.root) if self.viewer.model is not None else None
        if size is not None:
            focus=self.focus_get()
            if focus is None or focus.winfo_class()!='TEntry':        # keep what the user is typing
                self.dw_var.set(f'{size[0]:g}'); self.dd_var.set(f'{size[1]:g}')

    def _try(self,fn):
        try:
            return fn()
        except ValueError as e:
            self.viewer.refusal=str(e); self.viewer._refresh_info(); return None

    def create(self):
        def go():
            w=self._num(self.w_var,'Width'); d=self._num(self.d_var,'Depth')
            return self.viewer.base_plate_create(w,d)
        self._try(go)

    def designate(self): self.viewer.base_plate_designate()
    def clear(self): self.viewer.base_plate_clear()

    def resize(self):
        def go():
            w=self._num(self.dw_var,'Width'); d=self._num(self.dd_var,'Depth')
            return self.viewer.base_plate_resize(w,d)
        self._try(go)

    def close(self):
        self.viewer._listeners=[cb for cb in self.viewer._listeners if cb!=self.refresh]
        self.destroy()

class ListDialog:
    """Ordered folder list with add / remove / move up / move down. Calls on_change(items) after every edit."""
    def __init__(self,parent,title,items,on_change,allow_files=False):
        self.items=list(items); self.on_change=on_change; self.allow_files=allow_files
        self.top=tk.Toplevel(parent); self.top.title(title); self.top.geometry('620x300')
        self.lb=tk.Listbox(self.top,font='BostoolCode'); self.lb.pack(side='left',fill='both',expand=True,padx=6,pady=6)
        bf=ttk.Frame(self.top); bf.pack(side='right',fill='y',padx=6,pady=6)
        buttons=[('Add folder…',self.add)]
        if allow_files: buttons.append(('Add archive…',self.add_file))
        for text,cmd in buttons+[('Remove',self.remove),('Move up',lambda: self.move(-1)),('Move down',lambda: self.move(1)),('Close',self.top.destroy)]:
            ttk.Button(bf,text=text,command=cmd).pack(fill='x',pady=2)
        self._refresh()
    def _refresh(self):
        self.lb.delete(0,'end')
        for p in self.items: self.lb.insert('end',p)
    def _commit(self):
        self._refresh(); self.on_change(list(self.items))
    def add(self):
        d=filedialog.askdirectory(parent=self.top)
        if d and d not in self.items: self.items.append(_os.path.abspath(d)); self._commit()
    def add_file(self):
        f=filedialog.askopenfilename(parent=self.top,title='Texture archive',
            filetypes=[('HPI archives','*.hpi *.ufo *.ccx'),('All files','*.*')])
        if f and f not in self.items: self.items.append(_os.path.abspath(f)); self._commit()
    def remove(self):
        sel=self.lb.curselection()
        if sel: del self.items[sel[0]]; self._commit()
    def move(self,delta):
        sel=self.lb.curselection()
        if not sel: return
        i=sel[0]; j=i+delta
        if 0<=j<len(self.items):
            self.items[i],self.items[j]=self.items[j],self.items[i]; self._commit(); self.lb.selection_set(j)

def _parse_game_values(text):
    """'HEALTH=100, BUILD_PERCENT_LEFT=0' -> {'HEALTH': 100, 'BUILD_PERCENT_LEFT': 0}. Bad pairs are ignored."""
    out={}
    for part in (text or '').split(','):
        if '=' not in part: continue
        k,v=part.split('=',1)
        k=k.strip()
        try:
            if k and k.replace('_','').isalnum(): out[k]=int(v.strip())
        except ValueError: pass
    return out

def _play_notes_text(n):
    """One line on what a playback could not show: skipped conditional bodies, ignored commands, the tick cap."""
    if not n: return ''
    out=[]
    if n.get('skipped'): out.append('not evaluated (state-dependent, body skipped): '+'; '.join(n['skipped']))
    if n.get('unplayed'): out.append('motion not played yet: '+', '.join(n['unplayed']))
    if n.get('ignored'): out.append('no motion, ignored: '+', '.join(n['ignored']))
    if n.get('unknown_call'): out.append('calls to unknown scripts: '+', '.join(n['unknown_call']))
    if n.get('busy_loop'): out.append('a loop whose pass never reached a sleep or wait was stopped (its sleep is probably inside a skipped condition)')
    if n.get('depth'): out.append('nested calls deeper than 32 were cut')
    if n.get('capped'): out.append(f"stopped at the tick limit with {n['capped']} script(s) still running")
    return ' | '.join(out)

class TestRunPanel(tk.Toplevel):
    """Plays one BOS function on the open model, one engine tick per step, with halt and restore. The script comes
    from any BOS file or from the Animation output file. Before a part is first changed, its true base pose is
    recorded (the viewer's rest while animating, the tree otherwise); restore puts back only the parts the run changed,
    and a halted run is undone before the next one starts or when the panel closes."""
    TICK_MS=33
    # the script sources the panel can read: the open editor, the loaded COB, or the current animation timeline
    SOURCES=(('editor','Script in the editor'),('cob','Loaded COB'),('timeline','Animation timeline'))
    def __init__(self,parent,viewer,doc=None):
        super().__init__(parent)
        self.title('Test run'); self.viewer=viewer; self.transient(parent); self.doc=doc; self._key=None
        self.text=''; self.functions={}; self.frames=[]; self.i=0; self._job=None; self._orig={}; self._cur={}; self._statics={}; self._game={}
        bar=tk.Frame(self); bar.pack(fill='x',padx=6,pady=4)
        tk.Label(bar,text='Script:').pack(side='left')
        self.box=ttk.Combobox(bar,values=[lab for _,lab in self.SOURCES],state='readonly',width=22)
        self.box.pack(side='left',padx=4); self.box.bind('<<ComboboxSelected>>',self._choose)
        tk.Button(bar,text='Open BOS file…',command=self.open_file).pack(side='left',padx=4)
        self.src=tk.Label(bar,text='no script loaded',anchor='w'); self.src.pack(side='left',padx=6)
        self.lb=tk.Listbox(self,height=10,exportselection=False); self.lb.pack(fill='both',expand=True,padx=6)
        ctl=tk.Frame(self); ctl.pack(fill='x',padx=6,pady=4)
        tk.Button(ctl,text='Play',command=self.play).pack(side='left')
        tk.Button(ctl,text='Halt',command=self.halt).pack(side='left',padx=4)
        tk.Button(ctl,text='Restore base pose',command=self.restore).pack(side='left')
        tk.Label(ctl,text='  Game values (for get X):').pack(side='left')
        self._game_var=tk.StringVar(value='')
        ge=tk.Entry(ctl,textvariable=self._game_var,width=34); ge.pack(side='left',padx=4)
        ge.insert(0,''); self._game_entry=ge
        self.status=tk.Label(self,text='',anchor='w'); self.status.pack(fill='x',padx=6,pady=(0,6))
        self.protocol('WM_DELETE_WINDOW',self._close)
        if self.doc is not None: self._default_source()

    def _default_source(self):
        """Picks the first source that has something in it: the editor, then the loaded COB, then the timeline."""
        for key,lab in self.SOURCES:
            try: self.doc.test_source_text(key)
            except ThreeDOError: continue
            self.box.set(lab); self._key=key; self._load_source(); return

    def _choose(self,event=None):
        lab=self.box.get()
        self._key=next(k for k,l in self.SOURCES if l==lab)
        self._load_source()

    def _load_source(self):
        """Reads the chosen source again, so the script is what the editor, the COB or the timeline holds now.
        Returns False, with the reason in the status line, when the source has nothing to play."""
        if self._key is None or self.doc is None: return True
        try:
            text,label=self.doc.test_source_text(self._key)
            self.load_text(text,label)
            return True
        except ThreeDOError as e:
            self.status.config(text=str(e)); return False
        except Exception as e:
            self.status.config(text=f'could not read the script: {e}'); return False

    def load_text(self,text,source=''):
        """Shows the functions of a script. A script that is the same text as before keeps its statics and the function picked."""
        if text!=self.text: self._statics={}  # a changed script starts with its statics at zero
        picked=[self.lb.get(i) for i in self.lb.curselection()]
        self.halt()
        self.text=text; self.functions=bx_functions(text)
        self.lb.delete(0,'end')
        for n in self.functions: self.lb.insert('end',n)
        if picked and picked[0] in self.functions: self.lb.selection_set(list(self.functions).index(picked[0]))
        self.src.config(text=source or 'script')
        self.status.config(text=f'{len(self.functions)} function(s) in {source or "the script"}')
    def open_file(self):
        p=filedialog.askopenfilename(parent=self,title='Open BOS script',filetypes=[('BOS script','*.bos *.BOS'),('All files','*')])
        if not p: return
        self._key=None; self.box.set('')
        with open(p,encoding='utf-8',errors='replace') as fh: self.load_text(fh.read(),_os.path.basename(p))
    def _pieces(self):
        return {p.name:p for _,p in _roots_paths(self.viewer.roots())}
    def _base_of(self,key,piece):
        """A part's true base pose: the viewer's stored rest while animating, the tree otherwise."""
        if self.viewer.driver=='anim' and self.viewer.rest and key in self.viewer.rest:
            r=self.viewer.rest[key]; return (r[0],tuple(r[1]))
        return (piece.pend,tuple(piece.offset))
    def _touch(self,name):
        """Records a part's base pose before the run first changes it, so restore can put exactly that back."""
        if name in self._orig: return
        p=self._pieces().get(name)
        if p is None: return
        key=[k for k,n in bx_piece_names(self.viewer.roots()).items() if n==name]
        self._orig[name]=self._base_of(key[0] if key else None,p)
    def _undo_run(self):
        """Puts back every part the runs have changed, from the recorded base. True if anything was put back."""
        if not self._orig: return False
        pieces=self._pieces()
        for name,(pend,off) in self._orig.items():
            p=pieces.get(name)
            if p is not None: p.pend=pend; p.offset=tuple(off)
        self._orig={}; self._cur={}
        if self.viewer.driver=='anim': self.viewer._apply_time()     # the clip's frame goes back over the base
        self.viewer._resync_view()
        return True
    def play(self):
        if not self._load_source(): return      # a chosen source is read again, so edits made since the last run play
        sel=self.lb.curselection()
        if not sel: self.status.config(text='pick a function first'); return
        name=self.lb.get(sel[0])
        self._game=_parse_game_values(self._game_var.get())
        self.halt()
        self._undo_run()                      # a halted run left its pose behind: the next run starts from the base
        self.frames,self._notes=bx_play(self.text,name,statics=self._statics,game=self._game); self.i=0; self._name=name
        self._tick()
    def _tick(self):
        if self.i>=len(self.frames):
            self._job=None; self.status.config(text=f'{self._name} finished. '+_play_notes_text(getattr(self,'_notes',None))); return
        self._apply(self.frames[self.i])
        self.status.config(text=f'{self._name}: tick {self.i} of {len(self.frames)-1}')
        self.i+=1
        self._job=self.after(self.TICK_MS,self._tick)
    def _apply(self,frame):
        pieces=self._pieces()
        for name,kinds in frame.items():
            p=pieces.get(name)
            if p is None: continue
            self._touch(name)
            base_pend,base_off=self._orig[name]
            cur=self._cur.setdefault(name,{'rot':{'x':0,'y':0,'z':0},'pos':{}})
            cur['rot'].update(kinds['rot']); cur['pos'].update(kinds['pos'])
            deg=[((cur['rot'][a]+32768)&0xffff)-32768 for a in 'xyz']
            deg=[d*360.0/BX_ANGLE_UNITS for d in deg]
            # the script's angles and offsets are relative to rest, so they compose onto the part's base pose
            p.pend=q_norm(q_mul(base_pend or _QI,euler_to_q(engine_angles(tuple(deg)))))
            # the script's offsets are engine values relative to rest: map them back to the viewer, then add to the base
            d=engine_offset(tuple(cur['pos'].get(a,0)/float(LINEAR_SCALE) for a in 'xyz'))
            p.offset=tuple(base_off[i]+d[i] for i in range(3))
        self.viewer._resync_view()
    def halt(self):
        if self._job is not None:
            try: self.after_cancel(self._job)
            except Exception: pass
            self._job=None
            self.status.config(text=f'{getattr(self,"_name","")}: halted at tick {self.i}')
    def restore(self):
        self.halt()
        if not self._undo_run():
            self.status.config(text='nothing to restore: no run has changed the model'); return
        self.status.config(text='base pose restored')
    def _close(self):
        self.halt(); self._undo_run(); self.destroy()

class CurveEditor(tk.Toplevel):
    """Free-floating curve window for the selected part's keys. Rotation is shown per axis as Euler angles in degrees
    (X, Y, Z, applied X first); position as offsets. Select a key to edit its values in the row under the graph, or
    drag it sideways to move it in time. Keys are never created here: use Add Key on the timeline."""
    ROT=(('rot',0,'X','#ff6060'),('rot',1,'Y','#60ff60'),('rot',2,'Z','#6090ff'))
    POS=(('pos',0,'px','#ff9090'),('pos',1,'py','#90ff90'),('pos',2,'pz','#90b0ff'))
    ML,MR,MT,MB=52,12,18,22

    def __init__(self,master,viewer):
        super().__init__(master)
        self.title('Curve editor'); self.geometry('860x440'); self.viewer=viewer
        self.sel=None; self._drag=None; self._geom=(400,1,0,0); self._filled=None
        bar=tk.Frame(self); bar.pack(side='top',fill='x',padx=4,pady=2)
        self.part_lbl=tk.Label(bar,anchor='w'); self.part_lbl.pack(side='left',fill='x',expand=True)
        self.show_rot=tk.BooleanVar(value=True); self.show_pos=tk.BooleanVar(value=True)
        tk.Checkbutton(bar,text='Rotation (degrees)',variable=self.show_rot,command=self._draw).pack(side='left',padx=2)
        tk.Checkbutton(bar,text='Position',variable=self.show_pos,command=self._draw).pack(side='left',padx=2)
        tk.Label(bar,text='Key interpolation').pack(side='left',padx=(8,0))
        self.interp_var=tk.StringVar(value='smooth')
        cb=ttk.Combobox(bar,values=INTERP,textvariable=self.interp_var,state='readonly',width=8)
        cb.pack(side='left',padx=4); cb.bind('<<ComboboxSelected>>',lambda e: self._set_interp())
        tk.Button(bar,text='Delete key',command=self._delete).pack(side='left',padx=4)
        vals=tk.Frame(self); vals.pack(side='top',fill='x',padx=4,pady=2)
        self.val_lbl=tk.Label(vals,anchor='w',width=30); self.val_lbl.pack(side='left')
        self.entries={}
        for ax in ('X','Y','Z'):
            tk.Label(vals,text=ax).pack(side='left',padx=(6,1))
            var=tk.StringVar(value='')
            e=tk.Entry(vals,textvariable=var,width=10); e.pack(side='left')
            e.bind('<Return>',lambda ev: self._apply())
            self.entries[ax]=(var,e)
        self.apply_btn=tk.Button(vals,text='Apply',command=self._apply,state='disabled'); self.apply_btn.pack(side='left',padx=8)
        self.c=tk.Canvas(self,bg='#262626',highlightthickness=0); self.c.pack(fill='both',expand=True,padx=4,pady=2)
        tk.Label(self,anchor='w',text='Rotation is in degrees per axis (X, then Y, then Z). Between keys the curve is the '
                 'smooth path the clip takes. Drag a key sideways to move it in time.').pack(side='bottom',fill='x',padx=4)
        self.c.bind('<Configure>',lambda e: self.refresh())
        self.c.bind('<Button-1>',self._press); self.c.bind('<B1-Motion>',self._motion); self.c.bind('<ButtonRelease-1>',self._release)
        viewer.add_listener(self.refresh)
        self.protocol('WM_DELETE_WINDOW',self._close)

    def _close(self):
        self.viewer._listeners=[cb for cb in self.viewer._listeners if cb!=self.refresh]
        self.destroy()

    def _pk(self):
        v=self.viewer
        return piece_key(v._piece_path(v.sel_part)) if v.sel_part is not None else None

    def refresh(self):
        try: self.winfo_exists()
        except tk.TclError: return
        v=self.viewer
        name=(v.sel_part.name or '(unnamed)') if v.sel_part is not None else None
        self.part_lbl.configure(text=f'Part: {name}  ·  sequence: {v.seqs[v.seq_i]["name"]}' if name else 'Select a part to see its curves.')
        self._draw(); self._fill_fields()

    def _euler_track(self,keys,n):
        """Samples of a rotation track in degrees per axis, unwrapped so a curve does not jump at ±180."""
        out=[[],[],[]]; prev=None
        for j in range(n+1):
            f=self._S+self._L*j/float(n)
            e=q_to_euler(eval_rot(keys,f))
            if prev is not None:
                e=tuple(e[i]+360.0*round((prev[i]-e[i])/360.0) for i in range(3))
            prev=e
            for i in range(3): out[i].append(e[i])
        return out

    def _draw(self):
        c=self.c; c.delete('all'); v=self.viewer
        W=max(c.winfo_width(),200); H=max(c.winfo_height(),120)
        L=v.anim['timeline']['length']; s,e=v.span(); ml,mr,mt,mb=self.ML,self.MR,self.MT,self.MB
        self._geom=(W,L,ml,mr); self._L=L; self._S=s
        pk=self._pk()
        tr=v.anim['tracks'].get(pk) if pk else None
        if not tr or not (tr['rot'] or tr['pos']):
            c.create_text(W/2,H/2,text='No keys for this part yet. Turn Animate on and press Add Key.',fill='#aaa')
            self._playhead(W,L,H); return
        n=min(max(L*2,20),800)
        series=[]                     # (kind, comp, name, colour, samples or None, keys)
        if self.show_rot.get() and tr['rot']:
            rs=self._euler_track(tr['rot'],n)
            for i,(kind,comp,name,colour) in enumerate(self.ROT): series.append((kind,comp,name,colour,rs[comp],tr['rot']))
        if self.show_pos.get() and tr['pos']:
            for kind,comp,name,colour in self.POS: series.append((kind,comp,name,colour,None,tr[kind]))
        vmax=1.0
        for kind,comp,name,colour,samp,keys in series:
            vals=samp if samp is not None else []
            if samp is not None: vmax=max(vmax,max(abs(x) for x in samp))
            for k in keys: vmax=max(vmax,abs(k['v'][comp]) if kind=='pos' else abs(q_to_euler(k['v'])[comp]))
        vmax*=1.1
        X=lambda f: ml+(W-ml-mr)*(f-s)/float(L)
        Y=lambda val: mt+(H-mt-mb)*(vmax-val)/(2*vmax)
        for val,lbl in ((vmax,f'{vmax:.0f}'),(0.0,'0'),(-vmax,f'{-vmax:.0f}')):
            c.create_line(ml,Y(val),W-mr,Y(val),fill='#444' if val else '#666')
            c.create_text(ml-4,Y(val),text=lbl,fill='#aaa',anchor='e',font=('TkDefaultFont',7))
        step=max(1,L//10)
        for f in range(s,e+1,step):
            c.create_line(X(f),mt,X(f),H-mb,fill='#353535')
            c.create_text(X(f),H-mb+3,text=str(f),fill='#aaa',anchor='n',font=('TkDefaultFont',7))
        for kind,comp,name,colour,samp,keys in series:
            if samp is not None:
                pts=[]
                for j in range(n+1):
                    f=s+L*j/float(n); pts+=[X(f),Y(samp[j])]
                c.create_line(*pts,fill=colour,width=1,dash=(4,3))
            else:
                pts=[]
                for j in range(n+1):
                    f=s+L*j/float(n); pts+=[X(f),Y(eval_pos(keys,f)[comp])]
                c.create_line(*pts,fill=colour,width=2)
            for k in keys:
                val=k['v'][comp] if kind=='pos' else q_to_euler(k['v'])[comp]
                x,y=X(k['t']),Y(val); on=self.sel==(kind,k['t'])
                c.create_rectangle(x-4,y-4,x+4,y+4,fill='#ffd040' if on else colour,outline='',tags=(f'key:{kind}:{k["t"]}',))
        legend=[nm for kind,comp,nm,colour in self.ROT] if self.show_rot.get() else []
        legend+= [nm for kind,comp,nm,colour in self.POS] if self.show_pos.get() else []
        c.create_text(W-mr-4,mt+2,text='  '.join(legend)+('   dashed = rotation, solid = position' if legend else ''),fill='#aaa',anchor='ne',font=('TkDefaultFont',7))
        self._playhead(W,L,H)

    def _playhead(self,W,L,H):
        ml,mr=self.ML,self.MR; s,_=self.viewer.span()
        x=ml+(W-ml-mr)*(self.viewer.frame_t-s)/float(L)
        self.c.create_line(x,0,x,H,fill='#ff5050',width=2)

    def _key_values(self):
        """The selected key's values as [X,Y,Z], or None when nothing is selected."""
        if self.sel is None: return None
        kind,t=self.sel; pk=self._pk()
        hit=[k for k in self.viewer.anim['tracks'].get(pk,{}).get(kind,[]) if k['t']==t] if pk else []
        if not hit: return None
        v=hit[0]['v']
        return q_to_euler(v) if kind=='rot' else tuple(v)

    def _fill_fields(self):
        """Shows the selected key's values in the row. Typed text is only replaced when the selection changes."""
        key=self.sel and (self.sel,self._pk())
        if key==self._filled: return
        self._filled=key
        vals=self._key_values()
        if vals is None:
            self.val_lbl.configure(text='Select a key to edit its values.')
            for ax,(var,e) in self.entries.items(): var.set(''); e.configure(state='disabled')
            self.apply_btn.configure(state='disabled'); return
        kind,t=self.sel
        self.val_lbl.configure(text=(f'Rotation at frame {t} (degrees)' if kind=='rot' else f'Position at frame {t}'))
        for ax,x in zip(('X','Y','Z'),vals):
            var,e=self.entries[ax]; var.set(f'{x:.2f}'); e.configure(state='normal')
        self.apply_btn.configure(state='normal')

    def _apply(self):
        if self.sel is None: return
        kind,t=self.sel
        try:
            vals=tuple(float(self.entries[ax][0].get()) for ax in ('X','Y','Z'))
        except ValueError:
            messagebox.showerror('Value not a number','Type a number for each axis.',parent=self); return
        try:
            if kind=='rot': self.viewer.set_key_values(self._pk(),t,rot_deg=vals)
            else: self.viewer.set_key_values(self._pk(),t,pos=vals)
        except ThreeDOError as err:
            messagebox.showerror('Cannot set value',str(err),parent=self); return
        self._filled=None; self._fill_fields()

    def _press(self,e):
        items=self.c.find_closest(e.x,e.y)
        tags=[t for t in self.c.gettags(items[0]) if t.startswith('key:')] if items else []
        if not tags:
            self.sel=None; self._drag=None; self._draw(); self._fill_fields(); return
        _,kind,t=tags[0].split(':'); t=int(t)
        self.sel=(kind,t); self._drag=(e.x,t)
        self.interp_var.set(self._key_interp(kind,t))
        self._draw(); self._fill_fields()

    def _key_interp(self,kind,t):
        pk=self._pk()
        for k in (self.viewer.anim['tracks'].get(pk,{}).get(kind,[]) if pk else []):
            if k['t']==t: return k['i']
        return 'smooth'

    def _motion(self,e):
        pass        # the key follows on release; a live ghost is a later refinement

    def _release(self,e):
        if self._drag is None: return
        x0,t0=self._drag; self._drag=None
        W,L,ml,mr=self._geom
        s,e_=self.viewer.span()
        delta=round((e.x-x0)*L/float(max(W-ml-mr,1)))
        t_new=max(s,min(e_,t0+delta))
        if t_new==t0: return
        kind=self.sel[0]
        try:
            self.viewer.move_key(self._pk(),kind,t0,t_new)
            self.sel=(kind,t_new); self._filled=None
        except ThreeDOError as err:
            messagebox.showerror('Cannot move key',str(err),parent=self)

    def _delete(self):
        if self.sel is None: return
        kind,t=self.sel
        self.viewer.delete_key(self._pk(),kind,t); self.sel=None; self._filled=None

    def _set_interp(self):
        if self.sel is None: return
        kind,t=self.sel
        self.viewer.set_key_interp(self._pk(),kind,t,self.interp_var.get())

class DocWindow:
    def __init__(self,app,path=None):
        self.app=app; self.cfg=app.cfg
        self.path=None; self.cob_bytes=None; self.cob_path=None; self.decompiled_from=None
        self.origin=[]; self.error_items=[]
        self.win=tk.Toplevel(app.root); self.win.geometry('1150x760')
        self.win.protocol('WM_DELETE_WINDOW',self.close)
        self.case_var=tk.BooleanVar(value=self.cfg.data['case_check'])
        self.label_var=tk.BooleanVar(value=bool(self.cfg.data.get('label_functions')))
        self.scale_var=tk.IntVar(value=LINEAR_SCALE)
        self.layout_var=tk.StringVar(value='code')
        self._panes(); self._menu()          # the 3D View menu reads the viewer, so panes come first
        self.status=tk.StringVar(value='Ready')
        ttk.Label(self.win,textvariable=self.status,anchor='w').pack(side='bottom',fill='x')
        self.win.bind('<Control-s>',lambda e: self.save()); self.win.bind('<Control-o>',lambda e: self.open_dialog())
        self.win.bind('<Control-b>',lambda e: self.compile()); self.win.bind('<F5>',lambda e: self.compile())
        self.win.bind('<Control-n>',lambda e: self.app.new_doc())
        self.win.bind('<Alt-w>',lambda e: self.viewer.toggle_maximize()); self.win.bind('<Alt-W>',lambda e: self.viewer.toggle_maximize())
        if path and path.lower().endswith(('.3do','.3dox')): self._open_3do_path(path)   # a model or project on the command line
        elif path: self.open_path(path)
        self._update_title()
        self._last_autosave=_time.time(); self._start_autosave()

    # ---- layout ----
    def _menu(self):
        m=tk.Menu(self.win); self.win.config(menu=m)
        f=tk.Menu(m,tearoff=0); m.add_cascade(label='File',menu=f)
        f.add_command(label='New window',accelerator='Ctrl+N',command=self.app.new_doc)
        f.add_command(label='Open…',accelerator='Ctrl+O',command=self.open_dialog)
        self.recent_menu=tk.Menu(f,tearoff=0); f.add_cascade(label='Recent',menu=self.recent_menu)
        f.add_command(label='Save',accelerator='Ctrl+S',command=self.save)
        f.add_command(label='Save As…',command=self.save_as)
        f.add_separator()
        f.add_command(label='New 3DO model',command=self.new_3do)
        f.add_command(label='Open 3DO model…',command=self.open_3do)
        f.add_command(label='Save 3DO model',command=self.save_model)
        f.add_command(label='Save 3DO model as…',command=lambda: self.save_model(as_new=True))
        f.add_command(label='Finalize 3DO model (bake poses, write .3do)',command=self.finalize_3do)
        f.add_separator()
        f.add_command(label='Load project (.3dox)…',command=self.load_project_dialog)
        f.add_command(label='Save project (.3dox)…',command=self.save_project_dialog)
        self.recent_projects_menu=tk.Menu(f,tearoff=0); f.add_cascade(label='Recent Projects',menu=self.recent_projects_menu)
        ex=tk.Menu(f,tearoff=0); f.add_cascade(label='Export',menu=ex)
        for scope,label in (('part','Selected part as'),('model','Whole model as')):
            sub=tk.Menu(ex,tearoff=0); ex.add_cascade(label=label,menu=sub)
            fmts=[('lwo','LightWave (LWOB)…'),('dxf','DXF…'),('obj','Wavefront OBJ…')]
            if scope=='part': fmts.append(('3do','3DO (this part with its children)…'))
            for fmt,flabel in fmts:
                sub.add_command(label=flabel,command=lambda s=scope,q=fmt: self.export_3d_dialog(s,q))
        self.recent3_menu=tk.Menu(f,tearoff=0); f.add_cascade(label='Recent 3DO models',menu=self.recent3_menu)
        f.add_command(label='Autosave interval…',command=self.autosave_dialog)
        f.add_separator(); f.add_command(label='Close window',command=self.close)
        ed=tk.Menu(m,tearoff=0); m.add_cascade(label='Edit',menu=ed)
        ed.add_command(label='Undo model edit',command=self.viewer.undo)
        ed.add_command(label='Redo model edit',command=self.viewer.redo)
        ed.add_separator()
        ed.add_command(label='Cut (script)',accelerator='Ctrl+X',command=lambda: self._script_clip('<<Cut>>'))
        ed.add_command(label='Copy (script)',accelerator='Ctrl+C',command=lambda: self._script_clip('<<Copy>>'))
        ed.add_command(label='Paste (script)',accelerator='Ctrl+V',command=lambda: self._script_clip('<<Paste>>'))
        ed.add_separator()
        ed.add_command(label='Ctrl+Z / Ctrl+Y work when the 3D viewport has focus',state='disabled')
        v=tk.Menu(m,tearoff=0); m.add_cascade(label='View',menu=v)
        v.add_command(label='Larger text',accelerator='Ctrl+=',command=lambda: self._ui_size_change(1))
        v.add_command(label='Smaller text',accelerator='Ctrl+-',command=lambda: self._ui_size_change(-1))
        v.add_command(label='Reset text size',command=lambda: self._ui_size_change(reset=True))
        v.add_separator()
        v.add_radiobutton(label='Code editor only',variable=self.layout_var,value='code',command=lambda: self.set_layout('code'))
        v.add_radiobutton(label='Code editor + 3DO viewport',variable=self.layout_var,value='both',command=lambda: self.set_layout('both'))
        v.add_radiobutton(label='3DO viewport only',variable=self.layout_var,value='3d',command=lambda: self.set_layout('3d'))
        v.add_separator()
        self.dark_var=tk.BooleanVar(value=bool(self.app.cfg.data.get('dark_mode',False)))
        v.add_checkbutton(label='Dark mode',variable=self.dark_var,command=self._toggle_dark)
        self.win.bind('<Control-equal>',lambda e: self._ui_size_change(1))
        self.win.bind('<Control-minus>',lambda e: self._ui_size_change(-1))
        b=tk.Menu(m,tearoff=0); m.add_cascade(label='Build',menu=b)
        b.add_command(label='Compile',accelerator='F5',command=self.compile)
        b.add_command(label='Decompile COB (manual)',command=self.decompile)
        b.add_separator()
        b.add_command(label='Output file…',command=self.output_dialog)
        b.add_command(label='Include folders for this file…',command=self.incdirs_dialog)
        b.add_command(label='Global include folders…',command=self.global_incdirs_dialog)
        b.add_separator()
        b.add_checkbutton(label='Check for case-only filename collisions',variable=self.case_var,command=self._toggle_case)
        b.add_checkbutton(label='Label variables by function when decompiling',variable=self.label_var,command=self._toggle_label)
        b.add_separator()
        b.add_radiobutton(label='Linear scale 65536 (default)',variable=self.scale_var,value=65536,command=self._set_scale)
        b.add_radiobutton(label='Linear scale 163840 (2.5x)',variable=self.scale_var,value=163840,command=self._set_scale)
        b.add_command(label='About the linear scale…',command=self._scale_help)
        sepm=tk.Menu(m,tearoff=0); m.add_cascade(label='|',menu=sepm,state='disabled')
        d=tk.Menu(m,tearoff=0); m.add_cascade(label='3D View',menu=d)
        d.add_command(label='Toggle quad / single view',accelerator='Alt+W',command=self.viewer.toggle_maximize)
        self.pane_view_var=tk.StringVar(value='3D'); self.pane_mode_var=tk.StringVar(value='shaded'); self.pane_bg_var=tk.StringVar(value='grid')
        vv=tk.Menu(d,tearoff=0); d.add_cascade(label='Active pane view',menu=vv)
        for name in VIEW_NAMES:
            vv.add_radiobutton(label=name,variable=self.pane_view_var,value=name,command=lambda n=name: self.viewer.set_active_view(n))
        mm=tk.Menu(d,tearoff=0); d.add_cascade(label='Active pane render',menu=mm)
        for mode,label in (('wireframe','Wireframe'),('shaded','Shaded'),('textured','Textured')):
            mm.add_radiobutton(label=label,variable=self.pane_mode_var,value=mode,command=lambda md=mode: self.viewer.set_active_mode(md))
        bgm=tk.Menu(d,tearoff=0); d.add_cascade(label='Active pane background',menu=bgm)
        for key in ('grid','dark'):
            bgm.add_radiobutton(label=BACKDROP_LABELS[key],variable=self.pane_bg_var,value=key,command=lambda k=key: self.viewer.set_active_bg(k))
        d.add_command(label='Grid cell size…',command=self._grid_cell_dialog)
        d.add_separator()
        d.add_checkbutton(label='Highlight three-point faces',variable=self.viewer.hl3_var,command=self.viewer.set_hl3)
        d.add_command(label='Face outline colour…',command=self._pick_outline_colour)
        d.add_command(label='Reset active view',command=self.viewer.reset_active_view)
        d.add_command(label='Frame selection (Z)',command=self.viewer.frame_selection)
        d.add_command(label='Undo view change (Shift+Z)',command=self.viewer.undo_view)
        self._orbit_var=tk.BooleanVar(value=self.viewer._orbit_on())
        d.add_checkbutton(label='Orbit around selection',variable=self._orbit_var,
            command=lambda: self.viewer.set_orbit_selection(self._orbit_var.get()))
        tm=tk.Menu(d,tearoff=0); d.add_cascade(label='Manipulator tool',menu=tm)
        tm.add_radiobutton(label='Select (Q)',variable=self.viewer.tool_var,value='select',command=self.viewer._tool_changed)
        tm.add_radiobutton(label='Move axes (W)',variable=self.viewer.tool_var,value='move',command=self.viewer._tool_changed)
        tm.add_radiobutton(label='Rotate rings (E)',variable=self.viewer.tool_var,value='rotate',command=self.viewer._tool_changed)
        tm.add_separator()
        tm.add_checkbutton(label='Move: pivot only (origin moves, geometry stays)',variable=self.viewer.pivot_var)
        def _sync_3d_menu():
            p=self.viewer.panes[self.viewer.active]
            self.pane_view_var.set(p['view']); self.pane_mode_var.set(p['mode']); self.pane_bg_var.set(p['bg'])
        d.config(postcommand=_sync_3d_menu)
        pc=tk.Menu(m,tearoff=0); m.add_cascade(label='Piece',menu=pc)     # just right of 3D View
        pc.add_command(label='Import (new piece)…',command=lambda: self.import_piece_dialog(False))
        pc.add_command(label='Import (replace selected piece)…',command=lambda: self.import_piece_dialog(True))
        pxs=tk.Menu(pc,tearoff=0); pc.add_cascade(label='Export selected piece as',menu=pxs)
        for fmt,flabel in (('lwo','LightWave (LWOB)…'),('dxf','DXF…'),('obj','Wavefront OBJ…'),('3do','3DO (this part with its children)…')):
            pxs.add_command(label=flabel,command=lambda q=fmt: self.export_3d_dialog('part',q))
        pc.add_separator()
        pc.add_command(label='Create piece (no geometry)…',command=self.create_piece_dialog)
        pc.add_command(label='Duplicate selected piece',command=self.viewer.duplicate_selected)
        pc.add_separator()
        for axis,lab in ((0,'X'),(1,'Y'),(2,'Z')):
            pc.add_command(label=f'Mirror {lab} (across the pivot)',command=lambda a=axis: self.viewer.mirror_selected(a))
        pc.add_separator()
        pvm=tk.Menu(pc,tearoff=0); pc.add_cascade(label='Pivot',menu=pvm)
        pvm.add_checkbutton(label='Highlight pivot',variable=self.viewer.highlight_pivot,command=self.viewer.redraw)
        pvm.add_command(label='Move pivot… (accept or cancel)',command=self.viewer.pivot_move_start)
        pvm.add_command(label='Match to other piece (then click it)',command=self.viewer.match_pivot_start)
        pvm.add_command(label='Center to mesh',command=self.viewer.center_pivot_mesh)
        pvm.add_command(label='Center to world (0, 0, 0)',command=self.viewer.center_pivot_world)
        pc.add_separator()
        pc.add_command(label='Transform palette…',command=self.open_transform_palette)
        pc.add_command(label='Base plate tool…',command=self.open_base_plate_panel)
        pm=tk.Menu(m,tearoff=0); m.add_cascade(label='Part',menu=pm)
        pm.add_command(label='Set origin of selected part…',command=self.set_origin_dialog)
        pm.add_command(label='Make selected part top level',command=self.make_top_level)
        pm.add_separator()
        pm.add_command(label='Commit pending rotation of selected part',command=lambda: self.commit_pending_menu(False))
        pm.add_command(label='Commit all pending rotations',command=lambda: self.commit_pending_menu(True))
        pm.add_separator()
        pm.add_command(label='Spin quad edge (C)',command=self.viewer.spin_face_edge)
        pm.add_command(label='Flip face normal (V)',command=self.viewer.flip_face_normal)
        pm.add_separator()
        pm.add_command(label='Drag parts in the list to nest them (drop on empty space to unnest)',state='disabled')
        an=tk.Menu(m,tearoff=0); m.add_cascade(label='Animation',menu=an)
        an.add_checkbutton(label='Timeline toolbar (bottom of the 3D view)',variable=self.viewer.tl_visible,
            command=lambda: self.viewer.show_timeline(self.viewer.tl_visible.get()))
        an.add_command(label='Curve editor window…',command=self.open_curve_editor)
        an.add_separator()
        an.add_command(label='Load sequence file (.3dan)…',command=self.load_sequence_dialog)
        an.add_command(label='Save current sequence as file…',command=self.save_sequence_dialog)
        an.add_command(label='Animation output file…',command=self.output_location_dialog)
        an.add_command(label='Export animation to BOS (selected sequence)…',command=self.export_bos_dialog)
        an.add_command(label='Test-run panel…',command=self.open_test_run)
        an.add_separator()
        an.add_checkbutton(label='Animate (show the clip at the playhead)',variable=self.viewer.anim_var,command=self.viewer._animate_clicked)
        an.add_checkbutton(label='Auto Key (key the part when a gizmo drag ends)',variable=self.viewer.autokey_var,command=self.viewer._autokey_clicked)
        an.add_command(label='Add key to selected part',command=self.viewer._add_key_clicked)
        tx=tk.Menu(m,tearoff=0); m.add_cascade(label='Textures',menu=tx)
        tx.add_checkbutton(label='Texture palette (docked right of the 3D view)',variable=self.tex_panel_var,command=self.toggle_tex_panel)
        tx.add_separator()
        tx.add_command(label='Texture browser…',command=self._texture_browser)
        tx.add_separator()
        tl=tk.Menu(tx,tearoff=0); tx.add_cascade(label='Texture libraries',menu=tl)
        tl.add_command(label='Add folder…',command=lambda: self._add_texture_source(True))
        tl.add_command(label='Add archive (.hpi)…',command=lambda: self._add_texture_source(False))
        tl.add_command(label='Manage sources…',command=self._texture_sources_dialog)
        tl.add_command(label='Reload from disk',command=self.viewer.reload_textures)
        tx.add_separator()
        tx.add_command(label='Set palette file (TApalette.dat)…',command=self.palette_dialog)
        hp=tk.Menu(m,tearoff=0); m.add_cascade(label='Help',menu=hp)          # last on the menu line
        hp.add_command(label='How to use Advanced Model Factory…',command=lambda: show_help_how(self.win))
        hp.add_command(label='Hotkeys and navigation…',command=lambda: show_help_keys(self.win))
        hp.add_separator()
        hp.add_command(label='About Advanced Model Factory',command=lambda: show_help_about(self.win))
        self._rebuild_recent_menu(); self._rebuild_recent3(); self._rebuild_recent_projects()

    def _panes(self):
        self.split=tk.PanedWindow(self.win,orient='horizontal',sashwidth=6,sashrelief='raised')
        self.split.pack(fill='both',expand=True)
        self.nb=ttk.Notebook(self.split); self.split.add(self.nb,minsize=240,stretch='always')
        self.viewer=Viewport3DO(self.split,self.cfg)
        self.viewer.on_title=self._update_title     # the window title follows the loaded project
        self.tex_panel=TexturePanel(self.split,self.viewer); self.tex_panel_var=tk.BooleanVar(value=False)
        code=ttk.Frame(self.nb); self.nb.add(code,text='Code')
        code.rowconfigure(0,weight=1); code.columnconfigure(1,weight=1)
        self.gutter=theme_track(tk.Text(code,width=5,padx=4,bd=0,font='BostoolCode',background='#eeeeee',foreground='#666666',state='disabled',takefocus=0,cursor='arrow'),'alt')
        self.editor=theme_track(tk.Text(code,undo=True,wrap='none',font='BostoolCode',tabs=('2c',),background='white'),'field')
        sb=ttk.Scrollbar(code,orient='vertical',command=self._yview)
        hsb=ttk.Scrollbar(code,orient='horizontal',command=self.editor.xview)
        self.editor.configure(yscrollcommand=lambda a,b: (sb.set(a,b), self.gutter.yview_moveto(a)), xscrollcommand=hsb.set)
        self.gutter.grid(row=0,column=0,sticky='ns'); self.editor.grid(row=0,column=1,sticky='nsew')
        sb.grid(row=0,column=2,sticky='ns'); hsb.grid(row=1,column=1,sticky='ew')
        for k,fg in [('kw','#0000cc'),('com','#008000'),('dir','#a00000'),('num','#7a00a0')]:
            self.editor.tag_configure(k,foreground=fg)
        self.editor.tag_configure('errline',background='#ffd0d0')
        self.editor.bind('<KeyRelease>',lambda e: self._on_edit())
        self.editor.bind('<<Paste>>',lambda e: self.win.after(1,self._on_edit))
        self.pp_text=self._readonly_tab('Preprocessor'); self.pp_text.tag_configure('origin',foreground='#555599')
        self.asm_text=self._readonly_tab('Assembly')
        err=ttk.Frame(self.win); err.pack(side='bottom',fill='x')
        ttk.Label(err,text='Errors (double-click to jump):').pack(anchor='w')
        self.errlist=tk.Listbox(err,height=6,font='BostoolCode'); self.errlist.pack(fill='x')
        self.errlist.bind('<Double-Button-1>',lambda e: self._jump_error())

    # ---- projects (.3dox) ----
    def _note_recent_project(self,p):
        p=_os.path.abspath(p)
        lst=self.cfg.data.get('recent_projects',[])
        self.cfg.data['recent_projects']=([p]+[x for x in lst if x!=p])[:MAX_RECENT]
        self.cfg.save(); self._rebuild_recent_projects()

    def _rebuild_recent_projects(self):
        m=self.recent_projects_menu; m.delete(0,'end')
        items=self.cfg.data.get('recent_projects',[])
        for p in items: m.add_command(label=p,command=lambda q=p: self._open_recent_project(q))
        if not items: m.add_command(label='(none)',state='disabled')

    def _open_recent_project(self,p):
        if not _os.path.exists(p):
            messagebox.showerror('Recent Projects',f'{p} no longer exists; removing it from the list.',parent=self.win)
            self.cfg.data['recent_projects']=[x for x in self.cfg.data.get('recent_projects',[]) if x!=p]
            self.cfg.save(); self._rebuild_recent_projects(); return
        if not self._resolve_3do_changes('opening another project'): return
        self._open_3do_path(p)

    def load_project_dialog(self):
        if not self._resolve_3do_changes('opening another project'): return
        p=filedialog.askopenfilename(parent=self.win,title='Load project (.3dox)',filetypes=[('Projects','*.3dox *.3DOX'),('All files','*')])
        if p: self._open_3do_path(p)

    def save_project_dialog(self):
        v=self.viewer
        if v.model is None:
            messagebox.showinfo('Save project','Open a 3DO model first.',parent=self.win); return
        if not v.path:
            messagebox.showinfo('Save project','Save the 3DO model as a .3do first (Save 3DO model as…), then save the project.',parent=self.win); return
        start=v.project_path or sidecar_path(v.path)
        p=filedialog.asksaveasfilename(parent=self.win,title='Save project (.3dox)',defaultextension='.3dox',
            filetypes=[('Projects','*.3dox'),('All files','*')],initialdir=_os.path.dirname(start),initialfile=_os.path.basename(start))
        if not p: return
        try: v.save_project(p)
        except ThreeDOError as e:
            self._show_3do_error('Save project',e); return
        self._note_recent_project(p)
        self.status.set(f'Saved project {p}')

    _PROJECT_TITLES={'bad_3do':'Model unreadable','bad_3dox':'Project unreadable','ambiguous':'Several matching files',
                     'mismatch':'Project does not match model','unreconcilable':'Project cannot be reconciled with model',
                     'no_3do':'Model not found'}

    def _open_project_file(self,p,model_path=None):
        """Opens a .3do or .3dox. A failure is reported and halts the load; nothing is loaded unless everything checks out.
        A missing model is the one case that offers a way forward: locate it, or cancel."""
        v=self.viewer
        try:
            b=v.open_path(p,model_path=model_path)
        except ProjectError as e:
            if e.kind=='no_3do' and model_path is None:
                if messagebox.askyesno('Model not found',f'{e}\n\nLocate the .3do now? Choose No to cancel the load; nothing was loaded.',parent=self.win):
                    found=filedialog.askopenfilename(parent=self.win,title='Locate the 3DO model',
                        filetypes=[('3DO models','*.3do *.3DO'),('All files','*')])
                    if found: return self._open_project_file(p,model_path=found)
                self.status.set('Load cancelled: the model was not found.'); return
            detail=str(e)
            if e.candidates: detail+='\n\n'+'\n'.join(e.candidates)
            messagebox.showerror(self._PROJECT_TITLES.get(e.kind,'Load failed'),f'{detail}\n\nNothing was loaded. Fix or remove the file and try again, or cancel.',parent=self.win)
            self.status.set(f'Load failed: {e}')
            return
        self._note_recent3(b.model_file)
        if b.project_file: self._note_recent_project(b.project_file)
        if self.layout_var.get()=='code': self.set_layout('both')
        msg=f'3DO model: {b.model_file}'+(f'; project {_os.path.basename(b.project_file)}' if b.project_file else '')
        self.status.set(msg+(f'. {v.sidecar_note}' if v.sidecar_note else ''))

    # ---- animation sequence files and output location ----
    def _anim_refusal(self,err):
        self.viewer.refusal=str(err); self.viewer._refresh_info()

    def load_sequence_dialog(self):
        p=filedialog.askopenfilename(parent=self.win,title='Load sequence file',filetypes=[('Sequence files','*.3dan *.3DAN'),('All files','*')])
        if not p: return
        try:
            nm=self.viewer.seq_load_file(p)
            self.viewer.refusal=f'loaded "{nm}" as a new sequence'
        except ThreeDOError as err: self._anim_refusal(err)
        self.viewer._sync_timeline(); self.viewer._refresh_info()

    def save_sequence_dialog(self):
        name=self.viewer.seqs[self.viewer.seq_i]['name']
        p=filedialog.asksaveasfilename(parent=self.win,title='Save sequence as',defaultextension='.3dan',
                                       initialfile=f'{name}.3dan',filetypes=[('Sequence files','*.3dan'),('All files','*')])
        if not p: return
        try:
            self.viewer.seq_save_file(p); self.viewer.refusal=f'saved "{name}" to {_os.path.basename(p)}'
        except ThreeDOError as err: self._anim_refusal(err)
        self.viewer._refresh_info()

    def output_location_dialog(self):
        cur=self.viewer.anim_output
        p=filedialog.asksaveasfilename(parent=self.win,title='Animation output file (script text)',defaultextension='.bos',
                                       initialfile=_os.path.basename(cur) if cur else 'anim output.bos',
                                       filetypes=[('BOS script','*.bos *.BOS'),('All files','*')])
        if not p: return
        self.viewer.set_output(p); self.viewer.refusal=f'animation output will go to {_os.path.basename(p)}'
        self.viewer._refresh_info()

    def open_test_run(self):
        w=getattr(self,'_test_win',None)
        try:
            if w is not None and w.winfo_exists():
                w.lift(); return w
        except Exception: pass
        self._test_win=TestRunPanel(self.win,self.viewer,self)
        return self._test_win

    def test_source_text(self,key):
        """The BOS text the test-run panel plays for a source: the editor's script, the loaded COB decompiled, or the
        current animation timeline. Raises ThreeDOError with the reason when the source has nothing to play."""
        if key=='editor':
            text=self.editor.get('1.0','end-1c')
            if not text.strip(): raise ThreeDOError('the script editor is empty: open or write a BOS script first')
            return text,'editor script'+(f' ({_os.path.basename(self.path)})' if self.path else '')
        if key=='cob':
            if self.cob_bytes is None: raise ThreeDOError('no COB is loaded: open a .cob file first')
            cache=getattr(self,'_cob_bos',None)
            if cache is None or cache[0] is not self.cob_bytes:
                text,err=run_decompile(self.cob_bytes,bool(self.cfg.data.get('label_functions')))
                if err: raise ThreeDOError(f'the COB could not be decompiled: {err}')
                cache=(self.cob_bytes,text); self._cob_bos=cache
            return cache[1],f'loaded COB ({_os.path.basename(self.cob_path)})' if self.cob_path else 'loaded COB'
        if key=='timeline':
            if self.viewer.model is None: raise ThreeDOError('no model is open: the timeline needs a 3DO model')
            try: text,_rep,_rin,name=self.viewer.clip_bos_text()
            except ThreeDOError: raise
            except Exception as e: raise ThreeDOError(f'the animation timeline could not be read: {e}')
            return text,f'animation timeline ({name})'
        raise ThreeDOError('unknown script source')

    def export_bos_dialog(self):
        if not self.viewer.anim_output: self.output_location_dialog()
        if not self.viewer.anim_output: return
        try: msg=self.viewer.export_bos()
        except Exception as e:
            self._anim_refusal(e); return
        messagebox.showinfo('Animation export',msg,parent=self.win)

    # ---- animation curves (free-floating window) ----
    def open_curve_editor(self):
        w=getattr(self,'_curve_win',None)
        try:
            if w is not None and w.winfo_exists():
                w.lift(); return w
        except tk.TclError: pass
        self._curve_win=CurveEditor(self.win,self.viewer)
        self._curve_win.refresh()
        return self._curve_win

    # ---- docked texture palette ----
    def toggle_tex_panel(self):
        if self.tex_panel_var.get() and self.layout_var.get()=='code': self.set_layout('both')
        else: self.set_layout(self.layout_var.get())

    def set_layout(self,mode):
        """'code': code editor only. 'both': code | 3DO viewport with an adjustable splitter. '3d': viewport only."""
        self.layout_var.set(mode)
        want=[]
        if mode in ('code','both'): want.append(self.nb)
        if mode in ('both','3d'):
            want.append(self.viewer.frame)
            if self.tex_panel_var.get(): want.append(self.tex_panel)
        present=[str(p) for p in self.split.panes()]
        was_both=str(self.nb) in present and str(self.viewer.frame) in present
        for w in (self.nb,self.viewer.frame,self.tex_panel):
            if str(w) in present: self.split.forget(w)
        for w in want: self.split.add(w,minsize=200,stretch='always')
        if mode=='both' and not was_both:
            self.win.after_idle(self._split_default)     # open the splitter near the middle; keep the user's position after that

    def _split_default(self):
        w=self.split.winfo_width()
        if w>400: self.split.sash_place(0,int(w*0.52),0)

    # ---- 3DO file operations ----
    AUTOSAVE_TICK_MS=30000

    def _resolve_3do_changes(self,why):
        """If the open 3DO model has unsaved changes, ask before it is replaced or closed. True = carry on."""
        v=self.viewer
        if v.model is None or not v.dirty: return True
        ans=messagebox.askyesnocancel('Unsaved 3DO model',f'Save changes to the 3DO model before {why}?',parent=self.win)
        if ans is None: return False
        if ans: return self.save_model()
        v.discard_changes_file(); return True

    def _show_3do_error(self,title,e):
        messagebox.showerror(title,str(e),parent=self.win)

    def new_3do(self):
        if not self._resolve_3do_changes('starting a new model'): return
        self.viewer.new_model()
        if self.layout_var.get()=='code': self.set_layout('both')
        self.status.set('New 3DO model (unsaved)')

    def open_3do(self):
        if not self._resolve_3do_changes('opening another model'): return
        p=filedialog.askopenfilename(parent=self.win,title='Open 3DO model',filetypes=[('3DO models','*.3do *.3DO'),('All files','*')])
        if not p: return
        self._open_3do_path(p)

    def _open_3do_path(self,p):
        v=self.viewer
        rec=recovery_for(p) if not p.lower().endswith('.3dox') else None
        if rec:
            name=_os.path.basename(p)
            if messagebox.askyesno('Recover unsaved changes',f'An autosave of {name} is newer than the saved file.\n\nOpen the autosaved version? (Choose No to open the saved file; the autosave is kept until you save.)',parent=self.win):
                err=v.load(p,read_from=rec)
                if err:
                    messagebox.showerror('3DO',f'Could not recover {name}:\n{err}\n\nNothing was loaded.',parent=self.win); return
                v.mark_dirty(); self._note_recent3(p)
                if self.layout_var.get()=='code': self.set_layout('both')
                self.status.set(f'3DO model: {p} (recovered autosave, unsaved)'+(f'. {v.sidecar_note}' if v.sidecar_note else ''))
                return
        self._open_project_file(p)

    def save_model(self,as_new=False):
        """Saves the open 3DO model. Returns True on success (or nothing to save)."""
        v=self.viewer
        if v.model is None: return True
        p=v.path
        if as_new or not p:
            import os as _o
            p=filedialog.asksaveasfilename(parent=self.win,title='Save 3DO model',defaultextension='.3do',
                filetypes=[('3DO models','*.3do'),('All files','*')],initialfile=_o.path.basename(v.path) if v.path else 'model.3do')
            if not p: return False
        n=pending_count([v.model.root]+v.model.extra_roots)
        try:
            warn=v.save(p)
        except ThreeDOError as e:
            self._show_3do_error('Save 3DO model',e); return False
        self._note_recent3(p)
        kept=f'; {n} pending rotation{"s" if n!=1 else ""} kept in {_os.path.basename(v.project_path or "")} (Finalize writes the posed .3do)' if n else ''
        self.status.set(f'Saved {p}'+(f' ({len(warn)} warnings: see the 3D View info line)' if warn else '')+kept)
        return True

    def finalize_3do(self):
        v=self.viewer
        if v.model is None:
            messagebox.showinfo('Finalize','Open a model first.',parent=self.win); return
        if not v.path:
            messagebox.showinfo('Finalize','Save the model first (Save 3DO model as…), then finalize.',parent=self.win); return
        if not messagebox.askyesno('Finalize 3DO model',
                f'Bake every pending rotation into the geometry and write {_os.path.basename(v.path)}?\n\n'
                'Pending rotations are cleared from the project file. The written .3do is the posed model the engine reads.',parent=self.win):
            return
        try:
            err=v.finalize_engine()
        except ThreeDOError as e:
            self._show_3do_error('Finalize',e); return
        self.status.set(f'Finalized {v.path} (grid rounding up to {err:.7f} TA units)' if err else f'Finalized {v.path}')

    def set_origin_dialog(self):
        v=self.viewer
        if v.model is None or v.sel_part is None:
            messagebox.showinfo('Part origin','Select a part in the list first.',parent=self.win); return
        cur=v.origin_of_piece(v.sel_part)
        vals=[]
        for lab,val in zip('XYZ',cur):
            x=simpledialog.askfloat('Part origin',f'{v.sel_part.name or "part"}: origin {lab} (TA units). Geometry and child parts stay in place.',
                initialvalue=round(val,6),parent=self.win)
            if x is None: return
            vals.append(x)
        try:
            v.set_origin_of(v.sel_part,vals)
        except ThreeDOError as e:
            self._show_3do_error('Part origin',e); return
        self.status.set(f'Moved origin of {v.sel_part.name or "part"}')

    def make_top_level(self):
        v=self.viewer
        if v.model is None or v.sel_part is None:
            messagebox.showinfo('Part','Select a part in the list first.',parent=self.win); return
        try:
            v.reparent_piece(v.sel_part,None)
        except ThreeDOError as e:
            self._show_3do_error('Part',e); return
        self.status.set(f'{v.sel_part.name or "part"} is now top level')

    def commit_pending_menu(self,all_parts):
        v=self.viewer
        if v.model is None:
            messagebox.showinfo('Part','Open a model first.',parent=self.win); return
        try:
            err=v.commit_pending(all_parts=all_parts)
        except ThreeDOError as e:
            self._show_3do_error('Part',e); return
        what='all pending rotations' if all_parts else 'the pending rotation of the selected part'
        self.status.set(f'Committed {what} (grid rounding up to {err:.7f} TA units)' if err else f'Nothing to commit for {what}')

    def import_piece_dialog(self,replace):
        v=self.viewer
        if v.model is None:
            messagebox.showinfo('Import','Open or create a 3DO model first.',parent=self.win); return
        if replace and v.sel_part is None:
            messagebox.showinfo('Import','Select the part to replace first.',parent=self.win); return
        p=filedialog.askopenfilename(parent=self.win,title='Import mesh',
            filetypes=[('Meshes','*.obj *.OBJ *.dxf *.DXF *.lwo *.LWO *.lwob *.LWOB'),('All files','*')])
        if not p: return
        from tkinter import simpledialog as _isd
        scale=_isd.askfloat('Import scale','Scale for the imported units (1.0 keeps the file\'s numbers as TA units):',
                            parent=self.win,initialvalue=1.0,minvalue=1e-6)
        if scale is None: return
        colour=_isd.askinteger('Import colour','Palette colour for the new faces (0-255):',parent=self.win,
                               initialvalue=0,minvalue=0,maxvalue=255)
        if colour is None: return
        try:
            v.import_piece(p,replace,scale,colour)
        except OSError as e:
            messagebox.showerror('Import',str(e),parent=self.win)

    def _open_popout(self,attr,cls):
        """One popout per document: a second request lifts the window that is already open."""
        w=getattr(self,attr,None)
        try:
            if w is not None and w.winfo_exists(): w.lift(); return w
        except tk.TclError: pass
        w=cls(self.win,self.viewer); setattr(self,attr,w)
        return w

    def open_transform_palette(self): return self._open_popout('_xf_win',TransformPalette)

    def open_base_plate_panel(self): return self._open_popout('_base_win',BasePlatePanel)

    def create_piece_dialog(self):
        from tkinter import simpledialog as _isd
        name=_isd.askstring('Create piece','Name for the new part:',parent=self.win)
        if name is None: return
        self.viewer.create_piece_here(name)

    def export_3d_dialog(self,scope,fmt):
        v=self.viewer
        if v.model is None:
            messagebox.showinfo('Export','Open or create a 3DO model first.',parent=self.win); return
        if scope=='part' and v.sel_part is None:
            messagebox.showinfo('Export','Select a part in the list first.',parent=self.win); return
        ext={'lwo':'.lwo','dxf':'.dxf','obj':'.obj','3do':'.3do'}[fmt]
        base=(v.sel_part.name if scope=='part' else (_os.path.splitext(_os.path.basename(v.path))[0] if v.path else 'model')) or 'part'
        p=filedialog.asksaveasfilename(parent=self.win,title='Export '+('part' if scope=='part' else 'model'),
            defaultextension=ext,filetypes=[(EXPORT_FORMATS[fmt],'*'+ext),('All files','*')],initialfile=base+ext)
        if not p: return
        try:
            faces,skipped=v.export_3d(scope,fmt,p)
        except ThreeDOError as e:
            self._show_3do_error('Export',e); return
        msg=f'Exported {faces} faces to {p}'
        if skipped: msg+=f'; {skipped} part(s) with no geometry were skipped'
        self.status.set(msg)

    def _note_recent3(self,p):
        p=_os.path.abspath(p)
        lst=self.cfg.data.setdefault('recent_3do',[])
        self.cfg.data['recent_3do']=([p]+[x for x in lst if x!=p])[:MAX_RECENT]
        self.cfg.save(); self._rebuild_recent3()

    def _rebuild_recent3(self):
        m=self.recent3_menu; m.delete(0,'end')
        items=self.cfg.data.get('recent_3do',[])
        for p in items:
            m.add_command(label=p,command=lambda q=p: self._open_recent3(q))
        if not items: m.add_command(label='(none)',state='disabled')

    def _open_recent3(self,p):
        if not _os.path.exists(p):
            messagebox.showerror('Recent 3DO models',f'{p} no longer exists; removing it from the list.',parent=self.win)
            self.cfg.data['recent_3do']=[x for x in self.cfg.data.get('recent_3do',[]) if x!=p]
            self.cfg.save(); self._rebuild_recent3(); return
        if not self._resolve_3do_changes('opening another model'): return
        self._open_3do_path(p)

    def autosave_dialog(self):
        cur=int(self.cfg.data.get('autosave_minutes',5))
        v=simpledialog.askinteger('Autosave','Autosave unsaved 3DO changes every how many minutes? (0 = off)',
            initialvalue=cur,minvalue=0,maxvalue=240,parent=self.win)
        if v is None: return
        self.cfg.data['autosave_minutes']=v; self.cfg.save()
        self.status.set('Autosave off' if v==0 else f'Autosave every {v} min')

    def _start_autosave(self):
        self._autosave_job=self.win.after(self.AUTOSAVE_TICK_MS,self._autosave_tick)

    def _autosave_tick(self):
        try:
            mins=int(self.cfg.data.get('autosave_minutes',5))
            if mins>0 and self.viewer.dirty and _time.time()-self._last_autosave>=mins*60:
                target=self.viewer.autosave_now()
                self._last_autosave=_time.time()
                if target: self.status.set(f'Autosaved to {target}')
        except (ThreeDOError,OSError) as e:
            self.status.set(f'Autosave failed: {e}')
        self._start_autosave()

    def _cancel_autosave(self):
        try: self.win.after_cancel(self._autosave_job)
        except Exception: pass


    def _grid_cell_dialog(self):
        from tkinter import simpledialog
        v=simpledialog.askfloat('Grid cell size','Grid cell size in TA units:',initialvalue=self.viewer.grid_cell(),minvalue=0.1,parent=self.win)
        if v: self.viewer.set_grid_cell(v)

    def _pick_outline_colour(self):
        from tkinter import colorchooser
        _rgb,hexcol=colorchooser.askcolor(color=self.viewer.outline_colour(),parent=self.win,title='Face outline colour')
        if hexcol: self.viewer.set_outline_colour(hexcol)

    def palette_dialog(self):
        p=filedialog.askopenfilename(parent=self.win,title='Palette file (TApalette.dat)',filetypes=[('Palette','*.dat'),('All files','*')])
        if not p: return
        if load_palette(p) is None:
            messagebox.showerror('Palette',f'{p} is not a 768-byte RGB palette.',parent=self.win); return
        self.cfg.data['palette_path']=p; self.cfg.save()
        self.viewer.redraw()
        self.status.set(f'Palette: {p}')

    def _readonly_tab(self,title):
        fr=ttk.Frame(self.nb); self.nb.add(fr,text=title)
        fr.rowconfigure(0,weight=1); fr.columnconfigure(0,weight=1)
        t=tk.Text(fr,wrap='none',font='BostoolCode',state='disabled')
        sb=ttk.Scrollbar(fr,orient='vertical',command=t.yview); hsb=ttk.Scrollbar(fr,orient='horizontal',command=t.xview)
        t.configure(yscrollcommand=sb.set,xscrollcommand=hsb.set)
        t.grid(row=0,column=0,sticky='nsew'); sb.grid(row=0,column=1,sticky='ns'); hsb.grid(row=1,column=0,sticky='ew')
        return t

    def _yview(self,*a):
        self.editor.yview(*a); self.gutter.yview(*a)

    def _set_readonly(self,t,text):
        t.configure(state='normal'); t.delete('1.0','end'); t.insert('1.0',text); t.configure(state='disabled')

    def _update_title(self):
        # the project name when a project is loaded, else the model, else the script; BETA 0.1 after it
        v=self.viewer
        if v.project_path: name=_os.path.splitext(_os.path.basename(v.project_path))[0]
        elif v.path: name=_os.path.basename(v.path)
        elif self.path: name=_os.path.basename(self.path)
        else: name='untitled'
        self.win.title(f'{APP_TITLE} - {name} {APP_VERSION}')

    # ---- editing ----
    def _on_edit(self):
        self._update_gutter(); self._highlight()

    def _update_gutter(self):
        n=int(self.editor.index('end-1c').split('.')[0])
        self.gutter.configure(state='normal'); self.gutter.delete('1.0','end')
        self.gutter.insert('1.0','\n'.join(str(i) for i in range(1,n+1)))
        self.gutter.configure(state='disabled')

    def _highlight(self):
        for k in ('kw','com','dir','num'): self.editor.tag_remove(k,'1.0','end')
        for m in _TOK.finditer(self.editor.get('1.0','end-1c')):
            if m.group(1): tag='com'
            elif m.group(2): tag='dir'
            elif m.group(3):
                if m.group(3).lower() not in BOS_KEYWORDS_LOWER: continue
                tag='kw'
            else: tag='num'
            s,e=m.span(); self.editor.tag_add(tag,f'1.0+{s}c',f'1.0+{e}c')

    def _set_text(self,text,path):
        self.editor.delete('1.0','end'); self.editor.insert('1.0',text); self.editor.edit_reset(); self.editor.edit_modified(False)
        if path is not None:                      # a real source file replaces any COB state
            self.cob_bytes=None; self.cob_path=None; self.decompiled_from=None
        self.path=path; self._update_gutter(); self._highlight(); self._update_title()

    # ---- files ----
    def _is_empty(self):
        return not self.path and self.cob_bytes is None and not self.editor.get('1.0','end-1c').strip()

    def open_dialog(self):
        p=filedialog.askopenfilename(parent=self.win,filetypes=[('BOS / COB / headers','*.bos *.BOS *.h *.H *.cob *.COB'),('All','*')])
        if not p: return
        if self.viewer.model is not None:
            # a model is loaded: settle any unsaved work first, then ask where the script goes
            if not self._unsaved_check('opening another file'): return
            where=self._ask_open_where(p)
            if where=='new': self.app.new_doc(p)
            elif where=='here': self.open_path(p)      # this window, keeping the 3DO model loaded
            return
        if self._is_empty(): self.open_path(p)
        else: self.app.new_doc(p)     # keep this window and its script; the new file gets its own window

    def _unsaved_check(self,why):
        """Asks about unsaved changes to the open script and 3DO model before another file is opened. True = carry on."""
        if self.editor.edit_modified() and not self._is_empty():
            ans=messagebox.askyesnocancel('Unsaved script',f'Save changes to the script before {why}?',parent=self.win)
            if ans is None: return False
            if ans:
                self.save()
                if self.editor.edit_modified(): return False
            else: self.editor.edit_modified(False)
        return self._resolve_3do_changes(why)

    def _ask_open_where(self,p):
        """'new' for a new window, 'here' for this window (the 3DO model stays loaded), or None to cancel."""
        top=tk.Toplevel(self.win); top.title('Open script'); top.transient(self.win); top.resizable(False,False)
        result={'v':None}
        def pick(v): result['v']=v; top.destroy()
        tk.Label(top,text=f'Open {_os.path.basename(p)} where?\n\n'
                          'New window: the script opens in its own window.\n'
                          'This window: the script opens here, and the 3DO model stays loaded.',
                 justify='left').pack(padx=16,pady=(14,8))
        bar=tk.Frame(top); bar.pack(pady=(0,12))
        tk.Button(bar,text='New window',width=14,command=lambda: pick('new')).pack(side='left',padx=4)
        tk.Button(bar,text='This window',width=14,command=lambda: pick('here')).pack(side='left',padx=4)
        tk.Button(bar,text='Cancel',width=10,command=lambda: pick(None)).pack(side='left',padx=4)
        top.protocol('WM_DELETE_WINDOW',lambda: pick(None))
        top.grab_set(); self.win.wait_window(top)
        return result['v']

    def open_path(self,p):
        p=_os.path.abspath(p)
        if p.lower().endswith('.cob'):
            # Never decompile on open: the COB may be suspect. Keep the bytes until the user asks.
            with open(p,'rb') as f: self.cob_bytes=f.read()
            self.cob_path=p
            self.path=None; self._set_text('',None)
            self.status.set(f'{_os.path.basename(p)} loaded as COB ({len(self.cob_bytes)} bytes). Not decompiled: use Build > Decompile COB (manual) to view its source.')
        else:
            with open(p,'rb') as f: text=f.read().decode('latin1')
            self.cob_bytes=None; self._set_text(text,p); self.status.set(f'Opened {p}')
            self.cfg.add_recent(p); self._rebuild_recent_menu()
        self._update_title()

    def _script_clip(self,event):
        """Cut, Copy or Paste in the script window, through the text widget's own clipboard handling."""
        self.editor.focus_set(); self.editor.event_generate(event)

    def decompile(self):
        # Manual only, and separate from loading: the COB has already loaded fine by the time this runs.
        if self.cob_bytes is None:
            messagebox.showinfo('Decompile','Open a COB first.',parent=self.win); return
        self.status.set('Decompiling… (the IDE stays responsive; a bad COB is reported, not fatal)'); self.win.update_idletasks()
        text,err=run_decompile(self.cob_bytes,bool(self.cfg.data.get('label_functions')))
        if err:
            self.status.set(f'Decompile failed: {err}')
            messagebox.showerror('Decompile failed',
                f'The COB could not be decompiled:\n\n{err}\n\n'
                'The COB file itself loaded fine. Nothing in the editor was changed.',parent=self.win)
            return
        self.decompiled_from=self.cob_path
        self._set_text(text,None)
        try: self._fill_assembly(self.cob_bytes)
        except Exception as e: self._set_readonly(self.asm_text,f'Assembly view unavailable: {e}')
        self.status.set('Decompiled. Use Save As to keep the source.')

    def save(self):
        if not self.path: return self.save_as()
        with open(self.path,'wb') as f: f.write(self.editor.get('1.0','end-1c').encode('latin1','replace'))
        self.editor.edit_modified(False); self.status.set(f'Saved {self.path}')
        self.cfg.add_recent(self.path); self._rebuild_recent_menu()

    def save_as(self):
        p=filedialog.asksaveasfilename(parent=self.win,defaultextension='.BOS',filetypes=[('BOS source','*.BOS *.bos'),('All','*')])
        if not p: return
        self.path=_os.path.abspath(p); self.save(); self._update_title()

    def close(self):
        if self.editor.edit_modified():
            ans=messagebox.askyesnocancel('Unsaved changes','Save changes before closing?',parent=self.win)
            if ans is None: return
            if ans: self.save()
        if not self._resolve_3do_changes('closing this window'): return
        self._cancel_autosave()
        self.win.destroy(); self.app.doc_closed(self)

    def _rebuild_recent_menu(self):
        self.recent_menu.delete(0,'end')
        for p in self.cfg.data['recent']:
            self.recent_menu.add_command(label=p,command=lambda q=p: self.app.new_doc(q))
        if not self.cfg.data['recent']: self.recent_menu.add_command(label='(none)',state='disabled')

    # ---- per-file settings ----
    def _settings(self):
        if not self.path: return None
        return self.cfg.source(self.path)

    def out_path(self):
        base=_os.path.splitext(_os.path.basename(self.path))[0]+'.COB'
        s=self._settings()
        d=(s['out_dir'] if s and s['out_dir'] else _os.path.dirname(self.path))
        n=(s['out_name'] if s and s['out_name'] else base)
        return _os.path.join(d,n)

    def output_dialog(self):
        if not self.path:
            messagebox.showinfo('Output','Save the source first.',parent=self.win); return
        s=self._settings(); top=tk.Toplevel(self.win); top.title('Output file for this source'); top.geometry('640x150')
        ttk.Label(top,text='Output folder').grid(row=0,column=0,sticky='w',padx=8,pady=6)
        dv=tk.StringVar(value=(s['out_dir'] or _os.path.dirname(self.path)))
        ttk.Entry(top,textvariable=dv,width=60).grid(row=0,column=1,padx=8)
        ttk.Button(top,text='Browse…',command=lambda: dv.set(filedialog.askdirectory(parent=top) or dv.get())).grid(row=0,column=2,padx=4)
        ttk.Label(top,text='Output filename').grid(row=1,column=0,sticky='w',padx=8)
        nv=tk.StringVar(value=(s['out_name'] or _os.path.splitext(_os.path.basename(self.path))[0]+'.COB'))
        ttk.Entry(top,textvariable=nv,width=60).grid(row=1,column=1,padx=8)
        def ok():
            s['out_dir']=_os.path.abspath(dv.get()); s['out_name']=nv.get().strip() or None
            self.cfg.save(); self.status.set(f'Output: {self.out_path()}'); top.destroy()
        ttk.Button(top,text='OK',command=ok).grid(row=2,column=1,sticky='e',pady=10)

    def incdirs_dialog(self):
        if not self.path:
            messagebox.showinfo('Include folders','Save the source first.',parent=self.win); return
        s=self._settings()
        def changed(items): s['incdirs']=items; self.cfg.save()
        ListDialog(self.win,'Include folders for this file',s['incdirs'],changed)

    def _texture_browser(self):
        tb=getattr(self,'_tb',None)
        if tb is not None and tb.top.winfo_exists():
            tb.top.lift(); tb._update_sel(); return
        self._tb=TextureBrowser(self.win,self.viewer)

    def _add_texture_source(self,folder):
        from tkinter import filedialog
        if folder:
            p=filedialog.askdirectory(parent=self.win,title='Texture folder (contains .gaf files)')
        else:
            p=filedialog.askopenfilename(parent=self.win,title='Texture archive',
                filetypes=[('HPI archives','*.hpi *.ufo *.ccx'),('All files','*.*')])
        if not p: return
        p=_os.path.abspath(p)
        srcs=list(self.cfg.data.get('texture_sources') or [])
        if p not in srcs:
            self.viewer.set_texture_sources(srcs+[p])

    def _texture_sources_dialog(self):
        ListDialog(self.win,'Texture sources (folders of .gaf files, and .hpi archives)',
            list(self.cfg.data.get('texture_sources') or []),self.viewer.set_texture_sources,allow_files=True)

    def global_incdirs_dialog(self):
        def changed(items): self.cfg.data['global_incdirs']=items; self.cfg.save()
        ListDialog(self.win,'Global include folders (all files)',self.cfg.data['global_incdirs'],changed)

    def _toggle_case(self):
        self.cfg.data['case_check']=bool(self.case_var.get()); self.cfg.save()

    def _toggle_dark(self):
        on=bool(self.dark_var.get())
        self.app.set_dark(on)
        self.status.set('Dark mode on' if on else 'Light mode')

    def _ui_size_change(self,delta=0,reset=False):
        cur=int(self.cfg.data.get('ui_size',UI_SIZE_DEFAULT))
        n=apply_ui_size(UI_SIZE_DEFAULT if reset else cur+delta)
        self.cfg.data['ui_size']=n; self.cfg.save()
        self.status.set(f'Text size {n}')

    def _toggle_label(self):
        self.cfg.data['label_functions']=bool(self.label_var.get()); self.cfg.save()

    def _set_scale(self):
        set_linear_scale(int(self.scale_var.get()))
        self.cfg.data['linear_scale']=LINEAR_SCALE; self.cfg.save()
        self.status.set(f'Linear scale set to {LINEAR_SCALE}')

    def _scale_help(self):
        messagebox.showinfo('Linear scale',
            'Script values written as [x] (for example [3.0]) are converted to engine integers by multiplying by a scale.\n\n'
            '65536 (default): 16.16 fixed point. This matches the CORPYRO retail sample and the engine\'s fixed-point convention.\n\n'
            '163840: 2.5 times larger. Some retail-era source sets (the OTA archive, ARMFLASH sample) only compile to their COBs at this value.\n\n'
            'Choose the value your source was written for. It changes every linear value the compiler emits, so a COB built with the other value will move parts by a different distance.',
            parent=self.win)

    def _incdirs(self):
        base=[_os.path.dirname(self.path)] if self.path else [_os.getcwd()]
        s=self._settings()
        return base+(s['incdirs'] if s else [])+self.cfg.data['global_incdirs']

    # ---- build ----
    def _case_clashes(self,out):
        d,n=_os.path.split(out)
        if not _os.path.isdir(d): return []
        return [e for e in _os.listdir(d) if e.lower()==n.lower() and e!=n]

    def compile(self):
        if not self.path:
            self.save_as()
            if not self.path: return
        self.save()
        try:
            text,origin=preprocess_with_map(self.path,self._incdirs())
        except Exception as e:
            self._set_errors([(None,None,str(e))]); self.status.set('Build failed (preprocess)'); return
        self.origin=origin; self._fill_preprocessor(text,origin)
        try:
            out=compile_text(text)
        except Exception as e:
            msg=str(e); ln=None
            m=_re.match(r'line (\d+): (.*)',msg,_re.S)
            if m: ln=int(m.group(1)); msg=m.group(2)
            f,l=(origin[ln-1] if (ln and 0<ln<=len(origin)) else (None,None))
            self._set_errors([(f,l,msg)]); self.status.set('Build failed'); return
        outp=self.out_path()
        clashes=self._case_clashes(outp) if self.cfg.data['case_check'] else []
        if clashes:
            names=', '.join(clashes)
            messagebox.showwarning('Possible case-only filename collision',
                f'{names} differs from {_os.path.basename(outp)} only in letter case.\n'
                'A case-insensitive engine (Windows 95) cannot tell these apart.\n\n'
                'Nothing was deleted. Rename or remove the file(s) yourself.',parent=self.win)
        with open(outp,'wb') as f: f.write(out)
        self._set_errors([]); self._fill_assembly(out)
        self.status.set(f'Compiled -> {outp} ({len(out)} bytes)')

    def _fill_preprocessor(self,text,origin):
        rows=[]
        for i,l in enumerate(text.split('\n'),1):
            f,ln=origin[i-1] if i-1<len(origin) else ('?',0)
            rows.append(f'{i:5d} {_os.path.basename(f)[:20]:<20}{ln:5d} | {l}')
        self._set_readonly(self.pp_text,'\n'.join(rows))

    def _fill_assembly(self,data):
        tmp=tempfile.NamedTemporaryFile(suffix='.cob',delete=False); tmp.write(data); tmp.close()
        try:
            c=read_cob(tmp.name)
            out=[f'pieces: {", ".join(c["pieces"])}   statics: {c["nstatics"]}','']
            for (n,w),st in zip(c['scripts'],c['starts']):
                out.append(f'== {n}  ({len(w)} words)')
                for a,op,im in decode(w,st,c.get('blobs',())):     # same text-block skipping as the decompile
                    out.append(f'  {a:5d}  {_OPNAMES.get(op,hex(op)):<14} {" ".join(str(x) for x in im)}')
                out.append('')
            self._set_readonly(self.asm_text,'\n'.join(out))
        finally:
            _os.remove(tmp.name)

    def _set_errors(self,items):
        self.error_items=items; self.errlist.delete(0,'end')
        for f,l,msg in items:
            self.errlist.insert('end',(f'{_os.path.basename(f)}:{l}  ' if f else '')+msg)
        if not items: self.errlist.insert('end','(no errors)')

    def _jump_error(self):
        sel=self.errlist.curselection()
        if not sel or sel[0]>=len(self.error_items): return
        f,l,_=self.error_items[sel[0]]
        if not f: return
        if self.path is None or _os.path.abspath(f)!=self.path:
            d=self.app.new_doc(_os.path.abspath(f)); d._goto_error(l); return
        self._goto_error(l)

    def _goto_error(self,l):
        self.nb.select(0)
        self.editor.see(f'{l}.0'); self.editor.tag_remove('errline','1.0','end')
        self.editor.tag_add('errline',f'{l}.0',f'{l}.end'); self.editor.mark_set('insert',f'{l}.0')
        self.editor.focus_set()

class App:
    def __init__(self,path=None):
        self.root=tk.Tk(); self.root.withdraw()
        self.cfg=Config(); self.docs=[]
        _sv=self.cfg.data.get('linear_scale',65536)
        set_linear_scale(_sv if _sv in LINEAR_SCALES else 65536)
        apply_ui_size(self.cfg.data.get('ui_size',UI_SIZE_DEFAULT))
        self.new_doc(path)
        theme_set_mode(self.root,bool(self.cfg.data.get('dark_mode',False)))
        for d in self.docs: d.viewer.refresh_theme_edge()

    def set_dark(self,on):
        """Switches every window between light and dark, and remembers the choice."""
        self.cfg.data['dark_mode']=bool(on); self.cfg.save()
        theme_set_mode(self.root,on)
        for d in self.docs: d.viewer.refresh_theme_edge()

    def new_doc(self,path=None):
        if path:
            for d in self.docs:
                if d.path and _os.path.abspath(path)==d.path:
                    d.win.lift(); return d
        d=DocWindow(self,path); self.docs.append(d)
        theme_refresh(self.root)                  # widgets made just now take the current mode
        return d

    def doc_closed(self,d):
        if d in self.docs: self.docs.remove(d)
        if not self.docs: self.root.destroy()

    def run(self):
        self.root.mainloop()

_DISPLAY_HELP=(
    "Advanced Model Factory's window needs an X11 display. Check that DISPLAY is set (echo $DISPLAY should print something like :0). "
    "On Wayland, XWayland provides it; start the program from a terminal inside your desktop session, "
    "or run: DISPLAY=:0 python3 amf.py")
def run_gui(path=None):
    if tk is None: raise SystemExit('tkinter is not installed (Debian: apt install python3-tk)')
    if _sys.platform.startswith('linux') and not _os.environ.get('DISPLAY'):
        raise SystemExit('DISPLAY is not set. '+_DISPLAY_HELP)
    try:
        app=App(path)
    except tk.TclError as e:
        raise SystemExit(f'could not open the window ({e}). '+_DISPLAY_HELP)
    app.run()
