# Blender MCP 与 Codex 连接说明

## 1. 这条链路的大概原理

当前这套链路不是 `Codex -> 直接连 Blender`，而是分成了三层：

1. `Blender Add-on`
   Blender 里的 MCP 插件负责在 Blender 进程内部暴露一组可执行能力，并监听本地端口。

2. `blender-mcp`
   这是一个独立的 MCP Server 进程，由 `uvx blender-mcp` 启动。它对上游客户端说的是标准 MCP，对下游 Blender add-on 则通过本地 TCP 端口通信。

3. `Codex / mcporter`
   Codex 自己不会直接猜到 Blender 在哪里，而是通过 `mcporter` 发现一个名为 `blender` 的 MCP server。这个 server 实际上就是 `uvx blender-mcp` 启动出来的桥接层。

可以把它理解成：

```text
Codex
  -> mcporter 读取 MCP 配置
  -> 启动 uvx blender-mcp
  -> blender-mcp 连接 127.0.0.1:9876
  -> Blender add-on
  -> Blender 场景 / 操作能力
```

## 2. 关键配置文件分别是做什么的

### 2.1 `~/.mcporter/mcporter.json`

路径：

`/Users/bytedance/.mcporter/mcporter.json`

作用：

- 给 `mcporter` 注册一个名为 `blender` 的 MCP server
- 告诉 `mcporter`，如果有人要用 `blender` 这个 server，就执行 `uvx blender-mcp`

当前内容：

```json
{
  "mcpServers": {
    "blender": {
      "command": "uvx",
      "args": [
        "blender-mcp"
      ],
      "description": "Blender MCP server (Python) - requires Blender addon"
    }
  },
  "imports": []
}
```

含义：

- `command: "uvx"`：使用 `uvx` 启动 Python 版 MCP server
- `args: ["blender-mcp"]`：实际执行命令是 `uvx blender-mcp`
- `blender`：这个是 server 名字，后面调用时会用到，例如 `blender.some_tool`

### 2.2 `~/.mcporter/config.json`

路径：

`/Users/bytedance/.mcporter/config.json`

作用：

- 这是 Blender 连接信息本身
- 告诉桥接层真正要去连哪个 TCP 端口

当前内容：

```json
{
  "mcpServers": {
    "blender": {
      "type": "tcp",
      "host": "127.0.0.1",
      "port": 9876,
      "timeout": 30000
    }
  },
  "defaultServer": "blender"
}
```

含义：

- `type: "tcp"`：Blender add-on 这边暴露的是 TCP 端口
- `host: "127.0.0.1"`：只监听本机回环地址
- `port: 9876`：Blender add-on 当前监听的端口
- `timeout: 30000`：超时时间 30 秒

### 2.3 项目级 `config/mcporter.json`

路径：

`/Users/bytedance/Desktop/Convert-to-MMD/config/mcporter.json`

作用：

- 让当前项目显式声明它要用哪个 MCP server
- 比只放在用户全局目录里更容易被当前工作区识别

当前内容：

```json
{
  "mcpServers": {
    "blender": {
      "command": "uvx",
      "args": [
        "blender-mcp"
      ],
      "description": "Blender MCP server (Python) - requires Blender addon"
    }
  }
}
```

这个文件和 `~/.mcporter/mcporter.json` 基本同义，但作用域是当前仓库。

## 3. 这次我实际改了哪些内容

本次实际新增了一个文件：

- `/Users/bytedance/Desktop/Convert-to-MMD/config/mcporter.json`

新增原因：

- 你原来已经有全局配置
- 但当前 Codex 会话未必会自动把全局配置挂到当前项目里
- 增加项目级配置后，`mcporter config list` 已经确认优先使用当前仓库里的配置

我没有修改以下文件，只是做了读取确认：

- `/Users/bytedance/.mcporter/mcporter.json`
- `/Users/bytedance/.mcporter/config.json`

## 4. 这次我实际确认过的运行状态

### 4.1 Blender 端口已经在监听

我实际检查到：

```text
COMMAND  PID      USER   FD   TYPE   NAME
Blender 8166 bytedance    3u  IPv4   TCP 127.0.0.1:9876 (LISTEN)
```

说明：

- Blender 进程确实正在监听 `127.0.0.1:9876`
- 所以 Blender add-on 大概率已经启动

