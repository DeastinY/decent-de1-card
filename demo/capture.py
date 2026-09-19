"""Record images/ from demo.html in headless Chromium.

    python3 capture.py            # all three
    python3 capture.py gif        # or: desktop, phone

Needs chromium, ffmpeg, Pillow and websockets. demo.html pulls Roboto from Google
Fonts, so this wants a network connection; everything else is local.
"""
import asyncio, base64, io, json, os, shutil, subprocess, sys, tempfile, time, urllib.request
import websockets
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
IMAGES = os.path.join(ROOT, "images")
PORT, DEBUG_PORT = 8765, 9222

GIF = dict(w=760, h=456, fps=12.5, seconds=15.2)   # the story in demo.html is 15.2 s long
STILLS = {
    "desktop": dict(file="desktop-light-heating.png", theme="light", w=1086, h=533, scale=2,
                    state=dict(state="Idle", sub="heating", temp=71.3, water=96, shots=0,
                               lastShot=14 * 3600 * 1000)),
    "phone": dict(file="phone-dark.png", theme="dark", w=400, h=749, scale=2, fit=True,
                  state=dict(state="Idle", sub="ready", temp=92.9, water=52, shots=3,
                             lastShot=3 * 60 * 1000)),
}


class Chrome:
    """Just enough CDP to drive one page."""

    def __init__(self, width, height, scale):
        self.size = (width, height, scale)
        self.proc = subprocess.Popen([
            "chromium", "--headless=new", f"--remote-debugging-port={DEBUG_PORT}", "--no-sandbox",
            "--hide-scrollbars", "--force-color-profile=srgb", "--disable-lcd-text",
            f"--window-size={width},{height}", "about:blank",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _ws_url(self):
        for _ in range(80):
            try:
                targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json"))
                # skip the bundled extension's background page: we want the real tab
                return next(t for t in targets if t["type"] == "page"
                            and not t["url"].startswith("chrome-extension://"))["webSocketDebuggerUrl"]
            except Exception:
                time.sleep(0.25)
        raise SystemExit("chromium did not come up")

    async def __aenter__(self):
        self.ws = await websockets.connect(self._ws_url(), max_size=64 * 1024 * 1024)
        self._id = 0
        self.on_frame = None
        w, h, scale = self.size
        await self.cmd("Page.enable")
        await self.cmd("Emulation.setDeviceMetricsOverride", width=w, height=h,
                       deviceScaleFactor=scale, mobile=False)
        return self

    async def __aexit__(self, *exc):
        await self.ws.close()
        self.proc.terminate()

    async def pump(self, until_id):
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("method") == "Page.screencastFrame":
                p = msg["params"]
                await self.ws.send(json.dumps({"id": 10_000, "method": "Page.screencastFrameAck",
                                               "params": {"sessionId": p["sessionId"]}}))
                if self.on_frame:
                    self.on_frame(p["metadata"]["timestamp"], base64.b64decode(p["data"]))
            elif msg.get("id") == until_id:
                if "error" in msg:
                    raise SystemExit(f"{msg['error']}")
                return msg.get("result", {})

    async def cmd(self, method, **params):
        self._id += 1
        await self.ws.send(json.dumps({"id": self._id, "method": method, "params": params}))
        return await self.pump(self._id)

    async def eval(self, expression, **kw):
        r = await self.cmd("Runtime.evaluate", expression=expression, **kw)
        if "exceptionDetails" in r:
            raise SystemExit(r["exceptionDetails"]["exception"].get("description", "page error"))
        return r.get("result", {}).get("value")

    async def open(self, query):
        await self.cmd("Page.navigate", url=f"http://127.0.0.1:{PORT}/demo/demo.html{query}")
        for _ in range(120):
            if await self.eval("window.demoReady ? window.demoReady.then(()=>1) : 0", awaitPromise=True) == 1:
                return
            await asyncio.sleep(0.25)
        raise SystemExit("demo.html never became ready")


def serve():
    return subprocess.Popen([sys.executable, "-m", "http.server", str(PORT), "-d", ROOT],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def shoot(name):
    """One still: freeze a set of values, let the transitions land, screenshot."""
    s = STILLS[name]
    async with Chrome(s["w"], s["h"], s["scale"]) as c:
        await c.open(f"?still&theme={s['theme']}" + ("&fit" if s.get("fit") else ""))
        await c.eval(f"window.showState({json.dumps(s['state'])})")
        await asyncio.sleep(2.0)                 # screen fade, heat bar and water cross-fade
        if s.get("fit"):                         # trim the viewport to the card
            # scrollHeight never drops below the viewport, so measure the body itself
            h = await c.eval("Math.ceil(document.body.getBoundingClientRect().height)")
            await c.cmd("Emulation.setDeviceMetricsOverride", width=s["w"], height=h,
                        deviceScaleFactor=s["scale"], mobile=False)
            await asyncio.sleep(0.4)
        shot = await c.cmd("Page.captureScreenshot", format="png", fromSurface=True)
    im = Image.open(io.BytesIO(base64.b64decode(shot["data"]))).convert("RGB")
    if name == "desktop":                        # recorded at 2x, delivered at 1x
        im = im.resize((s["w"], s["h"]), Image.LANCZOS)
    out = os.path.join(IMAGES, s["file"])
    im.save(out)
    print(f"{s['file']}  {im.size[0]}x{im.size[1]}  {os.path.getsize(out) // 1024} KB")


async def record(tmp):
    """The story, as PNG frames stamped with the page's clock.

    Page.captureScreenshot costs ~110 ms a frame, slower than the animation runs;
    the screencast is push-based and keeps up. PNG, not JPEG: JPEG noise makes
    otherwise static pixels differ, which defeats the GIF's inter-frame diffing.
    """
    frames = []
    async with Chrome(GIF["w"], GIF["h"], 2) as c:   # 2x, downsampled later for clean text
        await c.open("?still")                       # hold still until the screencast is up
        c.on_frame = lambda t, data: frames.append((t, data))
        await c.cmd("Page.startScreencast", format="png", maxWidth=GIF["w"] * 2,
                    maxHeight=GIF["h"] * 2, everyNthFrame=1)
        await c.eval("window.startDemo()")
        try:
            await asyncio.wait_for(c.pump(until_id=-1), timeout=GIF["seconds"] + 0.4)
        except asyncio.TimeoutError:
            pass
        await c.cmd("Page.stopScreencast")

    t0 = frames[0][0]
    stamps = [t - t0 for t, _ in frames]
    print(f"screencast: {len(frames)} frames, {len(frames)/stamps[-1]:.0f} fps")
    n, j = int(GIF["seconds"] * GIF["fps"]), 0
    for i in range(n):                            # resample onto an even grid
        t = i / GIF["fps"]
        while j + 1 < len(stamps) and abs(stamps[j + 1] - t) <= abs(stamps[j] - t):
            j += 1
        im = Image.open(io.BytesIO(frames[j][1])).convert("RGB")
        im.resize((GIF["w"], GIF["h"]), Image.LANCZOS).save(f"{tmp}/s{i:04d}.png")
    return n


async def gif():
    with tempfile.TemporaryDirectory() as tmp:
        n = await record(tmp)
        out = os.path.join(IMAGES, "demo.gif")
        # One palette for the whole clip, no dithering: the render is mostly smooth
        # greys, and a dither pattern both shows and stops frames from compressing.
        run = lambda *a: subprocess.run(["ffmpeg", "-v", "error", "-y", *a], check=True)
        run("-framerate", str(GIF["fps"]), "-i", f"{tmp}/s%04d.png",
            "-vf", "palettegen=stats_mode=diff:max_colors=256", f"{tmp}/palette.png")
        run("-framerate", str(GIF["fps"]), "-i", f"{tmp}/s%04d.png", "-i", f"{tmp}/palette.png",
            "-lavfi", "paletteuse=dither=none:diff_mode=rectangle", "-loop", "0", out)
        print(f"demo.gif  {GIF['w']}x{GIF['h']}  {n} frames  {os.path.getsize(out) // 1024} KB")


async def main(which):
    srv = serve()
    try:
        for w in which:
            await (gif() if w == "gif" else shoot(w))
    finally:
        srv.terminate()


if __name__ == "__main__":
    for tool in ("chromium", "ffmpeg"):
        if not shutil.which(tool):
            raise SystemExit(f"{tool} is not on PATH")
    asyncio.run(main(sys.argv[1:] or ["gif", "desktop", "phone"]))
