# a0 Sileo 源

Sileo / Zebra / Cydia 通用 APT 源。纯静态，扔 GitHub Pages 就行。

## 加源（装好后在 Sileo 里）

    https://oaa233.github.io/SileoRepo/

## 日常维护

1. 新 .deb 丢进 `debs/`
2. `python3 build_repo.py`（会打印每个包 + PASS/FAIL 自校验）
3. `git add -A && git commit -m "update" && git push`

## 付费包

把包标识符一行一个写进 `paid.txt`，重跑脚本 → 生成的 Packages 里该包会带
`Tag: cydia::commercial`（Sileo 认这个标签才会走购买/授权流程）。

⚠️ GitHub Pages 上所有文件都是公开的：付费的 .deb 放这里等于免费送人。
付费包的二进制要单独放（见对话里的 B 方案：Cloudflare R2 + Worker 带 token）。

## 文件

- `debs/` — 包本体
- `build_repo.py` — 生成 + 校验（Packages / Packages.bz2 / Packages.gz / Release）
- `paid.txt` — 付费包白名单
- `.nojekyll` — 让 Pages 别用 Jekyll 处理这些文件
