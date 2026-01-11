"""HatchSmith exports PNG color layers and plotter-friendly hatch-filled SVGs (per layer + combined) using real stroke fills; parameters: target size (mm) and pen width (mm). © FIWAtec GmbH"""
import os,sys,subprocess,traceback,re,time,zipfile,colorsys
def ensure_deps():
    missing=[]
    try:
        import PySide6
    except Exception:
        missing.append("PySide6")
    try:
        import PIL
    except Exception:
        missing.append("Pillow")
    try:
        import numpy
    except Exception:
        missing.append("numpy")
    if not missing:
        return
    py=sys.executable
    try:
        subprocess.check_call([py,"-m","pip","install","--upgrade","pip"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    except Exception:
        pass
    subprocess.check_call([py,"-m","pip","install","--upgrade"]+missing)
ensure_deps()
from PySide6.QtCore import Qt,QThread,Signal,QObject,QSettings,QSize,QTimer
from PySide6.QtGui import QAction,QKeySequence,QPixmap,QImage,QPalette,QColor,QFont,QPainter
from PySide6.QtWidgets import QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QPlainTextEdit,QPushButton,QSpinBox,QDoubleSpinBox,QCheckBox,QComboBox,QFileDialog,QMessageBox,QProgressBar,QSplitter,QGroupBox,QGraphicsView,QGraphicsScene,QGraphicsPixmapItem
from PIL import Image
import numpy as np
class Cfg:
    ORG="FIWAtec GmbH"
    APP="HatchSmith"
    DEFAULT_COLORS=16
    DEFAULT_PEN_MM=1.0
    DEFAULT_DRAW_W_MM=1000.0
    DEFAULT_KEEP_ASPECT=True
    DEFAULT_CROSSHATCH=True
    DEFAULT_ANGLE_SET="Auto"
    UI_W=1920
    UI_H=1080
def script_dir():
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except Exception:
        return os.getcwd()
def safe_mkdir(p):
    os.makedirs(p,exist_ok=True)
    return p
def clamp(v,a,b):
    return a if v<a else b if v>b else v
def hex_to_rgb(hx):
    hx=hx.strip().lstrip("#")
    return (int(hx[0:2],16),int(hx[2:4],16),int(hx[4:6],16))
def rgb_to_hex(r,g,b):
    return f"{r:02X}{g:02X}{b:02X}"
def parse_label_list(text):
    lines=[l.strip() for l in text.splitlines() if l.strip()]
    items=[]
    pat=re.compile(r"^\s*(\d{2})\s*-\s*([a-zA-Z0-9_]+)\s*\(#([0-9A-Fa-f]{6})\)\s*Anteil\s*([0-9]+(?:\.[0-9]+)?)%")
    for l in lines:
        m=pat.search(l)
        if not m:
            continue
        prefix,name,hx,share=m.group(1),m.group(2),m.group(3).upper(),float(m.group(4))
        items.append((prefix,name,hx,share))
    return items
def quantize_image_rgb(img_rgb,n_colors):
    q=img_rgb.quantize(colors=n_colors,method=Image.MEDIANCUT)
    q_arr=np.array(q)
    pal=q.getpalette()[:n_colors*3]
    palette=[(pal[i],pal[i+1],pal[i+2]) for i in range(0,len(pal),3)]
    counts=np.bincount(q_arr.flatten(),minlength=n_colors)
    return q,q_arr,palette,counts
def palette_assignment_nearest(palette,desired_hex_list):
    desired_rgbs=[hex_to_rgb(hx) for hx in desired_hex_list]
    n=len(palette)
    dist=np.zeros((n,n),dtype=float)
    for i,(r,g,b) in enumerate(palette):
        for j,(rr,gg,bb) in enumerate(desired_rgbs):
            dist[i,j]=(r-rr)**2+(g-gg)**2+(b-bb)**2
    assigned={}
    used_i=set()
    used_j=set()
    for _ in range(n):
        best_i=-1
        best_j=-1
        best_val=1e18
        for i in range(n):
            if i in used_i:
                continue
            for j in range(n):
                if j in used_j:
                    continue
                v=dist[i,j]
                if v<best_val:
                    best_val=v
                    best_i=i
                    best_j=j
        assigned[best_j]=best_i
        used_i.add(best_i)
        used_j.add(best_j)
    return assigned
def hsv_v(r,g,b):
    rf,gf,bf=r/255.0,g/255.0,b/255.0
    hh,ss,vv=colorsys.rgb_to_hsv(rf,gf,bf)
    return vv,ss,hh
def spacing_mm_from_v(v,pen_mm):
    return float(clamp((0.9+(v**1.2)*3.6)*pen_mm,0.7*pen_mm,6.0*pen_mm))
def runs_from_bool_1d(arr_bool):
    r=arr_bool.astype(np.int16)
    if r.sum()==0:
        return []
    padded=np.pad(r,(1,1),constant_values=0)
    d=np.diff(padded)
    starts=np.where(d==1)[0]
    ends=np.where(d==-1)[0]-1
    if len(starts)==0 or len(ends)==0:
        return []
    m=min(len(starts),len(ends))
    return list(zip(starts[:m],ends[:m]))
def svg_header(width_mm,height_mm):
    return '<?xml version="1.0" encoding="UTF-8"?>\n'+f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_mm:.3f}mm" height="{height_mm:.3f}mm" viewBox="0 0 {width_mm:.3f} {height_mm:.3f}">\n'+'<metadata>HatchSmith © FIWAtec GmbH</metadata>\n'+'<rect x="0" y="0" width="100%" height="100%" fill="white"/>\n'
def svg_footer():
    return "</svg>\n"
def angle_modes_from_choice(choice,v,use_crosshatch):
    if choice=="Horizontal":
        return ["h"]
    if choice=="Vertical":
        return ["v"]
    if choice=="Cross":
        return ["h","v"]
    if choice=="45°":
        return ["d1"]
    if choice=="-45°":
        return ["d2"]
    if choice=="Cross + 45°":
        return ["h","v","d1","d2"]
    if choice=="Auto":
        if not use_crosshatch:
            return ["h"]
        return ["h","v"] if v<0.35 else ["h"]
    return ["h"]
def diag_coords_d1(w,h,idx):
    coords=[]
    x0=max(0,idx-(h-1))
    y0=idx-x0
    x=x0
    y=y0
    while x<w and y>=0:
        coords.append((x,y))
        x+=1
        y-=1
    return coords
def diag_coords_d2(w,h,idx):
    coords=[]
    x0=max(0,idx-(h-1))
    y0=idx-x0-(h-1)
    x=x0
    y=y0
    while x<w and y<h:
        if y>=0:
            coords.append((x,y))
        x+=1
        y+=1
    return coords
def emit_hatch_paths(mask,mm_per_px,step_px,modes):
    w=mask.shape[1]
    h=mask.shape[0]
    out=[]
    paths=0
    if "h" in modes:
        for y in range(0,h,step_px):
            runs=runs_from_bool_1d(mask[y,:])
            if not runs:
                continue
            y_mm=y*mm_per_px
            for x0,x1 in runs:
                out.append(f'<path d="M {x0*mm_per_px:.3f} {y_mm:.3f} L {(x1+1)*mm_per_px:.3f} {y_mm:.3f}"/>\n')
                paths+=1
    if "v" in modes:
        for x in range(0,w,step_px):
            runs=runs_from_bool_1d(mask[:,x])
            if not runs:
                continue
            x_mm=x*mm_per_px
            for y0,y1 in runs:
                out.append(f'<path d="M {x_mm:.3f} {y0*mm_per_px:.3f} L {x_mm:.3f} {(y1+1)*mm_per_px:.3f}"/>\n')
                paths+=1
    if "d1" in modes:
        for idx in range(0,(w+h-1),step_px):
            coords=diag_coords_d1(w,h,idx)
            if not coords:
                continue
            arr=np.array([mask[y,x] for x,y in coords],dtype=bool)
            runs=runs_from_bool_1d(arr)
            if not runs:
                continue
            for a,b in runs:
                x0,y0=coords[a]
                x1,y1=coords[b]
                out.append(f'<path d="M {x0*mm_per_px:.3f} {y0*mm_per_px:.3f} L {(x1+1)*mm_per_px:.3f} {(y1+1)*mm_per_px:.3f}"/>\n')
                paths+=1
    if "d2" in modes:
        for idx in range(0,(w+h-1),step_px):
            coords=diag_coords_d2(w,h,idx)
            if not coords:
                continue
            arr=np.array([mask[y,x] for x,y in coords],dtype=bool)
            runs=runs_from_bool_1d(arr)
            if not runs:
                continue
            for a,b in runs:
                x0,y0=coords[a]
                x1,y1=coords[b]
                out.append(f'<path d="M {x0*mm_per_px:.3f} {y0*mm_per_px:.3f} L {(x1+1)*mm_per_px:.3f} {(y1+1)*mm_per_px:.3f}"/>\n')
                paths+=1
    return out,paths
class ExportJob:
    def __init__(self):
        self.input_png_path=""
        self.output_dir=""
        self.n_colors=Cfg.DEFAULT_COLORS
        self.pen_mm=Cfg.DEFAULT_PEN_MM
        self.draw_w_mm=Cfg.DEFAULT_DRAW_W_MM
        self.draw_h_mm=0.0
        self.keep_aspect=Cfg.DEFAULT_KEEP_ASPECT
        self.use_crosshatch=Cfg.DEFAULT_CROSSHATCH
        self.angle_set=Cfg.DEFAULT_ANGLE_SET
        self.export_png_layers=True
        self.export_svg_layers=True
        self.export_svg_combined=True
        self.labels_text=""
        self.force_user_order=False
class Worker(QObject):
    log=Signal(str)
    progress=Signal(int)
    done=Signal(str)
    failed=Signal(str)
    def __init__(self,job):
        super().__init__()
        self.job=job
        self._stop=False
    def stop(self):
        self._stop=True
    def run(self):
        try:
            self._run_impl()
        except Exception as e:
            self.failed.emit(str(e)+"\n\n"+traceback.format_exc())
    def _run_impl(self):
        j=self.job
        t0=time.time()
        if not j.input_png_path or not os.path.isfile(j.input_png_path):
            raise RuntimeError("Missing input PNG.")
        out=safe_mkdir(j.output_dir)
        self.log.emit("Opened: "+j.input_png_path)
        img_rgb=Image.open(j.input_png_path).convert("RGB")
        w,h=img_rgb.size
        self.log.emit(f"Image size: {w}×{h}px")
        self.progress.emit(5)
        self.log.emit(f"Quantizing to {j.n_colors} colors…")
        q,q_arr,palette,counts=quantize_image_rgb(img_rgb,j.n_colors)
        total=int(counts.sum())
        self.progress.emit(12)
        preview_path=os.path.join(out,"quantized_preview.png")
        q.convert("RGB").save(preview_path)
        self.log.emit("Saved preview: "+preview_path)
        self.progress.emit(16)
        if j.keep_aspect or j.draw_h_mm<=0.0:
            mm_per_px=j.draw_w_mm/float(w)
            draw_h_mm=h*mm_per_px
        else:
            mm_per_px=j.draw_w_mm/float(w)
            draw_h_mm=j.draw_h_mm
        self.log.emit(f"Target size: {j.draw_w_mm:.1f}mm × {draw_h_mm:.1f}mm | Pen: {j.pen_mm:.2f}mm")
        self.progress.emit(20)
        labels=parse_label_list(j.labels_text) if j.labels_text.strip() else []
        have_user_labels=(len(labels)==j.n_colors)
        order=[]
        if have_user_labels and j.force_user_order:
            self.log.emit("Layer naming/order: custom list")
            desired_hex=[hx for _,_,hx,_ in labels]
            assigned=palette_assignment_nearest(palette,desired_hex)
            for idx,(prefix,name,hx,share) in enumerate(labels):
                pidx=assigned[idx]
                order.append((prefix,name,hx,float(share),pidx))
        else:
            self.log.emit("Layer order: automatic (dark → light)")
            meta=[]
            for i,(r,g,b) in enumerate(palette):
                v,_,_=hsv_v(r,g,b)
                meta.append((i,v,int(counts[i])))
            meta_sorted=sorted(meta,key=lambda t:(t[1],-t[2]))
            for k,(i,v,cnt) in enumerate(meta_sorted,start=1):
                prefix=f"{k:02d}"
                hx=rgb_to_hex(*palette[i])
                name=f"layer_{prefix}"
                share=cnt/total*100.0
                order.append((prefix,name,hx,share,i))
        mapping_path=os.path.join(out,"layer_list.txt")
        with open(mapping_path,"w",encoding="utf-8") as f:
            f.write("HatchSmith export list © FIWAtec GmbH\n")
            f.write(f"Source: {os.path.basename(j.input_png_path)}\n")
            f.write(f"PNG: {w}×{h}px\n")
            f.write(f"Target: {j.draw_w_mm:.1f}mm × {draw_h_mm:.1f}mm | Pen {j.pen_mm:.2f}mm\n")
            f.write(f"Colors: {j.n_colors}\n")
            f.write(f"Hatching: {j.angle_set} | Crosshatch: {int(j.use_crosshatch)}\n\n")
            for prefix,name,hx,share,pidx in order:
                f.write(f"{prefix} - {name} (#{hx}) Share {share:.2f}%\n")
        self.log.emit("Saved layer list: "+mapping_path)
        self.progress.emit(26)
        if j.export_png_layers:
            self.log.emit("Exporting PNG layers…")
            layers_dir=safe_mkdir(os.path.join(out,"png_layers"))
            for i,(prefix,name,hx,share,pidx) in enumerate(order):
                if self._stop:
                    raise RuntimeError("Canceled.")
                r,g,b=palette[pidx]
                mask=(q_arr==pidx).astype(np.uint8)*255
                layer=np.zeros((h,w,4),dtype=np.uint8)
                layer[...,0]=r
                layer[...,1]=g
                layer[...,2]=b
                layer[...,3]=mask
                fn=f"{prefix}_{name}_#{hx}.png"
                Image.fromarray(layer).save(os.path.join(layers_dir,fn))
                if (i%2)==0:
                    self.progress.emit(26+int(18*(i+1)/len(order)))
            self.log.emit("PNG layers: "+layers_dir)
        self.progress.emit(45)
        svg_dir=safe_mkdir(os.path.join(out,"svg"))
        combined=[]
        stats=[]
        if j.export_svg_combined:
            combined.append(svg_header(j.draw_w_mm,draw_h_mm))
        for i,(prefix,name,hx,share,pidx) in enumerate(order):
            if self._stop:
                raise RuntimeError("Canceled.")
            r,g,b=palette[pidx]
            v,_,_=hsv_v(r,g,b)
            spacing_mm=spacing_mm_from_v(v,j.pen_mm)
            step_px=max(1,int(round(spacing_mm/mm_per_px)))
            modes=angle_modes_from_choice(j.angle_set,v,j.use_crosshatch)
            mask=(q_arr==pidx)
            group=[]
            group.append(f'<g id="{prefix}_{name}" stroke="#{hx}" stroke-width="{j.pen_mm:.3f}" stroke-linecap="round" stroke-linejoin="round" fill="none">\n')
            paths,pc=emit_hatch_paths(mask,mm_per_px,step_px,modes)
            if pc==0:
                paths,pc=emit_hatch_paths(mask,mm_per_px,1,["h"])
            group.extend(paths)
            group.append("</g>\n")
            if j.export_svg_layers:
                layer_svg=os.path.join(svg_dir,f"{prefix}_{name}_{hx}.svg")
                with open(layer_svg,"w",encoding="utf-8") as f:
                    f.write(svg_header(j.draw_w_mm,draw_h_mm))
                    f.write("".join(group))
                    f.write(svg_footer())
            if j.export_svg_combined:
                combined.append("".join(group))
            stats.append((prefix,name,hx,pc))
            self.progress.emit(45+int(50*(i+1)/len(order)))
        if j.export_svg_combined:
            combined.append(svg_footer())
            combined_path=os.path.join(svg_dir,"combined.svg")
            with open(combined_path,"w",encoding="utf-8") as f:
                f.write("".join(combined))
            self.log.emit("Combined SVG: "+combined_path)
        stats_path=os.path.join(svg_dir,"svg_stats.txt")
        with open(stats_path,"w",encoding="utf-8") as f:
            for prefix,name,hx,pc in stats:
                f.write(f"{prefix}_{name}_{hx}.svg paths={pc}\n")
        self.log.emit("SVG stats: "+stats_path)
        self.progress.emit(97)
        bundle=os.path.join(out,"export.zip")
        self._zip_folder(out,bundle,exclude_names={"export.zip"})
        self.progress.emit(100)
        self.log.emit(f"Done in {time.time()-t0:.2f}s")
        self.done.emit(out)
    def _zip_folder(self,folder,zip_path,exclude_names=None):
        exclude_names=exclude_names or set()
        with zipfile.ZipFile(zip_path,"w",compression=zipfile.ZIP_DEFLATED) as z:
            for root,dirs,files in os.walk(folder):
                for fn in files:
                    if fn in exclude_names:
                        continue
                    fp=os.path.join(root,fn)
                    arc=os.path.relpath(fp,folder)
                    z.write(fp,arcname=arc)
class ZoomView(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.setRenderHints(self.renderHints()|QPainter.Antialiasing|QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._scale=1.0
    def wheelEvent(self,event):
        delta=event.angleDelta().y()
        factor=1.15 if delta>0 else 1/1.15
        self._scale*=factor
        self.scale(factor,factor)
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings=QSettings(Cfg.ORG,Cfg.APP)
        self.worker_thread=None
        self.worker=None
        self.input_path=""
        self.scene=QGraphicsScene()
        self.pixitem=QGraphicsPixmapItem()
        self.scene.addItem(self.pixitem)
        self._build_ui()
        self._apply_dark_theme()
        self._restore_state()
        QTimer.singleShot(50,self._enter_fullscreen_if_needed)
    def _build_ui(self):
        self.setWindowTitle("HatchSmith")
        self.setMinimumSize(QSize(1280,720))
        cw=QWidget()
        self.setCentralWidget(cw)
        root=QVBoxLayout(cw)
        root.setContentsMargins(12,12,12,12)
        root.setSpacing(10)
        top=QHBoxLayout()
        self.lbl_file=QLabel("No file loaded")
        self.lbl_file.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.btn_open=QPushButton("Open PNG…")
        self.btn_open.clicked.connect(self.on_open)
        self.btn_export=QPushButton("Export")
        self.btn_export.clicked.connect(self.on_export)
        self.btn_export.setEnabled(False)
        self.btn_cancel=QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.on_cancel)
        self.btn_cancel.setEnabled(False)
        top.addWidget(self.lbl_file,1)
        top.addWidget(self.btn_open)
        top.addWidget(self.btn_export)
        top.addWidget(self.btn_cancel)
        root.addLayout(top)
        split=QSplitter(Qt.Horizontal)
        root.addWidget(split,1)
        left=QWidget()
        left_l=QVBoxLayout(left)
        left_l.setContentsMargins(0,0,0,0)
        left_l.setSpacing(10)
        preview_box=QGroupBox("Preview")
        pb=QVBoxLayout(preview_box)
        self.view=ZoomView()
        self.view.setScene(self.scene)
        pb.addWidget(self.view)
        left_l.addWidget(preview_box,3)
        log_box=QGroupBox("Activity")
        lb=QVBoxLayout(log_box)
        self.log=QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(4000)
        lb.addWidget(self.log)
        self.progress=QProgressBar()
        self.progress.setRange(0,100)
        self.progress.setValue(0)
        lb.addWidget(self.progress)
        left_l.addWidget(log_box,2)
        split.addWidget(left)
        right=QWidget()
        right_l=QVBoxLayout(right)
        right_l.setContentsMargins(0,0,0,0)
        right_l.setSpacing(10)
        settings_box=QGroupBox("Export Settings")
        form=QFormLayout(settings_box)
        self.sp_colors=QSpinBox()
        self.sp_colors.setRange(2,64)
        self.sp_colors.setValue(int(self.settings.value("n_colors",Cfg.DEFAULT_COLORS)))
        self.sp_pen=QDoubleSpinBox()
        self.sp_pen.setRange(0.1,10.0)
        self.sp_pen.setSingleStep(0.1)
        self.sp_pen.setValue(float(self.settings.value("pen_mm",Cfg.DEFAULT_PEN_MM)))
        self.sp_w=QDoubleSpinBox()
        self.sp_w.setRange(50.0,20000.0)
        self.sp_w.setSingleStep(10.0)
        self.sp_w.setValue(float(self.settings.value("draw_w_mm",Cfg.DEFAULT_DRAW_W_MM)))
        self.sp_h=QDoubleSpinBox()
        self.sp_h.setRange(0.0,20000.0)
        self.sp_h.setSingleStep(10.0)
        self.sp_h.setValue(float(self.settings.value("draw_h_mm",0.0)))
        self.cb_keep=QCheckBox("Keep aspect ratio")
        self.cb_keep.setChecked(bool(int(self.settings.value("keep_aspect","1"))))
        self.cb_cross=QCheckBox("Crosshatch for dark areas")
        self.cb_cross.setChecked(bool(int(self.settings.value("crosshatch","1"))))
        self.cmb_angles=QComboBox()
        self.cmb_angles.addItems(["Auto","Horizontal","Vertical","Cross","45°","-45°","Cross + 45°"])
        self.cmb_angles.setCurrentText(self.settings.value("angle_set",Cfg.DEFAULT_ANGLE_SET))
        self.cb_user=QCheckBox("Use custom label/order list (must match color count)")
        self.cb_user.setChecked(bool(int(self.settings.value("use_user_order","0"))))
        self.cb_png=QCheckBox("Export PNG layers")
        self.cb_png.setChecked(bool(int(self.settings.value("export_png","1"))))
        self.cb_svg=QCheckBox("Export SVG per layer")
        self.cb_svg.setChecked(bool(int(self.settings.value("export_svg_layers","1"))))
        self.cb_comb=QCheckBox("Export combined SVG")
        self.cb_comb.setChecked(bool(int(self.settings.value("export_svg_combined","1"))))
        self.cmb_out=QComboBox()
        self.cmb_out.addItems(["Export to app folder","Choose export folder…"])
        self.cmb_out.setCurrentIndex(int(self.settings.value("export_dir_mode","0")))
        form.addRow("Colors",self.sp_colors)
        form.addRow("Pen width (mm)",self.sp_pen)
        form.addRow("Target width (mm)",self.sp_w)
        form.addRow("Target height (mm)",self.sp_h)
        form.addRow("",self.cb_keep)
        form.addRow("Hatching",self.cmb_angles)
        form.addRow("",self.cb_cross)
        form.addRow("",self.cb_user)
        form.addRow("",self.cb_png)
        form.addRow("",self.cb_svg)
        form.addRow("",self.cb_comb)
        form.addRow("Output",self.cmb_out)
        right_l.addWidget(settings_box)
        labels_box=QGroupBox("Optional: Label/Order List")
        vb=QVBoxLayout(labels_box)
        self.labels=QPlainTextEdit()
        self.labels.setPlaceholderText("Example:\n01 - hell_tuerkis_2 (#93DBE9) Anteil 11.41%\n02 - hell_beige (#F8F8CA) Anteil 9.53%\n…")
        self.labels.setPlainText(self.settings.value("labels_text",""))
        vb.addWidget(self.labels,1)
        right_l.addWidget(labels_box,2)
        note_box=QGroupBox("Notes")
        nb=QVBoxLayout(note_box)
        self.note=QLabel("Plotters follow strokes, not fills. This tool generates hatch strokes to visually fill areas.\nSet the real target size and pen width for correct hatch density.")
        self.note.setWordWrap(True)
        nb.addWidget(self.note)
        right_l.addWidget(note_box)
        split.addWidget(right)
        split.setSizes([720,520])
        self._build_menu()
    def _build_menu(self):
        menubar=self.menuBar()
        m_file=menubar.addMenu("File")
        a_open=QAction("Open…",self)
        a_open.setShortcut(QKeySequence.Open)
        a_open.triggered.connect(self.on_open)
        a_export=QAction("Export…",self)
        a_export.setShortcut(QKeySequence("Ctrl+E"))
        a_export.triggered.connect(self.on_export)
        a_quit=QAction("Quit",self)
        a_quit.setShortcut(QKeySequence.Quit)
        a_quit.triggered.connect(self.close)
        m_file.addAction(a_open)
        m_file.addAction(a_export)
        m_file.addSeparator()
        m_file.addAction(a_quit)
        m_edit=menubar.addMenu("Edit")
        a_copy=QAction("Copy Activity Log",self)
        a_copy.setShortcut(QKeySequence.Copy)
        a_copy.triggered.connect(self.on_copy_log)
        a_clear=QAction("Clear Activity Log",self)
        a_clear.setShortcut(QKeySequence("Ctrl+L"))
        a_clear.triggered.connect(lambda:self.log.setPlainText(""))
        m_edit.addAction(a_copy)
        m_edit.addAction(a_clear)
        m_view=menubar.addMenu("View")
        a_full=QAction("Toggle Fullscreen",self)
        a_full.setShortcut(QKeySequence("F11"))
        a_full.triggered.connect(self.toggle_fullscreen)
        m_view.addAction(a_full)
        m_help=menubar.addMenu("Help")
        a_guide=QAction("Guide",self)
        a_guide.triggered.connect(self.show_guide)
        a_about=QAction("About HatchSmith",self)
        a_about.triggered.connect(self.show_about)
        m_help.addAction(a_guide)
        m_help.addAction(a_about)
    def _apply_dark_theme(self):
        app=QApplication.instance()
        pal=QPalette()
        pal.setColor(QPalette.Window,QColor(18,18,20))
        pal.setColor(QPalette.WindowText,QColor(235,235,240))
        pal.setColor(QPalette.Base,QColor(24,24,28))
        pal.setColor(QPalette.AlternateBase,QColor(30,30,34))
        pal.setColor(QPalette.ToolTipBase,QColor(30,30,34))
        pal.setColor(QPalette.ToolTipText,QColor(240,240,240))
        pal.setColor(QPalette.Text,QColor(235,235,240))
        pal.setColor(QPalette.Button,QColor(30,30,34))
        pal.setColor(QPalette.ButtonText,QColor(235,235,240))
        pal.setColor(QPalette.BrightText,QColor(255,80,80))
        pal.setColor(QPalette.Highlight,QColor(68,132,255))
        pal.setColor(QPalette.HighlightedText,QColor(10,10,10))
        app.setPalette(pal)
        app.setFont(QFont("Segoe UI",10))
        self.setStyleSheet("QGroupBox{border:1px solid rgba(255,255,255,0.08);border-radius:14px;margin-top:8px;padding:10px;}QGroupBox::title{subcontrol-origin: margin;left:10px;padding:0 6px 0 6px;color:rgba(255,255,255,0.75);}QPushButton{border-radius:12px;padding:10px 14px;background:rgba(255,255,255,0.06);}QPushButton:hover{background:rgba(255,255,255,0.10);}QPushButton:pressed{background:rgba(255,255,255,0.14);}QPlainTextEdit{border-radius:12px;padding:10px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);}QProgressBar{border-radius:12px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);text-align:center;}QProgressBar::chunk{border-radius:12px;background:rgba(68,132,255,0.65);}")
        self.menuBar().setStyleSheet("""QMenuBar{background:rgba(18,18,20,1);color:rgba(245,245,248,1);}QMenuBar::item{background:transparent;color:rgba(245,245,248,1);padding:6px 10px;}QMenuBar::item:selected{background:rgba(255,255,255,0.10);border-radius:8px;}QMenu{background:rgba(24,24,28,1);color:rgba(245,245,248,1);border:1px solid rgba(255,255,255,0.10);}QMenu::item{padding:8px 18px;color:rgba(245,245,248,1);}QMenu::item:selected{background:rgba(68,132,255,0.35);border-radius:8px;}""")
    def _restore_state(self):
        self.input_path=self.settings.value("last_png","")
        if self.input_path and os.path.isfile(self.input_path):
            self._load_preview(self.input_path)
            self.lbl_file.setText(self.input_path)
            self.btn_export.setEnabled(True)
    def _save_state(self):
        self.settings.setValue("n_colors",self.sp_colors.value())
        self.settings.setValue("pen_mm",self.sp_pen.value())
        self.settings.setValue("draw_w_mm",self.sp_w.value())
        self.settings.setValue("draw_h_mm",self.sp_h.value())
        self.settings.setValue("keep_aspect","1" if self.cb_keep.isChecked() else "0")
        self.settings.setValue("crosshatch","1" if self.cb_cross.isChecked() else "0")
        self.settings.setValue("angle_set",self.cmb_angles.currentText())
        self.settings.setValue("use_user_order","1" if self.cb_user.isChecked() else "0")
        self.settings.setValue("export_png","1" if self.cb_png.isChecked() else "0")
        self.settings.setValue("export_svg_layers","1" if self.cb_svg.isChecked() else "0")
        self.settings.setValue("export_svg_combined","1" if self.cb_comb.isChecked() else "0")
        self.settings.setValue("export_dir_mode",self.cmb_out.currentIndex())
        self.settings.setValue("labels_text",self.labels.toPlainText())
        self.settings.setValue("fullscreen","1" if self.isFullScreen() else "0")
        if self.input_path:
            self.settings.setValue("last_png",self.input_path)
    def closeEvent(self,event):
        try:
            self._save_state()
        except Exception:
            pass
        super().closeEvent(event)
    def _enter_fullscreen_if_needed(self):
        if int(self.settings.value("fullscreen","1"))==1:
            self.showFullScreen()
        else:
            self.resize(Cfg.UI_W,Cfg.UI_H)
    def _append_log(self,msg):
        ts=time.strftime("%H:%M:%S")
        self.log.appendPlainText(f"[{ts}] {msg}")
    def on_copy_log(self):
        QApplication.clipboard().setText(self.log.toPlainText())
    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.resize(Cfg.UI_W,Cfg.UI_H)
        else:
            self.showFullScreen()
    def show_about(self):
        QMessageBox.information(self,"About HatchSmith","HatchSmith\n© FIWAtec GmbH\n\nPNG layers and hatch-filled SVG exports for pen plotters.\nDesigned for real stroke-based filling.")
    def show_guide(self):
        txt="Guide\n\n1) Open a PNG\n2) Set Colors, Target Size (mm) and Pen Width (mm)\n3) Optional: paste a label/order list and enable it\n4) Export\n\nTip: Target size and pen width directly control hatch density.\n\n© FIWAtec GmbH"
        QMessageBox.information(self,"Guide",txt)
    def on_open(self):
        start=self.settings.value("last_open_dir",script_dir())
        fn,_=QFileDialog.getOpenFileName(self,"Open PNG",start,"PNG (*.png)")
        if not fn:
            return
        self.settings.setValue("last_open_dir",os.path.dirname(fn))
        self.input_path=fn
        self.lbl_file.setText(fn)
        self.btn_export.setEnabled(True)
        self._append_log("Loaded: "+fn)
        self._load_preview(fn)
    def _load_preview(self,fn):
        try:
            img=Image.open(fn).convert("RGBA")
            w,h=img.size
            max_w=1200
            max_h=700
            scale=min(max_w/w,max_h/h,1.0)
            if scale<1.0:
                img=img.resize((int(w*scale),int(h*scale)),Image.LANCZOS)
            data=np.array(img)
            qimg=QImage(data.data,img.size[0],img.size[1],QImage.Format_RGBA8888)
            pix=QPixmap.fromImage(qimg)
            self.pixitem.setPixmap(pix)
            self.scene.setSceneRect(0,0,pix.width(),pix.height())
            self.view.resetTransform()
        except Exception as e:
            self._append_log("Preview failed: "+str(e))
    def on_cancel(self):
        if self.worker:
            self.worker.stop()
            self.btn_cancel.setEnabled(False)
            self._append_log("Cancel requested")
    def choose_output_dir(self):
        if self.cmb_out.currentIndex()==0:
            return safe_mkdir(os.path.join(script_dir(),"exports"))
        d=QFileDialog.getExistingDirectory(self,"Choose export folder",self.settings.value("last_export_dir",script_dir()))
        if not d:
            return ""
        self.settings.setValue("last_export_dir",d)
        return d
    def on_export(self):
        if not self.input_path or not os.path.isfile(self.input_path):
            QMessageBox.warning(self,"Export","Please open a PNG first.")
            return
        out_base=self.choose_output_dir()
        if not out_base:
            return
        stamp=time.strftime("%Y%m%d_%H%M%S")
        out=safe_mkdir(os.path.join(out_base,f"export_{stamp}"))
        job=ExportJob()
        job.input_png_path=self.input_path
        job.output_dir=out
        job.n_colors=int(self.sp_colors.value())
        job.pen_mm=float(self.sp_pen.value())
        job.draw_w_mm=float(self.sp_w.value())
        job.draw_h_mm=float(self.sp_h.value())
        job.keep_aspect=self.cb_keep.isChecked()
        job.use_crosshatch=self.cb_cross.isChecked()
        job.angle_set=self.cmb_angles.currentText()
        job.export_png_layers=self.cb_png.isChecked()
        job.export_svg_layers=self.cb_svg.isChecked()
        job.export_svg_combined=self.cb_comb.isChecked()
        job.labels_text=self.labels.toPlainText()
        job.force_user_order=self.cb_user.isChecked()
        self._save_state()
        self.start_worker(job)
    def start_worker(self,job):
        if self.worker_thread:
            QMessageBox.warning(self,"Export","An export is already running.")
            return
        self.progress.setValue(0)
        self.btn_export.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self._append_log("Export started…")
        self.worker_thread=QThread()
        self.worker=Worker(job)
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.log.connect(self._append_log)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.done.connect(self.on_done)
        self.worker.failed.connect(self.on_failed)
        self.worker.done.connect(self.worker_thread.quit)
        self.worker.failed.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self.cleanup_worker)
        self.worker_thread.start()
    def cleanup_worker(self):
        self.worker_thread=None
        self.worker=None
        self.btn_export.setEnabled(True)
        self.btn_cancel.setEnabled(False)
    def on_done(self,out_dir):
        self._append_log("Export complete: "+out_dir)
        QMessageBox.information(self,"Done","Export complete.\n\n"+out_dir)
    def on_failed(self,err):
        self._append_log("Export failed")
        QMessageBox.critical(self,"Error",err if err else "Export failed.")
def main():
    app=QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName(Cfg.APP)
    app.setOrganizationName(Cfg.ORG)
    w=MainWindow()
    w.show()
    sys.exit(app.exec())
if __name__=="__main__":
    main()
