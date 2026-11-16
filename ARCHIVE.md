# 归档说明

本目录（`Ticket/Dunpiao/`）是项目的 **GitHub 归档仓库**，只保留必要内容（README、配置模板、代码）；上级目录 `Ticket/` 是**工作区**，存放开发用的全部文件（TASKS、docs、doctor.py、Android SDK、模拟器镜像等），开发与调试在工作区进行。

## 与工作区的关系

- 本仓库初始历史继承自工作区仓库，之后内容**有意分叉**：本仓库是精简归档，工作区是全量开发目录。
- 因此不做整体 merge 同步（会把工作区文件整棵带回来），需要归档某个文件时按路径单独取：

```bash
cd /Users/Admin/Desktop/work/Ticket/Dunpiao
git fetch .. main
git checkout FETCH_HEAD -- <路径>   # 如 src/ 下某个新模块、config.example.yaml
```

或直接从工作区拷贝文件后 `git add` 提交。文档类文件（docs/plan、docs/research 等）整文件覆盖同步即可；归档方向永远是 工作区 → 本仓库 → GitHub，不要反向覆盖工作区。

## 推送到 GitHub

```bash
git remote add origin git@github.com:<用户名>/Dunpiao.git
git push -u origin main
```

注意：本仓库与工作区仓库历史同源，不要把工作区添加为本仓库的 remote 用于日常同步，避免双向拉扯。
