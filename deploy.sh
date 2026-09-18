#!/usr/bin/env bash
# 部署到 Cloudflare Pages。第一次要先跑一次： npx wrangler login
# 用法: ./deploy.sh
set -euo pipefail
cd "$(dirname "$0")"

PROJECT=wangyuan-repo   # 上线地址就是 https://$PROJECT.pages.dev/

python3 build_repo.py

# 只把这些文件传上去：源码、脚本、paid.txt 留在本地
rm -rf .dist
mkdir -p .dist
for f in Packages Packages.bz2 Packages.gz Packages.zst Release index.html 404.html CydiaIcon.png README.md .nojekyll; do
  [ -f "$f" ] && cp "$f" .dist/
done
cp -R debs icons depictions shots .dist/
[ -d mac ] && cp -R mac .dist/    # Mac 客户端 zip 之类的普通下载件（可选）

# 传之前先在本地当静态服务器验一遍（Packages/Release/deb/图标是否齐全）
python3 - <<'EOF'
import http.server, socketserver, threading, urllib.request, bz2, hashlib, re, os
os.chdir(".dist")
srv = socketserver.TCPServer(("127.0.0.1", 0), http.server.SimpleHTTPRequestHandler)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
get = lambda p: urllib.request.urlopen(f"http://127.0.0.1:{port}/{p}", timeout=10).read()
pkgs = get("Packages")
assert bz2.decompress(get("Packages.bz2")) == pkgs, "Packages.bz2 与 Packages 不一致"
assert get("Release"), "Release 缺失"
for stanza in pkgs.decode().split("\n\n"):
    if not stanza.strip():
        continue
    d = dict(re.findall(r"^([A-Za-z0-9-]+): (.*)$", stanza, re.M))
    blob = get(d["Filename"])
    assert hashlib.sha256(blob).hexdigest() == d["SHA256"], f"{d['Package']} deb 哈希对不上"
    icon = "icons/" + d["Icon"].rsplit("/", 1)[1].split("?")[0]   # 图标可能不在主源上，只取文件名本地验（?v= 是缓存版本号）
    assert get(icon), f"{d['Package']} 图标拉不到"
    if "SileoDepiction" in d:
        assert get("depictions/" + d["SileoDepiction"].rsplit("/", 1)[1]), f"{d['Package']} 介绍页拉不到"
    if "Header" in d:
        assert get("shots/" + d["Package"] + "/banner.png"), f"{d['Package']} 顶图拉不到"
    for url in re.findall(r'"url": "([^"]+)"', (get("depictions/" + d["Package"] + ".json").decode()
                                               if "SileoDepiction" in d else "")):
        assert get("shots/" + d["Package"] + "/" + url.rsplit("/", 1)[1]), f"{d['Package']} 贴图 {url} 拉不到"
print(f"本地自检通过：{len([s for s in pkgs.decode().split(chr(10)+chr(10)) if s.strip()])} 个包 + 图标/介绍页/贴图")
EOF

if [ "${1:-}" = "--stage" ]; then
  echo "只做准备（--stage），没上传"
  exit 0
fi

# 项目不存在就先建（已存在会报错，忽略即可）
npx --yes wrangler@4 pages project create "$PROJECT" --production-branch=main >/dev/null 2>&1 || true

if ! npx --yes wrangler@4 pages deploy .dist --project-name="$PROJECT" --branch=main --commit-dirty=true; then
  echo "⚠️ Cloudflare 上传失败（多半是本地网络问题），等 5 秒重试一次…"
  sleep 5
  npx --yes wrangler@4 pages deploy .dist --project-name="$PROJECT" --branch=main --commit-dirty=true \
    || echo "⚠️ 还是失败：主源（Cloudflare）没更新，但下面照常同步 GitHub —— jsDelivr 备用源是最新的"
fi

# 同步到 GitHub（jsDelivr 备用源和图标/介绍页读的就是它），再清掉 CDN 缓存
git add -A >/dev/null 2>&1 && git commit -q -m "deploy: $(date '+%Y-%m-%d %H:%M')" >/dev/null 2>&1 || true
git push -q origin main >/dev/null 2>&1 && echo "已同步到 GitHub" || echo "（GitHub 推送失败，跳过 —— jsDelivr 备用源会滞后）"
for f in Packages Packages.zst Packages.bz2 Packages.gz Release index.html CydiaIcon.png icons/*.png depictions/*.json shots/*/* mac/*; do
  curl -s -m 15 "https://purge.jsdelivr.net/gh/OAA233/repo@main/$f" -o /dev/null 2>/dev/null || true
done
echo "已清 jsDelivr 缓存"
echo
echo "主源地址: https://$PROJECT.pages.dev/"