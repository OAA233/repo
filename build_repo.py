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
PKG = os.path.join(ROOT, "pkg")             # 网页版详情页（给浏览器看，Sileo 不读它）
ZSTD = shutil.which("zstd") or "/opt/homebrew/bin/zstd"

# 源的身份信息 —— 改成你自己的
ORIGIN = "Wangyuan's Repo"
LABEL = "Wangyuan's Repo"
DESCRIPTION = "Wangyuan's rootless tweaks (iOS 17) · 王源的无根越狱插件源"
ARCHS = "iphoneos-arm iphoneos-arm64"

# 包里 control 写的还是旧占位名，仓库侧统一显示成这个（改 deb 要重新打包，先不动 deb）
AUTHOR = "wangyuan"
SPONSOR_DIR = os.path.join(ROOT, "sponsor")   # 赞赏页；微信/支付宝收款码放这儿（wechat.png / alipay.png）
SPONSOR = True                                # 各包的介绍页/详情页要不要挂「赞赏支持」入口
SPONSOR_LABEL = "赞赏支持（微信 / 支付宝）"
SPONSOR_MAIL = "oaawallet@gmail.com"
# 这些旧名字一律在源侧改写成 AUTHOR（deb 本体不动）
LEGACY_AUTHORS = ("a0", "", "王", "Wang", "wang", "wangyuan")

# 索引类文件的镜像：必须和主源**真的同步**。jsDelivr 对分支(@main)缓存不认 purge，
# 实测会出现三个镜像三个版本的惨案（主源 7.12 / cdn 7.13 / fastly 7.15），所以索引不用它。
MIRRORS = ["https://wangyuan-repo.pages.dev/",     # 主源（Cloudflare Pages）
           "https://oaa233.github.io/repo/"]        # 同一份 push 重建，天然同步
# 图标/介绍页/贴图也走主源：jsDelivr 对 @main 不认 purge，介绍页会一直拿旧缓存。
# URL 全部带内容哈希(?v=)，改完刷新源立即生效。国内裸网打不开 pages.dev 时，
# 临时把 ICON_BASE 改回 jsDelivr 并手动 purge。
ICON_BASE = MIRRORS[0]
DEP_BASE = ICON_BASE
# False = Sileo 看原生介绍页（depictions/*.json，好看、快）；
# True  = 连 Sileo 也去看网页版二级页（pkg/*.html，就是你在编辑模式里改的那个）
WEB_DEPICTION = False


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


def resolve_buttons(meta):
    """meta 里的 buttons → [{title, raw, external, tintColor}]。
    raw 是仓库内的相对路径（"mac:" 自动指向 mac/ 里最新的那个下载件），
    调用方自己决定前缀：Sileo 介绍页用 DEP_BASE，网页用 MIRRORS[0]。"""
    out = []
    for b in (meta.get("buttons") or []):
        raw = (b.get("url") or "").strip()
        if raw == "mac:":                        # 自动指向 mac/ 里最新的那个
            raw = "mac/" + (newest_mac() or "")
        if not raw:
            continue
        out.append({"title": b.get("title", ""), "raw": raw,
                    "external": bool(b.get("external", True)),
                    "tintColor": b.get("tintColor", "#5b5bd6")})
    return out


def sponsor_qrs():
    """赞赏页上的收款码：[（标签, 绝对 URL）]，只列真实存在的图片。"""
    out = []
    for key, label in (("wechat", "微信 · 扫一扫→相册"), ("alipay", "支付宝 · 长按识别")):
        p = os.path.join(SPONSOR_DIR, key + ".png")
        if os.path.exists(p):
            v = hashlib.md5(open(p, "rb").read()).hexdigest()[:8]
            out.append((label, f"{MIRRORS[0]}sponsor/{key}.png?v={v}"))
    return out


def sponsor_on():
    """有收款码（至少一张）才对外挂赞赏入口 —— 免得访客看到还没配好的页面。"""
    return SPONSOR and bool(sponsor_qrs())


