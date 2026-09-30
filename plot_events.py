class PlotEventManager:
    def __init__(self, app):
        self.app = app

    def on_key_press(self, event):
        self.app.current_key = event.key.lower() if event.key else None

    def on_key_release(self, event):
        self.app.current_key = None

    def on_zoom(self, event):
        if event.inaxes != self.app.ax or self.app.is_measuring: return
        
        try: ymax_limit = float(self.app.ent_ymax.get().replace(',', '.'))
        except: ymax_limit = 105
        
        scale = 1/1.2 if event.button == 'up' else 1.2
        scale_x = scale if self.app.current_key == 'x' else (scale if self.app.current_key not in ['x', 'y'] else 1.0)
        scale_y = scale if self.app.current_key == 'y' else (scale if self.app.current_key not in ['x', 'y'] else 1.0)
        
        xd, yd = event.xdata, event.ydata
        xl, yl = self.app.ax.get_xlim(), self.app.ax.get_ylim()
        
        nxw = (xl[1]-xl[0]) * scale_x
        nyh = (yl[1]-yl[0]) * scale_y
        
        if nxw < 0.01: nxw = 0.01
        
        if scale_x != 1.0 or nxw == 0.01:
            nxmin = xd - nxw * (1 - (xl[1]-xd)/(xl[1]-xl[0]))
            nxmax = nxmin + nxw
        else: nxmin, nxmax = xl[0], xl[1]
            
        if scale_y != 1.0:
            nymin = yd - nyh * (1 - (yl[1]-yd)/(yl[1]-yl[0]))
            nymax = nymin + nyh
        else: nymin, nymax = yl[0], yl[1]
        
        if nxmin < 0: nxmax -= nxmin; nxmin = 0
        if nymin < 0: nymax -= nymin; nymin = 0
            
        if nymax > ymax_limit:
            nymin -= (nymax - ymax_limit)
            nymax = ymax_limit
            if nymin < 0: nymin = 0
            
        self.app.ax.set_xlim([nxmin, nxmax])
        self.app.ax.set_ylim([nymin, nymax])
        self.app.canvas.draw_idle()

    def on_press(self, event):
        self.app.canvas.get_tk_widget().focus_set()
        if event.button in [1, 3] and event.inaxes == self.app.ax and not self.app.is_measuring:
            self.app.press = (event.x, event.y, self.app.ax.get_xlim(), self.app.ax.get_ylim())

    def on_release(self, event):
        self.app.press = None
        self.app.canvas.get_tk_widget().config(cursor="arrow")
        if not self.app.is_measuring: self.app.canvas.draw_idle()

    def on_motion(self, event):
        if event.inaxes != self.app.ax or self.app.is_measuring:
            if self.app.annot and self.app.annot.get_visible(): 
                self.app.annot.set_visible(False)
                self.app.canvas.draw_idle()
            return

        try: ymax_limit = float(self.app.ent_ymax.get().replace(',', '.'))
        except: ymax_limit = 105

        if self.app.press and self.app.current_key in ['x', 'y']:
            x0, y0, xl, yl = self.app.press
            dx, dy = (event.x-x0)*(xl[1]-xl[0])/self.app.ax.bbox.width, (event.y-y0)*(yl[1]-yl[0])/self.app.ax.bbox.height
            
            nxmin, nxmax = xl[0]-dx, xl[1]-dx
            nymin, nymax = yl[0]-dy, yl[1]-dy
            
            if nxmin < 0: nxmax -= nxmin; nxmin = 0
            if nymin < 0: nymax -= nymin; nymin = 0
            
            if nymax > ymax_limit:
                nymin -= (nymax - ymax_limit)
                nymax = ymax_limit
                if nymin < 0: nymin = 0
                    
            self.app.ax.set_xlim(nxmin, nxmax)
            self.app.ax.set_ylim(nymin, nymax)
            self.app.canvas.draw_idle()
            return
        
        if self.app.datasets and event.xdata and self.app.annot:
            _, df = self.app.datasets[-1]
            if self.app.smooth_var.get() > 1: df['Druck_mbar'] = df['Druck_mbar'].rolling(window=self.app.smooth_var.get(), center=True).mean()
            row = df.loc[(df['Sekunden'] - event.xdata).abs().idxmin()]
            if abs(row['Sekunden'] - event.xdata) < ((self.app.ax.get_xlim()[1] - self.app.ax.get_xlim()[0]) * 0.05):
                self.app.annot.xy = (row['Sekunden'], row['Druck_mbar'])
                self.app.annot.set_text(f"{row['Sekunden']:.3f} s\n{row['Druck_mbar']:.2f} mbar")
                self.app.annot.set_visible(True)
            else: self.app.annot.set_visible(False)
            self.app.canvas.draw_idle()