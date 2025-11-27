import tkinter as tk
from tkinter import ttk
import os
import tkinter.font
from browser_engine.url import URL
from render_engine.layout import HEIGHT, VSTEP, WIDTH, DisplayItem, DisplayItem, Layout,lex
from .utils import is_emoji
import cProfile
import pstats
import sys

SCROLL_STEP = 100
SCROLLBAR_WIDTH = 10

"""
A browser lays out the page — determines where everything on the page goes—in terms of page coordinates 
and then rasters the page—draws everything—in terms of screen coordinates.
https://browser.engineering/text.html

Ex: python3 -m render_engine.renderer https://browser.engineering/text.html
"""


"""
 # FONT METRICS
 {'ascent': 15, 'descent': 4, 'linespace': 19}
 A point (pt) is a physical unit from print typography.
     * 1 point = 1/72 inch (PostScript standard)
     * So 16 pt = 16/72 inch ≈ 0.222 inch
Typical displays are:
   * 96 DPI

points: 16 pt
16 pt = 16/72 inch = 0.222 inch
screen DPI ≈ 96
pixel_size = 0.222 inch * 96 ≈ 21.3 px

"""



class Renderer:
    def __init__(self, width=WIDTH, height=HEIGHT):
        
        self.display_list: list [DisplayItem]= []
        
        self.width = width
        self.height = height
        self.window = tk.Tk()
        self.window.geometry(f"{self.width}x{self.height}")
        self.canvas = tk.Canvas(self.window, width=self.width, height=self.height)

        self.canvas.pack(fill="both", expand=True)
        self.image_items = []          # track image create ids if needed
        self.scroll = 0
        self.tokens = [] 
        self.images = {}               # map codepoint-> PhotoImage to keep refs

         # Bind the Down arrow key to scrolling
        self.window.bind("<Down>", self.scrolldown)
        self.window.bind("<Up>", self.scrollup)

        # Mouse wheel scrolling (cross-platform)
        self.window.bind("<MouseWheel>", self.on_mousewheel)   # Windows / macOS
        # self.window.bind("<Button-4>", self.on_mousewheel_linux_up)    # Linux scroll up
        # self.window.bind("<Button-5>", self.on_mousewheel_linux_down)  # Linux scroll down

        # Resize support
        self.window.bind("<Configure>", self.on_resize)


    def load(self, url):
        text =url.fetch()
        self.tokens = lex(text)
        # print(f"[renderer] Lexed into {self.tokens} tokens.")
        self.display_list = Layout(self.tokens).layout()
        self.compute_document_height()
        self.draw()
    
    # ------------------------------------------------------------
    #   COMPUTE TOTAL DOCUMENT HEIGHT
    # ------------------------------------------------------------
    def compute_document_height(self):
        if not self.display_list:
            self.doc_height = 0
            return
        last_char = self.display_list[-1]
        self.doc_height = last_char.y + VSTEP



    def draw_scrollbar(self):
        self.clamp_scroll()
        if self.doc_height <= self.height:
            return  # hide scrollbar if everything fits on screen
        visible_ratio = self.height / self.doc_height
        
         # Compute scrollbar position and size
        bar_height = max(20, self.height * visible_ratio)
      


        # Ratio of scroll to total scrollable height(Residuent height)
        scroll_ratio = self.scroll / (self.doc_height - self.height)
        bar_top = scroll_ratio * (self.height - bar_height)
     
        # Draw scrollbar
        x0 = self.width - SCROLLBAR_WIDTH
        y0 = bar_top
        y1 = bar_top + bar_height

        self.canvas.create_rectangle(
            x0, y0, self.width, y1,
            fill="blue", outline="black"
        )


 

   
    
    # -------- emoji loading (simple) ----------
    def _load_emoji_image(self, ch: str):
        """
        Tries to load a PhotoImage for the emoji character ch.
        Looks for files named emoji_<HEX>.png in the same directory as this script.
        Caches PhotoImage objects in self.images to keep them alive.
        """
        code = ord(ch)
        key = f"{code:X}"
        if key in self.images:
            return self.images[key]
        # possible filenames
        candidates = [
            f"emoji_{key}.png",            # emoji_1F600.png
            f"{key}.png",                 # 1F600.png
            f"emoji_u{key}.png",          # emoji_u1F600.png
            f"emoji_{key.lower()}.png",
        ]
        base_dir = os.path.dirname(os.path.abspath(__file__))
        for name in candidates:
            path = os.path.join(base_dir, name)
            if os.path.isfile(path):
                try:
                    img = tk.PhotoImage(file=path)
                    self.images[key] = img
                    return img
                except Exception:
                    continue
        # not found
        return None

    
    # ---------------------------
    #        DRAWING
    # ---------------------------
    def draw(self):
        """ page coordinate y then has screen coordinate y - self.scroll"""
        self.canvas.delete("all")
        self.image_items.clear()
        for display_item in self.display_list:
            
            #skip drawing characters that are offscreen
            if display_item.y > self.scroll + HEIGHT: continue
            if display_item.y + VSTEP < self.scroll: continue
            # if is_emoji(c):
            #     img = self._load_emoji_image(c)
            #     if img is not None:
            #         item = self.canvas.create_image(x, y - self.scroll, image=img, anchor="nw")
            #         self.image_items.append(item)
            #         continue
            # # use anchor "nw" so (x,y) is top-left
            self.canvas.create_text(display_item.x, display_item.y - self.scroll, text=display_item.word, anchor="nw",font=display_item.font)
        self.draw_scrollbar()

    
        
    # ---------------------------
    #  SCROLLING
    # ---------------------------
    def scrolldown(self, event):
        self.scroll += SCROLL_STEP
        self.draw()
    
    def scrollup(self, event):
        self.scroll -= SCROLL_STEP
        self.draw()
    
    # Windows / macOS mouse wheel
    def on_mousewheel(self, event):
        delta = -1 * (event.delta // 120)  # normalize
        self.scroll = max(0, self.scroll + delta * SCROLL_STEP)
        self.draw()


    # ---------------------------
    #  RESIZING
    # ---------------------------
    def on_resize(self, event):
        # Only relayout if size actually changed
        if event.width != self.width :
            self.width = event.width
            self.height = event.height
            self.canvas.config(width=self.width, height=self.height)
            self.display_list = Layout(self.tokens,self.width).layout()
            self.compute_document_height()
            self.draw()
    
    

    def clamp_scroll(self):
       # Prevent scrolling past the content
       self.scroll = max(0, min(self.scroll, self.doc_height - self.height))

    
    def render(self):
        self.window.mainloop()

def main():
   
    renderer = Renderer()
    renderer.load(URL(sys.argv[1]))
    renderer.render()
if __name__ == "__main__":
  
    profiler = cProfile.Profile()
    profiler.runcall(main)
    stats = pstats.Stats(profiler)
    stats.sort_stats("cumulative").print_stats(30)

    