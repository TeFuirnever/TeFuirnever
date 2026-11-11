# 三步做出「活的」GitHub 主页,直接抄作业

> 整理了一份 GitHub 主页 README 的实现方式:原理三步、三档开源工具实测结论、一份可以直接抄的作业本。我的主页 [TeFuirnever/TeFuirnever](https://github.com/TeFuirnever) 就是按这套做的,本文末尾附完整抄作业清单。

**成品长什么样**:主页顶部是品牌区(头像快照 + 五枚实时徽章:Stars / Followers / 仓库数 / 提交数 / 代码行数);往下是项目卡片与主张;「开源足迹」区挂着两张每天自动重绘的 SVG——一年贡献热力图(含活跃天数、连击、最佳单日)和 Neofetch 风格系统快照(头像的彩色 ASCII 化身 + 实时数据行)。所有数字每天 03:17(UTC)自动刷新,数字没变就不产生新提交。

---

## 一、原理:只有三步

1. **特殊仓库**:新建一个和自己用户名同名的公开仓库 `username/username`,里面的 `README.md` 会自动挂在 GitHub 主页顶部。
2. **布局设计**:Markdown 排版 + 预生成的 ASCII 艺术或 SVG 卡片。卡片是静态图,在任何主题下渲染稳定。
3. **自动化数据**:GitHub Actions 定时拉 GitHub GraphQL 接口,自动更新提交数、Stars、代码行数,主页保持「活」的状态。

## 二、三档工具,按投入选一个

| 档位 | 工具 | 实测结论 |
| --- | --- | --- |
| ① 一键托管 | [jeantimex/neofetch-profile](https://github.com/jeantimex/neofetch-profile) | ✅ 可用。Vercel 托管服务,把生成的 SVG URL 嵌进 README 即得 Neofetch 风格卡片:头像自动转 ASCII,实时显示 repos / stars / commits / followers / 代码行数,支持 JSON 配置自定义字段与深浅色主题。**注意**:运行时依赖别人的在线服务,长期稳定性不受你控制。 |
| ② 照片转 ASCII + 贡献图 | [valthvn/animated-terminal-profile](https://github.com/valthvn/animated-terminal-profile) | ✅ 可用但很新(调研时 2 stars,MIT)。Python 脚本本地生成三张 SVG:打字动画 ASCII 肖像(你的照片一键转 ASCII)、Neofetch 信息卡、每日自动刷新的贡献热力图。动画靠 SVG SMIL,GitHub 能正常渲染。**注意**:项目年轻,建议通读脚本再用,别盲跑。 |
| ③ 进阶 DIY | 自己写 Python + Actions | ✅ 最可控。数据、字段、版式全部自定义,不依赖任何第三方在线服务。我的作业本走的就是这条路,见下文。 |

**替补方案**:只要贡献图不要 ASCII,可以用社区老牌组件——[Platane/snk](https://github.com/Platane/snk)(贪吃蛇贡献图)或 [Ashutosh00710/github-readme-activity-graph](https://github.com/Ashutosh00710/github-readme-activity-graph)(折线活动图),嵌 URL 即用。

## 三、我的作业本(可整套照抄)

仓库:`TeFuirnever/TeFuirnever`,结构如下:

```text
├── README.md                      # 主页文案 + STATS 徽章块(机器维护)
├── assets/profile/
│   ├── card-neofetch.svg          # Neofetch 系统快照卡(机器每日重绘)
│   └── card-contributions.svg     # 一年贡献热力图(机器每日重绘)
├── scripts/
│   ├── fetch_stats.py             # GraphQL 取数 → stats.json
│   ├── count_loc.py               # 浅克隆全部原创仓库,统计代码行数
│   ├── render_profile.py          # stats.json → 两张 SVG + README 徽章
│   └── requirements.txt           # 只有 pillow
└── .github/workflows/update-stats.yml   # 每日 cron,数据变了才提交
```

流水线:`fetch_stats.py → count_loc.py → render_profile.py`,中间产物落在 `.profile-build/`(gitignore),最终只提交 README 和两张卡。本地跑同一条命令,预览效果和线上完全一致。

截至 2026-11-11 的实测数字:Stars 1,094 · Followers 81 · 16 个原创公开仓库 · 全时段公开提交 739(近 12 个月 706)· 代码 412,829 行 · 近一年贡献 1,735 次(活跃 117 天,最长连击 25 天)。数字每天自动变,这组只是快照。

### 数据面:GraphQL 一次拿全

- 基础:Stars 总和、Followers、原创公开仓库数;
- 提交数:`contributionsCollection.totalCommitContributions`——注意查询窗口**最长一年**,全时段提交数要按年循环累加(我从 2018 建号查到现在);
- 贡献热力图:`contributionCalendar` 直接给每一天的贡献数,重绘成热力图 + 连击/活跃天数等衍生指标;
- 代码行数:GraphQL 没有这个字段,自食其力——浅克隆全部原创公开仓库(`--depth 1`),按扩展名统计代码行,排除 Markdown/JSON 等非代码文件和注释行,口径写进文档,数字才诚实。

### 视觉面:预生成 SVG 卡片

- ASCII 肖像:GitHub 头像 → 漫水填充抠背景 → 红通道加权亮度映射色阶 → 彩色字符网格。每个字符是独立 `<text>` 定位,不依赖等宽字体假设,跨平台不散架。
- 布局:1280 宽圆角卡、暖橙色板(`#FA9439` / `#FAA67C` / `#3F2414` / `#FEF9EB`)、终端窗口母题,和主页其他卡片同一套视觉语言。
- 热力图:53 周 × 7 天网格,5 级橙色阶 + 图例,配活跃天数、最长连击、当前连击、最佳单日四枚数据条。

### 自动化面:Actions 每日定时

`cron: "17 3 * * *"` 每日跑一次(错开整点,避开高峰),拉数 → 统计 → 重绘 → **只在数据变化时提交**(确定性渲染,数字没动 diff 就是空的,不制造垃圾提交)。

## 四、踩坑提醒

1. **GraphQL 贡献窗口限一年**:查"全时段提交数"必须按年循环,单次查询拿不到。
2. **代码行数口径要自己定义并写清楚**:排除哪些文件、算不算注释,不同工具差很多。口径不写,数字就是营销。
3. **克隆中断会产生残缺目录**:重跑时残缺目录会被误判为已完成,数字静默变小。对策:克隆到临时目录、成功后原子改名,失败自动重试,重试完仍失败就让任务红掉——绝不发布悄悄缺了一块的数字。
4. **SVG 在 GitHub 上经 camo 代理渲染**:外部字体和脚本会被剥离,SMIL 动画和内联样式没问题;文字排版别赌等宽字体,字符逐个定位最稳。
5. **确定性渲染**:生成物里不要放时间戳,否则每天都有无意义 diff;数字不变,文件就不变。
6. **徽章和卡片分开**:`img.shields.io` 动态徽章适合挂行内小指标,信息量大的用预生成 SVG 卡片,布局完全可控。

## 五、抄作业清单

- [ ] 建 `username/username` 公开仓库,`README.md` 自动上主页
- [ ] 三档工具选一档(求快选①,要照片+动画选②,要完全可控选③)
- [ ] 定一套色板和卡片版式,所有卡片共用一套视觉语言
- [ ] 配 workflow:定时 cron + `workflow_dispatch` 手动触发 + 只在变化时提交
- [ ] 需要"代码行数"这类接口没有的指标,写脚本自己数,并公开口径
- [ ] 跑一遍手动触发,确认数字、卡片、徽章三处一致再收工

---

*作业本:[github.com/TeFuirnever/TeFuirnever](https://github.com/TeFuirnever/TeFuirnever) —— scripts/ 与 workflow 全部开源,可整套 fork 后改用户名即用。*
