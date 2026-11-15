# Light and dark themes for the program UI. Light mode is the look the program always had: every colour that dark mode
# changes is recorded from the widget the first time it is changed, and light mode puts those recorded values back.
# Dark mode switches the ttk theme to clam, recolours the classic Tk widgets, sets the option database so widgets made
# later come up dark, and re-colours the code editor's syntax tags. Explicitly coloured canvases that are already dark
# (the timeline, the curve editor) are left alone.
import tkinter as _th
from tkinter import ttk as _thttk

THEME_DARK=dict(bg='#2b2b2b', fg='#e6e6e6', field='#1e1e1e', alt='#353535', muted='#9a9a9a',
          select='#3d6fb5', select_fg='#ffffff', border='#4a4a4a', accent='#c04040',
          tags=dict(kw='#7aa2ff', com='#6aa84f', dir='#ff7b7b', num='#c586ff', origin='#9aa0e0', errline='#6a2a2a'))
# the editor's syntax colours in light mode, and the values dark mode replaces them with
THEME_TAGS_LIGHT=dict(kw='#0000cc', com='#008000', dir='#a00000', num='#7a00a0', origin='#555599', errline='#ffd0d0')

_theme_mode={'dark':False}
_theme_roles={}        # str(widget) -> 'field' | 'alt' | 'canvas': what an explicitly coloured widget is painted as
_theme_orig={}         # (str(widget), option) -> (widget, original value), recorded before dark mode first touches it
_theme_ttk_before={'name':None}

def theme_is_dark(): return _theme_mode['dark']

def theme_track(w,role):
    """Marks an explicitly coloured widget so dark mode paints it with the given role. Returns the widget."""
    _theme_roles[str(w)]=role
    return w

def _theme_widgets(w):
    yield w
    for c in w.winfo_children(): yield from _theme_widgets(c)

def _theme_record(w,opt):
    key=(str(w),opt)
    if key not in _theme_orig:
        _theme_orig[key]=(w,w.cget(opt))
    return _theme_orig[key][1]

def _theme_ttk_apply(root,dark):
    st=_thttk.Style(root)
    # sizes are per theme, so the program's small button style is set again in whichever theme is now active
    try: st.configure('Small.TButton',font=('TkDefaultFont',7),padding=(2,0))
    except _th.TclError: pass
    if dark:
        if _theme_ttk_before['name'] is None: _theme_ttk_before['name']=st.theme_use()
        st.theme_use('clam')
        P=THEME_DARK
        st.configure('.',background=P['bg'],foreground=P['fg'],fieldbackground=P['field'],troughcolor=P['alt'],
                     bordercolor=P['border'],lightcolor=P['alt'],darkcolor=P['bg'],selectbackground=P['select'],
                     selectforeground=P['select_fg'],insertcolor=P['fg'],focuscolor=P['select'],arrowcolor=P['fg'],
                     indicatorbackground=P['field'],indicatorforeground=P['fg'])
        st.map('.',background=[('active',P['alt']),('pressed',P['alt']),('disabled',P['bg'])],
               foreground=[('disabled',P['muted'])],fieldbackground=[('readonly',P['field']),('disabled',P['bg'])],
               selectbackground=[('readonly',P['select'])],selectforeground=[('readonly',P['select_fg'])])
        st.map('TCombobox',fieldbackground=[('readonly',P['field']),('disabled',P['bg'])],
               foreground=[('readonly',P['fg']),('disabled',P['muted'])],
               background=[('active',P['alt']),('pressed',P['alt'])],arrowcolor=[('disabled',P['muted'])],
               selectbackground=[('readonly',P['select'])],selectforeground=[('readonly',P['select_fg'])])
        st.map('TNotebook.Tab',background=[('selected',P['bg']),('active',P['alt'])],
               foreground=[('selected',P['fg']),('!selected',P['muted'])])
        root.option_add('*TCombobox*Listbox.background',P['field'],'userDefault')
        root.option_add('*TCombobox*Listbox.foreground',P['fg'],'userDefault')
        root.option_add('*TCombobox*Listbox.selectBackground',P['select'],'userDefault')
        root.option_add('*TCombobox*Listbox.selectForeground',P['select_fg'],'userDefault')
    else:
        try: st.theme_use(_theme_ttk_before['name'] or 'default')
        except _th.TclError: pass
        root.option_clear()

