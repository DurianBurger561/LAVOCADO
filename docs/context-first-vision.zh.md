# 上下文优先的视觉保护

LAVOCADO 先判断当前应用或网站是否需要视觉保护，再看像素。Vision 不推断医学、
艺术、教育或新闻目的。这些例外由用户通过白名单主动管理。

> LAVOCADO 先通过应用 / 网站黑白名单判断当前上下文是否需要视觉保护；黑名单
> 直接 FORCE_BLOCK，白名单直接 FULL_BYPASS，只有 NORMAL 才运行 Vision。Vision
> 只判断画面是否违反视觉内容规则。白名单环境中显示的内容由用户自行负责。

分层、基准测试拆分和隐私边界见 [英文说明](context-first-vision.md)。
