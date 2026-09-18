#!/usr/bin/env python3
"""把 debs/ 里的 .deb 编成 APT 源(Sileo/Cydia/Zebra 通用)。

用法:  python3 build_repo.py          # 生成 Packages / Packages.bz2 / Packages.gz / Release
      python3 build_repo.py --check   # 只校验已生成的文件

付费包: 把包名(控制文件里的 Package:)一行一个写进 paid.txt，
       生成时会自动加 Tag: cydia::commercial (Sileo 认这个才会走购买流程)。
说明与贴图: 每个包可选一份 meta/<包名>.json:
       {"name": "我的镜子17", "desc": "中文说明(markdown)", "info": {"兼容": "iOS 17.0"}}
       name 会覆盖包列表里显示的名字(不用重打 deb)，desc 第一行进列表、整段进介绍页。
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
AUTHOR = "wangyuan"
# 这些旧名字一律在源侧改写成 AUTHOR（deb 本体不动）
LEGACY_AUTHORS = ("a0", "", "王", "Wang", "wang", "wangyuan")

# 索引类文件的镜像：必须和主源**真的同步**。jsDelivr 对分支(@main)缓存不认 purge，
# 实测会出现三个镜像三个版本的惨案（主源 7.12 / cdn 7.13 / fastly 7.15），所以索引不用它。
MIRRORS = ["https://wangyuan-repo.pages.dev/",     # 主源（Cloudflare Pages）
           "https://oaa233.github.io/repo/"]        # 同一份 push 重建，天然同步
# 图标/介绍页/贴图这类媒体文件才走 jsDelivr：按内容变化、可以显式 purge，国内也拉得到。
ICON_BASE = "https://cdn.jsdelivr.net/gh/OAA233/repo@main/"
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


def newest_mac():
    """mac/ 里最新的那个下载件（zip/dmg/pkg），给 meta 里的 "mac:" 快捷写法用。"""
    if not os.path.isdir(MAC):
        return None
    files = [n for n in os.listdir(MAC)
             if n.lower().endswith((".zip", ".dmg", ".pkg", ".tar.gz"))]
    return max(files, key=lambda n: os.path.getmtime(os.path.join(MAC, n))) if files else None


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
    for b in (meta.get("buttons") or []):        # 介绍页里的按钮（比如 Mac 客户端下载）
        raw = b["url"]
        if raw == "mac:":                        # 自动指向 mac/ 里最新的那个
            raw = "mac/" + (newest_mac() or "")
        url = raw if raw.startswith("http") else f"{DEP_BASE}{raw}"
        views.append({"class": "DepictionTableButtonView", "title": b["title"], "action": url,
                      "openExternal": bool(b.get("external", True)),
                      "tintColor": b.get("tintColor", "#5b5bd6")})
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
        if meta.get("depends"):                     # 仓库侧改依赖（不用重打包 deb）
            d["Depends"] = meta["depends"]
        # 显示名改写：meta/<包名>.json 里写 "name": "我的镜子17" 就行，不用重打 deb
        if meta.get("name"):
            d["Name"] = meta["name"]
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
            # URL 带图标内容哈希：文件一变 URL 就变，绕开 Sileo 按键控的图标缓存
            icon_ver = hashlib.md5(open(icon, "rb").read()).hexdigest()[:8]
            out.append(f"Icon: {ICON_BASE}icons/{os.path.basename(icon)}?v={icon_ver}")
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
    esc = __import__("html").escape
    cards = []
    for s in text.strip().split("\n\n"):
        d = dict(parse_control(s))
        icon = f"icons/{d['Package']}.png"
        if not os.path.exists(os.path.join(ROOT, icon)):
            icon = "icons/default.png"
        cards.append((d["Name"], d["Version"], d["Description"].splitlines()[0], icon))
    pkg_html = "".join(
        f'<div class="card"><img class="icon" src="{esc(icon)}" alt="" width="56" height="56">'
        f'<div class="meta"><div class="row"><span class="name">{esc(name)}</span>'
        f'<span class="ver">{esc(ver)}</span></div>'
        f'<div class="desc" title="{esc(desc)}">{esc(desc)}</div></div></div>'
        for name, ver, desc, icon in cards)

    # 非 APT 的普通下载件：mac/ 里的 zip/dmg（Mac 客户端这类东西 Sileo 装不了，只能当附件下）
    macs = sorted((n for n in os.listdir(MAC)
                   if n.lower().endswith((".zip", ".dmg", ".pkg", ".tar.gz"))) if os.path.isdir(MAC) else [],
                  key=lambda n: os.path.getmtime(os.path.join(MAC, n)), reverse=True)
    mac_html = ""
    if macs:
        MAC_ICON = ('<svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" '
                    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
                    '<rect x="3.5" y="4" width="17" height="11.5" rx="2"/>'
                    '<path d="M12 15.5v3.5"/><path d="M8.5 21h7"/></svg>')
        items = []
        for n in macs:
            p = os.path.join(MAC, n)
            info = (f"{os.path.getsize(p) // 1024} KB · "
                    f'{__import__("time").strftime("%Y-%m-%d", __import__("time").localtime(os.path.getmtime(p)))}'
                    " · 下载解压使用")
            items.append(
                f'<a class="card" href="mac/{quote(n)}">'
                f'<div class="icon macicon" aria-hidden="true">{MAC_ICON}</div>'
                f'<div class="meta"><div class="row"><span class="name">{esc(n)}</span></div>'
                f'<div class="desc">{esc(info)}</div></div></a>')
        mac_cards = "\n".join(items)
        # mac/ 里的说明文档也一起列出来，方便下载者（README.txt / NOTICE.txt）
        docs = "".join(f'<a href="mac/{quote(n)}">{esc(n)}</a> ' for n in ("README.txt", "NOTICE.txt")
                       if os.path.exists(os.path.join(MAC, n)))
        docs_html = f'<p class="fine">安装说明与许可证：{docs}</p>' if docs else ""
        mac_html = f"""
