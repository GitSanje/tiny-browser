import tkinter as tk
from tkinter import ttk
import os
import tkinter.font
from browser_engine.tiny_browser import URL
from .utils import is_emoji
from dataclasses import dataclass

WIDTH, HEIGHT = 800, 600
SCROLL_STEP = 100
HSTEP = 10 
VSTEP = 20 
SCROLLBAR_WIDTH = 10

"""
A browser lays out the page — determines where everything on the page goes—in terms of page coordinates 
and then rasters the page—draws everything—in terms of screen coordinates.
https://browser.engineering/examples/xiyouji.html
Ex: python3 -m render_engine.renderer https://browser.engineering/examples/xiyouji.html
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


@dataclass
class Text:
    text: str

@dataclass
class Tag:
    tag: str

def lex(body):
    """
    Very simple lexer that splits text into Text and Tag tokens.
    1. Text outside <...> is Text
    2. Text inside <...> is Tag
    Ex: "Hello <b>world</b>" -> [Text("Hello "), Tag("b"), Text("world"), Tag("/b")]
    """
    out = []
    buffer = ""
    in_tag = False
    for c in body:
        if c == "<":
            in_tag = True
            if buffer: out.append(Text(buffer))
            buffer = ""
        elif c == ">":
            in_tag = False
            if buffer:
                out.append(Tag(buffer))
            buffer = ""
        else:
            buffer += c
    if not in_tag and buffer:
        out.append(Text(buffer))
    return out
        



class Renderer:
    def __init__(self, width=WIDTH, height=HEIGHT):
        self.width = width
        self.height = height
        self.window = tk.Tk()
        self.window.geometry(f"{self.width}x{self.height}")
        self.canvas = tk.Canvas(self.window, width=self.width, height=self.height)

        self.canvas.pack(fill="both", expand=True)
        self.image_items = []          # track image create ids if needed
        self.display_list = []     # list[(char,x,y)]
        self.scroll = 0
        self.text = "" 
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
        self.text = url.fetch()
        self.display_list = self.layout()
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
        _, _, last_y = last_char
        self.doc_height = last_y + VSTEP



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
        # print(f"Scrollbar: doc_height={self.doc_height}, height={self.height}, scroll={self.scroll}, bar_top={bar_top}, bar_height={bar_height}, scroll_ratio={scroll_ratio}")

         # Draw scrollbar
        x0 = self.width - SCROLLBAR_WIDTH
        y0 = bar_top
        y1 = bar_top + bar_height

        self.canvas.create_rectangle(
            x0, y0, self.width, y1,
            fill="blue", outline="black"
        )


 

    def layout(self,WIDTH=WIDTH):
        """ Simple layout algorithm that creates a display list with positions for each character. (page coordinates)"""
        display_list = []
        cursor_x, cursor_y = HSTEP, VSTEP
        font = tkinter.font.Font()
       
        for word in self.text.split():
            w = font.measure(word)
            if cursor_x + w > WIDTH - HSTEP:
                cursor_y += font.metrics("linespace") * 1.25
                cursor_x = HSTEP
            display_list.append((word, cursor_x, cursor_y))
            cursor_x += w + font.measure(" ")
        return display_list
    
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
        for w, x, y in self.display_list:
            
            #skip drawing characters that are offscreen
            if y > self.scroll + HEIGHT: continue
            if y + VSTEP < self.scroll: continue
            # if is_emoji(c):
            #     img = self._load_emoji_image(c)
            #     if img is not None:
            #         item = self.canvas.create_image(x, y - self.scroll, image=img, anchor="nw")
            #         self.image_items.append(item)
            #         continue
            # # use anchor "nw" so (x,y) is top-left
            self.canvas.create_text(x, y - self.scroll, text=w, anchor="nw")
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
            self.display_list = self.layout(self.width)
            self.compute_document_height()
            self.draw()
    
    

    def clamp_scroll(self):
       # Prevent scrolling past the content
       self.scroll = max(0, min(self.scroll, self.doc_height - self.height))

    
    def render(self):
        self.window.mainloop()

if __name__ == "__main__":
    import sys
    renderer = Renderer()
    renderer.load(URL(sys.argv[1]))
    renderer.render()