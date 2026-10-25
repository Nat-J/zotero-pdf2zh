import assert from "node:assert/strict";
import test from "node:test";
import { askAboutSelection } from "../src/modules/selectionAssistantRequest.ts";

const api = {
    apiKey: "test-secret",
    model: "deepseek-v4-flash",
    apiUrl: "https://api.deepseek.com/v1",
};

test("uses the explicit browser APIs provided by the Zotero host", async (t) => {
    t.mock.method(globalThis, "fetch", async () => {
        throw new Error("sandbox fetch must not be used");
    });
    const web = {
        URL,
        fetch: async () => ({
            ok: true,
            json: async () => ({
                choices: [{ message: { content: "Host answer" } }],
            }),
        }),
    };
    assert.equal(
        await askAboutSelection(api, "text", "why", undefined, web),
        "Host answer",
    );
});

test("asks about only the selected text using the saved API configuration", async (t) => {
    t.mock.method(globalThis, "fetch", async (url, init) => {
        assert.equal(url, "https://api.deepseek.com/v1/chat/completions");
        assert.equal(init.headers.Authorization, "Bearer test-secret");
        assert.equal(init.redirect, "error");
        const body = JSON.parse(init.body);
        assert.deepEqual(body.thinking, { type: "disabled" });
        assert.equal(body.model, api.model);
        assert.match(body.messages[1].content, /Selected paragraph/);
        assert.match(body.messages[1].content, /What does it mean/);
        return {
            ok: true,
            json: async () => ({ choices: [{ message: { content: "解释" } }] }),
        };
    });
    assert.equal(
        await askAboutSelection(
            api,
            "Selected paragraph",
            "What does it mean?",
        ),
        "解释",
    );
});

test("rejects empty or oversized input and unsafe endpoints before a request", async (t) => {
    const fetch = t.mock.method(globalThis, "fetch", async () => {
        throw new Error("must not send");
    });
    for (const [selection, question] of [
        ["", "why"],
        ["text", ""],
        ["x".repeat(50_001), "why"],
    ]) {
        await assert.rejects(askAboutSelection(api, selection, question));
    }
    await assert.rejects(
        askAboutSelection(
            { ...api, apiUrl: "http://example.com" },
            "text",
            "why",
        ),
        /HTTPS/,
    );
    await assert.rejects(
        askAboutSelection({ ...api, apiKey: "" }, "text", "why"),
        /API/,
    );
    assert.equal(fetch.mock.callCount(), 0);
});

test("reports API failures without copying a credential from the error body", async (t) => {
    t.mock.method(globalThis, "fetch", async () => ({
        ok: false,
        status: 401,
        text: async () => "test-secret",
    }));
    await assert.rejects(
        askAboutSelection(api, "text", "why"),
        (error: Error) => {
            assert.match(error.message, /401/);
            assert.doesNotMatch(error.message, /test-secret/);
            return true;
        },
    );
});

test("rejects an empty answer and forwards cancellation", async (t) => {
    const controller = new AbortController();
    t.mock.method(globalThis, "fetch", async (_url, init) => {
        assert.equal(init.signal, controller.signal);
        return { ok: true, json: async () => ({ choices: [] }) };
    });
    await assert.rejects(
        askAboutSelection(api, "text", "why", controller.signal),
        /未返回/,
    );
});
