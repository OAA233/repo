# TrollVNC（王源构建版）对应源码 · GPL-2.0

本目录放的是 **`com.wangyuan.trollvnc` 这个包对应的完整源码**，按 GNU GPL-2.0 的要求随二进制一起公开。

| 项 | 值 |
|---|---|
| 包名 | `com.wangyuan.trollvnc` |
| 版本 | `3.2-293-1` |
| 源码 | `trollvnc-3.2-293-1-src.tar.gz` |
| 上游 | https://github.com/OwnGoalStudio/TrollVNC （GPL-2.0，commit a3e4081 起） |
| 官方付费版 | https://havoc.app/package/trollvnc （与本包无关，想支持原作者请买它） |

## 与上游的差别

1. `src/trollvncserver.mm`：新增「Mirror17 Native Stream (H.264 over USB)」一段（`#pragma mark - Mirror17 Native Stream`），提供 `127.0.0.1:38917` 上的长度前缀协议：
   `[u8 类型][u32 BE 长度][负载]`，`0x01` 服务端 JSON、`0x02` H.264 Annex-B、`0x10` 客户端输入事件。
   编码用 VideoToolbox `VTCompressionSession`。这部分是王源为 Mirror17（Mac 客户端）加的，上游没有。
2. `Makefile`：1 行改动（允许外部传 `PACKAGE_VERSION`）。
3. 打包元数据（`layout/DEBIAN/control`）改成王源自己的包名与署名，并声明 `Conflicts/Replaces/Provides: com.82flex.trollvnc`。

其余代码、资源与上游一致。**本包不包含 82Flex 官方付费版的任何代码或资源。**

## 怎么自己编译

```bash
tar -xzf trollvnc-3.2-293-1-src.tar.gz
cd trollvnc-src
export THEOS=~/theos THEOS_PACKAGE_SCHEME=rootless   # 无根越狱环境
make package PACKAGE_VERSION=3.2-293-1
# 产物在 packages/com.wangyuan.trollvnc_3.2-293-1_iphoneos-arm64.deb
```

需要 theos、iOS 16.5 SDK（theos 自带即可）。装包：`dpkg -i` 或直接丢进 Sileo 安装。

## 许可

本源码整体沿用上游的 **GPL-2.0**（见包内 `COPYING`）。任何人可自由获取、修改、编译、再分发，
但再分发时必须同样提供对应源码。原作者版权归 OwnGoalStudio / 82Flex 所有，本仓库只做构建与追加补丁。
