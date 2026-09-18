#!/usr/bin/env bash
# 部署到 Cloudflare Pages。第一次要先跑一次： npx wrangler login
# 用法: ./deploy.sh
set -euo pipefail
cd "$(dirname "$0")"

PROJECT=sileo-repo   # 上线地址就是 https://$PROJECT.pages.dev/

python3 build_repo.py

# 只把这些文件传上去：源码、脚本、paid.txt 留在本地
rm -rf .dist
mkdir -p .dist
cp Packages Packages.bz2 Packages.gz Release index.html CydiaIcon.png README.md .nojekyll .dist/
cp -R debs icons .dist/

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
    icon = "icons/" + d["Icon"].rsplit("/", 1)[1]   # 图标可能不在主源上，只取文件名本地验
    assert get(icon), f"{d['Package']} 图标拉不到"
print(f"本地自检通过：{len([s for s in pkgs.decode().split(chr(10)+chr(10)) if s.strip()])} 个包 + 全部图标")
EOF

if [ "${1:-}" = "--stage" ]; then
  echo "只做准备（--stage），没上传"
  exit 0
fi

npx --yes wrangler@4 pages deploy .dist --project-name="$PROJECT" --branch=main --commit-dirty=true
echo
echo "主源地址: https://$PROJECT.pages.dev/"