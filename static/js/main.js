/* 主页交互：滚动渐入动画 + 侧边导航高亮（渐进增强，无 JS 时内容仍可见） */
(function () {
  "use strict";

  document.body.classList.add("js");

  /* ---------- 滚动渐入 ---------- */
  var revealEls = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window && revealEls.length) {
    var revealObserver = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add("visible");
            revealObserver.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.12, rootMargin: "0px 0px -40px 0px" }
    );
    revealEls.forEach(function (el) {
      revealObserver.observe(el);
    });
  } else {
    revealEls.forEach(function (el) {
      el.classList.add("visible");
    });
  }

  /* ---------- 侧边导航随滚动高亮 ---------- */
  var navLinks = document.querySelectorAll("[data-nav]");
  if (!navLinks.length || !("IntersectionObserver" in window)) return;

  var sections = [];
  navLinks.forEach(function (link) {
    var section = document.getElementById(link.dataset.nav);
    if (section) sections.push(section);
  });

  var navObserver = new IntersectionObserver(
    function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        navLinks.forEach(function (link) {
          link.classList.toggle("active", link.dataset.nav === entry.target.id);
        });
      });
    },
    { rootMargin: "-30% 0px -60% 0px" }
  );

  sections.forEach(function (section) {
    navObserver.observe(section);
  });
})();

/* ---------- 联系区：点击按钮复制邮箱（无 JS 时按钮仍为 mailto 链接） ---------- */
(function () {
  "use strict";

  var btn = document.getElementById("copy-email");
  var label = btn ? btn.querySelector(".btn-label") : null;
  if (!btn || !label) return;

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
        resolve();
      } catch (err) {
        reject(err);
      } finally {
        document.body.removeChild(ta);
      }
    });
  }

  btn.addEventListener("click", function (e) {
    var email = btn.dataset.email || "";
    if (!email) return; /* 未配置邮箱时保持默认 mailto 行为 */
    e.preventDefault();
    if (btn.dataset.busy === "1") return;
    btn.dataset.busy = "1";

    var original = label.textContent;

    copyText(email)
      .then(function () {
        label.textContent = "已复制";
      })
      .catch(function () {
        label.textContent = "复制失败";
      })
      .then(function () {
        setTimeout(function () {
          label.textContent = original;
          btn.dataset.busy = "0";
        }, 1500);
      });
  });
})();
