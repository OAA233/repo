#!/usr/bin/env python3
"""把用户在各浏览器里用 ✏️ 编辑模式改的草稿（localStorage）读出来、合并进 meta/。
- 扫 Chrome / Brave / Chromium / Edge 的 Local Storage leveldb
- 每个包取最大的那份（= 最新最全）
- 合并用 apply_edits.merge（幂等：没变会报「没变化」）
用法：python3 pull_drafts.py [--dry]
"""
import glob, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) or '.')
import apply_edits

ROOTS = [
    "~/Library/Application Support/Google/Chrome/*/Local Storage/leveldb",
    "~/Library/Application Support/BraveSoftware/Brave-Browser/*/Local Storage/leveldb",
    "~/Library/Application Support/Chromium/*/Local Storage/leveldb",
    "~/Library/Application Support/Microsoft Edge/*/Local Storage/leveldb",
    "~/Library/Application Support/Arc/*/Local Storage/leveldb",
]
DRY = "--dry" in sys.argv


def scan():
    drafts = {}
    for pat in ROOTS:
        for d in glob.glob(os.path.expanduser(pat)):
            for f in glob.glob(d + "/*"):
                if not os.path.isfile(f):
                    continue
                try:
                    b = open(f, "rb").read()
                except OSError:
                    continue
                for m in re.finditer(rb"wangyuan-edit:com\.[a-z0-9._-]+", b):
                    key = m.group(0).decode()
                    tail = b[m.end():m.end() + 80000]
                    for enc in ("utf-16-le", "utf-8"):
                        # 直接在字节里找编码后的 JSON 头，避免 UTF-16 对齐问题
                        idx = tail.find('{"package"'.encode(enc))
                        if idx < 0:
                            continue
                        txt = tail[idx:idx + 80000].decode(enc, errors="ignore")
                        i = txt.find('{"package"')
                        depth = 0
                        for j, ch in enumerate(txt[i:]):
                            if ch == "{":
                                depth += 1
                            elif ch == "}":
                                depth -= 1
                                if depth == 0:
                                    try:
                                        d = json.loads(txt[i:i + j + 1])
                                    except Exception:
                                        break
                                    d["_src"] = os.path.basename(f)
                                    prev = drafts.get(key)
                                    if not prev or len(json.dumps(d)) > len(json.dumps(prev)):
                                        drafts[key] = d
                                    break
                        break
    return drafts


drafts = scan()
print(f"浏览器里找到 {len(drafts)} 个包的草稿：")
changed = 0
for key, d in sorted(drafts.items()):
    pkg = key.split(":", 1)[1]
    print(f"\n--- {pkg}   (editedAt {d.get('editedAt')}, 来自 {d['_src']})")
    res = apply_edits.merge(d, dry=DRY)
    changed += len(res)
print(f"\n{'（dry-run）' if DRY else ''}共 {changed} 处字段变化")
if not DRY and changed:
    print("下一步：python3 build_repo.py && ./deploy.sh")
