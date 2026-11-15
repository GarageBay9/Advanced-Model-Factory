# Help for Advanced Model Factory: the how-to and reference, the hotkey quick reference, and the About box.
# Text lives here so it can be read and edited apart from the code. Conventions in HELP_TOPICS bodies:
#   a line starting "## " is a subheading; a line starting "- " is a bullet; anything else is a paragraph line.
import tkinter as _htk
from tkinter import font as _hfont

APP_TITLE='Advanced Model Factory'
APP_VERSION='BETA 0.1'

HELP_TOPICS=[
('Getting started',
 'start open load new first run quick tour begin orientation',
 """Advanced Model Factory (AMF) edits Total Annihilation models and scripts in one place. It has two halves that
share a window: a BOS code editor (for the unit scripts, .bos and .cob) and a 3DO viewer (for the 3D models, .3do).
The Animation tools, the Test-run panel and the exporters all work from the model you have open.
## First steps
- File > Open… opens a .bos, .cob or .3do file. File > Open 3DO model… opens a model on its own.
- A project (.3dox) keeps a model together with its sequences, animation and any pending rotations. File > Load project.
- Ctrl+N opens a second window if you want two models or scripts side by side.
- Help > Quick reference lists every hotkey. The window you are reading now is the full how-to.
- The window title shows the loaded project's name (or the open file's name) and the version."""),

('Windows and layout',
 'layout view panes code editor 3d viewport single quad split text size dock palette',
 """Each window holds a code editor and a 3D viewport. View > Code editor only, Code editor + 3DO viewport, and
3DO viewport only switch between them. Alt+W toggles the viewport between quad (four panes) and single.
## Panes
- Each pane has its own view (3D, Top, Bottom, Front, Back, Left, Right), render mode, and background.
  Set them from 3D View > Active pane view / render / background. The active pane has the focus outline.
- Left-click a pane to make it active. Keys and wheel act on the pane under the mouse.
## Text size
- View > Larger text (Ctrl+=), Smaller text (Ctrl+-), and Reset text size. The setting is remembered.
## Dark mode
- View > Dark mode switches the whole program. The choice is remembered between sessions.
## Panels
- Textures > Texture palette docks the texture panel to the right of the viewport.
- Animation > Timeline toolbar shows the timeline along the bottom of the viewport.
- Dragging the sashes between panes resizes them."""),

('Projects, models and saving',
 'save open 3do 3dox project finalize sidecar autosave recovery save as file backup dirty unsaved',
 """A 3DO model is saved as a .3do file. A project (.3dox) is saved next to it and keeps everything that is not
part of the .3do: sequences, keys, the animation output setting, and pending rotations that have not been baked.
## Saving
- Save 3DO model (File menu) writes the .3do. Save 3DO model as… writes a new file.
- Save project (.3dox)… writes the project. It needs the model to be saved as a .3do first.
- A * after the model name in the 3D view means unsaved changes.
## Finalize
- File > Finalize 3DO model (bake poses, write .3do) bakes pending rotations and the animation's rest pose into
  the geometry, then writes the .3do. Use it when the model is finished and you no longer need pending rotations.
## Autosave and recovery
- File > Autosave interval… sets how often a copy is written. If the program closes unexpectedly, the next
  open of that model offers to recover the autosaved copy.
## Recent items
- File > Recent, Recent Projects and Recent 3DO models list what you opened last. (none) means the list is empty."""),

('Viewport: selecting and navigating',
 'select pick click ctrl multi selection camera orbit pan zoom frame wheel middle drag navigation',
 """## Selecting
- Left-click a part (or face) to select it. The selected part is outlined.
- In Animate mode, a click selects the whole part. Ctrl+click adds a part to the selection or removes it.
  The selection is shared by the gizmo, Add Key, and the Del Key controls.
- Clicking empty space clears the selection.
## Camera
- Middle-drag pans the view. Mouse wheel zooms.
- Alt + middle-drag orbits. With Orbit around selection on (3D View menu), the orbit centres on the selected part.
- Z frames the selection. Shift+Z steps back to the previous camera position (up to 200 steps per pane).
- 3D View > Reset active view puts the pane back to its default framing."""),

('Moving and rotating parts',
 'move rotate gizmo tool axes rings pivot origin pending commit bake nest hierarchy parent child top level',
 """Choose the tool with Q (select), W (move) or E (rotate), or from 3D View > Manipulator tool.
## Move (W)
- Drag one of the three coloured axis arrows of the selected part. The part slides along that axis.
- Move: pivot only (3D View > Manipulator tool) moves the origin and leaves the geometry in place.
## Rotate (E)
- Drag one of the three rings. The part turns about that axis.
- A rotation is pending: it shows in the viewport but is not written to the geometry until committed.
- Part > Commit pending rotation of selected part, or Commit all pending rotations, bakes it in.
## Origins and hierarchy
- Part > Set origin of selected part… sets the origin by typing coordinates.
- Parts nest in a tree. Drag a part onto another in the parts list to make it a child. Drop it on empty space to unnest.
- Part > Make selected part top level detaches it from its parent.
- Moving or rotating a parent moves its children with it. A selected child of a selected parent is not moved twice.
- Piece > Transform palette… types exact values and offers spinners for the same moves. See Transform palette."""),

('Piece menu: importing, building and pivots',
 'piece import export obj dxf lwo lwob create duplicate mirror pivot origin match center mesh world highlight move accept cancel',
 """The Piece menu sits just right of 3D View. It works on the selected part; an edit that is refused says why in the info line.
## Importing and exporting
- Piece > Import (new piece)… reads an OBJ, DXF, LWO or LWOB file and adds it as a new part under the selection, or under the
  base part when nothing is selected. Scale sets how the file's numbers become TA units (1.0 keeps them). Colour is the
  palette index given to every face.
- Piece > Import (replace selected piece)… replaces the selected part's geometry. Its name, pivot, children and pending
  rotation stay.
- Piece > Export selected piece as… writes LWO (LightWave, LWOB), DXF, OBJ, or 3DO for the part with its children.
- OBJ and LWO exports hold the part's geometry in world space. Imported back, the mesh is placed relative to the pivot of
  the part it lands under, which need not be the pivot it had before.
## Building parts
- Create piece (no geometry)… adds an empty part under the selection.
- Duplicate selected piece copies the part and its children, placed after the original with unique names.
- Mirror X, Y or Z mirrors the part and its children across the plane through the part's pivot. Faces keep facing outward.
  A part with a pending rotation under it must have that rotation committed first.
## Pivots (Piece > Pivot)
- Highlight pivot draws a cross at the selected part's origin.
- Move pivot… drags the pivot along its axes. Accept this location keeps the new place as one undo step; Cancel puts it back.
  Other edits wait until you accept or cancel.
- Match to other piece… then click the part whose pivot you want. Clicking empty space cancels.
- Center to mesh moves the pivot to the average of the part's vertices. A part with no geometry is refused.
- Center to world moves the pivot to (0, 0, 0)."""),

('Transform palette',
 'transform palette numeric entry value type exact world coordinates offset local spinner spinners jog drag up down rotate degrees move',
 """Piece > Transform palette… opens a popup with a value box for X, Y and Z and a spinner beside each. It follows the Move
(W) and Rotate (E) tools. Every change it makes is one undo step.
## Move
- World coordinates (absolute): the boxes show the selected part's world position. Type the position you want and press
  Apply or Enter. A selection of several parts moves together, by the same amount.
- Offset (local): the boxes are amounts added to the current position, along the part's own axes (its pending rotation
  included). The boxes go back to zero after each apply.
## Rotate
- The boxes are degrees turned about world X, then Y, then Z. Each apply turns the part as a pending rotation, so commit it
  from the Part menu when it is right. The boxes show zero: a rotation is a turn from the current pose.
## Spinners
- A tap on the top arrow steps the value up, and a tap on the bottom arrow steps it down: half a unit in Move, 5 degrees in
  Rotate.
- Press on a spinner and drag vertically. Up increases the value and down decreases it: 0.1 unit (Move) or 1 degree (Rotate)
  per pixel. Releasing the mouse records the whole drag as one undo step.
- Spinners follow the world-or-offset choice: in offset Move they move along the part's own axes.
- The palette is not used in Animate, or while a pivot move is open. Its refusals are shown in its status line."""),

('Base plate tool',
 'base plate ground footprint quad designate designation selection primitive flat quad width depth size dimensions unit terrain slope',
 """Piece > Base plate tool… opens a panel. The base plate is the flat quad that the base part designates as its ground.
Unit models need one; other models do not. The engine uses its four corners as the ground-contact quad when a unit
follows terrain slopes. The 3DO file stores it as the index of a face on the base part; no designation is stored as -1.
## What a base plate is
- A face of the base part with four different corners, all at one height, and a width and a depth above zero.
- It is designated, not drawn differently: the editor shows it like any other face.
## Create base plate
- Type a width (X) and depth (Z), then press Create base plate. The plate is centred on the base part's pivot at height zero
  and becomes the designated plate. A plate designated before stays as ordinary faces.
## Designate an existing quad
- Select the part, then press Designate selected part. On the base part, its one flat quad becomes the plate. The base part
  must have exactly one flat quad (move the others away first, or refusal explains).
- On any other part, the part must hold one flat four-corner face and no children. That face is moved into the base part,
  in the base part's frame, and the part it came from is removed. Undo puts the part back.
## Clear designation and dimensions
- Clear designation stops using the plate. The faces stay in the model.
- Dimensions sets the width and depth of the designated plate. Its centre and height stay where they are.
- A plate whose corners are shared with other faces gets its own corners, so those faces do not change shape."""),

('Faces and textures',
 'texture texture palette browser library hpi gaf palette tapalette render shaded wireframe textured outline face quad spin flip normal rotate three-point highlight',
 """## Face tools (select a face first)
- C spins the internal edge of a quad to the other diagonal.
- V flips the face normal (reverses which side is outside).
- B assigns the texture from the palette to the selected face(s).
- F7 and F8 turn the face's texture back or forward by 90 degrees, as 3DOBuilder does.
- Highlight three-point faces (3D View menu) marks triangles so you can find them.
## Texture palette and browser
- Textures > Texture palette docks the palette beside the viewport. Pick a texture, then use B on faces.
- Textures > Texture browser… lists every texture in the loaded sources with a preview.
## Texture sources
- Textures > Texture libraries > Add folder… adds a folder of .gaf files.
- Add archive (.hpi)… adds a packed archive. Manage sources… lists and removes them.
- Reload from disk re-reads the sources after you change them outside the program.
- Set palette file (TApalette.dat)… chooses the palette the textures are shown with.
## Display
- Render modes: wireframe, shaded, textured. Set per pane.
- Face outline colour… (3D View menu) changes the outline colour. Grid cell size… changes the grid spacing.
## Missing textures
- A texture name that resolves nowhere is shown as a flat colour, the way the game draws it."""),

('Animation: the core ideas',
 'animation animate keys key rest pose playhead sequence clip interpolation smooth linear instant auto key add key',
 """An animation is a sequence (also called a clip) of keys on the parts of a model. A model can hold several
sequences, and one is selected at a time.
## Terms
- Rest pose: the model's pose with no animation. Keys are stored relative to it.
- Playhead: the current frame. The red marker on the timeline.
- Key: a stored rotation or position for one part at one frame. A part can have rotation keys and position keys.
- Interpolation: how the pose moves between two keys. smooth (the default) eases in and out; linear moves at a
  constant rate; instant holds the earlier key until the next one. You set it in the Curve editor.
## Turning it on
- Animate (Animation menu, or the Animate checkbox on the timeline) shows the clip at the playhead.
  While Animate is on the rest pose is fixed. Structural changes and base-pose edits are refused and reported,
  so turn Animate off to change the model's structure.
- Add Key keys the selected parts at the playhead, recording their current pose.
- Auto Key keys the selected parts automatically when a gizmo drag ends. The viewport gets a red edge while it is on.
## Editing keys
- Move the playhead to a frame, pose the part with the gizmo, and Add Key or let Auto Key record it.
- Del Key removes the keys at the playhead for the selected parts. Delete or BackSpace does the same while the
  timeline has focus. With no part selected it removes keys at that frame on every part.
- Each key action is one undo step."""),

('Timeline toolbar',
 'timeline toolbar frame jog arrows start length end loop mode sequence dropdown new rename delete span',
 """The timeline sits along the bottom of the 3D view (Animation > Timeline toolbar).
## Top row
- The timeline. Click or drag to move the playhead. Gold diamonds mark frames with keys on the selected part
  (or on any part when none is selected). Clicking a diamond puts the playhead on it.
- ◀ and ▶ step the playhead one frame back or forward.
- Key adds keys to the selected parts. Auto Key turns automatic keying on. Del Key removes keys at the playhead.
## Second row
- Animate arms the clip. The readout shows the current frame.
- Start and Length set the span of the clip. Press Enter in either box to apply. end shows the last frame.
- The loop box sets how the clip repeats (see the loop section below).
- At the far right: the sequence dropdown, and small New, Rename and Delete buttons.
  Delete needs the name typed out to confirm, because the sequence cannot be recovered.
## Loop
- A clip with a loop mode wraps back to its start. The export reports a loop that does not match its first frame."""),

('Curve editor',
 'curve editor graph curves interpolation ease keys values plot window',
 """Animation > Curve editor window… plots each key's values over time for the selected part.
- Set the interpolation of a key (smooth, linear or instant) from the editor.
- Values can be typed directly; Enter applies them.
- The editor works on the same keys as the timeline, so changes appear in the viewport at once."""),

('Sequence files and animation export',
 'export bos sequence file 3dan output script loop ramps tolerance fidelity read back seam animation save load',
 """## Sequence files (.3dan)
- Animation > Save current sequence as file… saves one sequence so you can reuse it on another model.
- Animation > Load sequence file (.3dan)… adds a saved sequence to this model.
## Exporting to BOS
- Animation > Export animation to BOS (selected sequence)… writes the clip as BOS script text.
- Animation output file… (also in the Animation menu) sets where the script is written. Set it once per model.
- The export writes the script, reads it back to check it, and reports the result: how many seams (joins) do not
  match, the largest error in degrees and units, and how closely the script follows your keys.
- Ramps are on by default. Turn them off in the export dialog for a literal translation of the keys.
- Loop policy: the export reports a clip whose last frame does not match its first. Make the two match before export
  to get a clean loop.
- Angles are written in the engine's units. The tolerance used for the check is half a degree."""),

('Test-run panel',
 'test run panel function play script bos playback signal mask state statics game values sleep wait spin debug',
 """Animation > Test-run panel… plays a BOS function against the model, so you see its motion in the viewports
without loading the game.
## Using it
- Open the panel, pick a function from the list, and press Play. The viewports show the pose at each tick.
- Script chooses where the functions come from:
  - Script in the editor: the BOS text in the script editor, as you write it.
  - Loaded COB: the COB that is open, decompiled to script text.
  - Animation timeline: the selected sequence's keys, written as BOS script text in memory (nothing is saved to disk).
  - Open BOS file… reads any other .bos file.
  The chosen source is read again on every Play, so an edit made in the editor, or a key added on the timeline, is what
  plays next. An empty source, or a timeline with no model open, is reported in the panel's status line.
- Restore base pose returns the model to its base pose after a run. A run never changes the base pose itself.
- Statics (script variables) keep their values between runs of the same script text. A script whose text changes starts with its statics at zero.
- Game values: type values such as HEALTH=100, BUILD_PERCENT_LEFT=0 to answer the script's get queries.
  A query with no value is reported as skipped, not guessed.
## What plays
- Turns, moves, sleeps (including variable sleeps), waits for turns and moves, call-script and start-script,
  while and if, set-signal-mask, and signals.
## What does not
- spin and stop-spin are reported as unplayed. rand(), emit-sfx and other engine calls are skipped.
- Signal masks do not stop threads that are already running in the playback.
- The status line lists what was skipped or unplayed in each run, so you know what the pictures leave out."""),

('BOS script editor',
 'bos editor code script compile decompile cob bos syntax errors preprocessor assembly include output file headers scale',
 """Open a .bos script to edit it. Open a .cob to decompile it into readable BOS.
## Editing
- Syntax colours mark keywords, comments, directives and numbers. Errors are underlined in the error list at the bottom.
- Double-click an error to jump to its line.
- Edit menu: Cut, Copy and Paste (script) use Ctrl+X, Ctrl+C and Ctrl+V. Ctrl+Z and Ctrl+Y undo text while the editor has focus.
- Ctrl+S saves. Ctrl+O opens. Autosave keeps a copy as you work.
## Compiling
- Build > Compile (F5 or Ctrl+B) compiles the script to a .cob. The Preprocessor and Assembly tabs show the
  intermediate results (read-only).
- Build > Output file… chooses where the .cob goes. Include folders for this file… and Global include folders…
  tell the compiler where to find headers.
- Check for case-only filename collisions warns when two names differ only in case.
## Decompiling
- A .cob opens decompiled automatically. Build > Decompile COB (manual) does it on demand.
- Label variables by function when decompiling gives variables names that show which function uses them.
## Linear scale
- Build > Linear scale sets the value scale for linear moves (65536 is the default). About the linear scale… explains it.
  Use the scale the game build you are targeting uses."""),

('Exporting models',
 'export obj lwo dxf 3do wavefront lightwave autocad part model mesh file',
 """File > Export offers the whole model or the selected part, in these formats:
- LightWave (LWOB)
- DXF
- Wavefront OBJ
- 3DO (selected part and its children only)
Export writes a copy. It does not change the open model."""),

('Undo and history',
 'undo redo history ctrl z ctrl y edit view shift z model edit steps limit gesture',
 """## Model edits
- Ctrl+Z and Ctrl+Y undo and redo while the 3D viewport has focus. Edit > Undo model edit and Redo model edit do the same.
- One drag, one key action, or one menu command is one step. A move with Auto Key on is one step: undoing it
  removes the key, and that also returns the part, because the key is what holds the move.
- Undo brings back the selection that was active before the change, including a multi-part Animate selection.
- Up to 200 steps are kept.
- Undo does not cover the Test-run panel's playback, which is always run from a clean copy.
## View changes
- Shift+Z steps the camera back to the previous view, separately for each pane.
## Script edits
- Use Ctrl+Z and Ctrl+Y inside the code editor for text edits."""),

('Settings',
 'settings preferences config autosave dark mode text size layout remember',
 """Settings are saved in your home folder (.amf_config.json).
- View > Dark mode, View > text size, and the layout choice.
- File > Autosave interval…
- Build > Include folders and Linear scale.
- 3D View > Orbit around selection, and Face outline colour."""),

('Troubleshooting and known limits',
 'troubleshoot problem error help limits known missing not supported spin rand emit sfx display x11 linux',
 """## Common problems
- The program will not start on Linux: it needs a display. Check that DISPLAY is set, or start it from a terminal
  inside your desktop session.
- A model moved or changed unexpectedly while Animate was on: Animate fixes the rest pose. Turn Animate off to edit
  the structure or the base pose. The program reports refused edits in the status line.
- The viewport looks different from the game: check the render mode, the texture palette, and the Linear scale setting.
- A script will not compile: read the first error in the list, then the Preprocessor tab for the line it points to.
## Known limits
- The Test-run panel does not play spin, stop-spin, rand(), or emit-sfx. Signal masks do not stop running threads.
- The 3D background stays light in dark mode. It is set per pane.
- On very narrow windows the second row of the timeline can be clipped. Widen the window to see every control.
- Very large models redraw more slowly; no timing has been measured on large models.
- A designated base plate keeps its corner order. The engine's slope tilt depends on that order, so check a unit with a new
  plate in game before you rely on it.
- Imported meshes take one palette colour for every face. There is no material mapping."""),

('Glossary',
 'glossary terms 3do bos cob 3dox 3dan gaf hpi palette piece static var signal pend offset rest pose',
 """- 3DO: the model file format. Holds the part tree, the geometry and the texture names.
- BOS: the readable script language for units.
- COB: the compiled script the game runs.
- 3DOX (project): a model with its sequences, keys and pending rotations.
- 3DAN (sequence file): one saved animation sequence.
- GAF and HPI: texture and archive formats. Sources are added under Textures > Texture libraries.
- Piece: one part of a model.
- Pivot: a part's origin. Its children are placed from it, and rotations turn about it.
- Base part: the root part of a unit model. Its base plate sets the ground contact.
- Base plate: the flat quad the base part designates as its ground (see Base plate tool).
- Static var: a variable that keeps its value between calls in a script.
- Signal: a flag a script sends to stop or resume other threads.
- Pending rotation: a rotation shown in the viewport that is not yet baked into the geometry.
- Rest pose: the pose with no animation applied.
"""),
]

