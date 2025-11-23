import socket, ssl, sys, time, gzip, zlib
from io import BytesIO
from urllib.parse import unquote, urlsplit, urlunsplit

DEFAULT_USER_AGENT = "TinyBrowser/0.1"


# -------------------------
# Utilities
# -------------------------

def now():
    return time.time()

def decode_entities(text:str) -> str :
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")

# --------------------------------
# Connection pool for keep-alive 
# ---------------------------------


class ConnectionPool:
    def __init__(self):
        # key: (scheme, host, port) -> (socket, last_used_time)
        self.pool ={}

    def get(self, scheme, host, port):
        key = (scheme, host, port)
        entry = self.pool.get(key)
        if entry:
            s, t = entry
            return s
        return None
    
    def set(self, scheme, host, port, sock):
        key = (scheme, host, port)
        self.pool[key] = (sock, now())

    def close_all(self):
        for (s,_) in self.pool.values():
            try:
                s.close()
            except:
                pass
        self.pool.clear()

# -------------------------
# Simple in-memory cache 
# -------------------------

class SimpleCache:
    def __init__(self):
            # key: url -> (body_bytes, stored_time, max_age_seconds or None)
            self.store = {}

    def get(self, url):
        v = self.store.get(url)
        if not v:
            return None
        body, stored, max_age = v
        if max_age is None:
            return body
        if (now() - stored) <= max_age:
                return body
        else:
            # expired
            del self.store[url]
            return None
        
    def set(self, url, body, max_age):
        # if max_age is None means store indefinitely
        self.store[url] = (body, now(), max_age)
        
# --------------------------------------
# HTTP helpers: chunked decode, readexact
# ---------------------------------------

def read_exact(rfile, n):
    """Read exactly n bytes from file-like binary rfile."""
    chunks =[]
    remaining = n
    while remaining > 0:
        piece = rfile.read(remaining)
        if not piece:
            break
        chunks.append(piece)
        remaining -= len(piece)
    return b"".join(chunks)

def decode_chunked(rfile):
    """Decode HTTP chunked transfer from binary file-like rfile.
    Ex: 
        4\r\n -> byte size
        Wiki\r\n -> byte value
        5\r\n
        pedia\r\n
        E\r\n
        in\r\nchunks.\r\n
        0\r\n
        \r\n

    """

    body = BytesIO()

    while True:
         # chunk-size line
        line = rfile.readline()
        if not line:
            break
        line = line.strip()
        # ignore chunk extensions after ';'
        if b';' in line:
            line = line.split(b';',1)[0]
        try:
            size = int(line, 16)
        except:
            raise RuntimeError(f"Bad chunk size: {line!r}")
        if size == 0:
            # read and discard trailer headers until blank line
            while True:
                l = rfile.readline()
                if not l or l in (b'\r\n', b'\n', b''):
                    break
            break
        data = read_exact(rfile, size)
        body.write(data)
        # consume CRLF after chunk  ( removes the trailing \r\n)
        rfile.read(2)
    return body.getvalue()




#scheme://host/path
#     Scheme  Hostname    path
# Ex: http://example.org/index.html

