/* =====================================================================
 * 工作区面板：文件预览+文件管理器+@文件引用。
 * 在 console.js 之后加载并重用其全局变量（t、escapeHtml、
 * renderMarkdown、applyHighlighting、pendingAttachments、...）。
 * ===================================================================== */

const WS_WIDTH_KEY = 'cow_workspace_width';
const WS_DEFAULT_WIDTH = 420;
const WS_MIN_WIDTH = 280;

// 面板状态
let wsPanelOpen = false;
let wsActiveTab = 'preview';
let wsCurrentFile = null;
// 预览编辑器状态。 `wsEditBaseline` 是加载时文本区域自身的值，
// 因此，与它进行比较可以看出是否确实发生了任何变化；
// `wsEditBaseMtime` 是服务器检查以检测代理的时间戳
// 在编辑过程中重写了文件。
let wsEditing = false;
let wsEditBaseline = '';
let wsEditBaseMtime = null;
let wsSaving = false;
// 一旦用户手动关闭面板即可设置：从那时起我们就停止了
// 页面会话其余部分的自动打开工件。
let wsAutoOpenSuppressed = false;
// 目前正在播放的回合所产生的工件。
let wsTurnArtifacts = [];

// 文件管理器状态
let wsCurrentDir = '';
let wsCurrentRoot = '';   // 工作区/项目根的绝对路径
let wsSearchMode = false;
let wsSearchTimer = null;

// =====================================================================
// 元数据助手
// =====================================================================
const WS_KIND_ICONS = {
    directory: 'fa-folder',
    html: 'fa-file-code',
    markdown: 'fa-file-lines',
    image: 'fa-file-image',
    video: 'fa-file-video',
    audio: 'fa-file-audio',
    pdf: 'fa-file-pdf',
    csv: 'fa-file-csv',
    code: 'fa-file-code',
    office: 'fa-file-word',
    text: 'fa-file-lines',
    file: 'fa-file',
};

const WS_KIND_BY_EXT = {
    html: ['html', 'htm'],
    markdown: ['md', 'markdown'],
    image: ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'svg', 'ico'],
    video: ['mp4', 'webm', 'mov', 'avi', 'mkv', 'm4v'],
    audio: ['mp3', 'wav', 'ogg', 'm4a', 'flac', 'aac'],
    pdf: ['pdf'],
    csv: ['csv', 'tsv'],
    code: ['py', 'js', 'ts', 'tsx', 'jsx', 'java', 'c', 'cpp', 'h', 'go', 'rs',
           'rb', 'php', 'sh', 'sql', 'css', 'scss', 'json', 'yaml', 'yml',
           'xml', 'toml', 'ini'],
    text: ['txt', 'log'],
    office: ['doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx'],
};

const WS_EXT_KIND = (() => {
    const map = {};
    for (const [kind, exts] of Object.entries(WS_KIND_BY_EXT)) {
        exts.forEach(e => { map[e] = kind; });
    }
    return map;
})();

const WS_PREVIEWABLE = new Set(
    ['html', 'markdown', 'image', 'video', 'audio', 'pdf', 'csv', 'code', 'text']
);

// 面板提供编辑器的类型。镜像 EDITABLE_KINDS 于
// 代理/协议/artifact.py；服务器拒绝保存任何其他内容。
const WS_EDITABLE = new Set(['html', 'markdown', 'csv', 'code', 'text']);

function wsKindOf(name) {
    const ext = (name || '').split('.').pop().toLowerCase();
    return WS_EXT_KIND[ext] || 'file';
}

function wsIconClass(kind) {
    return `fas ${WS_KIND_ICONS[kind] || WS_KIND_ICONS.file} ws-icon-${kind}`;
}

function wsFormatSize(bytes) {
    if (!bytes && bytes !== 0) return '';
    const units = ['B', 'KB', 'MB', 'GB'];
    let n = bytes;
    for (const u of units) {
        if (n < 1024) return `${u === 'B' ? Math.round(n) : n.toFixed(1)}${u}`;
        n /= 1024;
    }
    return `${n.toFixed(1)}TB`;
}

async function wsApi(path) {
    // 作用域工作区读取到当前会话所以文件面板/@picker/
    // 预览遵循会话打开的项目目录。 `sessionId` 和
    // `activeAgentId` 是来自同一页面上的 console.js 的全局变量。
    try {
        if (path.startsWith('/api/workspace/')) {
            const sid = (typeof sessionId !== 'undefined') ? sessionId : '';
            if (sid) path += (path.includes('?') ? '&' : '?') + 'session=' + encodeURIComponent(sid);
            // 如果没有打开的项目，根将回退到代理自己的项目
            // 工作区，因此文件面板必须说明哪个代理处于活动状态 - 否则
            // 它始终显示默认代理的目录。
            const aid = (typeof activeAgentId !== 'undefined') ? activeAgentId : '';
            if (aid) path += (path.includes('?') ? '&' : '?') + 'agent=' + encodeURIComponent(aid);
        }
    } catch (e) { /* 全局变量尚不可用 */ }
    const res = await fetch(path);
    const data = await res.json();
    if (data.status !== 'success') throw new Error(data.message || 'Request failed');
    return data;
}

// =====================================================================
// 面板打开/关闭/调整大小
// =====================================================================
function openWorkspacePanel(tab) {
    const panel = document.getElementById('workspace-panel');
    if (!panel) return;
    panel.classList.remove('hidden');
    wsPanelOpen = true;
    const width = parseInt(localStorage.getItem(WS_WIDTH_KEY), 10);
    if (width >= WS_MIN_WIDTH) panel.style.width = `${width}px`;
    if (tab) switchWorkspaceTab(tab);
}

/**
 * @param {boolean} byUser - true when triggered by the close button, which
 *   also disables auto-open for the rest of the session.
 */
function closeWorkspacePanel(byUser) {
    const panel = document.getElementById('workspace-panel');
    if (!panel) return;
    panel.classList.add('hidden');
    wsPanelOpen = false;
    if (byUser) wsAutoOpenSuppressed = true;
}

function toggleWorkspacePanel() {
    if (wsPanelOpen) {
        closeWorkspacePanel(true);
        return;
    }
    wsAutoOpenSuppressed = false;
    openWorkspacePanel(wsCurrentFile ? 'preview' : 'files');
}

