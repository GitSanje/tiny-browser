
from dataclasses import dataclass
import tkinter.font
from .utils import decode_entities

HSTEP = 10 
VSTEP = 20 
WIDTH, HEIGHT = 800, 600


class Text:

    def __init__(self, text,parent):
        self.text= text
        self.parent = parent
        self.children = []
    
class Element:
    def __init__(self, tag, parent):
        self.tag = tag
        self.children = []
        self.parent = parent


class HTMLParser:
    def __init__(self, body):
        self.body = body
        self.unfinished_tags: list[Element] = []
        self.finished_tags = []

    def parse(self):
        in_tag = False
        out_tag= False
        buffer = ""
        i = 0 
        while i < len(self.body):
    
            if self.body[i] == "<":
                if buffer:
                        tag=  self.unfinished_tags[-1] if self.unfinished_tags else None
                        text = Text(text=buffer,parent=tag)
                        if tag is not None:
                            tag.children.append(text)
                if self.body[i]+ self.body[i+1] == "</":
                    out_tag = True
                    buffer =""
                    i += 2
                    
                else:
                    in_tag= True
                    buffer =""
                    i += 1
            elif self.body[i] == ">" and in_tag:
                in_tag =False
                if buffer:
                    tag=  self.unfinished_tags[-1] if self.unfinished_tags else None

                    element = Element(tag=buffer,parent=tag)
                    if tag is not None:
                        
                        tag.children.append(element)
                    self.unfinished_tags.append(element)
                   
                    print("appened element on unfinished_tags: ", element.tag,  element.parent.tag if element.parent else None)
                i += 1
                buffer =""
           
            
            elif self.body[i] == ">" and out_tag:
                out_tag =False
                finishedTag = [ tag for tag in self.unfinished_tags if tag.tag == buffer][0]
                for children in finishedTag.children:
                    print(f"parent: {buffer} => children :{children.tag if isinstance(children,Element) else children.text}")
                self.unfinished_tags = [
                        tag for tag in self.unfinished_tags if tag.tag != buffer
                    ]

                if buffer:
                    self.finished_tags.append(finishedTag)
                buffer = ""
                print("appened element on finished_tags: ", finishedTag.tag)
                i += 1
            else:
                 buffer += self.body[i]
                 i += 1
        for tag in self.finished_tags:
            print(f"Tag : {tag.tag}")
               

if __name__ == "__main__": 
    ex1 = """
    <html><video></video><section> what's up <h1>This is my webpage </h1></section></html>
    """

    parser = HTMLParser(body=ex1)
    parser.parse()





    
       


@dataclass
class Tag:
    tag: str
    attrs: dict = None

@dataclass
class DisplayItem:
    x: int
    y: int
    word: str
    font: "tkinter.font.Font"

def lex(body):
    """
    Very simple lexer that splits text into Text and Tag tokens.
    1. Text outside <...> is Text
    2. Text inside <...> is Tag
    Ex: "Hello <b>world</b>" -> [Text("Hello "), Tag("b"), Text("world"), Tag("/b")]
    """ 
    body = decode_entities(body)
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
     
FONTS = {}


def get_font(size, weight, style):
    key = (size, weight, style)

    # If not already cached, create and store it
    if key not in FONTS:
        font = tkinter.font.Font(size=size, weight=weight, slant=style)
        # Label required for proper metrics on some systems
        label = tkinter.Label(font=font)
        FONTS[key] = (font, label)

    return FONTS[key][0]

class Layout:
  
    def __init__(self, tokens,width=WIDTH):
        self.display_list: list [DisplayItem]= []
        self.tokens = tokens
        self.cursor_x = HSTEP
        self.cursor_y = VSTEP
        self.width = width
        self.weight = "normal"
        self.style = "roman"
        self.size = 12
        self.line = []   # buffer for (x, word, font)
        self.superscript = False
        self.centering = False

        self.flush()

    def flush(self):
        """
        line height = ascent + descent + leading
        Where:
            ascent = height above baseline
            descent = height below baseline
            leading = extra spacing added above + below the text together
        leading = 25% of ascent 
            +12.5% above
            +12.5% below

        1. it align the words along the baseline ;
        2. it  add all those words to the display list; and
        3. it  update the cursor_x and cursor_y fields.

        """
        if not self.line: return
        metrics = [ font.metrics() for x, word, font in self.line]
      
        max_ascent = max(m['ascent'] for m in metrics)
        max_descent = max(m['descent'] for m in metrics)
         # leading = 0.25 * max_ascent
        baseline = self.cursor_y + 1.25 * max_ascent
        if self.centering:
            # compute total line width
            total_width = self.line[-1][0] + self.line[-1][2].measure(self.line[-1][1]) - self.line[0][0]
            # compute starting x to center the line
            offset = (self.width - total_width) // 2
        else:
            offset = 0
    
            
        for x, word, font in self.line:
            y = baseline - font.metrics("ascent")
            if self.superscript:
               y -= int(0.5 * max_ascent)
            self.display_list.append(DisplayItem(x + offset, y, word, font))
            
        self.cursor_y = baseline + 1.25 * max_descent

        # reset line buffer + x
        self.cursor_x = HSTEP
        self.line = []


    def word(self, tok):
        for word in tok.text.split():
            font = get_font(self.size, self.weight, self.style)
            # font = tkinter.font.Font(
            #         size=self.size,
            #         weight=self.weight,
            #         slant=self.style,
            #     )
            
            w = font.measure(word)
             # line wrap: flush line if needed
            if self.cursor_x + w > self.width - HSTEP:
                self.flush()
            self.line.append((self.cursor_x, word, font))
            self.cursor_x += w + font.measure(" ")


    def layout(self):
        """
        ## **Pass 1 (horizontal layout):**

            * measure each word
            * compute `x` positions
            * buffer the line
            (do NOT compute y yet)

            ---

        ## **Pass 2 (vertical layout):**

            * find largest ascent & descent in the line
            * compute baseline
            * assign final `y` for each word
            * output display items
                    
        """
     
       
        for tok in self.tokens:
            if isinstance(tok, Text):
                self.word(tok)
                
            elif tok.tag == "i":
               self.style = "italic"
            elif tok.tag == "/i":
                self.style = "roman"
            elif tok.tag == "b":
                self.weight = "bold"
            elif tok.tag == "/b":
                self.weight = "normal"
            elif tok.tag == "small":
                self.size -= 2
            elif tok.tag == "/small":
                self.size += 2
            
            elif tok.tag.startswith("h1"):
                self.size += 4
                if "title" in tok.tag:
                    self.centering = True
            elif tok.tag == "/h1":
                self.size -= 4
                self.centering = False
            elif tok.tag == "sup":
                self.size = int(self.size * 0.5)
                self.superscript = True
            elif tok.tag == "/sup":
                self.size = int(self.size * 2)
                self.superscript = False

        
        return self.display_list