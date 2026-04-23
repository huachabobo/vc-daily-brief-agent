# VC 信息聚合 Agent 设计文档

这个 Agent 的目标不是“全网抓更多”，而是每天产出一份 VC 合伙人 5 分钟看完的手机简报。原型真实接入 YouTube 和 RSS，X 与公众号给出扩展方案。

## 1. 架构设计

系统采用单流水线，便于调试、重跑和长期运行。

```text
Scheduler
   |
Fetch -> Raw Store -> Normalize/Dedup -> Rank -> Summarize -> Brief -> Feishu
                                                                  |
                                                                  v
                                                            Feedback -> Preference
```

`Fetch` 采集内容；`Raw Store` 保存原始数据；`Normalize/Dedup` 统一字段并去重；`Rank` 打分；`Summarize` 生成两句摘要和 `why it matters`；`Brief` 负责编排；`Feedback/Preference` 把“有用 / 不想看”写回数据库并影响下一轮排序。

## 2. 数据采集方案

- `YouTube`：用 Data API 从频道白名单增量抓最新视频，稳定、结构化好，但受配额限制。
- `RSS`：补充网站型高信号源，如 TechCrunch AI、SemiEngineering、The Robot Report，接入快但摘要质量参差，需要规则和 LLM 补足。
- `Twitter/X`：生产上可用官方 API 或合规第三方服务围绕白名单账号拉时间线，而不是做大规模关键词海捞。限制是权限和成本高、噪音多。
- `公众号`：技术风险最高，抓取稳定性差且合规边界更敏感。原型不设为强依赖；生产上更适合 RSS、合作源或人工白名单。

## 3. “高质量”怎么定义

冷启动阶段，“高质量”被定义为“能影响投资判断的新增信号”，而不是流量高。规则包括：只保留 AI、芯片、机器人主题；对白名单来源加权；对“融资、发布、benchmark、部署、量产、政策、供应链”等词加分；对“广告、课程、直播预告、抽奖、重复搬运”减分；再用 `ID + 标题近似` 去重。

有了反馈后，不训练模型，而是做轻量在线学习：`useful` 提高 source、topic、phrase 权重，`dislike` 降低权重，下一轮排序直接叠加这些偏好分。同时保留 1 个探索位，避免越学越窄。

## 4. 简报设计

简报按手机阅读场景设计：顶部是“今日 3 个重点”和“今日变化”，中间按 `AI / 芯片 / 机器人` 分组，正文控制在 5 到 8 条；每条固定包含标题、两句摘要、`why it matters`、`why selected`、来源链接、标签和反馈动作。

示例：

```text
[芯片] NVIDIA 新芯片发布
两句摘要
Why it matters
来源 | 标签 | 👍/👎
```

核心不是“更炫”，而是让 VC 在碎片时间里完成“扫一遍、点两条、标一次反馈”的闭环。