function switchWorkspaceTab(tab) {
    wsActiveTab = tab;
    document.querySelectorAll('.workspace-tab').forEach(el => {
        el.classList.toggle('active', el.dataset.wsTab === tab);
    });
    document.querySelectorAll('.workspace-body').forEach(el => {
        el.classList.toggle('active', el.id === `ws-body-${tab}`);
    });
    wsUpdateHeaderActions();
    if (tab === 'files' && !document.getElementById('ws-file-list').childElementCount) {
        loadWorkspaceDir(wsCurrentDir);
    }
}

function wsUpdateHeaderActions() {
    const onFile = wsActiveTab === 'preview' && !!wsCurrentFile;
    // 编辑时，查看器操作将作用于保存的文件而不是
    // 关于文本区域中的内容，这被视为错误。相反，将它们隐藏起来。
    ['ws-btn-external', 'ws-btn-download', 'ws-btn-copy'].forEach(id => {
        document.getElementById(id)?.classList.toggle('hidden', !onFile || wsEditing);
    });
    document.getElementById('ws-btn-edit')
        ?.classList.toggle('hidden', !onFile || wsEditing || !wsIsEditable(wsCurrentFile));
    ['ws-btn-save', 'ws-btn-edit-cancel'].forEach(id => {
        document.getElementById(id)?.classList.toggle('hidden', !onFile || !wsEditing);
    });
}

function initWorkspaceResizer() {
    const resizer = document.getElementById('ws-resizer');
    const panel = document.getElementById('workspace-panel');
    if (!resizer || !panel) return;

    let startX = 0;
    let startWidth = 0;

    function onMove(e) {
        const delta = startX - e.clientX;
        const next = Math.max(WS_MIN_WIDTH, Math.min(window.innerWidth * 0.7, startWidth + delta));
        panel.style.width = `${next}px`;
    }

    function onUp() {
        resizer.classList.remove('dragging');
        document.body.style.userSelect = '';
        // 预览 iframe 在拖动鼠标时会吞下 mousemove。
        document.getElementById('ws-preview-content')?.style.removeProperty('pointer-events');
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        localStorage.setItem(WS_WIDTH_KEY, String(parseInt(panel.style.width, 10) || WS_DEFAULT_WIDTH));
    }

    resizer.addEventListener('mousedown', (e) => {
        e.preventDefault();
        startX = e.clientX;
        startWidth = panel.offsetWidth;
        resizer.classList.add('dragging');
        document.body.style.userSelect = 'none';
        document.getElementById('ws-preview-content')?.style.setProperty('pointer-events', 'none');
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
    });
}

// =====================================================================
// 预览
// =====================================================================
function wsSetPreviewEmpty(message, icon) {
    const body = document.getElementById('ws-preview-content');
    const title = document.getElementById('ws-preview-title');
    if (!body) return;
    title?.classList.add('hidden');
    body.innerHTML = `<div class="workspace-empty">
        <i class="fas ${icon || 'fa-eye'}"></i>
        <span>${escapeHtml(message)}</span>
    </div>`;
}

/**
 * Open a file in the preview tab.
 * @param {object|string} target - file metadata, or a path to resolve first.
 */
async function openInPreview(target) {
    // 打开另一个文件会替换编辑器，因此请先解决未保存的编辑。
    if (!wsGuardUnsaved(() => openInPreview(target))) return;

    let meta = target;
    if (typeof target === 'string') {
        try {
            meta = (await wsApi(`/api/workspace/resolve?path=${encodeURIComponent(target)}`)).file;
        } catch (e) {
            openWorkspacePanel('preview');
            wsSetPreviewEmpty(t('ws_preview_failed') + ': ' + e.message, 'fa-triangle-exclamation');
            return;
        }
    }
    if (!meta) return;
    // 目录没有什么可渲染的；而是浏览它们。
    if (meta.is_dir) {
        openWorkspacePanel('files');
        switchWorkspaceTab('files');
        loadWorkspaceDir(meta.path || '');
        return;
    }

    wsCurrentFile = meta;
    wsEditing = false;
    openWorkspacePanel('preview');
    switchWorkspaceTab('preview');
    wsRenderPreviewTitle();
    wsUpdateHeaderActions();
    await wsRenderPreview(meta);
}

/** Show the current file's path, marked with a dot while edits are unsaved. */
function wsRenderPreviewTitle() {
    const title = document.getElementById('ws-preview-title');
    if (!title) return;
    if (!wsCurrentFile) {
        title.classList.add('hidden');
        return;
    }
    const name = wsCurrentFile.path || wsCurrentFile.file_name || wsCurrentFile.name || '';
    title.textContent = wsEditorDirty() ? `${name} •` : name;
    title.classList.remove('hidden');
}

