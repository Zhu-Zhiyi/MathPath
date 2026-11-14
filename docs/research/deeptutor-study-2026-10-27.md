# DeepTutor 对照研究与 MathPath 迭代方案

核查日期：2026-10-27。参考项目为 [HKUDS/DeepTutor](https://github.com/HKUDS/DeepTutor)，固定源码提交 [`a31d826`](https://github.com/HKUDS/DeepTutor/tree/a31d82624c27d75f4e771d4fcb78dce16470b383)。MathPath 对照版本为 v0.5.1，提交 `69624de4a0ebaab68c224e9a03fdb1e90b1fb81d`。

本次固定获取了 28 份公开源码、说明和测试文件，重点审阅教学流程、反馈、记忆、路线修订和对应界面。未安装或运行 DeepTutor；阅读测试用例不等于执行测试，也不能证明教学效果。本轮没有更改 MathPath 运行代码、迁移数据或调用 MathPath 的真实模型。以下把源码事实与我们的拟议设计分开。

## 结论与项目定位

DeepTutor 与 MathPath 在目标引导、提问、练习、学习路径、记忆和可视化方面确实重叠，值得作为主要相关项目。当前实现已经采用共享 Agent 运行机制和不同能力自己的流程；截图中的概览不能代替对当前实现的核查。[上游能力入口](https://github.com/HKUDS/DeepTutor/blob/a31d82624c27d75f4e771d4fcb78dce16470b383/deeptutor/capabilities/mastery/capability.py#L1-L20)

MathPath 的下一步重点应是**可检查的数学先修依赖、数学约定，以及从困惑到独立作答的学习过程**。这是一项产品定位选择，不是对同类项目独创性的声明。课程展示应清楚引用相关项目，并通过自己的实际评测说明使用价值。

最有价值的借鉴是：让教学动作能执行、学习证据能回查、反馈能质疑、路线调整能审阅。现有 Windows/FastAPI/NetworkX/受限 SVG 架构足以先实现一个小版本。

## 已有能力与真正缺口

| 方向 | MathPath 已有 | 下一步可借鉴的部分 |
|---|---|---|
| 学习路径 | AND/OR 先修组、本地路线计算、编号、能力自报 | 将当前卡点、待答题、复习与聊天统一为一个下一教学动作 |
| 练习与反馈 | 诊断、微练习、提示、开放题、独立题、复习、题目快照 | 在对话中直接送达可作答题卡，并把答题反馈接回同一目标 |
| 反馈可靠性 | 模型候选意见、待核对标记、原始作答 | 针对某条反馈提出质疑并持久保存，重评保留旧记录 |
| 历史与记忆 | 项目、历史、笔记、问答；模型最近十轮上下文 | 带原问答定位的教学记忆；明确哪些早期内容未进入本次请求 |
| 来源与图示 | 教材链接、章节、审阅状态、SVG 图示 | 引用具体原文片段，区分原文证据、教学示意和模型建议 |
| 路线修改 | 保存版本冲突检查、旧题快照 | 修改草案、精确差异、用户确认与旧版本保留 |

因此，不能把“增加练习、历史、来源链接”当作本轮的新发现；这些功能已存在，改进应集中在它们之间的衔接。

## 借鉴一：统一下一教学动作

DeepTutor 的 `next_objective` 依次处理待答问题、到期复习和未完成目标，再选择讲解、探查、练习或评估；模型教学行为和确定性状态规则各有边界。[策略实现](https://github.com/HKUDS/DeepTutor/blob/a31d82624c27d75f4e771d4fcb78dce16470b383/deeptutor/learning/policy.py#L266-L368)

MathPath 可在 `planner.py`、`study_builder.py` 与 `teaching_help.py` 之间增加小型教学决策适配层：一次只给出一个知识点、一个动作、选择依据和一个检查问题。节点必须属于当前地图，先修可用性继续由本地规划器判断。模型提出补先修时应产出修订建议，不能悄悄改变图。

建议先复用现有练习、反馈和本地参考接口，不增加多个互相讨论的模型。验收时分别检查动作是否合法、是否回应困惑、数学内容是否正确，不能只检查 JSON 可解析。

## 借鉴二：聊天中的练习也成为真实学习记录

DeepTutor 的流程会检查出题操作是否产生成功的题卡投递回执；只有“我已给你一道题”的文字不算完成出题。这也不意味着学生已经阅读或掌握。[题卡投递检查](https://github.com/HKUDS/DeepTutor/blob/a31d82624c27d75f4e771d4fcb78dce16470b383/deeptutor/capabilities/mastery/loop.py#L489-L587)

MathPath 可将“给我一道练习”连接到已有任务快照：显示题卡、接收作答、保存反馈，再建议继续或回看先修。任务与请求都要有稳定 ID；保存失败、切换历史、取消和重试不能造成丢失、串历史或重复记录。收到候选反馈与确认已保存应分别显示。

在反馈旁增加“这条反馈有疑问”，把原题、原答、反馈和质疑理由连接到现有未解决问题。进一步调用模型重评由用户明确触发；原记录继续保留。[上游题卡的提交与质疑状态](https://github.com/HKUDS/DeepTutor/blob/a31d82624c27d75f4e771d4fcb78dce16470b383/web/components/chat/home/MasteryQuestionCard.tsx#L129-L175)

## 借鉴三：记住有证据的卡点与教学偏好

上游将显式偏好、暂定观察和教学策略效果分开保存；声称来自学生原话的证据须能在当前消息中找到，并限制更新数量。该层本身不授予掌握。[教学反馈模型](https://github.com/HKUDS/DeepTutor/blob/a31d82624c27d75f4e771d4fcb78dce16470b383/deeptutor/learning/teaching.py#L14-L105)

MathPath 可先在单条学习历史内保存几条可查看、可更正的记录，例如“尚不理解陪集的等价关系”“这个具体矩阵例子帮助了我”。每条附原 `chat_turn_id` 或 `attempt_id`；模型猜测标为待确认。用户偏好与事实性学习证据分开，项目之间默认隔离。

较长对话再加入有界摘要。上游记忆实现保留原对话档案引用，明确摘要不是掌握状态或原始来源，摘要失败不应推进覆盖水位。[有界记忆与引用](https://github.com/HKUDS/DeepTutor/blob/a31d82624c27d75f4e771d4fcb78dce16470b383/deeptutor/capabilities/mastery/memory.py#L29-L38) [覆盖校验](https://github.com/HKUDS/DeepTutor/blob/a31d82624c27d75f4e771d4fcb78dce16470b383/deeptutor/capabilities/mastery/memory.py#L204-L245)

先保留原始问答，再增加摘要；摘要不能代替原文。需要评估早期卡点召回、错误记忆、误引和额外调用成本。

## 借鉴四：来源定位与示意图分开

DeepTutor 的相关组件使用受限的原来源页接口，并展示来源路径、页码和材料不可用等状态。组件也明确：展示回执不能证明学生已经看过内容。[来源展示](https://github.com/HKUDS/DeepTutor/blob/a31d82624c27d75f4e771d4fcb78dce16470b383/web/components/chat/home/MasterySourcePresentation.tsx#L11-L45)

MathPath 第一阶段只需让用户粘贴短文本，标记书名、章节或页码，并记录 `source_id`、内容摘要和引用范围。卡片和题目指向这些具体片段。界面清楚标记“原文片段 / 教学示意 / 模型建议”；当前 SVG 仍作为教学示意。

原文中找得到引用，不等于引用支持该数学结论；仍需检查适用条件和论证。之后再考虑单页 PDF 或图片预览，不必把完整 PDF/RAG、知识图谱检索与多模态出题同时引入。

## 借鉴五：修订路线先给草案与精确差异

上游实现先在副本中计算改变，记录基础版本及前后状态摘要，提交时拒绝过期或不匹配状态。[精确差异](https://github.com/HKUDS/DeepTutor/blob/a31d82624c27d75f4e771d4fcb78dce16470b383/deeptutor/learning/outline_revision.py#L33-L75) [预览与提交](https://github.com/HKUDS/DeepTutor/blob/a31d82624c27d75f4e771d4fcb78dce16470b383/deeptutor/learning/service.py#L1922-L2030)

MathPath 可增加“在当前路线补充先修”的候选修订，展示哪些节点、依赖和旧卡片受到影响，经用户确认后另存版本。继续验证节点上限、无环、AND/OR 引用和数学约定；不能把新题或新概念的正确性套用到旧作答。

**需要准确归因：上游不是一律要求真人确认。** 其工具描述要求后续模型轮次审阅预览，并保留部分直接内容修订入口；“必须用户确认”是建议给 MathPath 额外增加的产品要求。[上游工具边界](https://github.com/HKUDS/DeepTutor/blob/a31d82624c27d75f4e771d4fcb78dce16470b383/deeptutor/capabilities/mastery/tools.py#L2828-L2839)

## 借鉴六：展示实际请求范围与可观察状态

上游上下文预算代码根据实际组装的提示、历史和工具计算分段占用；这是值得借鉴的“说明本次请求用了什么”的思路。本次未验证其运行界面。[上下文统计](https://github.com/HKUDS/DeepTutor/blob/a31d82624c27d75f4e771d4fcb78dce16470b383/deeptutor/agents/loop/context_budget.py#L185-L238)

MathPath 可先显示本次目标、所选卡片、最近几轮、略过多少轮、是否包含教学摘要。只显示程序实际知道的环节，如“整理上下文、请求中、收到回复、保存成功”；不要编造数学核查阶段、精确百分比或未返回的 token 用量，也不展示模型内部思维链。

## 不照搬的判断规则

1. 上游语义评分可将模型置信度不低于 0.8 的结果视为 final，并在相关路径写入定性掌握。这不是数学正确性证明；MathPath 继续保留 `model_candidate` 和 `review_required`，开放题候选反馈不自动勾选掌握。[评分收据](https://github.com/HKUDS/DeepTutor/blob/a31d82624c27d75f4e771d4fcb78dce16470b383/deeptutor/learning/semantic_assessment.py#L22-L39) [相关状态写入](https://github.com/HKUDS/DeepTutor/blob/a31d82624c27d75f4e771d4fcb78dce16470b383/deeptutor/learning/service.py#L3098-L3111)
2. 上游允许明确的学习者自报覆盖，并区分其来源，不能描述成“所有节点只有测评通过才能继续”。[掌握来源](https://github.com/HKUDS/DeepTutor/blob/a31d82624c27d75f4e771d4fcb78dce16470b383/deeptutor/learning/policy.py#L140-L158)
3. 材料证据检查有适用条件。未选择相关 PDF 材料且没有旧证据时存在直接返回路径，不能声称每个回答都已核查教材。[材料条件](https://github.com/HKUDS/DeepTutor/blob/a31d82624c27d75f4e771d4fcb78dce16470b383/deeptutor/learning/lesson_evidence.py#L351-L399)
4. 仓库星数、代码量、模型数量和测试文件存在，都不能直接证明教学效果。也不因为架构规模大，就认为 MathPath 必须改用 Next.js、Docker、多用户和完整 RAG。

## 建议落地顺序与验收

| 阶段 | 交付 | 必要验收 |
|---|---|---|
| P0：教学过程衔接 | 单一步骤建议、聊天题卡、反馈质疑、实际上下文说明 | 节点和动作有效；题卡真实存在；失败不假报保存；重试不重复；不自动授予掌握 |
| P1：来源和路线 | 短原文引用、候选路线差异、用户确认与旧版本 | 引用能定位；不越过来源范围；过期修订被拒；旧作答快照仍可回查 |
| P2：长对话教学记忆 | 有界摘要、原文回查、用户纠正与删除 | 早期卡点能召回；无伪造引用；摘要失败不推进；历史和项目范围清楚 |

优先做一个端到端例子：“我不懂同调为什么取商 → 系统选一个够用的先修 → 解释 → 真实题卡 → 学生作答 → 候选反馈 → 继续或回看先修”。这能检验各模块是否形成学习过程。

评测分开报告：软件层检查送达、保存、恢复和修订冲突；内容层用同模型案例人工评审数学正确性、状态适配与教学动作；真实使用层至少收集三名用户的具体卡点和反馈。若要声称提高学习效果，还需独立题目及相应比较设计。当前原型的 352 项软件检查不能替代这些新功能或学习效果的评估。

## 研究记录与后续使用

上游固定快照及获取清单保存在本次工作区 `work/deeptutor-review`，没有带入发行包。上游标注 Apache-2.0；本轮只记录机制与自写设计，没有移植上游实现。未来若复用代码，应另外核对所涉文件的许可和第三方声明。[上游许可](https://github.com/HKUDS/DeepTutor/blob/a31d82624c27d75f4e771d4fcb78dce16470b383/LICENSE)

一次 `deepseek-reasoner` 辅助字段提取达到 180 秒期限，未正常完成；残留文件有行号和数量约束问题，未作为架构结论依据。本报告依据源码定点阅读和交叉复核，不将该辅助请求记为成功审计。
