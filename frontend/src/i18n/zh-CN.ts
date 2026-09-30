/*
 * 模块描述：简体中文词条（源语言），也是词条表的**类型来源**。
 *
 * 约定：
 *   · 这里是唯一的事实源，其它语言按同一结构提供；缺键回退到这里；
 *   · 键用「命名空间.语义」的点分路径（workbench.tabs.close），不要写句子当键；
 *   · 带参数的文案写 `{name}` 占位符，由 t() 做插值；
 *   · 面向屏幕阅读器的可访问名（aria-label / title）与可见文案走同一套词条，
 *     所以无障碍内容天然跟着语言切换。
 */

export const zhCN = {
  common: {
    close: "关闭",
    cancel: "取消",
    confirm: "确定",
    save: "保存",
    retry: "重试",
    unknownError: "操作失败，请稍后重试。",
  },
  login: {
    title: "登录工作台",
    username: "账号",
    password: "密码",
    submit: "登录",
    backHome: "返回首页",
    loggingIn: "正在登录…",
  },
  workbench: {
    shell: {
      openNav: "打开导航",
      closeNav: "关闭导航",
      workspaceLayout: "布局",
      skillsAndPlugins: "技能与插件",
      localArchive: "本地旧资料",
      settings: "设置",
      unlimited: "不限",
      credits: "credits",
    },
    tabs: {
      newTab: "新建会话标签页",
      newTabHint: "新建会话标签页（悬停或按 ↓ 可选择模拟庭审）",
      newTabMenuLabel: "新建",
      newSession: "会话",
      newCourt: "模拟庭审",
      close: "关闭 {title}",
      running: "任务运行中",
      unseen: "已有新结果",
      fullscreenOn: "会话全屏",
      fullscreenOff: "并排显示文档",
      history: "会话历史",
      historyMenuLabel: "会话历史",
    },
    home: {
      suggestions: "工作建议",
      refreshSuggestions: "换一批",
      refreshSuggestionsHint: "按当前材料重新生成建议",
      recentSessions: "最近会话",
      openHistory: "查看全部",
      projects: "项目",
      filterAll: "全部",
      filterRecent: "最近",
      newProject: "新建项目",
      emptySessions: "发送第一条消息，开启会话。",
      manage: "管理 {title}",
      greetingMorning: "早上好，今天先处理哪件事？",
      greetingAfternoon: "下午好，今天先处理哪件事？",
      greetingEvening: "晚上好，今天先处理哪件事？",
      greetingLead: "从左侧选择文件，或直接描述你要完成的工作。",
      today: "今天",
    },
    composer: {
      placeholder: "描述你的法律问题，或用 @ 引用材料…",
      send: "发送任务",
      stop: "停止生成",
      upload: "上传文件",
      reference: "引用",
      referenceHint: "引用材料（@）",
      skill: "技能",
      skillHint: "选择技能（$）",
      task: "任务",
      taskHint: "任务模板（/）",
      taskSettings: "任务设置",
      taskMode: "任务模式",
      taskModeStandard: "标准",
      taskModePlan: "规划与执行",
      ocp: "高级输出审查",
      disclaimer: "法律意见需结合事实核验 · 仅使用本次明确引用的资料",
      offlineHint: "离线可编辑草稿；联网后请主动发送。",
      removeReference: "移除 {title}",
      candidates: "引用候选",
      closeCandidates: "关闭候选",
    },
    session: {
      headingDoc: "与文档一起思考",
      headingChat: "当前会话",
      untitled: "新的开始",
      emptyDoc: "让思考与文档同行",
      emptyChat: "从一个问题开始",
      emptyDocLead: "选择文档片段，即可提问、解释或提出修改建议。",
      emptyChatLead: "引用材料，选择技能，描述你希望完成的工作。",
      branch: "从此处分支",
      you: "你",
      assistant: "Lawver",
      runFailed: "任务未完成",
      runStalled: "上一轮没有收到回复，可能是任务失败或被中断，可以重新发送。",
      runFailedFallback: "本轮任务执行失败，请重试；若反复失败请把时间点告诉管理员。",
      connectInterrupted: "连接中断，正在恢复任务状态…",
      viewRun: "查看执行过程",
      collapseRun: "收起执行过程",
      viewThought: "查看思考过程",
      collapseThought: "收起思考过程",
      openDocument: "打开文档",
    },
  },
} as const;

export type Messages = typeof zhCN;
