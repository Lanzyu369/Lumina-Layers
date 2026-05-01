# Bug Report Email Configuration

Lumina Studio can send user bug reports through SMTP. If SMTP is not configured, bug reports are still accepted and saved as JSON files under the feedback dump directory, but the UI will show that email is not configured.

## Security rule

Never commit real SMTP usernames, passwords, app passwords, or tokens to GitHub.

`.env.local` is intentionally ignored by git. Each deployment machine must create its own `.env.local` file or provide the same variables through the process manager, container platform, or hosting provider secrets.

## Configuration files

- `.env.example` is the public template committed to the repository.
- `.env.local` is the private local/production override file and must stay out of git.
- `LUMINA_ENV_LOCAL_PATH` can point the backend to a custom env file path.

The backend loads `<repo>/.env.local` automatically when `api.app` is imported, including when started through `python api_server.py`, `uvicorn api.app:app`, Docker, or development launchers.

## Required minimum variables

Email delivery is enabled only when both variables are present:

```bash
LUMINA_FEEDBACK_SMTP_HOST=smtp.example.com
LUMINA_FEEDBACK_TO=developer@example.com
```

In most real deployments you should also set the login credentials:

```bash
LUMINA_FEEDBACK_SMTP_PORT=587
LUMINA_FEEDBACK_SMTP_USER=developer@example.com
LUMINA_FEEDBACK_SMTP_PASSWORD=replace-with-app-password
LUMINA_FEEDBACK_SMTP_FROM=developer@example.com
LUMINA_FEEDBACK_SMTP_USE_TLS=true
LUMINA_FEEDBACK_SMTP_TIMEOUT_S=5
```

## QQ Mail example

For QQ Mail, enable SMTP in the QQ Mail settings and use the generated SMTP authorization code, not the QQ account login password.

```bash
LUMINA_FEEDBACK_SMTP_HOST=smtp.qq.com
LUMINA_FEEDBACK_SMTP_PORT=587
LUMINA_FEEDBACK_SMTP_USER=your@qq.com
LUMINA_FEEDBACK_SMTP_PASSWORD=replace-with-qq-smtp-authorization-code
LUMINA_FEEDBACK_SMTP_FROM=your@qq.com
LUMINA_FEEDBACK_TO=your@qq.com
LUMINA_FEEDBACK_SMTP_USE_TLS=true
LUMINA_FEEDBACK_SMTP_TIMEOUT_S=5
```

After editing `.env.local`, restart the backend process so the new environment is loaded.

## Gmail example

For Gmail, enable 2-Step Verification and create a Google App Password. Regular Google account passwords are blocked for SMTP.

```bash
LUMINA_FEEDBACK_SMTP_HOST=smtp.gmail.com
LUMINA_FEEDBACK_SMTP_PORT=587
LUMINA_FEEDBACK_SMTP_USER=you@gmail.com
LUMINA_FEEDBACK_SMTP_PASSWORD=replace-with-google-app-password
LUMINA_FEEDBACK_SMTP_FROM=you@gmail.com
LUMINA_FEEDBACK_TO=you@gmail.com
LUMINA_FEEDBACK_SMTP_USE_TLS=true
LUMINA_FEEDBACK_SMTP_TIMEOUT_S=5
```

## systemd example

If the server is managed by systemd, you can either use `.env.local` or add environment variables to the service unit:

```ini
[Service]
Environment="LUMINA_FEEDBACK_SMTP_HOST=smtp.qq.com"
Environment="LUMINA_FEEDBACK_SMTP_PORT=587"
Environment="LUMINA_FEEDBACK_SMTP_USER=your@qq.com"
Environment="LUMINA_FEEDBACK_SMTP_PASSWORD=replace-with-qq-smtp-authorization-code"
Environment="LUMINA_FEEDBACK_SMTP_FROM=your@qq.com"
Environment="LUMINA_FEEDBACK_TO=your@qq.com"
Environment="LUMINA_FEEDBACK_SMTP_USE_TLS=true"
```

Then reload and restart:

```bash
sudo systemctl daemon-reload
sudo systemctl restart lumina
```

## Docker example

Pass secrets at container runtime instead of baking them into the image:

```bash
docker run -p 7860:7860 \
  -e LUMINA_FEEDBACK_SMTP_HOST=smtp.qq.com \
  -e LUMINA_FEEDBACK_SMTP_PORT=587 \
  -e LUMINA_FEEDBACK_SMTP_USER=your@qq.com \
  -e LUMINA_FEEDBACK_SMTP_PASSWORD=replace-with-qq-smtp-authorization-code \
  -e LUMINA_FEEDBACK_SMTP_FROM=your@qq.com \
  -e LUMINA_FEEDBACK_TO=your@qq.com \
  -e LUMINA_FEEDBACK_SMTP_USE_TLS=true \
  lumina-layers
```

## Verification

1. Restart the backend.
2. Submit a bug report from the UI.
3. A successful email-enabled response should not show the "email is not configured" message.
4. If it still shows that email is unconfigured, check that `LUMINA_FEEDBACK_SMTP_HOST` and `LUMINA_FEEDBACK_TO` are visible to the backend process.
5. If the UI no longer says unconfigured but no email arrives, check backend logs for `feedback_email_failed` and verify host, port, TLS mode, username, password or app password, and provider SMTP permissions.

# 反馈邮件配置