async function wsRenderPreview(meta) {
    const body = document.getElementById('ws-preview-content');
    if (!body) return;
    const kind = meta.kind || wsKindOf(meta.file_name || meta.name || meta.path);
    const name = meta.file_name || meta.name || (meta.path || '').split('/').pop();
    const previewUrl = meta.preview_url;
    const rawUrl = meta.raw_url || previewUrl;

    if (kind === 'html') {
        body.innerHTML = '';
        const frame = document.createElement('iframe');
        // 不允许同源：生成的页面在不透明的源中运行，并且
        // 无法访问控制台的存储或身份验证 cookie。
        frame.setAttribute('sandbox', 'allow-scripts allow-popups allow-forms allow-modals');
        frame.src = previewUrl;
        body.appendChild(frame);
        return;
    }

    if (kind === 'image') {
        body.innerHTML = `<div class="ws-pad"><img class="ws-media" src="${escapeHtml(rawUrl)}" alt="${escapeHtml(name)}"></div>`;
        return;
    }

    if (kind === 'video') {
        body.innerHTML = `<div class="ws-pad"><video class="ws-media" controls preload="metadata" src="${escapeHtml(rawUrl)}"></video></div>`;
        return;
    }

    if (kind === 'audio') {
        body.innerHTML = `<div class="ws-pad"><audio class="ws-media" controls src="${escapeHtml(rawUrl)}"></audio></div>`;
        return;
    }

    if (kind === 'pdf') {
        body.innerHTML = '';
        const frame = document.createElement('iframe');
        frame.src = previewUrl;
        body.appendChild(frame);
        return;
    }

    if (kind === 'markdown' || kind === 'code' || kind === 'text' || kind === 'csv') {
        body.innerHTML = `<div class="workspace-empty"><i class="fas fa-spinner fa-spin"></i></div>`;
        try {
            const res = await fetch(previewUrl);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const text = await res.text();
            if (kind === 'markdown') {
                body.innerHTML = `<div class="ws-pad msg-content">${renderMarkdown(text)}</div>`;
            } else if (kind === 'csv') {
                body.innerHTML = `<pre>${escapeHtml(text)}</pre>`;
            } else {
                const lang = (name.split('.').pop() || '').toLowerCase();
                body.innerHTML = `<pre><code class="language-${escapeHtml(lang)}">${escapeHtml(text)}</code></pre>`;
            }
            applyHighlighting(body);
        } catch (e) {
            wsSetPreviewEmpty(t('ws_preview_failed') + ': ' + e.message, 'fa-triangle-exclamation');
        }
        return;
    }

    // 不支持的类型：提供下载而不是损坏的查看器。
    body.innerHTML = `<div class="workspace-empty">
        <i class="${wsIconClass(kind)}"></i>
        <span>${escapeHtml(name)}</span>
        <span>${escapeHtml(t('ws_no_inline_preview'))}</span>
        <a href="${escapeHtml(rawUrl)}" download="${escapeHtml(name)}"
           class="file-card-btn" style="width:auto;padding:4px 12px;border:1px solid currentColor;">
            <i class="fas fa-download"></i>&nbsp;${escapeHtml(t('ws_download'))}
        </a>
    </div>`;
}

function openPreviewExternally() {
    if (!wsCurrentFile) return;
    window.open(wsCurrentFile.preview_url || wsCurrentFile.raw_url, '_blank', 'noopener');
}

function downloadPreviewFile() {
    if (!wsCurrentFile) return;
    const a = document.createElement('a');
    a.href = wsCurrentFile.raw_url || wsCurrentFile.preview_url;
    a.download = wsCurrentFile.file_name || wsCurrentFile.name || '';
    document.body.appendChild(a);
    a.click();
    a.remove();
}

function copyPreviewPath() {
    if (!wsCurrentFile) return;
    const path = wsCurrentFile.abs_path || wsCurrentFile.path || '';
    copyToClipboard(path).then(() => {
        const btn = document.getElementById('ws-btn-copy');
        const icon = btn && btn.querySelector('i');
        if (icon) {
            icon.className = 'fas fa-check';
            setTimeout(() => { icon.className = 'fas fa-link'; }, 1500);
        }
    });
}

// =====================================================================
// 预览编辑器
// =====================================================================
function wsIsEditable(meta) {
    if (!meta || meta.is_dir) return false;
    return WS_EDITABLE.has(meta.kind || wsKindOf(meta.file_name || meta.name || meta.path));
}

/**
 * Path to send to the read/write API. The absolute path is unambiguous, which
 * matters for files the panel reaches outside the session's workspace root
 * (memory / knowledge assets while a project is open).
 */
function wsEditTargetPath(meta) {
    return meta.abs_path || meta.path || meta.rel_path || '';
}

function wsEditorTextarea() {
    return document.getElementById('ws-editor');
}

function wsEditorDirty() {
    const ta = wsEditorTextarea();
    return wsEditing && !!ta && ta.value !== wsEditBaseline;
}

/** Forget the editor's state, leaving what is on screen to the caller. */
function wsDiscardEditState() {
    wsEditing = false;
    wsEditBaseline = '';
    wsEditBaseMtime = null;
}

/**
 * Gate an action that would throw away the editor's contents.
 *
 * @param {function} next - run once the user agrees to discard the edits, and
 *   responsible for whatever replaces the editor. It runs with edit mode
 *   already off, so it must not be a function that bails out when not editing.
 * @returns {boolean} true when there is nothing to lose and the caller may
 *   proceed immediately; false once the confirmation has been put on screen.
 */
function wsGuardUnsaved(next) {
    if (!wsEditorDirty()) return true;
    showConfirmDialog({
        title: t('ws_edit_discard_title'),
        message: t('ws_edit_discard_msg'),
        okText: t('ws_edit_discard_ok'),
        onConfirm: () => {
            wsDiscardEditState();
            next();
        },
    });
    return false;
}

/**
 * Why the server refused to make a file editable. Truncation is reported first:
 * a partial read can also split a multi-byte character and so come back lossy,
 * but the size is the reason the user needs to hear.
 */
function wsUneditableReason(data) {
    if (data.truncated) return 'ws_edit_too_large';
    if (data.lossy) return 'ws_edit_encoding';
    return 'ws_edit_unsupported';
}

/** Load the file's current text into an editable text area. */
async function startPreviewEdit() {
    if (wsEditing || !wsIsEditable(wsCurrentFile)) return;
    const target = wsCurrentFile;
    const body = document.getElementById('ws-preview-content');
    if (!body) return;
    body.innerHTML = `<div class="workspace-empty"><i class="fas fa-spinner fa-spin"></i></div>`;

    let data;
    try {
        data = await wsApi(`/api/workspace/read?path=${encodeURIComponent(wsEditTargetPath(target))}`);
    } catch (e) {
        _wsToast(`${t('ws_edit_load_failed')}: ${e.message}`);
        await wsRenderPreview(target);
        return;
    }
    // 当请求进行时，用户可能已经离开。
    if (wsCurrentFile !== target) return;
    if (!data.editable) {
        _wsToast(t(wsUneditableReason(data)));
        await wsRenderPreview(target);
        return;
    }

    wsEditing = true;
    wsEditBaseMtime = data.mtime;
    // 从文本区域读回基线，而不是使用响应
    // 文本：文本区域将其值中的 CRLF 标准化为 LF，因此 CRLF 文件将
    // 比较从加载那一刻起的修改情况。
    wsEditBaseline = wsMountEditor(body, data.content).value;
    wsRenderPreviewTitle();
    wsUpdateHeaderActions();
}

