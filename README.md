# channel-gate · 渠道访问治理闸门

**单写者锁 + 日预算 + 拟人节奏，三合一。** 让你的爬虫/采集/高频 API 调用"像个人"，从机制上防止触发对方风控。

> 缘起：某电商比价账号因程序化高频查询触发风控封禁，客服解封时原话——
> *"这种情况是由于您操作频繁导致……建议您后续不要频繁连续搜索或查价，多次被封禁后无法处理。"*
> 解封次数有限，靠自觉守纪律不可靠，于是把红线做成了机制。

## 安装

```bash
# 从 GitHub 直接装（推荐）
pip install git+https://github.com/xucunyang/channel-gate.git

# 或本机开发态安装（改代码即时生效）
pip install -e E:\code\channel-gate
```

零第三方依赖，Python ≥ 3.10。

## 快速上手

### 只要节奏（轻量，任何业务）

```python
from channel_gate import Pacer

p = Pacer(2, 7, pause_every=10, pause_range=(300, 600))   # 间隔 2~7s 随机，连发 10 发歇 5~10 分钟
for url in urls:
    p.wait()          # 该歇就歇，返回实际等待秒数
    fetch(url)
```

### 完整治理（多会话/多脚本共用的渠道）

```python
from channel_gate import ChannelGate

gate = ChannelGate("my_channel", budget=60)   # 日预算 60 发
with gate.session("某某采集"):                # 单写者锁：被占会报持有者 pid/任务
    for url in anchors:
        gate.wait()                            # 拟人间隔 + 批间休息
        if not gate.spend(1, url):             # 预算扣减，超了 fail-closed 拒发
            print("今日预算已尽，停发")
            break
        fetch(url)
```

## 三道防线

| 防线 | 机制 | 参数 |
|---|---|---|
| **单写者锁** | 锁文件（默认 `~/.channel_gate/locks/`，机器级：不管哪个项目发起，同渠道同刻只能一个任务）；持锁进程已死自动抢占，活锁拒绝并报持有者 | `session()` |
| **日预算** | 台账落盘（`~/.channel_gate/budget/`，按日归零）；超预算 **fail-closed 拒发**，不是警告 | `budget=` |
| **拟人节奏** | 随机间隔（固定间隔是机器指纹）+ 连发 N 发强制批间休息 | `Pacer` |

## 预置档

```python
from channel_gate import PRESETS, Pacer
Pacer.for_channel("mmb")      # 间隔 2~7s，每 10 发歇 5~10 分钟
Pacer.for_channel("gwdang")   # 间隔 4~12s，每 8 发歇 5~15 分钟（整体拉长）
```

新渠道在 `channel_gate.pace.PRESETS` 登记档位，并把预算/节奏写进该渠道的操作手册。

## CLI

```bash
channel-gate status mmb          # 看锁（谁在跑）
channel-gate budget mmb          # 看今日用量
channel-gate release mmb         # 释放自己的锁
channel-gate release mmb --force # 强制接管（仅确认对方进程已死后用）
```

## 行为约定

- **遇风控信号（403/4030/验证码/is_ban）立即全停并报告**，禁止重试轰炸、换 IP/换会话折腾——闸门管"别触发"，触发后的处置在渠道自己的操作手册里
- 状态目录可用环境变量 `CHANNEL_STATE_DIR` 重定向（测试/多机）
- 同进程可重入同一渠道的锁（嵌套调用不自己挡自己）

## 设计原则

1. **fail-closed**：预算尽/锁被占 → 拒发，宁可停下也不硬闯
2. **机制 > 纪律**：文档会被忘，锁和预算不会
3. **零依赖**：标准库实现，pip 即装即用
4. **可注入**：时钟/随机数可替换，测试零真实睡眠

## License

MIT