HELP_KEYS=[
('Files and windows', [
 ('Ctrl+N', 'New window'),
 ('Ctrl+O', 'Open a file'),
 ('Ctrl+S', 'Save the open script'),
 ('Ctrl+B  or  F5', 'Compile the script'),
 ('Ctrl+=  /  Ctrl+-', 'Larger / smaller text'),
 ('Alt+W', 'Quad / single view in the 3D viewport'),
]),
('Editing', [
 ('Ctrl+X / Ctrl+C / Ctrl+V', 'Cut, copy, paste in the script editor'),
 ('Ctrl+Z / Ctrl+Y', 'Undo / redo (in the code editor, text; in the 3D viewport, model edits)'),
]),
('Manipulator tool (3D viewport, hover over it first)', [
 ('Q', 'Select tool'),
 ('W', 'Move tool (drag an axis arrow)'),
 ('E', 'Rotate tool (drag a ring)'),
]),
('View and camera', [
 ('Z', 'Frame the selection'),
 ('Shift+Z', 'Previous camera view (per pane)'),
 ('Middle-drag', 'Pan'),
 ('Alt + middle-drag', 'Orbit (about the selection when Orbit around selection is on)'),
 ('Mouse wheel', 'Zoom'),
]),
('Faces and textures (select a face first)', [
 ('C', 'Spin the quad edge'),
 ('V', 'Flip the face normal'),
 ('B', 'Assign the palette texture to the face'),
 ('F7 / F8', 'Turn the texture back / forward 90 degrees'),
]),
('Animation and timeline', [
 ('Delete or BackSpace (timeline focused)', 'Delete keys at the playhead for the selected parts'),
 ('Click the timeline', 'Move the playhead'),
 ('Click a gold diamond', 'Move the playhead onto that key'),
 ('◀ / ▶ buttons', 'Step the playhead one frame'),
 ('Enter in Start or Length', 'Apply the span'),
]),
('Mouse selection', [
 ('Left-click', 'Select a part (in Animate mode, the whole part) or a face'),
 ('Ctrl + left-click (Animate)', 'Add the part to the selection, or remove it'),
 ('Left-click empty space', 'Clear the selection'),
 ('Double-click an error (editor)', 'Jump to that line'),
]),
]