/** @returns {HTMLTextAreaElement} the text area now holding the file. */
function wsMountEditor(body, content) {
    body.innerHTML = '';
    const ta = document.createElement('textarea');
    ta.id = 'ws-editor';
    ta.className = 'ws-editor';
    ta.spellcheck = false;
    ta.value = content;
    body.appendChild(ta);

    ta.addEventListener('input', wsRenderPreviewTitle);
    ta.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
            // 像编辑器一样保存到位。改为“保存”按钮
            // 返回到渲染预览。
            e.preventDefault();
            savePreviewEdit({ keepEditing: true });
        } else if (e.key === 'Escape') {
            e.preventDefault();
            cancelPreviewEdit();
        } else if (e.key === 'Tab') {
            // 否则 Tab 会离开文本区域，这绝不是缩进
            // 一行代码就是要做的事。
            e.preventDefault();
            wsInsertAtCursor(ta, '    ');
        }
    });
    ta.focus();
    return ta;
}

function wsInsertAtCursor(ta, text) {
    const { selectionStart: start, selectionEnd: end } = ta;
    ta.value = ta.value.slice(0, start) + text + ta.value.slice(end);
    ta.selectionStart = ta.selectionEnd = start + text.length;
    wsRenderPreviewTitle();
}

/**
 * Write the text area back to disk.
 *
 * @param {object} [opts]
 * @param {boolean} [opts.keepEditing] - stay in the editor after saving.
 * @param {boolean} [opts.force] - save even though the file changed on disk.
 */
async function savePreviewEdit(opts) {
    const { keepEditing = false, force = false } = opts || {};
    const ta = wsEditorTextarea();
    if (!wsEditing || !wsCurrentFile || !ta) return;
    // Ctrl+S 绕过按钮的禁用状态，并发送第二次保存
    // 在第一个回复带有陈旧的时间之前 - 它将作为
    // 与我们自己写的冲突。
    if (wsSaving) return;
    // 编写一个未修改的文件会毫无意义地影响它的运行时间。
    if (!force && !wsEditorDirty()) {
        if (!keepEditing) await wsExitEdit();
        return;
    }

    const target = wsCurrentFile;
    const content = ta.value;
    const btn = document.getElementById('ws-btn-save');
    wsSaving = true;
    btn?.classList.add('ws-btn-busy');
    try {
        const res = await fetch('/api/workspace/write', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                path: wsEditTargetPath(target),
                content: content,
                session: (typeof sessionId !== 'undefined') ? sessionId : '',
                expected_mtime: force ? null : wsEditBaseMtime,
            }),
        });
        const data = await res.json();
        if (data.code === 'conflict') {
            showConfirmDialog({
                title: t('ws_edit_conflict_title'),
                message: t('ws_edit_conflict_msg'),
                okText: t('ws_edit_overwrite'),
                onConfirm: () => savePreviewEdit({ keepEditing: keepEditing, force: true }),
            });
            return;
        }
        if (data.status !== 'success') throw new Error(data.message || 'save failed');

        wsEditBaseline = content;
        wsEditBaseMtime = data.mtime;
        target.size = data.size;
        target.mtime = data.mtime;
        _wsToast(t('ws_edit_saved'));
        if (keepEditing) {
            wsRenderPreviewTitle();
        } else {
            await wsExitEdit();
        }
    } catch (e) {
        _wsToast(`${t('ws_edit_save_failed')}: ${e.message}`);
    } finally {
        wsSaving = false;
        btn?.classList.remove('ws-btn-busy');
    }
}

function cancelPreviewEdit() {
    if (!wsEditing) return;
    // 通过 wsExitEdit 重试，而不是通过此函数，这样可以避免
    // 守卫在重试之前清除了旗帜。
    if (!wsGuardUnsaved(wsExitEdit)) return;
    wsExitEdit();
}

/** Leave edit mode and show the rendered preview again. */
async function wsExitEdit() {
    wsDiscardEditState();
    wsRenderPreviewTitle();
    wsUpdateHeaderActions();
    if (wsCurrentFile) await wsRenderPreview(wsCurrentFile);
}

// =====================================================================
// 消息中的神器卡
// =====================================================================

/** Build the HTML for a file card. `meta` needs file_name / kind / raw_url. */
function renderFileCard(meta) {
    const name = meta.file_name || meta.name || '';
    const kind = meta.kind || wsKindOf(name);
    const relPath = meta.rel_path || meta.path || '';
    // 当路径除了已显示的文件名之外不添加任何内容时，请跳过该路径。
    const sub = [relPath === name ? '' : relPath, wsFormatSize(meta.size)]
        .filter(Boolean).join(' · ');
    const payload = escapeHtml(JSON.stringify({
        file_name: name,
        rel_path: meta.rel_path || meta.path || '',
        abs_path: meta.abs_path || '',
        kind: kind,
        size: meta.size || 0,
        raw_url: meta.raw_url || '',
        preview_url: meta.preview_url || '',
        previewable: meta.previewable !== false && WS_PREVIEWABLE.has(kind),
    }));
    const canPreview = meta.previewable !== false && WS_PREVIEWABLE.has(kind);
    return `<div class="file-card" data-file='${payload}'>
        <i class="file-card-icon ${wsIconClass(kind)}"></i>
        <div class="file-card-info">
            <div class="file-card-name">${escapeHtml(name)}</div>
            ${sub ? `<div class="file-card-sub">${escapeHtml(sub)}</div>` : ''}
        </div>
        <div class="file-card-actions">
            ${canPreview ? `<div class="file-card-btn" data-action="preview" title="${escapeHtml(t('ws_preview'))}"><i class="fas fa-eye"></i></div>` : ''}
            <div class="file-card-btn" data-action="download" title="${escapeHtml(t('ws_download'))}"><i class="fas fa-download"></i></div>
        </div>
    </div>`;
}

/** Append an artifact card to a live bot bubble and remember it for auto-open. */
function appendArtifactCard(container, item) {
    if (!container) return;
    const existing = container.querySelector(`[data-artifact-path="${CSS.escape(item.abs_path || '')}"]`);
    if (existing) return;
    const wrap = document.createElement('div');
    wrap.className = 'file-card-list';
    wrap.dataset.artifactPath = item.abs_path || '';
    wrap.innerHTML = renderFileCard(item);
    container.appendChild(wrap);
    wsTurnArtifacts.push(item);
}

