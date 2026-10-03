#!/usr/bin/env python3
"""comfy_gen.py - queue one image on the local ComfyUI, wait, save it, print the path (JSON)."""
import argparse, json, os, random, sys, time, urllib.parse, urllib.request as u
KIT = os.path.expanduser(os.environ.get("KIT", "~/kit"))
URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188")
OUT = os.path.expanduser(os.environ.get("DESK_OUT", "~/desk-out"))
MODELS = {"sdxl": ("sdxl_api.json", "6"), "zit": ("zit_api.json", "27")}
p = argparse.ArgumentParser()
p.add_argument("--ticket", required=True); p.add_argument("--prompt", required=True)
p.add_argument("--model", default=os.environ.get("DESK_MODEL", "sdxl"), choices=MODELS)
p.add_argument("--seed", type=int, default=None); p.add_argument("--timeout", type=int, default=300)
p.add_argument("--negative", default=os.environ.get("DESK_NEGATIVE", "text, letters, words, numbers, writing, signature, watermark, logo, jersey numbers, scoreboard, blurry, cropped, cut off, multiple panels"))
a = p.parse_args()
wf_file, prompt_node = MODELS[a.model]
wf = json.load(open(os.path.join(KIT, "workflows", wf_file)))
wf[prompt_node]["inputs"]["text"] = a.prompt
seed = a.seed if a.seed is not None else random.randint(1, 2**31)
for n in wf.values():
    if n.get("class_type", "").startswith("KSampler") and "seed" in n.get("inputs", {}):
        n["inputs"]["seed"] = seed
        neg = n["inputs"].get("negative")
        if isinstance(neg, list) and str(neg[0]) in wf and "text" in wf[str(neg[0])].get("inputs", {}) and str(neg[0]) != prompt_node:
            wf[str(neg[0])]["inputs"]["text"] = a.negative
    if n.get("class_type") == "SaveImage":
        n["inputs"]["filename_prefix"] = f"desk/{a.ticket}"
def call(path, data=None):
    req = u.Request(URL + path, data=json.dumps(data).encode() if data else None, headers={"Content-Type": "application/json"})
    return json.load(u.urlopen(req, timeout=30))
t0 = time.time()
try:
    pid = call("/prompt", {"prompt": wf})["prompt_id"]
    while True:
        h = call(f"/history/{pid}")
        if pid in h: break
        if time.time() - t0 > a.timeout: raise TimeoutError(f"no result after {a.timeout}s")
        time.sleep(2)
    entry = h[pid]
    if entry.get("status", {}).get("status_str") == "error":
        raise RuntimeError(json.dumps(entry["status"])[:500])
    img = next(i for o in entry["outputs"].values() for i in o.get("images", []))
    q = urllib.parse.urlencode({"filename": img["filename"], "subfolder": img.get("subfolder", ""), "type": img.get("type", "output")})
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"{a.ticket}_{int(time.time())}.png")
    with u.urlopen(f"{URL}/view?{q}", timeout=60) as r, open(path, "wb") as f:
        f.write(r.read())
    print(json.dumps({"ok": True, "file": path, "seed": seed, "model": a.model, "seconds": round(time.time() - t0, 1)}))
except Exception as e:
    print(json.dumps({"ok": False, "error": str(e)}))
    sys.exit(1)