class URL:

    def __init__(self, raw_url=None):
         
        self.conn_pool = ConnectionPool()
        self.cache = SimpleCache()
        self.default_file_on_no_url = "test.html"
        self.max_redirects = 10
        self.raw_url = raw_url
        
        


    # ---------------------
    # Public: load (entry)
    # ---------------------      
    def fetch(self):
        if self.raw_url is None:
            self.raw_url = "file:///" + self.default_file_on_no_url
            print(f"[info] No URL given. Opening {self.raw_url}")
        
        # handle view-source wrapper
        view_source_mode = False

        if self.raw_url.startswith("view-source:"):
            view_source_mode = True
            self.raw_url = self.raw_url[len("view-source:"):]

        scheme = self.raw_url.split(":",1)[0].lower()
        if scheme == "file":
            body = self._handle_file_url(self.raw_url)
            if view_source_mode:
                  self._show_raw_bytes(body)
            else:
                self._show_text(body.decode("utf8", errors="replace"))
            return
        if scheme == "data":
            body = self._handle_data_url(self.raw_url)
            if view_source_mode:
                self._show_raw_bytes(body)
            else:
                self._show_text(body.decode("utf8", errors="replace"))
            return
        # http/https
        # Follow redirects with limit
        redirects = 0
        url_to_fetch = self.raw_url

        while True:
            if redirects > self.max_redirects:
                print("[error] Too many redirects")
                return
            # caching (only GET and 200 responses cached—this is applied after response)
            # try cache lookup first (cache keys are full URL)
            cached_body = self.cache.get(url_to_fetch)
            if cached_body is not None:
                print(f"[cache] HIT for {url_to_fetch}")
                if view_source_mode:
                    self._show_raw_bytes(cached_body)
                else:
                  response_content=  self._show_text(cached_body.decode("utf8", errors="replace"),tag_strip=False)
                return response_content
            resp = self._http_request(url_to_fetch)
            if resp is None:
                return
            status_code, headers, body = resp
            # handle redirects (3xx)
            if 300 <= status_code < 400:
                loc = headers.get("location")
                if not loc:
                    print("[error] redirect with no Location")
                    return
                # resolve relative location
                from urllib.parse import urljoin
                url_to_fetch = urljoin(url_to_fetch, loc)
                print(f"[redirect] {status_code} -> {url_to_fetch}")
                redirects += 1
                continue
            # cache if allowed: GET & 200
            # parse Cache-Control header
            cc = headers.get("cache-control", "")
            # simple parsing: look for no-store, look for max-age=N
            if status_code == 200:
                if "no-store" in cc:
                    pass  # do not cache
                else:
                    max_age = None
                    if "max-age" in cc:
                        try:
                            # find max-age
                            parts = [p.strip() for p in cc.split(',')]
                            for p in parts:
                                if p.startswith("max-age"):
                                    _, val = p.split("=",1)
                                    max_age = int(val)
                        except:
                            max_age = None
                    self.cache.set(url_to_fetch, body, max_age)
                 # finally display
            if view_source_mode:
                self._show_raw_bytes(body)
            else:
                # body is bytes. decode and render
                text = body.decode("utf8", errors="replace")
                response_content = self._show_text(text, tag_strip=False)
            return response_content
            

        
    # ---------------------
    # File URL
    # ---------------------
    def _handle_file_url(self, raw_url):
        # file:///absolute/path
        # note: urlsplit returns path with leading '/'
        u = urlsplit(raw_url)
        path = u.path
        try:
            with open(path, "rb") as f:
                return f.read()
        except Exception as e:
            return f"<html><body><h1>File error</h1><p>{e}</p></body></html>".encode("utf8")
        
    # ---------------------
    # Data URL
    # ---------------------
    def _handle_data_url(self, raw_url):
       
        """
        # format: data:[<mediatype>][;base64],<data>
        # We'll support text/html and percent-encoded data

        1. Plain text : data:,Hello%20World
        2. text/html : data:text/html,<h1>Hello</h1>
        3. Base64 encoded PNG image : data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA...

        """
        assert raw_url.startswith("data:")
        body = raw_url[len("data:"):]
        if "," not in body:
            return b""
        meta, data = body.split(",",1)
        is_base64 = False
        if ";base64" in meta:
            is_base64 = True
            meta = meta.replace(";base64","")
        mediatype = meta or "text/plain"
        if is_base64:
            import base64
            return base64.b64decode(data)
        else:
            # percent-decoded (URL encoded)
            return unquote(data).encode("utf8")


    
    # ---------------------
    # HTTP request: returns (status_code:int, headers:dict, body:bytes)
    # ---------------------
    def _http_request(self, raw_url):
        parsed = urlsplit(raw_url)
        scheme = parsed.scheme
        host = parsed.hostname
        port = parsed.port or (443 if scheme=="https" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        
        # try reuse connection
        sock = None
        reuse = True
        if reuse:
            sock = self.conn_pool.get(scheme, host, port)
            
        created_new = False
        if not sock:
            sock = self.create_socket(scheme,host,port)
            if sock is None:
                return
            created_new = True

         # Build request (HTTP/1.1)
        headers = {
            "Host": host,
            "Connection": "keep-alive",     
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept-Encoding": "gzip",       
        }
        request_lines = [f"GET {path} HTTP/1.1"]
        for k,v in headers.items():
            request_lines.append(f"{k}: {v}")
        request_lines.append("")  # blank line
        request_raw = "\r\n".join(request_lines) + "\r\n"
        try:
             sock.sendall(request_raw.encode("utf8"))
        except Exception as e:
            # socket may have gone stale; try create a new one once
            try:
                sock.close()
            except: pass
            sock = self.create_socket(scheme,host,port)
            if sock is None:
                return
            sock.sendall(request_raw.encode("utf8"))

        # read response using file-like in binary mode (important for bytes)
        rfile = sock.makefile("rb", buffering=0)
         # read status line
        status_line = rfile.readline().decode("iso-8859-1").strip()
        if not status_line:
            print("[error] empty response")
            return None
        parts = status_line.split(" ",2)
        if len(parts) < 2:
            print(f"[error] bad status line: {status_line}")
            return None
        try:
            status_code = int(parts[1])
        except:
            status_code = 0
        # read headers
        headers_out = {}
        while True:
            line = rfile.readline().decode("iso-8859-1")
            if line in ("\r\n", "\n", ""):
                break
            if ":" not in line:
                continue
            name, val = line.split(":",1)
            headers_out[name.strip().lower()] = val.strip()


        # Transfer-Encoding / Content-Encoding handling
        if headers_out.get("transfer-encoding","").lower() == "chunked":
            body = decode_chunked(rfile)
        else:
            # if content-length present, read exact bytes
            if "content-length" in headers_out:
                try:
                    clen = int(headers_out["content-length"])
                    body = read_exact(rfile, clen)
                except:
                    body = rfile.read()
            else:
                # no content-length and not chunked:
                # read until socket EOF (server will close if Connection: close)
                body = rfile.read()


        # Handle gzip content-encoding
        cenc = headers_out.get("content-encoding","").lower()
        if cenc == "gzip":
            try:
                body = gzip.decompress(body)
            except:
                try:
                    body = zlib.decompress(body, 16+zlib.MAX_WBITS)
                except:
                    pass
        elif cenc == "deflate":
            try:
                body = zlib.decompress(body)
            except:
                pass
        
        # Manage connection reuse: if server wants close, close socket; else keep
        server_conn = headers_out.get("connection","").lower()
        if server_conn == "close" or headers_out.get("proxy-connection","").lower() == "close":
            try:
                sock.close()
            except:
                pass
            # remove from pool if present
            # (pool will only hold sockets we set)
        else:
            # keep socket in pool for reuse
            self.conn_pool.set(scheme, host, port, sock)


        return status_code, headers_out, body


    def create_socket(self,scheme,host,port):

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP)
        sock.settimeout(6)
        try:
            sock.connect((host, port))
        except Exception as e:
                print(f"[error] connect failed: {e}")
                return None
        if scheme == "https":
                ctx = ssl.create_default_context()
                sock = ctx.wrap_socket(sock, server_hostname=host)
        return sock
    
    # ---------------------
    # Output helpers: show raw bytes or "rendered" (strip tags + decode entities)
    # ---------------------
    def _show_raw_bytes(self, bts: bytes):
        try:
            txt = bts.decode("utf8", errors="replace")
        except:
            txt = str(bts)
        print(txt)
    
    def _show_text(self, text: str, tag_strip: bool = True) -> str:
        if not tag_strip : 
            return text
        # very small HTML text-only renderer: strip tags and decode entities 
        out = []
        in_tag = False
        i = 0
        while i < len(text):
            c = text[i]
            if c == "<":
                in_tag = True
            elif c == ">":
                in_tag = False
            elif not in_tag:
                out.append(c)
            i += 1
        rendered = "".join(out)
        rendered = decode_entities(rendered)
        
        return rendered



# -------------------------
# Main
# -------------------------
def main():
    """
    Example Usage:

    Example 1 — Simple text:
       python3 browser-engine/tiny-browser.py data:,Hello%20World

    Example 2 — HTML inside URL:
        python3 browser_engine/tiny_browser.py "data:text/html,<b>Hello</b>"
    Example 3 — text with entities (<, >) encoded:
        python3 browser_engine/tiny_browser.py "data:text/html,Hello%20%3Cworld%3E"
    Example 4 — text with view-source:
        python3 browser_engine/tiny_browser.py view-source:http://example.org/
    Example 5 — redirects:
       python3 browser_engine/tiny_browser.py http://browser.engineering/redirect
    
 

    """
    b = URL()
    if len(sys.argv) < 2:
        url = None
    else:
        url = sys.argv[1]
    try:
        b.fetch(url)
    finally:
        b.conn_pool.close_all()

if __name__ == "__main__":
    main()


