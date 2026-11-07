/*
 * YouLikeIt — Plausible custom-events helper (self-hosted, cookieless).
 *
 * Loaded alongside the Plausible script tag:
 *   <script defer data-domain="youlikeit.vara-alta.lat"
 *           src="https://analytics.vara-alta.lat/js/script.js"></script>
 *   <script defer src="/assets/analytics.js"></script>
 *
 * Pageviews are tracked automatically by script.js. This file only adds
 * goal/custom events. No cookies, no IP/UA persistence (matches privacy.html).
 *
 * Usage:
 *   - Declarative: add `data-analytics="<target>"` to any clickable element.
 *     A `cta_click` event fires with props {target, page}.
 *   - Programmatic: window.ylAnalytics.personaClick('deep_mind') — reserved
 *     for future per-persona pages (fires `persona_click` with props {persona}).
 */
(function () {
  "use strict";

  // Queue shim: ensures plausible() calls before script.js finishes loading
  // are not lost (Plausible's documented pattern).
  window.plausible =
    window.plausible ||
    function () {
      (window.plausible.q = window.plausible.q || []).push(arguments);
    };

  function track(eventName, props) {
    try {
      window.plausible(eventName, props ? { props: props } : undefined);
    } catch (_e) {
      /* never break the page for analytics */
    }
  }

  // Public API for programmatic events.
  window.ylAnalytics = {
    track: track,
    personaClick: function (persona) {
      track("persona_click", { persona: String(persona || "unknown") });
    },
  };

  // Delegated listener: any element with [data-analytics] becomes a CTA goal.
  document.addEventListener(
    "click",
    function (ev) {
      var el = ev.target && ev.target.closest
        ? ev.target.closest("[data-analytics]")
        : null;
      if (!el) return;
      track("cta_click", {
        target: el.getAttribute("data-analytics") || "unknown",
        page: location.pathname || "/",
      });
    },
    { passive: true }
  );
})();
