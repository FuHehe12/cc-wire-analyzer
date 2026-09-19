"""mac 冻结态的 CA 信任源：所有 Python 侧 https 出口的唯一取用处。

为什么存在（issue 260916 修更新检查、260919 修翻译 LLM——同一个病两次）：
CPython 的 ssl 在 macOS 不读钥匙串，只认编译期 OPENSSLDIR / SSL_CERT_FILE；
CI（actions/setup-python + macos-latest）构建的这些路径在用户机器上不存在 →
冻结态没有任何 CA 信任源 → Python 侧 https 必挂 CERTIFICATE_VERIFY_FAILED。
Windows 的 load_default_certs 有系统证书存储兜底，不受影响。certifi 随包打进
来（PyInstaller 对直接 import 的模块自动分析，hook 附带 cacert.pem），
`where()` 冻结态自动指向解包目录里那份。

**新增出网点（LLM、下载、任何 https）一律从本模块拿 opener，不要裸 urlopen**——
260916 修在 updater 单点时的依据是「更新器是全 app 唯一从 Python 侧发起 https
的路径」，后来翻译功能加了第二条出口没接上，260919 挂在「测试模型」上。

否决过的方案（260916 定案，对一切出网点同理）：启动时全局设 `SSL_CERT_FILE`——
影响面全局、与 ssl 初始化时序有坑；双平台统一 certifi-only——会把「企业 MITM
根证书装在系统存储」的 Windows 用户弄断，不修没坏的东西。
"""
from __future__ import annotations

import ssl
import sys
import urllib.request

try:
    import certifi
except ImportError:            # 裸 python 源码模式可能没装；回落系统默认路径
    certifi = None


def ca_context() -> ssl.SSLContext | None:
    """仅非 win32 且 certifi 可导入时返回 certifi context，否则 None 走系统默认。

    Windows 明确不走 certifi：系统证书存储是通的，换成 certifi-only 反而弄断
    「根证书装在系统存储」的企业代理用户（260827 真更新成功反证链路通）。
    """
    if sys.platform == "win32" or certifi is None:
        return None
    return ssl.create_default_context(cafile=certifi.where())


def opener(*handlers) -> urllib.request.OpenerDirector:
    """带 CA 信任源的 opener；调用方可追加自己的 handler（如 updater 的重定向白名单）。

    ProxyHandler() 不传参 = 用 urllib.getproxies()：Windows 读环境变量 + 系统
    代理注册表，macOS 读 scutil 系统代理——用户走 Clash 类系统代理时后端与
    浏览器走同一条路（260916：否则出现「前端检查更新好使、后端永远超时」
    这种最难判的故障）。
    """
    hs = [urllib.request.ProxyHandler(), *handlers]
    ctx = ca_context()
    if ctx is not None:
        hs.append(urllib.request.HTTPSHandler(context=ctx))
    return urllib.request.build_opener(*hs)
