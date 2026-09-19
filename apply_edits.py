#!/usr/bin/env python3
"""把二级页 ✏️ 编辑模式导出的 JSON 合进 meta/<包名>.json。

用法:
  python3 apply_edits.py ~/Downloads/com.a0.noswipe.edits.json
  python3 apply_edits.py - < edits.json          # 从 stdin
  python3 apply_edits.py --self-test

只改 name / desc / info，其余键（depends、buttons…）原样保留；旧文件备份成 .json.bak。
改完自己跑：python3 build_repo.py && ./deploy.sh
"""
import json, os, sys, difflib

ROOT = os.path.dirname(os.path.abspath(__file__))
META = os.path.join(ROOT, "meta")
KEYS = ("name", "desc", "info")


def merge(d, meta_dir=META, dry=False):
    pkg = (d.get("package") or "").strip()
    if not pkg:
        raise SystemExit("✘ 这份 JSON 里没有 package 字段（要用二级页「导出 JSON」出来的文件）")
    path = os.path.join(meta_dir, pkg + ".json")
    if not os.path.exists(path):
        raise SystemExit(f"✘ 找不到 meta/{pkg}.json —— 包名对不上？")
    old = json.load(open(path, encoding="utf-8"))
    new = dict(old)
    changed = []
    for k in KEYS:
        if k == "name" and not d.get("nameChanged"):
            continue                      # 编辑页没改标题时也会带上 name，别拿它覆盖 meta
        if k in d and d[k] != old.get(k):
            new[k] = d[k]
            changed.append(k)
    if not changed:
        print(f"= {pkg}: 和源里一样，没变化")
        return []
    if not dry:
        with open(path + ".bak", "w", encoding="utf-8") as fh:
            json.dump(old, fh, ensure_ascii=False, indent=1)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(new, fh, ensure_ascii=False, indent=1)
            fh.write("\n")
    print(f"✔ {pkg}: 更新 {'、'.join(changed)}" + ("（dry-run，没写）" if dry else f" → 备份 meta/{pkg}.json.bak"))
    if "name" in changed:
        print(f"  name: {old.get('name')!r} → {new.get('name')!r}")
    if "info" in changed:
        for k in sorted(set(old.get("info") or {}) | set(new.get("info") or {})):
            a, b = (old.get("info") or {}).get(k), (new.get("info") or {}).get(k)
            if a != b:
                print(f"  info[{k}]: {a!r} → {b!r}")
    if "desc" in changed:
        for line in difflib.unified_diff((old.get("desc") or "").splitlines(),
                                         (new.get("desc") or "").splitlines(),
                                         "旧 desc", "新 desc", lineterm="", n=1):
            print("  " + line)
    return changed


def self_test():
    import shutil, tempfile
    tmp = tempfile.mkdtemp()
    try:
        md = os.path.join(tmp, "meta")
        os.makedirs(md)
        p = os.path.join(md, "com.a0.demo.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({"desc": "旧文字\n\n- 一条", "info": {"版本": "1.0"}, "depends": "ellekit"}, fh, ensure_ascii=False)
        edits = {"package": "com.a0.demo", "name": "Demo", "nameChanged": True,
                 "desc": "新文字\n\n- 改过的条目", "info": {"版本": "1.1"}}
        ch = merge(dict(edits), meta_dir=md)
        got = json.load(open(p, encoding="utf-8"))
        assert set(ch) == {"name", "desc", "info"}, ch
        assert got["desc"] == "新文字\n\n- 改过的条目", got
        assert got["info"] == {"版本": "1.1"}, got
        assert got["depends"] == "ellekit", "无关的键必须原样保留"
        assert os.path.exists(p + ".bak"), "必须留备份"
        assert merge(dict(edits), meta_dir=md) == [], "重复应用应当报告无变化（幂等）"
        # 标题没改过时，导出里带的 name 不该覆盖 meta
        assert merge({"package": "com.a0.demo", "name": "别的名字", "nameChanged": False,
                      "desc": got["desc"], "info": got["info"]}, meta_dir=md) == []
        assert json.load(open(p, encoding="utf-8"))["name"] == "Demo", "标题没改就不该动 name"
        try:
            merge({"desc": "没有包名"}, meta_dir=md)
            raise AssertionError("缺 package 时必须报错")
        except SystemExit:
            pass
        print("self-test PASS：合并 / 保留其它键 / 备份 / 幂等 / 缺字段报错 都正常")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        raise SystemExit(__doc__)
    if args[0] == "--self-test":
        self_test()
    else:
        for f in args:
            data = json.load(sys.stdin if f == "-" else open(f, encoding="utf-8"))
            merge(data)
        print("\n下一步：python3 build_repo.py && ./deploy.sh")