def _theme_dark_opts(w,cls,role):
    """The options dark mode sets on one classic widget, or None to leave it alone."""
    P=THEME_DARK
    if cls=='Text':
        return {'background':P[role] if role in ('field','alt') else P['field'],'foreground':P['fg'],
                'insertbackground':P['fg'],'selectbackground':P['select'],'selectforeground':P['select_fg']}
    if cls=='Listbox':
        return {'background':P['field'],'foreground':P['fg'],'selectbackground':P['select'],'selectforeground':P['select_fg']}
    if cls=='Canvas':
        return {'background':P[role]} if role in ('field','alt') else None
    if cls=='Menu':
        return {'background':P['bg'],'foreground':P['fg'],'activebackground':P['select'],'activeforeground':P['select_fg']}
    if cls in ('Frame','Labelframe','Toplevel'):
        return {'background':P['bg']}
    if cls in ('Label','Button','Checkbutton','Radiobutton'):
        out={'background':P['bg']}
        if cls=='Label':                      # a label with a deliberately grey hint text stays muted
            orig_fg=str(_theme_record(w,'foreground')).lower()
            out['foreground']=P['fg'] if orig_fg in ('black','#000000','') else P['muted']
        else:                                 # buttons and toggles always get the normal text colour
            out['foreground']=P['fg']
        if cls!='Label':
            out['activebackground']=P['alt']; out['activeforeground']=P['fg']
            if cls in ('Checkbutton','Radiobutton') and str(w.cget('indicatoron')) not in ('0','False'):
                out['selectcolor']=P['field']
        return out
    return None

def _theme_paint(root,dark):
    for w in _theme_widgets(root):
        cls=w.winfo_class(); role=_theme_roles.get(str(w))
        if dark:
            opts=_theme_dark_opts(w,cls,role)
            if not opts: continue
            for opt in opts: _theme_record(w,opt)
            try: w.configure(**opts)
            except _th.TclError: pass
        else:
            for (wp,opt),(ww,val) in list(_theme_orig.items()):
                if wp==str(w):
                    try: ww.configure(**{opt:val})
                    except _th.TclError: pass
    # syntax tags in every text widget that has them
    for w in _theme_widgets(root):
        if w.winfo_class()!='Text': continue
        tags=set(w.tag_names())
        for tag,light in THEME_TAGS_LIGHT.items():
            if tag not in tags: continue
            opt='background' if tag=='errline' else 'foreground'
            try: w.tag_configure(tag,**{opt:(THEME_DARK['tags'][tag] if dark else light)})
            except _th.TclError: pass

def theme_set_mode(root,dark):
    """Switches the whole program between light and dark. Safe to call again; it is idempotent."""
    dark=bool(dark)
    _theme_mode['dark']=dark
    _theme_ttk_apply(root,dark)
    if dark:
        root.option_add('*Background',THEME_DARK['bg'],'userDefault')
        root.option_add('*Foreground',THEME_DARK['fg'],'userDefault')
        root.option_add('*Text.background',THEME_DARK['field'],'userDefault')
        root.option_add('*Listbox.background',THEME_DARK['field'],'userDefault')
        root.option_add('*Entry.background',THEME_DARK['field'],'userDefault')
    else:
        root.option_clear()
    _theme_paint(root,dark)

def theme_refresh(root):
    """Paints widgets created since the last switch with the current mode."""
    if _theme_mode['dark']: _theme_paint(root,True)