HELP_ABOUT=('By RavenFire & Claude... let\'s be honest, mostly Claude.\n\n'
            'With thanks to Kinboat, Immerman, Rhadamanthus, and every other community member who made tools for '
            'Total Annihilation in its heyday and paved the way.\n\n'
            'BETA 0.1 NOV 11 2026')

def _help_bold_font(base='TkDefaultFont',size_delta=0):
    f=_hfont.nametofont(base).copy()
    f.configure(weight='bold',size=f.cget('size')+size_delta)
    return f

def _help_text_widget(parent):
    frame=_htk.Frame(parent)
    txt=_htk.Text(frame,wrap='word',padx=12,pady=8,relief='flat',borderwidth=0,highlightthickness=0)
    sb=_htk.Scrollbar(frame,orient='vertical',command=txt.yview)
    txt.configure(yscrollcommand=sb.set)
    sb.pack(side='right',fill='y'); txt.pack(side='left',fill='both',expand=True)
    theme_track(txt,'field')                   # dark mode recolours this text area
    return frame,txt

def show_help_how(parent):
    """The how-to and reference: topics on the left, a keyword filter, and a find box for the text."""
    top=_htk.Toplevel(parent); top.title(f'{APP_TITLE}: how-to and reference'); top.geometry('1000x660')
    top.transient(parent)
    paned=_htk.PanedWindow(top,orient='horizontal',sashwidth=6); paned.pack(fill='both',expand=True)
    left=_htk.Frame(paned); paned.add(left,minsize=200,width=250)
    _htk.Label(left,text='Topics (filter by keyword):',anchor='w').pack(fill='x',padx=6,pady=(6,0))
    filt=_htk.Entry(left); filt.pack(fill='x',padx=6,pady=(2,4))
    lb=_htk.Listbox(left,exportselection=False); lb.pack(fill='both',expand=True,padx=6,pady=(0,6))
    right=_htk.Frame(paned); paned.add(right,stretch='always')
    bar=_htk.Frame(right); bar.pack(fill='x',padx=6,pady=(6,0))
    _htk.Label(bar,text='Find in text (Enter for next):').pack(side='left')
    find=_htk.Entry(bar); find.pack(side='left',fill='x',expand=True,padx=6)
    body,txt=_help_text_widget(right); body.pack(fill='both',expand=True,padx=6,pady=6)
    h1=_help_bold_font(size_delta=4); h2=_help_bold_font(size_delta=1)
    txt.tag_configure('h1',font=h1,spacing1=14,spacing3=2)
    txt.tag_configure('kw',foreground='#666666',spacing3=6)
    txt.tag_configure('h2',font=h2,spacing1=8)
    txt.tag_configure('bullet',lmargin1=18,lmargin2=30)
    txt.tag_configure('found',background='#ffe680')
    # build the text, remembering where each topic starts
    for i,(title,kws,body_text) in enumerate(HELP_TOPICS):
        txt.insert('end',title+'\n','h1')
        txt.insert('end','Keywords: '+kws+'\n','kw')
        txt.mark_set(f'topic{i}',txt.index('end-1c'))
        txt.mark_gravity(f'topic{i}','left')
        for line in body_text.split('\n'):
            if line.startswith('## '): txt.insert('end',line[3:]+'\n','h2')
            elif line.startswith('- '): txt.insert('end','•  '+line[2:]+'\n','bullet')
            else: txt.insert('end',line+'\n')
        txt.insert('end','\n')
    txt.configure(state='disabled')
    shown=[]
    def fill_list(*_):
        q=filt.get().strip().lower()
        lb.delete(0,'end'); shown.clear()
        for i,(title,kws,_b) in enumerate(HELP_TOPICS):
            if not q or q in title.lower() or q in kws.lower():
                shown.append(i); lb.insert('end',title)
    def jump(_e=None):
        sel=lb.curselection()
        if not sel: return
        i=shown[sel[0]]
        txt.yview(f'topic{i}')
    def find_next(_e=None):
        q=find.get()
        if not q: return
        txt.tag_remove('found','1.0','end')
        start=txt.index('insert +1c') if txt.tag_ranges('found') or True else '1.0'
        pos=txt.search(q,start,nocase=True,stopindex='end') or txt.search(q,'1.0',nocase=True,stopindex='end')
        if not pos: return
        end=f'{pos}+{len(q)}c'
        txt.tag_add('found',pos,end); txt.mark_set('insert',pos); txt.see(pos)
    filt.bind('<KeyRelease>',fill_list); lb.bind('<<ListboxSelect>>',jump)
    find.bind('<Return>',find_next)
    fill_list()
    if lb.size(): lb.selection_set(0); jump()
    top.bind('<Escape>',lambda e: top.destroy())
    theme_refresh(top._root())                 # paint the new window with the current light or dark mode
    return top

