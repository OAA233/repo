Mirror17 for macOS — 安装说明
=============================

这个文件夹里的东西是给 Mac 用的，不是越狱插件。
Sileo / Zebra 装不了它们（那两个只会处理 iPhone 的 .deb），所以只能在这里当普通附件下载。

安装步骤
--------

1. 下载 Mirror17-mac-<版本>.zip，双击解压得到 Mirror17.app。
2. 把 Mirror17.app 拖进「应用程序」。
3. 第一次打开如果提示「已损坏，无法打开」或「无法验证开发者」，
   在「终端」里执行下面这行（把路径换成你放的位置），之后就能正常双击打开：

       xattr -dr com.apple.quarantine /Applications/Mirror17.app

   或者：在访达里按住 Control 点图标 → 打开 → 在弹窗里再点一次「打开」。
   （原因：这个 app 只做了 ad-hoc 签名，没有 Apple 开发者证书，也没花钱做公证。）

依赖
----

- macOS 14 或更高，Apple 芯片（M 系列）。
- 走「数据线直控」需要 iproxy：brew install libimobiledevice
- 走「Wi-Fi 直控」需要 TigerVNC：brew install --cask tigervnc
- 底部「返回 / 主屏幕 / 后台」三个键需要授权：
  系统设置 → 隐私与安全性 → 辅助功能 → 勾上 Mirror17

iPhone 那边
-----------

装源里的 com.a0.mirror17dim（连接时压暗屏幕）和 com.a0.mirror17ka（投屏期间不锁屏），
再在 iPhone 上打开 TrollVNC、启用服务、设「完全访问密码」并关掉「仅查看」。

关于隐私
--------

这个 app 里**不含**任何人的 IP 或密码：

- IP 每次由你在界面上手输，程序不保存（输入框里的 192.168.1.x 只是提示文字）。
- TrollVNC 密码只存在你自己 Mac 的钥匙串里（服务名 local.mirror17.trollvnc），
  运行时才临时生成一个 8 字节的 TigerVNC 密码文件，退出即删。包里没有密码。
