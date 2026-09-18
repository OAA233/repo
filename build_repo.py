#!/usr/bin/env python3
"""把 debs/ 里的 .deb 编成 APT 源(Sileo/Cydia/Zebra 通用)。

用法:  python3 build_repo.py          # 生成 Packages / Packages.bz2 / Packages.gz / Release
      python3 build_repo.py --check   # 只校验已生成的文件

付费包: 把包名(控制文件里的 Package:)一行一个写进 paid.txt，
       生成时会自动加 Tag: cydia::commercial (Sileo 认这个才会走购买流程)。
说明与贴图: 每个包可选一份 meta/<包名>.json:
       {"desc": "中文说明(markdown)", "info": {"兼容": "iOS 17", "作者": "王"}}
       贴图丢进 shots/<包名>/ 里(任意 *.png|jpg，按文件名排序)，
       文件名叫 banner.png 的那张会当介绍页顶图。
       有 meta 或贴图的包会自动生成 depictions/<包名>.json 原生介绍页。
新版本: 把新 .deb 丢进 debs/ 再跑一次即可，同一个包名多版本没问题，装的时候取最高版。
"""
import bz2, gzip, hashlib, io, json, os, re, shutil, subprocess, sys, tarfile
from urllib.parse import quote

ROOT = os.path.dirname(os.path.abspath(__file__))
DEBS = os.path.join(ROOT, "debs")
PAID = os.path.join(ROOT, "paid.txt")
META = os.path.join(ROOT, "meta")
SHOTS = os.path.join(ROOT, "shots")
MAC = os.path.join(ROOT, "mac")            # 非 APT 的普通下载件（Mac 客户端 zip 等）
DEPICTIONS = os.path.join(ROOT, "depictions")
ZSTD = shutil.which("zstd") or "/opt/homebrew/bin/zstd"

# 源的身份信息 —— 改成你自己的
ORIGIN = "Wangyuan's Repo"
LABEL = "Wangyuan's Repo"
DESCRIPTION = "Wangyuan's rootless tweaks (iOS 17) · 王源的无根越狱插件源"
ARCHS = "iphoneos-arm iphoneos-arm64"

# 包里 control 写的还是旧占位名，仓库侧统一显示成这个（改 deb 要重新打包，先不动 deb）
AUTHOR = "王源"
# 这些旧名字一律在源侧改写成 AUTHOR（deb 本体不动）
LEGACY_AUTHORS = ("a0", "", "王", "Wang", "wang", "wangyuan")

# 可用地址，第 1 个是主源（Cloudflare Pages），后面是国内/海外备用
MIRRORS = ["https://wangyuan-repo.pages.dev/",
           "https://cdn.jsdelivr.net/gh/OAA233/repo@main/",
           "https://fastly.jsdelivr.net/gh/OAA233/repo@main/",
           "https://sileo-repo.pages.dev/"]
# 图标固定走 jsDelivr（国内实测能拉）。主源如果是 Cloudflare Pages，手机偶尔不通时
# 图标也不会跟着挂掉。想让图标也走主源就把下面这行改成 MIRRORS[0]。
ICON_BASE = MIRRORS[1]
# 介绍页 JSON 和贴图也走 jsDelivr：实测国内这条路比 pages.dev 稳（pages.dev 偶发连不上）
DEP_BASE = ICON_BASE


# ---------- .deb 读取 (ar + control.tar.*) ----------
def ar_members(blob):
    assert blob[:8] == b"!<arch>\n", "不是 ar 归档"
    off, out = 8, {}
    while off + 60 <= len(blob):
        name = blob[off:off + 16].decode().strip().rstrip("/")
        size = int(blob[off + 48:off + 58].decode().strip())
        out[name] = blob[off + 60:off + 60 + size]
        off += 60 + size + (size & 1)
    return out


def control_of(path):
    m = ar_members(open(path, "rb").read())
    name = next(k for k in m if k.startswith("control.tar"))
    raw = m[name]
    ext = name.rsplit(".", 1)[-1]
    if ext == "zst":
        raise SystemExit("control.tar.zst 需要 python3.14 或 pip install zstandard —— " + path)
    data = {"gz": gzip.decompress, "xz": __import__("lzma").decompress,
            "lzma": __import__("lzma").decompress, "bz2": bz2.decompress}[ext](raw)
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        member = next(x for x in t.getmembers() if x.name.rstrip("/").split("/")[-1] == "control")
        return t.extractfile(member).read().decode("utf-8")


