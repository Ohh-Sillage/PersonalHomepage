/* AI 助手聊天组件：SSE 流式对话 */
(function () {
  "use strict";

  var widget = document.getElementById("chatWidget");
  if (!widget) return;

  var toggle = document.getElementById("chatToggle");
  var panel = document.getElementById("chatPanel");
  var closeBtn = document.getElementById("chatClose");
  var form = document.getElementById("chatForm");
  var input = document.getElementById("chatText");
  var messagesEl = document.getElementById("chatMessages");

  var history = [];
  var busy = false;

  function openPanel() {
    panel.hidden = false;
    input.focus();
  }

  function closePanel() {
    panel.hidden = true;
  }

  toggle.addEventListener("click", function () {
    if (panel.hidden) {
      openPanel();
    } else {
      closePanel();
    }
  });

  closeBtn.addEventListener("click", closePanel);

  function appendMessage(role, text) {
    var div = document.createElement("div");
    div.className = "msg " + role;
    div.textContent = text || "";
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return div;
  }

  function finishStream(botEl, fullText) {
    botEl.classList.remove("typing");
    if (fullText) {
      history.push({ role: "assistant", content: fullText });
      // 只保留最近 8 条，控制请求体积
      if (history.length > 8) history = history.slice(-8);
    }
  }

  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    var text = input.value.trim();
    if (!text || busy) return;

    busy = true;
    input.value = "";
    appendMessage("user", text);

    var priorHistory = history.slice();
    history.push({ role: "user", content: text });

    var botEl = appendMessage("bot", "");
    botEl.classList.add("typing");

    try {
      var resp = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, history: priorHistory })
      });

      if (!resp.ok) {
        var errData = await resp.json().catch(function () { return {}; });
        botEl.textContent = errData.error || "服务暂时不可用，请稍后再试。";
        botEl.classList.remove("typing");
        return;
      }

      var reader = resp.body.getReader();
      var decoder = new TextDecoder("utf-8");
      var buffer = "";
      var fullText = "";

      while (true) {
        var chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true });

        var lines = buffer.split("\n");
        buffer = lines.pop();

        for (var i = 0; i < lines.length; i++) {
          var line = lines[i];
          if (line.indexOf("data: ") !== 0) continue;
          var payload = line.slice(6).trim();
          if (payload === "[DONE]") continue;
          try {
            var data = JSON.parse(payload);
            if (data.error) {
              botEl.textContent = data.error;
              continue;
            }
            if (data.delta) {
              fullText += data.delta;
              botEl.textContent = fullText;
              messagesEl.scrollTop = messagesEl.scrollHeight;
            }
          } catch (e) {
            /* 忽略不完整分片 */
          }
        }
      }

      finishStream(botEl, fullText);
    } catch (err) {
      botEl.textContent = "网络异常，请稍后再试。";
      botEl.classList.remove("typing");
    } finally {
      busy = false;
    }
  });
})();