def show_help_keys(parent):
    """The quick reference: every hotkey and navigation combination, grouped by where it works."""
    top=_htk.Toplevel(parent); top.title(f'{APP_TITLE}: quick reference'); top.geometry('640x560'); top.transient(parent)
    body,txt=_help_text_widget(top); body.pack(fill='both',expand=True)
    h1=_help_bold_font(size_delta=3)
    txt.tag_configure('h1',font=h1,spacing1=10,spacing3=2)
    txt.tag_configure('row',lmargin1=16,lmargin2=16,tabs=('250p',))
    txt.insert('end','Quick reference: hotkeys and navigation\n','h1')
    txt.insert('end','Keys act when the window or pane they belong to has the focus. Hover over the 3D viewport before using its keys.\n\n')
    for group,rows in HELP_KEYS:
        txt.insert('end',group+'\n','h1')
        for keys,what in rows:
            txt.insert('end',keys+'\t'+what+'\n','row')
        txt.insert('end','\n')
    txt.configure(state='disabled')
    top.bind('<Escape>',lambda e: top.destroy())
    theme_refresh(top._root())
    return top

def show_help_about(parent):
    top=_htk.Toplevel(parent); top.title(f'About {APP_TITLE}'); top.resizable(False,False); top.transient(parent)
    _htk.Label(top,text=APP_TITLE,font=_help_bold_font(size_delta=6)).pack(padx=24,pady=(20,4))
    _htk.Label(top,text=APP_VERSION,font=_help_bold_font()).pack(padx=24)
    _htk.Label(top,text=HELP_ABOUT,wraplength=420,justify='center').pack(padx=24,pady=(12,4))
    _htk.Button(top,text='Close',width=10,command=top.destroy).pack(pady=(10,18))
    top.bind('<Escape>',lambda e: top.destroy())
    theme_refresh(top._root())
    return top