def write_sponsor_page():
    """生成 sponsor/index.html（赞赏页）。没放收款码也能生成，只是那一格不显示。"""
    qrs = sponsor_qrs()
    cards = "".join(
        f'<figure><img src="{esc_html(u)}" alt="{esc_html(l)}收款码"><figcaption>{esc_html(l)}</figcaption></figure>'
        for l, u in qrs)
    if not cards:
        cards = ('<p class="fine">（这里会显示微信 / 支付宝收款码：把两张图放到仓库的 '
                 '<code>sponsor/wechat.png</code> 和 <code>sponsor/alipay.png</code> 即可）</p>')
    html = f"""<!doctype html>
<html lang="zh-CN">
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark light">
<title>赞赏支持 · {esc_html(LABEL)}</title>
<style>{PKG_CSS}
.qrs{{display:flex;flex-wrap:wrap;gap:22px;margin:20px 0}}
.qrs figure{{margin:0;text-align:center}}
.qrs img{{width:260px;max-width:72vw;border-radius:14px;border:1px solid var(--border);display:block}}
.qrs figcaption{{color:var(--sub);font-size:.9rem;margin-top:8px}}
</style>
<div class="wrap">
<p class="backlink"><a href="../index.html">← 返回源首页</a></p>
<h1>赞赏支持</h1>
<p class="tagline">请我喝杯牛奶 🥛</p>
<div class="qrs">{cards}</div>
<p class="fine"><strong>微信</strong>：保存本图 → 打开微信「扫一扫」→ 右下角「相册」→ 选这张图，就能直接进付款页。<br>
（微信 8.0.32 之后禁止长按识别<strong>个人收款码</strong>，长按没反应是微信的限制，不是页面问题。）<br>
<strong>支付宝</strong>：长按这张码选「识别图中二维码」，或用支付宝「扫一扫」直接扫。</p>
</div>
</html>"""
    os.makedirs(SPONSOR_DIR, exist_ok=True)
    with open(os.path.join(SPONSOR_DIR, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(html)
    return len(qrs)


def build_depiction(stanza, meta):
    pkg = stanza["Package"]
    views = [{"class": "DepictionHeaderView", "title": stanza.get("Name", pkg)},
             {"class": "DepictionSubheaderView",
              "title": f"{stanza.get('Version', '?')} · {stanza.get('Author', AUTHOR)}"}]
    shots = []
    for n in shot_files(pkg):
        v = hashlib.md5(open(os.path.join(SHOTS, pkg, n), "rb").read()).hexdigest()[:8]
        shots.append({"url": f"{DEP_BASE}shots/{pkg}/{quote(n)}?v={v}",
                      "accessibilityText": "", "video": False})
    if shots:
        views.append({"class": "DepictionScreenshotsView", "itemCornerRadius": 8,
                      "itemSize": {"x": 260, "y": 563}, "screenshots": shots})
    if meta.get("desc"):
        views.append({"class": "DepictionMarkdownView", "markdown": meta["desc"]})
    for k, v in (meta.get("info") or {}).items():
        views.append({"class": "DepictionTableTextView", "title": str(k), "text": str(v)})
    if meta.get("info"):
        views.insert(len(views) - len(meta["info"]), {"class": "DepictionSeparatorView"})
    for b in resolve_buttons(meta):              # 介绍页里的按钮（比如 Mac 客户端下载）
        raw = b["raw"]
        views.append({"class": "DepictionTableButtonView", "title": b["title"],
                      "action": raw if raw.startswith("http") else f"{DEP_BASE}{raw}",
                      "openExternal": b["external"], "tintColor": b["tintColor"]})
    if sponsor_on():                             # 所有包的介绍页底部挂一个赞赏入口
        views.append({"class": "DepictionTableButtonView", "title": "♥ " + SPONSOR_LABEL,
                      "action": f"{MIRRORS[0]}sponsor/", "openExternal": True,
                      "tintColor": "#e08a3c"})
    doc = {"minVersion": "0.4", "class": "DepictionTabView", "tintColor": "#5b5bd6",
           "tabs": [{"class": "DepictionStackView", "tabname": "介绍", "views": views}]}
    banner = os.path.join(SHOTS, pkg, "banner.png")
    if os.path.exists(banner):
        v = hashlib.md5(open(banner, "rb").read()).hexdigest()[:8]
        doc["headerImage"] = f"{DEP_BASE}shots/{pkg}/banner.png?v={v}"
    return doc


def has_depiction(pkg):
    return bool(load_meta(pkg)) or bool(shot_files(pkg)) or \
        os.path.exists(os.path.join(SHOTS, pkg, "banner.png"))


def esc_html(s):
    return __import__("html").escape(str(s))


def md_inline(s):
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)


def md_to_html(md):
    """desc 用的 markdown 子集（**粗体** / - 列表 / ## ### 标题 / 空行分段）→ HTML。"""
    out, in_list = [], False
    for line in md.split("\n"):
        if line.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{md_inline(esc_html(line[2:]))}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if not line.strip():
            continue
        if line.startswith("### "):
            out.append(f"<h3>{md_inline(esc_html(line[4:]))}</h3>")
        elif line.startswith("## "):
            out.append(f"<h2>{md_inline(esc_html(line[3:]))}</h2>")
        else:
            out.append(f"<p>{md_inline(esc_html(line))}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


PKG_CSS = """
:root{--bg:#0d0f13;--panel:#161a21;--border:#282d38;--text:#e9ebef;--sub:#9aa2ad;--accent:#5b5bd6}
@media (prefers-color-scheme: light){:root{--bg:#f5f6f8;--panel:#ffffff;--border:#e4e6eb;--text:#17181c;--sub:#6d7480}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
  font:16px/1.7 -apple-system,BlinkMacSystemFont,"PingFang SC","Segoe UI",Roboto,"Helvetica Neue",sans-serif;
  -webkit-font-smoothing:antialiased}
.wrap{max-width:46rem;margin:0 auto;padding:28px 16px 56px}
.backlink a{color:var(--sub);text-decoration:none;font-size:.9rem}
h1{font-size:1.6rem;margin:6px 0 4px}
.tagline{color:var(--sub);margin:0 0 20px}
.shots{display:flex;gap:12px;overflow-x:auto;padding:4px 0 18px}
.shots img{height:320px;border-radius:12px;border:1px solid var(--border);display:block}
.dlbtns{display:flex;flex-wrap:wrap;gap:10px;margin:2px 0 18px}
.dlbtn{display:inline-block;background:var(--accent);color:#fff;text-decoration:none;
  padding:11px 16px;border-radius:12px;font-weight:600;font-size:.95rem}
.dlbtn+.dlbtn{background:transparent;color:var(--text);border:1px solid var(--border);font-weight:500}
.prose h2,.prose h3{margin:1.4em 0 .5em}
.prose p{margin:.8em 0}
.prose ul{margin:.6em 0;padding-left:1.3em}
.prose li{margin:.35em 0}
table.info{border-collapse:collapse;width:100%;margin-top:26px}
table.info th,table.info td{border-bottom:1px solid var(--border);text-align:left;padding:9px 4px;font-size:.95em;font-weight:normal}
table.info th{color:var(--sub);width:7em}
/* ---------- ✏️ 编辑模式（草稿只存本机浏览器 localStorage，不上传） ---------- */
.editbtn{display:none;position:fixed;right:14px;bottom:14px;z-index:20;background:var(--accent);color:#fff;border:0;
  border-radius:999px;padding:11px 16px;font-size:15px;box-shadow:0 6px 20px rgba(0,0,0,.35);cursor:pointer}
body.editor .editbtn{display:block}
.editbtn.dirty{background:#c98a12}
.toolbar{display:none;position:fixed;left:0;right:0;bottom:0;z-index:19;background:var(--panel);
  border-top:1px solid var(--border);padding:9px 12px;gap:8px;flex-wrap:wrap;align-items:center}
body.editing .toolbar{display:flex}
body.editing{padding-bottom:120px}
body.editing .prose,body.editing .info th,body.editing .info td{background:rgba(91,91,214,.10);
  border-radius:6px;outline:1px dashed rgba(91,91,214,.5);min-height:1.3em}
body.editing .prose *{outline:0}
.toolbar button{background:var(--accent);color:#fff;border:0;border-radius:8px;padding:9px 13px;font-size:14px;cursor:pointer}
.toolbar button.ghost{background:transparent;color:var(--sub);border:1px solid var(--border)}
.toolbar .hint{color:var(--sub);font-size:12.5px;margin-left:auto}
.rowdel{display:none;background:none;border:0;color:#e5534b;font-size:15px;cursor:pointer}
body.editing .rowdel{display:inline}
.banner{display:none;margin:0 0 16px;padding:9px 11px;border-radius:8px;font-size:13.5px;
  background:rgba(255,180,0,.13);border:1px solid rgba(255,180,0,.4);color:var(--text)}
body.editing .banner{display:block}
"""


PKG_EDIT_JS = r"""
(function(){
try{
  const PKG = __PKG__, KEY = "wangyuan-edit:" + PKG;
  const btn = document.getElementById("editbtn"), hint = document.getElementById("hint");
  const prose = document.querySelector(".prose"), info = document.querySelector("table.info");
  const h1 = document.querySelector("h1");
  const NAME0 = h1 ? h1.innerText.trim() : "";   // 原始标题，没改就不把 name 带进导出结果
  const esc = s => String(s).replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));

  /* DOM → markdown：只覆盖 desc 用到的那套语法（**粗体** / - 列表 / ## ### / 段落） */
  function inlineHtml(n){
    return n.innerHTML.replace(/<br\s*\/?>/gi, "\n")
      .replace(/<strong[^>]*>([\s\S]*?)<\/strong>/gi, "**$1**")
      .replace(/<[^>]+>/g, "").replace(/&nbsp;/g, " ")
      .replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").trim();
  }
  function toMD(){
    if(!prose) return "";
    const out = [];
    prose.childNodes.forEach(n => {
      if(n.nodeType === 3){ if(n.textContent.trim()) out.push("", n.textContent.trim()); return; }
      if(n.nodeType !== 1) return;
      const tag = n.tagName.toLowerCase();
      if(tag === "ul" || tag === "ol"){ [...n.children].forEach(li => out.push("- " + inlineHtml(li))); out.push(""); }
      else if(tag === "h2") out.push("## " + inlineHtml(n), "");
      else if(tag === "h3") out.push("### " + inlineHtml(n), "");
      else out.push(inlineHtml(n), "");
    });
    return out.join("\n").replace(/\n{3,}/g, "\n\n").trim();
  }
  function toInfo(){
    const o = {};
    if(info) info.querySelectorAll("tr").forEach(tr => {
      const c = tr.children;
      if(c.length < 2) return;
      const k = c[0].innerText.trim(), v = c[1].innerText.trim();
      if(k) o[k] = v;
    });
    return o;
  }
  function collect(){
    const nm = h1 ? h1.innerText.trim() : "";
    return { package: PKG, name: nm, nameChanged: nm !== NAME0,
      desc: toMD(), info: toInfo(), proseHTML: prose ? prose.innerHTML : "",
      editedAt: new Date().toLocaleString("sv-SE").slice(0, 16) };
  }
  function save(){
    try{ localStorage.setItem(KEY, JSON.stringify(collect())); }
    catch(e){ hint.textContent = "保存失败：" + e.message; return; }
    document.body.classList.add("hasdraft"); btn.classList.add("dirty");
    hint.textContent = "草稿存在这台浏览器（没上传）";
  }
  function load(){ try{ return JSON.parse(localStorage.getItem(KEY) || "null"); }catch(e){ return null; } }
  function applyDraft(d){
    if(d.proseHTML && prose) prose.innerHTML = d.proseHTML;
    if(d.info && info){
      info.innerHTML = Object.entries(d.info).map(([k, v]) =>
        '<tr><th>' + esc(k) + '</th><td>' + esc(v) + '</td><td><button class="rowdel" title="删除这行">✕</button></td></tr>').join("");
    }
    document.body.classList.add("hasdraft");
    btn.classList.add("dirty");
  }
  function setEditable(on){
    document.body.classList.toggle("editing", on);
    if(prose) prose.contentEditable = on ? "true" : "false";
    if(h1) h1.contentEditable = on ? "true" : "false";
    if(info) info.querySelectorAll("th,td").forEach(c => { if(!c.querySelector(".rowdel")) c.contentEditable = on ? "true" : "false"; });
    btn.textContent = on ? "✅ 编辑中" : (load() ? "✏️ 编辑（有草稿）" : "✏️ 编辑");
    hint.textContent = on ? "点文字直接改；改完「导出 JSON」发我" : "";
  }
  function addRow(){
    if(!info) return;
    const tr = document.createElement("tr");
    tr.innerHTML = '<th contenteditable="true"></th><td contenteditable="true"></td><td><button class="rowdel">✕</button></td>';
    info.appendChild(tr); save(); (tr.querySelector("th")).focus();
  }
  function download(){
    const b = new Blob([JSON.stringify(collect(), null, 1)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(b); a.download = PKG + ".edits.json"; a.click();
    hint.textContent = "已导出 " + PKG + ".edits.json —— 发给我";
  }
  function copyJSON(){
    const s = JSON.stringify(collect(), null, 1);
    const fallback = () => {
      const ta = document.createElement("textarea"); ta.value = s; document.body.appendChild(ta); ta.select();
      try{ document.execCommand("copy"); hint.textContent = "已复制，直接粘给我"; }
      catch(e){ hint.textContent = "复制失败，用「导出 JSON」"; }
      ta.remove();
    };
    if(navigator.clipboard && navigator.clipboard.writeText)
      navigator.clipboard.writeText(s).then(() => hint.textContent = "已复制，直接粘给我", fallback);
    else fallback();
  }
  let timer = null;
  document.addEventListener("input", () => {
    if(!document.body.classList.contains("editing")) return;
    clearTimeout(timer); timer = setTimeout(save, 500);
  });
  document.addEventListener("click", e => {
    if(e.target.classList && e.target.classList.contains("rowdel")){ e.target.closest("tr").remove(); save(); }
  });
  btn.addEventListener("click", () => setEditable(!document.body.classList.contains("editing")));
  document.getElementById("baddrow").addEventListener("click", addRow);
  document.getElementById("bexp").addEventListener("click", download);
  document.getElementById("bcopy").addEventListener("click", copyJSON);
  document.getElementById("breset").addEventListener("click", () => {
    if(confirm("清掉本地草稿，恢复线上原文？")){ localStorage.removeItem(KEY); location.reload(); }
  });
  document.getElementById("bexit").addEventListener("click", () => setEditable(false));

  // 编辑入口默认对访客隐藏：只有你自己在本浏览器打开过一次 #edit 之后才会出现 ✏️
  const FLAG = "wangyuan-editor";
  try{
    if(location.hash === "#edit") localStorage.setItem(FLAG, "1");
    if(location.hash === "#editoff") localStorage.removeItem(FLAG);
  }catch(e){}
  let isEditor = false;
  try{ isEditor = localStorage.getItem(FLAG) === "1"; }catch(e){}
  if(isEditor) document.body.classList.add("editor");
  const draft = load();
  if(draft) applyDraft(draft);
  if(isEditor && location.hash === "#edit") setEditable(true);
}catch(e){ console.error("edit mode failed:", e); }
})();
"""


def build_pkg_page(d, meta, doc):
    """把介绍页（depiction）渲染成给人看的静态网页，落地页卡片点开就是它。带 ✏️ 编辑模式。"""
    pkg = d["Package"]
    shots = []
    for t in doc.get("tabs", []):
        for v in t.get("views", []):
            if v.get("class") == "DepictionScreenshotsView":
                shots = [s["url"] for s in v["screenshots"]]
    shots_html = "".join(f'<img src="{esc_html(u)}" alt="">' for u in shots)
    info_rows = "".join(
        f"<tr><th>{esc_html(k)}</th><td>{esc_html(v)}</td></tr>"
        for k, v in (meta.get("info") or {}).items())
    edit_js = PKG_EDIT_JS.replace("__PKG__", json.dumps(pkg))
    btns_html = "".join(
        f'<a class="dlbtn" href="{esc_html(b["raw"] if b["raw"].startswith("http") else MIRRORS[0] + b["raw"])}">'
        f'{esc_html(b["title"])}</a>' for b in resolve_buttons(meta))
    if sponsor_on():
        btns_html += f'<a class="dlbtn" href="{MIRRORS[0]}sponsor/">♥ {esc_html(SPONSOR_LABEL)}</a>'
    return f"""<!doctype html>
<html lang="zh-CN">
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark light">
<title>{esc_html(d["Name"])} · {LABEL}</title>
<style>{PKG_CSS}</style>
<div class="wrap">
<p class="backlink"><a href="../index.html">← 返回源首页</a></p>
<div class="banner">你在编辑本页 —— 改的是你自己浏览器里的草稿，没上传。改完点「导出 JSON」或「复制 JSON」发给我，我合进源里再发布。</div>
<h1>{esc_html(d["Name"])}</h1>
<p class="tagline">{esc_html(d.get("Version", "?"))} · {esc_html(d.get("Author", AUTHOR))}</p>
{f'<div class="shots">{shots_html}</div>' if shots else ""}
{f'<div class="dlbtns">{btns_html}</div>' if btns_html else ""}
<div class="prose">{md_to_html(meta.get("desc") or "")}</div>
{('<table class="info">' + info_rows + "</table>") if info_rows else ""}
</div>
<button class="editbtn" id="editbtn">✏️ 编辑</button>
<div class="toolbar">
  <button id="bexp">导出 JSON</button>
  <button id="bcopy" class="ghost">复制 JSON</button>
  <button id="baddrow" class="ghost">+ 表格一行</button>
  <button id="breset" class="ghost">还原原始</button>
  <button id="bexit" class="ghost">退出编辑</button>
  <span class="hint" id="hint"></span>
</div>
<script>{edit_js}</script>
</html>"""


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
        dep_ver = ""
        if has_depiction(d["Package"]):
            os.makedirs(DEPICTIONS, exist_ok=True)
            doc = build_depiction(d, meta)
            doc_json = json.dumps(doc, ensure_ascii=False, indent=1)
            with open(os.path.join(DEPICTIONS, d["Package"] + ".json"), "w", encoding="utf-8") as fh:
                fh.write(doc_json)
            # URL 带内容哈希：介绍页一变 URL 就变，绕开 Sileo 与 CDN 的旧缓存
            dep_ver = "?v=" + hashlib.md5(doc_json.encode()).hexdigest()[:8]
            os.makedirs(PKG, exist_ok=True)
            with open(os.path.join(PKG, d["Package"] + ".html"), "w", encoding="utf-8") as fh:
                fh.write(build_pkg_page(d, meta, doc))
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
            # Zebra / Cydia / 老客户端读 Depiction（网页版二级页）
            out.append(f"Depiction: {MIRRORS[0]}pkg/{quote(d['Package'])}.html")
            if not WEB_DEPICTION:
                # Sileo 读原生介绍页，且官方文档写明 SileoDepiction 优先于 Depiction；
                # 想让 Sileo 也去读网页版二级页，把 WEB_DEPICTION 改成 True 即可。
                out.append(f"SileoDepiction: {DEP_BASE}depictions/{d['Package']}.json{dep_ver}")
            if os.path.exists(os.path.join(SHOTS, d["Package"], "banner.png")):
                bv = hashlib.md5(open(os.path.join(SHOTS, d["Package"], "banner.png"), "rb").read()).hexdigest()[:8]
                out.append(f"Header: {DEP_BASE}shots/{d['Package']}/banner.png?v={bv}")
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
    shutil.rmtree(PKG, ignore_errors=True)          # 同上：网页版详情页
    _qrs = write_sponsor_page()                     # 赞赏页（收款码放 sponsor/ 里）
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
        cards.append((d["Name"], d["Version"], d["Description"].splitlines()[0], icon, d["Package"]))
    def _card(name, ver, desc, icon, pid):
        card = (f'<a class="card" href="pkg/{quote(pid)}.html">'
                f'<img class="icon" src="{esc(icon)}" alt="" width="56" height="56">'
                f'<div class="meta"><div class="row"><span class="name">{esc(name)}</span>'
                f'<span class="ver">{esc(ver)}</span></div>'
                f'<div class="desc" title="{esc(desc)}">{esc(desc)}</div></div></a>')
        btns = resolve_buttons(load_meta(pid))     # 有 buttons 的包（如 Mirror17）在卡片下方直接给下载
        if not btns:
            return card
        row = "".join(
            f'<a class="dlbtn" href="{esc(b["raw"] if b["raw"].startswith("http") else MIRRORS[0] + b["raw"])}">'
            f'⬇ {esc(b["title"])}</a>' for b in btns)
        return f'<div class="cardwrap">{card}<div class="cardbtns">{row}</div></div>'

    pkg_html = "".join(_card(*c) for c in cards)

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
.cards>*+*{margin-top:10px}
.cardbtns{display:flex;flex-wrap:wrap;gap:8px;padding:9px 4px 0 84px}
.dlbtn{display:inline-block;border:1px solid var(--border);background:var(--panel);color:var(--text);
  text-decoration:none;border-radius:10px;padding:7px 12px;font-size:.86rem}
.dlbtn:hover{border-color:var(--accent)}
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
    foot_sponsor = ' · <a href="sponsor/" style="color:inherit">♥ 赞赏支持</a>' if sponsor_on() else ""
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
<footer><small>本页由 build_repo.py 生成 · 更新 {date} · 主源 {esc(MIRRORS[0])} {foot_sponsor}</small></footer>
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
