Mirror17 for macOS — 安装说明
===============================

这个文件夹里的东西是给 Mac 用的，不是越狱插件。
Sileo / Zebra 装不了它们（那两个只会处理 iPhone 的 .deb），所以只能在这里当普通附件下载。

安装步骤
--------

1. 下载 Mirror17-mac-<版本>.zip，双击解压得到Mirror17.app。
2. 把它拖进「应用程序」。
3. 第一次打开如果提示「已损坏，无法打开」或「无法验证开发者」，
   在「终端」里执行下面这行（把路径换成你放的位置），之后就能正常双击打开：

       xattr -dr com.apple.quarantine /Applications/Mirror17.app

   或者：在访达里按住 Control 点图标 → 打开 → 在弹窗里再点一次「打开」。
   （原因：这个 app 只做了 ad-hoc 签名，没有 Apple 开发者证书，也没花钱做公证。）

系统要求
--------

- macOS 14 或更高，Apple 芯片（M 系列）。
- 这个包里已经把全部第三方动态库内嵌好了（Contents/Frameworks），
  **不需要** brew install 任何东西就能启动。

可选依赖（想用对应功能才装）
----------------------------

- 走「数据线直控」需要 iproxy：brew install libimobiledevice
- 走「Wi-Fi 直控」需要 TigerVNC：brew install --cask tigervnc
- 底部控制条里除最左边那个箭头之外的按键需要授权：
  系统设置 → 隐私与安全性 → 辅助功能 → 勾上 Mirror17

底部控制条是什么
----------------

连上之后窗口底部会有一条悬浮控制条，从左到右：

- **返回主页** —— 回到 iPhone 主屏幕
- **后台** —— 打开多任务
- **后退10秒** —— 在画面上模拟向左拖动进度
- **暂停** —— 播放 / 暂停
- **快进10秒** —— 在画面上模拟向右拖动进度

最左边那个箭头是系统返回手势，最右边的「⋯」里是更多（切换采集卡画面 / 开启媒体键映射 /
翻转滚动方向 / **反馈问题**）。

遇到问题怎么办（1.0.1 起）
--------------------------

- 连接页报错文字下面有一个「遇到问题？导出诊断报告…」；
  连上之后的底部控制条「⋯」菜单里也有「反馈问题（导出诊断报告）…」。
- 点一下会在桌面生成 `Mirror17-诊断-<时间>.txt`，并在访达里选中它。
- 里面是：app 版本、macOS 版本、机型、iPhone 的 UDID/机型/iOS 版本、
  当前连接状态与最近一次错误、mirror17 日志尾部。
  **不含**你的 VNC 密码和 Wi-Fi 地址之外的隐私信息。
- 把这个 txt 发到 **oaawallet@gmail.com** 或作者的聊天里，就能定位问题。

命令行也能用（不弹界面，写完就退出，方便让脚本/远程排查）：

    /Applications/Mirror17.app/Contents/MacOS/Mirror17 --diagnose

iPhone 那边
-----------

装源里的 Mirror17 Dim（连接时压暗屏幕）和 Mirror17 Keep Awake（投屏期间不锁屏），
再在 iPhone 上打开 TrollVNC、启用服务、设「完全访问密码」并关掉「仅查看」。

关于隐私
--------

这个 app 里**不含**任何人的 IP 或密码：

- IP 每次由你在界面上手输，程序不保存（输入框里的 192.168.1.x 只是提示文字）。
- TrollVNC 密码只存在你自己 Mac 的钥匙串里（服务名 local.mirror17.trollvnc），
  运行时才临时生成一个 8 字节的 TigerVNC 密码文件，退出即删。包里没有密码。

第三方组件与许可证
------------------

包里内嵌了 libvncclient（libvncserver，GPL-2.0）、libjpeg-turbo（BSD/IJG）、
OpenSSL（Apache-2.0）。详见同目录的 NOTICE.txt。
