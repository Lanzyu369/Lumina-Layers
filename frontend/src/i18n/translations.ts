/**
 * Lumina Studio - Translation Dictionary
 * Migrated from core/i18n.py TEXTS dictionary
 * Contains all zh/en translation key-value pairs
 */
export const translations: Record<string, Record<"zh" | "en", string>> = {
  // ==================== Application Title and Header ====================
  app_subtitle: {
    zh: "多材料3D打印色彩系统 | v1.6.3",
    en: "Multi-Material 3D Print Color System | v1.6.3",
  },
  app_panel_controls: {
    zh: "面板控件",
    en: "Panel Controls",
  },
  bug_report_button_label: {
    zh: "反馈问题",
    en: "Report a bug",
  },
  bug_report_button_tooltip: {
    zh: "向开发者发送 bug 反馈",
    en: "Send a bug report to the developer",
  },
  bug_report_modal_title: {
    zh: "反馈问题",
    en: "Report a bug",
  },
  bug_report_modal_description_label: {
    zh: "问题描述",
    en: "Describe the problem",
  },
  bug_report_modal_description_placeholder: {
    zh: "请详细描述发生了什么、你期望发生什么、复现步骤……",
    en: "What happened, what did you expect, and how can we reproduce it?",
  },
  bug_report_modal_email_label: {
    zh: "你的邮箱（可选，方便我们回复你）",
    en: "Your email (optional, so we can follow up)",
  },
  bug_report_modal_screenshot_label: {
    zh: "截图（可选）",
    en: "Screenshot (optional)",
  },
  bug_report_modal_screenshot_hint: {
    zh: "支持 PNG、JPG、WebP 或 GIF，最大 5 MB。",
    en: "PNG, JPG, WebP, or GIF up to 5 MB.",
  },
  bug_report_modal_screenshot_attached_label: {
    zh: "已附加截图",
    en: "Attached screenshot",
  },
  bug_report_modal_screenshot_remove: {
    zh: "移除截图",
    en: "Remove screenshot",
  },
  bug_report_modal_context_disclosure: {
    zh: "已自动收集的信息（点击展开）",
    en: "Automatically collected info (click to expand)",
  },
  bug_report_modal_context_summary_heading: {
    zh: "上下文摘要",
    en: "Context summary",
  },
  bug_report_modal_context_summary_none: {
    zh: "当前没有可用的上下文信息。",
    en: "No context information available right now.",
  },
  bug_report_modal_context_active_tab: {
    zh: "标签",
    en: "Tab",
  },
  bug_report_modal_context_color_mode: {
    zh: "颜色模式",
    en: "Color mode",
  },
  bug_report_modal_context_lut: {
    zh: "LUT",
    en: "LUT",
  },
  bug_report_modal_context_recent_actions: {
    zh: "近期操作",
    en: "Recent actions",
  },
  bug_report_modal_context_recent_errors: {
    zh: "近期接口错误",
    en: "Recent API errors",
  },
  api_error_http_400: {
    zh: "请求数据无效，请检查填写的值。",
    en: "Request data is invalid. Please check the entered values.",
  },
  api_error_http_401: {
    zh: "继续操作前需要先完成登录或认证。",
    en: "Authentication is required before this action can continue.",
  },
  api_error_http_402: {
    zh: "此操作需要可用额度或付款状态后才能继续。",
    en: "This action requires an available quota or payment before it can continue.",
  },
  api_error_http_403: {
    zh: "你没有权限执行此操作。",
    en: "You do not have permission to perform this action.",
  },
  api_error_http_404: {
    zh: "请求的资源不存在或已过期。",
    en: "The requested resource was not found or has expired.",
  },
  api_error_http_405: {
    zh: "所选接口不支持此操作。",
    en: "This action is not supported by the selected API endpoint.",
  },
  api_error_http_408: {
    zh: "服务器未能在超时前完成请求。",
    en: "The request timed out before the server could finish.",
  },
  api_error_http_409: {
    zh: "请求与当前服务器状态冲突。",
    en: "The request conflicts with the current server state.",
  },
  api_error_http_413: {
    zh: "上传文件或请求内容过大。",
    en: "The uploaded file or request is too large.",
  },
  api_error_http_415: {
    zh: "服务器不支持此文件类型。",
    en: "This file type is not supported by the server.",
  },
  api_error_http_422: {
    zh: "请求缺少必填数据或包含无效值。",
    en: "The request is missing required data or contains invalid values.",
  },
  api_error_http_429: {
    zh: "请求过于频繁，请稍后再试。",
    en: "Too many requests were sent. Please wait and try again.",
  },
  api_error_http_500: {
    zh: "服务器发生内部错误。请稍后重试；如果问题持续，请提交反馈。",
    en: "The server hit an internal error. Try again later, or submit feedback if it keeps happening.",
  },
  api_error_http_500_with_request_id: {
    zh: "服务器发生内部错误。请求 ID：{requestId}。",
    en: "The server hit an internal error. Request ID: {requestId}.",
  },
  api_error_http_502: {
    zh: "处理请求时上游依赖失败。",
    en: "An upstream dependency failed while handling this request.",
  },
  api_error_http_503: {
    zh: "服务器暂时不可用，请稍后再试。",
    en: "Server temporarily unavailable. Please try again later.",
  },
  api_error_http_504: {
    zh: "服务器等待依赖服务时超时。",
    en: "The server timed out waiting for a dependency.",
  },
  api_error_http_default: {
    zh: "接口请求失败。请重试；如果问题持续，请提交反馈。",
    en: "The API request failed. Try again, or submit feedback if it keeps happening.",
  },
  api_error_http_client_default: {
    zh: "请求未被服务器接受。请检查当前输入、权限或资源是否仍然可用。",
    en: "The server did not accept the request. Check the current input, permissions, or resource availability.",
  },
  api_error_http_server_default: {
    zh: "服务器处理请求时失败。请稍后重试；如果问题持续，请提交反馈。",
    en: "The server failed while handling the request. Try again later, or submit feedback if it keeps happening.",
  },
  api_error_no_response: {
    zh: "请求没有收到服务器响应。请确认 Lumina 后端已启动、网络连接正常，然后重试。",
    en: "The request did not receive a server response. Make sure the Lumina backend is running, check the network connection, and try again.",
  },
  api_error_with_request_id: {
    zh: "{message}请求 ID：{requestId}。",
    en: "{message} Request ID: {requestId}.",
  },
  bug_report_modal_privacy_note: {
    zh: "本反馈仅发送到 Lumina Studio 开发者邮箱，用于定位和回复问题。",
    en: "This report is sent only to the Lumina Studio developer mailbox for triage and follow-up.",
  },
  bug_report_modal_submit: {
    zh: "发送",
    en: "Send",
  },
  bug_report_modal_cancel: {
    zh: "取消",
    en: "Cancel",
  },
  bug_report_toast_success: {
    zh: "已收到，谢谢。工单号：{{ticket}}",
    en: "Thanks, we got it. Ticket: {{ticket}}",
  },
  bug_report_toast_error: {
    zh: "提交失败，请稍后再试。",
    en: "Submission failed, please retry.",
  },
  bug_report_fallback_intro: {
    zh: "如果多次失败，请复制下面的反馈内容，通过邮箱或即时通讯发给开发者。",
    en: "If submission keeps failing, copy the report below and send it to the developer by email or chat.",
  },
  bug_report_fallback_copy: {
    zh: "复制反馈内容",
    en: "Copy report",
  },
  bug_report_fallback_copied: {
    zh: "反馈内容已复制",
    en: "Report copied",
  },
  bug_report_fallback_copy_failed: {
    zh: "自动复制失败，请手动选中文本复制。",
    en: "Automatic copy failed. Select the report text and copy it manually.",
  },
  bug_report_fallback_mailto: {
    zh: "用默认邮箱发送",
    en: "Send with default mail app",
  },
  bug_report_fallback_qq_mail: {
    zh: "打开 QQ 邮箱",
    en: "Open QQ Mail",
  },
  bug_report_relay_prompt: {
    zh: "本机邮件未成功发送。是否同意将这份反馈转发到 Lumina Studio 官方问题收集服务？",
    en: "Local email delivery did not succeed. Do you agree to forward this report to the Lumina Studio official bug collection service?",
  },
  bug_report_relay_privacy: {
    zh: "转发内容包含你的问题描述、可选邮箱、截图和自动收集的环境信息，仅用于定位和回复问题。",
    en: "The forwarded report includes your description, optional email, screenshot, and automatically collected diagnostic context, only for triage and follow-up.",
  },
  bug_report_relay_send: {
    zh: "同意并转发",
    en: "Agree and forward",
  },
  bug_report_relay_skip: {
    zh: "不转发，手动发送",
    en: "Do not forward; send manually",
  },
  bug_report_relay_success: {
    zh: "已转发到官方问题收集服务。",
    en: "Forwarded to the official bug collection service.",
  },
  bug_report_relay_failed: {
    zh: "官方转发失败，请使用下面的手动方式发送。",
    en: "Official forwarding failed. Use one of the manual options below.",
  },
  bug_report_relay_unavailable: {
    zh: "官方转发未配置，请使用下面的手动方式发送。",
    en: "Official forwarding is not configured. Use one of the manual options below.",
  },
  bug_report_relay_skipped: {
    zh: "未转发到官方服务，请使用下面的手动方式发送。",
    en: "Official forwarding was skipped. Use one of the manual options below.",
  },
  bug_report_success_ticket_label: {
    zh: "工单号",
    en: "Ticket ID",
  },
  bug_report_success_copy: {
    zh: "复制",
    en: "Copy",
  },
  bug_report_success_copied: {
    zh: "已复制",
    en: "Copied",
  },
  bug_report_success_copy_failed: {
    zh: "自动复制失败，请手动选中工单号复制。",
    en: "Automatic copy failed. Select the ticket id and copy it manually.",
  },
  bug_report_success_emailed_yes: {
    zh: "报告已通过本机邮件发送给开发者。",
    en: "Report was sent to the developer mailbox from this device.",
  },
  bug_report_success_emailed_no: {
    zh: "本机邮件未成功发送，报告已保存到本地。请继续选择官方转发或手动发送。",
    en: "Local email delivery did not succeed; the report was saved locally. Choose official forwarding or send it manually.",
  },
  bug_report_success_email_pending: {
    zh: "报告已收到，邮件正在后台发送。你可以关闭此对话框，结果会在日志中记录。",
    en: "Report received; the email is being sent in the background. You can close this dialog — the outcome is captured in the logs.",
  },
  bug_report_success_email_failed: {
    zh: "本机邮件发送失败。报告已保存到本地，可以选择官方转发或手动发送。",
    en: "Local email delivery failed. The report was saved locally; choose official forwarding or send it manually.",
  },
  bug_report_success_email_unconfigured: {
    zh: "本机未配置邮件，报告已保存到本地。请选择官方转发或手动发送。",
    en: "Local email is not configured; the report was saved locally. Choose official forwarding or send it manually.",
  },
  bug_report_success_dump_path_label: {
    zh: "本地路径",
    en: "Local path",
  },
  bug_report_success_close: {
    zh: "完成",
    en: "Done",
  },
  bug_report_validation_description_required: {
    zh: "请填写问题描述",
    en: "Please describe the problem",
  },
  bug_report_validation_description_truncated: {
    zh: "问题描述已截断到 10000 个字符。",
    en: "The description was truncated to 10,000 characters.",
  },
  bug_report_validation_screenshot_type: {
    zh: "请选择图片文件作为截图。",
    en: "Choose an image file for the screenshot.",
  },
  bug_report_validation_screenshot_size: {
    zh: "截图不能超过 5 MB。",
    en: "Screenshot must be no larger than 5 MB.",
  },
  bug_report_validation_screenshot_read_failed: {
    zh: "读取截图失败，请重试。",
    en: "Could not read the screenshot. Please try again.",
  },
  lang_btn_zh: {
    zh: "🌐 中文",
    en: "🌐 中文",
  },
  lang_btn_en: {
    zh: "🌐 English",
    en: "🌐 English",
  },

  // ==================== Stats Bar ====================
  stats_calibrations: {
    zh: "校准板",
    en: "Calibrations",
  },
  stats_extractions: {
    zh: "颜色提取",
    en: "Extractions",
  },
  stats_conversions: {
    zh: "模型转换",
    en: "Conversions",
  },

  // ==================== Tab Titles ====================
  tab_about: {
    zh: "ℹ️ 关于",
    en: "ℹ️ About",
  },

  // ==================== Converter Tab ====================
  conv_title: {
    zh: "### 第一步：转换图像",
    en: "### Step 1: Convert Image",
  },
  conv_desc: {
    zh: "**两种建模模式**：高保真（RLE无缝拼接）、像素艺术（方块风格）\n\n**流程**: 上传LUT和图像 → 选择建模模式 → 调整色彩细节 → 预览 → 生成",
    en: "**Two Modeling Modes**: High-Fidelity (RLE seamless) and Pixel Art (blocky style)\n\n**Workflow**: Upload LUT & Image → Select Mode → Adjust Color Detail → Preview → Generate",
  },
  conv_lut_title: {
    zh: "**校准数据**",
    en: "**Calibration Data**",
  },
  conv_lut_dropdown: {
    zh: "选择预设",
    en: "Select Preset",
  },
  conv_lut_info: {
    zh: "从预设库中选择LUT",
    en: "Select from library",
  },
  conv_image_label: {
    zh: "输入图像",
    en: "Input Image",
  },
  crop_title: {
    zh: "图片裁剪",
    en: "Image Crop",
  },
  crop_original_size: {
    zh: "原图尺寸",
    en: "Original size",
  },
  crop_selection_size: {
    zh: "选区尺寸",
    en: "Selection size",
  },
  crop_x: {
    zh: "X 偏移",
    en: "X Offset",
  },
  crop_y: {
    zh: "Y 偏移",
    en: "Y Offset",
  },
  crop_width: {
    zh: "宽度",
    en: "Width",
  },
  crop_height: {
    zh: "高度",
    en: "Height",
  },
  crop_use_original: {
    zh: "使用原图",
    en: "Use original",
  },
  crop_confirm: {
    zh: "确认裁剪",
    en: "Confirm crop",
  },
  conv_color_mode: {
    zh: "色彩模式",
    en: "Color Mode",
  },
  conv_color_mode_cmyw: {
    zh: "CMYW (青/品红/黄)",
    en: "CMYW (Cyan/Magenta/Yellow)",
  },
  conv_color_mode_rybw: {
    zh: "RYBW (红/黄/蓝)",
    en: "RYBW (Red/Yellow/Blue)",
  },
  conv_structure: {
    zh: "结构",
    en: "Structure",
  },
  conv_structure_double: {
    zh: "双面",
    en: "Double-sided",
  },
  conv_structure_single: {
    zh: "单面",
    en: "Single-sided",
  },
  conv_modeling_mode_info: {
    zh: "高保真：RLE无缝拼接，水密模型 | 像素艺术：经典方块美学 | SVG模式：矢量直接转换",
    en: "High-Fidelity: RLE seamless, watertight | Pixel Art: Classic blocky aesthetic | SVG Mode: Direct vector conversion",
  },
  conv_quantize_info: {
    zh: "颜色数量越多细节越丰富，但生成越慢",
    en: "Higher = More detail, Slower",
  },
  conv_auto_color_btn: {
    zh: "自动计算",
    en: "Auto Detect",
  },
  conv_auto_color_calculating: {
    zh: "⏳ 计算中...",
    en: "⏳ Calculating...",
  },
  conv_width: {
    zh: "宽度 (mm)",
    en: "Width (mm)",
  },
  conv_height: {
    zh: "高度 (mm)",
    en: "Height (mm)",
  },
  conv_thickness: {
    zh: "背板 (mm)",
    en: "Backing (mm)",
  },
  conv_backing_color: {
    zh: "底板颜色",
    en: "Backing Color",
  },
  converter_preview_2d_alt: {
    zh: "2D 预览图",
    en: "2D preview image",
  },
  canvas_preview_load_failed: {
    zh: "预览资源加载失败。请重新生成预览或刷新后再试。",
    en: "Preview resource failed to load. Regenerate the preview or refresh and try again.",
  },
  conv_palette_step1: {
    zh: "### 1. 原图颜色（点击预览图）",
    en: "### 1. Original Color (Click Preview)",
  },
  conv_palette_step2: {
    zh: "### 2. 替换为（点击色块）",
    en: "### 2. Replace With (Click Swatch)",
  },
  conv_palette_selected_label: {
    zh: "当前选中",
    en: "Selected",
  },
  conv_palette_replace_label: {
    zh: "将替换为",
    en: "Replace With",
  },
  conv_palette_lut_loading: {
    zh: "⏳ 正在加载 LUT 颜色...",
    en: "⏳ Loading LUT colors...",
  },
  conv_palette_replacements_placeholder: {
    zh: "生成预览后显示替换列表",
    en: "Generate preview to see replacements",
  },
  conv_palette_replacements_label: {
    zh: "已生效的替换",
    en: "Applied Replacements",
  },
  conv_palette_undo_btn: {
    zh: "↩️ 撤销",
    en: "↩️ Undo",
  },
  conv_palette_user_replacements_title: {
    zh: "用户替换",
    en: "User Replacements",
  },
  conv_palette_auto_pairs_title: {
    zh: "自动配准",
    en: "Auto Pairs",
  },
  conv_palette_delete_selected_btn: {
    zh: "删除选中",
    en: "Delete Selected",
  },
  conv_palette_user_empty: {
    zh: "暂无替换",
    en: "No replacements",
  },
  conv_palette_auto_empty: {
    zh: "暂无自动配准",
    en: "No auto pairs",
  },
  // ==================== Loop / Outline / Cloisonne / Coating ====================
  conv_loop_enable: {
    zh: "启用挂孔",
    en: "Enable Loop",
  },
  conv_loop_width: {
    zh: "宽度(mm)",
    en: "Width(mm)",
  },
  conv_loop_length: {
    zh: "长度(mm)",
    en: "Length(mm)",
  },
  conv_loop_hole: {
    zh: "孔径(mm)",
    en: "Hole(mm)",
  },
  conv_loop_angle: {
    zh: "旋转角度°",
    en: "Rotation°",
  },
  conv_loop_info: {
    zh: "挂孔位置",
    en: "Loop Position",
  },
  conv_outline_section: {
    zh: "##### 外轮廓设置",
    en: "##### Outline Settings",
  },
  conv_outline_enable: {
    zh: "启用外轮廓",
    en: "Enable Outline",
  },
  conv_outline_width: {
    zh: "外轮廓厚度(mm)",
    en: "Outline Width(mm)",
  },
  conv_cloisonne_section: {
    zh: "##### 掐丝珐琅特效",
    en: "##### Cloisonné Effect",
  },
  conv_cloisonne_enable: {
    zh: "启用掐丝珐琅",
    en: "Enable Cloisonné",
  },
  conv_cloisonne_wire_width: {
    zh: "丝线宽度(mm)",
    en: "Wire Width(mm)",
  },
  conv_cloisonne_wire_height: {
    zh: "丝线高度(mm)",
    en: "Wire Height(mm)",
  },
  conv_cloisonne_wire_color: {
    zh: "丝线颜色槽位",
    en: "Wire Color Slot",
  },
  conv_free_color_btn: {
    zh: "标记为自由色",
    en: "Mark as Free Color",
  },
  conv_free_color_clear_btn: {
    zh: "清除自由色",
    en: "Clear Free Colors",
  },
  conv_free_color_label: {
    zh: "自由色",
    en: "Free Colors",
  },
  conv_coating_section: {
    zh: "##### 透明镀层",
    en: "##### Transparent Coating",
  },
  conv_coating_enable: {
    zh: "启用透明镀层",
    en: "Enable Transparent Coating",
  },
  conv_coating_height: {
    zh: "透明镀层厚度(mm)",
    en: "Transparent Coating Height(mm)",
  },
  conv_status: {
    zh: "状态",
    en: "Status",
  },
  conv_download_file: {
    zh: "3MF文件",
    en: "3MF File",
  },

  // ==================== Calibration Tab ====================
  cal_title: {
    zh: "生成校准板",
    en: "Generate Calibration Board",
  },
  cal_desc: {
    zh: "生成1024种颜色的校准板，打印后用于提取打印机的实际色彩数据。",
    en: "Generate a 1024-color calibration board to extract your printer's actual color data.",
  },
  cal_params: {
    zh: "参数",
    en: "Parameters",
  },
  cal_color_mode: {
    zh: "色彩模式",
    en: "Color Mode",
  },
  cal_block_size: {
    zh: "色块尺寸 (mm)",
    en: "Block Size (mm)",
  },
  cal_gap: {
    zh: "间隙 (mm)",
    en: "Gap (mm)",
  },
  cal_generate_btn: {
    zh: "生成",
    en: "Generate",
  },
  cal_status: {
    zh: "状态",
    en: "Status",
  },
  cal_preview: {
    zh: "预览",
    en: "Preview",
  },
  cal_download: {
    zh: "下载 3MF",
    en: "Download 3MF",
  },

  // ==================== Color Extractor Tab ====================
  ext_title: {
    zh: "提取颜色数据",
    en: "Extract Color Data",
  },
  ext_desc: {
    zh: "拍摄打印好的校准板照片，提取真实的色彩数据生成 LUT 文件。",
    en: "Take a photo of your printed calibration board to extract real color data.",
  },
  ext_photo: {
    zh: "校准板照片",
    en: "Calibration Photo",
  },
  ext_rotate_btn: {
    zh: "↺ 旋转",
    en: "↺ Rotate",
  },
  ext_correction_section: {
    zh: "校正参数",
    en: "Correction",
  },
  ext_nudge_section: {
    zh: "角点位置微调",
    en: "Corner Fine-Tune",
  },
  ext_nudge_step_label: {
    zh: "微调步长 (像素)",
    en: "Step (px)",
  },
  ext_nudge_step_hint: {
    zh: "每次点击方向按钮时角点移动的像素数量。值越大移动越快，值越小移动越精细。",
    en: "Number of pixels each directional button press moves the corner. Larger values move faster, smaller values allow finer adjustment.",
  },
  ext_nudge_active_corner_label: {
    zh: "当前调整角点",
    en: "Active Corner",
  },
  ext_nudge_hint_empty: {
    zh: "请先在画布上放置角点",
    en: "Place corners on the canvas first",
  },
  ext_nudge_up: {
    zh: "上移",
    en: "Up",
  },
  ext_nudge_down: {
    zh: "下移",
    en: "Down",
  },
  ext_nudge_left: {
    zh: "左移",
    en: "Left",
  },
  ext_nudge_right: {
    zh: "右移",
    en: "Right",
  },
  ext_nudge_keyboard_hint: {
    zh: "提示：可使用键盘方向键进行微调",
    en: "Tip: arrow keys also nudge the active corner",
  },
  ext_corner_pos_tl: { zh: "左上", en: "Top-Left" },
  ext_corner_pos_tr: { zh: "右上", en: "Top-Right" },
  ext_corner_pos_br: { zh: "右下", en: "Bottom-Right" },
  ext_corner_pos_bl: { zh: "左下", en: "Bottom-Left" },
  ext_color_white: { zh: "白色", en: "White" },
  ext_color_black: { zh: "黑色", en: "Black" },
  ext_color_cyan: { zh: "青色", en: "Cyan" },
  ext_color_magenta: { zh: "品红", en: "Magenta" },
  ext_color_yellow: { zh: "黄色", en: "Yellow" },
  ext_color_red: { zh: "红色", en: "Red" },
  ext_color_blue: { zh: "蓝色", en: "Blue" },
  ext_vignette: {
    zh: "暗角校正",
    en: "Vignette",
  },
  ext_zoom: {
    zh: "缩放",
    en: "Zoom",
  },
  ext_distortion: {
    zh: "畸变",
    en: "Distortion",
  },
  ext_offset_x: {
    zh: "X偏移",
    en: "Offset X",
  },
  ext_offset_y: {
    zh: "Y偏移",
    en: "Offset Y",
  },
  ext_status: {
    zh: "状态",
    en: "Status",
  },
  ext_marked: {
    zh: "标记图",
    en: "Marked",
  },
  ext_click_cell: {
    zh: "点击左侧色块查看...",
    en: "Click cell on left...",
  },
  ext_override: {
    zh: "替换颜色",
    en: "Override Color",
  },
  ext_download_npy: {
    zh: "下载 .npy",
    en: "Download .npy",
  },

  // ==================== 3D Viewer ====================
  viewer_fullscreen: {
    zh: "全屏",
    en: "Fullscreen",
  },
  viewer_exit_fullscreen: {
    zh: "退出全屏",
    en: "Exit Fullscreen",
  },
  viewer_screenshot: {
    zh: "截图",
    en: "Screenshot",
  },
  viewer_diagnostics_toggle: {
    zh: "3D 诊断",
    en: "Diagnostics",
  },
  viewer_diagnostics_title: {
    zh: "3D 诊断",
    en: "3D Diagnostics",
  },
  viewer_diagnostics_source: {
    zh: "来源",
    en: "Source",
  },
  viewer_diagnostics_source_generate: {
    zh: "生成 GLB",
    en: "Generated GLB",
  },
  viewer_diagnostics_source_preview: {
    zh: "预览 GLB",
    en: "Preview GLB",
  },
  viewer_diagnostics_source_idle: {
    zh: "空闲画布",
    en: "Idle Canvas",
  },
  viewer_diagnostics_fps: {
    zh: "FPS",
    en: "FPS",
  },
  viewer_diagnostics_frame_time: {
    zh: "帧时间",
    en: "Frame Time",
  },
  viewer_diagnostics_js_heap: {
    zh: "JS 堆",
    en: "JS Heap",
  },
  viewer_diagnostics_js_heap_unavailable: {
    zh: "不可用",
    en: "Unavailable",
  },
  viewer_diagnostics_geometries: {
    zh: "几何体",
    en: "Geometries",
  },
  viewer_diagnostics_textures: {
    zh: "纹理",
    en: "Textures",
  },
  viewer_diagnostics_programs: {
    zh: "Programs",
    en: "Programs",
  },
  viewer_diagnostics_draw_calls: {
    zh: "调用数",
    en: "Draw Calls",
  },
  viewer_diagnostics_triangles: {
    zh: "三角面",
    en: "Triangles",
  },
  viewer_diagnostics_canvas: {
    zh: "画布",
    en: "Canvas",
  },
  viewer_performance_toggle: {
    zh: "性能统计",
    en: "Performance",
  },
  viewer_performance_title: {
    zh: "性能统计",
    en: "Performance Stats",
  },
  viewer_performance_empty: {
    zh: "暂无性能数据",
    en: "No performance data yet",
  },
  viewer_performance_preview_title: {
    zh: "预览生成",
    en: "Preview Generation",
  },
  viewer_performance_generate_title: {
    zh: "模型生成",
    en: "Model Generation",
  },
  viewer_performance_total: {
    zh: "总耗时",
    en: "Total",
  },
  viewer_performance_upload: {
    zh: "上传处理",
    en: "Upload",
  },
  viewer_performance_worker: {
    zh: "核心计算",
    en: "Worker",
  },
  viewer_performance_pickle_load: {
    zh: "缓存读取",
    en: "Cache Load",
  },
  viewer_performance_segmented_glb: {
    zh: "预览 GLB",
    en: "Preview GLB",
  },
  viewer_performance_palette: {
    zh: "调色板",
    en: "Palette",
  },
  viewer_performance_overhead: {
    zh: "接口开销",
    en: "API Overhead",
  },
  viewer_hover_magnifier: {
    zh: "放大镜",
    en: "Magnifier",
  },
  viewer_hover_toggle_group: {
    zh: "悬停显示",
    en: "Hover Display",
  },
  viewer_hover_toggle_magnifier: {
    zh: "放大镜",
    en: "Magnifier",
  },
  viewer_hover_toggle_layers: {
    zh: "分层颜色",
    en: "Layer Colors",
  },
  viewer_hover_pixel: {
    zh: "像素坐标",
    en: "Pixel",
  },
  viewer_hover_surface_color: {
    zh: "预测颜色",
    en: "Predicted Color",
  },
  viewer_hover_layers_title: {
    zh: "分层颜色",
    en: "Layer Colors",
  },
  viewer_hover_loading_layers: {
    zh: "正在加载分层颜色...",
    en: "Loading layer colors...",
  },
  viewer_hover_no_layer_data: {
    zh: "暂无分层颜色数据",
    en: "No layer color data",
  },
  viewer_hover_transparent: {
    zh: "透明",
    en: "Transparent",
  },

  // ==================== Footer ====================
  // ==================== Status Messages ====================
  msg_click_to_place: {
    zh: "点击图片放置挂孔",
    en: "Click to place loop",
  },
  msg_resolution: {
    zh: "分辨率",
    en: "Resolution",
  },
  msg_loop: {
    zh: "挂孔",
    en: "Loop",
  },
  msg_preview_simplified: {
    zh: "ℹ️ 3D预览已简化",
    en: "ℹ️ 3D preview simplified",
  },

  // ==================== Palette / Replacement ====================
  palette_empty: {
    zh: "暂无颜色，请先生成预览。",
    en: "No colors yet. Generate a preview first.",
  },
  palette_count: {
    zh: "共 {count} 种颜色",
    en: "{count} colors in image",
  },
  palette_hint: {
    zh: "点击色块高亮预览",
    en: "Click swatch to highlight in preview",
  },
  palette_tooltip: {
    zh: "点击高亮: {hex} ({pct}%)",
    en: "Click to highlight: {hex} ({pct}%)",
  },
  palette_replaced_with: {
    zh: "替换为 {hex}",
    en: "Replaced with {hex}",
  },
  palette_click_to_select: {
    zh: "点击调色板选择颜色",
    en: "Click palette to select",
  },
  palette_undone: {
    zh: "↩️ 已撤销",
    en: "↩️ Undone",
  },
  palette_mode_select_all: {
    zh: "全选",
    en: "All",
  },
  palette_mode_current: {
    zh: "当前",
    en: "Current",
  },
  palette_mode_multi_select: {
    zh: "多选",
    en: "Multi",
  },
  palette_mode_region: {
    zh: "局部区域",
    en: "Region",
  },
  palette_multi_select_count: {
    zh: "已选 {count} 色",
    en: "{count} selected",
  },
  palette_multi_select_region_count: {
    zh: "已选 {count} 个区域",
    en: "{count} regions selected",
  },
  palette_multi_select_click_remove: {
    zh: "点击取消选择",
    en: "Click to deselect",
  },

  // ==================== Color Merging ====================
  merge_enable_label: {
    zh: "启用自动颜色合并 Enable Auto Color Merging",
    en: "Enable Auto Color Merging",
  },
  merge_enable_info: {
    zh: "自动合并低使用率颜色到相近颜色",
    en: "Automatically merge low-usage colors to similar colors",
  },
  merge_threshold_label: {
    zh: "使用率阈值 Usage Threshold (%)",
    en: "Usage Threshold (%)",
  },
  merge_threshold_info: {
    zh: "低于此百分比的颜色将被合并",
    en: "Colors below this percentage will be merged",
  },
  merge_max_distance_label: {
    zh: "最大颜色距离 Max Color Distance (Delta-E)",
    en: "Max Color Distance (Delta-E)",
  },
  merge_max_distance_info: {
    zh: "只合并距离小于此值的颜色",
    en: "Only merge colors with distance below this value",
  },
  merge_revert_btn: {
    zh: "↩️ 恢复原始 Revert",
    en: "↩️ Revert",
  },
  merge_status_reverted: {
    zh: "↩️ 已恢复到原始颜色",
    en: "↩️ Reverted to original colors",
  },
  // ==================== LUT Grid ====================
  lut_grid_load_hint: {
    zh: "加载 LUT 后显示可用颜色",
    en: "Load LUT to see available colors",
  },
  lut_grid_count: {
    zh: "共 {count} 种可用颜色",
    en: "{count} available colors",
  },
  lut_grid_search_placeholder: {
    zh: "搜索色号 (如 ff0000)",
    en: "Search hex (e.g. ff0000)",
  },
  lut_grid_search_clear: {
    zh: "清除",
    en: "Clear",
  },
  lut_grid_used: {
    zh: "图中已使用 ({count})",
    en: "Used in image ({count})",
  },
  lut_grid_other: {
    zh: "其他可用颜色 ({count})",
    en: "Other colors ({count})",
  },
  lut_grid_tooltip: {
    zh: "点击选择: {hex}",
    en: "Click to select: {hex}",
  },
  lut_grid_picker_hint: {
    zh: "选一个颜色，自动匹配 LUT 中最接近的物理色",
    en: "Pick a color to find the closest match in LUT",
  },
  lut_grid_picker_btn: {
    zh: "匹配最近色",
    en: "Find Nearest",
  },
  lut_grid_hue_all: {
    zh: "全部",
    en: "All",
  },
  lut_grid_hue_red: {
    zh: "红色系",
    en: "Red",
  },
  lut_grid_hue_orange: {
    zh: "橙色系",
    en: "Orange",
  },
  lut_grid_hue_yellow: {
    zh: "黄色系",
    en: "Yellow",
  },
  lut_grid_hue_green: {
    zh: "绿色系",
    en: "Green",
  },
  lut_grid_hue_cyan: {
    zh: "青色系",
    en: "Cyan",
  },
  lut_grid_hue_blue: {
    zh: "蓝色系",
    en: "Blue",
  },
  lut_grid_hue_purple: {
    zh: "紫色系",
    en: "Purple",
  },
  lut_grid_hue_neutral: {
    zh: "中性色",
    en: "Neutral",
  },
  lut_grid_hue_fav: {
    zh: "收藏",
    en: "Favorites",
  },
  lut_grid_search_hex_placeholder: {
    zh: "输入 Hex 或 RGB 搜索定位 (如 #FF0000 或 255,0,0)",
    en: "Search by Hex or RGB (e.g. #FF0000 or 255,0,0)",
  },

  // ==================== Settings ====================
  // ==================== LUT Merge Tab ====================
  merge_desc: {
    zh: "将不同色彩模式的LUT色卡合并为一个，获得更丰富的色彩。",
    en: "Merge LUT cards from different color modes into one for richer colors.",
  },
  merge_lut_1_label: {
    zh: "选择LUT 1（主色卡）",
    en: "Select LUT 1 (Primary)",
  },
  merge_lut_2_label: {
    zh: "选择LUT 2（合并色卡）",
    en: "Select LUT 2 (Secondary)",
  },
  merge_secondary_modes: {
    zh: "已选副色卡",
    en: "Selected Secondary LUTs",
  },
  merge_secondary_none: {
    zh: "未选择副色卡",
    en: "No secondary LUTs selected",
  },
  merge_mode_label: {
    zh: "检测到的模式",
    en: "Detected Mode",
  },
  merge_mode_unknown: {
    zh: "未选择",
    en: "Not selected",
  },
  merge_dedup_label: {
    zh: "Delta-E 去重阈值",
    en: "Delta-E Dedup Threshold",
  },
  merge_dedup_info: {
    zh: "值越大去除的相近色越多，0=仅精确去重",
    en: "Higher = remove more similar colors, 0 = exact dedup only",
  },
  merge_status_running: {
    zh: "⏳ 合并中...",
    en: "⏳ Merging...",
  },
  // ==================== About Page Content ====================
  about_content: {
    zh: [
      "## 🌟 Lumina Studio v1.6.3",
      "",
      "**多材料3D打印色彩系统**",
      "",
      "让FDM打印也能拥有精准的色彩还原",
      "",
      "---",
      "",
      "### 📖 使用流程",
      "",
      "1. **生成校准板** → 打印1024色校准网格",
      "2. **提取颜色** → 拍照并提取打印机实际色彩",
      "3. **转换图像** → 将图片转为多层3D模型",
      "",
      "---",
      "",
      "### 🎨 色彩模式定位点顺序",
      "",
      "| 模式 | 左上 | 右上 | 右下 | 左下 |",
      "|------|------|------|------|------|",
      "| **RYBW** | ⬜ 白色 | 🟥 红色 | 🟦 蓝色 | 🟨 黄色 |",
      "| **CMYW** | ⬜ 白色 | 🔵 青色 | 🟣 品红 | 🟨 黄色 |",
      "",
      "---",
      "",
      "### 🔬 技术原理",
      "",
      "- **Beer-Lambert 光学混色**",
      "- **KD-Tree 色彩匹配**",
      "- **RLE 几何生成**",
      "- **K-Means 色彩量化**",
    ].join("\n"),
    en: [
      "## 🌟 Lumina Studio v1.6.3",
      "",
      "**Multi-Material 3D Print Color System**",
      "",
      "Accurate color reproduction for FDM printing",
      "",
      "---",
      "",
      "### 📖 Workflow",
      "",
      "1. **Generate Calibration** → Print 1024-color grid",
      "2. **Extract Colors** → Photo → extract real colors",
      "3. **Convert Image** → Image → multi-layer 3D model",
      "",
      "---",
      "",
      "### 🎨 Color Mode Corner Order",
      "",
      "| Mode | Top-Left | Top-Right | Bottom-Right | Bottom-Left |",
      "|------|----------|-----------|--------------|-------------|",
      "| **RYBW** | ⬜ White | 🟥 Red | 🟦 Blue | 🟨 Yellow |",
      "| **CMYW** | ⬜ White | 🔵 Cyan | 🟣 Magenta | 🟨 Yellow |",
      "",
      "---",
      "",
      "### 🔬 Technology",
      "",
      "- **Beer-Lambert Optical Color Mixing**",
      "- **KD-Tree Color Matching**",
      "- **RLE Geometry Generation**",
      "- **K-Means Color Quantization**",
    ].join("\n"),
  },

  // ==================== Widget Titles ====================
  "widget.converter": {
    zh: "图像转换",
    en: "Converter",
  },
  "widget.calibration": {
    zh: "校准板",
    en: "Calibration",
  },
  "widget.extractor": {
    zh: "颜色提取",
    en: "Extractor",
  },
  "widget.lutManager": {
    zh: "LUT 合并",
    en: "LUT Merge",
  },
  "widget.fiveColor": {
    zh: "配方查询",
    en: "Five-Color",
  },
  "widget.basicSettings": {
    zh: "基础设置",
    en: "Basic Settings",
  },
  "widget.advancedSettings": {
    zh: "高级设置",
    en: "Advanced Settings",
  },
  "widget.reliefSettings": {
    zh: "浮雕设置",
    en: "Relief Settings",
  },
  "widget.palettePanel": {
    zh: "调色板",
    en: "Palette",
  },
  "widget.lutColorGrid": {
    zh: "LUT 颜色网格",
    en: "LUT Color Grid",
  },
  "widget.outlineSettings": {
    zh: "外轮廓设置",
    en: "Outline Settings",
  },
  "widget.cloisonneSettings": {
    zh: "掐丝珐琅设置",
    en: "Cloisonné Settings",
  },
  "widget.coatingSettings": {
    zh: "透明镀层设置",
    en: "Transparent Coating Settings",
  },
  "widget.keychainLoop": {
    zh: "挂件环设置",
    en: "Keychain Loop",
  },
  "widget.fridgeMagnetSettings": {
    zh: "冰箱贴磁铁槽",
    en: "Fridge Magnet Settings",
  },
  "widget.puzzleSettings": {
    zh: "拼图设置",
    en: "Puzzle Settings",
  },
  "widget.actionBar": {
    zh: "操作栏",
    en: "Actions",
  },
  "widget.colorWorkstation": {
    zh: "颜色工作站",
    en: "Color Workstation",
  },
  "widget.colorWorkstationHint": {
    zh: "点击打开颜色工作站",
    en: "Click to open Color Workstation",
  },

  // ==================== 2D Color Overlay ====================
  fridge_magnet_enable: {
    zh: "启用冰箱贴磁铁槽",
    en: "Enable Fridge Magnet Mode",
  },
  fridge_magnet_mode_hint: {
    zh: "冰箱贴模式会强制切换为单面结构，并禁用拼图、大画幅和挂件环。",
    en: "Fridge magnet mode forces single-sided structure and disables puzzle, large-format, and keychain loop modes.",
  },
  fridge_magnet_summary_structure: {
    zh: "当前结构",
    en: "Structure",
  },
  fridge_magnet_summary_spacer: {
    zh: "当前底板厚度",
    en: "Spacer Thickness",
  },
  fridge_magnet_add: {
    zh: "添加磁铁",
    en: "Add Magnet",
  },
  fridge_magnet_reset_layout: {
    zh: "自动布局",
    en: "Auto Layout",
  },
  fridge_magnet_remove_selected: {
    zh: "删除当前磁铁",
    en: "Remove Selected",
  },
  fridge_magnet_list_title: {
    zh: "磁铁列表",
    en: "Magnet List",
  },
  fridge_magnet_item_label: {
    zh: "磁铁 {index}",
    en: "Magnet {index}",
  },
  fridge_magnet_empty_state: {
    zh: "当前没有磁铁槽，请先添加一个磁铁。",
    en: "No magnet cavities are configured yet. Add a magnet first.",
  },
  fridge_magnet_select_hint: {
    zh: "从上方列表选择一个磁铁以编辑尺寸和位置。",
    en: "Select a magnet above to edit its size and position.",
  },
  fridge_magnet_clear_selection: {
    zh: "清除选中",
    en: "Clear Selection",
  },
  fridge_magnet_shape: {
    zh: "形状",
    en: "Shape",
  },
  fridge_magnet_shape_round: {
    zh: "圆形",
    en: "Round",
  },
  fridge_magnet_shape_rect: {
    zh: "矩形",
    en: "Rectangular",
  },
  fridge_magnet_preset: {
    zh: "官方预设",
    en: "Official Preset",
  },
  fridge_magnet_preset_custom: {
    zh: "自定义",
    en: "Custom",
  },
  fridge_magnet_preset_round_d6x2: {
    zh: "圆形 D6×2 mm",
    en: "Round D6×2 mm",
  },
  fridge_magnet_preset_round_d12x3: {
    zh: "圆形 D12×3 mm",
    en: "Round D12×3 mm",
  },
  fridge_magnet_preset_round_d8x3: {
    zh: "圆形 D8×3 mm",
    en: "Round D8×3 mm",
  },
  fridge_magnet_preset_round_d10x3: {
    zh: "圆形 D10×3 mm",
    en: "Round D10×3 mm",
  },
  fridge_magnet_preset_rect_10x5x1: {
    zh: "矩形 10×5×1 mm",
    en: "Rect 10×5×1 mm",
  },
  fridge_magnet_preset_rect_15x5x2: {
    zh: "矩形 15×5×2 mm",
    en: "Rect 15×5×2 mm",
  },
  fridge_magnet_preset_rect_20x10x2: {
    zh: "矩形 20×10×2 mm",
    en: "Rect 20×10×2 mm",
  },
  fridge_magnet_diameter: {
    zh: "直径",
    en: "Diameter",
  },
  fridge_magnet_width: {
    zh: "宽度",
    en: "Width",
  },
  fridge_magnet_height: {
    zh: "高度",
    en: "Height",
  },
  fridge_magnet_thickness: {
    zh: "厚度",
    en: "Thickness",
  },
  fridge_magnet_center_x: {
    zh: "中心 X",
    en: "Center X",
  },
  fridge_magnet_center_y: {
    zh: "中心 Y",
    en: "Center Y",
  },
  color_2d_overlay_title: {
    zh: "颜色工作站",
    en: "Color Workstation",
  },
  color_2d_overlay_close: {
    zh: "关闭",
    en: "Close",
  },
  color_2d_overlay_close_shortcut: {
    zh: "ESC",
    en: "ESC",
  },
  color_2d_tab_preview: {
    zh: "2D 预览",
    en: "2D Preview",
  },
  color_2d_tab_palette: {
    zh: "调色板",
    en: "Palette",
  },
  color_2d_tab_lut_grid: {
    zh: "LUT 颜色",
    en: "LUT Colors",
  },
  color_2d_no_preview: {
    zh: "暂无预览图，请先完成预览",
    en: "No preview available. Please generate a preview first.",
  },
  color_2d_generating_preview: {
    zh: "正在生成预览…",
    en: "Generating preview…",
  },
  preview_debug_main_2d: {
    zh: "2D 预览",
    en: "2D Preview",
  },
  color_2d_hold_view_original: {
    zh: "按住按钮或按住 Shift 键查看原图",
    en: "Hold this button or hold Shift to view the original image",
  },
  preview_debug_action_2d: {
    zh: "操作栏 2D 小预览",
    en: "ActionBar Mini Preview",
  },
  puzzle_enable: {
    zh: "启用拼图模式",
    en: "Enable Puzzle Mode",
  },
  puzzle_batch_disabled_hint: {
    zh: "批量模式下暂不支持拼图模式。",
    en: "Puzzle mode is unavailable while batch mode is active.",
  },
  puzzle_style: {
    zh: "拼图风格",
    en: "Puzzle Style",
  },
  puzzle_style_regular: {
    zh: "规则拼图",
    en: "Regular Puzzle",
  },
  puzzle_style_irregular: {
    zh: "不规则拼图",
    en: "Irregular Puzzle",
  },
  puzzle_sizing_mode: {
    zh: "尺寸控制方式",
    en: "Sizing Mode",
  },
  puzzle_sizing_piece_size: {
    zh: "按块尺寸",
    en: "By Piece Size",
  },
  puzzle_sizing_grid: {
    zh: "按行列",
    en: "By Grid",
  },
  puzzle_sizing_piece_count: {
    zh: "按总片数",
    en: "By Piece Count",
  },
  puzzle_piece_width: {
    zh: "平均块宽",
    en: "Average Piece Width",
  },
  puzzle_piece_height: {
    zh: "平均块高",
    en: "Average Piece Height",
  },
  puzzle_rows: {
    zh: "行数",
    en: "Rows",
  },
  puzzle_cols: {
    zh: "列数",
    en: "Columns",
  },
  puzzle_target_piece_count: {
    zh: "目标片数",
    en: "Target Piece Count",
  },
  puzzle_connector_style: {
    zh: "连接器风格",
    en: "Connector Style",
  },
  puzzle_connector_classic: {
    zh: "经典风格",
    en: "Classic",
  },
  puzzle_connector_easy_cut: {
    zh: "易切割风格",
    en: "Easy Cut",
  },
  puzzle_seed: {
    zh: "随机种子",
    en: "Seed",
  },
  puzzle_randomize_seed: {
    zh: "重新随机",
    en: "Randomize",
  },
  puzzle_labels: {
    zh: "显示编号",
    en: "Show Piece Labels",
  },
  puzzle_engrave_back_labels: {
    zh: "背面刻号",
    en: "Engrave Back Labels",
  },
  puzzle_back_engrave_unavailable_hint: {
    zh: "背面刻号尚未写入导出几何，当前版本暂不可用。",
    en: "Back-label engraving is not embedded into exported geometry yet, so it is disabled for now.",
  },
  puzzle_irregularity_strength: {
    zh: "不规则强度",
    en: "Irregularity Strength",
  },
  puzzle_min_neck_width: {
    zh: "最小脖颈宽度",
    en: "Minimum Neck Width",
  },
  puzzle_summary_grid: {
    zh: "解析网格",
    en: "Resolved Grid",
  },
  puzzle_summary_requested_grid: {
    zh: "目标网格",
    en: "Requested Grid",
  },
  puzzle_summary_requested_piece_count: {
    zh: "目标片数",
    en: "Requested Piece Count",
  },
  puzzle_summary_piece_count: {
    zh: "最终片数",
    en: "Resolved Piece Count",
  },
  puzzle_summary_piece_size: {
    zh: "平均块尺寸",
    en: "Derived Piece Size",
  },
  puzzle_warnings: {
    zh: "几何警告",
    en: "Geometry Warnings",
  },
  puzzle_large_format_disabled_hint: {
    zh: "拼图模式开启时，大画幅模式会被禁用。",
    en: "Large Format is disabled while puzzle mode is enabled.",
  },
  puzzle_loop_disabled_hint: {
    zh: "拼图模式开启时，挂件环会被禁用。",
    en: "Keychain Loop is disabled while puzzle mode is enabled.",
  },

  // ==================== TAB Navigation Titles ====================
  "tab.converter": {
    zh: "图像转换",
    en: "Converter",
  },
  "tab.lutManagement": {
    zh: "LUT管理",
    en: "LUT Management",
  },
  "tab.materialManagement": {
    zh: "耗材管理",
    en: "Material Management",
  },
  "tab.calibration": {
    zh: "生成校准板",
    en: "Calibration Board",
  },
  "tab.extractor": {
    zh: "LUT提取",
    en: "LUT Extractor",
  },
  "tab.gradientCardGenerate": {
    zh: "梯度卡生成",
    en: "Gradient Generator",
  },
  "tab.gradientCardExtract": {
    zh: "梯度卡提取",
    en: "Gradient Extractor",
  },
  "tab.materialLibrary": {
    zh: "耗材库",
    en: "Material Library",
  },
  "tab.materialCloudSync": {
    zh: "云端耗材库",
    en: "Cloud Material Library",
  },
  "tab.materialRecipe": {
    zh: "配方查询",
    en: "Recipe Query",
  },
  "tab.lutManager": {
    zh: "LUT 合并",
    en: "LUT Merge",
  },
  "tab.lutLibrary": {
    zh: "LUT库",
    en: "LUT Library",
  },
  "tab.lutCloudSync": {
    zh: "云端 LUT 库",
    en: "Cloud LUT Library",
  },
  "tab.lutDetails": {
    zh: "LUT 详情",
    en: "LUT Details",
  },
  "tab.lutCompare": {
    zh: "LUT 对比",
    en: "LUT Compare",
  },
  "tab.fiveColor": {
    zh: "配方查询",
    en: "Five-Color",
  },
  "tab.vectorizer": {
    zh: "图像转矢量",
    en: "Vectorizer",
  },
  "tab.settings": {
    zh: "设置",
    en: "Settings",
  },
  "tab.colorEditor": {
    zh: "颜色编辑",
    en: "Color Editor",
  },
  "tab.converterCore": {
    zh: "核心设置",
    en: "Core Settings",
  },
  "tab.converterColor": {
    zh: "颜色调整",
    en: "Color Adjustment",
  },
  "tab.converterAdvanced": {
    zh: "高级功能",
    en: "Advanced",
  },

  // ==================== Settings Panel (Particle Loading) ====================
  "settings.title": {
    zh: "系统设置",
    en: "System Settings",
  },
  "settings.desc": {
    zh: "管理缓存与运行时偏好设置，保持工作区轻量且稳定。",
    en: "Manage cache and runtime preferences to keep the workspace light and stable.",
  },
  "settings.maintenance": {
    zh: "维护",
    en: "Maintenance",
  },
  "settings.fancy_loading": {
    zh: "粒子特效加载动画",
    en: "Particle Effect Loading",
  },
  "settings.fancy_loading_desc": {
    zh: "启用七彩粒子聚合加载特效，关闭后使用轻量级扫描线动画",
    en: "Enable rainbow particle convergence effect, disable for lightweight scan line animation",
  },
  "settings.witty_loading": {
    zh: "加载趣味消息",
    en: "Loading Witty Messages",
  },
  "settings.witty_loading_desc": {
    zh: "在加载时显示趣味提示消息",
    en: "Show witty messages during loading",
  },
  "settings.cache": {
    zh: "缓存管理",
    en: "Cache Management",
  },
  "settings.clear_cache": {
    zh: "清除缓存",
    en: "Clear Cache",
  },
  "settings.clear_cache_desc": {
    zh: "清除后端临时文件和缓存数据",
    en: "Clear backend temporary files and cached data",
  },
  "settings.cache_summary": {
    zh: "快速回收后端临时文件，适合在长时间使用后整理空间。",
    en: "Reclaim backend temporary files after longer sessions to tidy up storage.",
  },
  "settings.cache_cleared": {
    zh: "缓存已清除",
    en: "Cache cleared",
  },
  "settings.cache_cleared_detail": {
    zh: "已清除 {count} 个临时文件，释放 {size}",
    en: "Cleared {count} temporary files, freed {size}",
  },
  "settings.cache_clear_failed": {
    zh: "清除缓存失败，请稍后重试",
    en: "Failed to clear cache. Please try again.",
  },

  // ==================== Settings Panel (Solver Cache Density) ====================
  "settings.advanced": {
    zh: "高级",
    en: "Advanced",
  },
  "settings.solver_cache_density_heading": {
    zh: "穷举数量",
    en: "Exhaustive density",
  },
  "settings.solver_cache_density_description": {
    zh: "控制穷举缓存使用的 Lab 网格精度。默认走低档；开启后可选择更高档以保留更多可达配方、获得更低的色差。极高档把同一份耗材组合下所有物理可达的配方都各自保留，几乎不再因桶碰撞被丢弃。",
    en: "Controls the Lab grid resolution used by the exhaustive cache. Defaults to low; opt in to higher tiers to keep more reachable recipes and get tighter color accuracy. The ultra tiers retain every physically reachable recipe in a given material × layer setup, virtually eliminating bucket-collision losses.",
  },
  "settings.solver_cache_density_enable_label": {
    zh: "允许自定义穷举数量",
    en: "Customise exhaustive density",
  },
  "settings.solver_cache_density_default_hint": {
    zh: "未开启时统一使用低档（64³），构建快、内存占用低。",
    en: "When disabled, every build uses the low tier (64³) — fast to build, low memory.",
  },
  "settings.solver_cache_density_select_label": {
    zh: "穷举数量",
    en: "Exhaustive density",
  },
  "settings.solver_cache_density_option_64": {
    zh: "低（64³）",
    en: "Low (64³)",
  },
  "settings.solver_cache_density_option_128": {
    zh: "中（128³）",
    en: "Medium (128³)",
  },
  "settings.solver_cache_density_option_256": {
    zh: "高（256³）",
    en: "High (256³)",
  },
  "settings.solver_cache_density_option_512": {
    zh: "极高（512³）",
    en: "Very high (512³)",
  },
  "settings.solver_cache_density_option_1024": {
    zh: "极致（1024³）",
    en: "Ultra (1024³)",
  },
  "settings.solver_cache_density_option_2048": {
    zh: "极致+（2048³，覆盖全部可达配方）",
    en: "Ultra+ (2048³, captures every reachable recipe)",
  },
  "settings.solver_cache_density_tip": {
    zh: "构建采用稀疏存储，内存只随实际可达配方数增长（与档位无关），极致档也不会爆内存；查找时间会随档位略有增加，但通常仍是毫秒级。改动后旧缓存不会被覆盖，首次点击「构建」时会产生对应分辨率的新缓存文件。",
    en: "Builds use sparse storage, so memory grows with the number of physically reachable recipes (not with the tier) — even the ultra tiers stay lightweight. Per-lookup time grows mildly with tier but typically stays in the millisecond range. Existing caches are not overwritten — the first build at a new resolution produces a separate cache file.",
  },
  "settings.svg_pixels_per_mm_heading": {
    zh: "高保真 SVG 采样密度",
    en: "High-Fidelity SVG sampling density",
  },
  "settings.svg_pixels_per_mm_description": {
    zh: "控制 SVG 图片在高保真模式下先转成像素图时的清晰度。直接使用矢量模式处理 SVG 时不会使用这个设置。",
    en: "Controls how sharply SVG images are rasterized before High-Fidelity processing. Native Vector mode does not use this setting.",
  },
  "settings.svg_pixels_per_mm_label": {
    zh: "高保真 SVG 采样密度",
    en: "High-Fidelity SVG sampling density",
  },
  "settings.svg_pixels_per_mm_tip": {
    zh: "仅在“高保真”模式处理 SVG 图片时生效；数值越大边缘越细，处理时间和内存占用也会增加。允许范围 2.0–50.0，步进 0.1。",
    en: "Only affects SVG images processed in High-Fidelity mode. Higher values preserve finer edges but increase processing time and memory use. Allowed range: 2.0–50.0 in 0.1 steps.",
  },
  "settings.svg_pixels_per_mm_reset": {
    zh: "恢复默认",
    en: "Reset default",
  },
  "settings.svg_pixels_per_mm_default_hint": {
    zh: "默认值是 10.0 像素/毫米。这个设置不会改变直接矢量模式的 SVG 结果。",
    en: "Default is 10.0 px/mm. This setting does not change SVG output in native Vector mode.",
  },
  "settings.auto_replace_gradient_heading": {
    zh: "渐变自动换色",
    en: "Auto replace gradient banding",
  },
  "settings.auto_replace_gradient_description": {
    zh: "开启后，每次预览成功会自动把每一条海带纹渐变内的多个耗材色统一替换为组内代表色（组内像素最多的那一个），一键去掉渐变被量化切割出来的条纹。仍可在颜色工作站手动撤销或进一步调整。",
    en: "When enabled, every successful preview automatically collapses each detected banding gradient to the group's representative colour (the material with the most pixels), erasing the stripes in one shot. You can still undo or fine-tune from the Color Workstation.",
  },
  "settings.auto_replace_gradient_label": {
    zh: "自动应用渐变换色",
    en: "Auto-apply gradient replacement",
  },
  "settings.auto_replace_gradient_default_hint": {
    zh: "默认关闭：预览保留原始渐变，由你在颜色工作站里按需替换。",
    en: "Off by default: previews keep the original banded gradient, you apply the fix manually from the Color Workstation.",
  },
  "settings.auto_replace_gradient_tip": {
    zh: "开启后渐变较多的图片在预览后会略慢一步出现最终效果（需要额外的批量替换）。若关闭，同样的功能仍可在颜色工作站里手动使用。",
    en: "With this on, images rich in gradients show the final banding-free result a beat later (extra batch replacement runs). Turning it off keeps the same capability available as a manual action in the Color Workstation.",
  },

  // ==================== Settings Panel (Slicer Settings) ====================
  "settings.slicer_settings": {
    zh: "切片软件设置",
    en: "Slicer Settings",
  },
  "settings.slicer_software": {
    zh: "切片软件",
    en: "Slicer Software",
  },
  "settings.printer_model": {
    zh: "打印机型号",
    en: "Printer Model",
  },
  "settings.printer_options_load_failed": {
    zh: "打印机列表加载失败：{error}",
    en: "Failed to load printer options: {error}",
  },
  "settings.slicer_options_load_failed": {
    zh: "切片器列表加载失败：{error}",
    en: "Failed to load slicer options: {error}",
  },
  "settings.bed_size": {
    zh: "打印床尺寸",
    en: "Bed Size",
  },
  "settings.nozzle_size": {
    zh: "喷嘴尺寸",
    en: "Nozzle Size",
  },
  "settings.device_profile": {
    zh: "设备配置",
    en: "Device Profile",
  },
  "settings.base_layer_height_modifier": {
    zh: "底板层高修改器",
    en: "Base-plate layer-height modifier",
  },
  "settings.base_layer_height_modifier_desc": {
    zh: "在 3MF 里写入 layer_config_ranges，让底板用喷嘴直径一半的粗层高打印（0.4 → 0.2 mm，0.2 → 0.1 mm），显著缩短底板耗时。仅对 Bambu 系切片器生效；双面模型会自动跳过。",
    en: "Writes layer_config_ranges so the base plate prints at half the nozzle diameter (0.4 → 0.2 mm, 0.2 → 0.1 mm), noticeably reducing base-plate time. Bambu-family slicers only; skipped for double-sided prints.",
  },
  "settings.custom_slicer_path": {
    zh: "手动切片软件路径",
    en: "Manual slicer app path",
  },
  "settings.custom_slicer_path_help": {
    zh: "macOS 可粘贴 .app 路径，例如 /Applications/Bambu Studio.app；保存后会优先用于打开 3MF。",
    en: "On macOS, paste a .app path such as /Applications/Bambu Studio.app. Saved paths are preferred when opening 3MF files.",
  },
  "settings.custom_slicer_path_placeholder": {
    zh: "/Applications/Bambu Studio.app",
    en: "/Applications/Bambu Studio.app",
  },
  "settings.custom_slicer_save": {
    zh: "校验并保存",
    en: "Validate & Save",
  },
  "settings.custom_slicer_clear": {
    zh: "清除",
    en: "Clear",
  },
  "settings.nozzle_count": {
    zh: "喷头数量",
    en: "Nozzle Count",
  },
  "settings.dual_head": {
    zh: "双头",
    en: "Dual Head",
  },
  "settings.single_head": {
    zh: "单头",
    en: "Single Head",
  },
  "loading.generating": {
    zh: "模型生成中...",
    en: "Generating model...",
  },

  // ==================== App Header ====================
  app_header_title: {
    zh: "Lumina Studio 2",
    en: "Lumina Studio 2",
  },
  app_checking_backend: {
    zh: "正在检查后端…",
    en: "Checking backend…",
  },
  app_backend_connected: {
    zh: "后端已连接",
    en: "Backend Connected",
  },
  app_backend_unreachable: {
    zh: "后端不可达",
    en: "Backend Unreachable",
  },
  app_reset_layout: {
    zh: "重置布局",
    en: "Reset Layout",
  },
  app_3d_scene_error: {
    zh: "3D 场景加载失败",
    en: "3D scene failed to load",
  },
  app_toggle_language: {
    zh: "切换语言",
    en: "Toggle language",
  },
  app_toggle_theme: {
    zh: "切换主题",
    en: "Toggle theme",
  },
  app_quit_confirm_title: {
    zh: "退出确认",
    en: "Quit Confirmation",
  },
  app_quit_confirm_message: {
    zh: "确定要退出 Lumina Studio 吗？",
    en: "Are you sure you want to quit Lumina Studio?",
  },
  app_quit_quit: {
    zh: "退出",
    en: "Quit",
  },
  app_quit_cancel: {
    zh: "取消",
    en: "Cancel",
  },

  // ==================== LUT Manager Panel ====================
  lut_manager_title: {
    zh: "LUT 合并工具",
    en: "LUT Merge Tool",
  },
  lut_manager_desc: {
    zh: "将多个 LUT 合并为一个，支持 Delta-E 去重。主 LUT 必须为 6-Color 或 8-Color 模式。",
    en: "Merge multiple LUTs into one with Delta-E dedup. Primary LUT must be 6-Color or 8-Color mode.",
  },
  lut_manager_primary_label: {
    zh: "主 LUT",
    en: "Primary LUT",
  },
  lut_manager_primary_placeholder: {
    zh: "选择主 LUT...",
    en: "Select primary LUT...",
  },
  lut_manager_loading: {
    zh: "加载中...",
    en: "Loading...",
  },
  lut_manager_primary_mode_invalid: {
    zh: "主 LUT 必须为 6-Color 或 8-Color 模式",
    en: "Primary LUT must be 6-Color or 8-Color mode",
  },
  lut_manager_secondary_label: {
    zh: "副 LUT",
    en: "Secondary LUTs",
  },
  lut_manager_no_secondary: {
    zh: "无可用的副 LUT",
    en: "No secondary LUTs available",
  },
  lut_manager_select_primary_first: {
    zh: "请先选择主 LUT",
    en: "Please select a primary LUT first",
  },
  lut_manager_dedup_label: {
    zh: "去重阈值",
    en: "Dedup Threshold",
  },
  lut_manager_dedup_hint: {
    zh: "0 = 仅精确去重，值越大去除越多相近色",
    en: "0 = exact dedup only, higher = remove more similar colors",
  },
  lut_manager_merge_btn: {
    zh: "合并并保存",
    en: "Merge & Save",
  },
  lut_manager_merge_success: {
    zh: "✓ 合并成功！",
    en: "✓ Merge successful!",
  },
  lut_manager_merge_before: {
    zh: "合并前",
    en: "Before",
  },
  lut_manager_merge_after: {
    zh: "合并后",
    en: "After",
  },
  lut_manager_exact_dupes: {
    zh: "精确去重",
    en: "Exact dupes",
  },
  lut_manager_similar_removed: {
    zh: "相近色去除",
    en: "Similar removed",
  },
  lut_manager_file: {
    zh: "文件",
    en: "File",
  },
  lut_manager_close_error: {
    zh: "关闭错误",
    en: "Close error",
  },
  lut_manager_mode_summary: {
    zh: "模式 {mode} · 共 {count} 色",
    en: "Mode {mode} · {count} colors",
  },
  lut_manager_selected_count: {
    zh: "已选择 {count} 个副 LUT",
    en: "{count} secondary LUTs selected",
  },

  // ==================== LUT Details Panel ====================
  lut_details_title: {
    zh: "LUT 详情浏览",
    en: "LUT Details Browser",
  },
  lut_details_desc: {
    zh: "查找 LUT，并查看其颜色、材料和分布图。",
    en: "Find LUTs and inspect their colors, materials, and distribution charts.",
  },
  lut_details_query_label: {
    zh: "筛选 LUT",
    en: "Filter LUTs",
  },
  lut_details_query_placeholder: {
    zh: "输入名称、材料或别名",
    en: "Search by name, material, or alias",
  },
  lut_details_manufacturer_label: {
    zh: "制造商",
    en: "Manufacturer",
  },
  lut_details_manufacturer_placeholder: {
    zh: "选择制造商...",
    en: "Select manufacturer...",
  },
  lut_details_lut_label: {
    zh: "LUT 方案",
    en: "LUT",
  },
  lut_details_lut_placeholder: {
    zh: "选择 LUT...",
    en: "Select LUT...",
  },
  lut_details_load_action: {
    zh: "加载 LUT",
    en: "Load LUT",
  },
  lut_details_load_hint: {
    zh: "选择 LUT 后点击加载。",
    en: "Select a LUT, then click load.",
  },
  lut_details_pending_loaded_notice: {
    zh: "当前显示的是已加载 LUT，点击加载后更新。",
    en: "You are viewing the loaded LUT. Click load to update it.",
  },
  lut_details_loading_selected: {
    zh: "正在加载所选 LUT...",
    en: "Loading selected LUT...",
  },
  lut_details_catalog_loading: {
    zh: "正在加载 LUT 目录...",
    en: "Loading LUT catalog...",
  },
  lut_details_close_error: {
    zh: "关闭错误",
    en: "Dismiss error",
  },
  lut_details_no_matches: {
    zh: "没有匹配的 LUT，请调整筛选条件。",
    en: "No LUTs match the current filters.",
  },
  lut_details_summary_title: {
    zh: "摘要",
    en: "Summary",
  },
  lut_details_summary_desc: {
    zh: "当前 LUT 的基本信息。",
    en: "Core information for the current LUT.",
  },
  lut_details_no_detail: {
    zh: "请选择一个 LUT。",
    en: "Select a LUT.",
  },
  lut_details_loading: {
    zh: "加载详情中...",
    en: "Loading details...",
  },
  lut_details_error_load_catalog: {
    zh: "LUT 详情目录加载失败",
    en: "Failed to load LUT details catalog",
  },
  lut_details_error_load_detail: {
    zh: "LUT 详情加载失败",
    en: "Failed to load LUT details",
  },
  lut_error_missing_refresh: {
    zh: "该 LUT 已不存在，请刷新列表后重试。",
    en: "The selected LUT no longer exists. Refresh the list and try again.",
  },
  lut_details_summary_name: {
    zh: "名称",
    en: "Name",
  },
  lut_details_summary_manufacturer: {
    zh: "制造商",
    en: "Manufacturer",
  },
  lut_details_summary_material: {
    zh: "材料",
    en: "Material",
  },
  lut_details_summary_color_mode: {
    zh: "色彩模式",
    en: "Color Mode",
  },
  lut_details_summary_color_count: {
    zh: "颜色数",
    en: "Color Count",
  },
  lut_details_summary_source_kind: {
    zh: "来源类型",
    en: "Source Kind",
  },
  lut_details_summary_fingerprint: {
    zh: "指纹",
    en: "Fingerprint",
  },
  lut_details_summary_path: {
    zh: "公开引用",
    en: "Public reference",
  },
  lut_details_metadata_title: {
    zh: "类型化元数据",
    en: "Typed Metadata",
  },
  lut_details_metadata_desc: {
    zh: "结构化参数与打印设置。",
    en: "Structured parameters and print settings.",
  },
  lut_details_metadata_schema: {
    zh: "Schema",
    en: "Schema",
  },
  lut_details_metadata_manufacturer_source: {
    zh: "制造商来源",
    en: "Manufacturer Source",
  },
  lut_details_metadata_material_source: {
    zh: "材料来源",
    en: "Material Source",
  },
  lut_details_metadata_max_color_layers: {
    zh: "最大颜色层数",
    en: "Max Color Layers",
  },
  lut_details_metadata_layer_height: {
    zh: "层高",
    en: "Layer Height",
  },
  lut_details_metadata_line_width: {
    zh: "线宽",
    en: "Line Width",
  },
  lut_details_metadata_base_layers: {
    zh: "底层数",
    en: "Base Layers",
  },
  lut_details_metadata_base_channel: {
    zh: "基础通道",
    en: "Base Channel",
  },
  lut_details_metadata_layer_order: {
    zh: "层顺序",
    en: "Layer Order",
  },
  lut_details_metadata_coverage: {
    zh: "覆盖统计",
    en: "Coverage",
  },
  lut_details_coverage_summary: {
    zh: "{entries} 条记录 / {points} 个点",
    en: "{entries} entries / {points} plotted points",
  },
  lut_details_capabilities_title: {
    zh: "能力",
    en: "Capabilities",
  },
  lut_details_capabilities_desc: {
    zh: "该 LUT 声明的能力。",
    en: "Capabilities declared by this LUT.",
  },
  lut_details_capabilities_empty: {
    zh: "无能力信息",
    en: "No capabilities",
  },
  lut_details_supported_modes_title: {
    zh: "支持模式",
    en: "Supported Modes",
  },
  lut_details_supported_modes_desc: {
    zh: "可用的层数与层高组合。",
    en: "Available layer-count and layer-height combinations.",
  },
  lut_details_supported_modes_empty: {
    zh: "无支持模式",
    en: "No supported modes",
  },
  lut_details_supported_mode_item: {
    zh: "{layers} 层 · {height} mm",
    en: "{layers} layers · {height} mm",
  },
  lut_details_raw_metadata_title: {
    zh: "LUT 原始元数据",
    en: "Raw LUT Metadata",
  },
  lut_details_raw_metadata_desc: {
    zh: "",
    en: "",
  },
  lut_details_no_raw_metadata: {
    zh: "{}",
    en: "{}",
  },
  lut_details_palette_title: {
    zh: "调色板",
    en: "Palette",
  },
  lut_details_palette_desc: {
    zh: "颜色、材料与色值对应关系。",
    en: "Color, material, and color-value mappings.",
  },
  lut_details_palette_count: {
    zh: "{count} 项",
    en: "{count} entries",
  },
  lut_details_palette_color: {
    zh: "颜色",
    en: "Color",
  },
  lut_details_palette_material: {
    zh: "材料",
    en: "Material",
  },
  lut_details_palette_hex: {
    zh: "HEX",
    en: "Hex",
  },
  lut_details_palette_unknown: {
    zh: "未知",
    en: "Unknown",
  },
  lut_details_no_palette: {
    zh: "没有调色板数据。",
    en: "No palette data.",
  },
  lut_details_lab_chart_title: {
    zh: "Lab 图",
    en: "Lab Chart",
  },
  lut_details_lab_chart_desc: {
    zh: "显示颜色在 Lab a*/b* 平面上的分布。X 轴为 a*，负方向偏绿、正方向偏红；Y 轴为 b*，负方向偏蓝、正方向偏黄。亮度维度 L* 在该图中不显示。",
    en: "Shows the color distribution on the Lab a*/b* plane. The X axis is a*, with negative values toward green and positive values toward red; the Y axis is b*, with negative values toward blue and positive values toward yellow. The L* lightness dimension is not shown in this chart.",
  },
  lut_details_lab_chart_3d_desc: {
    zh: "显示颜色在 Lab 三维空间中的分布。X 轴为 a*，负方向偏绿、正方向偏红；Y 轴为 L*，负方向更暗、正方向更亮；Z 轴为 b*，负方向偏蓝、正方向偏黄。",
    en: "Shows the color distribution in the Lab 3D space. The X axis is a*, with negative values toward green and positive values toward red; the Y axis is L*, with negative values darker and positive values lighter; the Z axis is b*, with negative values toward blue and positive values toward yellow.",
  },
  lut_details_lab_view_2d: {
    zh: "2D",
    en: "2D",
  },
  lut_details_lab_view_3d: {
    zh: "3D",
    en: "3D",
  },
  lut_details_lab_chart_x: {
    zh: "a* 轴",
    en: "a* axis",
  },
  lut_details_lab_chart_y: {
    zh: "b* 轴",
    en: "b* axis",
  },
  lut_details_lab_chart_footer: {
    zh: "L 范围: {lRange} | a 范围: {aRange} | b 范围: {bRange}",
    en: "L range: {lRange} | a range: {aRange} | b range: {bRange}",
  },
  lut_details_lab_3d_axis_x: {
    zh: "X = a*（-绿 / +红）",
    en: "X = a* (-green / +red)",
  },
  lut_details_lab_3d_axis_y: {
    zh: "Y = L*（暗 → 亮）",
    en: "Y = L* (dark -> light)",
  },
  lut_details_lab_3d_axis_z: {
    zh: "Z = b*（-蓝 / +黄）",
    en: "Z = b* (-blue / +yellow)",
  },
  lut_details_lab_3d_loading_hull: {
    zh: "正在生成 3D 外壳...",
    en: "Generating the 3D hull...",
  },
  lut_details_lab_3d_error_hull: {
    zh: "3D 外壳生成失败，已仅显示点云。",
    en: "The 3D hull failed to generate. Only the point cloud is shown.",
  },
  lut_details_lab_3d_reference_toggle: {
    zh: "参考切片",
    en: "Reference Slice",
  },
  lut_details_lab_3d_reference_status: {
    zh: "参考切片 · L* {lightness}",
    en: "Reference Slice · L* {lightness}",
  },
  lut_details_lab_3d_reference_slider: {
    zh: "参考切片 L*",
    en: "Reference Slice L*",
  },
  lut_details_rgb_chart_title: {
    zh: "RGB 投影视图",
    en: "RGB Projection Chart",
  },
  lut_details_rgb_chart_desc: {
    zh: "显示颜色在 RGB 空间中的整体分布趋势。由于采用二维等距投影表示，沿 R=G=B 的中性轴，也就是黑到白的第三维度，在该图中不直接显示，因此不适合用于精确读取单独通道值。",
    en: "Shows the overall distribution trend in RGB space. Because this chart uses a 2D isometric projection, the third dimension along the neutral R=G=B axis, from black to white, is not shown directly, so the chart is not suitable for precise single-channel readings.",
  },
  lut_details_rgb_chart_x: {
    zh: "投影 X",
    en: "Projection X",
  },
  lut_details_rgb_chart_y: {
    zh: "投影 Y",
    en: "Projection Y",
  },
  lut_details_rgb_chart_footer: {
    zh: "原始通道范围 R: {rRange} | G: {gRange} | B: {bRange}",
    en: "Raw channel ranges R: {rRange} | G: {gRange} | B: {bRange}",
  },
  lut_details_hue_lightness_chart_title: {
    zh: "色相 × 相对亮度",
    en: "Hue × Relative Lightness",
  },
  lut_details_hue_lightness_chart_desc: {
    zh: "显示各色相上的相对亮度分布，用于观察不同色相对应的亮度覆盖情况。饱和度维度在该图中不显示。",
    en: "Shows the relative lightness distribution across hues, so you can inspect the lightness coverage for each hue. The saturation dimension is not shown in this chart.",
  },
  lut_details_hue_lightness_chart_x: {
    zh: "色相 (°)",
    en: "Hue (°)",
  },
  lut_details_hue_lightness_chart_y: {
    zh: "相对亮度 (%)",
    en: "Relative Lightness (%)",
  },
  lut_details_hue_lightness_chart_footer: {
    zh: "相对亮度范围: {lRange} | 色相范围: {hRange}",
    en: "Relative lightness range: {lRange} | Hue range: {hRange}",
  },
  lut_details_hue_chroma_chart_title: {
    zh: "色相 × 饱和度",
    en: "Hue × Saturation",
  },
  lut_details_hue_chroma_chart_desc: {
    zh: "显示各色相上的相对饱和度分布，用于观察不同色相对应的饱和度覆盖情况。亮度维度在该图中不显示。",
    en: "Shows the relative saturation distribution across hues, so you can inspect the saturation coverage for each hue. The lightness dimension is not shown in this chart.",
  },
  lut_details_hue_chroma_chart_x: {
    zh: "色相 (°)",
    en: "Hue (°)",
  },
  lut_details_hue_chroma_chart_y: {
    zh: "相对饱和度 (%)",
    en: "Relative Saturation (%)",
  },
  lut_details_hue_chroma_chart_footer: {
    zh: "相对饱和度范围: {cRange} | 色相范围: {hRange}",
    en: "Relative saturation range: {cRange} | Hue range: {hRange}",
  },
  lut_details_hue_chart_omitted_neutral: {
    zh: "低饱和、色相未定义的点未显示：{count}",
    en: "Low-saturation points with undefined hue are not shown: {count}",
  },
  lut_details_no_chart_points: {
    zh: "暂无点位数据",
    en: "No point data available",
  },

  lut_compare_title: {
    zh: "LUT 对比工具",
    en: "LUT Compare Tool",
  },
  lut_compare_desc: {
    zh: "按同配方比较两个 LUT 的颜色偏移，适用于耗材、批次和重复校准的一致性分析。",
    en: "Compare two LUTs by shared recipe to measure material, batch, and calibration drift.",
  },
  lut_compare_lut_a_label: {
    zh: "基准 LUT",
    en: "Baseline LUT",
  },
  lut_compare_lut_b_label: {
    zh: "对比 LUT",
    en: "Comparison LUT",
  },
  lut_compare_lut_a_placeholder: {
    zh: "选择基准 LUT...",
    en: "Select baseline LUT...",
  },
  lut_compare_lut_b_placeholder: {
    zh: "选择对比 LUT...",
    en: "Select comparison LUT...",
  },
  lut_compare_compare_btn: {
    zh: "开始对比",
    en: "Compare LUTs",
  },
  lut_compare_result_title: {
    zh: "对比结果",
    en: "Comparison Result",
  },
  lut_compare_summary: {
    zh: "已比较 {lutA} 与 {lutB} 的 {count} 个共享配方。",
    en: "Compared {count} shared recipes between {lutA} and {lutB}.",
  },
  lut_compare_matched: {
    zh: "共享配方",
    en: "Shared Recipes",
  },
  lut_compare_coverage_a: {
    zh: "A 覆盖率",
    en: "A Coverage",
  },
  lut_compare_coverage_b: {
    zh: "B 覆盖率",
    en: "B Coverage",
  },
  lut_compare_mean: {
    zh: "平均 ΔE00",
    en: "Mean ΔE00",
  },
  lut_compare_p95: {
    zh: "P95 ΔE00",
    en: "P95 ΔE00",
  },
  lut_compare_max: {
    zh: "最大 ΔE00",
    en: "Max ΔE00",
  },
  lut_compare_identical: {
    zh: "RGB 完全一致",
    en: "Exact RGB Matches",
  },
  lut_compare_warnings_title: {
    zh: "注意事项",
    en: "Warnings",
  },
  lut_compare_warning_mode_mismatch: {
    zh: "LUT 模式不一致：{modeA} vs {modeB}",
    en: "LUT modes differ: {modeA} vs {modeB}",
  },
  lut_compare_warning_layer_count_mismatch: {
    zh: "配方层数不一致：{countA} vs {countB}",
    en: "Recipe layer counts differ: {countA} vs {countB}",
  },
  lut_compare_warning_layer_height_mismatch: {
    zh: "层高不一致：{values}",
    en: "Layer heights differ: {values}",
  },
  lut_compare_warning_line_width_mismatch: {
    zh: "线宽不一致：{values}",
    en: "Line widths differ: {values}",
  },
  lut_compare_warning_no_shared_recipes: {
    zh: "没有共享配方，统计结果已归零。",
    en: "No shared recipes were found, so comparison metrics were zeroed.",
  },
  lut_compare_warning_row_mismatch: {
    zh: "{label} 的 rgb/stacks 行数不一致：rgb={rgb}，stacks={stacks}；已仅使用前 {used} 行。",
    en: "{label} has mismatched rgb/stacks rows: rgb={rgb}, stacks={stacks}; only the first {used} rows were used.",
  },
  lut_compare_warning_duplicate_recipes: {
    zh: "{label} 存在 {count} 条重复配方记录；每个配方仅保留第一条。",
    en: "{label} contains {count} duplicate recipe rows; only the first row for each recipe was kept.",
  },
  lut_compare_warning_generic: {
    zh: "对比过程中返回了额外警告，请结合结果谨慎解读。",
    en: "Additional warnings were returned during comparison; please interpret the result with care.",
  },
  lut_compare_worst_title: {
    zh: "最大差异配方",
    en: "Largest Recipe Diffs",
  },
  lut_compare_worst_desc: {
    zh: "展示共享配方中差异最大的若干条目，帮助快速定位色偏最明显的配方。",
    en: "Shows the shared recipes with the largest differences so the biggest color shifts are easy to spot.",
  },
  lut_compare_delta: {
    zh: "ΔE00",
    en: "ΔE00",
  },
  lut_compare_no_result: {
    zh: "选择两个 LUT 后即可开始对比。",
    en: "Select two LUTs to start comparing.",
  },
  lut_compare_no_diffs: {
    zh: "当前没有可展示的共享配方差异。",
    en: "There are no shared recipe diffs to display.",
  },

  // ==================== About View ====================
  about_title: {
    zh: "Lumina Studio 2",
    en: "Lumina Studio 2",
  },
  about_desc: {
    zh: "更多信息即将推出",
    en: "More info coming soon",
  },
  about_clear_cache_loading: {
    zh: "清理中...",
    en: "Clearing...",
  },
  about_clear_cache: {
    zh: "清除系统缓存",
    en: "Clear System Cache",
  },
  about_close_notification: {
    zh: "关闭通知",
    en: "Close notification",
  },
  about_cache_clear_success: {
    zh: "已清理 {deleted_files} 个缓存文件，释放 {freed}",
    en: "Cleared {deleted_files} cached files, freed {freed}",
  },
  about_cache_clear_failed: {
    zh: "缓存清理失败",
    en: "Cache clear failed",
  },

  // ==================== Calibration Panel ====================
  cal_color_mode_label: {
    zh: "颜色模式",
    en: "Color Mode",
  },
  cal_color_mode_hint: {
    zh: "选择要生成的校准板颜色模式。",
    en: "Select the color mode for the calibration board.",
  },
  cal_block_size_label: {
    zh: "色块尺寸",
    en: "Block Size",
  },
  cal_block_size_hint: {
    zh: "定义单个色块的边长（毫米）。推荐值: 5.00mm。",
    en: "Define the edge length of a single block (in mm). Recommended: 5.00mm.",
  },
  cal_gap_label: {
    zh: "色块间距",
    en: "Block Gap",
  },
  cal_gap_hint: {
    zh: "定义相邻色块之间的间隙（毫米）。推荐值: 0.84mm。",
    en: "Define the gap between adjacent blocks (in mm). Recommended: 0.84mm.",
  },
  cal_backing_thickness_label: {
    zh: "底板厚度",
    en: "Backing Thickness",
  },
  cal_backing_thickness_hint: {
    zh: "调整底板层的物理厚度（毫米）。每一格对应一层打印层（0.08 mm），推荐值: 1.20 mm。",
    en: "Adjust the backing layer thickness in millimeters. Each tick equals one print layer (0.08 mm); recommended: 1.20 mm.",
  },
  cal_generate_btn_panel: {
    zh: "生成校准板",
    en: "Generate Calibration",
  },
  calibration_generation_failed: {
    zh: "校准板生成失败，请稍后重试。",
    en: "Calibration generation failed. Please try again.",
  },
  cal_download_3mf: {
    zh: "下载校准文件",
    en: "Download Calibration File",
  },
  cal_8color_full_export_label: {
    zh: "导出全部 8 色配方",
    en: "Export Full 8-Color Recipes",
  },
  cal_8color_full_export_hint: {
    zh: "生成多页 ZIP，每页包含 3MF 和对应配方 JSON，不影响现有两页提取流程。",
    en: "Generate a multi-page ZIP with a 3MF and matching recipe JSON for each page without changing the existing two-page extraction flow.",
  },
  cal_8color_full_export_on: {
    zh: "全量",
    en: "Full",
  },
  cal_8color_full_export_off: {
    zh: "精简",
    en: "Compact",
  },
  cal_preview_alt: {
    zh: "校准板预览",
    en: "Calibration preview",
  },

  // ==================== Extractor Panel ====================
  ext_color_mode_label: {
    zh: "颜色模式",
    en: "Color Mode",
  },
  ext_color_mode_hint: {
    zh: "选择与您打印的校准板对应的颜色模式。不同的模式会决定提取颜色时使用的色块数量和布局。",
    en: "Select the color mode corresponding to your printed calibration board. This determines the number and layout of color blocks extracted.",
  },
  ext_page_label: {
    zh: "校准板页码",
    en: "Board Page",
  },
  ext_page_hint: {
    zh: "选择当前上传照片对应的校准板页码。部分颜色模式（如 8色 或 5色扩展）由多张校准板组成。",
    en: "Select the page number for the current photo. Some color modes (like 8-Color or 5-Color Extended) span multiple boards.",
  },
  ext_page_number_prefix: {
    zh: "",
    en: "Page ",
  },
  ext_page_number_suffix: {
    zh: "号",
    en: "",
  },
  ext_upload_label: {
    zh: "上传校准板照片",
    en: "Upload Calibration Board Photo",
  },
  ext_offset_x_label: {
    zh: "水平偏移 (offset_x)",
    en: "Horizontal Offset (offset_x)",
  },
  ext_offset_x_hint: {
    zh: "水平方向位移校正。向右偏移为正，向左为负，单位为像素。",
    en: "Horizontal displacement correction. Positive moves right, negative moves left, in pixels.",
  },
  ext_offset_y_label: {
    zh: "垂直偏移 (offset_y)",
    en: "Vertical Offset (offset_y)",
  },
  ext_offset_y_hint: {
    zh: "垂直方向位移校正。向下偏移为正，向上为负，单位为像素。",
    en: "Vertical displacement correction. Positive moves down, negative moves up, in pixels.",
  },
  ext_zoom_label: {
    zh: "缩放 (zoom)",
    en: "Zoom",
  },
  ext_zoom_hint: {
    zh: "对检测到的棋盘格进行缩放校正。1.0 表示原始尺寸，小于 1 则缩小，大于 1 则放大。",
    en: "Scale correction for the detected checkerboard. 1.0 means original size; less than 1 shrinks, greater than 1 enlarges.",
  },
  ext_distortion_label: {
    zh: "畸变校正 (distortion)",
    en: "Distortion Correction",
  },
  ext_distortion_hint: {
    zh: "桶形/枕形畸变校正系数。正值矫正桶形畸变，负值矫正枕形畸变，0 表示不校正。",
    en: "Barrel/pincushion distortion correction coefficient. Positive corrects barrel distortion, negative corrects pincushion, zero disables correction.",
  },
  ext_vignette_label: {
    zh: "暗角校正",
    en: "Vignette Correction",
  },
  ext_vignette_hint: {
    zh: "自动检测并补偿镜头暗角导致的边缘亮度下降，使颜色提取更均匀准确。",
    en: "Automatically detects and compensates for edge brightness falloff caused by lens vignetting for more uniform and accurate color extraction.",
  },
  ext_auto_wb_label: {
    zh: "自动白平衡",
    en: "Auto White Balance",
  },
  ext_auto_wb_hint: {
    zh: "自动校正图像的白平衡，将白色参考块还原为标准白色，使整体色彩更准确。",
    en: "Automatically corrects the image white balance, restoring the white reference patch to standard white for more accurate overall colors.",
  },
  ext_colorchecker_label: {
    zh: "ColorChecker 校色",
    en: "ColorChecker Calibration",
  },
  ext_colorchecker_hint: {
    zh: "启用后将使用图片中的 ColorChecker 色卡计算颜色校正矩阵 (CCM)，先校正图片颜色再进行提取，适用于照片色温偏差较大的场景。",
    en: "When enabled, computes a Color Correction Matrix (CCM) from the ColorChecker card in the image, applying color correction before extraction. Useful when photos have significant color temperature deviation.",
  },
  ext_cc_step1_title: {
    zh: "第 1 步：标记 ColorChecker 色卡",
    en: "Step 1: Mark ColorChecker Card",
  },
  ext_cc_step1_hint: {
    zh: "请在图片上点击 ColorChecker 色卡的 4 个角点",
    en: "Click the 4 corners of the ColorChecker card in the image",
  },
  ext_cc_warp_btn: {
    zh: "生成预览",
    en: "Generate Preview",
  },
  ext_cc_calibrate_btn: {
    zh: "执行校色",
    en: "Calibrate",
  },
  ext_cc_clear_corners_btn: {
    zh: "清除色卡角点",
    en: "Clear Card Corners",
  },
  ext_cc_step_review_title: {
    zh: "检查采样点",
    en: "Review Patch Points",
  },
  ext_cc_step_review_hint: {
    zh: "下方为校色卡透视展开预览，标注了 24 个采样点。如有偏差，先选择编号再在图上点击新的位置来修正；确认无误后点击「执行校色」。",
    en: "Below is the warped ColorChecker preview with 24 sampling points. To adjust, select a patch number then click its correct position on the image. When satisfied, click Calibrate.",
  },
  ext_cc_step2_title: {
    zh: "第 2 步：标记校准板",
    en: "Step 2: Mark Calibration Board",
  },
  ext_cc_step2_hint: {
    zh: "校色完成，请在校正后的图片上点击校准板的 4 个角点，然后提取",
    en: "Calibration done. Click the 4 corners of the calibration board on the corrected image, then extract.",
  },
  ext_cc_dialog_title: {
    zh: "ColorChecker 色卡校色",
    en: "ColorChecker Calibration",
  },
  ext_cc_close_btn: {
    zh: "关闭",
    en: "Close",
  },
  ext_cc_open_dialog_btn: {
    zh: "打开校色工具",
    en: "Open Calibration Tool",
  },
  ext_cc_recalibrate_btn: {
    zh: "重新校色 / 替换",
    en: "Recalibrate / Replace",
  },
  ext_cc_auto_detect_btn: {
    zh: "自动定位色卡",
    en: "Auto Locate Card",
  },
  ext_cc_auto_detect_success: {
    zh: "已自动定位色卡",
    en: "Card auto-located",
  },
  ext_cc_auto_detect_failed: {
    zh: "自动定位失败，请手动点选四角",
    en: "Auto locate failed. Mark the four corners manually.",
  },
  ext_cc_corner_adjust_hint: {
    zh: "按顺序点选四角；点完后可拖动圆点，或先选中角点再在图片上点击新位置。",
    en: "Mark the four corners in order. After that, drag a handle or select a corner and click a new position.",
  },
  ext_cc_corner_label: {
    zh: "色卡角点",
    en: "Card corner",
  },
  ext_cc_patch_orientation_label: {
    zh: "色块方向",
    en: "Patch Order",
  },
  ext_cc_patch_orientation_normal: {
    zh: "正常",
    en: "Normal",
  },
  ext_cc_patch_orientation_rotate_180: {
    zh: "旋转 180°",
    en: "Rotated 180°",
  },
  ext_cc_patch_orientation_flip_horizontal: {
    zh: "水平镜像",
    en: "Mirrored Horizontally",
  },
  ext_cc_patch_orientation_flip_vertical: {
    zh: "垂直镜像",
    en: "Mirrored Vertically",
  },
  ext_cc_missing_image: {
    zh: "请先选择图片",
    en: "Choose an image first",
  },
  ext_cc_status_preparing: {
    zh: "正在生成校色预览",
    en: "Preparing calibration preview",
  },
  ext_cc_upload_progress: {
    zh: "正在上传原图 {percent}%",
    en: "Uploading source image {percent}%",
  },
  ext_cc_upload_progress_label: {
    zh: "原图上传进度",
    en: "Source image upload progress",
  },
  ext_cc_source_prepare_timeout: {
    zh: "校色器原图上传或预览生成超时。图片较大或网络较慢时可能发生，请重试或使用更快网络。",
    en: "Timed out while uploading the source image or preparing its preview. This can happen with large images or slow networks. Please retry or use a faster connection.",
  },
  ext_cc_source_prepare_failed: {
    zh: "原图上传或预览生成失败，请重试。",
    en: "Failed to upload the source image or prepare its preview. Please retry.",
  },
  ext_cc_auto_detect_timeout: {
    zh: "ColorChecker 自动识别超时。请重试，或手动点选四个色卡角点。",
    en: "ColorChecker auto detection timed out. Please retry or mark the four chart corners manually.",
  },
  ext_cc_warp_timeout: {
    zh: "ColorChecker 透视预览生成超时。请重试，或检查角点是否框住完整色卡。",
    en: "ColorChecker warp preview generation timed out. Please retry or check that the corners bound the full chart.",
  },
  ext_cc_calibrate_timeout: {
    zh: "ColorChecker 校色计算超时。请重试；大 RAW/DNG 图片可能需要更长处理时间。",
    en: "ColorChecker calibration timed out. Please retry; large RAW/DNG images can need more processing time.",
  },
  ext_cc_warp_ready: {
    zh: "透视预览已生成，可执行校色",
    en: "Warp preview is ready. You can calibrate now.",
  },
  ext_cc_warp_failed: {
    zh: "透视预览生成失败",
    en: "Failed to generate warp preview",
  },
  ext_cc_calibrate_failed: {
    zh: "校色失败",
    en: "Calibration failed",
  },
  ext_cc_result_ready: {
    zh: "校色完成，请检查结果后确认使用。",
    en: "Calibration is complete. Review the result before accepting it.",
  },
  ext_cc_confirm_preview_failed: {
    zh: "校色预览加载失败，请重试或重新执行校色。",
    en: "Failed to load the calibrated preview. Try again or recalibrate.",
  },
  ext_cc_metric_mean: {
    zh: "平均",
    en: "Mean",
  },
  ext_cc_metric_median: {
    zh: "中位",
    en: "Median",
  },
  ext_cc_metric_p95: {
    zh: "P95",
    en: "P95",
  },
  ext_cc_metric_worst: {
    zh: "最差",
    en: "Worst",
  },
  ext_cc_metric_worst_patch: {
    zh: "最差色块",
    en: "Worst Patch",
  },
  ext_cc_metric_delta_e00: {
    zh: "DeltaE00",
    en: "DeltaE00",
  },
  ext_cc_luminance_curve: {
    zh: "亮度曲线",
    en: "Luminance Curve",
  },
  ext_cc_no_curve: {
    zh: "暂无曲线",
    en: "No curve",
  },
  ext_cc_calibrated_badge: {
    zh: "已校色 ✓",
    en: "Calibrated ✓",
  },
  ext_cc_confirm_title: {
    zh: "校色结果确认",
    en: "Calibration Result",
  },
  ext_cc_confirm_body: {
    zh: "请检查下方校色后的图片。如果颜色看起来正确，点击「确认使用」将此校色结果用于后续提取；否则点击「重新校色」重新标记角点。",
    en: "Review the calibrated image below. If colors look correct, click Accept to use it for extraction; otherwise click Retry to re-mark corners.",
  },
  ext_cc_compare_original: {
    zh: "原图",
    en: "Original",
  },
  ext_cc_compare_calibrated: {
    zh: "校准后",
    en: "Calibrated",
  },
  ext_cc_confirm_accept: {
    zh: "确认使用",
    en: "Accept",
  },
  ext_cc_confirm_reject: {
    zh: "重新校色",
    en: "Retry",
  },
  ext_cc_main_area_hint: {
    zh: "24 色卡校色会在弹窗中进行，完成并确认后再继续选择 LUT 色卡四角。",
    en: "The 24-patch correction runs in a popup. Continue picking LUT corners after you confirm.",
  },
  ext_cc_main_area_hint_upload: {
    zh: "上传校准板照片后会自动弹出校色窗口；也可以稍后点「打开校色工具」手动打开。",
    en: "Uploading the calibration board photo opens the correction popup automatically. You can also reopen it later with Open Calibration Tool.",
  },
  ext_cc_advanced_toggle: {
    zh: "高级选项",
    en: "Advanced Options",
  },
  ext_cc_advanced_hint: {
    zh: "默认使用 3x3 矩阵校色。只有需要对比算法、采样方式或灰阶归一化时再打开。",
    en: "The default uses a 3x3 matrix. Enable this only when comparing algorithms, sampling, or gray-axis normalization.",
  },
  ext_cc_algorithm_label: {
    zh: "校色算法",
    en: "Calibration Algorithm",
  },
  ext_cc_algorithm_matrix_3x3: {
    zh: "3x3 矩阵（默认）",
    en: "3x3 Matrix (Default)",
  },
  ext_cc_algorithm_matrix_3x4: {
    zh: "3x4 仿射矩阵",
    en: "3x4 Affine Matrix",
  },
  ext_cc_algorithm_root_polynomial: {
    zh: "二阶 Root-Polynomial",
    en: "Degree-2 Root-Polynomial",
  },
  ext_cc_algorithm_auto: {
    zh: "自动选择",
    en: "Auto",
  },
  ext_cc_sampling_method_label: {
    zh: "采样方式",
    en: "Sampling Method",
  },
  ext_cc_sampling_mean: {
    zh: "平均值",
    en: "Mean",
  },
  ext_cc_sampling_median: {
    zh: "中位数",
    en: "Median",
  },
  ext_cc_gray_affine_label: {
    zh: "灰阶归一化",
    en: "Gray Normalization",
  },
  ext_cc_gray_affine_auto: {
    zh: "自动",
    en: "Auto",
  },
  ext_cc_gray_affine_enabled: {
    zh: "强制启用",
    en: "Force On",
  },
  ext_cc_gray_affine_fallback: {
    zh: "回退模式",
    en: "Fallback",
  },
  ext_cc_sample_radius_label: {
    zh: "采样半径",
    en: "Sample Radius",
  },
  ext_cc_blur_radius_label: {
    zh: "输出柔化",
    en: "Output Blur",
  },
  ext_cc_reference_label: {
    zh: "当前基准",
    en: "Reference",
  },
  ext_cc_reference_builtin: {
    zh: "内置 24 色卡基准",
    en: "Built-in 24-patch reference",
  },
  ext_cc_reference_meta: {
    zh: "{count} 个色块 · Lab 白点 {whitePoint}",
    en: "{count} patches · Lab white point {whitePoint}",
  },
  ext_cc_reference_select_title: {
    zh: "校色基准",
    en: "Calibration Reference",
  },
  ext_cc_reference_select_hint: {
    zh: "检测评分和校色拟合会使用同一个基准。",
    en: "Detection scoring and calibration fitting use the same reference.",
  },
  ext_cc_reference_select_label: {
    zh: "选择基准",
    en: "Select reference",
  },
  ext_cc_reference_group_server: {
    zh: "服务端预设",
    en: "Server presets",
  },
  ext_cc_reference_group_custom: {
    zh: "自定义基准",
    en: "Custom references",
  },
  ext_cc_reference_upload_btn: {
    zh: "上传 .xlsx",
    en: "Upload .xlsx",
  },
  ext_cc_reference_delete_btn: {
    zh: "删除自定义",
    en: "Delete custom",
  },
  ext_cc_reference_upload_ready: {
    zh: "校色基准已上传并选中",
    en: "Reference uploaded and selected",
  },
  ext_cc_reference_upload_ready_with_warnings: {
    zh: "校色基准已上传并选中，{count} 条提示",
    en: "Reference uploaded and selected with {count} warnings",
  },
  ext_cc_reference_upload_ready_session_only: {
    zh: "校色基准已用于当前会话，但浏览器阻止保存，刷新页面后需要重新上传。",
    en: "Reference is selected for this session, but the browser blocked saving it. Upload it again after refreshing.",
  },
  ext_cc_reference_upload_failed: {
    zh: "校色基准上传失败",
    en: "Reference upload failed",
  },
  ext_cc_reference_load_failed: {
    zh: "校色基准列表加载失败",
    en: "Failed to load references",
  },
  ext_cc_reference_serial: {
    zh: "SN：{serial}",
    en: "SN: {serial}",
  },
  ext_cc_algorithm_meta: {
    zh: "{method} 采样 · 灰阶 {gray}",
    en: "{method} sampling · Gray {gray}",
  },
  ext_cc_unknown_value: {
    zh: "未知",
    en: "Unknown",
  },
  ext_cc_overlay_title: {
    zh: "色卡检查图",
    en: "Patch Check View",
  },
  ext_cc_no_overlay: {
    zh: "暂无检查图",
    en: "No check view",
  },
  ext_cc_warning_title: {
    zh: "校色质量提示",
    en: "Correction Quality Notice",
  },
  ext_cc_warning_fit_metric: {
    zh: "{metric} ΔE00 为 {value}，高于建议值 {threshold}。建议检查色卡角点、采样点和光照。",
    en: "{metric} ΔE00 is {value}, above the suggested {threshold}. Check chart corners, sample points, and lighting.",
  },
  ext_cc_warning_patch_validity: {
    zh: "{total} 个色块中有 {invalid} 个未参与拟合。请检查采样点是否落在色块中心，并适当调小采样半径。",
    en: "{invalid} of {total} patches were excluded from fitting. Check that sample points are centered and reduce the sample radius if needed.",
  },
  ext_cc_warning_gray_l_not_monotonic: {
    zh: "中性灰亮度顺序不稳定。请检查灰阶色块是否被反光、阴影或错误采样影响。",
    en: "Neutral gray brightness is not monotonic. Check for glare, shadow, or misplaced gray samples.",
  },
  ext_cc_warning_gray_a_threshold: {
    zh: "中性灰 a* 偏色偏高。建议检查白平衡、光源和灰阶采样点。",
    en: "Neutral gray a* cast is high. Check white balance, lighting, and gray sample points.",
  },
  ext_cc_warning_gray_b_threshold: {
    zh: "中性灰 b* 偏色偏高。建议检查白平衡、光源和灰阶采样点。",
    en: "Neutral gray b* cast is high. Check white balance, lighting, and gray sample points.",
  },
  ext_cc_warning_gray_reference_delta: {
    zh: "{index}. {label} 灰块的 Δ{axis}* 为 {delta}（校色后 {corrected}，参考 {reference}），高于建议值 {threshold}。建议检查白平衡、光源和该灰阶采样点。",
    en: "Gray patch {index}. {label} has Δ{axis}* {delta} (corrected {corrected}, reference {reference}), above the suggested {threshold}. Check white balance, lighting, and that gray sample point.",
  },
  ext_cc_warning_negative_ratio: {
    zh: "校色后有 {value} 的像素出现负通道裁剪。建议改用默认算法或降低高级校正强度。",
    en: "{value} of corrected pixels have negative-channel clipping. Prefer the default algorithm or reduce advanced correction strength.",
  },
  ext_cc_warning_clipping_ratio: {
    zh: "校色后有 {value} 的线性 RGB 通道样本超过 1.0，导出到当前显示色域时会被裁剪。建议检查曝光，或改用更保守的算法。",
    en: "{value} of corrected linear RGB channel samples exceed 1.0 and will be clipped for the current display gamut. Check exposure or use a more conservative algorithm.",
  },
  ext_cc_delta_status_high_precision: {
    zh: "高精度",
    en: "High precision",
  },
  ext_cc_delta_status_acceptable: {
    zh: "可接受",
    en: "Acceptable",
  },
  ext_cc_delta_status_check: {
    zh: "需检查",
    en: "Check",
  },
  ext_cc_warning_exposure_drift: {
    zh: "该算法对曝光变化较敏感，结果可能随亮度变化而偏色。建议优先使用默认 3x3 矩阵。",
    en: "This algorithm is sensitive to exposure changes. Prefer the default 3x3 matrix unless you are comparing expert settings.",
  },
  ext_cc_warning_affine_bias: {
    zh: "仿射算法的偏置项较大，暗部颜色可能漂移。建议检查黑色块采样或改回 3x3 矩阵。",
    en: "The affine bias is high, so dark colors may drift. Check black-patch sampling or switch back to the 3x3 matrix.",
  },
  ext_cc_warning_generic: {
    zh: "校色结果存在质量风险。请检查角点、采样点、曝光和色卡摆放。",
    en: "The correction result has a quality risk. Check corners, samples, exposure, and chart placement.",
  },
  ext_extract_btn_label: {
    zh: "提取颜色",
    en: "Extract Colors",
  },
  ext_clear_corners: {
    zh: "清除角点",
    en: "Clear Corners",
  },
  ext_merge_5c_title: {
    zh: "5色扩展双页合并",
    en: "5-Color Extended Dual-Page Merge",
  },
  ext_merge_8c_title: {
    zh: "8色双页合并",
    en: "8-Color Dual-Page Merge",
  },
  ext_merge_8c_full_title: {
    zh: "8色完整版合并",
    en: "8-Color Full Merge",
  },
  ext_merge_5c_btn: {
    zh: "合并 5 色 LUT",
    en: "Merge 5-Color LUT",
  },
  ext_merge_8c_btn: {
    zh: "合并 8 色 LUT",
    en: "Merge 8-Color LUT",
  },
  ext_merge_8c_full_btn: {
    zh: "合并 8 色完整版 LUT",
    en: "Merge Full 8-Color LUT",
  },
  ext_pages_extracted_label: {
    zh: "已提取页数",
    en: "Extracted Pages",
  },
  ext_page_extracted: {
    zh: "已提取",
    en: "Extracted",
  },
  ext_page_not_extracted: {
    zh: "未提取",
    en: "Not extracted",
  },
  ext_page_1_label: {
    zh: "第 1 页",
    en: "Page 1",
  },
  ext_page_2_label: {
    zh: "第 2 页",
    en: "Page 2",
  },
  ext_8color_full_export_label: {
    zh: "8色完整版提取",
    en: "Full 8-Color Extraction",
  },
  ext_8color_full_export_hint: {
    zh: "如果你的校准板来自完整版 ZIP，请开启后按 1号-24号逐页提取并在全部完成后合并。",
    en: "Enable this if your calibration boards come from the full 8-color ZIP, then extract pages 1-24 and merge after all pages are complete.",
  },
  ext_8color_full_export_on: {
    zh: "全量",
    en: "Full",
  },
  ext_8color_full_export_off: {
    zh: "精简",
    en: "Compact",
  },
  ext_download_lut: {
    zh: "下载 LUT 文件 (.json)",
    en: "Download LUT File (.json)",
  },
  ext_manual_fix_hint: {
    zh: "点击右侧 LUT 预览图中的色块可手动修正颜色",
    en: "Click a cell in the LUT preview to manually fix its color",
  },
  ext_manual_fix_resolve_failed: {
    zh: "无法识别你点击的 LUT 色块，请重新提取后再试。",
    en: "Could not resolve the selected LUT cell. Re-run extraction and try again.",
  },
  ext_material_type_label: {
    zh: "耗材类型",
    en: "Material Type",
  },
  ext_palette_title: {
    zh: "调色板确认",
    en: "Palette Confirmation",
  },
  ext_palette_metadata_hint: {
    zh: "填写厂商、类型，并为每个颜色记录厂商命名",
    en: "Set manufacturer, type, and vendor color names for each entry",
  },
  ext_manufacturer_label: {
    zh: "厂商",
    en: "Manufacturer",
  },
  ext_type_label: {
    zh: "类型",
    en: "Type",
  },
  ext_palette_internal_color_label: {
    zh: "内部通道",
    en: "Internal Slot",
  },
  ext_palette_color_name_label: {
    zh: "厂商颜色名称",
    en: "Vendor Color Name",
  },
  ext_confirm_palette_btn: {
    zh: "确认调色板",
    en: "Confirm Palette",
  },
  ext_palette_confirmed: {
    zh: "✓ 调色板已确认",
    en: "✓ Palette confirmed",
  },

  // ==================== Extractor Canvas ====================
  ext_canvas_warp_view: {
    zh: "定位标记图",
    en: "Corner Markers",
  },
  ext_canvas_lut_preview: {
    zh: "LUT 预览 / 点击色块修正颜色",
    en: "LUT Preview / Click cell to fix color",
  },
  ext_canvas_row: {
    zh: "行",
    en: "Row",
  },
  ext_canvas_col: {
    zh: "列",
    en: "Col",
  },
  ext_canvas_fixing: {
    zh: "修正中...",
    en: "Fixing...",
  },
  ext_canvas_confirm_fix: {
    zh: "确认修正",
    en: "Confirm Fix",
  },
  ext_canvas_cancel: {
    zh: "取消",
    en: "Cancel",
  },
  ext_canvas_upload_hint: {
    zh: "请在左侧面板上传校准板照片",
    en: "Upload a calibration board photo from the left panel",
  },
  ext_canvas_upload_hint_en: {
    zh: "上传校准板照片以开始",
    en: "Upload a calibration board photo to begin",
  },
  ext_canvas_positioning_done: {
    zh: "定位完成",
    en: "Positioning Complete",
  },
  ext_canvas_click_corner: {
    zh: "请点击第 {n} 个角点: {label}",
    en: "Click corner {n}: {label}",
  },

  // ==================== Basic Settings ====================
  basic_crop_after_upload: {
    zh: "上传后裁剪",
    en: "Crop After Upload",
  },
  basic_image_rotation_label: {
    zh: "图像旋转",
    en: "Image Rotation",
  },
  basic_image_rotation_apply: {
    zh: "应用旋转",
    en: "Apply Rotation",
  },
  basic_image_rotation_hint: {
    zh: "旋转会直接更新当前图片；后续预览和导出都会使用旋转后的图像。",
    en: "Rotation updates the current image; later previews and exports use the rotated image.",
  },
  basic_image_rotation_failed: {
    zh: "图像旋转失败",
    en: "Failed to rotate image",
  },
  basic_lut_label: {
    zh: "LUT",
    en: "LUT",
  },
  basic_lut_manufacturer_label: {
    zh: "品牌",
    en: "Brand",
  },
  basic_lut_manufacturer_placeholder: {
    zh: "选择品牌",
    en: "Select a brand",
  },
  basic_lut_unlabeled_brand: {
    zh: "个人",
    en: "Personal",
  },
  basic_lut_placeholder: {
    zh: "选择 LUT...",
    en: "Select LUT...",
  },
  basic_lut_lut_placeholder: {
    zh: "选择 LUT",
    en: "Select a LUT",
  },
  basic_lut_no_brand_hint: {
    zh: "请先选择品牌",
    en: "Pick a brand first",
  },
  basic_lut_multi_select: {
    zh: "同组多选 LUT",
    en: "Multi-select LUTs in this group",
  },
  basic_lut_selected_count: {
    zh: "已选",
    en: "Selected",
  },
  basic_lut_color_mode_bw: {
    zh: "黑白",
    en: "BW",
  },
  basic_lut_color_mode_4color: {
    zh: "4 色",
    en: "4-Color",
  },
  basic_lut_color_mode_4color_cmyw: {
    zh: "4 色 CMYW",
    en: "4-Color (CMYW)",
  },
  basic_lut_color_mode_4color_rybw: {
    zh: "4 色 RYBW",
    en: "4-Color (RYBW)",
  },
  basic_lut_color_mode_5color_ext: {
    zh: "5 色扩展",
    en: "5-Color Extended",
  },
  basic_lut_color_mode_5color_ext_1444: {
    zh: "5 色扩展 1444",
    en: "5-Color Extended (1444)",
  },
  basic_lut_color_mode_6color: {
    zh: "6 色",
    en: "6-Color",
  },
  basic_lut_color_mode_6color_cmywgk: {
    zh: "6 色 CMYWGK",
    en: "6-Color (CMYWGK 1296)",
  },
  basic_lut_color_mode_6color_rybwgk: {
    zh: "6 色 RYBWGK",
    en: "6-Color (RYBWGK 1296)",
  },
  basic_lut_color_mode_8color: {
    zh: "8 色",
    en: "8-Color",
  },
  basic_lut_color_mode_8color_max: {
    zh: "8 色 Max",
    en: "8-Color Max",
  },
  basic_lut_color_mode_merged: {
    zh: "合并 LUT",
    en: "Merged",
  },
  basic_lut_upload: {
    zh: "上传",
    en: "Upload",
  },
  basic_lut_refresh: {
    zh: "刷新",
    en: "Refresh",
  },
  basic_lut_refresh_tooltip: {
    zh: "重新读取 LUT 目录",
    en: "Reload LUT directory",
  },
  basic_lut_upload_success: {
    zh: "LUT 上传成功",
    en: "LUT uploaded",
  },
  basic_lut_upload_error: {
    zh: "LUT 上传失败",
    en: "LUT upload failed",
  },
  basic_color_mode_label: {
    zh: "色彩模式",
    en: "Color Mode",
  },
  basic_source_version_label: {
    zh: "来源类型",
    en: "Source Type",
  },
  basic_source_version_legacy: {
    zh: "传统 LUT",
    en: "Legacy LUT",
  },
  basic_source_version_native: {
    zh: "\u53cd\u63a8LUT",
    en: "Inferred LUT",
  },
  basic_source_version_material: {
    zh: "\u8017\u6750\u6863\u6848",
    en: "Material Archive",
  },
  basic_material_select_label: {
    zh: "\u9009\u62e9\u8017\u6750",
    en: "Select Materials",
  },
  basic_material_loading: {
    zh: "\u52a0\u8f7d\u8017\u6750\u5e93\u2026",
    en: "Loading materials\u2026",
  },
  basic_material_empty: {
    zh: "\u65e0\u53ef\u7528\u8017\u6750\uff0c\u8bf7\u5148\u5728\u300c\u8017\u6750\u63d0\u53d6\u300d\u4e2d\u521b\u5efa",
    en: "No materials available. Create one in Material Extraction first.",
  },
  basic_material_selected_count: {
    zh: "\u5df2\u9009\u8017\u6750",
    en: "Selected",
  },
  basic_material_layer_count_label: {
    zh: "\u53e0\u8272\u5c42\u6570",
    en: "Color Layers",
  },
  basic_material_layer_count_hint: {
    zh: "\u53c2\u4e0e\u53e0\u8272\u6df7\u5408\u7684\u8017\u6750\u79cd\u7c7b\u6570\u91cf\u3002\u5c42\u6570\u8d8a\u591a\u8272\u5f69\u8fc7\u6e21\u8d8a\u4e30\u5bcc\uff0c\u4f46\u6253\u5370\u65f6\u95f4\u8d8a\u957f\u3002",
    en: "Number of material types involved in color blending. More layers produce richer color transitions but increase print time.",
  },
  basic_material_layer_height_label: {
    zh: "\u5c42\u9ad8",
    en: "Layer Height",
  },
  basic_material_backing_label: {
    zh: "\u5e95\u677f\u8017\u6750",
    en: "Base Plate Material",
  },
  basic_material_backing_placeholder: {
    zh: "\u5148\u9009\u62e9\u8017\u6750",
    en: "Select materials first",
  },
  basic_material_picker_open: {
    zh: "\u9009\u62e9\u8017\u6750\u2026",
    en: "Choose materials\u2026",
  },
  basic_material_picker_summary_more: {
    zh: "\u7b49 {count} \u79cd",
    en: "+{count} more",
  },
  basic_material_picker_dialog_title: {
    zh: "\u9009\u62e9\u8017\u6750",
    en: "Choose Materials",
  },
  basic_material_picker_dialog_subtitle: {
    zh: "\u52fe\u9009\u8981\u53c2\u4e0e\u8c03\u8272\u7684\u8017\u6750\uff08\u53ef\u591a\u9009\uff09",
    en: "Pick materials to use for color blending (multi-select)",
  },
  basic_material_picker_done: {
    zh: "\u5b8c\u6210",
    en: "Done",
  },
  basic_material_picker_clear: {
    zh: "\u6e05\u7a7a",
    en: "Clear all",
  },
  basic_material_picker_select_all: {
    zh: "\u5168\u9009",
    en: "Select all",
  },
  basic_material_picker_deselect_all: {
    zh: "\u6e05\u7a7a\u9009\u62e9",
    en: "Deselect all",
  },
  basic_material_picker_close: {
    zh: "\u5173\u95ed",
    en: "Close",
  },
  basic_material_picker_search_placeholder: {
    zh: "\u641c\u7d22\u8017\u6750\u540d\u79f0\u2026",
    en: "Search materials\u2026",
  },
  basic_material_picker_search_clear: {
    zh: "\u6e05\u9664\u641c\u7d22",
    en: "Clear search",
  },
  basic_material_picker_no_match: {
    zh: "\u6ca1\u6709\u5339\u914d\u7684\u8017\u6750",
    en: "No materials match your search",
  },
  basic_material_cache_section_title: {
    zh: "穷举缓存",
    en: "Exhaustive Cache",
  },
  basic_material_cache_open_button: {
    zh: "\u7a77\u4e3e\u7f13\u5b58\u2026",
    en: "Exhaustive cache\u2026",
  },
  basic_material_cache_section_description: {
    zh: "为当前耗材组合构建 Lab 网格配方库，后续出图直接查表。",
    en: "Build a Lab-grid recipe library for this palette so future conversions are served from cache.",
  },
  basic_material_cache_active_grid_label: {
    zh: "当前穷举数量：{tier}（{grid}³）。可在设置里切换。",
    en: "Current density: {tier} ({grid}³). Change in Settings.",
  },
  basic_material_cache_status_idle: {
    zh: "请选择至少一种耗材后查看缓存状态。",
    en: "Select at least one material to view cache status.",
  },
  basic_material_cache_status_checking: {
    zh: "正在检查缓存\u2026",
    en: "Checking cache\u2026",
  },
  basic_material_cache_status_ready: {
    zh: "缓存已就绪",
    en: "Cache ready",
  },
  basic_material_cache_status_missing: {
    zh: "缓存未构建",
    en: "Cache not built",
  },
  basic_material_cache_status_error: {
    zh: "缓存状态查询失败",
    en: "Failed to query cache status",
  },
  basic_material_cache_status_error_detail: {
    zh: "缓存状态查询失败，请稍后重试。",
    en: "Failed to query the cache status. Please try again later.",
  },
  basic_material_cache_fallback_hint: {
    zh: "未构建缓存时，每张图将使用 B&B 最优求解器（耗时较长，保证最优）。",
    en: "When no cache is available, every conversion runs the B&B optimal solver (slower, always optimal).",
  },
  basic_material_cache_build_button: {
    zh: "立即构建缓存",
    en: "Build cache now",
  },
  basic_material_cache_building_label: {
    zh: "正在构建\u2026",
    en: "Building\u2026",
  },
  basic_material_cache_building_hint: {
    zh: "穷举 {combinations} 种组合并落盘，大约需要 {seconds} 秒。",
    en: "Enumerating {combinations} combinations and writing to disk — about {seconds} seconds.",
  },
  basic_material_cache_budget_warning: {
    zh: "当前组合约 {combinations} 种配方，grid={grid} 的缓存构建可能超过穷举或内存预算。请减少耗材/层数；若是高密度档位，也可降低 grid。",
    en: "This combination has about {combinations} recipes; building grid={grid} may exceed the enumeration or memory budget. Reduce materials/layers; for high-density builds, lower grid.",
  },
  basic_material_cache_rebuild_button: {
    zh: "重新构建",
    en: "Rebuild",
  },
  basic_material_cache_delete_button: {
    zh: "删除缓存",
    en: "Delete cache",
  },
  basic_material_cache_charts_show_button: {
    zh: "查看色彩分布图",
    en: "View color charts",
  },
  basic_material_cache_charts_hide_button: {
    zh: "收起色彩分布图",
    en: "Hide color charts",
  },
  basic_material_cache_charts_loading: {
    zh: "正在加载色彩分布图…",
    en: "Loading color charts…",
  },
  basic_material_cache_charts_error: {
    zh: "色彩分布图加载失败：{message}",
    en: "Failed to load color charts: {message}",
  },
  basic_material_cache_charts_failed: {
    zh: "色彩分布图加载失败，请稍后重试。",
    en: "Failed to load the color charts. Please try again later.",
  },
  basic_material_cache_confirm_delete: {
    zh: "确认删除当前组合的缓存？",
    en: "Delete the cache for this combination?",
  },
  basic_material_cache_built_at_label: {
    zh: "构建时间",
    en: "Built at",
  },
  basic_material_cache_size_label: {
    zh: "缓存大小",
    en: "Cache size",
  },
  basic_material_cache_coverage_label: {
    zh: "覆盖格数",
    en: "Cell coverage",
  },
  basic_material_cache_mean_delta_e_label: {
    zh: "平均 ΔE",
    en: "Mean ΔE",
  },
  basic_material_cache_max_delta_e_label: {
    zh: "最大 ΔE",
    en: "Max ΔE",
  },
  basic_material_cache_build_time_label: {
    zh: "构建耗时",
    en: "Build time",
  },
  basic_material_cache_units_seconds: {
    zh: "{seconds} 秒",
    en: "{seconds} s",
  },
  basic_material_cache_units_mb: {
    zh: "{mb} MB",
    en: "{mb} MB",
  },
  basic_material_cache_build_error: {
    zh: "构建失败：{message}",
    en: "Build failed: {message}",
  },
  basic_material_cache_build_failed: {
    zh: "缓存构建失败，请稍后重试。",
    en: "Cache build failed. Please try again later.",
  },
  basic_material_cache_delete_error: {
    zh: "删除失败：{message}",
    en: "Delete failed: {message}",
  },
  basic_material_cache_delete_failed: {
    zh: "缓存删除失败，请稍后重试。",
    en: "Cache delete failed. Please try again later.",
  },
  basic_material_runtime_section_title: {
    zh: "智能配方缓存",
    en: "Smart Recipe Cache",
  },
  basic_material_runtime_section_description: {
    zh: "为大耗材组合预生成覆盖广的配方，加速颜色匹配。",
    en: "Precompute broad recipe coverage for large material palettes to speed color matching.",
  },
  basic_material_runtime_status_idle: {
    zh: "请选择至少一种耗材后查看智能缓存状态。",
    en: "Select at least one material to view smart cache status.",
  },
  basic_material_runtime_status_checking: {
    zh: "正在检查智能缓存…",
    en: "Checking smart cache…",
  },
  basic_material_runtime_status_ready: {
    zh: "智能缓存已就绪",
    en: "Smart cache ready",
  },
  basic_material_runtime_status_missing: {
    zh: "配方缓存未构建",
    en: "Smart recipe cache not built",
  },
  basic_material_runtime_status_error: {
    zh: "智能缓存状态查询失败",
    en: "Failed to query smart cache status",
  },
  basic_material_runtime_status_error_detail: {
    zh: "智能缓存状态查询失败，请稍后重试。",
    en: "Failed to query the smart cache status. Please try again later.",
  },
  basic_material_runtime_budget_label: {
    zh: "缓存规模",
    en: "Cache size",
  },
  basic_material_runtime_budget_option_1048576: {
    zh: "快速 1M",
    en: "Fast 1M",
  },
  basic_material_runtime_budget_option_4194304: {
    zh: "标准 4M",
    en: "Standard 4M",
  },
  basic_material_runtime_budget_option_8388608: {
    zh: "高精度 8M",
    en: "High 8M",
  },
  basic_material_runtime_budget_option_33554432: {
    zh: "推荐 32M",
    en: "Recommended 32M",
  },
  basic_material_runtime_budget_option_67108864: {
    zh: "极高 64M",
    en: "Extreme 64M",
  },
  basic_material_runtime_missing_hint: {
    zh: "未构建时，系统会按需临时生成一份小规模配方缓存。",
    en: "When no smart cache is saved, the system builds a small recipe cache on demand.",
  },
  basic_material_runtime_build_button: {
    zh: "构建智能缓存",
    en: "Build smart cache",
  },
  basic_material_runtime_rebuild_button: {
    zh: "重建智能缓存",
    en: "Rebuild smart cache",
  },
  basic_material_runtime_delete_button: {
    zh: "删除智能缓存",
    en: "Delete smart cache",
  },
  basic_material_runtime_charts_show_button: {
    zh: "查看配方覆盖图",
    en: "View recipe coverage",
  },
  basic_material_runtime_charts_hide_button: {
    zh: "收起配方覆盖图",
    en: "Hide recipe coverage",
  },
  basic_material_runtime_charts_loading: {
    zh: "正在加载配方覆盖图…",
    en: "Loading recipe coverage…",
  },
  basic_material_runtime_charts_error: {
    zh: "配方覆盖图加载失败：{message}",
    en: "Failed to load recipe coverage: {message}",
  },
  basic_material_runtime_charts_failed: {
    zh: "配方覆盖图加载失败，请稍后重试。",
    en: "Failed to load recipe coverage. Please try again later.",
  },
  basic_material_runtime_building_label: {
    zh: "正在构建智能缓存…",
    en: "Building smart cache…",
  },
  basic_material_runtime_building_hint: {
    zh: "正在生成 {budget} 条配方并保存。",
    en: "Generating and saving {budget} recipes.",
  },
  basic_material_runtime_confirm_delete: {
    zh: "确认删除当前组合的智能配方缓存？",
    en: "Delete the smart recipe cache for this combination?",
  },
  basic_material_runtime_candidates_label: {
    zh: "配方数",
    en: "Recipe count",
  },
  basic_material_runtime_inverse_label: {
    zh: "反推精修",
    en: "Inverse refinement",
  },
  basic_material_runtime_enabled: {
    zh: "启用",
    en: "Enabled",
  },
  basic_material_runtime_disabled: {
    zh: "关闭",
    en: "Disabled",
  },
  basic_material_runtime_build_error: {
    zh: "智能缓存构建失败：{message}",
    en: "Smart cache build failed: {message}",
  },
  basic_material_runtime_build_failed: {
    zh: "智能缓存构建失败，请稍后重试。",
    en: "Smart cache build failed. Please try again later.",
  },
  basic_material_runtime_delete_error: {
    zh: "智能缓存删除失败：{message}",
    en: "Smart cache delete failed: {message}",
  },
  basic_material_runtime_delete_failed: {
    zh: "智能缓存删除失败，请稍后重试。",
    en: "Smart cache delete failed. Please try again later.",
  },
  basic_source_kind_label: {
    zh: "颜色源类型",
    en: "Source Kind",
  },
  basic_brand_label: {
    zh: "品牌",
    en: "Brand",
  },
  basic_brand_loading: {
    zh: "品牌目录加载中…",
    en: "Loading brands…",
  },
  basic_brand_placeholder: {
    zh: "请选择品牌",
    en: "Select a brand",
  },
  basic_native_brand_placeholder: {
    zh: "请选择品牌",
    en: "Select a brand",
  },
  basic_native_brand_summary_label: {
    zh: "品牌信息",
    en: "Brand Info",
  },
  basic_native_material_label: {
    zh: "材质类型",
    en: "Material Type",
  },
  basic_native_vendor_label: {
    zh: "供应商",
    en: "Vendor",
  },
  basic_native_db_label: {
    zh: "数据库",
    en: "Databases",
  },
  basic_native_db_placeholder: {
    zh: "未选择数据库",
    en: "No databases selected",
  },
  basic_native_mode_label: {
    zh: "动态层模式",
    en: "Layer Mode",
  },
  basic_native_layer_count_label: {
    zh: "层数",
    en: "Layer Count",
  },
  basic_native_mode_placeholder: {
    zh: "请选择支持模式",
    en: "Select a supported mode",
  },
  basic_color_layers_label: {
    zh: "叠色层数",
    en: "Color Layers",
  },
  basic_color_layers_hint: {
    zh: "叠色混合使用的层数。层数越多可表现的颜色越丰富，但打印耗时和耗材消耗也相应增加。",
    en: "Number of layers used for color blending. More layers enable richer colors but increase print time and material consumption.",
  },
  basic_layer_height_label: {
    zh: "叠色层高",
    en: "Layer Height",
  },
  basic_layer_height_hint: {
    zh: "每层叠色的打印高度（毫米）。较小的层高可获得更细腻的色彩过渡，但打印时间更长。",
    en: "Print height per color layer (in mm). Smaller layer heights produce smoother color transitions but increase print time.",
  },
  basic_supported_modes_label: {
    zh: "支持模式",
    en: "Supported Modes",
  },
  basic_model_gate_label: {
    zh: "模型辅助匹配",
    en: "Model-Assisted Matching",
  },
  basic_model_enable: {
    zh: "模型辅助匹配",
    en: "Model-Assisted Matching",
  },
  basic_model_only: {
    zh: "仅模型匹配",
    en: "Model only",
  },
  basic_model_threshold: {
    zh: "模型阈值",
    en: "Model Threshold",
  },
  basic_model_margin: {
    zh: "模型边距",
    en: "Model Margin",
  },
  basic_model_runtime_defaults_hint: {
    zh: "留空则使用运行时默认值。",
    en: "Leave blank to use runtime defaults.",
  },
  basic_dynamic_layers_legacy_hint: {
    zh: "当前为旧 LUT，不支持动态层数或自定义配方。",
    en: "This legacy LUT does not support dynamic layers or custom recipes.",
  },
  basic_width: {
    zh: "宽度",
    en: "Width",
  },
  basic_width_hint: {
    zh: "打印成品的宽度（毫米）。需在打印机有效打印范围内。",
    en: "Printed output width (in mm). Must be within the printer's effective print area.",
  },
  basic_height: {
    zh: "高度",
    en: "Height",
  },
  basic_height_hint: {
    zh: "打印成品的高度（毫米）。需在打印机有效打印范围内。",
    en: "Printed output height (in mm). Must be within the printer's effective print area.",
  },
  basic_thickness: {
    zh: "厚度",
    en: "Thickness",
  },
  basic_thickness_hint: {
    zh: "底板的厚度（毫米）。每一格对应一层打印层（0.08 mm），影响成品的整体厚度。",
    en: "Base plate thickness (in mm). Each tick equals one print layer (0.08 mm), affecting the overall thickness of the output.",
  },
  basic_structure_mode: {
    zh: "结构模式",
    en: "Structure Mode",
  },
  basic_modeling_mode: {
    zh: "建模模式",
    en: "Modeling Mode",
  },
  basic_image_format_error: {
    zh: "仅支持 JPG/PNG/SVG/WebP/HEIC 格式",
    en: "Only JPG/PNG/SVG/WebP/HEIC formats are supported",
  },
  converter_raw_preview_failed: {
    zh: "RAW 图片预览失败：{error}。请先转换为 PNG/JPG 后再试。",
    en: "RAW image preview failed: {error}. Please convert it to PNG or JPG and try again.",
  },
  extractor_raw_preview_failed: {
    zh: "RAW 图片预览失败：{error}。请先转换为 PNG/JPG 后再试。",
    en: "RAW image preview failed: {error}. Please convert it to PNG or JPG and try again.",
  },

  // ==================== Large Format Mode ====================
  slicer_download_zip: {
    zh: "下载 ZIP",
    en: "Download ZIP",
  },
  slicer_generate_download_zip: {
    zh: "生成并下载 ZIP",
    en: "Generate & Download ZIP",
  },
  basic_large_format: {
    zh: "大画幅模式",
    en: "Large Format Mode",
  },
  basic_large_format_hint: {
    zh: "自动切割为多片 3MF 压缩包",
    en: "Auto-tiled into a ZIP of 3MF files",
  },
  basic_tile_width: {
    zh: "切片宽度",
    en: "Tile Width",
  },
  basic_tile_width_hint: {
    zh: "大画幅模式下每个切片的宽度（毫米）。切片越小，拼接数量越多。",
    en: "Width of each tile in large format mode (in mm). Smaller tiles result in more pieces to assemble.",
  },
  basic_tile_height: {
    zh: "切片高度",
    en: "Tile Height",
  },
  basic_tile_height_hint: {
    zh: "大画幅模式下每个切片的高度（毫米）。切片越小，拼接数量越多。",
    en: "Height of each tile in large format mode (in mm). Smaller tiles result in more pieces to assemble.",
  },

  // ==================== Structure Mode Options ====================
  "structure_mode.Double-sided": {
    zh: "双面",
    en: "Double-sided",
  },
  "structure_mode.Single-sided": {
    zh: "单面",
    en: "Single-sided",
  },

  // ==================== Modeling Mode Options ====================
  "modeling_mode.high-fidelity": {
    zh: "高保真",
    en: "High-Fidelity",
  },
  "modeling_mode.pixel": {
    zh: "像素艺术",
    en: "Pixel Art",
  },
  "modeling_mode.vector": {
    zh: "矢量模式",
    en: "Vector",
  },
  "modeling_mode.color-card": {
    zh: "验证色卡",
    en: "Color Card",
  },

  // ==================== Advanced Settings ====================
  adv_quantize_colors: {
    zh: "量化颜色数",
    en: "Quantize Colors",
  },
  adv_quantize_colors_hint: {
    zh: "K-Means 聚类的色彩细节数量。值越大色彩过渡越细腻，但处理越慢；值越小色块越少、渲染越快。仅适用于高保真模式，矢量模式下不进行量化处理，此参数不生效。",
    en: "Number of K-Means clusters for color quantization. Higher values produce smoother color transitions but increase processing time; lower values produce fewer color blocks and faster rendering. Only applies in High-Fidelity mode; this parameter has no effect in Vector mode as quantization is not performed.",
  },
  adv_isolated_pixel_cleanup: {
    zh: "孤立像素清理",
    en: "Isolated Pixel Cleanup",
  },
  adv_isolated_pixel_cleanup_hint: {
    zh: "将色彩匹配后与 8 邻域完全不同的孤立像素替换为邻域众数邻居的对应值，不会造调色板外的新颜色。高保真模式下的 LUT 匹配、预测匹配与耗材档案路径均会应用此清理。",
    en: "Replaces isolated pixels (whose material stack differs from all 8 neighbors) with values copied from the neighborhood-mode neighbor — palette-preserving by construction. Runs in High-Fidelity modeling mode across the legacy LUT, predictive matching, and material-archive pipelines.",
  },
  adv_separate_backing: {
    zh: "分离底板",
    en: "Separate Backing",
  },
  adv_separate_backing_hint: {
    zh: "将底板层（通常是白色或背景色）作为独立颜色层输出，适用于需要单独处理底板的打印机或后处理流程。",
    en: "Outputs the backing layer as a separate color layer, useful for printers or post-processing workflows that handle the backing layer independently.",
  },
  adv_hue_protection: {
    zh: "色相保护",
    en: "Hue Protection",
  },
  adv_hue_protection_hint: {
    zh: "在色彩匹配时优先保护色相，减少色相漂移。适合色彩准确度要求高、颜色种类多的图像。",
    en: "Prioritizes hue preservation during color matching to reduce hue shift. Suitable for images requiring high color accuracy and a wide variety of colors.",
  },
  adv_unlock_quantize: {
    zh: "解锁量化颜色数",
    en: "Unlock quantize ceiling",
  },
  adv_unlock_quantize_hint: {
    zh: "解锁后最高可拉到 8192，会显著增加内存占用与处理耗时，仅适合极端场景。",
    en: "Unlocking raises the ceiling to 8192. This significantly increases memory and processing time; use only for extreme cases.",
  },
  adv_chroma_gate: {
    zh: "暗色彩度门槛",
    en: "Dark Chroma Gate",
  },
  adv_chroma_gate_hint: {
    zh: "仅对色度低于此值的暗色区域启用色相保护。设为 0 则对所有暗色生效，设为较高值则仅对非常暗的阴影生效。推荐值: 15。",
    en: "Applies hue protection only to dark areas whose chroma is below this threshold. Set to 0 to apply to all dark colors; higher values restrict it to very dark shadows. Recommended: 15.",
  },
  adv_precise_color_matching: {
    zh: "高精度颜色匹配（实验性功能）",
    en: "Precise Color Matching (Experimental)",
  },
  adv_precise_color_matching_hint: {
    zh: "将聚类中心约束在打印机可达颜色集合内，减少颜色偏移；性能可能略慢，仅在 LUT 颜色匹配模式生效。",
    en: "Constrains cluster centers to printer-achievable colors, reducing color shifts. May be slightly slower; only effective in LUT color matching mode.",
  },
  adv_hue_protection_disabled_hint: {
    zh: "高精度匹配开启时，色相保护已被接管，无需手动启用。",
    en: "Hue protection is automatically handled when high-precision matching is enabled; no need to enable manually.",
  },
  adv_auto_dynamic_range: {
    zh: "自动动态范围（实验性功能）",
    en: "Auto Dynamic Range (Experimental)",
  },
  adv_auto_dynamic_range_hint: {
    zh: "根据所选 LUT 或耗材档案的可达亮度范围，对原图 L* 进行压缩映射；高光与阴影使用软滚降以保留局部对比度，色度通道保持不变。",
    en: "Compresses the source image's L* into the luminance range achievable by the selected LUT or material profile, using soft roll-offs in highlights and shadows to preserve local contrast while leaving chroma channels untouched.",
  },
  adv_high_precision_3d_preview: {
    zh: "3D高精度颜色预览",
    en: "High-precision 3D colour preview",
  },
  adv_high_precision_3d_preview_hint: {
    zh: "开启后，3D 预览的颜色网格上限会提升到当前量化颜色数；可减少低频颜色被合并成灰色，但 GLB 生成和浏览器渲染会更慢。",
    en: "When enabled, the 3D preview colour mesh limit is raised to the current quantized colour count. This reduces low-frequency colours being merged into greys, but GLB generation and browser rendering may be slower.",
  },

  // ==================== Relief Settings ====================
  relief_enable: {
    zh: "启用浮雕",
    en: "Enable Relief",
  },
  relief_vector_unsupported: {
    zh: "矢量模式暂不支持浮雕",
    en: "Relief is not supported in Vector mode",
  },
  relief_max_height: {
    zh: "最大高度",
    en: "Max Height",
  },
  relief_max_height_hint: {
    zh: "浮雕模型最高点的高度（毫米）。值越大浮雕凸起越高，值越小浮雕越浅。",
    en: "The height of the tallest point of the relief model (in mm). Larger values produce taller relief, smaller values produce shallower relief.",
  },
  relief_auto_height_mode: {
    zh: "自动高度模式",
    en: "Auto Height Mode",
  },
  relief_darker_higher: {
    zh: "深色凸起",
    en: "Darker Higher",
  },
  relief_lighter_higher: {
    zh: "浅色凸起",
    en: "Lighter Higher",
  },
  relief_use_heightmap: {
    zh: "根据高度图",
    en: "Use Heightmap",
  },
  relief_heightmap_label: {
    zh: "高度图",
    en: "Heightmap",
  },
  relief_file_selected: {
    zh: "已选择",
    en: "Selected",
  },

  // ==================== Outline Settings ====================
  outline_enable: {
    zh: "启用外轮廓",
    en: "Enable Outline",
  },
  outline_width: {
    zh: "外轮廓厚度",
    en: "Outline Width",
  },
  outline_width_hint: {
    zh: "外描边线条的宽度（毫米）。值越大轮廓线越粗，值越小轮廓线越细。",
    en: "Width of the outline stroke (in mm). Larger values produce thicker lines, smaller values produce thinner lines.",
  },
  // TODO(vector-outline): canonical key names reserved by the acceptance
  // design decision matrix rows D5 / D6. Copy is intentionally a concise
  // placeholder; refine in a follow-up spec when D5 / D6 detection is wired
  // and we have real product copy. See
  // `progress/svg-vector-outline-acceptance-checkpoint.md` Open Question OQ-2.
  // 仅作占位文案；当 D5/D6 真正命中并需要正式提示时再单独立 spec 完善。
  outline_enable_unsupported_alpha_unavailable: {
    zh: "无法在透明通道不可用的素材上启用外轮廓",
    en: "Outline unavailable when image has no usable alpha channel",
  },
  outline_enable_unsupported_subscription_combo: {
    zh: "当前组合暂不支持外轮廓",
    en: "Outline temporarily unavailable for this configuration",
  },

  // ==================== Cloisonne Settings ====================
  cloisonne_enable: {
    zh: "启用掐丝珐琅",
    en: "Enable Cloisonné",
  },
  cloisonne_wire_width: {
    zh: "金属丝宽度",
    en: "Wire Width",
  },
  cloisonne_wire_width_hint: {
    zh: "掐丝珐琅金属丝的水平宽度（毫米）。值越大金属丝越粗，掐丝效果越明显。",
    en: "Horizontal width of the cloisonné wire (in mm). Larger values produce thicker wires with more pronounced cloisonné effect.",
  },
  cloisonne_wire_height: {
    zh: "金属丝高度",
    en: "Wire Height",
  },
  cloisonne_wire_height_hint: {
    zh: "掐丝珐琅金属丝的垂直高度（毫米）。值越大金属丝凸起越高，立体感越强。",
    en: "Vertical height of the cloisonné wire (in mm). Larger values produce taller wire protrusion with stronger three-dimensional appearance.",
  },
  cloisonne_wip: {
    zh: "此功能正在施工中，部分效果可能不完整",
    en: "This feature is under construction, some effects may be incomplete",
  },

  // ==================== Coating Settings ====================
  coating_enable: {
    zh: "启用透明镀层",
    en: "Enable Transparent Coating",
  },
  coating_height: {
    zh: "透明镀层高度",
    en: "Transparent Coating Height",
  },
  coating_height_hint: {
    zh: "透明镀层覆盖层的高度（毫米）。值越大镀层凸起越高，表面越光滑。",
    en: "Height of the transparent coating layer (in mm). Larger values produce taller coating protrusion and a smoother surface.",
  },

  // ==================== Keychain Loop Settings ====================
  loop_enable: {
    zh: "添加挂件环",
    en: "Add Keychain Loop",
  },
  loop_width: {
    zh: "环宽度",
    en: "Loop Width",
  },
  loop_width_hint: {
    zh: "挂件环的水平宽度（毫米）。值越大环越宽。",
    en: "Horizontal width of the keychain loop (in mm). Larger values produce a wider loop.",
  },
  loop_length: {
    zh: "环长度",
    en: "Loop Length",
  },
  loop_length_hint: {
    zh: "挂件环的垂直长度（毫米）。值越大环越长。",
    en: "Vertical length of the keychain loop (in mm). Larger values produce a longer loop.",
  },
  loop_hole_diameter: {
    zh: "环孔直径",
    en: "Loop Hole Diameter",
  },
  loop_hole_diameter_hint: {
    zh: "挂件环内孔的直径（毫米）。需确保钥匙扣或挂绳能穿过。",
    en: "Diameter of the inner hole (in mm). Must be large enough for a keychain or lanyard to pass through.",
  },
  loop_angle: {
    zh: "旋转角度",
    en: "Rotation Angle",
  },
  loop_angle_hint: {
    zh: "挂件环相对于模型的旋转角度（度）。0° 为竖直向上，正值顺时针旋转。",
    en: "Rotation angle of the loop relative to the model (in degrees). 0° is vertical upward; positive values rotate clockwise.",
  },
  loop_position_preset: {
    zh: "位置预设",
    en: "Position Preset",
  },
  loop_offset_x: {
    zh: "X 偏移",
    en: "X Offset",
  },
  loop_offset_x_hint: {
    zh: "挂件环中心相对于模型中心的水平偏移（毫米）。正值向右，负值向左。",
    en: "Horizontal offset of the loop center from the model center (in mm). Positive moves right, negative moves left.",
  },
  loop_offset_y: {
    zh: "Y 偏移",
    en: "Y Offset",
  },
  loop_offset_y_hint: {
    zh: "挂件环中心相对于模型中心的垂直偏移（毫米）。正值向上，负值向下。",
    en: "Vertical offset of the loop center from the model center (in mm). Positive moves up, negative moves down.",
  },
  loop_preset_top_center: {
    zh: "上中",
    en: "Top Center",
  },
  loop_preset_top_left: {
    zh: "左上",
    en: "Top Left",
  },
  loop_preset_top_right: {
    zh: "右上",
    en: "Top Right",
  },
  loop_preset_left_center: {
    zh: "左中",
    en: "Left Center",
  },
  loop_preset_right_center: {
    zh: "右中",
    en: "Right Center",
  },
  loop_preset_bottom_center: {
    zh: "下中",
    en: "Bottom Center",
  },

  // ==================== Action Bar ====================
  action_upload_hint: {
    zh: "请先上传图片并选择 LUT",
    en: "Please upload an image and select a LUT first",
  },
  action_upload_hint_material: {
    zh: "请先上传图片并选择耗材",
    en: "Please upload an image and select materials first",
  },
  action_batch_upload_hint: {
    zh: "请先添加图片并选择 LUT",
    en: "Please add images and select a LUT first",
  },
  action_batch_upload_hint_material: {
    zh: "请先添加图片并选择耗材",
    en: "Please add images and select materials first",
  },
  action_batch_upload_hint_native: {
    zh: "请先添加图片并选择品牌和数据库",
    en: "Please add images and select a brand and databases first",
  },
  action_preview: {
    zh: "预览",
    en: "Preview",
  },
  action_generate: {
    zh: "生成",
    en: "Generate",
  },
  action_color_card: {
    zh: "生成色卡",
    en: "Color Card",
  },
  action_color_card_loading: {
    zh: "色卡生成中…",
    en: "Generating Card…",
  },
  action_color_card_title: {
    zh: "验证色卡",
    en: "Validation Color Card",
  },
  action_color_card_desc: {
    zh: "从当前调色板生成可打印的色卡 3MF，用于在打印机上验证颜色准确性。",
    en: "Generate a printable colour swatch 3MF from the current palette to verify colour accuracy on your printer.",
  },
  action_batch_generate: {
    zh: "批量生成",
    en: "Batch Generate",
  },
  action_preview_alt: {
    zh: "预览结果",
    en: "Preview result",
  },
  action_view_layers: {
    zh: "查看分层",
    en: "View Layers",
  },
  action_layers_loading: {
    zh: "加载分层...",
    en: "Loading layers...",
  },
  loading_witty_1: {
    zh: "正在折叠高维空间...",
    en: "Folding higher dimensions...",
  },
  loading_witty_2: {
    zh: "正在为打印床预热赛博能量...",
    en: "Preheating cyber energy for the print bed...",
  },
  loading_witty_3: {
    zh: "正在提炼像素点中的灵魂...",
    en: "Extracting souls from pixels...",
  },
  loading_witty_4: {
    zh: "正在拼接彩色多边形...",
    en: "Splicing colorful polygons...",
  },
  loading_witty_5: {
    zh: "正在向打印机注入魔法...",
    en: "Injecting magic into the printer...",
  },
  loading_witty_6: {
    zh: "正在打磨 3MF 积木块...",
    en: "Polishing 3MF building blocks...",
  },
  loading_witty_7: {
    zh: "正在从异世界召唤材质...",
    en: "Summoning textures from another world...",
  },
  loading_witty_8: {
    zh: "正在计算光子跳跃轨道...",
    en: "Calculating photon jump trajectories...",
  },
  loading_witty_9: {
    zh: "不要走开，马上渲染完毕...",
    en: "Hold on, rendering almost complete...",
  },
  loading_witty_10: {
    zh: "请给您的喷嘴一点准备时间...",
    en: "Please give your nozzle some time to prepare...",
  },
  loading_witty_11: {
    zh: "正在校准多发混合挤出机...",
    en: "Calibrating multi-color mixing extruder...",
  },
  loading_witty_12: {
    zh: "正在清理虚拟构建底板...",
    en: "Cleaning virtual build plate...",
  },
  loading_witty_13: {
    zh: "正在熔化高精度的数字耗材...",
    en: "Melting high-precision digital filament...",
  },
  loading_witty_14: {
    zh: "正在挤出完美的底层裙边...",
    en: "Extruding the perfect base skirt...",
  },
  loading_witty_15: {
    zh: "正在规划 G 代码的最优路径...",
    en: "Planning optimal G-code paths...",
  },
  loading_witty_16: {
    zh: "正在调教步进电机的脾气...",
    en: "Tuning the temper of stepper motors...",
  },
  loading_witty_17: {
    zh: "正在精心填充网格内部...",
    en: "Carefully infilling the mesh interior...",
  },
  loading_witty_18: {
    zh: "预热虚拟喷头至 210°C 中...",
    en: "Preheating virtual nozzle to 210°C...",
  },
  loading_witty_19: {
    zh: "正在生成仿生有机树状支撑...",
    en: "Generating bionic organic tree supports...",
  },
  loading_witty_20: {
    zh: "正在抹平第一层讨厌的大象腿...",
    en: "Smoothing the annoying first layer elephant foot...",
  },
  loading_witty_21: {
    zh: "超级风扇启动，冷却悬垂区域...",
    en: "Superfan activated, cooling overhangs...",
  },
  loading_witty_22: {
    zh: "正在计算桥接的完美抛物线...",
    en: "Calculating the perfect parabola for bridging...",
  },
  loading_witty_23: {
    zh: "正在对层叠颜色进行魔法混合...",
    en: "Magically blending stacked layers of colors...",
  },
  loading_witty_24: {
    zh: "正在宇宙中寻找丢失的 Z 轴原点...",
    en: "Searching the universe for the lost Z-axis origin...",
  },
  loading_witty_25: {
    zh: "正在安抚打滑的挤出机齿轮...",
    en: "Pacifying slipping extruder gears...",
  },
  loading_witty_26: {
    zh: "为模型注入强防翘边附着力...",
    en: "Injecting anti-warping adhesion into the model...",
  },
  loading_witty_27: {
    zh: "正在用微波清理喷嘴上的拉丝...",
    en: "Microwaving stringing residue off the nozzle...",
  },
  loading_witty_28: {
    zh: "正在将您的灵感切片成一层层...",
    en: "Slicing your inspiration layer by layer...",
  },
  loading_witty_29: {
    zh: "为调色盘补充一点赛博朋克墨水...",
    en: "Refilling cyberpunk ink for the palette...",
  },
  loading_witty_30: {
    zh: "正在进行一百万次色彩碰撞测试...",
    en: "Conducting an intense color collision test...",
  },
  loading_witty_31: {
    zh: "正在把二维像素用力吹成三维...",
    en: "Blowing 2D pixels vigorously into 3D...",
  },
  loading_witty_32: {
    zh: "构建坚不可摧的 3D 底层网格中...",
    en: "Building indestructible 3D base grids...",
  },
  loading_witty_33: {
    zh: "熨平顶层，让它像镜面一样反光...",
    en: "Ironing top layers until they shine like mirrors...",
  },
  loading_witty_34: {
    zh: "正在从虚空深渊中召唤支撑材料...",
    en: "Summoning support structures from the void abyss...",
  },
  loading_witty_35: {
    zh: "正在解构庞大的彩色三维点云矩阵...",
    en: "Deconstructing massive colorful 3D matrices...",
  },
  loading_witty_36: {
    zh: "正在为立体模型注入引力波形...",
    en: "Injecting gravitational waveforms into 3D models...",
  },
  loading_witty_37: {
    zh: "调色中...不，是在重新发明颜色...",
    en: "Calibrating colors... no, reinventing colors...",
  },
  loading_witty_38: {
    zh: "正在为您一砖一瓦搭建浮雕世界...",
    en: "Building a relief world for you, brick by brick...",
  },
  loading_witty_39: {
    zh: "正在拿针线缝补模型的破损多边形...",
    en: "Darning the broken polygons of your model...",
  },
  loading_witty_40: {
    zh: "Lumina 工作室正在为您打印一个好心情...",
    en: "Lumina Studio is printing a good mood for you...",
  },
  action_layers_title: {
    zh: "分层预览",
    en: "Layer Preview",
  },
  action_layer_nth: {
    zh: "第",
    en: "Layer ",
  },
  action_layer_unit: {
    zh: "层",
    en: "",
  },
  action_layer_prev: {
    zh: "上一层",
    en: "Prev",
  },
  action_layer_next: {
    zh: "下一层",
    en: "Next",
  },

  // ==================== Bed Size Selector ====================
  bed_size_label: {
    zh: "热床尺寸",
    en: "Bed Size",
  },
  bed_size_loading: {
    zh: "加载中...",
    en: "Loading...",
  },
  bed_size_placeholder: {
    zh: "选择热床尺寸...",
    en: "Select bed size...",
  },

  // ==================== Palette Panel ====================
  palette_no_data: {
    zh: "暂无调色板数据，请先完成预览",
    en: "No palette data. Please generate a preview first.",
  },
  palette_quantized: {
    zh: "量化色",
    en: "Quantized",
  },
  palette_matched: {
    zh: "匹配色",
    en: "Matched",
  },
  palette_replaced_label: {
    zh: "替换色",
    en: "Replaced",
  },
  palette_undo: {
    zh: "撤销",
    en: "Undo",
  },
  palette_clear_remaps: {
    zh: "清空替换",
    en: "Clear Remaps",
  },
  palette_group_history: {
    zh: "历史",
    en: "History",
  },
  palette_group_mode: {
    zh: "选择模式",
    en: "Mode",
  },
  palette_group_free: {
    zh: "自由色",
    en: "Free Color",
  },
  palette_group_recipe: {
    zh: "配方",
    en: "Recipe",
  },
  palette_list_label: {
    zh: "调色板颜色列表",
    en: "Palette color list",
  },

  // ==================== LUT Color Grid ====================
  lut_grid_loading: {
    zh: "加载 LUT 颜色中...",
    en: "Loading LUT colors...",
  },
  lut_grid_select_lut: {
    zh: "请先选择 LUT 以加载可用颜色",
    en: "Select a LUT to load available colors",
  },

  // ==================== Material Color Picker (material-archive mode) ====================
  material_picker_title: {
    zh: "耗材可达色",
    en: "Achievable colors",
  },
  material_picker_hint: {
    zh: "输入或选取目标颜色，系统会根据当前耗材求解出最接近的 20 个可达色。",
    en: "Pick a target color — the solver returns the 20 closest achievable colors for the current materials.",
  },
  material_picker_target_label: {
    zh: "目标颜色",
    en: "Target color",
  },
  material_picker_target_placeholder: {
    zh: "#RRGGBB",
    en: "#RRGGBB",
  },
  material_picker_submit: {
    zh: "生成建议",
    en: "Suggest colors",
  },
  material_picker_loading: {
    zh: "正在为目标色求解可达色...",
    en: "Solving achievable colors for the target...",
  },
  material_picker_empty: {
    zh: "输入目标颜色后生成可达色建议。",
    en: "Enter a target color to get achievable suggestions.",
  },
  material_picker_error: {
    zh: "求解失败：{message}",
    en: "Failed: {message}",
  },
  material_picker_no_material: {
    zh: "请先在「耗材档案」下选择至少一个耗材。",
    en: 'Select at least one material under "Material Archive" first.',
  },
  material_picker_suggestion_tooltip: {
    zh: "{hex} · ΔE={delta} · 配方 {recipe}",
    en: "{hex} · ΔE={delta} · recipe {recipe}",
  },
  material_picker_source_cache: {
    zh: "缓存命中（毫秒级返回）",
    en: "Cache hit (millisecond response)",
  },
  material_picker_source_runtime: {
    zh: "运行时命中（适合大耗材组合）",
    en: "Runtime hit (large-palette solve)",
  },
  material_picker_source_mitm: {
    zh: "MITM 实时求解（构建持久化缓存可显著加速）",
    en: "MITM live solve (build a persisted cache to accelerate)",
  },
  material_picker_result_count: {
    zh: "共 {count} 个可达色建议",
    en: "{count} achievable colors",
  },
  material_picker_delta_e_label: {
    zh: "ΔE{value}",
    en: "ΔE{value}",
  },

  // ==================== Gradient groups panel (banding detection) ====================
  gradient_groups_title: {
    zh: "渐变分组（海带纹）",
    en: "Gradient groups (banding)",
  },
  gradient_groups_hint: {
    zh: "发现 {count} 条平滑渐变被切成多个耗材色。点击「选中整组」可一次性选中组内所有颜色，再配合上方的拾色器换成同一个目标色。",
    en: "Detected {count} smooth gradients split across multiple material colors. Click Select all to multi-select the whole group, then use the picker above to replace them with a single target color.",
  },
  gradient_groups_loading: {
    zh: "正在读取渐变分组...",
    en: "Loading gradient groups...",
  },
  gradient_groups_empty: {
    zh: "未检测到海带纹渐变。",
    en: "No banding gradients detected.",
  },
  gradient_groups_error: {
    zh: "读取失败：{message}",
    en: "Failed: {message}",
  },
  gradient_groups_select_group: {
    zh: "选中整组",
    en: "Select all",
  },
  gradient_groups_select_region: {
    zh: "选中区域",
    en: "Select region",
  },
  gradient_groups_view_highlight: {
    zh: "查看高亮图",
    en: "View highlight",
  },
  gradient_groups_view_highlight_group_title: {
    zh: "第 {index} 组 高亮预览",
    en: "Group #{index} highlight preview",
  },
  gradient_groups_view_highlight_region_title: {
    zh: "第 {group} 组 · 区域 {region} 高亮预览",
    en: "Group #{group} · region #{region} highlight preview",
  },
  gradient_groups_view_highlight_loading: {
    zh: "生成高亮图中…",
    en: "Generating highlight…",
  },
  gradient_groups_view_highlight_error: {
    zh: "生成高亮图失败：{message}",
    en: "Failed to generate highlight: {message}",
  },
  gradient_groups_view_highlight_close: {
    zh: "关闭",
    en: "Close",
  },
  gradient_groups_expand_regions: {
    zh: "展开区域（{count}）",
    en: "Expand regions ({count})",
  },
  gradient_groups_collapse_regions: {
    zh: "收起区域",
    en: "Collapse regions",
  },
  gradient_groups_materials_count: {
    zh: "{count} 种颜色",
    en: "{count} colors",
  },
  gradient_groups_pixels_count: {
    zh: "{count} 像素",
    en: "{count} px",
  },
  gradient_groups_region_label: {
    zh: "区域 {index}",
    en: "Region {index}",
  },
  gradient_groups_auto_banner: {
    zh: "已按设置自动替换为代表色，可在高级设置关闭。",
    en: "Auto-replaced with representative colors (toggle off in Advanced Settings).",
  },
  gradient_groups_apply_now: {
    zh: "一键去除海带纹",
    en: "Flatten all gradients",
  },
  gradient_groups_flatten_group: {
    zh: "去海带纹",
    en: "Flatten",
  },
  gradient_groups_flatten_region: {
    zh: "去海带纹",
    en: "Flatten",
  },
  gradient_groups_merge_flatten: {
    zh: "合并去海带纹 ({count})",
    en: "Merge flatten ({count})",
  },
  gradient_groups_merge_checkbox_label: {
    zh: "勾选区域 {index} 加入合并",
    en: "Select region {index} for merge",
  },
  gradient_groups_requantize: {
    zh: "二次量化 ({count})",
    en: "Re-quantize ({count})",
  },
  // Short label for the per-region requantize button that lives on every
  // region row. Keeps the chip narrow so it does not crowd the existing
  // "Select / Flatten / Highlight" trio.
  // 单 region 行上的"二次量化"按钮文案；尽量短以免挤占同行其它按钮。
  gradient_groups_requantize_region: {
    zh: "二次量化",
    en: "Re-quantize",
  },
  // External batch button shown at the panel header so the user never has
  // to scroll back to find the group their selection belongs to.
  // 外置批量按钮文案（面板顶部）；避免用户为了找到所在分组而滚动列表。
  gradient_groups_batch_requantize: {
    zh: "批量二次量化 ({count})",
    en: "Batch re-quantize ({count})",
  },
  gradient_groups_batch_requantize_empty: {
    zh: "请先勾选至少一个区域",
    en: "Select at least one region first",
  },
  // Shown in the dialog description when the explicit target list spans
  // multiple gradient groups (the batch button can do this).
  // 批量调用跨多 group 时，dialog 描述里用这个字符串替换 {group}。
  gradient_groups_requantize_dialog_multi_group: {
    zh: "多组",
    en: "multiple",
  },
  gradient_groups_requantize_dialog_title: {
    zh: "区域二次量化",
    en: "Region re-quantization",
  },
  gradient_groups_requantize_dialog_description: {
    zh: "为分组 {group} 中勾选的 {count} 个区域分别重新量化，随后用材料求解器重新匹配。保留低频渐变，消除条纹。",
    en: "Re-quantize {count} selected region(s) in group {group} with a dedicated palette each, then re-match via the material solver. Keeps low-frequency gradients while collapsing kelp banding.",
  },
  gradient_groups_requantize_dialog_slider_label: {
    zh: "每个区域的量化色数",
    en: "Per-region quantize colour count",
  },
  gradient_groups_requantize_dialog_hint: {
    zh: "范围 {min}-{max}；值越大保留的色阶越多，越小越接近直接平坦化。",
    en: "Range {min}-{max}; larger keeps more gradient detail, smaller approximates flatten.",
  },
  gradient_groups_requantize_dialog_cancel: {
    zh: "取消",
    en: "Cancel",
  },
  gradient_groups_requantize_dialog_submit: {
    zh: "开始量化",
    en: "Re-quantize",
  },
  gradient_groups_requantize_dialog_submitting: {
    zh: "处理中...",
    en: "Working...",
  },
  lut_grid_total_colors: {
    zh: "共 {total} 色，显示 {visible} 色",
    en: "{total} colors, showing {visible}",
  },
  lut_grid_selected: {
    zh: "已选中",
    en: "Selected",
  },
  lut_grid_search_placeholder_short: {
    zh: "搜索 HEX / RGB 颜色...",
    en: "Search HEX / RGB...",
  },
  lut_grid_hue_all_short: {
    zh: "全部",
    en: "All",
  },
  lut_grid_hue_fav_short: {
    zh: "收藏",
    en: "Favorites",
  },
  lut_grid_hue_red_short: {
    zh: "红",
    en: "Red",
  },
  lut_grid_hue_orange_short: {
    zh: "橙",
    en: "Orange",
  },
  lut_grid_hue_yellow_short: {
    zh: "黄",
    en: "Yellow",
  },
  lut_grid_hue_green_short: {
    zh: "绿",
    en: "Green",
  },
  lut_grid_hue_cyan_short: {
    zh: "青",
    en: "Cyan",
  },
  lut_grid_hue_blue_short: {
    zh: "蓝",
    en: "Blue",
  },
  lut_grid_hue_purple_short: {
    zh: "紫",
    en: "Purple",
  },
  lut_grid_hue_neutral_short: {
    zh: "中性",
    en: "Neutral",
  },
  lut_grid_recommendations: {
    zh: "推荐替换色",
    en: "Recommended Replacements",
  },
  lut_grid_used_in_image: {
    zh: "图中使用",
    en: "Used in image",
  },
  lut_grid_other_available: {
    zh: "其他可用",
    en: "Other available",
  },
  lut_grid_all_available: {
    zh: "全部可用",
    en: "All available",
  },
  lut_grid_no_match: {
    zh: "无匹配颜色",
    en: "No matching colors",
  },
  lut_grid_color_label: {
    zh: "颜色 {hex}",
    en: "Color {hex}",
  },
  lut_grid_color_fav: {
    zh: "已收藏",
    en: "Favorited",
  },
  lut_grid_dblclick_fav: {
    zh: "双击收藏",
    en: "Double-click to favorite",
  },
  lut_grid_dblclick_unfav: {
    zh: "双击取消收藏",
    en: "Double-click to unfavorite",
  },
  lut_grid_mode_swatch: {
    zh: "色块",
    en: "Swatch",
  },
  lut_grid_mode_card: {
    zh: "色卡",
    en: "Card",
  },
  lut_grid_card_a: {
    zh: "色卡 A",
    en: "Card A",
  },
  lut_grid_card_b: {
    zh: "色卡 B",
    en: "Card B",
  },
  lut_grid_card_label: {
    zh: "色卡 {card}",
    en: "Card {card}",
  },

  // ==================== Replace Confirmation ====================
  replace_confirm_btn: {
    zh: "确认替换",
    en: "Confirm Replace",
  },
  replace_cancel_btn: {
    zh: "取消",
    en: "Cancel",
  },
  replace_preview_label: {
    zh: "替换预览",
    en: "Replace Preview",
  },

  // ==================== Image Upload ====================
  upload_drag_hint: {
    zh: "拖拽图片或点击上传",
    en: "Drag & drop image or click to upload",
  },

  // ==================== Unified Uploader ====================
  upload_unified_hint: {
    zh: "拖拽图片或点击上传（支持多选）",
    en: "Drag & drop or click to upload (multi-select)",
  },
  upload_tap_to_change: {
    zh: "点击更换或追加",
    en: "Change or add",
  },
  upload_replace_current: {
    zh: "更换当前图片",
    en: "Replace current image",
  },
  upload_unified_aria: {
    zh: "拖拽图片或点击上传文件",
    en: "Drag images or click to upload files",
  },
  upload_add_more: {
    zh: "添加更多图片",
    en: "Add more images",
  },
  upload_file_count: {
    zh: "已选 {count} 个文件",
    en: "{count} files selected",
  },
  upload_file_list_label: {
    zh: "已选文件列表",
    en: "Selected files list",
  },
  upload_delete_file: {
    zh: "删除 {name}",
    en: "Delete {name}",
  },
  upload_file_list_truncated: {
    zh: "还有 {count} 个文件已加入批量队列，未在这里展开显示。",
    en: "{count} more files are in the batch queue and are not expanded here.",
  },

  // ==================== Zoomable Image ====================
  zoom_reset: {
    zh: "重置缩放",
    en: "Reset Zoom",
  },

  // ==================== Batch Result Summary ====================
  batch_success: {
    zh: "成功",
    en: "Success",
  },
  batch_total: {
    zh: "总计",
    en: "Total",
  },
  batch_failed: {
    zh: "失败",
    en: "Failed",
  },
  batch_download_zip: {
    zh: "下载 ZIP",
    en: "Download ZIP",
  },
  batch_download_zip_aria: {
    zh: "下载 ZIP 文件",
    en: "Download ZIP file",
  },
  batch_failed_files: {
    zh: "失败文件：",
    en: "Failed files:",
  },
  batch_failed_list_label: {
    zh: "失败文件列表",
    en: "Failed files list",
  },
  "batch.itemError.conversionFailed": {
    zh: "这个文件无法转换。请重新上传该文件，或查看服务端日志了解详情。",
    en: "This file could not be converted. Re-upload it or check the server log for details.",
  },
  "batch.itemError.timeout": {
    zh: "这个文件转换超时。请减少模型复杂度后重试，或单独转换该文件。",
    en: "This file took too long to convert. Reduce the model complexity and try again, or convert this file on its own.",
  },
  // Merged batch 3MF download + plate-overflow warning (batch-mode-merged-3mf).
  // 批量合并 3MF 下载与超出热床范围的警告文案。
  "batch.download.mergedThreemf": {
    zh: "下载批量 3MF",
    en: "Download batch 3MF",
  },
  "batch.warnings.plateOverflow.title": {
    zh: "部分模型超出热床范围",
    en: "Some models extend beyond the print bed",
  },
  "batch.warnings.plateOverflow.body": {
    zh: "部分模型可能超出热床范围，请在切片软件中调整。",
    en: "Some models may extend beyond the print bed; please adjust them in the slicer.",
  },
  "batch.warnings.previewLimited.body": {
    zh: "批量 3MF 已包含全部成功模型；3D 预览会按当前热床尺寸自动显示可容纳的前若干个模型。",
    en: "The batch 3MF includes every successful model; the 3D preview automatically shows the first models that fit on the current print bed.",
  },

  // ==================== Slicer Selector ====================
  slicer_open_in: {
    zh: "在 {name} 中打开",
    en: "Open in {name}",
  },
  slicer_generate_open_in: {
    zh: "生成并在 {name} 中打开",
    en: "Generate & open in {name}",
  },
  slicer_download_3mf: {
    zh: "下载 3MF",
    en: "Download 3MF",
  },
  slicer_generate_download: {
    zh: "生成并下载",
    en: "Generate & Download",
  },
  slicer_download_failed: {
    zh: "下载文件暂时无法读取，请重新生成后再试。",
    en: "The download file could not be read. Regenerate it and try again.",
  },
  slicer_detecting: {
    zh: "正在检测切片软件...",
    en: "Detecting slicers...",
  },
  slicer_not_detected: {
    zh: "未检测到切片软件",
    en: "No slicers detected",
  },
  slicer_toggle_list: {
    zh: "切换切片软件列表",
    en: "Toggle slicer list",
  },
  slicer_preferred_mismatch: {
    zh: "当前导出格式为 {expected}，但操作栏启动目标是 {actual}",
    en: "Current export format targets {expected}, but the action bar is set to {actual}",
  },
  slicer_preferred_missing: {
    zh: "当前导出格式为 {name}，但本机未检测到对应切片软件",
    en: "Current export format targets {name}, but the matching slicer is not detected on this device",
  },

  // ==================== Crop Modal ====================
  crop_modal_title: {
    zh: "裁剪图片",
    en: "Crop Image",
  },
  crop_modal_close: {
    zh: "关闭",
    en: "Close",
  },
  crop_modal_original: {
    zh: "原图",
    en: "Original",
  },
  crop_modal_selection: {
    zh: "选区",
    en: "Selection",
  },
  crop_modal_free: {
    zh: "自由",
    en: "Free",
  },
  crop_modal_use_original: {
    zh: "使用原图",
    en: "Use Original",
  },
  crop_modal_confirm: {
    zh: "确认裁剪",
    en: "Confirm Crop",
  },

  // ==================== Five Color Query Panel ====================
  five_color_lut_label: {
    zh: "LUT 选择",
    en: "LUT Selection",
  },
  five_color_title: {
    zh: "五色配方查询",
    en: "Five-Color Recipe Query",
  },
  five_color_desc: {
    zh: "从基础色中选出配方颜色并查询叠层后的结果色，适合快速验证色片配方。",
    en: "Pick base colors and query the blended result to validate layered color recipes quickly.",
  },
  five_color_palette: {
    zh: "基础色板",
    en: "Base Palette",
  },
  five_color_match_title: {
    zh: "按色值查询",
    en: "Match by color value",
  },
  five_color_match_desc: {
    zh: "输入目标 Hex 色值，从当前色卡中按标准最近邻匹配配方。",
    en: "Enter a target Hex value and match the nearest recipe from the current LUT card.",
  },
  five_color_match_input_label: {
    zh: "目标色值",
    en: "Target Hex",
  },
  five_color_match_input_placeholder: {
    zh: "#RRGGBB",
    en: "#RRGGBB",
  },
  five_color_match_button: {
    zh: "匹配配方",
    en: "Match recipe",
  },
  five_color_match_target: {
    zh: "目标色",
    en: "Target",
  },
  five_color_match_matched: {
    zh: "匹配色",
    en: "Matched",
  },
  five_color_match_rgb_value: {
    zh: "RGB {value}",
    en: "RGB {value}",
  },
  five_color_match_delta: {
    zh: "ΔE",
    en: "Delta E",
  },
  five_color_match_position: {
    zh: "色卡位置",
    en: "Card position",
  },
  five_color_match_card: {
    zh: "色卡 {card}",
    en: "Card {card}",
  },
  five_color_match_row: {
    zh: "第 {row} 行",
    en: "Row {row}",
  },
  five_color_match_col: {
    zh: "第 {col} 列",
    en: "Column {col}",
  },
  five_color_match_recipe: {
    zh: "匹配配方",
    en: "Matched recipe",
  },
  five_color_match_neighborhood: {
    zh: "虚拟小色卡",
    en: "Virtual card",
  },
  five_color_match_empty_cell: {
    zh: "空位",
    en: "Empty cell",
  },
  five_color_match_recipe_unavailable: {
    zh: "已找到最接近的色卡颜色，但该行无法反推出配方。",
    en: "The nearest LUT color was found, but this row cannot be converted into a recipe.",
  },
  five_color_match_recipe_unavailable_title: {
    zh: "无法生成配方",
    en: "Recipe unavailable",
  },
  five_color_error_select_lut_first: {
    zh: "请先选择 LUT",
    en: "Select a LUT first",
  },
  five_color_error_load_base_colors_failed: {
    zh: "基础色板加载失败",
    en: "Base palette loading failed",
  },
  five_color_error_match_failed: {
    zh: "按色值查询失败",
    en: "Color value lookup failed",
  },
  five_color_error_invalid_hex: {
    zh: "请输入 #RRGGBB 格式的色值",
    en: "Enter a color value in #RRGGBB format",
  },
  five_color_error_query_failed: {
    zh: "五色配方查询失败",
    en: "Five-color recipe lookup failed",
  },
  five_color_error_generate_swatch_failed: {
    zh: "色卡生成失败",
    en: "Swatch generation failed",
  },
  five_color_error_download_swatch_failed: {
    zh: "色卡下载失败",
    en: "Swatch download failed",
  },
  five_color_error_generic: {
    zh: "五色操作失败",
    en: "Five-color operation failed",
  },
  five_color_actions: {
    zh: "操作",
    en: "Actions",
  },
  five_color_lut_placeholder: {
    zh: "请选择 LUT",
    en: "Select LUT",
  },
  five_color_clear: {
    zh: "清除",
    en: "Clear",
  },
  five_color_undo: {
    zh: "撤销",
    en: "Undo",
  },
  five_color_add_to_list: {
    zh: "加入配方收藏",
    en: "Add to collection",
  },
  five_color_already_in_list: {
    zh: "已在收藏",
    en: "Already in collection",
  },
  five_color_collection_title: {
    zh: "配方收藏",
    en: "Recipe collection",
  },
  five_color_collection_count: {
    zh: "共 {count} 条",
    en: "{count} item(s)",
  },
  five_color_collection_empty: {
    zh: "尚未收藏任何配方",
    en: "No recipes collected yet",
  },
  five_color_collection_clear: {
    zh: "清空收藏",
    en: "Clear collection",
  },
  five_color_remove_recipe: {
    zh: "移除此配方",
    en: "Remove this recipe",
  },
  five_color_swatch_block_size: {
    zh: "色块尺寸 (mm)",
    en: "Block size (mm)",
  },
  five_color_swatch_gap: {
    zh: "色块间距 (mm)",
    en: "Gap (mm)",
  },
  five_color_swatch_cols: {
    zh: "每行列数",
    en: "Columns per row",
  },
  five_color_swatch_structure: {
    zh: "色卡结构",
    en: "Swatch structure",
  },
  five_color_swatch_single_sided: {
    zh: "单面",
    en: "Single-sided",
  },
  five_color_swatch_double_sided: {
    zh: "双面",
    en: "Double-sided",
  },
  five_color_swatch_legend_alt: {
    zh: "色卡预览图",
    en: "Swatch preview",
  },
  five_color_generate_swatch: {
    zh: "生成色卡",
    en: "Generate swatch",
  },
  five_color_generating_swatch: {
    zh: "生成中...",
    en: "Generating...",
  },
  five_color_download_swatch: {
    zh: "下载色卡",
    en: "Download swatch",
  },
  five_color_reverse: {
    zh: "反序",
    en: "Reverse",
  },
  five_color_query: {
    zh: "查询",
    en: "Query",
  },
  five_color_query_loading: {
    zh: "查询中...",
    en: "Querying...",
  },
  five_color_close_error: {
    zh: "关闭错误",
    en: "Close error",
  },
  five_color_result_hex: {
    zh: "Hex",
    en: "Hex",
  },
  five_color_result_rgb: {
    zh: "RGB",
    en: "RGB",
  },
  five_color_result_row: {
    zh: "行号",
    en: "Row",
  },
  five_color_result_lut_row_index: {
    zh: "LUT 行索引（0 起）",
    en: "LUT row index (0-based)",
  },
  five_color_result_source: {
    zh: "来源",
    en: "Source",
  },
  five_color_result_color: {
    zh: "结果颜色 {hex}",
    en: "Result color {hex}",
  },
  five_color_result_panel: {
    zh: "查询结果",
    en: "Query Result",
  },
  five_color_not_found: {
    zh: "未找到匹配",
    en: "No match found",
  },
  five_color_not_found_message: {
    zh: "当前颜色顺序没有对应的色卡记录。",
    en: "The current color order does not match a LUT record.",
  },
  five_color_selection_progress: {
    zh: "已选择 {count}/{total} 种颜色，请继续完成配方。",
    en: "{count}/{total} colors selected. Keep building the recipe.",
  },
  five_color_selected: {
    zh: "已选颜色 {n}: {name}",
    en: "Selected color {n}: {name}",
  },
  five_color_slot_empty: {
    zh: "颜色槽 {n}: 空",
    en: "Color slot {n}: empty",
  },
  five_color_select_color: {
    zh: "选择颜色 {name} ({hex})",
    en: "Select color {name} ({hex})",
  },
  five_color_no_base_colors: {
    zh: "未加载到基础颜色",
    en: "No base colors loaded",
  },
  five_color_select_lut_first: {
    zh: "请先选择 LUT 以加载基础颜色",
    en: "Select a LUT to load base colors",
  },

  // ==================== Widget Error ====================
  widget_error: {
    zh: "组件出错",
    en: "Widget error",
  },
  widget_retry: {
    zh: "重试",
    en: "Retry",
  },
  widget_expand: {
    zh: "展开",
    en: "Expand",
  },
  widget_collapse: {
    zh: "折叠",
    en: "Collapse",
  },

  // ==================== WikiTooltip ====================
  wiki_tooltip_link: {
    zh: "查看 Wiki 详情 ↗",
    en: "View Wiki Details ↗",
  },

  // ==================== Vectorizer Panel ====================
  "vec.title": {
    zh: "图像转矢量",
    en: "Image Vectorizer",
  },
  "vec.upload_hint": {
    zh: "拖放或点击上传图片进行矢量化",
    en: "Drag & drop or click to upload an image for vectorization",
  },
  "vec.basic_params": {
    zh: "基础参数",
    en: "Basic Parameters",
  },
  "vec.advanced_params": {
    zh: "高级参数",
    en: "Advanced Parameters",
  },
  "vec.output_enhance": {
    zh: "输出增强",
    en: "Output Enhancement",
  },

  // Core params
  "vec.num_colors": {
    zh: "颜色数量",
    en: "Number of Colors",
  },
  "vec.num_colors_auto": {
    zh: "自动",
    en: "Auto",
  },
  "vec.num_colors_manual": {
    zh: "手动",
    en: "Manual",
  },
  "vec.detail_level": {
    zh: "细节等级",
    en: "Detail Level",
  },
  "vec.detail_level_enable": {
    zh: "启用统一细节控制",
    en: "Enable Unified Detail Control",
  },
  "vec.detail_level_on": {
    zh: "启用",
    en: "On",
  },
  "vec.detail_level_off": {
    zh: "禁用",
    en: "Off",
  },
  "vec.smoothness": {
    zh: "平滑度",
    en: "Smoothness",
  },

  // Output enhancement
  "vec.svg_enable_stroke": {
    zh: "启用描边",
    en: "Enable Stroke",
  },
  "vec.svg_stroke_width": {
    zh: "描边宽度",
    en: "Stroke Width",
  },
  "vec.thin_line_max_radius": {
    zh: "薄线检测半径",
    en: "Thin Line Max Radius",
  },
  "vec.enable_coverage_fix": {
    zh: "启用覆盖修复",
    en: "Enable Coverage Fix",
  },
  "vec.min_coverage_ratio": {
    zh: "最小覆盖率",
    en: "Min Coverage Ratio",
  },

  // Advanced - Preprocessing
  "vec.adv_preprocess": {
    zh: "预处理",
    en: "Preprocessing",
  },
  "vec.smoothing_spatial": {
    zh: "空间平滑半径",
    en: "Spatial Smoothing",
  },
  "vec.smoothing_color": {
    zh: "颜色平滑半径",
    en: "Color Smoothing",
  },
  "vec.max_working_pixels": {
    zh: "最大工作像素数",
    en: "Max Working Pixels",
  },

  // Advanced - Segmentation
  "vec.adv_segmentation": {
    zh: "超像素分割",
    en: "Superpixel Segmentation",
  },
  "vec.slic_region_size": {
    zh: "超像素区域大小",
    en: "SLIC Region Size",
  },
  "vec.edge_sensitivity": {
    zh: "边缘敏感度",
    en: "Edge Sensitivity",
  },
  "vec.refine_passes": {
    zh: "边界细化次数",
    en: "Refine Passes",
  },
  "vec.enable_antialias_detect": {
    zh: "启用抗锯齿检测",
    en: "Antialiasing Detection",
  },
  "vec.aa_tolerance": {
    zh: "抗锯齿容差",
    en: "AA Tolerance",
  },

  // Advanced - Curve fitting
  "vec.adv_curve_fitting": {
    zh: "曲线拟合",
    en: "Curve Fitting",
  },
  "vec.curve_fit_error": {
    zh: "曲线拟合误差",
    en: "Curve Fit Error",
  },
  "vec.contour_simplify": {
    zh: "轮廓简化强度",
    en: "Contour Simplification",
  },
  "vec.merge_segment_tolerance": {
    zh: "线段合并容差",
    en: "Merge Segment Tolerance",
  },

  // Advanced - Filtering
  "vec.adv_filtering": {
    zh: "区域过滤",
    en: "Region Filtering",
  },
  "vec.min_region_area": {
    zh: "最小区域面积",
    en: "Min Region Area",
  },
  "vec.max_merge_color_dist": {
    zh: "最大合并色差",
    en: "Max Merge Color Dist",
  },
  "vec.min_contour_area": {
    zh: "最小轮廓面积",
    en: "Min Contour Area",
  },
  "vec.min_hole_area": {
    zh: "最小孔洞面积",
    en: "Min Hole Area",
  },
  "vec.submit": {
    zh: "开始矢量化",
    en: "Start Vectorization",
  },
  "vec.processing": {
    zh: "正在矢量化...",
    en: "Vectorizing...",
  },
  "vec.result_title": {
    zh: "矢量化结果",
    en: "Vectorization Result",
  },
  "vec.original": {
    zh: "原始图片",
    en: "Original",
  },
  "vec.svg_preview": {
    zh: "SVG 预览",
    en: "SVG Preview",
  },
  "vec.shapes": {
    zh: "形状数",
    en: "Shapes",
  },
  "vec.colors": {
    zh: "颜色数",
    en: "Colors",
  },
  "vec.download_svg": {
    zh: "下载 SVG",
    en: "Download SVG",
  },
  "vec.send_to_converter": {
    zh: "发送到图像转换",
    en: "Send to Image Converter",
  },
  "vec.resource_action_failed": {
    zh: "SVG 文件暂时无法读取，请重新生成后再试。",
    en: "The SVG file could not be read. Regenerate it and try again.",
  },
  "vec.error": {
    zh: "矢量化失败",
    en: "Vectorization Failed",
  },
  "vec.no_image": {
    zh: "请先上传图片",
    en: "Please upload an image first",
  },

  // ===== Vectorizer Parameter Hints =====
  "vec.hint_num_colors": {
    zh: "自动模式会检测图像的最优颜色数量。切换到手动模式可指定固定值（2-256）。",
    en: "Auto mode detects the optimal color count. Switch to Manual to specify a fixed value (2-256).",
  },
  "vec.hint_smoothness": {
    zh: "整体轮廓平滑度。0 = 保留所有细节；1 = 最大平滑。控制抽稀精度和平滑迭代。",
    en: "Overall contour smoothness. 0 = preserve all details; 1 = maximum smoothing. Controls decimation precision and smoothing iterations.",
  },
  "vec.hint_detail_level": {
    zh: "统一细节控制。启用后用一个滑块同时调整多个细节参数；禁用时使用各项独立参数。",
    en: "Unified detail control. When enabled, a single slider adjusts multiple detail parameters; when disabled, individual parameters are used.",
  },
  "vec.hint_svg_enable_stroke": {
    zh: "为 SVG 路径添加描边。可以减少色块之间的接缝（白线）。",
    en: "Add stroke to SVG paths. Helps reduce visible seams (white gaps) between color regions.",
  },
  "vec.hint_svg_stroke_width": {
    zh: "描边线条的宽度。增大可更好覆盖接缝，但可能导致细节丢失。",
    en: "Width of the stroke lines. Larger values cover seams better but may blur fine details.",
  },
  "vec.hint_thin_line_max_radius": {
    zh: "薄线检测的最大半径。用于检测并保留图像中的细线结构。",
    en: "Max radius for thin line detection. Used to detect and preserve thin structures in the image.",
  },
  "vec.hint_enable_coverage_fix": {
    zh: "启用后会扩展区域边界以确保完整覆盖画布，消除微小间隙。",
    en: "Expands region boundaries to ensure full canvas coverage, eliminating tiny gaps.",
  },
  "vec.hint_min_coverage_ratio": {
    zh: "画布最小覆盖率阈值。低于此值时会触发覆盖修复。通常保持接近 1.0。",
    en: "Minimum canvas coverage ratio threshold. Coverage fix is triggered below this value. Keep close to 1.0.",
  },
  "vec.hint_smoothing_spatial": {
    zh: "Mean Shift 空间半径。增大可降噪，但可能模糊细小结构。",
    en: "Mean Shift spatial radius. Larger values reduce noise but may blur fine structures.",
  },
  "vec.hint_smoothing_color": {
    zh: "Mean Shift 颜色半径。增大可合并相近颜色，减少颜色碎片。",
    en: "Mean Shift color radius. Larger values merge similar colors, reducing color fragmentation.",
  },
  "vec.hint_max_working_pixels": {
    zh: "内部处理的最大像素数。大图会被缩小到此限制以提升速度。增大可保留更多细节但更慢。",
    en: "Max pixels for internal processing. Large images are downscaled to this limit for speed. Increase to preserve more detail at the cost of speed.",
  },
  "vec.hint_slic_region_size": {
    zh: "超像素初始区域大小。小值产生更多超像素，保留更多细节但更慢。",
    en: "Initial superpixel region size. Smaller values create more superpixels with more detail but slower processing.",
  },
  "vec.hint_edge_sensitivity": {
    zh: "边缘检测敏感度。高值更积极地保留边缘，低值产生更平滑的分割。",
    en: "Edge detection sensitivity. Higher values preserve edges more aggressively; lower values produce smoother segmentation.",
  },
  "vec.hint_refine_passes": {
    zh: "边界细化迭代次数。更多次迭代产生更精确的区域边界，但增加处理时间。",
    en: "Boundary refinement iterations. More passes produce more precise region boundaries at the cost of processing time.",
  },
  "vec.hint_enable_antialias_detect": {
    zh: "检测并处理抗锯齿像素。对带有平滑边缘的图像效果好，但可能影响像素画风格图像。",
    en: "Detect and handle antialiased pixels. Works well for images with smooth edges but may affect pixel art style images.",
  },
  "vec.hint_aa_tolerance": {
    zh: "抗锯齿检测的颜色容差（LAB ΔE）。增大可检测更多抗锯齿像素。",
    en: "Color tolerance for antialiasing detection (LAB ΔE). Increase to detect more antialiased pixels.",
  },
  "vec.hint_curve_fit_error": {
    zh: "贝塞尔曲线拟合的最大误差（像素）。小值更精确但产生更多锚点；大值更平滑但可能丢失细节。",
    en: "Max error for Bezier curve fitting (pixels). Smaller values are more precise with more anchor points; larger values are smoother but may lose detail.",
  },
  "vec.hint_contour_simplify": {
    zh: "轮廓简化强度。增大可减少轮廓点数，使路径更简洁。",
    en: "Contour simplification strength. Increase to reduce contour points for cleaner paths.",
  },
  "vec.hint_merge_segment_tolerance": {
    zh: "共线线段合并容差。增大可合并更多近似共线的线段。",
    en: "Tolerance for merging collinear segments. Increase to merge more nearly-collinear segments.",
  },
  "vec.hint_min_region_area": {
    zh: "面积小于此值的区域会被合并到相邻区域。增大可减少小碎片。",
    en: "Regions smaller than this area are merged into neighbors. Increase to reduce small fragments.",
  },
  "vec.hint_max_merge_color_dist": {
    zh: "区域合并时允许的最大色差（LAB ΔE²）。增大可合并颜色差异更大的相邻区域。",
    en: "Max color distance for region merging (LAB ΔE²). Increase to merge neighbors with larger color differences.",
  },
  "vec.hint_min_contour_area": {
    zh: "面积小于此值的轮廓会被过滤掉。用于去除微小噪点形状。",
    en: "Contours smaller than this area are filtered out. Used to remove tiny noise shapes.",
  },
  "vec.hint_min_hole_area": {
    zh: "面积小于此值的孔洞会被填充。用于去除区域内的微小空洞。",
    en: "Holes smaller than this area are filled in. Used to remove tiny voids inside regions.",
  },

  app_logo_alt: {
    zh: "Lumina Studio 标志",
    en: "Lumina Studio logo",
  },
  common_preview_alt: {
    zh: "预览图片",
    en: "Preview image",
  },
  common_unit_mm: {
    zh: "毫米",
    en: "mm",
  },
  common_not_available: {
    zh: "不可用",
    en: "N/A",
  },
  common_unit_px: {
    zh: "像素",
    en: "px",
  },
  common_unit_px_per_mm: {
    zh: "像素/毫米",
    en: "px/mm",
  },
  crop_modal_axis_x: {
    zh: "X 轴",
    en: "X",
  },
  crop_modal_axis_y: {
    zh: "Y 轴",
    en: "Y",
  },
  action_generate_model_title: {
    zh: "生成 3D 模型",
    en: "Generate 3D Model",
  },
  action_generate_model_desc: {
    zh: "根据当前图像和 LUT 生成可打印的 3MF 模型文件。",
    en: "Generate a printable 3MF model from current image and LUT.",
  },
  action_zoom_icon: {
    zh: "缩放",
    en: "Zoom",
  },
  action_layer_prev_arrow: {
    zh: "<",
    en: "<",
  },
  action_layer_next_arrow: {
    zh: ">",
    en: ">",
  },
  action_close_overlay: {
    zh: "关闭预览",
    en: "Close preview",
  },
  action_close_icon: {
    zh: "✕",
    en: "✕",
  },
  five_color_combinations_loaded: {
    zh: "已加载 {count} 个有效组合",
    en: "{count} valid combinations loaded",
  },
  five_color_combinations_hint: {
    zh: "灰色选项表示当前选择路径下不可用的组合。",
    en: "Gray items are unavailable for the current selection path.",
  },
  five_color_error_close_icon: {
    zh: "✕",
    en: "✕",
  },
  five_color_not_found_suggestions_title: {
    zh: "建议操作：",
    en: "Suggestions:",
  },
  five_color_not_found_tip_reverse: {
    zh: "尝试使用反转操作来反转颜色顺序。",
    en: "Try the reverse order with the reverse action.",
  },
  five_color_not_found_tip_change: {
    zh: "尝试不同的颜色组合。",
    en: "Try a different color combination.",
  },
  five_color_not_found_tip_gray: {
    zh: "灰色选项表示该位置上的无效组合。",
    en: "Gray options indicate invalid combinations at that position.",
  },

  // ==================== Recipe Share Card ====================
  share_card_footer_caption: {
    zh: "Lumina 2.0 可直接导入本图片生成",
    en: "Import this image directly into Lumina 2.0 to recreate",
  },
  recipe_export_btn: {
    zh: "导出分享卡",
    en: "Export Share Card",
  },
  recipe_export_sidecar_btn: {
    zh: "导出 JSON",
    en: "Export JSON",
  },
  recipe_export_loading: {
    zh: "正在导出...",
    en: "Exporting...",
  },
  recipe_export_success: {
    zh: "分享卡已保存",
    en: "Share card saved",
  },
  recipe_export_error: {
    zh: "导出失败：{error}",
    en: "Export failed: {error}",
  },
  recipe_export_error_no_image: {
    zh: "请先载入图片。",
    en: "Load an image first.",
  },
  recipe_export_error_no_preview: {
    zh: "请先生成预览后再导出。",
    en: "Generate a preview before exporting.",
  },
  recipe_export_error_preview_load: {
    zh: "预览图已失效，请重新生成预览后再导出。",
    en: "The preview image is no longer available. Generate a new preview before exporting.",
  },
  recipe_export_error_unknown: {
    zh: "导出没有完成，请稍后重试。",
    en: "The export did not finish. Please try again.",
  },
  recipe_import_title: {
    zh: "导入分享卡",
    en: "Import Share Card",
  },
  recipe_import_source_label: {
    zh: "来源",
    en: "Source",
  },
  recipe_import_source_png: {
    zh: "PNG 分享卡",
    en: "PNG Share Card",
  },
  recipe_import_source_json: {
    zh: "JSON 配方文件",
    en: "JSON Recipe File",
  },
  recipe_import_version_label: {
    zh: "应用版本",
    en: "App Version",
  },
  recipe_import_created_label: {
    zh: "创建时间",
    en: "Created",
  },
  recipe_import_lut_label: {
    zh: "LUT",
    en: "LUT",
  },
  recipe_import_color_mode_label: {
    zh: "色彩模式",
    en: "Color Mode",
  },
  recipe_import_size_label: {
    zh: "尺寸",
    en: "Size",
  },
  recipe_import_warnings_label: {
    zh: "警告",
    en: "Warnings",
  },
  recipe_import_confirm: {
    zh: "确认恢复",
    en: "Confirm Restore",
  },
  recipe_import_cancel: {
    zh: "取消",
    en: "Cancel",
  },
  announcement_title: {
    zh: "版本更新",
    en: "What's New",
  },
  announcement_close: {
    zh: "关闭",
    en: "Close",
  },
  announcement_close_label: {
    zh: "稍后再看",
    en: "Later",
  },
  announcement_mark_read: {
    zh: "知道了",
    en: "Got it",
  },
  announcement_version_label: {
    zh: "发布日期",
    en: "Released",
  },
  recipe_import_success: {
    zh: "配方已恢复",
    en: "Recipe restored",
  },
  recipe_import_error: {
    zh: "导入失败：{error}",
    en: "Import failed: {error}",
  },
  recipe_import_error_unreadable: {
    zh: "无法读取这个分享卡文件，请确认文件未损坏且来自 Lumina。",
    en: "This share card could not be read. Make sure the file is not corrupted and was created by Lumina.",
  },
  recipe_import_not_share_card: {
    zh: "该 PNG 不包含 Lumina 配方数据",
    en: "This PNG does not contain Lumina recipe data",
  },
  recipe_export_with_sidecar: {
    zh: "同时导出 JSON",
    en: "Also export JSON",
  },
  recipe_custom_button: {
    zh: "自定义配方",
    en: "Custom Recipe",
  },
  recipe_custom_disabled_region: {
    zh: "请先在预览图上点选一个颜色区域，再打开自定义配方",
    en: "Click a color region in the preview first, then open Custom Recipe",
  },
  recipe_custom_undo: {
    zh: "撤销编辑",
    en: "Undo edit",
  },
  recipe_custom_applied_toast: {
    zh: "已应用到当前区域。可以继续调整，或换一个区域再打开。",
    en: "Applied to this region. Keep tweaking, or pick another region and reopen.",
  },
  recipe_custom_current_region: {
    zh: "当前区域",
    en: "Current region",
  },
  recipe_custom_region_multiple: {
    zh: "已选 {count} 个区域",
    en: "{count} regions selected",
  },
  recipe_custom_title: {
    zh: "自定义配方编辑器",
    en: "Custom Recipe Editor",
  },
  recipe_custom_close: {
    zh: "关闭",
    en: "Close",
  },
  recipe_custom_layer_count: {
    zh: "{count} 层",
    en: "{count} layers",
  },
  recipe_custom_layer_label: {
    zh: "第 {index} 层",
    en: "Layer {index}",
  },
  recipe_custom_add_layer: {
    zh: "添加层",
    en: "Add Layer",
  },
  recipe_custom_remove_layer: {
    zh: "删除层",
    en: "Remove Layer",
  },
  recipe_custom_move_up: {
    zh: "上移",
    en: "Move Up",
  },
  recipe_custom_move_down: {
    zh: "下移",
    en: "Move Down",
  },
  recipe_custom_predict: {
    zh: "预测颜色",
    en: "Predict Color",
  },
  recipe_custom_predicting: {
    zh: "正在预测…",
    en: "Predicting…",
  },
  recipe_custom_predict_hint: {
    zh: "点击「预测颜色」查看当前配方的预览颜色。",
    en: "Use Predict Color to preview the current recipe.",
  },
  recipe_custom_preview_color: {
    zh: "预览颜色",
    en: "Preview Color",
  },
  recipe_custom_rgb_label: {
    zh: "RGB",
    en: "RGB",
  },
  recipe_custom_lab_label: {
    zh: "Lab",
    en: "Lab",
  },
  recipe_custom_apply: {
    zh: "应用到选区",
    en: "Apply to Selection",
  },
  recipe_custom_applying: {
    zh: "正在应用…",
    en: "Applying…",
  },
  recipe_custom_region_required: {
    zh: "请先选中至少一个区域，再应用自定义配方。",
    en: "Select at least one region before applying a custom recipe.",
  },
  recipe_custom_region_count: {
    zh: "目标区域：{count}",
    en: "Target Regions: {count}",
  },
  recipe_custom_pattern_placeholder: {
    zh: "层色搜索，例如 WRYB?",
    en: "Pattern search, e.g. WRYB?",
  },
  recipe_custom_pattern_hint: {
    zh: "按层颜色快速填充。字母=颜色首字母，?=保留当前层，-=可选分隔。",
    en: "Quick-fill by layer pattern. Letter=color initial, ?=keep current, -=optional separator.",
  },
  recipe_custom_pattern_apply: {
    zh: "应用模式",
    en: "Apply Pattern",
  },
  recipe_custom_pattern_invalid: {
    zh: "无法识别的字符：{char}",
    en: "Unrecognized character: {char}",
  },
  recipe_custom_predict_failed: {
    zh: "颜色预测失败",
    en: "Color prediction failed",
  },
  recipe_custom_apply_failed: {
    zh: "应用自定义配方失败",
    en: "Failed to apply custom recipe",
  },
  recipe_custom_layer_upgrade_warning: {
    zh: "新配方 {new} 层比当前预览的 {old} 层多，应用后整张图都会按新层数重新出图。再点一次确认。",
    en: "The new recipe has {new} layers, more than the current {old}-layer preview. Applying will re-render the whole image at the new layer count. Click again to confirm.",
  },
  recipe_custom_layer_upgrade_confirm: {
    zh: "确认升级层数并应用",
    en: "Confirm layer upgrade",
  },
  recipe_custom_predict_no_forward_model: {
    zh: "当前 LUT 没带预测模型，无法算出这张配方的颜色。换一张带模型的 LUT，或者直接应用试试。",
    en: "This LUT has no forward model, so the recipe colour can't be predicted. Switch to a LUT with a model, or apply directly to try it out.",
  },
  recipe_custom_target_from_model: {
    zh: "来自模型",
    en: "From Model",
  },
  recipe_custom_history_title: {
    zh: "历史配方",
    en: "Recipe History",
  },
  recipe_custom_history_empty: {
    zh: "还没有自定义配方记录。应用一次后，这里会留下可一键复用的快照。",
    en: "No custom recipes yet. After you apply one, a reusable snapshot will appear here.",
  },
  recipe_custom_history_layers: {
    zh: "{count} 层",
    en: "{count} layers",
  },
  recipe_import_lut_missing: {
    zh: "LUT 未找到，请手动选择兼容的 LUT",
    en: "LUT not found, please select a compatible LUT manually",
  },
  recipe_import_lut_degraded: {
    zh: "LUT 已降级匹配（名称相同但指纹不一致）",
    en: "LUT matched by name but fingerprint differs — colors may vary",
  },
  recipe_import_warning_secondary_lut_missing: {
    zh: "部分多选 LUT 在本机未找到，已从导入选择中移除。",
    en: "Some selected LUTs were not found locally and were removed from the imported selection.",
  },
  recipe_import_warning_fridge_conflict_puzzle: {
    zh: "导入的配方同时启用了冰箱贴模式和拼图模式。为保持状态有效，拼图模式已被禁用。",
    en: "The imported recipe enabled both fridge magnet mode and puzzle mode. Puzzle mode has been disabled to keep the state valid.",
  },
  recipe_import_warning_fridge_conflict_large_format: {
    zh: "导入的配方同时启用了冰箱贴模式和大画幅切片。为保持状态有效，大画幅模式已被禁用。",
    en: "The imported recipe enabled both fridge magnet mode and large-format tiling. Large-format mode has been disabled to keep the state valid.",
  },
  recipe_import_warning_fridge_conflict_loop: {
    zh: "导入的配方同时启用了冰箱贴模式和挂件环。为保持状态有效，挂件环已被禁用。",
    en: "The imported recipe enabled both fridge magnet mode and a keychain loop. The loop has been disabled to keep the state valid.",
  },
  recipe_import_warning_puzzle_conflict_large_format: {
    zh: "导入的配方同时启用了拼图模式和大画幅切片。为保持状态有效，大画幅模式已被禁用。",
    en: "The imported recipe enabled both puzzle mode and large-format tiling. Large-format mode has been disabled to keep the state valid.",
  },
  recipe_import_warning_puzzle_conflict_loop: {
    zh: "导入的配方同时启用了拼图模式和挂件环。为保持状态有效，挂件环已被禁用。",
    en: "The imported recipe enabled both puzzle mode and a keychain loop. The loop has been disabled to keep the state valid.",
  },
  recipe_import_warning_back_labels_unavailable: {
    zh: "导入的配方启用了拼图背面标签。当前版本暂不支持背面标签，已自动关闭。",
    en: "The imported recipe enabled puzzle back labels. Back labels are not available in this version and have been disabled.",
  },
  recipe_import_schema_newer: {
    zh: "配方版本较新，部分参数可能无法恢复",
    en: "Recipe uses a newer schema version — some parameters may not restore",
  },
  recipe_import_integrity_fail: {
    zh: "完整性校验失败，配方数据可能已损坏",
    en: "Integrity check failed — recipe data may be corrupted",
  },
  recipe_import_asset_corrupt: {
    zh: "素材数据损坏，无法恢复原始文件",
    en: "Asset data is corrupted — unable to restore original file",
  },

  lut_info_schema_label: {
    zh: "Schema",
    en: "Schema",
  },
  lut_info_capabilities_label: {
    zh: "能力",
    en: "Capabilities",
  },
  lut_info_predictive_enabled: {
    zh: "支持预测式匹配",
    en: "Predictive match enabled",
  },
  lut_info_predictive_disabled: {
    zh: "仅传统查表",
    en: "Legacy lookup only",
  },
  lut_info_dynamic_enabled: {
    zh: "支持动态层高",
    en: "Dynamic layer height enabled",
  },
  lut_info_dynamic_disabled: {
    zh: "固定层高",
    en: "Fixed layer height",
  },
  lut_info_dynamic_count_enabled: {
    zh: "支持动态层数",
    en: "Dynamic layer count enabled",
  },
  lut_info_dynamic_count_disabled: {
    zh: "固定层数",
    en: "Fixed layer count",
  },
  lut_info_custom_recipe_enabled: {
    zh: "支持自定义配方",
    en: "Custom recipe enabled",
  },
  lut_info_custom_recipe_disabled: {
    zh: "不支持自定义配方",
    en: "Custom recipe unavailable",
  },
  lut_info_source_kind_label: {
    zh: "来源类型",
    en: "Source Kind",
  },
  lut_info_supported_modes_label: {
    zh: "支持模式",
    en: "Supported Modes",
  },
  lut_info_capability_legacy_lookup: {
    zh: "传统查表",
    en: "Legacy lookup",
  },
  lut_info_capability_predictive_match: {
    zh: "预测式匹配",
    en: "Predictive match",
  },
  lut_info_capability_predictive_model: {
    zh: "预测模型",
    en: "Predictive model",
  },
  lut_info_capability_dynamic_layer_height: {
    zh: "动态层高",
    en: "Dynamic layer height",
  },
  lut_info_capability_dynamic_layer_count: {
    zh: "动态层数",
    en: "Dynamic layer count",
  },
  lut_info_capability_custom_recipe: {
    zh: "自定义配方",
    en: "Custom recipe",
  },
  lut_info_capability_native_reference: {
    zh: "原生参考源",
    en: "Native reference",
  },
  lut_compare_warning_schema_mismatch: {
    zh: "Schema 版本不一致：{schemaA} vs {schemaB}",
    en: "Schema versions differ: {schemaA} vs {schemaB}",
  },
  lut_compare_warning_predictive_mismatch: {
    zh: "预测式匹配支持不一致：{valueA} vs {valueB}",
    en: "Predictive match support differs: {valueA} vs {valueB}",
  },
  lut_compare_warning_dynamic_mismatch: {
    zh: "动态层高支持不一致：{valueA} vs {valueB}",
    en: "Dynamic layer height support differs: {valueA} vs {valueB}",
  },
  action_lut_match_label: {
    zh: "LUT 匹配",
    en: "LUT Match",
  },
  action_lut_match_legacy: {
    zh: "传统查表",
    en: "Legacy KD-tree",
  },
  action_lut_match_predictive: {
    zh: "预测式运行时",
    en: "Predictive Runtime",
  },
  action_lut_match_mode_key: {
    zh: "模式 {mode}",
    en: "Mode {mode}",
  },
  recipe_editor_button: {
    zh: "自定义配方",
    en: "Custom Recipe",
  },
  recipe_editor_title: {
    zh: "自定义配方编辑器",
    en: "Custom Recipe Editor",
  },
  recipe_editor_layers_label: {
    zh: "按层编辑当前选区的配方，并可直接预测颜色。",
    en: "Edit the per-layer recipe for the current selection and predict its color.",
  },
  recipe_editor_layer_n: {
    zh: "第 {n} 层",
    en: "Layer {n}",
  },
  recipe_editor_add_layer: {
    zh: "添加层",
    en: "Add Layer",
  },
  recipe_editor_remove_layer: {
    zh: "删除层",
    en: "Remove Layer",
  },
  recipe_editor_move_up: {
    zh: "上移",
    en: "Move Up",
  },
  recipe_editor_move_down: {
    zh: "下移",
    en: "Move Down",
  },
  recipe_editor_predict: {
    zh: "预测颜色",
    en: "Predict Color",
  },
  recipe_editor_predict_loading: {
    zh: "预测中...",
    en: "Predicting...",
  },
  recipe_editor_predict_failed: {
    zh: "颜色预测失败",
    en: "Color prediction failed",
  },
  recipe_editor_search: {
    zh: "搜索候选",
    en: "Search Recipes",
  },
  recipe_editor_search_loading: {
    zh: "搜索中...",
    en: "Searching...",
  },
  recipe_editor_search_placeholder: {
    zh: "按层搜索，如 W?BK*",
    en: "Search by layer pattern, e.g. W?BK*",
  },
  recipe_editor_search_results: {
    zh: "候选配方",
    en: "Candidate Recipes",
  },
  recipe_editor_search_failed: {
    zh: "配方搜索失败",
    en: "Recipe search failed",
  },
  recipe_editor_apply: {
    zh: "应用到选区",
    en: "Apply to Selection",
  },
  recipe_editor_apply_failed: {
    zh: "配方应用失败",
    en: "Failed to apply recipe override",
  },
  recipe_editor_clear: {
    zh: "清除覆盖",
    en: "Clear Override",
  },
  recipe_editor_no_region: {
    zh: "请先选择一个区域或选区。",
    en: "Select a region or active selection first.",
  },
  recipe_editor_upgrade_confirm: {
    zh: "当前全局层数为 {old}，应用该配方后会升到 {new} 层。继续吗？",
    en: "The current global layer count is {old}. Applying this recipe will upgrade it to {new}. Continue?",
  },
  cal_workflow_label: {
    zh: "工作流模式",
    en: "Workflow",
  },
  cal_substrate_id_label: {
    zh: "基板 ID",
    en: "Substrate ID",
  },
  cal_substrate_name_label: {
    zh: "基板名称",
    en: "Substrate Name",
  },
  cal_material_default_label: {
    zh: "默认材料",
    en: "Default Material",
  },
  cal_single_stage_layer_height_label: {
    zh: "层高",
    en: "Layer Height",
  },
  cal_generate_single_stage_btn: {
    zh: "生成 梯度色卡",
    en: "Generate Single-Stage Kit",
  },
  cal_download_kit: {
    zh: "下载 Kit ZIP",
    en: "Download Kit ZIP",
  },
  cal_download_manifest: {
    zh: "下载 Manifest",
    en: "Download Manifest",
  },
  cal_single_stage_jobs_title: {
    zh: "Single-Stage 任务",
    en: "Single-Stage Jobs",
  },
  cal_single_stage_jobs_desc: {
    zh: "每个颜色都会生成一个可打印的 3MF 任务",
    en: "One printable 3MF job is generated per color",
  },
  mat_gradient_generate_title: {
    zh: "生成梯度卡",
    en: "Generate Gradient Card",
  },
  mat_gradient_generate_desc: {
    zh: "生成用于打印和提取的梯度卡文件包（包含不同层高的切片配置文件和参数信息）。",
    en: "Generate gradient card print files (including slicer profiles and parameters) used for printing and color extraction.",
  },
  mat_gradient_generate_section_title: {
    zh: "生成设置",
    en: "Generation Settings",
  },
  mat_gradient_generate_section_desc: {
    zh: "选择你的打印层高，生成包含 3MF 打印文件和提取所需的配置包。",
    en: "Select your print layer height and generate the package containing 3MF print files and configuration needed for extraction.",
  },
  mat_gradient_generate_notice_title: {
    zh: "使用须知与线上模型",
    en: "Instructions & Online Models",
  },
  mat_gradient_generate_notice_desc: {
    zh: "打印前请务必阅读此说明，以确保后续操作顺利进行。",
    en: "Please read these instructions before printing to ensure smooth operation later.",
  },
  mat_gradient_generate_notice_dual_print: {
    zh: "注意：每种测试耗材需要打印两张梯度卡（一张白底，一张黑底）。无论你使用本地生成还是下载线上模型，都必须在这里点击生成并下载配置文件包（ZIP），后续「提取梯度卡」步骤会用到它。",
    en: "Note: Each test material requires printing two gradient cards (one on a white base, one on a black base). Whether you generate them locally or download the online models, you must generate and download the configuration package (ZIP) here, as it is required for the 'Extract Gradient Card' step later.",
  },
  mat_gradient_generate_notice_online_model: {
    zh: "线上模型与本地生成的模型完全相同。如果你通过 MakerWorld 下载在线模型，可以为 Lumina 团队提供积分支持，积分将用于社区抽奖福利。",
    en: "The online models are identical to the locally generated ones. Downloading via MakerWorld provides points to the Lumina team, which will be used for community giveaways.",
  },
  mat_gradient_generate_online_model_link: {
    zh: "梯度卡在线模型",
    en: "Gradient Card Online Model",
  },
  mat_gradient_generate_parametric_box_link: {
    zh: "梯度卡收纳盒在线模型",
    en: "Gradient Card Parametric Storage Box",
  },
  mat_gradient_generate_btn: {
    zh: "生成配置文件包",
    en: "Generate Configuration Package",
  },
  mat_gradient_download_title: {
    zh: "下载结果",
    en: "Download Result",
  },
  mat_gradient_download_desc: {
    zh: "配置包已生成，请下载并妥善保存。在提取色彩时需要上传此 ZIP 文件。",
    en: "Configuration package generated. Please download and save it. You will need to upload this ZIP file during color extraction.",
  },
  mat_gradient_download_btn: {
    zh: "下载配置文件包 (.zip)",
    en: "Download Configuration Package (.zip)",
  },
  mat_gradient_extract_title: {
    zh: "提取梯度卡数据",
    en: "Extract Gradient Card Data",
  },
  mat_gradient_extract_desc: {
    zh: "首先导入下载好的梯度卡ZIP，然后分别上传白底与黑底照片，并框选出色块区域即可完成提取。",
    en: "First import the downloaded gradient card ZIP, then upload the white and black background photos separately, and bound the color blocks area to complete extraction.",
  },
  mat_gradient_colorchecker_hint: {
    zh: "这里的 ColorChecker 只负责先校正白底图或黑底图的颜色；确认使用后，梯度卡提取会明确标记为已校色图片来源。",
    en: "ColorChecker only corrects the white or black image first. After you accept it, gradient extraction explicitly records the image as a calibrated source.",
  },
  mat_gradient_colorchecker_white_btn: {
    zh: "校色白底图",
    en: "Calibrate White Image",
  },
  mat_gradient_colorchecker_black_btn: {
    zh: "校色黑底图",
    en: "Calibrate Black Image",
  },
  mat_gradient_colorchecker_restored_source: {
    zh: "已使用校色后的图片。后续提取会标记为校色来源，避免和原始拍摄图混用。",
    en: "Using the corrected image. Later extraction will keep it separate from original captures.",
  },
  mat_gradient_view_details_btn: {
    zh: "查看详细信息",
    en: "View Details",
  },
  mat_gradient_details_dialog_title: {
    zh: "提取详细信息",
    en: "Extraction Details",
  },
  mat_gradient_details_dialog_desc: {
    zh: "拟合参数和材料摘要的原始数据，可用于排查问题或手动校准。",
    en: "Raw fit parameters and material summary for troubleshooting or manual calibration.",
  },
  mat_gradient_details_close_btn: {
    zh: "关闭",
    en: "Close",
  },
  mat_gradient_select_dataset_btn: {
    zh: "选择数据集 ZIP",
    en: "Choose Dataset ZIP",
  },
  mat_gradient_no_dataset_selected: {
    zh: "尚未选择数据集 ZIP",
    en: "No dataset ZIP selected",
  },
  mat_gradient_invalid_zip_error: {
    zh: "你上传的 ZIP 不是正确的梯度卡 Kit ZIP，请重新选择生成时下载的 Kit ZIP。",
    en: "The uploaded ZIP is not a valid gradient card kit. Please reselect the Kit ZIP downloaded during generation.",
  },
  mat_gradient_extract_inputs_required_error: {
    zh: "请先选择 Kit ZIP，并上传白底图和黑底图。",
    en: "Please choose the Kit ZIP and upload both the white and black images first.",
  },
  mat_gradient_extract_corners_required_error: {
    zh: "请先在白底图和黑底图上各点选四个角。",
    en: "Please mark four corners on both the white and black images first.",
  },
  mat_gradient_extract_colorchecker_pair_required_error: {
    zh: "ColorChecker 校色图需要白底图和黑底图都确认后才能用于梯度卡拟合。",
    en: "Confirm both white and black ColorChecker images before using them for gradient-card fitting.",
  },
  mat_gradient_colorchecker_confirm_error: {
    zh: "ColorChecker 校色图确认失败，请重新执行校色后再试。",
    en: "Failed to confirm the ColorChecker calibrated image. Please recalibrate and try again.",
  },
  mat_gradient_invalid_image_error: {
    zh: "上传的图片无法识别，请重新选择清晰且完整的梯度卡照片。",
    en: "The uploaded image could not be read. Please reselect a clear and complete gradient card photo.",
  },
  mat_gradient_heic_unsupported_error: {
    zh: "当前环境暂不支持 HEIC/HEIF 图片，请先转换为 PNG 或 JPG 后再上传。",
    en: "HEIC/HEIF images are not supported in the current environment. Please convert them to PNG or JPG before uploading.",
  },
  mat_gradient_invalid_corner_error: {
    zh: "四角数据无效，请重新点选四个角后再试。",
    en: "The corner selection is invalid. Please re-mark the four corners and try again.",
  },
  mat_gradient_invalid_orientation_error: {
    zh: "无法可靠判断梯度卡方向，请检查图片方向和四角位置后重试。",
    en: "The gradient card orientation could not be determined reliably. Please check the image orientation and corner positions, then try again.",
  },
  mat_gradient_extract_failed_error: {
    zh: "梯度卡提取失败，请重试。",
    en: "Gradient card extraction failed. Please try again.",
  },
  mat_gradient_rotate_white_failed: {
    zh: "白底梯度卡图片旋转失败，请重试。",
    en: "Failed to rotate the white gradient card image. Please try again.",
  },
  mat_gradient_rotate_black_failed: {
    zh: "黑底梯度卡图片旋转失败，请重试。",
    en: "Failed to rotate the black gradient card image. Please try again.",
  },
  mat_gradient_save_requires_extract_error: {
    zh: "请先完成提取，再保存耗材档案。",
    en: "Please complete extraction before saving the material archive.",
  },
  mat_gradient_save_name_required_error: {
    zh: "请输入耗材名称后再保存。",
    en: "Please enter a material name before saving.",
  },
  mat_gradient_save_session_expired_error: {
    zh: "当前提取结果已失效，请重新提取后再保存。",
    en: "The current extraction result has expired. Please run extraction again before saving.",
  },
  mat_gradient_save_target_missing_error: {
    zh: "目标耗材档案不存在，可能已被删除，请刷新后重试。",
    en: "The target material archive no longer exists. It may have been deleted. Please refresh and try again.",
  },
  mat_gradient_save_target_invalid_error: {
    zh: "目标耗材档案已损坏，无法继续保存，请检查后重试。",
    en: "The target material archive is invalid, so saving cannot continue. Please check it and try again.",
  },
  mat_gradient_save_failed_error: {
    zh: "保存耗材档案失败，请重试。",
    en: "Saving the material archive failed. Please try again.",
  },
  mat_gradient_extract_output_title: {
    zh: "提取输出",
    en: "Extraction Output",
  },
  mat_gradient_fit_output_title: {
    zh: "拟合输出",
    en: "Fit Output",
  },
  mat_gradient_upload_title: {
    zh: "导入生成的梯度卡ZIP",
    en: "Import Generated Gradient Card ZIP",
  },
  mat_gradient_upload_desc: {
    zh: "导入您在梯度卡生成工具中下载的zip。",
    en: "Import the ZIP you downloaded from the gradient card generation tool.",
  },
  mat_gradient_white_image_label: {
    zh: "白底梯度卡图片",
    en: "White Gradient Card Image",
  },
  mat_gradient_black_image_label: {
    zh: "黑底梯度卡图片",
    en: "Black Gradient Card Image",
  },
  mat_gradient_no_image_selected: {
    zh: "尚未选择图片",
    en: "No image selected",
  },
  mat_gradient_select_image_btn: {
    zh: "选择图片",
    en: "Choose Image",
  },
  mat_gradient_rotate_cw_btn: {
    zh: "顺时针 90°",
    en: "Rotate 90° CW",
  },
  mat_gradient_rotate_ccw_btn: {
    zh: "逆时针 90°",
    en: "Rotate 90° CCW",
  },
  mat_gradient_clear_points_btn: {
    zh: "清除角点",
    en: "Clear Corners",
  },
  mat_gradient_corner_hint_prefix: {
    zh: "已标记角点",
    en: "Corners Marked",
  },
  mat_gradient_corner_complete: {
    zh: "四角已完成，可开始提取。",
    en: "All four corners are set and ready for extraction.",
  },
  mat_gradient_white_canvas_title: {
    zh: "白底梯度卡",
    en: "White Gradient Card",
  },
  mat_gradient_black_canvas_title: {
    zh: "黑底梯度卡",
    en: "Black Gradient Card",
  },
  mat_gradient_empty_white_canvas: {
    zh: "上传白底梯度卡图片后，在这里点选四角。",
    en: "Upload the white gradient card image to mark its four corners here.",
  },
  mat_gradient_empty_black_canvas: {
    zh: "上传黑底梯度卡图片后，在这里点选四角。",
    en: "Upload the black gradient card image to mark its four corners here.",
  },
  mat_gradient_compute_btn: {
    zh: "提取耗材",
    en: "Extract Material",
  },
  mat_gradient_material_name_label: {
    zh: "耗材名称",
    en: "Material Name",
  },
  mat_gradient_material_name_placeholder: {
    zh: "输入要保存的耗材名称",
    en: "Enter the material name to save",
  },
  mat_gradient_brand_label: {
    zh: "品牌（可选）",
    en: "Brand (optional)",
  },
  mat_gradient_brand_placeholder: {
    zh: "例如：瑞贝思、拓竹",
    en: "e.g. Ribes, Bambu Lab",
  },
  mat_gradient_brand_hint: {
    zh: "填写后，该耗材将保存至 materials/<品牌>/<耗材名>/",
    en: "If set, the material is saved under materials/<brand>/<name>/",
  },
  mat_gradient_brand_loading: {
    zh: "正在加载已有品牌...",
    en: "Loading saved brands...",
  },
  mat_gradient_brand_empty: {
    zh: "暂无已有品牌，可直接输入新品牌",
    en: "No saved brands yet. You can type a new brand directly.",
  },
  mat_gradient_brand_create_option: {
    zh: "新增品牌：{brand}",
    en: "Create brand: {brand}",
  },
  mat_gradient_save_material_btn: {
    zh: "保存耗材档案",
    en: "Save Material Archive",
  },
  mat_gradient_warp_preview_title: {
    zh: "透视校正预览",
    en: "Perspective Warp Preview",
  },
  mat_gradient_sample_boxes_hint: {
    zh: "方框表示实际取色区域。",
    en: "Boxes indicate the actual sampled regions.",
  },
  mat_gradient_estimated_color_title: {
    zh: "计算出的耗材颜色",
    en: "Estimated Material Color",
  },
  mat_gradient_rgb_label: {
    zh: "RGB",
    en: "RGB",
  },
  mat_gradient_hex_label: {
    zh: "HEX",
    en: "HEX",
  },
  mat_gradient_mean_delta_e_label: {
    zh: "平均 ΔE",
    en: "Mean ΔE",
  },
  mat_gradient_max_delta_e_label: {
    zh: "最大 ΔE",
    en: "Max ΔE",
  },
  mat_gradient_rmse_linear_label: {
    zh: "线性 RMSE",
    en: "Linear RMSE",
  },
  mat_gradient_channel_rmse_label: {
    zh: "通道 RMSE",
    en: "Channel RMSE",
  },
  mat_gradient_channel_rmse_value: {
    zh: "红 {r} / 绿 {g} / 蓝 {b}",
    en: "R {r} / G {g} / B {b}",
  },
  mat_gradient_orientation_title: {
    zh: "方向检测",
    en: "Orientation Detection",
  },
  mat_gradient_orientation_reliable: {
    zh: "可靠",
    en: "Reliable",
  },
  mat_gradient_orientation_unreliable: {
    zh: "置信度低",
    en: "Low Confidence",
  },
  mat_gradient_white_orientation_label: {
    zh: "白底方向",
    en: "White Orientation",
  },
  mat_gradient_black_orientation_label: {
    zh: "黑底方向",
    en: "Black Orientation",
  },
  mat_gradient_delta_e_gap_label: {
    zh: "ΔE 差距",
    en: "ΔE Gap",
  },
  mat_gradient_anchor_section_title: {
    zh: "色块位置（决定读取顺序）",
    en: "Pure Block Position (Drives Sampling Order)",
  },
  mat_gradient_anchor_section_desc: {
    zh: "请告诉系统照片上「露出底板的纯色块」位于哪个角。先按 1.左上 → 2.右上 → 3.右下 → 4.左下 顺序点选 4 个角，再选这里。若不确定可保留「自动检测」。",
    en: "Tell the system which screen corner holds the pure substrate block (the only patch where the bare board shows through). Pick the four corners in 1.top-left → 2.top-right → 3.bottom-right → 4.bottom-left order first, then choose here. Leave on \"Auto detect\" if unsure.",
  },
  mat_gradient_white_anchor_label: {
    zh: "纯白色块位置",
    en: "Pure White Block Position",
  },
  mat_gradient_black_anchor_label: {
    zh: "纯黑色块位置",
    en: "Pure Black Block Position",
  },
  mat_gradient_anchor_option_auto: {
    zh: "自动检测（推荐）",
    en: "Auto detect (recommended)",
  },
  mat_gradient_anchor_option_tl: {
    zh: "左上角",
    en: "Top-left",
  },
  mat_gradient_anchor_option_tr: {
    zh: "右上角",
    en: "Top-right",
  },
  mat_gradient_anchor_option_br: {
    zh: "右下角",
    en: "Bottom-right",
  },
  mat_gradient_anchor_option_bl: {
    zh: "左下角",
    en: "Bottom-left",
  },
  mat_gradient_corner_pick_order_hint: {
    zh: "请按 1.左上 → 2.右上 → 3.右下 → 4.左下 顺序点选 4 个角。",
    en: "Click the four corners in 1.top-left → 2.top-right → 3.bottom-right → 4.bottom-left order.",
  },
  mat_gradient_image_source_section_title: {
    zh: "图像来源",
    en: "Image Source",
  },
  mat_gradient_image_source_section_desc: {
    zh: "请确认上传的两张梯度卡图是「相机/扫描仪原图」还是「ColorChecker 校正/还原图」。色卡校正可减少相机色差，通常有利于拟合；请保持白底图、黑底图使用同一相机、曝光、白平衡和校色设置，并关注采样区域是否出现高光/阴影裁切。若出现「零厚度白底采样接近纯白」等警告，请按该警告处理。",
    en: "Tell the system whether the two uploaded gradient-card images are direct camera/scanner captures (raw) or ColorChecker-corrected/restored renders. ColorChecker correction can reduce camera color bias and can help the fit; keep the white/black images on the same camera, exposure, white balance, and calibration settings, and watch for highlight/shadow clipping in the sampled area. If warnings such as \"zero-thickness white near pure white\" appear, treat those warnings as the deciding signal.",
  },
  mat_gradient_image_source_option_raw: {
    zh: "原图（相机/扫描仪直出，推荐）",
    en: "Raw photo (camera/scanner direct, recommended)",
  },
  mat_gradient_image_source_option_restored: {
    zh: "ColorChecker 校正/还原图",
    en: "ColorChecker-corrected / restored image",
  },
  mat_gradient_image_source_restored_warning: {
    zh: "已选择「ColorChecker 校正/还原图」。该来源会与原图记录分开合并；请确认两张图使用同一校色设置，且 Stage A 采样区域没有裁切。若出现「零厚度白底采样接近纯白」等警告，请重新拍摄或调整曝光/校色设置后再提取。",
    en: "ColorChecker-corrected/restored source selected. This source is kept separate from raw captures during merging; make sure both images use the same calibration settings and the sampled Stage A area is not clipped. If warnings such as \"zero-thickness white near pure white\" appear, re-capture or adjust exposure/calibration before extracting again.",
  },
  mat_gradient_image_source_mismatch_error: {
    zh: "本次上传的图像来源与该耗材已有的验证记录不一致，无法合并。请使用相同来源（同为原图或同为校正/还原图）重新拍摄，或在保存时改用「覆盖」模式以丢弃原有验证记录。",
    en: "The image source of this capture does not match the existing verification runs for this material, so they cannot be merged. Re-capture using the same source (raw or corrected/restored) or use override mode when saving to discard previous verification runs.",
  },
  // ----- Aggregation diagnostics ("merge diagnostics" section) -----
  // Surfaced in the saved-material card after a successful save so the
  // user can see which historical runs participated in the joint refit
  // and why others were dropped.
  mat_gradient_aggregation_section_title: {
    zh: "合并诊断",
    en: "Merge Diagnostics",
  },
  mat_gradient_aggregation_method_label: {
    zh: "聚合方式",
    en: "Aggregation Method",
  },
  mat_gradient_aggregation_method_refit_combined_samples: {
    zh: "合并样本重拟合",
    en: "Refit on combined samples",
  },
  mat_gradient_aggregation_method_mean: {
    zh: "参数均值兜底",
    en: "Parameter-mean fallback",
  },
  mat_gradient_aggregation_selection_strategy_label: {
    zh: "选择策略",
    en: "Selection Strategy",
  },
  mat_gradient_aggregation_strategy_bias_filter_v1: {
    zh: "偏置硬过滤",
    en: "Bias filter",
  },
  "mat_gradient_aggregation_strategy_bias_filter_v1+cross_val": {
    zh: "偏置过滤 + 交叉验证",
    en: "Bias filter + cross-val",
  },
  mat_gradient_aggregation_runs_used: {
    zh: "{{used}} / {{total}} 次校准参与本次重拟合",
    en: "{{used}} of {{total}} verification runs participated in this refit",
  },
  mat_gradient_aggregation_run_label: {
    zh: "第 {{index}} 次校准",
    en: "Run #{{index}}",
  },
  mat_gradient_aggregation_run_fresh_badge: {
    zh: "本次新增",
    en: "Fresh",
  },
  mat_gradient_aggregation_run_excluded_badge: {
    zh: "已排除",
    en: "Excluded",
  },
  mat_gradient_aggregation_run_included_badge: {
    zh: "已采纳",
    en: "Included",
  },
  mat_gradient_aggregation_no_excluded: {
    zh: "本次合并未排除任何历史校准。",
    en: "No historical runs were excluded by the bias filter for this merge.",
  },
  // Bias-flag labels (stable codes from backend → localised strings)
  mat_gradient_bias_flag_c0_white_avg_gt_0_95: {
    zh: "白底零厚度像素接近纯白（C0_white > 0.95，可能裁切/过亮归一化）",
    en: "Zero-thickness white near pure white (C0_white > 0.95, possible clipping or overbright normalization)",
  },
  mat_gradient_bias_flag_image_source_restored: {
    zh: "图像来源标记为「ColorChecker 校正/还原图」",
    en: "Image source tagged as ColorChecker-corrected/restored",
  },
  mat_gradient_bias_flag_white_substrate_flat: {
    zh: "白底信号过弱（朝向不可分辨）",
    en: "White substrate signal too flat",
  },
  mat_gradient_bias_flag_black_substrate_flat: {
    zh: "黑底信号过弱（朝向不可分辨）",
    en: "Black substrate signal too flat",
  },
  mat_gradient_bias_flag_orientation_unreliable: {
    zh: "朝向打分不可靠（提示性，不参与硬过滤）",
    en: "Orientation ranking unreliable (advisory, not used for hard filter)",
  },
  mat_gradient_bias_flag_c0_white_avg_lt_0_60: {
    zh: "白底零厚度像素过暗（C0_white < 0.60，曝光不足或角点选错）",
    en: "Zero-thickness white too dark (C0_white < 0.60, underexposed or wrong anchor)",
  },
  mat_gradient_bias_flag_mean_de_gt_3: {
    zh: "本次拟合平均 ΔE > 3（拟合本身已不可信，禁止其样本进入联合重拟）",
    en: "Run's own mean ΔE > 3 (fit already unreliable; samples blocked from joint refit)",
  },
  mat_gradient_bias_flag_c0_session_outlier: {
    zh: "白底读数与同期校准的其他材料中位数偏差过大（疑似白底取样位置错误或光照不一致，建议重拍）",
    en: "White-substrate reading deviates from the session median across other materials (likely wrong patch sample or inconsistent lighting; please re-shoot)",
  },
  mat_gradient_aggregation_excluded_reason_bias_filter: {
    zh: "偏置硬过滤",
    en: "Bias filter",
  },
  mat_gradient_aggregation_excluded_reason_cross_val: {
    zh: "交叉验证排序",
    en: "Cross-val ranking",
  },
  mat_gradient_aggregation_excluded_reason_c0_white_pairwise_mismatch: {
    zh: "白底亮度与新捕获相差过大（>1.5×，光照环境不一致）",
    en: "White-substrate brightness differs from fresh capture by more than 1.5x (inconsistent lighting)",
  },
  mat_gradient_aggregation_excluded_reason_c0_session_outlier: {
    zh: "白底跨材料一致性（与同 session 其他材料的中位数偏差超阈值）",
    en: "Cross-material session white_C0 outlier (deviates from same-session median beyond threshold)",
  },
  mat_gradient_white_signal_label: {
    zh: "白底信号",
    en: "White Signal",
  },
  mat_gradient_black_signal_label: {
    zh: "黑底信号",
    en: "Black Signal",
  },
  mat_gradient_signal_flat_badge: {
    zh: "信号过弱",
    en: "Low Signal",
  },
  mat_gradient_manual_override_badge: {
    zh: "手动指定",
    en: "Manual",
  },
  mat_gradient_signal_flat_hint: {
    zh: "此基底梯度极弱（采样格颜色几乎一致），自动方向检测可能不可靠。建议在上方手动选择「色块位置」对应的角。",
    en: "This substrate's gradient is very weak (sample cells are nearly identical). Auto orientation detection may be unreliable — pick the matching anchor in the \"Pure Block Position\" selector above.",
  },
  mat_gradient_saved_material_title: {
    zh: "底层参数文件（可选导出）",
    en: "Low-Level Parameter Files (Optional Export)",
  },
  mat_gradient_saved_material_desc: {
    zh: "提取结果已自动保存至软件本地，普通用户无需下载。这些底层文件仅供跨设备备份或高级调试使用。",
    en: "Extraction results are automatically saved locally; normal users do not need to download them. These low-level files are only for cross-device backup or advanced debugging.",
  },
  mat_gradient_download_material_btn: {
    zh: "导出基础耗材信息 (material.json)",
    en: "Export Basic Material Info (material.json)",
  },
  mat_gradient_library_title: {
    zh: "耗材库",
    en: "Material Library",
  },
  mat_gradient_library_desc: {
    zh: "浏览已保存的 Stage A 耗材档案，并支持多选导出 ZIP 或批量导入 ZIP。",
    en: "Browse saved Stage A material archives, export selected ZIP bundles, or import ZIP bundles in bulk.",
  },
  mat_gradient_library_select_all_btn: {
    zh: "全选耗材",
    en: "Select All",
  },
  mat_gradient_library_clear_selection_btn: {
    zh: "清空选择",
    en: "Clear Selection",
  },
  mat_gradient_library_import_btn: {
    zh: "导入耗材 ZIP",
    en: "Import Material ZIP",
  },
  mat_gradient_library_export_btn: {
    zh: "导出所选耗材",
    en: "Export Selected",
  },
  mat_gradient_library_import_hint: {
    zh: "可一次选择多个 ZIP；导出文件也可再次批量导入。",
    en: "You can choose multiple ZIP files at once, and exported bundles can be imported again in bulk.",
  },
  lut_library_title: {
    zh: "LUT库",
    en: "LUT Library",
  },
  lut_library_total_label: {
    zh: "本地 LUT",
    en: "Local LUTs",
  },
  lut_library_cloud_label: {
    zh: "云端安装",
    en: "Cloud Installed",
  },
  lut_library_custom_label: {
    zh: "自定义",
    en: "Custom",
  },
  lut_library_mode_count_label: {
    zh: "颜色模式",
    en: "Color Modes",
  },
  lut_library_refresh_btn: {
    zh: "刷新本地库",
    en: "Refresh Library",
  },
  lut_library_upload_btn: {
    zh: "导入 LUT 文件",
    en: "Import LUT File",
  },
  lut_library_search_placeholder: {
    zh: "搜索名称、厂商、路径、颜色模式",
    en: "Search name, maker, path, or color mode",
  },
  lut_library_loading: {
    zh: "正在加载本地 LUT...",
    en: "Loading local LUTs...",
  },
  lut_library_empty: {
    zh: "没有匹配的本地 LUT。",
    en: "No matching local LUTs.",
  },
  lut_library_load_failed: {
    zh: "读取本地 LUT 库失败",
    en: "Failed to load local LUT library",
  },
  lut_library_upload_success: {
    zh: "LUT 已导入本地库。",
    en: "LUT imported into the local library.",
  },
  lut_library_upload_failed: {
    zh: "LUT 导入失败",
    en: "LUT import failed",
  },
  lut_library_group_count: {
    zh: "{count} 个 LUT",
    en: "{count} LUTs",
  },
  lut_library_origin_cloud: {
    zh: "云端",
    en: "Cloud",
  },
  lut_library_origin_custom: {
    zh: "自定义",
    en: "Custom",
  },
  lut_library_origin_preset: {
    zh: "预设",
    en: "Preset",
  },
  lut_library_color_mode_label: {
    zh: "颜色模式",
    en: "Color Mode",
  },
  lut_library_source_kind_label: {
    zh: "来源类型",
    en: "Source Kind",
  },
  lut_library_path_label: {
    zh: "路径",
    en: "Path",
  },
  lut_library_fingerprint_label: {
    zh: "指纹",
    en: "Fingerprint",
  },
  lut_library_details_btn: {
    zh: "查看详情",
    en: "View Details",
  },
  lut_library_unknown: {
    zh: "未知",
    en: "Unknown",
  },
  lut_sync_title: {
    zh: "云端 LUT 库",
    en: "Cloud LUT Library",
  },
  lut_sync_catalog_count_label: {
    zh: "云端条目",
    en: "Cloud Items",
  },
  lut_sync_catalog_loaded_inline: {
    zh: "已加载 {loaded} / {total} 个云端 LUT",
    en: "Loaded {loaded} / {total} cloud LUTs",
  },
  lut_sync_installed_count_label: {
    zh: "已安装",
    en: "Installed",
  },
  lut_sync_config_label: {
    zh: "远端配置",
    en: "Remote",
  },
  lut_sync_configured: {
    zh: "已配置",
    en: "Configured",
  },
  lut_sync_not_configured: {
    zh: "未配置",
    en: "Not configured",
  },
  lut_sync_refresh_btn: {
    zh: "刷新云端目录",
    en: "Refresh Catalog",
  },
  lut_sync_load_more_btn: {
    zh: "加载更多",
    en: "Load More",
  },
  lut_sync_status_failed: {
    zh: "读取云端 LUT 库失败",
    en: "Failed to load cloud LUT library",
  },
  lut_sync_catalog_not_configured: {
    zh: "尚未配置云端 LUT 库。本地 LUT 仍可离线使用；配置 LUMINA_LUT_REGISTRY_URL 后会显示云端 LUT。",
    en: "Cloud LUT registry is not configured. Local LUTs remain available offline; configure LUMINA_LUT_REGISTRY_URL to show cloud LUTs.",
  },
  lut_sync_catalog_refresh_success: {
    zh: "云端 LUT 目录已刷新。",
    en: "Cloud LUT catalog refreshed.",
  },
  lut_sync_search_placeholder: {
    zh: "搜索名称、厂商、路径或 ID",
    en: "Search name, maker, path, or ID",
  },
  lut_sync_install_btn: {
    zh: "下载到本地",
    en: "Download",
  },
  lut_sync_installed_btn: {
    zh: "已安装",
    en: "Installed",
  },
  lut_sync_local_available_btn: {
    zh: "已安装",
    en: "Installed",
  },
  lut_sync_install_success: {
    zh: "LUT 已下载并安装到本地。",
    en: "LUT downloaded and installed locally.",
  },
  lut_sync_install_failed: {
    zh: "LUT 下载失败",
    en: "LUT download failed",
  },
  lut_sync_catalog_empty: {
    zh: "没有匹配的云端 LUT。",
    en: "No matching cloud LUTs.",
  },
  lut_sync_loading: {
    zh: "正在加载云端 LUT...",
    en: "Loading cloud LUTs...",
  },
  lut_sync_package_size_label: {
    zh: "体积",
    en: "Size",
  },
  lut_sync_content_fingerprint_label: {
    zh: "内容指纹",
    en: "Fingerprint",
  },
  lut_sync_color_mode_label: {
    zh: "颜色模式",
    en: "Color Mode",
  },
  lut_sync_catalog_state_label: {
    zh: "状态",
    en: "Status",
  },
  lut_sync_catalog_state_not_installed: {
    zh: "未下载",
    en: "Not Downloaded",
  },
  lut_sync_catalog_state_installed: {
    zh: "已安装",
    en: "Installed",
  },
  lut_sync_catalog_state_local_available: {
    zh: "已安装",
    en: "Installed",
  },
  lut_sync_local_path_label: {
    zh: "本地路径",
    en: "Local Path",
  },
  lut_sync_unknown: {
    zh: "未知",
    en: "Unknown",
  },
  mat_sync_title: {
    zh: "云端耗材库",
    en: "Cloud Material Library",
  },
  mat_sync_catalog_count_label: {
    zh: "云端条目",
    en: "Cloud Items",
  },
  mat_sync_catalog_loaded_inline: {
    zh: "已加载 {loaded} / {total} 个云端耗材",
    en: "Loaded {loaded} / {total} cloud materials",
  },
  mat_sync_index_state_label: {
    zh: "索引状态",
    en: "Index",
  },
  mat_sync_installed_count_label: {
    zh: "已安装",
    en: "Installed",
  },
  mat_sync_update_count_label: {
    zh: "可更新",
    en: "Updates",
  },
  mat_sync_last_sync_label: {
    zh: "上次同步",
    en: "Last Sync",
  },
  mat_sync_last_sync_inline: {
    zh: "本地索引更新时间：{time}",
    en: "Local index updated: {time}",
  },
  mat_sync_state_missing: {
    zh: "未建立",
    en: "Missing",
  },
  mat_sync_state_ready: {
    zh: "正常",
    en: "Ready",
  },
  mat_sync_state_invalid: {
    zh: "异常",
    en: "Invalid",
  },
  mat_sync_state_unknown: {
    zh: "未知",
    en: "Unknown",
  },
  mat_sync_refresh_btn: {
    zh: "刷新云端目录",
    en: "Refresh Catalog",
  },
  mat_sync_load_more_btn: {
    zh: "加载更多",
    en: "Load More",
  },
  mat_sync_load_all_btn: {
    zh: "加载全部",
    en: "Load All",
  },
  mat_sync_status_failed: {
    zh: "读取云端耗材库失败",
    en: "Failed to load cloud material library",
  },
  mat_sync_catalog_not_configured: {
    zh: "尚未配置云端耗材库。本地耗材库仍可离线使用；配置 LUMINA_MATERIAL_REGISTRY_URL 后会显示云端耗材。",
    en: "Cloud material registry is not configured. The local material library remains available offline; configure LUMINA_MATERIAL_REGISTRY_URL to show cloud materials.",
  },
  mat_sync_catalog_refresh_success: {
    zh: "云端耗材目录已刷新。",
    en: "Cloud material catalog refreshed.",
  },
  mat_sync_refresh_success: {
    zh: "云端耗材同步完成。",
    en: "Cloud material sync completed.",
  },
  mat_sync_refresh_failed: {
    zh: "云端耗材同步失败",
    en: "Cloud material sync failed",
  },
  mat_sync_official_badge: {
    zh: "官方",
    en: "Official",
  },
  mat_sync_search_placeholder: {
    zh: "搜索品牌、名称、目录或 ID",
    en: "Search brand, name, directory, or ID",
  },
  mat_sync_filter_group_label: {
    zh: "云端耗材筛选",
    en: "Cloud material filters",
  },
  mat_sync_filter_all: {
    zh: "全部",
    en: "All",
  },
  mat_sync_filter_official: {
    zh: "官方",
    en: "Official",
  },
  mat_sync_filter_not_installed: {
    zh: "未安装",
    en: "Not Installed",
  },
  mat_sync_filter_updates: {
    zh: "可更新",
    en: "Updates",
  },
  mat_sync_filter_installed: {
    zh: "已安装",
    en: "Installed",
  },
  mat_sync_install_btn: {
    zh: "下载到本地",
    en: "Download",
  },
  mat_sync_update_btn: {
    zh: "更新到 {revisionId}",
    en: "Update to {revisionId}",
  },
  mat_sync_installed_btn: {
    zh: "已安装",
    en: "Installed",
  },
  mat_sync_local_available_btn: {
    zh: "本地已有版本",
    en: "Local revision available",
  },
  mat_sync_official_password_required_btn: {
    zh: "需要官方密码",
    en: "Official password required",
  },
  mat_sync_install_success: {
    zh: "耗材已下载并安装到本地。",
    en: "Material downloaded and installed locally.",
  },
  mat_sync_install_failed: {
    zh: "耗材下载失败",
    en: "Material download failed",
  },
  mat_sync_catalog_state_label: {
    zh: "状态",
    en: "Status",
  },
  mat_sync_catalog_state_not_installed: {
    zh: "未安装",
    en: "Not installed",
  },
  mat_sync_catalog_state_installed: {
    zh: "已安装",
    en: "Installed",
  },
  mat_sync_catalog_state_update_available: {
    zh: "有新版本",
    en: "Update available",
  },
  mat_sync_catalog_state_local_available: {
    zh: "本地已有版本",
    en: "Local revision available",
  },
  mat_sync_catalog_state_local_missing: {
    zh: "本地文件缺失",
    en: "Local files missing",
  },
  mat_sync_local_section_title: {
    zh: "本地已安装 / 版本回滚",
    en: "Local Installed / Rollback",
  },
  mat_sync_catalog_empty: {
    zh: "没有匹配的云端耗材。",
    en: "No matching cloud materials.",
  },
  mat_sync_admin_section_title: {
    zh: "贡献者 / 管理员入口",
    en: "Contributor / Admin",
  },
  mat_sync_upload_title: {
    zh: "测试服务器上传与审批",
    en: "Test Server Upload & Approval",
  },
  mat_sync_upload_empty: {
    zh: "上传耗材包后，可用官方密码批准为 official 耗材。",
    en: "After uploading a material package, approve it as official with the official password.",
  },
  mat_sync_upload_btn: {
    zh: "上传耗材包",
    en: "Upload Package",
  },
  mat_sync_upload_success: {
    zh: "耗材包已上传到待审核队列。",
    en: "Material package uploaded to the review queue.",
  },
  mat_sync_upload_failed: {
    zh: "耗材包上传失败",
    en: "Material package upload failed",
  },
  mat_sync_approve_official_btn: {
    zh: "批准为官方耗材",
    en: "Approve as Official",
  },
  mat_sync_approve_success: {
    zh: "耗材包已批准为官方耗材。",
    en: "Material package approved as official.",
  },
  mat_sync_approve_failed: {
    zh: "官方耗材审批失败",
    en: "Official approval failed",
  },
  mat_sync_approve_existing_title: {
    zh: "审批已有云端耗材",
    en: "Approve Existing Cloud Materials",
  },
  mat_sync_approve_existing_empty: {
    zh: "在上方云端耗材卡片勾选非 official 耗材后，可在这里批准为官方耗材。",
    en: "Select non-official cloud material cards above, then approve them as official here.",
  },
  mat_sync_approve_selected_summary: {
    zh: "已选择 {count} 个云端耗材，审批后会进入 official 频道。",
    en: "{count} cloud materials selected. Approval will publish them to the official channel.",
  },
  mat_sync_approve_selected_btn: {
    zh: "批准选中云端耗材为官方",
    en: "Approve Selected Cloud Materials",
  },
  mat_sync_approve_selected_success: {
    zh: "已将 {count} 个云端耗材批准为官方耗材。",
    en: "Approved {count} cloud materials as official.",
  },
  mat_sync_approve_package_path_invalid: {
    zh: "无法解析所选云端耗材的包路径。",
    en: "Could not resolve the selected cloud material package path.",
  },
  mat_sync_official_password_placeholder: {
    zh: "官方审批密码",
    en: "Official approval password",
  },
  mat_sync_package_path_label: {
    zh: "包路径",
    en: "Package Path",
  },
  mat_sync_package_size_label: {
    zh: "体积",
    en: "Size",
  },
  mat_sync_material_id_label: {
    zh: "耗材 ID",
    en: "Material ID",
  },
  mat_sync_revision_label: {
    zh: "版本",
    en: "Revision",
  },
  mat_sync_content_fingerprint_label: {
    zh: "内容指纹",
    en: "Fingerprint",
  },
  mat_sync_select_catalog_item_label: {
    zh: "选择云端耗材「{materialName}」",
    en: 'Select cloud material "{materialName}"',
  },
  mat_sync_rollback_btn: {
    zh: "回滚到 {revisionId}",
    en: "Rollback to {revisionId}",
  },
  mat_sync_rollback_success: {
    zh: "耗材版本已回滚。",
    en: "Material revision rolled back.",
  },
  mat_sync_rollback_failed: {
    zh: "耗材版本回滚失败",
    en: "Material rollback failed",
  },
  mat_sync_no_rollback: {
    zh: "暂无可回滚版本",
    en: "No rollback revision",
  },
  mat_gradient_library_selection_summary: {
    zh: "已选择 {selected} / {total} 个耗材",
    en: "Selected {selected} / {total} materials",
  },
  mat_gradient_library_select_item_label: {
    zh: "选择耗材「{materialName}」",
    en: 'Select material "{materialName}"',
  },
  mat_gradient_library_refresh_btn: {
    zh: "刷新耗材库",
    en: "Refresh Library",
  },
  mat_gradient_library_loading: {
    zh: "正在加载耗材库...",
    en: "Loading material library...",
  },
  mat_gradient_library_load_failed: {
    zh: "加载耗材库失败",
    en: "Failed to load material library",
  },
  mat_gradient_library_empty: {
    zh: "还没有已保存的耗材档案。先在「梯度卡提取」里保存一个耗材。",
    en: "No saved material archives yet. Save one from Gradient Card Extract first.",
  },
  mat_gradient_library_updated_at_label: {
    zh: "最近更新",
    en: "Last Updated",
  },
  mat_gradient_library_created_at_label: {
    zh: "创建时间",
    en: "Created",
  },
  mat_gradient_library_verification_count_label: {
    zh: "验证次数",
    en: "Verification Runs",
  },
  mat_gradient_library_usage_count_label: {
    zh: "使用次数",
    en: "Usage Count",
  },
  mat_gradient_library_usage_last_used: {
    zh: "最近使用：{when}",
    en: "Last used: {when}",
  },
  mat_gradient_library_directory_label: {
    zh: "目录名",
    en: "Directory",
  },
  mat_gradient_library_brand_label: {
    zh: "品牌",
    en: "Brand",
  },
  mat_gradient_library_brand_unassigned: {
    zh: "未分组",
    en: "Unassigned",
  },
  basic_material_picker_brand_unassigned: {
    zh: "未分组",
    en: "Unassigned",
  },
  mat_gradient_library_fit_error_label: {
    zh: "拟合误差",
    en: "Fit Error",
  },
  mat_gradient_library_layer_height_label: {
    zh: "层高",
    en: "Layer Height",
  },
  mat_gradient_library_edit_btn: {
    zh: "编辑信息",
    en: "Edit Details",
  },
  mat_gradient_library_edit_title: {
    zh: "编辑耗材信息",
    en: "Edit Material Details",
  },
  mat_gradient_library_edit_desc: {
    zh: "你正在编辑目录 {directoryName} 的显示名称、品牌与颜色。",
    en: "You are editing the display name, brand and color for directory {directoryName}.",
  },
  mat_gradient_library_edit_color_label: {
    zh: "显示颜色",
    en: "Display Color",
  },
  mat_gradient_library_edit_color_hex_placeholder: {
    zh: "#RRGGBB 色号",
    en: "#RRGGBB hex",
  },
  mat_gradient_library_edit_color_invalid_hex: {
    zh: "色号必须是 #RGB 或 #RRGGBB 格式",
    en: "Color must be #RGB or #RRGGBB format",
  },
  mat_gradient_library_edit_color_hint: {
    zh: "可使用颜色选择器或直接输入色号；修改后会替换测量得到的显示颜色。",
    en: "Use the picker or enter a hex code; this overrides the measured display color.",
  },
  mat_gradient_library_edit_cancel_btn: {
    zh: "取消",
    en: "Cancel",
  },
  mat_gradient_library_edit_save_btn: {
    zh: "保存修改",
    en: "Save Changes",
  },
  mat_gradient_library_edit_success: {
    zh: "耗材信息已更新。",
    en: "Material details updated.",
  },
  mat_gradient_library_edit_failed: {
    zh: "更新耗材信息失败",
    en: "Failed to update material details",
  },
  mat_gradient_library_reverify_btn: {
    zh: "再次验证",
    en: "Re-Verify",
  },
  mat_gradient_library_cloud_upload_btn: {
    zh: "上传到云端",
    en: "Upload to Cloud",
  },
  mat_gradient_library_cloud_upload_password_prompt: {
    zh: "请输入官方审批密码，用于上传这个耗材到云端待审核队列。",
    en: "Enter the official approval password to upload this material to the cloud review queue.",
  },
  mat_gradient_library_cloud_upload_success: {
    zh: "耗材已提交到云端待审核队列。",
    en: "Material uploaded to the cloud review queue.",
  },
  mat_gradient_library_cloud_upload_failed: {
    zh: "上传到云端失败",
    en: "Failed to upload material to cloud",
  },
  mat_gradient_library_delete_btn: {
    zh: "删除耗材",
    en: "Delete Material",
  },
  mat_gradient_library_duplicate_badge: {
    zh: "同名 {count} 份",
    en: "{count} copies",
  },
  mat_gradient_library_card_meta: {
    zh: "目录：{directoryName} · 创建：{createdAt} · 最近更新：{updatedAt}",
    en: "Directory: {directoryName} · Created: {createdAt} · Last updated: {updatedAt}",
  },
  mat_gradient_library_delete_confirm: {
    zh: "确认删除这份耗材「{materialName}」？\n目录：{directoryName}\n最近更新：{updatedAt}\n此操作只删除当前服务器上的这份本地耗材档案，且不可撤销。",
    en: 'Delete this material copy "{materialName}"?\nDirectory: {directoryName}\nLast updated: {updatedAt}\nThis only deletes this local material archive on the current server and cannot be undone.',
  },
  mat_gradient_library_delete_success: {
    zh: "耗材已删除。",
    en: "Material deleted.",
  },
  mat_gradient_library_delete_failed: {
    zh: "删除耗材失败",
    en: "Failed to delete material",
  },
  mat_gradient_library_export_requires_selection: {
    zh: "请先至少选择一个耗材再导出。",
    en: "Select at least one material before exporting.",
  },
  mat_gradient_library_export_success: {
    zh: "已导出所选耗材。",
    en: "Selected materials exported.",
  },
  mat_gradient_library_export_failed: {
    zh: "导出耗材失败",
    en: "Failed to export materials",
  },
  mat_gradient_library_import_success: {
    zh: "耗材导入完成。",
    en: "Materials imported.",
  },
  mat_gradient_library_import_failed: {
    zh: "导入耗材失败",
    en: "Failed to import materials",
  },
  mat_gradient_library_show_history_btn: {
    zh: "展开验证历史",
    en: "Show Verification History",
  },
  mat_gradient_library_hide_history_btn: {
    zh: "收起验证历史",
    en: "Hide Verification History",
  },
  mat_gradient_library_history_title: {
    zh: "验证历史",
    en: "Verification History",
  },
  mat_gradient_library_history_close_btn: {
    zh: "关闭",
    en: "Close",
  },
  mat_gradient_library_history_empty: {
    zh: "当前还没有可展示的验证历史摘要。",
    en: "No verification history summary is available yet.",
  },
  mat_gradient_library_history_run_label: {
    zh: "第 {index} 次验证",
    en: "Run {index}",
  },
  mat_gradient_library_history_time_label: {
    zh: "验证时间",
    en: "Verified At",
  },
  mat_gradient_library_history_color_label: {
    zh: "估算颜色",
    en: "Estimated Color",
  },
  mat_gradient_library_history_rmse_label: {
    zh: "线性 RMSE",
    en: "Linear RMSE",
  },
  mat_gradient_library_history_e_label: {
    zh: "E 参数",
    en: "E Parameters",
  },
  mat_gradient_library_history_k_label: {
    zh: "k 参数",
    en: "k Parameters",
  },
  mat_gradient_library_history_white_c0_label: {
    zh: "白底 C0",
    en: "White C0",
  },
  mat_gradient_library_history_black_c0_label: {
    zh: "黑底 C0",
    en: "Black C0",
  },
  mat_gradient_library_history_orientation_label: {
    zh: "识别方向",
    en: "Detected Orientation",
  },
  mat_gradient_library_history_orientation_value: {
    zh: "白底 {white} / 黑底 {black}",
    en: "White {white} / Black {black}",
  },
  mat_gradient_verification_mode_title: {
    zh: "当前正在进行耗材复验",
    en: "Material Re-Verification Active",
  },
  mat_gradient_verification_mode_desc: {
    zh: "目标耗材：{materialName}。当前已累计 {count} 次验证；本次保存后会继续聚合参数。",
    en: "Target material: {materialName}. There are already {count} verification runs; saving this run will further aggregate the parameters.",
  },
  mat_gradient_verification_name_label: {
    zh: "复验目标耗材",
    en: "Verification Target Material",
  },
  mat_gradient_verification_name_desc: {
    zh: "当前为已有耗材做复验。已累计 {count} 次验证，本次结果会并入同一档案。",
    en: "You are re-verifying an existing material. There are already {count} runs and this result will be merged into the same archive.",
  },
  mat_gradient_save_verification_btn: {
    zh: "保存验证结果",
    en: "Save Verification Result",
  },
  mat_gradient_save_merge_btn: {
    zh: "合并结果",
    en: "Merge Result",
  },
  mat_gradient_save_override_btn: {
    zh: "覆盖结果",
    en: "Override",
  },
  mat_gradient_material_saved_success: {
    zh: "耗材保存成功",
    en: "Material saved successfully",
  },
  mat_gradient_verification_saved_success: {
    zh: "耗材校验保存成功（已聚合 {count} 次校验结果）",
    en: "Verification saved successfully ({count} runs aggregated)",
  },
  mat_gradient_cancel_verification_btn: {
    zh: "取消复验",
    en: "Cancel Re-Verification",
  },
  ext_workflow_label: {
    zh: "工作流模式",
    en: "Workflow",
  },
  ext_single_stage_upload_title: {
    zh: "Single-Stage 数据集上传",
    en: "Single-Stage Dataset Upload",
  },
  ext_single_stage_upload_desc: {
    zh: "上传按 {substrate}/{color}/ 结构打包的 ZIP 数据集",
    en: "Upload a ZIP dataset organized as {substrate}/{color}/",
  },
  ext_single_stage_zip_label: {
    zh: "数据集 ZIP",
    en: "Dataset ZIP",
  },
  ext_single_stage_extract_btn: {
    zh: "提取 1_single_stage.json",
    en: "Extract 1_single_stage.json",
  },
  ext_single_stage_download_json: {
    zh: "下载 1_single_stage.json",
    en: "Download 1_single_stage.json",
  },
  ext_single_stage_fit_btn: {
    zh: "继续拟合 Stage A",
    en: "Fit Stage A",
  },
  ext_single_stage_download_stage_a: {
    zh: "导出预测模型参数 (stage_A_parameters.json)",
    en: "Export Predictive Model Parameters (stage_A_parameters.json)",
  },
  ext_single_stage_summary_title: {
    zh: "数据集摘要",
    en: "Dataset Summary",
  },
  ext_single_stage_fit_summary_title: {
    zh: "Stage A 拟合摘要",
    en: "Stage A Fit Summary",
  },
  ext_single_stage_warnings_title: {
    zh: "提取警告",
    en: "Extraction Warnings",
  },
  cal_workflow_legacy: {
    zh: "传统 LUT",
    en: "Legacy LUT",
  },
  cal_workflow_single_stage: {
    zh: "梯度卡",
    en: "Gradient Card",
  },
  ext_workflow_legacy: {
    zh: "传统 LUT",
    en: "Legacy LUT",
  },
  ext_workflow_single_stage: {
    zh: "梯度卡",
    en: "Gradient Card",
  },
  material_recipe_title: {
    zh: "耗材配方查询",
    en: "Material Recipe Query",
  },
  material_recipe_desc: {
    zh: "从耗材库中按观赏面朝基底的顺序选择多层耗材，使用 Beer-Lambert 正向模型直接预测叠层颜色，不依赖任何 LUT。层数不受 5 层限制。",
    en: "Pick materials from the library from the viewing face toward the substrate; the Beer-Lambert forward model predicts the stacked color directly, without any LUT. Layer count is not capped at 5.",
  },
  material_recipe_layers_heading: {
    zh: "配方层（观赏面 → 基底）",
    en: "Recipe layers (viewing face → substrate)",
  },
  material_recipe_layers_empty: {
    zh: "尚未添加任何层。点击下方耗材以追加到靠近基底的一侧。",
    en: "No layers yet. Click a material below to append it toward the substrate side.",
  },
  material_recipe_visible_face: {
    zh: "观赏面",
    en: "Viewing face",
  },
  material_recipe_substrate_side: {
    zh: "基底侧",
    en: "Substrate side",
  },
  material_recipe_layers_count: {
    zh: "已选 {count} 层",
    en: "{count} layer(s)",
  },
  material_recipe_layer_label: {
    zh: "第 {index} 层",
    en: "Layer {index}",
  },
  material_recipe_remove_layer: {
    zh: "移除该层",
    en: "Remove this layer",
  },
  material_recipe_clear: {
    zh: "清空",
    en: "Clear",
  },
  material_recipe_undo: {
    zh: "撤销最后一层",
    en: "Undo last layer",
  },
  material_recipe_reverse: {
    zh: "反序",
    en: "Reverse",
  },
  material_recipe_search_placeholder: {
    zh: "搜索耗材名 / 品牌 / 目录名",
    en: "Search material name / brand / directory",
  },
  material_recipe_search_empty: {
    zh: "未找到匹配的耗材",
    en: "No materials match the search",
  },
  material_recipe_search_clear: {
    zh: "清除搜索",
    en: "Clear search",
  },
  material_recipe_query: {
    zh: "计算混色",
    en: "Compute color",
  },
  material_recipe_query_loading: {
    zh: "计算中...",
    en: "Computing...",
  },
  material_recipe_substrate_label: {
    zh: "基底",
    en: "Substrate",
  },
  material_recipe_substrate_white: {
    zh: "白色基底",
    en: "White",
  },
  material_recipe_substrate_black: {
    zh: "黑色基底",
    en: "Black",
  },
  material_recipe_layer_height_label: {
    zh: "层厚 (mm)",
    en: "Layer height (mm)",
  },
  material_recipe_palette_heading: {
    zh: "耗材库",
    en: "Material library",
  },
  material_recipe_palette_empty: {
    zh: "耗材库为空，请先在「耗材库」或「梯度卡提取」页面建立耗材。",
    en: "Material library is empty. Use the Material Library or Gradient Extractor first to create materials.",
  },
  material_recipe_palette_loading: {
    zh: "加载耗材库...",
    en: "Loading material library...",
  },
  material_recipe_palette_load_failed: {
    zh: "加载耗材库失败",
    en: "Failed to load material library",
  },
  material_recipe_result_heading: {
    zh: "预测颜色",
    en: "Predicted color",
  },
  material_recipe_result_pending: {
    zh: "添加至少一层并点击「计算混色」即可查看预测结果。",
    en: "Add at least one layer then click \"Compute color\" to see the prediction.",
  },
  material_recipe_query_failed: {
    zh: "配方计算失败",
    en: "Recipe computation failed",
  },
  material_recipe_close_error: {
    zh: "关闭错误",
    en: "Close error",
  },
  material_recipe_result_rgb_value: {
    zh: "RGB {value}",
    en: "RGB {value}",
  },
  material_recipe_result_meta: {
    zh: "{count} 层 · {height} mm · {substrate}",
    en: "{count} layer(s) · {height} mm · {substrate}",
  },
  material_recipe_add_to_collection: {
    zh: "添加到队列",
    en: "Add to queue",
  },
  material_recipe_already_in_collection: {
    zh: "已在队列中",
    en: "Already in queue",
  },
  material_recipe_collection_title: {
    zh: "配方队列",
    en: "Recipe queue",
  },
  material_recipe_collection_count: {
    zh: "{count} 个配方",
    en: "{count} recipe(s)",
  },
  material_recipe_collection_empty: {
    zh: "队列为空。计算配方颜色后可添加到队列。",
    en: "Queue is empty. Compute a recipe color then add it to the queue.",
  },
  material_recipe_collection_clear: {
    zh: "清空队列",
    en: "Clear queue",
  },
  material_recipe_remove_from_collection: {
    zh: "移除",
    en: "Remove",
  },
  material_recipe_swatch_block_size: {
    zh: "色块尺寸",
    en: "Block size",
  },
  material_recipe_swatch_gap: {
    zh: "间距",
    en: "Gap",
  },
  material_recipe_swatch_cols: {
    zh: "列数",
    en: "Columns",
  },
  material_recipe_swatch_structure: {
    zh: "结构模式",
    en: "Structure mode",
  },
  material_recipe_swatch_single_sided: {
    zh: "单面",
    en: "Single-sided",
  },
  material_recipe_swatch_double_sided: {
    zh: "双面",
    en: "Double-sided",
  },
  material_recipe_generate_swatch: {
    zh: "生成验证色块",
    en: "Generate swatch",
  },
  material_recipe_generating_swatch: {
    zh: "生成中...",
    en: "Generating...",
  },
  material_recipe_download_swatch: {
    zh: "下载 3MF",
    en: "Download 3MF",
  },
  material_recipe_generate_swatch_failed: {
    zh: "色块生成失败",
    en: "Swatch generation failed",
  },
  material_recipe_download_swatch_failed: {
    zh: "色块下载失败",
    en: "Swatch download failed",
  },
  material_recipe_swatch_legend_alt: {
    zh: "色块图例",
    en: "Swatch legend",
  },
};
