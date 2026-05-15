(function () {
  "use strict";

  var TZ = "America/New_York";
  var DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
  var DAY_LABELS = {
    mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu", fri: "Fri", sat: "Sat", sun: "Sun",
  };
  var DAY_FULL = {
    mon: "Monday", tue: "Tuesday", wed: "Wednesday",
    thu: "Thursday", fri: "Friday", sat: "Saturday", sun: "Sunday",
  };

  function dataUrl() {
    var params = new URLSearchParams(location.search);
    if (params.get("fixture") === "1") return "tests/fixtures/hours.sample.json";
    return "data/hours.json";
  }

  function nowInTz() {
    var parts = new Intl.DateTimeFormat("en-US", {
      timeZone: TZ, hour12: false,
      weekday: "short", hour: "2-digit", minute: "2-digit",
    }).formatToParts(new Date());
    var lookup = {};
    parts.forEach(function (p) { lookup[p.type] = p.value; });
    var weekdayMap = { Mon: "mon", Tue: "tue", Wed: "wed", Thu: "thu", Fri: "fri", Sat: "sat", Sun: "sun" };
    var hour = parseInt(lookup.hour, 10);
    if (hour === 24) hour = 0;
    var minute = parseInt(lookup.minute, 10);
    return {
      day: weekdayMap[lookup.weekday],
      minutes: hour * 60 + minute,
    };
  }

  function toMinutes(hhmm) {
    var bits = hhmm.split(":");
    return parseInt(bits[0], 10) * 60 + parseInt(bits[1], 10);
  }

  function formatTime(hhmm) {
    var bits = hhmm.split(":");
    var h = parseInt(bits[0], 10);
    var m = parseInt(bits[1], 10);
    var suffix = h >= 12 ? "PM" : "AM";
    var h12 = ((h + 11) % 12) + 1;
    return h12 + ":" + (m < 10 ? "0" + m : m) + " " + suffix;
  }

  function nextDay(d) {
    return DAYS[(DAYS.indexOf(d) + 1) % 7];
  }

  function computeStatus(hours, now) {
    var today = hours[now.day] || [];
    for (var i = 0; i < today.length; i++) {
      var iv = today[i];
      if (now.minutes >= toMinutes(iv.open) && now.minutes < toMinutes(iv.close)) {
        return { open: true, until: iv.close };
      }
    }
    // Find next opening today
    for (var j = 0; j < today.length; j++) {
      var iv2 = today[j];
      if (toMinutes(iv2.open) > now.minutes) {
        return { open: false, nextDay: now.day, nextTime: iv2.open, isToday: true };
      }
    }
    // Walk forward up to 7 days
    var d = now.day;
    for (var k = 0; k < 7; k++) {
      d = nextDay(d);
      var slots = hours[d] || [];
      if (slots.length > 0) {
        return { open: false, nextDay: d, nextTime: slots[0].open, isToday: false };
      }
    }
    return { open: false, nextDay: null, nextTime: null, isToday: false };
  }

  function formatRelative(iso) {
    var then = new Date(iso).getTime();
    var diffMs = Date.now() - then;
    if (isNaN(diffMs)) return iso;
    var mins = Math.floor(diffMs / 60000);
    if (mins < 60) return mins + " min ago";
    var hrs = Math.floor(mins / 60);
    if (hrs < 24) return hrs + " hr ago";
    var days = Math.floor(hrs / 24);
    return days + " day" + (days === 1 ? "" : "s") + " ago";
  }

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        if (k === "class") node.className = attrs[k];
        else if (k === "html") node.innerHTML = attrs[k];
        else node.setAttribute(k, attrs[k]);
      });
    }
    (children || []).forEach(function (c) {
      if (c == null) return;
      node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return node;
  }

  function renderStatus(facility, now) {
    var s = computeStatus(facility.hours, now);
    if (s.open) {
      return el("p", { class: "status open" }, ["OPEN until " + formatTime(s.until)]);
    }
    if (!s.nextDay) {
      return el("p", { class: "status closed" }, ["CLOSED"]);
    }
    var when = s.isToday ? "today" : DAY_FULL[s.nextDay];
    return el("p", { class: "status closed" }, ["CLOSED — opens " + when + " at " + formatTime(s.nextTime)]);
  }

  function renderWeekTable(facility, now) {
    var tbody = el("tbody", {}, DAYS.map(function (d) {
      var slots = facility.hours[d] || [];
      var label = slots.length === 0
        ? "Closed"
        : slots.map(function (iv) { return formatTime(iv.open) + " – " + formatTime(iv.close); }).join(", ");
      return el("tr", d === now.day ? { class: "today" } : {}, [
        el("th", {}, [DAY_LABELS[d]]),
        el("td", {}, [label]),
      ]);
    }));
    return el("table", { class: "week" }, [tbody]);
  }

  function renderCard(facility, now) {
    var children = [el("h3", {}, [facility.name])];
    if (facility.scrape_status !== "ok") {
      children.push(el("p", { class: "stale-banner" }, [
        "Data may be outdated — last refreshed " + formatRelative(facility.last_scraped),
      ]));
    }
    children.push(renderStatus(facility, now));
    children.push(renderWeekTable(facility, now));
    if (facility.notes && facility.notes.length) {
      var ul = el("ul", { class: "notes" }, facility.notes.map(function (n) {
        return el("li", {}, [n]);
      }));
      children.push(ul);
    }
    var meta = el("p", { class: "meta" }, []);
    if (facility.location && facility.location.maps_url) {
      meta.appendChild(el("a", { href: facility.location.maps_url, target: "_blank", rel: "noopener" }, [
        facility.location.label || "Map",
      ]));
      meta.appendChild(document.createTextNode(" · "));
    }
    if (facility.source_url) {
      meta.appendChild(el("a", { href: facility.source_url, target: "_blank", rel: "noopener" }, ["Source"]));
    }
    children.push(meta);
    return el("article", { class: "card" }, children);
  }

  var PROGRAM_GROUP_LABELS = {
    climbing: "Climbing",
    fitness: "Group Fitness",
  };

  function todayIsoInTz() {
    var parts = new Intl.DateTimeFormat("en-CA", {
      timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit",
    }).formatToParts(new Date());
    var m = {};
    parts.forEach(function (p) { m[p.type] = p.value; });
    return m.year + "-" + m.month + "-" + m.day;
  }

  function formatDateHeading(iso, weekday) {
    var bits = iso.split("-");
    var months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    var mo = months[parseInt(bits[1], 10) - 1];
    return weekday + ", " + mo + " " + parseInt(bits[2], 10) + " " + bits[0];
  }

  function renderSchedule(days, programIndex) {
    var root = document.getElementById("schedule");
    if (!root) return;
    root.innerHTML = "";
    if (!days || !days.length) {
      root.appendChild(el("p", { class: "section-note" }, ["No upcoming classes."]));
      return;
    }
    var today = todayIsoInTz();
    var orientationRe = /15\s*minute\s*climbing\s*orientation/i;
    days.forEach(function (day) {
      if (day.date < today) return;
      var visibleEvents = day.events.filter(function (e) {
        return !orientationRe.test(e.name);
      });
      if (!visibleEvents.length) return;
      var isToday = day.date === today;
      var headingText = formatDateHeading(day.date, day.weekday) + (isToday ? " — Today" : "");
      var heading = el("h3", isToday ? { class: "today" } : {}, [headingText]);
      var list = el("ul", { class: "schedule-list" }, visibleEvents.map(function (e) {
        var url = programIndex[e.name.toLowerCase()];
        var nameNode = url
          ? el("a", { href: url, target: "_blank", rel: "noopener" }, [e.name])
          : el("span", {}, [e.name]);
        return el("li", {}, [
          el("span", { class: "t" }, [formatTime(e.time)]),
          nameNode,
        ]);
      }));
      root.appendChild(el("div", { class: "schedule-day" }, [heading, list]));
    });
    if (!root.children.length) {
      root.appendChild(el("p", { class: "section-note" }, ["No upcoming classes."]));
    }
  }

  function renderPrograms(programs, upcomingNames) {
    var root = document.getElementById("programs");
    if (!root) return;
    root.innerHTML = "";
    if (!programs || !programs.length) {
      root.appendChild(el("p", { class: "section-note" }, ["No programs available."]));
      return;
    }
    var byCat = {};
    programs.forEach(function (p) {
      (byCat[p.category] = byCat[p.category] || []).push(p);
    });
    // Sort each category so programs WITH upcoming sessions come first
    Object.keys(byCat).sort().forEach(function (cat) {
      var label = PROGRAM_GROUP_LABELS[cat] || cat;
      var list = el("ul", { class: "programs-list" }, byCat[cat]
        .slice()
        .sort(function (a, b) {
          var ua = upcomingNames.has(a.name.toLowerCase()) ? 0 : 1;
          var ub = upcomingNames.has(b.name.toLowerCase()) ? 0 : 1;
          if (ua !== ub) return ua - ub;
          return a.name.localeCompare(b.name);
        })
        .map(function (p) {
          var hasUpcoming = upcomingNames.has(p.name.toLowerCase());
          var attrs = hasUpcoming ? {} : { class: "program-empty", title: "No upcoming sessions" };
          return el("li", attrs, [
            el("a", { href: p.url, target: "_blank", rel: "noopener" }, [p.name]),
          ]);
        }));
      root.appendChild(el("div", { class: "programs-group" }, [
        el("h3", {}, [label]),
        list,
      ]));
    });
  }

  function formatCountdown(minutesLeft) {
    if (minutesLeft <= 0) return "closing now";
    if (minutesLeft < 60) return minutesLeft + " min left";
    var h = Math.floor(minutesLeft / 60);
    var m = minutesLeft % 60;
    if (m === 0) return h + "h left";
    return h + "h " + m + "m left";
  }

  function renderOpenNow(facilities, now) {
    var root = document.getElementById("open-now");
    if (!root) return;
    root.innerHTML = "";
    var openItems = [];
    facilities.forEach(function (f) {
      var status = computeStatus(f.hours, now);
      if (!status.open) return;
      var minutesLeft = toMinutes(status.until) - now.minutes;
      openItems.push({ facility: f, until: status.until, minutesLeft: minutesLeft });
    });
    if (!openItems.length) {
      root.appendChild(el("p", { class: "open-now-empty" }, [
        "Nothing open right now. Check the sections below for upcoming hours.",
      ]));
      return;
    }
    openItems.sort(function (a, b) { return a.minutesLeft - b.minutesLeft; });
    var list = el("ul", { class: "open-now-list" }, openItems.map(function (it) {
      var urgent = it.minutesLeft <= 30;
      return el("li", urgent ? { class: "urgent" } : {}, [
        el("span", { class: "on-name" }, [it.facility.name]),
        el("span", { class: "on-until" }, ["until " + formatTime(it.until)]),
        el("span", { class: "on-countdown" }, [formatCountdown(it.minutesLeft)]),
      ]);
    }));
    root.appendChild(list);
  }

  function renderAlert(text) {
    var root = document.getElementById("alert-banner");
    if (!root) return;
    if (!text) { root.hidden = true; return; }
    root.hidden = false;
    root.innerHTML = "";
    var inner = el("div", { class: "alert-inner" }, []);
    var lines = text.split("\n");
    var heading = lines.shift();
    inner.appendChild(el("p", { class: "alert-heading" }, [heading]));
    var bodyText = lines.join("\n").trim();
    if (bodyText) {
      var pre = el("pre", { class: "alert-body" }, [bodyText]);
      inner.appendChild(pre);
    }
    inner.appendChild(el("p", { class: "alert-source" }, [
      el("a", { href: "https://www.umass.edu/recwell/", target: "_blank", rel: "noopener" },
        ["Source: umass.edu/recwell"]),
    ]));
    root.appendChild(inner);
  }

  function render(doc) {
    var now = nowInTz();
    document.getElementById("updated").textContent =
      "Last updated " + formatRelative(doc.last_updated);
    renderAlert(doc.alert);
    renderOpenNow(doc.facilities, now);
    ["swim", "ice", "climbing", "fitness", "tennis"].forEach(function (cat) {
      var container = document.querySelector('[data-cards-for="' + cat + '"]');
      container.innerHTML = "";
      doc.facilities
        .filter(function (f) { return f.category === cat; })
        .forEach(function (f) { container.appendChild(renderCard(f, now)); });
    });
    var programIndex = {};
    (doc.programs || []).forEach(function (p) {
      programIndex[p.name.toLowerCase()] = p.url;
    });
    renderSchedule(doc.schedule || [], programIndex);
    var todayStr = todayIsoInTz();
    var upcomingNames = new Set();
    (doc.schedule || []).forEach(function (day) {
      if (day.date < todayStr) return;
      day.events.forEach(function (e) {
        upcomingNames.add(e.name.toLowerCase());
      });
    });
    renderPrograms(doc.programs || [], upcomingNames);
  }

  function showError(message) {
    document.getElementById("updated").textContent = message;
  }

  fetch(dataUrl(), { cache: "no-cache" })
    .then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    })
    .then(render)
    .catch(function (e) { showError("Failed to load hours: " + e.message); });
})();
