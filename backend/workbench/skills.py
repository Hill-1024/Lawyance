BUILTINS = [
    (
        "contract",
        "审查合同",
        "检查权利义务、履行条件、违约责任与争议解决。逐项说明风险、依据和修改建议；使用 propose_document_change 提出可审阅修改，不覆盖原文。",
    ),
    (
        "draft",
        "生成文书",
        "先核对文书种类、当事人、事实与诉求，缺失信息明确留空。使用 create_document 交付可编辑文书。不得编造事实或法律依据。",
    ),
    (
        "organize",
        "整理材料",
        "依据用户明确引用的文件整理事实、时间线、争点和证据，标明来源，区分已证实信息与待核实信息。",
    ),
    (
        "research",
        "案例检索",
        "先明确争点和管辖，调用可用法律检索工具，给出可核验来源与原文。未取得的信息明确标注未知，不编造案例或适用时间。",
    ),
    (
        "company",
        "企业调查",
        "使用可用企业查询工具汇总登记、股权及关联信息，标注来源和查询时间；区分数据事实与推断。",
    ),
    (
        "court",
        "庭审准备",
        "整理庭审争点、证据清单、提问及可能抗辩，区分公开材料与用户私有策略，不披露私有策略给模拟对方。",
    ),
]


def builtins():
    return [
        dict(
            id="builtin-" + key,
            kind="skill",
            title=title,
            revision=1,
            data=dict(
                instructions=instructions, published=True, enabled=True, builtin=True
            ),
        )
        for key, title, instructions in BUILTINS
    ]