### 4.2 `mcporter` 已经能识别当前项目配置

执行 `mcporter config list` 后，结果显示：

```text
blender
  Source: local (/Users/bytedance/Desktop/Convert-to-MMD/config/mcporter.json)
  Transport: stdio (uvx blender-mcp)
  CWD: /Users/bytedance/Desktop/Convert-to-MMD/config
  Description: Blender MCP server (Python) - requires Blender addon
```

说明：

- 当前项目已经有一个名为 `blender` 的 MCP server 定义
- `mcporter` 会通过 `uvx blender-mcp` 启动它

## 5. 为什么端口通了，Codex 还不一定马上能控制 Blender

因为“端口通”只说明：

- Blender add-on 在运行
- 本地 TCP 监听正常

但要让 Codex 真正可用，还要满足：

1. 当前 Codex 会话加载到了 MCP 配置
2. Codex 把 `blender` 这个 server 识别成可用工具
3. `uvx blender-mcp` 启动成功
4. 该桥接层成功连上 `127.0.0.1:9876`

也就是说，链路中任何一层没挂上，Codex 都还不能真正调用 Blender 工具。

## 6. 推荐的标准配置步骤

以后从零配置时，按这个顺序最稳：

1. 在 Blender 中安装并启用 MCP add-on
2. 在 add-on 中确认监听地址是 `127.0.0.1:9876`
3. 准备 `~/.mcporter/config.json`，把 TCP 地址指向 Blender
4. 准备 `~/.mcporter/mcporter.json`，注册 `uvx blender-mcp`
5. 在项目里补一个 `config/mcporter.json`
6. 重启 Codex 桌面端或新开项目会话
7. 在该项目中测试 Blender MCP 工具是否被识别

## 7. 最小配置模板

### 7.1 全局桥接注册

文件：`~/.mcporter/mcporter.json`

```json
{
  "mcpServers": {
    "blender": {
      "command": "uvx",
      "args": [
        "blender-mcp"
      ],
      "description": "Blender MCP server (Python) - requires Blender addon"
    }
  },
  "imports": []
}
```

### 7.2 Blender TCP 目标

文件：`~/.mcporter/config.json`

```json
{
  "mcpServers": {
    "blender": {
      "type": "tcp",
      "host": "127.0.0.1",
      "port": 9876,
      "timeout": 30000
    }
  },
  "defaultServer": "blender"
}
```

### 7.3 当前项目声明

文件：`config/mcporter.json`

```json
{
  "mcpServers": {
    "blender": {
      "command": "uvx",
      "args": [
        "blender-mcp"
      ],
      "description": "Blender MCP server (Python) - requires Blender addon"
    }
  }
}
```

## 8. 常见故障与判断方法

### 8.1 `telnet 127.0.0.1 9876` 能连，但 `curl http://127.0.0.1:9876` 失败

这通常不表示有问题。

原因：

- `telnet` 只验证 TCP 能不能建立连接
- `curl` 默认按 HTTP 协议发请求
- Blender add-on 暴露的很可能不是普通 HTTP 首页

所以：

- `telnet` 成功更能说明端口活着
- `curl` 失败不代表 Blender MCP 坏了

### 8.2 Blender 在监听，但 Codex 里没有 Blender 工具

优先检查：

1. 当前项目是否有 `config/mcporter.json`
2. Codex 是否已经重启或新开会话
3. `mcporter config list` 是否能看到 `blender`
4. `uvx` 是否可用
5. Blender 是否仍然开着，且 add-on 没断连

### 8.3 `uvx blender-mcp` 启动失败

优先检查：

1. `uvx` 是否已安装
2. `blender-mcp` 包是否能被 `uvx` 拉起
3. 是否有本机权限或缓存目录问题
4. Blender 端口是否与配置一致

## 9. 当前结论

截至本次检查，可以确认：

- Blender add-on 已经在本机 `127.0.0.1:9876` 监听
- `mcporter` 的 Blender server 注册已经存在
- 当前项目也已经补齐项目级 MCP 配置

当前最可能还差的一步是：

- 让 Codex 重新加载当前项目的 MCP 配置

最简单的做法是：

1. 保持 Blender 打开
2. 关闭并重新打开 Codex 桌面端，或至少新开一个会话
3. 回到这个项目目录
4. 再测试 Blender 工具是否出现

