#!/usr/bin/env python3
"""把 debs/ 里的 .deb 编成 APT 源(Sileo/Cydia/Zebra 通用)。

用法:  python3 build_repo.py          # 生成 Packages / Packages.bz2 / Packages.gz / Release
      python3 build_repo.py --check   # 只校验已生成的文件

付费包: 把包名(控制文件里的 Package:)一行一个写进 paid.txt，
       生成时会自动加 Tag: cydia::commercial (Sileo 认这个才会走购买流程)。
新版本: 把新 .deb 丢进 debs/ 再跑一次即可，同一个包名多版本没问题，装的时候取最高版。
"""
import bz2, gzip, hashlib, io, os, sys, tarfile

ROOT = os.path.dirname(os.path.abspath(__file__))
DEBS = os.path.join(ROOT, "debs")
PAID = os.path.join(ROOT, "paid.txt")

# 源的身份信息 —— 改成你自己的
ORIGIN = "a0"
LABEL = "a0 repo"
DESCRIPTION = "a0 tweaks repo"
ARCHS = "iphoneos-arm iphoneos-arm64"


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
        if d["Package"] in paid:
            tags = [t.strip() for t in d.get("Tag", "").split(",") if t.strip()]
            if "cydia::commercial" not in tags:
                tags.append("cydia::commercial")
            d["Tag"] = ", ".join(tags)

        head = ["Package", "Name", "Version", "Architecture", "Description", "Author",
                "Maintainer", "Section", "Depends", "Pre-Depends", "Conflicts", "Replaces",
                "Provides", "Tag", "Icon", "Depiction", "SileoDepiction"]
        out = [f"{k}: {d[k]}" for k in head if k in d]
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
    text = build_packages()
    blob = text.encode()
    for name, data in [("Packages", blob), ("Packages.bz2", bz2.compress(blob)),
                       ("Packages.gz", gzip.compress(blob))]:
        open(os.path.join(ROOT, name), "wb").write(data)

    lines = [f"Origin: {ORIGIN}", f"Label: {LABEL}", "Suite: stable", "Version: 1.0",
             "Codename: ios", f"Architectures: {ARCHS}", "Components: main",
             f"Description: {DESCRIPTION}", "Date: " + __import__("email.utils", fromlist=["x"]).formatdate(usegmt=True)]
    for algo, fn in [("MD5Sum", hashlib.md5), ("SHA256", hashlib.sha256)]:
        lines.append(f"{algo}:")
        for name in ["Packages", "Packages.bz2", "Packages.gz"]:
            data = open(os.path.join(ROOT, name), "rb").read()
            lines.append(f" {fn(data).hexdigest()} {len(data)} {name}")
    open(os.path.join(ROOT, "Release"), "w").write("\n".join(lines) + "\n")
    open(os.path.join(ROOT, ".nojekyll"), "w").write("")


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
    print("PASS" if ok else "FAILED", f"— {len(stanzas)} 个包, {os.path.getsize(os.path.join(ROOT, 'Packages'))} 字节")
    return ok


if __name__ == "__main__":
    if "--check" not in sys.argv:
        write_all()
    sys.exit(0 if check() else 1)