function resetTurnArtifacts() {
    wsTurnArtifacts = [];
}

/**
 * Auto-open policy: only when the turn produced exactly one previewable
 * artifact, only while the user hasn't dismissed the panel by hand, and never
 * over an open editor - the file cards stay in the message either way.
 */
function maybeAutoOpenArtifact() {
    const items = wsTurnArtifacts.filter(a => a.previewable);
    wsTurnArtifacts = [];
    if (wsAutoOpenSuppressed || wsEditing || items.length !== 1) return;
    openInPreview(items[0]);
}

/**
 * Render the artifact cards of a history message. The list is built by the
 * backend from the persisted write/edit steps, since only it knows the
 * workspace root and which files still exist.
 */
function renderArtifactCards(artifacts) {
    if (!Array.isArray(artifacts) || !artifacts.length) return '';
    return artifacts.map(item =>
        `<div class="file-card-list" data-artifact-path="${escapeHtml(item.abs_path || '')}">
            ${renderFileCard(item)}
        </div>`
    ).join('');
}

async function wsResolveMeta(meta) {
    if (meta.preview_url && meta.raw_url) return meta;
    const path = meta.abs_path || meta.rel_path || meta.path;
    if (!path) return null;
    return (await wsApi(`/api/workspace/resolve?path=${encodeURIComponent(path)}`)).file;
}

function wsTriggerDownload(url, name) {
    const a = document.createElement('a');
    a.href = url;
    a.download = name || '';
    document.body.appendChild(a);
    a.click();
    a.remove();
}

// 代表单击文件卡、内联路径芯片和工作区链接。
// 委托（而不是每个元素的侦听器）是保持其正常运行的原因
// 在流式消息重新呈现其innerHTML之后。
document.addEventListener('click', async (e) => {
    // 更接近的处理程序已经声明了此点击（例如知识查看器
    // 在其自己的文档之间导航）。
    if (e.defaultPrevented) return;

    // 渲染的 Markdown 内的工作空间相关链接。
    const wsLink = e.target.closest('a[data-ws-path]');
    if (wsLink) {
        e.preventDefault();
        openWorkspaceLink(wsLink.dataset.wsPath);
        return;
    }

    const chip = e.target.closest('.file-chip');
    if (chip && chip.dataset.path) {
        e.preventDefault();
        openInPreview(chip.dataset.path);
        return;
    }

    // 用户消息气泡内的工作区参考芯片。
    const ref = e.target.closest('[data-ws-open]');
    if (ref) {
        e.preventDefault();
        openInPreview(ref.dataset.wsOpen);
        return;
    }

    const card = e.target.closest('.file-card');
    if (!card) return;
    e.preventDefault();
    let meta;
    try { meta = JSON.parse(card.dataset.file); } catch (_) { return; }

    const action = e.target.closest('[data-action]')?.dataset.action;
    if (action === 'download') {
        if (meta.raw_url) {
            wsTriggerDownload(meta.raw_url, meta.file_name);
            return;
        }
        try {
            const full = await wsResolveMeta(meta);
            if (full) wsTriggerDownload(full.raw_url, full.name);
        } catch (_) {}
        return;
    }
    openInPreview(meta.preview_url ? meta : (meta.abs_path || meta.rel_path));
});

// =====================================================================
// 内联路径芯片：将文本中提到的本地路径转换为可点击的芯片
// =====================================================================
const WS_PATH_EXTS = Object.values(WS_KIND_BY_EXT).flat().join('|');
// 绝对（/Users/...、C:\...）、相对于家庭（~/cow/...）或相对于工作区
// (websites/report.html) 路径，始终锚定在已知的文件扩展名上，并且
// 包含至少一个分隔符，保留类似“see report.html”的散文
// 从变成芯片。比赛前排除 `:` 和 `/` 就会停止
// http(s) URL 的尾部被拾取。
const WS_PATH_RE = new RegExp(
    '(^|[^\\w/\\\\.~:-])((?:~\\/|\\/|[A-Za-z]:\\\\)?(?:[\\w.\\-\\u4e00-\\u9fa5]+[\\/\\\\])+[\\w.\\-\\u4e00-\\u9fa5]+\\.(?:'
    + WS_PATH_EXTS + '))(?=$|[^\\w.\\-\\u4e00-\\u9fa5]|$)',
    'gi'
);

function _buildFileChip(path) {
    const name = path.split(/[\\/]/).pop();
    const kind = wsKindOf(name);
    return `<span class="file-chip" data-path="${escapeHtml(path)}" title="${escapeHtml(path)}">` +
        `<i class="${wsIconClass(kind)}"></i>${escapeHtml(name)}</span>`;
}

/**
 * Rewrite bare file paths in already-rendered markdown into chips.
 * Only touches text nodes outside <pre>/<code>/<a> so code samples and
 * existing links stay untouched.
 */
function injectFileChips(html) {
    if (!html || !html.includes('.')) return html;

    // 按标签拆分；跟踪我们是否处于一个我们不能重写的区域内。
    let depthSkip = 0;
    return html.split(/(<[^>]+>)/).map((chunk) => {
        if (chunk.startsWith('<')) {
            const tag = chunk.match(/^<\/?\s*([a-zA-Z0-9]+)/);
            const name = tag ? tag[1].toLowerCase() : '';
            if (['pre', 'code', 'a', 'img', 'video', 'audio'].includes(name)) {
                if (chunk.startsWith('</')) depthSkip = Math.max(0, depthSkip - 1);
                else if (!chunk.endsWith('/>')) depthSkip += 1;
            }
            return chunk;
        }
        if (depthSkip > 0 || !chunk.trim()) return chunk;
        return chunk.replace(WS_PATH_RE, (match, lead, path) =>
            path.includes('://') ? match : lead + _buildFileChip(path)
        );
    }).join('');
}

// =====================================================================
// 渲染的 Markdown 内的工作区链接
// =====================================================================
/**
 * Decide whether an href points at a workspace file rather than the web.
 *
 * Agent replies cite their own files with a workspace-relative markdown link
 * (`[title](knowledge/x.md)`). The browser would resolve those against the
 * console URL and open a 404 in a new tab, so they need routing to the
 * preview panel instead.
 *
 * @returns {string|null} the cleaned workspace path, or null if not one.
 */
