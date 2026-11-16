# 归档说明

本目录（`Ticket/Dunpiao/`）是项目的 **GitHub 归档仓库**；上级目录 `Ticket/` 是**工作区**，存放 Android SDK、模拟器镜像等不入仓库的大体积文件，开发与调试在工作区进行。

## 与工作区的关系

- 本仓库通过 `git fetch .. main` 继承了工作区仓库的全部提交历史，文件为归档快照。
- 工作区（`Ticket/`）中的后续提交不会自动进入本仓库，需要手动同步：

```bash
cd /Users/Admin/Desktop/work/Ticket/Dunpiao
git fetch .. main
git merge FETCH_HEAD
```

同步后如需推送 GitHub：`git push origin main`。

## 推送到 GitHub

```bash
git remote add origin git@github.com:<用户名>/Dunpiao.git
git push -u origin main
```

注意：本仓库与工作区仓库历史相同，不要把工作区添加为本仓库的 `origin` 以外的常规 remote，避免双向拉扯；归档方向永远是 工作区 → 本仓库 → GitHub。
