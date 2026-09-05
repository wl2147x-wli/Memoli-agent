/* =====================================================================
   CowAgent 控制台 - 主应用程序脚本
   ===================================================================== */

// =====================================================================
// 版本 — 从后端获取（单一来源：/VERSION 文件）
// =====================================================================
let APP_VERSION = '';

// =====================================================================
// 国际化
// =====================================================================
const I18N = {
    zh: {
        console: '控制台',
        nav_chat: '对话', nav_manage: '管理', nav_monitor: '监控',
        menu_chat: '对话', menu_agents: '智能体', menu_config: '配置', menu_skills: '技能',
        agents_page_title: '智能体团队', agents_page_desc: '管理团队中的智能体成员',
        agents_create: '创建智能体',
        agents_name_placeholder: '智能体名称',
        agents_name_required: '请填写名称',
        agents_stale: '列表已更新，请刷新后重试',
        agents_id_placeholder: '留空则自动生成',
        agents_id_tip: '智能体的唯一标识，创建后不可修改。仅支持小写英文、数字和连字符（-），如 coding-agent。留空则根据名称自动生成。',
        agents_id_invalid: 'ID 需以字母或数字开头，仅支持字母、数字、下划线和连字符，最长 64 位',
        agents_avatar: '头像',
        agents_tab_profile: '概况',
        agents_tab_skills: '能力',
        agents_tab_files: '核心文件',
        agents_core_edit: '编辑',
        agents_core_preview: '预览',
        agents_core_file_agent: '智能体设定',
        agents_core_file_user: '用户信息',
        agents_core_file_rule: '工作空间规则',
        agents_core_file_memory: '长期记忆',
        agents_default: '默认',
        agents_archived: '已归档',
        agents_chat: '开始对话',
        agents_delete: '删除',
        agents_delete_title: '删除智能体',
        agents_delete_confirm: '确定删除智能体「{name}」吗？其工作空间和会话将一并移除，且无法恢复。',
        agents_pick_hint: '选择智能体',
        agents_clone_label: '从已有智能体复制',
        agents_clone_hint: '复制其配置、技能与知识作为起点',
        agents_avatar_upload: '上传图片',
        agents_clone_none: '空白',
        agents_clone_from: '{name}',
        agents_name: '名称',
        agents_saved: '已保存',
        agents_save_failed: '保存失败',
        agents_no_desc: '暂无职责',
        agents_description: '职责',
        agents_description_placeholder: '该智能体负责哪些工作、在什么场景被使用',
        agents_description_hint: '用于多智能体协作时的任务分配',
        agents_model: '默认模型',
        agents_model_follows_global: '跟随全局配置',
        agents_model_default_hint: '默认使用主模型，在「模型配置」中修改。',
        agents_skills_all: '使用全部已安装技能',
        agents_skills_pick: '只启用勾选的技能',
        agents_knowledge: '知识库',
        agents_knowledge_shared: '共享',
        agents_knowledge_own: '独立',
        agents_knowledge_hint: '共享：与团队读写同一个知识库\n独立：拥有专属知识库，互不影响',
        agents_knowledge_working: '处理中…',
        agents_knowledge_failed: '切换失败',
        agents_empty: '还没有智能体。创建一个，开始组团队。',
        agents_select_hint: '从左侧选择一个智能体进行配置',
        agents_pick_tip: '切换当前智能体',
        team_members: '当前会话成员',
        team_invite: '添加到当前会话',
        team_remove: '移出这个会话',
        composer_agent_owner: '主',
        channel_bound_agent: '绑定智能体',
        channel_bound_default: '默认',
        channel_bound_agent_hint: '第一个为默认智能体，负责接收消息并可委派给其他成员',
        channel_team_none: '未选择',
        channel_team_no_candidates: '暂无可选的智能体',
        settings_tab_basic: '基础配置',
        settings_tab_models: '模型配置',
        knowledge_shared_hint: '知识库默认全员共享，在侧栏「知识」查看和编辑。',
        menu_memory: '记忆', menu_knowledge: '知识', menu_channels: '通道', menu_tasks: '定时',
        menu_logs: '日志',
        models_title: '模型管理',
        models_desc: '统一管理对话、图像、语音、向量、搜索能力',
        models_section_vendors: '厂商凭据',
        models_section_vendors_desc: '一处配置，多个模型能力共享',
        models_section_capabilities: '模型能力',
        models_add_vendor: '添加厂商',
        models_provider: '厂商',
        models_model: '模型',
        models_voice: '音色',
        models_configured: '已配置',
        models_not_configured: '未配置',
        models_pick_to_configure: '选择以配置',
        models_clear_credential: '清除凭据',
        models_base_default_hint: '留空将使用官方默认地址',
        models_base_default: '默认',
        models_custom_vendor_label: '自定义',
        models_custom_name: '名称',
        models_custom_delete: '删除',
        models_custom_delete_confirm_title: '删除自定义厂商',
        models_custom_delete_confirm_msg: '确定删除该自定义厂商吗？此操作无法撤销。',
        models_custom_name_required: '请填写名称',
        models_custom_base_required: '请填写 API Base',
        models_custom_edit_title: '编辑自定义厂商',
        models_custom_add_title: '添加自定义厂商',
        models_capability_chat: '主模型',
        models_capability_chat_desc: '用于基础对话和 Agent 推理',
        models_capability_chat_fallback: '主模型兜底',
        models_capability_chat_fallback_desc: '仅在主模型彻底失败（重试耗尽）后接管',
        models_fallback_enable: '启用兜底模型',
        models_fallback_config: '兜底模型',
        models_fallback_config_tip: '配置主模型兜底：主模型彻底失败后接管',
        models_fallback_modal_title: '主模型兜底',
        models_fallback_modal_desc: '当主模型重试次数用尽仍然失败时，自动切换到兜底模型完成本轮回复',
        models_fallback_badge_on: '兜底已启用',
        models_capability_vision: '图像理解',
        models_capability_vision_desc: '识别图片内容，用于图像识别工具',
        models_capability_image: '图像生成',
        models_capability_image_desc: '生成图片，用于图像生成技能',
        models_auto_using: '当前优先使用',
        models_capability_asr: '语音识别',
        models_capability_asr_desc: '语音转文字',
        models_capability_tts: '语音合成',
        models_capability_tts_desc: '文字转语音',
        models_capability_embedding: '向量',
        models_capability_embedding_desc: '用于记忆与知识的向量化检索',
        models_capability_search: '联网搜索',
        models_capability_search_desc: '实时网页检索能力，用于搜索工具',
        models_strategy_auto: '自动',
        models_search_strategy_label: '策略',
        models_search_strategy_fixed: '指定',
        models_search_strategy_auto_hint: '从已配置厂商中自动选择',
        models_search_strategy_fixed_hint: '指定使用搜索厂商',
        models_pending_config: '待配置',
        models_search_available_label: '可用搜索厂商：',
        models_search_none_configured: '暂未启用任何搜索厂商，点击添加',
        models_search_add_provider: '添加厂商',
        models_search_add_desc: '选择一个搜索厂商进行配置',
        models_search_bocha_title: '配置博查 API Key',
        models_search_bocha_desc: '前往博查开放平台创建 API Key',
        models_search_anysearch_title: '配置 AnySearch API Key',
        models_search_anysearch_desc: '前往 anysearch.com 控制台创建 API Key。',
        models_search_serply_title: '配置 Serply API Key',
        models_search_serply_desc: '前往 serply.io 控制台创建 API Key。',
        models_search_edit_hint: '点击修改配置',
        models_unavailable: '不可用',
        models_set_via_env: '通过环境变量启用',
        models_dim_label: '维度',
        models_save_success: '已保存',
        models_save_failed: '保存失败',
        models_cleared: '已清除',
        models_clear_failed: '清除失败',
        models_embedding_change_title: '更改向量模型',
        models_embedding_change_msg: '切换向量模型后，已有索引将失效，需要重建。是否继续？',
        models_embedding_saved_title: '向量模型已更新',
        models_embedding_saved_msg: '请在聊天框输入 /memory rebuild-index 重建索引。',
        models_embedding_saved_ok: '去执行',
        models_pick_provider: '待选择',
        models_manage_api_key: '管理 API Key',
        models_clear_confirm_title: '清除厂商凭据',
        models_clear_confirm_msg: '确认清除该厂商的 API Key 与 Base URL 吗？相关能力将不再可用。',
        cancel: '取消',
        save: '保存',
        ok: '确定',
        knowledge_title: '知识库', knowledge_desc: '浏览和探索你的知识库',
        knowledge_tab_docs: '文档', knowledge_tab_graph: '图谱',
        knowledge_loading: '加载知识库中...', knowledge_loading_desc: '知识页面将显示在这里',
        knowledge_select_hint: '选择一个文档查看', knowledge_empty_hint: '暂无知识页面',
        knowledge_empty_guide: '在对话中发送文档、链接或主题给 Agent，它会自动整理到你的知识库中。',
        knowledge_go_chat: '开始对话',
        knowledge_new: '新建',
        knowledge_new_category: '新建分类',
        knowledge_new_document: '新建文档',
        knowledge_import_documents: '导入文档',
        welcome_subtitle: '我可以帮你解答问题、管理计算机、创造和执行技能，并通过<br>长期记忆和知识库不断成长',
        example_sys_title: '系统管理', example_sys_text: '查看工作空间里有哪些文件',
        example_task_title: '定时任务', example_task_text: '1分钟后提醒我检查服务器',
        example_code_title: '编程助手', example_code_text: '搜索AI资讯并生成可视化网页报告',
        example_knowledge_title: '知识库', example_knowledge_text: '查看知识库当前文档情况',
        example_skill_title: '技能系统', example_skill_text: '查看所有支持的工具和技能',
        example_web_title: '指令中心', example_web_text: '查看全部命令',
        slash_help: '显示命令帮助',
        slash_status: '查看运行状态',
        slash_context: '查看对话上下文',
        slash_context_clear: '清除对话上下文',
        slash_compact: '压缩较早的对话以释放上下文',
        slash_skill_list: '查看已安装技能',
        slash_skill_list_remote: '浏览技能广场',
        slash_skill_search: '搜索技能',
        slash_skill_install: '安装技能 (名称或 GitHub URL)',
        slash_skill_uninstall: '卸载技能',
        slash_skill_info: '查看技能详情',
        slash_skill_enable: '启用技能',
        slash_skill_disable: '禁用技能',
        slash_memory_dream: '手动触发记忆蒸馏 (可指定天数, 默认3)',
        slash_knowledge: '查看知识库统计',
        slash_knowledge_list: '查看知识库文件树',
        slash_knowledge_on: '开启知识库',
        slash_knowledge_off: '关闭知识库',
        slash_config: '查看当前配置',
        slash_cancel: '中止当前正在运行的 Agent 任务',
        slash_steer: '向当前正在运行的 Agent 任务注入引导指令',
        steer_active: '引导当前任务',
        slash_logs: '查看最近日志',
        slash_version: '查看版本',
        input_placeholder: '输入消息，/ 使用指令，@ 引用智能体或文件',
        config_title: '配置管理', config_desc: '管理模型和 Agent 配置',
        config_model: '模型配置', config_agent: 'Agent 配置',
        config_language: '语言', config_language_hint: '界面展示、命令文案、系统提示词等使用的语言（与右上角切换同步）',
        config_system: '系统',
        config_task_notify: '任务通知', config_task_notify_hint: '窗口在后台且任务完成或失败时发送浏览器通知，点击可跳转会话',
        config_task_notify_sound: '通知声音', config_task_notify_sound_hint: '通知开启时可单独关闭提示音',
        config_task_notify_blocked: '系统通知已被浏览器屏蔽，请点击地址栏左侧图标 → 通知 → 允许后刷新页面',
        notify_task_done: '任务完成',
        notify_task_error: '任务失败',
        config_model_advanced: '高级配置',
        config_channel: '通道配置',
        config_agent_enabled: 'Agent 模式',
        config_max_tokens: '最大上下文 Token', config_max_tokens_hint: '对话中 Agent 能输入的最大 Token 长度，超过后会智能压缩处理',
        config_max_turns: '最大记忆轮次', config_max_turns_hint: '一问一答为一轮，超过后会智能压缩处理',
        config_max_steps: '最大执行步数', config_max_steps_hint: '单次对话中 Agent 最多调用工具的次数',
        config_enable_thinking: '深度思考', config_enable_thinking_hint: '是否启用深度思考模式',
        config_reasoning_effort: '思考强度', config_reasoning_effort_hint: '按当前模型厂商支持的原生枚举发送',
        config_subagent: '子 Agent', config_subagent_hint: '把可独立完成的任务交给子 Agent，多个任务并行执行，只把结论带回主对话',
        config_self_evolution: '自主进化', config_self_evolution_hint: '会话空闲后自动复盘，沉淀记忆、优化技能、处理未完成事项',
        evolution_badge: '自主学习',
        config_channel_type: '通道类型',
        config_provider: '模型厂商', config_model_name: '模型',
        config_custom_model_hint: '输入自定义模型名称',
        config_save: '保存', config_saved: '已保存',
        config_save_error: '保存失败',
        config_custom_option: '自定义',
        config_custom_tip: '接口需遵循 OpenAI API 协议',
        config_security: '安全设置', config_password: '访问密码',
        config_password_hint: '留空则不启用密码保护',
        config_permission: '默认权限',
        config_permission_hint: '新会话的默认权限范围，决定 Agent 能修改哪些文件、能执行哪些命令',
        config_permission_desc: '新会话默认使用该权限；单个会话可在输入框下方单独调整',
        config_password_changed: '密码已更新',
        config_password_cleared: '密码已清除',
        config_password_security_warning: '⚠️ 警告：目前密码为空且对外连接埠开放，建议重启服务，或检查是否调整监听位址绑定。',
        skills_title: '技能管理', skills_desc: '查看、启用或禁用 Agent 工具和技能', skills_hub_btn: '探索技能广场',
        skills_loading: '加载技能中...', skills_loading_desc: '技能加载后将显示在此处',
        tools_section_title: '内置工具', tools_loading: '加载工具中...',
        skills_section_title: '技能', skill_enable: '启用', skill_disable: '禁用',
        skill_toggle_error: '操作失败，请稍后再试',
        skill_open_hint: '点击查看技能内容',
        skill_back: '返回列表',
        skill_load_failed: '读取技能内容失败',
        skill_builtin_readonly: '内置技能不可编辑（重启会覆盖）',
        memory_title: '记忆管理', memory_desc: '查看 Agent 记忆文件和内容',
        memory_tab_files: '记忆文件', memory_tab_dreams: '自主进化',
        memory_loading: '加载记忆文件中...', memory_loading_desc: '记忆文件将显示在此处',
        memory_back: '返回列表',
        memory_col_name: '文件名', memory_col_type: '类型', memory_col_size: '大小', memory_col_updated: '更新时间',
        channels_title: '通道管理', channels_desc: '管理已接入的消息通道',
        channels_add: '接入通道', channels_disconnect: '断开',
        channels_save: '保存配置', channels_saved: '已保存', channels_save_error: '保存失败',
        channels_restarted: '已保存并重启',
        channels_connect_btn: '接入', channels_cancel: '取消',
        channels_select_placeholder: '选择要接入的通道...',
        channels_empty: '暂未接入任何通道', channels_empty_desc: '点击右上角「接入通道」按钮开始配置',
        channels_disconnect_confirm: '确认断开该通道？配置将保留但通道会停止运行。',
        channels_connected: '已接入', channels_connecting: '接入中...',
        weixin_scan_title: '微信扫码登录', weixin_scan_desc: '请使用微信扫描下方二维码',
        weixin_scan_loading: '正在获取二维码...', weixin_scan_waiting: '等待扫码...',
        weixin_scan_scanned: '已扫码，请在手机上确认', weixin_scan_expired: '二维码已过期，正在刷新...',
        weixin_scan_success: '登录成功，正在启动通道...', weixin_scan_fail: '获取二维码失败',
        weixin_qr_tip: '二维码约2分钟后过期',
        wecom_scan_btn: '扫码创建企微机器人', wecom_scan_desc: '使用企业微信扫码，一键创建智能机器人',
        wecom_scan_success: '创建成功，正在启动通道...',
        wecom_scan_fail: '创建失败',
        wecom_mode_scan: '扫码接入', wecom_mode_manual: '手动填写',
        feishu_scan_btn: '一键创建飞书应用',
        feishu_scan_desc: '使用飞书 App 扫码，自动创建应用并预置全部权限与事件订阅',
        feishu_scan_replace_desc: '使用飞书 App 扫码创建新机器人，将覆盖当前的 App ID / Secret',
        feishu_scan_loading: '正在向飞书申请二维码...',
        feishu_scan_waiting: '等待扫码...',
        feishu_scan_tip: '二维码 10 分钟内有效，仅供一次扫描',
        feishu_scan_open_link: '或点击此处在浏览器中打开',
        feishu_scan_success: '应用创建成功，正在启动通道...',
        feishu_scan_expired: '二维码已过期，请重试',
        feishu_scan_denied: '已取消授权',
        feishu_scan_fail: '创建失败',
        feishu_scan_retry: '重试',
        feishu_sdk_downloading: '正在下载飞书组件...',
        feishu_sdk_downloading_tip: '首次启用需要下载，约 1MB，稍后自动继续',
        feishu_mode_scan: '扫码创建', feishu_mode_manual: '手动填写',
        tasks_title: '定时任务', tasks_desc: '查看和管理定时任务',
        tasks_coming: '即将推出', tasks_coming_desc: '定时任务管理功能即将在此提供',
        task_add_btn: '新增任务',
        task_edit_title: '编辑定时任务',
        task_add_title: '新增定时任务',
        task_name: '任务名称',
        task_enabled: '启用任务',
        task_schedule_type: '调度类型',
        task_schedule_cron: 'Cron 表达式',
        task_schedule_interval: '固定间隔',
        task_schedule_once: '一次性任务',
        task_cron_expression: 'Cron 表达式',
        task_cron_hint: '格式: 分 时 日 月 周，例如 "0 9 * * *" 表示每天 9:00',
        task_interval_seconds: '间隔秒数',
        task_interval_hint: '最小 60 秒，例如 3600 表示每小时执行一次',
        task_once_time: '执行时间',
        task_action_type: '动作类型',
        task_action_send_message: '发送消息',
        task_action_agent_task: 'AI 任务',
        task_channel_type: '通道类型',
        task_channel_hint: '选择定时消息发送的通道',
        task_message_content: '消息内容',
        task_task_description: '任务描述',
        task_delete_btn: '删除任务',
        task_delete_confirm_title: '删除定时任务',
        task_delete_confirm_msg: '确定删除该定时任务吗？此操作无法撤销。',
        task_run_now: '立即执行',
        task_run_confirm_title: '立即执行任务',
        task_run_confirm_msg: '该任务会立即向已配置的通道和接收者发送内容。是否继续？',
        task_run_started: '已开始执行',
        task_run_failed: '执行失败',
        logs_title: '日志', logs_desc: '实时日志输出 (run.log)',
        logs_live: '实时', logs_coming_msg: '日志流即将在此提供。将连接 run.log 实现类似 tail -f 的实时输出。',
        new_chat: '新对话',
        new_team_chat: '多智能体对话',
        new_team_chat_hint: '选择参与本次对话的智能体，第一个为会话的默认智能体。',
        new_team_chat_owner: '默认',
        new_team_chat_start: '开始对话',
        new_team_chat_min: '至少选择两个智能体',
        session_history: '历史会话',
        ws_toggle: '工作空间', ws_tab_preview: '预览', ws_tab_files: '文件',
        ws_default_workspace: '默认空间', ws_sel_title: '选择工作空间',
        ws_sel_default_hint: '使用默认工作空间（~/cow）', ws_sel_recents: '最近使用',
        ws_sel_open: '打开项目…', ws_sel_new: '新建项目', ws_sel_new_placeholder: '项目名称',
        ws_sel_create: '创建', ws_sel_up: '上一级',
        ws_sel_new_subtitle: '将在 {root} 下创建新项目目录', ws_sel_new_hint: '仅填写项目名称，不含路径分隔符',
        ws_sel_name_required: '请输入项目名称', ws_sel_name_no_slash: '项目名称不能包含 / 或 \\',
        ws_sel_open_here: '打开此目录', ws_sel_dblclick_hint: '双击进入子目录，单击选中',
        ws_sel_no_subdirs: '此目录下没有子文件夹', ws_sel_drives: '此电脑',
        ws_open_external: '在新标签页打开', ws_download: '下载', ws_copy_path: '复制路径',
        ws_close: '关闭', ws_refresh: '刷新', ws_preview: '预览',
        ws_search_placeholder: '搜索文件',
        ws_preview_empty: '选择一个文件进行预览',
        ws_preview_failed: '预览失败',
        ws_link_not_found: '工作空间中找不到该文件',
        ws_no_inline_preview: '该类型不支持内嵌预览',
        ws_empty_dir: '空目录', ws_no_results: '没有匹配的文件',
        ws_truncated: '文件过多，仅显示部分',
        ws_edit: '编辑', ws_edit_save: '保存 (Ctrl+S)', ws_edit_cancel: '退出编辑',
        ws_edit_saved: '已保存',
        ws_edit_load_failed: '打开编辑器失败',
        ws_edit_save_failed: '保存失败',
        ws_edit_too_large: '文件过大，无法在面板中编辑',
        ws_edit_unsupported: '该类型不支持编辑',
        ws_edit_encoding: '该文件不是 UTF-8 编码，编辑会损坏内容',
        ws_edit_conflict_title: '文件已被改动',
        ws_edit_conflict_msg: '这个文件在你编辑期间被改动过（可能是 Agent 写入的）。覆盖保存会丢弃磁盘上的新内容。',
        ws_edit_overwrite: '覆盖保存',
        ws_edit_discard_title: '放弃未保存的修改？',
        ws_edit_discard_msg: '当前文件有未保存的修改，继续操作会丢失这些内容。',
        ws_edit_discard_ok: '放弃修改',
        today: '今天', yesterday: '昨天', earlier: '更早',
        session_pinned_group: '置顶',
        pin_session: '置顶',
        unpin_session: '取消置顶',
        project_rename: '重命名项目',
        project_delete: '删除项目',
        project_rename_title: '重命名项目',
        project_delete_title: '删除项目',
        project_delete_confirm: '确认删除项目「{name}」？仅移除项目记录，磁盘上的文件不会被删除，其下会话将回到默认空间。',
        perm_menu_title: '本次会话权限',
        perm_read_only: '只读',
        perm_workspace_write: '工作区可写',
        perm_full_access: '全部可访问',
        perm_read_only_desc: '只能查看和分析，不修改任何文件',
        perm_workspace_write_desc: '在当前工作空间内自由读写，空间之外的写入会被拒绝',
        perm_full_access_desc: '不加限制，可修改任意位置（当前默认）',
        perm_follow_global: '跟随全局设置',
        perm_tip: '权限：{name}',
        perm_denied_hint: '当前权限为「{name}」，此操作被拒绝。',
        perm_denied_action: '调整权限',
        model_menu_title: '本次会话模型',
        model_follow_global: '跟随全局设置',
        model_follow_agent: '跟随智能体默认模型',
        model_tip: '模型：{name}',
        model_unset: '未配置',
        session_settings_failed: '设置失败，请重试',
        delete_session_confirm: '确认删除该会话？所有消息将被清除。',
        delete_session_title: '删除会话',
        rename_session: '重命名',
        delete_message_confirm: '确认删除这条消息？',
        delete_message_title: '删除消息',
        edit_disabled_reply_active: '正在生成回复，暂时无法编辑。',
        delete_disabled_reply_active: '正在生成回复，暂时无法删除。',
        untitled_session: '新对话',
        context_cleared: '— 以上内容已从上下文中移除 —',
        tip_new_chat: '新建对话',
        tip_clear_context: '清除上下文',
        tip_attach: '添加附件',
        tip_cancel: '中止',
        tip_cancelled: '已中止',
        attach_menu_file: '上传文件',
        mic_idle_title: '点击录音 / 再按一次结束',
        mic_recording_title: '录音中，再次点击结束',
        mic_busy_title: '识别中…',
        mic_permission_denied: '无法访问麦克风，请检查浏览器权限',
        mic_too_short: '录音太短，请重试',
        mic_error: '语音识别失败',
        optimize_idle_title: '智能优化输入',
        optimize_busy_title: '优化中…',
        optimize_error: '指令优化失败',
        optimize_empty: '输入为空，无法优化',
        speak_msg: '朗读这段回复',
        voice_reply_mode_label: '语音回复策略',
        voice_reply_off: '关闭',
        voice_reply_if_voice: '仅语音问/语音答',
        voice_reply_always: '总是语音回复',
        attach_menu_folder: '上传文件夹',
        confirm_yes: '确认',
        confirm_cancel: '取消',
        error_send: '发送失败，请稍后再试。', error_timeout: '请求超时，请再试一次。',
        thinking_in_progress: '思考中...', thinking_done: '已深度思考', thinking_duration: '耗时',
        edit_message: '编辑消息',
        regenerate_response: '重新生成',
        edit_save: '保存并发送',
        edit_cancel: '取消',
        logout: '退出',
    },
    'zh-Hant': {

        console: '控制台',
        nav_chat: '對話', nav_manage: '管理', nav_monitor: '監控',
        menu_chat: '對話', menu_agents: '智慧體', menu_config: '設定', menu_skills: '技能',
        agents_page_title: '智慧體團隊', agents_page_desc: '管理團隊中的智慧體成員',
        agents_create: '建立智慧體',
        agents_name_placeholder: '智慧體名稱',
        agents_name_required: '請填寫名稱',
        agents_stale: '列表已更新，請重新整理後再試',
        agents_id_placeholder: '留空則自動產生',
        agents_id_tip: '智慧體的唯一識別碼，建立後不可修改。僅支援小寫英文、數字與連字號（-），如 coding-agent。留空則依名稱自動產生。',
        agents_id_invalid: 'ID 需以字母或數字開頭，僅支援字母、數字、底線與連字號，最長 64 位',
        agents_avatar: '頭像',
        agents_tab_profile: '概況',
        agents_tab_skills: '能力',
        agents_tab_files: '核心檔案',
        agents_core_edit: '編輯',
        agents_core_preview: '預覽',
        agents_core_file_agent: '智慧體設定',
        agents_core_file_user: '使用者資訊',
        agents_core_file_rule: '工作空間規則',
        agents_core_file_memory: '長期記憶',
        agents_default: '預設',
        agents_archived: '已封存',
        agents_chat: '開始對話',
        agents_delete: '刪除',
        agents_delete_title: '刪除智慧體',
        agents_delete_confirm: '確定刪除智慧體「{name}」嗎？其工作空間與會話將一併移除，且無法復原。',
        agents_pick_hint: '選擇智慧體',
        agents_clone_label: '從已有智慧體複製',
        agents_clone_hint: '複製其設定、技能與知識作為起點',
        agents_avatar_upload: '上傳圖片',
        agents_clone_none: '空白',
        agents_clone_from: '{name}',
        agents_name: '名稱',
        agents_saved: '已儲存',
        agents_save_failed: '儲存失敗',
        agents_no_desc: '暫無職責',
        agents_description: '職責',
        agents_description_placeholder: '該智慧體負責哪些工作、在什麼場景被使用',
        agents_description_hint: '用於多智慧體協作時的任務分配',
        agents_model: '預設模型',
        agents_model_follows_global: '跟隨全域設定',
        agents_model_default_hint: '預設使用主模型，於「模型設定」中修改。',
        agents_skills_all: '使用全部已安裝技能',
        agents_skills_pick: '只啟用勾選的技能',
        agents_knowledge: '知識庫',
        agents_knowledge_shared: '共享',
        agents_knowledge_own: '獨立',
        agents_knowledge_hint: '共享：與團隊讀寫同一個知識庫\n獨立：擁有專屬知識庫，互不影響',
        agents_knowledge_working: '處理中…',
        agents_knowledge_failed: '切換失敗',
        agents_empty: '還沒有智慧體。建立一個，開始組團隊。',
        agents_select_hint: '從左側選擇一個智能體進行設定',
        agents_pick_tip: '切換當前智能體',
        team_members: '當前會話成員',
        team_invite: '新增到目前會話',
        team_remove: '移出這個會話',
        composer_agent_owner: '主',
        channel_bound_agent: '綁定智慧體',
        channel_bound_default: '預設',
        channel_bound_agent_hint: '第一個為預設智慧體，負責接收訊息並可委派給其他成員',
        channel_team_none: '未選擇',
        channel_team_no_candidates: '暫無可選的智慧體',
        settings_tab_basic: '基礎設定',
        settings_tab_models: '模型設定',
        knowledge_shared_hint: '知識庫預設全員共享，在側欄「知識」查看和編輯。',
        menu_memory: '記憶', menu_knowledge: '知識', menu_channels: '管道', menu_tasks: '定時',
        menu_logs: '日誌',
        models_title: '模型管理',
        models_desc: '統一管理對話、影像、語音、向量、搜尋能力',
        models_section_vendors: '廠商憑據',
        models_section_vendors_desc: '一處設定，多個模型能力共享',
        models_section_capabilities: '模型能力',
        models_add_vendor: '新增廠商',
        models_provider: '廠商',
        models_model: '模型',
        models_voice: '音色',
        models_configured: '已設定',
        models_not_configured: '未設定',
        models_pick_to_configure: '選擇以設定',
        models_clear_credential: '清除憑據',
        models_base_default_hint: '留空將使用官方預設地址',
        models_base_default: '預設',
        models_custom_vendor_label: '自定義',
        models_custom_name: '名稱',
        models_custom_delete: '刪除',
        models_custom_delete_confirm_title: '刪除自定義廠商',
        models_custom_delete_confirm_msg: '確定刪除該自定義廠商嗎？此操作無法撤銷。',
        models_custom_name_required: '請填寫名稱',
        models_custom_base_required: '請填寫 API Base',
        models_custom_edit_title: '編輯自定義廠商',
        models_custom_add_title: '新增自定義廠商',
        models_capability_chat: '主模型',
        models_capability_chat_desc: '用於基礎對話和 Agent 推理',
        models_capability_chat_fallback: '主模型兜底',
        models_capability_chat_fallback_desc: '僅在主模型徹底失敗（重試耗盡）後接管',
        models_fallback_enable: '啟用兜底模型',
        models_fallback_config: '兜底模型',
        models_fallback_config_tip: '設定主模型兜底：主模型徹底失敗後接管',
        models_fallback_modal_title: '主模型兜底',
        models_fallback_modal_desc: '當主模型重試次數用盡仍然失敗時，自動切換到兜底模型完成本輪回覆',
        models_fallback_badge_on: '兜底已啟用',
        models_capability_vision: '影像理解',
        models_capability_vision_desc: '識別圖片內容，用於影像識別工具',
        models_capability_image: '影像生成',
        models_capability_image_desc: '生成圖片，用於影像生成技能',
        models_auto_using: '當前優先使用',
        models_capability_asr: '語音識別',
        models_capability_asr_desc: '語音轉文字',
        models_capability_tts: '語音合成',
        models_capability_tts_desc: '文字轉語音',
        models_capability_embedding: '向量',
        models_capability_embedding_desc: '用於記憶與知識的向量化檢索',
        models_capability_search: '聯網搜尋',
        models_capability_search_desc: '實時網頁檢索能力，用於搜尋工具',
        models_strategy_auto: '自動',
        models_search_strategy_label: '策略',
        models_search_strategy_fixed: '指定',
        models_search_strategy_auto_hint: '從已設定廠商中自動選擇',
        models_search_strategy_fixed_hint: '指定使用搜尋廠商',
        models_pending_config: '待設定',
        models_search_available_label: '可用搜尋廠商：',
        models_search_none_configured: '暫未啟用任何搜尋廠商，點選新增',
        models_search_add_provider: '新增廠商',
        models_search_add_desc: '選擇一個搜尋廠商進行設定',
        models_search_bocha_title: '設定博查 API Key',
        models_search_bocha_desc: '前往博查開放平臺建立 API Key',
        models_search_anysearch_title: '設定 AnySearch API Key',
        models_search_anysearch_desc: '前往 anysearch.com 控制台建立 API Key',
        models_search_serply_title: '設定 Serply API Key',
        models_search_serply_desc: '前往 serply.io 控制台建立 API Key',
        models_search_edit_hint: '點選修改設定',
        models_unavailable: '不可用',
        models_set_via_env: '透過環境變數啟用',
        models_dim_label: '維度',
        models_save_success: '已儲存',
        models_save_failed: '儲存失敗',
        models_cleared: '已清除',
        models_clear_failed: '清除失敗',
        models_embedding_change_title: '更改向量模型',
        models_embedding_change_msg: '切換向量模型後，已有索引將失效，需要重建。是否繼續？',
        models_embedding_saved_title: '向量模型已更新',
        models_embedding_saved_msg: '請在聊天框輸入 /memory rebuild-index 重建索引。',
        models_embedding_saved_ok: '去執行',
        models_pick_provider: '待選擇',
        models_manage_api_key: '管理 API Key',
        models_clear_confirm_title: '清除廠商憑據',
        models_clear_confirm_msg: '確認清除該廠商的 API Key 與 Base URL 嗎？相關能力將不再可用。',
        cancel: '取消',
        save: '儲存',
        ok: '確定',
        knowledge_title: '知識庫', knowledge_desc: '瀏覽和探索你的知識庫',
        knowledge_tab_docs: '檔案', knowledge_tab_graph: '圖譜',
        knowledge_loading: '載入知識庫中...', knowledge_loading_desc: '知識頁面將顯示在這裡',
        knowledge_select_hint: '選擇一個檔案檢視', knowledge_empty_hint: '暫無知識頁面',
        knowledge_empty_guide: '在對話中傳送檔案、連結或主題給 Agent，它會自動整理到你的知識庫中。',
        knowledge_go_chat: '開始對話',
        knowledge_new: '新建',
        knowledge_new_category: '新建分類',
        knowledge_new_document: '新建檔案',
        knowledge_import_documents: '匯入檔案',
        welcome_subtitle: '我可以幫你解答問題、管理電腦、創造和執行技能，並透過<br>長期記憶和知識庫不斷成長',
        example_sys_title: '系統管理', example_sys_text: '檢視工作空間裡有哪些檔案',
        example_task_title: '定時任務', example_task_text: '1分鐘後提醒我檢查伺服器',
        example_code_title: '程式設計助手', example_code_text: '搜尋AI資訊並生成視覺化網頁報告',
        example_knowledge_title: '知識庫', example_knowledge_text: '檢視知識庫當前檔案情況',
        example_skill_title: '技能系統', example_skill_text: '檢視所有支援的工具和技能',
        example_web_title: '指令中心', example_web_text: '檢視全部命令',
        slash_help: '顯示命令幫助',
        slash_status: '檢視執行狀態',
        slash_context: '檢視對話上下文',
        slash_context_clear: '清除對話上下文',
        slash_compact: '壓縮較早的對話以釋放上下文',
        slash_skill_list: '檢視已安裝技能',
        slash_skill_list_remote: '瀏覽技能廣場',
        slash_skill_search: '搜尋技能',
        slash_skill_install: '安裝技能 (名稱或 GitHub URL)',
        slash_skill_uninstall: '解除安裝技能',
        slash_skill_info: '檢視技能詳情',
        slash_skill_enable: '啟用技能',
        slash_skill_disable: '禁用技能',
        slash_memory_dream: '手動觸發記憶蒸餾 (可指定天數, 預設3)',
        slash_knowledge: '檢視知識庫統計',
        slash_knowledge_list: '檢視知識庫檔案樹',
        slash_knowledge_on: '開啟知識庫',
        slash_knowledge_off: '關閉知識庫',
        slash_config: '檢視當前設定',
        slash_cancel: '中止當前正在執行的 Agent 任務',
        slash_steer: '向當前正在執行的 Agent 任務注入引導指令',
        steer_active: '引導當前任務',
        slash_logs: '檢視最近日誌',
        slash_version: '檢視版本',
        input_placeholder: '輸入訊息，/ 使用指令，@ 引用智慧體或檔案',
        config_title: '設定管理', config_desc: '管理模型和 Agent 設定',
        config_model: '模型設定', config_agent: 'Agent 設定',
        config_language: '語言', config_language_hint: '介面展示、命令文案、系統提示詞等使用的語言（與右上角切換同步）',
        config_system: '系統',
        config_task_notify: '任務通知', config_task_notify_hint: '視窗在背景且任務完成或失敗時發送瀏覽器通知，點擊可跳轉會話',
        config_task_notify_sound: '通知聲音', config_task_notify_sound_hint: '通知開啟時可單獨關閉提示音',
        config_task_notify_blocked: '系統通知已被瀏覽器封鎖，請點擊網址列左側圖示 → 通知 → 允許後重新整理頁面',
        notify_task_done: '任務完成',
        notify_task_error: '任務失敗',
        config_model_advanced: '高階設定',
        config_channel: '管道設定',
        config_agent_enabled: 'Agent 模式',
        config_max_tokens: '最大上下文 Token', config_max_tokens_hint: '對話中 Agent 能輸入的最大 Token 長度，超過後會智慧壓縮處理',
        config_max_turns: '最大記憶輪次', config_max_turns_hint: '一問一答為一輪，超過後會智慧壓縮處理',
        config_max_steps: '最大執行步數', config_max_steps_hint: '單次對話中 Agent 最多呼叫工具的次數',
        config_enable_thinking: '深度思考', config_enable_thinking_hint: '是否啟用深度思考模式',
        config_reasoning_effort: '思考強度', config_reasoning_effort_hint: '按目前模型廠商支援的原生枚舉傳送',
        config_subagent: '子 Agent', config_subagent_hint: '把可獨立完成的任務交給子 Agent，多個任務並行執行，只把結論帶回主對話',
        config_self_evolution: '自主進化', config_self_evolution_hint: '會話空閒後自動覆盤，沉澱記憶、最佳化技能、處理未完成事項',
        evolution_badge: '自主學習',
        config_channel_type: '管道型別',
        config_provider: '模型廠商', config_model_name: '模型',
        config_custom_model_hint: '輸入自定義模型名稱',
        config_save: '儲存', config_saved: '已儲存',
        config_save_error: '儲存失敗',
        config_custom_option: '自定義',
        config_custom_tip: '介面需遵循 OpenAI API 協議',
        config_security: '安全設定', config_password: '訪問密碼',
        config_password_hint: '留空則不啟用密碼保護',
        config_permission: '預設權限',
        config_permission_hint: '新會話的預設權限範圍，決定 Agent 能修改哪些檔案、能執行哪些命令',
        config_permission_desc: '新會話預設使用該權限；單個會話可在輸入框下方單獨調整',
        config_password_changed: '密碼已更新',
        config_password_cleared: '密碼已清除',
        config_password_security_warning: '⚠️ 警告：目前密碼為空且對外連接埠開放，建議重啟服務，或檢查是否調整監聽位址綁定。',
        skills_title: '技能管理', skills_desc: '檢視、啟用或禁用 Agent 工具和技能', skills_hub_btn: '探索技能廣場',
        skills_loading: '載入技能中...', skills_loading_desc: '技能載入後將顯示在此處',
        tools_section_title: '內建工具', tools_loading: '載入工具中...',
        skills_section_title: '技能', skill_enable: '啟用', skill_disable: '禁用',
        skill_toggle_error: '操作失敗，請稍後再試',
        skill_open_hint: '點擊檢視技能內容',
        skill_back: '返回列表',
        skill_load_failed: '讀取技能內容失敗',
        skill_builtin_readonly: '內建技能不可編輯（重啟會覆蓋）',
        memory_title: '記憶管理', memory_desc: '檢視 Agent 記憶檔案和內容',
        memory_tab_files: '記憶檔案', memory_tab_dreams: '自主進化',
        memory_loading: '載入記憶檔案中...', memory_loading_desc: '記憶檔案將顯示在此處',
        memory_back: '返回列表',
        memory_col_name: '檔名', memory_col_type: '型別', memory_col_size: '大小', memory_col_updated: '更新時間',
        channels_title: '管道管理', channels_desc: '管理已接入的訊息管道',
        channels_add: '接入管道', channels_disconnect: '斷開',
        channels_save: '儲存設定', channels_saved: '已儲存', channels_save_error: '儲存失敗',
        channels_restarted: '已儲存並重啟',
        channels_connect_btn: '接入', channels_cancel: '取消',
        channels_select_placeholder: '選擇要接入的管道...',
        channels_empty: '暫未接入任何管道', channels_empty_desc: '點選右上角「接入管道」按鈕開始設定',
        channels_disconnect_confirm: '確認斷開該管道？設定將保留但管道會停止執行。',
        channels_connected: '已接入', channels_connecting: '接入中...',
        weixin_scan_title: '微信掃碼登入', weixin_scan_desc: '請使用微信掃描下方二維碼',
        weixin_scan_loading: '正在獲取二維碼...', weixin_scan_waiting: '等待掃碼...',
        weixin_scan_scanned: '已掃碼，請在手機上確認', weixin_scan_expired: '二維碼已過期，正在重新整理...',
        weixin_scan_success: '登入成功，正在啟動管道...', weixin_scan_fail: '獲取二維碼失敗',
        weixin_qr_tip: '二維碼約2分鐘後過期',
        wecom_scan_btn: '掃碼建立企微機器人', wecom_scan_desc: '使用企業微信掃碼，一鍵建立智慧機器人',
        wecom_scan_success: '建立成功，正在啟動管道...',
        wecom_scan_fail: '建立失敗',
        wecom_mode_scan: '掃碼接入', wecom_mode_manual: '手動填寫',
        feishu_scan_btn: '一鍵建立飛書應用',
        feishu_scan_desc: '使用飛書 App 掃碼，自動建立應用並預置全部許可權與事件訂閱',
        feishu_scan_replace_desc: '使用飛書 App 掃碼建立新機器人，將覆蓋當前的 App ID / Secret',
        feishu_scan_loading: '正在向飛書申請二維碼...',
        feishu_scan_waiting: '等待掃碼...',
        feishu_scan_tip: '二維碼 10 分鐘內有效，僅供一次掃描',
        feishu_scan_open_link: '或點選此處在瀏覽器中開啟',
        feishu_scan_success: '應用建立成功，正在啟動管道...',
        feishu_scan_expired: '二維碼已過期，請重試',
        feishu_scan_denied: '已取消授權',
        feishu_scan_fail: '建立失敗',
        feishu_scan_retry: '重試',
        feishu_sdk_downloading: '正在下載飛書元件...',
        feishu_sdk_downloading_tip: '首次啟用需要下載，約 1MB，稍後自動繼續',
        feishu_mode_scan: '掃碼建立', feishu_mode_manual: '手動填寫',
        tasks_title: '定時任務', tasks_desc: '檢視和管理定時任務',
        tasks_coming: '即將推出', tasks_coming_desc: '定時任務管理功能即將在此提供',
        task_add_btn: '新增任務',
        task_edit_title: '編輯定時任務',
        task_add_title: '新增定時任務',
        task_name: '任務名稱',
        task_enabled: '啟用任務',
        task_schedule_type: '排程型別',
        task_schedule_cron: 'Cron 表示式',
        task_schedule_interval: '固定間隔',
        task_schedule_once: '一次性任務',
        task_cron_expression: 'Cron 表示式',
        task_cron_hint: '格式: 分 時 日 月 周，例如 "0 9 * * *" 表示每天 9:00',
        task_interval_seconds: '間隔秒數',
        task_interval_hint: '最小 60 秒，例如 3600 表示每小時執行一次',
        task_once_time: '執行時間',
        task_action_type: '動作型別',
        task_action_send_message: '傳送訊息',
        task_action_agent_task: 'AI 任務',
        task_channel_type: '管道型別',
        task_channel_hint: '選擇定時訊息傳送的管道',
        task_message_content: '訊息內容',
        task_task_description: '任務描述',
        task_delete_btn: '刪除任務',
        task_delete_confirm_title: '刪除定時任務',
        task_delete_confirm_msg: '確定刪除該定時任務嗎？此操作無法撤銷。',
        task_run_now: '立即執行',
        task_run_confirm_title: '立即執行任務',
        task_run_confirm_msg: '該任務會立即向已設定的通道和接收者傳送內容。是否繼續？',
        task_run_started: '已開始執行',
        task_run_failed: '執行失敗',
        logs_title: '日誌', logs_desc: '實時日誌輸出 (run.log)',
        logs_live: '實時', logs_coming_msg: '日誌流即將在此提供。將連線 run.log 實現類似 tail -f 的實時輸出。',
        new_chat: '新對話',
        new_team_chat: '多智慧體對話',
        new_team_chat_hint: '選擇參與本次對話的智慧體，第一個為會話的預設智慧體。',
        new_team_chat_owner: '預設',
        new_team_chat_start: '開始對話',
        new_team_chat_min: '至少選擇兩個智慧體',
        session_history: '歷史會話',
        ws_toggle: '工作空間', ws_tab_preview: '預覽', ws_tab_files: '檔案',
        ws_default_workspace: '預設空間', ws_sel_title: '選擇工作空間',
        ws_sel_default_hint: '使用預設工作空間（~/cow）', ws_sel_recents: '最近使用',
        ws_sel_open: '開啟專案…', ws_sel_new: '新建專案', ws_sel_new_placeholder: '專案名稱',
        ws_sel_create: '建立', ws_sel_up: '上一層',
        ws_sel_new_subtitle: '將在 {root} 下建立新專案目錄', ws_sel_new_hint: '僅填寫專案名稱，不含路徑分隔符',
        ws_sel_name_required: '請輸入專案名稱', ws_sel_name_no_slash: '專案名稱不能包含 / 或 \\',
        ws_sel_open_here: '開啟此目錄', ws_sel_dblclick_hint: '雙擊進入子目錄，單擊選中',
        ws_sel_no_subdirs: '此目錄下沒有子資料夾', ws_sel_drives: '本機',
        ws_open_external: '在新分頁開啟', ws_download: '下載', ws_copy_path: '複製路徑',
        ws_close: '關閉', ws_refresh: '重新整理', ws_preview: '預覽',
        ws_search_placeholder: '搜尋檔案',
        ws_preview_empty: '選擇一個檔案進行預覽',
        ws_preview_failed: '預覽失敗',
        ws_link_not_found: '工作空間中找不到該檔案',
        ws_no_inline_preview: '該類型不支援內嵌預覽',
        ws_empty_dir: '空目錄', ws_no_results: '沒有符合的檔案',
        ws_truncated: '檔案過多，僅顯示部分',
        ws_edit: '編輯', ws_edit_save: '儲存 (Ctrl+S)', ws_edit_cancel: '離開編輯',
        ws_edit_saved: '已儲存',
        ws_edit_load_failed: '開啟編輯器失敗',
        ws_edit_save_failed: '儲存失敗',
        ws_edit_too_large: '檔案過大，無法在面板中編輯',
        ws_edit_unsupported: '該類型不支援編輯',
        ws_edit_encoding: '該檔案不是 UTF-8 編碼，編輯會損壞內容',
        ws_edit_conflict_title: '檔案已被變更',
        ws_edit_conflict_msg: '這個檔案在你編輯期間被變更過（可能是 Agent 寫入的）。覆寫儲存會丟棄磁碟上的新內容。',
        ws_edit_overwrite: '覆寫儲存',
        ws_edit_discard_title: '放棄未儲存的變更？',
        ws_edit_discard_msg: '目前檔案有未儲存的變更，繼續操作會遺失這些內容。',
        ws_edit_discard_ok: '放棄變更',
        today: '今天', yesterday: '昨天', earlier: '更早',
        session_pinned_group: '置頂',
        pin_session: '置頂',
        unpin_session: '取消置頂',
        project_rename: '重新命名專案',
        project_delete: '刪除專案',
        project_rename_title: '重新命名專案',
        project_delete_title: '刪除專案',
        project_delete_confirm: '確認刪除專案「{name}」？僅移除專案記錄，磁碟上的檔案不會被刪除，其下會話將回到預設空間。',
        perm_menu_title: '本次會話權限',
        perm_read_only: '唯讀',
        perm_workspace_write: '工作區可寫',
        perm_full_access: '全部可存取',
        perm_read_only_desc: '只能查看和分析，不修改任何檔案',
        perm_workspace_write_desc: '在目前工作空間內自由讀寫，空間之外的寫入會被拒絕',
        perm_full_access_desc: '不加限制，可修改任意位置（目前預設）',
        perm_follow_global: '跟隨全域設定',
        perm_tip: '權限：{name}',
        perm_denied_hint: '目前權限為「{name}」，此操作被拒絕。',
        perm_denied_action: '調整權限',
        model_menu_title: '本次會話模型',
        model_follow_global: '跟隨全域設定',
        model_follow_agent: '跟隨智慧體預設模型',
        model_tip: '模型：{name}',
        model_unset: '未設定',
        session_settings_failed: '設定失敗，請重試',
        delete_session_confirm: '確認刪除該會話？所有訊息將被清除。',
        delete_session_title: '刪除會話',
        rename_session: '重新命名',
        delete_message_confirm: '確認刪除這條訊息？',
        delete_message_title: '刪除訊息',
        edit_disabled_reply_active: '正在生成回覆，暫時無法編輯。',
        delete_disabled_reply_active: '正在生成回覆，暫時無法刪除。',
        untitled_session: '新對話',
        context_cleared: '— 以上內容已從上下文中移除 —',
        tip_new_chat: '新建對話',
        tip_clear_context: '清除上下文',
        tip_attach: '新增附件',
        tip_cancel: '中止',
        tip_cancelled: '已中止',
        attach_menu_file: '上傳檔案',
        mic_idle_title: '點選錄音 / 再按一次結束',
        mic_recording_title: '錄音中，再次點選結束',
        mic_busy_title: '識別中…',
        mic_permission_denied: '無法訪問麥克風，請檢查瀏覽器許可權',
        mic_too_short: '錄音太短，請重試',
        mic_error: '語音識別失敗',
        speak_msg: '朗讀這段回覆',
        voice_reply_mode_label: '語音回覆策略',
        voice_reply_off: '關閉',
        voice_reply_if_voice: '僅語音問/語音答',
        voice_reply_always: '總是語音回覆',
        attach_menu_folder: '上傳資料夾',
        confirm_yes: '確認',
        confirm_cancel: '取消',
        error_send: '傳送失敗，請稍後再試。', error_timeout: '請求超時，請再試一次。',
        thinking_in_progress: '思考中...', thinking_done: '已深度思考', thinking_duration: '耗時',
        edit_message: '編輯訊息',
        regenerate_response: '重新生成',
        edit_save: '儲存併傳送',
        edit_cancel: '取消',
        logout: '登出',
        },
    en: {
        console: 'Console',
        nav_chat: 'Chat', nav_manage: 'Management', nav_monitor: 'Monitor',
        menu_chat: 'Chat', menu_agents: 'Agents', menu_config: 'Config', menu_skills: 'Skills',
        agents_page_title: 'Agent Team', agents_page_desc: 'Manage the Agents on your team',
        agents_create: 'New Agent',
        agents_name_placeholder: 'Agent name',
        agents_name_required: 'Please enter a name',
        agents_stale: 'The list changed; please refresh and try again',
        agents_id_placeholder: 'Auto-generated if left blank',
        agents_id_tip: 'A unique identifier, fixed once created. Lowercase letters, digits and hyphens (-) only, e.g. ops-agent. Left blank, it is derived from the name.',
        agents_id_invalid: 'The id must start with a letter or digit and use only letters, digits, underscores and hyphens (max 64)',
        agents_avatar: 'Avatar',
        agents_tab_profile: 'Profile',
        agents_tab_skills: 'Skills',
        agents_tab_files: 'Core files',
        agents_core_edit: 'Edit',
        agents_core_preview: 'Preview',
        agents_core_file_agent: 'Persona',
        agents_core_file_user: 'User info',
        agents_core_file_rule: 'Workspace rules',
        agents_core_file_memory: 'Long-term memory',
        agents_default: 'Default',
        agents_archived: 'Archived',
        agents_chat: 'Start chat',
        agents_delete: 'Delete',
        agents_delete_title: 'Delete Agent',
        agents_delete_confirm: 'Delete Agent "{name}"? Its workspace and conversations will be removed for good.',
        agents_pick_hint: 'Pick Agents',
        agents_clone_label: 'Copy from an existing agent',
        agents_clone_hint: 'Copy its config, skills and knowledge as a starting point',
        agents_avatar_upload: 'Upload image',
        agents_clone_none: 'Blank',
        agents_clone_from: '{name}',
        agents_name: 'Name',
        agents_saved: 'Saved',
        agents_save_failed: 'Save failed',
        agents_no_desc: 'No responsibilities yet',
        agents_description: 'Responsibilities',
        agents_description_placeholder: 'What this Agent handles and when it should be used',
        agents_description_hint: 'Used for task assignment when Agents collaborate',
        agents_model: 'Default model',
        agents_model_follows_global: 'Follow the configured model',
        agents_model_default_hint: 'Uses the primary model. Change it under Model config.',
        agents_skills_all: 'Use every installed skill',
        agents_knowledge: 'Knowledge base',
        agents_knowledge_shared: 'Shared',
        agents_knowledge_own: 'Own',
        agents_knowledge_hint: 'Shared: read and write the same knowledge base as the team\nOwn: a private base, isolated from others',
        agents_knowledge_working: 'Working…',
        agents_knowledge_failed: 'Switch failed',
        agents_skills_pick: 'Only the skills checked below',
        agents_empty: 'No Agents yet. Create one to start a team.',
        agents_select_hint: 'Pick an Agent on the left to configure it',
        agents_pick_tip: 'Switch current Agent',
        team_members: 'In this conversation',
        team_invite: 'Add to current chat',
        team_remove: 'Remove from this chat',
        composer_agent_owner: 'Owner',
        channel_bound_agent: 'Bind agent',
        channel_bound_default: 'default',
        channel_bound_agent_hint: 'first pick is the default agent: it receives messages and can delegate to the rest',
        channel_team_none: 'None',
        channel_team_no_candidates: 'No agents available',
        settings_tab_basic: 'General',
        settings_tab_models: 'Models',
        knowledge_shared_hint: 'Knowledge is shared by every Agent. Open it from the Knowledge page.',
        menu_memory: 'Memory', menu_knowledge: 'Knowledge', menu_channels: 'Channels', menu_tasks: 'Tasks',
        menu_logs: 'Logs',
        models_title: 'Models',
        models_desc: 'Manage chat, image, voice, embedding and search capabilities in one place',
        models_section_vendors: 'Provider Credentials',
        models_section_vendors_desc: 'Configured once, shared by multiple model capabilities',
        models_section_capabilities: 'Capabilities',
        models_add_vendor: 'Add Provider',
        models_provider: 'Provider',
        models_model: 'Model',
        models_voice: 'Voice',
        models_configured: 'configured',
        models_not_configured: 'not configured',
        models_pick_to_configure: 'pick to configure',
        models_clear_credential: 'Clear credentials',
        models_base_default_hint: 'Leave blank to use the official default base URL',
        models_base_default: 'Default',
        models_custom_vendor_label: 'Custom',
        models_custom_name: 'Name',
        models_custom_delete: 'Delete',
        models_custom_delete_confirm_title: 'Delete custom provider',
        models_custom_delete_confirm_msg: 'Delete this custom provider? This cannot be undone.',
        models_custom_name_required: 'Name is required',
        models_custom_base_required: 'API Base is required',
        models_custom_edit_title: 'Edit custom provider',
        models_custom_add_title: 'Add custom provider',
        models_capability_chat: 'Main Model',
        models_capability_chat_desc: 'Used for basic chat and agent reasoning',
        models_capability_chat_fallback: 'Main Model Fallback',
        models_capability_chat_fallback_desc: 'Takes over only after the main model fails for good',
        models_fallback_enable: 'Enable the fallback model',
        models_fallback_config: 'Fallback',
        models_fallback_config_tip: 'Configure the main-model fallback (takes over after the main model fails)',
        models_fallback_modal_title: 'Main Model Fallback',
        models_fallback_modal_desc: 'When the main model still fails after exhausting its retries, automatically switch to the fallback model to finish the reply.',
        models_fallback_badge_on: 'Fallback on',
        models_capability_vision: 'Image Understanding',
        models_capability_vision_desc: 'Recognizes image content, used by image recognition tools',
        models_capability_image: 'Image Generation',
        models_capability_image_desc: 'Generates images, used by image generation skills',
        models_auto_using: 'Preferred',
        models_capability_asr: 'Speech Recognition',
        models_capability_asr_desc: 'Voice to text',
        models_capability_tts: 'Speech Synthesis',
        models_capability_tts_desc: 'Text to voice',
        models_capability_embedding: 'Embedding',
        models_capability_embedding_desc: 'Used for vectorized retrieval of memory and knowledge',
        models_capability_search: 'Web Search',
        models_capability_search_desc: 'Real-time web retrieval, used by search tools',
        models_strategy_auto: 'auto',
        models_search_strategy_label: 'Strategy',
        models_search_strategy_fixed: 'Pinned',
        models_search_strategy_auto_hint: 'Auto-pick from configured providers',
        models_search_strategy_fixed_hint: 'Always use a specific provider',
        models_pending_config: 'Pending setup',
        models_search_available_label: 'Available:',
        models_search_none_configured: 'No search provider enabled yet — click add.',
        models_search_add_provider: 'Add provider',
        models_search_add_desc: 'Pick a search provider to configure',
        models_search_bocha_title: 'Configure Bocha API Key',
        models_search_bocha_desc: 'Create a key at the Bocha open platform.',
        models_search_anysearch_title: 'Configure AnySearch API Key',
        models_search_anysearch_desc: 'Create a key at the AnySearch console (anysearch.com).',
        models_search_serply_title: 'Configure Serply API Key',
        models_search_serply_desc: 'Create a key at the Serply console (serply.io).',
        models_search_edit_hint: 'Click to edit',
        models_unavailable: 'unavailable',
        models_set_via_env: 'enable via environment variable',
        models_dim_label: 'dim',
        models_save_success: 'Saved',
        models_save_failed: 'Save failed',
        models_cleared: 'Cleared',
        models_clear_failed: 'Clear failed',
        models_embedding_change_title: 'Change embedding model',
        models_embedding_change_msg: 'Switching the embedding model invalidates the existing index — a rebuild will be needed. Continue?',
        models_embedding_saved_title: 'Embedding model updated',
        models_embedding_saved_msg: 'Send /memory rebuild-index in the chat to rebuild the index.',
        models_embedding_saved_ok: 'Go',
        models_pick_provider: 'Pick a provider',
        models_manage_api_key: 'Manage API keys',
        models_clear_confirm_title: 'Clear provider credentials',
        models_clear_confirm_msg: 'Remove this provider\'s API Key and Base URL? Capabilities relying on it will stop working.',
        cancel: 'Cancel',
        save: 'Save',
        ok: 'OK',
        knowledge_title: 'Knowledge', knowledge_desc: 'Browse and explore your knowledge base',
        knowledge_tab_docs: 'Documents', knowledge_tab_graph: 'Graph',
        knowledge_loading: 'Loading knowledge base...', knowledge_loading_desc: 'Knowledge pages will be displayed here',
        knowledge_select_hint: 'Select a document to view', knowledge_empty_hint: 'No knowledge pages yet',
        knowledge_empty_guide: 'Send documents, links or topics to the agent in chat, and it will automatically organize them into your knowledge base.',
        knowledge_go_chat: 'Start a conversation',
        knowledge_new: 'New',
        knowledge_new_category: 'New category',
        knowledge_new_document: 'New document',
        knowledge_import_documents: 'Import documents',
        welcome_subtitle: 'I can help you answer questions, manage your computer, create and execute skills, and keep growing through <br> long-term memory and a personal knowledge base.',
        example_sys_title: 'System', example_sys_text: 'Show me the files in the workspace',
        example_task_title: 'Scheduler', example_task_text: 'Remind me to check the server in 5 minutes',
        example_code_title: 'Coding', example_code_text: 'Search today\'s AI news and generate a visual report webpage',
        example_knowledge_title: 'Knowledge', example_knowledge_text: 'Show me the current knowledge base',
        example_skill_title: 'Skills', example_skill_text: 'Show current tools and skills',
        example_web_title: 'Commands', example_web_text: 'Show all commands',
        slash_help: 'Show this help',
        slash_status: 'Show running status',
        slash_context: 'Show conversation context',
        slash_context_clear: 'Clear conversation context',
        slash_compact: 'Summarize older turns to free up context',
        slash_skill_list: 'List installed skills',
        slash_skill_list_remote: 'Browse Skill Hub',
        slash_skill_search: 'Search skills',
        slash_skill_install: 'Install a skill (name or GitHub URL)',
        slash_skill_uninstall: 'Uninstall a skill',
        slash_skill_info: 'Show skill details',
        slash_skill_enable: 'Enable a skill',
        slash_skill_disable: 'Disable a skill',
        slash_memory_dream: 'Trigger memory distillation (optional days, default 3)',
        slash_knowledge: 'Show knowledge base stats',
        slash_knowledge_list: 'Show knowledge base file tree',
        slash_knowledge_on: 'Enable knowledge base',
        slash_knowledge_off: 'Disable knowledge base',
        slash_config: 'Show current config',
        slash_cancel: 'Abort the running Agent task',
        slash_steer: 'Inject guidance into the running Agent task',
        steer_active: 'Steer active task',
        slash_logs: 'Show recent logs',
        slash_version: 'Show version',
        input_placeholder: 'Type a message, / for commands, @ to mention an Agent or a file',
        config_title: 'Configuration', config_desc: 'Manage model and agent settings',
        config_model: 'Model Configuration', config_agent: 'Agent Configuration',
        config_language: 'Language', config_language_hint: 'Language for the UI, command text, system prompts and more (synced with the top-right switch)',
        config_system: 'System',
        config_task_notify: 'Task Notifications', config_task_notify_hint: 'Show a browser notification when a task finishes or fails while the window is in the background; click to open the session',
        config_task_notify_sound: 'Notification Sound', config_task_notify_sound_hint: 'Turn off the alert sound while keeping notifications',
        config_task_notify_blocked: 'Notifications are blocked by the browser. Click the icon on the left of the address bar → Notifications → Allow, then reload.',
        notify_task_done: 'Task finished',
        notify_task_error: 'Task failed',
        config_model_advanced: 'Advanced',
        config_channel: 'Channel Configuration',
        config_agent_enabled: 'Agent Mode',
        config_max_tokens: 'Max Context Tokens', config_max_tokens_hint: 'Max tokens the Agent can input per conversation, auto-compressed when exceeded',
        config_max_turns: 'Max Memory Turns', config_max_turns_hint: 'One Q&A pair = one turn, auto-compressed when exceeded',
        config_max_steps: 'Max Steps', config_max_steps_hint: 'Max tool calls the Agent can make in a single conversation',
        config_enable_thinking: 'Deep Thinking', config_enable_thinking_hint: 'Enable deep thinking mode',
        config_reasoning_effort: 'Reasoning Effort', config_reasoning_effort_hint: 'Sent as the active provider\'s native enum value',
        config_subagent: 'Sub Agents', config_subagent_hint: 'Hand self-contained tasks to sub agents, which run in parallel and report back only their conclusions',
        config_self_evolution: 'Self-Evolution', config_self_evolution_hint: 'Auto-review idle conversations to consolidate memory, improve skills, and follow up on unfinished tasks',
        evolution_badge: 'Self-learned',
        config_channel_type: 'Channel Type',
        config_provider: 'Provider', config_model_name: 'Model',
        config_custom_model_hint: 'Enter custom model name',
        config_save: 'Save', config_saved: 'Saved',
        config_save_error: 'Save failed',
        config_custom_option: 'Custom',
        config_custom_tip: 'API must follow OpenAI protocol.',
        config_security: 'Security', config_password: 'Password',
        config_password_hint: 'Leave empty to disable password protection',
        config_permission: 'Default permissions',
        config_permission_hint: 'The default scope for new chats: which files the agent may change and which commands it may run',
        config_permission_desc: 'New chats start with this; each chat can be changed under the input box',
        config_password_changed: 'Password updated',
        config_password_cleared: 'Password cleared',
        config_password_security_warning: '⚠️ Warning: Password is now empty and the port is exposed. Consider restarting the service or adjusting the listening address binding.',
        skills_title: 'Skills', skills_desc: 'View, enable, or disable agent tools and skills', skills_hub_btn: 'Skill Hub',
        skills_loading: 'Loading skills...', skills_loading_desc: 'Skills will be displayed here after loading',
        tools_section_title: 'Built-in Tools', tools_loading: 'Loading tools...',
        skills_section_title: 'Skills', skill_enable: 'Enable', skill_disable: 'Disable',
        skill_toggle_error: 'Operation failed, please try again',
        skill_open_hint: 'Click to view this skill',
        skill_back: 'Back to list',
        skill_load_failed: 'Could not read the skill',
        skill_builtin_readonly: 'Built-in skill, read-only (replaced on restart)',
        memory_title: 'Memory', memory_desc: 'View agent memory files and contents',
        memory_tab_files: 'Memory Files', memory_tab_dreams: 'Self-Evolution',
        memory_loading: 'Loading memory files...', memory_loading_desc: 'Memory files will be displayed here',
        memory_back: 'Back to list',
        memory_col_name: 'Filename', memory_col_type: 'Type', memory_col_size: 'Size', memory_col_updated: 'Updated',
        channels_title: 'Channels', channels_desc: 'Manage connected messaging channels',
        channels_add: 'Connect', channels_disconnect: 'Disconnect',
        channels_save: 'Save', channels_saved: 'Saved', channels_save_error: 'Save failed',
        channels_restarted: 'Saved & Restarted',
        channels_connect_btn: 'Connect', channels_cancel: 'Cancel',
        channels_select_placeholder: 'Select a channel to connect...',
        channels_empty: 'No channels connected', channels_empty_desc: 'Click the "Connect" button above to get started',
        channels_disconnect_confirm: 'Disconnect this channel? Config will be preserved but the channel will stop.',
        channels_connected: 'Connected', channels_connecting: 'Connecting...',
        weixin_scan_title: 'WeChat QR Login', weixin_scan_desc: 'Scan the QR code below with WeChat',
        weixin_scan_loading: 'Loading QR code...', weixin_scan_waiting: 'Waiting for scan...',
        weixin_scan_scanned: 'Scanned, please confirm on your phone', weixin_scan_expired: 'QR code expired, refreshing...',
        weixin_scan_success: 'Login successful, starting channel...', weixin_scan_fail: 'Failed to load QR code',
        weixin_qr_tip: 'QR code expires in ~2 minutes',
        wecom_scan_btn: 'Scan to Create WeCom Bot', wecom_scan_desc: 'Scan with WeCom to create a bot instantly',
        wecom_scan_success: 'Bot created, starting channel...',
        wecom_scan_fail: 'Bot creation failed',
        wecom_mode_scan: 'Scan QR', wecom_mode_manual: 'Manual',
        feishu_scan_btn: 'One-click Create Feishu App',
        feishu_scan_desc: 'Scan with Feishu App to create an app with all required permissions pre-configured',
        feishu_scan_replace_desc: 'Scan with Feishu App to create a new bot — will overwrite the current App ID / Secret',
        feishu_scan_loading: 'Requesting QR code from Feishu...',
        feishu_scan_waiting: 'Waiting for scan...',
        feishu_scan_tip: 'QR code expires in 10 minutes, single use only',
        feishu_scan_open_link: 'Or click here to open in browser',
        feishu_scan_success: 'App created, starting channel...',
        feishu_scan_expired: 'QR code expired, please retry',
        feishu_scan_denied: 'Authorization cancelled',
        feishu_scan_fail: 'App creation failed',
        feishu_scan_retry: 'Retry',
        feishu_sdk_downloading: 'Downloading Feishu components...',
        feishu_sdk_downloading_tip: 'A one-time ~1MB download; this will continue automatically',
        feishu_mode_scan: 'Scan QR', feishu_mode_manual: 'Manual',
        tasks_title: 'Scheduled Tasks', tasks_desc: 'View and manage scheduled tasks',
        tasks_coming: 'Coming Soon', tasks_coming_desc: 'Scheduled task management will be available here',
        task_add_btn: 'Add Task',
        task_edit_title: 'Edit Task',
        task_add_title: 'Add Task',
        task_name: 'Task Name',
        task_enabled: 'Enable Task',
        task_schedule_type: 'Schedule Type',
        task_schedule_cron: 'Cron Expression',
        task_schedule_interval: 'Fixed Interval',
        task_schedule_once: 'One-time Task',
        task_cron_expression: 'Cron Expression',
        task_cron_hint: 'Format: minute hour day month weekday, e.g. "0 9 * * *" means daily at 9:00',
        task_interval_seconds: 'Interval (seconds)',
        task_interval_hint: 'Minimum 60 seconds, e.g. 3600 means once per hour',
        task_once_time: 'Execution Time',
        task_action_type: 'Action Type',
        task_action_send_message: 'Send Message',
        task_action_agent_task: 'AI Task',
        task_channel_type: 'Channel Type',
        task_channel_hint: 'Select the channel to send scheduled messages',
        task_message_content: 'Message Content',
        task_task_description: 'Task Description',
        task_delete_btn: 'Delete Task',
        task_delete_confirm_title: 'Delete Task',
        task_delete_confirm_msg: 'Delete this scheduled task? This action cannot be undone.',
        task_run_now: 'Run now',
        task_run_confirm_title: 'Run task now',
        task_run_confirm_msg: 'This task will immediately send to its configured channel and receiver. Continue?',
        task_run_started: 'Run started',
        task_run_failed: 'Run failed',
        logs_title: 'Logs', logs_desc: 'Real-time log output (run.log)',
        logs_live: 'Live', logs_coming_msg: 'Log streaming will be available here. Connects to run.log for real-time output similar to tail -f.',
        new_chat: 'New Chat',
        new_team_chat: 'Group chat',
        new_team_chat_hint: 'Pick the Agents for this conversation; the first is its default Agent.',
        new_team_chat_owner: 'Default',
        new_team_chat_start: 'Start chat',
        new_team_chat_min: 'Pick at least two Agents',
        session_history: 'History',
        ws_toggle: 'Workspace', ws_tab_preview: 'Preview', ws_tab_files: 'Files',
        ws_default_workspace: 'Default', ws_sel_title: 'Select workspace',
        ws_sel_default_hint: 'Use the default workspace (~/cow)', ws_sel_recents: 'Recent',
        ws_sel_open: 'Open project…', ws_sel_new: 'New project', ws_sel_new_placeholder: 'Project name',
        ws_sel_create: 'Create', ws_sel_up: 'Up',
        ws_sel_new_subtitle: 'Creates a new project directory under {root}', ws_sel_new_hint: 'Project name only, no path separators',
        ws_sel_name_required: 'Please enter a project name', ws_sel_name_no_slash: 'Project name must not contain / or \\',
        ws_sel_open_here: 'Open this folder', ws_sel_dblclick_hint: 'Double-click to enter, single-click to select',
        ws_sel_no_subdirs: 'No sub-folders here', ws_sel_drives: 'This PC',
        ws_open_external: 'Open in new tab', ws_download: 'Download', ws_copy_path: 'Copy path',
        ws_close: 'Close', ws_refresh: 'Refresh', ws_preview: 'Preview',
        ws_search_placeholder: 'Search files',
        ws_preview_empty: 'Select a file to preview',
        ws_preview_failed: 'Preview failed',
        ws_link_not_found: 'File not found in the workspace',
        ws_no_inline_preview: 'No inline preview for this file type',
        ws_empty_dir: 'Empty directory', ws_no_results: 'No matching files',
        ws_truncated: 'Too many files, showing a subset',
        ws_edit: 'Edit', ws_edit_save: 'Save (Ctrl+S)', ws_edit_cancel: 'Leave editor',
        ws_edit_saved: 'Saved',
        ws_edit_load_failed: 'Could not open the editor',
        ws_edit_save_failed: 'Save failed',
        ws_edit_too_large: 'File is too large to edit in the panel',
        ws_edit_unsupported: 'This file type cannot be edited',
        ws_edit_encoding: 'This file is not UTF-8; editing would corrupt it',
        ws_edit_conflict_title: 'File changed on disk',
        ws_edit_conflict_msg: 'This file changed while you were editing it, most likely written by the agent. Overwriting discards the newer content on disk.',
        ws_edit_overwrite: 'Overwrite',
        ws_edit_discard_title: 'Discard unsaved changes?',
        ws_edit_discard_msg: 'This file has unsaved changes and continuing will lose them.',
        ws_edit_discard_ok: 'Discard',
        today: 'Today', yesterday: 'Yesterday', earlier: 'Earlier',
        session_pinned_group: 'Pinned',
        pin_session: 'Pin',
        unpin_session: 'Unpin',
        project_rename: 'Rename project',
        project_delete: 'Delete project',
        project_rename_title: 'Rename project',
        project_delete_title: 'Delete project',
        project_delete_confirm: 'Delete project “{name}”? Only the project record is removed — files on disk are kept, and its chats revert to the default workspace.',
        perm_menu_title: 'Permissions for this chat',
        perm_read_only: 'Read-only',
        perm_workspace_write: 'Workspace write',
        perm_full_access: 'Full access',
        perm_read_only_desc: 'Read and analyse only; no file is modified',
        perm_workspace_write_desc: 'Write freely inside this workspace; writes outside it are refused',
        perm_full_access_desc: 'No limits, anywhere on the machine (current default)',
        perm_follow_global: 'Follow global setting',
        perm_tip: 'Permissions: {name}',
        perm_denied_hint: 'This session is “{name}”, so the action was refused.',
        perm_denied_action: 'Adjust permissions',
        model_menu_title: 'Model for this chat',
        model_follow_global: 'Follow global setting',
        model_follow_agent: 'Follow the agent\u2019s default model',
        model_tip: 'Model: {name}',
        model_unset: 'Not set',
        session_settings_failed: 'Could not apply, please retry',
        delete_session_confirm: 'Delete this session? All messages will be removed.',
        delete_session_title: 'Delete Session',
        rename_session: 'Rename',
        delete_message_confirm: 'Delete this message?',
        delete_message_title: 'Delete Message',
        edit_disabled_reply_active: 'Reply is being generated; editing is temporarily unavailable.',
        delete_disabled_reply_active: 'Reply is being generated; deletion is temporarily unavailable.',
        untitled_session: 'New Chat',
        context_cleared: '— Context above has been cleared —',
        tip_new_chat: 'New Chat',
        tip_clear_context: 'Clear Context',
        tip_attach: 'Add Attachment',
        tip_cancel: 'Cancel',
        tip_cancelled: 'Cancelled',
        attach_menu_file: 'Upload File',
        mic_idle_title: 'Click to record, click again to stop',
        mic_recording_title: 'Recording, click to stop',
        mic_busy_title: 'Transcribing…',
        mic_permission_denied: 'Cannot access microphone — check browser permissions',
        mic_too_short: 'Recording too short, please retry',
        mic_error: 'Speech recognition failed',
        optimize_idle_title: 'Optimize prompt',
        optimize_busy_title: 'Optimizing…',
        optimize_error: 'Prompt optimization failed',
        optimize_empty: 'Input is empty, nothing to optimize',
        speak_msg: 'Read this reply aloud',
        voice_reply_mode_label: 'Voice reply policy',
        voice_reply_off: 'Off',
        voice_reply_if_voice: 'Voice only if voice input',
        voice_reply_always: 'Always reply with voice',
        attach_menu_folder: 'Upload Folder',
        confirm_yes: 'Confirm',
        confirm_cancel: 'Cancel',
        error_send: 'Failed to send. Please try again.', error_timeout: 'Request timeout. Please try again.',
        thinking_in_progress: 'Thinking...', thinking_done: 'Thought', thinking_duration: 'Duration',
        edit_message: 'Edit message',
        regenerate_response: 'Regenerate',
        edit_save: 'Save and send',
        edit_cancel: 'Cancel',
        logout: 'Logout',
    }
};

// 按优先级解析语言：用户选择（localStorage）->后端检测
// (cow_lang) -> 浏览器语言 -> 'zh'。共享 __cowResolveLang__ 定义于
// 聊天.html；如果独立加载，则回退到本地解析器。
let currentLang = (typeof window.__cowResolveLang__ === 'function')
    ? window.__cowResolveLang__()
    : (function () {
        const norm = (raw) => {
            if (!raw) return '';
            const v = String(raw).trim().toLowerCase();
            if (v === 'auto') return '';
            // 首先处理繁体中文变体（更具体）
            if (v === 'zh-hant' || v.startsWith('zh-hant-') || v === 'zh-tw' || v === 'zh-hk') return 'zh-Hant';
            // 然后是简体中文
            if (v.indexOf('zh') === 0) return 'zh';
            if (v.indexOf('en') === 0) return 'en';
            return '';
        };
        return norm(localStorage.getItem('cow_lang'))
            || norm(window.__COW_DEFAULT_LANG__)
            || norm(navigator.language)
            || 'zh';
    })();

function t(key) {
    return (I18N[currentLang] && I18N[currentLang][key]) || (I18N.en[key]) || key;
}

// 解析本地化标签，该标签可以是纯字符串或
// 后端返回的 {zh, en} 对象。
function localizedLabel(label) {
    if (label && typeof label === 'object') {
        return label[currentLang] || label.en || label.zh || '';
    }
    return label || '';
}

function applyI18n() {
    document.querySelectorAll('[data-i18n]').forEach(el => {
        el.textContent = t(el.dataset.i18n);
    });
    document.querySelectorAll('[data-i18n-html]').forEach(el => {
        el.innerHTML = t(el.dataset.i18nHtml);
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
        el.placeholder = t(el.dataset['i18nPlaceholder']);
    });
    document.querySelectorAll('[data-i18n-title]').forEach(el => {
        el.title = t(el.dataset['i18nTitle']);
    });
    document.querySelectorAll('[data-i18n-aria-label]').forEach(el => {
        el.setAttribute('aria-label', t(el.dataset['i18nAriaLabel']));
    });
    document.querySelectorAll('[data-i18n-tip]').forEach(el => {
        el.setAttribute('data-tip', t(el.dataset['i18nTip']));
    });
    document.querySelectorAll('[data-tip-key]').forEach(el => {
        el.setAttribute('data-tooltip', t(el.dataset.tipKey));
    });
    installCfgTipPortal();
    
    // 语言更改时清除所有状态消息
    document.querySelectorAll('[id$="-status"]').forEach(el => {
        el.classList.add('opacity-0');
    });
    
    _syncLangControls();
    // 将文档链接指向特定于区域设置的文档站点。
    const docsLink = document.getElementById('docs-link');
    if (docsLink) docsLink.href = currentLang === 'zh' ? 'https://docs.cowagent.ai/zh' : 'https://docs.cowagent.ai';
    // 工作区面板内容由 JS 渲染，而不是 data-i18n 属性。
    if (typeof relocalizeWorkspacePanel === 'function') relocalizeWorkspacePanel();
}

// 切换语言的单一入口点。更新内存中的语言，
// 在本地保留用户选择，重新呈现 UI，并将选择绑定到
// 后端 `cow_lang` 配置，以便记录/代理回复/CLI 遵循。
function setLanguage(lang) {
    const next = (lang === 'en' || lang === 'zh' || lang === 'zh-Hant') ? lang : 'zh';
    if (next === currentLang) {
        // 仍然坚持+同步，以防存储/后端偏离用户界面。
        syncLanguageToBackend(next);
        return;
    }
    currentLang = next;
    localStorage.setItem('cow_lang', currentLang);
    applyI18n();
    _applyInputTooltips();
    // 保持语言切换按钮和配置选择器在视觉上同步。
    try { updateLangControls(); } catch (e) {}
    
    // 首先将语言选择同步到后端，然后触发动态视图重新加载
    // 以避免 API 端点上的竞争条件。
    syncLanguageToBackend(currentLang, () => {
        try { rerenderDynamicViews(); } catch (e) {}
    });
}

// 将语言保留到后端 `cow_lang` 配置（尽力而为；UI
// 已经在本地进行切换，因此网络故障是非阻塞的）。
function syncLanguageToBackend(lang, callback) {
    try {
        fetch('/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ updates: { cow_lang: lang } })
        })
        .then(() => { if (callback) callback(); })
        .catch(() => { if (callback) callback(); });
    } catch (e) {
        if (callback) callback();
    }
}

// 在右上角切换和配置上反映当前语言
// 选择器（如果存在），因此两个入口点保持同步。
function updateLangControls() {
    _syncLangControls();
    // 配置语言选择器是自定义的 .cfg-dropdown 组件。仅
    // 初始化后同步它（即打开配置面板）。
    const sel = document.getElementById('cfg-lang-select');
    if (sel && sel._ddValue !== undefined && sel._ddValue !== currentLang) {
        sel._ddValue = currentLang;
        const textEl = sel.querySelector('.cfg-dropdown-text');
        if (textEl) {
            if (currentLang === 'zh-Hant') textEl.textContent = '繁體中文';
            else if (currentLang === 'zh') textEl.textContent = '简体中文';
            else textEl.textContent = 'English';
        }
        sel.querySelectorAll('.cfg-dropdown-item').forEach(i => {
            i.classList.toggle('active', i.dataset.value === currentLang);
        });
    }
}

// 在标题下拉列表中反映当前语言：短标签
// toggle (简 / 繁 / EN) plus the active item highlighted in the menu.
function _syncLangControls() {
    const langLabel = document.getElementById('lang-label');
    if (langLabel) {
        if (currentLang === 'zh-Hant') langLabel.textContent = '繁';
        else if (currentLang === 'zh') langLabel.textContent = '简';
        else langLabel.textContent = 'EN';
    }
    document.querySelectorAll('#lang-menu .lang-menu-item').forEach(item => {
        const active = item.dataset.lang === currentLang;
        item.classList.toggle('text-blue-600', active);
        item.classList.toggle('dark:text-blue-400', active);
        item.classList.toggle('font-medium', active);
    });
}

// 打开/关闭标题语言下拉菜单。
function toggleLangMenu(event) {
    if (event) event.stopPropagation();
    const menu = document.getElementById('lang-menu');
    if (menu) menu.classList.toggle('hidden');
}

// 从下拉列表中选择一种语言，然后关闭菜单。
function selectLanguage(lang) {
    const menu = document.getElementById('lang-menu');
    if (menu) menu.classList.add('hidden');
    setLanguage(lang);
}
window.toggleLangMenu = toggleLangMenu;
window.selectLanguage = selectLanguage;

// 单击语言菜单外部时关闭语言菜单。
document.addEventListener('click', (e) => {
    const selector = document.getElementById('lang-selector');
    const menu = document.getElementById('lang-menu');
    if (menu && !menu.classList.contains('hidden') && selector && !selector.contains(e.target)) {
        menu.classList.add('hidden');
    }
});

// 语言切换后刷新 JS 渲染视图。每个分支都使用
// 轻量级内存中重新渲染路径（没有额外的网络往返）。
function rerenderDynamicViews() {
    // 模型是配置视图的一个选项卡，而不是它们自己的视图。
    if (currentView === 'config' && typeof renderModelsView === 'function'
            && modelsState && (modelsState.providers || modelsState.capabilities)) {
        renderModelsView();
    }
    // 语言切换后重新加载任务列表
    if (currentView === 'tasks') {
        tasksLoaded = false;
        loadTasksView();
    }
    // 语言切换后重新加载技能和工具
    if (currentView === 'skills') {
        toolsLoaded = false;
        loadSkillsView();
    }
    // 语言切换后重新加载频道
    if (currentView === 'channels') {
        loadChannelsView();
    }
    // 语言切换后重新加载配置
    if (currentView === 'config') {
        loadConfigView();
    }
}

// [data-tip-key] 元素的浮动工具提示门户。工具提示节点是
// 附加到 <body> 中，这样它们就不会被溢出：隐藏的祖先剪切掉
// （例如配置面板的滚动容器）。
let _cfgTipPortalEl = null;
let _cfgTipPortalInstalled = false;
function installCfgTipPortal() {
    if (_cfgTipPortalInstalled) return;
    _cfgTipPortalInstalled = true;

    const showTip = (target) => {
        const text = target.getAttribute('data-tooltip');
        if (!text) return;
        if (!_cfgTipPortalEl) {
            _cfgTipPortalEl = document.createElement('div');
            _cfgTipPortalEl.className = 'cfg-tip-floating';
            document.body.appendChild(_cfgTipPortalEl);
        }
        _cfgTipPortalEl.textContent = text;
        const rect = target.getBoundingClientRect();
        // 渲染一次以进行测量，然后相对于目标进行定位。
        _cfgTipPortalEl.style.left = '0px';
        _cfgTipPortalEl.style.top = '0px';
        _cfgTipPortalEl.classList.add('show');
        const tipRect = _cfgTipPortalEl.getBoundingClientRect();
        let left = rect.left + rect.width / 2 - tipRect.width / 2;
        // 使用 8px 的装订线水平固定到视口。
        left = Math.max(8, Math.min(left, window.innerWidth - tipRect.width - 8));
        // 默认高于目标；当 data-tooltip-pos="bottom" 时放在下面。
        const below = target.getAttribute('data-tooltip-pos') === 'bottom';
        const top = below ? rect.bottom + 6 : rect.top - tipRect.height - 6;
        _cfgTipPortalEl.style.left = left + 'px';
        _cfgTipPortalEl.style.top = top + 'px';
    };
    const hideTip = () => {
        if (_cfgTipPortalEl) _cfgTipPortalEl.classList.remove('show');
    };

    // 匹配配置键和任何选择浮动工具提示的元素
    // [data-tip-float]（用于动态工具提示，例如工作区选择器，
    // 其数据工具提示是在运行时设置的，而不是从翻译键设置的）。
    const _tipSel = '[data-tip-key],[data-tip-float]';
    document.addEventListener('mouseover', (e) => {
        const target = e.target.closest(_tipSel);
        if (target) showTip(target);
    });
    document.addEventListener('mouseout', (e) => {
        const target = e.target.closest(_tipSel);
        if (target) hideTip();
    });
    // 滚动/调整大小时隐藏，以便工具提示不会偏离其锚点。
    window.addEventListener('scroll', hideTip, true);
    window.addEventListener('resize', hideTip);
}

// =====================================================================
// 主题
// =====================================================================
let currentTheme = localStorage.getItem('cow_theme') || 'dark';

function applyTheme() {
    const root = document.documentElement;
    if (currentTheme === 'dark') {
        root.classList.add('dark');
        document.getElementById('theme-icon').className = 'fas fa-sun';
        document.getElementById('hljs-light').disabled = true;
        document.getElementById('hljs-dark').disabled = false;
    } else {
        root.classList.remove('dark');
        document.getElementById('theme-icon').className = 'fas fa-moon';
        document.getElementById('hljs-light').disabled = false;
        document.getElementById('hljs-dark').disabled = true;
    }
}

function toggleTheme() {
    currentTheme = currentTheme === 'dark' ? 'light' : 'dark';
    localStorage.setItem('cow_theme', currentTheme);
    applyTheme();
}

// =====================================================================
// 任务完成通知（客户端优先）
// =====================================================================
const TASK_NOTIFY_KEY = 'cow_task_notify';
const TASK_NOTIFY_SOUND_KEY = 'cow_task_notify_sound';
let taskNotifyEnabled = localStorage.getItem(TASK_NOTIFY_KEY) !== '0';
let taskNotifySound = localStorage.getItem(TASK_NOTIFY_SOUND_KEY) !== '0';
let notifyAudioCtx = null;
let unreadCount = 0;
const baseDocTitle = document.title;

// 在第一个用户手势上解锁音频；否则浏览器会阻止自动播放。
document.addEventListener('pointerdown', function() {
    if (window.AudioContext) notifyAudioCtx = notifyAudioCtx || new AudioContext();
    if (notifyAudioCtx && notifyAudioCtx.state === 'suspended') {
        notifyAudioCtx.resume().catch(function() {});
    }
}, { once: true });

function playNotifyBeep() {
    if (!taskNotifySound) return;
    try {
        if (!notifyAudioCtx) {
            const Ctx = window.AudioContext || window.webkitAudioContext;
            if (!Ctx) return;
            notifyAudioCtx = new Ctx();
        }
        if (notifyAudioCtx.state === 'suspended') {
            notifyAudioCtx.resume().catch(function() {});
        }
        // 两个短正弦音（A5 → D6）；不需要音频资源。
        const t0 = notifyAudioCtx.currentTime;
        [880, 1174.66].forEach(function(freq, i) {
            const at = t0 + i * 0.09;
            const osc = notifyAudioCtx.createOscillator();
            const gain = notifyAudioCtx.createGain();
            osc.type = 'sine';
            osc.frequency.value = freq;
            gain.gain.setValueAtTime(0.001, at);
            gain.gain.exponentialRampToValueAtTime(0.12, at + 0.01);
            gain.gain.exponentialRampToValueAtTime(0.001, at + 0.09);
            osc.connect(gain).connect(notifyAudioCtx.destination);
            osc.start(at);
            osc.stop(at + 0.1);
        });
    } catch (_) {
        // 自动播放仍然被阻止或 AudioContext 不可用；保持沉默。
    }
}

function firstLineSnippet(text) {
    return (text || '').split('\n')[0].trim().slice(0, 80);
}

function sessionTitleOf(sid) {
    const el = document.querySelector(`.session-item[data-session-id="${sid}"] .session-title`);
    return el ? el.textContent.trim() : '';
}

function popNotification(title, body, sid) {
    if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return;
    try {
        const n = new Notification(title, { body: body || title });
        n.onclick = function() {
            window.focus();
            if (sid && sid !== sessionId) switchSession(sid);
            n.close();
        };
    } catch (_) {
        // 通知API不可用；蜂鸣声 + 头衔徽章仍然适用。
    }
}

function showTaskNotification(title, body, sid) {
    if (!taskNotifyEnabled) return;
    // 仅在窗口未聚焦时发出通知。如果用户主动
    // 观看选项卡，回复已在屏幕上 - 通知/蜂鸣声
    // 只会是噪音（特别是对于短期任务）。
    if (document.hasFocus()) return;
    playNotifyBeep();
    if (document.hidden) {
        unreadCount += 1;
        document.title = `(${unreadCount}) ${baseDocTitle}`;
    }
    if (typeof Notification === 'undefined') return;
    // 第一次我们实际上需要通知（窗口在后台）：
    // 立即请求许可，然后在获得许可后显示此通知。这个
    // 比页面加载提示更符合上下文。
    if (Notification.permission === 'default') {
        Notification.requestPermission()
            .then(function(perm) {
                if (perm === 'granted') popNotification(title, body, sid);
                else refreshNotifyBlockedHint();
            })
            .catch(function() {});
        return;
    }
    if (Notification.permission === 'denied') {
        // 无法通知；在设置中显示提示，以便用户知道原因。
        refreshNotifyBlockedHint();
        return;
    }
    popNotification(title, body, sid);
}

function notifyTaskFinished(sid, kind, text) {
    const label = t(kind === 'error' ? 'notify_task_error' : 'notify_task_done');
    const snippet = firstLineSnippet(text);
    showTaskNotification(sessionTitleOf(sid) || label, snippet ? `${label}: ${snippet}` : label, sid);
}

document.addEventListener('visibilitychange', function() {
    if (!document.hidden) {
        unreadCount = 0;
        document.title = baseDocTitle;
    }
});

// 启用通知时请求操作系统通知权限，并且
// 浏览器还没有决定。可以安全地重复调用。
function ensureNotifyPermission() {
    if (taskNotifyEnabled
        && typeof Notification !== 'undefined'
        && Notification.permission === 'default') {
        Notification.requestPermission().catch(function() {});
    }
}

// 仅当启用通知时显示“被浏览器阻止”提示，但
// 浏览器权限被拒绝（应用程序无法在代码中对此执行任何操作）。
function refreshNotifyBlockedHint() {
    const el = document.getElementById('cfg-task-notify-blocked');
    if (!el) return;
    const blocked = taskNotifyEnabled
        && typeof Notification !== 'undefined'
        && Notification.permission === 'denied';
    el.classList.toggle('hidden', !blocked);
}

function initTaskNotifyToggles() {
    const notifyEl = document.getElementById('cfg-task-notify');
    if (notifyEl) {
        notifyEl.checked = taskNotifyEnabled;
        notifyEl.addEventListener('change', function() {
            taskNotifyEnabled = notifyEl.checked;
            localStorage.setItem(TASK_NOTIFY_KEY, taskNotifyEnabled ? '1' : '0');
            ensureNotifyPermission();
            refreshNotifyBlockedHint();
        });
    }
    const soundEl = document.getElementById('cfg-task-notify-sound');
    if (soundEl) {
        soundEl.checked = taskNotifySound;
        soundEl.addEventListener('change', function() {
            taskNotifySound = soundEl.checked;
            localStorage.setItem(TASK_NOTIFY_SOUND_KEY, taskNotifySound ? '1' : '0');
        });
    }
    refreshNotifyBlockedHint();
}

document.addEventListener('DOMContentLoaded', initTaskNotifyToggles);

// =====================================================================
// 侧边栏和导航
// =====================================================================
const VIEW_META = {
    chat:     { group: 'nav_chat',    page: 'menu_chat' },
    agents:   { group: 'nav_manage',  page: 'menu_agents' },
    config:   { group: 'nav_manage',  page: 'menu_config' },
    skills:   { group: 'nav_manage',  page: 'menu_skills' },
    memory:   { group: 'nav_manage',  page: 'menu_memory' },
    knowledge:{ group: 'nav_manage',  page: 'menu_knowledge' },
    channels: { group: 'nav_manage',  page: 'menu_channels' },
    tasks:    { group: 'nav_manage',  page: 'menu_tasks' },
    logs:     { group: 'nav_monitor', page: 'menu_logs' },
};

let currentView = 'chat';

function navigateTo(viewId) {
    if (!VIEW_META[viewId]) return;
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    const target = document.getElementById('view-' + viewId);
    if (target) target.classList.add('active');
    document.querySelectorAll('.sidebar-item').forEach(item => {
        item.classList.toggle('active', item.dataset.view === viewId);
    });
    const meta = VIEW_META[viewId];
    document.getElementById('breadcrumb-group').textContent = t(meta.group);
    document.getElementById('breadcrumb-group').dataset.i18n = meta.group;
    document.getElementById('breadcrumb-page').textContent = t(meta.page);
    document.getElementById('breadcrumb-page').dataset.i18n = meta.page;
    const leavingAgents = currentView === 'agents' && viewId !== 'agents';
    currentView = viewId;
    // 代理详细信息是一个固定抽屉，因此它会悬挂在上面
    // 无论您导航到哪个视图。它仅属于代理团队页面。
    if (viewId !== 'agents') closeAgentDetail();
    if (viewId === 'agents') {
        // 团队页面是一个宽阔的两窗格工作台；顶部的历史记录面板
        // 它会使细节变得狭窄。将其收起并放在入口处
        // 恢复到用户离开时的状态（仅当他们还没有离开时）
        // 同时自行切换）。
        _sessionPanelWasOpen = sessionPanelOpen;
        if (sessionPanelOpen) closeSessionPanel(true);
        loadAgentCatalog();
    } else if (leavingAgents && _sessionPanelWasOpen) {
        _sessionPanelWasOpen = false;
        openSessionPanel();
    }
    
    // 离开时清除状态消息
    document.querySelectorAll('[id$="-status"]').forEach(el => {
        el.classList.add('opacity-0');
    });
    
    if (window.innerWidth < 1024) closeSidebar();
}

function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebar-overlay');
    const isOpen = !sidebar.classList.contains('-translate-x-full');
    if (isOpen) {
        closeSidebar();
    } else {
        sidebar.classList.remove('-translate-x-full');
        overlay.classList.remove('hidden');
    }
}

function closeSidebar() {
    document.getElementById('sidebar').classList.add('-translate-x-full');
    document.getElementById('sidebar-overlay').classList.add('hidden');
}

document.querySelectorAll('.menu-group > button').forEach(btn => {
    btn.addEventListener('click', () => {
        btn.parentElement.classList.toggle('open');
    });
});

document.querySelectorAll('.sidebar-item').forEach(item => {
    item.addEventListener('click', () => navigateTo(item.dataset.view));
});

window.addEventListener('resize', () => {
    if (window.innerWidth >= 1024) {
        document.getElementById('sidebar').classList.remove('-translate-x-full');
        document.getElementById('sidebar-overlay').classList.add('hidden');
    } else {
        if (!document.getElementById('sidebar').classList.contains('-translate-x-full')) {
            closeSidebar();
        }
    }
});

// =====================================================================
// 代理商
// =====================================================================
let agentCatalog = [];
let channelInstances = [];
let rosterRevision = '';
let defaultAgentId = localStorage.getItem('cow_default_agent') || 'default';
let selectedAdminAgentId = '';
let selectedCoreRevision = '';
let installedSkills = [];

function findAgent(agentId) {
    return agentCatalog.find(a => a.id === agentId) || null;
}

function enabledAgents() {
    return agentCatalog.filter(a => a.enabled);
}

/* 上传的头像每次都会重复使用相同的 URL，因此浏览器会保留
   服务过时的字节。仅当名单的
   *内容*发生变化，并且重新上传现有图像时，该字段将保留为
   相同的“图像”令牌 - 因此我们用新的令牌标记每个成功的上传
   这里并更喜欢它，这会强制重新获取显示新图片的内容。 */
const avatarVersions = {};

/* 首字母回退循环经过多少张静音光盘。 */
const AVATAR_TONES = 6;

/* 特工获得哪张光盘。单独关闭ID，所以面孔永远不会改变
   一旦代理存在，颜色，因此创建模式中的草稿（还没有 id）
   坐在中性音上，而不是在输入名称时移动。 */
function avatarTone(agentId) {
    const key = String(agentId || '');
    let hash = 0;
    for (let i = 0; i < key.length; i++) hash = (hash * 31 + key.charCodeAt(i)) >>> 0;
    return hash % AVATAR_TONES;
}

/* 代理没有图片时显示的角色。 Array.from 而是
   比 [0] 因此星体平面角色被视为完整而不是半个
   代理对；拉丁文大写，不区分大小写的脚本则单独保留。 */
function avatarInitial(name) {
    return (Array.from(String(name || '').trim())[0] || '').toUpperCase();
}

/* 每个特工都有自己的面孔：其所有者上传的图像，或静音光盘
   带有其名称的第一个字符。缩写而不是产品
   徽标使团队一目了然，低饱和度色调使
   他们的名单保持安静。

   空代理意味着 id 不再解析 - 对话固定到
   自删除代理。退回到默认特工的脸部而不是
   空光盘，因此删除的代理明显降级为默认代理。 */
function agentAvatarHTML(agent, size) {
    const cls = `agent-avatar agent-avatar-${size || 32}`;
    if (!agent && defaultAgentId) {
        agent = findAgent(defaultAgentId);
    }
    if (agent && agent.avatar === 'image') {
        const v = avatarVersions[agent.id] || rosterRevision || agent.id;
        return `<img class="${cls}" src="/api/agents/${encodeURIComponent(agent.id)}/avatar?v=${encodeURIComponent(v)}" alt="">`;
    }
    const initial = avatarInitial(agent && (agent.name || agent.id));
    return `<span class="${cls} agent-avatar-tone-${avatarTone(agent && agent.id)}">${escapeHtml(initial)}</span>`;
}

/* 在屏幕上已有的气泡上重新绘制脸部。气泡渲染一次并且
   单独留下，因此在“设置”中更改的头像将继续显示
   公开对话中的旧图片直到重新加载。每个机器人泡沫都会记住
   它的扬声器；加载指示器跟随活动代理。 */
function refreshBubbleAvatars() {
    const container = document.getElementById('chat-messages');
    if (!container) return;
    container.querySelectorAll('.bot-face').forEach(face => {
        const group = face.closest('.bot-message-group');
        // 泡沫知道它的说话者；加载指示器（无组）跟踪
        // 活跃代理，唯一可以在单人聊天中进行回复的代理。
        const id = (group && group.dataset.speakerAgent) || activeAgentId;
        face.innerHTML = agentAvatarHTML(findAgent(id), 32);
    });
}

// 从名称派生 ascii slug，或者当没有可使用的 ascii 时派生 ''
// （例如用中文写的名字）。调用者退回到 randomAgentId()。
function slugAgentId(name) {
    return String(name || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 32);
}

// 不产生 slug 的名称的 id。
function randomAgentId() {
    return 'agent-' + Math.random().toString(36).slice(2, 8);
}

function loadAgentCatalog() {
    return fetch('/api/agents')
        .then(r => r.json())
        .then(data => {
            if (data.status !== 'success') throw new Error(data.message || 'Failed to load Agents');
            agentCatalog = data.agents || [];
            channelInstances = data.channel_instances || [];
            rosterRevision = data.revision || '';
            defaultAgentId = data.default_agent_id || (agentCatalog[0] && agentCatalog[0].id) || 'default';
            localStorage.setItem('cow_default_agent', defaultAgentId);
            // 默认代理引导它出现的每个列表——菜单、网格、
            // 内存选择器 - 所以它的位置永远不依赖于加载顺序。
            agentCatalog.sort((a, b) => (b.id === defaultAgentId) - (a.id === defaultAgentId));
            const enabled = enabledAgents();
            if (!enabled.some(a => a.id === activeAgentId)) {
                activeAgentId = defaultAgentId;
                localStorage.setItem('cow_active_agent', activeAgentId);
            }
            if (!selectedAdminAgentId || !agentCatalog.some(a => a.id === selectedAdminAgentId)) {
                selectedAdminAgentId = '';
            }
            // 两窗格工作台：在宽屏幕上，降落在第一个代理上，以便
            // 右窗格永远不是空白占位符。在手机上该列表显示
            // 首先（详细信息是一张纸），所以不要在那里留下任何选择。
            if (!selectedAdminAgentId && currentView === 'agents'
                    && agentCatalog.length && window.innerWidth > 900) {
                openAgentDetail((enabledAgents()[0] || agentCatalog[0]).id);
                return data;
            }
            renderAgentsGrid();
            if (selectedAdminAgentId) renderAgentDetail();
            else closeAgentDetail();
            renderComposerIdentity();
            renderMemoryAgentSelect();
            // 新聊天按钮只会在出现时出现一个菜单（及其插入符号）
            // 有多个代理可供选择。
            document.getElementById('new-chat-caret')?.classList.toggle('hidden', !multiAgentMode());
            // 姓名或头像可能已更改；保留屏幕上已存在的面孔
            // 与名册同步，而不仅仅是新的气泡。
            refreshBubbleAvatars();
            return data;
        })
        .catch(err => {
            const status = document.getElementById('agent-editor-status');
            if (status) status.textContent = err.message;
        });
}

function renderAgentsGrid() {
    const grid = document.getElementById('agents-grid');
    if (!grid) return;
    if (!agentCatalog.length) {
        grid.innerHTML = `<div class="col-span-full text-sm text-slate-400 py-16 text-center">${escapeHtml(t('agents_empty'))}</div>`;
        return;
    }
    grid.innerHTML = agentCatalog.map(agent => {
        const selected = agent.id === selectedAdminAgentId;
        const desc = (agent.description || '').trim();
        // 状态芯片漂浮在右上角，因此“默认”或
        // “存档”卡与其他卡一样高。
        const corner = agent.id === defaultAgentId
            ? `<span class="agent-card-badge agent-chip-on">${escapeHtml(t('agents_default'))}</span>`
            : (!agent.enabled ? `<span class="agent-card-badge">${escapeHtml(t('agents_archived'))}</span>` : '');
        return `<div class="agent-card${selected ? ' selected' : ''}${agent.enabled ? '' : ' archived'}" onclick="openAgentDetail('${escapeHtml(agent.id)}')">
            ${corner}
            <div class="agent-card-top">
                ${agentAvatarHTML(agent, 32)}
                <div class="min-w-0 flex-1">
                    <div class="agent-card-name truncate">${escapeHtml(agent.name)}</div>
                    <div class="agent-card-desc">${desc ? escapeHtml(desc) : `<span class="agent-card-desc-empty">${escapeHtml(t('agents_no_desc'))}</span>`}</div>
                </div>
            </div>
        </div>`;
    }).join('');
}

function openAgentDetail(agentId) {
    selectedAdminAgentId = agentId;
    document.getElementById('agent-detail')?.classList.remove('hidden');
    renderAgentsGrid();
    renderAgentDetail();
    // 将每个代理的核心文件选择器重置为干净状态，而不是
    // 保留选择的文件/查看模式
    // 上一篇。
    const fileDd = document.getElementById('agent-core-file');
    if (fileDd) fileDd._ddValue = 'AGENT.md';
    setAgentCoreViewMode('edit');
    loadAgentCoreFile();
    // 模型选择器是从作曲家使用的同一目录中提取的，其中
    // 取决于哪些提供商拥有密钥。到达后重新渲染。
    if (!_sessCfg) refreshSessionSettings().then(() => {
        if (selectedAdminAgentId === agentId) renderAgentDetail();
    });
}

function closeAgentDetail() {
    selectedAdminAgentId = '';
    const detail = document.getElementById('agent-detail');
    if (detail) {
        detail.classList.add('hidden');
        // 空窗格的占位符文本（桌面两窗格布局）。
        detail.setAttribute('data-empty-label', t('agents_select_hint'));
    }
    renderAgentsGrid();
}

function selectAgentDetailTab(tab) {
    document.querySelectorAll('.agent-detail-tab').forEach(el => {
        el.classList.toggle('active', el.dataset.tab === tab);
    });
    ['profile', 'skills', 'files'].forEach(name => {
        document.getElementById(`agent-detail-${name}`)?.classList.toggle('hidden', name !== tab);
    });
    if (tab === 'skills') renderAgentSkillsPane();
    if (tab === 'files') loadAgentCoreFile();
}

// 字段标签后跟一个小信息图标，其帮助会在悬停时显示，因此
// 表单保持紧凑，而不是在每个字段下都带有一段提示。
// 提示文本可能包含 \n 以强制换行（例如每个选项一行
// 共享/自己的选择）——通过弹出窗口的 `white-space: pre-line` 呈现。
function fieldLabelWithTip(label, tip) {
    return `<div class="agent-field-label-row">
        <label class="agent-field-label">${escapeHtml(label)}</label>
        <span class="agent-field-tip" data-tip="${escapeHtml(tip)}"><i class="fas fa-circle-info"></i></span>
    </div>`;
}

// 单个弹出窗口实例固定到 <body>，相对于任何一个进行定位
// .agent-field-tip 悬停。生活在每个抽屉/模态之外意味着它是
// 永远不会被祖先的 `overflow: auto` 剪裁（与 CSS ::after 不同）
// 位于滚动代理详细信息窗格内）。
let _fieldTipEl = null;
let _fieldTipIcon = null;  // 弹出窗口当前属于哪个图标
function _ensureFieldTipEl() {
    if (!_fieldTipEl) {
        _fieldTipEl = document.createElement('div');
        _fieldTipEl.className = 'agent-tip-popup';
        document.body.appendChild(_fieldTipEl);
    }
    return _fieldTipEl;
}

function _showFieldTip(iconEl) {
    const tip = iconEl.dataset.tip;
    if (!tip) return;
    // 已显示此图标：请勿重新测量/重新设置动画。移动
    // 光标从 <span> 移到其自己的 <i> 上，否则会重新触发
    // 整个显示序列并使尖端明显闪烁。
    if (_fieldTipIcon === iconEl && _fieldTipEl && _fieldTipEl.classList.contains('show')) return;
    _fieldTipIcon = iconEl;
    const popup = _ensureFieldTipEl();
    popup.textContent = tip;
    popup.classList.remove('show');
    popup.style.left = '0px';
    popup.style.top = '0px';
    // 布局后测量，以便宽度/高度反映实际情况（可能
    // 多行）内容，然后将其夹入视口。
    requestAnimationFrame(() => {
        const rect = iconEl.getBoundingClientRect();
        const pw = popup.offsetWidth, ph = popup.offsetHeight;
        let left = rect.left + rect.width / 2 - pw / 2;
        const margin = 8;
        left = Math.max(margin, Math.min(left, window.innerWidth - pw - margin));
        let top = rect.top - ph - 8;
        let arrowTop = false;
        if (top < margin) { top = rect.bottom + 8; arrowTop = true; } // 如果在上面剪裁，则翻转到下面
        popup.style.left = `${left}px`;
        popup.style.top = `${top}px`;
        popup.style.setProperty('--tip-arrow-x', `${rect.left + rect.width / 2 - left}px`);
        popup.classList.toggle('tip-arrow-top', arrowTop);
        popup.classList.add('show');
    });
}

function _hideFieldTip() {
    if (_fieldTipEl) _fieldTipEl.classList.remove('show');
    _fieldTipIcon = null;
}

document.addEventListener('mouseover', (e) => {
    const icon = e.target.closest ? e.target.closest('.agent-field-tip') : null;
    if (icon) _showFieldTip(icon);
});
document.addEventListener('mouseout', (e) => {
    const icon = e.target.closest ? e.target.closest('.agent-field-tip') : null;
    if (!icon) return;
    // mouseout 在图标自己的子图标之间移动时触发（span -> <i>）。
    // 仅当光标实际离开该图标的子树时才隐藏，即
    // 它移动到的元素不在同一个 .agent-field-tip 内。
    const to = e.relatedTarget;
    if (to && icon.contains(to)) return;
    _hideFieldTip();
});
document.addEventListener('scroll', _hideFieldTip, true);

function renderAgentDetail() {
    const agent = findAgent(selectedAdminAgentId);
    const identity = document.getElementById('agent-detail-identity');
    const profile = document.getElementById('agent-detail-profile');
    if (!agent || !identity || !profile) return;
    identity.innerHTML = `
        ${agentAvatarHTML(agent, 56)}
        <div class="min-w-0">
            <div class="text-lg font-semibold text-slate-800 dark:text-slate-100 truncate">${escapeHtml(agent.name)}</div>
            <div class="text-xs text-slate-400 font-mono truncate">${escapeHtml(agent.id)}</div>
        </div>`;
    const isDefault = agent.id === defaultAgentId;
    profile.innerHTML = `
        <div class="agent-field">
            <label class="agent-field-label">${escapeHtml(t('agents_avatar'))}</label>
            <div id="agent-edit-avatar" class="agent-avatar-picker"></div>
        </div>
        <div class="agent-field">
            <label class="agent-field-label">${escapeHtml(t('agents_name'))}</label>
            <input id="agent-edit-name" value="${escapeHtml(agent.name)}" class="agent-input">
        </div>
        <div class="agent-field">
            ${fieldLabelWithTip(t('agents_description'), t('agents_description_hint'))}
            <textarea id="agent-edit-description" rows="4"
                   placeholder="${escapeHtml(t('agents_description_placeholder'))}"
                   class="agent-input agent-textarea">${escapeHtml(agent.description || '')}</textarea>
        </div>
        <div class="agent-field">
            <label class="agent-field-label">${escapeHtml(t('agents_model'))}</label>
            ${isDefault
                ? `<div class="agent-input-locked">${escapeHtml(t('agents_model_follows_global'))}</div>
                   <p class="agent-field-hint">${escapeHtml(t('agents_model_default_hint'))}</p>`
                : `<div id="agent-edit-model" class="cfg-dropdown" tabindex="0">
                       <div class="cfg-dropdown-selected">
                           <span class="cfg-dropdown-text">--</span>
                           <i class="fas fa-chevron-down cfg-dropdown-arrow"></i>
                       </div>
                       <div class="cfg-dropdown-menu"></div>
                   </div>`}
        </div>
        ${isDefault ? '' : `
        <div class="agent-field">
            ${fieldLabelWithTip(t('agents_knowledge'), t('agents_knowledge_hint'))}
            <div class="flex items-center gap-3">
                <div id="agent-knowledge-toggle" class="agent-seg" role="group">
                    <button type="button" class="agent-seg-btn ${agent.knowledge_mode !== 'own' ? 'active' : ''}" data-mode="shared" onclick="setAgentKnowledgeMode('${escapeHtml(agent.id)}','shared')">
                        <i class="fas fa-users mr-1"></i>${escapeHtml(t('agents_knowledge_shared'))}
                    </button>
                    <button type="button" class="agent-seg-btn ${agent.knowledge_mode === 'own' ? 'active' : ''}" data-mode="own" onclick="setAgentKnowledgeMode('${escapeHtml(agent.id)}','own')">
                        <i class="fas fa-box-archive mr-1"></i>${escapeHtml(t('agents_knowledge_own'))}
                    </button>
                </div>
                <span id="agent-knowledge-status" class="agent-field-hint" style="margin-top:0"></span>
            </div>
        </div>`}
        <div class="agent-detail-actions">
            <button type="button" onclick="saveAgentProfile()" class="agent-btn agent-btn-primary">${escapeHtml(t('save'))}</button>
            <button type="button" onclick="startChatWithAgent('${escapeHtml(agent.id)}')" class="agent-btn agent-btn-ghost">${escapeHtml(t('agents_chat'))}</button>
            ${isDefault ? '' : `<button type="button" onclick="deleteAgent('${escapeHtml(agent.id)}')" class="agent-btn agent-btn-danger agent-detail-delete">${escapeHtml(t('agents_delete'))}</button>`}
        </div>
        <div id="agent-profile-status" class="agent-field-hint mt-3"></div>`;

    renderAvatarPicker('agent-edit-avatar', agent, (file) => uploadAgentAvatar(agent.id, file));

    if (!isDefault) {
        const dd = document.getElementById('agent-edit-model');
        const opts = agentModelDropdownOptions();
        const current = agent.model ? `${agent.bot_type || ''}|${agent.model}` : '';
        initDropdown(dd, opts, current, () => {}, { placeholder: t('agents_model_follows_global') });
    }
    // 保存可能会多次重新渲染此窗格；重新申请飞行中
    // “已保存”确认，因此它可以生存而不是被擦除。
    paintAgentSavedFlash();
}

/* 上传按钮旁边的实时预览，采用页面自己的样式，而不是
   原始文件输入。默认为Agent的首字母；上传将其替换为
   所选图像。当 Agent 尚不存在时， `onUpload` 可能为 null
   （创建模式），只留下预览。 */
function renderAvatarPicker(containerId, agent, onUpload) {
    const box = document.getElementById(containerId);
    if (!box) return;
    box.innerHTML = `
        <div class="agent-avatar-picker-preview">${agentAvatarHTML(agent, 56)}</div>
        <div class="agent-avatar-picker-body">
            ${onUpload ? `<button type="button" class="agent-avatar-upload">
                <i class="fas fa-arrow-up-from-bracket"></i><span>${escapeHtml(t('agents_avatar_upload'))}</span>
                <input type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden>
            </button>` : ''}
        </div>`;
    const upload = box.querySelector('.agent-avatar-upload');
    if (upload && onUpload) {
        const input = upload.querySelector('input');
        upload.addEventListener('click', () => input.click());
        input.addEventListener('change', () => onUpload(input.files && input.files[0]));
    }
}

/* 扁平化样式下拉列表：每个模型一行，其提供者包含在
   值（向错误供应商询问的型号是错误的），其品牌显示为
   一个模糊的暗示。第一行清除选择回到配置的模型。 */
function agentModelDropdownOptions() {
    const opts = [{ value: '', label: t('agents_model_follows_global') }];
    const providers = (_sessCfg && _sessCfg.model && _sessCfg.model.providers) || [];
    providers.forEach(p => {
        (p.models || []).forEach(m => {
            opts.push({ value: `${p.id}|${m}`, label: m, hint: localizedLabel(p.label) });
        });
    });
    return opts;
}

// 保留特工的技能选择。写入按代理序列化，并且
// 合并到最新的所需状态，因此勾选几个框可以快速发送
// 它们按顺序排列（每个都有前一个返回的修订版）而不是
// 比赛并绊倒陈旧的守卫。不会发生目录重新加载，因此
// 网格、作曲家和头像永远不会闪烁，复选框也永远不会跳跃。
//   null -> 使用每个已安装的技能（“使用全部”主开关）
//   [...] -> 正是这个子集（[] 表示没有）
const _skillSaveState = {};  // agentId -> { 飞行中：bool，待定：技能|未定义 }

function saveAgentSkills(agent, skills) {
    agent.skills = skills;  // 乐观；窗格已经反映了它
    const st = _skillSaveState[agent.id] || (_skillSaveState[agent.id] = { inflight: false, pending: undefined });
    if (st.inflight) { st.pending = skills; return; }  // 最新胜利；丢弃陈旧的中间体
    st.inflight = true;
    fetch('/api/agents', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'update', id: agent.id, revision: rosterRevision, skills }),
    }).then(r => r.json()).then(data => {
        if (data.status === 'success') {
            if (data.revision) rosterRevision = data.revision;
        } else {
            const status = document.getElementById('agent-editor-status');
            if (status) status.textContent = data.message || 'Update failed';
        }
    }).catch(() => {}).then(() => {
        st.inflight = false;
        if (st.pending !== undefined) {
            const next = st.pending;
            st.pending = undefined;
            saveAgentSkills(agent, next);  // 刷新最新的排队状态
        }
    });
}

// 在共享知识库和自己的知识库之间切换代理。这是一个
// 文件系统切换（符号链接与真实知识/目录），因此它立即适用
// 而不是等待配置文件“保存”。
async function setAgentKnowledgeMode(agentId, mode) {
    const agent = findAgent(agentId);
    if (!agent || agent.knowledge_mode === mode) return;
    const status = document.getElementById('agent-knowledge-status');
    const paintActive = (m) => document.querySelectorAll('#agent-knowledge-toggle .agent-seg-btn')
        .forEach(b => b.classList.toggle('active', b.dataset.mode === m));
    const prev = agent.knowledge_mode || 'shared';
    agent.knowledge_mode = mode;  // 乐观的
    paintActive(mode);
    if (status) status.textContent = t('agents_knowledge_working') || '...';
    try {
        const res = await fetch('/api/agents', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'set_knowledge_mode', id: agentId, mode }),
        });
        const data = await res.json();
        if (data.status === 'success') {
            agent.knowledge_mode = (data.mode || mode);
            paintActive(agent.knowledge_mode);
            if (status) status.textContent = '';
        } else {
            agent.knowledge_mode = prev;  // 回滚
            paintActive(prev);
            if (status) status.textContent = data.message || t('agents_knowledge_failed') || 'Failed';
        }
    } catch (e) {
        agent.knowledge_mode = prev;
        paintActive(prev);
        if (status) status.textContent = t('agents_knowledge_failed') || 'Failed';
    }
}

function renderAgentSkillsPane() {
    const pane = document.getElementById('agent-detail-skills');
    const agent = findAgent(selectedAdminAgentId);
    if (!pane || !agent) return;
    const render = () => {
        const all = agent.skills == null;
        const picked = new Set(all ? [] : agent.skills);
        pane.innerHTML = `
            <label class="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300 mb-3">
                <input type="checkbox" id="agent-skills-all" ${all ? 'checked' : ''}>
                <span>${escapeHtml(t('agents_skills_all'))}</span>
            </label>
            <p class="text-xs text-slate-400 mb-3">${escapeHtml(t('agents_skills_pick'))}</p>
            ${(installedSkills || []).map(skill => {
                const name = skill.name || skill.id;
                const checked = all || picked.has(name);
                return `<label class="agent-skill-row">
                    <input type="checkbox" class="agent-skill-item" value="${escapeHtml(name)}" ${checked ? 'checked' : ''} ${all ? 'disabled' : ''}>
                    <div>
                        <div class="text-sm text-slate-700 dark:text-slate-200">${escapeHtml(skill.display_name || name)}</div>
                        <div class="text-xs text-slate-400">${escapeHtml(skill.description || '')}</div>
                    </div>
                </label>`;
            }).join('')}`;
        document.getElementById('agent-skills-all')?.addEventListener('change', (e) => {
            // 切换仅翻转 ALL <-> 空子集。关闭它从
            // 一个空列表，以便用户准确地选择他们想要的内容，并且
            // 存储的值是[]而不是完整的枚举。
            const next = e.target.checked ? null : [];
            saveAgentSkills(agent, next);
            render();  // 就地重绘——无页面范围的重新加载，无闪烁
        });
        pane.querySelectorAll('.agent-skill-item').forEach(box => {
            box.addEventListener('change', () => {
                const names = Array.from(pane.querySelectorAll('.agent-skill-item:checked')).map(el => el.value);
                saveAgentSkills(agent, names);
            });
        });
    };
    if (installedSkills.length) {
        render();
        return;
    }
    fetch('/api/skills').then(r => r.json()).then(data => {
        installedSkills = data.skills || [];
        render();
    }).catch(() => {
        pane.innerHTML = `<p class="text-sm text-slate-400">${escapeHtml(t('agents_skills_all'))}</p>`;
    });
}

// 在打开创建模式和成功创建之间举行：所选择的
// 在代理存在之前，头像无法在服务器端生存，因此我们保留
// 文件及其预览 URL 客户端并在创建返回后上传。
let _pendingCreateAvatar = null;
let _createKnowledgeMode = 'shared';

// 填写的 Agent 看起来像：还没有 id，所以光盘是
// 中性语气，名字后面只有首字母。
function createAvatarDraft() {
    const name = document.getElementById('agent-create-name');
    return { id: '', name: (name && name.value) || '', avatar: '' };
}

// 键入名称时仅重新绘制预览光盘。整个选择器不是
// 重新渲染，因为这会在每次击键时重新绑定上传输入。
function refreshCreateAvatarPreview() {
    if (_pendingCreateAvatar) return;
    const slot = document.querySelector('#agent-create-avatar .agent-avatar-picker-preview');
    if (slot) slot.innerHTML = agentAvatarHTML(createAvatarDraft(), 56);
}

// 创建模式的头像选择器：与编辑模式相同，但上传
// 在本地暂存（从对象 URL 预览）而不是立即发布。
function renderCreateAvatarPicker() {
    const box = document.getElementById('agent-create-avatar');
    if (!box) return;
    const preview = _pendingCreateAvatar
        ? `<img class="agent-avatar agent-avatar-56" src="${_pendingCreateAvatar.url}" alt="">`
        : agentAvatarHTML(createAvatarDraft(), 56);
    box.innerHTML = `
        <div class="agent-avatar-picker-preview">${preview}</div>
        <div class="agent-avatar-picker-body">
            <button type="button" class="agent-avatar-upload">
                <i class="fas fa-arrow-up-from-bracket"></i><span>${escapeHtml(t('agents_avatar_upload'))}</span>
                <input type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden>
            </button>
        </div>`;
    const upload = box.querySelector('.agent-avatar-upload');
    const input = upload.querySelector('input');
    upload.addEventListener('click', () => input.click());
    input.addEventListener('change', () => {
        const file = input.files && input.files[0];
        if (!file) return;
        if (_pendingCreateAvatar && _pendingCreateAvatar.url) URL.revokeObjectURL(_pendingCreateAvatar.url);
        _pendingCreateAvatar = { file, url: URL.createObjectURL(file) };
        renderCreateAvatarPicker();
    });
}

function openAgentCreateForm() {
    const form = document.getElementById('agent-create-form');
    if (!form) return;
    form.classList.remove('hidden');
    const name = document.getElementById('agent-create-name');
    // id 是手写的或故意留空；没有任何内容写入它
    // 当表格打开时。提交时填写一次空白。
    const id = document.getElementById('agent-create-id');
    const description = document.getElementById('agent-create-description');
    [name, id, description].forEach(el => { if (el) el.value = ''; });
    document.getElementById('agent-create-status').textContent = '';

    // 代理还没有地方可以存储头像，因此上传被保存在
    // 内存并本地预览；创建成功后立即发布。
    _pendingCreateAvatar = null;
    renderCreateAvatarPicker();
    if (name && !name.dataset.avatarBound) {
        name.dataset.avatarBound = '1';
        // 如果没有上传，面孔是名字的第一个字符，所以
        // 预览必须遵循正在键入的内容。
        name.addEventListener('input', refreshCreateAvatarPreview);
    }

    // 知识默认共享；每次打开时重置分段控制。
    _createKnowledgeMode = 'shared';
    document.querySelectorAll('#agent-create-knowledge .agent-seg-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.mode === 'shared');
        if (!b.dataset.bound) {
            b.dataset.bound = '1';
            b.addEventListener('click', () => {
                _createKnowledgeMode = b.dataset.mode;
                document.querySelectorAll('#agent-create-knowledge .agent-seg-btn')
                    .forEach(x => x.classList.toggle('active', x === b));
            });
        }
    });

    const clone = document.getElementById('agent-create-clone');
    if (clone) {
        // 选项带有代理，因此行和触发器都显示其
        // 头像+姓名； “空白”（无克隆）没有面孔。
        const opts = [{ value: '', label: t('agents_clone_none') }].concat(
            enabledAgents().map(a => ({
                value: a.id,
                label: a.name || a.id,
                agent: a,
            }))
        );
        initDropdown(clone, opts, '', () => {});
    }
}

function closeAgentCreateForm() {
    document.getElementById('agent-create-form')?.classList.add('hidden');
    if (_pendingCreateAvatar && _pendingCreateAvatar.url) URL.revokeObjectURL(_pendingCreateAvatar.url);
    _pendingCreateAvatar = null;
}

document.addEventListener('click', (e) => {
    const menu = document.getElementById('composer-agent-menu');
    const btn = document.getElementById('composer-agent-btn');
    if (menu && !menu.classList.contains('hidden') && !menu.contains(e.target) && btn && !btn.contains(e.target)) {
        menu.classList.add('hidden');
    }
    const modal = document.getElementById('agent-create-form');
    if (modal && !modal.classList.contains('hidden') && e.target === modal) {
        closeAgentCreateForm();
    }
    const newMenu = document.getElementById('new-chat-menu');
    const newWrap = document.querySelector('.session-panel-new-wrap');
    if (newMenu && !newMenu.classList.contains('hidden') && newWrap && !newWrap.contains(e.target)) {
        newMenu.classList.add('hidden');
    }
    const teamModal = document.getElementById('team-chat-modal');
    if (teamModal && !teamModal.classList.contains('hidden') && e.target === teamModal) {
        closeTeamChatModal();
    }
});

function createAgentWorkspace() {
    const name = document.getElementById('agent-create-name').value.trim();
    const status = document.getElementById('agent-create-status');
    if (!name) {
        status.textContent = t('agents_name_required');
        return;
    }
    // 按给定方式使用手写 ID；空白又回到名字的鼻涕虫，
    // 然后当名称没有 ascii 来插入时随机选择一个（例如，它是
    // 中文写的）。在这里生成，而不是在输入字段时生成
    // 完全保持用户离开时的样子。
    const typed = document.getElementById('agent-create-id').value.trim();
    const id = typed || slugAgentId(name) || randomAgentId();
    // 镜像服务器的规则，因此在往返之前会捕获错误的 ID。
    if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(id)) {
        status.textContent = t('agents_id_invalid');
        return;
    }
    fetch('/api/agents', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            action: 'create',
            id,
            name,
            description: document.getElementById('agent-create-description')?.value.trim() || '',
            clone_from: getDropdownValue(document.getElementById('agent-create-clone')) || null,
            knowledge_mode: _createKnowledgeMode,
            revision: rosterRevision,
        }),
    }).then(r => r.json()).then(data => {
        if (data.status !== 'success') {
            throw new Error(data.code === 'stale_roster' ? t('agents_stale') : (data.message || 'Create failed'));
        }
        if (data.revision) rosterRevision = data.revision;
        // 现在工作区已存在，将暂存的头像（如果有）推送到之前
        // 正在重新加载，因此名册到达时已经带有新图像。
        const avatarStep = _pendingCreateAvatar
            ? uploadAgentAvatar(id, _pendingCreateAvatar.file).catch(() => {})
            : Promise.resolve();
        closeAgentCreateForm();
        return avatarStep.then(() => loadAgentCatalog()).then(() => openAgentDetail(id));
    }).catch(err => { status.textContent = err.message; });
}

function saveAgentProfile() {
    const agent = findAgent(selectedAdminAgentId);
    if (!agent) return;
    const payload = {
        name: document.getElementById('agent-edit-name')?.value.trim(),
        description: document.getElementById('agent-edit-description')?.value.trim() || '',
    };
    // 默认 Agent 不存在，它遵循配置的模型。
    const picker = document.getElementById('agent-edit-model');
    if (picker) {
        const [provider, model] = (getDropdownValue(picker) || '').split('|');
        payload.model = model || '';
        payload.bot_type = provider || '';
    }
    // 写入本身很快；后续目录重新加载速度很慢
    // （默认代理带有大量技能列表）。乐观地确认如此
    // 反馈是即时的，只有在保存实际失败时才会覆盖它。
    flashAgentProfileStatus();
    updateAgentWorkspace(agent.id, payload).then(ok => {
        if (!ok) {
            _agentSavedFlashUntil = 0;
            const status = document.getElementById('agent-profile-status');
            if (status) {
                status.textContent = t('agents_save_failed');
                status.classList.remove('agent-status-ok');
            }
        }
    });
}

/* 详细信息窗格状态行上的简短内联确认。保存重新加载
   目录，并且可以多次重新渲染此窗格（模型目录
   异步到达），因此确认将作为每次渲染的最后期限
   重新应用，而不是一次性写入，稍后渲染会擦除。 */
let _agentSavedFlashUntil = 0;

function paintAgentSavedFlash() {
    const status = document.getElementById('agent-profile-status');
    if (!status) return;
    if (Date.now() < _agentSavedFlashUntil) {
        status.textContent = t('agents_saved');
        status.classList.add('agent-status-ok');
    }
}

function flashAgentProfileStatus() {
    _agentSavedFlashUntil = Date.now() + 2200;
    paintAgentSavedFlash();
    clearTimeout(flashAgentProfileStatus._t);
    flashAgentProfileStatus._t = setTimeout(() => {
        _agentSavedFlashUntil = 0;
        const status = document.getElementById('agent-profile-status');
        if (!status) return;
        status.textContent = '';
        status.classList.remove('agent-status-ok');
    }, 2200);
}

function uploadAgentAvatar(agentId, file) {
    if (!file) return;
    const picker = document.getElementById('agent-edit-avatar');
    if (picker) picker.classList.add('is-uploading');
    const status = document.getElementById('agent-profile-status');
    if (status) { status.classList.remove('agent-status-ok'); status.textContent = ''; }
    const form = new FormData();
    form.append('avatar', file);
    return fetch(`/api/agents/${encodeURIComponent(agentId)}/avatar`, { method: 'POST', body: form })
        .then(r => r.json())
        .then(data => {
            if (data.status !== 'success') throw new Error(data.message || 'Upload failed');
            // 该图像已保留在服务器端。修补本地目录
            // 仅放置并重新绘制受影响的表面，而不是重新加载
            // 整个名册（当默认特工拥有许多技能时速度很慢）。
            avatarVersions[agentId] = String(Date.now());
            if (data.revision) rosterRevision = data.revision;
            const agent = findAgent(agentId);
            if (agent) agent.avatar = 'image';
            renderAgentsGrid();
            if (selectedAdminAgentId === agentId) renderAgentDetail();
            renderComposerIdentity();
            refreshBubbleAvatars();
            flashAgentProfileStatus();
        })
        .catch(err => {
            const s = document.getElementById('agent-profile-status');
            if (s) { s.classList.remove('agent-status-ok'); s.textContent = err.message; }
        })
        .then(() => {
            const p = document.getElementById('agent-edit-avatar');
            if (p) p.classList.remove('is-uploading');
        });
}

function updateAgentWorkspace(agentId, updates, _retried) {
    return fetch('/api/agents', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'update', id: agentId, revision: rosterRevision, ...updates }),
    }).then(r => r.json()).then(data => {
        if (data.status !== 'success') {
            // 两次快速编辑竞赛：第二次仍然进行了修订
            // 在第一架飞机着陆之前。重新同步并重试一次，静默，这样
            // 快速单击即可正常工作，而不会显示锁定错误。
            if (data.code === 'stale_roster' && !_retried) {
                return loadAgentCatalog().then(() => updateAgentWorkspace(agentId, updates, true));
            }
            throw new Error(data.code === 'stale_roster' ? t('agents_stale') : (data.message || 'Update failed'));
        }
        return loadAgentCatalog().then(() => true);
    }).catch(err => {
        const status = document.getElementById('agent-profile-status') || document.getElementById('agent-editor-status');
        if (status) status.textContent = err.message;
        return false;
    });
}

function deleteAgent(agentId) {
    const agent = findAgent(agentId);
    if (!agent) return;
    if (agentId === defaultAgentId) return; // 默认代理是实例
    showConfirmDialog({
        title: t('agents_delete_title'),
        message: t('agents_delete_confirm').replace('{name}', agent.name || agentId),
        okText: t('agents_delete'),
        cancelText: t('cancel'),
        onConfirm: () => _performAgentDelete(agentId),
    });
}

function _performAgentDelete(agentId, _retried) {
    return fetch('/api/agents', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'delete', id: agentId, revision: rosterRevision }),
    }).then(r => r.json()).then(data => {
        if (data.status !== 'success') {
            if (data.code === 'stale_roster' && !_retried) {
                return loadAgentCatalog().then(() => _performAgentDelete(agentId, true));
            }
            throw new Error(data.code === 'stale_roster' ? t('agents_stale') : (data.message || 'Delete failed'));
        }
        // 如果对现已删除的特工保留详细信息，则会显示出鬼魂。
        if (selectedAdminAgentId === agentId) closeAgentDetail();
        // 已删除代理拥有的对话将恢复为默认状态。
        if (activeAgentId === agentId) {
            activeAgentId = defaultAgentId;
            localStorage.setItem('cow_active_agent', activeAgentId);
        }
        // 删除已删除代理记住的会话 ID — 其对话
        // 与工作区一起使用，因此固定的 ID 只会重新固定幽灵。
        localStorage.removeItem(`${SESSION_ID_KEY}:${agentId}`);
        return loadAgentCatalog().then(() => {
            renderComposerIdentity();
            // 代理的会话已在服务器端删除；刷新打开
            // 列表，以便其行不会停留在下一次不相关的重新加载之前。
            if (typeof loadSessionList === 'function') loadSessionList();
            return true;
        });
    }).catch(err => {
        const status = document.getElementById('agent-profile-status');
        if (status) status.textContent = err.message;
        else alert(err.message);
        return false;
    });
}

// 代理可以通过四个核心文件进行编辑。 BOOTSTRAP.md 存在于
// 供内部使用的磁盘，但不适合手动编辑，因此它被排除在外
// 完全是选择器。每个选项都带有一个简短的提示（呈现在
// 下拉行的右侧），因此原始文件名并不是唯一的线索
// 它成立。
function _agentCoreFileOptions() {
    return [
        { value: 'AGENT.md', label: 'AGENT.md', hint: t('agents_core_file_agent') },
        { value: 'USER.md', label: 'USER.md', hint: t('agents_core_file_user') },
        { value: 'RULE.md', label: 'RULE.md', hint: t('agents_core_file_rule') },
        { value: 'MEMORY.md', label: 'MEMORY.md', hint: t('agents_core_file_memory') },
    ];
}

let agentCoreViewMode = 'edit';

function initAgentCoreFileDropdown() {
    const el = document.getElementById('agent-core-file');
    if (!el) return;
    const current = el._ddValue || 'AGENT.md';
    initDropdown(el, _agentCoreFileOptions(), current, () => loadAgentCoreFile());
}

function currentAgentCoreFile() {
    const el = document.getElementById('agent-core-file');
    return (el && el._ddValue) || 'AGENT.md';
}

function setAgentCoreViewMode(mode) {
    agentCoreViewMode = mode;
    document.querySelectorAll('#agent-core-mode .agent-seg-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.mode === mode);
    });
    const editor = document.getElementById('agent-core-editor');
    const preview = document.getElementById('agent-core-preview');
    if (!editor || !preview) return;
    if (mode === 'preview') {
        preview.innerHTML = renderMarkdown(editor.value || '');
        // 相同的后处理聊天消息得到：语法突出显示加上
        // 每个代码块上的语言标签 + 复制按钮（仅限 renderMarkdown
        // 产生原始的<pre>；之后标头将添加到实时 DOM 中）。
        if (typeof applyHighlighting === 'function') applyHighlighting(preview);
        editor.classList.add('hidden');
        preview.classList.remove('hidden');
    } else {
        preview.classList.add('hidden');
        editor.classList.remove('hidden');
    }
}

function loadAgentCoreFile() {
    if (!selectedAdminAgentId) return;
    initAgentCoreFileDropdown();
    const filename = currentAgentCoreFile();
    if (!filename) return;
    _paintCoreFileStatus('pending', '…');
    fetch(`/api/agents/${encodeURIComponent(selectedAdminAgentId)}/files/${encodeURIComponent(filename)}`)
        .then(r => r.json()).then(data => {
            if (data.status !== 'success') throw new Error(data.message || t('agents_save_failed'));
            selectedCoreRevision = data.revision;
            document.getElementById('agent-core-editor').value = data.content || '';
            document.getElementById('agent-editor-label').textContent = `${selectedAdminAgentId} / ${filename}`;
            // 修订版哈希对于人类读者来说没有任何意义；空白状态
            // （没有什么可报告的）比杂散的十六进制片段读起来更好。
            _paintCoreFileStatus('pending', '');
            // 如果这是活动视图，则刷新预览，因此
            // 在预览模式下切换文件不会显示过时的内容。
            if (agentCoreViewMode === 'preview') setAgentCoreViewMode('preview');
        }).catch(err => { _paintCoreFileStatus('error', err.message); });
}

// 用颜色+图标绘制保存状态，而不仅仅是纯文本，这样就成功了
// 乍一看，失败实际上是不同的。成功又回到了
// 过了一会儿就空白了；失败会一直保留到下一次尝试，因此不会错过。
//
// 此控制台中的所有其他 `*-status` 元素都通过共享隐藏
// `opacity-0`约定（请参阅navigateTo/setLanguage，它会淡化任何
// 导航上的 `[id$="-status"]` 元素）。这个有相同的id后缀
// 所以它会被同一个扫描捕获——它必须切换 `opacity-0` 本身
// 太早了，或者一次偶然的扫掠让它永远不可见
// 之后将绘制什么innerHTML。
function _paintCoreFileStatus(kind, text) {
    const status = document.getElementById('agent-editor-status');
    if (!status) return;
    clearTimeout(_paintCoreFileStatus._t);
    status.classList.remove('agent-status-ok', 'agent-status-error');
    if (kind === 'ok') {
        status.innerHTML = `<i class="fas fa-check mr-1"></i>${escapeHtml(text)}`;
        status.classList.add('agent-status-ok');
        status.classList.remove('opacity-0');
        _paintCoreFileStatus._t = setTimeout(() => {
            status.textContent = '';
            status.classList.remove('agent-status-ok');
            status.classList.add('opacity-0');
        }, 2200);
    } else if (kind === 'error') {
        status.innerHTML = `<i class="fas fa-triangle-exclamation mr-1"></i>${escapeHtml(text)}`;
        status.classList.add('agent-status-error');
        status.classList.remove('opacity-0');
    } else {
        status.textContent = text || '';
        if (text) status.classList.remove('opacity-0');
    }
}

function saveAgentCoreFile() {
    if (!selectedAdminAgentId) return;
    const filename = currentAgentCoreFile();
    const btn = document.querySelector('#agent-detail-files button[onclick="saveAgentCoreFile()"]');
    _paintCoreFileStatus('pending', '…');
    if (btn) btn.disabled = true;
    fetch(`/api/agents/${encodeURIComponent(selectedAdminAgentId)}/files/${encodeURIComponent(filename)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: document.getElementById('agent-core-editor').value, revision: selectedCoreRevision }),
    }).then(async r => ({ ok: r.ok, data: await r.json() })).then(({ ok, data }) => {
        if (!ok || data.status !== 'success') throw new Error(data.message || t('agents_save_failed'));
        selectedCoreRevision = data.revision;
        _paintCoreFileStatus('ok', t('agents_saved'));
    }).catch(err => {
        _paintCoreFileStatus('error', err.message);
    }).finally(() => {
        if (btn) btn.disabled = false;
    });
}

function startChatWithAgent(agentId) {
    if (!agentId) return;
    activeAgentId = agentId;
    localStorage.setItem('cow_active_agent', activeAgentId);
    newChat(true);
    navigateTo('chat');
    renderComposerIdentity();
}

function conversationHasMessages() {
    return !!document.querySelector('#chat-messages .user-message-group, #chat-messages .bot-message-group');
}

/** A roster of one behaves exactly like the console did before Agents existed:
 *  no face on the composer, no faces in the session list, no @ mentions. */
function multiAgentMode() {
    return enabledAgents().length > 1;
}

/** True once this conversation holds more than its owner. Until then it is an
 *  ordinary chat and is drawn like one. */
function sharedConversation() {
    return multiAgentMode() && currentTeamIds().length > 0;
}

// 谁正在回答每个飞行中的请求，如接受时所报告的那样。
// 在任何内容被持久化之前，让流式气泡带有正确的名称。
const _liveSpeakers = {};

function rememberLiveSpeaker(data) {
    if (data && data.request_id && data.speaker) {
        _liveSpeakers[data.request_id] = data.speaker;
    }
}

/** Repaint a still-visible loading indicator with the resolved speaker's face,
 *  once /message has said who took the turn. No-op if streaming already
 *  replaced the dots with a bubble. */
function setLoadingSpeaker(loadingEl, requestId) {
    if (!loadingEl || !loadingEl.isConnected) return;
    const face = loadingEl.querySelector('.bot-face');
    if (face) face.innerHTML = agentAvatarHTML(liveSpeakerAgent(requestId), 32);
}

/** The Agent to draw on a reply, or null to keep the product's own face. */
function botSpeakerAgent(msg, requestId) {
    if (!sharedConversation()) return null;
    const id = (msg && msg.extras && msg.extras.agent_id)
        || (requestId && _liveSpeakers[requestId])
        || activeAgentId;
    return findAgent(id) || null;
}

/** The Agent answering a live request, for the streaming bubble and the loading
 *  dots. Unlike botSpeakerAgent this also resolves in a solo chat, so a single
 *  Agent's own uploaded avatar shows while it streams instead of the logo. */
function liveSpeakerAgent(requestId) {
    const id = (requestId && _liveSpeakers[requestId]) || activeAgentId;
    return findAgent(id) || null;
}

/** Turn a written-out mention into a chip, so a name reads as a name instead
 *  of as an id someone pasted. Runs on the rendered bubble rather than on the
 *  markdown source, which keeps code spans untouched. */
function highlightMentions(root) {
    const roster = sessionRoster();
    if (!root || roster.length < 2) return;
    const byLabel = new Map();
    roster.forEach(agent => {
        [agent.name, agent.id].forEach(label => {
            if (label) byLabel.set(String(label).toLowerCase(), agent);
        });
    });
    const alternation = Array.from(byLabel.keys())
        .sort((a, b) => b.length - a.length)
        .map(label => label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
        .join('|');
    const re = new RegExp('@(' + alternation + ')(?=[\\s，,：:、]|$)', 'gi');

    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
        acceptNode: node => node.parentElement
            && node.parentElement.closest('code, pre, .mention-tag')
            ? NodeFilter.FILTER_REJECT
            : NodeFilter.FILTER_ACCEPT,
    });
    const targets = [];
    let node;
    while ((node = walker.nextNode())) {
        re.lastIndex = 0;
        if (re.test(node.nodeValue)) targets.push(node);
    }
    targets.forEach(text => {
        const value = text.nodeValue;
        const frag = document.createDocumentFragment();
        let cursor = 0;
        let match;
        re.lastIndex = 0;
        while ((match = re.exec(value))) {
            if (match.index > cursor) {
                frag.appendChild(document.createTextNode(value.slice(cursor, match.index)));
            }
            const agent = byLabel.get(match[1].toLowerCase());
            const tag = document.createElement('span');
            tag.className = 'mention-tag';
            if (agent) {
                // 一个看起来像它命名的队友的芯片：他们的脸，然后
                // 他们的名字。对于未知标签，返回纯文本。
                tag.innerHTML = `<span class="mention-tag-face">${agentAvatarHTML(agent, 16)}</span><span class="mention-tag-name">${escapeHtml(agent.name || agent.id)}</span>`;
            } else {
                tag.textContent = '@' + match[1];
            }
            frag.appendChild(tag);
            cursor = match.index + match[0].length;
        }
        if (cursor < value.length) {
            frag.appendChild(document.createTextNode(value.slice(cursor)));
        }
        text.parentNode.replaceChild(frag, text);
    });
}

function renderComposerIdentity() {
    const wrap = document.getElementById('composer-identity');
    const btn = document.getElementById('composer-agent-btn');
    if (!wrap || !btn) return;
    // 单代理安装使作曲家完全保持原样：否
    // 头像，没有菜单。身份芯片只有在超过以下数量时才会出现
    // 一个代理，因此是一个实际的选择。
    if (!multiAgentMode()) {
        wrap.classList.add('hidden');
        document.getElementById('composer-agent-menu')?.classList.add('hidden');
        return;
    }
    wrap.classList.remove('hidden');
    const agent = findAgent(activeAgentId) || { id: activeAgentId || defaultAgentId, name: activeAgentId || 'Agent' };
    const others = currentTeamIds().length;
    btn.innerHTML = agentAvatarHTML(agent, 22)
        + (others ? `<span class="composer-agent-count">${others + 1}</span>` : '');
    const face = btn.querySelector('.agent-avatar');
    if (face) face.id = 'composer-agent-avatar';
    // 所有者只能在第一回合之前交换，但加入是
    // 任何时候都允许，因此按钮本身永远不会消失。
    btn.classList.toggle('locked', conversationHasMessages());
    btn.dataset.tooltip = agent.name || agent.id;
}

function toggleComposerAgentMenu(event) {
    event.stopPropagation();
    const menu = document.getElementById('composer-agent-menu');
    if (!menu) return;
    if (!menu.classList.contains('hidden')) {
        menu.classList.add('hidden');
        return;
    }
    _closeComposerMenus(menu);
    renderComposerAgentMenu();
    menu.classList.remove('hidden');
}

/** Paint the agent menu's body from the current roster / team. Kept separate
 *  from the open/close toggle so an invite or removal can refresh the list in
 *  place — the menu stays open, the +/× flips, and the user can keep going. */
function renderComposerAgentMenu() {
    const menu = document.getElementById('composer-agent-menu');
    if (!menu) return;
    const taken = new Set(currentTeamIds());
    const members = (_sessCfg && _sessCfg.team && _sessCfg.team.members) || [];
    const sections = [];

    // 一旦对话有了队友，它就是一个群体，并且是唯一明智的
    // 操作是添加和删除成员 - “切换当前代理”将
    // 默默地离开群组，开始新的单独聊天。所以仅切换列表
    // 出现在普通（尚未共享）聊天中，它会打开一个干净的
    // 所选代理拥有的对话。
    if (!sharedConversation()) {
        sections.push(
            `<div class="composer-menu-title">${escapeHtml(t('agents_pick_tip'))}</div>`
            + enabledAgents().map(agent => `
                <button type="button" class="composer-menu-item agent-row${agent.id === activeAgentId ? ' current' : ''}"
                        onclick="pickComposerAgent('${escapeHtml(agent.id)}')">
                    ${agentAvatarHTML(agent, 24)}
                    <span>${escapeHtml(agent.name)}</span>
                    ${agent.id === activeAgentId ? '<i class="fas fa-check ml-auto text-[11px]"></i>' : ''}
                </button>`).join('')
        );
    }

    const candidates = enabledAgents().filter(a => a.id !== activeAgentId && !taken.has(a.id));

    // 群聊首先会列出已经在对话中的队友（
    // 所有者是隐式的并且未显示），那么，在下面的单独部分中，谁
    // 仍然可以拉入。将这两行分开可以明显看出这些行是
    // 要删除的成员，而不是要选择的选项。
    if (sharedConversation()) {
        const joined = members.filter(m => m.id !== activeAgentId).map(m => `
            <button type="button" class="composer-menu-item agent-row joined"
                    onclick="removeTeamMember('${escapeHtml(m.id)}')" title="${escapeHtml(t('team_remove'))}">
                ${agentAvatarHTML(m, 24)}
                <span>${escapeHtml(m.name || m.id)}</span>
                <i class="fas fa-check ml-auto text-[11px] joined-check"></i>
                <i class="fas fa-xmark ml-auto text-[11px] joined-remove"></i>
            </button>`).join('');
        if (joined) {
            sections.push(
                `<div class="composer-menu-title">${escapeHtml(t('team_members'))}</div>${joined}`
            );
        }
    }

    const invitable = candidates.map(agent => `
        <button type="button" class="composer-menu-item agent-row"
                onclick="inviteTeamMember('${escapeHtml(agent.id)}')">
            ${agentAvatarHTML(agent, 24)}
            <span>${escapeHtml(agent.name)}</span>
            <i class="fas fa-plus ml-auto text-[11px] text-slate-400"></i>
        </button>`).join('');
    if (invitable) {
        sections.push(
            `<div class="composer-menu-title">${escapeHtml(t('team_invite'))}</div>${invitable}`
        );
    }

    // 始终提供一种创建新代理的方法，以便单代理用户发现
    // 该团队的特色直接来自作曲家。
    sections.push(
        `<button type="button" class="composer-menu-item agent-row composer-menu-create"
                onclick="openAgentCreateFromComposer()">
            <span class="composer-menu-create-icon"><i class="fas fa-plus"></i></span>
            <span>${escapeHtml(t('agents_create'))}</span>
        </button>`
    );

    menu.innerHTML = sections.join('<div class="composer-menu-sep"></div>');
}

/** Jump from the composer straight into agent creation: close the menu, land on
 *  the team tab, and open the create form. */
function openAgentCreateFromComposer() {
    document.getElementById('composer-agent-menu')?.classList.add('hidden');
    navigateTo('agents');
    if (typeof openAgentCreateForm === 'function') openAgentCreateForm();
}

function pickComposerAgent(agentId) {
    document.getElementById('composer-agent-menu')?.classList.add('hidden');
    if (!agentId || agentId === activeAgentId) return;
    activeAgentId = agentId;
    localStorage.setItem('cow_active_agent', activeAgentId);
    // 切换开始由所选代理拥有的干净对话，而不是
    // 而不是重写当前的，因此它可以在聊天中的任何时刻发挥作用。
    newChat(true);
    if (typeof resetWorkspaceToAgentRoot === 'function') resetWorkspaceToAgentRoot();
    renderComposerIdentity();
}

function inviteTeamMember(agentId) {
    // 保持菜单打开，以便受邀代理明显从“+ 添加”移动到
    // “×移除”列表，用户可以连续邀请多个而无需
    // 每次都重新打开它。
    addTeamMember(agentId).then(refreshComposerAgentMenuIfOpen);
}

/** Everyone addressable in this conversation, owner first. */
function sessionRoster() {
    const owner = findAgent(activeAgentId);
    const members = (_sessCfg && _sessCfg.team && _sessCfg.team.members) || [];
    const roster = owner ? [owner] : [];
    members.forEach(m => {
        if (!roster.some(a => a.id === m.id)) roster.push(findAgent(m.id) || m);
    });
    return roster;
}

/** The teammate a message hands the turn to, or '' for nobody.
 *  Mirrors the server's rule: a leading mention only. */
function addressedAgentId(text) {
    const stripped = String(text || '').replace(/^\s+/, '');
    if (!stripped.startsWith('@')) return '';
    const labels = [];
    sessionRoster().forEach(agent => {
        [agent.name, agent.id].forEach(label => {
            if (label) labels.push([String(label), agent.id]);
        });
    });
    labels.sort((a, b) => b[0].length - a[0].length);
    for (const [label, id] of labels) {
        const re = new RegExp('^@' + label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(?=[\\s，,：:、]|$)', 'i');
        // 所有者也是可寻址的；服务器将“@owner”视为所有者
        // 只是轮流，所以这里没有特殊情况。
        if (re.test(stripped)) return id;
    }
    return '';
}

function mentionedAgentIds(text) {
    const id = addressedAgentId(text);
    return id ? [id] : [];
}

function currentTeamIds() {
    return ((_sessCfg && _sessCfg.team && _sessCfg.team.members) || []).map(m => m.id);
}

function setTeamMembers(ids) {
    const unique = Array.from(new Set(ids.filter(id => id && id !== activeAgentId)));
    return fetch(`/api/sessions/${encodeURIComponent(sessionId)}/settings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ members: unique.length ? unique : null }),
    }).then(r => r.json()).then(data => {
        if (data.status === 'success') {
            _sessCfg = { model: data.model, permission: data.permission, team: data.team };
            renderComposerIdentity();
            // 邀请或删除某人会改变一个模特是否可以发言
            // 对于这次谈话。
            _renderModelChip();
        }
    });
}

function addTeamMember(agentId) {
    if (!agentId || agentId === activeAgentId) return Promise.resolve();
    const ids = currentTeamIds();
    if (ids.includes(agentId)) return Promise.resolve();
    return setTeamMembers([...ids, agentId]);
}

function removeTeamMember(agentId) {
    return setTeamMembers(currentTeamIds().filter(id => id !== agentId))
        .then(refreshComposerAgentMenuIfOpen);
}

/** Repaint the agent menu if it is still open, so add/remove show immediately. */
function refreshComposerAgentMenuIfOpen() {
    const menu = document.getElementById('composer-agent-menu');
    if (menu && !menu.classList.contains('hidden')) renderComposerAgentMenu();
}

async function syncTeamFromText(text) {
    const extra = mentionedAgentIds(text);
    if (!extra.length) return;
    await setTeamMembers([...currentTeamIds(), ...extra]);
}

// 将通道实例指向代理。绑定实例本身的生命周期
// (channel_instances[].agent_id);空的agentId表示“遵循默认
// Agent”。instanceId 默认为单实例通道的通道类型。
function bindChannelAgent(channelType, agentId, instanceId, members) {
    const defaultId = defaultAgentId;
    const bound = (agentId && agentId !== defaultId) ? agentId : '';
    const iid = instanceId || channelType;
    const payload = {
        action: 'bind_channel_instance',
        channel_type: channelType,
        instance_id: iid,
        agent_id: bound,
    };
    // 仅当我们打算组建团队时才派遣成员；省略它留下
    // 存储的名册未受影响（仅限所有者重新绑定）。
    if (Array.isArray(members)) payload.members = members;
    return fetch('/api/agents', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    }).then(r => r.json()).then(data => {
        if (data.status !== 'success') throw new Error(data.message || 'Save failed');
        // 重新绑定是服务器上的热插拔（无需重新启动通道），并且
        // 下拉列表已经反映了本地的新值，因此只有名册
        // 目录需要刷新。在这里重新渲染频道视图将
        // 重建卡片并无缘无故重置扫描/手动选项卡状态。
        if (Array.isArray(channelInstancesView)) {
            const rec = channelInstancesView.find(i => i.instance_id === iid);
            if (rec) {
                rec.agent_id = bound;
                if (data.result && Array.isArray(data.result.members)) {
                    rec.members = data.result.members.slice();
                }
            }
        }
        return loadAgentCatalog();
    }).catch(err => _wsToast(err.message));
}

function channelBoundAgentId(channelType) {
    const inst = channelInstances.find(i =>
        (i.channel_type || '').toLowerCase() === channelType
    );
    return inst ? (inst.agent_id || '') : '';
}

let memoryAgentId = localStorage.getItem('cow_memory_agent') || '';

function viewingMemoryAgentId() {
    return memoryAgentId || activeAgentId || defaultAgentId;
}

function renderMemoryAgentSelect() {
    const el = document.getElementById('memory-agent-select');
    if (!el) return;
    const current = viewingMemoryAgentId();
    const list = agentCatalog.length ? agentCatalog : enabledAgents();
    const options = list.map(a => ({ value: a.id, label: a.name || a.id, agent: a }));
    initDropdown(el, options, current, (value) => selectMemoryAgent(value), { withAvatar: true });
}

function selectMemoryAgent(agentId) {
    memoryAgentId = agentId;
    localStorage.setItem('cow_memory_agent', agentId);
    closeMemoryViewer();
    loadMemoryView(1);
}

loadAgentCatalog();

// =====================================================================
// Markdown 渲染器
// =====================================================================
const FALLBACK_HLJS = {
    getLanguage() { return false; },
    highlight(str) { return { value: escapeHtml(str) }; },
    highlightAuto(str) { return { value: escapeHtml(str) }; },
    highlightElement() {},
};

function getHljs() {
    return window.hljs || FALLBACK_HLJS;
}

// CJK 表意文字、假名、韩文和全角/半角形式（仅限 BMP）。
const CJK_CHAR_RE = /[\u1100-\u11FF\u2E80-\u303F\u3040-\u33FF\u3400-\u4DBF\u4E00-\u9FFF\uA960-\uA97F\uAC00-\uD7FF\uF900-\uFAFF\uFE10-\uFE19\uFE30-\uFE6F\uFF00-\uFF60\uFFE0-\uFFE6]/;

// CommonMark 的侧翼规则对每个 Unicode 标点符号都一视同仁，因此
// `是**"引号"**——` never opens emphasis: the quote after `**` is punctuation
// while 是 before it is neither punctuation nor space, and the run degrades to
// 字面星号。应用中日韩友好修正案
// (github.com/tats-u/markdown-cjk-friend)：与 CJK 邻居一起运行 `*` 并
// 没有相邻的空白同时打开和关闭。 `_` 保留库存规则，
// 其词内行为取决于原始分类。
function patchCjkEmphasis(md) {
    const State = md.inline && md.inline.State;
    if (!State || !State.prototype.scanDelims || State.prototype._cjkEmphasisPatched) return;
    const utils = md.utils;
    const scanDelims = State.prototype.scanDelims;
    State.prototype.scanDelims = function(start, canSplitWord) {
        const res = scanDelims.call(this, start, canSplitWord);
        if (!canSplitWord) return res;
        const lastCode = start > 0 ? this.src.charCodeAt(start - 1) : 0x20;
        const nextPos = start + res.length;
        const nextCode = nextPos < this.posMax ? this.src.charCodeAt(nextPos) : 0x20;
        if (utils.isWhiteSpace(lastCode) || utils.isWhiteSpace(nextCode)) return res;
        if (!CJK_CHAR_RE.test(String.fromCharCode(lastCode)) &&
            !CJK_CHAR_RE.test(String.fromCharCode(nextCode))) return res;
        res.can_open = true;
        res.can_close = true;
        return res;
    };
    State.prototype._cjkEmphasisPatched = true;
}

function createMd() {
    const hljsLib = getHljs();
    const mdFactory = window.markdownit;
    if (typeof mdFactory !== 'function') {
        return {
            render(text) {
                return `<p>${escapeHtml(text || '')}</p>`;
            }
        };
    }
    const md = mdFactory({
        html: false, breaks: true, linkify: true, typographer: true,
        highlight: function(str, lang) {
            if (lang && hljsLib.getLanguage(lang)) {
                try { return hljsLib.highlight(str, { language: lang }).value; } catch (_) {}
            }
            return hljsLib.highlightAuto(str).value;
        }
    });
    patchCjkEmphasis(md);
    // 修复贪婪的 linkify: markdown - 它的 linkify 吞噬了 markdown 强调 (*)
    // 和粘贴到 URL 的 CJK 全角标点符号（常见于 LLM 输出，例如
    // "**https://x**，中文"), turning the whole tail into one broken link. Cut
    // 第一个此类字符处的 URL 并将其余部分作为文本溢出。
    var GREEDY_LINK_CUT = /[*\u3000-\u303F\uFF00-\uFFEF]/;
    md.core.ruler.after('linkify', 'fix_greedy_linkify', function(state) {
        for (var b = 0; b < state.tokens.length; b++) {
            var blk = state.tokens[b];
            if (blk.type !== 'inline' || !blk.children) continue;
            var ch = blk.children;
            for (var i = 0; i < ch.length; i++) {
                var open = ch[i];
                if (open.type !== 'link_open' || open.markup !== 'linkify') continue;
                var textTok = ch[i + 1], close = ch[i + 2];
                if (!textTok || textTok.type !== 'text' || !close || close.type !== 'link_close') continue;
                var idx = textTok.content.search(GREEDY_LINK_CUT);
                if (idx < 0) continue;
                var keep = textTok.content.slice(0, idx);
                var spill = textTok.content.slice(idx);
                textTok.content = keep;
                open.attrSet('href', keep);
                var spillTok = new state.Token('text', '', 0);
                spillTok.content = spill;
                ch.splice(i + 3, 0, spillTok);
            }
        }
    });
    const defaultLinkOpen = md.renderer.rules.link_open || function(tokens, idx, options, env, self) {
        return self.renderToken(tokens, idx, options);
    };
    md.renderer.rules.link_open = function(tokens, idx, options, env, self) {
        const token = tokens[idx];
        // 工作区相关的 href 将根据控制台 URL 进行解析，并且
        // 404 在新选项卡中。对其进行标记，以便单击处理程序
        // workspace.js 在预览面板中打开它。
        const wsPath = typeof wsWorkspaceHref === 'function'
            ? wsWorkspaceHref(token.attrGet('href') || '') : null;
        if (wsPath) {
            token.attrPush(['data-ws-path', wsPath]);
            token.attrJoin('class', 'ws-link');
        } else {
            token.attrPush(['target', '_blank']);
            token.attrPush(['rel', 'noopener noreferrer']);
        }
        return defaultLinkOpen(tokens, idx, options, env, self);
    };
    // 表格不能缩小到低于其列的最小内容宽度，因此宽
    // 比较表将超越泡沫。将其包裹在滚动条中：it
    // 当气泡适合时仍然会填充气泡，而当气泡不适合时会向侧面滚动。
    const defaultTableOpen = md.renderer.rules.table_open || function(tokens, idx, options, env, self) {
        return self.renderToken(tokens, idx, options);
    };
    const defaultTableClose = md.renderer.rules.table_close || function(tokens, idx, options, env, self) {
        return self.renderToken(tokens, idx, options);
    };
    md.renderer.rules.table_open = function(tokens, idx, options, env, self) {
        return '<div class="table-wrap">' + defaultTableOpen(tokens, idx, options, env, self);
    };
    md.renderer.rules.table_close = function(tokens, idx, options, env, self) {
        return defaultTableClose(tokens, idx, options, env, self) + '</div>';
    };
    return md;
}

const md = createMd();

const VIDEO_EXT_RE = /\.(?:mp4|webm|mov|avi|mkv)$/i;  // 针对没有查询字符串的 URL 进行测试
const IMAGE_EXT_RE = /\.(?:jpg|jpeg|png|gif|webp|bmp|svg)$/i;  // 针对没有查询字符串的 URL 进行测试

// Windows 绝对路径 (D:\x.png / D:/x.png)。
const WIN_ABS_PATH_RE = /^[A-Za-z]:[\\/]/;

function _toWebUrl(url) {
    if ((/^\/[A-Za-z]/.test(url) || WIN_ABS_PATH_RE.test(url)) && !url.startsWith('/api/')) {
        return '/api/file?path=' + encodeURIComponent(url);
    }
    if (/^file:\/\/\//i.test(url)) {
        // file:///home/x → /home/x，但 file:///D:/x 保持相对于驱动器的状态。
        const p = url.replace(/^file:\/\/\//i, '');
        return '/api/file?path=' + encodeURIComponent(WIN_ABS_PATH_RE.test(p) ? p : '/' + p);
    }
    return url;
}

function _buildVideoHtml(url) {
    const webUrl = _toWebUrl(url);
    const fileName = url.split('/').pop().split('?')[0];
    return `<div style="margin:10px 0;">` +
        `<video controls preload="metadata" ` +
        `style="max-width:100%;border-radius:10px;box-shadow:0 2px 8px rgba(0,0,0,0.15);display:block;">` +
        `<source src="${webUrl}"></video>` +
        `<a href="${webUrl}" target="_blank" ` +
        `style="display:inline-flex;align-items:center;gap:4px;margin-top:4px;font-size:12px;color:#8b8fa8;text-decoration:none;">` +
        `<i class="fas fa-download"></i> ${escapeHtml(fileName)}</a></div>`;
}

function _openImageLightbox(src) {
    let overlay = document.getElementById('cow-lightbox');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'cow-lightbox';
        overlay.style.cssText = 'position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,0.85);display:flex;align-items:center;justify-content:center;cursor:zoom-out;opacity:0;transition:opacity .2s';
        overlay.onclick = () => { overlay.style.opacity = '0'; setTimeout(() => overlay.style.display = 'none', 200); };
        const img = document.createElement('img');
        img.id = 'cow-lightbox-img';
        img.style.cssText = 'max-width:92vw;max-height:92vh;border-radius:8px;box-shadow:0 4px 24px rgba(0,0,0,0.5);object-fit:contain;';
        img.onclick = (e) => e.stopPropagation();
        overlay.appendChild(img);
        document.body.appendChild(overlay);
    }
    overlay.querySelector('#cow-lightbox-img').src = src;
    overlay.style.display = 'flex';
    requestAnimationFrame(() => overlay.style.opacity = '1');
}

function _buildImageHtml(url) {
    const webUrl = _toWebUrl(url);
    const safeUrl = webUrl.replace(/"/g, '&quot;');
    return `<div style="margin:10px 0;">` +
        `<img src="${safeUrl}" alt="image" loading="lazy" ` +
        `onclick="_openImageLightbox(this.src)" ` +
        `style="max-width:520px;width:100%;border-radius:10px;box-shadow:0 2px 8px rgba(0,0,0,0.15);display:block;cursor:zoom-in;">` +
        `</div>`;
}

function injectVideoPlayers(html) {
    // 步骤1：替换href指向视频文件的markdown-it锚标签。
    const step1 = html.replace(
        /<a\s+href="(https?:\/\/[^"]+)"[^>]*>[^<]*<\/a>/gi,
        (match, url) => VIDEO_EXT_RE.test(url.split('?')[0]) ? _buildVideoHtml(url) : match
    );
    // 步骤 2：替换文本节点中剩余的裸视频 URL（不在 HTML 标签内）。
    // 拆分 HTML 标记以避免触及标记中已有的 src/href 属性。
    return step1.split(/(<[^>]+>)/).map((chunk, idx) => {
        // 甚至索引也是文本节点；奇数索引是 HTML 标签——保持它们不变。
        if (idx % 2 !== 0) return chunk;
        return chunk.replace(/https?:\/\/\S+/gi, (url) => {
            const bare = url.replace(/[),.\s]+$/, '');  // 去掉尾随标点符号
            return VIDEO_EXT_RE.test(bare.split('?')[0]) ? _buildVideoHtml(bare) : url;
        });
    }).join('');
}

// 将图像 URL 转换为内联 <img> 预览。镜像注入VideoPlayers，但用于图像。
// 处理 markdown-it 产生的三种情况：
//   1. <a href="...image.jpg">...</a>（裸 URL 或链接化为锚点的自动链接）
//   2. <img src="..."> (markdown 图像语法) — 保持原样，但规范化样式
//   3. 原始 URL 仍然存在于文本节点中——仅作为安全网
function injectImagePreviews(html) {
    // 步骤1：href指向图像文件的锚点->替换为<img>预览。
    const step1 = html.replace(
        /<a\s+href="(https?:\/\/[^"]+)"[^>]*>[^<]*<\/a>/gi,
        (match, url) => IMAGE_EXT_RE.test(url.split('?')[0]) ? _buildImageHtml(url) : match
    );
    // 第 2 步：在文本节点中留下裸露的图像 URL（罕见 - markdown - 它的 linkify 通常会捕获它们）。
    return step1.split(/(<[^>]+>)/).map((chunk, idx) => {
        if (idx % 2 !== 0) return chunk;
        return chunk.replace(/https?:\/\/\S+/gi, (url) => {
            const bare = url.replace(/[),.\s]+$/, '');
            return IMAGE_EXT_RE.test(bare.split('?')[0]) ? _buildImageHtml(bare) : url;
        });
    }).join('');
}

function _rewriteLocalImgSrc(html) {
    return html.replace(/<img\s([^>]*?)src="([^"]+)"([^>]*?)>/gi, (match, pre, src, post) => {
        const webSrc = _toWebUrl(src);
        const safeSrc = webSrc.replace(/"/g, '&quot;');
        const hasClick = /onclick/i.test(pre + post);
        const clickAttr = hasClick ? '' : ` onclick="_openImageLightbox(this.src)" style="cursor:zoom-in;"`;
        return `<img ${pre}src="${safeSrc}"${post}${clickAttr}>`;
    });
}

function renderMarkdown(text) {
    try {
        let html = md.render(text);
        html = _rewriteLocalImgSrc(html);
        // 顺序很重要：首先是视频（更具体），然后是图像。
        html = injectImagePreviews(injectVideoPlayers(html));
        // 代理仅通过路径 (workspace.js) 提及的文件的后备。
        if (typeof injectFileChips === 'function') html = injectFileChips(html);
        // 注意：代码块头是在插入后通过 DOM 操作添加的
        // 请参阅 addCodeBlockHeadersToElement()
        return html;
    }
    catch (e) { return text.replace(/\n/g, '<br>'); }
}

function _addCodeBlockHeaders(container) {
    // 使用 DOM 操作向每个 <pre> 块添加带有语言标签的标题和复制按钮
    const preBlocks = container.querySelectorAll('pre');
    preBlocks.forEach(pre => {
        if (pre.parentElement && pre.parentElement.classList.contains('code-block-wrapper')) return;
        
        const codeEl = pre.querySelector('code');
        if (!codeEl) return;
        
        const langClass = Array.from(codeEl.classList).find(c => c.startsWith('language-'));
        const language = langClass ? langClass.replace('language-', '') : '';
        // 隐藏未知/空语言的标签（例如语言未定义）
        const showLang = language && language !== 'undefined' && language !== 'code';
        const langLabel = showLang ? language.charAt(0).toUpperCase() + language.slice(1) : '';
        
        const wrapper = document.createElement('div');
        wrapper.className = 'code-block-wrapper';
        
        const header = document.createElement('div');
        header.className = 'code-block-header';
        header.innerHTML = `
            <span class="code-block-lang">${langLabel}</span>
            <button class="code-copy-btn" title="Copy code">
                <i class="fas fa-copy"></i>
            </button>
        `;
        
        pre.parentNode.insertBefore(wrapper, pre);
        wrapper.appendChild(header);
        wrapper.appendChild(pre);
    });
}

// =====================================================================
// 聊天模块
// =====================================================================
let isPolling = false;
let pollGeneration = 0;   // 每次重新启动时递增以取消陈旧的轮询循环
let loadingContainers = {};
let activeStreams = {};   // request_id -> 事件源
let sessionActiveRequest = {};   // agent_id + session_id -> request_id
const PENDING_VOICE_ATTACH_TTL_MS = 2 * 60 * 1000;
const PENDING_VOICE_ATTACH_MAX = 100;
const pendingVoiceAttachments = new Map(); // session_id:bot_seq -> 待处理的音频

function runtimeSessionKey(sid, agentId = activeAgentId) {
    return `${agentId || defaultAgentId || 'default'}::${sid}`;
}

function isCurrentSessionConversationActive() {
    return !!sessionActiveRequest[runtimeSessionKey(sessionId)];
}

function updateEditButtonsState() {
    const active = isCurrentSessionConversationActive();
    document.querySelectorAll('.edit-msg-btn, .delete-msg-btn').forEach(btn => {
        btn.disabled = active;
        if (btn.classList.contains('edit-msg-btn')) {
            btn.title = active
                ? t('edit_disabled_reply_active')
                : t('edit_message');
        } else {
            btn.title = active
                ? t('delete_disabled_reply_active')
                : t('delete_message_title');
        }
    });
}
let streamBuffers = {};   // request_id -> { items: [event...], timestamp } 用于重新附加重播
let isComposing = false;
let appConfig = { use_agent: false, title: 'CowAgent', subtitle: '', providers: {}, api_bases: {} };

let activeAgentId = localStorage.getItem('cow_active_agent') || '';
const SESSION_ID_KEY = 'cow_session_id';

function activeSessionStorageKey() {
    return activeAgentId && activeAgentId !== defaultAgentId && activeAgentId !== 'default'
        ? `${SESSION_ID_KEY}:${activeAgentId}`
        : SESSION_ID_KEY;
}

// 通过现有控制台请求携带所选代理而不强制
// 每个功能面板都实现自己的路由粘合。
const _nativeFetch = window.fetch.bind(window);
window.fetch = function(input, init) {
    init = init ? { ...init } : {};
    let url = typeof input === 'string' ? input : input.url;
    if (activeAgentId && typeof url === 'string' && url.startsWith('/')) {
        if (!/[?&]agent_id=/.test(url)) {
            const joiner = url.includes('?') ? '&' : '?';
            url = `${url}${joiner}agent_id=${encodeURIComponent(activeAgentId)}`;
        }
        if (typeof input !== 'string') input = new Request(url, input);
        else input = url;

        // JSON 主体从有效负载中读取 agent_id，因此也将其注入那里。
        // 分段（FormData）上传不得获取正文副本：查询
        // 上面的字符串已经携带它，并且web.py合并了query + body，
        // 将重复项折叠到列表中 (agent_id=['x','x'])。那个清单
        // 然后到达期望纯字符串的处理程序并引发
        // “unhashable type: 'list'”，默默地杀死每个文件上传。
        if (typeof init.body === 'string') {
            const contentType = new Headers(init.headers || {}).get('Content-Type') || '';
            if (contentType.includes('application/json')) {
                try {
                    const body = JSON.parse(init.body);
                    if (body && typeof body === 'object' && !Array.isArray(body) && !body.agent_id) {
                        body.agent_id = activeAgentId;
                        init.body = JSON.stringify(body);
                    }
                } catch (_) {}
            }
        }
    }
    return _nativeFetch(input, init);
};

function generateSessionId() {
    return 'session_' + ([1e7]+-1e3+-4e3+-8e3+-1e11).replace(/[018]/g, c =>
        (c ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> c / 4).toString(16)
    );
}

// 从 localStorage 恢复 session_id，以便对话历史记录在页面刷新后仍然存在。
// 仅当用户明确开始新聊天时才会生成新的 ID。
function loadOrCreateSessionId() {
    const stored = localStorage.getItem(activeSessionStorageKey());
    if (stored) return stored;
    const fresh = generateSessionId();
    localStorage.setItem(activeSessionStorageKey(), fresh);
    return fresh;
}

let sessionId = loadOrCreateSessionId();

// ---- 对话历史状态 ----
let historyPage = 0;       // 已获取最后一页（0 = 尚未获取任何内容）
let historyHasMore = false;
let historyLoading = false;

fetch('/config').then(r => r.json()).then(data => {
    if (data.status === 'success') {
        appConfig = data;
        const title = data.title || 'CowAgent';
        document.getElementById('welcome-title').textContent = title;
        initConfigView(data);
    }
    loadHistory(1);
}).catch(() => { loadHistory(1); });

// 立即开始轮询，以便随时接收调度程序/推送消息
startPolling();

const chatInput = document.getElementById('chat-input');
const sendBtn = document.getElementById('send-btn');
const steerBtn = document.getElementById('steer-btn');
const messagesDiv = document.getElementById('chat-messages');
const fileInput = document.getElementById('file-input');
const folderInput = document.getElementById('folder-input');
const attachBtn = document.getElementById('attach-btn');
const attachMenu = document.getElementById('attach-menu');
const attachFolderOption = document.getElementById('attach-folder-option');
const supportsDirectoryUpload = !!folderInput && 'webkitdirectory' in folderInput;

if (!supportsDirectoryUpload && attachFolderOption) {
    attachFolderOption.classList.add('hidden');
}

// Composer 文本区域大小调整。空盒子故意放高（几行
// 房间，像其他编码代理一样）并随着文本增长到上限，之后
// 它滚动。
const COMPOSER_MIN_H = 52;
const COMPOSER_MAX_H = 220;

function autoResizeComposer() {
    chatInput.style.height = COMPOSER_MIN_H + 'px';
    const scrollH = chatInput.scrollHeight;
    chatInput.style.height = Math.max(COMPOSER_MIN_H, Math.min(scrollH, COMPOSER_MAX_H)) + 'px';
    chatInput.style.overflowY = scrollH > COMPOSER_MAX_H ? 'auto' : 'hidden';
}

/** Shrink the composer back to its resting height after the text is consumed. */
function resetComposerHeight() {
    chatInput.style.height = COMPOSER_MIN_H + 'px';
    chatInput.style.overflowY = 'hidden';
}

// ---------------- 麦克风按钮：通过配置的 ASR 提供程序进行页内语音输入 ----------------
(function setupMicButton() {
    const micBtn = document.getElementById('mic-btn');
    if (!micBtn) return;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia ||
        typeof window.MediaRecorder === 'undefined') {
        micBtn.style.display = 'none';
        return;
    }

    let mediaRecorder = null;
    let stream = null;
    let chunks = [];
    let recording = false;

    // 使用自定义 CSS 工具提示 (data-tooltip) 而不是原生标题：
    // 原生标题有约 1.5 秒的悬停延迟，并且不支持 i18n。
    const setTip = (text) => {
        micBtn.setAttribute('data-tooltip', text);
        micBtn.removeAttribute('title');
    };

    const setIdle = () => {
        recording = false;
        micBtn.classList.remove('text-red-500', 'animate-pulse');
        micBtn.classList.add('text-slate-400');
        micBtn.querySelector('i').className = 'fas fa-microphone text-sm';
        setTip(t('mic_idle_title'));
    };
    const setRecording = () => {
        recording = true;
        micBtn.classList.remove('text-slate-400');
        micBtn.classList.add('text-red-500', 'animate-pulse');
        micBtn.querySelector('i').className = 'fas fa-stop text-sm';
        setTip(t('mic_recording_title'));
    };
    const setBusy = () => {
        micBtn.classList.remove('text-red-500', 'animate-pulse', 'text-slate-400');
        micBtn.classList.add('text-primary-500');
        micBtn.querySelector('i').className = 'fas fa-spinner fa-spin text-sm';
        setTip(t('mic_busy_title'));
    };

    const pickMimeType = () => {
        const candidates = [
            'audio/webm;codecs=opus',
            'audio/webm',
            'audio/ogg;codecs=opus',
            'audio/mp4',
        ];
        for (const m of candidates) {
            if (window.MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(m)) {
                return m;
            }
        }
        return '';
    };

    const stopStream = () => {
        if (stream) {
            stream.getTracks().forEach(t => t.stop());
            stream = null;
        }
    };

    let _micTipTimer = null;
    const flashError = (msg) => {
        console.warn('[mic]', msg);
        // 在麦克风上方弹出一个小气泡，以便用户真正注意到它。
        // 麦克风位于围绕麦克风的相对定位的包装内
        // textarea（参见 chat.html），所以我们将提示挂在包装上。
        const wrapper = micBtn.parentElement;
        if (!wrapper) return;
        let tip = wrapper.querySelector('.mic-tip');
        if (!tip) {
            tip = document.createElement('div');
            tip.className = 'mic-tip absolute right-1 bottom-full mb-2 px-2 py-1 rounded-md '
                + 'text-xs text-white bg-slate-800/90 dark:bg-slate-700/90 shadow-md '
                + 'pointer-events-none whitespace-nowrap z-10';
            wrapper.appendChild(tip);
        }
        tip.textContent = msg;
        tip.style.opacity = '1';
        if (_micTipTimer) clearTimeout(_micTipTimer);
        _micTipTimer = setTimeout(() => {
            tip.style.opacity = '0';
            tip.style.transition = 'opacity 200ms';
            setTimeout(() => tip.remove(), 250);
        }, 2000);
    };

    const upload = async (blob, ext) => {
        setBusy();
        const fd = new FormData();
        fd.append('file', blob, `recording.${ext}`);
        try {
            const resp = await fetch('/api/voice/asr', { method: 'POST', body: fd });
            const data = await resp.json();
            if (data.status === 'success' && data.text) {
                // 语音消息用户体验：将录音放入对话中
                // 作为一个可播放的气泡，下面有标题，然后
                // 通过常规发送路径发送已识别的文本。
                sendVoiceMessage(data.text, data.audio_url);
            } else {
                flashError(data.message || t('mic_error'));
            }
        } catch (e) {
            flashError(t('mic_error') + ': ' + e.message);
        } finally {
            setIdle();
        }
    };

    const start = async () => {
        try {
            stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        } catch (e) {
            flashError(t('mic_permission_denied'));
            return;
        }
        chunks = [];
        const mimeType = pickMimeType();
        try {
            mediaRecorder = mimeType
                ? new MediaRecorder(stream, { mimeType })
                : new MediaRecorder(stream);
        } catch (e) {
            stopStream();
            flashError(t('mic_error') + ': ' + e.message);
            return;
        }
        mediaRecorder.ondataavailable = (ev) => {
            if (ev.data && ev.data.size > 0) chunks.push(ev.data);
        };
        mediaRecorder.onstop = () => {
            stopStream();
            const blob = new Blob(chunks, { type: mediaRecorder.mimeType || 'audio/webm' });
            // 映射 mime -> 扩展名，以便服务器选择正确的文件后缀。
            const mt = (mediaRecorder.mimeType || 'audio/webm').split(';')[0];
            const extMap = {
                'audio/webm': 'webm', 'audio/ogg': 'ogg',
                'audio/mp4': 'm4a',   'audio/mpeg': 'mp3',
            };
            const ext = extMap[mt] || 'webm';
            // 256 字节 ~ 仅容器标头，没有实际音频。任何东西
            // 下面我们将其视为“错误点击”。
            if (blob.size < 256) {
                setIdle();
                flashError(t('mic_too_short'));
                return;
            }
            upload(blob, ext);
        };
        // timeslice=250ms：强制记录器每 250ms 刷新一个块。
        // 如果没有它，一些浏览器会在生成任何数据之前等待 stop()，
        // 非常短的点击就会丢失音频。
        mediaRecorder.start(250);
        recordStartedAt = Date.now();
        setRecording();
    };

    let recordStartedAt = 0;

    const stopWithMinDuration = () => {
        const elapsed = Date.now() - recordStartedAt;
        const minMs = 350;
        if (elapsed < minMs) {
            // 给录音机一点时间来捕获至少一个块
            // 在我们告诉它停止之前。
            setTimeout(() => stop(), minMs - elapsed);
        } else {
            stop();
        }
    };

    const stop = () => {
        if (mediaRecorder && mediaRecorder.state !== 'inactive') {
            mediaRecorder.stop();
        }
    };

    micBtn.addEventListener('click', () => {
        if (recording) {
            stopWithMinDuration();
        } else {
            start();
        }
    });

    setIdle();
})();

// ----------------优化按钮：通过AI提示优化----------------
(function setupOptimizeButton() {
    const optBtn = document.getElementById('optimize-btn');
    if (!optBtn) return;

    let busy = false;

    // 使用自定义 CSS 工具提示 (data-tooltip) 而不是原生标题：
    // 原生标题有约 1.5 秒的悬停延迟，并且不支持 i18n。
    const setTip = (text) => {
        optBtn.setAttribute('data-tooltip', text);
        optBtn.removeAttribute('title');
    };

    const setIdle = () => {
        busy = false;
        optBtn.classList.remove('text-primary-500', 'animate-spin');
        optBtn.classList.add('text-slate-400');
        optBtn.querySelector('i').className = 'fas fa-magic text-[13px]';
        setTip(t('optimize_idle_title'));
        optBtn.style.pointerEvents = '';
    };
    const setBusy = () => {
        busy = true;
        optBtn.classList.remove('text-slate-400');
        optBtn.classList.add('text-primary-500');
        optBtn.querySelector('i').className = 'fas fa-spinner fa-spin text-[13px]';
        setTip(t('optimize_busy_title'));
        optBtn.style.pointerEvents = 'none';
    };

    // 来自麦克风设置的共享 flashError — 通过注入相同的包装器来重用其样式
    const flashError = (msg) => {
        console.warn('[optimize]', msg);
        const wrapper = optBtn.parentElement;
        if (!wrapper) return;
        let tip = wrapper.querySelector('.opt-tip');
        if (!tip) {
            tip = document.createElement('div');
            tip.className = 'opt-tip absolute right-9 bottom-full mb-2 px-2 py-1 rounded-md '
                + 'text-xs text-white bg-slate-800/90 dark:bg-slate-700/90 shadow-md '
                + 'pointer-events-none whitespace-nowrap z-10';
            wrapper.appendChild(tip);
        }
        tip.textContent = msg;
        tip.style.opacity = '1';
        tip.style.transition = '';
        clearTimeout(tip._timer);
        tip._timer = setTimeout(() => {
            tip.style.transition = 'opacity 200ms';
            tip.style.opacity = '0';
        }, 2500);
    };

    optBtn.addEventListener('click', async () => {
        if (busy) return;
        const raw = chatInput.value.trim();
        if (!raw) {
            flashError(t('optimize_empty'));
            return;
        }
        setBusy();
        try {
            // 收集可选上下文：聊天中可见的最后几个消息组。
            // 用户和机器人消息按其组类别进行区分。
            const contextMessages = [];
            const groups = messagesDiv.querySelectorAll('.user-message-group, .bot-message-group');
            const recentGroups = Array.from(groups).slice(-6);
            for (const g of recentGroups) {
                const role = g.classList.contains('user-message-group') ? 'user' : 'assistant';
                // 仅读取主要消息内容，而不读取操作按钮或时间戳。
                const contentEl = g.querySelector('.msg-content');
                const text = ((contentEl || g).textContent || '').trim().slice(0, 200);
                if (text) {
                    contextMessages.push({ role: role, content: text });
                }
            }

            const resp = await fetch('/api/prompt/optimize', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ input: raw, context_messages: contextMessages }),
            });
            const data = await resp.json();
            if (data.status === 'success' && data.optimized) {
                chatInput.value = data.optimized;
                chatInput.dispatchEvent(new Event('input', { bubbles: true }));
                chatInput.focus();
                // 将光标置于末尾
                chatInput.setSelectionRange(chatInput.value.length, chatInput.value.length);
            } else {
                flashError(data.message || t('optimize_error'));
            }
        } catch (e) {
            flashError(t('optimize_error') + ': ' + e.message);
        } finally {
            setIdle();
        }
    });

    setIdle();
})();


// 智能自动滚动：用户向上滚动时暂停，接近底部时恢复
let _autoScrollEnabled = true;
const _SCROLL_THRESHOLD = 80; // px 从底部重新启用自动滚动

messagesDiv.addEventListener('scroll', () => {
    const distFromBottom = messagesDiv.scrollHeight - messagesDiv.scrollTop - messagesDiv.clientHeight;
    _autoScrollEnabled = distFromBottom <= _SCROLL_THRESHOLD;
    _updateScrollToBottomBtn();
});

// 拦截聊天消息中的内部导航链接
messagesDiv.addEventListener('click', (e) => {
    // 代码块复制按钮
    const codeCopyBtn = e.target.closest('.code-copy-btn');
    if (codeCopyBtn) {
        e.preventDefault();
        const wrapper = codeCopyBtn.closest('.code-block-wrapper');
        const codeEl = wrapper && wrapper.querySelector('pre code');
        if (codeEl) {
            const codeText = codeEl.textContent;
            copyToClipboard(codeText).then(() => {
                const icon = codeCopyBtn.querySelector('i');
                if (icon) { icon.className = 'fas fa-check'; setTimeout(() => { icon.className = 'fas fa-copy'; }, 1500); }
            });
        }
        return;
    }

    const copyBtn = e.target.closest('.copy-msg-btn');
    if (copyBtn) {
        e.preventDefault();
        const msgRoot = copyBtn.closest('.flex.gap-3');
        const answerEl = msgRoot && msgRoot.querySelector('.answer-content');
        const rawMd = answerEl && answerEl.dataset.rawMd;
        if (rawMd) {
            copyToClipboard(rawMd).then(() => {
                const icon = copyBtn.querySelector('i');
                if (icon) { icon.className = 'fas fa-check'; setTimeout(() => { icon.className = 'fas fa-copy'; }, 1500); }
            });
        }
        return;
    }

    // 编辑用户消息
    const editBtn = e.target.closest('.edit-msg-btn');
    if (editBtn) {
        e.preventDefault();
        if (isCurrentSessionConversationActive()) return;
        const msgRoot = editBtn.closest('.user-message-group');
        if (msgRoot) editUserMessage(msgRoot);
        return;
    }

    // 重新生成机器人响应
    const regenerateBtn = e.target.closest('.regenerate-msg-btn');
    if (regenerateBtn) {
        e.preventDefault();
        const botMsgRoot = regenerateBtn.closest('.flex.gap-3');
        if (botMsgRoot) regenerateResponse(botMsgRoot);
        return;
    }

    // 删除消息（仅限用户气泡；机器人气泡故意缺少
    // 删除按钮 - 仅删除机器人回复会留下孤儿
    // 中断 LLM 上下文交替的用户消息）。
    const deleteBtn = e.target.closest('.delete-msg-btn');
    if (deleteBtn) {
        e.preventDefault();
        if (isCurrentSessionConversationActive()) return;
        const userMsgEl = deleteBtn.closest('.user-message-group');
        if (!userMsgEl) return;

        showConfirmModal(t('delete_message_title'), t('delete_message_confirm'), () => {
            // 查找本回合的下一个机器人回复（跳过非消息节点）。
            let botReplyEl = null;
            let sibling = userMsgEl.nextElementSibling;
            while (sibling) {
                if (sibling.classList && sibling.classList.contains('bot-message-group')) {
                    botReplyEl = sibling;
                    break;
                }
                sibling = sibling.nextElementSibling;
            }
            userMsgEl.remove();
            if (botReplyEl) botReplyEl.remove();

            const userSeq = userMsgEl.dataset.seq;
            if (userSeq) {
                fetch('/api/messages/delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ session_id: sessionId, user_seq: parseInt(userSeq) })
                }).then(r => r.json()).then(data => {
                    if (data.status === 'success') console.log(`Deleted ${data.deleted} messages`);
                }).catch(err => console.error('Failed to delete:', err));
            }
        });
        return;
    }

    const a = e.target.closest('a');
    if (!a) return;
    const href = a.getAttribute('href') || '';
    if (href === '/memory/dreams') {
        e.preventDefault();
        navigateTo('memory');
        setTimeout(() => switchMemoryTab('dreams'), 50);
    } else if (href === '/memory/MEMORY.md') {
        e.preventDefault();
        navigateTo('memory');
        setTimeout(() => { switchMemoryTab('files'); openMemoryFile('MEMORY.md', 'memory'); }, 50);
    }
});
const attachmentPreview = document.getElementById('attachment-preview');

// 待处理附件：[{file_path、file_name、file_type、preview_url}]
// _uploading=true 的项目仍在飞行中。
let pendingAttachments = [];
let uploadingCount = 0;

// 输入历史记录（如终端箭头键调用）
const inputHistory = [];
let historyIdx = -1;
let historySavedDraft = '';

// 当 SSE 流正在传输时，发送按钮会变成取消按钮
// 按钮。一次仅支持一个飞行中请求。
let activeRequestId = null;
let sendBtnMode = 'send'; // '发送' | ‘取消’

function setSendBtnCancelMode(requestId) {
    activeRequestId = requestId;
    sendBtnMode = 'cancel';
    sendBtn.disabled = false;
    sendBtn.classList.add('send-btn-cancel');
    _setBtnTooltip(sendBtn, t('tip_cancel'));
    sendBtn.innerHTML = '<i class="fas fa-stop text-sm"></i>';
    updateSteerBtnState();
}

function resetSendBtnSendMode() {
    activeRequestId = null;
    sendBtnMode = 'send';
    sendBtn.classList.remove('send-btn-cancel');
    _setBtnTooltip(sendBtn, '');
    sendBtn.innerHTML = '<i class="fas fa-paper-plane text-sm"></i>';
    steerBtn.classList.add('hidden');
    steerBtn.classList.remove('flex');
    steerBtn.disabled = true;
    updateSendBtnState();
}

function updateSteerBtnState() {
    // 任务运行时保持转向按钮处于启用状态，以便用户可以
    // 火力连续引导。空输入在 steerActiveTask 中受到保护，
    // 避免每次转向后出现刺耳的禁用/不允许状态。
    const active = sendBtnMode === 'cancel' && !!activeRequestId;
    steerBtn.classList.toggle('hidden', !active);
    steerBtn.classList.toggle('flex', active);
    steerBtn.disabled = !active || uploadingCount > 0;
}

function steerActiveTask() {
    const instruction = chatInput.value.trim();
    if (!instruction || sendBtnMode !== 'cancel' || !activeRequestId) return;

    inputHistory.push(instruction);
    historyIdx = -1;
    historySavedDraft = '';
    addUserMessage(`↪ ${instruction}`, new Date());

    chatInput.value = '';
    resetComposerHeight();
    updateSteerBtnState();

    fetch('/message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            session_id: sessionId,
            message: instruction,
            steer: true,
            stream: false,
            lang: currentLang,
        }),
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'success' && data.inline_reply) {
            addBotMessage(data.inline_reply, new Date());
        } else {
            addBotMessage(t('error_send'), new Date());
        }
    })
    .catch(err => {
        console.warn('[steer] request failed', err);
        addBotMessage(t('error_send'), new Date());
    })
    .finally(updateSteerBtnState);
}

steerBtn.addEventListener('click', steerActiveTask);

function requestCancel() {
    const reqId = activeRequestId;
    if (!reqId) return;
    fetch('/cancel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ request_id: reqId, session_id: sessionId, lang: currentLang }),
    }).catch(err => {
        console.warn('[cancel] request failed', err);
    });
    // 乐观 UI 锁定，因此点击在 SSE 之前明显注册
    // “取消”事件到来。
    sendBtn.disabled = true;
    _setBtnTooltip(sendBtn, t('tip_cancelled'));
}

// 单击按钮是取消的唯一途径。按 Enter 键仍会调用
// sendMessage() 以便用户可以将“/cancel”作为常规斜杠命令提交。
sendBtn.addEventListener('click', () => {
    if (sendBtnMode === 'cancel') {
        requestCancel();
    } else {
        sendMessage();
    }
});

function updateSendBtnState() {
    if (sendBtnMode === 'cancel') {
        // 自我修复卡住的取消按钮：如果没有实时流支持
        // 当前请求，取消状态泄漏（例如流结束
        // 无需重置）。恢复到发送，这样输入就不会被阻止。
        if (!activeRequestId || !activeStreams[activeRequestId]) {
            resetSendBtnSendMode();
        } else {
            // 不要降级输入编辑时真正有效的“取消”按钮。
            updateSteerBtnState();
            return;
        }
    }
    sendBtn.disabled = uploadingCount > 0 || (!chatInput.value.trim() && pendingAttachments.length === 0);
    updateSteerBtnState();
}

function renderAttachmentPreview() {
    if (pendingAttachments.length === 0) {
        attachmentPreview.classList.add('hidden');
        attachmentPreview.innerHTML = '';
        updateSendBtnState();
        return;
    }
    attachmentPreview.classList.remove('hidden');
    attachmentPreview.innerHTML = pendingAttachments.map((att, idx) => {
        if (att._uploading) {
            const suffix = att.file_type === 'directory' && att.file_count
                ? ` (${att.file_count})`
                : '';
            return `<div class="att-chip att-uploading" data-idx="${idx}">
                <i class="fas fa-spinner fa-spin"></i>
                <span class="att-name">${escapeHtml(att.file_name)}${suffix}</span>
            </div>`;
        }
        if (att.file_type === 'image') {
            return `<div class="att-thumb" data-idx="${idx}">
                <img src="${att.preview_url}" alt="${escapeHtml(att.file_name)}">
                <button class="att-remove" onclick="removeAttachment(${idx})">&times;</button>
            </div>`;
        }
        const icon = att.file_type === 'video'
            ? 'fa-film'
            : (att.file_type === 'directory' ? 'fa-folder-tree'
            : (att.is_dir ? 'fa-folder' : 'fa-file-alt'));
        const suffix = att.file_type === 'directory' && att.file_count
            ? ` (${att.file_count})`
            : '';
        return `<div class="att-chip" data-idx="${idx}">
            <i class="fas ${icon}"></i>
            <span class="att-name">${escapeHtml(att.file_name)}${suffix}</span>
            <button class="att-remove" onclick="removeAttachment(${idx})">&times;</button>
        </div>`;
    }).join('');
    updateSendBtnState();
}

function removeAttachment(idx) {
    if (pendingAttachments[idx]?._uploading) return;
    pendingAttachments.splice(idx, 1);
    renderAttachmentPreview();
}

function isAttachMenuVisible() {
    return attachMenu && !attachMenu.classList.contains('hidden');
}

function hideAttachMenu() {
    if (attachMenu) attachMenu.classList.add('hidden');
}

function toggleAttachMenu(event) {
    if (!attachMenu) return;
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }
    attachMenu.classList.toggle('hidden');
}

function triggerFileUpload() {
    hideAttachMenu();
    fileInput?.click();
}

function triggerFolderUpload() {
    if (!supportsDirectoryUpload) return;
    hideAttachMenu();
    folderInput?.click();
}

async function handleFileSelect(files) {
    if (!files || files.length === 0) return;
    const tasks = [];
    for (const file of files) {
        const placeholder = { file_name: file.name, file_type: 'file', _uploading: true };
        pendingAttachments.push(placeholder);
        uploadingCount++;
        renderAttachmentPreview();

        tasks.push((async () => {
            const formData = new FormData();
            formData.append('file', file);
            formData.append('session_id', sessionId);
            try {
                const resp = await fetch('/upload', { method: 'POST', body: formData });
                const data = await resp.json();
                if (data.status === 'success') {
                    placeholder.file_path = data.file_path;
                    placeholder.file_name = data.file_name;
                    placeholder.file_type = data.file_type;
                    placeholder.preview_url = data.preview_url;
                    delete placeholder._uploading;
                } else {
                    const i = pendingAttachments.indexOf(placeholder);
                    if (i !== -1) pendingAttachments.splice(i, 1);
                }
            } catch (e) {
                console.error('Upload failed:', e);
                const i = pendingAttachments.indexOf(placeholder);
                if (i !== -1) pendingAttachments.splice(i, 1);
            }
            uploadingCount--;
            renderAttachmentPreview();
        })());
    }
    await Promise.all(tasks);
}

function _makeUploadId() {
    return `dir_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

function _groupDirectoryFiles(files) {
    const groups = new Map();
    for (const file of Array.from(files || [])) {
        const relPath = file.webkitRelativePath || file.name;
        const parts = relPath.split('/').filter(Boolean);
        const rootName = parts[0] || file.name;
        if (!groups.has(rootName)) groups.set(rootName, []);
        groups.get(rootName).push({ file, relPath });
    }
    return groups;
}

async function handleFolderSelect(files) {
    if (!files || files.length === 0) return;
    const groups = _groupDirectoryFiles(files);
    const groupTasks = [];

    for (const [rootName, entries] of groups.entries()) {
        const placeholder = {
            file_name: rootName,
            file_type: 'directory',
            file_count: entries.length,
            _uploading: true,
        };
        pendingAttachments.push(placeholder);
        uploadingCount++;
        renderAttachmentPreview();

        const uploadId = _makeUploadId();
        groupTasks.push((async () => {
            try {
                const formData = new FormData();
                formData.append('session_id', sessionId);
                formData.append('upload_id', uploadId);
                for (const { file, relPath } of entries) {
                    formData.append('files', file);
                    formData.append('relative_paths', relPath);
                }

                const resp = await fetch('/upload', { method: 'POST', body: formData });
                const data = await resp.json();
                if (data.status !== 'success') {
                    throw new Error(data.message || 'Upload failed');
                }
                if (!data.root_path) {
                    throw new Error('Directory root path missing');
                }
                placeholder.file_path = data.root_path;
                placeholder.file_name = data.root_name || rootName;
                delete placeholder._uploading;
            } catch (e) {
                console.error('Directory upload failed:', e);
                const i = pendingAttachments.indexOf(placeholder);
                if (i !== -1) pendingAttachments.splice(i, 1);
            } finally {
                uploadingCount--;
            }
            renderAttachmentPreview();
        })());
    }

    await Promise.all(groupTasks);
}

fileInput.addEventListener('change', function() {
    handleFileSelect(this.files);
    this.value = '';
});

folderInput.addEventListener('change', function() {
    handleFolderSelect(this.files);
    this.value = '';
});

document.addEventListener('click', (e) => {
    if (!isAttachMenuVisible()) return;
    if (attachMenu.contains(e.target) || attachBtn.contains(e.target)) return;
    hideAttachMenu();
});

// =====================================================================
// 工作区选择器（输入上方的项目选择器）
// =====================================================================
let _wsSelState = { current: null, recents: [], defaultWorkspace: '', projectsRoot: '' };

function _wsSelBtn() { return document.getElementById('workspace-selector-btn'); }
function _wsSelMenu() { return document.getElementById('workspace-selector-menu'); }

// 针对选择器错误的最小自解除 toast（不存在全局 toast）。
function _wsToast(msg) {
    let el = document.getElementById('ws-sel-toast');
    if (!el) {
        el = document.createElement('div');
        el.id = 'ws-sel-toast';
        el.style.cssText = 'position:fixed;bottom:80px;left:50%;transform:translateX(-50%);' +
            'background:#1e293b;color:#fff;padding:8px 14px;border-radius:8px;font-size:13px;' +
            'z-index:9999;box-shadow:0 4px 16px rgba(0,0,0,0.2);opacity:0;transition:opacity .2s;';
        document.body.appendChild(el);
    }
    el.textContent = msg;
    el.style.opacity = '1';
    clearTimeout(el._t);
    el._t = setTimeout(() => { el.style.opacity = '0'; }, 2600);
}

// 刷新当前会话的选择器状态+标签。
async function refreshWorkspaceSelector() {
    const label = document.getElementById('workspace-selector-label');
    try {
        const res = await fetch(`/api/projects?session=${encodeURIComponent(sessionId)}`);
        const data = await res.json();
        if (data.status !== 'success') return;
        _wsSelState = {
            current: data.current || null,
            recents: data.recents || [],
            defaultWorkspace: data.default_workspace || '',
            projectsRoot: data.projects_root || '',
        };
        _wsSelUpdateLabel();
    } catch (e) { /* 保留最后一个标签 */ }
}

// 将选择器按钮的标签和悬停工具提示与当前状态同步。
// 每次选择后调用，以便工具提示始终显示实时完整路径。
function _wsSelUpdateLabel() {
    const label = document.getElementById('workspace-selector-label');
    if (label) {
        label.textContent = _wsSelState.current
            ? _wsSelState.current.name
            : t('ws_default_workspace');
    }
    const btn = _wsSelBtn();
    if (btn) {
        // 默认工作区是静止状态，因此它会折叠到仅
        // 文件夹图标（与桌面编辑器匹配）；选定的工作空间
        // 显示其名称，以便用户知道他们已经放弃了默认设置。
        btn.classList.toggle('composer-chip-icon-only', !_wsSelState.current);
        const full = _wsSelState.current
            ? _wsSelState.current.path
            : _wsSelState.defaultWorkspace;
        btn.setAttribute('data-tooltip', full || t('ws_sel_title'));
        btn.setAttribute('data-tooltip-pos', 'top');
        // 通过身体级浮动工具提示进行路由，这样完整路径就不会出现
        // 被输入栏上方的聊天历史记录剪切/覆盖。
        btn.setAttribute('data-tip-float', '');
    }
}

function toggleWorkspaceSelector(event) {
    if (event) { event.preventDefault(); event.stopPropagation(); }
    const menu = _wsSelMenu();
    if (!menu) return;
    if (!menu.classList.contains('hidden')) {
        _wsSelHide();
        return;
    }
    _closeComposerMenus(menu);
    refreshWorkspaceSelector().then(renderWorkspaceSelectorMenu);
    menu.classList.remove('hidden');
    _wsSelBtn()?.classList.add('open');
}

function _wsSelHide() {
    const menu = _wsSelMenu();
    if (menu) menu.classList.add('hidden');
    _wsSelBtn()?.classList.remove('open');
}

function renderWorkspaceSelectorMenu() {
    const menu = _wsSelMenu();
    if (!menu) return;

    const parts = [];
    const isDefault = !_wsSelState.current;
    parts.push(`<div class="ws-sel-section-title">${escapeHtml(t('ws_sel_title'))}</div>`);
    // 默认工作区：悬停显示完整的 ~/cow 绝对路径。
    parts.push(`
        <button class="ws-sel-item ${isDefault ? 'active' : ''}" onclick="selectWorkspaceProject(null)"
                data-tip-float data-tooltip="${escapeHtml(_wsSelState.defaultWorkspace || '')}" data-tooltip-pos="bottom">
            <i class="fas fa-house"></i>
            <span class="ws-sel-name">${escapeHtml(t('ws_default_workspace'))}</span>
            ${isDefault ? '<i class="fas fa-check ws-sel-check"></i>' : ''}
        </button>`);

    if ((_wsSelState.recents || []).length) {
        parts.push(`<div class="ws-sel-divider"></div>`);
        parts.push(`<div class="ws-sel-section-title">${escapeHtml(t('ws_sel_recents'))}</div>`);
        _wsSelState.recents.forEach(r => {
            const active = _wsSelState.current && _wsSelState.current.path === r.path;
            parts.push(`
                <button class="ws-sel-item ${active ? 'active' : ''}" onclick="selectWorkspaceProject('${_wsAttr(r.path)}')"
                        data-tip-float data-tooltip="${escapeHtml(r.path)}" data-tooltip-pos="bottom">
                    <i class="fas fa-folder"></i>
                    <span class="ws-sel-name">${escapeHtml(r.name)}</span>
                    ${active ? '<i class="fas fa-check ws-sel-check"></i>' : ''}
                </button>`);
        });
    }

    parts.push(`<div class="ws-sel-divider"></div>`);
    parts.push(`
        <button class="ws-sel-item" onclick="wsSelOpenProjectDialog()">
            <i class="fas fa-folder-open"></i>
            <span class="ws-sel-name">${escapeHtml(t('ws_sel_open'))}</span>
        </button>`);
    parts.push(`
        <button class="ws-sel-item" onclick="wsSelNewProjectDialog()">
            <i class="fas fa-folder-plus"></i>
            <span class="ws-sel-name">${escapeHtml(t('ws_sel_new'))}</span>
        </button>`);

    menu.innerHTML = parts.join('');
}

// 转义路径以安全嵌入单引号内联处理程序中。
function _wsAttr(p) { return String(p || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'"); }

// ------- 文件夹选择器模式（打开现有项目）-------
let _fpCurrent = '';   // 当前列出的绝对路径
let _fpBound = false;  // 一次性侦听器绑定防护

function wsSelOpenProjectDialog() {
    _wsSelHide();
    _fpBindOnce();
    const overlay = document.getElementById('folder-picker-overlay');
    document.getElementById('folder-picker-cancel').textContent = t('channels_cancel') || t('ws_sel_up');
    document.getElementById('folder-picker-open').textContent = t('ws_sel_open_here');
    document.getElementById('folder-picker-hint').textContent = t('ws_sel_dblclick_hint');
    overlay.classList.remove('hidden');
    _fpBrowse('');  // '' => 后端从 ~ 开始
}

function _fpBindOnce() {
    if (_fpBound) return;
    _fpBound = true;
    const overlay = document.getElementById('folder-picker-overlay');
    const close = () => overlay.classList.add('hidden');
    document.getElementById('folder-picker-cancel').addEventListener('click', close);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    document.getElementById('folder-picker-open').addEventListener('click', async () => {
        if (!_fpCurrent) return;
        const ok = await _wsSelApply('/api/projects/select', { session: sessionId, project_dir: _fpCurrent });
        if (ok) close();
    });
}

// 列出逻辑驱动器的虚拟路径（Windows）；不是真正的可打开目录。
const _FP_DRIVES = '__DRIVES__';

async function _fpBrowse(path) {
    const list = document.getElementById('folder-picker-list');
    list.innerHTML = `<div class="fp-empty"><i class="fas fa-spinner fa-spin"></i></div>`;
    try {
        const res = await fetch(`/api/projects/browse?path=${encodeURIComponent(path || '')}`);
        const data = await res.json();
        if (data.status !== 'success') { list.innerHTML = `<div class="fp-empty">${escapeHtml(data.message || 'error')}</div>`; return; }
        const isDrives = data.path === _FP_DRIVES;
        _fpCurrent = isDrives ? null : data.path;
        // 驱动器视图是一个选择器，而不是真正的目录：显示标签和
        // 禁用“在此处打开”，以便无法将哨兵选为项目。
        const label = isDrives ? (t('ws_sel_drives') || 'This PC') : data.path;
        document.getElementById('folder-picker-path').textContent = label;
        document.getElementById('folder-picker-path').setAttribute('title', label);
        document.getElementById('folder-picker-open').disabled = isDrives;
        _fpRenderToolbar(data);
        _fpRenderList(data);
    } catch (e) {
        list.innerHTML = `<div class="fp-empty">${escapeHtml(String(e.message || e))}</div>`;
    }
}

function _fpRenderToolbar(data) {
    const bar = document.getElementById('folder-picker-toolbar');
    const upDisabled = !data.parent;
    bar.innerHTML = `
        <button class="fp-btn" ${upDisabled ? 'disabled' : ''} onclick="_fpBrowse('${_wsAttr(data.parent || '')}')" data-tooltip="${escapeHtml(t('ws_sel_up'))}" data-tooltip-pos="bottom">
            <i class="fas fa-arrow-up"></i>
        </button>
        <button class="fp-btn" onclick="_fpBrowse('~')" data-tooltip="~" data-tooltip-pos="bottom">
            <i class="fas fa-house"></i>
        </button>`;
}

function _fpRenderList(data) {
    const list = document.getElementById('folder-picker-list');
    const dirs = data.dirs || [];
    if (!dirs.length) {
        list.innerHTML = `<div class="fp-empty"><i class="fas fa-folder-open"></i><span>${escapeHtml(t('ws_sel_no_subdirs'))}</span></div>`;
        return;
    }
    list.innerHTML = dirs.map(d => `
        <div class="fp-row" ondblclick="_fpBrowse('${_wsAttr(d.path)}')" onclick="_fpSelectRow(this,'${_wsAttr(d.path)}')" title="${escapeHtml(d.path)}">
            <i class="fas fa-folder"></i>
            <span class="fp-name">${escapeHtml(d.name)}</span>
            <i class="fas fa-chevron-right fp-into" onclick="event.stopPropagation();_fpBrowse('${_wsAttr(d.path)}')"></i>
        </div>`).join('');
}

// 单击选择一个子文件夹作为目标（这样您就可以打开一个文件夹
// 无需导航）；双击/V 形在内部导航。
function _fpSelectRow(el, path) {
    document.querySelectorAll('#folder-picker-list .fp-row.selected').forEach(r => r.classList.remove('selected'));
    el.classList.add('selected');
    _fpCurrent = path;
    // 选择一行（例如驱动器视图中的驱动器）再次成为有效目标。
    document.getElementById('folder-picker-open').disabled = false;
    document.getElementById('folder-picker-path').textContent = path;
}

// 按名称创建一个新项目（位于项目根目录下），然后将其打开。
function wsSelNewProjectDialog() {
    _wsSelHide();
    openKnowledgeDialog({
        title: t('ws_sel_new'),
        subtitle: (t('ws_sel_new_subtitle') || '').replace('{root}', _wsSelState.projectsRoot || ''),
        label: t('ws_sel_new_placeholder'),
        hint: t('ws_sel_new_hint'),
        icon: 'fa-folder-plus',
        value: '',
        validate: (v) => {
            v = (v || '').trim();
            if (!v) return t('ws_sel_name_required');
            if (v.includes('/') || v.includes('\\')) return t('ws_sel_name_no_slash');
            return '';
        },
        onSubmit: async (name) => {
            const ok = await _wsSelApply('/api/projects/create', { session: sessionId, name: name.trim() });
            return ok ? true : null;
        },
    });
}

// 选择/创建的共享应用路径：POST，更新标签，然后显示
// 项目位于右侧文件面板中，以便用户看到它们位于其中“内部”。
async function _wsSelApply(url, body) {
    try {
        const res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await res.json();
        if (data.status !== 'success') { _wsToast(data.message || 'failed'); return false; }
        _wsSelState.current = data.current || null;
        if (Array.isArray(data.recents)) _wsSelState.recents = data.recents;
        if (data.default_workspace) _wsSelState.defaultWorkspace = data.default_workspace;
        _wsSelUpdateLabel();
        _wsSelRevealFiles();
        return true;
    } catch (e) { _wsToast(String(e.message || e)); return false; }
}

// 打开（或刷新）“文件”选项卡上的右侧文件面板，以便新
// 所选项目的目录是可见的。
function _wsSelRevealFiles() {
    try {
        if (typeof openWorkspacePanel === 'function') {
            wsAutoOpenSuppressed = false;
            // 打开之前重置为新工作区的根目录。
            if (typeof wsCurrentDir !== 'undefined') wsCurrentDir = '';
            openWorkspacePanel('files');
        }
        if (typeof refreshWorkspaceTree === 'function') refreshWorkspaceTree();
    } catch (e) { /* 该视图中不存在面板 */ }
}

// 为不通过对话框进行选择的呼叫者保留（默认/最近）。
async function selectWorkspaceProject(projectDir) {
    _wsSelHide();
    await _wsSelApply('/api/projects/select', { session: sessionId, project_dir: projectDir });
}

document.addEventListener('click', (e) => {
    const menu = _wsSelMenu();
    const btn = _wsSelBtn();
    if (!menu || menu.classList.contains('hidden')) return;
    if (menu.contains(e.target) || (btn && btn.contains(e.target))) return;
    _wsSelHide();
});

// =====================================================================
// 每会话设置：权限模式和模型
//
// 两者都位于输入下方的工作区选择器旁边，因为所有三个
// 回答同样的问题 - 这个对话可以做什么，以及
// 什么。每个都回退到全局设置，直到用户在此处固定一个，因此
// 从未触及的会话会继续遵循设置。
// =====================================================================

// 每种模式的图标和 i18n 键。首先订购最开放的，以便菜单读取
// “最少限制”向下，与芯片颜色升级的方式相匹配。
const PERMISSION_META = {
    'full-access':     { icon: 'fa-lock-open',     key: 'perm_full_access' },
    'workspace-write': { icon: 'fa-shield-halved', key: 'perm_workspace_write' },
    'read-only':       { icon: 'fa-eye',           key: 'perm_read_only' },
};

// GET /api/sessions/<id>/settings 的最后状态； null 直到第一次获取。
let _sessCfg = null;

function _permBtn() { return document.getElementById('permission-selector-btn'); }
function _permMenu() { return document.getElementById('permission-selector-menu'); }
function _modelBtn() { return document.getElementById('model-selector-btn'); }
function _modelMenu() { return document.getElementById('model-selector-menu'); }

function _permLabel(mode) { return t((PERMISSION_META[mode] || {}).key || 'perm_full_access'); }

/** Close every composer popover except `keep` (so one chip's menu replaces another's). */
function _closeComposerMenus(keep) {
    [[_wsSelMenu(), _wsSelBtn()], [_permMenu(), _permBtn()], [_modelMenu(), _modelBtn()]]
        .forEach(([menu, btn]) => {
            if (!menu || menu === keep) return;
            menu.classList.add('hidden');
            if (btn) btn.classList.remove('open');
        });
    const agentMenu = document.getElementById('composer-agent-menu');
    if (agentMenu && agentMenu !== keep) agentMenu.classList.add('hidden');
}

// 获取本次会话的有效模型+权限并重新绘制两个芯片。
async function refreshSessionSettings() {
    try {
        const res = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/settings`);
        const data = await res.json();
        if (data.status !== 'success') return;
        _sessCfg = { model: data.model, permission: data.permission, team: data.team };
    } catch (e) {
        // 保留芯片已经显示的任何内容，而不是消隐它们。
        return;
    }
    _renderPermissionChip();
    _renderModelChip();
    renderComposerIdentity();
}

function _renderPermissionChip() {
    const btn = _permBtn();
    if (!btn || !_sessCfg) return;
    const state = _sessCfg.permission || {};
    const mode = state.mode || 'full-access';
    const meta = PERMISSION_META[mode] || PERMISSION_META['full-access'];

    const label = document.getElementById('permission-selector-label');
    if (label) label.textContent = _permLabel(mode);
    const icon = document.getElementById('permission-selector-icon');
    if (icon) icon.className = `fas ${meta.icon}`;

    // 每种模式一种颜色，因此不受限制的会话与
    // 只读的，无需阅读标签。
    btn.classList.remove('perm-read-only', 'perm-workspace-write', 'perm-full-access');
    btn.classList.add(`perm-${mode}`);

    const tip = t('perm_tip').replace('{name}', _permLabel(mode))
        + (state.source === 'global' ? ` · ${t('perm_follow_global')}` : '');
    btn.setAttribute('data-tooltip', tip);
    btn.setAttribute('data-tooltip-pos', 'top');
    btn.setAttribute('data-tip-float', '');
}

function _renderModelChip() {
    const btn = _modelBtn();
    if (!btn || !_sessCfg) return;
    // 一旦对话有多个代理，就没有单一的模型可以
    // 显示：每个人都有自己的答案。在这里固定一个会默默地适用于
    // 无论谁碰巧拥有对话。
    const shared = sharedConversation();
    btn.classList.toggle('hidden', shared);
    if (shared) {
        _modelMenu()?.classList.add('hidden');
        btn.classList.remove('open');
        return;
    }
    const state = _sessCfg.model || {};
    const model = state.model || '';

    const label = document.getElementById('model-selector-label');
    if (label) label.textContent = model || t('model_unset');

    const tip = t('model_tip').replace('{name}', model || t('model_unset'))
        + (state.source === 'global' ? ` · ${t('model_follow_global')}` : '')
        + (state.source === 'agent' ? ` · ${t('model_follow_agent')}` : '');
    btn.setAttribute('data-tooltip', tip);
    btn.setAttribute('data-tooltip-pos', 'top');
    btn.setAttribute('data-tip-float', '');
}

function togglePermissionSelector(event) {
    if (event) { event.preventDefault(); event.stopPropagation(); }
    const menu = _permMenu();
    if (!menu) return;
    if (!menu.classList.contains('hidden')) {
        _closeComposerMenus();
        return;
    }
    _closeComposerMenus(menu);
    const open = () => { renderPermissionMenu(); menu.classList.remove('hidden'); _permBtn()?.classList.add('open'); };
    if (_sessCfg) open(); else refreshSessionSettings().then(open);
}

function renderPermissionMenu() {
    const menu = _permMenu();
    if (!menu) return;
    const state = (_sessCfg && _sessCfg.permission) || {};
    const modes = state.modes && state.modes.length ? state.modes : Object.keys(PERMISSION_META);
    const current = state.mode || 'full-access';
    const isGlobal = state.source === 'global';

    const parts = [`<div class="composer-menu-title">${escapeHtml(t('perm_menu_title'))}</div>`];
    // 菜单顺序遵循 PERMISSION_META，而不是后端元组，因此列表
    // 即使后端重新排序其模式，也能一致地读取。 “关注全球”
    // 故意不单独成一行：选择一个模式只需将其固定，并且
    // 单击已经激活的模式会清除引脚（返回全局），因此
    // 行为仍然可以实现，而不会使菜单混乱。
    Object.keys(PERMISSION_META).filter(m => modes.includes(m)).forEach(mode => {
        const meta = PERMISSION_META[mode];
        const active = mode === current;
        // 当此模式处于活动状态并且已固定时，单击它会清除
        // 引脚；否则单击固定此模式。
        const arg = (active && !isGlobal) ? 'null' : `'${mode}'`;
        parts.push(`
            <button class="composer-menu-item ${active ? 'active' : ''}" onclick="selectSessionPermission(${arg})">
                <i class="fas ${meta.icon}"></i>
                <span class="composer-menu-body">
                    <span class="composer-menu-name">${escapeHtml(t(meta.key))}</span>
                    <span class="composer-menu-desc">${escapeHtml(t(meta.key + '_desc'))}</span>
                </span>
                ${active ? '<i class="fas fa-check composer-menu-check"></i>' : ''}
            </button>`);
    });

    menu.innerHTML = parts.join('');
}

/** Pin this session's permission mode, or pass null to follow the global one. */
async function selectSessionPermission(mode) {
    _closeComposerMenus();
    await _applySessionSettings({ permission: mode });
}

// 在其调用被拒绝的工具卡后插入可操作的提示
// 许可门。单击它会在输入下打开权限选择器，以便
// 用户无需寻找芯片即可提高模式。
function _appendPermissionDeniedHint(toolEl, mode) {
    if (!toolEl || !toolEl.parentElement) return;
    // 如果模型重试同一个被阻止的调用，请避免堆叠重复的提示。
    if (toolEl.nextElementSibling
        && toolEl.nextElementSibling.classList
        && toolEl.nextElementSibling.classList.contains('perm-denied-hint')) {
        return;
    }
    const label = _permLabel(mode || (_sessCfg && _sessCfg.permission && _sessCfg.permission.mode) || 'workspace-write');
    const hint = document.createElement('div');
    hint.className = 'perm-denied-hint';
    hint.innerHTML = `
        <i class="fas fa-shield-halved"></i>
        <span class="perm-denied-text">${escapeHtml(t('perm_denied_hint').replace('{name}', label))}</span>
        <button type="button" class="perm-denied-btn">${escapeHtml(t('perm_denied_action'))}</button>`;
    hint.querySelector('.perm-denied-btn').addEventListener('click', (e) => {
        e.stopPropagation();
        const btn = _permBtn();
        if (btn) { btn.scrollIntoView({ block: 'nearest' }); }
        togglePermissionSelector();
    });
    toolEl.parentElement.insertBefore(hint, toolEl.nextElementSibling);
}

function toggleModelSelector(event) {
    if (event) { event.preventDefault(); event.stopPropagation(); }
    const menu = _modelMenu();
    if (!menu) return;
    if (!menu.classList.contains('hidden')) {
        _closeComposerMenus();
        return;
    }
    _closeComposerMenus(menu);
    const open = () => { renderModelMenu(); menu.classList.remove('hidden'); _modelBtn()?.classList.add('open'); };
    // 始终重新获取：目录取决于哪些提供者拥有密钥，哪些提供者拥有密钥
    // 自加载此页面以来，“设置”中可能已发生更改。
    refreshSessionSettings().then(() => { if (_sessCfg) open(); });
}

function renderModelMenu() {
    const menu = _modelMenu();
    if (!menu) return;
    const state = (_sessCfg && _sessCfg.model) || {};
    const providers = state.providers || [];
    const pinned = state.source === 'session';

    // 目前哪种模型有效（固定的或者继承自全局），所以
    // 即使会话遵循全局模型，复选标记也会显示在其上。
    const activeModel = state.model || (state.global && state.global.model) || '';
    const activeProvider = state.provider || (state.global && state.global.provider) || '';

    const parts = [`<div class="composer-menu-title">${escapeHtml(t('model_menu_title'))}</div>`];
    providers.forEach((p, idx) => {
        if (idx > 0) parts.push('<div class="composer-menu-divider"></div>');
        parts.push(`<div class="composer-menu-title">${escapeHtml(localizedLabel(p.label))}</div>`);
        (p.models || []).forEach(m => {
            const active = m === activeModel && p.id === activeProvider;
            // 单击已固定的模型可清除固定（返回全局）；
            // “关注全球”不再是单独的一行。
            const arg = (active && pinned)
                ? 'null, null'
                : `'${_wsAttr(p.id)}','${_wsAttr(m)}'`;
            parts.push(`
                <button class="composer-menu-item ${active ? 'active' : ''}"
                        onclick="selectSessionModel(${arg})">
                    <i class="fas fa-microchip"></i>
                    <span class="composer-menu-body">
                        <span class="composer-menu-name">${escapeHtml(m)}</span>
                    </span>
                    ${active ? '<i class="fas fa-check composer-menu-check"></i>' : ''}
                </button>`);
        });
    });

    menu.innerHTML = parts.join('');
}

/** Pin a model for this session; pass nulls to follow the global model again. */
async function selectSessionModel(provider, model) {
    _closeComposerMenus();
    await _applySessionSettings({ provider: provider, model: model });
}

// 两个芯片的单一编写器：发布更改，然后从状态重新绘制
// 后端回显，因此 UI 永远不会与存储的内容不一致。
async function _applySessionSettings(body) {
    try {
        const res = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/settings`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await res.json();
        if (data.status !== 'success') { _wsToast(data.message || t('session_settings_failed')); return; }
        _sessCfg = { model: data.model, permission: data.permission };
        _renderPermissionChip();
        _renderModelChip();
    } catch (e) {
        _wsToast(t('session_settings_failed'));
    }
}

document.addEventListener('click', (e) => {
    [[_permMenu(), _permBtn()], [_modelMenu(), _modelBtn()]].forEach(([menu, btn]) => {
        if (!menu || menu.classList.contains('hidden')) return;
        if (menu.contains(e.target) || (btn && btn.contains(e.target))) return;
        menu.classList.add('hidden');
        if (btn) btn.classList.remove('open');
    });
});

// 整个聊天视图上的拖放支持
const chatView = document.getElementById('view-chat');
const chatInputArea = document.getElementById('composer-card') || chatInput.closest('.flex-shrink-0');

// 创建拖动叠加以获得视觉反馈
let dragOverlay = document.getElementById('drag-overlay');
if (!dragOverlay) {
    dragOverlay = document.createElement('div');
    dragOverlay.id = 'drag-overlay';
    dragOverlay.className = 'drag-overlay hidden';
    dragOverlay.innerHTML = `
        <div class="drag-overlay-content">
            <i class="fas fa-cloud-arrow-up"></i>
            <p>Drop files here to upload</p>
        </div>
    `;
    chatView.appendChild(dragOverlay);
}

let dragCounter = 0;

function showDragOverlay() {
    dragOverlay.classList.remove('hidden');
    dragOverlay.classList.add('active');
}

function hideDragOverlay() {
    dragOverlay.classList.remove('active');
    dragOverlay.classList.add('hidden');
}

/** Clear every drag affordance at once, whatever the drag's outcome was. */
function resetDragState() {
    dragCounter = 0;
    hideDragOverlay();
    chatInputArea.classList.remove('drag-over');
    document.getElementById('chat-main')?.classList.remove('ws-drop-active');
}

chatView.addEventListener('dragenter', (e) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter++;
    if (e.dataTransfer.types.includes('Files')) {
        showDragOverlay();
    }
});

chatView.addEventListener('dragover', (e) => {
    e.preventDefault();
    e.stopPropagation();
    // 这里只有外部文件拖拽上传；工作区拖动有自己的目标。
    if (e.dataTransfer.types.includes('Files')) {
        chatInputArea.classList.add('drag-over');
    }
});

chatView.addEventListener('dragleave', (e) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter--;
    if (dragCounter <= 0) {
        resetDragState();
    }
});

chatView.addEventListener('drop', (e) => {
    e.preventDefault();
    e.stopPropagation();
    resetDragState();
    if (e.dataTransfer.files.length) {
        handleFileSelect(e.dataTransfer.files);
    }
});

// 拖动可能会在未到达放置目标（Esc 或通过释放）的情况下结束
// 另一个元素）。无条件清除突出显示，使其不会卡住
// 直到下一次重新加载。
document.addEventListener('dragend', resetDragState);
window.addEventListener('drop', resetDragState);

document.body.addEventListener('dragover', (e) => {
    if (e.dataTransfer.types.includes('Files')) {
        e.preventDefault();
    }
});

document.body.addEventListener('drop', (e) => {
    if (e.dataTransfer.types.includes('Files')) {
        e.preventDefault();
    }
});

// 粘贴图像支持
chatInput.addEventListener('paste', (e) => {
    const items = e.clipboardData?.items;
    if (!items) return;
    const files = [];
    for (const item of items) {
        if (item.kind === 'file') {
            files.push(item.getAsFile());
        }
    }
    if (files.length) {
        e.preventDefault();
        handleFileSelect(files);
    }
});

chatInput.addEventListener('compositionstart', () => { isComposing = true; });
chatInput.addEventListener('compositionend', () => { setTimeout(() => { isComposing = false; }, 100); });

// ── 斜线命令菜单────────────────────────────────────────
// desc 持有一个 i18n 键，在渲染时通过 t() 解析，因此菜单如下
// 当前的用户界面语言。
const SLASH_COMMANDS = [
    { cmd: '/help',                desc: 'slash_help' },
    { cmd: '/status',              desc: 'slash_status' },
    { cmd: '/context',             desc: 'slash_context' },
    { cmd: '/clear',               desc: 'slash_context_clear' },
    { cmd: '/compact',             desc: 'slash_compact' },
    { cmd: '/skill list',          desc: 'slash_skill_list' },
    { cmd: '/skill list --remote', desc: 'slash_skill_list_remote' },
    { cmd: '/skill search ',       desc: 'slash_skill_search' },
    { cmd: '/skill install ',      desc: 'slash_skill_install' },
    { cmd: '/skill uninstall ',    desc: 'slash_skill_uninstall' },
    { cmd: '/skill info ',         desc: 'slash_skill_info' },
    { cmd: '/skill enable ',       desc: 'slash_skill_enable' },
    { cmd: '/skill disable ',      desc: 'slash_skill_disable' },
    { cmd: '/memory dream ',       desc: 'slash_memory_dream' },
    { cmd: '/knowledge',           desc: 'slash_knowledge' },
    { cmd: '/knowledge list',      desc: 'slash_knowledge_list' },
    { cmd: '/knowledge on',        desc: 'slash_knowledge_on' },
    { cmd: '/knowledge off',       desc: 'slash_knowledge_off' },
    { cmd: '/config',              desc: 'slash_config' },
    { cmd: '/cancel',              desc: 'slash_cancel' },
    { cmd: '/steer ',              desc: 'slash_steer' },
    { cmd: '/logs',                desc: 'slash_logs' },
    { cmd: '/version',             desc: 'slash_version' },
];

const slashMenu = document.getElementById('slash-menu');
let slashActiveIdx = 0;
let slashFiltered = [];
let slashJustSelected = false;
let slashLastFilter = '';
let slashLastMouseX = -1;
let slashLastMouseY = -1;

function showSlashMenu(filter) {
    const q = filter.toLowerCase();
    if (q === slashLastFilter && !slashMenu.classList.contains('hidden')) return;
    slashLastFilter = q;

    const newFiltered = SLASH_COMMANDS.filter(c => c.cmd.toLowerCase().startsWith(q));
    if (newFiltered.length === 0) {
        hideSlashMenu();
        return;
    }

    const changed = newFiltered.length !== slashFiltered.length ||
        newFiltered.some((c, i) => c.cmd !== slashFiltered[i]?.cmd);
    slashFiltered = newFiltered;
    if (changed) slashActiveIdx = 0;
    slashActiveIdx = Math.min(slashActiveIdx, slashFiltered.length - 1);

    slashNavByKeyboard = true;
    renderSlashItems();
    slashMenu.classList.remove('hidden');
}

function hideSlashMenu() {
    slashMenu.classList.add('hidden');
    slashMenu.innerHTML = '';
    slashFiltered = [];
    slashActiveIdx = -1;
    slashLastFilter = '';
    slashNavByKeyboard = false;
    slashLastMouseX = -1;
    slashLastMouseY = -1;
}

function isSlashMenuVisible() {
    return !slashMenu.classList.contains('hidden') && slashFiltered.length > 0;
}

function renderSlashItems() {
    slashMenu.innerHTML =
        '<div class="slash-menu-header">Commands</div>' +
        slashFiltered.map((c, i) =>
            `<div class="slash-menu-item${i === slashActiveIdx ? ' active' : ''}" data-idx="${i}">` +
            `<span class="cmd">${escapeHtml(c.cmd)}</span>` +
            `<span class="desc">${escapeHtml(t(c.desc))}</span></div>`
        ).join('');

    const activeEl = slashMenu.querySelector('.slash-menu-item.active');
    if (activeEl) activeEl.scrollIntoView({ block: 'nearest' });
}

// 持久的slashMenu容器上的委派事件（不会被innerHTML破坏）
// 使用坐标比较来区分真实的鼠标移动和 DOM 重建幻像事件。
slashMenu.addEventListener('mousemove', (e) => {
    if (e.clientX === slashLastMouseX && e.clientY === slashLastMouseY) return;
    slashLastMouseX = e.clientX;
    slashLastMouseY = e.clientY;
    if (!slashNavByKeyboard) return;
    slashNavByKeyboard = false;
    const item = e.target.closest('.slash-menu-item');
    if (!item) return;
    const idx = parseInt(item.dataset.idx);
    if (idx === slashActiveIdx) return;
    slashActiveIdx = idx;
    slashMenu.querySelectorAll('.slash-menu-item').forEach(el => {
        el.classList.toggle('active', parseInt(el.dataset.idx) === idx);
    });
});

slashMenu.addEventListener('mouseover', (e) => {
    if (slashNavByKeyboard) return;
    const item = e.target.closest('.slash-menu-item');
    if (!item) return;
    const idx = parseInt(item.dataset.idx);
    if (idx === slashActiveIdx) return;
    slashActiveIdx = idx;
    slashMenu.querySelectorAll('.slash-menu-item').forEach(el => {
        el.classList.toggle('active', parseInt(el.dataset.idx) === idx);
    });
});

slashMenu.addEventListener('mousedown', (e) => {
    const item = e.target.closest('.slash-menu-item');
    if (!item) return;
    e.preventDefault();
    selectSlashCommand(parseInt(item.dataset.idx));
});

function selectSlashCommand(idx) {
    if (idx < 0 || idx >= slashFiltered.length) return;
    const chosen = slashFiltered[idx].cmd;
    slashJustSelected = true;
    chatInput.value = chosen;
    chatInput.dispatchEvent(new Event('input'));
    hideSlashMenu();
    chatInput.focus();
    chatInput.selectionStart = chatInput.selectionEnd = chosen.length;
}

chatInput.addEventListener('input', function() {
    autoResizeComposer();
    updateSendBtnState();

    const val = this.value;
    if (slashJustSelected) {
        slashJustSelected = false;
    } else if (val.startsWith('/')) {
        showSlashMenu(val);
    } else {
        hideSlashMenu();
    }
});

chatInput.addEventListener('keydown', function(e) {
    if (e.keyCode === 229 || e.isComposing || isComposing) return;

    if (e.key === 'Escape' && isAttachMenuVisible()) {
        hideAttachMenu();
        return;
    }

    if (isSlashMenuVisible()) {
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            slashNavByKeyboard = true;
            slashActiveIdx = Math.min(slashActiveIdx + 1, slashFiltered.length - 1);
            renderSlashItems();
            return;
        }
        if (e.key === 'ArrowUp') {
            e.preventDefault();
            slashNavByKeyboard = true;
            slashActiveIdx = Math.max(slashActiveIdx - 1, 0);
            renderSlashItems();
            return;
        }
        if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey) {
            e.preventDefault();
            selectSlashCommand(slashActiveIdx);
            return;
        }
        if (e.key === 'Escape') {
            e.preventDefault();
            hideSlashMenu();
            return;
        }
        if (e.key === 'Tab') {
            e.preventDefault();
            selectSlashCommand(slashActiveIdx);
            return;
        }
    }

    // 箭头键历史记录调用（仅当输入为空或已经浏览历史记录时）
    if (e.key === 'ArrowUp' && inputHistory.length > 0 && !isSlashMenuVisible()) {
        const curVal = this.value.trim();
        const isSingleLine = !this.value.includes('\n');
        if (isSingleLine && (curVal === '' || historyIdx >= 0)) {
            e.preventDefault();
            if (historyIdx < 0) {
                historySavedDraft = this.value;
                historyIdx = inputHistory.length - 1;
            } else if (historyIdx > 0) {
                historyIdx--;
            }
            this.value = inputHistory[historyIdx];
            slashJustSelected = true;
            this.dispatchEvent(new Event('input'));
            hideSlashMenu();
            this.selectionStart = this.selectionEnd = this.value.length;
            return;
        }
    }
    if (e.key === 'ArrowDown' && historyIdx >= 0 && !isSlashMenuVisible()) {
        const isSingleLine = !this.value.includes('\n');
        if (isSingleLine) {
            e.preventDefault();
            if (historyIdx < inputHistory.length - 1) {
                historyIdx++;
                this.value = inputHistory[historyIdx];
            } else {
                historyIdx = -1;
                this.value = historySavedDraft;
                historySavedDraft = '';
            }
            slashJustSelected = true;
            this.dispatchEvent(new Event('input'));
            hideSlashMenu();
            this.selectionStart = this.selectionEnd = this.value.length;
            return;
        }
    }

    if ((e.ctrlKey || e.shiftKey) && e.key === 'Enter') {
        const start = this.selectionStart;
        const end = this.selectionEnd;
        this.value = this.value.substring(0, start) + '\n' + this.value.substring(end);
        this.selectionStart = this.selectionEnd = start + 1;
        this.dispatchEvent(new Event('input'));
        e.preventDefault();
    } else if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey) {
        sendMessage();
        e.preventDefault();
    }
});

chatInput.addEventListener('blur', () => {
    setTimeout(hideSlashMenu, 150);
});

document.querySelectorAll('.example-card').forEach(card => {
    card.addEventListener('click', () => {
        // data-send overrides the visible text (e.g. show "查看全部命令" but send "/help")
        const sendText = card.dataset.send;
        if (sendText) {
            chatInput.value = sendText;
            chatInput.dispatchEvent(new Event('input'));
            chatInput.focus();
            return;
        }
        const textEl = card.querySelector('[data-i18n*="text"]');
        if (textEl) {
            chatInput.value = textEl.textContent;
            chatInput.dispatchEvent(new Event('input'));
            chatInput.focus();
        }
    });
});

// sendMessage() 的语音消息变体：呈现可播放的音频气泡
// 带有 ASR 标题，然后将识别的文本发送到 /message
// 通过与键入消息相同的 SSE/加载流程。
function sendVoiceMessage(text, audioUrl) {
    text = (text || '').trim();
    if (!text) return;

    inputHistory.push(text);
    historyIdx = -1;
    historySavedDraft = '';

    const ws = document.getElementById('welcome-screen');
    const isFirstMessage = !!ws;
    if (ws) ws.remove();

    const titleInfo = isFirstMessage ? { sid: sessionId, userMsg: text } : null;
    const timestamp = new Date();
    addUserVoiceMessage(audioUrl, text, timestamp);
    const loadingEl = addLoadingIndicator();

    const body = {
        session_id: sessionId,
        message: text,
        stream: true,
        timestamp: timestamp.toISOString(),
        is_voice: true,
        lang: currentLang,
    };

    const MAX_RETRIES = 2;
    const RETRY_DELAY_MS = 1000;
    function postWithRetry(attempt) {
        fetch('/message', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'success') {
                rememberLiveSpeaker(data);
                setLoadingSpeaker(loadingEl, data.request_id);
                if (data.inline_reply) {
                    // 同步快速路径回复（例如/取消）；跳过上交所。
                    loadingEl.remove();
                    addBotMessage(data.inline_reply, new Date());
                } else if (data.stream) {
                    setSendBtnCancelMode(data.request_id);
                    startSSE(data.request_id, loadingEl, timestamp, titleInfo);
                } else {
                    loadingContainers[data.request_id] = loadingEl;
                }
            } else {
                loadingEl.remove();
                addBotMessage(t('error_send'), new Date());
                resetSendBtnSendMode();
            }
        })
        .catch(err => {
            if (attempt < MAX_RETRIES) {
                setTimeout(() => postWithRetry(attempt + 1), RETRY_DELAY_MS * (attempt + 1));
                return;
            }
            loadingEl.remove();
            addBotMessage(t('error_send'), new Date());
        });
    }
    postWithRetry(0);
}

function addUserVoiceMessage(audioUrl, caption, timestamp) {
    const el = document.createElement('div');
    el.className = 'flex justify-end px-4 sm:px-6 py-3';
    // 语音消息气泡：紧凑的语音丸位于顶部，ASR 标题位于下方。
    // 气泡与普通用户消息保持相同的主色调，因此
    // 它在视觉上融入了对话流。
    el.innerHTML = `
        <div class="max-w-[75%] sm:max-w-[60%]">
            <div class="bg-slate-100 dark:bg-white/10 text-slate-700 dark:text-slate-200 rounded-2xl px-3 py-2 msg-content user-bubble">
                <div class="user-voice-slot"></div>
                ${caption ? `<div class="text-xs mt-1.5 leading-snug text-slate-500 dark:text-slate-400 whitespace-pre-wrap break-words">${escapeHtml(caption)}</div>` : ''}
            </div>
            <div class="text-xs text-slate-400 dark:text-slate-500 mt-1.5 text-right">${formatTime(timestamp)}</div>
        </div>
    `;
    el.querySelector('.user-voice-slot').appendChild(renderVoicePill(audioUrl));
    messagesDiv.appendChild(el);
    _autoScrollEnabled = true;
    scrollChatToBottom(true);
}

// 具有非 HTTPS 环境回退功能的剪贴板助手
function copyToClipboard(text) {
    if (navigator.clipboard && window.isSecureContext) {
        return navigator.clipboard.writeText(text);
    }
    // HTTP 环境的后备
    return new Promise((resolve, reject) => {
        const textArea = document.createElement('textarea');
        textArea.value = text;
        textArea.style.position = 'fixed';
        textArea.style.left = '-999999px';
        textArea.style.top = '-999999px';
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        try {
            document.execCommand('copy') ? resolve() : reject(new Error('Copy failed'));
        } catch (err) {
            reject(err);
        } finally {
            textArea.remove();
        }
    });
}

// 编辑用户消息：提取内容、删除此消息及后续消息、填写输入
async function editUserMessage(msgEl) {
    if (isCurrentSessionConversationActive()) return;
    const rawContent = msgEl.dataset.rawContent;
    if (!rawContent) return;

    // 从数据库中删除此消息和所有后续消息（级联）
    // 必须等待以确保在用户发送新消息之前删除完成
    const userSeq = msgEl.dataset.seq;
    if (userSeq) {
        try {
            const resp = await fetch('/api/messages/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    session_id: sessionId, 
                    user_seq: parseInt(userSeq),
                    delete_user: true,
                    cascade: true
                })
            });
            const data = await resp.json();
            if (data.status === 'success') console.log(`Deleted ${data.deleted} old messages`);
        } catch (err) {
            console.error('Failed to delete old messages:', err);
        }
    }

    // 删除此消息气泡以及所属的所有后续气泡
    // 本轮或后续轮。我们镜像后端级联合约：
    // data-seq >= 当前 seq 的任何内容，以及任何实时 SSE 泡沫
    // 此后仍在流式传输（还没有序列）。
    const currentSeqNum = userSeq ? parseInt(userSeq) : null;
    const messagesToRemove = [];
    let current = msgEl;
    while (current) {
        if (current.classList && (current.classList.contains('user-message-group') || current.classList.contains('bot-message-group'))) {
            const seqAttr = current.dataset.seq;
            if (seqAttr === undefined || seqAttr === '') {
                // 还没有持久序列的实时消息 - 稍后处理。
                messagesToRemove.push(current);
            } else if (currentSeqNum === null || parseInt(seqAttr) >= currentSeqNum) {
                messagesToRemove.push(current);
            }
        }
        current = current.nextElementSibling;
    }
    messagesToRemove.forEach(el => {
        if (el && el.parentNode) el.parentNode.removeChild(el);
    });

    // 使用原始内容填充输入
    chatInput.value = rawContent;
    chatInput.dispatchEvent(new Event("input", { bubbles: true }));
    chatInput.focus();
    chatInput.selectionStart = chatInput.selectionEnd = chatInput.value.length;
    scrollChatToBottom();
}

// 重新生成机器人响应：找到前面的用户消息并重新发送
async function regenerateResponse(botMsgEl) {
    let prevEl = botMsgEl.previousElementSibling;
    while (prevEl && !prevEl.classList.contains('user-message-group')) {
        prevEl = prevEl.previousElementSibling;
    }

    if (!prevEl) {
        console.warn('No preceding user message found');
        return;
    }

    const userContent = prevEl.dataset.rawContent;
    if (!userContent) {
        console.warn('No content in preceding user message');
        return;
    }

    // 从数据库中删除旧的用户消息和机器人回复
    // （因为 /message 将创建一条新的用户消息+新的机器人回复）
    // 必须等待以确保删除在发送/消息之前完成
    const userSeq = prevEl.dataset.seq;
    if (userSeq) {
        try {
            const resp = await fetch('/api/messages/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    session_id: sessionId, 
                    user_seq: parseInt(userSeq),
                    delete_user: true
                })
            });
            const data = await resp.json();
            if (data.status === 'success') console.log(`Deleted ${data.deleted} old messages`);
        } catch (err) {
            console.error('Failed to delete old messages:', err);
        }
    }

    // 从 DOM 中删除旧的用户消息和机器人消息
    if (prevEl.parentNode) prevEl.parentNode.removeChild(prevEl);
    if (botMsgEl.parentNode) botMsgEl.parentNode.removeChild(botMsgEl);

    // 将用户消息重新添加到 DOM（以便它出现在加载指示器之前）
    addUserMessage(userContent, new Date());

    // 显示加载指示器
    const loadingEl = addLoadingIndicator();

    // 重新发送消息
    const timestamp = new Date();
    const body = { session_id: sessionId, message: userContent, stream: true, timestamp: timestamp.toISOString(), lang: currentLang };
    const regenAddressed = addressedAgentId(userContent);
    if (regenAddressed) body.speaker_agent_id = regenAddressed;

    const MAX_RETRIES = 2;
    const RETRY_DELAY_MS = 1000;

    function postWithRetry(attempt) {
        fetch('/message', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'success') {
                rememberLiveSpeaker(data);
                setLoadingSpeaker(loadingEl, data.request_id);
                if (data.inline_reply) {
                    loadingEl.remove();
                    addBotMessage(data.inline_reply, new Date());
                } else if (data.stream) {
                    setSendBtnCancelMode(data.request_id);
                    startSSE(data.request_id, loadingEl, timestamp, null);
                } else {
                    loadingContainers[data.request_id] = loadingEl;
                }
            } else {
                loadingEl.remove();
                addBotMessage(t('error_send'), new Date());
                resetSendBtnSendMode();
            }
        })
        .catch(err => {
            if (err.name === 'AbortError') {
                loadingEl.remove();
                addBotMessage(t('error_timeout'), new Date());
                resetSendBtnSendMode();
                return;
            }
            if (attempt < MAX_RETRIES) {
                console.warn(`[regenerateResponse] attempt ${attempt + 1} failed, retrying...`, err);
                setTimeout(() => postWithRetry(attempt + 1), RETRY_DELAY_MS * (attempt + 1));
                return;
            }
            loadingEl.remove();
            addBotMessage(t('error_send'), new Date());
            resetSendBtnSendMode();
        });
    }

    postWithRetry(0);
}

function sendMessage() {
    // 不要在此处的 sendBtnMode 上分支：Enter 应始终发送（因此
    // 输入“/cancel”即可正常提交）。取消仅连接到
    // 发送按钮的指针单击 — 请参阅上面的 send-btn 侦听器。

    const text = chatInput.value.trim();
    if (!text && pendingAttachments.length === 0) return;

    if (text) {
        inputHistory.push(text);
        historyIdx = -1;
        historySavedDraft = '';
    }

    const ws = document.getElementById('welcome-screen');
    const isFirstMessage = !!ws;
    if (ws) ws.remove();

    const titleInfo = (isFirstMessage && text) ? { sid: sessionId, userMsg: text } : null;
    syncTeamFromText(text);
    renderComposerIdentity();

    const timestamp = new Date();
    const attachments = [...pendingAttachments];
    addUserMessage(text, timestamp, attachments);

    const loadingEl = addLoadingIndicator();

    chatInput.value = '';
    resetComposerHeight();
    pendingAttachments = [];
    renderAttachmentPreview();
    sendBtn.disabled = true;
    if (typeof resetTurnArtifacts === 'function') resetTurnArtifacts();

    const body = { session_id: sessionId, message: text, stream: true, timestamp: timestamp.toISOString(), lang: currentLang };
    // 说出某人的名字就可以让他们轮到他们。明确发送，因为作曲家
    // 已经知道它是谁写的，并且服务器会重新检查它。
    const addressed = addressedAgentId(text);
    if (addressed) body.speaker_agent_id = addressed;
    if (attachments.length > 0) {
        body.attachments = attachments.map(a => ({
            file_path: a.file_path,
            file_name: a.file_name,
            file_type: a.file_type,
            file_count: a.file_count,
        }));
    }

    const MAX_RETRIES = 2;
    const RETRY_DELAY_MS = 1000;

    function postWithRetry(attempt) {
        fetch('/message', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'success') {
                rememberLiveSpeaker(data);
                setLoadingSpeaker(loadingEl, data.request_id);
                if (data.inline_reply) {
                    // 同步处理通道（例如/取消快速路径）；
                    // 渲染为机器人气泡并完全跳过 SSE。
                    loadingEl.remove();
                    addBotMessage(data.inline_reply, new Date());
                } else if (data.stream) {
                    setSendBtnCancelMode(data.request_id);
                    startSSE(data.request_id, loadingEl, timestamp, titleInfo);
                } else {
                    loadingContainers[data.request_id] = loadingEl;
                }
            } else {
                loadingEl.remove();
                addBotMessage(t('error_send'), new Date());
                resetSendBtnSendMode();
            }
        })
        .catch(err => {
            if (err.name === 'AbortError') {
                loadingEl.remove();
                addBotMessage(t('error_timeout'), new Date());
                resetSendBtnSendMode();
                return;
            }
            if (attempt < MAX_RETRIES) {
                console.warn(`[sendMessage] attempt ${attempt + 1} failed, retrying...`, err);
                setTimeout(() => postWithRetry(attempt + 1), RETRY_DELAY_MS * (attempt + 1));
                return;
            }
            loadingEl.remove();
            addBotMessage(t('error_send'), new Date());
            resetSendBtnSendMode();
        });
    }

    postWithRetry(0);
}

function startSSE(requestId, loadingEl, timestamp, titleInfo, replayItems) {
    let botEl = null;
    let stepsEl = null;    // .agent-steps（思路总结+工具指标）
    let contentEl = null;  // .answer-content（最终流答案）
    let mediaEl = null;    // .media-content（图像和文件附件）
    let accumulatedText = '';
    const toolElements = new Map();
    let currentReasoningEl = null;  // 现场推理泡沫
    let reasoningText = '';
    let reasoningStartTime = 0;
    let done = false;
    let mainDone = false;
    let completedBotSeq = null;
    let cancelled = false;
    let lastSeq = 0;

    // 当工具仍标记为运行中（取消、删除）时，流可以结束
    // 连接）。解决掉它们，这样就不会永远旋转。
    function settlePendingTools() {
        toolElements.forEach(el => {
            el.classList.remove('tool-streaming');
            const icon = el.querySelector('.tool-icon');
            if (icon) icon.className = 'fas fa-minus text-slate-400 flex-shrink-0 tool-icon';
        });
        toolElements.clear();
    }

    // 该流所属的会话。会话并行运行：用户
    // 当这个会话仍在流式传输时，可能会切换到另一个会话。的
    // 流继续在后台运行（因此回复仍然完成并且
    // 持续存在）；当在国外时，它不会触及视图，但仍然记录
    // 每个事件都放入缓冲区，因此返回会话可以重建
    // 通过重播缓冲区来冒泡，然后恢复实时渲染。
    const ownerSession = sessionId;
    const ownerAgent = activeAgentId;
    const ownerKey = runtimeSessionKey(ownerSession, ownerAgent);
    const isActive = () => ownerSession === sessionId && ownerAgent === activeAgentId;
    sessionActiveRequest[ownerKey] = requestId;
    updateEditButtonsState();
    // 每个请求事件缓冲区用于在重新附加时重建气泡。
    const buffer = streamBuffers[requestId] || { items: [], timestamp };
    streamBuffers[requestId] = buffer;
    const clearOwnerRequest = () => {
        if (sessionActiveRequest[ownerKey] === requestId) {
            delete sessionActiveRequest[ownerKey];
            updateEditButtonsState();
        }
        delete streamBuffers[requestId];
    };

    const MAX_RECONNECTS = 10;
    const RECONNECT_BASE_MS = 1000;
    let reconnectCount = 0;

    function ensureBotEl() {
        if (botEl) return;
        if (loadingEl) { loadingEl.remove(); loadingEl = null; }
        botEl = document.createElement('div');
        botEl.className = 'flex gap-3 px-4 sm:px-6 py-3 bot-message-group';
        botEl.dataset.requestId = requestId;
        // 重新生成按钮开始隐藏；它在“完成”中揭示
        // 一旦 seq 元数据从后端到达，事件处理程序。
        // 流媒体面孔是回答此请求的人：被寻址的人
        // 如果被指定为队友，则为对话中自己的特工。包裹着
        // 在 .bot-face 中，因此稍后的头像更改会像任何气泡一样重新绘制它。
        const speaker = liveSpeakerAgent(requestId);
        if (speaker && speaker.id) botEl.dataset.speakerAgent = speaker.id;
        // 在一个组中，气泡在流动时会标有其作者，
        // 正如重播的历史记录所显示的那样——单独聊天保持未标记状态。
        const speakerName = (sharedConversation() && speaker)
            ? `<div class="bot-speaker">${escapeHtml(speaker.name || speaker.id)}</div>`
            : '';
        botEl.innerHTML = `
            <span class="bot-face">${agentAvatarHTML(speaker, 32)}</span>
            <div class="min-w-0 flex-1 max-w-[85%]">
                ${speakerName}
                <div class="bg-white dark:bg-[#1A1A1A] border border-slate-200 dark:border-white/10 rounded-2xl px-4 py-3 text-sm leading-relaxed msg-content text-slate-700 dark:text-slate-200">
                    <div class="agent-steps"></div>
                    <div class="answer-content sse-streaming"></div>
                    <div class="media-content"></div>
                    <div class="bot-audio-slot"></div>
                </div>
                <div class="flex items-center gap-2 mt-1.5">
                    <span class="text-xs text-slate-400 dark:text-slate-500">${formatTime(timestamp)}</span>
                    <button class="copy-msg-btn text-xs text-slate-300 dark:text-slate-600 hover:text-slate-500 dark:hover:text-slate-400 transition-colors cursor-pointer" title="${currentLang === 'zh' ? '复制' : 'Copy'}" style="display:none">
                        <i class="fas fa-copy"></i>
                    </button>
                    <button class="speak-msg-btn text-xs text-slate-300 dark:text-slate-600 hover:text-slate-500 dark:hover:text-slate-400 transition-colors cursor-pointer" title="${t('speak_msg')}" style="display:none;">
                        <i class="fas fa-volume-up"></i>
                    </button>
                    <button class="regenerate-msg-btn text-xs text-slate-300 dark:text-slate-600 hover:text-primary-400 dark:hover:text-primary-400 transition-colors cursor-pointer" title="${t('regenerate_response')}" style="display:none;">
                        <i class="fas fa-rotate-right"></i>
                    </button>
                </div>
            </div>
        `;
        messagesDiv.appendChild(botEl);
        stepsEl = botEl.querySelector('.agent-steps');
        contentEl = botEl.querySelector('.answer-content');
        mediaEl = botEl.querySelector('.media-content');
    }

    // 保存实时 EventSource，以便终端事件（完成/voice_attach/错误）
    // 可以关闭它。重播期间没有实时连接（空）。
    let currentEs = null;

    // 将一个 SSE 事件渲染到气泡中。由现场处理程序和
    // 重新附加重播类似，因此两条路径都会产生相同的 UI。
    function processSSEItem(item) {
            if (item.type === 'reasoning') {
                ensureBotEl();
                reasoningText += item.content;
                if (!currentReasoningEl) {
                    reasoningStartTime = Date.now();
                    currentReasoningEl = document.createElement('div');
                    currentReasoningEl.className = 'agent-step agent-thinking-step';
                    // 在流式传输期间，使用带有单个文本节点的 <pre> 并
                    // 仅附加更新。这避免了重新解析 markdown 和
                    // 在每个块上重新设置innerHTML，这就是导致
                    // 页面会因长长的思维链而崩溃。
                    currentReasoningEl.innerHTML = `
                        <div class="thinking-header" onclick="this.parentElement.classList.toggle('expanded')">
                            <i class="fas fa-lightbulb text-amber-400 flex-shrink-0"></i>
                            <span class="thinking-summary">${t('thinking_in_progress')}</span>
                            <i class="fas fa-chevron-right thinking-chevron"></i>
                        </div>
                        <div class="thinking-full"><pre class="thinking-stream-pre"></pre></div>`;
                    stepsEl.appendChild(currentReasoningEl);
                    const preEl = currentReasoningEl.querySelector('.thinking-stream-pre');
                    preEl.appendChild(document.createTextNode(''));
                    currentReasoningEl._streamTextNode = preEl.firstChild;
                    currentReasoningEl._streamPendingText = '';
                    currentReasoningEl._streamRafScheduled = false;
                    currentReasoningEl._streamCharsRendered = 0;
                    currentReasoningEl._streamCapped = false;
                }
                // 硬上限：一旦 REASONING_RENDER_CAP 字符出现在 DOM 中，就停止
                // 附加更多增量。全文仍保存在
                // `reasoningText` 用于最终确定时间头+尾渲染。
                if (!currentReasoningEl._streamCapped) {
                    currentReasoningEl._streamPendingText += item.content;
                    if (!currentReasoningEl._streamRafScheduled) {
                        currentReasoningEl._streamRafScheduled = true;
                        const elRef = currentReasoningEl;
                        requestAnimationFrame(() => {
                            elRef._streamRafScheduled = false;
                            if (!elRef.isConnected || !elRef._streamTextNode) return;
                            let pending = elRef._streamPendingText;
                            elRef._streamPendingText = '';
                            if (!pending) return;
                            const remaining = REASONING_RENDER_CAP - elRef._streamCharsRendered;
                            if (remaining <= 0) {
                                elRef._streamCapped = true;
                            } else {
                                if (pending.length > remaining) {
                                    pending = pending.slice(0, remaining);
                                    elRef._streamCapped = true;
                                }
                                elRef._streamTextNode.appendData(pending);
                                elRef._streamCharsRendered += pending.length;
                                if (elRef._streamCapped) {
                                    elRef._streamTextNode.appendData(
                                        '\n\n... [reasoning truncated for display] ...'
                                    );
                                }
                            }
                            scrollChatToBottom();
                        });
                    }
                }

            } else if (item.type === 'delta') {
                ensureBotEl();
                if (currentReasoningEl) {
                    finalizeThinking(currentReasoningEl, reasoningStartTime, reasoningText);
                    currentReasoningEl = null;
                    reasoningText = '';
                }
                accumulatedText += item.content;
                contentEl.innerHTML = renderMarkdown(accumulatedText);
                scrollChatToBottom();

            } else if (item.type === 'message_end') {
                if (item.has_tool_calls && accumulatedText.trim()) {
                    ensureBotEl();
                    const frozenEl = document.createElement('div');
                    frozenEl.className = 'agent-step agent-content-step';
                    frozenEl.innerHTML = `<div class="agent-content-body">${renderMarkdown(accumulatedText.trim())}</div>`;
                    stepsEl.appendChild(frozenEl);
                    accumulatedText = '';
                    contentEl.innerHTML = '';
                    scrollChatToBottom();
                }

            } else if (item.type === 'tool_start') {
                ensureBotEl();
                if (currentReasoningEl) {
                    finalizeThinking(currentReasoningEl, reasoningStartTime, reasoningText);
                    currentReasoningEl = null;
                    reasoningText = '';
                }
                accumulatedText = '';
                contentEl.innerHTML = '';

                // 添加工具执行指示器（可折叠）
                const toolEl = document.createElement('div');
                toolEl.className = 'agent-step agent-tool-step tool-streaming';
                toolEl.dataset.progressReceived = 'false';
                const argsStr = formatToolArgs(item.arguments || {});
                toolEl.innerHTML = `
                    <div class="tool-header" onclick="this.parentElement.classList.toggle('expanded')">
                        <i class="fas fa-cog fa-spin text-primary-400 flex-shrink-0 tool-icon"></i>
                        <span class="tool-name">${item.tool}</span>
                        <span class="tool-substep-count"></span>
                        <i class="fas fa-chevron-right tool-chevron"></i>
                    </div>
                    <div class="tool-detail">
                        <div class="tool-detail-section">
                            <div class="tool-detail-label">Input</div>
                            <pre class="tool-detail-content">${argsStr}</pre>
                        </div>
                        <div class="tool-detail-section tool-substeps-section hidden">
                            <div class="tool-detail-label">Steps</div>
                            <div class="tool-substeps"></div>
                        </div>
                        <div class="tool-detail-section tool-output-section">
                            <div class="tool-detail-label tool-output-label">Output</div>
                            <pre class="tool-detail-content tool-live-output"></pre>
                            <div class="tool-display-output"></div>
                        </div>
                    </div>`;
                stepsEl.appendChild(toolEl);
                toolElements.set(item.tool_call_id, toolEl);

                scrollChatToBottom();

            } else if (item.type === 'tool_progress') {
                const toolEl = toolElements.get(item.tool_call_id);
                if (toolEl) {
                    if (toolEl.dataset.progressReceived !== 'true') {
                        toolEl.classList.add('expanded');
                        toolEl.dataset.progressReceived = 'true';
                    }
                    toolEl.querySelector('.tool-live-output').textContent = String(item.content || '');
                    scrollChatToBottom();
                }

            } else if (item.type === 'tool_end') {
                const toolEl = toolElements.get(item.tool_call_id);
                if (toolEl) {
                    const isError = item.status !== 'success';
                    const icon = toolEl.querySelector('.tool-icon');
                    icon.className = isError
                        ? 'fas fa-times text-red-400 flex-shrink-0 tool-icon'
                        : 'fas fa-check text-primary-400 flex-shrink-0 tool-icon';

                    // 显示执行时间
                    const nameEl = toolEl.querySelector('.tool-name');
                    if (item.execution_time !== undefined) {
                        nameEl.innerHTML += ` <span class="tool-time">${item.execution_time}s</span>`;
                    }

                    // 填充输出部分。一个为以下内容编写结果的工具
                    // person (item.display) 被渲染为 markdown；原始的
                    // 结果是模型读取并保持隐藏的内容。
                    const outputLabel = toolEl.querySelector('.tool-output-label');
                    const outputEl = toolEl.querySelector('.tool-live-output');
                    const displayEl = toolEl.querySelector('.tool-display-output');
                    if (outputLabel) outputLabel.textContent = isError ? 'Error' : 'Output';
                    if (displayEl && item.display) {
                        displayEl.innerHTML = renderMarkdown(String(item.display));
                        displayEl.classList.add('has-content');
                        if (outputEl) outputEl.textContent = '';
                    } else if (outputEl) {
                        outputEl.textContent = item.result ? String(item.result) : '';
                        outputEl.classList.toggle('tool-error-text', isError);
                    }

                    toolEl.classList.remove('tool-streaming');
                    // 工具一旦完成就会崩溃；他们的输出是
                    // 踪迹。一种写东西供人阅读的工具
                    // 保持开放——读者只是等待。
                    toolEl.classList.toggle('expanded', !!item.display);
                    if (!item.result && !item.display) {
                        const outputSection = toolEl.querySelector('.tool-output-section');
                        if (outputSection) outputSection.remove();
                    }
                    if (isError) toolEl.classList.add('tool-failed');
                    // 权限拒绝不是普通的失败：表面上
                    // 一键提升此会话的权限而不是
                    // 让用户解码模型的错误文本。
                    if (item.permission_denied) {
                        _appendPermissionDeniedHint(toolEl, item.permission_mode);
                    }
                    toolElements.delete(item.tool_call_id);
                }

            } else if (item.type === 'subagent_step') {
                // 在子代理内部进行的工具调用，在该子代理下呈现
                // 代理卡，因此其工作记录可追踪。
                renderSubagentStep(toolElements.get(item.card_id), item);
                scrollChatToBottom();

            } else if (item.type === 'image') {
                ensureBotEl();
                const imgEl = document.createElement('img');
                imgEl.src = item.content;
                imgEl.alt = 'screenshot';
                imgEl.style.cssText = 'max-width:600px;border-radius:8px;margin:8px 0;cursor:zoom-in;box-shadow:0 1px 4px rgba(0,0,0,0.1);';
                imgEl.onclick = () => _openImageLightbox(imgEl.src);
                mediaEl.appendChild(imgEl);
                scrollChatToBottom();

            } else if (item.type === 'text') {
                // 在媒体项目之前发送的中间文本；显示它但保持 SSE 打开。
                ensureBotEl();
                contentEl.classList.remove('sse-streaming');
                const textContent = item.content || accumulatedText;
                if (textContent) contentEl.innerHTML = renderMarkdown(textContent);
                applyHighlighting(botEl);
                scrollChatToBottom();

            } else if (item.type === 'video') {
                ensureBotEl();
                const wrapper = document.createElement('div');
                wrapper.innerHTML = _buildVideoHtml(item.content);
                mediaEl.appendChild(wrapper.firstElementChild || wrapper);
                scrollChatToBottom();

            } else if (item.type === 'file') {
                ensureBotEl();
                const fileName = item.file_name || item.content.split('/').pop();
                const fileEl = document.createElement('a');
                fileEl.href = item.content;
                fileEl.download = fileName;
                fileEl.target = '_blank';
                fileEl.className = 'file-attachment';
                fileEl.style.cssText = 'display:inline-flex;align-items:center;gap:6px;padding:8px 14px;margin:8px 0;border-radius:8px;background:var(--bg-secondary,#f3f4f6);color:var(--text-primary,#374151);text-decoration:none;font-size:14px;border:1px solid var(--border-color,#e5e7eb);';
                fileEl.innerHTML = `<i class="fas fa-file-download" style="color:#6b7280;"></i> ${fileName}`;
                mediaEl.appendChild(fileEl);
                scrollChatToBottom();

            } else if (item.type === 'artifact') {
                // 代理编写的面向用户的文件；渲染一张卡片并让
                // 工作区面板决定是否自动打开它（workspace.js）。
                ensureBotEl();
                if (typeof appendArtifactCard === 'function') {
                    appendArtifactCard(mediaEl, item);
                }
                scrollChatToBottom();

            } else if (item.type === 'phase') {
                // 粗略进度（例如，cow install-browser）；不得关闭 SSE（与“完成”不同）
                ensureBotEl();
                const wrap = document.createElement('div');
                wrap.className = 'text-xs sm:text-sm text-slate-600 dark:text-slate-400 border-l-2 border-primary-400 pl-2 py-1 my-0.5';
                wrap.textContent = String(item.content || '');
                stepsEl.appendChild(wrap);
                scrollChatToBottom();

            } else if (item.type === 'cancelled') {
                // 特工确认停车；标记气泡。尾随一个
                // “完成”仍然带有部分答案。
                cancelled = true;
                ensureBotEl();
                if (currentReasoningEl) {
                    finalizeThinking(currentReasoningEl, reasoningStartTime, reasoningText);
                    currentReasoningEl = null;
                    reasoningText = '';
                }
                if (!botEl.querySelector('.agent-cancelled-tag')) {
                    const tag = document.createElement('div');
                    tag.className = 'agent-cancelled-tag text-xs text-amber-600 dark:text-amber-400 mt-1';
                    tag.textContent = (currentLang === 'zh') ? '已中止' : 'Cancelled';
                    stepsEl.appendChild(tag);
                }
                resetSendBtnSendMode();

            } else if (item.type === 'done') {
                // 答案仍然存在，但异步附件可能仍然
                // 跟随。只有stream_end关闭请求生命周期。
                mainDone = true;
                if (item.bot_seq !== undefined && item.bot_seq !== null) {
                    completedBotSeq = item.bot_seq;
                }
                settlePendingTools();
                resetSendBtnSendMode();

                const finalTextRaw = item.content || accumulatedText;
                const finalText = localizeCancelMarker(finalTextRaw);

                if (!botEl && finalText) {
                    if (loadingEl) { loadingEl.remove(); loadingEl = null; }
                    addBotMessage(finalText, new Date((item.timestamp || Date.now() / 1000) * 1000), requestId);
                } else if (botEl) {
                    contentEl.classList.remove('sse-streaming');
                    if (finalText) contentEl.innerHTML = renderMarkdown(finalText);
                    contentEl.dataset.rawMd = finalTextRaw || '';
                    const copyBtn = botEl.querySelector('.copy-msg-btn');
                    if (copyBtn && finalText) copyBtn.style.display = '';
                    applyHighlighting(botEl);
                }

                // 回填 seq 元数据，以便编辑/重新生成按钮可以调用
                // 无需刷新页面即可删除 API。后端包括
                // 持久化后完成事件上的 user_seq / bot_seq。
                const targetBotEl = botEl || (requestId ? messagesDiv.querySelector(`[data-request-id="${requestId}"]`) : null);
                if (targetBotEl) {
                    if (item.bot_seq !== undefined && item.bot_seq !== null) {
                        targetBotEl.dataset.seq = item.bot_seq;
                    }
                    // 现在序列已连接，显示重新生成按钮。
                    const regenBtn = targetBotEl.querySelector('.regenerate-msg-btn');
                    if (regenBtn) regenBtn.style.display = '';
                    if (item.user_seq !== undefined && item.user_seq !== null) {
                        // 找到本回合的前一个用户气泡。
                        let prev = targetBotEl.previousElementSibling;
                        while (prev && !prev.classList.contains('user-message-group')) {
                            prev = prev.previousElementSibling;
                        }
                        if (prev && !prev.dataset.seq) {
                            prev.dataset.seq = item.user_seq;
                        }
                    }
                }
                renderBotSpeakerButton(botEl, finalText);
                scrollChatToBottom();

                if (typeof maybeAutoOpenArtifact === 'function') maybeAutoOpenArtifact();

                if (titleInfo) {
                    generateSessionTitle(titleInfo.sid, titleInfo.userMsg, '');
                    titleInfo = null;
                } else if (sessionPanelOpen) {
                    loadSessionList();
                }

            } else if (item.type === 'voice_attach') {
                // TTS 完成 — 将可播放的音频元素附加到
                // 持续存在的机器人泡沫。如果历史记录在一段时间后仍在加载
                // 会话切换，保留附件，直到气泡存在。
                if (item.url && completedBotSeq !== null) {
                    rememberPendingVoiceAttachment(
                        ownerSession, completedBotSeq, item.url
                    );
                    flushPendingVoiceAttachments(ownerSession, true);
                }

            } else if (item.type === 'stream_end') {
                done = true;
                if (currentEs) { currentEs.close(); }
                delete activeStreams[requestId];
                clearOwnerRequest();

            } else if (item.type === 'resync_required') {
                done = true;
                settlePendingTools();
                if (currentEs) { currentEs.close(); }
                delete activeStreams[requestId];
                clearOwnerRequest();
                resetSendBtnSendMode();
                if (isActive()) {
                    messagesDiv.innerHTML = '';
                    historyPage = 0;
                    historyHasMore = false;
                    historyLoading = false;
                    loadHistory(1);
                }

            } else if (item.type === 'error') {
                done = true;
                settlePendingTools();
                if (currentEs) { currentEs.close(); }
                delete activeStreams[requestId];
                clearOwnerRequest();
                if (loadingEl) { loadingEl.remove(); loadingEl = null; }
                // 停止后，流预计结束；泡沫是
                // already tagged "已中止", so don't stack a failure on top.
                if (!cancelled) addBotMessage(t('error_send'), new Date());
                resetSendBtnSendMode();
            }
    }

    function connect() {
        const es = new EventSource(
            `/stream?request_id=${encodeURIComponent(requestId)}`
            + `&after_seq=${lastSeq}`
        );
        currentEs = es;
        activeStreams[requestId] = es;

        es.onmessage = function(e) {
            let item;
            try { item = JSON.parse(e.data); } catch (_) { return; }

            const seq = Number(item.seq || 0);
            if (seq && seq <= lastSeq) return;

            // 成功接收数据，重置重新连接计数器
            reconnectCount = 0;

            // 记录每个事件以便重新附加重播（上限以避免
            // 在很长的流上无限增长）。
            if (item.type === 'tool_progress' && item.tool_call_id) {
                const previousIndex = buffer.items.findIndex(
                    buffered => buffered.type === 'tool_progress'
                        && buffered.tool_call_id === item.tool_call_id
                );
                if (previousIndex >= 0) buffer.items.splice(previousIndex, 1);
            }
            if (buffer.items.length < 5000) buffer.items.push(item);
            if (seq) lastSeq = seq;

            // done 在发布之前会被持久化。记住那个状态
            // 即使此会话处于后台，渲染
            // 是故意跳过的。通知前台和
            // 后台会话，在下面的渲染守卫之前。
            if (item.type === 'done') {
                mainDone = true;
                if (item.bot_seq !== undefined && item.bot_seq !== null) {
                    completedBotSeq = item.bot_seq;
                }
                notifyTaskFinished(ownerSession, 'done', item.content);
            } else if (item.type === 'error') {
                if (!cancelled) notifyTaskFinished(ownerSession, 'error', '');
            } else if (
                item.type === 'voice_attach'
                && item.url
                && completedBotSeq !== null
            ) {
                // 后台会话跳过下面的渲染。保存他们的
                // 附件，以便当用户返回时 loadHistory 可以挂载它。
                rememberPendingVoiceAttachment(
                    ownerSession, completedBotSeq, item.url
                );
            }

            // 后台会话：保持流处于活动状态以便回复完成
            // 并持续存在，但跳过渲染到现在的外部视图中。的
            // 上面的缓冲区仍然增长，因此返回会话可以重建
            // 气泡并恢复实时渲染。
            if (ownerSession !== sessionId) {
                if (item.type === 'stream_end' || item.type === 'error' || item.type === 'resync_required') {
                    done = true;
                    es.close();
                    delete activeStreams[requestId];
                    clearOwnerRequest();
                }
                return;
            }

            processSSEItem(item);
        };

        es.onerror = function() {
            es.close();
            delete activeStreams[requestId];

            if (done) {
                // Stream_end 或不可恢复的事件已将其关闭。
                return;
            }

            if (cancelled && !mainDone) {
                // 用户停止了运行，因此此处结束的流是
                // 预期结果。重新连接只会进入队列
                // 后端已经回收了。
                settlePendingTools();
                clearOwnerRequest();
                if (loadingEl) { loadingEl.remove(); loadingEl = null; }
                if (contentEl) contentEl.classList.remove('sse-streaming');
                resetSendBtnSendMode();
                return;
            }

            if (currentReasoningEl) {
                finalizeThinking(currentReasoningEl, reasoningStartTime, reasoningText);
                currentReasoningEl = null;
                reasoningText = '';
            }

            if (reconnectCount < MAX_RECONNECTS) {
                reconnectCount++;
                const delay = Math.min(RECONNECT_BASE_MS * reconnectCount, 5000);
                console.warn(`[SSE] connection lost for ${requestId}, reconnecting in ${delay}ms (attempt ${reconnectCount}/${MAX_RECONNECTS})`);
                setTimeout(connect, delay);
                return;
            }

            // 精疲力竭的重试。只在拥有者的视角中揭示失败——
            // 后台会话不得改变当前显示的聊天。
            clearOwnerRequest();
            settlePendingTools();
            if (!isActive()) return;
            if (loadingEl) { loadingEl.remove(); loadingEl = null; }
            if (!botEl) {
                addBotMessage(t('error_send'), new Date());
            } else if (accumulatedText) {
                contentEl.classList.remove('sse-streaming');
                contentEl.innerHTML = renderMarkdown(accumulatedText);
                applyHighlighting(botEl);
            }
            resetSendBtnSendMode();
        };
    }

    // 重新附加重播：从缓冲事件（快照、
    // 在连接实时尾部之前，没有动画）。 `processSSEItem`
    // 与实时 onmessage 处理程序使用的渲染器相同，因此
    // 快照与实时渲染所产生的效果完全匹配。
    if (replayItems && replayItems.length) {
        for (const item of replayItems) {
            const seq = Number(item.seq || 0);
            if (seq > lastSeq) lastSeq = seq;
            try { processSSEItem(item); } catch (_) {}
            if (item.type === 'stream_end' || item.type === 'error' || item.type === 'resync_required') {
                done = true;
            }
        }
        // 如果缓冲流已经完成，则不要重新连接 -
        // 回复已完成并持续；显示其最终状态并停止。
        if (done) {
            clearOwnerRequest();
            resetSendBtnSendMode();
            scrollChatToBottom(true);
            return;
        }
    }

    connect();
}

function startPolling() {
    const gen = ++pollGeneration;
    isPolling = true;
    let pollInFlight = false;

    function poll() {
        if (gen !== pollGeneration) return;
        if (pollInFlight) return;
        // 隐藏时保持轮询：推送消息正是
        // 下面的通知应发送到后台选项卡。
        pollInFlight = true;
        fetch('/poll', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: sessionId })
        })
        .then(r => r.json())
        .then(data => {
            pollInFlight = false;
            if (gen !== pollGeneration) return;
            if (data.status === 'success' && data.has_content) {
                const rid = data.request_id;
                if (loadingContainers[rid]) {
                    loadingContainers[rid].remove();
                    delete loadingContainers[rid];
                }
                // 如果此回复已在屏幕上，则跳过。回复时发生
                // 通过 SSE 流和轮询队列到达（例如
                // 用户在运行中途切换离开，将排队的回复保留为
                // 返回时重新获取）——仅渲染一次。
                const already = rid && messagesDiv.querySelector(
                    `[data-request-id="${rid}"]`
                );
                if (!already) {
                    const welcomeScreen = document.getElementById('welcome-screen');
                    if (welcomeScreen) welcomeScreen.remove();
                    addBotMessage(data.content, new Date(data.timestamp * 1000), rid);
                    scrollChatToBottom();
                    // 推送消息（调度结果、错过回复）：显示
                    // 内容本身，与桌面推送通知相匹配。
                    showTaskNotification(
                        sessionTitleOf(sessionId) || 'CowAgent',
                        firstLineSnippet(data.content),
                        sessionId
                    );
                }
            }
            const delay = (data.status === 'success' && data.has_content) ? 5000 : 10000;
            setTimeout(poll, delay);
        })
        .catch(() => { pollInFlight = false; setTimeout(poll, 10000); });
    }
    poll();
}

// 后端附加到提示的附件标记，由标签键入
// 发出（请参阅 web_channel.post_message 中的workspace_ref 分支）。历史
// 只保留提示文本，因此这是返回芯片的唯一方法。
const ATTACHMENT_MARKER_TYPES = {
    '工作空间文件': 'workspace_ref', '工作空间檔案': 'workspace_ref', 'Workspace file': 'workspace_ref',
    '工作空间目录': 'workspace_dir', '工作空间目錄': 'workspace_dir', 'Workspace directory': 'workspace_dir',
    '图片': 'image', '圖片': 'image', 'Image': 'image',
    '视频': 'video', '影片': 'video', 'Video': 'video',
    '目录': 'directory', '目錄': 'directory', 'Directory': 'directory',
    '文件': 'file', '檔案': 'file', 'File': 'file',
};

/**
 * Split trailing `[label: path]` lines off a persisted user message.
 * Returns the remaining text plus the attachments they describe.
 */
function parseAttachmentMarkers(content) {
    const lines = (content || '').split('\n');
    const found = [];
    while (lines.length) {
        const line = lines[lines.length - 1].trim();
        if (!line) { lines.pop(); continue; }
        const m = line.match(/^\[([^\]:]+):\s*(.+)\]$/);
        const type = m && ATTACHMENT_MARKER_TYPES[m[1].trim()];
        if (!type) break;
        found.unshift({ type, path: m[2].trim() });
        lines.pop();
    }
    if (!found.length) return { text: content, attachments: null };
    return {
        text: lines.join('\n').trimEnd(),
        attachments: found.map(f => ({
            file_path: f.path,
            file_name: f.path.split(/[\\/]/).filter(Boolean).pop() || f.path,
            file_type: f.type === 'workspace_dir' ? 'workspace_ref' : f.type,
            is_dir: f.type === 'workspace_dir' || f.type === 'directory',
        })),
    };
}

function createUserMessageEl(content, timestamp, attachments) {
    const el = document.createElement('div');
    el.className = 'flex justify-end px-4 sm:px-6 py-3 user-message-group';

    // 回放历史：从文本中留下的标记中恢复碎片。
    if (!attachments) {
        const parsed = parseAttachmentMarkers(content);
        if (parsed.attachments) {
            attachments = parsed.attachments;
            content = parsed.text;
        }
    }

    let attachHtml = '';
    if (attachments && attachments.length > 0) {
        const items = attachments.map(a => {
            if (a.file_type === 'image') {
                // 历史重播从提示标记中恢复附件，这
                // 仅携带本地 file_path — 通过 /api/file 路由它。
                const src = (a.preview_url || _toWebUrl(a.file_path || '')).replace(/"/g, '&quot;');
                return `<img src="${src}" alt="${escapeHtml(a.file_name)}" class="user-msg-image" onclick="_openImageLightbox(this.src)">`;
            }
            const icon = a.file_type === 'video'
                ? 'fa-film'
                : (a.file_type === 'directory' ? 'fa-folder-tree'
                : (a.is_dir ? 'fa-folder' : 'fa-file-alt'));
            const suffix = a.file_type === 'directory' && a.file_count
                ? ` (${a.file_count})`
                : '';
            // 工作区引用在预览面板中保持可打开状态。
            const openable = a.file_type === 'workspace_ref'
                ? ` data-ws-open="${escapeHtml(a.file_path)}" title="${escapeHtml(a.file_path)}"`
                : '';
            return `<div class="user-msg-file${openable ? ' is-openable' : ''}"${openable}>` +
                `<i class="fas ${icon}"></i> ${escapeHtml(a.file_name)}${suffix}</div>`;
        }).join('');
        attachHtml = `<div class="user-msg-attachments">${items}</div>`;
    }

    const textHtml = content ? renderMarkdown(content) : '';
    el.innerHTML = `
        <div class="max-w-[75%] sm:max-w-[60%]">
            <div class="bg-primary-400 text-white rounded-2xl px-4 py-2.5 text-sm leading-relaxed msg-content user-bubble">
                ${attachHtml}${textHtml}
            </div>
            <div class="flex items-center justify-end gap-2 mt-1.5">
                <button class="edit-msg-btn text-xs text-slate-300 dark:text-slate-600 hover:text-primary-400 dark:hover:text-primary-400 transition-colors cursor-pointer" title="${t('edit_message')}">
                    <i class="fas fa-pen-to-square"></i>
                </button>
                <button class="delete-msg-btn text-xs text-slate-300 dark:text-slate-600 hover:text-red-500 dark:hover:text-red-400 transition-colors cursor-pointer" title="${t('delete_message_title')}">
                    <i class="fas fa-trash"></i>
                </button>
                <span class="text-xs text-slate-400 dark:text-slate-500">${formatTime(timestamp)}</span>
            </div>
        </div>
    `;
    // 存储原始内容以供编辑
    el.dataset.rawContent = content || '';
    highlightMentions(el.querySelector('.msg-content'));
    return el;
}

function renderToolCallsHtml(toolCalls) {
    if (!toolCalls || toolCalls.length === 0) return '';
    return toolCalls.map(tc => {
        const argsStr = formatToolArgs(tc.arguments || {});
        const resultStr = tc.result ? escapeHtml(String(tc.result)) : '';
        const hasResult = !!resultStr;
        return `
<div class="agent-step agent-tool-step">
    <div class="tool-header" onclick="this.parentElement.classList.toggle('expanded')">
        <i class="fas fa-check text-primary-400 flex-shrink-0 tool-icon"></i>
        <span class="tool-name">${escapeHtml(tc.name || '')}</span>
        <i class="fas fa-chevron-right tool-chevron"></i>
    </div>
    <div class="tool-detail">
        <div class="tool-detail-section">
            <div class="tool-detail-label">Input</div>
            <pre class="tool-detail-content">${argsStr}</pre>
        </div>
        ${hasResult ? `
        <div class="tool-detail-section tool-output-section">
            <div class="tool-detail-label">Output</div>
            <pre class="tool-detail-content">${resultStr}</pre>
        </div>` : ''}
    </div>
</div>`;
    }).join('');
}

// 用于在气泡中渲染推理内容的上限。超出这个尺寸，
// 我们完全跳过 Markdown 渲染并显示纯文本 head + tail
// 保持页面响应（很长的思想链可以否则
// 当被marked.js重新解析时，浏览器停止或崩溃）。
// 使其与后端 MAX_STORED_REASONING_CHARS 保持同步并且
// MAX_REASONING_STREAM_CHARS 使存储/SSE/显示保持对齐。
const REASONING_RENDER_CAP = 4 * 1024; // 4KB

function _truncateReasoningForDisplay(text) {
    if (!text || text.length <= REASONING_RENDER_CAP) return { text, truncated: false, omitted: 0 };
    const half = Math.floor(REASONING_RENDER_CAP / 2);
    const head = text.slice(0, half);
    const tail = text.slice(-half);
    return {
        text: head + '\n\n... [' + (text.length - head.length - tail.length) + ' chars omitted] ...\n\n' + tail,
        truncated: true,
        omitted: text.length - head.length - tail.length,
    };
}

function _renderReasoningBody(text) {
    // 简单来说，渲染为 markdown。对于长的，回落到
    // 转义的 <pre> 块以避免昂贵的降价解析。
    const { text: shown, truncated } = _truncateReasoningForDisplay(text);
    if (truncated || shown.length > REASONING_RENDER_CAP) {
        return '<pre class="thinking-stream-pre">' + escapeHtml(shown) + '</pre>';
    }
    return renderMarkdown(shown);
}

function finalizeThinking(el, startTime, text) {
    const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
    el.querySelector('.thinking-summary').textContent = t('thinking_done');
    const fullDiv = el.querySelector('.thinking-full');
    fullDiv.innerHTML = `<div class="thinking-duration">${t('thinking_duration')} ${elapsed}s</div>` + _renderReasoningBody(text);
}

function renderThinkingHtml(text) {
    if (!text || !text.trim()) return '';
    const full = text.trim();
    return `
<div class="agent-step agent-thinking-step">
    <div class="thinking-header" onclick="this.parentElement.classList.toggle('expanded')">
        <i class="fas fa-lightbulb text-amber-400 flex-shrink-0"></i>
        <span class="thinking-summary">${t('thinking_done')}</span>
        <i class="fas fa-chevron-right thinking-chevron"></i>
    </div>
    <div class="thinking-full">${_renderReasoningBody(full)}</div>
</div>`;
}

function renderStepsHtml(steps) {
    if (!steps || steps.length === 0) return { stepsHtml: '', finalContent: '' };

    // 找到最后一个内容步骤的索引 - 它成为主要答案，而不是步骤
    let lastContentIdx = -1;
    for (let i = steps.length - 1; i >= 0; i--) {
        if (steps[i].type === 'content') { lastContentIdx = i; break; }
    }

    let html = '';
    let lastContentText = '';
    for (let i = 0; i < steps.length; i++) {
        const step = steps[i];
        if (step.type === 'thinking') {
            html += renderThinkingHtml(step.content);
        } else if (step.type === 'content') {
            if (i === lastContentIdx) {
                lastContentText = step.content;
            } else {
                html += `<div class="agent-step agent-content-step"><div class="agent-content-body">${renderMarkdown(step.content)}</div></div>`;
            }
        } else if (step.type === 'tool') {
            const argsStr = formatToolArgs(step.arguments || {});
            const resultStr = step.result ? escapeHtml(String(step.result)) : '';
            const isErr = step.is_error === true;
            const iconClass = isErr
                ? 'fas fa-times text-red-400 flex-shrink-0 tool-icon'
                : 'fas fa-check text-primary-400 flex-shrink-0 tool-icon';
            // 与直播相同的规则：为以下内容编写结果的工具
            // 一个人展示了这一点，而不是模型提交的表格。
            const outputHtml = step.display
                ? `<div class="tool-display-output has-content">${renderMarkdown(String(step.display))}</div>`
                : (resultStr
                    ? `<pre class="tool-detail-content${isErr ? ' tool-error-text' : ''}">${resultStr}</pre>`
                    : '');
            html += `
<div class="agent-step agent-tool-step${isErr ? ' tool-failed' : ''}">
    <div class="tool-header" onclick="this.parentElement.classList.toggle('expanded')">
        <i class="${iconClass}"></i>
        <span class="tool-name">${escapeHtml(step.name || '')}</span>
        <i class="fas fa-chevron-right tool-chevron"></i>
    </div>
    <div class="tool-detail">
        <div class="tool-detail-section">
            <div class="tool-detail-label">Input</div>
            <pre class="tool-detail-content">${argsStr}</pre>
        </div>
        ${outputHtml ? `
        <div class="tool-detail-section tool-output-section">
            <div class="tool-detail-label">${isErr ? 'Error' : 'Output'}</div>
            ${outputHtml}
        </div>` : ''}
    </div>
</div>`;
            // 如果此工具发送了文件（发送/读取工具），则内联渲染媒体
            // 因此它在页面刷新后仍然存在（不存储仅限 SSE 的文件事件）。
            const mediaHtml = _renderSentFileFromToolResult(step);
            if (mediaHtml) html += mediaHtml;
        }
    }
    return { stepsHtml: html, lastContentText };
}

// 从工具的结果中提取要发送的文件元数据并渲染内联预览。
// 如果结果不是 file_to_send 有效负载，则返回 ''。
function _renderSentFileFromToolResult(step) {
    if (!step || !step.result) return '';
    let payload;
    try {
        payload = typeof step.result === 'string' ? JSON.parse(step.result) : step.result;
    } catch (_) { return ''; }
    if (!payload || payload.type !== 'file_to_send' || !payload.path) return '';
    const webUrl = _toWebUrl(payload.path);
    const fileType = payload.file_type || 'file';
    const fileName = payload.file_name || payload.path.split('/').pop();
    if (fileType === 'image') {
        return `<div class="agent-step">${_buildImageHtml(webUrl)}</div>`;
    }
    if (fileType === 'video') {
        return `<div class="agent-step">${_buildVideoHtml(webUrl)}</div>`;
    }
    return `<div class="agent-step"><a href="${webUrl}" download="${escapeHtml(fileName)}" target="_blank" ` +
        `style="display:inline-flex;align-items:center;gap:6px;padding:8px 14px;margin:8px 0;border-radius:8px;` +
        `background:var(--bg-secondary,#f3f4f6);color:var(--text-primary,#374151);text-decoration:none;font-size:14px;` +
        `border:1px solid var(--border-color,#e5e7eb);">` +
        `<i class="fas fa-file-download" style="color:#6b7280;"></i> ${escapeHtml(fileName)}</a></div>`;
}

// 取消标记的修饰翻译器一直存在于历史中。
// 历史保留了法学硕士的英文规范形式；仅显示被本地化。
function localizeCancelMarker(text) {
    if (!text) return text;
    if (currentLang !== 'zh') return text;
    return text
        .replace(/_\(Cancelled by user\)_/g, '_(用户已中止)_')
        .replace(/_\(Cancelled\)_/g, '_(已中止)_');
}

function createBotMessageEl(content, timestamp, requestId, msg) {
    const el = document.createElement('div');
    el.className = 'flex gap-3 px-4 sm:px-6 py-3 bot-message-group';
    if (requestId) el.dataset.requestId = requestId;

    let stepsHtml = '';
    let displayContent = localizeCancelMarker(content);

    if (msg && msg.steps && msg.steps.length > 0) {
        // 新格式：带有交错内容的有序步骤
        const result = renderStepsHtml(msg.steps);
        stepsHtml = result.stepsHtml;
        // 最终内容（所有步骤后的最后一个文本）是主要答案
        displayContent = content || result.lastContentText;
    } else {
        // 传统格式：单独的工具调用+可选推理
        const toolCalls = msg && msg.tool_calls;
        const reasoning = msg && msg.reasoning;
        stepsHtml = renderThinkingHtml(reasoning) + renderToolCallsHtml(toolCalls);
    }

    // 本轮写入的文件，由历史记录 API (workspace.js) 计算得出。
    const artifactsHtml = typeof renderArtifactCards === 'function'
        ? renderArtifactCards(msg && msg.artifacts)
        : '';

    // 自我进化的气泡会获得一个小徽章，以便用户可以感受到代理
    // 自己学到了一些东西（文本本身保持干净）。历史回放
    // 携带msg.kind；实时推送由evolution_请求id标识。
    const isEvolution = (msg && msg.kind === 'evolution')
        || (typeof requestId === 'string' && requestId.startsWith('evolution_'));
    const evolutionBadge = isEvolution
        ? `<div class="flex items-center gap-1 mb-1.5 text-xs text-slate-400 dark:text-slate-500">
                <i class="fas fa-seedling text-[11px]"></i>
                <span>${t('evolution_badge')}</span>
           </div>`
        : '';

    // 回复的面孔是代理说话的人：其上传的图像，或
    // 默认产品徽标。共同的对话也给泡沫贴上了标签，
    // 因为连续的气泡可能来自不同的代理；单独聊天
    // 保持未标记，但仍反映该特工自己的化身。
    const speaker = botSpeakerAgent(msg, requestId) || findAgent(activeAgentId);
    // 记住谁说话，这样以后的头像变化就可以重新绘制这张脸
    // 无需重新渲染整个气泡。
    if (speaker && speaker.id) el.dataset.speakerAgent = speaker.id;
    const faceHtml = `<span class="bot-face">${agentAvatarHTML(speaker, 32)}</span>`;
    const speakerName = (sharedConversation() && speaker)
        ? `<div class="bot-speaker">${escapeHtml(speaker.name || speaker.id)}</div>`
        : '';

    el.innerHTML = `
        ${faceHtml}
        <div class="min-w-0 flex-1 max-w-[85%]">
            ${speakerName}
            <div class="bg-white dark:bg-[#1A1A1A] border border-slate-200 dark:border-white/10 rounded-2xl px-4 py-3 text-sm leading-relaxed msg-content text-slate-700 dark:text-slate-200">
                ${evolutionBadge}
                ${stepsHtml ? `<div class="agent-steps">${stepsHtml}</div>` : ''}
                <div class="answer-content">${renderMarkdown(displayContent)}</div>
                <div class="media-content">${artifactsHtml}</div>
                <div class="bot-audio-slot"></div>
            </div>
            <div class="flex items-center gap-2 mt-1.5">
                <span class="text-xs text-slate-400 dark:text-slate-500">${formatTime(timestamp)}</span>
                <button class="copy-msg-btn text-xs text-slate-300 dark:text-slate-600 hover:text-slate-500 dark:hover:text-slate-400 transition-colors cursor-pointer" title="${currentLang === 'zh' ? '复制' : 'Copy'}">
                    <i class="fas fa-copy"></i>
                </button>
                <button class="speak-msg-btn text-xs text-slate-300 dark:text-slate-600 hover:text-slate-500 dark:hover:text-slate-400 transition-colors cursor-pointer" title="${t('speak_msg')}" style="display:none;">
                    <i class="fas fa-volume-up"></i>
                </button>
                <button class="regenerate-msg-btn text-xs text-slate-300 dark:text-slate-600 hover:text-primary-400 dark:hover:text-primary-400 transition-colors cursor-pointer" title="${t('regenerate_response')}">
                    <i class="fas fa-rotate-right"></i>
                </button>
            </div>
        </div>
    `;
    el.querySelector('.answer-content').dataset.rawMd = displayContent;
    // 现有 TTS 附件（历史回放）：预先安装播放器。
    const existingAudio = msg && msg.extras && msg.extras.audio && msg.extras.audio.url;
    if (existingAudio) {
        attachAudioToBotBubble(el, existingAudio, { autoplay: false });
    }
    renderBotSpeakerButton(el, displayContent);
    applyHighlighting(el);
    return el;
}

// 在机器人气泡内添加（或替换）一个小型音频播放器
// 专用`.bot-audio-slot`。用于实时 TTS 推送和历史记录
// 重播。无声失败：从不抛出。
function attachAudioToBotBubble(botEl, audioUrl, opts) {
    try {
        if (!botEl || !audioUrl) return;
        const slot = botEl.querySelector('.bot-audio-slot');
        if (!slot) return;
        slot.innerHTML = '';
        slot.style.marginTop = '6px';
        const pill = renderVoicePill(audioUrl, { autoplay: !!(opts && opts.autoplay) });
        slot.appendChild(pill);
        const speakBtn = botEl.querySelector('.speak-msg-btn');
        if (speakBtn) speakBtn.style.display = 'none';
    } catch (_) { /* 沉默的 */ }
}

function pendingVoiceAttachmentKey(sid, botSeq) {
    return `${sid}:${botSeq}`;
}

function rememberPendingVoiceAttachment(sid, botSeq, audioUrl) {
    if (!sid || botSeq === undefined || botSeq === null || !audioUrl) return;
    const key = pendingVoiceAttachmentKey(sid, botSeq);
    const pending = {
        sid,
        botSeq: String(botSeq),
        audioUrl,
        expiresAt: Date.now() + PENDING_VOICE_ATTACH_TTL_MS,
    };
    pendingVoiceAttachments.delete(key);
    pendingVoiceAttachments.set(key, pending);

    while (pendingVoiceAttachments.size > PENDING_VOICE_ATTACH_MAX) {
        pendingVoiceAttachments.delete(pendingVoiceAttachments.keys().next().value);
    }
    setTimeout(() => {
        if (pendingVoiceAttachments.get(key) === pending) {
            pendingVoiceAttachments.delete(key);
        }
    }, PENDING_VOICE_ATTACH_TTL_MS);
}

function flushPendingVoiceAttachments(sid, autoplay) {
    if (!sid || sid !== sessionId) return 0;
    const now = Date.now();
    let attached = 0;
    pendingVoiceAttachments.forEach((pending, key) => {
        if (pending.expiresAt <= now) {
            pendingVoiceAttachments.delete(key);
            return;
        }
        if (pending.sid !== sid) return;
        const botEl = Array.from(
            messagesDiv.querySelectorAll('.bot-message-group[data-seq]')
        ).find(el => el.dataset.seq === pending.botSeq);
        if (!botEl) return;
        attachAudioToBotBubble(botEl, pending.audioUrl, { autoplay: !!autoplay });
        pendingVoiceAttachments.delete(key);
        attached++;
    });
    return attached;
}

// 构建一个紧凑的播放/暂停 + 进度 + 持续时间药丸，将
// 隐藏<音频>。返回根元素；可以安全地嵌入任何地方。
function renderVoicePill(audioUrl, opts) {
    opts = opts || {};
    const wrap = document.createElement('div');
    wrap.className = 'voice-pill';
    wrap.innerHTML = `
        <button type="button" class="voice-pill-btn" data-state="play" aria-label="play">
            <i class="fas fa-play"></i>
        </button>
        <div class="voice-pill-track"><div class="voice-pill-fill"></div></div>
        <span class="voice-pill-time">0:00</span>
        <audio preload="metadata" src="${audioUrl}"></audio>
    `;
    const btn = wrap.querySelector('.voice-pill-btn');
    const fill = wrap.querySelector('.voice-pill-fill');
    const timeEl = wrap.querySelector('.voice-pill-time');
    const audio = wrap.querySelector('audio');

    const fmt = (s) => {
        if (!isFinite(s) || s < 0) s = 0;
        const m = Math.floor(s / 60);
        const r = Math.floor(s % 60);
        return `${m}:${r < 10 ? '0' : ''}${r}`;
    };
    const setIcon = (state) => {
        btn.dataset.state = state;
        btn.querySelector('i').className = state === 'pause' ? 'fas fa-pause' : 'fas fa-play';
        btn.setAttribute('aria-label', state === 'pause' ? 'pause' : 'play');
    };

    audio.addEventListener('loadedmetadata', () => {
        if (audio.duration && isFinite(audio.duration)) timeEl.textContent = fmt(audio.duration);
    });
    audio.addEventListener('timeupdate', () => {
        const dur = audio.duration || 0;
        if (dur > 0) {
            fill.style.width = `${Math.min(100, (audio.currentTime / dur) * 100)}%`;
            timeEl.textContent = fmt(dur - audio.currentTime);
        }
    });
    audio.addEventListener('ended', () => {
        setIcon('play');
        fill.style.width = '0%';
        timeEl.textContent = fmt(audio.duration || 0);
    });
    audio.addEventListener('play',  () => setIcon('pause'));
    audio.addEventListener('pause', () => setIcon('play'));

    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (audio.paused) {
            audio.play().catch(() => {});
        } else {
            audio.pause();
        }
    });

    if (opts.autoplay) {
        // 自动播放可能被浏览器阻止；默默地后退
        // 让用户点击播放按钮。
        const tryPlay = () => audio.play().catch(() => {});
        if (audio.readyState >= 2) tryPlay();
        else audio.addEventListener('canplay', tryPlay, { once: true });
    }
    return wrap;
}

// 配置 TTS 时显示手动“朗读”按钮，但
// bubble 还没有音频。通过 /api/models 延迟探测功能，以便
// 当没有任何东西可以合成语音时，我们不会暴露按钮。
function renderBotSpeakerButton(botEl, text) {
    if (!botEl || !text || !text.trim()) return;
    const btn = botEl.querySelector('.speak-msg-btn');
    if (!btn) return;
    if (botEl.querySelector('.bot-audio-slot audio')) return;
    _isTtsReady().then(ready => {
        if (!ready) return;
        btn.style.display = '';
        btn.onclick = () => _triggerManualTts(btn, botEl, text);
    });
}

let _ttsReadyPromise = null;
let _ttsReadyTs = 0;
function _isTtsReady() {
    // 缓存 30 秒，以避免在每个气泡上敲击 /api/models。
    if (_ttsReadyPromise && Date.now() - _ttsReadyTs < 30000) {
        return _ttsReadyPromise;
    }
    _ttsReadyTs = Date.now();
    _ttsReadyPromise = fetch('/api/models')
        .then(r => r.json())
        .then(data => {
            const tts = data && data.capabilities && data.capabilities.tts;
            if (!tts) return false;
            return Boolean(tts.current_provider || tts.suggested_provider);
        })
        .catch(() => false);
    return _ttsReadyPromise;
}

function _triggerManualTts(btn, botEl, text) {
    if (btn.dataset.busy === '1') return;
    btn.dataset.busy = '1';
    const icon = btn.querySelector('i');
    const prev = icon ? icon.className : '';
    if (icon) icon.className = 'fas fa-spinner fa-spin';
    fetch('/api/voice/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, session_id: sessionId }),
    })
        .then(r => r.json())
        .then(data => {
            if (data && data.status === 'success' && data.audio_url) {
                attachAudioToBotBubble(botEl, data.audio_url, { autoplay: true });
            }
        })
        .catch(() => {})
        .finally(() => {
            btn.dataset.busy = '0';
            if (icon) icon.className = prev || 'fas fa-volume-up';
        });
}

function addUserMessage(content, timestamp, attachments) {
    const el = createUserMessageEl(content, timestamp, attachments);
    messagesDiv.appendChild(el);
    _autoScrollEnabled = true;
    scrollChatToBottom(true);
}

function addBotMessage(content, timestamp, requestId) {
    const el = createBotMessageEl(content, timestamp, requestId);
    messagesDiv.appendChild(el);
    scrollChatToBottom();
}

// 从服务器加载对话历史记录（第 1 页 = 最近的消息）。
// 当用户滚动到顶部时，后续页面会在前面添加较旧的消息。
function loadHistory(page) {
    if (historyLoading) return;
    historyLoading = true;
    const historySessionId = sessionId;

    // 共享对话为每个气泡贴上了作者的标签，并描绘了
    // 右脸。该决议需要本次会议的团队名单 (_sessCfg)，
    // 异步加载；没有它，每个重播的泡沫都会回落
    // 变成主人的头像并失去名字。确保名册在手
    // 在渲染之前，因此重新加载看起来与实时对话完全相同。
    const ready = _sessCfg ? Promise.resolve() : refreshSessionSettings().catch(() => {});

    ready.then(() => fetch(`/api/history?session_id=${encodeURIComponent(historySessionId)}&page=${page}&page_size=20`)
        .then(r => r.json())
        .then(data => {
            // 我们离开后的会话的响应绝不能呈现
            // 进入新会话的消息列表。
            if (historySessionId !== sessionId) return;
            if (data.status !== 'success' || data.messages.length === 0) return;

            const prevScrollHeight = messagesDiv.scrollHeight;
            const isFirstLoad = page === 1;

            // 首次加载时，如果历史记录存在，则删除欢迎屏幕
            if (isFirstLoad) {
                const ws = document.getElementById('welcome-screen');
                if (ws) ws.remove();
            }

            // 按时间顺序构建历史消息元素片段
            const fragment = document.createDocumentFragment();

            if (data.has_more && page > 1) {
                // 将“加载更多”哨兵保持在适当的位置（插入在下面）
            }

            const ctxStartSeq = data.context_start_seq || 0;
            let dividerInserted = false;

            data.messages.forEach(msg => {
                const hasContent = msg.content && msg.content.trim();
                const hasToolCalls = msg.role === 'assistant' && msg.tool_calls && msg.tool_calls.length > 0;
                if (!hasContent && !hasToolCalls) return;

                // 从上方边界过渡到下方边界时插入上下文分隔符
                if (ctxStartSeq > 0 && !dividerInserted && msg._seq !== undefined && msg._seq >= ctxStartSeq) {
                    dividerInserted = true;
                    const divider = document.createElement('div');
                    divider.className = 'context-divider';
                    divider.innerHTML = `<span>${t('context_cleared')}</span>`;
                    fragment.appendChild(divider);
                }

                const ts = new Date(msg.created_at * 1000);
                const el = msg.role === 'user'
                    ? createUserMessageEl(msg.content, ts)
                    : createBotMessageEl(msg.content || '', ts, null, msg);
                // 存储删除功能的序列
                if (msg._seq !== undefined) {
                    el.dataset.seq = msg._seq;
                }
                fragment.appendChild(el);
            });

            // 如果上下文已清除但尚不存在新消息，则在末尾附加分隔符
            if (ctxStartSeq > 0 && !dividerInserted) {
                const divider = document.createElement('div');
                divider.className = 'context-divider';
                divider.innerHTML = `<span>${t('context_cleared')}</span>`;
                fragment.appendChild(divider);
            }

            // 将历史记录添加到任何现有消息之上
            const sentinel = document.getElementById('history-load-more');
            const insertBefore = sentinel ? sentinel.nextSibling : messagesDiv.firstChild;
            messagesDiv.insertBefore(fragment, insertBefore);
            updateEditButtonsState();
            // 后台 voice_attach 可以在此历史记录之前到达
            // 片段创建其目标气泡。现在重试 seq 元数据
            // 存在于 DOM 中；不自动播放延迟的附件。
            if (isFirstLoad) {
                flushPendingVoiceAttachments(historySessionId, false);
            }

            // 管理最顶部的“加载更多”哨兵
            if (data.has_more) {
                if (!document.getElementById('history-load-more')) {
                    const btn = document.createElement('div');
                    btn.id = 'history-load-more';
                    btn.className = 'flex justify-center py-3';
                    btn.innerHTML = `<button class="text-xs text-slate-400 dark:text-slate-500 hover:text-primary-400 transition-colors" onclick="loadHistory(historyPage + 1)">Load earlier messages</button>`;
                    messagesDiv.insertBefore(btn, messagesDiv.firstChild);
                }
            } else {
                const sentinel = document.getElementById('history-load-more');
                if (sentinel) sentinel.remove();
            }

            historyHasMore = data.has_more;
            historyPage = page;

            if (isFirstLoad) {
                // DOM 稳定后滚动到最底部。单个
                // rAF 还不够：markdown/代码高亮/图像不断增长
                // 第一次绘制后的滚动高度，留下最后一个气泡的
                // 时间戳被剪裁。重新固定几次以赶上后期布局。
                requestAnimationFrame(() => scrollChatToBottom(true));
                [120, 350, 700].forEach(d => setTimeout(() => scrollChatToBottom(true), d));
            } else {
                // 恢复滚动位置，以便加载较旧的消息不会跳转视图
                messagesDiv.scrollTop = messagesDiv.scrollHeight - prevScrollHeight;
            }
        })
        .catch(() => {})
        .finally(() => {
            historyLoading = false;
            renderComposerIdentity();
        }));
}

function addLoadingIndicator() {
    const el = document.createElement('div');
    el.className = 'flex gap-3 px-4 sm:px-6 py-3 loading-indicator';
    // 在对话自己的 Agent 上启动； setLoadingSpeaker 交换脸部
    // 一旦服务器说出谁真正轮到了（一位被称呼的队友）。
    el.innerHTML = `
        <span class="bot-face">${agentAvatarHTML(findAgent(activeAgentId), 32)}</span>
        <div class="bg-white dark:bg-[#1A1A1A] border border-slate-200 dark:border-white/10 rounded-2xl px-4 py-3">
            <div class="flex items-center gap-1.5">
                <span class="w-2 h-2 rounded-full bg-primary-400 animate-pulse-dot" style="animation-delay: 0s"></span>
                <span class="w-2 h-2 rounded-full bg-primary-400 animate-pulse-dot" style="animation-delay: 0.2s"></span>
                <span class="w-2 h-2 rounded-full bg-primary-400 animate-pulse-dot" style="animation-delay: 0.4s"></span>
            </div>
        </div>
    `;
    messagesDiv.appendChild(el);
    scrollChatToBottom();
    return el;
}

/* The session-panel "新对话" button. With a single Agent there is nobody to
   选择之间，所以它只是开始聊天。有几个，它会打开一个菜单：选择
   一个代理进行单独聊天，或打开团队选择器进行群聊。 */
function onNewChatButton(event) {
    if (!multiAgentMode()) { newChat(true); return; }
    if (event) event.stopPropagation();
    const menu = document.getElementById('new-chat-menu');
    if (!menu) { newChat(true); return; }
    if (!menu.classList.contains('hidden')) { menu.classList.add('hidden'); return; }
    const rows = enabledAgents().map(agent => `
        <button type="button" class="new-chat-item" onclick="startSoloChat('${escapeHtml(agent.id)}')">
            ${agentAvatarHTML(agent, 22)}
            <span>${escapeHtml(agent.name)}</span>
        </button>`).join('');
    menu.innerHTML = `
        <div class="new-chat-section">${rows}</div>
        <div class="new-chat-sep"></div>
        <button type="button" class="new-chat-item new-chat-team" onclick="openTeamChatModal()">
            <span class="new-chat-team-ico"><i class="fas fa-user-group"></i></span>
            <span>${escapeHtml(t('new_team_chat'))}</span>
        </button>`;
    menu.classList.remove('hidden');
}

function startSoloChat(agentId) {
    document.getElementById('new-chat-menu')?.classList.add('hidden');
    if (!agentId) { newChat(true); return; }
    activeAgentId = agentId;
    localStorage.setItem('cow_active_agent', activeAgentId);
    newChat(true);
    if (typeof resetWorkspaceToAgentRoot === 'function') resetWorkspaceToAgentRoot();
    renderComposerIdentity();
}

// 第一个检查的代理拥有对话；其余的人被邀请作为客人。
let _teamChatPicks = [];

function openTeamChatModal() {
    document.getElementById('new-chat-menu')?.classList.add('hidden');
    _teamChatPicks = [activeAgentId || defaultAgentId];
    const status = document.getElementById('team-chat-status');
    if (status) status.textContent = '';
    renderTeamChatList();
    document.getElementById('team-chat-modal')?.classList.remove('hidden');
}

function closeTeamChatModal() {
    document.getElementById('team-chat-modal')?.classList.add('hidden');
}

/** From the group-chat picker, jump to creating a new Agent. */
function openAgentCreateFromModal() {
    closeTeamChatModal();
    navigateTo('agents');
    if (typeof openAgentCreateForm === 'function') openAgentCreateForm();
}

function toggleTeamChatPick(agentId) {
    const i = _teamChatPicks.indexOf(agentId);
    if (i === -1) _teamChatPicks.push(agentId);
    else _teamChatPicks.splice(i, 1);
    renderTeamChatList();
}

function renderTeamChatList() {
    const list = document.getElementById('team-chat-list');
    if (!list) return;
    list.innerHTML = enabledAgents().map(agent => {
        const rank = _teamChatPicks.indexOf(agent.id);
        const on = rank !== -1;
        const owner = rank === 0;
        return `<button type="button" class="team-chat-row${on ? ' on' : ''}" onclick="toggleTeamChatPick('${escapeHtml(agent.id)}')">
            ${agentAvatarHTML(agent, 28)}
            <span class="team-chat-name">${escapeHtml(agent.name)}</span>
            ${owner ? `<span class="team-chat-owner">${escapeHtml(t('new_team_chat_owner'))}</span>` : ''}
            <span class="team-chat-check"><i class="fas ${on ? 'fa-circle-check' : 'fa-circle'}"></i></span>
        </button>`;
    }).join('');
}

function startTeamChat() {
    const picks = _teamChatPicks.filter(id => enabledAgents().some(a => a.id === id));
    if (picks.length < 2) {
        const status = document.getElementById('team-chat-status');
        if (status) status.textContent = t('new_team_chat_min');
        return;
    }
    closeTeamChatModal();
    const [owner, ...guests] = picks;
    activeAgentId = owner;
    localStorage.setItem('cow_active_agent', activeAgentId);
    newChat(true);
    if (typeof resetWorkspaceToAgentRoot === 'function') resetWorkspaceToAgentRoot();
    // 新会话存在于客户端；邀请客人上来，这样
    // 第一条消息已发送至群组。
    setTeamMembers(guests).then(() => renderComposerIdentity());
}

function newChat(optimistic = true, inherit = true) {
    // 新的会话会重置预览面板，放弃打开的编辑器。
    if (typeof wsGuardUnsaved === 'function'
        && !wsGuardUnsaved(() => newChat(optimistic, inherit))) return;

    // 不要关闭活动流：其他会话继续在流中进行流传输
    // 背景（每个流派都自我防范外来观点）及其
    // 答复仍然完整并持续。

    // 生成一个新的会话并保留它，以便下一个页面加载也开始干净
    sessionId = generateSessionId();
    localStorage.setItem(activeSessionStorageKey(), sessionId);
    refreshWorkspaceSelector();  // 新的会话在默认工作区上启动
    refreshSessionSettings();    // ...以及全局模型/许可
    if (typeof wsOnSessionSwitch === 'function') wsOnSessionSwitch();
    resetSendBtnSendMode();  // 新会话没有正在进行的回复
    startPolling();  // 碰撞生成，因此旧循环自行取消，新循环使用新的 sessionId
    messagesDiv.innerHTML = '';
    const ws = document.createElement('div');
    ws.id = 'welcome-screen';
    ws.className = 'flex flex-col items-center justify-center h-full px-6 pb-16';
    ws.style.paddingTop = '6vh';
    ws.innerHTML = `
        <img src="assets/logo.jpg" alt="CowAgent" class="w-16 h-16 rounded-2xl mb-6 shadow-lg shadow-primary-500/20">
        <h1 class="text-2xl font-bold text-slate-800 dark:text-slate-100 mb-3">${appConfig.title || 'CowAgent'}</h1>
        <p class="text-slate-500 dark:text-slate-400 text-center max-w-lg mb-10 leading-relaxed" data-i18n="welcome_subtitle">${t('welcome_subtitle')}</p>
        <div class="grid grid-cols-2 sm:grid-cols-3 gap-3 w-full max-w-2xl">
            <div class="example-card group bg-white dark:bg-[#1A1A1A] border border-slate-200 dark:border-white/10 rounded-xl p-4 cursor-pointer hover:border-primary-300 dark:hover:border-primary-600 hover:shadow-md transition-all duration-200">
                <div class="flex items-center gap-2 mb-2">
                    <div class="w-7 h-7 rounded-lg bg-blue-50 dark:bg-blue-900/30 flex items-center justify-center">
                        <i class="fas fa-folder-open text-blue-500 text-xs"></i>
                    </div>
                    <span class="font-medium text-sm text-slate-700 dark:text-slate-200" data-i18n="example_sys_title">${t('example_sys_title')}</span>
                </div>
                <p class="text-sm text-slate-500 dark:text-slate-400 leading-relaxed" data-i18n="example_sys_text">${t('example_sys_text')}</p>
            </div>
            <div class="example-card group bg-white dark:bg-[#1A1A1A] border border-slate-200 dark:border-white/10 rounded-xl p-4 cursor-pointer hover:border-primary-300 dark:hover:border-primary-600 hover:shadow-md transition-all duration-200">
                <div class="flex items-center gap-2 mb-2">
                    <div class="w-7 h-7 rounded-lg bg-amber-50 dark:bg-amber-900/30 flex items-center justify-center">
                        <i class="fas fa-clock text-amber-500 text-xs"></i>
                    </div>
                    <span class="font-medium text-sm text-slate-700 dark:text-slate-200" data-i18n="example_task_title">${t('example_task_title')}</span>
                </div>
                <p class="text-sm text-slate-500 dark:text-slate-400 leading-relaxed" data-i18n="example_task_text">${t('example_task_text')}</p>
            </div>
            <div class="example-card group bg-white dark:bg-[#1A1A1A] border border-slate-200 dark:border-white/10 rounded-xl p-4 cursor-pointer hover:border-primary-300 dark:hover:border-primary-600 hover:shadow-md transition-all duration-200">
                <div class="flex items-center gap-2 mb-2">
                    <div class="w-7 h-7 rounded-lg bg-emerald-50 dark:bg-emerald-900/30 flex items-center justify-center">
                        <i class="fas fa-code text-emerald-500 text-xs"></i>
                    </div>
                    <span class="font-medium text-sm text-slate-700 dark:text-slate-200" data-i18n="example_code_title">${t('example_code_title')}</span>
                </div>
                <p class="text-sm text-slate-500 dark:text-slate-400 leading-relaxed" data-i18n="example_code_text">${t('example_code_text')}</p>
            </div>
            <div class="example-card group bg-white dark:bg-[#1A1A1A] border border-slate-200 dark:border-white/10 rounded-xl p-4 cursor-pointer hover:border-primary-300 dark:hover:border-primary-600 hover:shadow-md transition-all duration-200">
                <div class="flex items-center gap-2 mb-2">
                    <div class="w-7 h-7 rounded-lg bg-violet-50 dark:bg-violet-900/30 flex items-center justify-center">
                        <i class="fas fa-book text-violet-500 text-xs"></i>
                    </div>
                    <span class="font-medium text-sm text-slate-700 dark:text-slate-200" data-i18n="example_knowledge_title">${t('example_knowledge_title')}</span>
                </div>
                <p class="text-sm text-slate-500 dark:text-slate-400 leading-relaxed" data-i18n="example_knowledge_text">${t('example_knowledge_text')}</p>
            </div>
            <div class="example-card group bg-white dark:bg-[#1A1A1A] border border-slate-200 dark:border-white/10 rounded-xl p-4 cursor-pointer hover:border-primary-300 dark:hover:border-primary-600 hover:shadow-md transition-all duration-200">
                <div class="flex items-center gap-2 mb-2">
                    <div class="w-7 h-7 rounded-lg bg-rose-50 dark:bg-rose-900/30 flex items-center justify-center">
                        <i class="fas fa-puzzle-piece text-rose-500 text-xs"></i>
                    </div>
                    <span class="font-medium text-sm text-slate-700 dark:text-slate-200" data-i18n="example_skill_title">${t('example_skill_title')}</span>
                </div>
                <p class="text-sm text-slate-500 dark:text-slate-400 leading-relaxed" data-i18n="example_skill_text">${t('example_skill_text')}</p>
            </div>
            <div class="example-card group bg-white dark:bg-[#1A1A1A] border border-slate-200 dark:border-white/10 rounded-xl p-4 cursor-pointer hover:border-primary-300 dark:hover:border-primary-600 hover:shadow-md transition-all duration-200" data-send="/help">
                <div class="flex items-center gap-2 mb-2">
                    <div class="w-7 h-7 rounded-lg bg-slate-100 dark:bg-slate-800 flex items-center justify-center">
                        <i class="fas fa-terminal text-slate-500 text-xs"></i>
                    </div>
                    <span class="font-medium text-sm text-slate-700 dark:text-slate-200" data-i18n="example_web_title">${t('example_web_title')}</span>
                </div>
                <p class="text-sm text-slate-500 dark:text-slate-400 leading-relaxed" data-i18n="example_web_text">${t('example_web_text')}</p>
            </div>
        </div>
    `;
    messagesDiv.appendChild(ws);
    renderComposerIdentity();
    ws.querySelectorAll('.example-card').forEach(card => {
        card.addEventListener('click', () => {
            const sendText = card.dataset.send;
            if (sendText) {
                chatInput.value = sendText;
                chatInput.dispatchEvent(new Event('input'));
                chatInput.focus();
                return;
            }
            const textEl = card.querySelector('[data-i18n*="text"]');
            if (textEl) {
                chatInput.value = textEl.textContent;
                chatInput.dispatchEvent(new Event('input'));
                chatInput.focus();
            }
        });
    });
    if (currentView !== 'chat') navigateTo('chat');

    // 显示面板并加载完整的会话列表，然后将新会话添加到顶部
    const panel = document.getElementById('session-panel');
    if (panel && !sessionPanelOpen) {
        sessionPanelOpen = true;
        panel.classList.remove('hidden');
        _showSessionOverlay();
        _persistPanelState();
    }
    // 仅当这是真正的新聊天时才在前面添加乐观的“新聊天”项目
    // 行动。删除当前会话后调用时，跳过它：
    // 新会话还没有后端记录，因此插入它会留下一个
    // 列表中空的、不可删除的项目（删除它只会产生另一个）。
    const newSid = sessionId;
    if (optimistic) {
        loadSessionList(() => _addOptimisticSessionItem(newSid));
    } else {
        loadSessionList();
    }
}

// =====================================================================
// 会议小组
// =====================================================================

const SESSION_PANEL_KEY = 'cow_session_panel_open';
let sessionPanelOpen = localStorage.getItem(SESSION_PANEL_KEY) === '1';
// 进入团队页面前是否打开历史记录面板，以便可以查看
// 在退出时恢复（团队页面强制关闭它以腾出空间）。
let _sessionPanelWasOpen = false;

function _persistPanelState() {
    localStorage.setItem(SESSION_PANEL_KEY, sessionPanelOpen ? '1' : '0');
}

function _isMobileView() {
    return window.innerWidth <= 768;
}

function _showSessionOverlay() {
    if (!_isMobileView()) return;
    const overlay = document.getElementById('session-panel-overlay');
    if (overlay) overlay.classList.remove('hidden');
}

function _hideSessionOverlay() {
    const overlay = document.getElementById('session-panel-overlay');
    if (overlay) overlay.classList.add('hidden');
}

function closeSessionPanel(skipPersist) {
    const panel = document.getElementById('session-panel');
    if (!panel || !sessionPanelOpen) return;
    sessionPanelOpen = false;
    panel.classList.add('hidden');
    _hideSessionOverlay();
    // 当团队页面将面板收起来时，它不应该覆盖用户的面板
    // 自己的喜好；只有真正的用户关闭才会持续存在。
    if (!skipPersist) _persistPanelState();
}

function toggleSessionPanel() {
    const panel = document.getElementById('session-panel');
    if (!panel) return;
    sessionPanelOpen = !sessionPanelOpen;
    panel.classList.toggle('hidden', !sessionPanelOpen);
    if (sessionPanelOpen) {
        _showSessionOverlay();
    } else {
        _hideSessionOverlay();
    }
    _persistPanelState();
    if (sessionPanelOpen) loadSessionList();
}

function openSessionPanel() {
    const panel = document.getElementById('session-panel');
    if (!panel || sessionPanelOpen) return;
    sessionPanelOpen = true;
    panel.classList.remove('hidden');
    _showSessionOverlay();
    _persistPanelState();
    loadSessionList();
}

function _restoreSessionPanel() {
    const panel = document.getElementById('session-panel');
    if (!panel) return;
    if (sessionPanelOpen && !_isMobileView()) {
        panel.classList.remove('hidden');
        _showSessionOverlay();
        loadSessionList();
    } else {
        panel.classList.add('hidden');
        _hideSessionOverlay();
    }
}

// 将原生 `title` 替换为 CSS 工具提示，以便立即出现提示
// 而不是等待浏览器的内置延迟。
function _setBtnTooltip(el, text) {
    if (!el) return;
    el.setAttribute('data-tooltip', text);
    el.removeAttribute('title');
}

function _applyInputTooltips() {
    const set = (id, key, pos) => {
        const el = document.getElementById(id);
        if (!el) return;
        _setBtnTooltip(el, t(key));
        if (pos) el.setAttribute('data-tooltip-pos', pos);
    };
    set('new-chat-btn', 'tip_new_chat');
    set('clear-context-btn', 'tip_clear_context');
    set('attach-btn', 'tip_attach');
    set('steer-btn', 'steer_active');
    set('session-toggle-btn', 'session_history', 'bottom');
    set('workspace-toggle-btn', 'ws_toggle', 'bottom');
    // 优化/麦克风按钮带有状态相关的工具提示，在其管理中
    // 自己的设置，但在语言切换时我们将它们重置为空闲标签，以便
    // 工具提示遵循当前区域设置。
    set('optimize-btn', 'optimize_idle_title');
    set('mic-btn', 'mic_idle_title');
    // 发送按钮仅带有工具提示，而它充当取消按钮。
    _setBtnTooltip(sendBtn, sendBtnMode === 'cancel' ? t('tip_cancel') : '');
    // 许可/模型芯片带有翻译的标签和工具提示，因此它们
    // 也在这里重新绘制（这在每个语言切换上运行）。
    _renderPermissionChip();
    _renderModelChip();
}

// 浏览器中存在但数据库中尚未存在的会话：用户
// 按“新聊天”并且尚未发送第一条消息。从相同的渲染
// 路径作为真实会话，因此它位于正确的组中。
function _addOptimisticSessionItem(sid) {
    const container = document.getElementById('session-list');
    if (!container) return;
    if (_sessionItems.some(s => s.session_id === sid)) return;

    _sessionItems.unshift({
        session_id: sid,
        title: t('new_chat'),
        last_active: Math.floor(Date.now() / 1000),
        pinned: 0,
        // 新会话继承选择器当前显示的工作区。
        project: _wsSelState.current
            ? { path: _wsSelState.current.path, name: _wsSelState.current.name }
            : null,
    });
    _renderSessionList();
}

function _sessionTimeGroup(ts) {
    const now = new Date();
    const d = new Date(ts * 1000);
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1);
    if (d >= today) return t('today');
    if (d >= yesterday) return t('yesterday');
    return t('earlier');
}

let _sessionPage = 1;
let _sessionHasMore = false;
let _sessionLoading = false;
const _SESSION_PAGE_SIZE = 50;

// 到目前为止，每个会话均按后端顺序加载（首先固定，然后是新近度）。
// 保留为数据而不仅仅是 DOM，因为按项目分组会重新排序
// 整个列表，这不能通过逐页附加来完成。
let _sessionItems = [];
// 'time' (今天/昨天/更早, the behavior before projects existed) or 'project'.
// 后端根据所有会话中使用的空间数量来决定。
let _sessionGroupMode = 'time';
// 用户从后端选择的项目空间顺序（路径 + '__default__'）。
let _projectOrder = [];
// Sentinel 后端用于排序中的默认工作区。
const DEFAULT_SPACE_KEY = '__default__';

// 哪些项目组是折叠的，每个浏览器都保留，所以选择
// 重新加载后仍然存在。通过空格键（项目路径或默认标记）进行键入。
const _COLLAPSED_KEY = 'cow_collapsed_projects';
function _loadCollapsed() {
    try { return new Set(JSON.parse(localStorage.getItem(_COLLAPSED_KEY) || '[]')); }
    catch (e) { return new Set(); }
}
function _saveCollapsed(set) {
    try { localStorage.setItem(_COLLAPSED_KEY, JSON.stringify([...set])); } catch (e) {}
}
let _collapsedProjects = _loadCollapsed();

function loadSessionList(onDone) {
    const container = document.getElementById('session-list');
    if (!container) return;

    _sessionPage = 1;
    _sessionHasMore = false;

    _fetchSessionPage(1, true, onDone);
}

function _fetchSessionPage(page, clear, onDone) {
    if (_sessionLoading) return;
    _sessionLoading = true;

    const container = document.getElementById('session-list');
    if (!container) { _sessionLoading = false; return; }

    fetch(`/api/sessions?page=${page}&page_size=${_SESSION_PAGE_SIZE}&scope=all`)
        .then(r => r.json())
        .then(data => {
            _sessionLoading = false;
            if (data.status !== 'success') return;

            if (clear) _sessionItems = [];

            const sessions = data.sessions || [];
            _sessionPage = page;
            _sessionHasMore = !!data.has_more;
            _sessionGroupMode = data.group_mode === 'project' ? 'project' : 'time';
            if (Array.isArray(data.project_order)) _projectOrder = data.project_order;

            const sessionKey = s => `${(s.agent && s.agent.id) || ''}::${s.session_id}`;
            const seen = new Set(_sessionItems.map(sessionKey));
            sessions.forEach(s => {
                const key = sessionKey(s);
                if (seen.has(key)) return;
                seen.add(key);
                _sessionItems.push(s);
            });

            _renderSessionList();
            if (typeof onDone === 'function') onDone();
        })
        .catch(() => { _sessionLoading = false; });
}

// 将加载的会话分成有序的、带标签的组。
//
// 时间模式保留原始的今天/昨天/早些时候的存储桶，其中一个
// 另外：固定的对话会移至顶部的一组对话中，
// 因为留在日期桶内的图钉将无法找到。
// 项目模式按工作区分组，并且引脚浮动到其顶部
// 自己的项目 - 这是用户提交它们的地方。
function _sessionGroups() {
    const groups = [];
    const bucket = (key, label, icon, hint, isProject) => {
        let g = groups.find(x => x.key === key);
        if (!g) { g = { key, label, icon, hint, isProject, items: [] }; groups.push(g); }
        return g;
    };

    if (_sessionGroupMode === 'project') {
        // `_sessionItems` 已经先固定/最新先，所以追加
        // order 为每个项目提供相同的免费订购。
        _sessionItems.forEach(s => {
            const key = s.project ? s.project.path : DEFAULT_SPACE_KEY;
            const name = s.project ? s.project.name : t('ws_default_workspace');
            const icon = s.project ? 'fa-folder' : 'fa-house';
            bucket(key, name, icon, s.project ? s.project.path : '', !!s.project).items.push(s);
        });
        // 按用户选择的顺序对组进行排序；没有保存的空格
        // 位置在有序的位置之后保持自然（新近度）顺序。
        if (_projectOrder.length) {
            const rank = new Map(_projectOrder.map((k, i) => [k, i]));
            groups.sort((a, b) => {
                const ra = rank.has(a.key) ? rank.get(a.key) : Infinity;
                const rb = rank.has(b.key) ? rank.get(b.key) : Infinity;
                return ra - rb;
            });
        }
        return groups;
    }

    const pinned = _sessionItems.filter(s => s.pinned);
    if (pinned.length) {
        bucket('__pinned__', t('session_pinned_group'), 'fa-thumbtack', '', false).items.push(...pinned);
    }
    _sessionItems.filter(s => !s.pinned).forEach(s => {
        const label = _sessionTimeGroup(s.last_active);
        bucket('time:' + label, label, '', '', false).items.push(s);
    });
    return groups;
}

function _renderSessionList() {
    const container = document.getElementById('session-list');
    if (!container) return;

    if (!_sessionItems.length) {
        container.innerHTML = '<div class="session-empty">' + t('untitled_session') + '</div>';
        return;
    }

    container.innerHTML = '';
    const projectMode = _sessionGroupMode === 'project';
    // 当多个项目同时存在时，将会话缩进其项目标题下
    // 显示，因此该列表读取为与上面的文件夹图标对齐的树。
    const indentItems = projectMode && _sessionGroups().length > 1;
    _sessionGroups().forEach(group => {
        const collapsed = projectMode && _collapsedProjects.has(group.key);
        const header = document.createElement('div');
        header.className = 'session-group-label' + (projectMode ? ' session-group-project' : '');
        if (group.hint) header.title = group.hint;

        if (projectMode) {
            // 可折叠、可拖动的项目标题。默认空间没有
            // 重命名/删除操作（没有要编辑的记录）但仍然拖动。
            header.draggable = true;
            header.dataset.spaceKey = group.key;
            const isDefault = group.key === DEFAULT_SPACE_KEY;
            const actions = isDefault ? '' : `
                <button class="session-group-action" title="${escapeHtml(t('project_rename'))}"
                        onclick="event.stopPropagation(); renameProject('${_wsAttr(group.key)}','${_wsAttr(group.label)}')">
                    <i class="fas fa-pen"></i>
                </button>
                <button class="session-group-action" title="${escapeHtml(t('project_delete'))}"
                        onclick="event.stopPropagation(); deleteProject('${_wsAttr(group.key)}','${_wsAttr(group.label)}')">
                    <i class="fas fa-trash-can"></i>
                </button>`;
            header.innerHTML = `
                <i class="fas fa-chevron-down session-group-caret ${collapsed ? 'collapsed' : ''}"></i>
                <i class="fas ${group.icon} session-group-icon"></i>
                <span class="session-group-name">${escapeHtml(group.label)}</span>
                <span class="session-group-count">${group.items.length}</span>
                <span class="session-group-actions">${actions}</span>`;
            header.addEventListener('click', () => _toggleProjectCollapse(group.key));
            _wireGroupDrag(header, group.key);
        } else if (group.icon) {
            header.innerHTML = `<i class="fas ${group.icon}"></i><span>${escapeHtml(group.label)}</span>`;
        } else {
            header.textContent = group.label;
        }
        container.appendChild(header);

        if (!collapsed) {
            group.items.forEach(s => container.appendChild(_sessionItemEl(s, indentItems)));
        }
    });
}

function _toggleProjectCollapse(key) {
    if (_collapsedProjects.has(key)) _collapsedProjects.delete(key);
    else _collapsedProjects.add(key);
    _saveCollapsed(_collapsedProjects);
    _renderSessionList();
}

// --- 项目组拖动重新排序 -------------------------------------------
let _dragSpaceKey = null;

function _wireGroupDrag(header, key) {
    header.addEventListener('dragstart', (e) => {
        _dragSpaceKey = key;
        header.classList.add('dragging');
        try { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', key); } catch (err) {}
    });
    header.addEventListener('dragend', () => {
        _dragSpaceKey = null;
        header.classList.remove('dragging');
        document.querySelectorAll('.session-group-project.drop-target')
            .forEach(el => el.classList.remove('drop-target'));
    });
    header.addEventListener('dragover', (e) => {
        if (_dragSpaceKey === null || _dragSpaceKey === key) return;
        e.preventDefault();
        header.classList.add('drop-target');
    });
    header.addEventListener('dragleave', () => header.classList.remove('drop-target'));
    header.addEventListener('drop', (e) => {
        e.preventDefault();
        header.classList.remove('drop-target');
        if (_dragSpaceKey === null || _dragSpaceKey === key) return;
        _reorderSpace(_dragSpaceKey, key);
    });
}

// 将 `fromKey` 移动到 `beforeKey` 之前，然后保留新顺序。
function _reorderSpace(fromKey, beforeKey) {
    // 从当前显示的组顺序开始，即使拖动也稳定
    // 当某些空间还没有保存位置时。
    const current = _sessionGroups().map(g => g.key);
    const order = current.filter(k => k !== fromKey);
    const idx = order.indexOf(beforeKey);
    if (idx < 0) order.push(fromKey);
    else order.splice(idx, 0, fromKey);

    _projectOrder = order;
    _renderSessionList();

    fetch('/api/projects/order', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ order }),
    }).catch(() => {});
}

// 重命名项目（仅显示名称；磁盘上的文件夹不变）。
function renameProject(path, currentName) {
    showPromptModal(t('project_rename_title'), currentName, (name) => {
        if (name === null) return;
        fetch('/api/projects/manage', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path, name }),
        })
            .then(r => r.json())
            .then(data => {
                if (data.status !== 'success') { _wsToast(data.message || t('session_settings_failed')); return; }
                loadSessionList();
            })
            .catch(() => _wsToast(t('session_settings_failed')));
    });
}

// 删除项目记录。仅删除CowAgent记录；文件保留并
// 绑定会话恢复到默认工作区。
function deleteProject(path, name) {
    showConfirmModal(
        t('project_delete_title'),
        t('project_delete_confirm').replace('{name}', name || path),
        () => {
            fetch('/api/projects/manage', {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path }),
            })
                .then(r => r.json())
                .then(data => {
                    if (data.status !== 'success') { _wsToast(data.message || t('session_settings_failed')); return; }
                    loadSessionList();
                })
                .catch(() => _wsToast(t('session_settings_failed')));
        }
    );
}

function _sessionItemEl(s, indent) {
    const item = document.createElement('div');
    const ownerId = (s.agent && s.agent.id) || '';
    const isActive = s.session_id === sessionId && (!ownerId || ownerId === activeAgentId);
    item.className = 'session-item' + (isActive ? ' active' : '') + (s.pinned ? ' pinned' : '')
        + (indent ? ' session-item-indent' : '');
    item.dataset.sessionId = s.session_id;
    if (ownerId) item.dataset.agentId = ownerId;

    const title = s.title || t('untitled_session');
    const sid = _wsAttr(s.session_id);
    const owner = ownerId ? _wsAttr(ownerId) : '';
    // 面孔标志着有多个代理参与的对话，就像一个团体一样
    // 聊天与直接聊天是有区别的。与单身人士的对话
    // 无论其他地方的名单是什么样子，特工都保持着朴素的一排。我们展示
    // 最多三个重叠面以保持行整齐；当更多人参与的时候，
    // 一个小“+N”限制了堆栈，因此组的大小仍然清晰可辨。
    const roster = s.participants || [];
    const crowd = roster.length > 1 ? roster.slice(0, 3) : null;
    const overflow = roster.length - 3;
    const face = crowd
        ? `<span class="session-faces">${crowd.map(a => agentAvatarHTML(a, 20)).join('')}`
            + (overflow > 0 ? `<span class="session-face-more">+${overflow}</span>` : '')
            + `</span>`
        : `<i class="fas ${s.pinned ? 'fa-thumbtack' : 'fa-message'} session-icon"></i>`;
    item.innerHTML = `
        ${face}
        <span class="session-title" title="${escapeHtml(title)}">${escapeHtml(title)}</span>
        <button class="session-pin" onclick="event.stopPropagation(); toggleSessionPin('${sid}', '${owner}')"
                title="${escapeHtml(t(s.pinned ? 'unpin_session' : 'pin_session'))}">
            <i class="fas fa-thumbtack"></i>
        </button>
        <button class="session-rename" onclick="event.stopPropagation(); renameSession('${sid}')" title="${escapeHtml(t('rename_session'))}">
            <i class="fas fa-pen"></i>
        </button>
        <button class="session-delete" onclick="event.stopPropagation(); deleteSession('${sid}', '${owner}')" title="Delete">
            <i class="fas fa-trash-can"></i>
        </button>
    `;
    item.addEventListener('click', () => switchSession(s.session_id, ownerId || undefined));
    return item;
}

// 固定/取消固定，然后重新渲染，以便对话移至新位置。
// 对加载的会话重新排序以匹配后端的顺序（先固定，然后
// 最近活跃），因此乐观的固定/取消固定会落在正确的位置
// 无需等待重新加载。在每个桶内稳定。
function _sortSessionItems() {
    _sessionItems.sort((a, b) => {
        const pa = a.pinned ? 1 : 0;
        const pb = b.pinned ? 1 : 0;
        if (pa !== pb) return pb - pa;
        return (b.last_active || 0) - (a.last_active || 0);
    });
}

function toggleSessionPin(sid, agentId) {
    const entry = _sessionItems.find(s => s.session_id === sid && (!agentId || (s.agent && s.agent.id) === agentId));
    if (!entry) return;
    const pinned = !entry.pinned;

    // 乐观地移动它：重新排序是点击的全部重点，并且
    // 无论如何，该列表都是根据相同的数据重新呈现的。固定也必须
    // 重新排序 `_sessionItems` — 组渲染器已经依赖于数组
    // 首先被固定，因此仅翻转标志就会留下刚刚固定的
    // 坐在原地聊天（尤其是在项目组内）。
    entry.pinned = pinned ? 1 : 0;
    _sortSessionItems();
    _renderSessionList();

    const owner = agentId || (entry.agent && entry.agent.id) || activeAgentId;
    fetch(`/api/sessions/${encodeURIComponent(sid)}?agent_id=${encodeURIComponent(owner || '')}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pinned, agent_id: owner }),
    })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'success') return;
            // 最常见的是一个空的全新聊天：它没有行可以固定，直到
            // 第一条消息已存储。
            _wsToast(data.message || t('session_settings_failed'));
            entry.pinned = pinned ? 0 : 1;
            _sortSessionItems();
            _renderSessionList();
        })
        .catch(() => {
            entry.pinned = pinned ? 0 : 1;
            _sortSessionItems();
            _renderSessionList();
        });
}

function _onSessionListScroll() {
    if (!_sessionHasMore || _sessionLoading) return;
    const container = document.getElementById('session-list');
    if (!container) return;
    // 滚动到底部附近（60px以内）时触发
    if (container.scrollHeight - container.scrollTop - container.clientHeight < 60) {
        _fetchSessionPage(_sessionPage + 1, false);
    }
}

// DOM 准备好后附加滚动侦听器
(function _initSessionScroll() {
    const el = document.getElementById('session-list');
    if (el) {
        el.addEventListener('scroll', _onSessionListScroll);
    } else {
        document.addEventListener('DOMContentLoaded', () => {
            const el2 = document.getElementById('session-list');
            if (el2) el2.addEventListener('scroll', _onSessionListScroll);
        });
    }
})();

// 返回到其回复仍在后台流动的会话。
// 关闭后台EventSource，从缓冲中重建气泡
// 事件（快照），然后通过新连接恢复直播
// 从后端重播日志中读取剩余的尾部。如果是流则返回 true
// 被重新连接。用户自己的泡沫已经成为历史（持续存在
// 急切地），因此它是在运行之前由 loadHistory 渲染的。
function _reattachStream(sid) {
    const key = runtimeSessionKey(sid);
    const requestId = sessionActiveRequest[key];
    if (!requestId) return false;
    const buffer = streamBuffers[requestId];
    if (!buffer) return false;

    // 如果缓冲流已经结束，则助理回复已经
    // 由 loadHistory 持久化并呈现 - 重新附加会复制它。
    // 只需清理缓冲区/光标并依赖历史记录即可。
    const finished = buffer.items.some(
        it => it.type === 'stream_end' || it.type === 'error' || it.type === 'resync_required'
    );
    if (finished) {
        const oldEs = activeStreams[requestId];
        if (oldEs) { try { oldEs.close(); } catch (_) {} delete activeStreams[requestId]; }
        delete streamBuffers[requestId];
        delete sessionActiveRequest[key];
        resetSendBtnSendMode();
        return false;
    }

    // 完成已经存在于持久的历史中。保留背景尾部
    // 连接了 voice_attach/stream_end，但不将答案重播到
    // 新加载的历史视图，否则会创建重复的气泡。
    if (buffer.items.some(it => it.type === 'done')) {
        resetSendBtnSendMode();
        return false;
    }

    // 重建之前停止后台连接。每个新连接
    // 独立于其最后接受的序列号恢复。
    const oldEs = activeStreams[requestId];
    if (oldEs) { try { oldEs.close(); } catch (_) {} delete activeStreams[requestId]; }

    // 将缓冲的事件快照到重播中，然后启动新的流
    // 重放它们并重新连接实时尾部。
    const replay = buffer.items.slice();
    startSSE(requestId, null, buffer.timestamp || new Date(), null, replay);
    return true;
}

function switchSession(newSessionId, agentId) {
    if (agentId && agentId !== activeAgentId) {
        activeAgentId = agentId;
        localStorage.setItem('cow_active_agent', activeAgentId);
    }
    if (newSessionId === sessionId) {
        if (currentView !== 'chat') navigateTo('chat');
        renderComposerIdentity();
        return;
    }

    // 预览面板的范围仅限于会话的工作区，因此切换眼泪
    // 打开打开的编辑器。在提交切换之前解决未保存的编辑。
    if (typeof wsGuardUnsaved === 'function'
        && !wsGuardUnsaved(() => switchSession(newSessionId))) return;

    // 不要在此处关闭活动流：会话并行运行，因此任何
    // 另一个会话的正在进行的回复必须继续在
    // 背景（它自我防范渲染到外部视图中）。
    // 切换回来重新连接并恢复直播。

    sessionId = newSessionId;
    updateEditButtonsState();
    localStorage.setItem(activeSessionStorageKey(), sessionId);
    refreshWorkspaceSelector();
    refreshSessionSettings();
    // 重置文件/预览面板，使其反映新会话的根目录。
    if (typeof wsOnSessionSwitch === 'function') wsOnSessionSwitch();

    historyPage = 0;
    historyHasMore = false;
    historyLoading = false;

    messagesDiv.innerHTML = '';
    loadHistory(1);
    startPolling();

    // 恢复发送按钮以匹配此会话的流状态，并且如果
    // 回复仍在后台流式传输，重新附加以恢复显示
    // 它是活的（用户回合本身来自上面的历史）。
    const pendingReq = sessionActiveRequest[runtimeSessionKey(sessionId)];
    if (pendingReq) {
        setSendBtnCancelMode(pendingReq);
        _reattachStream(sessionId);
    } else {
        resetSendBtnSendMode();
    }

    document.querySelectorAll('.session-item').forEach(el => {
        el.classList.toggle('active', el.dataset.sessionId === sessionId);
    });

    if (_isMobileView()) closeSessionPanel();
    if (currentView !== 'chat') navigateTo('chat');
    renderComposerIdentity();
}

// 就地重命名会话标题：将标题 <span> 替换为 <input>，
// Enter/blur 时提交，Escape 时取消。通过 PUT /api/sessions/<id> 保留。
function renameSession(sid) {
    const item = document.querySelector(`.session-item[data-session-id="${sid}"]`);
    if (!item) return;
    const titleEl = item.querySelector('.session-title');
    if (!titleEl || item.querySelector('.session-title-input')) return;

    const oldTitle = titleEl.textContent;

    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'session-title-input';
    input.value = oldTitle;
    input.maxLength = 100;

    // 避免在与输入交互时切换会话
    const stop = e => e.stopPropagation();
    input.addEventListener('click', stop);
    input.addEventListener('mousedown', stop);

    titleEl.replaceWith(input);
    input.focus();
    input.select();

    let done = false;

    const restore = (title) => {
        if (done) return;
        done = true;
        const span = document.createElement('span');
        span.className = 'session-title';
        span.title = title;
        span.textContent = title;
        input.replaceWith(span);
    };

    // 撤消 DOM 和缓存条目中的乐观重命名。
    const revert = () => {
        const cachedEntry = _sessionItems.find(s => s.session_id === sid);
        if (cachedEntry) cachedEntry.title = oldTitle;
        const span = item.querySelector('.session-title');
        if (span) {
            span.title = oldTitle;
            span.textContent = oldTitle;
        }
    };

    const commit = () => {
        if (done) return;
        const newTitle = input.value.trim();
        if (!newTitle || newTitle === oldTitle) {
            restore(oldTitle);
            return;
        }
        // 乐观地展示新头衔，然后坚持下去。缓存的条目是
        // 也更新了，或者下一次重新渲染（例如，一个图钉）将恢复旧的。
        restore(newTitle);
        const cached = _sessionItems.find(s => s.session_id === sid);
        if (cached) cached.title = newTitle;
        fetch(`/api/sessions/${encodeURIComponent(sid)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: newTitle })
        })
            .then(r => r.json())
            .then(data => {
                if (data.status !== 'success') revert();
            })
            .catch(revert);
    };

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); commit(); }
        else if (e.key === 'Escape') { e.preventDefault(); restore(oldTitle); }
    });
    input.addEventListener('blur', commit);
}

function deleteSession(sid, agentId) {
    showConfirmModal(t('delete_session_title'), t('delete_session_confirm'), () => {
        const owner = agentId || activeAgentId;
        const deletingCurrent = sid === sessionId && (!owner || owner === activeAgentId);
        const next = deletingCurrent ? _findNextSession(sid, owner) : null;

        fetch(`/api/sessions/${encodeURIComponent(sid)}?agent_id=${encodeURIComponent(owner || '')}`, { method: 'DELETE' })
            .then(r => r.json())
            .then(data => {
                if (data.status !== 'success') return;
                if (!deletingCurrent) {
                    loadSessionList();
                    return;
                }
                if (next) {
                    switchSession(next.sessionId, next.agentId);
                    loadSessionList();
                } else {
                    newChat(false);
                }
            })
            .catch(() => {});
    });
}

// 选择删除 `sid` 后要显示的会话（当前会话）：更喜欢
// 列表中其下方的下一项，否则为上一项。返回空值
// 如果不存在其他会话。
function _findNextSession(sid, agentId) {
    const items = Array.from(document.querySelectorAll('.session-item[data-session-id]'));
    const same = el => el.dataset.sessionId === sid && (!agentId || el.dataset.agentId === agentId);
    const idx = items.findIndex(same);
    const pick = el => el ? { sessionId: el.dataset.sessionId, agentId: el.dataset.agentId || '' } : null;
    if (idx === -1) {
        return pick(items.find(el => !same(el)));
    }
    return pick(items[idx + 1] || items[idx - 1]);
}

function showConfirmModal(title, message, onConfirm) {
    let overlay = document.getElementById('confirm-modal-overlay');
    if (overlay) overlay.remove();

    overlay = document.createElement('div');
    overlay.id = 'confirm-modal-overlay';
    overlay.className = 'confirm-overlay';

    const modal = document.createElement('div');
    modal.className = 'confirm-modal';
    modal.innerHTML = `
        <div class="confirm-title">${escapeHtml(title)}</div>
        <div class="confirm-message">${escapeHtml(message)}</div>
        <div class="confirm-actions">
            <button class="confirm-btn confirm-btn-cancel">${t('confirm_cancel')}</button>
            <button class="confirm-btn confirm-btn-ok">${t('confirm_yes')}</button>
        </div>
    `;
    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    requestAnimationFrame(() => overlay.classList.add('visible'));

    const close = () => {
        overlay.classList.remove('visible');
        setTimeout(() => overlay.remove(), 200);
    };

    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    modal.querySelector('.confirm-btn-cancel').addEventListener('click', close);
    modal.querySelector('.confirm-btn-ok').addEventListener('click', () => {
        close();
        onConfirm();
    });
}

// 具有单个文本输入的确认模式。调用 onSubmit(value) 就OK了，并且
// 取消时不执行任何操作。镜子显示ConfirmModal 的外观和生命周期。
function showPromptModal(title, initialValue, onSubmit) {
    let overlay = document.getElementById('confirm-modal-overlay');
    if (overlay) overlay.remove();

    overlay = document.createElement('div');
    overlay.id = 'confirm-modal-overlay';
    overlay.className = 'confirm-overlay';

    const modal = document.createElement('div');
    modal.className = 'confirm-modal';
    modal.innerHTML = `
        <div class="confirm-title">${escapeHtml(title)}</div>
        <input type="text" class="prompt-modal-input" maxlength="100" />
        <div class="confirm-actions">
            <button class="confirm-btn confirm-btn-cancel">${t('confirm_cancel')}</button>
            <button class="confirm-btn confirm-btn-ok">${t('confirm_yes')}</button>
        </div>
    `;
    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    const input = modal.querySelector('.prompt-modal-input');
    input.value = initialValue || '';
    requestAnimationFrame(() => { overlay.classList.add('visible'); input.focus(); input.select(); });

    const close = () => {
        overlay.classList.remove('visible');
        setTimeout(() => overlay.remove(), 200);
    };
    const submit = () => { const v = input.value.trim(); close(); onSubmit(v); };

    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    modal.querySelector('.confirm-btn-cancel').addEventListener('click', close);
    modal.querySelector('.confirm-btn-ok').addEventListener('click', submit);
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); submit(); }
        else if (e.key === 'Escape') { e.preventDefault(); close(); }
    });
}

function clearContext() {
    fetch(`/api/sessions/${encodeURIComponent(sessionId)}/clear_context`, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (data.status !== 'success') return;
            // 在聊天中插入视觉分隔线
            const divider = document.createElement('div');
            divider.className = 'context-divider';
            divider.innerHTML = `<span>${t('context_cleared')}</span>`;
            messagesDiv.appendChild(divider);
            scrollChatToBottom();
        })
        .catch(() => {});
}

function generateSessionTitle(sid, userMsg, assistantReply) {
    fetch(`/api/sessions/${encodeURIComponent(sid)}/generate_title`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_message: userMsg, assistant_reply: assistantReply }),
    })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'success' && sessionPanelOpen) {
                loadSessionList();
            }
        })
        .catch(() => {});
}

// =====================================================================
// 公用事业
// =====================================================================
function formatTime(date) {
    const now = new Date();
    const sameDay = date.getFullYear() === now.getFullYear()
        && date.getMonth() === now.getMonth()
        && date.getDate() === now.getDate();
    const time = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    if (sameDay) return time;
    const m = String(date.getMonth() + 1).padStart(2, '0');
    const d = String(date.getDate()).padStart(2, '0');
    if (date.getFullYear() === now.getFullYear()) return `${m}-${d} ${time}`;
    return `${date.getFullYear()}-${m}-${d} ${time}`;
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}

function ChannelsHandler_maskSecret(val) {
    if (!val || val.length <= 8) return val;
    return val.slice(0, 4) + '*'.repeat(val.length - 8) + val.slice(-4);
}

function formatToolArgs(args) {
    if (!args || Object.keys(args).length === 0) return '(none)';
    try {
        return escapeHtml(JSON.stringify(args, null, 2));
    } catch (_) {
        return escapeHtml(String(args));
    }
}

const SUBSTEP_ARGS_CHARS = 90;

/** Tool arguments on one line, for a step in a list of dozens. */
function summarizeToolArgs(args) {
    if (!args || typeof args !== 'object') return '';
    const parts = [];
    for (const [key, value] of Object.entries(args)) {
        const text = typeof value === 'object' ? JSON.stringify(value) : String(value);
        parts.push(`${key}=${text}`);
    }
    const joined = parts.join(', ');
    return joined.length > SUBSTEP_ARGS_CHARS
        ? joined.slice(0, SUBSTEP_ARGS_CHARS) + '…'
        : joined;
}

/**
 * Add or settle one step inside a sub agent's card.
 *
 * Silent when the card is gone: a sub agent cancelled on timeout keeps working
 * until its next checkpoint, and steps that arrive after its card closed
 * describe work nobody is waiting on any more.
 */
function renderSubagentStep(toolEl, item) {
    if (!toolEl || !item.step_id) return;
    const section = toolEl.querySelector('.tool-substeps-section');
    const list = toolEl.querySelector('.tool-substeps');
    if (!section || !list) return;

    let stepEl = list.querySelector(`[data-step-id="${CSS.escape(item.step_id)}"]`);
    if (!stepEl) {
        if (item.phase !== 'start') return;
        stepEl = document.createElement('div');
        stepEl.className = 'tool-substep';
        stepEl.dataset.stepId = item.step_id;
        stepEl.innerHTML = `
            <i class="fas fa-circle-notch fa-spin tool-substep-icon"></i>
            <span class="tool-substep-name">${escapeHtml(item.tool || 'tool')}</span>
            <span class="tool-substep-args">${escapeHtml(summarizeToolArgs(item.arguments))}</span>
            <span class="tool-substep-time"></span>`;
        list.appendChild(stepEl);
        section.classList.remove('hidden');
        // 第一步也是子代理生命的第一个迹象，
        // 运行几分钟，因此它会打开它所属的卡。
        toolEl.classList.add('expanded');
        updateSubstepCount(toolEl, list.children.length);
        return;
    }

    if (item.phase !== 'end') return;
    const isError = item.status && item.status !== 'success';
    const icon = stepEl.querySelector('.tool-substep-icon');
    if (icon) {
        icon.className = isError
            ? 'fas fa-times tool-substep-icon tool-substep-failed'
            : 'fas fa-check tool-substep-icon';
    }
    const timeEl = stepEl.querySelector('.tool-substep-time');
    if (timeEl && item.execution_time) timeEl.textContent = `${item.execution_time}s`;
    if (item.error) {
        // 失败的步骤说明了它发生的位置；分代理人的报告
        // 涵盖了成功人士的发现。
        const argsEl = stepEl.querySelector('.tool-substep-args');
        if (argsEl) {
            argsEl.textContent = String(item.error);
            argsEl.classList.add('tool-substep-failed');
        }
        stepEl.title = String(item.error);
    }
}

function updateSubstepCount(toolEl, count) {
    const countEl = toolEl.querySelector('.tool-substep-count');
    if (countEl) countEl.textContent = count === 1 ? '1 step' : `${count} steps`;
}

function scrollChatToBottom(force) {
    if (force || _autoScrollEnabled) {
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
    }
}

function _updateScrollToBottomBtn() {
    const btn = document.getElementById('scroll-to-bottom-btn');
    if (!btn) return;
    const distFromBottom = messagesDiv.scrollHeight - messagesDiv.scrollTop - messagesDiv.clientHeight;
    btn.classList.toggle('hidden', distFromBottom <= _SCROLL_THRESHOLD);
}

function applyHighlighting(container) {
    const root = container || document;
    setTimeout(() => {
        const hljsLib = getHljs();
        root.querySelectorAll('pre code').forEach(block => {
            if (!block.classList.contains('hljs')) {
                hljsLib.highlightElement(block);
            }
        });
        // 添加语言标签并将按钮复制到代码块
        _addCodeBlockHeaders(root);
    }, 0);
}

// =====================================================================
// 配置视图
// =====================================================================
let configProviders = {};
let configApiBases = {};
let configApiKeys = {};
let configCurrentModel = '';
let cfgProviderValue = '';
let cfgModelValue = '';
let cfgReasoningEffortValue = 'high';
let configReasoningByModel = {};
// 记住用户为每个提供商输入的自定义模型名称，因此切换
// 远离提供者（重建其模型下拉列表）并且返回不会
// 丢失未保存的自定义模型。由提供商 ID 键入。
let configCustomModelByProvider = {};
// “模型”选项卡功能卡的想法相同：记住自定义模型
// 用户键入每个（功能，提供者）并且提供者在之前处于活动状态
// 最后一次切换，因此切换供应商并返回可恢复自定义模型。
// 由 `${capabilityId}:${providerId}` -> 自定义模型字符串键入。
let capabilityCustomModelMemory = {};
// 由当前切换前处于活动状态的capabilityId -> 提供程序id 键入。
let capabilityLastProviderId = {};

// --- 自定义下拉帮助器 ---
function initDropdown(el, options, selectedValue, onChange, opts) {
    // opts.placeholder：当设置且 selectedValue 为空时，渲染该文本
    // 以暗淡风格而不是自动选择选项[0]。有用于
    // 我们想要的“拾取或清空”功能（asr /嵌入）
    // 用户做出明确的选择。
    opts = opts || {};
    const textEl = el.querySelector('.cfg-dropdown-text');
    const menuEl = el.querySelector('.cfg-dropdown-menu');
    const selEl = el.querySelector('.cfg-dropdown-selected');
    // 触发器中可选的头像面孔（opts.withAvatar）。然后每个选项
    // 带有一个 `agent` 对象，因此行和触发器都可以绘制它。
    const faceEl = el.querySelector('.cfg-dropdown-face');

    el._ddValue = selectedValue || '';
    el._ddOnChange = onChange;

    function paintFace(opt) {
        if (!faceEl) return;
        faceEl.innerHTML = (opt && opt.agent) ? agentAvatarHTML(opt.agent, 20) : '';
    }

    function render() {
        menuEl.innerHTML = '';
        options.forEach(opt => {
            const item = document.createElement('div');
            item.className = 'cfg-dropdown-item' + (opt.value === el._ddValue ? ' active' : '');
            item.dataset.value = opt.value;
            // 提示是右侧呈现的可选暗淡辅助标签
            // 行的一侧（例如，技术旁边的友好品牌名称
            // 型号 ID）。如果不存在，该行将降级为原始行
            // 单字符串布局。
            if (opt.agent) {
                const face = document.createElement('span');
                face.className = 'cfg-dropdown-item-face';
                face.innerHTML = agentAvatarHTML(opt.agent, 20);
                const labelEl = document.createElement('span');
                labelEl.className = 'cfg-dropdown-label';
                labelEl.textContent = opt.label;
                item.appendChild(face);
                item.appendChild(labelEl);
                // 呈现可选的尾随药丸（例如“默认”标记）
                // 名字后变暗。
                if (opt.badge) {
                    const badgeEl = document.createElement('span');
                    badgeEl.className = 'cfg-dropdown-badge';
                    badgeEl.textContent = opt.badge;
                    item.appendChild(badgeEl);
                }
            } else if (opt.hint) {
                const labelEl = document.createElement('span');
                labelEl.className = 'cfg-dropdown-label';
                labelEl.textContent = opt.label;
                const hintEl = document.createElement('span');
                hintEl.className = 'cfg-dropdown-hint';
                hintEl.textContent = opt.hint;
                item.appendChild(labelEl);
                item.appendChild(hintEl);
            } else {
                item.textContent = opt.label;
            }
            item.addEventListener('click', (e) => {
                e.stopPropagation();
                el._ddValue = opt.value;
                textEl.textContent = opt.label;
                // 现在选择了实际选项，删除静音占位符
                // 样式 - 否则所选标签保持灰色（在
                // 以占位符状态开始的下拉菜单，例如聊天
                // 后备选择器）。
                textEl.classList.remove('text-slate-400', 'dark:text-slate-500');
                paintFace(opt);
                menuEl.querySelectorAll('.cfg-dropdown-item').forEach(i => i.classList.remove('active'));
                item.classList.add('active');
                el.classList.remove('open');
                if (el._ddOnChange) el._ddOnChange(opt.value);
            });
            menuEl.appendChild(item);
        });
        const sel = options.find(o => o.value === el._ddValue);
        if (sel) {
            textEl.textContent = sel.label;
            paintFace(sel);
            textEl.classList.remove('text-slate-400', 'dark:text-slate-500');
        } else if (opts.placeholder && !el._ddValue) {
            // 尚未选择 - 以静音风格显示占位符。
            // 不要写入后备值，因此下拉菜单会保留
            // “未保存”直到用户明确选择。
            textEl.textContent = opts.placeholder;
            paintFace(null);
            textEl.classList.add('text-slate-400', 'dark:text-slate-500');
        } else {
            textEl.textContent = options[0] ? options[0].label : '--';
            paintFace(options[0]);
            textEl.classList.remove('text-slate-400', 'dark:text-slate-500');
            if (options[0]) el._ddValue = options[0].value;
        }
    }

    render();

    if (!el._ddBound) {
        selEl.addEventListener('click', (e) => {
            e.stopPropagation();
            document.querySelectorAll('.cfg-dropdown.open').forEach(d => { if (d !== el) d.classList.remove('open'); });
            const willOpen = !el.classList.contains('open');
            if (willOpen) {
                // 翻转控件上方的菜单，否则会出现这样的情况
                // 剪裁在视口底部（例如最后一个通道的
                // 配置下拉菜单位于窗口边缘附近）。
                const rect = el.getBoundingClientRect();
                const below = window.innerHeight - rect.bottom;
                const menuH = Math.min(menuEl.scrollHeight || 240, 280) + 8;
                el.classList.toggle('drop-up', below < menuH && rect.top > below);
            }
            el.classList.toggle('open');
        });
        el._ddBound = true;
    }
}

document.addEventListener('click', () => {
    document.querySelectorAll('.cfg-dropdown.open').forEach(d => d.classList.remove('open'));
});

function getDropdownValue(el) { return el._ddValue || ''; }

// --- 配置初始化 ---
function initConfigView(data) {
    configProviders = data.providers || {};
    configApiBases = data.api_bases || {};
    configApiKeys = data.api_keys || {};
    configCurrentModel = data.model || '';
    configReasoningByModel = data.reasoning_effort_by_model || {};
    cfgReasoningEffortValue = data.reasoning_effort || 'high';

    const providerEl = document.getElementById('cfg-provider');
    const providerOpts = Object.entries(configProviders).map(([pid, p]) => ({ value: pid, label: localizedLabel(p.label) }));

    // 如果启用了 use_linkai，则始终选择 linkai 作为提供者
    // 否则更喜欢配置中的 bot_type，回退到基于模型的检测
    const detected = data.use_linkai ? 'linkai'
        : (data.bot_type && configProviders[data.bot_type] ? data.bot_type : detectProvider(configCurrentModel));
    cfgProviderValue = detected || (providerOpts[0] ? providerOpts[0].value : '');

    initDropdown(providerEl, providerOpts, cfgProviderValue, onProviderChange);

    onProviderChange(cfgProviderValue);
    syncModelSelection(configCurrentModel);

    document.getElementById('cfg-max-tokens').value = data.agent_max_context_tokens || 50000;
    document.getElementById('cfg-max-turns').value = data.agent_max_context_turns || 20;
    document.getElementById('cfg-max-steps').value = data.agent_max_steps || 20;
    const thinkingEl = document.getElementById('cfg-enable-thinking');
    thinkingEl.checked = data.enable_thinking === true;
    if (!thinkingEl._cfgReasoningBound) {
        thinkingEl.addEventListener('change', syncReasoningEffortOptions);
        thinkingEl._cfgReasoningBound = true;
    }
    const customModelEl = document.getElementById('cfg-model-custom');
    if (customModelEl && !customModelEl._cfgReasoningBound) {
        customModelEl.addEventListener('input', () => {
            // 记住当前提供程序的类型自定义模型，以便
            // 提供商切换和切回不会丢失它。
            if (cfgModelValue === '__custom__') {
                configCustomModelByProvider[cfgProviderValue] = customModelEl.value.trim();
            }
            syncReasoningEffortOptions();
        });
        customModelEl._cfgReasoningBound = true;
    }
    syncReasoningEffortOptions();
    document.getElementById('cfg-subagent').checked = data.subagent_enabled !== false;
    document.getElementById('cfg-self-evolution').checked = data.self_evolution_enabled === true;

    // 反映当前的UI语言（已经解决，可能包括用户的
    // 选择器上的本地选择），以便它与右上角的切换保持同步。
    const langSel = document.getElementById('cfg-lang-select');
    if (langSel) {
        initDropdown(
            langSel,
            [{ value: 'zh', label: '简体中文' }, { value: 'zh-Hant', label: '繁體中文' }, { value: 'en', label: 'English' }],
            currentLang,
            (val) => setLanguage(val)
        );
    }

    // 新对话的默认权限模式。应用于镐，如
    // 语言选择器：卡的保存按钮属于密码字段，
    // 默默地等待保存的安全默认设置会比
    // 立即生效的一项。
    const permEl = document.getElementById('cfg-permission');
    if (permEl) {
        const offered = data.permission_modes && data.permission_modes.length
            ? data.permission_modes
            : Object.keys(PERMISSION_META);
        const permOpts = Object.keys(PERMISSION_META)
            .filter(mode => offered.includes(mode))
            .map(mode => ({ value: mode, label: t(PERMISSION_META[mode].key) }));
        initDropdown(permEl, permOpts, data.agent_permission_mode || 'full-access', saveGlobalPermission);
    }

    const pwdInput = document.getElementById('cfg-password');
    const maskedPwd = data.web_password_masked || '';
    pwdInput.value = maskedPwd;
    pwdInput.dataset.masked = maskedPwd ? '1' : '';
    pwdInput.dataset.maskedVal = maskedPwd;
    pwdInput.classList.toggle('cfg-key-masked', !!maskedPwd);

    if (maskedPwd) {
        pwdInput.placeholder = '••••••••';
    } else {
        pwdInput.placeholder = '';
    }

    if (!pwdInput._cfgBound) {
        pwdInput.addEventListener('focus', function() {
            if (this.dataset.masked === '1') {
                this.value = '';
                this.dataset.masked = '';
                this.classList.remove('cfg-key-masked');
            }
        });
        pwdInput.addEventListener('input', function() {
            this.dataset.masked = '';
        });
        pwdInput._cfgBound = true;
    }
}

function detectProvider(model) {
    if (!model) return Object.keys(configProviders)[0] || '';
    for (const [pid, p] of Object.entries(configProviders)) {
        if (pid === 'linkai') continue;
        if (p.models && p.models.includes(model)) return pid;
    }
    return Object.keys(configProviders)[0] || '';
}

function onProviderChange(pid) {
    cfgProviderValue = pid || getDropdownValue(document.getElementById('cfg-provider'));
    const p = configProviders[cfgProviderValue];
    if (!p) return;

    const customTip = document.getElementById('cfg-custom-tip');
    if (customTip) customTip.classList.toggle('hidden', cfgProviderValue !== 'custom');

    const modelEl = document.getElementById('cfg-model-select');
    const modelOpts = (p.models || []).map(m => ({ value: m, label: m }));
    modelOpts.push({ value: '__custom__', label: t('config_custom_option') });

    // 恢复用户之前为此提供程序键入的自定义模型
    // 会话（保存在 configCustomModelByProvider 中）。退回到第一个
    // 预设。对于没有预设模型的自定义提供者，选择器只有
    // “__custom__”条目，因此记住的值是其模型的唯一方式
    // 在提供商切换后仍然存在。
    const rememberedCustom = configCustomModelByProvider[cfgProviderValue];
    const initialModelValue = rememberedCustom
        ? '__custom__'
        : (modelOpts[0] ? modelOpts[0].value : '');

    initDropdown(modelEl, modelOpts, initialModelValue, onModelSelectChange);

    // API密钥
    const keyField = p.api_key_field;
    const keyWrap = document.getElementById('cfg-api-key-wrap');
    const keyInput = document.getElementById('cfg-api-key');

    // 只有 LinkAI（一个聚合平台）才能获得其控制台的链接
    // 管理聚合密钥；其他提供商在其网站上管理密钥。
    const cfgManageKey = document.getElementById('cfg-manage-key');
    if (cfgManageKey) cfgManageKey.classList.toggle('hidden', cfgProviderValue !== 'linkai');
    if (keyField) {
        keyWrap.classList.remove('hidden');
        keyInput.classList.add('cfg-key-masked');
        const maskedVal = configApiKeys[keyField] || '';
        keyInput.value = maskedVal;
        keyInput.dataset.field = keyField;
        keyInput.dataset.masked = maskedVal ? '1' : '';
        keyInput.dataset.maskedVal = maskedVal;
        const toggleIcon = document.querySelector('#cfg-api-key-toggle i');
        if (toggleIcon) toggleIcon.className = 'fas fa-eye text-xs';

        if (!keyInput._cfgBound) {
            keyInput.addEventListener('focus', function() {
                if (this.dataset.masked === '1') {
                    this.value = '';
                    this.dataset.masked = '';
                    this.classList.remove('cfg-key-masked');
                }
            });
            keyInput.addEventListener('blur', function() {
                if (!this.value.trim() && this.dataset.maskedVal) {
                    this.value = this.dataset.maskedVal;
                    this.dataset.masked = '1';
                    this.classList.add('cfg-key-masked');
                }
            });
            keyInput.addEventListener('input', function() {
                this.dataset.masked = '';
            });
            keyInput._cfgBound = true;
        }
    } else {
        keyWrap.classList.add('hidden');
        keyInput.value = '';
        keyInput.dataset.field = '';
    }

    // API库
    const apiBaseInput = document.getElementById('cfg-api-base');
    if (p.api_base_key) {
        document.getElementById('cfg-api-base-wrap').classList.remove('hidden');
        apiBaseInput.value = configApiBases[p.api_base_key] || p.api_base_default || '';
        // 提示版本路径尾部（例如 /v1），以便提醒用户
        // 包括它自己。我们不会自动重写服务器端的任何内容。
        apiBaseInput.placeholder = p.api_base_placeholder || 'https://...';
    } else {
        document.getElementById('cfg-api-base-wrap').classList.add('hidden');
        apiBaseInput.value = '';
        apiBaseInput.placeholder = 'https://...';
    }

    onModelSelectChange(initialModelValue, { restoredCustom: rememberedCustom });
    syncReasoningEffortOptions();
}

function onModelSelectChange(val, opts) {
    opts = opts || {};
    cfgModelValue = val || getDropdownValue(document.getElementById('cfg-model-select'));
    const customWrap = document.getElementById('cfg-model-custom-wrap');
    const customInput = document.getElementById('cfg-model-custom');
    if (cfgModelValue === '__custom__') {
        customWrap.classList.remove('hidden');
        // 当切换回提供商时，我们会恢复记住的值；
        // 否则，这是“自定义”的新选择，我们专注于输入。
        if (opts.restoredCustom) {
            customInput.value = opts.restoredCustom;
        } else {
            customInput.focus();
        }
    } else {
        customWrap.classList.add('hidden');
        customInput.value = '';
    }
    syncReasoningEffortOptions();
}

function syncModelSelection(model) {
    const p = configProviders[cfgProviderValue];
    if (!p) return;

    const modelEl = document.getElementById('cfg-model-select');
    if (p.models && p.models.includes(model)) {
        const modelOpts = (p.models || []).map(m => ({ value: m, label: m }));
        modelOpts.push({ value: '__custom__', label: t('config_custom_option') });
        initDropdown(modelEl, modelOpts, model, onModelSelectChange);
        cfgModelValue = model;
        document.getElementById('cfg-model-custom-wrap').classList.add('hidden');
    } else {
        cfgModelValue = '__custom__';
        const modelOpts = (p.models || []).map(m => ({ value: m, label: m }));
        modelOpts.push({ value: '__custom__', label: t('config_custom_option') });
        initDropdown(modelEl, modelOpts, '__custom__', onModelSelectChange);
        document.getElementById('cfg-model-custom-wrap').classList.remove('hidden');
        document.getElementById('cfg-model-custom').value = model;
        // 为每个提供者的内存添加种子，以便切换回来可以保留它。
        if (model) configCustomModelByProvider[cfgProviderValue] = model;
    }
    syncReasoningEffortOptions();
}

function syncReasoningEffortOptions() {
    const wrap = document.getElementById('cfg-reasoning-effort-wrap');
    const el = document.getElementById('cfg-reasoning-effort');
    if (!wrap || !el) return;

    const provider = configProviders[cfgProviderValue] || {};
    const selectedModel = getSelectedModel();
    const reasoningByModel = provider.reasoning_by_model || {};
    const reasoning = reasoningByModel[selectedModel] || provider.reasoning || {};
    const options = reasoning.supported ? (reasoning.options || []) : [];
    const thinkingEl = document.getElementById('cfg-enable-thinking');

    if (options.length) {
        const values = options.map(opt => opt.value);
        // 更喜欢这个模型自己节省的精力（每个模型配置），所以切换
        // 供应商从不重新解释为不同模型设置的值。关键是
        // 小写的模型名称，与后端解析路径匹配。
        const savedForModel = configReasoningByModel[`${cfgProviderValue}:${selectedModel.trim().toLowerCase()}`]
            || configReasoningByModel[cfgProviderValue + ':' + selectedModel];
        const saved = savedForModel || cfgReasoningEffortValue;
        // 当保存的值是时，回退到活动模型的本机枚举
        // 此处无效。即使隐藏也已解决，因此保存永远不会写入
        // 该模型的键下的另一个模型的枚举。
        cfgReasoningEffortValue = values.includes(saved) ? saved : (reasoning.default || options[0].value);
    }

    // 努力只会塑造思维过程，因此领域会跟随切换。
    if (!thinkingEl || !thinkingEl.checked || !options.length) {
        wrap.classList.add('hidden');
        return;
    }

    wrap.classList.remove('hidden');
    initDropdown(
        el,
        options.map(opt => ({ value: opt.value, label: opt.label || opt.value })),
        cfgReasoningEffortValue,
        (val) => { cfgReasoningEffortValue = val; }
    );
}

function getSelectedModel() {
    if (cfgModelValue === '__custom__') {
        return document.getElementById('cfg-model-custom').value.trim();
    }
    return cfgModelValue;
}

function toggleApiKeyVisibility() {
    const input = document.getElementById('cfg-api-key');
    const icon = document.querySelector('#cfg-api-key-toggle i');
    if (input.classList.contains('cfg-key-masked')) {
        input.classList.remove('cfg-key-masked');
        icon.className = 'fas fa-eye-slash text-xs';
    } else {
        input.classList.add('cfg-key-masked');
        icon.className = 'fas fa-eye text-xs';
    }
}

function showStatus(elId, msgKey, isError) {
    const el = document.getElementById(elId);
    el.textContent = t(msgKey);
    el.classList.toggle('text-red-500', !!isError);
    el.classList.toggle('text-primary-500', !isError);
    el.classList.remove('opacity-0');
    // 警告消息（错误）应保持可见，成功消息自动隐藏
    if (!isError) {
        setTimeout(() => el.classList.add('opacity-0'), 2500);
    }
}

function saveModelConfig() {
    const model = getSelectedModel();
    if (!model) return;

    const updates = { model: model };
    const p = configProviders[cfgProviderValue];
    updates.use_linkai = (cfgProviderValue === 'linkai');
    if (cfgProviderValue === 'linkai') {
        updates.bot_type = '';
    } else {
        updates.bot_type = cfgProviderValue;
    }
    if (p && p.api_base_key) {
        const base = document.getElementById('cfg-api-base').value.trim();
        if (base) updates[p.api_base_key] = base;
    }
    if (p && p.api_key_field) {
        const keyInput = document.getElementById('cfg-api-key');
        const rawVal = keyInput.value.trim();
        if (rawVal && keyInput.dataset.masked !== '1') {
            updates[p.api_key_field] = rawVal;
        }
    }

    const btn = document.getElementById('cfg-model-save');
    btn.disabled = true;
    fetch('/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ updates })
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'success') {
            configCurrentModel = model;
            if (data.applied) {
                const keyInput = document.getElementById('cfg-api-key');
                Object.entries(data.applied).forEach(([k, v]) => {
                    if (k === 'model') return;
                    if (k.includes('api_key')) {
                        const masked = v.length > 8
                            ? v.substring(0, 4) + '*'.repeat(v.length - 8) + v.substring(v.length - 4)
                            : v;
                        configApiKeys[k] = masked;
                        if (keyInput.dataset.field === k) {
                            keyInput.value = masked;
                            keyInput.dataset.masked = '1';
                            keyInput.dataset.maskedVal = masked;
                            keyInput.classList.add('cfg-key-masked');
                            const toggleIcon = document.querySelector('#cfg-api-key-toggle i');
                            if (toggleIcon) toggleIcon.className = 'fas fa-eye text-xs';
                        }
                    } else {
                        configApiBases[k] = v;
                    }
                });
            }
            showStatus('cfg-model-status', 'config_saved', false);
        } else {
            showStatus('cfg-model-status', 'config_save_error', true);
        }
    })
    .catch(() => showStatus('cfg-model-status', 'config_save_error', true))
    .finally(() => { btn.disabled = false; });
}

function saveAgentConfig() {
    const effortKey = `${cfgProviderValue}:${getSelectedModel().trim().toLowerCase()}`;
    const mergedEffortByModel = Object.assign({}, configReasoningByModel, { [effortKey]: cfgReasoningEffortValue });
    const updates = {
        agent_max_context_tokens: parseInt(document.getElementById('cfg-max-tokens').value) || 50000,
        agent_max_context_turns: parseInt(document.getElementById('cfg-max-turns').value) || 20,
        agent_max_steps: parseInt(document.getElementById('cfg-max-steps').value) || 20,
        enable_thinking: document.getElementById('cfg-enable-thinking').checked,
        // 坚持每个模型的努力（与现有地图合并，以便其他
        // 模型保存的工作在平面配置保存中幸存下来）。
        reasoning_effort_by_model: mergedEffortByModel,
        subagent_enabled: document.getElementById('cfg-subagent').checked,
        self_evolution_enabled: document.getElementById('cfg-self-evolution').checked,
    };

    const btn = document.getElementById('cfg-agent-save');
    btn.disabled = true;
    fetch('/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ updates })
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'success') {
            // 反映合并的地图，以便稍后的模型切换显示/使用
            // 刚刚保存的值而不是内存中陈旧的值。
            configReasoningByModel = mergedEffortByModel;
            showStatus('cfg-agent-status', 'config_saved', false);
        } else {
            showStatus('cfg-agent-status', 'config_save_error', true);
        }
    })
    .catch(() => showStatus('cfg-agent-status', 'config_save_error', true))
    .finally(() => { btn.disabled = false; });
}

// 保留实例范围的默认权限模式。从未固定的会话
// 他们自己遵循它，因此作曲家芯片随后被刷新。
function saveGlobalPermission(mode) {
    fetch('/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ updates: { agent_permission_mode: mode } })
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'success') {
            showStatus('cfg-password-status', 'config_saved', false);
            refreshSessionSettings();
        } else {
            showStatus('cfg-password-status', 'config_save_error', true);
        }
    })
    .catch(() => showStatus('cfg-password-status', 'config_save_error', true));
}

function savePasswordConfig() {
    const input = document.getElementById('cfg-password');
    if (input.dataset.masked === '1') {
        showStatus('cfg-password-status', 'config_saved', false);
        return;
    }
    const newPwd = input.value.trim();
    const btn = document.getElementById('cfg-password-save');
    btn.disabled = true;
    fetch('/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ updates: { web_password: newPwd } })
    })
    .then(r => r.json())
    .then(data => {
        console.log('[Password Config] Response:', data); // 调试
        if (data.status === 'success') {
            if (newPwd) {
                showStatus('cfg-password-status', 'config_password_changed', false);
                // 标记为屏蔽，因此用户需要重新输入才能再次更改
                input.dataset.masked = '1';
                input.dataset.maskedVal = newPwd;
                input.value = '••••••••';
                input.classList.add('cfg-key-masked');
                
                // 由于现已启用密码，因此显示注销按钮
                const logoutBtn = document.getElementById('logout-btn-header');
                if (logoutBtn) logoutBtn.classList.remove('hidden');
            } else {
                input.dataset.masked = '';
                input.dataset.maskedVal = '';
                input.classList.remove('cfg-key-masked');
                
                // 如果通过公共主机清除密码，则显示安全警告
                if (data.warning === 'password_cleared_with_public_host') {
                    showStatus('cfg-password-status', 'config_password_security_warning', true);
                } else {
                    showStatus('cfg-password-status', 'config_password_cleared', false);
                }
                
                const logoutBtn = document.getElementById('logout-btn-header');
                if (logoutBtn) logoutBtn.classList.add('hidden');
            }
        } else {
            showStatus('cfg-password-status', 'config_save_error', true);
        }
    })
    .catch(() => showStatus('cfg-password-status', 'config_save_error', true))
    .finally(() => { btn.disabled = false; });
}

function loadConfigView() {
    fetch('/config').then(r => r.json()).then(data => {
        if (data.status !== 'success') return;
        appConfig = data;
        initConfigView(data);
    }).catch(() => {});
}

function switchConfigTab(tab) {
    ['basic', 'models'].forEach(name => {
        document.getElementById(`config-tab-${name}`)?.classList.toggle('active', name === tab);
        document.getElementById(`config-panel-${name}`)?.classList.toggle('hidden', name !== tab);
    });
    if (tab === 'models') loadModelsView();
    // 返回 Basic 时重新拉取 /config：在模型上添加提供程序
    // 选项卡必须显示在基本主模型提供程序选择器中，无需手册
    // 页面刷新。 loadConfigView 从新的提供程序列表中重新呈现。
    if (tab === 'basic') loadConfigView();
}

// =====================================================================
// 技能视图
// =====================================================================
let toolsLoaded = false;

const TOOL_ICONS = {
    bash: 'fa-terminal',
    edit: 'fa-pen-to-square',
    read: 'fa-file-lines',
    write: 'fa-file-pen',
    ls: 'fa-folder-open',
    send: 'fa-paper-plane',
    web_search: 'fa-magnifying-glass',
    browser: 'fa-globe',
    env_config: 'fa-key',
    scheduler: 'fa-clock',
    memory_get: 'fa-brain',
    memory_search: 'fa-brain',
};

function getToolIcon(name) {
    return TOOL_ICONS[name] || 'fa-wrench';
}

function loadSkillsView() {
    loadToolsSection();
    loadSkillsSection();
}

function loadToolsSection() {
    if (toolsLoaded) return;
    const emptyEl = document.getElementById('tools-empty');
    const listEl = document.getElementById('tools-list');
    const badge = document.getElementById('tools-count-badge');

    fetch('/api/tools').then(r => r.json()).then(data => {
        if (data.status !== 'success') return;
        const tools = data.tools || [];
        emptyEl.classList.add('hidden');
        if (tools.length === 0) {
            emptyEl.classList.remove('hidden');
            emptyEl.innerHTML = `<span class="text-sm text-slate-400 dark:text-slate-500">${currentLang === 'zh' ? '暂无内置工具' : 'No built-in tools'}</span>`;
            return;
        }
        badge.textContent = tools.length;
        badge.classList.remove('hidden');
        listEl.innerHTML = '';
        tools.forEach(tool => {
            const card = document.createElement('div');
            card.className = 'bg-white dark:bg-[#1A1A1A] rounded-xl border border-slate-200 dark:border-white/10 p-4 flex items-start gap-3';
            card.innerHTML = `
                <div class="w-9 h-9 rounded-lg bg-blue-50 dark:bg-blue-900/20 flex items-center justify-center flex-shrink-0">
                    <i class="fas ${getToolIcon(tool.name)} text-blue-500 dark:text-blue-400 text-sm"></i>
                </div>
                <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2">
                        <span class="font-medium text-sm text-slate-700 dark:text-slate-200 font-mono">${escapeHtml(tool.name)}</span>
                    </div>
                    <p class="text-xs text-slate-400 dark:text-slate-500 mt-1 line-clamp-2">${escapeHtml(tool.description || '--')}</p>
                </div>`;
            listEl.appendChild(card);
        });
        listEl.classList.remove('hidden');
        toolsLoaded = true;
    }).catch(() => {
        emptyEl.classList.remove('hidden');
        emptyEl.innerHTML = `<span class="text-sm text-slate-400 dark:text-slate-500">${currentLang === 'zh' ? '加载失败' : 'Failed to load'}</span>`;
    });
}

function loadSkillsSection() {
    const emptyEl = document.getElementById('skills-empty');
    const listEl = document.getElementById('skills-list');
    const badge = document.getElementById('skills-count-badge');

    fetch('/api/skills').then(r => r.json()).then(data => {
        if (data.status !== 'success') return;
        const skills = data.skills || [];
        if (skills.length === 0) {
            const p = emptyEl.querySelector('p');
            if (p) p.textContent = currentLang === 'zh' ? '暂无技能' : 'No skills found';
            return;
        }
        badge.textContent = skills.length;
        badge.classList.remove('hidden');
        emptyEl.classList.add('hidden');
        listEl.innerHTML = '';

        skills.forEach(sk => {
            const card = document.createElement('div');
            card.className = 'bg-white dark:bg-[#1A1A1A] rounded-xl border border-slate-200 dark:border-white/10 '
                + 'p-4 flex items-start gap-3 transition-opacity cursor-pointer '
                + 'hover:border-slate-300 dark:hover:border-white/20';
            card.dataset.skillName = sk.name;
            card.dataset.skillDesc = sk.description || '';
            card.dataset.skillDisplayName = sk.display_name || '';
            card.dataset.enabled = sk.enabled ? '1' : '0';
            renderSkillCard(card, sk);
            listEl.appendChild(card);
        });
    }).catch(() => {});
}

function renderSkillCard(card, sk) {
    const enabled = sk.enabled;
    const iconColor = enabled ? 'text-primary-400' : 'text-slate-300 dark:text-slate-600';
    const trackClass = enabled
        ? 'bg-primary-400'
        : 'bg-slate-200 dark:bg-slate-700';
    const thumbTranslate = enabled ? 'translate-x-3' : 'translate-x-0.5';
    card.innerHTML = `
        <div class="w-9 h-9 rounded-lg bg-amber-50 dark:bg-amber-900/20 flex items-center justify-center flex-shrink-0">
            <i class="fas fa-bolt ${iconColor} text-sm"></i>
        </div>
        <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2 mb-1">
                <span class="font-medium text-sm text-slate-700 dark:text-slate-200 truncate flex-1">${escapeHtml(sk.display_name || sk.name)}</span>
                <button
                    role="switch"
                    data-skill-switch
                    aria-checked="${enabled}"
                    class="relative inline-flex h-4 w-7 flex-shrink-0 cursor-pointer rounded-full transition-colors duration-200 ease-in-out focus:outline-none ${trackClass}"
                    title="${enabled ? (currentLang === 'zh' ? '点击禁用' : 'Click to disable') : (currentLang === 'zh' ? '点击启用' : 'Click to enable')}"
                >
                    <span class="inline-block h-3 w-3 mt-0.5 rounded-full bg-white shadow transform transition-transform duration-200 ease-in-out ${thumbTranslate}"></span>
                </button>
            </div>
            <p class="text-xs text-slate-400 dark:text-slate-500 line-clamp-2">${escapeHtml(sk.description || '--')}</p>
        </div>`;

    // 绑定在这里而不是写入上面的标记中：技能名称出现
    // 从它自己的正面内容开始，并且包含引用的内容会脱离
    // 内联 onclick 属性。
    card.title = t('skill_open_hint');
    card.onclick = () => openSkillFile(sk.name);
    const sw = card.querySelector('[data-skill-switch]');
    if (sw) {
        sw.onclick = (e) => {
            e.stopPropagation();
            toggleSkill(sk.name, enabled);
        };
    }
}

function toggleSkill(name, currentlyEnabled) {
    const action = currentlyEnabled ? 'close' : 'open';
    const card = document.querySelector(`[data-skill-name="${CSS.escape(name)}"]`);
    if (card) card.style.opacity = '0.5';

    fetch('/api/skills', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, name })
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'success') {
            if (card) {
                card.dataset.enabled = currentlyEnabled ? '0' : '1';
                card.style.opacity = '1';
                renderSkillCard(card, {
                    name: name,
                    description: card.dataset.skillDesc || '',
                    display_name: card.dataset.skillDisplayName || '',
                    enabled: !currentlyEnabled,
                });
            }
        } else {
            if (card) card.style.opacity = '1';
            alert(currentLang === 'zh' ? '操作失败，请稍后再试' : 'Operation failed, please try again');
        }
    })
    .catch(() => {
        if (card) card.style.opacity = '1';
        alert(currentLang === 'zh' ? '操作失败，请稍后再试' : 'Operation failed, please try again');
    });
}

// ---------------------------------------------------------------------
// 技能查看器/编辑器
// ---------------------------------------------------------------------

/**
 * Skills are addressed by name, not by path: which file a name resolves to is
 * the loader's business, and a builtin skill lives outside the workspace that
 * the file APIs are confined to.
 */
async function skillReadContent(name) {
    const res = await fetch(`/api/skills/content?name=${encodeURIComponent(name)}`);
    const data = await res.json();
    if (data.status !== 'success') throw new Error(data.message || 'read failed');
    return data;
}

/** Save a skill's definition. Returns the raw response, a conflict included. */
async function skillWriteContent(name, content, expectedMtime) {
    const res = await fetch('/api/skills/content', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name, content: content, expected_mtime: expectedMtime }),
    });
    return res.json();
}

/** The i18n key explaining why a skill cannot be edited, or null if it can. */
function skillReadonlyReason(data) {
    if (data.editable) return null;
    // 不是 `source === 'builtin'`：内置技能的工作区副本读取
    // 返回为 `custom` 并且仍然被拒绝，所以服务器是这么说的。
    if (data.ships_with_install) return 'skill_builtin_readonly';
    return docUneditableReason(data);
}

const skillEditor = createDocEditor({
    body: () => document.getElementById('skill-viewer-content'),
    buttons: () => ({
        edit: document.getElementById('skill-btn-edit'),
        save: document.getElementById('skill-btn-save'),
        cancel: document.getElementById('skill-btn-cancel'),
    }),
    read: (doc) => skillReadContent(doc.name),
    write: (doc, content, mtime) => skillWriteContent(doc.name, content, mtime),
    render: (doc) => docRenderBody('skill-viewer-content', doc.content),
    canEdit: (doc) => !doc.readonlyKey,
    refusal: skillReadonlyReason,
    onState: (state) => docRenderTitle('skill-viewer-title', skillEditor.current()?.name, state),
});

function openSkillFile(name) {
    skillReadContent(name).then(data => {
        const badge = document.getElementById('skill-viewer-readonly');
        const readonlyKey = skillReadonlyReason(data);
        if (badge) {
            badge.classList.toggle('hidden', !readonlyKey);
            if (readonlyKey) {
                // 保持 data-i18n 同步，以便语言切换重新翻译它。
                badge.dataset.i18n = readonlyKey;
                badge.textContent = t(readonlyKey);
                badge.title = t(readonlyKey);
            }
        }
        document.getElementById('skills-panel-list').classList.add('hidden');
        document.getElementById('skills-panel-viewer').classList.remove('hidden');
        skillEditor.open({
            name: data.name || name,
            content: data.content || '',
            readonlyKey: readonlyKey,
        });
    }).catch(e => _wsToast(`${t('skill_load_failed')}: ${e.message}`));
}

function closeSkillViewer() {
    if (!skillEditor.guard(closeSkillViewer)) return;
    resetSkillViewer();
    // 保存的编辑可以更改 frontmatter 中的名称和描述，因此
    // 该面板后面的卡片可能已过时。
    loadSkillsSection();
}

/** Drop the viewer and show the list, without asking about unsaved edits. */
function resetSkillViewer() {
    skillEditor.forget();
    document.getElementById('skills-panel-viewer')?.classList.add('hidden');
    document.getElementById('skills-panel-list')?.classList.remove('hidden');
}

// =====================================================================
// 内存视图
// =====================================================================
let memoryPage = 1;
let memoryCategory = 'memory';   // '记忆' | “进化”
const memoryPageSize = 10;

function switchMemoryTab(tab) {
    document.querySelectorAll('.memory-tab').forEach(el => el.classList.remove('active'));
    document.getElementById('memory-tab-' + tab).classList.add('active');
    // “梦想”选项卡现在显示自我进化日志（与梦想日记合并）。
    memoryCategory = tab === 'dreams' ? 'evolution' : 'memory';
    loadMemoryView(1);
}

function loadMemoryView(page) {
    page = page || 1;
    memoryPage = page;
    const agent = viewingMemoryAgentId();
    fetch(`/api/memory?page=${page}&page_size=${memoryPageSize}&category=${memoryCategory}&agent_id=${encodeURIComponent(agent || '')}`).then(r => r.json()).then(data => {
        if (data.status !== 'success') return;
        const emptyEl = document.getElementById('memory-empty');
        const listEl = document.getElementById('memory-list');
        const files = data.list || [];
        const total = data.total || 0;

        if (total === 0) {
            const emptyIcon = emptyEl.querySelector('i');
            const emptyTitle = emptyEl.querySelector('p');
            if (memoryCategory === 'evolution') {
                emptyIcon.className = 'fas fa-seedling text-emerald-400 text-xl';
                emptyTitle.textContent = currentLang === 'zh' ? '暂无进化记录' : 'No evolution records yet';
            } else {
                emptyIcon.className = 'fas fa-brain text-purple-400 text-xl';
                emptyTitle.textContent = currentLang === 'zh' ? '暂无记忆文件' : 'No memory files';
            }
            emptyEl.classList.remove('hidden');
            listEl.classList.add('hidden');
            return;
        }
        emptyEl.classList.add('hidden');
        listEl.classList.remove('hidden');

        const tbody = document.getElementById('memory-table-body');
        tbody.innerHTML = '';
        files.forEach(f => {
            const tr = document.createElement('tr');
            tr.className = 'border-b border-slate-100 dark:border-white/5 hover:bg-slate-50 dark:hover:bg-white/5 cursor-pointer transition-colors';
            // 在合并的进化选项卡中，按其自己的来源解析每个文件
            // （进化日志与梦想日记位于不同的目录中）。
            const fileCategory = (f.type === 'dream' || f.type === 'evolution') ? f.type : memoryCategory;
            tr.onclick = () => openMemoryFile(f.filename, fileCategory);
            let typeLabel;
            if (f.type === 'global') {
                typeLabel = '<span class="px-2 py-0.5 rounded-full text-xs bg-primary-50 dark:bg-primary-900/30 text-primary-600 dark:text-primary-400">Global</span>';
            } else if (f.type === 'evolution') {
                typeLabel = '<span class="px-2 py-0.5 rounded-full text-xs bg-emerald-50 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400">Evolution</span>';
            } else if (f.type === 'dream') {
                typeLabel = '<span class="px-2 py-0.5 rounded-full text-xs bg-violet-50 dark:bg-violet-900/30 text-violet-600 dark:text-violet-400">Dream</span>';
            } else {
                typeLabel = '<span class="px-2 py-0.5 rounded-full text-xs bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400">Daily</span>';
            }
            const sizeStr = f.size < 1024 ? f.size + ' B' : (f.size / 1024).toFixed(1) + ' KB';
            tr.innerHTML = `
                <td class="px-4 py-3 text-sm font-mono text-slate-700 dark:text-slate-200">${escapeHtml(f.filename)}</td>
                <td class="px-4 py-3 text-sm">${typeLabel}</td>
                <td class="px-4 py-3 text-sm text-slate-500 dark:text-slate-400">${sizeStr}</td>
                <td class="px-4 py-3 text-sm text-slate-500 dark:text-slate-400">${escapeHtml(f.updated_at)}</td>`;
            tbody.appendChild(tr);
        });

        // 分页
        const totalPages = Math.ceil(total / memoryPageSize);
        const pagEl = document.getElementById('memory-pagination');
        if (totalPages <= 1) { pagEl.innerHTML = ''; return; }
        let pagHtml = `<span>${page} / ${totalPages}</span><div class="flex gap-2">`;
        if (page > 1) pagHtml += `<button onclick="loadMemoryView(${page - 1})" class="px-3 py-1 rounded-lg border border-slate-200 dark:border-white/10 hover:bg-slate-100 dark:hover:bg-white/10 text-xs">Prev</button>`;
        if (page < totalPages) pagHtml += `<button onclick="loadMemoryView(${page + 1})" class="px-3 py-1 rounded-lg border border-slate-200 dark:border-white/10 hover:bg-slate-100 dark:hover:bg-white/10 text-xs">Next</button>`;
        pagHtml += '</div>';
        pagEl.innerHTML = pagHtml;
    }).catch(() => {});
}

// =====================================================================
// 文档查看器（内存文件、技能定义）
// =====================================================================

/**
 * Read one file's text for an editor. Throws on an API error so the editor can
 * report it.
 *
 * No session is passed on purpose. Memory files are anchored to the agent's
 * state root, and a session with a project open would resolve the same relative
 * path against that project instead.
 */
async function docReadFile(relPath) {
    const res = await fetch(`/api/workspace/read?path=${encodeURIComponent(relPath)}`);
    const data = await res.json();
    if (data.status !== 'success') throw new Error(data.message || 'read failed');
    return data;
}

/** Save one file's text. Returns the raw response, a conflict included. */
async function docWriteFile(relPath, content, expectedMtime) {
    const res = await fetch('/api/workspace/write', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: relPath, content: content, expected_mtime: expectedMtime }),
    });
    return res.json();
}

/** Render Markdown into a viewer body. */
function docRenderBody(id, content) {
    const el = document.getElementById(id);
    if (!el) return;
    el.innerHTML = renderMarkdown(content || '');
    applyHighlighting(el);
}

/** Put a document's name in a viewer title, with a dot while it is unsaved. */
function docRenderTitle(id, name, state) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = name || '';
    if (state && state.dirty) {
        el.insertAdjacentHTML('beforeend', ' <span class="doc-dirty-dot">•</span>');
    }
}

/**
 * Ask about any unsaved document edit before something tears its page down.
 *
 * @param {function} next - retried once the user agrees to lose the edits.
 * @returns {boolean} true when nothing is at stake and the caller may proceed.
 */
function docGuardUnsaved(next) {
    return memoryEditor.guard(next) && skillEditor.guard(next);
}

const memoryEditor = createDocEditor({
    body: () => document.getElementById('memory-viewer-content'),
    buttons: () => ({
        edit: document.getElementById('memory-btn-edit'),
        save: document.getElementById('memory-btn-save'),
        cancel: document.getElementById('memory-btn-cancel'),
    }),
    read: (doc) => docReadFile(doc.relPath),
    write: (doc, content, mtime) => docWriteFile(doc.relPath, content, mtime),
    render: (doc) => docRenderBody('memory-viewer-content', doc.content),
    onState: (state) => docRenderTitle('memory-viewer-title', memoryEditor.current()?.filename, state),
});

function openMemoryFile(filename, category) {
    category = category || 'memory';
    const agent = viewingMemoryAgentId();
    fetch(`/api/memory/content?filename=${encodeURIComponent(filename)}&category=${category}&agent_id=${encodeURIComponent(agent || '')}`).then(r => r.json()).then(data => {
        if (data.status !== 'success') return;
        document.getElementById('memory-panel-list').classList.add('hidden');
        document.getElementById('memory-panel-viewer').classList.remove('hidden');
        memoryEditor.open({
            filename: filename,
            // 内存 API 报告文件位于工作区下的位置
            // 根；编辑器在那里解决它而不是重建
            // 文件名加类别的路径。
            relPath: data.rel_path || filename,
            content: data.content || '',
        });
    }).catch(() => {});
}

function closeMemoryViewer() {
    if (!memoryEditor.guard(closeMemoryViewer)) return;
    memoryEditor.forget();
    document.getElementById('memory-panel-viewer').classList.add('hidden');
    document.getElementById('memory-panel-list').classList.remove('hidden');
    // 保存更改了列表显示的大小和时间戳。
    loadMemoryView(memoryPage);
}

// 重新加载或关闭选项卡会删除未保存的编辑。所有浏览器允许
// 这是它自己的通用提示，它仍然比默默地丢失文本要好。
window.addEventListener('beforeunload', (e) => {
    if (!memoryEditor.isDirty() && !skillEditor.isDirty()) return;
    e.preventDefault();
    e.returnValue = '';
});

// =====================================================================
// 自定义确认对话框
// =====================================================================
function showConfirmDialog({ title, message, okText, cancelText, onConfirm, hideCancel }) {
    const overlay = document.getElementById('confirm-dialog-overlay');
    document.getElementById('confirm-dialog-title').textContent = title || '';
    document.getElementById('confirm-dialog-message').textContent = message || '';
    document.getElementById('confirm-dialog-ok').textContent = okText || 'OK';
    const cancelBtn = document.getElementById('confirm-dialog-cancel');
    cancelBtn.textContent = cancelText || t('channels_cancel');
    cancelBtn.classList.toggle('hidden', !!hideCancel);

    function cleanup() {
        overlay.classList.add('hidden');
        okBtn.removeEventListener('click', onOk);
        cancelBtn.removeEventListener('click', onCancel);
        overlay.removeEventListener('click', onOverlayClick);
    }
    function onOk() { cleanup(); if (onConfirm) onConfirm(); }
    function onCancel() { cleanup(); }
    function onOverlayClick(e) { if (e.target === overlay) cleanup(); }

    const okBtn = document.getElementById('confirm-dialog-ok');
    okBtn.addEventListener('click', onOk);
    cancelBtn.addEventListener('click', onCancel);
    overlay.addEventListener('click', onOverlayClick);
    overlay.classList.remove('hidden');
}

// =====================================================================
// 模型视图
// =====================================================================
// 模型页面上呈现的功能卡。订单事宜——主要型号
// 首先是因为它传递地决定视觉和图像的默认值。
// 图标调色板按功能系列分组：
//   - 聊天 → 主要（品牌绿色；“主要”功能）
//   - 视觉+图像→蓝色（一切视觉）
//   - asr + tts → amber（所有音频）
//   - 嵌入→紫色（向量）
//   - 搜索→橙色（检索）
// 每张卡都使用显式的 `iconClass` 字符串，因此 Tailwind 的 CDN JIT 可以
// 查看字面类名 - 动态 `bg-${color}-50` 字符串不会
// 被可靠地拾取。
const MODELS_CAPABILITY_DEFS = [
    { id: 'chat',      icon: 'fa-microchip',        editable: true,  needsModel: true,  toggleable: false, titleKey: 'models_capability_chat',      descKey: 'models_capability_chat_desc',
      iconChip: 'bg-primary-50 dark:bg-primary-900/30',  iconGlyph: 'text-primary-500' },
    // 注意：聊天后备卡故意不是顶级卡。它是一个
    // 很少接触安全网，因此它位于主装置上的一个小齿轮后面
    // 模型卡（参见 renderCapabilityHeaderTag / openChatFallbackModal）和
    // 在重用相同拾取器机械的模式中进行编辑。
    { id: 'vision',    icon: 'fa-eye',              editable: true,  needsModel: true,  titleKey: 'models_capability_vision',    descKey: 'models_capability_vision_desc',
      iconChip: 'bg-blue-50 dark:bg-blue-900/30',        iconGlyph: 'text-blue-500' },
    { id: 'image',     icon: 'fa-image',            editable: true,  needsModel: true,  titleKey: 'models_capability_image',     descKey: 'models_capability_image_desc',
      iconChip: 'bg-blue-50 dark:bg-blue-900/30',        iconGlyph: 'text-blue-500' },
    { id: 'asr',       icon: 'fa-microphone',       editable: true,  needsModel: true,  titleKey: 'models_capability_asr',       descKey: 'models_capability_asr_desc',
      iconChip: 'bg-amber-50 dark:bg-amber-900/30',      iconGlyph: 'text-amber-500' },
    { id: 'tts',       icon: 'fa-volume-high',      editable: true,  needsModel: true,  titleKey: 'models_capability_tts',       descKey: 'models_capability_tts_desc',
      iconChip: 'bg-amber-50 dark:bg-amber-900/30',      iconGlyph: 'text-amber-500' },
    { id: 'embedding', icon: 'fa-vector-square',    editable: true,  needsModel: true,  titleKey: 'models_capability_embedding', descKey: 'models_capability_embedding_desc',
      iconChip: 'bg-purple-50 dark:bg-purple-900/30',    iconGlyph: 'text-purple-500' },
    { id: 'search',    icon: 'fa-magnifying-glass', editable: true,  needsModel: false, titleKey: 'models_capability_search',    descKey: 'models_capability_search_desc',
      iconChip: 'bg-orange-50 dark:bg-orange-900/30',    iconGlyph: 'text-orange-500' },
];

// 提供商徽标：当 static/logos/<id>.svg 下存在真正的 SVG 时，我们使用
// 它；否则我们就会退回到中性的字母组合芯片。已获取 SVG
// 通过带有隐藏 onerror 的 <img> ，因此当文件打开时布局保持稳定
// 缺席。其标记以纯（或接近纯）黑色呈现的供应商是
// MODELS_PROVIDER_LOGO_DARK_INVERT 中列出 — 对于这些，我们应用 CSS
// 在深色模式下反转滤镜，使字形相对于 #1A1A1A 保持可见。
const MODELS_PROVIDER_LOGO_PATH = 'assets/logos';
const MODELS_PROVIDER_LOGO_DARK_INVERT = new Set([
    'openai',     // 黑色字标
    'moonshot',   // 深色字母组合
    'zhipu',      // 深色字母组合
    'custom',     // 单色滑块字形
]);

let modelsState = { providers: [], capabilities: {} };

// 一次性：{capabilityId,providerId}在模型重新加载之前存储，
// 由 renderCapabilityBody 使用来预选刚刚配置的供应商。
let pendingCapabilitySelection = null;

// `opts.preserveScroll` 保持页面的垂直滚动位置
// 刷新。我们在取消隐藏加载骨架（它会折叠）之前捕获它
// 内容高度为零）并在安装新内容后恢复它。
// 当用户从功能内部配置供应商时，这一点很重要
// 卡的下拉菜单 - 不保存，保存后重新加载会将它们弹开
// 返回页面顶部，远离他们正在配置的卡。
function loadModelsView(opts) {
    const loading = document.getElementById('models-loading');
    const content = document.getElementById('models-content');
    if (!loading || !content) return;
    const preserveScroll = !!(opts && opts.preserveScroll);
    // 模型窗格有自己的可滚动容器；占领其位置
    // （不是 window.scrollY），这样我们就可以将用户准确地放回到原来的位置。
    const scroller = document.querySelector('#view-config .overflow-y-auto');
    const savedTop = preserveScroll && scroller ? scroller.scrollTop : null;

    loading.classList.remove('hidden');
    content.classList.add('hidden');

    fetch('/api/models').then(r => r.json()).then(data => {
        if (data.status !== 'success') {
            loading.innerHTML = `<span class="text-sm text-red-400">${escapeHtml(data.message || 'Failed to load')}</span>`;
            return;
        }
        modelsState.providers = data.providers || [];
        modelsState.capabilities = data.capabilities || {};
        renderModelsView();
        loading.classList.add('hidden');
        content.classList.remove('hidden');
        if (savedTop !== null && scroller) {
            // 等待一帧让新布局稳定下来，否则
            // 恢复的scrollTop 会捕捉到之前（较小的）最大值。
            requestAnimationFrame(() => { scroller.scrollTop = savedTop; });
        }
    }).catch(err => {
        loading.innerHTML = `<span class="text-sm text-red-400">${escapeHtml(String(err))}</span>`;
    });
}

function renderModelsView() {
    const container = document.getElementById('models-content');
    container.innerHTML = '';
    container.appendChild(renderVendorsSection());
    MODELS_CAPABILITY_DEFS.forEach(def => container.appendChild(renderCapabilityCard(def)));
}

// 当提供商卡是扩展自定义卡之一（兼容 OpenAI）时为真
// 提供商 (id "custom:<id>") — 在供应商网格中与内置一起显示
// 供应商，但通过专用的定制提供商模式进行编辑。
function isCustomProviderCard(p) {
    return !!(p && p.is_custom && p.custom_name);
}

// ---------- 供应商部分（第 1 层）-----------------------------------

function renderVendorsSection() {
    const wrap = document.createElement('div');
    wrap.className = 'bg-white dark:bg-[#1A1A1A] rounded-xl border border-slate-200 dark:border-white/10 p-6';

    // 自定义提供程序在创建后始终显示（即使没有 api 密钥，
    // 例如本地 vLLM/Ollama 端点）；配置时会显示内置供应商。
    const configured = modelsState.providers.filter(p => p.configured || isCustomProviderCard(p));

    const header = `
        <div class="flex items-start gap-3 mb-5">
            <div class="w-9 h-9 rounded-lg bg-primary-50 dark:bg-primary-900/30 flex items-center justify-center flex-shrink-0">
                <i class="fas fa-key text-primary-500 text-sm"></i>
            </div>
            <div class="flex-1 min-w-0">
                <h3 class="font-semibold text-slate-800 dark:text-slate-100">${t('models_section_vendors')}</h3>
                <p class="text-xs text-slate-500 dark:text-slate-400 mt-0.5">${t('models_section_vendors_desc')}</p>
            </div>
        </div>`;

    let body;
    if (configured.length === 0) {
        body = `
            <div class="flex flex-col items-center justify-center py-8 px-4 rounded-lg border border-dashed border-slate-200 dark:border-white/10">
                <p class="text-sm text-slate-500 dark:text-slate-400 text-center">${t('models_not_configured')}</p>
                <button onclick="openVendorModal('')"
                        class="mt-3 px-3 py-1.5 rounded-lg text-xs font-medium bg-primary-50 dark:bg-primary-900/30 text-primary-600 dark:text-primary-400 hover:bg-primary-100 dark:hover:bg-primary-900/50 cursor-pointer transition-colors">
                    <i class="fas fa-plus text-[10px] mr-1"></i>${t('models_add_vendor')}
                </button>
            </div>`;
    } else {
        // 现有供应商作为芯片，加上尾随的“添加”图块，这样就形成了新的
        // 一旦至少有一个内置或自定义提供程序，仍然可以添加
        // 已经配置（否则添加条目仅显示在空的
        // 状态）。 openVendorModal('') 打开选择器 → 内置或自定义。
        const addTile = `
            <button onclick="openVendorModal('')"
                    class="flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg border border-dashed
                           border-slate-300 dark:border-white/15 text-slate-500 dark:text-slate-400
                           hover:border-primary-400 hover:text-primary-500 cursor-pointer transition-colors text-sm">
                <i class="fas fa-plus text-[11px]"></i>${t('models_add_vendor')}
            </button>`;
        body = `<div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
            ${configured.map(renderVendorChip).join('')}
            ${addTile}
        </div>`;
    }

    wrap.innerHTML = header + body;
    return wrap;
}

function renderVendorChip(p) {
    // 此处故意不显示被屏蔽的 API 密钥；显示
    // 在编辑模式内，使芯片保持整洁且可扫描。
    // 自定义提供商打开其专用模式（名称+基础+密钥）；
    // 它们的 ID 是服务器生成的十六进制，可以安全内联。
    const onclick = isCustomProviderCard(p)
        ? `openCustomProviderModal('${escapeHtml(p.custom_id)}')`
        : `openVendorModal('${escapeHtml(p.id)}')`;
    return `
        <button onclick="${onclick}"
                class="group flex items-center gap-3 px-3 py-2.5 rounded-lg border border-slate-200 dark:border-white/10
                       bg-slate-50 dark:bg-white/5 hover:border-primary-300 dark:hover:border-primary-500/50
                       cursor-pointer transition-colors duration-150 text-left">
            ${renderProviderLogo(p, 28)}
            <span class="flex-1 min-w-0 text-sm font-medium text-slate-800 dark:text-slate-100 truncate">${escapeHtml(localizedLabel(p.label))}</span>
            <i class="fas fa-pen-to-square text-[11px] text-slate-400 dark:text-slate-500 group-hover:text-primary-500 transition-colors"></i>
        </button>`;
}

// 为提供商呈现统一风格的徽标。首先尝试 SVG 资源；如果
// 它 404s <img> 通过 onerror 将自身交换为字母组合回退。
function renderProviderLogo(p, sizePx) {
    const initial = (localizedLabel(p.label) || p.id || '?').slice(0, 1).toUpperCase();
    const sz = sizePx || 32;
    const url = `${MODELS_PROVIDER_LOGO_PATH}/${encodeURIComponent(p.id)}.svg`;
    const fallbackId = `pl-${p.id}-${Math.random().toString(36).slice(2, 8)}`;
    const imgClass = MODELS_PROVIDER_LOGO_DARK_INVERT.has(p.id)
        ? 'absolute inset-0 m-auto provider-logo-img provider-logo-invert-dark'
        : 'absolute inset-0 m-auto provider-logo-img';
    return `
        <span class="relative flex items-center justify-center rounded-lg bg-slate-100 dark:bg-white/10
                     text-slate-600 dark:text-slate-300 flex-shrink-0 overflow-hidden"
              style="width:${sz}px;height:${sz}px;">
            <span id="${fallbackId}" class="text-xs font-bold">${escapeHtml(initial)}</span>
            <img src="${url}" alt="" aria-hidden="true"
                 class="${imgClass}"
                 style="width:${Math.round(sz * 0.65)}px;height:${Math.round(sz * 0.65)}px;"
                 onload="(function(el){var f=document.getElementById('${fallbackId}');if(f)f.style.display='none';})(this)"
                 onerror="this.remove();">
        </span>`;
}

function getCustomProviderCards() {
    return modelsState.providers.filter(isCustomProviderCard);
}

// ---------- 能力卡（第 2 层）---------------------------------

function renderCapabilityCard(def) {
    const cap = modelsState.capabilities[def.id] || {};
    const wrap = document.createElement('div');
    wrap.className = 'bg-white dark:bg-[#1A1A1A] rounded-xl border border-slate-200 dark:border-white/10 p-6';
    wrap.id = `models-card-${def.id}`;

    const headerRight = renderCapabilityHeaderTag(def, cap);

    wrap.innerHTML = `
        <div class="flex items-start gap-3 mb-5">
            <div class="w-9 h-9 rounded-lg ${def.iconChip} flex items-center justify-center flex-shrink-0">
                <i class="fas ${def.icon} ${def.iconGlyph} text-sm"></i>
            </div>
            <div class="flex-1 min-w-0">
                <h3 class="font-semibold text-slate-800 dark:text-slate-100">${t(def.titleKey)}</h3>
                <p class="text-xs text-slate-500 dark:text-slate-400 mt-0.5">${t(def.descKey)}</p>
            </div>
            ${headerRight}
        </div>
        <div class="space-y-4" data-cap-body="${def.id}"></div>`;

    const body = wrap.querySelector(`[data-cap-body="${def.id}"]`);
    renderCapabilityBody(def, cap, body);
    return wrap;
}

function renderCapabilityHeaderTag(def, cap) {
    // 主模型卡带有一个打开聊天后备的小齿轮
    // 模态。后备措施是一个很少触及的安全网，因此它不会受到影响
    // 卡体；仅当齿轮打开时，齿轮旁边才会出现一个徽章，因此
    // 一眼就能发现主动后备。
    if (def.id === 'chat') {
        const fb = modelsState.capabilities.chat_fallback || {};
        // 也反映状态的单个入口点：绿色+“on”标签
        // 启用回退时，静音 + 关闭时“配置”标签。
        const on = !!fb.enabled;
        const cls = on
            ? 'text-primary-600 dark:text-primary-300 bg-primary-50 dark:bg-primary-900/30 hover:bg-primary-100 dark:hover:bg-primary-900/50'
            : 'text-slate-500 dark:text-slate-400 hover:text-primary-600 dark:hover:text-primary-300 hover:bg-slate-100 dark:hover:bg-white/5';
        const label = on ? t('models_fallback_badge_on') : t('models_fallback_config');
        return `
            <button type="button" onclick="openChatFallbackModal()"
                    title="${escapeHtml(t('models_fallback_config_tip'))}"
                    class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs flex-shrink-0
                           cursor-pointer transition-colors ${cls}">
                <i class="fas fa-shield-halved text-[11px]"></i>${label}
            </button>`;
    }
    return '';
}

// 聊天回退是在模式中配置的，而不是作为顶级卡配置的
// （这是一个很少有人触及的安全网）。模态体重用完全相同
// 拾取器机械作为功能卡 — `renderCapabilityBody` 键每隔
// 元素关闭 `cap-chat_fallback-*`，所以我们给它一个带有该 id 的 def 并让
// 现有的提供程序/模型/切换/保存代码运行不变。没有这样的卡
// 在 MODELS_CAPABILITY_DEFS 中注册，因此 id 永远不会发生冲突。
const CHAT_FALLBACK_DEF = {
    id: 'chat_fallback', editable: true, needsModel: true, toggleable: true,
    titleKey: 'models_fallback_modal_title', descKey: 'models_capability_chat_fallback_desc',
};

// 通过 id 解析能力定义。聊天回退是故意缺席的
// 来自 MODELS_CAPABILITY_DEFS （它以模态形式呈现，而不是作为卡片呈现），因此
// 共享保存/切换处理程序也可以在这里查找。
function capabilityDefById(capId) {
    if (capId === 'chat_fallback') return CHAT_FALLBACK_DEF;
    return MODELS_CAPABILITY_DEFS.find(d => d.id === capId);
}

function openChatFallbackModal() {
    closeChatFallbackModal(); // 切勿堆叠两个

    const overlay = document.createElement('div');
    overlay.id = 'chat-fallback-modal-overlay';
    overlay.className = 'fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4';
    overlay.innerHTML = `
        <div class="w-full max-w-md rounded-2xl bg-white dark:bg-[#1A1A1A] border border-slate-200 dark:border-white/10 shadow-xl">
            <div class="flex items-start gap-3 px-6 pt-6 pb-4 border-b border-slate-100 dark:border-white/5">
                <div class="w-9 h-9 rounded-lg bg-primary-50 dark:bg-primary-900/30 flex items-center justify-center flex-shrink-0">
                    <i class="fas fa-shield-halved text-primary-500 text-sm"></i>
                </div>
                <div class="flex-1 min-w-0">
                    <h3 class="font-semibold text-slate-800 dark:text-slate-100">${t('models_fallback_modal_title')}</h3>
                    <p class="text-xs text-slate-500 dark:text-slate-400 mt-1 leading-relaxed">${t('models_fallback_modal_desc')}</p>
                </div>
                <button type="button" onclick="closeChatFallbackModal()"
                        class="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 cursor-pointer transition-colors flex-shrink-0">
                    <i class="fas fa-xmark"></i>
                </button>
            </div>
            <div class="px-6 py-5 space-y-4" data-cap-body="chat_fallback"></div>
        </div>`;

    // 单击背景时关闭（但在对话框内单击时不关闭）。
    overlay.addEventListener('click', (e) => { if (e.target === overlay) closeChatFallbackModal(); });

    document.body.appendChild(overlay);

    const cap = modelsState.capabilities.chat_fallback || {};
    const body = overlay.querySelector('[data-cap-body="chat_fallback"]');
    renderCapabilityBody(CHAT_FALLBACK_DEF, cap, body);
}

function closeChatFallbackModal() {
    const overlay = document.getElementById('chat-fallback-modal-overlay');
    if (overlay) overlay.remove();
}

function _searchProviderLabel(cap, providerId) {
    const list = (cap && cap.providers) || [];
    const hit = list.find(p => p.id === providerId);
    return hit ? localizedLabel(hit.label) : providerId;
}

// 搜索卡主体：策略选择器+（固定时）提供商选择器+a
// 状态行显示哪些提供程序已准备就绪以及如何添加
// 失踪的。四个后端中的三个依赖于模型供应商
// 凭证（zhipu / qianfan / linkai）； bocha 拥有自己的密钥
// tools.web_search 并获得自己的最小凭证模式。
function renderSearchCapability(def, cap, body) {
    const providers = cap.providers || [];
    const configuredIds = cap.configured_providers || [];
    const hasAny = configuredIds.length > 0;
    const strategy = cap.strategy || 'auto';

    body.innerHTML = `
        <div>
            <label class="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-1.5">${t('models_search_strategy_label')}</label>
            <div id="cap-search-strategy" class="cfg-dropdown" tabindex="0">
                <div class="cfg-dropdown-selected">
                    <span class="cfg-dropdown-text">--</span>
                    <i class="fas fa-chevron-down cfg-dropdown-arrow"></i>
                </div>
                <div class="cfg-dropdown-menu"></div>
            </div>
        </div>
        <div id="cap-search-provider-wrap" class="hidden">
            <label class="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-1.5">${t('models_provider')}</label>
            <div id="cap-search-provider" class="cfg-dropdown" tabindex="0">
                <div class="cfg-dropdown-selected">
                    <span class="cfg-dropdown-text">--</span>
                    <i class="fas fa-chevron-down cfg-dropdown-arrow"></i>
                </div>
                <div class="cfg-dropdown-menu"></div>
            </div>
        </div>
        <div id="cap-search-summary"></div>
        <div class="flex items-center justify-end gap-3 pt-1">
            <span id="cap-search-status" class="text-xs text-primary-500 opacity-0 transition-opacity duration-300"></span>
            <button onclick="saveSearchCapability()"
                    class="px-4 py-2 rounded-lg bg-primary-500 hover:bg-primary-600 text-white text-sm font-medium
                           cursor-pointer transition-colors duration-150 disabled:opacity-50 disabled:cursor-not-allowed">
                ${t('save')}
            </button>
        </div>
    `;

    // 策略下拉菜单 - 当没有提供者配置策略时
    // value is meaningless, so we show a "待配置" placeholder instead of
    // 默认选择。一旦任何提供者被配置保存
    // 策略（或“自动”）成为活动值。
    initDropdown(
        body.querySelector('#cap-search-strategy'),
        [
            { value: 'auto',  label: t('models_strategy_auto'),         hint: t('models_search_strategy_auto_hint') },
            { value: 'fixed', label: t('models_search_strategy_fixed'), hint: t('models_search_strategy_fixed_hint') },
        ],
        hasAny ? strategy : '',
        (value) => _onSearchStrategyChange(cap, value, body),
        hasAny ? null : { placeholder: t('models_pending_config') },
    );

    // 提供者下拉菜单——仅填充已配置的提供者；
    // 未配置的无法固定（它们会默默地回退）。
    const provOpts = configuredIds.map(id => ({
        value: id,
        label: _searchProviderLabel(cap, id),
    }));
    if (provOpts.length === 0) provOpts.push({ value: '', label: '--' });
    initDropdown(
        body.querySelector('#cap-search-provider'),
        provOpts,
        cap.fixed_provider || configuredIds[0] || '',
        () => {},
    );

    _renderSearchSummary(body, cap);
    _setSearchProviderPickerVisible(body, strategy === 'fixed' && hasAny);
}

function _onSearchStrategyChange(cap, value, body) {
    const configuredIds = cap.configured_providers || [];
    _setSearchProviderPickerVisible(body, value === 'fixed' && configuredIds.length > 0);
}

function _setSearchProviderPickerVisible(body, visible) {
    const wrap = body.querySelector('#cap-search-provider-wrap');
    if (!wrap) return;
    if (visible) wrap.classList.remove('hidden');
    else wrap.classList.add('hidden');
}

// 搜索摘要行：仅列出配置的提供程序 + 尾随“+
// 添加”按钮。未配置的后端被隐藏——用户可以从中选择一个
// 单击“添加”时的一个小选择器。空状态面同样添加
// 按钮作为主要 CTA。
function _renderSearchSummary(body, cap) {
    const host = body.querySelector('#cap-search-summary');
    if (!host) return;
    const providers = cap.providers || [];
    const configured = providers.filter(p => p.configured);
    const missing = providers.filter(p => !p.configured);

    const addBtn = missing.length
        ? `<button type="button" id="cap-search-add-btn"
                  class="inline-flex items-center gap-1 px-2 py-0.5 text-[11px] rounded-md cursor-pointer
                         bg-slate-100 dark:bg-white/5 text-slate-500 dark:text-slate-400
                         hover:bg-slate-200 dark:hover:bg-white/10 transition-colors">
              <i class="fas fa-plus text-[10px]"></i>${t('models_search_add_provider')}
           </button>`
        : '';

    if (configured.length === 0) {
        host.innerHTML = `
            <div class="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
                <i class="fas fa-circle-info text-[10px] text-amber-500"></i>
                <span>${t('models_search_none_configured')}</span>
                ${addBtn}
            </div>
        `;
    } else {
        const chips = configured.map(p => `
            <button type="button" data-search-edit-provider="${p.id}"
                    title="${t('models_search_edit_hint')}"
                    class="inline-flex items-center gap-1 px-2 py-0.5 text-[11px] rounded-md cursor-pointer
                           bg-emerald-50 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400
                           hover:bg-emerald-100 dark:hover:bg-emerald-900/50 transition-colors">
                <i class="fas fa-check text-[10px]"></i>${escapeHtml(localizedLabel(p.label))}
            </button>
        `).join('');
        host.innerHTML = `
            <div class="flex items-center flex-wrap gap-2 text-xs text-slate-500 dark:text-slate-400">
                <span>${t('models_search_available_label')}</span>
                ${chips}
                ${addBtn}
            </div>
        `;
    }

    const addBtnEl = host.querySelector('#cap-search-add-btn');
    if (addBtnEl) {
        addBtnEl.addEventListener('click', (ev) => {
            ev.preventDefault();
            openSearchAddProviderPicker(missing);
        });
    }
    host.querySelectorAll('[data-search-edit-provider]').forEach(el => {
        el.addEventListener('click', (ev) => {
            ev.preventDefault();
            const pid = el.getAttribute('data-search-edit-provider');
            const meta = (cap.providers || []).find(p => p.id === pid);
            _launchSearchProviderConfig(pid, meta);
        });
    });
}

// Two-step add flow: click "+ 添加厂商" -> chooser dialog -> per-provider
// 凭证编辑器。 Bocha 登陆专用按键模态；其他人
// 搭载现有的供应商凭证模式。
function openSearchAddProviderPicker(missingProviders) {
    if (!missingProviders || missingProviders.length === 0) return;
    if (missingProviders.length === 1) {
        _launchSearchProviderConfig(missingProviders[0].id);
        return;
    }

    const existing = document.getElementById('search-add-modal');
    if (existing) existing.remove();

    const rows = missingProviders.map(p => `
        <button type="button" data-pid="${p.id}"
                class="w-full flex items-center justify-between px-3 py-2.5 rounded-lg cursor-pointer
                       bg-slate-50 dark:bg-white/5 hover:bg-slate-100 dark:hover:bg-white/10
                       text-sm text-slate-700 dark:text-slate-200 transition-colors">
            <span>${escapeHtml(localizedLabel(p.label))}</span>
            <i class="fas fa-chevron-right text-[10px] text-slate-400"></i>
        </button>
    `).join('');

    const modal = document.createElement('div');
    modal.id = 'search-add-modal';
    modal.className = 'fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm';
    modal.innerHTML = `
        <div class="bg-white dark:bg-[#1A1A1A] rounded-xl border border-slate-200 dark:border-white/10
                    w-full max-w-md mx-4 p-6 shadow-xl">
            <h3 class="text-lg font-semibold text-slate-800 dark:text-slate-100 mb-1">${t('models_search_add_provider')}</h3>
            <p class="text-xs text-slate-500 dark:text-slate-400 mb-4">${t('models_search_add_desc')}</p>
            <div class="space-y-2">${rows}</div>
            <div class="flex items-center justify-end mt-5">
                <button type="button" onclick="document.getElementById('search-add-modal').remove()"
                        class="px-3 py-1.5 rounded-md text-sm text-slate-600 dark:text-slate-300
                               hover:bg-slate-100 dark:hover:bg-white/5 transition-colors">
                    ${t('cancel')}
                </button>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
    modal.querySelectorAll('[data-pid]').forEach(el => {
        el.addEventListener('click', () => {
            const pid = el.getAttribute('data-pid');
            modal.remove();
            _launchSearchProviderConfig(pid);
        });
    });
}

function _launchSearchProviderConfig(providerId, providerMeta) {
    if (providerId === 'bocha' || providerId === 'anysearch' || providerId === 'serply') {
        openSearchKeyModal(providerId, providerMeta);
    } else {
        openVendorModal(providerId, () => loadModelsView({ preserveScroll: true }));
    }
}

function saveSearchCapability() {
    const strategyDd = document.getElementById('cap-search-strategy');
    const providerDd = document.getElementById('cap-search-provider');
    const strategy = strategyDd ? getDropdownValue(strategyDd) : 'auto';
    const provider = (strategy === 'fixed' && providerDd) ? getDropdownValue(providerDd) : '';

    fetch('/api/models', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            action: 'set_capability',
            capability: 'search',
            strategy,
            provider,
        }),
    }).then(r => r.json()).then(data => {
        if (data.status === 'success') {
            showStatus('cap-search-status', 'models_save_success', false);
            setTimeout(() => loadModelsView({ preserveScroll: true }), 400);
        } else {
            showStatus('cap-search-status', 'models_save_failed', true);
        }
    }).catch(() => showStatus('cap-search-status', 'models_save_failed', true));
}

// 最小 bocha API 密钥模式。重用现有的供应商模式标记
// 助手会很好，但 bocha 不在 PROVIDER_MODELS 中（它不是
// 模型供应商），所以我们渲染一个小的专用对话框。
// 对于拥有自己密钥的搜索供应商。

function openSearchKeyModal(providerId, providerMeta) {
    const existing = document.getElementById('search-key-modal');
    if (existing) existing.remove();

    let masked = (providerMeta && providerMeta.api_key_masked) || '';
    if (!masked) {
        const searchCap = (modelsState && modelsState.capabilities && modelsState.capabilities.search) || {};
        const bocha = (searchCap.providers || []).find(p => p.id === providerId);
        if (bocha && bocha.api_key_masked) masked = bocha.api_key_masked;
    }
    const hasKey = !!masked;
    const clearBtnHtml = hasKey
        ? `<button type="button" id="search-key-clear"
                  class="px-3 py-1.5 rounded-md text-xs text-red-500 dark:text-red-400
                         hover:bg-red-50 dark:hover:bg-red-900/20 cursor-pointer transition-colors">
              ${t('models_clear_credential')}
           </button>`
        : '';

    const modal = document.createElement('div');
    modal.id = 'search-key-modal';
    modal.className = 'fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm';
    modal.innerHTML = `
        <div id="search-key-modal-card"
             class="bg-white dark:bg-[#1A1A1A] rounded-xl border border-slate-200 dark:border-white/10
                    w-full max-w-md mx-4 p-6 shadow-xl">
            <h3 class="text-lg font-semibold text-slate-800 dark:text-slate-100 mb-1">${t('models_search_' + providerId + '_title')}</h3>
            <p class="text-xs text-slate-500 dark:text-slate-400 mb-4">${t('models_search_' + providerId + '_desc')}</p>
            <label class="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-1.5">API Key</label>
            <input id="search-key-input" type="text" autocomplete="off" data-1p-ignore data-lpignore="true"
                   class="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600
                          bg-slate-50 dark:bg-white/5 text-sm text-slate-800 dark:text-slate-100
                          focus:outline-none focus:border-primary-500 font-mono ${hasKey ? 'cfg-key-masked' : ''}"
                   value="${escapeHtml(masked)}"
                   data-masked="${hasKey ? '1' : ''}"
                   placeholder="sk-..." />
            <div class="flex items-center justify-between gap-3 mt-5">
                <div>${clearBtnHtml}</div>
                <div class="flex items-center gap-3">
                    <button type="button" onclick="document.getElementById('search-key-modal').remove()"
                            class="px-3 py-1.5 rounded-md text-sm text-slate-600 dark:text-slate-300
                                   hover:bg-slate-100 dark:hover:bg-white/5 transition-colors">
                        ${t('cancel')}
                    </button>
                    <button type="button" onclick="_saveSearchKey('${providerId}')"
                            class="px-4 py-1.5 rounded-md bg-primary-500 hover:bg-primary-600 text-white text-sm font-medium
                                   cursor-pointer transition-colors">
                        ${t('save')}
                    </button>
                </div>
            </div>
        </div>
    `;
    document.body.appendChild(modal);

    // 用户开始编辑后立即重置屏蔽哨兵，以便保存
    // 处理程序可以区分“保留现有密钥”和“输入新密钥”。
    const input = document.getElementById('search-key-input');
    if (input) {
        const unmask = () => {
            if (input.dataset.masked === '1') {
                input.value = '';
                input.dataset.masked = '';
                input.classList.remove('cfg-key-masked');
            }
        };
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Tab' || e.key === 'Escape') return;
            unmask();
        });
        input.addEventListener('paste', unmask);
        if (!hasKey) setTimeout(() => input.focus(), 50);
    }
    const clearBtn = document.getElementById('search-key-clear');
    if (clearBtn) clearBtn.addEventListener('click', () => _clearSearchKey(providerId));

    modal.addEventListener('mousedown', (e) => {
        if (e.target === modal) modal.remove();
    });
    const onKey = (e) => {
        if (e.key === 'Escape') {
            modal.remove();
            document.removeEventListener('keydown', onKey);
        }
    };
    document.addEventListener('keydown', onKey);
}

function _saveSearchKey(providerId) {
    const input = document.getElementById('search-key-input');
    if (!input) return;
    // 未触及的屏蔽值 => 不请求更改；默默地关闭。
    if (input.dataset.masked === '1') {
        const modal = document.getElementById('search-key-modal');
        if (modal) modal.remove();
        return;
    }
    const apiKey = input.value.trim();
    if (!apiKey) {
        input.focus();
        return;
    }
    fetch('/api/models', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'set_search_credential', provider: providerId, api_key: apiKey }),
    }).then(r => r.json()).then(data => {
        if (data.status === 'success') {
            const modal = document.getElementById('search-key-modal');
            if (modal) modal.remove();
            loadModelsView({ preserveScroll: true });
        }
    });
}

function _clearSearchKey(providerId) {
    fetch('/api/models', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'set_search_credential', provider: providerId, api_key: '' }),
    }).then(r => r.json()).then(data => {
        if (data.status === 'success') {
            const modal = document.getElementById('search-key-modal');
            if (modal) modal.remove();
            loadModelsView({ preserveScroll: true });
        }
    });
}

function renderCapabilityBody(def, cap, body) {
    if (def.id === 'search') {
        renderSearchCapability(def, cap, body);
        return;
    }

    // 可编辑卡：提供商下拉菜单 + （可选）模型下拉菜单 + 保存行
    const providerOpts = buildCapabilityProviderOptions(def, cap);
    const providerHtml = `
        <div>
            <label class="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-1.5">${t('models_provider')}</label>
            <div id="cap-${def.id}-provider" class="cfg-dropdown" tabindex="0">
                <div class="cfg-dropdown-selected">
                    <span class="cfg-dropdown-text">--</span>
                    <i class="fas fa-chevron-down cfg-dropdown-arrow"></i>
                </div>
                <div class="cfg-dropdown-menu"></div>
            </div>
        </div>`;

    // 模型选择器容器始终被发出，因此提供者更改
    // 处理程序可以显示/隐藏它；对于 `auto` 功能，它开始隐藏并且
    // 通过 setCapabilityModelPickerVisible 进行切换。
    const modelHtml = def.needsModel ? `
        <div id="cap-${def.id}-model-wrap">
            <label class="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-1.5">${t('models_model')}</label>
            <div id="cap-${def.id}-model" class="cfg-dropdown" tabindex="0">
                <div class="cfg-dropdown-selected">
                    <span class="cfg-dropdown-text">--</span>
                    <i class="fas fa-chevron-down cfg-dropdown-arrow"></i>
                </div>
                <div class="cfg-dropdown-menu"></div>
            </div>
            <div id="cap-${def.id}-model-custom-wrap" class="mt-2 hidden">
                <input id="cap-${def.id}-model-custom" type="text"
                       class="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600
                              bg-slate-50 dark:bg-white/5 text-sm text-slate-800 dark:text-slate-100
                              focus:outline-none focus:border-primary-500 font-mono transition-colors"
                       placeholder="custom model name">
            </div>
        </div>` : '';

    const dimHtml = (def.id === 'embedding' && cap.current_dim) ? `
        <p class="text-xs text-slate-400 dark:text-slate-500">
            <i class="fas fa-cube text-[10px] mr-1"></i>${t('models_dim_label')}: <span class="font-mono">${cap.current_dim}</span>
        </p>` : '';

    // 选择加入功能在选择器上方有一个开/关开关。一切
    // 关闭时它的下面是隐藏的，因此禁用的回退看起来永远不会像
    // 未配置的——它根本不是设置的一部分。
    const toggleHtml = def.toggleable ? `
        <div id="cap-${def.id}-toggle-wrap" class="flex items-center justify-between gap-3">
            <label class="text-sm font-medium text-slate-600 dark:text-slate-400">${t('models_fallback_enable')}</label>
            <button type="button" id="cap-${def.id}-toggle" role="switch"
                    aria-checked="${cap.enabled ? 'true' : 'false'}"
                    onclick="toggleCapabilityEnabled('${def.id}')"
                    class="relative inline-flex h-5 w-9 flex-shrink-0 items-center rounded-full transition-colors cursor-pointer ${cap.enabled ? 'bg-primary-500' : 'bg-slate-200 dark:bg-slate-700'}">
                <span class="inline-block h-3.5 w-3.5 rounded-full bg-white shadow transition-transform ${cap.enabled ? 'translate-x-[18px]' : 'translate-x-[3px]'}"></span>
            </button>
        </div>` : '';

    // 页脚布局：一个“提示槽”（稍后由 renderCapabilityHints 填充）
    // 自动模式卡）位于左侧，而状态 + 保存保持锚定
    // 右边的。将它们保持在同一行意味着保存按钮拥抱
    // 输入上面的内容，而不是通过单独的提示行向下推。
    const footer = `
        <div class="flex items-center justify-between gap-3 pt-1">
            <div data-cap-hint="${def.id}" class="flex-1 min-w-0"></div>
            <div class="flex items-center gap-3 flex-shrink-0">
                <span id="cap-${def.id}-status" class="text-xs text-primary-500 opacity-0 transition-opacity duration-300"></span>
                <button onclick="saveCapability('${def.id}')"
                        class="px-4 py-2 rounded-lg bg-primary-500 hover:bg-primary-600 text-white text-sm font-medium
                               cursor-pointer transition-colors duration-150 disabled:opacity-50 disabled:cursor-not-allowed">
                    ${t('save')}
                </button>
            </div>
        </div>`;

    // 选择器位于自己的包装器中，因此禁用的选择加入功能可以
    // 将它们作为一个组隐藏（切换按钮本身在上方保持可见）。的
    // 包装器带有自己的 `space-y-4` 因为主体的 `space-y-4` 仅
    // 适用于*直接*子项：没有它，提供者/模型行将
    // 相互折叠（以及它们上面的标签）。
    const pickersHtml = `<div id="cap-${def.id}-pickers" class="space-y-4">${providerHtml + modelHtml + dimHtml}</div>`;
    body.innerHTML = toggleHtml + pickersHtml + footer;

    // TTS：在提供商上方安装回复模式；将关闭模式切换推迟到最后。
    if (def.id === 'tts') {
        renderVoiceReplyMode(body, cap.reply_mode || 'off', { skipVisibilityToggle: true });
        // 语音音色选择器取决于提供商+型号；通过回调重建。
        const modelWrap = body.querySelector(`#cap-${def.id}-model-wrap`);
        if (modelWrap) {
            const voiceWrap = document.createElement('div');
            voiceWrap.id = `cap-${def.id}-voice-wrap`;
            voiceWrap.innerHTML = `
                <label class="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-1.5">${t('models_voice')}</label>
                <div id="cap-${def.id}-voice" class="cfg-dropdown" tabindex="0">
                    <div class="cfg-dropdown-selected">
                        <span class="cfg-dropdown-text">--</span>
                        <i class="fas fa-chevron-down cfg-dropdown-arrow"></i>
                    </div>
                    <div class="cfg-dropdown-menu"></div>
                </div>
                <div id="cap-${def.id}-voice-custom-wrap" class="hidden mt-2">
                    <input id="cap-${def.id}-voice-custom" type="text"
                           class="w-full px-3 py-2 text-sm rounded-md border border-slate-200 dark:border-slate-700
                                  bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-200
                                  placeholder:text-slate-400 dark:placeholder:text-slate-500
                                  focus:outline-none focus:ring-2 focus:ring-primary-500"
                           placeholder="voice id" />
                </div>
            `;
            modelWrap.parentNode.insertBefore(voiceWrap, modelWrap.nextSibling);
        }
    }

    // `body` 仍然与 `document` 分离；本地范围查找。
    const provDd = body.querySelector(`#cap-${def.id}-provider`);
    // 在交给通用 initDropdown 助手之前剥离私有字段。
    const ddOpts = providerOpts.map(o => ({ value: o.value, label: o.label }));

    let pendingProvider = null;
    if (pendingCapabilitySelection
            && pendingCapabilitySelection.capabilityId === def.id
            && providerOpts.some(o => o.value === pendingCapabilitySelection.providerId)) {
        pendingProvider = pendingCapabilitySelection.providerId;
        pendingCapabilitySelection = null;
    }

    // 自动策略 => 选择空哨兵。 `suggested_provider`
    // 是仅 UI 预选（在用户单击“保存”之前不会保留）。
    // 没有当前 + 无建议 => 使用占位符保持未选中状态。
    //
    // Pending-config 优先于“自动”和“选择提供商”：
    // 当不存在真正的（非哨兵）配置选项时，浮出水面
    // “auto”或“pick”会误导用户——没有什么可以自动路由的
    // to or pick from. Force a "待配置" placeholder instead so all
    // 功能在新环境中表现一致。
    const hasConfiguredOpt = providerOpts.some(o => !o._isAuto && o._configured);
    const noSelectionAndNoHint = !cap.current_provider && !cap.suggested_provider;
    let initialProviderValue;
    let dropdownPlaceholder = null;
    if (!hasConfiguredOpt) {
        initialProviderValue = '';
        dropdownPlaceholder = { placeholder: t('models_pending_config') };
    } else {
        initialProviderValue = pendingProvider
            ? pendingProvider
            : ((cap.strategy === 'auto' && capabilitySupportsAuto(def.id))
                ? ''
                : (cap.current_provider
                    || cap.suggested_provider
                    || (noSelectionAndNoHint ? '' : (ddOpts[0] && ddOpts[0].value))
                    || ''));
        if (noSelectionAndNoHint) {
            dropdownPlaceholder = { placeholder: t('models_pick_provider') };
        }
    }
    // 播种“最后一次切换前活跃的提供商”跟踪器，以便
    // 第一个供应商切换仍然可以隐藏初始供应商的自定义模型。
    capabilityLastProviderId[def.id] = initialProviderValue;
    // 如果最初选择的型号是定制型号，请记住它
    // 初始提供商，因此切换后也可以保留它。
    if (initialProviderValue && cap.current_model) {
        const provList = (cap.provider_models && cap.provider_models[initialProviderValue])
            || (initialProviderValue.startsWith('custom:') && cap.provider_models && cap.provider_models['custom'])
            || [];
        const presetValues = provList.map(e => (typeof e === 'string' ? e : e.value));
        if (!presetValues.includes(cap.current_model)) {
            capabilityCustomModelMemory[`${def.id}:${initialProviderValue}`] = cap.current_model;
        }
    }
    initDropdown(
        provDd,
        ddOpts,
        initialProviderValue,
        (value) => onCapabilityProviderChange(def, value, body),
        dropdownPlaceholder,
    );
    decorateCapabilityProviderDropdown(def, provDd, providerOpts);

    if (def.needsModel) {
        rebuildCapabilityModelDropdown(def, initialProviderValue, cap.current_model || '', body);
        // 嵌入：在未选择提供程序时隐藏模型选择器。
        const showModel = def.id === 'embedding' ? initialProviderValue !== '' :
            (initialProviderValue !== '' || !capabilitySupportsAuto(def.id));
        setCapabilityModelPickerVisible(def, showModel, body);
    }

    if (def.id === 'tts') {
        rebuildCapabilityVoiceDropdown(
            initialProviderValue,
            cap.current_voice || '',
            body,
            cap.current_model || ''
        );
    }

    // 在操作页脚之前插入自动/路由器挂起提示横幅。
    renderCapabilityHints(def, cap, body, initialProviderValue);

    // 选择加入功能在禁用时开始崩溃，因此不活动
    // 回退读作“关闭”，而不是半配置的功能。
    if (def.toggleable) {
        _setCapabilityPickersVisible(def, body, !!cap.enabled);
    }

    if (def.id === 'tts') {
        _setTtsConfigVisible(body, (cap.reply_mode || 'off') !== 'off');
    }
}

// TTS 回复策略下拉列表（关闭/voice_if_voice/始终）。坚持
// 改变。关闭时，隐藏 TTS 卡的其余部分。
function renderVoiceReplyMode(host, currentMode, options) {
    options = options || {};
    const opts = [
        { value: 'off',            label: t('voice_reply_off') },
        { value: 'voice_if_voice', label: t('voice_reply_if_voice') },
        { value: 'always',         label: t('voice_reply_always') },
    ];
    const wrap = document.createElement('div');
    wrap.id = 'voice-reply-mode-wrap';
    wrap.innerHTML = `
        <label class="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-1.5">${t('voice_reply_mode_label')}</label>
        <div id="voice-reply-mode-dd" class="cfg-dropdown" tabindex="0">
            <div class="cfg-dropdown-selected">
                <span class="cfg-dropdown-text">--</span>
                <i class="fas fa-chevron-down cfg-dropdown-arrow"></i>
            </div>
            <div class="cfg-dropdown-menu"></div>
        </div>
    `;
    host.prepend(wrap);

    const dd = wrap.querySelector('#voice-reply-mode-dd');
    const valid = ['off', 'voice_if_voice', 'always'];
    const initial = valid.includes(currentMode) ? currentMode : 'off';
    if (!options.skipVisibilityToggle) _setTtsConfigVisible(host, initial !== 'off');
    initDropdown(dd, opts, initial, (mode) => {
        if (!valid.includes(mode)) return;
        _setTtsConfigVisible(host, mode !== 'off');
        fetch('/api/models', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'set_voice_reply_mode', mode }),
        })
            .then(r => r.json())
            .then(data => {
                if (data && data.status === 'success') {
                    _ttsReadyPromise = null;  // 强制重新探测下一个气泡
                }
            })
            .catch(() => {});
    });
}

// 显示/隐藏回复模式下拉列表下方 TTS 卡中的所有内容。
function _setTtsConfigVisible(host, visible) {
    if (!host) return;
    Array.from(host.children).forEach((child) => {
        if (child.id === 'voice-reply-mode-wrap') return;
        child.classList.toggle('hidden', !visible);
    });
}

// 切换包装器可见性而不是重新渲染，以便下拉状态得以保留。
function setCapabilityModelPickerVisible(def, visible, scope) {
    const root = scope || document;
    const wrap = root.querySelector(`#cap-${def.id}-model-wrap`);
    if (!wrap) return;
    wrap.classList.toggle('hidden', !visible);
}

function renderCapabilityHints(def, cap, body, currentProvider) {
    // 处于“自动”模式的功能会在右侧显示后备提示
    // 在输入下方，以便用户始终知道实际会受到什么打击。的
    // 图像卡还会显示“路由器挂起”警告，直到
    // 独立调度员着陆。
    // 提示槽与页脚行中的保存按钮位于同一位置
    // （请参阅 renderCapabilityBody），以便保存按钮保持靠近
    // 上面的输入。我们只是重写槽的innerHTML——清空它
    // 当卡离开自动模式时，或呈现一行提示时
    // 它处于自动模式。
    const slot = body.querySelector(`[data-cap-hint="${def.id}"]`);
    if (!slot) return;
    slot.innerHTML = '';

    if (currentProvider !== '' || !capabilitySupportsAuto(def.id)) return;

    // 该提示反映了运行时在自动模式下实际选择的内容
    // 模式。 Fallback_provider/model 在后端预先计算（请参阅
    // _predict_vision_auto、_predict_image_auto），这样我们就可以信任它们
    // 这里无需重新实现提供商链。
    const fbProv = cap.fallback_provider || '';
    const fbModel = cap.fallback_model || '';
    if (!fbProv && !fbModel) return;
    // 显示供应商的显示标签（例如“LinkAI”）而不是原始标签
    // id（“linkai”）当我们知道它时。当
    // 提供商不在我们的供应商表中（罕见）。
    const provMeta = modelsState.providers.find(p => p.id === fbProv);
    const fbProvLabel = (provMeta && localizedLabel(provMeta.label)) || fbProv;
    const fbText = fbModel ? `${fbProvLabel} / ${fbModel}` : fbProvLabel;
    slot.innerHTML = `
        <p class="flex items-center gap-1.5 text-xs text-slate-400 dark:text-slate-500 min-w-0">
            <i class="fas fa-circle-info text-[10px] flex-shrink-0"></i>
            <span class="flex-shrink-0">${t('models_auto_using')}</span>
            <span class="font-mono text-slate-500 dark:text-slate-400 truncate">${escapeHtml(fbText)}</span>
        </p>`;
}

function buildCapabilityProviderOptions(def, cap) {
    // 在功能下拉列表中显示所有供应商，以便用户一目了然
    // 谁已配置（绿色勾号）和谁未配置（灰点，单击进行设置
    // 上）。列表顺序将已配置的供应商放在第一位；单击
    // 未配置的行会就地打开供应商模式。 ASR/TTS 引擎
    // 不被PROVIDER_MODELS（azure/baidu/google等）跟踪的被处理
    // “始终可用”——没有凭证门。
    const knownProviderMap = {};
    modelsState.providers.forEach(p => { knownProviderMap[p.id] = p; });

    const explicitList = cap.providers && cap.providers.length ? cap.providers : null;
    let providerIds = explicitList ? explicitList.slice() : modelsState.providers.map(p => p.id);
    if (cap.current_provider && !providerIds.includes(cap.current_provider)) {
        providerIds = [cap.current_provider, ...providerIds];
    }

    const opts = providerIds.map(pid => {
        const meta = knownProviderMap[pid];
        const tracked = !!meta;
        const configured = !tracked || !!meta.configured;
        return {
            value: pid,
            label: (meta && localizedLabel(meta.label)) || pid,
            _tracked: tracked,
            _configured: configured,
        };
    });

    opts.sort((a, b) => {
        if (a._configured === b._configured) return 0;
        return a._configured ? -1 : 1;
    });

    // 具有后备（“自动”）策略的功能将其暴露为哨兵
    // 选项固定到列表顶部。我们使用空字符串作为自动
    // 值，以便现有的保存处理程序将其原封不动地传播到
    // backend，它将“”解释为“回退到主模型”。
    // 当没有配置真正的供应商时跳过哨兵 - “auto”将
    // route to nothing useful and the renderer will show "待配置" instead.
    const hasAnyConfigured = opts.some(o => o._configured);
    if ((cap.strategy === 'auto' || cap.strategy === 'specified') && hasAnyConfigured) {
        if (capabilitySupportsAuto(def.id)) {
            opts.unshift({
                value: '',
                label: t('models_strategy_auto'),
                _tracked: false,
                _configured: true,
                _isAuto: true,
            });
        }
    }
    return opts;
}

function capabilitySupportsAuto(capId) {
    // 嵌入故意不在这里：运行时仅自动回退到
    // OpenAI/LinkAI，因此将其装扮成“自动”会向用户隐藏现实。
    return capId === 'image' || capId === 'vision';
}

// initDropdown 渲染出能力提供者菜单后，装饰每个
// 具有右对齐配置提示的行：
//   - 配置行：没有额外的内容 - .active 标记（品牌绿色 ✓）
//     已经来自 initDropdown 行的选定状态 CSS
//     用户当前选择的。其他配置的行显示无镶边、镜像
//     一个简单的“切换到此”选择器。
//   - 未配置的行：柔和的齿轮图标暗示“单击以配置”。
//     该行的整个点击处理程序被交换以启动供应商模式
//     到位，而不是选择一个不可用的值。
function decorateCapabilityProviderDropdown(def, ddEl, opts) {
    if (!ddEl) return;
    const menu = ddEl.querySelector('.cfg-dropdown-menu');
    if (!menu) return;

    const optByValue = {};
    opts.forEach(o => { optByValue[o.value] = o; });

    menu.querySelectorAll('.cfg-dropdown-item').forEach(item => {
        const value = item.dataset.value;
        const opt = optByValue[value];
        if (!opt) return;
        item.classList.add('cap-provider-item');
        if (!opt._configured) item.classList.add('cap-provider-unconfigured');

        // 包裹标签，使尾随可供性通过 flex:auto 对齐。
        const labelText = item.textContent;
        item.textContent = '';
        const labelEl = document.createElement('span');
        labelEl.className = 'cap-provider-label';
        labelEl.textContent = labelText;
        item.appendChild(labelEl);

        if (!opt._configured) {
            // 尾随齿轮图标作为“配置此供应商”的功能。
            const gear = document.createElement('i');
            gear.className = 'fas fa-gear cap-provider-gear';
            item.appendChild(gear);
        }

        if (!opt._configured && opt._tracked) {
            // 劫持点击：打开供应商模式而不是选择
            // 一个不可用的值，并记住用户的能力
            // 配置以便保存后重新加载可以预先选择供应商。
            const newItem = item.cloneNode(true);
            item.replaceWith(newItem);
            newItem.addEventListener('click', (e) => {
                e.stopPropagation();
                ddEl.classList.remove('open');
                openVendorModal(value, (savedProviderId) => {
                    pendingCapabilitySelection = {
                        capabilityId: def.id,
                        providerId: savedProviderId || value,
                    };
                    loadModelsView({ preserveScroll: true });
                });
            });
        }
    });
}

// “添加供应商”模式的提供商选择器的轻量级装饰器：
// 每个配置的供应商行都会有一个尾随的绿色品牌 ✓，以便用户可以
// 一目了然地看到谁已经设置了，而无需阅读每一行。
// 与decorateCapabilityProviderDropdown 不同，我们不会在这里劫持点击 -
// 在此模式中选择未配置的供应商*是*预期的操作。
function decorateVendorModalPicker(ddEl, opts) {
    if (!ddEl) return;
    const menu = ddEl.querySelector('.cfg-dropdown-menu');
    if (!menu) return;

    const optByValue = {};
    opts.forEach(o => { optByValue[o.value] = o; });

    menu.querySelectorAll('.cfg-dropdown-item').forEach(item => {
        const opt = optByValue[item.dataset.value];
        if (!opt) return;
        // 标记该行，以便在 CSS 中抑制全局活动行 ✓ 规则
        // （否则配置的 AND 选定的行将呈现两个检查）。
        item.classList.add('vendor-picker-item');
        if (opt._isAddNew) {
            // “自定义”是一个添加新操作（允许多个条目），
            // 因此显示尾随 + 而不是配置的 ✓。
            const plus = document.createElement('i');
            plus.className = 'fas fa-plus vendor-picker-add-mark';
            item.appendChild(plus);
            return;
        }
        if (!opt._configured) return;
        const check = document.createElement('i');
        check.className = 'fas fa-check vendor-picker-configured-mark';
        item.appendChild(check);
    });
}

function rebuildCapabilityModelDropdown(def, providerId, selectedModel, scope) {
    // `scope` 让调用者 (renderCapabilityBody) 定位一个仍然分离的对象
    // 子树。卡挂载后，调用者可以通过`document`来代替。
    const root = scope || document;
    const el = root.querySelector(`#cap-${def.id}-model`);
    if (!el) return;

    // 当后端提供一个时，首选功能范围的模型列表
    // （视觉/图像）。它反映了运行时实际上可以的模型
    // 调度到此功能，而不是供应商的完整聊天-
    // 型号目录。回退到通用的provider.models进行聊天/
    // 嵌入/tts，任何供应商模型都是公平的游戏。
    //
    // 条目可以是纯字符串或{value,hint}对象（图像目录
    // 使用后者来显示品牌别名，例如“Nano Banana 2”旁边
    // 技术 Gemini 型号 id）。我们标准化为 {value, label,hint}
    // 在交给 initDropdown 之前。
    const cap = modelsState.capabilities[def.id] || {};
    const capModelMap = cap.provider_models || {};
    let rawList;
    if (capModelMap[providerId]) {
        rawList = capModelMap[providerId].slice();
    } else if (providerId.startsWith('custom:') && capModelMap['custom']) {
        // 扩展自定义：<id>条目共享相同的预设模型列表
        rawList = capModelMap['custom'].slice();
    } else {
        const provider = modelsState.providers.find(p => p.id === providerId);
        rawList = (provider && provider.models) ? provider.models.slice() : [];
    }
    const modelValues = [];
    const opts = rawList.map(entry => {
        if (typeof entry === 'string') {
            modelValues.push(entry);
            return { value: entry, label: entry };
        }
        modelValues.push(entry.value);
        return { value: entry.value, label: entry.label || entry.value, hint: entry.hint || '' };
    });
    opts.push({ value: '__custom__', label: currentLang === 'zh' ? '自定义' : 'Custom' });

    let initialValue = selectedModel || '';
    if (initialValue && !modelValues.includes(initialValue)) {
        initialValue = '__custom__';
    }
    if (!initialValue && opts.length) initialValue = opts[0].value;

    initDropdown(el, opts, initialValue, (value) => {
        const customWrap = document.getElementById(`cap-${def.id}-model-custom-wrap`);
        if (customWrap) {
            if (value === '__custom__') {
                customWrap.classList.remove('hidden');
                const input = document.getElementById(`cap-${def.id}-model-custom`);
                if (input && !input.value) input.value = selectedModel || '';
            } else {
                customWrap.classList.add('hidden');
            }
        }
        // TTS 语音目录可以按引擎模型划分范围（聚合
        // 网关）。每当模型发生变化时，重建语音选择器。
        if (def.id === 'tts') {
            const provDd = document.getElementById('cap-tts-provider');
            const provId = provDd ? getDropdownValue(provDd) : '';
            rebuildCapabilityVoiceDropdown(provId, '', null, value);
        }
    });

    const customWrap = root.querySelector(`#cap-${def.id}-model-custom-wrap`);
    if (customWrap) {
        if (initialValue === '__custom__') {
            customWrap.classList.remove('hidden');
            const input = root.querySelector(`#cap-${def.id}-model-custom`);
            if (input) input.value = selectedModel || '';
        } else {
            customWrap.classList.add('hidden');
        }
    }
}

// 仅 TTS：根据提供商的声音重建语音音色选择器
// 精选的语音列表。当没有选择提供者时隐藏。
//
// 每个语音条目可能是：
//   - 一个裸字符串（代码=标签）
//   - {value,label,hint?} 这样我们就可以显示一个友好的中文名称
//     同时保留运行时发送的原始 API 代码。
function rebuildCapabilityVoiceDropdown(providerId, selectedVoice, scope, modelId) {
    const root = scope || document;
    const wrap = root.querySelector(`#cap-tts-voice-wrap`);
    const el = root.querySelector(`#cap-tts-voice`);
    if (!wrap || !el) return;
    const cap = modelsState.capabilities.tts || {};
    const voicesByProvider = cap.provider_voices || {};
    let raw = (providerId && voicesByProvider[providerId]) || [];
    // 某些提供商（网关）按引擎型号 ID 确定语音范围。
    if (raw && !Array.isArray(raw) && typeof raw === 'object') {
        const activeModel = modelId
            || (root.querySelector(`#cap-tts-model`) ? getDropdownValue(root.querySelector(`#cap-tts-model`)) : '');
        raw = (activeModel && raw[activeModel]) || [];
    }
    if (!raw || raw.length === 0) {
        wrap.classList.add('hidden');
        return;
    }
    wrap.classList.remove('hidden');
    // 语音选择器：左侧为友好名称，右侧为原始 API 代码
    // 提示。保留/发送的值始终是原始代码。
    const codes = [];
    const opts = raw.map(entry => {
        if (typeof entry === 'string') {
            codes.push(entry);
            return { value: entry, label: entry };
        }
        codes.push(entry.value);
        const code = entry.value;
        const desc = entry.hint || entry.label || code;
        return {
            value: code,
            label: desc,
            hint: desc === code ? '' : code,
        };
    });
    opts.push({ value: '__custom__', label: currentLang === 'zh' ? '自定义' : 'Custom' });

    // 目录外值通过自定义分支路由。
    let initial = selectedVoice || '';
    const isCustom = initial && !codes.includes(initial);
    if (isCustom) initial = '__custom__';
    if (!initial) initial = codes[0];

    initDropdown(el, opts, initial, (value) => {
        const customWrap = root.querySelector(`#cap-tts-voice-custom-wrap`);
        if (!customWrap) return;
        if (value === '__custom__') {
            customWrap.classList.remove('hidden');
            const input = root.querySelector(`#cap-tts-voice-custom`);
            if (input && !input.value) input.value = isCustom ? selectedVoice : '';
        } else {
            customWrap.classList.add('hidden');
        }
    });

    const customWrap = root.querySelector(`#cap-tts-voice-custom-wrap`);
    if (customWrap) {
        if (initial === '__custom__') {
            customWrap.classList.remove('hidden');
            const input = root.querySelector(`#cap-tts-voice-custom`);
            if (input) input.value = isCustom ? selectedVoice : '';
        } else {
            customWrap.classList.add('hidden');
        }
    }
}

function onCapabilityProviderChange(def, providerId, scope) {
    if (def.needsModel) {
        // 在为新选择的提供者重建模型选择器之前，
        // 存储用户在*上一个*下输入的自定义模型
        // 提供者，因此稍后切换回它会恢复该值。
        const prevProvider = capabilityLastProviderId[def.id];
        if (prevProvider && prevProvider !== providerId) {
            const prevDd = document.getElementById(`cap-${def.id}-model`);
            const prevInput = document.getElementById(`cap-${def.id}-model-custom`);
            if (prevDd && prevInput && getDropdownValue(prevDd) === '__custom__') {
                const typed = prevInput.value.trim();
                if (typed) capabilityCustomModelMemory[`${def.id}:${prevProvider}`] = typed;
            }
        }
        capabilityLastProviderId[def.id] = providerId;

        // 嵌入：在未选择提供程序时隐藏模型选择器。
        const showModel = def.id === 'embedding' ? providerId !== '' :
            !(providerId === '' && capabilitySupportsAuto(def.id));
        if (showModel) {
            // 恢复该提供程序的记住的自定义模型（如果有），以便
            // 切换供应商并返回不会放弃它。
            const remembered = capabilityCustomModelMemory[`${def.id}:${providerId}`] || '';
            rebuildCapabilityModelDropdown(def, providerId, remembered, scope);
        }
        setCapabilityModelPickerVisible(def, showModel, scope);
    }
    if (def.id === 'tts') {
        rebuildCapabilityVoiceDropdown(providerId, '', scope);
    }
    const body = scope || document.querySelector(`[data-cap-body="${def.id}"]`);
    if (body) {
        const cap = modelsState.capabilities[def.id] || {};
        renderCapabilityHints(def, cap, body, providerId);
    }
}

function getCapabilityModelValue(def) {
    if (!def.needsModel) return '';
    const dd = document.getElementById(`cap-${def.id}-model`);
    if (!dd) return '';
    const v = getDropdownValue(dd);
    if (v === '__custom__') {
        const input = document.getElementById(`cap-${def.id}-model-custom`);
        return input ? input.value.trim() : '';
    }
    return v || '';
}

// 选择加入功能：显示/隐藏切换器下的选择器，无需
// 触摸配置。镜像 TTS 回复模式模式 — 切换本身是
// 纯 UI 状态，直到用户按下“保存”。
function _setCapabilityPickersVisible(def, body, visible) {
    const wrap = body.querySelector(`#cap-${def.id}-pickers`);
    if (wrap) wrap.classList.toggle('hidden', !visible);
}

// 单击切换开关可翻转本地开关。坚持是一个单独的行为
// （保存），这样用户就可以翻转回来而无需写入配置。
function toggleCapabilityEnabled(capId) {
    const def = capabilityDefById(capId);
    if (!def || !def.toggleable) return;
    const cap = modelsState.capabilities[capId] || {};
    cap.enabled = !cap.enabled;
    modelsState.capabilities[capId] = cap;
    const btn = document.getElementById(`cap-${capId}-toggle`);
    if (btn) {
        btn.setAttribute('aria-checked', cap.enabled ? 'true' : 'false');
        btn.classList.toggle('bg-primary-500', cap.enabled);
        btn.classList.toggle('bg-slate-200', !cap.enabled);
        btn.classList.toggle('dark:bg-slate-700', !cap.enabled);
        const knob = btn.querySelector('span');
        if (knob) {
            knob.classList.toggle('translate-x-[18px]', cap.enabled);
            knob.classList.toggle('translate-x-[3px]', !cap.enabled);
        }
    }
    // 文件的其余部分对功能体使用相同的查找。
    const body = document.querySelector(`[data-cap-body="${capId}"]`);
    if (body) _setCapabilityPickersVisible(def, body, cap.enabled);
}

function saveCapability(capId) {
    const def = capabilityDefById(capId);
    if (!def || !def.editable) return;
    // 搜索有自己的形式（策略+提供者，无模型选择器）。
    if (capId === 'search') { saveSearchCapability(); return; }
    const provDd = document.getElementById(`cap-${capId}-provider`);
    const provider = provDd ? getDropdownValue(provDd) : '';
    // 当用户处于自动模式（provider == ""）时，模型选择器是
    // 隐藏并且其中留下的任何值都已过时；保留一个空模型所以
    // 后端将此视为“回退到运行时链”。
    const isAuto = provider === '' && capabilitySupportsAuto(capId);
    // 没有提供者的嵌入同样意味着“清除”——不要泄漏
    // 将过时的模型值放入配置中。
    const model = (isAuto || (capId === 'embedding' && !provider)) ? '' : getCapabilityModelValue(def);
    // TTS 带有额外的语音音色（支持自由文本自定义 ID）。
    let voice = '';
    if (capId === 'tts' && !isAuto) {
        const voiceDd = document.getElementById(`cap-${capId}-voice`);
        voice = voiceDd ? getDropdownValue(voiceDd) : '';
        if (voice === '__custom__') {
            const input = document.getElementById(`cap-${capId}-voice-custom`);
            voice = input ? input.value.trim() : '';
        }
    }

    // 嵌入更改会使任何预先存在的向量索引无效，因为
    // 尺寸/供应商不同。确认后选择保存，然后打开
    // 成功后会出现一个专门的信息对话框，告诉用户如何
    // 重建 - 都是通过应用程序内的自定义对话框，而不是本机警报。
    if (capId === 'embedding') {
        const cap = modelsState.capabilities[capId] || {};
        const before = (cap.current_provider || '').trim();
        const after = (provider || '').trim();
        if (before !== after) {
            showConfirmDialog({
                title: t('models_embedding_change_title'),
                message: t('models_embedding_change_msg'),
                okText: t('save'),
                cancelText: t('cancel'),
                onConfirm: () => _persistCapability(capId, provider, model, () => {
                    showConfirmDialog({
                        title: t('models_embedding_saved_title'),
                        message: t('models_embedding_saved_msg'),
                        okText: t('models_embedding_saved_ok'),
                        hideCancel: true,
                        onConfirm: () => {
                            navigateTo('chat');
                            // 延迟焦点+值设置：navigateTo 可能
                            // 重新渲染聊天面板；之前设定值
                            // 安装的输入将会丢失。
                            setTimeout(() => {
                                const input = document.getElementById('chat-input');
                                if (!input) return;
                                input.value = '/memory rebuild-index';
                                input.focus();
                                // 触发任何输入侦听器（自动调整大小、启用发送按钮等）
                                input.dispatchEvent(new Event('input', { bubbles: true }));
                            }, 60);
                        },
                    });
                }),
            });
            return;
        }
    }
    // 选择加入功能将其开/关开关与选择器一起保留。
    // 即使在关闭时也会发送，因此损坏的条目始终可以
    // 已清除 - 并且后端拒绝启用半填充的。
    let enabled = undefined;
    if (def.toggleable) {
        const cap = modelsState.capabilities[capId] || {};
        enabled = !!cap.enabled;
    }
    // 聊天回退是在模式内编辑的；保存后关闭它
    // 着陆，以便用户直接返回到模型页面（已经
    // 由 _persistCapability 重新加载，刷新主卡徽章）。
    const onAfterSuccess = capId === 'chat_fallback' ? closeChatFallbackModal : undefined;
    _persistCapability(capId, provider, model, onAfterSuccess, { voice, enabled });
}

function _persistCapability(capId, provider, model, onAfterSuccess, extras) {
    const payload = { action: 'set_capability', capability: capId, provider_id: provider, model: model };
    if (extras && extras.voice !== undefined) payload.voice = extras.voice;
    // 选择加入功能（聊天后备）带有其开/关开关。
    if (extras && extras.enabled !== undefined) payload.enabled = extras.enabled;
    fetch('/api/models', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    }).then(r => r.json()).then(data => {
        if (data.status === 'success') {
            // 在重新加载之前闪烁“已保存”，以便状态在重建后仍然存在。
            showStatus(`cap-${capId}-status`, 'models_save_success', false);
            setTimeout(() => {
                loadModelsView({ preserveScroll: true });
                if (onAfterSuccess) onAfterSuccess();
            }, 400);
        } else {
            showStatus(`cap-${capId}-status`, 'models_save_failed', true);
        }
    }).catch(() => showStatus(`cap-${capId}-status`, 'models_save_failed', true));
}

// ---------- 供应商凭证模态 ------------------------------------

let vendorModalState = { providerId: '', onSaved: null };

function openVendorModal(providerId, onSaved) {
    vendorModalState = { providerId: providerId || '', onSaved: onSaved || null };

    const overlay = document.getElementById('vendor-modal-overlay');
    const titleEl = document.getElementById('vendor-modal-title');
    const subEl = document.getElementById('vendor-modal-subtitle');
    const pickerWrap = document.getElementById('vendor-modal-picker-wrap');
    const baseWrap = document.getElementById('vendor-modal-base-wrap');
    const baseInput = document.getElementById('vendor-modal-base');
    const baseHint = document.getElementById('vendor-modal-base-hint');
    const keyInput = document.getElementById('vendor-modal-key');
    const clearBtn = document.getElementById('vendor-modal-clear');

    // 重置任何剩余状态（例如之前的“已保存”消息）
    const statusEl = document.getElementById('vendor-modal-status');
    if (statusEl) {
        statusEl.textContent = '';
        statusEl.classList.add('opacity-0');
    }

    if (!providerId) {
        // 添加流程 — 显示提供程序选择器，默认为第一个未配置的选择器。
        // 我们通过以下方式为每个配置的供应商提供尾随绿色 ✓
        // 下拉装饰器，反映了所使用的视觉语言
        // 能力提供者下拉菜单。 .active 行已经显示
        // 当前通过其自己的背景突出显示选择的供应商，所以我们
        // 故意抑制此选择器的全局活动行✓
        // （参见CSS）——否则配置+选定的行将显示两个。
        // 扩展的自定义提供商卡（“custom:<id>”）通过其编辑
        // 专用模式，因此它们被排除在此选择器之外。挑选
        // “自定义”条目通过该模式创建一个*新的*自定义提供程序 -
        // 这就是添加多个 OpenAI 兼容端点的方式。
        const builtinProviders = modelsState.providers.filter(p => !isCustomProviderCard(p));
        const pickerOpts = builtinProviders.map(p => ({
            value: p.id,
            label: localizedLabel(p.label),
            _configured: !!p.configured,
        }));
        // 在多提供商模式下，后端取代了裸露的“自定义”卡
        // 与扩展的；在此处重新添加它，以便该条目保持可用。
        if (!pickerOpts.some(o => o.value === 'custom')) {
            pickerOpts.push({ value: 'custom', label: t('models_custom_vendor_label'), _configured: false });
        }
        // “自定义”始终表现为添加新操作（多个条目
        // 允许），因此它显示一个 + 标记，而不是配置的 ✓。
        pickerOpts.forEach(o => { if (o.value === 'custom') { o._isAddNew = true; o._configured = false; } });
        const unconfigured = builtinProviders.filter(p => !p.configured);
        const defaultId = (unconfigured[0] && unconfigured[0].id) || (builtinProviders[0] && builtinProviders[0].id) || 'custom';
        pickerWrap.classList.remove('hidden');
        const pickerEl = document.getElementById('vendor-modal-picker');
        const onPick = (val) => {
            if (val === 'custom') {
                // 添加流程中的“自定义”始终会创建一个新的
                // 通过专用模式进入兼容 OpenAI 的提供商
                // （名称+基础+密钥），支持多个自定义端点。
                closeVendorModal();
                openCustomProviderModal('');
                return;
            }
            fillVendorModalForProvider(val);
        };
        initDropdown(pickerEl, pickerOpts, defaultId, onPick);
        decorateVendorModalPicker(pickerEl, pickerOpts);
        onPick(defaultId);
    } else {
        pickerWrap.classList.add('hidden');
        fillVendorModalForProvider(providerId);
    }

    overlay.classList.remove('hidden');

    document.getElementById('vendor-modal-cancel').onclick = closeVendorModal;
    document.getElementById('vendor-modal-save').onclick = saveVendorModal;
    clearBtn.onclick = clearVendorModal;

    // 用户编辑屏蔽值后，删除“屏蔽哨兵”数据集
    // 因此保存处理程序将其输入视为真正的新密钥。我们比较
    // 下一个刻度，因为 keydown 在新字符到达 .value 之前触发。
    keyInput.oninput = function () {
        if (keyInput.dataset.masked === '1' && keyInput.value !== keyInput.dataset.maskedVal) {
            keyInput.dataset.masked = '';
        }
    };

    function onOverlayClick(e) {
        if (e.target === overlay) {
            closeVendorModal();
            overlay.removeEventListener('click', onOverlayClick);
        }
    }
    overlay.addEventListener('click', onOverlayClick);
    keyInput.focus();
}

function fillVendorModalForProvider(providerId) {
    const meta = modelsState.providers.find(p => p.id === providerId);
    if (!meta) return;
    document.getElementById('vendor-modal-title').textContent = localizedLabel(meta.label);
    document.getElementById('vendor-modal-subtitle').textContent = meta.id;

    // LinkAI 聚合了许多供应商，因此我们只为它提供指向其的链接
    // 用于创建/管理聚合密钥的控制台。其他提供商管理
    // 他们的密钥在自己的网站上。
    const manageKey = document.getElementById('vendor-modal-manage-key');
    if (manageKey) manageKey.classList.toggle('hidden', meta.id !== 'linkai');

    // ----- API 基础 -----
    // 始终将*当前有效*基数反映为输入值，以便
    // 用户可以查看（并编辑）今天正在使用的内容。占位符已保留
    // 严格针对“尚未输入任何内容”状态并显示官方
    // 默认值——不与实际值混合。
    const baseWrap = document.getElementById('vendor-modal-base-wrap');
    const baseInput = document.getElementById('vendor-modal-base');
    const baseHint = document.getElementById('vendor-modal-base-hint');
    if (meta.api_base_field) {
        baseWrap.classList.remove('hidden');
        baseInput.placeholder = meta.api_base_default || meta.api_base_placeholder || '';
        baseInput.value = meta.api_base || '';
        baseHint.classList.add('hidden');
    } else {
        baseWrap.classList.add('hidden');
        baseInput.value = '';
    }

    // ----- API 密钥 -----
    // 对于已配置的供应商，将屏蔽键显示为输入*值*，以便
    // 它以与真实条目相同的深色文本显示 - 使“已配置”
    // 视觉上不含糊。掩码形式（例如“sk-r***zRU”）也是一种
    // 哨兵：保存处理程序将未触及的屏蔽输入视为“无更改”。
    const keyInput = document.getElementById('vendor-modal-key');
    if (meta.configured && meta.api_key_masked) {
        keyInput.value = meta.api_key_masked;
        keyInput.dataset.masked = '1';
        keyInput.dataset.maskedVal = meta.api_key_masked;
        keyInput.placeholder = '';
    } else {
        keyInput.value = '';
        keyInput.dataset.masked = '';
        keyInput.dataset.maskedVal = '';
        keyInput.placeholder = 'sk-...';
    }

    const clearBtn = document.getElementById('vendor-modal-clear');
    clearBtn.classList.toggle('hidden', !meta.configured);

    vendorModalState.providerId = providerId;
}

function closeVendorModal() {
    document.getElementById('vendor-modal-overlay').classList.add('hidden');
}

function saveVendorModal() {
    const providerId = vendorModalState.providerId;
    if (!providerId) return;
    const keyInput = document.getElementById('vendor-modal-key');
    const apiBase = document.getElementById('vendor-modal-base').value.trim();

    // 将“输入仍然等于我们在打开时出现的屏蔽值”视为“否”
    // 更改” — 后端使用丢失/空的 api_key 来跳过该字段。
    let apiKey = keyInput.value.trim();
    const masked = keyInput.dataset.masked === '1';
    const maskedVal = keyInput.dataset.maskedVal || '';
    if (masked && apiKey === maskedVal) {
        apiKey = '';
    }

    if (!apiKey && !masked) {
        // 首次设置无需输入按键 → 轻推用户。
        keyInput.focus();
        return;
    }

    const btn = document.getElementById('vendor-modal-save');
    btn.disabled = true;
    const payload = { action: 'set_provider', provider_id: providerId, api_base: apiBase };
    if (apiKey) payload.api_key = apiKey;
    fetch('/api/models', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    }).then(r => r.json()).then(data => {
        btn.disabled = false;
        if (data.status === 'success') {
            closeVendorModal();
            const onSaved = vendorModalState.onSaved;
            if (onSaved) {
                try { onSaved(providerId); } catch (e) { /* 努普 */ }
            } else {
                loadModelsView();
            }
        } else {
            showStatus('vendor-modal-status', 'models_save_failed', true);
        }
    }).catch(() => {
        btn.disabled = false;
        showStatus('vendor-modal-status', 'models_save_failed', true);
    });
}

function clearVendorModal() {
    const providerId = vendorModalState.providerId;
    if (!providerId) return;
    showConfirmDialog({
        title: t('models_clear_confirm_title'),
        message: t('models_clear_confirm_msg'),
        okText: t('models_clear_credential'),
        cancelText: t('cancel'),
        onConfirm: () => {
            fetch('/api/models', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: 'delete_provider', provider_id: providerId }),
            }).then(r => r.json()).then(data => {
                if (data.status === 'success') {
                    closeVendorModal();
                    loadModelsView();
                } else {
                    showStatus('vendor-modal-status', 'models_clear_failed', true);
                }
            }).catch(() => showStatus('vendor-modal-status', 'models_clear_failed', true));
        }
    });
}

// =====================================================================
// 自定义（OpenAI 兼容）提供者模式 — 添加/编辑
// =====================================================================
// 专用定制提供商模式的状态。 `editId` 为空时
// 编辑时添加并设置为提供商 ID。
let customProviderModalState = { editId: '' };

function openCustomProviderModal(providerId) {
    const editing = !!providerId;
    customProviderModalState = { editId: editing ? providerId : '' };

    const card = editing ? getCustomProviderCards().find(p => p.custom_id === providerId) : null;

    const overlay = document.getElementById('custom-provider-modal-overlay');
    if (!overlay) return;

    document.getElementById('custom-provider-modal-title').textContent =
        editing ? t('models_custom_edit_title') : t('models_custom_add_title');

    const nameInput = document.getElementById('custom-provider-name');
    const baseInput = document.getElementById('custom-provider-base');
    const keyInput = document.getElementById('custom-provider-key');

    nameInput.value = card ? (card.custom_name || '') : '';
    baseInput.value = card ? (card.api_base || '') : '';

    // 将屏蔽键显示为已配置提供程序的值，以便
    // “已设置”状态是明确的；未触及的掩码值意味着
    // 保存时“保留现有密钥”（镜像供应商模式合同）。
    if (card && card.configured && card.api_key_masked) {
        keyInput.value = card.api_key_masked;
        keyInput.dataset.masked = '1';
        keyInput.dataset.maskedVal = card.api_key_masked;
    } else {
        keyInput.value = '';
        keyInput.dataset.masked = '';
        keyInput.dataset.maskedVal = '';
    }
    keyInput.oninput = function () {
        if (keyInput.dataset.masked === '1' && keyInput.value !== keyInput.dataset.maskedVal) {
            keyInput.dataset.masked = '';
        }
    };

    const statusEl = document.getElementById('custom-provider-modal-status');
    if (statusEl) { statusEl.textContent = ''; statusEl.classList.add('opacity-0'); }

    overlay.classList.remove('hidden');
    document.getElementById('custom-provider-modal-cancel').onclick = closeCustomProviderModal;
    document.getElementById('custom-provider-modal-save').onclick = saveCustomProviderModal;

    // 仅当编辑现有提供程序时，删除才可用。
    const deleteBtn = document.getElementById('custom-provider-modal-delete');
    if (deleteBtn) {
        deleteBtn.classList.toggle('hidden', !editing);
        deleteBtn.onclick = editing ? () => deleteCustomProvider(providerId) : null;
    }

    function onOverlayClick(e) {
        if (e.target === overlay) {
            closeCustomProviderModal();
            overlay.removeEventListener('click', onOverlayClick);
        }
    }
    overlay.addEventListener('click', onOverlayClick);
    nameInput.focus();
}

function closeCustomProviderModal() {
    const overlay = document.getElementById('custom-provider-modal-overlay');
    if (overlay) overlay.classList.add('hidden');
}

function saveCustomProviderModal() {
    const name = document.getElementById('custom-provider-name').value.trim();
    const apiBase = document.getElementById('custom-provider-base').value.trim();
    const keyInput = document.getElementById('custom-provider-key');

    if (!name) {
        showStatus('custom-provider-modal-status', 'models_custom_name_required', true);
        document.getElementById('custom-provider-name').focus();
        return;
    }
    const editing = !!customProviderModalState.editId;
    if (!editing && !apiBase) {
        showStatus('custom-provider-modal-status', 'models_custom_base_required', true);
        document.getElementById('custom-provider-base').focus();
        return;
    }

    // 密钥处理（自定义提供程序的密钥是可选的）：
    //  - 屏蔽 + 未触及 => 保持现有状态，从有效负载中省略
    //  - 非空类型值 => 设置它
    //  - 在编辑时明确清除=>发送“”，以便后端清除它
    const untouchedMasked =
        keyInput.dataset.masked === '1' && keyInput.value.trim() === (keyInput.dataset.maskedVal || '');
    const apiKey = untouchedMasked ? '' : keyInput.value.trim();

    const payload = {
        action: 'set_custom_provider',
        name: name,
        api_base: apiBase,
    };
    if (untouchedMasked) {
        // 完全省略 api_key => 后端保留存储的密钥
    } else {
        // 发送值（可能是“”），以便执行显式清除。
        payload.api_key = apiKey;
    }
    if (editing) payload.id = customProviderModalState.editId;

    const btn = document.getElementById('custom-provider-modal-save');
    btn.disabled = true;
    fetch('/api/models', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    }).then(r => r.json()).then(data => {
        btn.disabled = false;
        if (data.status === 'success') {
            closeCustomProviderModal();
            loadModelsView();
        } else {
            showStatus('custom-provider-modal-status', 'models_save_failed', true);
        }
    }).catch(() => {
        btn.disabled = false;
        showStatus('custom-provider-modal-status', 'models_save_failed', true);
    });
}

function deleteCustomProvider(providerId) {
    showConfirmDialog({
        title: t('models_custom_delete_confirm_title'),
        message: t('models_custom_delete_confirm_msg'),
        okText: t('models_custom_delete'),
        cancelText: t('cancel'),
        onConfirm: () => {
            fetch('/api/models', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: 'delete_custom_provider', id: providerId }),
            }).then(r => r.json()).then(data => {
                if (data.status === 'success') {
                    closeCustomProviderModal();
                    loadModelsView();
                }
            }).catch(() => { /* 努普 */ });
        }
    });
}

// =====================================================================
// 频道视图
// =====================================================================
let channelsData = [];
// 多代理模式：多实例就绪类型（飞书）每渲染一张卡
// Channel_instances 记录。这些反映了 API 返回的额外字段。
let channelInstancesView = [];
let multiInstanceTypes = [];
let channelsMultiAgent = false;

function isMultiInstanceType(name) {
    return channelsMultiAgent && multiInstanceTypes.indexOf(name) !== -1;
}

function loadChannelsView() {
    const container = document.getElementById('channels-content');
    if (!container) return Promise.resolve();
    container.innerHTML = `<div class="flex items-center gap-2 py-8 justify-center text-slate-400 dark:text-slate-500 text-sm">
        <i class="fas fa-spinner fa-spin text-xs"></i><span>Loading...</span></div>`;

    const roster = agentCatalog.length ? Promise.resolve() : loadAgentCatalog();
    return roster.then(() => fetch('/api/channels').then(r => r.json()).then(data => {
        if (data.status !== 'success') return;
        channelsData = data.channels || [];
        channelsMultiAgent = !!data.multi_agent;
        multiInstanceTypes = data.multi_instance_types || [];
        channelInstancesView = data.instances || [];
        renderActiveChannels();
    }).catch(() => {
        container.innerHTML = '<p class="text-sm text-red-400 py-8 text-center">Failed to load channels</p>';
    }));
}

// 构建要渲染的卡片列表。多Agent模式下，多实例
// types (feishu) 为每个channel_instances 记录贡献一张卡片（来自
// 数据.实例）；其他所有内容都贡献其单一的每种类型卡。每个
// item 带有一个 `iid` （实例 id），它是其 DOM 和操作的关键：对于遗留
// 对于每种类型的卡，它只是通道名称。
function channelRenderList() {
    const list = [];
    channelsData.forEach(ch => {
        if (isMultiInstanceType(ch.name)) return;  // 从实例渲染
        if (ch.active) list.push(Object.assign({}, ch, { iid: ch.name }));
    });
    if (channelsMultiAgent) {
        channelInstancesView.forEach(inst => {
            list.push(Object.assign({}, inst, { iid: inst.instance_id }));
        });
    }
    return list;
}

function renderActiveChannels() {
    stopWeixinQrPoll();
    stopWeixinStatusPoll();
    const container = document.getElementById('channels-content');
    container.innerHTML = '';
    closeAddChannelPanel();

    const activeChannels = channelRenderList();

    if (activeChannels.length === 0) {
        container.innerHTML = `
            <div class="flex flex-col items-center justify-center py-20">
                <div class="w-16 h-16 rounded-2xl bg-blue-50 dark:bg-blue-900/20 flex items-center justify-center mb-4">
                    <i class="fas fa-tower-broadcast text-blue-400 text-xl"></i>
                </div>
                <p class="text-slate-500 dark:text-slate-400 font-medium">${t('channels_empty')}</p>
                <p class="text-sm text-slate-400 dark:text-slate-500 mt-1">${t('channels_empty_desc')}</p>
            </div>`;
        return;
    }

    activeChannels.forEach(ch => {
        const iid = ch.iid;
        const label = (typeof ch.label === 'object') ? (ch.label[currentLang] || ch.label.en) : ch.label;
        const card = document.createElement('div');
        card.className = 'bg-white dark:bg-[#1A1A1A] rounded-xl border border-slate-200 dark:border-white/10 p-6';
        card.id = `channel-card-${iid}`;

        const fieldsHtml = buildChannelFieldsHtml(iid, ch.fields || []);
        const hasFields = (ch.fields || []).length > 0;

        const weixinWaiting = ch.name === 'weixin' && ch.login_status && ch.login_status !== 'logged_in';
        const wecomNeedsCreds = ch.name === 'wecom_bot' && !_wecomBotHasCreds(ch);
        // 飞书 active 卡片渲染带 Tab 的 panel：手动填写 + 扫码重建（覆盖现有配置）
        const isFeishu = ch.name === 'feishu';
        // 实例卡（多代理飞书）显示绑定的代理内联和
        // 使用实例 ID 作为其副标题，而不是裸类型名称。
        const isInstance = isMultiInstanceType(ch.name) && !!ch.instance_id;
        let statusDot, statusText;
        if (weixinWaiting) {
            statusDot = 'bg-amber-400 animate-pulse';
            statusText = ch.login_status === 'scanned'
                ? `<span class="text-xs text-primary-500">${t('weixin_scan_scanned')}</span>`
                : `<span class="text-xs text-amber-500">${t('weixin_scan_waiting')}</span>`;
        } else if (wecomNeedsCreds) {
            statusDot = 'bg-amber-400 animate-pulse';
            statusText = `<span class="text-xs text-amber-500">${t('channels_connecting')}</span>`;
        } else {
            statusDot = 'bg-primary-400';
            statusText = `<span class="text-xs text-primary-500">${t('channels_connected')}</span>`;
        }

        card.innerHTML = `
            <div class="flex items-center gap-4${hasFields || weixinWaiting || wecomNeedsCreds || isFeishu || multiAgentMode() ? ' mb-5' : ''}">
                <div class="w-10 h-10 rounded-xl bg-${ch.color}-50 dark:bg-${ch.color}-900/20 flex items-center justify-center flex-shrink-0">
                    <i class="fas ${ch.icon} text-${ch.color}-500 text-base"></i>
                </div>
                <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2">
                        <span class="font-semibold text-slate-800 dark:text-slate-100">${escapeHtml(label)}</span>
                        <span class="w-2 h-2 rounded-full ${statusDot}"></span>
                        ${statusText}
                    </div>
                    <p class="text-xs text-slate-500 dark:text-slate-400 mt-0.5 font-mono">${escapeHtml(iid)}</p>
                </div>
                <button onclick="disconnectChannel('${ch.name}', '${isInstance ? iid : ''}')"
                    class="px-3 py-1.5 rounded-lg text-xs font-medium
                           bg-red-50 dark:bg-red-900/20 text-red-500 dark:text-red-400
                           hover:bg-red-100 dark:hover:bg-red-900/40
                           cursor-pointer transition-colors flex-shrink-0">
                    ${t('channels_disconnect')}
                </button>
            </div>
            ${multiAgentMode() ? `<div class="channel-agent-bind">
                <span class="text-xs text-slate-500 whitespace-nowrap" title="${escapeHtml(t('channel_bound_agent_hint'))}">${escapeHtml(t('channel_bound_agent'))}</span>
                <div id="ch-members-${iid}" class="cfg-dropdown cfg-dropdown-avatar cfg-dropdown-sm cfg-dropdown-multi" tabindex="0" style="width: 200px;">
                    <div class="cfg-dropdown-selected">
                        <span class="cfg-dropdown-faces"></span>
                        <span class="cfg-dropdown-text">--</span>
                        <i class="fas fa-chevron-down cfg-dropdown-arrow"></i>
                    </div>
                    <div class="cfg-dropdown-menu"></div>
                </div>
            </div>` : ''}
            ${weixinWaiting ? `<div id="weixin-active-qr" class="flex flex-col items-center py-2">
                <button onclick="showWeixinActiveQr()"
                    class="px-4 py-2 rounded-lg bg-primary-500 hover:bg-primary-600 text-white text-sm font-medium
                           cursor-pointer transition-colors duration-150">
                    ${t('weixin_scan_title')}
                </button>
            </div>` : ''}
            ${wecomNeedsCreds ? `<div id="wecom-active-auth" class="flex flex-col items-center py-2">
                <p class="text-sm text-slate-500 dark:text-slate-400 mb-3">${t('wecom_scan_desc')}</p>
                <button onclick="startWecomBotAuthInCard()"
                    class="px-5 py-2 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-white text-sm font-medium
                           cursor-pointer transition-colors duration-150">
                    <i class="fas fa-qrcode mr-2"></i>${t('wecom_scan_btn')}
                </button>
                <div id="wecom-card-scan-status" class="mt-3"></div>
            </div>` : ''}
            ${isFeishu ? buildFeishuPanel(ch, true) : (hasFields ? `<div class="space-y-4">
                ${fieldsHtml}
                <div class="flex items-center justify-end gap-3 pt-1">
                    <span id="ch-status-${iid}" class="text-xs text-primary-500 opacity-0 transition-opacity duration-300"></span>
                    <button onclick="saveChannelConfig('${ch.name}', '${isInstance ? iid : ''}')"
                        class="px-4 py-2 rounded-lg bg-primary-500 hover:bg-primary-600 text-white text-sm font-medium
                               cursor-pointer transition-colors duration-150 disabled:opacity-50 disabled:cursor-not-allowed"
                        id="ch-save-${iid}">${t('channels_save')}</button>
                </div>
            </div>` : '')}`;

        container.appendChild(card);
        bindSecretFieldEvents(card);
        initChannelTeam(ch);

        if (weixinWaiting) {
            startWeixinActiveStatusPoll();
        }
    });
}

// 每个频道一张多选卡，与在聊天中创建团队相同的想法
// 历史：选择一组代理；第一个选择是所有者（收到每个
// 消息并可以委托），其余的是队友。一个有序列表，所以
// 首先检查的是业主。空=跟随默认Agent，solo。
let _channelTeam = {};  // iid -> 有序 [ownerId, ...memberIds]

function initChannelTeam(ch) {
    const iid = ch.iid || ch.name;
    if (!multiAgentMode()) return;
    const box = document.getElementById(`ch-members-${iid}`);
    if (!box) return;
    // 为有序团队播种：首先是所有者，然后是其成员。每个类型的遗产
    // 卡没有实例字段，因此回退到其通道类型绑定。
    const owner = ch.instance_id ? (ch.agent_id || '') : (channelBoundAgentId(ch.name) || '');
    const members = Array.isArray(ch.members) ? ch.members : [];
    _channelTeam[iid] = [owner, ...members].filter((id, i, arr) => id && arr.indexOf(id) === i);
    box.dataset.channelName = ch.name;
    renderChannelTeam(iid);
    if (!box._ddBound) {
        box.querySelector('.cfg-dropdown-selected').addEventListener('click', (e) => {
            e.stopPropagation();
            document.querySelectorAll('.cfg-dropdown.open').forEach(d => { if (d !== box) d.classList.remove('open'); });
            box.classList.toggle('open');
        });
        box._ddBound = true;
    }
}

function renderChannelTeam(iid) {
    const box = document.getElementById(`ch-members-${iid}`);
    if (!box) return;
    const team = _channelTeam[iid] || [];
    const ownerId = team[0] || '';
    const agents = enabledAgents();
    const chosen = team.map(id => findAgent(id)).filter(Boolean);

    const faces = box.querySelector('.cfg-dropdown-faces');
    const textEl = box.querySelector('.cfg-dropdown-text');
    const MAX_FACES = 3;
    if (chosen.length) {
        // 触发：最多 MAX_FACES 个头像；除此之外的任何药物都将成为“+N”药丸
        // 因此计数始终与隐藏的数量匹配，而不是总数。
        const shown = chosen.slice(0, MAX_FACES);
        const extra = chosen.length - shown.length;
        faces.innerHTML = shown.map(a => agentAvatarHTML(a, 18)).join('')
            + (extra > 0 ? `<span class="cfg-dropdown-more">+${extra}</span>` : '');
        textEl.textContent = chosen[0].name || chosen[0].id;
        textEl.classList.remove('text-slate-400', 'dark:text-slate-500');
    } else {
        // 没有选择任何内容：此通道遵循默认代理。显示它
        // （暗淡）而不是空的“无”，因此接收器始终是清晰的。
        const def = findAgent(defaultAgentId);
        faces.innerHTML = def ? agentAvatarHTML(def, 18) : '';
        textEl.textContent = def ? (def.name || def.id) : t('channel_team_none');
        textEl.classList.add('text-slate-400', 'dark:text-slate-500');
    }

    // 菜单：清单。第一个被选中的人带有一个小的“默认”徽章，因此它
    // 明确哪个代理接收和委托。所选的勾号是
    // 下拉列表的全局 .active::after，因此不需要每行刻度元素。
    const menu = box.querySelector('.cfg-dropdown-menu');
    if (!agents.length) {
        menu.innerHTML = `<div class="cfg-dropdown-item cfg-dropdown-empty">${escapeHtml(t('channel_team_no_candidates'))}</div>`;
        return;
    }
    menu.innerHTML = agents.map(a => {
        const on = team.includes(a.id);
        const isOwner = a.id === ownerId;
        return `<div class="cfg-dropdown-item cfg-dropdown-check${on ? ' active' : ''}"
            onclick="event.stopPropagation(); toggleChannelTeam('${iid}','${a.id}')">
            <span class="cfg-dropdown-item-face">${agentAvatarHTML(a, 20)}</span>
            <span class="cfg-dropdown-label">${escapeHtml(a.name || a.id)}</span>
            ${isOwner ? `<span class="cfg-dropdown-badge">${escapeHtml(t('channel_bound_default'))}</span>` : ''}
        </div>`;
    }).join('');
}

function toggleChannelTeam(iid, agentId) {
    const box = document.getElementById(`ch-members-${iid}`);
    const chName = box ? (box.dataset.channelName || '') : '';
    const team = _channelTeam[iid] || [];
    const i = team.indexOf(agentId);
    if (i === -1) team.push(agentId);       // 附加：订单 = 挑选订单
    else team.splice(i, 1);                 // 删除；如果它是所有者，那么下一个将成为所有者
    _channelTeam[iid] = team;
    renderChannelTeam(iid);
    // 坚持：首先选择的是所有者（空->默认代理），其余成员。
    const ownerId = team[0] || '';
    const members = team.slice(1);
    bindChannelAgent(chName, ownerId, iid, members);
}

function buildChannelFieldsHtml(chName, fields) {
    let html = '';
    fields.forEach(f => {
        const inputId = `ch-${chName}-${f.key}`;
        let inputHtml = '';
        if (f.type === 'bool') {
            const checked = f.value ? 'checked' : '';
            inputHtml = `<label class="relative inline-flex items-center cursor-pointer">
                <input id="${inputId}" type="checkbox" ${checked} class="sr-only peer" data-field="${f.key}" data-ch="${chName}">
                <div class="w-9 h-5 bg-slate-200 dark:bg-slate-700 peer-checked:bg-primary-400 rounded-full
                            after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white
                            after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:after:translate-x-full"></div>
            </label>`;
        } else if (f.type === 'secret') {
            inputHtml = `<input id="${inputId}" type="text" value="${escapeHtml(String(f.value || ''))}"
                data-field="${f.key}" data-ch="${chName}" data-masked="${f.value ? '1' : ''}"
                class="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600
                       bg-slate-50 dark:bg-white/5 text-sm text-slate-800 dark:text-slate-100
                       focus:outline-none focus:border-primary-500 font-mono transition-colors
                       ${f.value ? 'cfg-key-masked' : ''}"
                placeholder="${escapeHtml(f.label)}">`;
        } else {
            const inputType = f.type === 'number' ? 'number' : 'text';
            inputHtml = `<input id="${inputId}" type="${inputType}" value="${escapeHtml(String(f.value ?? f.default ?? ''))}"
                data-field="${f.key}" data-ch="${chName}"
                class="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600
                       bg-slate-50 dark:bg-white/5 text-sm text-slate-800 dark:text-slate-100
                       focus:outline-none focus:border-primary-500 font-mono transition-colors"
                placeholder="${escapeHtml(f.label)}">`;
        }
        html += `<div>
            <label class="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-1.5">${escapeHtml(f.label)}</label>
            ${inputHtml}
        </div>`;
    });
    return html;
}

function bindSecretFieldEvents(container) {
    container.querySelectorAll('input[data-masked="1"]').forEach(inp => {
        inp.addEventListener('focus', function() {
            if (this.dataset.masked === '1') {
                this.value = '';
                this.dataset.masked = '';
                this.classList.remove('cfg-key-masked');
            }
        });
    });
}

function showChannelStatus(chName, msgKey, isError) {
    const el = document.getElementById(`ch-status-${chName}`);
    if (!el) return;
    el.textContent = t(msgKey);
    el.classList.toggle('text-red-500', !!isError);
    el.classList.toggle('text-primary-500', !isError);
    el.classList.remove('opacity-0');
    setTimeout(() => el.classList.add('opacity-0'), 2500);
}

function saveChannelConfig(chName, instanceId) {
    // instanceId 是 DOM 的键（每个实例卡）；回落至通道
    // 旧版单实例卡的名称。
    const iid = instanceId || chName;
    const card = document.getElementById(`channel-card-${iid}`);
    if (!card) return;

    const updates = {};
    card.querySelectorAll('input[data-ch="' + iid + '"]').forEach(inp => {
        const key = inp.dataset.field;
        if (inp.type === 'checkbox') {
            updates[key] = inp.checked;
        } else {
            if (inp.dataset.masked === '1') return;
            updates[key] = inp.value;
        }
    });

    const btn = document.getElementById(`ch-save-${iid}`);
    if (btn) btn.disabled = true;

    fetch('/api/channels', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'save', channel: chName, instance_id: instanceId || '', config: updates })
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'success') {
            showChannelStatus(iid, data.restarted ? 'channels_restarted' : 'channels_saved', false);
        } else {
            showChannelStatus(iid, 'channels_save_error', true);
        }
    })
    .catch(() => showChannelStatus(iid, 'channels_save_error', true))
    .finally(() => { if (btn) btn.disabled = false; });
}

function disconnectChannel(chName, instanceId) {
    const ch = channelsData.find(c => c.name === chName);
    const label = ch ? ((typeof ch.label === 'object') ? (ch.label[currentLang] || ch.label.en) : ch.label) : chName;

    showConfirmDialog({
        title: t('channels_disconnect'),
        message: t('channels_disconnect_confirm'),
        okText: t('channels_disconnect'),
        cancelText: t('channels_cancel'),
        onConfirm: () => {
            fetch('/api/channels', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: 'disconnect', channel: chName, instance_id: instanceId || '' })
            })
            .then(r => r.json())
            .then(data => {
                if (data.status === 'success') {
                    // 实例删除会更改实例列表；重新加载自
                    // 服务器所以卡组是权威的。每个类型的旧版本
                    // 断开连接可以在本地翻转标志。
                    if (instanceId) {
                        loadChannelsView();
                    } else {
                        if (ch) ch.active = false;
                        renderActiveChannels();
                    }
                }
            })
            .catch(() => {});
        }
    });
}

// ---添加通道面板---
function openAddChannelPanel() {
    const panel = document.getElementById('channels-add-panel');
    // 多实例就绪类型（feishu）总是可以再次添加 - 每次添加
    // 创建一个新实例。其他类型一旦激活就会消失。
    const activeNames = new Set(
        channelsData.filter(c => c.active && !isMultiInstanceType(c.name)).map(c => c.name)
    );
    const available = channelsData.filter(c => !activeNames.has(c.name));

    const anyCards = channelRenderList().length > 0;
    const content = document.getElementById('channels-content');
    if (!anyCards && content) content.classList.add('hidden');

    if (available.length === 0) {
        panel.innerHTML = `<div class="bg-white dark:bg-[#1A1A1A] rounded-xl border border-slate-200 dark:border-white/10 p-6 text-center">
            <p class="text-sm text-slate-500 dark:text-slate-400">${currentLang === 'zh' ? '所有通道均已接入' : 'All channels are already connected'}</p>
            <button onclick="closeAddChannelPanel()" class="mt-3 text-xs text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 cursor-pointer">${t('channels_cancel')}</button>
        </div>`;
        panel.classList.remove('hidden');
        return;
    }

    const ddOptions = [
        { value: '', label: t('channels_select_placeholder') },
        ...available.map(ch => {
            const label = (typeof ch.label === 'object') ? (ch.label[currentLang] || ch.label.en) : ch.label;
            return { value: ch.name, label: `${label} (${ch.name})` };
        })
    ];

    panel.innerHTML = `
        <div class="bg-white dark:bg-[#1A1A1A] rounded-xl border border-primary-200 dark:border-primary-800 p-6">
            <div class="flex items-center gap-3 mb-5">
                <div class="w-9 h-9 rounded-lg bg-primary-50 dark:bg-primary-900/30 flex items-center justify-center">
                    <i class="fas fa-plus text-primary-500 text-sm"></i>
                </div>
                <h3 class="font-semibold text-slate-800 dark:text-slate-100">${t('channels_add')}</h3>
            </div>
            <div class="mb-4">
                <div id="add-channel-select" class="cfg-dropdown" tabindex="0">
                    <div class="cfg-dropdown-selected">
                        <span class="cfg-dropdown-text">--</span>
                        <i class="fas fa-chevron-down cfg-dropdown-arrow"></i>
                    </div>
                    <div class="cfg-dropdown-menu"></div>
                </div>
            </div>
            <div id="add-channel-fields" class="space-y-4"></div>
            <div id="add-channel-actions" class="hidden flex items-center justify-end gap-3 pt-4">
                <button onclick="closeAddChannelPanel()"
                    class="px-4 py-2 rounded-lg border border-slate-200 dark:border-white/10
                           text-slate-600 dark:text-slate-300 text-sm font-medium
                           hover:bg-slate-50 dark:hover:bg-white/5
                           cursor-pointer transition-colors duration-150">${t('channels_cancel')}</button>
                <button id="add-channel-submit" onclick="submitAddChannel()"
                    class="px-4 py-2 rounded-lg bg-primary-500 hover:bg-primary-600 text-white text-sm font-medium
                           cursor-pointer transition-colors duration-150 disabled:opacity-50 disabled:cursor-not-allowed">${t('channels_connect_btn')}</button>
            </div>
        </div>`;
    panel.classList.remove('hidden');
    panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

    const ddEl = document.getElementById('add-channel-select');
    initDropdown(ddEl, ddOptions, '', onAddChannelSelect);
}

function closeAddChannelPanel() {
    stopWeixinQrPoll();
    stopFeishuRegisterPoll();
    const panel = document.getElementById('channels-add-panel');
    if (panel) {
        panel.classList.add('hidden');
        panel.innerHTML = '';
    }
    const content = document.getElementById('channels-content');
    if (content) content.classList.remove('hidden');
}

function onAddChannelSelect(chName) {
    stopWeixinQrPoll();
    stopFeishuRegisterPoll();
    const fieldsContainer = document.getElementById('add-channel-fields');
    const actions = document.getElementById('add-channel-actions');

    if (!chName) {
        fieldsContainer.innerHTML = '';
        actions.classList.add('hidden');
        return;
    }

    if (chName === 'weixin') {
        actions.classList.add('hidden');
        fieldsContainer.innerHTML = `
            <div id="weixin-qr-panel" class="flex flex-col items-center py-4">
                <p class="text-sm text-slate-500 dark:text-slate-400 mb-4">${t('weixin_scan_loading')}</p>
            </div>`;
        startWeixinQrLogin();
        return;
    }

    if (chName === 'wecom_bot') {
        actions.classList.add('hidden');
        const ch = channelsData.find(c => c.name === chName);
        fieldsContainer.innerHTML = buildWecomBotPanel(ch);
        return;
    }

    if (chName === 'feishu') {
        actions.classList.add('hidden');
        const ch = channelsData.find(c => c.name === chName);
        fieldsContainer.innerHTML = buildFeishuPanel(ch);
        return;
    }

    const ch = channelsData.find(c => c.name === chName);
    if (!ch) return;

    fieldsContainer.innerHTML = buildChannelFieldsHtml(chName, ch.fields || []);
    bindSecretFieldEvents(fieldsContainer);
    actions.classList.remove('hidden');
}

function submitAddChannel() {
    const ddEl = document.getElementById('add-channel-select');
    const chName = getDropdownValue(ddEl);
    if (!chName) return;

    const fieldsContainer = document.getElementById('add-channel-fields');
    const updates = {};
    fieldsContainer.querySelectorAll('input[data-ch="' + chName + '"]').forEach(inp => {
        const key = inp.dataset.field;
        if (inp.type === 'checkbox') {
            updates[key] = inp.checked;
        } else {
            if (inp.dataset.masked === '1') return;
            updates[key] = inp.value;
        }
    });

    const btn = document.getElementById('add-channel-submit');
    if (btn) { btn.disabled = true; btn.textContent = t('channels_connecting'); }

    fetch('/api/channels', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'connect', channel: chName, config: updates })
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'success') {
            // 新的多实例记录只能通过重新加载来显示
            // 来自服务器的实例列表；遗留的每类型添加可以修补
            // 本地状态并重新渲染。
            if (isMultiInstanceType(chName) || data.instance_id) {
                loadChannelsView();
                return;
            }
            const ch = channelsData.find(c => c.name === chName);
            if (ch) {
                ch.active = true;
                (ch.fields || []).forEach(f => {
                    if (updates[f.key] !== undefined) {
                        f.value = f.type === 'secret' ? ChannelsHandler_maskSecret(updates[f.key]) : updates[f.key];
                    }
                });
            }
            renderActiveChannels();
        } else {
            if (btn) { btn.disabled = false; btn.textContent = t('channels_connect_btn'); }
        }
    })
    .catch(() => {
        if (btn) { btn.disabled = false; btn.textContent = t('channels_connect_btn'); }
    });
}

// =====================================================================
// 微信二维码登录
// =====================================================================
let _weixinQrPollTimer = null;
let _weixinStatusPollTimer = null;

function stopWeixinStatusPoll() {
    if (_weixinStatusPollTimer) {
        clearTimeout(_weixinStatusPollTimer);
        _weixinStatusPollTimer = null;
    }
}

function startWeixinActiveStatusPoll() {
    stopWeixinStatusPoll();
    _weixinStatusPollTimer = setTimeout(() => {
        fetch('/api/channels').then(r => r.json()).then(data => {
            if (data.status !== 'success') return;
            const wx = (data.channels || []).find(c => c.name === 'weixin');
            if (!wx || !wx.active) return;
            if (wx.login_status === 'logged_in') {
                channelsData = data.channels;
                renderActiveChannels();
            } else {
                const ch = channelsData.find(c => c.name === 'weixin');
                if (ch) ch.login_status = wx.login_status;
                startWeixinActiveStatusPoll();
            }
        }).catch(() => { startWeixinActiveStatusPoll(); });
    }, 3000);
}

function showWeixinActiveQr() {
    const container = document.getElementById('weixin-active-qr');
    if (!container) return;
    container.innerHTML = `
        <div id="weixin-qr-panel" class="flex flex-col items-center py-2">
            <p class="text-sm text-slate-500 dark:text-slate-400 mb-4">${t('weixin_scan_loading')}</p>
        </div>`;
    stopWeixinStatusPoll();
    startWeixinQrLogin();
}

function stopWeixinQrPoll() {
    if (_weixinQrPollTimer) {
        clearTimeout(_weixinQrPollTimer);
        _weixinQrPollTimer = null;
    }
}

function startWeixinQrLogin() {
    stopWeixinQrPoll();
    fetch('/api/weixin/qrlogin')
        .then(r => r.json())
        .then(data => {
            const panel = document.getElementById('weixin-qr-panel');
            if (!panel) return;
            if (data.status !== 'success') {
                panel.innerHTML = `<p class="text-sm text-red-500">${t('weixin_scan_fail')}: ${data.message || ''}</p>`;
                return;
            }
            renderWeixinQr(data.qr_image || data.qrcode_url, 'waiting');
            if (data.source === 'channel') {
                startWeixinActiveStatusPoll();
            } else {
                pollWeixinQrStatus();
            }
        })
        .catch(() => {
            const panel = document.getElementById('weixin-qr-panel');
            if (panel) panel.innerHTML = `<p class="text-sm text-red-500">${t('weixin_scan_fail')}</p>`;
        });
}

function renderWeixinQr(qrcodeUrl, status) {
    const panel = document.getElementById('weixin-qr-panel');
    if (!panel) return;

    let statusText = t('weixin_scan_waiting');
    let statusColor = 'text-slate-500 dark:text-slate-400';
    if (status === 'scanned') {
        statusText = t('weixin_scan_scanned');
        statusColor = 'text-primary-500';
    } else if (status === 'expired') {
        statusText = t('weixin_scan_expired');
        statusColor = 'text-amber-500';
    } else if (status === 'confirmed') {
        statusText = t('weixin_scan_success');
        statusColor = 'text-primary-500';
    }

    panel.innerHTML = `
        <div class="flex flex-col items-center">
            <p class="text-sm font-medium text-slate-700 dark:text-slate-200 mb-1">${t('weixin_scan_title')}</p>
            <p class="text-xs text-slate-400 dark:text-slate-500 mb-4">${t('weixin_scan_desc')}</p>
            <div class="bg-white p-3 rounded-xl shadow-sm border border-slate-100 dark:border-slate-700 mb-3">
                <img src="${escapeHtml(qrcodeUrl)}" alt="QR Code" class="w-52 h-52" style="image-rendering: pixelated;"/>
            </div>
            <p class="text-xs ${statusColor} mb-1">${statusText}</p>
            <p class="text-xs text-slate-400 dark:text-slate-500">${t('weixin_qr_tip')}</p>
        </div>`;
}

function pollWeixinQrStatus() {
    _weixinQrPollTimer = setTimeout(() => {
        fetch('/api/weixin/qrlogin', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'poll' })
        })
        .then(r => r.json())
        .then(data => {
            const panel = document.getElementById('weixin-qr-panel');
            if (!panel) { stopWeixinQrPoll(); return; }

            if (data.status !== 'success') {
                pollWeixinQrStatus();
                return;
            }

            const qrStatus = data.qr_status;
            if (qrStatus === 'confirmed') {
                renderWeixinQr('', 'confirmed');
                panel.innerHTML = `
                    <div class="flex flex-col items-center py-4">
                        <div class="w-12 h-12 rounded-full bg-primary-50 dark:bg-primary-900/30 flex items-center justify-center mb-3">
                            <i class="fas fa-check text-primary-500 text-lg"></i>
                        </div>
                        <p class="text-sm font-medium text-primary-600 dark:text-primary-400">${t('weixin_scan_success')}</p>
                    </div>`;
                connectWeixinAfterQr();
            } else if (qrStatus === 'expired' && (data.qr_image || data.qrcode_url)) {
                renderWeixinQr(data.qr_image || data.qrcode_url, 'waiting');
                pollWeixinQrStatus();
            } else if (qrStatus === 'scaned') {
                const img = panel.querySelector('img');
                const currentSrc = img ? img.src : '';
                renderWeixinQr(currentSrc, 'scanned');
                pollWeixinQrStatus();
            } else {
                pollWeixinQrStatus();
            }
        })
        .catch(() => {
            pollWeixinQrStatus();
        });
    }, 2000);
}

function connectWeixinAfterQr() {
    fetch('/api/channels', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'connect', channel: 'weixin', config: {} })
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'success') {
            // 多代理：新的微信实例只存在于服务器中
            // Channel_instances 还没有，它的卡片是从该列表中渲染的 -
            // 因此，重新加载频道视图以使其出现。重新渲染自
            // 过时的本地状态将丢弃新扫描的卡，直到
            // 手动刷新。旧版单实例修补本地状态。
            if (isMultiInstanceType('weixin') || data.instance_id) {
                setTimeout(() => loadChannelsView(), 1500);
                return;
            }
            const ch = channelsData.find(c => c.name === 'weixin');
            if (ch) ch.active = true;
            setTimeout(() => renderActiveChannels(), 1500);
        }
    })
    .catch(() => {});
}

// =====================================================================
// WeCom 机器人二维码验证
// =====================================================================
// 注意：这是 Web 控制台中唯一剩余的外部脚本。
// 腾讯的WeCom Bot SDK必须从他们的官方CDN加载 - 它
// 执行运行时来源/签名检查，如果
// 自托管。仅当用户打开 SDK 时才会延迟获取 SDK
// “WeCom Bot”通道 QR 登录流程，因此控制台的其余部分可以正常工作
// 完全离线。
const WECOM_BOT_SDK_URL = 'https://wwcdn.weixin.qq.com/node/wework/js/wecom-aibot-sdk@0.1.0.min.js';
const WECOM_BOT_SOURCE = 'cowagent';
let _wecomSdkLoaded = false;

function ensureWecomSdkLoaded() {
    return new Promise((resolve, reject) => {
        if (_wecomSdkLoaded && window.WecomAIBotSDK) { resolve(); return; }
        if (document.querySelector(`script[src="${WECOM_BOT_SDK_URL}"]`)) {
            _wecomSdkLoaded = true; resolve(); return;
        }
        const s = document.createElement('script');
        s.src = WECOM_BOT_SDK_URL;
        s.onload = () => { _wecomSdkLoaded = true; resolve(); };
        s.onerror = () => reject(new Error('Failed to load WecomAIBotSDK'));
        document.head.appendChild(s);
    });
}

function _wecomBotHasCreds(ch) {
    if (!ch || !ch.fields) return false;
    const idField = ch.fields.find(f => f.key === 'wecom_bot_id');
    const secretField = ch.fields.find(f => f.key === 'wecom_bot_secret');
    return !!(idField && idField.value && secretField && secretField.value);
}

function buildWecomBotPanel(ch) {
    const scanLabel = t('wecom_mode_scan');
    const manualLabel = t('wecom_mode_manual');
    const hasCreds = _wecomBotHasCreds(ch);
    const defaultMode = hasCreds ? 'manual' : 'scan';
    return `
        <div id="wecom-bot-panel" data-default-mode="${defaultMode}">
            <div class="flex items-center justify-center gap-1 mb-5 bg-slate-100 dark:bg-white/5 rounded-lg p-1">
                <button id="wecom-tab-scan" onclick="switchWecomBotMode('scan')"
                    class="flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-colors
                           bg-white dark:bg-slate-700 text-slate-800 dark:text-slate-100 shadow-sm">
                    ${scanLabel}
                </button>
                <button id="wecom-tab-manual" onclick="switchWecomBotMode('manual')"
                    class="flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-colors
                           text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200">
                    ${manualLabel}
                </button>
            </div>
            <div id="wecom-mode-content"></div>
        </div>`;
}

function switchWecomBotMode(mode) {
    const scanTab = document.getElementById('wecom-tab-scan');
    const manualTab = document.getElementById('wecom-tab-manual');
    const content = document.getElementById('wecom-mode-content');
    const actions = document.getElementById('add-channel-actions');
    if (!scanTab || !manualTab || !content) return;

    const activeClasses = 'bg-white dark:bg-slate-700 text-slate-800 dark:text-slate-100 shadow-sm';
    const inactiveClasses = 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200';

    if (mode === 'scan') {
        scanTab.className = scanTab.className.replace(/text-slate-500[^\s]*/g, '').replace(/hover:\S+/g, '');
        scanTab.className = `flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${activeClasses}`;
        manualTab.className = `flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${inactiveClasses}`;
        actions.classList.add('hidden');
        content.innerHTML = `
            <div class="flex flex-col items-center py-4">
                <p class="text-sm text-slate-600 dark:text-slate-300 mb-2">${t('wecom_scan_desc')}</p>
                <button onclick="startWecomBotAuth()"
                    class="mt-3 px-6 py-2.5 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-white text-sm font-medium
                           cursor-pointer transition-colors duration-150">
                    <i class="fas fa-qrcode mr-2"></i>${t('wecom_scan_btn')}
                </button>
                <div id="wecom-scan-status" class="mt-3"></div>
            </div>`;
    } else {
        manualTab.className = `flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${activeClasses}`;
        scanTab.className = `flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${inactiveClasses}`;
        const ch = channelsData.find(c => c.name === 'wecom_bot');
        content.innerHTML = `<div class="space-y-4">${buildChannelFieldsHtml('wecom_bot', ch ? ch.fields || [] : [])}</div>`;
        bindSecretFieldEvents(content);
        actions.classList.remove('hidden');
    }
}

function startWecomBotAuth() {
    const statusEl = document.getElementById('wecom-scan-status');
    ensureWecomSdkLoaded().then(() => {
        WecomAIBotSDK.openBotInfoAuthWindow({
            source: WECOM_BOT_SOURCE,
            onCreated: function(bot) {
                if (statusEl) {
                    statusEl.innerHTML = `
                        <div class="flex flex-col items-center py-2">
                            <div class="w-10 h-10 rounded-full bg-emerald-50 dark:bg-emerald-900/30 flex items-center justify-center mb-2">
                                <i class="fas fa-check text-emerald-500 text-lg"></i>
                            </div>
                            <p class="text-sm font-medium text-emerald-600 dark:text-emerald-400">${t('wecom_scan_success')}</p>
                        </div>`;
                }
                connectWecomBotAfterAuth(bot.botid, bot.secret);
            },
            onError: function(err) {
                if (statusEl) {
                    statusEl.innerHTML = `<p class="text-sm text-red-500">${t('wecom_scan_fail')}: ${err.message || err.code || ''}</p>`;
                }
            }
        });
    }).catch(err => {
        if (statusEl) {
            statusEl.innerHTML = `<p class="text-sm text-red-500">SDK load failed: ${err.message}</p>`;
        }
    });
}

function connectWecomBotAfterAuth(botId, secret) {
    fetch('/api/channels', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            action: 'connect',
            channel: 'wecom_bot',
            config: { wecom_bot_id: botId, wecom_bot_secret: secret }
        })
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'success') {
            const ch = channelsData.find(c => c.name === 'wecom_bot');
            if (ch) {
                ch.active = true;
                (ch.fields || []).forEach(f => {
                    if (f.key === 'wecom_bot_id') f.value = botId;
                    if (f.key === 'wecom_bot_secret') f.value = ChannelsHandler_maskSecret(secret);
                });
            }
            setTimeout(() => renderActiveChannels(), 1500);
        }
    })
    .catch(() => {});
}

function startWecomBotAuthInCard() {
    const statusEl = document.getElementById('wecom-card-scan-status');
    ensureWecomSdkLoaded().then(() => {
        WecomAIBotSDK.openBotInfoAuthWindow({
            source: WECOM_BOT_SOURCE,
            onCreated: function(bot) {
                if (statusEl) {
                    statusEl.innerHTML = `
                        <div class="flex flex-col items-center py-2">
                            <div class="w-10 h-10 rounded-full bg-emerald-50 dark:bg-emerald-900/30 flex items-center justify-center mb-2">
                                <i class="fas fa-check text-emerald-500 text-lg"></i>
                            </div>
                            <p class="text-sm font-medium text-emerald-600 dark:text-emerald-400">${t('wecom_scan_success')}</p>
                        </div>`;
                }
                connectWecomBotAfterAuth(bot.botid, bot.secret);
            },
            onError: function(err) {
                if (statusEl) {
                    statusEl.innerHTML = `<p class="text-sm text-red-500">${t('wecom_scan_fail')}: ${err.message || err.code || ''}</p>`;
                }
            }
        });
    }).catch(err => {
        if (statusEl) {
            statusEl.innerHTML = `<p class="text-sm text-red-500">SDK load failed: ${err.message}</p>`;
        }
    });
}

// 插入 DOM 时使用正确的默认模式初始化 wecom 机器人面板
document.addEventListener('DOMContentLoaded', function() {
    const observer = new MutationObserver(function() {
        const wecomPanel = document.getElementById('wecom-bot-panel');
        if (wecomPanel && !wecomPanel.dataset.initialized) {
            wecomPanel.dataset.initialized = '1';
            switchWecomBotMode(wecomPanel.dataset.defaultMode || 'scan');
        }
        // 初始化屏幕上的每个飞书面板，而不仅仅是第一个：多个
        // 实例卡可以同时出现，每张都有自己的 ID 后缀。
        document.querySelectorAll('.feishu-panel').forEach(feishuPanel => {
            if (feishuPanel.dataset.initialized) return;
            feishuPanel.dataset.initialized = '1';
            switchFeishuMode(feishuPanel.dataset.iid || 'feishu', feishuPanel.dataset.defaultMode || 'scan');
        });
    });
    observer.observe(document.body, { childList: true, subtree: true });
});

// =====================================================================
// 飞书一键应用注册（lark-oapi register_app）
// =====================================================================
let _feishuRegisterPollTimer = null;

function _feishuHasCreds(ch) {
    if (!ch || !ch.fields) return false;
    const idField = ch.fields.find(f => f.key === 'feishu_app_id');
    const secretField = ch.fields.find(f => f.key === 'feishu_app_secret');
    return !!(idField && idField.value && secretField && secretField.value);
}

function buildFeishuPanel(ch, isActive) {
    const scanLabel = t('feishu_mode_scan');
    const manualLabel = t('feishu_mode_manual');
    // 已有凭据时默认进入手动 Tab，方便修改；否则推荐扫码
    const defaultMode = _feishuHasCreds(ch) ? 'manual' : 'scan';
    const activeAttr = isActive ? 'data-active="1"' : '';
    // 面板中的每个 DOM id 都带有实例 id 后缀，因此两个 feishu
    // 屏幕上的卡片永远不会碰撞：没有这个， getElementById()
    // 始终解析为第一张卡，因此第二张卡已失效且其选项卡
    // 点击驱动第一个。添加面板（还没有实例）使用裸露的
    // “飞书”后缀；活动实例卡使用其真实实例 ID。
    const iid = (isActive && ch && ch.iid) ? ch.iid : 'feishu';
    return `
        <div id="feishu-panel-${iid}" class="feishu-panel" data-default-mode="${defaultMode}" data-iid="${escapeHtml(iid)}" ${activeAttr}>
            <div class="flex items-center justify-center gap-1 mb-5 bg-slate-100 dark:bg-white/5 rounded-lg p-1">
                <button id="feishu-tab-scan-${iid}" onclick="switchFeishuMode('${iid}', 'scan')"
                    class="flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-colors
                           bg-white dark:bg-slate-700 text-slate-800 dark:text-slate-100 shadow-sm">
                    ${scanLabel}
                </button>
                <button id="feishu-tab-manual-${iid}" onclick="switchFeishuMode('${iid}', 'manual')"
                    class="flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-colors
                           text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200">
                    ${manualLabel}
                </button>
            </div>
            <div id="feishu-mode-content-${iid}"></div>
        </div>`;
}

function switchFeishuMode(iid, mode) {
    // 向后兼容：旧的调用站点仅传递模式。将裸模式视为
    // 添加面板的“飞书”实例。
    if (mode === undefined && (iid === 'scan' || iid === 'manual')) {
        mode = iid;
        iid = 'feishu';
    }
    iid = iid || 'feishu';
    const panel = document.getElementById(`feishu-panel-${iid}`);
    const scanTab = document.getElementById(`feishu-tab-scan-${iid}`);
    const manualTab = document.getElementById(`feishu-tab-manual-${iid}`);
    const content = document.getElementById(`feishu-mode-content-${iid}`);
    if (!scanTab || !manualTab || !content) return;

    // 已激活通道卡片中嵌入此 panel 时，没有 add-channel-actions（保存按钮就近渲染）
    const isActive = panel && panel.dataset.active === '1';
    const actions = isActive ? null : document.getElementById('add-channel-actions');
    const scanStatusId = `feishu-scan-status-${iid}`;

    const activeClasses = 'bg-white dark:bg-slate-700 text-slate-800 dark:text-slate-100 shadow-sm';
    const inactiveClasses = 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200';

    stopFeishuRegisterPoll();

    if (mode === 'scan') {
        scanTab.className = `flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${activeClasses}`;
        manualTab.className = `flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${inactiveClasses}`;
        if (actions) actions.classList.add('hidden');
        // active 卡片下扫码替换的提示文案，强调"创建新机器人会覆盖现有配置"
        const desc = isActive
            ? t('feishu_scan_replace_desc')
            : t('feishu_scan_desc');
        content.innerHTML = `
            <div class="flex flex-col items-center py-4">
                <p class="text-sm text-slate-600 dark:text-slate-300 mb-3 text-center">${desc}</p>
                <button onclick="startFeishuRegister('${scanStatusId}')"
                    class="mt-2 px-6 py-2.5 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-white text-sm font-medium
                           cursor-pointer transition-colors duration-150">
                    <i class="fas fa-qrcode mr-2"></i>${t('feishu_scan_btn')}
                </button>
                <div id="${scanStatusId}" class="mt-4 w-full"></div>
            </div>`;
    } else {
        manualTab.className = `flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${activeClasses}`;
        scanTab.className = `flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${inactiveClasses}`;
        // 活动实例卡通过实例 ID 为其字段设置关键字（因此
        // 卡的数据通道查询和保存目标队列）；添加面板按键
        // 由于尚不存在实例，因此使用裸类型。
        const ch = (isActive && iid !== 'feishu')
            ? channelInstancesView.find(c => c.instance_id === iid)
            : channelsData.find(c => c.name === 'feishu');
        const fieldsHtml = buildChannelFieldsHtml(iid, ch ? ch.fields || [] : []);
        if (isActive) {
            // 已接入卡片：内置保存按钮，复用 saveChannelConfig 走 update 流程
            content.innerHTML = `
                <div class="space-y-4">
                    ${fieldsHtml}
                    <div class="flex items-center justify-end gap-3 pt-1">
                        <span id="ch-status-${iid}" class="text-xs text-primary-500 opacity-0 transition-opacity duration-300"></span>
                        <button onclick="saveChannelConfig('feishu', '${iid === 'feishu' ? '' : iid}')"
                            class="px-4 py-2 rounded-lg bg-primary-500 hover:bg-primary-600 text-white text-sm font-medium
                                   cursor-pointer transition-colors duration-150 disabled:opacity-50 disabled:cursor-not-allowed"
                            id="ch-save-${iid}">${t('channels_save')}</button>
                    </div>
                </div>`;
        } else {
            content.innerHTML = `<div class="space-y-4">${fieldsHtml}</div>`;
            if (actions) actions.classList.remove('hidden');
        }
        bindSecretFieldEvents(content);
    }
}

function stopFeishuRegisterPoll() {
    if (_feishuRegisterPollTimer) {
        clearTimeout(_feishuRegisterPollTimer);
        _feishuRegisterPollTimer = null;
    }
}

function startFeishuRegister(targetStatusId) {
    const statusId = targetStatusId || 'feishu-scan-status';
    const statusEl = document.getElementById(statusId);
    if (statusEl) {
        statusEl.innerHTML = `<p class="text-sm text-slate-500 dark:text-slate-400 text-center">${t('feishu_scan_loading')}</p>`;
    }
    stopFeishuRegisterPoll();
    fetch('/api/feishu/register')
        .then(r => r.json())
        .then(data => {
            if (data.status !== 'success') {
                renderFeishuRegisterError(statusId, data.message || t('feishu_scan_fail'));
                return;
            }
            if (data.register_status === 'downloading') {
                // 桌面首次运行：SDK 捆绑包在 QR 存在之前落地。
                renderFeishuSdkDownloading(statusId);
            } else {
                renderFeishuQr(statusId, data.qr_image, data.qrcode_url);
            }
            pollFeishuRegisterStatus(statusId);
        })
        .catch(err => {
            renderFeishuRegisterError(statusId, err.message || t('feishu_scan_fail'));
        });
}

function renderFeishuQr(statusId, qrImage, qrUrl) {
    const statusEl = document.getElementById(statusId);
    if (!statusEl) return;
    const imgHtml = qrImage
        ? `<img src="${qrImage}" alt="QR" class="w-44 h-44 rounded-lg border border-slate-200 dark:border-white/10 bg-white p-2"/>`
        : `<div class="w-44 h-44 rounded-lg border border-dashed border-slate-300 flex items-center justify-center text-xs text-slate-400">QR</div>`;
    statusEl.innerHTML = `
        <div class="flex flex-col items-center gap-3">
            ${imgHtml}
            <p class="text-xs text-amber-500">${t('feishu_scan_waiting')}</p>
            <p class="text-xs text-slate-400 dark:text-slate-500">${t('feishu_scan_tip')}</p>
            ${qrUrl ? `<a href="${qrUrl}" target="_blank" rel="noopener"
                class="text-xs text-blue-500 hover:text-blue-600 underline">${t('feishu_scan_open_link')}</a>` : ''}
        </div>`;
}

function renderFeishuSdkDownloading(statusId) {
    const statusEl = document.getElementById(statusId);
    if (!statusEl) return;
    statusEl.innerHTML = `
        <div class="flex flex-col items-center gap-2 py-6">
            <i class="fas fa-spinner fa-spin text-slate-400"></i>
            <p class="text-sm text-slate-500 dark:text-slate-400">${t('feishu_sdk_downloading')}</p>
            <p class="text-xs text-slate-400 dark:text-slate-500">${t('feishu_sdk_downloading_tip')}</p>
        </div>`;
}

function renderFeishuRegisterError(statusId, message) {
    const statusEl = document.getElementById(statusId);
    if (!statusEl) return;
    statusEl.innerHTML = `
        <div class="flex flex-col items-center gap-2 py-2">
            <p class="text-sm text-red-500 text-center">${message}</p>
            <button onclick="startFeishuRegister('${statusId}')"
                class="mt-1 px-4 py-1.5 rounded-md text-xs font-medium
                       bg-slate-100 dark:bg-white/10 text-slate-700 dark:text-slate-200
                       hover:bg-slate-200 dark:hover:bg-white/20 cursor-pointer">
                <i class="fas fa-rotate-right mr-1"></i>${t('feishu_scan_retry')}
            </button>
        </div>`;
}

function pollFeishuRegisterStatus(statusId) {
    stopFeishuRegisterPoll();
    _feishuRegisterPollTimer = setTimeout(() => {
        fetch('/api/feishu/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'poll' })
        })
        .then(r => r.json())
        .then(data => {
            if (data.status !== 'success') {
                renderFeishuRegisterError(statusId, data.message || t('feishu_scan_fail'));
                return;
            }
            const rs = data.register_status;
            if (rs === 'downloading') {
                renderFeishuSdkDownloading(statusId);
                pollFeishuRegisterStatus(statusId);
                return;
            }
            // QR 只能在捆绑包下载后生成，在
            // 这种情况下初始的GET就无法携带它。渲染一次；
            // 对每个民意调查重新绘制都会使其闪烁。
            const shown = document.getElementById(statusId);
            if ((data.qr_image || data.qrcode_url) && shown && !shown.querySelector('img')) {
                renderFeishuQr(statusId, data.qr_image, data.qrcode_url);
            }
            if (rs === 'done') {
                const statusEl = document.getElementById(statusId);
                if (statusEl) {
                    statusEl.innerHTML = `
                        <div class="flex flex-col items-center py-2">
                            <div class="w-10 h-10 rounded-full bg-emerald-50 dark:bg-emerald-900/30 flex items-center justify-center mb-2">
                                <i class="fas fa-check text-emerald-500 text-lg"></i>
                            </div>
                            <p class="text-sm font-medium text-emerald-600 dark:text-emerald-400">${t('feishu_scan_success')}</p>
                        </div>`;
                }
                connectFeishuAfterRegister(data.app_id, data.app_secret);
            } else if (rs === 'expired') {
                renderFeishuRegisterError(statusId, t('feishu_scan_expired'));
            } else if (rs === 'denied') {
                renderFeishuRegisterError(statusId, t('feishu_scan_denied'));
            } else if (rs === 'error') {
                renderFeishuRegisterError(statusId, data.message || t('feishu_scan_fail'));
            } else {
                pollFeishuRegisterStatus(statusId);
            }
        })
        .catch(() => {
            pollFeishuRegisterStatus(statusId);
        });
    }, 2000);
}

function connectFeishuAfterRegister(appId, appSecret) {
    fetch('/api/channels', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            action: 'connect',
            channel: 'feishu',
            config: { feishu_app_id: appId, feishu_app_secret: appSecret }
        })
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'success') {
            // Multi-Agent模式在服务器端创建了一个新的飞书实例；重新加载
            // 所以它的卡片出现了。传统模式修补本地状态。
            if (isMultiInstanceType('feishu') || data.instance_id) {
                setTimeout(() => loadChannelsView(), 1500);
                return;
            }
            const ch = channelsData.find(c => c.name === 'feishu');
            if (ch) {
                ch.active = true;
                (ch.fields || []).forEach(f => {
                    if (f.key === 'feishu_app_id') f.value = appId;
                    if (f.key === 'feishu_app_secret') f.value = ChannelsHandler_maskSecret(appSecret);
                });
            }
            setTimeout(() => renderActiveChannels(), 1500);
        }
    })
    .catch(() => {});
}

// =====================================================================
// 调度程序视图
// =====================================================================
let tasksLoaded = false;
function refreshTasksView() {
    const btn = document.getElementById('task-refresh-btn');
    const icon = btn.querySelector('i');
    
    // 添加旋转动画
    icon.classList.add('fa-spin');
    btn.disabled = true;
    
    tasksLoaded = false;
    const listEl = document.getElementById('tasks-list');
    listEl.innerHTML = '';
    
    loadTasksView();
    
    // 动画结束后恢复按钮
    setTimeout(() => {
        icon.classList.remove('fa-spin');
        btn.disabled = false;
    }, 500);
}

function runTaskNow(task, button) {
    showConfirmDialog({
        title: t('task_run_confirm_title'),
        message: `${task.name || task.id}: ${t('task_run_confirm_msg')}`,
        okText: t('task_run_now'),
        onConfirm: () => {
            const originalHtml = button.innerHTML;
            button.disabled = true;
            button.innerHTML = `<i class="fas fa-spinner fa-spin mr-1"></i>${t('task_run_now')}`;
            fetch('/api/scheduler/run', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({task_id: task.id, agent_id: task.agent_id || ''})
            }).then(r => r.json()).then(res => {
                if (res.status !== 'success') throw new Error(res.message || t('task_run_failed'));
                button.innerHTML = `<i class="fas fa-check mr-1"></i>${t('task_run_started')}`;
                setTimeout(() => {
                    button.innerHTML = originalHtml;
                    button.disabled = false;
                }, 1500);
            }).catch(() => {
                button.innerHTML = `<i class="fas fa-triangle-exclamation mr-1"></i>${t('task_run_failed')}`;
                setTimeout(() => {
                    button.innerHTML = originalHtml;
                    button.disabled = false;
                }, 2000);
            });
        }
    });
}

function loadTasksView() {
    if (tasksLoaded) return;
    // 该列表用所属代理标记每个任务；确保名册在
    // 先手，这样 findAgent()/multiAgentMode() 就可以解析头像 + 姓名。
    const rosterReady = agentCatalog.length ? Promise.resolve() : loadAgentCatalog();
    rosterReady.then(() => {
    // 显式空的agent_id，因此全局获取包装器不会注入
    // 主动聊天Agent：任务清单是整个团队的日程安排，必须
    // 不要关注当前正在进行对话的任何代理。后端
    // 将空的agent_id视为“所有代理的聚合”。
    fetch('/api/scheduler?agent_id=').then(r => r.json()).then(data => {
        if (data.status !== 'success') return;
        const emptyEl = document.getElementById('tasks-empty');
        const listEl = document.getElementById('tasks-list');
        const allTasks = data.tasks || [];
        // 后端已按enabled和next_run_at排序，无需在前端重新排序
        if (allTasks.length === 0) {
            emptyEl.querySelector('p').textContent = currentLang === 'zh' ? '暂无定时任务' : 'No scheduled tasks';
            emptyEl.classList.remove('hidden');
            listEl.classList.add('hidden');
            tasksLoaded = true;
            return;
        }
        emptyEl.classList.add('hidden');
        listEl.classList.remove('hidden');
        listEl.innerHTML = '';

        allTasks.forEach(task => {
            const isEnabled = task.enabled !== false;
            const card = document.createElement('div');
            card.className = 'bg-white dark:bg-[#1A1A1A] rounded-xl border border-slate-200 dark:border-white/10 p-4';
            card.dataset.taskId = task.id;
            if (!isEnabled) card.classList.add('opacity-50');
            const schedule = task.schedule || {};
            let typeLabel = '';
            if (schedule.type === 'cron') {
                typeLabel = `<span class="text-xs font-mono text-slate-400">${escapeHtml(schedule.expression || '')}</span>`;
            } else if (schedule.type === 'interval') {
                const seconds = schedule.seconds || 0;
                const hours = Math.floor(seconds / 3600);
                const mins = Math.floor((seconds % 3600) / 60);
                const secs = seconds % 60;
                let intervalText = [];
                if (hours > 0) intervalText.push(`${hours}h`);
                if (mins > 0) intervalText.push(`${mins}m`);
                if (secs > 0 || intervalText.length === 0) intervalText.push(`${secs}s`);
                typeLabel = `<span class="text-xs text-slate-400">${intervalText.join(' ')}</span>`;
            } else {
                typeLabel = `<span class="text-xs text-slate-400">${escapeHtml(schedule.type || 'once')}</span>`;
            }
            let nextRun = '--';
            if (task.next_run_at) {
                const d = new Date(task.next_run_at);
                if (!isNaN(d.getTime())) nextRun = d.toLocaleString();
            }
            const action = task.action || {};
            const taskContent = action.content || action.task_description || '';
            const toggleId = 'toggle-' + task.id;
            // 所有者芯片：仅当存在多个 Agent 时（否则每个任务
            // 带有相同的面孔，这只是噪音）。单独安装时为空。
            const owner = (multiAgentMode() && task.agent_id) ? findAgent(task.agent_id) : null;
            const ownerChip = owner
                ? `<span class="inline-flex items-center gap-1 ml-2 pl-1 pr-1.5 py-0.5 rounded-full bg-slate-100 dark:bg-white/10 text-[10px] leading-none text-slate-400 dark:text-slate-500">
                        ${agentAvatarHTML(owner, 15)}<span class="truncate max-w-[80px]">${escapeHtml(owner.name || owner.id)}</span>
                   </span>`
                : '';
            card.innerHTML = `
                <div class="flex items-center gap-2 mb-2">
                    <span class="w-2 h-2 rounded-full ${isEnabled ? 'bg-primary-400' : 'bg-slate-300 dark:bg-slate-600'}"></span>
                    <span class="font-medium text-sm text-slate-700 dark:text-slate-200">${escapeHtml(task.name || task.id || '--')}</span>
                    ${ownerChip}
                    <div class="flex-1"></div>
                    ${typeLabel}
                </div>
                <p class="text-xs text-slate-500 dark:text-slate-400 mb-2 line-clamp-2">${escapeHtml(taskContent)}</p>
                <div class="flex items-center gap-4 text-xs text-slate-400 dark:text-slate-500">
                    <span><i class="fas fa-clock mr-1"></i>${currentLang === 'zh' ? '下次执行' : 'Next run'}: ${nextRun}</span>
                    <div class="flex-1"></div>
                    <button type="button" class="task-run-now px-2 py-1 rounded-md text-primary-500 hover:bg-primary-50 dark:hover:bg-primary-500/10 transition-colors">
                        <i class="fas fa-play mr-1"></i>${t('task_run_now')}
                    </button>
                    <label class="relative inline-flex items-center cursor-pointer" for="${toggleId}">
                        <input type="checkbox" id="${toggleId}" class="sr-only peer" ${isEnabled ? 'checked' : ''}>
                        <div class="w-9 h-5 bg-slate-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-primary-500 dark:bg-slate-600 dark:peer-checked:bg-primary-500"></div>
                    </label>
                </div>`;
            const runButton = card.querySelector('.task-run-now');
            runButton.addEventListener('click', function(e) {
                e.stopPropagation();
                runTaskNow(task, runButton);
            });
            const checkbox = card.querySelector('#' + toggleId);
            checkbox.addEventListener('change', function() {
                const newEnabled = this.checked;
                fetch('/api/scheduler/toggle', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({task_id: task.id, enabled: newEnabled, agent_id: task.agent_id || ''})
                }).then(r => r.json()).then(res => {
                    if (res.status === 'success') {
                        const dot = card.querySelector('.rounded-full.w-2');
                        if (newEnabled) {
                            card.classList.remove('opacity-50');
                            if (dot) { dot.classList.remove('bg-slate-300','dark:bg-slate-600'); dot.classList.add('bg-primary-400'); }
                        } else {
                            card.classList.add('opacity-50');
                            if (dot) { dot.classList.remove('bg-primary-400'); dot.classList.add('bg-slate-300','dark:bg-slate-600'); }
                        }
                    } else {
                        this.checked = !newEnabled;
                    }
                }).catch(() => { this.checked = !newEnabled; });
            });
            // 卡点击事件（不包括切换开关点击）
            card.addEventListener('click', function(e) {
                if (!e.target.closest('label') && !e.target.closest('input[type="checkbox"]')) {
                    openTaskEditModal(task);
                }
            });
            card.style.cursor = 'pointer';
            listEl.appendChild(card);
        });
        tasksLoaded = true;
    }).catch(() => {});
    });
}

// =====================================================================
// 日志查看
// =====================================================================
let logEventSource = null;

function logLevelClass(line) {
    if (/\[CRITICAL\]/.test(line)) return 'log-line-critical';
    if (/\[ERROR\]/.test(line))    return 'log-line-error';
    if (/\[WARNING\]/.test(line))  return 'log-line-warning';
    if (/\[INFO\]/.test(line))     return 'log-line-info';
    if (/\[DEBUG\]/.test(line))    return 'log-line-debug';
    return '';
}

function getHiddenLevels() {
    const hidden = new Set();
    document.querySelectorAll('.log-filter-cb').forEach(function(cb) {
        if (!cb.checked) hidden.add('log-line-' + cb.dataset.level);
    });
    return hidden;
}

function applyLogFilter() {
    const hidden = getHiddenLevels();
    document.querySelectorAll('#log-output .log-line').forEach(function(span) {
        const level = span.classList[1] || '';
        span.style.display = hidden.has(level) ? 'none' : '';
    });
}

function appendLogLines(output, text) {
    const hidden = getHiddenLevels();
    let lastLevelClass = '';
    const lines = text.split('\n');
    lines.forEach(function(line, i) {
        if (i === lines.length - 1 && line === '') return;
        const span = document.createElement('span');
        const levelClass = logLevelClass(line) || lastLevelClass;
        if (logLevelClass(line)) lastLevelClass = levelClass;
        span.className = 'log-line ' + levelClass;
        span.textContent = line + '\n';
        if (hidden.has(levelClass)) span.style.display = 'none';
        output.appendChild(span);
    });
}

document.addEventListener('change', function(e) {
    if (e.target.classList.contains('log-filter-cb')) applyLogFilter();
});

function startLogStream() {
    if (logEventSource) return;
    const output = document.getElementById('log-output');
    output.innerHTML = '';

    logEventSource = new EventSource('/api/logs');
    logEventSource.onmessage = function(e) {
        let item;
        try { item = JSON.parse(e.data); } catch (_) { return; }

        if (item.type === 'init') {
            output.innerHTML = '';
            appendLogLines(output, item.content || '');
            output.scrollTop = output.scrollHeight;
        } else if (item.type === 'line') {
            appendLogLines(output, item.content);
            output.scrollTop = output.scrollHeight;
        } else if (item.type === 'error') {
            output.textContent = item.message || 'Error loading logs';
        }
    };
    logEventSource.onerror = function() {
        logEventSource.close();
        logEventSource = null;
    };
}

function stopLogStream() {
    if (logEventSource) {
        logEventSource.close();
        logEventSource = null;
    }
}

// =====================================================================
// 查看导航挂钩
// =====================================================================
const _origNavigateTo = navigateTo;
navigateTo = function(viewId) {
    // 一个打开的文档编辑器即将被另一个视图取代，该视图
    // 会在屏幕上没有任何内容说明的情况下放弃编辑。
    if (!docGuardUnsaved(() => navigateTo(viewId))) return;

    // 离开日志视图时停止日志流
    if (currentView === 'logs' && viewId !== 'logs') stopLogStream();

    _origNavigateTo(viewId);

    // 延迟加载视图数据
    if (viewId === 'config') { loadConfigView(); switchConfigTab('basic'); }
    else if (viewId === 'skills') { resetSkillViewer(); loadSkillsView(); }
    else if (viewId === 'memory') {
        memoryEditor.forget();
        document.getElementById('memory-panel-viewer').classList.add('hidden');
        document.getElementById('memory-panel-list').classList.remove('hidden');
        // 刷新时保留上次查看的代理，但如果发生这种情况则将其删除
        // 特工已被删除，所以我们不会指着幽灵。
        if (memoryAgentId && agentCatalog.length && !agentCatalog.some(a => a.id === memoryAgentId)) {
            memoryAgentId = '';
            localStorage.removeItem('cow_memory_agent');
        }
        if (!memoryAgentId) memoryAgentId = activeAgentId || defaultAgentId;
        renderMemoryAgentSelect();
        switchMemoryTab('files');
    }
    else if (viewId === 'knowledge') loadKnowledgeView();
    else if (viewId === 'channels') loadChannelsView();
    else if (viewId === 'tasks') loadTasksView();
    else if (viewId === 'logs') startLogStream();
};

// =====================================================================
// 知识观
// =====================================================================
let _knowledgeTreeData = [];
let _knowledgeRootFiles = [];
let _knowledgeCurrentFile = null;
let _knowledgeGraphLoaded = false;
const KNOWLEDGE_IMPORT_MAX_FILES = 100;
const KNOWLEDGE_IMPORT_MAX_FILE_SIZE = 10 * 1024 * 1024;
const KNOWLEDGE_IMPORT_MAX_TOTAL_SIZE = 200 * 1024 * 1024;

// 页面正在查看哪个代理的知识库。像记忆一样一直存在
// 页面的选择器，以便刷新保留最后的选择。 “共享”模式下的代理
// 解析为后端的共享基础，因此这只是简单地限定了视图的范围。
let knowledgeAgentId = localStorage.getItem('cow_knowledge_agent') || '';

function viewingKnowledgeAgentId() {
    return knowledgeAgentId || activeAgentId || defaultAgentId;
}

// 将查看的代理附加到知识 URL。仅全局获取包装器
// 当不存在 agent_id 时注入 activeAgentId，因此显式的会获胜。
function _kbUrl(path) {
    const joiner = path.includes('?') ? '&' : '?';
    return `${path}${joiner}agent_id=${encodeURIComponent(viewingKnowledgeAgentId())}`;
}

function renderKnowledgeAgentSelect() {
    const el = document.getElementById('knowledge-agent-select');
    if (!el) return;
    const current = viewingKnowledgeAgentId();
    const list = agentCatalog.length ? agentCatalog : enabledAgents();
    const options = list.map(a => ({ value: a.id, label: a.name || a.id, agent: a }));
    initDropdown(el, options, current, (value) => selectKnowledgeAgent(value), { withAvatar: true });
}

function selectKnowledgeAgent(agentId) {
    knowledgeAgentId = agentId;
    localStorage.setItem('cow_knowledge_agent', agentId);
    loadKnowledgeView();
}

function loadKnowledgeView(targetPath) {
    // 重置到文档选项卡
    switchKnowledgeTab('docs');
    _knowledgeGraphLoaded = false;
    _knowledgeCurrentFile = null;

    // 删除已删除的代理选择，这样我们就不会指向幽灵。
    if (knowledgeAgentId && agentCatalog.length && !agentCatalog.some(a => a.id === knowledgeAgentId)) {
        knowledgeAgentId = '';
        localStorage.removeItem('cow_knowledge_agent');
    }
    renderKnowledgeAgentSelect();

    fetch(_kbUrl('/api/knowledge/list')).then(r => r.json()).then(data => {
        if (data.status !== 'success') return;
        initKnowledgeImportDropZone();

        const emptyEl = document.getElementById('knowledge-empty');
        const docsPanel = document.getElementById('knowledge-panel-docs');
        const statsEl = document.getElementById('knowledge-stats');

        const tree = data.tree || [];
        const rootFiles = data.root_files || [];
        _knowledgeTreeData = tree;
        _knowledgeRootFiles = rootFiles;
        const stats = data.stats || {};
        const totalPages = stats.pages || 0;
        const sizeStr = stats.size < 1024 ? stats.size + ' B' : (stats.size / 1024).toFixed(1) + ' KB';

        statsEl.textContent = totalPages + ' pages · ' + sizeStr;

        if (totalPages === 0 && tree.length === 0 && rootFiles.length === 0) {
            emptyEl.querySelector('p').textContent = t('knowledge_empty_hint');
            const guideEl = document.getElementById('knowledge-empty-guide');
            if (guideEl) guideEl.classList.remove('hidden');
            emptyEl.classList.remove('hidden');
            docsPanel.classList.add('hidden');
            return;
        }
        emptyEl.classList.add('hidden');
        docsPanel.classList.remove('hidden');

        renderKnowledgeTree(tree, rootFiles);

        // 更喜欢打开刚刚创建/导入的文件；确保其组是
        // 展开以便活动项目在树中可见。
        const targetTitle = targetPath ? _findKnowledgeFileTitle(targetPath) : null;
        if (targetTitle !== null) {
            _expandKnowledgeGroupFor(targetPath);
            openKnowledgeFile(targetPath, targetTitle);
            return;
        }

        // 自动选择第一个文件（仅限桌面）
        if (window.innerWidth >= 768) {
            const firstFile = rootFiles.length > 0 ? rootFiles[0] : null;
            const firstGroup = !firstFile ? tree.find(g => g.files && g.files.length > 0) : null;
            if (firstFile) {
                openKnowledgeFile(firstFile.name, firstFile.title);
            } else if (firstGroup) {
                const gf = firstGroup.files[0];
                openKnowledgeFile(firstGroup.dir + '/' + gf.name, gf.title);
            }
        } else {
            document.getElementById('knowledge-content-placeholder').classList.add('hidden');
            document.getElementById('knowledge-content-viewer').classList.add('hidden');
        }
    }).catch(() => {});
}

// 通过知识树中的相对路径查找文件的显示标题。
// 返回标题，如果路径不存在，则返回 null。
function _findKnowledgeFileTitle(path) {
    if (!path) return null;
    const rootHit = (_knowledgeRootFiles || []).find(f => f.name === path);
    if (rootHit) return rootHit.title || rootHit.name;
    const walk = (groups, parentPath) => {
        for (const group of groups || []) {
            const groupPath = parentPath ? `${parentPath}/${group.dir}` : group.dir;
            const hit = (group.files || []).find(f => `${groupPath}/${f.name}` === path);
            if (hit) return hit.title || hit.name;
            const childHit = walk(group.children, groupPath);
            if (childHit !== null) return childHit;
        }
        return null;
    };
    return walk(_knowledgeTreeData, '');
}

// 打开给定文件路径的每个祖先组，使其可见。
function _expandKnowledgeGroupFor(path) {
    if (!path || !path.includes('/')) return;
    const target = document.querySelector(`.knowledge-tree-file[data-path="${CSS.escape(path)}"]`);
    let node = target ? target.closest('.knowledge-tree-group') : null;
    while (node) {
        node.classList.add('open');
        node = node.parentElement ? node.parentElement.closest('.knowledge-tree-group') : null;
    }
}

function renderKnowledgeTree(tree, rootFilesOrFilter, filter) {
    const container = document.getElementById('knowledge-tree');
    container.innerHTML = '';
    let rootFiles, lowerFilter;
    if (typeof rootFilesOrFilter === 'string') {
        rootFiles = _knowledgeRootFiles;
        lowerFilter = (rootFilesOrFilter || '').toLowerCase();
    } else {
        rootFiles = rootFilesOrFilter || _knowledgeRootFiles;
        lowerFilter = (filter || '').toLowerCase();
    }
    (rootFiles || []).forEach(f => {
        if (lowerFilter && !f.title.toLowerCase().includes(lowerFilter) && !f.name.toLowerCase().includes(lowerFilter)) return;
        const fbtn = document.createElement('button');
        fbtn.className = 'knowledge-tree-file' + (_knowledgeCurrentFile === f.name ? ' active' : '');
        fbtn.dataset.path = f.name;
        fbtn.innerHTML = `<i class="fas fa-file-lines text-[10px] text-slate-400"></i><span class="truncate">${escapeHtml(f.title)}</span>${_knowledgeFileActions(f.name)}`;
        fbtn.onclick = () => openKnowledgeFile(f.name, f.title);
        container.appendChild(fbtn);
    });
    _renderKnowledgeGroups(container, tree, '', lowerFilter, 0);
}

function _renderKnowledgeGroups(container, groups, parentPath, lowerFilter, depth) {
    const indent = depth * 12;
    groups.forEach(group => {
        const groupPath = parentPath ? parentPath + '/' + group.dir : group.dir;
        const files = (group.files || []).filter(f =>
            !lowerFilter || f.title.toLowerCase().includes(lowerFilter) || f.name.toLowerCase().includes(lowerFilter)
        );
        const children = group.children || [];
        const hasMatchingChildren = lowerFilter ? _hasFilterMatch(children, lowerFilter) : children.length > 0;
        if (files.length === 0 && !hasMatchingChildren && lowerFilter) return;

        const div = document.createElement('div');
        div.className = 'knowledge-tree-group open';

        const fileCount = _countFiles(group);
        const btn = document.createElement('button');
        btn.className = 'knowledge-tree-group-btn';
        btn.style.paddingLeft = (8 + indent) + 'px';
        btn.innerHTML = `<i class="fas fa-chevron-right chevron"></i><i class="fas fa-folder text-amber-400 text-[11px]"></i><span>${escapeHtml(group.dir)}</span><span class="ml-auto text-[10px] text-slate-400">${fileCount}</span>${_knowledgeCategoryActions(groupPath)}`;
        btn.onclick = () => div.classList.toggle('open');
        div.appendChild(btn);

        const items = document.createElement('div');
        items.className = 'knowledge-tree-group-items';
        files.forEach(f => {
            const fbtn = document.createElement('button');
            const fpath = groupPath + '/' + f.name;
            fbtn.className = 'knowledge-tree-file' + (_knowledgeCurrentFile === fpath ? ' active' : '');
            fbtn.dataset.path = fpath;
            fbtn.style.paddingLeft = (24 + indent) + 'px';
            fbtn.innerHTML = `<i class="fas fa-file-lines text-[10px] text-slate-400"></i><span class="truncate">${escapeHtml(f.title)}</span>${_knowledgeFileActions(fpath)}`;
            fbtn.onclick = () => openKnowledgeFile(fpath, f.title);
            items.appendChild(fbtn);
        });
        if (children.length > 0) {
            _renderKnowledgeGroups(items, children, groupPath, lowerFilter, depth + 1);
        }
        div.appendChild(items);
        container.appendChild(div);
    });
}

function _knowledgeActionButton(icon, title, handler) {
    const danger = icon === 'fa-trash' ? ' danger' : '';
    return `<span role="button" tabindex="0" title="${escapeHtml(title)}" onclick="event.stopPropagation();${handler}" class="knowledge-action${danger}"><i class="fas ${icon}"></i></span>`;
}

function _knowledgeFileActions(path) {
    if (path === 'index.md' || path === 'log.md') return '';
    const value = JSON.stringify(path).replace(/"/g, '&quot;');
    return `<span class="knowledge-actions">${_knowledgeActionButton('fa-arrow-right-arrow-left', '移动', `moveKnowledgeDocument(${value})`)}${_knowledgeActionButton('fa-trash', '删除', `deleteKnowledgeDocument(${value})`)}</span>`;
}

function _knowledgeCategoryActions(path) {
    const value = JSON.stringify(path).replace(/"/g, '&quot;');
    return `<span class="knowledge-actions">${_knowledgeActionButton('fa-pen', '重命名', `renameKnowledgeCategory(${value})`)}${_knowledgeActionButton('fa-trash', '删除', `deleteKnowledgeCategory(${value})`)}</span>`;
}

async function dispatchKnowledgeAction(action, payload, openPathResolver) {
    _setKnowledgeStatus(currentLang === 'zh' ? '处理中...' : 'Working...', false, true);
    try {
        const response = await fetch('/api/knowledge/action', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({action, payload, agent_id: viewingKnowledgeAgentId()}),
        });
        const result = await response.json();
        if (result.status !== 'success') {
            _setKnowledgeStatus(result.message || (currentLang === 'zh' ? '操作失败' : 'Operation failed'), true);
            loadKnowledgeView();
            return null;
        }
        _setKnowledgeStatus(_knowledgeResultMessage(action, result.payload), false);
        // （可选）在树刷新后自动打开受影响的文件。
        const openPath = openPathResolver ? openPathResolver(result.payload) : null;
        loadKnowledgeView(openPath || undefined);
        return result.payload;
    } catch (error) {
        _setKnowledgeStatus(currentLang === 'zh' ? '请求失败，请稍后重试' : 'Request failed, please try again', true);
        return null;
    }
}

function _setKnowledgeStatus(message, isError, persistent) {
    const el = document.getElementById('knowledge-action-status');
    el.textContent = message;
    el.className = `text-xs transition-opacity duration-200 ${isError ? 'text-red-500' : 'text-primary-500'}`;
    el.classList.remove('opacity-0');
    clearTimeout(el._hideTimer);
    if (!persistent) el._hideTimer = setTimeout(() => el.classList.add('opacity-0'), 3500);
}

function _knowledgeResultMessage(action, payload) {
    if (currentLang !== 'zh') {
        return action === 'create_category' ? 'Category created' :
            action === 'create_document' ? 'Document created' :
            action === 'rename_category' ? 'Category renamed' :
            action === 'delete_category' ? 'Category deleted' :
            action === 'import_documents' ? `${payload?.imported || 0} imported · ${payload?.skipped || 0} skipped · ${payload?.failed || 0} failed` :
            action === 'move_documents' ? `${payload?.moved || 0} document moved` :
            `${payload?.deleted || 0} document deleted`;
    }
    return action === 'create_category' ? '分类已创建' :
        action === 'create_document' ? '文档已创建' :
        action === 'rename_category' ? '分类已重命名' :
        action === 'delete_category' ? '分类已删除' :
        action === 'import_documents' ? `导入 ${payload?.imported || 0} 个，跳过 ${payload?.skipped || 0} 个，失败 ${payload?.failed || 0} 个` :
        action === 'move_documents' ? `已移动 ${payload?.moved || 0} 个文档` :
        `已删除 ${payload?.deleted || 0} 个文档`;
}

function _knowledgeCategoryPaths(groups, parent = '') {
    const paths = [];
    for (const group of groups || []) {
        const path = parent ? `${parent}/${group.dir}` : group.dir;
        paths.push(path, ..._knowledgeCategoryPaths(group.children || [], path));
    }
    return paths;
}

function openKnowledgeDialog(options) {
    const overlay = document.getElementById('knowledge-dialog-overlay');
    const card = document.getElementById('knowledge-dialog-card');
    const input = document.getElementById('knowledge-dialog-input');
    const select = document.getElementById('knowledge-dialog-select');
    const textarea = document.getElementById('knowledge-dialog-textarea');
    const documentForm = document.getElementById('knowledge-document-form');
    const documentFilename = document.getElementById('knowledge-document-filename');
    const documentContent = document.getElementById('knowledge-document-content');
    const templateBtn = document.getElementById('knowledge-document-template');
    const documentPathPreview = document.getElementById('knowledge-document-path-preview');
    const submit = document.getElementById('knowledge-dialog-submit');
    const cancel = document.getElementById('knowledge-dialog-cancel');
    document.getElementById('knowledge-dialog-title').textContent = options.title;
    document.getElementById('knowledge-dialog-subtitle').textContent = options.subtitle || '';
    document.getElementById('knowledge-dialog-label').textContent = options.label;
    document.getElementById('knowledge-dialog-hint').textContent = options.hint || '';
    document.getElementById('knowledge-dialog-error').classList.add('hidden');
    document.getElementById('knowledge-dialog-icon').className = `fas ${options.icon || 'fa-folder'} text-emerald-500`;
    card.classList.toggle('knowledge-document-dialog', options.type === 'document');
    input.classList.toggle('hidden', options.type === 'select' || options.type === 'textarea' || options.type === 'document');
    select.classList.toggle('hidden', options.type !== 'select');
    textarea.classList.toggle('hidden', options.type !== 'textarea');
    documentForm.classList.toggle('hidden', options.type !== 'document');
    input.value = options.value || '';
    textarea.value = options.value || '';
    documentFilename.value = options.filename || '';
    documentContent.value = options.content || '';
    document.getElementById('knowledge-document-category-label').textContent = currentLang === 'zh' ? '目标分类' : 'Destination category';
    documentPathPreview.textContent = options.category
        ? `knowledge/${options.category}/`
        : 'knowledge/';
    documentFilename.oninput = null;
    document.getElementById('knowledge-document-filename-label').textContent = currentLang === 'zh' ? '文件名' : 'Filename';
    document.getElementById('knowledge-document-content-label').textContent = currentLang === 'zh' ? 'Markdown 内容' : 'Markdown content';
    templateBtn.textContent = currentLang === 'zh' ? '插入模板' : 'Insert template';
    templateBtn.onclick = () => {
        if (documentContent.value.trim()) return;
        const title = (documentFilename.value || 'untitled').replace(/\.md$/i, '');
        documentContent.value = currentLang === 'zh'
            ? `# ${title}\n\n## 摘要\n\n\n## 关键点\n\n- \n\n## 参考\n\n`
            : `# ${title}\n\n## Summary\n\n\n## Key points\n\n- \n\n## References\n\n`;
        documentContent.focus();
    };
    if (options.type === 'select') {
        // 使用共享的自定义下拉组件而不是本机
        // <select> 使箭头/菜单与控制台的其余部分相匹配。
        const ddOptions = (options.choices || []).map(value => ({ value, label: value }));
        initDropdown(select, ddOptions, (options.choices || [])[0] || '', null);
    }
    submit.textContent = currentLang === 'zh' ? '确定' : 'Confirm';
    cancel.textContent = currentLang === 'zh' ? '取消' : 'Cancel';
    submit.disabled = options.type === 'select' && !(options.choices || []).length;

    const close = () => overlay.classList.add('hidden');
    const submitAction = async () => {
        const rawValue = options.type === 'select' ? getDropdownValue(select) :
            (options.type === 'textarea' ? textarea.value :
            (options.type === 'document' ? {
                filename: documentFilename.value.trim(),
                content: documentContent.value,
            } : input.value));
        const value = options.type === 'textarea' || options.type === 'document' ? rawValue : rawValue.trim();
        const error = options.validate ? options.validate(value) : (!value ? (currentLang === 'zh' ? '此项不能为空' : 'This field is required') : '');
        if (error) {
            const errorEl = document.getElementById('knowledge-dialog-error');
            errorEl.textContent = error;
            errorEl.classList.remove('hidden');
            return;
        }
        submit.disabled = true;
        const ok = await options.onSubmit(value);
        submit.disabled = false;
        if (ok !== null) close();
    };
    submit.onclick = submitAction;
    cancel.onclick = close;
    overlay.onclick = event => { if (event.target === overlay) close(); };
    input.onkeydown = event => { if (event.key === 'Enter') submitAction(); };
    overlay.classList.remove('hidden');
    setTimeout(() => (options.type === 'select' ? select : (options.type === 'textarea' ? textarea : (options.type === 'document' ? documentFilename : input))).focus(), 0);
}

function closeKnowledgeNewMenu() {
    const list = document.getElementById('knowledge-new-menu-list');
    if (list) list.classList.add('hidden');
    document.removeEventListener('click', _knowledgeNewMenuOutside, true);
}

function _knowledgeNewMenuOutside(event) {
    const menu = document.getElementById('knowledge-new-menu');
    if (menu && !menu.contains(event.target)) closeKnowledgeNewMenu();
}

function toggleKnowledgeNewMenu(event) {
    if (event) event.stopPropagation();
    const list = document.getElementById('knowledge-new-menu-list');
    if (!list) return;
    const willOpen = list.classList.contains('hidden');
    list.classList.toggle('hidden');
    if (willOpen) {
        document.addEventListener('click', _knowledgeNewMenuOutside, true);
    } else {
        document.removeEventListener('click', _knowledgeNewMenuOutside, true);
    }
}

function createKnowledgeCategory() {
    openKnowledgeDialog({
        title: currentLang === 'zh' ? '新建分类' : 'New category',
        subtitle: currentLang === 'zh' ? '分类会创建为 knowledge/ 下的目录' : 'Creates a directory under knowledge/',
        label: currentLang === 'zh' ? '分类路径' : 'Category path',
        hint: currentLang === 'zh' ? '支持嵌套路径，例如 research/ai' : 'Nested paths are supported, e.g. research/ai',
        icon: 'fa-folder-plus',
        onSubmit: path => dispatchKnowledgeAction('create_category', {path}),
    });
}

function createKnowledgeDocument() {
    const categories = _knowledgeCategoryPaths(_knowledgeTreeData);
    if (!categories.length) {
        _setKnowledgeStatus(currentLang === 'zh' ? '请先创建分类' : 'Create a category first', true);
        return;
    }
    openKnowledgeDialog({
        title: currentLang === 'zh' ? '新建文档' : 'New document',
        subtitle: currentLang === 'zh' ? '先选择分类，然后输入文件名' : 'Choose a category, then enter a filename',
        label: currentLang === 'zh' ? '目标分类' : 'Destination category',
        type: 'select',
        choices: categories,
        icon: 'fa-file-circle-plus',
        onSubmit: category => {
            openKnowledgeDocumentEditor(category);
            return null;
        },
    });
}

function openKnowledgeDocumentEditor(category) {
    openKnowledgeDialog({
        title: currentLang === 'zh' ? '新建文档' : 'New document',
        subtitle: currentLang === 'zh' ? `保存到 ${category}` : `Save to ${category}`,
        label: '',
        hint: currentLang === 'zh' ? '文件名可省略 .md 后缀；保存后会自动同步索引。' : 'The .md suffix is optional. Index sync runs after saving.',
        type: 'document',
        category,
        filename: '',
        content: '',
        icon: 'fa-file-circle-plus',
        validate: value => {
            if (!value.filename) return currentLang === 'zh' ? '文件名不能为空' : 'Filename is required';
            if (/\.[^.]+$/i.test(value.filename) && !/\.md$/i.test(value.filename)) {
                return currentLang === 'zh' ? '新建文档仅支持 .md 文件名' : 'New documents must be .md files';
            }
            if (!value.content.trim()) return currentLang === 'zh' ? '内容不能为空' : 'Content is required';
            if (new Blob([value.content]).size > KNOWLEDGE_IMPORT_MAX_FILE_SIZE) {
                return currentLang === 'zh' ? '内容不能超过 10MB' : 'Content cannot exceed 10MB';
            }
            return '';
        },
        onSubmit: value => {
            const safeName = value.filename.endsWith('.md') ? value.filename : `${value.filename}.md`;
            return dispatchKnowledgeAction('create_document', {
                path: `${category}/${safeName}`,
                content: value.content,
                overwrite: false,
            }, payload => payload?.path || `${category}/${safeName}`);
        },
    });
}

function selectKnowledgeImportFiles() {
    const input = document.getElementById('knowledge-import-input');
    input.value = '';
    input.onchange = () => {
        if (input.files && input.files.length) openKnowledgeImportDialog(Array.from(input.files));
    };
    input.click();
}

function openKnowledgeImportDialog(files) {
    const validationError = validateKnowledgeImportFiles(files);
    if (validationError) {
        _setKnowledgeStatus(validationError, true);
        return;
    }
    const choices = _knowledgeCategoryPaths(_knowledgeTreeData);
    openKnowledgeDialog({
        title: currentLang === 'zh' ? '导入文档' : 'Import documents',
        subtitle: currentLang === 'zh' ? `已选择 ${files.length} 个文件` : `${files.length} file(s) selected`,
        label: currentLang === 'zh' ? '目标分类' : 'Destination category',
        hint: choices.length ? (currentLang === 'zh' ? '支持 Markdown 和 TXT，TXT 会转成 Markdown 文档' : 'Markdown and TXT are supported. TXT is converted to Markdown.') :
            (currentLang === 'zh' ? '请先创建一个分类' : 'Create a category first'),
        type: 'select',
        choices,
        icon: 'fa-file-arrow-up',
        onSubmit: target => importKnowledgeDocuments(files, target),
    });
}

async function importKnowledgeDocuments(files, targetCategory) {
    const validationError = validateKnowledgeImportFiles(files);
    if (validationError) {
        _setKnowledgeStatus(validationError, true);
        return null;
    }
    const supported = files.filter(file => /\.(md|txt)$/i.test(file.name || ''));
    if (!supported.length) {
        _setKnowledgeStatus(currentLang === 'zh' ? '请选择 .md 或 .txt 文件' : 'Choose .md or .txt files', true);
        return null;
    }
    const formData = new FormData();
    formData.append('target_category', targetCategory);
    formData.append('conflict_strategy', 'rename');
    supported.forEach(file => formData.append('files', file, file.name));
    _setKnowledgeStatus(currentLang === 'zh' ? '正在导入...' : 'Importing...', false, true);
    try {
        const response = await fetch(_kbUrl('/api/knowledge/import'), { method: 'POST', body: formData });
        const result = await response.json();
        if (result.status !== 'success') {
            _setKnowledgeStatus(result.message || (currentLang === 'zh' ? '导入失败' : 'Import failed'), true);
            loadKnowledgeView();
            return null;
        }
        _setKnowledgeStatus(_knowledgeResultMessage('import_documents', result.payload), false);
        // 自动打开第一个成功导入的文档。
        const firstImported = (result.payload?.results || []).find(item => item.status === 'imported');
        loadKnowledgeView(firstImported ? firstImported.path : undefined);
        return result.payload;
    } catch (error) {
        _setKnowledgeStatus(currentLang === 'zh' ? '导入请求失败' : 'Import request failed', true);
        return null;
    }
}

function validateKnowledgeImportFiles(files) {
    if (!files || !files.length) return currentLang === 'zh' ? '请选择文件' : 'Choose files';
    if (files.length > KNOWLEDGE_IMPORT_MAX_FILES) {
        return currentLang === 'zh' ? `一次最多导入 ${KNOWLEDGE_IMPORT_MAX_FILES} 个文件` : `Import at most ${KNOWLEDGE_IMPORT_MAX_FILES} files at a time`;
    }
    let total = 0;
    for (const file of files) {
        total += file.size || 0;
        if ((file.size || 0) > KNOWLEDGE_IMPORT_MAX_FILE_SIZE) {
            return currentLang === 'zh' ? `${file.name} 超过 10MB` : `${file.name} exceeds 10MB`;
        }
    }
    if (total > KNOWLEDGE_IMPORT_MAX_TOTAL_SIZE) {
        return currentLang === 'zh' ? '单次导入总大小不能超过 200MB' : 'Total import size cannot exceed 200MB';
    }
    return '';
}

let _knowledgeImportDropReady = false;
function initKnowledgeImportDropZone() {
    if (_knowledgeImportDropReady) return;
    const panel = document.getElementById('knowledge-panel-docs');
    if (!panel) return;
    _knowledgeImportDropReady = true;
    ['dragenter', 'dragover'].forEach(name => {
        panel.addEventListener(name, event => {
            if (!event.dataTransfer || !event.dataTransfer.types.includes('Files')) return;
            event.preventDefault();
            panel.classList.add('knowledge-import-drag-over');
        });
    });
    ['dragleave', 'drop'].forEach(name => {
        panel.addEventListener(name, event => {
            if (event.type === 'drop') {
                event.preventDefault();
                const files = Array.from(event.dataTransfer?.files || []);
                if (files.length) openKnowledgeImportDialog(files);
            }
            panel.classList.remove('knowledge-import-drag-over');
        });
    });
}

function renameKnowledgeCategory(path) {
    openKnowledgeDialog({
        title: currentLang === 'zh' ? '重命名分类' : 'Rename category',
        subtitle: path,
        label: currentLang === 'zh' ? '新的分类路径' : 'New category path',
        value: path,
        icon: 'fa-pen',
        validate: value => value === path ? (currentLang === 'zh' ? '请输入不同的分类路径' : 'Enter a different category path') : '',
        onSubmit: newPath => dispatchKnowledgeAction('rename_category', {path, new_path: newPath}),
    });
}

function deleteKnowledgeCategory(path) {
    showConfirmDialog({
        title: '删除分类',
        message: `确认删除“${path}”及其中全部文档？`,
        okText: t('confirm_yes'),
        cancelText: t('confirm_cancel'),
        onConfirm: () => dispatchKnowledgeAction('delete_category', {path, confirm: true}),
    });
}

function deleteKnowledgeDocument(path) {
    showConfirmDialog({
        title: '删除文档',
        message: `确认删除“${path}”？`,
        okText: t('confirm_yes'),
        cancelText: t('confirm_cancel'),
        onConfirm: () => dispatchKnowledgeAction('delete_documents', {paths: [path]}),
    });
}

function moveKnowledgeDocument(path) {
    const currentCategory = path.includes('/') ? path.split('/').slice(0, -1).join('/') : '';
    const choices = _knowledgeCategoryPaths(_knowledgeTreeData).filter(value => value !== currentCategory);
    openKnowledgeDialog({
        title: currentLang === 'zh' ? '移动文档' : 'Move document',
        subtitle: path,
        label: currentLang === 'zh' ? '目标分类' : 'Destination category',
        hint: choices.length ? '' : (currentLang === 'zh' ? '请先创建其他分类' : 'Create another category first'),
        type: 'select',
        choices,
        icon: 'fa-arrow-right-arrow-left',
        onSubmit: target => dispatchKnowledgeAction('move_documents', {paths: [path], target_category: target}),
    });
}

function _hasFilterMatch(groups, lowerFilter) {
    for (const g of groups) {
        for (const f of (g.files || [])) {
            if (f.title.toLowerCase().includes(lowerFilter) || f.name.toLowerCase().includes(lowerFilter)) return true;
        }
        if (_hasFilterMatch(g.children || [], lowerFilter)) return true;
    }
    return false;
}

function _countFiles(group) {
    let count = (group.files || []).length;
    for (const child of (group.children || [])) {
        count += _countFiles(child);
    }
    return count;
}

function filterKnowledgeTree(query) {
    renderKnowledgeTree(_knowledgeTreeData, _knowledgeRootFiles, query);
}

function resolveKnowledgePath(currentFilePath, relativeHref) {
    // 当前文件路径：例如“概念/mcp-protocol.md”
    // 相对参考：例如“../entities/openai.md”
    const parts = currentFilePath.split('/');
    parts.pop(); // 删除文件名，保留目录
    const segments = [...parts, ...relativeHref.split('/')];
    const resolved = [];
    for (const seg of segments) {
        if (seg === '..') resolved.pop();
        else if (seg !== '.' && seg !== '') resolved.push(seg);
    }
    return resolved.join('/');
}

function bindKnowledgeLinks(container, currentFilePath) {
    container.querySelectorAll('a').forEach(a => {
        const href = a.getAttribute('href');
        if (!href || !href.endsWith('.md')) return;
        // 跳过绝对 URL
        if (/^https?:\/\//.test(href)) return;

        a.addEventListener('click', (e) => {
            e.preventDefault();
            const resolved = resolveKnowledgePath(currentFilePath, href);
            const linkTitle = a.textContent.trim() || resolved.replace(/\.md$/, '').split('/').pop();
            openKnowledgeFile(resolved, linkTitle);
        });
        a.style.cursor = 'pointer';
        a.classList.add('text-primary-500', 'hover:underline');
    });
}

// 将与知识文档目录相关的 <img> src 重写为
// /api/file URL，镜像 linkKnowledgeLinks 的链接。在渲染上运行
// DOM，因此代码块内引用的 Markdown 语法永远不会被触及。的
// renderMarkdown 附加的 lightbox onclick 在点击时读取 this.src，
// 因此，仅重写 src 即可使 Zoom 正常工作。
function bindKnowledgeImages(container, baseDir) {
    if (!baseDir) return;
    container.querySelectorAll('img').forEach(img => {
        const src = img.getAttribute('src');
        // 远程/数据/站点绝对 src 自行解析。
        if (!src || /^(?:[a-z][\w+.-]*:|\/)/i.test(src)) return;
        const combined = `${baseDir}/${src.split('?')[0]}`;
        const segments = [];
        for (const seg of combined.split('/')) {
            if (seg === '..') segments.pop();
            else if (seg !== '.' && seg !== '') segments.push(seg);
        }
        // baseDir 是绝对 posix 路径，因此恢复前导斜杠
        // split() 已删除 — /api/file 拒绝非绝对路径。
        const resolved = (combined.startsWith('/') ? '/' : '') + segments.join('/');
        img.src = '/api/file?path=' + encodeURIComponent(resolved);
    });
}

function openKnowledgeFile(path, title) {
    _knowledgeCurrentFile = path;
    // 通过数据路径更新树中的活动状态
    document.querySelectorAll('.knowledge-tree-file').forEach(el => {
        el.classList.toggle('active', el.dataset.path === path);
    });

    // 立即隐藏占位符
    document.getElementById('knowledge-content-placeholder').classList.add('hidden');

    fetch(_kbUrl(`/api/knowledge/read?path=${encodeURIComponent(path)}`)).then(r => r.json()).then(data => {
        if (data.status !== 'success') return;
        const viewer = document.getElementById('knowledge-content-viewer');
        document.getElementById('knowledge-viewer-title').textContent = title;
        document.getElementById('knowledge-viewer-path').textContent = path;
        const bodyEl = document.getElementById('knowledge-viewer-body');
        bodyEl.innerHTML = renderMarkdown(data.content || '');
        viewer.classList.remove('hidden');
        applyHighlighting(viewer);
        bindKnowledgeLinks(bodyEl, path);
        bindKnowledgeImages(bodyEl, data.dir);

        // 移动设备：隐藏侧边栏，显示内容
        if (window.innerWidth < 768) {
            document.getElementById('knowledge-sidebar').classList.add('hidden');
        }
    }).catch(() => {});
}

function knowledgeMobileBack() {
    document.getElementById('knowledge-sidebar').classList.remove('hidden');
    document.getElementById('knowledge-content-viewer').classList.add('hidden');
}

function switchKnowledgeTab(tab) {
    document.querySelectorAll('.knowledge-tab').forEach(el => el.classList.remove('active'));
    document.getElementById('knowledge-tab-' + tab).classList.add('active');

    const docsPanel = document.getElementById('knowledge-panel-docs');
    const graphPanel = document.getElementById('knowledge-panel-graph');

    if (tab === 'docs') {
        docsPanel.classList.remove('hidden');
        graphPanel.classList.add('hidden');
    } else {
        docsPanel.classList.add('hidden');
        graphPanel.classList.remove('hidden');
        if (!_knowledgeGraphLoaded) {
            loadKnowledgeGraph();
        }
    }
}

let _d3LoadPromise = null;

function ensureD3Loaded() {
    if (window.d3) return Promise.resolve(window.d3);
    if (_d3LoadPromise) return _d3LoadPromise;
    _d3LoadPromise = new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = 'assets/vendor/d3/d3.min.js';
        script.async = true;
        script.onload = () => resolve(window.d3);
        script.onerror = () => reject(new Error('Failed to load d3'));
        document.head.appendChild(script);
    });
    return _d3LoadPromise;
}

function loadKnowledgeGraph() {
    _knowledgeGraphLoaded = true;
    const container = document.getElementById('knowledge-graph-container');
    container.innerHTML = '<div class="flex items-center justify-center h-full text-slate-400 text-sm"><i class="fas fa-spinner fa-spin mr-2"></i>Loading graph...</div>';

    Promise.all([
        ensureD3Loaded(),
        fetch(_kbUrl('/api/knowledge/graph')).then(r => r.json()),
    ]).then(([, data]) => {
        const nodes = data.nodes || [];
        const links = data.links || [];
        if (nodes.length === 0) {
            container.innerHTML = `<div class="flex flex-col items-center justify-center h-full text-slate-400"><i class="fas fa-diagram-project text-3xl mb-3 opacity-40"></i><p class="text-sm">${t('knowledge_empty_hint')}</p></div>`;
            return;
        }
        container.innerHTML = '';
        renderKnowledgeGraph(container, nodes, links);
    }).catch(() => {
        container.innerHTML = '<div class="flex items-center justify-center h-full text-slate-400 text-sm">Failed to load graph</div>';
    });
}

function renderKnowledgeGraph(container, nodes, links) {
    const width = container.clientWidth;
    const height = container.clientHeight || 600;

    // 按节点数对类别进行排序，以便主导集群获得最多
    // 显着的调色板条目。关系按名称断开，以保持颜色稳定。
    const catCount = {};
    nodes.forEach(n => { catCount[n.category] = (catCount[n.category] || 0) + 1; });
    const categories = Object.keys(catCount).sort(
        (a, b) => catCount[b] - catCount[a] || a.localeCompare(b)
    );
    const colorScale = d3.scaleOrdinal(d3.schemeTableau10).domain(categories);

    // 用于调整大小的连接数
    const connCount = {};
    nodes.forEach(n => connCount[n.id] = 0);
    links.forEach(l => {
        connCount[l.source] = (connCount[l.source] || 0) + 1;
        connCount[l.target] = (connCount[l.target] || 0) + 1;
    });

    const svg = d3.select(container)
        .append('svg')
        .attr('width', width)
        .attr('height', height);

    const g = svg.append('g');

    // 具有自适应标签可见性的缩放
    let currentZoomScale = 1;
    // 图形适合视口后进行设置。标签隐藏在它下面，所以
    // 缩小超过默认视图仍然会显得整洁。
    let fittedScale = 1;
    const zoom = d3.zoom()
        .scaleExtent([0.2, 5])
        .on('zoom', (event) => {
            g.attr('transform', event.transform);
            currentZoomScale = event.transform.k;
            updateLabelVisibility();
        });
    svg.call(zoom);

    function updateLabelVisibility() {
        if (!label) return;
        // 将任何尺寸的图表拟合到面板中都远低于比例 1，
        // 因此固定阈值将隐藏默认视图中的每个标签。
        // 相反，与拟合比例进行比较，并将文本保留为
        // 屏幕上的恒定大小 - 在缩放的 <g> 内，这意味着划分
        // 按规模。
        if (currentZoomScale < fittedScale * 0.9) {
            label.attr('opacity', 0);
            return;
        }
        label.attr('opacity', 1)
            .attr('font-size', 10 / currentZoomScale)
            .attr('dx', d => getNodeRadius(d) + 4 / currentZoomScale)
            .attr('dy', 3 / currentZoomScale);
    }

    const simulation = d3.forceSimulation(nodes)
        .force('link', d3.forceLink(links).id(d => d.id).distance(90))
        .force('charge', d3.forceManyBody().strength(-180))
        .force('center', d3.forceCenter(width / 2, height / 2))
        .force('x', d3.forceX(width / 2).strength(0.06))
        .force('y', d3.forceY(height / 2).strength(0.06))
        .force('collision', d3.forceCollide().radius(d => getNodeRadius(d) + 30));

    function getNodeRadius(d) {
        return Math.max(5, Math.min(16, 5 + (connCount[d.id] || 0) * 2));
    }

    const link = g.append('g')
        .selectAll('line')
        .data(links)
        .join('line')
        .attr('stroke', '#94a3b8')
        .attr('stroke-opacity', 0.3)
        .attr('stroke-width', 1);

    const node = g.append('g')
        .selectAll('circle')
        .data(nodes)
        .join('circle')
        .attr('r', d => getNodeRadius(d))
        .attr('fill', d => colorScale(d.category))
        .attr('stroke', '#fff')
        .attr('stroke-width', 1.5)
        .style('cursor', 'pointer')
        .call(d3.drag()
            .on('start', (event, d) => { if (!event.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
            .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y; })
            .on('end', (event, d) => { if (!event.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; })
        );

    const label = g.append('g')
        .selectAll('text')
        .data(nodes)
        .join('text')
        .text(d => d.label.length > 15 ? d.label.slice(0, 14) + '…' : d.label)
        .attr('font-size', 9)
        .attr('dx', d => getNodeRadius(d) + 4)
        .attr('dy', 3)
        .attr('fill', '#64748b')
        .style('pointer-events', 'none');

    // 工具提示
    const tooltip = document.createElement('div');
    tooltip.className = 'knowledge-graph-tooltip';
    container.style.position = 'relative';
    container.appendChild(tooltip);

    node.on('mouseover', (event, d) => {
        tooltip.textContent = d.label + ' (' + d.category + ')';
        tooltip.style.opacity = '1';
        tooltip.style.left = (event.offsetX + 12) + 'px';
        tooltip.style.top = (event.offsetY - 8) + 'px';
        // 突出显示连接
        link.attr('stroke-opacity', l => (l.source.id === d.id || l.target.id === d.id) ? 0.8 : 0.1);
        node.attr('opacity', n => n.id === d.id || links.some(l => (l.source.id === d.id && l.target.id === n.id) || (l.target.id === d.id && l.source.id === n.id)) ? 1 : 0.2);
        label.attr('opacity', n => n.id === d.id || links.some(l => (l.source.id === d.id && l.target.id === n.id) || (l.target.id === d.id && l.source.id === n.id)) ? 1 : 0.1);
    }).on('mousemove', (event) => {
        tooltip.style.left = (event.offsetX + 12) + 'px';
        tooltip.style.top = (event.offsetY - 8) + 'px';
    }).on('mouseout', () => {
        tooltip.style.opacity = '0';
        link.attr('stroke-opacity', 0.3);
        node.attr('opacity', 1);
        label.attr('opacity', 1);
    }).on('click', (event, d) => {
        // 切换到文档选项卡并打开文件
        switchKnowledgeTab('docs');
        openKnowledgeFile(d.id, d.label);
    });

    simulation.on('tick', () => {
        link.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
            .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
        node.attr('cx', d => d.x).attr('cy', d => d.y);
        label.attr('x', d => d.x).attr('y', d => d.y);
    });

    // 模拟稳定后自动适应视图
    simulation.on('end', () => {
        const pad = 16;
        let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
        nodes.forEach(n => {
            if (n.x < x0) x0 = n.x;
            if (n.y < y0) y0 = n.y;
            if (n.x > x1) x1 = n.x;
            if (n.y > y1) y1 = n.y;
        });
        const bw = x1 - x0 + pad * 2;
        const bh = y1 - y0 + pad * 2;
        if (bw > 0 && bh > 0) {
            const scale = Math.min(width / bw, height / bh, 4);
            fittedScale = scale;
            const tx = width / 2 - (x0 + x1) / 2 * scale;
            const ty = height / 2 - (y0 + y1) / 2 * scale;
            svg.transition().duration(500).call(
                zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(scale)
            );
        }
    });

    // 传奇
    const legendDiv = document.createElement('div');
    legendDiv.className = 'knowledge-graph-legend';
    categories.forEach(cat => {
        const item = document.createElement('span');
        item.className = 'knowledge-graph-legend-item';
        item.innerHTML = `<span class="knowledge-graph-legend-dot" style="background:${colorScale(cat)}"></span>${escapeHtml(cat)}`;
        legendDiv.appendChild(item);
    });
    container.appendChild(legendDiv);
}

// =====================================================================
// 认证
// =====================================================================
function toggleLoginPassword() {
    const input = document.getElementById('login-password');
    const icon = document.querySelector('#login-toggle-pwd i');
    if (input.type === 'password') {
        input.type = 'text';
        icon.classList.replace('fa-eye', 'fa-eye-slash');
    } else {
        input.type = 'password';
        icon.classList.replace('fa-eye-slash', 'fa-eye');
    }
}
window.toggleLoginPassword = toggleLoginPassword;

function showLoginScreen() {
    const overlay = document.getElementById('login-overlay');
    if (!overlay) return;
    overlay.classList.remove('hidden');
    document.getElementById('app').classList.add('hidden');

    const subtitle = document.getElementById('login-subtitle');
    const loginBtn = document.getElementById('login-btn');
    if (currentLang === 'en') {
        subtitle.textContent = 'Enter password to access the console';
        loginBtn.textContent = 'Login';
    } else if (currentLang === 'zh-Hant') {
        subtitle.textContent = '請輸入密碼以存取控制台';
        loginBtn.textContent = '登入';
    } else {
        subtitle.textContent = '请输入密码以访问控制台';
        loginBtn.textContent = '登录';
    }

    const form = document.getElementById('login-form');
    const pwdInput = document.getElementById('login-password');
    pwdInput.focus();

    form.onsubmit = function(e) {
        e.preventDefault();
        const pwd = pwdInput.value;
        if (!pwd) return;
        const btn = document.getElementById('login-btn');
        const errEl = document.getElementById('login-error');
        btn.disabled = true;
        errEl.classList.add('hidden');

        fetch('/auth/login', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({password: pwd})
        }).then(r => r.json()).then(data => {
            if (data.status === 'success') {
                overlay.classList.add('hidden');
                document.getElementById('app').classList.remove('hidden');
                const logoutBtn = document.getElementById('logout-btn-header');
                if (logoutBtn) logoutBtn.classList.remove('hidden');
                initApp();
            } else {
                if (currentLang === 'zh-Hant') {
                    errEl.textContent = '密碼錯誤';
                } else if (currentLang === 'zh') {
                    errEl.textContent = '密码错误';
                } else {
                    errEl.textContent = 'Wrong password';
                }
                errEl.classList.remove('hidden');
                pwdInput.value = '';
                pwdInput.focus();
            }
            btn.disabled = false;
        }).catch(() => {
            if (currentLang === 'zh-Hant') {
                errEl.textContent = '網路錯誤，請重試';
            } else if (currentLang === 'zh') {
                errEl.textContent = '网络错误，请重试';
            } else {
                errEl.textContent = 'Network error, please retry';
            }
            errEl.classList.remove('hidden');
            btn.disabled = false;
        });
        return false;
    };
}

function handleLogout() {
    fetch('/auth/logout', {
        method: 'POST'
    }).then(r => r.json()).then(data => {
        if (data.status === 'success') {
            window.location.reload();
        }
    }).catch(() => {
        window.location.reload();
    });
}
window.handleLogout = handleLogout;

// 全局拦截 401 响应以在会话到期时显示登录屏幕
const _originalFetch = window.fetch;
window.fetch = function(...args) {
    return _originalFetch.apply(this, args).then(response => {
        if (response.status === 401) {
            const url = typeof args[0] === 'string' ? args[0] : (args[0]?.url || '');
            if (!url.startsWith('/auth/')) {
                showLoginScreen();
            }
        }
        return response;
    });
};

function initApp() {
    applyI18n();
    _applyInputTooltips();
    _restoreSessionPanel();
    refreshWorkspaceSelector();
    refreshSessionSettings();

    fetch('/api/knowledge/list').then(r => r.json()).then(data => {
        if (data.status === 'success') {
            _knowledgeTreeData = data.tree || [];
            _knowledgeRootFiles = data.root_files || [];
        }
    }).catch(() => {});

    fetch('/api/version').then(r => r.json()).then(data => {
        APP_VERSION = `v${data.version}`;
        document.getElementById('sidebar-version').textContent = `CowAgent ${APP_VERSION}`;
    }).catch(() => {
        document.getElementById('sidebar-version').textContent = 'CowAgent';
    });
    chatInput.focus();
}

// =====================================================================
// 初始化
// =====================================================================
applyTheme();
applyI18n();

fetch('/auth/check').then(r => r.json()).then(data => {
    if (data.auth_required && !data.authenticated) {
        showLoginScreen();
    } else {
        if (data.auth_required) {
            const logoutBtn = document.getElementById('logout-btn-header');
            if (logoutBtn) logoutBtn.classList.remove('hidden');
        }
        initApp();
    }
}).catch(() => {
    initApp();
});

requestAnimationFrame(() => {
    document.body.classList.add('transition-colors', 'duration-200');
});

// =====================================================================
// 任务编辑模式
// =====================================================================
let currentEditingTask = null;

function loadTaskChannelOptions(selectedChannelType) {
    const select = document.getElementById('task-edit-channel-type');
    select.innerHTML = '';
    fetch('/api/channels').then(r => r.json()).then(data => {
        if (data.status !== 'success') return;
        const allChannels = data.channels || [];
        // 只包含当前活跃的频道，严格遵循频道管理页面逻辑
        let channels = allChannels.filter(c => c.active).map(c => {
            const label = (typeof c.label === 'object') ? (c.label[currentLang] || c.label.en || c.name) : (c.label || c.name);
            return { name: c.name, label: label };
        });
        const channelNames = channels.map(c => c.name);
        // 始终包含 Web 控制台通道
        if (!channelNames.includes('web')) {
            channels.unshift({ name: 'web', label: currentLang === 'zh' ? 'Web' : 'Web' });
        }
        // 如果当前选择的通道不在活动列表中（例如禁用），则将其附加以保留选择
        if (selectedChannelType && !channelNames.includes(selectedChannelType) && selectedChannelType !== 'web') {
            const ch = allChannels.find(c => c.name === selectedChannelType);
            const label = ch
                ? ((typeof ch.label === 'object') ? (ch.label[currentLang] || ch.label.en || ch.name) : (ch.label || ch.name))
                : selectedChannelType;
            channels.push({ name: selectedChannelType, label: label });
        }
        channels.forEach(c => {
            const opt = document.createElement('option');
            opt.value = c.name;
            opt.textContent = c.label;
            select.appendChild(opt);
        });
        // 设置选定值
        if (selectedChannelType) {
            select.value = selectedChannelType;
        }
    }).catch(() => {
        // 后备：至少保留当前选择和网络
        select.innerHTML = '';
        const webOpt = document.createElement('option');
        webOpt.value = 'web';
        webOpt.textContent = 'Web';
        select.appendChild(webOpt);
        
        if (selectedChannelType && selectedChannelType !== 'web') {
            const opt = document.createElement('option');
            opt.value = selectedChannelType;
            opt.textContent = selectedChannelType;
            select.appendChild(opt);
        }
        if (selectedChannelType) {
            select.value = selectedChannelType;
        }
        
        // 显示错误信息
        console.error('Failed to load channel options');
    });
}

// 任务编辑模式标题中显示（只读）的所属代理。隐藏在一个
// 单代理安装，其中每项任务无论如何都属于一个代理。
function renderTaskOwnerChip(task) {
    const el = document.getElementById('task-edit-owner');
    if (!el) return;
    const agent = task.agent_id ? findAgent(task.agent_id) : null;
    if (!multiAgentMode() || !agent) {
        el.classList.add('hidden');
        el.innerHTML = '';
        return;
    }
    el.innerHTML = `${agentAvatarHTML(agent, 20)}
        <span class="text-xs font-medium text-slate-600 dark:text-slate-300 truncate max-w-[120px]">${escapeHtml(agent.name || agent.id)}</span>`;
    el.classList.remove('hidden');
    el.classList.add('flex');
}

function openTaskEditModal(task) {
    currentEditingTask = task;
    const overlay = document.getElementById('task-edit-modal-overlay');
    const titleEl = document.querySelector('#task-edit-modal-overlay h3');
    const subtitle = document.getElementById('task-edit-modal-subtitle');
    const deleteBtn = document.getElementById('task-edit-modal-delete');
    const nameInput = document.getElementById('task-edit-name');
    const enabledInput = document.getElementById('task-edit-enabled');
    const scheduleTypeSelect = document.getElementById('task-edit-schedule-type');
    const cronInput = document.getElementById('task-edit-cron-expression');
    const intervalInput = document.getElementById('task-edit-interval-seconds');
    const onceInput = document.getElementById('task-edit-once-time');
    const actionTypeSelect = document.getElementById('task-edit-action-type');
    const receiverInput = document.getElementById('task-edit-receiver');
    const contentInput = document.getElementById('task-edit-content');

    // 设置标题和副标题
    titleEl.textContent = t('task_edit_title');
    subtitle.textContent = task.id;
    deleteBtn.classList.remove('hidden');

    // 显示哪个代理拥有此任务（只读）。只有拥有更多才有意义
    // 超过一名代理人；单独安装只会重复显而易见的事情。
    renderTaskOwnerChip(task);

    // 填充数据
    nameInput.value = task.name || '';
    enabledInput.checked = task.enabled !== false;

    const schedule = task.schedule || {};
    scheduleTypeSelect.value = schedule.type || 'cron';

    // 首先清除所有计划类型输入值以避免数据过时
    cronInput.value = '';
    intervalInput.value = '';
    onceInput.value = '';

    if (schedule.type === 'cron') {
        cronInput.value = schedule.expression || '';
    } else if (schedule.type === 'interval') {
        intervalInput.value = schedule.seconds || '';
    } else if (schedule.type === 'once') {
        if (schedule.run_at) {
            // 手动解析 ISO 时间字符串以避免 new Date() 的跨浏览器时区问题
            // run_at 格式：“YYYY-MM-DDTHH:mm:ss”或“YYYY-MM-DDTHH:mm:ss.ffffff”
            const parts = schedule.run_at.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})/);
            if (parts) {
                const timeInput = document.getElementById('task-edit-once-time');
                timeInput.value = `${parts[1]}-${parts[2]}-${parts[3]}T${parts[4]}:${parts[5]}:${parts[6]}`;
            }
        }
    }

    const action = task.action || {};
    actionTypeSelect.value = action.type || 'send_message';
    receiverInput.value = action.receiver || '';
    contentInput.value = action.content || action.task_description || '';

    // 加载通道选项并设置所选值
    loadTaskChannelOptions(action.channel_type || 'web');

    // 禁用通道类型选择器 — 编辑时通道为只读。
    // 创建任务后切换通道是有问题的，因为：
    //   1. 微信（weixin/ilink）机器人需要绑定的有效context_token
    //      到该频道上的特定用户会话。换频道到微信
    //      会使现有令牌失效——微信上的新接收者可能不会
    //      有一个活动的 context_token，导致计划的推送默默失败。
    //   2、其他渠道（钉钉、飞书等）也带有渠道特定字段
    //      （例如 dingtalk_sender_staff_id）不能简单地重新填充
    //      无需用户干预的不同通道类型。
    //   3. 接收者身份本身是通道绑定的——微信用户ID意味着
    //      飞书频道上没有任何内容，因此更改频道会导致任务孤立。
    // 由于这些原因，一旦任务存在，通道类型就会被有意冻结。
    // 需要在不同渠道上执行任务的用户应通过以下方式创建新任务
    // 聊天界面（通过询问机器人）而不是编辑现有界面。
    document.getElementById('task-edit-channel-type').disabled = true;

    // 更新用户界面
    updateTaskScheduleFields();
    updateTaskActionLabel();

    overlay.classList.remove('hidden');
}

function closeTaskEditModal() {
    document.getElementById('task-edit-modal-overlay').classList.add('hidden');
    currentEditingTask = null;
}

function updateTaskScheduleFields() {
    const scheduleType = document.getElementById('task-edit-schedule-type').value;
    const cronWrap = document.getElementById('task-edit-cron-wrap');
    const intervalWrap = document.getElementById('task-edit-interval-wrap');
    const onceWrap = document.getElementById('task-edit-once-wrap');
    const cronHint = document.getElementById('task-edit-cron-hint');
    const intervalHint = document.getElementById('task-edit-interval-hint');
    
    cronWrap.classList.toggle('hidden', scheduleType !== 'cron');
    intervalWrap.classList.toggle('hidden', scheduleType !== 'interval');
    onceWrap.classList.toggle('hidden', scheduleType !== 'once');
    
    if (cronHint) cronHint.classList.toggle('hidden', scheduleType !== 'cron');
    if (intervalHint) intervalHint.classList.toggle('hidden', scheduleType !== 'interval');
}

function updateTaskActionLabel() {
    const actionType = document.getElementById('task-edit-action-type').value;
    const label = document.getElementById('task-edit-content-label');
    const content = document.getElementById('task-edit-content');
    
    if (actionType === 'send_message') {
        label.textContent = t('task_message_content');
        content.placeholder = t('task_message_content');
    } else {
        label.textContent = t('task_task_description');
        content.placeholder = t('task_task_description');
    }
}

function saveTaskEdit() {
    const nameInput = document.getElementById('task-edit-name');
    const enabledInput = document.getElementById('task-edit-enabled');
    const scheduleTypeSelect = document.getElementById('task-edit-schedule-type');
    const cronInput = document.getElementById('task-edit-cron-expression');
    const intervalInput = document.getElementById('task-edit-interval-seconds');
    const onceInput = document.getElementById('task-edit-once-time');
    const actionTypeSelect = document.getElementById('task-edit-action-type');
    const channelTypeSelect = document.getElementById('task-edit-channel-type');
    const receiverInput = document.getElementById('task-edit-receiver');
    const contentInput = document.getElementById('task-edit-content');
    const statusEl = document.getElementById('task-edit-modal-status');
    const saveBtn = document.getElementById('task-edit-modal-save');
    
    const name = nameInput.value.trim();
    if (!name) {
        statusEl.textContent = currentLang === 'zh' ? '请输入任务名称' : 'Please enter task name';
        statusEl.style.opacity = '1';
        setTimeout(() => { statusEl.style.opacity = '0'; }, 3000);
        return;
    }
    
    const scheduleType = scheduleTypeSelect.value;
    const schedule = { type: scheduleType };
    
    if (scheduleType === 'cron') {
        const expr = cronInput.value.trim();
        if (!expr) {
            statusEl.textContent = currentLang === 'zh' ? '请输入 Cron 表达式' : 'Please enter cron expression';
            statusEl.style.opacity = '1';
            setTimeout(() => { statusEl.style.opacity = '0'; }, 3000);
            return;
        }
        // 基本 cron 表达式格式验证：5 或 6 个字段
        const fields = expr.split(/\s+/);
        if (fields.length < 5 || fields.length > 6) {
            statusEl.textContent = currentLang === 'zh' ? 'Cron 表达式格式错误，应为 5 或 6 个字段（分 时 日 月 周）' : 'Invalid cron expression, expected 5 or 6 fields (min hour day month weekday)';
            statusEl.style.opacity = '1';
            setTimeout(() => { statusEl.style.opacity = '0'; }, 3000);
            return;
        }
        schedule.expression = expr;
        // 注：详细的cron表达式有效性由后端croniter库验证；前端仅进行基本格式验证
    } else if (scheduleType === 'interval') {
        const seconds = parseInt(intervalInput.value);
        if (!seconds || seconds < 60) {
            statusEl.textContent = currentLang === 'zh' ? '间隔秒数最小为 60 秒' : 'Interval must be at least 60 seconds';
            statusEl.style.opacity = '1';
            setTimeout(() => { statusEl.style.opacity = '0'; }, 3000);
            return;
        }
        schedule.seconds = seconds;
    } else if (scheduleType === 'once') {
        const time = onceInput.value;
        if (!time) {
            statusEl.textContent = currentLang === 'zh' ? '请选择执行时间' : 'Please select execution time';
            statusEl.style.opacity = '1';
            setTimeout(() => { statusEl.style.opacity = '0'; }, 3000);
            return;
        }
        // 验证执行时间格式
        const selectedTime = new Date(time);
        if (isNaN(selectedTime.getTime())) {
            statusEl.textContent = currentLang === 'zh' ? '执行时间格式错误' : 'Invalid execution time format';
            statusEl.style.opacity = '1';
            setTimeout(() => { statusEl.style.opacity = '0'; }, 3000);
            return;
        }
        // 验证一次性任务的时间是将来的时间
        if (selectedTime <= new Date()) {
            statusEl.textContent = currentLang === 'zh' ? '执行时间必须在当前时间之后' : 'Execution time must be in the future';
            statusEl.style.opacity = '1';
            setTimeout(() => { statusEl.style.opacity = '0'; }, 3000);
            return;
        }
        // step="1" 的 datetime-local 值已采用 YYYY-MM-DDTHH:mm:ss 格式
        // 后端 _parse_naive_local 将没有时区后缀的字符串视为本地时间
        schedule.run_at = time;
    }
    
    const actionType = actionTypeSelect.value;
    const channelType = channelTypeSelect.value;
    const content = contentInput.value.trim();

    if (!content) {
        statusEl.textContent = currentLang === 'zh' ? '请输入内容' : 'Please enter content';
        statusEl.style.opacity = '1';
        setTimeout(() => { statusEl.style.opacity = '0'; }, 3000);
        return;
    }
    
    // 仅使用必要的字段构建操作以避免数据过时
    const action = {
        type: actionType,
        channel_type: channelType,
        receiver: '',
        receiver_name: '',
        is_group: false,
        notify_session_id: ''
    };
    
    if (actionType === 'send_message') {
        action.content = content;
    } else {
        action.task_description = content;
    }
    
    // 保留原始接收者信息（频道是只读的，因此永远不会改变）
    if (currentEditingTask && currentEditingTask.action) {
        action.receiver = currentEditingTask.action.receiver || '';
        action.receiver_name = currentEditingTask.action.receiver_name || '';
        action.is_group = currentEditingTask.action.is_group || false;
        action.notify_session_id = currentEditingTask.action.notify_session_id || '';
        
        // 保留频道特定字段（例如钉钉sender_staff_id）
        if (channelType === 'dingtalk' && currentEditingTask.action.dingtalk_sender_staff_id) {
            action.dingtalk_sender_staff_id = currentEditingTask.action.dingtalk_sender_staff_id;
        }
    }
    
    saveBtn.disabled = true;
    
    const payload = {
        task_id: currentEditingTask.id,
        agent_id: currentEditingTask.agent_id || '',
        name: name,
        enabled: enabledInput.checked,
        schedule: schedule,
        action: action
    };
    
    fetch('/api/scheduler/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    }).then(r => r.json()).then(res => {
        saveBtn.disabled = false;
        if (res.status === 'success') {
            closeTaskEditModal();
            tasksLoaded = false;
            loadTasksView();
        } else {
            statusEl.textContent = res.message || (currentLang === 'zh' ? '保存失败' : 'Save failed');
            statusEl.style.opacity = '1';
            setTimeout(() => { statusEl.style.opacity = '0'; }, 3000);
        }
    }).catch(() => {
        saveBtn.disabled = false;
        statusEl.textContent = currentLang === 'zh' ? '网络错误' : 'Network error';
        statusEl.style.opacity = '1';
        setTimeout(() => { statusEl.style.opacity = '0'; }, 3000);
    });
}

function deleteTask() {
    if (!currentEditingTask) return;
    
    const taskName = currentEditingTask.name || currentEditingTask.id || '未知任务';
    const taskId = currentEditingTask.id;  // 尽早捕获以避免封闭竞争状况
    const taskAgentId = currentEditingTask.agent_id || '';  // 将删除路由到所有者的商店
    showConfirmDialog({
        title: t('task_delete_confirm_title'),
        message: (currentLang === 'zh' ? `确定要删除任务「${taskName}」吗？` : `Are you sure to delete task "${taskName}"?`),
        onConfirm: () => {
            fetch('/api/scheduler/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ task_id: taskId, agent_id: taskAgentId })
            }).then(r => r.json()).then(res => {
                if (res.status === 'success') {
                    closeTaskEditModal();
                    tasksLoaded = false;
                    loadTasksView();
                } else {
                    const statusEl = document.getElementById('task-edit-modal-status');
                    if (statusEl) {
                        statusEl.textContent = res.message || 'Delete failed';
                        statusEl.classList.remove('hidden', 'text-green-500');
                        statusEl.classList.add('text-red-500');
                        setTimeout(() => { statusEl.style.opacity = '0'; }, 3000);
                    }
                }
            }).catch(() => {
                const statusEl = document.getElementById('task-edit-modal-status');
                if (statusEl) {
                    statusEl.textContent = 'Network error';
                    statusEl.classList.remove('hidden', 'text-green-500');
                    statusEl.classList.add('text-red-500');
                    setTimeout(() => { statusEl.style.opacity = '0'; }, 3000);
                }
            });
        }
    });
}


document.getElementById('task-edit-schedule-type').addEventListener('change', updateTaskScheduleFields);
document.getElementById('task-edit-action-type').addEventListener('change', updateTaskActionLabel);
document.getElementById('task-edit-modal-cancel').addEventListener('click', closeTaskEditModal);
document.getElementById('task-edit-modal-save').addEventListener('click', saveTaskEdit);
document.getElementById('task-edit-modal-delete').addEventListener('click', deleteTask);
document.getElementById('task-edit-modal-overlay').addEventListener('click', function(e) {
    if (e.target === this) closeTaskEditModal();
});
