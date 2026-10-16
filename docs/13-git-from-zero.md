# 13 · Git 从零到面试够用

## 1. Git 解决什么问题？

Git 是分布式版本控制工具，记录每次改动的快照，让你能：

- 回退到任意历史版本。
- 多人协作不互相覆盖。
- 用分支同时开发不同功能。

三个核心区域：

```text
工作区(working directory)
  -> git add -> 暂存区(staging area)
  -> git commit -> 本地仓库(local repo)
  -> git push -> 远程仓库(remote)
```

## 2. 必须会的基本命令

```bash
git init                          # 初始化仓库
git status                        # 看当前状态
git add .                         # 把所有改动加入暂存区
git commit -m "feat: 添加登录功能"  # 提交一次快照
git log --oneline                 # 看提交历史
git diff                          # 看未暂存的改动
git diff --staged                 # 看已暂存的改动
```

提交信息要语义化，常用前缀：

```text
feat:  新功能
fix:   修复 bug
refactor: 重构
docs:  文档
chore: 杂项
```

## 3. 分支：并行开发的关键

```bash
git branch                    # 查看分支
git checkout -b feature/rag   # 新建并切换分支
git switch feature/rag        # 切换分支（新写法）
git merge feature/rag         # 把分支合并到当前分支
git branch -d feature/rag     # 删除已合并的分支
```

工作流：

```text
main 保持可运行
  -> 每个功能开新分支
  -> 完成后合并回 main
```

## 4. 远程仓库

```bash
git remote add origin https://github.com/you/lab-agent.git
git push -u origin main        # 第一次推送
git push                       # 之后直接推
git pull                       # 拉取别人更新
git clone <url>                # 克隆仓库
```

`pull = fetch + merge`：先把远程更新拿下来，再合并。

## 5. 回退：出错了怎么办

```bash
git restore <file>              # 撤销工作区改动
git restore --staged <file>     # 取消暂存
git reset --soft HEAD~1         # 撤销上次 commit，改动保留在暂存区
git reset --hard HEAD~1         # 撤销 commit 并丢弃改动（危险）
git revert <commit-id>          # 生成一次反向提交（安全，推荐）
```

原则：**已推送的提交不要用 `reset --hard`，用 `revert`。**

## 6. 合并冲突

两个人改了同一行就会冲突。Git 会标出来：

```text
<<<<<<< HEAD
你的版本
=======
别人的版本
>>>>>>> feature/xxx
```

手动改成正确的最终内容，删掉标记，然后：

```bash
git add .
git commit -m "fix: 解决冲突"
```

## 7. 这个项目怎么用 Git 管理

1. 先建 `.gitignore`（本项目已写好，忽略 `.venv`、`node_modules`、`__pycache__`、`*.db`、`.env`）。
2. 关键点：**`.env` 和数据库文件不要提交**，里面有密钥和数据。
3. 建议分支：

```text
main                稳定可演示版本
feature/fastapi      后端业务
feature/rag          向量检索
feature/agent        LangGraph + MCP
```

## 8. 面试常问

- `git merge` 和 `git rebase` 区别：merge 保留分支历史，rebase 把提交线变直。
- `git reset` 和 `git revert` 区别：reset 改写历史，revert 生成新提交。
- 为什么 `.env` 不进仓库：避免密钥泄露。
- 冲突怎么处理：先 pull、定位冲突、手改、add、commit。

## 9. 练习清单

- 初始化仓库，提交 3 次，看 `git log`。
- 开分支加功能，合并回 main，删分支。
- 故意制造一次冲突并解决。
- 推到 GitHub/Gitee，再 clone 到另一个目录。