function wsWorkspaceHref(href) {
    if (!href) return null;
    // 方案（http、mailto、文件、数据）、协议相关主机、
    // 页内锚点或站点绝对路径永远不是工作区文件。
    if (/^[a-zA-Z][\w+.-]*:/.test(href)) return null;
    if (href.startsWith('//') || href.startsWith('#') || href.startsWith('/')) return null;

    let path = href.split('#')[0].split('?')[0].trim();
    // markdown-it 对非 ASCII href 进行百分比编码； API 希望它们是原始的。
    try { path = decodeURI(path); } catch (_) {}
    if (!path) return null;
    // 需要一个已知的扩展名，以便散文链接保持不变。
    return WS_EXT_KIND[(path.split('.').pop() || '').toLowerCase()] ? path : null;
}

/**
 * Open a workspace file referenced by a link in a rendered message.
 * Agent links are occasionally relative to the citing document rather than to
 * the workspace root, so fall back to a filename search before giving up.
 */
async function openWorkspaceLink(path) {
    // 该面板位于聊天视图中，因此从其他地方单击的链接（
    // 知识阅读器（内存文件）否则将在视线之外打开。
    if (typeof navigateTo === 'function' && currentView !== 'chat') navigateTo('chat');

    try {
        const data = await wsApi(`/api/workspace/resolve?path=${encodeURIComponent(path)}`);
        openInPreview(data.file);
        return;
    } catch (_) { /* 进入名称搜索 */ }

    const name = path.split('/').pop();
    try {
        const data = await wsApi(`/api/workspace/search?q=${encodeURIComponent(name)}&limit=10`);
        const hit = (data.results || []).find(r => !r.is_dir && r.name === name);
        if (hit) {
            openInPreview(hit);
            return;
        }
    } catch (_) {}

    openWorkspacePanel('preview');
    switchWorkspaceTab('preview');
    wsSetPreviewEmpty(`${t('ws_link_not_found')}: ${path}`, 'fa-triangle-exclamation');
}

// =====================================================================
// 文件管理器选项卡
// =====================================================================
function refreshWorkspaceTree() {
    const input = document.getElementById('ws-search-input');
    if (input) input.value = '';
    wsSearchMode = false;
    loadWorkspaceDir(wsCurrentDir);
}

/** Switching the active Agent moves the file panel's root to that Agent's own
 *  workspace (when no project is open). Drop back to the root and reload, but
 *  only if the panel is already open — never pop it open on a switch. */
function resetWorkspaceToAgentRoot() {
    wsCurrentDir = '';
    if (wsPanelOpen) refreshWorkspaceTree();
}

async function loadWorkspaceDir(relPath) {
    const list = document.getElementById('ws-file-list');
    if (!list) return;
    list.innerHTML = `<div class="workspace-empty"><i class="fas fa-spinner fa-spin"></i></div>`;
    try {
        const data = await wsApi(`/api/workspace/tree?path=${encodeURIComponent(relPath || '')}`);
        wsCurrentDir = data.path || '';
        wsCurrentRoot = data.root || wsCurrentRoot;
        wsSearchMode = false;
        // 浏览离开搜索模式；从框中删除过时的查询。
        const searchBox = document.getElementById('ws-search-input');
        if (searchBox && searchBox.value) searchBox.value = '';
        renderWorkspaceBreadcrumb(wsCurrentDir);
        renderWorkspaceEntries(data.entries, data.truncated);
    } catch (e) {
        list.innerHTML = `<div class="workspace-empty">
            <i class="fas fa-triangle-exclamation"></i><span>${escapeHtml(e.message)}</span></div>`;
    }
}

function renderWorkspaceBreadcrumb(relPath) {
    const bar = document.getElementById('ws-breadcrumb');
    if (!bar) return;
    const parts = (relPath || '').split('/').filter(Boolean);
    // 在根目录下，显示房子旁边的根目录的绝对路径，以便用户
    // 知道面板锚定到哪个目录。当导航进入内部时，
    // 更深的面包屑已经传达了位置，所以房子仍然只有图标。
    const atRoot = parts.length === 0;
    const rootLabel = atRoot && wsCurrentRoot
        ? ` <span class="crumb-root">${escapeHtml(wsCurrentRoot)}</span>`
        : '';
    const crumbs = [`<span class="crumb" data-ws-dir="" data-tooltip="${escapeHtml(wsCurrentRoot || '')}"><i class="fas fa-house"></i>${rootLabel}</span>`];
    let acc = '';
    parts.forEach((p) => {
        acc = acc ? `${acc}/${p}` : p;
        crumbs.push('<span class="sep">/</span>');
        crumbs.push(`<span class="crumb" data-ws-dir="${escapeHtml(acc)}">${escapeHtml(p)}</span>`);
    });
    bar.innerHTML = crumbs.join('');
}

function renderWorkspaceEntries(entries, truncated) {
    const list = document.getElementById('ws-file-list');
    if (!list) return;
    if (!entries || entries.length === 0) {
        list.innerHTML = `<div class="workspace-empty"><i class="fas fa-folder-open"></i>
            <span>${escapeHtml(t('ws_empty_dir'))}</span></div>`;
        return;
    }
    const rows = entries.map(entry => {
        const meta = entry.is_dir ? '' : wsFormatSize(entry.size);
        return `<div class="ws-file-row" ${wsRowAttrs(entry)}>
            <i class="${wsIconClass(entry.kind)}"></i>
            <span class="ws-file-name">${escapeHtml(entry.name)}</span>
            <span class="ws-file-meta">${escapeHtml(meta)}</span>
        </div>`;
    });
    if (truncated) {
        rows.push(`<div class="workspace-empty" style="height:auto;padding:12px;">
            <span>${escapeHtml(t('ws_truncated'))}</span></div>`);
    }
    list.innerHTML = rows.join('');
}

/**
 * Row attributes for a tree/search entry. Everything is draggable into the
 * composer; `data-ws-dir` additionally makes a click navigate rather than
 * preview, since directories have nothing to render.
 */
function wsRowAttrs(entry) {
    const payload = escapeHtml(JSON.stringify(entry));
    const nav = entry.is_dir ? ` data-ws-dir="${escapeHtml(entry.path)}"` : '';
    return `data-ws-file='${payload}' draggable="true"${nav}`;
}

