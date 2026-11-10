# 学院 logo 资源

透明底母版：`academy-logo-transparent.png`。网页、启动器与程序图标分别使用 `frontend/public/assets/academy-logo.png`、`academy-launcher.png` 与 `academy.ico`。派生文件必须保留 RGBA alpha，不得转换为 RGB 或铺白底。图案、颜色及文字沿用用户原图。

2026-11-10 使用内置 image_gen 工具移除背景，没有使用 CLI/API 回退。已检查透明通道范围为 0–255，并在界面的米白背景上检查文字和边缘。本次仅替换源码图片资源，按用户要求暂不重新封装 EXE；音频逻辑未修改。

使用的完整提示词：

> Use case: background-extraction. Edit target: the provided Qingjin Academy logo image. Remove ONLY the off-white background and make it genuinely transparent with clean anti-aliased alpha edges, including the white spaces between book leaves, fingers, plant leaves, circular brush strokes, Chinese characters and English letters. Preserve the exact existing artwork, all colors and gradients, proportions, placement and fine strokes. Preserve all text verbatim: 青衿学院 and Qingjin Academy, including the horizontal decorative rules. No redesign, no extra graphics, no shadows, no recoloring, no replacement typography, no visible checkerboard baked into the image. Output a transparent PNG of this same complete logo, centered with a modest transparent margin. This is an existing brand asset; only background removal is authorized.
