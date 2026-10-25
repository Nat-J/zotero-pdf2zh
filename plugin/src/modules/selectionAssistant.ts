import { PDF2zhHelperFactory } from "./pdf2zhHelper";
import { askAboutSelection } from "./selectionAssistantRequest";

const panels = new Map<Document, () => void>();

function openAssistant(doc: Document, selection: string) {
    const web = Zotero.getMainWindow() as unknown as Window & typeof globalThis;
    panels.get(doc)?.();
    const panel = doc.createElement("section");
    panel.className = "pdf2zh-assistant";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", "PDF2zh AI 提问");
    // This markup is static; selections and model responses are assigned as plain text below.
    panel.innerHTML = `
        <style>
            .pdf2zh-assistant {position:fixed;right:16px;top:72px;width:min(520px,calc(100vw - 32px));max-height:calc(100vh - 96px);overflow:auto;z-index:2147483647;box-sizing:border-box;padding:20px;border:1px solid #888;border-radius:10px;box-shadow:0 8px 32px #0004;background:Canvas;color:CanvasText;font:14px system-ui}
            .pdf2zh-assistant header {display:flex;align-items:center;justify-content:space-between}
            .pdf2zh-assistant h2 {font:600 16px system-ui;margin:0}
            .pdf2zh-assistant label {display:block;margin:16px 0 6px;font-weight:600}
            .pdf2zh-assistant textarea {box-sizing:border-box;width:100%;padding:8px;font:14px/1.6 system-ui;border:1px solid #888;border-radius:4px;background:Field;color:FieldText}
            .pdf2zh-assistant button {padding:6px 14px;cursor:pointer;font:14px system-ui}
            .pdf2zh-assistant [role=status] {margin-left:10px}
            .pdf2zh-assistant [role=region] {min-height:100px;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.7;user-select:text}
        </style>
        <header><h2>PDF2zh · AI 提问</h2><button type="button" data-close="true" aria-label="关闭 AI 提问">关闭</button></header>
        <label for="pdf2zh-assistant-selection">选中的文字</label>
        <textarea id="pdf2zh-assistant-selection" readonly="readonly" rows="4"></textarea>
        <label for="pdf2zh-assistant-question">向 DeepSeek 提问</label>
        <textarea id="pdf2zh-assistant-question" rows="3">请解释这段文字的含义及关键概念。</textarea>
        <p><button type="button" data-ask="true">提问</button><span role="status" aria-live="polite"></span></p>
        <label>回答</label><div role="region" aria-label="AI 回答" tabindex="0"></div>
    `;
    doc.body.append(panel);
    const selected = panel.querySelector(
        "#pdf2zh-assistant-selection",
    ) as HTMLTextAreaElement;
    const question = panel.querySelector(
        "#pdf2zh-assistant-question",
    ) as HTMLTextAreaElement;
    const button = panel.querySelector("[data-ask]") as HTMLButtonElement;
    const answer = panel.querySelector("[role=region]")!;
    const status = panel.querySelector("[role=status]")!;
    selected.value = selection;
    question.focus();
    question.select();
    let controller: AbortController | undefined;
    const close = () => {
        controller?.abort();
        panel.remove();
        doc.defaultView?.removeEventListener("unload", close);
        panels.delete(doc);
    };
    panels.set(doc, close);
    panel.querySelector("[data-close]")!.addEventListener("click", close);
    panel.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            event.stopPropagation();
            close();
        }
    });
    doc.defaultView?.addEventListener("unload", close, false);
    button.addEventListener("click", async () => {
        controller = new web.AbortController();
        const timeout = web.setTimeout(() => controller?.abort(), 90_000);
        button.disabled = true;
        status.textContent = "正在请求 DeepSeek…";
        answer.textContent = "";
        try {
            const api = PDF2zhHelperFactory.getActiveLLMApiConfig("deepseek");
            answer.textContent = await askAboutSelection(
                api,
                selection,
                question.value,
                controller.signal,
                web,
            );
            status.textContent = "已完成";
        } catch (error) {
            if (!panel.isConnected) return;
            status.textContent = "提问失败";
            answer.textContent =
                error instanceof Error
                    ? error.name === "AbortError"
                        ? "请求已取消或超时，请重试。"
                        : error.message
                    : "无法连接 DeepSeek，请稍后重试。";
        } finally {
            web.clearTimeout(timeout);
            if (panel.isConnected) button.disabled = false;
        }
    });
}

const renderSelectionButton: _ZoteroTypes.Reader.EventHandler<
    "renderTextSelectionPopup"
> = (event) => {
    const selection = event.params.annotation.text?.trim();
    if (!selection) return;
    const button = event.doc.createElement("button");
    button.textContent = "AI 提问";
    button.title = "向 DeepSeek 提问选中的文字";
    button.addEventListener("click", () => openAssistant(event.doc, selection));
    event.append(button);
};

export function registerSelectionAssistant() {
    Zotero.Reader.registerEventListener(
        "renderTextSelectionPopup",
        renderSelectionButton,
        addon.data.config.addonID,
    );
}

export function unregisterSelectionAssistant() {
    Zotero.Reader.unregisterEventListener(
        "renderTextSelectionPopup",
        renderSelectionButton,
    );
    for (const close of [...panels.values()]) close();
}
