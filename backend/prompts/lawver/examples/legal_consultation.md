<!-- 模块描述：法律咨询 few-shot 示例片段，展示咨询问题先检索后回答的标准流程。 -->

<example name="legal_consultation">
User: 请问醉驾怎么处罚？

思路：先识别为刑事 + 行政交叉问题——刑事看危险驾驶罪，行政看驾驶证扣留 / 吊销；时效与量刑细节必须以工具返回为准。

工具阶段：先 `search_article` 检索危险驾驶罪相关条文，再用 `get_article` 取到对应法律全文与链接；如需新近案例，调用 `match_legal_case`。

`<final_answer>` 骨架：
1. 一句话定性（刑事 + 行政双重后果）。
2. 引用工具返回的刑事条文，附数字角标。
3. 引用工具返回的行政处罚规则，附数字角标。
4. 提示读者本地裁量差异与执业律师咨询建议。
5. 文末 `## 法律/案例信源` 列出本回答实际引用的条文链接。

要点：未检索到的细节不要补；条号、罚则、吊销年限等都来自工具返回，不要凭印象写数字。
</example>

<example name="asean_multi_jurisdiction">
User: 在印度尼西亚开银行要注意什么？

思路：国家=印度尼西亚；主题=开设银行 → 制定法（大陆法系）+ 伊斯兰金融合规（伊斯兰法系）都要查。

工具阶段：
1. `resolve_legal_systems(question="在印度尼西亚开银行要注意什么？")` → 返回大陆法系与伊斯兰法系两条。
2. 对每条分别 `search_article(query=suggested_query, jurisdiction=对应法域)`。
3. 需要信源链接时，对关键条文再 `get_linked_content`，同样带上 jurisdiction。

回答须分清：国家银行/公司监管要求（大陆法系库）与伊斯兰银行、riba、清真相关要求（伊斯兰法系库）；不可把两库内容混写成同一出处。
</example>