Lumina Studio 可以通过 SMTP 发送用户提交的 Bug 反馈。如果没有配置 SMTP，反馈仍然会被接收并保存为本地 JSON 文件，但界面会提示邮件未配置。

## 安全规则

不要把真实 SMTP 用户名、密码、授权码或 token 提交到 GitHub。

`.env.local` 会被 git 忽略。每台部署机器都需要自己创建 `.env.local`，或者通过 systemd、Docker、云平台 Secret 等方式提供同样的环境变量。

## 配置文件

- `.env.example` 是提交到仓库里的公开模板。
- `.env.local` 是本地或生产环境的私密配置文件，不能进 git。
- `LUMINA_ENV_LOCAL_PATH` 可以指定自定义 env 文件路径。

后端导入 `api.app` 时会自动读取仓库根目录的 `.env.local`，包括 `python api_server.py`、`uvicorn api.app:app`、Docker 和开发启动器等入口。

## 最小必需变量

只有同时存在下面两个变量，邮件发送才会启用：

```bash
LUMINA_FEEDBACK_SMTP_HOST=smtp.example.com
LUMINA_FEEDBACK_TO=developer@example.com
```

实际部署通常还需要配置登录信息：

```bash
LUMINA_FEEDBACK_SMTP_PORT=587
LUMINA_FEEDBACK_SMTP_USER=developer@example.com
LUMINA_FEEDBACK_SMTP_PASSWORD=replace-with-app-password
LUMINA_FEEDBACK_SMTP_FROM=developer@example.com
LUMINA_FEEDBACK_SMTP_USE_TLS=true
LUMINA_FEEDBACK_SMTP_TIMEOUT_S=5
```

## QQ 邮箱示例

QQ 邮箱需要先在邮箱设置里开启 SMTP 服务，并使用生成的 SMTP 授权码，不要使用 QQ 登录密码。

```bash
LUMINA_FEEDBACK_SMTP_HOST=smtp.qq.com
LUMINA_FEEDBACK_SMTP_PORT=587
LUMINA_FEEDBACK_SMTP_USER=your@qq.com
LUMINA_FEEDBACK_SMTP_PASSWORD=replace-with-qq-smtp-authorization-code
LUMINA_FEEDBACK_SMTP_FROM=your@qq.com
LUMINA_FEEDBACK_TO=your@qq.com
LUMINA_FEEDBACK_SMTP_USE_TLS=true
LUMINA_FEEDBACK_SMTP_TIMEOUT_S=5
```

修改 `.env.local` 后，需要重启后端进程，新的配置才会生效。

## Gmail 示例

Gmail 需要先启用两步验证，再创建 Google App Password。普通 Google 账号密码无法用于 SMTP。

```bash
LUMINA_FEEDBACK_SMTP_HOST=smtp.gmail.com
LUMINA_FEEDBACK_SMTP_PORT=587
LUMINA_FEEDBACK_SMTP_USER=you@gmail.com
LUMINA_FEEDBACK_SMTP_PASSWORD=replace-with-google-app-password
LUMINA_FEEDBACK_SMTP_FROM=you@gmail.com
LUMINA_FEEDBACK_TO=you@gmail.com
LUMINA_FEEDBACK_SMTP_USE_TLS=true
LUMINA_FEEDBACK_SMTP_TIMEOUT_S=5
```

## systemd 示例

如果服务器通过 systemd 管理，可以使用 `.env.local`，也可以把环境变量写入 service unit：

```ini
[Service]
Environment="LUMINA_FEEDBACK_SMTP_HOST=smtp.qq.com"
Environment="LUMINA_FEEDBACK_SMTP_PORT=587"
Environment="LUMINA_FEEDBACK_SMTP_USER=your@qq.com"
Environment="LUMINA_FEEDBACK_SMTP_PASSWORD=replace-with-qq-smtp-authorization-code"
Environment="LUMINA_FEEDBACK_SMTP_FROM=your@qq.com"
Environment="LUMINA_FEEDBACK_TO=your@qq.com"
Environment="LUMINA_FEEDBACK_SMTP_USE_TLS=true"
```

然后重新加载并重启：

```bash
sudo systemctl daemon-reload
sudo systemctl restart lumina
```

## Docker 示例

运行容器时传入 Secret，不要把密码写入镜像：

```bash
docker run -p 7860:7860 \
  -e LUMINA_FEEDBACK_SMTP_HOST=smtp.qq.com \
  -e LUMINA_FEEDBACK_SMTP_PORT=587 \
  -e LUMINA_FEEDBACK_SMTP_USER=your@qq.com \
  -e LUMINA_FEEDBACK_SMTP_PASSWORD=replace-with-qq-smtp-authorization-code \
  -e LUMINA_FEEDBACK_SMTP_FROM=your@qq.com \
  -e LUMINA_FEEDBACK_TO=your@qq.com \
  -e LUMINA_FEEDBACK_SMTP_USE_TLS=true \
  lumina-layers
```

## 验证方式

1. 重启后端。
2. 在界面提交一条 Bug 反馈。
3. 如果邮件配置生效，成功页不应再显示“邮件未配置”。
4. 如果仍显示未配置，检查后端进程是否能读到 `LUMINA_FEEDBACK_SMTP_HOST` 和 `LUMINA_FEEDBACK_TO`。
5. 如果不再提示未配置但没有收到邮件，检查后端日志中的 `feedback_email_failed`，并核对 host、端口、TLS、用户名、授权码和邮箱服务商的 SMTP 权限。
