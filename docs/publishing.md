# 安全发布与 GitHub 上传手册

本手册对应独立发布目录 `release/Ecommerce-Agent-public`。它与正在运行的私人工作目录分开，上传前应在该目录内操作。发布目录不继承原项目Git历史，避免把历史中的本地配置带入新仓库。

## 本次准备的内容

包含后端、前端、测试、评测、Docker配置、SQL虚构样例、环境模板、MIT许可、CI和文档。不包含私人知识库及其构建脚本、真实密钥、原始`.env`、模型、虚拟环境、运行数据、容器卷、日志、备份、简历或个人求职材料。

API配置已替换为占位模板，`python -m scripts.setup_env` 在克隆后生成随机应用/数据库/存储密码；用户自行填模型供应商密钥。本操作没有重置供应商账户中的真实密钥；若密钥曾被公开，需要去供应商控制台单独撤销/轮换。

## 当前上传状态

2026-10-18检查发现本机现有HTTPS缓存凭证访问GitHub `/user` 返回401，未能确认有效身份；不能把本地提交或压缩包当成已经成功上传。Git推送预检也返回“Invalid username or token”，未上传代码；公开只读的Git远程可以访问。请先完成下面登录步骤，再从发布目录推送。

## 推荐方式 新建干净仓库

1. 在浏览器登录你的GitHub账户。创建空仓库，例如 `Ecommerce-Agent-Studio`，不要勾选初始化README、License或.gitignore。
2. 从发布目录打开PowerShell。确认 `git status` 展示的是公开版本，没有`.env`、私人知识库或简历。
3. 如本次交付已经建立Git仓库并提交，直接从 `git remote add` 开始；否则依次运行：

```powershell
git init -b main
git add .
git diff --cached --stat
git commit -m "Publish ecommerce Agent workspace"
```

4. 以GitHub页面显示的仓库URL替换下面示例，并修改README最前面的clone地址为同一个URL：

```powershell
git remote add origin https://github.com/TT959/Ecommerce-Agent-Studio.git
git push -u origin main
```

Git Credential Manager弹出登录时在浏览器完成，不要把账户密码或Token发给聊天，也不要把Token写入远程URL。如果origin已经存在，用 `git remote set-url origin <正确仓库URL>`。修改README后记得另行add/commit/push。

若旧缓存阻止登录，可运行 `git credential-manager github login`，按提示选择账户；不同Git版本子命令可能不同，可先 `git credential-manager github --help`。也可使用GitHub Desktop把这个已存在的本地仓库添加后发布。GitHub不使用普通账户密码进行HTTPS Git认证，参见 [GitHub认证说明](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/about-authentication-to-github)。

## 如果必须更新原有 Ecommerce-Agent 仓库

不要直接强制覆盖main，也不要在私人根目录执行 `git add .`。先确认原仓库历史不包含密钥及私人资料；若有，使用新仓库更容易保持独立发布边界，或按GitHub官方流程清理历史并轮换泄露密钥。

可将干净版本推到新分支，再在GitHub检查差异：

```powershell
git remote add origin https://github.com/TT959/Ecommerce-Agent.git
git push origin main:codex/public-release
```

若origin已存在则改URL。由于公开版本是独立历史，GitHub可能提示无法直接比较无共同祖先；此时建议发布为新仓库，而不是使用 `--force`。要合并到旧仓库，应先克隆原仓库至另一个临时目录，在新分支替换工作树并审查提交；这会保留旧历史，不能解决历史已泄密的问题。

## 推送前和推送后核验

```powershell
git status --short
git ls-files
# 应没有输出
git ls-files .env knowledge_base Models data logs backups deliverables
```

提交前查看 `git diff --cached`。推送后在GitHub网页检查README、.env.example与CI结果，再到一个新文件夹执行clone，并按README从零启动。不要以“push没有报错”替代检查仓库内容。

## 日常更新

在发布目录修改源码后先跑测试与构建，再提交。不要直接把整个私人目录覆盖过去；私人知识库导入脚本与公开样例不同，简单复制会重新引入不应发布的数据。

README给出的启动链路依赖模型服务商可用、Docker镜像能下载、本地端口空闲和完整BGE模型。配置校验、接口测试与前端构建不是在新电脑上完整部署成功的证明。