<section>
  <h2>Mac 客户端下载</h2>
  <p class="sectionnote">macOS 上的配套程序，Sileo/Zebra 装不了，直接下载解压使用。</p>
  {mac_cards}
  <p class="fine">需要 macOS 14+ 和 Apple 芯片；第三方动态库已内嵌在包里，不用额外装东西。
  「数据线直控」要 <code>brew install libimobiledevice</code>，「Wi-Fi 直控」要
  <code>brew install --cask tigervnc</code>。没做 Apple 公证，第一次打开可能要在「终端」跑
  <code>xattr -dr com.apple.quarantine /Applications/Mirror17.app</code>。</p>
  {docs_html}
  <p class="fine">镜像直链（主源连不上时用）：<a href="{MIRRORS[1]}mac/{quote(macs[0])}">{esc(MIRRORS[1])}mac/{esc(macs[0])}</a></p>
</section>"""

    CSS = """
:root{--bg:#0d0f13;--panel:#161a21;--border:#282d38;--text:#e9ebef;--sub:#9aa2ad;--code:#0a0c10;--accent:#5b5bd6}
@media (prefers-color-scheme: light){:root{--bg:#f5f6f8;--panel:#ffffff;--border:#e4e6eb;--text:#17181c;--sub:#6d7480;--code:#eef0f4}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--text);
  font:16px/1.65 -apple-system,BlinkMacSystemFont,"PingFang SC","Segoe UI",Roboto,"Helvetica Neue",sans-serif;
  -webkit-font-smoothing:antialiased}
.wrap{max-width:46rem;margin:0 auto;padding:30px 16px 52px}
h1{font-size:1.72rem;line-height:1.25;margin:0 0 6px}
.tagline{margin:0 0 26px;color:var(--sub)}
h2{font-size:.9rem;font-weight:600;letter-spacing:.1em;color:var(--sub);margin:32px 0 12px;text-transform:uppercase}
.panel{background:var(--panel);border:1px solid var(--border);border-radius:16px;padding:18px}
.panel h2{margin:0 0 14px}
.urlrow{display:flex;gap:10px;margin-bottom:14px}
.mainurl{flex:1;min-width:0;display:flex;align-items:center;
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:1.04rem;font-weight:600;
  background:var(--code);border:1px solid var(--border);border-radius:12px;padding:12px 14px;word-break:break-all}
.copy{flex:none;border:1px solid var(--border);background:transparent;color:var(--text);
  border-radius:12px;padding:0 16px;font-size:.92rem;cursor:pointer;font-family:inherit}
.copy:active{transform:translateY(1px)}
.btn{display:inline-block;background:var(--accent);color:#fff;padding:11px 18px;border-radius:12px;
  text-decoration:none;font-weight:600;font-size:.98rem}
.btn:hover{filter:brightness(1.12)}
.mirrors{margin-top:16px;border-top:1px solid var(--border);padding-top:12px}
.mhead{color:var(--sub);font-size:.85rem;margin-bottom:8px}
.mrow{display:flex;gap:10px;align-items:baseline;justify-content:space-between;padding:3px 0}
.mrow code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.8rem;word-break:break-all}
.mrow span{color:var(--sub);font-size:.78rem;flex:none}
code{background:var(--code);padding:.1em .35em;border-radius:6px}
.card{display:flex;align-items:center;gap:14px;background:var(--panel);border:1px solid var(--border);
  border-radius:16px;padding:13px 14px;transition:border-color .15s ease}
.cards .card+.card{margin-top:10px}
a.card{text-decoration:none;color:inherit}
.card:hover{border-color:var(--accent)}
.icon{width:56px;height:56px;border-radius:13px;flex:none;display:block;background:var(--code);object-fit:cover}
.macicon{display:flex;align-items:center;justify-content:center;color:var(--sub)}
.meta{min-width:0;flex:1}
.row{display:flex;align-items:baseline;gap:10px}
.name{font-weight:650;font-size:1.03rem;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ver{color:var(--sub);font-size:.84rem;flex:none}
.desc{color:var(--sub);font-size:.9rem;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sectionnote{color:var(--sub);margin:-4px 0 12px;font-size:.92rem}
.fine{color:var(--sub);font-size:.82rem;line-height:1.75;overflow-wrap:anywhere}
.fine a{color:var(--text)}
.fine code,.warn code{font-size:.9em}
.warn{margin:14px 1px 0;color:var(--sub);font-size:.85rem}
footer{margin-top:40px;border-top:1px solid var(--border);padding-top:16px}
footer small{color:var(--sub);word-break:break-all}
"""
    JS = """function cp(b,t){var d=function(){b.textContent='已复制';
setTimeout(function(){b.textContent='复制'},1200)};
try{navigator.clipboard.writeText(t).then(d,function(){fb(t);d()})}catch(e){fb(t);d()}}
function fb(t){try{var x=document.createElement('textarea');x.value=t;document.body.appendChild(x);
x.select();document.execCommand('copy');document.body.removeChild(x)}catch(e){}}"""

    date = __import__("time").strftime("%Y-%m-%d")
    # 备用地址按 MIRRORS 列表实际长度生成，别写死下标（列表增删会 IndexError）
    _labels = ["GitHub Pages · 海外快", "Cloudflare Pages · 备用", "备用", "备用"]
    mirror_rows = "\n".join(
        f'    <div class="mrow"><code>{esc(u)}</code><span>{_labels[i - 1]}</span></div>'
        for i, u in enumerate(MIRRORS[1:], start=1))
    open(os.path.join(ROOT, "index.html"), "w", encoding="utf-8").write(f"""<!doctype html>
<html lang="zh-CN">
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark light">
<title>{esc(LABEL)}</title>
<style>{CSS}</style>
<div class="wrap">
<header>
  <h1>{esc(LABEL)}</h1>
  <p class="tagline">{esc(DESCRIPTION)}</p>
</header>

<section class="panel">
  <h2>添加软件源</h2>
  <div class="urlrow">
    <code class="mainurl">{esc(MIRRORS[0])}</code>
    <button class="copy" type="button" onclick="cp(this,'{MIRRORS[0]}')">复制</button>
  </div>
  <a class="btn" href="sileo://source/{MIRRORS[0]}">添加到 Sileo</a>
  <div class="mirrors">
    <div class="mhead">备用地址 —— 主源连不上时在「添加源」里手动粘贴：</div>
{mirror_rows}
  </div>
  <p class="warn">⚠️ 添加源时只粘上面这种纯网址，不要粘 <code>sileo://</code> 开头的一键链接（那是给浏览器点开的）。</p>
</section>

<section>
  <h2>软件包 · {len(cards)}</h2>
  <div class="cards">
{pkg_html}
  </div>
</section>
{mac_html}
<footer><small>本页由 build_repo.py 生成 · 更新 {date} · 主源 {esc(MIRRORS[0])}</small></footer>
</div>
<script>{JS}</script>
</html>""")



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