function renderWorkspaceSearchResults(results) {
    const list = document.getElementById('ws-file-list');
    if (!list) return;
    if (!results.length) {
        list.innerHTML = `<div class="workspace-empty"><i class="fas fa-magnifying-glass"></i>
            <span>${escapeHtml(t('ws_no_results'))}</span></div>`;
        return;
    }
    list.innerHTML = results.map(entry => `
        <div class="ws-file-row" ${wsRowAttrs(entry)}>
            <i class="${wsIconClass(entry.kind)}"></i>
            <span class="ws-file-name">${escapeHtml(entry.name)}</span>
            <span class="ws-file-path">${escapeHtml(entry.path)}</span>
        </div>`).join('');
}

async function runWorkspaceSearch(query) {
    if (!query.trim()) {
        loadWorkspaceDir(wsCurrentDir);
        return;
    }
    try {
        const data = await wsApi(`/api/workspace/search?q=${encodeURIComponent(query)}&limit=60`);
        wsSearchMode = true;
        renderWorkspaceSearchResults(data.results || []);
    } catch (e) {
        const list = document.getElementById('ws-file-list');
        if (list) {
            list.innerHTML = `<div class="workspace-empty">
                <i class="fas fa-triangle-exclamation"></i><span>${escapeHtml(e.message)}</span></div>`;
        }
    }
}

function initWorkspaceFilesTab() {
    const list = document.getElementById('ws-file-list');
    const bar = document.getElementById('ws-breadcrumb');
    const input = document.getElementById('ws-search-input');

    bar?.addEventListener('click', (e) => {
        const crumb = e.target.closest('[data-ws-dir]');
        if (crumb) loadWorkspaceDir(crumb.dataset.wsDir);
    });

    list?.addEventListener('click', (e) => {
        const row = e.target.closest('.ws-file-row');
        if (!row) return;
        if (row.dataset.wsDir !== undefined) {
            loadWorkspaceDir(row.dataset.wsDir);
            return;
        }
        list.querySelectorAll('.ws-file-row.active').forEach(el => el.classList.remove('active'));
        row.classList.add('active');
        try { openInPreview(JSON.parse(row.dataset.wsFile)); } catch (_) {}
    });

    list?.addEventListener('dragstart', (e) => {
        const row = e.target.closest('.ws-file-row[data-ws-file]');
        if (!row) return;
        e.dataTransfer.effectAllowed = 'copy';
        e.dataTransfer.setData('application/x-cow-workspace-file', row.dataset.wsFile);
    });

    input?.addEventListener('input', () => {
        clearTimeout(wsSearchTimer);
        const q = input.value;
        wsSearchTimer = setTimeout(() => runWorkspaceSearch(q), 200);
    });
}

// =====================================================================
// 将工作区文件拖到对话中
// =====================================================================
function addWorkspaceRefAttachment(entry) {
    const relPath = entry.path || entry.rel_path || '';
    if (!relPath) return;
    if (pendingAttachments.some(a => a.file_type === 'workspace_ref' && a.file_path === relPath)) return;
    pendingAttachments.push({
        file_path: relPath,
        file_name: entry.name || entry.file_name || relPath.split('/').pop(),
        // 就地引用；后端不得将其视为上传。
        file_type: 'workspace_ref',
        is_dir: !!entry.is_dir,
    });
    renderAttachmentPreview();
}

function initWorkspaceDropTarget() {
    const target = document.getElementById('chat-main');
    if (!target) return;

    const isWorkspaceDrag = (e) =>
        Array.from(e.dataTransfer?.types || []).includes('application/x-cow-workspace-file');

    target.addEventListener('dragover', (e) => {
        if (!isWorkspaceDrag(e)) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = 'copy';
        target.classList.add('ws-drop-active');
    });

    // relatedTarget是正在进入的节点；在后代之间流动
    // target 仍然会触发 Dragleave，因此只有在指针真正离开时才清除。
    target.addEventListener('dragleave', (e) => {
        if (!target.contains(e.relatedTarget)) target.classList.remove('ws-drop-active');
    });

    // 无 stopPropagation：外部 #view-chat 删除处理程序拥有重置
    // 上传覆盖状态，它会忽略不携带文件的drop。
    target.addEventListener('drop', (e) => {
        if (!isWorkspaceDrag(e)) return;
        e.preventDefault();
        target.classList.remove('ws-drop-active');
        try {
            addWorkspaceRefAttachment(JSON.parse(e.dataTransfer.getData('application/x-cow-workspace-file')));
        } catch (_) {}
    });
}

// =====================================================================
// @聊天输入中的文件引用
// =====================================================================
let mentionActive = false;
let mentionStart = -1;
let mentionItems = [];
let mentionIndex = 0;
let mentionTimer = null;

function hideMentionMenu() {
    mentionActive = false;
    mentionStart = -1;
    mentionItems = [];
    document.getElementById('mention-menu')?.classList.add('hidden');
}

function renderMentionMenu() {
    const menu = document.getElementById('mention-menu');
    if (!menu) return;
    if (!mentionItems.length) {
        menu.innerHTML = `<div class="mention-empty">${escapeHtml(t('ws_no_results'))}</div>`;
        menu.classList.remove('hidden');
        return;
    }
    menu.innerHTML = mentionItems.map((item, i) => {
        if (item.kind === 'agent') {
            const face = typeof agentAvatarHTML === 'function'
                ? agentAvatarHTML(item, 20)
                : `<i class="fas fa-user"></i>`;
            return `<div class="mention-item ${i === mentionIndex ? 'active' : ''}" data-idx="${i}">
                ${face}
                <span class="m-name">${escapeHtml(item.name)}</span>
                <span class="m-path">${escapeHtml(item.id)}</span>
            </div>`;
        }
        return `<div class="mention-item ${i === mentionIndex ? 'active' : ''}" data-idx="${i}">
            <i class="${wsIconClass(item.kind)}"></i>
            <span class="m-name">${escapeHtml(item.name)}</span>
            <span class="m-path">${escapeHtml(item.path)}</span>
        </div>`;
    }).join('');
    menu.classList.remove('hidden');
}