def parse_control(text):
    """RFC822 解析: 'Key: value' 起头，续行以空格开头。"""
    fields, key = [], None
    for line in text.splitlines():
        if line[:1] in (" ", "\t") and key:
            fields[-1][1] += "\n" + line
        elif ":" in line:
            key, _, val = line.partition(":")
            fields.append([key.strip(), val.strip()])
        key = fields[-1][0] if fields else None
    return fields


# ---------- 介绍页 (Sileo 原生 depiction) ----------
def load_meta(pkg):
    p = os.path.join(META, pkg + ".json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}


def shot_files(pkg):
    d = os.path.join(SHOTS, pkg)
    if not os.path.isdir(d):
        return []
    return [n for n in sorted(os.listdir(d))
            if n.lower().endswith((".png", ".jpg", ".jpeg")) and n != "banner.png"]


def build_depiction(stanza, meta):
    pkg = stanza["Package"]
    views = [{"class": "DepictionHeaderView", "title": stanza.get("Name", pkg)},
             {"class": "DepictionSubheaderView",
              "title": f"{stanza.get('Version', '?')} · {stanza.get('Author', AUTHOR)}"}]
    shots = [{"url": f"{DEP_BASE}shots/{pkg}/{quote(n)}", "accessibilityText": "", "video": False}
             for n in shot_files(pkg)]
    if shots:
        views.append({"class": "DepictionScreenshotsView", "itemCornerRadius": 8,
                      "itemSize": {"x": 260, "y": 563}, "screenshots": shots})
    if meta.get("desc"):
        views.append({"class": "DepictionMarkdownView", "markdown": meta["desc"]})
    for k, v in (meta.get("info") or {}).items():
        views.append({"class": "DepictionTableTextView", "title": str(k), "text": str(v)})
    if meta.get("info"):
        views.insert(len(views) - len(meta["info"]), {"class": "DepictionSeparatorView"})
    doc = {"minVersion": "0.4", "class": "DepictionTabView", "tintColor": "#5b5bd6",
           "tabs": [{"class": "DepictionStackView", "tabname": "介绍", "views": views}]}
    if os.path.exists(os.path.join(SHOTS, pkg, "banner.png")):
        doc["headerImage"] = f"{DEP_BASE}shots/{pkg}/banner.png"
    return doc


def has_depiction(pkg):
    return bool(load_meta(pkg)) or bool(shot_files(pkg)) or \
        os.path.exists(os.path.join(SHOTS, pkg, "banner.png"))


# ---------- 生成 Packages ----------
def build_packages():
    paid = {l.split("#")[0].strip() for l in open(PAID, encoding="utf-8")} if os.path.exists(PAID) else set()
    paid.discard("")
    stanzas = []
    for fn in sorted(os.listdir(DEBS)):
        if not fn.endswith(".deb"):
            continue
        path = os.path.join(DEBS, fn)
        fields = parse_control(control_of(path))
        d = dict(fields)
        blob = open(path, "rb").read()

        # 付费标记 (合并原本可能已有的 Tag)
        for k in ("Author", "Maintainer"):          # deb 里是旧占位名，仓库侧改写
            if d.get(k, "").strip() in LEGACY_AUTHORS:
                d[k] = AUTHOR
        # 中文说明：meta/<包名>.json 里的 desc 第一行进列表，完整 markdown 进介绍页
        meta = load_meta(d["Package"])
        if meta.get("desc"):
            first = re.sub(r"[#*`>]", "", meta["desc"].strip().split("\n")[0]).strip()
            d["Description"] = first[:120]
        if has_depiction(d["Package"]):
            os.makedirs(DEPICTIONS, exist_ok=True)
            with open(os.path.join(DEPICTIONS, d["Package"] + ".json"), "w", encoding="utf-8") as fh:
                json.dump(build_depiction(d, meta), fh, ensure_ascii=False, indent=1)
        if d["Package"] in paid:
            tags = [t.strip() for t in d.get("Tag", "").split(",") if t.strip()]
            if "cydia::commercial" not in tags:
                tags.append("cydia::commercial")
            d["Tag"] = ", ".join(tags)

        head = ["Package", "Name", "Version", "Architecture", "Description", "Author",
                "Maintainer", "Section", "Depends", "Pre-Depends", "Conflicts", "Replaces",
                "Provides", "Tag", "Icon", "Depiction", "SileoDepiction"]
        out = [f"{k}: {d[k]}" for k in head if k in d]
        # Sileo/Zebra 包列表里的图标：icons/<包名>.png，没有就用 icons/default.png
        icon = os.path.join(ROOT, "icons", d["Package"] + ".png")
        if not os.path.exists(icon):
            icon = os.path.join(ROOT, "icons", "default.png")
        if os.path.exists(icon):
            out.append(f"Icon: {ICON_BASE}icons/{os.path.basename(icon)}")
        if has_depiction(d["Package"]):
            out.append(f"SileoDepiction: {DEP_BASE}depictions/{d['Package']}.json")
            if os.path.exists(os.path.join(SHOTS, d["Package"], "banner.png")):
                out.append(f"Header: {DEP_BASE}shots/{d['Package']}/banner.png")
        out.append(f"Filename: debs/{fn}")
        out.append(f"Size: {len(blob)}")
        out.append(f"SHA256: {hashlib.sha256(blob).hexdigest()}")
        out.append(f"MD5sum: {hashlib.md5(blob).hexdigest()}")
        stanzas.append("\n".join(out))
        print(f"  + {d['Package']} {d['Version']} ({d['Architecture']})"
              + ("  [付费]" if d["Package"] in paid else ""))
    return "\n\n".join(stanzas) + "\n"


def write_all():
    os.makedirs(DEBS, exist_ok=True)
    os.makedirs(SHOTS, exist_ok=True)
    os.makedirs(MAC, exist_ok=True)
    shutil.rmtree(DEPICTIONS, ignore_errors=True)   # 清掉已删包的旧介绍页
    text = build_packages()
    blob = text.encode()
    variants = ["Packages", "Packages.bz2", "Packages.gz"]
    for name, data in [("Packages", blob), ("Packages.bz2", bz2.compress(blob)),
                       ("Packages.gz", gzip.compress(blob))]:
        open(os.path.join(ROOT, name), "wb").write(data)

    # Sileo 优先探测 Packages.zst；Cloudflare Pages 对不存在的路径会拿 index.html 冒充
    # 200，客户端解压就报 "Hash invalid / ZSTDError"，所以必须给一份真的 .zst
    if os.path.exists(ZSTD):
        subprocess.run([ZSTD, "-q", "-f", os.path.join(ROOT, "Packages"), "-o",
                        os.path.join(ROOT, "Packages.zst")], check=True)
        variants.append("Packages.zst")
    else:
        print("  (没找到 zstd 命令，跳过 Packages.zst —— brew install zstd)")

    # 同上：缺文件时老老实实 404，别拿 index.html 冒充
    open(os.path.join(ROOT, "404.html"), "w").write(
        "<!doctype html><meta charset=utf-8><title>404</title>404: no such file in this repo.\n")

    lines = [f"Origin: {ORIGIN}", f"Label: {LABEL}", "Suite: stable", "Version: 1.0",
             "Codename: ios", f"Architectures: {ARCHS}", "Components: main",
             f"Description: {DESCRIPTION}", "Date: " + __import__("email.utils", fromlist=["x"]).formatdate(usegmt=True)]
    for algo, fn in [("MD5Sum", hashlib.md5), ("SHA256", hashlib.sha256)]:
        lines.append(f"{algo}:")
        for name in variants:
            data = open(os.path.join(ROOT, name), "rb").read()
            lines.append(f" {fn(data).hexdigest()} {len(data)} {name}")
    open(os.path.join(ROOT, "Release"), "w").write("\n".join(lines) + "\n")
    open(os.path.join(ROOT, ".nojekyll"), "w").write("")

    # 给人看的落地页 (.nojekyll 关掉了 Jekyll，没有 index.html 就是 404)
    rows = []
    for s in text.strip().split("\n\n"):
        d = dict(parse_control(s))
        rows.append(f"<tr><td>{d['Name']}</td><td>{d['Version']}</td><td>{d['Description'].splitlines()[0]}</td></tr>")

    # 非 APT 的普通下载件：mac/ 里的 zip/dmg（Mac 客户端这类东西 Sileo 装不了，只能当附件下）
    macs = sorted((n for n in os.listdir(MAC)
                   if n.lower().endswith((".zip", ".dmg", ".pkg", ".tar.gz"))) if os.path.isdir(MAC) else [],
                  key=lambda n: os.path.getmtime(os.path.join(MAC, n)), reverse=True)
    mac_html = ""
    if macs:
        links = "".join(
            f'<li><a href="mac/{quote(n)}">{n}</a> '
            f'<small>{os.path.getsize(os.path.join(MAC, n)) // 1024} KB · '
            f'{__import__("time").strftime("%Y-%m-%d", __import__("time").localtime(os.path.getmtime(os.path.join(MAC, n))))}</small></li>'
            for n in macs)
        mac_html = f"""
<h3>Mac 客户端下载</h3>
<p>这些是 macOS 上的配套程序，Sileo/Zebra 装不了，直接下载解压用：</p>
<ul>{links}</ul>
<p><small>镜像（主源连不上时用）：{MIRRORS[1]}mac/{quote(macs[0])}</small></p>
"""

    open(os.path.join(ROOT, "index.html"), "w", encoding="utf-8").write(f"""<!doctype html>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{LABEL}</title>
<style>body{{font:16px/1.6 -apple-system,sans-serif;max-width:40em;margin:2em auto;padding:0 1em}}
a.btn{{display:inline-block;background:#5b5bd6;color:#fff;padding:.7em 1.2em;border-radius:.6em;text-decoration:none;margin:.3em .3em .3em 0}}
code{{background:#0001;padding:.15em .4em;border-radius:.3em;word-break:break-all}}table{{border-collapse:collapse;width:100%}}
td,th{{border-bottom:1px solid #8884;padding:.4em .3em;text-align:left;font-size:.95em}}
ul{{padding-left:1.2em}}small{{color:#888}}</style>
<h2>{LABEL}</h2>
<p><a class="btn" href="sileo://source/{MIRRORS[0]}">添加到 Sileo（主）</a>
<a class="btn" href="sileo://source/{MIRRORS[1]}">添加到 Sileo（备用）</a></p>
<p><b>在软件源里手动添加</b>（一行一个，先试第一个）：</p>
<p><code>{MIRRORS[0]}</code><br><small>Cloudflare Pages 主源</small></p>
<p><code>{MIRRORS[1]}</code><br><small>jsDelivr 国内 CDN，不通就换 {MIRRORS[2]} 或 {MIRRORS[3]}</small></p>
<p><small>⚠️ 添加源时只粘上面这种纯网址，不要粘 <code>sileo://</code> 开头的那种链接（那是给浏览器点击用的）。</small></p>
<table><tr><th>包</th><th>版本</th><th>说明</th></tr>
{chr(10).join(rows)}
</table>
{mac_html}""")



# ---------- 校验 ----------
def check():
    ok = True
    text = open(os.path.join(ROOT, "Packages"), encoding="utf-8").read()
    stanzas = [s for s in text.split("\n\n") if s.strip()]
    try:
        rel = parse_control(open(os.path.join(ROOT, "Release"), encoding="utf-8").read())
    except Exception as e:
        print("FAIL Release 不可解析:", e)
        return False
    rel_hashes = dict(rel)
    for s in stanzas:
        d = dict(parse_control(s))
        path = os.path.join(ROOT, d["Filename"])
        blob = open(path, "rb").read()
        for key, fn in [("Size", len), ("SHA256", lambda b: hashlib.sha256(b).hexdigest()),
                        ("MD5sum", lambda b: hashlib.md5(b).hexdigest())]:
            want = d[key]
            got = str(fn(blob))
            if want != got:
                print(f"FAIL {d['Package']} {key}: {want} != {got}")
                ok = False
    # Release 里的散列要跟真的 Packages 对上
    for algo in ("MD5Sum", "SHA256"):
        for line in rel_hashes[algo].strip().split("\n"):
            if not line.strip():
                continue
            h, size, name = line.split()
            blob = open(os.path.join(ROOT, name), "rb").read()
            real = (hashlib.md5 if algo == "MD5Sum" else hashlib.sha256)(blob).hexdigest()
            if (h, size) != (real, str(len(blob))):
                print(f"FAIL Release {algo} {name}")
                ok = False
    # 压缩件解出来必须跟原文一字节不差
    for name, dec in [("Packages.bz2", bz2.decompress), ("Packages.gz", gzip.decompress)]:
        if dec(open(os.path.join(ROOT, name), "rb").read()) != open(os.path.join(ROOT, "Packages"), "rb").read():
            print(f"FAIL {name} 解压内容不一致")
            ok = False
    # zst 是 Sileo 的首选，必须解得回来
    zst = os.path.join(ROOT, "Packages.zst")
    if os.path.exists(zst):
        out = subprocess.run([ZSTD, "-d", "-c", zst], capture_output=True, check=True).stdout
        if out != open(os.path.join(ROOT, "Packages"), "rb").read():
            print("FAIL Packages.zst 解压内容不一致")
            ok = False
    else:
        print("FAIL 缺 Packages.zst（Sileo 会报 Hash/ZSTD 错误）")
        ok = False
    print("PASS" if ok else "FAILED", f"— {len(stanzas)} 个包, {os.path.getsize(os.path.join(ROOT, 'Packages'))} 字节")
    return ok


if __name__ == "__main__":
    if "--check" not in sys.argv:
        write_all()
    sys.exit(0 if check() else 1)
