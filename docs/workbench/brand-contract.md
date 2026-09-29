# Lawver 品牌复用契约

依据本轮用户纠正：Quote 只提供布局与交互参考，不能替换 Lawver 的品牌系统。用户提到的两个文件是品牌示例，不是唯一允许使用的资产。

- 应用组合字标：复用 `src/components/Brand.tsx` 的 `BrandLockup`，保持斜体 L、Cormorant Garamond 字形与原有尺寸关系。
- 小尺寸导航、头像、加载与独立标识：复用 `BrandMark`，不使用普通文字、emoji 或通用图标代替。
- 静态资源场景：使用 `src/assets/logo-wordmark.svg`、`logo-mark.svg`、`favicon.svg`；PWA 安装图标沿用 `public/pwa-icon-*.png`。
- 官网：复用现有 Vue `BrandLogo` 的 full / compact / hero / mark-only 变体；不引入跨框架 React 组件。
- 字体：继承现有 `--font-brand`、`--font-serif`、`--font-sans`、`--font-mono`。品牌 Cormorant Garamond，法律标题/文档 Noto Serif SC，界面 Inter / Noto Sans SC。
- 配色：继承 `--brand-logo-*`、`--accent*`、`--bg-*`、`--fg-*`、`--border-*`。由 `ThemeContext` 与 `palette.ts` 管理深色、自定义种子色和 Android Monet，不另写一套硬编码配色覆盖。
- 生成的四组早期视觉图只作为信息布局参考。其替代字标、字体和品牌蓝块已被用户否定，不作为像素复刻依据。

- 组件形态：圆角、阴影和过渡复用 `--radius-*`、`--shadow-*`、`--dur-*`、`--ease-*`；选区高亮从 `--accent` 派生，错误与审阅结果使用现有语义色，避免固定色绕过主题。

## 2026-09-28 浏览器核对

1. 导航组合标识直接使用 `BrandLockup`，顶栏及会话空态使用 `BrandMark`。
2. 字标实际计算字体为 Cormorant Garamond，首字母 L 保留 italic。
3. 首页标题与文档采用 Noto Serif SC，界面采用 Inter / Noto Sans SC。
4. 默认强调色为既有 `#3b62b8`；选区、控件与背景从主题变量继承，工作台 CSS 无独立十六进制颜色。
5. 已在原设置页切换深色检查工作台；标识、文字、边框与工作面继承原深色主题。
6. 原有项目导航、留白、文档中心结构继续保留；早期概念图的无衬线蓝字标与大面积蓝色新建按钮不采用，以现有品牌组件为准。

验证：TypeScript、Vite 与 Astro 构建通过；构建仍提示部分 chunk 超过 500 kB。品牌修正不代表整个工作台 M1–M5 验收完成。

## 2026-09-29 会话标签改版后核对

1. 侧栏改为纯文件区，会话入口移到主区顶部的会话标签条；导航组合标识仍用 `BrandLockup`，会话空态仍用 `BrandMark`。
2. 标签条、标签右键菜单、首页建议 chips 全部取自 `--accent*`、`--wb-*`、`--radius-*`、`--shadow-*`、`--dur-*`、`--ease-*`，未新增硬编码颜色（危险项沿用 `--color-danger-500`）。
3. 样式按主题拆成 `workbench.{shell,tabs,nav,home,session,document,overlays,responsive}.css`，由 `workbench.css` 按原顺序 `@import`；新增规则请落到对应主题文件，避免在 shell 里堆叠。
4. 组件拆分：`Workbench.tsx` 只保留状态、副作用与编排，视图在 `SessionView/HomeView/Sidebar/TabStrip/HistoryMenu/ManageMenu`，数据在 `useWorkbenchIndex/useSuggestions`，纯函数在 `activity.ts`，标签模型在 `tabs.ts`。

## 2026-09-29 登录页与功能页统一

登录页此前混用 Tailwind 工具类与遗留的 `md3-*`（Material 3）类，与工作台是两套视觉。现改为同一套 island 语言，样式集中在 `frontend/src/components/login.css`（类前缀 `.lg-`，只用全局令牌，随主题切换）：

- 结构：暖画布（`--bg-app`）上一张 400px 白卡（`--bg-surface` + `--radius-lg` + `--shadow-2`），`BrandLockup` 组合字标 + 宋体标题（`--font-serif`）。
- 控件：标签在输入框上方（不再用占位符当标签），输入框 42px、主按钮 44px，圆角与工作台一致（`--radius-sm`），强调色取自 `--accent` / `--accent-on`。
- 状态齐全：错误内联在字段上方（`role=alert` + `aria-live`，失败后焦点回密码框并全选）、提交中禁用 + 旋转指示、`--border-default` 静止边界、`:focus` 用强调色描边 + `--accent-quiet` 光圈。
- 可访问性实测（按令牌换算 WCAG 对比度）：标题 17.9 / 15.4，正文与标签 4.76 / 5.76，占位符 10.0 / 11.7，主按钮 5.79 / 6.42（浅色 / 深色），全部达到 AA，多数达 AAA。
- 键盘：用户名字段 Enter 跳到密码框，密码框 Enter 直接提交（不依赖浏览器隐式提交，实测部分内嵌环境不触发）。
- 通过 IP 直连的安全提示（原为硬编码 Tailwind 颜色）改为 `.lg-notice`，与卡片同列居中，窄屏自动堆叠。

## 2026-09-29 执行过程（思考区）的位置与样式

- **入口位置**：状态与「查看思考过程」开关放在消息标签行里、`Lawver` 的右侧（`Lawver  [✓ 任务已完成 · 查看思考过程 ⌄]  …  分支`），不再堆在消息底部。运行中开关显示当前动作（如「正在执行 检索法条」）并自动展开，结束后可随时收起/展开。
- **展开区域**：`--bg-inset` 填充 + `--radius-md` 圆角的内嵌面板，不再使用「蓝色左侧竖条 + 品牌色淡底」的引用块样式；正文 13px/1.75 用 `--fg-2`，代码片段反过来用 `--bg-surface` 才分得出层次。
- **标签文案**：时间线小标题改中文句首（思考 / 初稿 / 工具 / 计划 / 输出审查 / 记忆；其余事件错误 / 工具结果 / 状态 / 提示 / 执行），去掉 10px 全大写英文眉标。
- **终态任务可回看**：重新进入会话时对已结束的 run 补拉一次事件，因此「查看思考过程」在回看历史会话时依然能展开。