function matchingAgentMentions(query) {
    // @ 称呼队友，仅当对话超过
    // 它的主人。单独聊天将@保留为文件选择器。
    if (typeof sharedConversation !== 'function' || !sharedConversation()) return [];
    const q = String(query || '').toLowerCase();
    // 只提供队友：@将回合交给其他人，因此
    // 所有者（已经回复的人）被从选择器中过滤掉。
    const owner = typeof activeAgentId !== 'undefined' ? activeAgentId : '';
    const roster = (typeof sessionRoster === 'function' ? sessionRoster() : [])
        .filter(agent => agent.id !== owner);
    return roster
        .filter(agent => !q || agent.id.toLowerCase().includes(q) || String(agent.name).toLowerCase().includes(q))
        .slice(0, 6)
        .map(agent => ({ kind: 'agent', id: agent.id, name: agent.name, avatar: agent.avatar || '' }));
}

async function updateMentionQuery(query) {
    const agents = matchingAgentMentions(query);
    try {
        const data = await wsApi(`/api/workspace/search?q=${encodeURIComponent(query)}&limit=12`);
        if (!mentionActive) return;
        mentionItems = agents.concat(data.results || []);
        mentionIndex = 0;
        renderMentionMenu();
    } catch (_) {
        if (!mentionActive) return;
        mentionItems = agents;
        mentionIndex = 0;
        if (agents.length) renderMentionMenu();
        else hideMentionMenu();
    }
}

function acceptMention(idx) {
    const item = mentionItems[idx];
    const input = document.getElementById('chat-input');
    if (!item || !input) return;
    const before = input.value.slice(0, mentionStart);
    const after = input.value.slice(input.selectionStart);
    if (item.kind === 'agent') {
        // 写下名字，而不是 ID：提及的是一位同事
        // 并且应该读起来像一个。服务器解析任一形式。
        const inserted = `@${item.name || item.id} `;
        input.value = before + inserted + after;
        input.selectionStart = input.selectionEnd = before.length + inserted.length;
        if (typeof addTeamMember === 'function') addTeamMember(item.id);
    } else {
        addWorkspaceRefAttachment(item);
        // 删除“@query”片段：文件作为附件而不是文本传输。
        input.value = before + after;
        input.selectionStart = input.selectionEnd = before.length;
    }
    hideMentionMenu();
    input.focus();
    input.dispatchEvent(new Event('input'));
}

function initMention() {
    const input = document.getElementById('chat-input');
    const menu = document.getElementById('mention-menu');
    if (!input || !menu) return;

    input.addEventListener('input', () => {
        const pos = input.selectionStart;
        const before = input.value.slice(0, pos);
        // 在输入开头或空格之后触发“@”。
        const match = before.match(/(?:^|\s)@([^\s@]*)$/);
        if (!match) {
            if (mentionActive) hideMentionMenu();
            return;
        }
        mentionActive = true;
        mentionStart = pos - match[1].length - 1;
        clearTimeout(mentionTimer);
        const q = match[1];
        mentionTimer = setTimeout(() => updateMentionQuery(q), 150);
    });

    // 捕获阶段，因此 Enter/箭头在发送处理程序之前被消耗。
    input.addEventListener('keydown', (e) => {
        if (!mentionActive || !mentionItems.length) return;
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            e.stopImmediatePropagation();
            mentionIndex = (mentionIndex + 1) % mentionItems.length;
            renderMentionMenu();
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            e.stopImmediatePropagation();
            mentionIndex = (mentionIndex - 1 + mentionItems.length) % mentionItems.length;
            renderMentionMenu();
        } else if (e.key === 'Enter' || e.key === 'Tab') {
            e.preventDefault();
            e.stopImmediatePropagation();
            acceptMention(mentionIndex);
        } else if (e.key === 'Escape') {
            e.preventDefault();
            e.stopImmediatePropagation();
            hideMentionMenu();
        }
    }, true);

    menu.addEventListener('mousedown', (e) => {
        const item = e.target.closest('.mention-item');
        if (!item) return;
        e.preventDefault();
        acceptMention(parseInt(item.dataset.idx, 10));
    });

    document.addEventListener('click', (e) => {
        if (mentionActive && !menu.contains(e.target) && e.target !== input) hideMentionMenu();
    });
}

/** Re-render the JS-generated parts of the panel after a language switch. */
function relocalizeWorkspacePanel() {
    if (!wsCurrentFile) wsSetPreviewEmpty(t('ws_preview_empty'));
    if (wsActiveTab === 'files' && !wsSearchMode
        && document.getElementById('ws-file-list')?.childElementCount) {
        loadWorkspaceDir(wsCurrentDir);
    }
}

// 当活动会话更改时重置面板。文件树和预览
// 范围仅限于会话的工作目录（项目或默认目录），因此状态陈旧
// 必须删除上一个会话中的内容，如果打开，则必须根据
// 新会话的根。
function wsOnSessionSwitch() {
    wsCurrentDir = '';
    wsCurrentRoot = '';
    wsSearchMode = false;
    wsCurrentFile = null;
    wsTurnArtifacts = [];
    wsDiscardEditState();
    wsUpdateHeaderActions();
    if (!wsPanelOpen) return;
    if (wsActiveTab === 'files') {
        loadWorkspaceDir('');
    } else {
        wsSetPreviewEmpty(t('ws_preview_empty'));
    }
}

// =====================================================================
// 初始化
// =====================================================================
function initWorkspacePanel() {
    initWorkspaceResizer();
    initWorkspaceFilesTab();
    initWorkspaceDropTarget();
    initMention();
    wsSetPreviewEmpty(t('ws_preview_empty'));

    // 重新加载或关闭选项卡会默默地删除打开的编辑器的更改。
    window.addEventListener('beforeunload', (e) => {
        if (!wsEditorDirty()) return;
        e.preventDefault();
        e.returnValue = '';
    });

    // 该面板仅属于聊天视图；跟随视图切换。
    const toggle = document.getElementById('workspace-toggle-btn');
    const chatView = document.getElementById('view-chat');
    if (toggle && chatView) {
        const sync = () => toggle.classList.toggle('hidden', !chatView.classList.contains('active'));
        sync();
        new MutationObserver(sync).observe(chatView, { attributes: true, attributeFilter: ['class'] });
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initWorkspacePanel);
} else {
    initWorkspacePanel();
}
