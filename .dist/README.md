# 王源的 Sileo / Zebra 源

纯静态 APT 源，没有服务端。

源名（`Origin`/`Label`）、落地页标题、包列表里显示的作者名，都在 `build_repo.py` 顶上那几个常量里 —— 改完重跑一次 `./deploy.sh` 就生效。`AUTHOR = "王源"` 那行配合 `LEGACY_AUTHORS`，把 deb 控制文件里的旧占位名（`a0` / `王` / `Wang`）统一显示成「王源」（deb 本身没动，装上以后本地包信息里还是旧名 —— 要彻底改得重新打包 deb）。

## 换到自己的地址（Cloudflare Pages，免备案、免费）

第一次：

```bash
npx wrangler login     # 浏览器里点一下授权
./deploy.sh            # 生成 + 本地自检 + 上传
```

上线地址 = `https://<PROJECT>.pages.dev/`，`PROJECT` 在 `deploy.sh` 顶上（现在叫 `sileo-repo`）。
想换名字：改 `deploy.sh` 的 `PROJECT` + `build_repo.py` 的 `MIRRORS[0]`，重跑一次 `./deploy.sh`。

**以后每次发新版就一条命令**：`./deploy.sh`（它自己会重新生成、本地抓一遍自检、再上传）。

绑自己的域名：Cloudflare → Pages → 选项目 → Custom domains → 添加，DNS 托管在 Cloudflare 就自动 HTTPS，不用备案。

## 加源地址（在 Zebra/Sileo 的「添加源」里只粘纯网址，不要粘 `sileo://` 开头那种链接 —— 那是给浏览器点击用的）

    主：  https://wangyuan-repo.pages.dev/       ← Cloudflare Pages
    备用：https://cdn.jsdelivr.net/gh/OAA233/repo@main/
          https://fastly.jsdelivr.net/gh/OAA233/repo@main/
          https://sileo-repo.pages.dev/
          https://oaa233.github.io/repo/

jsDelivr 是国内 CDN，不通就依次换后面的节点。一键加源链接（发到手机点开）：<https://wangyuan-repo.pages.dev/>

## 当前包

| 包 | 版本 | 说明 |
|---|---|---|
| com.a0.noswipe | 7.13 | XHS NoSwipe — 小红书禁滑 + 图文守护 |
| com.a0.mirror17dim | 1.0.0 | 有镜像客户端连接时把 iPhone 亮度降到最低 |
| com.a0.mirror17ka | 1.0.0 | 投屏期间禁止自动锁屏 |
| com.a0.doubletapflipcameraplus | 0.0.7 | 双击翻转相机 |
| com.a0.resumerecafterflip | 0.8.0 | 相机翻转打断录像后自动续录，停止时把各分段无损拼成一个完整视频 |

## Mac 客户端（不在 APT 里）

`mac/` 放的是给 Mac 用的普通附件，**不是越狱插件** —— Sileo/Zebra 只认 iPhone 的 `.deb`，
装不了 macOS 程序，所以这类东西只能当下载件挂在这里。

- `mac/Mirror17-mac-<版本>.zip` —— Mirror17 Mac 客户端（release 构建 + ad-hoc 签名）
- `mac/README.txt` —— 给下载者的安装说明（Gatekeeper 绕过、brew 依赖、隐私说明）

落地页（`index.html`）会自动扫 `mac/` 里的 `.zip/.dmg/.pkg/.tar.gz`，挑**最新**的一个列成下载区，
链接直接指向 `mac/<文件名>`，所以换版本不用改任何链接。

重新生成一个 Mac 包：

```bash
cd ~/Desktop/王源/Mirror17
./make_app.sh --zip       # 只打包 → dist/Mirror17-mac-<版本>.zip
./make_app.sh --release   # 打包 + 拷进 SileoRepo/mac/ + 重建索引
```

`make_app.sh` 里有两条硬自检：二进制不许依赖 `/opt/homebrew`（否则别人机器上 dyld 直接崩），
不许残留 `/Users/...` 源码调试路径（会泄露本机目录结构）。

## 给包加截图（介绍页里的横滑贴图）

1. 在 `shots/` 下建一个和包名同名的文件夹，例如 `shots/com.a0.noswipe/`。
2. 往里丢 PNG/JPG，**按文件名排序**显示 —— 建议 `01-xxx.png`、`02-xxx.png`。
   竖屏截图按 **260×563** 比例最贴合 Sileo 的展示框；中文文件名没问题（脚本会做 URL 编码）。
3. 想要介绍页顶部的大横幅，就再放一张 **`banner.png`**（16:9，横向）。它不会出现在横滑列表里。
4. `cd ~/Desktop/王源/SileoRepo && ./deploy.sh` —— 脚本会自动生成 `depictions/<包名>.json`，
   并在 `Packages` 里补上 `SileoDepiction:` / `Header:` 字段。
5. 手机上刷新源；图标和贴图缓存都很凶，必要时杀掉 Sileo 重开。

没有 meta 也没有贴图的包不会生成介绍页；只要有其中之一就会生成。

## 各插件的工程位置

都在 `~/Desktop/王源/` 下，与本源同级：

| 工程 | 对应包 | 构建方式 |
|---|---|---|
| `ResumeRecAfterFlip/` | com.a0.resumerecafterflip | `./build.sh`（加 `--release` 会自动拷进 debs/ 并重建索引） |
| `XHS-NoSwipe/` | com.a0.noswipe | `v7.13/build_deb.sh`（独立 git 仓库 RedNote-Video-NoSwipe） |
| `Mirror17/` | com.a0.mirror17dim / mirror17ka | Swift 工程，产物在 `iphone-rootless/`；Mac 端用 `./make_app.sh --release` |

新增包时：工程放这里 → 改 `control`（`Package: com.a0.*`、`Author/Maintainer: 王源`、`Section: Tweaks`）→ 打包丢进 `debs/` → 放 `icons/<包名>.png`（180×180，缺省用 default.png）→ 重跑本脚本 → 部署。

## 发新版

1. 新 .deb 丢进 `debs/`（同名多版本也行，装的时候取最高版）
2. `python3 build_repo.py` — 生成 Packages / Packages.bz2 / Packages.gz / Release / index.html，并自校验哈希
3. `git add -A && git commit -m "xxx 1.2" && git push`
4. 清 jsDelivr 缓存，否则备用地址最多 12 小时才看到新版：
   `curl -s "https://purge.jsdelivr.net/gh/OAA233/repo@main/Packages" >/dev/null`

Pages 约 1 分钟后生效。

## 图标

Sileo / Zebra 包列表里每个包的图标来自这里：

- `icons/<包名>.png` —— 只作用于那一个包，如 `icons/com.a0.noswipe.png`
- `icons/default.png` —— 没单独给的包用这张
- `CydiaIcon.png` —— 源本身在源列表里的图标

都建议 180×180 PNG（透明底最好，深色列表里不糊）。换图后重跑脚本 + push + 清缓存即可。

## 付费包

把包标识符一行一个写进 `paid.txt`，重跑脚本 → 该包会带 `Tag: cydia::commercial`（Sileo 认这个才会走购买/授权流程）。

⚠️ Pages 上所有文件都是公开可下的：付费的 .deb 放这里等于免费送人。付费包的二进制要放别处（Cloudflare R2 + Worker 带 token），这里只放免费包。

## 备注

- `.nojekyll` 是必须的，否则 Pages 的 Jekyll 会动这些文件。
- 包的描述/依赖来自 .deb 里的 control 文件，改文案要重新打包 deb，不是改这里。
