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
